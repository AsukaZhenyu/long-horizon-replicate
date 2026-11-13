"""Benchmark adapters and the shared runner."""
from __future__ import annotations

from typing import Dict, List

from contract.types import (
    Action, BenchmarkAdapter, ExperimentConfig, Grade, Host, MethodAdapter,
    MockHost, MockVerifier, NativeAgent, RunRecord, TaskSpec, VerifierSpec,
)


class MockBenchmarkAdapter(BenchmarkAdapter):
    """Contract-test benchmark adapter.

    Real dataset loaders are added per benchmark; this class only provides the
    deterministic mock tasks used to prove the adapter layer works.
    """

    name = "mock"
    mock_only = True

    def __init__(self):
        self._verifiers: Dict[str, MockVerifier] = {}

    def load_tasks(self, path: str | None = None) -> List[TaskSpec]:
        if path is not None:
            raise NotImplementedError(
                f"{self.name}: real dataset loader not configured in the contract tests"
            )
        tasks = [
            TaskSpec(
                task_id=f"{self.name}-hello",
                benchmark=self.name,
                instruction="Write answer.txt containing hello.",
                initial_files={},
                metadata={"complexity": "low"},
            ),
            TaskSpec(
                task_id=f"{self.name}-sum",
                benchmark=self.name,
                instruction="Write result.txt containing 42.",
                initial_files={},
                metadata={"complexity": "mid"},
            ),
        ]
        for task in tasks:
            checks = ({"answer.txt": "hello\n"} if task.task_id.endswith("hello")
                      else {"result.txt": "42\n"})
            self._verifiers[task.task_id] = MockVerifier(VerifierSpec(checks))
        return tasks

    def make_host(self, task: TaskSpec, config: ExperimentConfig) -> Host:
        if task.task_id not in self._verifiers:
            raise KeyError(f"unknown task {task.task_id}")
        return MockHost(task, self._verifiers[task.task_id], config)

    def grade(self, task: TaskSpec, host: Host) -> Grade:
        return host.grade()


class TB21Adapter(MockBenchmarkAdapter):
    name = "tb21"


class LHTB2Adapter(MockBenchmarkAdapter):
    name = "lhtb2"


class CoreAdapter(MockBenchmarkAdapter):
    name = "core"


class MLEAdapter(MockBenchmarkAdapter):
    name = "mle"


def run_task(benchmark: BenchmarkAdapter, method: MethodAdapter,
             task: TaskSpec, config: ExperimentConfig):
    host = benchmark.make_host(task, config)
    before_actions = len(host.actions)
    before_tokens = host.tokens_used
    method.run(task, host)
    grade_calls_during_run = host.grade_calls
    grade = benchmark.grade(task, host)
    actions = tuple(host.actions[before_actions:])
    record = RunRecord(
        method=method.name,
        benchmark=benchmark.name,
        task_id=task.task_id,
        actions=actions,
        tokens=host.tokens_used - before_tokens,
        completion=bool(grade.valid and grade.passed),
        grade=grade,
        mechanism=tuple(method.mechanism),
        adapter_changes=tuple(method.adapter_changes),
        hidden_test_access=False,
        grade_calls_during_run=grade_calls_during_run,
        config=config,
    )
    return record, grade


def run_native(benchmark: BenchmarkAdapter, agent: NativeAgent,
               task: TaskSpec, config: ExperimentConfig):
    """Run a native agent without the adapter; used for invariance checks."""
    host = benchmark.make_host(task, config)
    agent.run(task, host)
    grade = benchmark.grade(task, host)
    return tuple(host.actions), host.tokens_used, grade
