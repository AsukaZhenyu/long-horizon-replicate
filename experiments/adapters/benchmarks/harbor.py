"""Harbor-format benchmark adapter.

Terminal-Bench 2.1 and Long-Horizon-Terminal-Bench 2.0 both ship tasks in the
Harbor layout::

    <root>/<task_id>/task.toml
    <root>/<task_id>/instruction.md
    <root>/<task_id>/environment/Dockerfile   (or a pinned docker_image)
    <root>/<task_id>/tests/test.sh

The adapter loads the task, starts one container from the task image, exposes
only shell/read/write/submit to the method, and -- after the method stops --
copies the official ``tests/`` directory into the container and runs
``tests/test.sh``.  The verifier writes ``/logs/verifier/reward.txt``; the
adapter reads that file rather than inventing a grade.

If a task's ``test.sh`` references a private verifier directory that is not
part of the checkout, ``official_tests`` is false and the host returns an
invalid grade with the reason instead of faking a pass.  In the LHTB
``tasks-2.0`` snapshot used here the private files are present, so those tasks
are graded officially; the method still never sees them because they are
copied only after it stops.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List

from contract.types import (
    BenchmarkAdapter, ExperimentConfig, Grade, Host, TaskSpec,
)
from hosts.docker import DockerHost


@dataclass(frozen=True)
class HarborTaskMeta:
    task_dir: Path
    docker_image: str | None
    build_timeout_sec: int
    agent_timeout_sec: int | None
    verifier_timeout_sec: int
    allow_internet: bool
    cpus: float | None
    memory_mb: int | None
    storage_mb: int | None
    official_tests: bool
    official_tests_reason: str


def _as_int(value, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_float(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _read_toml(path: Path) -> dict:
    with path.open("rb") as handle:
        return tomllib.load(handle)


def _official_tests(tests_dir: Path) -> tuple[bool, str]:
    test_sh = tests_dir / "test.sh"
    if not test_sh.is_file():
        return False, "tests/test.sh missing"
    try:
        text = test_sh.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return False, f"tests/test.sh unreadable: {exc}"
    # LHTB 2.0 task-2.0 verifiers are private: the shell script references a
    # private directory that is not part of the public task snapshot.
    if ("private/" in text or "PRIVATE_ROOT" in text) and not (tests_dir / "private").is_dir():
        return False, "private verifier absent from public task snapshot"
    return True, ""


class MissingOfficialVerifier:
    def __init__(self, reason: str):
        self.reason = reason

    def grade(self) -> Grade:
        return Grade(valid=False, passed=False, checks_passed=0, checks_total=0,
                     detail=f"official verifier unavailable: {self.reason}")


def _parse_reward(text: str | None) -> float | None:
    if not text:
        return None
    for line in reversed(text.strip().splitlines()):
        try:
            return float(line.strip())
        except ValueError:
            continue
    return None


def _parse_ctrf(text: str | None) -> tuple[int, int] | None:
    """Return (passed, total) from a pytest-json-ctrf report if present."""
    if not text:
        return None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    summary = (data.get("results") or {}).get("summary") or {}
    passed = summary.get("passed")
    total = summary.get("tests") or summary.get("total")
    if isinstance(passed, int) and isinstance(total, int):
        return passed, total
    return None


class OfficialTestVerifier:
    """Run the task's official ``tests/test.sh`` inside the task container.

    Harbor's reference runner builds a separate verifier image for tasks with
    ``environment_mode = "shared"``.  The task containers used here expose the
    same ``/app`` filesystem, so copying the public tests in and running the
    same entrypoint is a faithful single-container approximation.  The grade is
    read from the official reward file, not recomputed.
    """

    def __init__(self, host: DockerHost, tests_dir: Path, timeout: int = 900,
                 workdir: str = "/app", private_root: str = "/tests/private"):
        self.host = host
        self.tests_dir = Path(tests_dir)
        self.timeout = timeout
        self.workdir = workdir
        self.private_root = private_root

    def _staged_tests(self) -> tuple[Path, Path]:
        """Copy tests to a temp dir and normalize shell-script line endings.

        Git on Windows may check out ``*.sh`` with CRLF; the container's
        ``sh``/``bash`` then sees ``then\\r`` and fails.  Normalizing a staged
        copy keeps the checked-out task files untouched.
        """
        staging = Path(tempfile.mkdtemp(prefix="harbor-tests-"))
        target = staging / "tests"
        shutil.copytree(self.tests_dir, target)
        for script in target.rglob("*.sh"):
            data = script.read_bytes().replace(b"\r\n", b"\n")
            script.write_bytes(data)
        return staging, target

    def grade(self) -> Grade:
        # The agent ran in this container.  Remove any /tests or reward file it
        # could have planted before copying the official tests in.  This is the
        # single-container approximation; Harbor uses a separate verifier
        # container for shared-mode tasks.
        self.host.exec(["rm", "-rf", "/tests", "/logs/verifier"])
        self.host.exec(["mkdir", "-p", "/tests", "/logs/verifier"])
        staging, staged = self._staged_tests()
        try:
            self.host.copy_in(staged, "/tests")
        finally:
            shutil.rmtree(staging, ignore_errors=True)
        # test.sh is expected to be bash; fall back to sh for minimal images.
        proc = self.host.exec(
            ["bash", "/tests/test.sh"],
            timeout=self.timeout,
            env={
                "WORKSPACE_ROOT": self.workdir,
                "PRIVATE_ROOT": self.private_root,
            },
            workdir="/tests",
        )
        error_text = (proc.stdout or "") + (proc.stderr or "")
        if proc.returncode == 127 and "bash" in error_text and "not found" in error_text:
            # Minimal images (alpine/busybox) have sh but not bash.  Official
            # tasks normally ship bash; this keeps the adapter usable on the
            # local smoke image without changing the task script.
            proc = self.host.exec(
                ["sh", "/tests/test.sh"],
                timeout=self.timeout,
                env={
                    "WORKSPACE_ROOT": self.workdir,
                    "PRIVATE_ROOT": self.private_root,
                },
                workdir="/tests",
            )
        reward_text = self.host.read_container_file("/logs/verifier/reward.txt")
        reward = _parse_reward(reward_text)
        ctrf_text = self.host.read_container_file("/logs/verifier/ctrf.json")
        checks = _parse_ctrf(ctrf_text)
        raw = (proc.stdout or "") + (proc.stderr or "")
        detail = f"official tests exit={proc.returncode}"
        if reward is not None:
            detail += f" reward={reward}"
        if checks:
            detail += f" checks={checks[0]}/{checks[1]}"
        detail += "\n" + raw[-3000:]
        if reward is None:
            return Grade(valid=False, passed=False,
                         checks_passed=checks[0] if checks else 0,
                         checks_total=checks[1] if checks else 0,
                         detail="official reward missing; " + detail)
        passed = reward >= 1.0
        return Grade(valid=True, passed=passed,
                     checks_passed=checks[0] if checks else (1 if passed else 0),
                     checks_total=checks[1] if checks else 1,
                     detail=detail)


class HarborBenchmarkAdapter(BenchmarkAdapter):
    """Load and run a directory of Harbor-format tasks."""

    name = "harbor"
    mock_only = False
    real_loader = True
    real_host = True

    def __init__(self, root: str | Path, name: str | None = None,
                 container_workdir: str = "/app"):
        self.root = Path(root)
        if not self.root.is_dir():
            raise FileNotFoundError(self.root)
        if name:
            self.name = name
        self.container_workdir = container_workdir
        self._meta: Dict[str, HarborTaskMeta] = {}
        self._tasks: List[TaskSpec] = []
        self._loaded = False

    # ------------------------------------------------------------------ load
    def _scan(self) -> None:
        if self._loaded:
            return
        for task_dir in sorted(p for p in self.root.iterdir() if p.is_dir()):
            toml_path = task_dir / "task.toml"
            instruction_path = task_dir / "instruction.md"
            if not toml_path.is_file() or not instruction_path.is_file():
                continue
            data = _read_toml(toml_path)
            env = data.get("environment") or {}
            agent = data.get("agent") or {}
            verifier = data.get("verifier") or {}
            tests_dir = task_dir / "tests"
            official, reason = _official_tests(tests_dir)
            meta = HarborTaskMeta(
                task_dir=task_dir,
                docker_image=env.get("docker_image"),
                build_timeout_sec=_as_int(env.get("build_timeout_sec"), 1800),
                agent_timeout_sec=_as_int(agent.get("timeout_sec"), 0) or None,
                verifier_timeout_sec=_as_int(verifier.get("timeout_sec"), 900),
                allow_internet=bool(env.get("allow_internet", True)),
                cpus=_as_float(env.get("cpus")),
                memory_mb=_as_int(env.get("memory_mb"), 0) or None,
                storage_mb=_as_int(env.get("storage_mb"), 0) or None,
                official_tests=official,
                official_tests_reason=reason,
            )
            self._meta[task_dir.name] = meta
            self._tasks.append(TaskSpec(
                task_id=task_dir.name,
                benchmark=self.name,
                instruction=instruction_path.read_text(encoding="utf-8"),
                initial_files={},
                metadata={
                    "task_dir": str(task_dir),
                    "docker_image": meta.docker_image,
                    "agent_timeout_sec": meta.agent_timeout_sec,
                    "timeout_sec": meta.agent_timeout_sec,
                    "continue_until_timeout": bool(agent.get("continue_until_timeout", False)),
                    "verifier_timeout_sec": meta.verifier_timeout_sec,
                    "allow_internet": meta.allow_internet,
                    "cpus": meta.cpus,
                    "memory_mb": meta.memory_mb,
                    "storage_mb": meta.storage_mb,
                    "official_tests": meta.official_tests,
                    "official_tests_reason": meta.official_tests_reason,
                    "artifacts": data.get("artifacts", []),
                    "task_name": (data.get("task") or {}).get("name"),
                    "benchmark": self.name,
                },
            ))
        self._loaded = True

    def load_tasks(self, path: str | None = None) -> List[TaskSpec]:
        if path is not None and Path(path) != self.root:
            self.root = Path(path)
            self._meta.clear()
            self._tasks.clear()
            self._loaded = False
        self._scan()
        return list(self._tasks)

    @property
    def official_task_count(self) -> int:
        self._scan()
        return sum(1 for m in self._meta.values() if m.official_tests)

    @property
    def hidden_task_count(self) -> int:
        self._scan()
        return sum(1 for m in self._meta.values() if not m.official_tests)

    @property
    def real_grader(self) -> bool:
        return self.official_task_count > 0

    @property
    def dataset_missing(self) -> str:
        return ""

    # ------------------------------------------------------------------ host
    def _docker_args(self, meta: HarborTaskMeta) -> List[str]:
        args: List[str] = []
        if meta.cpus:
            args.extend(["--cpus", str(meta.cpus)])
        if meta.memory_mb:
            args.extend(["--memory", f"{meta.memory_mb}m"])
        if not meta.allow_internet:
            args.extend(["--network", "none"])
        return args

    def _build_image(self, task: TaskSpec, meta: HarborTaskMeta) -> str:
        dockerfile = meta.task_dir / "environment" / "Dockerfile"
        if not dockerfile.is_file():
            raise FileNotFoundError(
                f"{task.task_id}: no docker_image and no environment/Dockerfile")
        slug = re.sub(r"[^a-z0-9_.-]+", "-", f"{self.name}-{task.task_id}".lower())
        tag = f"adapter-{slug}:latest"
        proc = subprocess.run(
            ["docker", "build", "-t", tag, "-f", str(dockerfile),
             str(dockerfile.parent)],
            capture_output=True, text=True, timeout=meta.build_timeout_sec,
        )
        if proc.returncode != 0:
            raise RuntimeError(
                f"{task.task_id}: docker build failed\n{proc.stdout[-2000:]}\n{proc.stderr[-2000:]}")
        return tag

    def make_host(self, task: TaskSpec, config: ExperimentConfig) -> Host:
        self._scan()
        meta = self._meta[task.task_id]
        image = meta.docker_image or self._build_image(task, meta)
        host = DockerHost(
            task, config, image, "true",
            container_workdir=self.container_workdir,
            docker_args=self._docker_args(meta),
        )
        if meta.official_tests:
            host.verifier = OfficialTestVerifier(
                host, meta.task_dir / "tests",
                timeout=meta.verifier_timeout_sec,
                workdir=self.container_workdir,
            )
        else:
            host.verifier = MissingOfficialVerifier(meta.official_tests_reason)
        return host

    def grade(self, task: TaskSpec, host: Host) -> Grade:
        return host.grade()


class MissingDatasetAdapter(BenchmarkAdapter):
    """A benchmark whose public dataset is not present on this machine."""

    name = "missing"
    mock_only = True
    real_loader = False
    real_host = False
    real_grader = False

    def __init__(self, name: str, reason: str):
        self.name = name
        self.reason = reason

    @property
    def dataset_missing(self) -> str:
        return self.reason

    def load_tasks(self, path: str | None = None) -> List[TaskSpec]:
        raise FileNotFoundError(self.reason)

    def make_host(self, task: TaskSpec, config: ExperimentConfig) -> Host:
        raise FileNotFoundError(self.reason)

    def grade(self, task: TaskSpec, host: Host) -> Grade:
        return Grade(valid=False, passed=False, checks_passed=0, checks_total=0,
                     detail=self.reason)
