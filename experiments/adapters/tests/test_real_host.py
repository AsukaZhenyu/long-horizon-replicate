"""End-to-end tests on a real LocalHost and a real Docker host."""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from agents.base_react import BaseReactAgent, ListModelClient, ModelResponse
from benchmarks.base import run_task
from benchmarks.lhtb import LHTBBenchmarkAdapter
from benchmarks.manifest import ManifestBenchmarkAdapter
from contract.types import Action, ExperimentConfig, ScriptedAgent, TaskSpec
from hosts.docker import DockerHost
from methods.adapters import BaseAgentAdapter


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


class RealHostTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.manifest = Path(self.tmp.name) / "manifest.json"
        self.manifest.write_text(json.dumps(MANIFEST), encoding="utf-8")
        self.config = ExperimentConfig(token_budget=1000, max_actions=50)

    def tearDown(self):
        self.tmp.cleanup()

    def test_manifest_scripted_agent_end_to_end(self):
        benchmark = ManifestBenchmarkAdapter(self.manifest)
        base = BaseAgentAdapter(ScriptedAgent([
            Action("write", {"path": "answer.txt", "content": "hello"}),
            Action("write", {"path": "result.txt", "content": "42"}),
            Action("submit"),
        ]))
        for task in benchmark.load_tasks():
            record, grade = run_task(benchmark, base, task, self.config)
            self.assertTrue(grade.valid)
            self.assertTrue(grade.passed, task.task_id)
            self.assertTrue(record.completion)

    def test_base_react_agent_end_to_end(self):
        benchmark = ManifestBenchmarkAdapter(self.manifest)
        task = benchmark.load_tasks()[0]
        host = benchmark.make_host(task, self.config)
        client = ListModelClient([
            ModelResponse('{"command":"echo hello> answer.txt"}', 10),
            ModelResponse('{"final":"done"}', 10),
        ])
        try:
            BaseReactAgent(client).run(task, host)
            self.assertEqual(host.grade_calls, 0)
            grade = benchmark.grade(task, host)
            self.assertTrue(grade.valid)
            self.assertTrue(grade.passed, grade.detail)
            self.assertGreater(host.tokens_used, 0)
        finally:
            host.cleanup()

    @unittest.skipUnless(
        shutil.which("docker") and subprocess.run(
            ["docker", "info"], capture_output=True).returncode == 0,
        "docker daemon not available",
    )
    def test_docker_host_end_to_end(self):
        task = TaskSpec("docker-hello", "docker", "write hello", initial_files={})
        host = DockerHost(
            task, self.config, "alpine:latest",
            "test -f /app/answer.txt && grep -q hello /app/answer.txt",
        )
        try:
            host.step(Action("write", {"path": "answer.txt", "content": "hello\n"}))
            host.submit()
            self.assertEqual(host.grade_calls, 0)
            grade = host.grade()
            self.assertTrue(grade.valid)
            self.assertTrue(grade.passed, grade.detail)
        finally:
            host.cleanup()

    def test_token_budget_stops_agent(self):
        benchmark = ManifestBenchmarkAdapter(self.manifest)
        task = benchmark.load_tasks()[0]
        host = benchmark.make_host(task, self.config)
        client = ListModelClient([
            ModelResponse('{"command":"echo hello> answer.txt"}', 5000),
            ModelResponse('{"final":"done"}', 10),
        ])
        try:
            BaseReactAgent(client).run(task, host)
            grade = benchmark.grade(task, host)
            self.assertFalse(grade.passed)
        finally:
            host.cleanup()


if __name__ == "__main__":
    unittest.main()
