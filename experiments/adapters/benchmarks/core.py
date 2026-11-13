"""CORE-Bench adapter: train split, easy/medium/hard prompt, official grading.

CORE-Bench tasks are CodeOcean capsules.  The agent receives an ``environment/``
directory containing ``task.txt`` and ``capsule-XXXXXXX/`` and must write
``report.json`` with one answer per question.  The official grader compares
numeric answers against the 95% prediction interval of three gold runs, string
answers case-insensitively, and list answers exactly; a task passes only when
every question is correct.

This adapter uses the public train split (45 tasks) because the held-out test
split is GPG-encrypted.  The capsule tarball is downloaded lazily (the full set
is large) into the ignored cache.  The first integration targets
``codeocean_easy`` (answer from the capsule's ``results/`` directory without
executing code); medium/hard share the same host and grader and can reuse the
same adapter.
"""
from __future__ import annotations

import json
import os
import shutil
import tarfile
import tempfile
import time
import urllib.request
from pathlib import Path
from typing import Any, Dict, List

from benchmarks.core_grading import eval_result_json
from contract.types import (
    BenchmarkAdapter, ExperimentConfig, Grade, Host, TaskSpec,
)
from hosts.docker import DockerHost

REPO = Path(__file__).resolve().parents[3]
DEFAULT_ROOT = REPO / ".cache" / "upstream" / "core-bench"
DEFAULT_DATASET = DEFAULT_ROOT / "benchmark" / "dataset" / "core_train.json"
DEFAULT_PROMPTS = DEFAULT_ROOT / "benchmark" / "benchmark_prompts.json"
DEFAULT_CAPSULES = DEFAULT_ROOT / "capsules"
CAPSULE_URL = "https://corebench.cs.princeton.edu/capsules/{capsule_id}.tar.gz"

LEVELS = ("codeocean_easy", "codeocean_medium", "codeocean_hard")


def _load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


class CoreReportVerifier:
    """Read the agent's ``report.json`` and apply the official grader."""

    def __init__(self, host: DockerHost, gold: List[Dict[str, Any]]):
        self.host = host
        self.gold = gold

    def _find_report(self) -> str | None:
        text = self.host.read_container_file("/app/report.json")
        if text is not None:
            return text
        proc = self.host._exec(
            "find /app -name report.json -type f 2>/dev/null | head -n 1")
        if proc.returncode == 0 and proc.stdout.strip():
            return self.host.read_container_file(proc.stdout.splitlines()[0].strip())
        return None

    def grade(self) -> Grade:
        empty = eval_result_json(self.gold, {})
        text = self._find_report()
        if text is None:
            return Grade(
                valid=True, passed=False, checks_passed=0,
                checks_total=empty.total_questions,
                detail="report.json missing; method did not answer",
            )
        try:
            report = json.loads(text)
        except json.JSONDecodeError as exc:
            return Grade(
                valid=False, passed=False, checks_passed=0,
                checks_total=empty.total_questions,
                detail=f"report.json is not valid JSON: {exc}",
            )
        if not isinstance(report, dict):
            return Grade(
                valid=False, passed=False, checks_passed=0,
                checks_total=empty.total_questions,
                detail=f"report.json must be an object, got {type(report).__name__}",
            )
        result = eval_result_json(self.gold, report)
        detail = (
            f"correct_questions={result.correct_questions}/{result.total_questions} "
            f"written={result.correct_written_answers}/{result.total_written_questions} "
            f"vision={result.correct_vision_answers}/{result.total_vision_questions}"
        )
        return Grade(
            valid=True, passed=result.passed,
            checks_passed=result.correct_questions,
            checks_total=result.total_questions,
            detail=detail,
        )


class CoreDockerHost(DockerHost):
    """DockerHost that also removes the per-task environment copy."""

    def __init__(self, *args, env_dir: Path, **kwargs):
        self.env_dir = Path(env_dir)
        super().__init__(*args, **kwargs)

    def cleanup(self) -> None:
        super().cleanup()
        shutil.rmtree(self.env_dir, ignore_errors=True)


class CoreBenchAdapter(BenchmarkAdapter):
    name = "core"
    mock_only = False
    real_loader = True
    real_host = True
    real_grader = True

    def __init__(self, root: str | Path | None = None,
                 dataset: str | Path | None = None,
                 level: str = "codeocean_easy",
                 capsule_dir: str | Path | None = None,
                 image: str | None = None,
                 download: bool = True,
                 timeout: int = 1800):
        if level not in LEVELS:
            raise ValueError(f"unknown CORE-Bench level: {level}")
        self.root = Path(root or os.environ.get("HW_CORE_ROOT") or DEFAULT_ROOT)
        self.dataset_path = Path(
            dataset or os.environ.get("HW_CORE_DATASET") or DEFAULT_DATASET)
        prompts_path = self.root / "benchmark" / "benchmark_prompts.json"
        if not self.dataset_path.is_file():
            raise FileNotFoundError(self.dataset_path)
        if not prompts_path.is_file():
            raise FileNotFoundError(prompts_path)
        self.level = level
        self.capsule_dir = Path(
            capsule_dir or os.environ.get("HW_CORE_CAPSULES") or DEFAULT_CAPSULES)
        self.image = image
        self.download = download
        self.timeout = timeout
        self._prompts = _load_json(prompts_path)
        self._raw = _load_json(self.dataset_path)
        self._gold: Dict[str, List[Dict[str, Any]]] = {}
        self._tasks = self._build_tasks()

    # ------------------------------------------------------------------ load
    def _instruction(self, raw: Dict[str, Any]) -> str:
        template = self._prompts[self.level]
        fields = str(list(raw["results"][0].keys()))
        return (template
                .replace("{task_prompt}", raw["task_prompt"])
                .replace("{json_fields}", fields)
                .replace("{registry_link}", raw.get("capsule_doi", "")))

    def _build_tasks(self) -> List[TaskSpec]:
        tasks = []
        for raw in self._raw:
            capsule_id = raw["capsule_id"]
            self._gold[capsule_id] = raw["results"]
            tasks.append(TaskSpec(
                task_id=capsule_id,
                benchmark=self.name,
                instruction=self._instruction(raw),
                initial_files={},
                metadata={
                    "capsule_id": capsule_id,
                    "capsule_title": raw["capsule_title"],
                    "capsule_doi": raw.get("capsule_doi", ""),
                    "field": raw.get("field", ""),
                    "language": raw.get("language", ""),
                    "level": self.level,
                    "questions": list(raw["results"][0].keys()),
                },
            ))
        return tasks

    def load_tasks(self, path: str | None = None) -> List[TaskSpec]:
        if path is not None:
            self.dataset_path = Path(path)
            self._raw = _load_json(self.dataset_path)
            self._gold.clear()
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
        return ""

    # --------------------------------------------------------------- capsules
    def _ensure_capsule(self, capsule_id: str) -> Path:
        target = self.capsule_dir / capsule_id
        if target.is_dir():
            return target
        self.capsule_dir.mkdir(parents=True, exist_ok=True)
        tar_path = self.capsule_dir / f"{capsule_id}.tar.gz"
        if not tar_path.is_file():
            if not self.download:
                raise FileNotFoundError(target)
            url = CAPSULE_URL.format(capsule_id=capsule_id)
            last_error = None
            for attempt in range(3):
                try:
                    urllib.request.urlretrieve(url, tar_path)
                    last_error = None
                    break
                except Exception as exc:  # network errors vary by platform
                    last_error = exc
                    time.sleep(2 ** attempt)
            if last_error is not None:
                raise RuntimeError(f"failed to download {url}: {last_error}")
        with tarfile.open(tar_path, "r:gz") as tar:
            # Python 3.12's data filter rejects absolute/escaping members.
            try:
                tar.extractall(path=self.capsule_dir, filter="data")
            except TypeError:  # Python < 3.12
                tar.extractall(path=self.capsule_dir)
        tar_path.unlink(missing_ok=True)
        if not target.is_dir():
            raise RuntimeError(
                f"{capsule_id}: archive did not extract to {target}")
        return target

    def _prepare_environment(self, task: TaskSpec) -> Path:
        capsule_id = task.task_id
        env_dir = Path(tempfile.mkdtemp(prefix=f"core-{capsule_id}-"))
        try:
            shutil.copytree(self._ensure_capsule(capsule_id),
                            env_dir / capsule_id)
            capsule = env_dir / capsule_id
            results = capsule / "results"
            if self.level != "codeocean_easy":
                shutil.rmtree(results, ignore_errors=True)
                results.mkdir(parents=True, exist_ok=True)
            if self.level != "codeocean_medium":
                for path in (capsule / "REPRODUCING.md",
                             capsule / "environment",
                             capsule / "code" / "run.sh",
                             capsule / "code" / "run"):
                    if path.is_dir():
                        shutil.rmtree(path, ignore_errors=True)
                    elif path.exists():
                        path.unlink()
            (env_dir / "task.txt").write_text(task.instruction, encoding="utf-8")
            return env_dir
        except Exception:
            shutil.rmtree(env_dir, ignore_errors=True)
            raise

    # ------------------------------------------------------------------ host
    def _image_for(self, task: TaskSpec) -> str:
        if self.image:
            return self.image
        language = str(task.metadata.get("language", "")).lower()
        return "r-base:4.3.1" if language == "r" else "python:3.11-slim"

    def make_host(self, task: TaskSpec, config: ExperimentConfig) -> Host:
        env_dir = self._prepare_environment(task)
        docker_args = []
        if self.level != "codeocean_easy":
            # The official harness uses Docker-in-Docker for medium tasks.
            docker_args.append("--privileged")
        try:
            host = CoreDockerHost(
                task, config, self._image_for(task), "true",
                container_workdir="/app", docker_args=docker_args, env_dir=env_dir,
            )
        except Exception:
            shutil.rmtree(env_dir, ignore_errors=True)
            raise
        try:
            host.copy_in(env_dir, "/app")
        except Exception:
            host.cleanup()
            raise
        host.verifier = CoreReportVerifier(host, self._gold[task.task_id])
        return host

    def grade(self, task: TaskSpec, host: Host) -> Grade:
        return host.grade()
