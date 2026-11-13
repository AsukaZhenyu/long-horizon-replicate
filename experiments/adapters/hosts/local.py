"""A real local host: shell, read/write, submit and a verifier.

The host runs in a per-task temporary directory.  It is deliberately small; it
is used by manifest tasks and by the base ReAct loop before the Docker host is
connected.
"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, List

from contract.types import (
    Action, ExperimentConfig, Grade, Host, Observation, TaskSpec,
)


class Verifier(ABC):
    @abstractmethod
    def grade(self, workdir: Path) -> Grade:
        raise NotImplementedError


class FileCheckVerifier(Verifier):
    """Check exact file contents (strip trailing whitespace)."""

    def __init__(self, checks: Dict[str, str]):
        self.checks = checks

    def grade(self, workdir: Path) -> Grade:
        total = len(self.checks)
        passed = 0
        detail = []
        for path, expected in self.checks.items():
            target = workdir / path
            try:
                got = target.read_text(encoding="utf-8").strip()
            except (FileNotFoundError, UnicodeDecodeError):
                got = None
            ok = got == expected.strip()
            passed += int(ok)
            detail.append(f"{path}:{'ok' if ok else 'miss'}")
        return Grade(valid=True, passed=passed == total,
                     checks_passed=passed, checks_total=total,
                     detail=", ".join(detail))


class CommandVerifier(Verifier):
    """Run a verifier command; exit 0 means all checks passed."""

    def __init__(self, command: str, timeout: int = 60):
        self.command = command
        self.timeout = timeout

    def grade(self, workdir: Path) -> Grade:
        proc = subprocess.run(self.command, shell=True, cwd=workdir,
                              capture_output=True, text=True,
                              timeout=self.timeout)
        passed = proc.returncode == 0
        return Grade(valid=True, passed=passed,
                     checks_passed=1 if passed else 0, checks_total=1,
                     detail=(proc.stdout + proc.stderr)[-2000:])


class LocalHost(Host):
    def __init__(self, task: TaskSpec, verifier: Verifier,
                 config: ExperimentConfig, workdir: Path | None = None):
        self.task = task
        self._verifier = verifier
        self.config = config
        self.workdir = Path(workdir or tempfile.mkdtemp(prefix="adapter-"))
        self.workdir.mkdir(parents=True, exist_ok=True)
        for path, content in task.initial_files.items():
            target = self.workdir / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        self._actions: List[Action] = []
        self._tokens = 0
        self.grade_calls = 0
        self.submitted = False

    @property
    def tokens_used(self) -> int:
        return self._tokens

    @property
    def actions(self) -> List[Action]:
        return list(self._actions)

    def charge_tokens(self, n: int) -> None:
        self._tokens += max(0, int(n))
        if self._tokens > self.config.token_budget:
            raise RuntimeError(f"token budget exceeded: {self._tokens}")

    def _safe(self, path: str) -> Path:
        target = (self.workdir / path).resolve()
        if target != self.workdir and self.workdir not in target.parents:
            raise ValueError(f"path escapes workspace: {path}")
        return target

    def step(self, action: Action) -> Observation:
        if len(self._actions) >= self.config.max_actions:
            return Observation(error="max actions reached", exit_code=1)
        self._actions.append(action)
        if action.kind == "write":
            target = self._safe(action.payload.get("path", ""))
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(action.payload.get("content", ""), encoding="utf-8")
            return Observation(output=f"wrote {target.relative_to(self.workdir)}")
        if action.kind == "read":
            target = self._safe(action.payload.get("path", ""))
            try:
                return Observation(output=target.read_text(encoding="utf-8"))
            except FileNotFoundError:
                return Observation(error=f"missing {action.payload.get('path')}", exit_code=1)
        if action.kind == "shell":
            command = action.payload.get("command", "")
            proc = subprocess.run(command, shell=True, cwd=self.workdir,
                                  capture_output=True, text=True, timeout=120)
            return Observation(output=proc.stdout[-8000:],
                               error=proc.stderr[-8000:],
                               exit_code=proc.returncode)
        if action.kind == "submit":
            self.submitted = True
            return Observation(output="submitted")
        return Observation(error=f"unknown action {action.kind}", exit_code=1)

    def submit(self) -> Observation:
        return self.step(Action("submit"))

    def grade(self) -> Grade:
        self.grade_calls += 1
        return self._verifier.grade(self.workdir)

    def cleanup(self) -> None:
        shutil.rmtree(self.workdir, ignore_errors=True)
