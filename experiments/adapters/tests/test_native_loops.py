"""Offline tests for the three native method loops.

Each loop runs against a real LocalHost + manifest task with a deterministic
model client.  No 9B inference is involved; the point is that the method's own
mechanism (Recuris memory, Sentry detector, RRSI candidate prompt) is executed
inside the common contract and the benchmark still grades independently.

Two tasks are used per loop (a file write and a different file write) so the
smoke is not a single-task artifact.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agents.base_react import ListModelClient, ModelClient, ModelResponse
from benchmarks.base import run_task
from benchmarks.manifest import ManifestBenchmarkAdapter
from contract.types import ExperimentConfig
from methods.adapters import RecurisAdapter, RRSIAdapter, SentryAdapter, build_recuris, build_rrsi, build_sentry

MANIFEST = [
    {
        "task_id": "hello",
        "instruction": "Write answer.txt containing hello.",
        "initial_files": {},
        "checks": {"answer.txt": "hello"},
    },
    {
        "task_id": "sum",
        "instruction": "Write result.txt containing 42.",
        "initial_files": {},
        "checks": {"result.txt": "42"},
    },
]

TASK_ARTIFACTS = {
    "hello": ("answer.txt", "hello"),
    "sum": ("result.txt", "42"),
}


class RoutingClient(ModelClient):
    """Serve actor turns and the Sentry detector's auxiliary JSON."""

    def __init__(self, actor):
        self.actor = list(actor)
        self.detector_calls = 0

    def complete(self, messages, **kwargs):
        prompt = messages[-1]["content"] if messages else ""
        if isinstance(prompt, str) and prompt.startswith("[SENTRY DETECTOR]"):
            self.detector_calls += 1
            return ModelResponse(json.dumps({
                "intervention_needed": False,
                "failure_type": "no_failure",
                "retrieval_labels": [],
                "local_evidence": [],
                "diagnosis": "no failure in the current window",
            }), 5)
        if self.actor:
            return self.actor.pop(0)
        return ModelResponse('{"final":"out of responses"}', 5)


def actor_responses(task_id: str):
    path, value = TASK_ARTIFACTS[task_id]
    return [
        ModelResponse(json.dumps({"command": f"echo {value} > {path}"}), 10),
        ModelResponse('{"final":"done"}', 10),
    ]


class NativeLoopTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        manifest = Path(self.tmp.name) / "manifest.json"
        manifest.write_text(json.dumps(MANIFEST), encoding="utf-8")
        self.benchmark = ManifestBenchmarkAdapter(manifest)
        self.tasks = self.benchmark.load_tasks()
        self.config = ExperimentConfig(token_budget=10_000, max_actions=20)

    def tearDown(self):
        self.tmp.cleanup()

    def test_recuris_m0_runs_and_grades(self):
        for task in self.tasks:
            with self.subTest(task=task.task_id):
                client = ListModelClient(actor_responses(task.task_id))
                agent = build_recuris(client, completion_gate=False)
                self.assertIsInstance(agent, RecurisAdapter)
                record, grade = run_task(self.benchmark, agent, task, self.config)
                self.assertTrue(grade.valid, grade.detail)
                self.assertTrue(grade.passed, grade.detail)
                self.assertGreaterEqual(agent.native.turns, 2)
                self.assertTrue(agent.native.counters)
                self.assertEqual(record.grade_calls_during_run, 0)

    def test_recuris_completion_gate_runs(self):
        for task in self.tasks:
            with self.subTest(task=task.task_id):
                # Extra turns let a gate bounce happen without exhausting the script.
                client = ListModelClient(
                    actor_responses(task.task_id)
                    + actor_responses(task.task_id)
                    + actor_responses(task.task_id)
                )
                agent = build_recuris(client, completion_gate=True)
                record, grade = run_task(self.benchmark, agent, task, self.config)
                self.assertTrue(grade.valid, grade.detail)
                self.assertTrue(grade.passed, grade.detail)
                self.assertLessEqual(agent.native.bounces, agent.native.max_bounces)

    def test_sentry_detector_runs_and_grades(self):
        for task in self.tasks:
            with self.subTest(task=task.task_id):
                client = RoutingClient(actor_responses(task.task_id))
                agent = build_sentry(client)
                self.assertIsInstance(agent, SentryAdapter)
                record, grade = run_task(self.benchmark, agent, task, self.config)
                self.assertTrue(grade.valid, grade.detail)
                self.assertTrue(grade.passed, grade.detail)
                self.assertGreaterEqual(client.detector_calls, 1)
                self.assertGreaterEqual(agent.native.phases["detector"], 1)
                self.assertGreaterEqual(agent.native.steps, 2)
                self.assertEqual(record.grade_calls_during_run, 0)

    def test_rrsi_candidate_prompt_runs_and_grades(self):
        for task in self.tasks:
            with self.subTest(task=task.task_id):
                client = ListModelClient(actor_responses(task.task_id))
                agent = build_rrsi(client)
                self.assertIsInstance(agent, RRSIAdapter)
                record, grade = run_task(self.benchmark, agent, task, self.config)
                self.assertTrue(grade.valid, grade.detail)
                self.assertTrue(grade.passed, grade.detail)
                self.assertEqual(len(agent.native.prompt_sha256), 64)
                self.assertIn("terminal", agent.native.system_prompt.lower())
                self.assertEqual(record.grade_calls_during_run, 0)


if __name__ == "__main__":
    unittest.main()
