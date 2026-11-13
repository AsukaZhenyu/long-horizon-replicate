"""Agents must continue after a benchmark-side submit rejection."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agents.base_react import BaseReactAgent, ListModelClient, ModelResponse
from agents.recuris import RecurisAgent
from benchmarks.manifest import ManifestBenchmarkAdapter
from contract.types import ExperimentConfig

MANIFEST = [{
    "task_id": "hello",
    "instruction": "Write answer.txt containing hello.",
    "initial_files": {},
    "checks": {"answer.txt": "hello"},
}]


def responses():
    return [
        ModelResponse('{"final":"done"}', 10),
        ModelResponse('{"command":"echo hello > answer.txt"}', 10),
        ModelResponse('{"final":"done"}', 10),
    ]


class SubmitGuardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        manifest = Path(self.tmp.name) / "manifest.json"
        manifest.write_text(json.dumps(MANIFEST), encoding="utf-8")
        self.benchmark = ManifestBenchmarkAdapter(manifest)
        self.task = self.benchmark.load_tasks()[0]
        self.config = ExperimentConfig(token_budget=10_000, max_actions=20)

    def tearDown(self):
        self.tmp.cleanup()

    def _host(self):
        host = self.benchmark.make_host(self.task, self.config)
        host.submit_guard = lambda: (
            None if (host.workdir / "answer.txt").is_file()
            else "answer.txt is required before submit")
        return host

    def test_base_react_continues_after_rejection(self):
        host = self._host()
        try:
            agent = BaseReactAgent(ListModelClient(responses()), max_steps=6)
            agent.run(self.task, host)
            self.assertTrue(host.submitted)
            grade = self.benchmark.grade(self.task, host)
            self.assertTrue(grade.valid, grade.detail)
            self.assertTrue(grade.passed, grade.detail)
        finally:
            host.cleanup()

    def test_recuris_continues_after_rejection(self):
        host = self._host()
        try:
            agent = RecurisAgent(ListModelClient(responses()),
                                 completion_gate=False, max_steps=6)
            agent.run(self.task, host)
            self.assertTrue(host.submitted)
            grade = self.benchmark.grade(self.task, host)
            self.assertTrue(grade.valid, grade.detail)
            self.assertTrue(grade.passed, grade.detail)
        finally:
            host.cleanup()


if __name__ == "__main__":
    unittest.main()
