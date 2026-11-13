"""MLE-bench adapter: competition registry, prepared-data host, medal grading.

The official MLE-bench harness gives the agent a prepared Kaggle competition
under ``/home/data`` and expects a CSV at ``/home/submission/submission.csv``.
Grading uses the competition's own metric and the Kaggle leaderboard thresholds
(gold/silver/bronze/median).

This adapter loads the public competition registry (the ``low`` split of 22
competitions by default) and the official description, starts a Docker host
with the prepared public data, and grades a submission.

Real MLE-bench data is **not** in this repository: it is downloaded from Kaggle
by ``mlebench prepare`` and requires Kaggle API credentials.  When the prepared
data or the official ``mlebench`` package is absent, the adapter reports the
missing dependency and returns an invalid grade instead of inventing a score.
The test suite uses a synthetic competition and a dependency-free metric.
"""
from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path
from typing import Callable, Dict, List

import yaml

from benchmarks.mle_grading import (
    MedalReport, is_lower_better, rank_score, read_leaderboard,
)
from contract.types import (
    BenchmarkAdapter, ExperimentConfig, Grade, Host, TaskSpec,
)
from hosts.docker import DockerHost

REPO = Path(__file__).resolve().parents[3]
DEFAULT_ROOT = REPO / ".cache" / "upstream" / "mle-bench"
DEFAULT_DATA = DEFAULT_ROOT / "data"
DEFAULT_SPLIT = "low"
DEFAULT_IMAGE = "mlebench-agent:latest"
SUBMISSION_PATH = "/home/submission/submission.csv"

Metric = Callable[[str, Path], float | None]


class MLESubmissionVerifier:
    def __init__(self, host: DockerHost, task: TaskSpec, metric: Metric | None,
                 answers_path: Path, leaderboard_path: Path, data_dir: Path):
        self.host = host
        self.task = task
        self.metric = metric
        self.answers_path = Path(answers_path)
        self.leaderboard_path = Path(leaderboard_path)
        self.data_dir = Path(data_dir)

    def grade(self) -> Grade:
        text = self.host.read_container_file(SUBMISSION_PATH)
        if text is None:
            return Grade(valid=True, passed=False, checks_passed=0,
                         checks_total=1,
                         detail="submission.csv missing; method did not submit")
        try:
            scores = read_leaderboard(self.leaderboard_path)
        except (FileNotFoundError, KeyError, ValueError) as exc:
            return Grade(valid=False, passed=False, checks_passed=0,
                         checks_total=1,
                         detail=f"leaderboard unavailable: {exc}")
        if self.metric is not None:
            score = self.metric(text, self.answers_path)
            if score is None:
                return Grade(valid=False, passed=False, checks_passed=0,
                             checks_total=1,
                             detail="submission is not valid for the metric")
            medal = rank_score(score, scores)
            return self._grade_from_medal(medal, scores, source="synthetic metric")
        return self._official_grade(text, scores)

    def _official_grade(self, text: str, scores: List[float]) -> Grade:
        try:
            from mlebench.grade import grade_csv
            from mlebench.registry import Registry
        except Exception as exc:  # pandas/mlebench not installed
            return Grade(
                valid=False, passed=False, checks_passed=0, checks_total=1,
                detail=f"official MLE-bench grader unavailable: {exc}",
            )
        temp = Path(tempfile.mkdtemp(prefix="mle-submission-")) / "submission.csv"
        try:
            temp.write_text(text, encoding="utf-8")
            registry = Registry(self.data_dir)
            competition = registry.get_competition(self.task.task_id)
            report = grade_csv(temp, competition)
        except Exception as exc:
            return Grade(
                valid=False, passed=False, checks_passed=0, checks_total=1,
                detail=f"official MLE-bench grading failed: {exc}",
            )
        finally:
            shutil.rmtree(temp.parent, ignore_errors=True)
        # The official report is authoritative for the medal flags.
        detail = (
            f"score={report.score} any_medal={report.any_medal} "
            f"gold={report.gold_medal} silver={report.silver_medal} "
            f"bronze={report.bronze_medal} above_median={report.above_median} "
            f"thresholds=gold:{report.gold_threshold},"
            f"silver:{report.silver_threshold},bronze:{report.bronze_threshold},"
            f"median:{report.median_threshold}"
        )
        return Grade(valid=True, passed=report.any_medal,
                     checks_passed=1 if report.any_medal else 0,
                     checks_total=1, detail=detail)

    def _grade_from_medal(self, medal: MedalReport, scores: List[float],
                          source: str) -> Grade:
        detail = (
            f"source={source} score={medal.score} "
            f"any_medal={medal.any_medal} gold={medal.gold_medal} "
            f"silver={medal.silver_medal} bronze={medal.bronze_medal} "
            f"above_median={medal.above_median} "
            f"lower_is_better={is_lower_better(scores)} "
            f"thresholds=gold:{medal.gold_threshold},"
            f"silver:{medal.silver_threshold},bronze:{medal.bronze_threshold},"
            f"median:{medal.median_threshold}"
        )
        return Grade(valid=True, passed=medal.any_medal,
                     checks_passed=1 if medal.any_medal else 0,
                     checks_total=1, detail=detail)


class MLEBenchAdapter(BenchmarkAdapter):
    name = "mle"
    mock_only = False
    real_loader = True
    real_host = True

    def __init__(self, root: str | Path | None = None, split: str = DEFAULT_SPLIT,
                 data_dir: str | Path | None = None,
                 image: str | None = None,
                 metric: Metric | None = None,
                 enforce_submission: bool = False):
        self.root = Path(root or os.environ.get("HW_MLE_ROOT") or DEFAULT_ROOT)
        competitions = self.root / "mlebench" / "competitions"
        if not competitions.is_dir():
            raise FileNotFoundError(competitions)
        self.split = split
        self.data_dir = Path(
            data_dir or os.environ.get("HW_MLE_DATA") or DEFAULT_DATA)
        self.image = image or os.environ.get("HW_MLE_IMAGE") or DEFAULT_IMAGE
        self.metric = metric
        # Off by default: the guard adds host-side feedback and can change an
        # agent's stopping behavior.  Enable it only for strict-submission runs.
        self.enforce_submission = enforce_submission
        self._answers: Dict[str, Path] = {}
        self._leaderboards: Dict[str, Path] = {}
        self._configs: Dict[str, dict] = {}
        self._instructions = (
            self.root / "environment" / "instructions.txt").read_text(
                encoding="utf-8")
        self._tasks = self._build_tasks()

    def _competition_ids(self) -> List[str]:
        competitions = self.root / "mlebench" / "competitions"
        all_ids = sorted(p.parent.name for p in competitions.rglob("config.yaml"))
        if self.split == "all":
            return all_ids
        if self.split == "low":
            split_file = self.root / "experiments" / "splits" / "low.txt"
        else:
            split_file = Path(self.split)
        ids = [line.strip() for line in split_file.read_text(encoding="utf-8").splitlines()
               if line.strip()]
        allowed = set(all_ids)
        return [comp for comp in ids if comp in allowed]

    def _build_tasks(self) -> List[TaskSpec]:
        tasks = []
        for competition_id in self._competition_ids():
            comp_dir = self.root / "mlebench" / "competitions" / competition_id
            config = yaml.safe_load((comp_dir / "config.yaml").read_text(encoding="utf-8"))
            description = (comp_dir / "description.md").read_text(encoding="utf-8")
            answers = self.data_dir / config["dataset"]["answers"]
            leaderboard = comp_dir / "leaderboard.csv"
            self._configs[competition_id] = config
            self._answers[competition_id] = answers
            self._leaderboards[competition_id] = leaderboard
            tasks.append(TaskSpec(
                task_id=competition_id,
                benchmark=self.name,
                instruction=(
                    f"{self._instructions}\n\nCompetition: {config['name']}\n\n"
                    f"{description}"
                ),
                initial_files={},
                metadata={
                    "competition_id": competition_id,
                    "name": config["name"],
                    "competition_type": config.get("competition_type", ""),
                    "metric_name": (config.get("grader") or {}).get("name", ""),
                    "split": self.split if self.split in ("low", "all") else "custom",
                    "submission_path": SUBMISSION_PATH,
                    "data_dir": str(self.data_dir),
                },
            ))
        return tasks

    def load_tasks(self, path: str | None = None) -> List[TaskSpec]:
        if path is not None:
            self.split = path
            self._answers.clear()
            self._leaderboards.clear()
            self._configs.clear()
            self._tasks = self._build_tasks()
        return list(self._tasks)

    @property
    def official_task_count(self) -> int:
        return len(self._tasks)

    @property
    def hidden_task_count(self) -> int:
        return 0

    @property
    def dataset_missing(self) -> str:
        prepared = [
            comp for comp in self._configs
            if (self.data_dir / comp / "prepared" / "public").is_dir()
        ]
        if prepared:
            return ""
        try:
            shown = self.data_dir.relative_to(REPO).as_posix()
        except ValueError:
            shown = self.data_dir.as_posix()
        return (
            f"MLE-bench data not prepared under {shown}; "
            "install Kaggle credentials and run `mlebench prepare -c <competition>`"
        )

    @property
    def real_grader(self) -> bool:
        if self.metric is not None:
            return True
        try:
            import mlebench.grade  # noqa: F401
            import mlebench.registry  # noqa: F401
        except Exception:
            return False
        return any(
            (self.data_dir / comp / "prepared" / "private").is_dir()
            for comp in self._configs
        )

    def make_host(self, task: TaskSpec, config: ExperimentConfig) -> Host:
        public = self.data_dir / task.task_id / "prepared" / "public"
        if not public.is_dir():
            raise FileNotFoundError(
                f"{task.task_id}: MLE-bench public data missing at {public}; "
                "run `mlebench prepare` first")
        # The official image has an entrypoint; override it so the container
        # stays alive while the method works.
        host = DockerHost(
            task, config, self.image, "true", container_workdir="/home",
            docker_args=["--entrypoint", "/bin/sh"],
            command=["-c", "sleep infinity"],
        )
        try:
            host.exec(["mkdir", "-p", "/home/data", "/home/submission"])
            host.copy_in(public, "/home/data")
        except Exception:
            host.cleanup()
            raise
        host.verifier = MLESubmissionVerifier(
            host, task, self.metric, self._answers[task.task_id],
            self._leaderboards[task.task_id], self.data_dir,
        )
        if self.enforce_submission:
            host.submit_guard = lambda: (
                None if host.read_container_file(SUBMISSION_PATH) is not None
                else "submission.csv is required before submit; write it at "
                     f"{SUBMISSION_PATH}")
        return host

    def grade(self, task: TaskSpec, host: Host) -> Grade:
        return host.grade()
