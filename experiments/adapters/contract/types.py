"""Common host contract shared by every benchmark and method adapter.

The contract is deliberately small: a task, an action, an observation, a grade.
Method adapters translate their native action schema to Action and back; they do
not change the task, the tools, the token budget or the grading.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Tuple


@dataclass(frozen=True)
class ExperimentConfig:
    model: str = "qwen3.5-9b"
    token_budget: int = 1_000_000
    tools: Tuple[str, ...] = ("bash", "write", "read", "submit")
    seed: int = 0
    max_actions: int = 1000


@dataclass(frozen=True)
class TaskSpec:
    task_id: str
    benchmark: str
    instruction: str
    initial_files: Dict[str, str] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Action:
    kind: str
    payload: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Observation:
    output: str = ""
    error: str = ""
    exit_code: int = 0


@dataclass(frozen=True)
class Grade:
    valid: bool
    passed: bool
    checks_passed: int
    checks_total: int
    detail: str = ""


@dataclass(frozen=True)
class VerifierSpec:
    """Hidden checks.  Only the benchmark adapter and the runner hold this."""
    checks: Dict[str, str]


class Host(ABC):
    """What a method sees.  No hidden checks are reachable from here."""

    @abstractmethod
    def step(self, action: Action) -> Observation:
        raise NotImplementedError

    @abstractmethod
    def submit(self) -> Observation:
        raise NotImplementedError

    @abstractmethod
    def grade(self) -> Grade:
        raise NotImplementedError

    @property
    @abstractmethod
    def tokens_used(self) -> int:
        raise NotImplementedError

    @property
    @abstractmethod
    def actions(self) -> List[Action]:
        raise NotImplementedError


class NativeAgent(ABC):
    """A method's native loop.  It may only interact through the Host."""

    @abstractmethod
    def run(self, task: TaskSpec, host: Host) -> None:
        raise NotImplementedError


class MethodAdapter(ABC):
    """Translates a native action schema to/from the common contract.

    The adapter must not add, remove or reorder actions, and must not change
    the token budget, tool permissions or grading.
    """

    name: str = ""
    native_loop_ready: bool = False
    mechanism: Tuple[str, ...] = ()
    adapter_changes: Tuple[str, ...] = ()

    def __init__(self, native: NativeAgent):
        self.native = native

    def run(self, task: TaskSpec, host: Host) -> None:
        self.native.run(task, host)


class BenchmarkAdapter(ABC):
    name: str = ""
    mock_only: bool = True
    real_loader: bool = False
    real_host: bool = False
    real_grader: bool = False

    @abstractmethod
    def load_tasks(self, path: str | None = None) -> List[TaskSpec]:
        raise NotImplementedError

    @abstractmethod
    def make_host(self, task: TaskSpec, config: ExperimentConfig) -> Host:
        raise NotImplementedError

    @abstractmethod
    def grade(self, task: TaskSpec, host: Host) -> Grade:
        raise NotImplementedError


class MockVerifier:
    def __init__(self, spec: VerifierSpec):
        self.spec = spec

    def grade(self, files: Dict[str, str]) -> Grade:
        total = len(self.spec.checks)
        passed = sum(1 for path, content in self.spec.checks.items()
                     if files.get(path) == content)
        return Grade(valid=True, passed=passed == total,
                     checks_passed=passed, checks_total=total,
                     detail=f"{passed}/{total} checks")


class MockHost(Host):
    """In-memory host used by the contract tests.

    It deliberately does NOT expose the hidden checks.  The verifier is held by
    the benchmark adapter, and grade() is only called by the runner after the
    method stops.
    """

    def __init__(self, task: TaskSpec, verifier: MockVerifier,
                 config: ExperimentConfig):
        self.task = task
        self._verifier = verifier
        self.config = config
        self.files: Dict[str, str] = dict(task.initial_files)
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

    def step(self, action: Action) -> Observation:
        if len(self._actions) >= self.config.max_actions:
            return Observation(error="max actions reached", exit_code=1)
        self._actions.append(action)
        self._tokens += 1
        kind = action.kind
        if kind == "write":
            path = action.payload.get("path", "")
            content = action.payload.get("content", "")
            self.files[path] = content
            return Observation(output=f"wrote {path}")
        if kind == "read":
            path = action.payload.get("path", "")
            if path in self.files:
                return Observation(output=self.files[path])
            return Observation(error=f"missing {path}", exit_code=1)
        if kind == "shell":
            command = action.payload.get("command", "")
            # Minimal shell for the mock: echo TEXT > PATH
            if command.startswith("echo ") and " > " in command:
                text = command[len("echo "):].split(" > ", 1)[0].strip("'\"")
                path = command.split(" > ", 1)[1].strip()
                self.files[path] = text + "\n"
                return Observation(output=f"wrote {path}")
            return Observation(error="unsupported mock shell", exit_code=1)
        if kind == "submit":
            self.submitted = True
            return Observation(output="submitted")
        return Observation(error=f"unknown action {kind}", exit_code=1)

    def submit(self) -> Observation:
        return self.step(Action("submit"))

    def grade(self) -> Grade:
        self.grade_calls += 1
        return self._verifier.grade(self.files)


class ScriptedAgent(NativeAgent):
    """Deterministic agent for adapter tests."""

    def __init__(self, actions: List[Action]):
        self._actions = actions

    def run(self, task: TaskSpec, host: Host) -> None:
        for action in self._actions:
            host.step(action)
            if action.kind == "submit":
                break


@dataclass(frozen=True)
class RunRecord:
    method: str
    benchmark: str
    task_id: str
    actions: Tuple[Action, ...]
    tokens: int
    completion: bool
    grade: Grade
    mechanism: Tuple[str, ...]
    adapter_changes: Tuple[str, ...]
    hidden_test_access: bool
    grade_calls_during_run: int
    config: ExperimentConfig
