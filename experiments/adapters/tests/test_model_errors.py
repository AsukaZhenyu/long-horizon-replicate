"""A model endpoint error must become a recorded agent error, not a crash."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agents.base_react import BaseReactAgent, ModelClient, ModelRequestError
from agents.recuris import RecurisAgent
from agents.sentry import SentryAgent
from agents.spine import SpineAgent
from benchmarks.manifest import ManifestBenchmarkAdapter
from contract.types import ExperimentConfig

MANIFEST = [{
    "task_id": "hello",
    "instruction": "Write answer.txt containing hello.",
    "initial_files": {},
    "checks": {"answer.txt": "hello"},
}]


class FailingClient(ModelClient):
    def complete(self, messages, **kwargs):
        raise ModelRequestError("HTTP 400: context overflow")


class HugeTokenClient(ModelClient):
    def complete(self, messages, **kwargs):
        from agents.base_react import ModelResponse
        return ModelResponse('{"final":"done"}', 2000)


class ModelErrorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        manifest = Path(self.tmp.name) / "manifest.json"
        manifest.write_text(json.dumps(MANIFEST), encoding="utf-8")
        self.benchmark = ManifestBenchmarkAdapter(manifest)
        self.task = self.benchmark.load_tasks()[0]
        self.config = ExperimentConfig(token_budget=1000, max_actions=20)

    def tearDown(self):
        self.tmp.cleanup()

    def _run(self, agent):
        host = self.benchmark.make_host(self.task, self.config)
        try:
            agent.run(self.task, host)
            self.assertIn("HTTP 400", agent.last_error)
            self.assertEqual(host.actions, [])
            grade = self.benchmark.grade(self.task, host)
            self.assertTrue(grade.valid)
            self.assertFalse(grade.passed)
        finally:
            host.cleanup()

    def test_base_react_records_model_error(self):
        self._run(BaseReactAgent(FailingClient(), max_steps=2))

    def test_recuris_records_model_error(self):
        self._run(RecurisAgent(FailingClient(), completion_gate=False, max_steps=2))

    def test_sentry_records_model_error(self):
        self._run(SentryAgent(FailingClient(), max_steps=2))

    def _run_budget(self, agent):
        host = self.benchmark.make_host(self.task, self.config)
        try:
            agent.run(self.task, host)
            self.assertIn("token budget exceeded", agent.last_error)
            grade = self.benchmark.grade(self.task, host)
            self.assertTrue(grade.valid)
            self.assertFalse(grade.passed)
        finally:
            host.cleanup()

    def test_base_records_token_budget(self):
        self._run_budget(BaseReactAgent(HugeTokenClient(), max_steps=2))

    def test_recuris_records_token_budget(self):
        self._run_budget(RecurisAgent(HugeTokenClient(), completion_gate=False,
                                      max_steps=2))

    def test_sentry_records_token_budget(self):
        self._run_budget(SentryAgent(HugeTokenClient(), max_steps=2))

    def test_spine_records_token_budget(self):
        self._run_budget(SpineAgent(HugeTokenClient(), max_steps=2))


if __name__ == "__main__":
    unittest.main()
