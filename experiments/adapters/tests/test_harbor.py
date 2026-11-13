"""Harbor-format loader and official-test grading tests.

The loader tests use the real TB 2.1 / LHTB checkouts when present.  The
grading test uses a synthetic task on a locally available image so it can run
without pulling a benchmark image; the verifier path is the same one used for
official tasks.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from benchmarks.base import run_task
from benchmarks.harbor import HarborBenchmarkAdapter
from benchmarks.lhtb import LHTBBenchmarkAdapter
from benchmarks.tb import TerminalBench21Adapter, DEFAULT_ROOT as TB21_ROOT
from contract.types import Action, ExperimentConfig, ScriptedAgent
from methods.adapters import BaseAgentAdapter


def docker_available() -> bool:
    return bool(shutil.which("docker")) and subprocess.run(
        ["docker", "info"], capture_output=True).returncode == 0


def local_alpine() -> str | None:
    proc = subprocess.run(
        ["docker", "images", "--format", "{{.Repository}}:{{.Tag}}"],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        return None
    images = [line.strip() for line in proc.stdout.splitlines()]
    for name in ("alpine:latest", "busybox:latest"):
        if name in images:
            return name
    # A TB8 client image is a known local fallback with a shell.
    for name in images:
        if "hello-world" in name and "client" not in name:
            return name
    return None


class HarborLoaderTests(unittest.TestCase):
    @unittest.skipUnless(TB21_ROOT.is_dir(), "TB 2.1 checkout not present")
    def test_tb21_loads_official_tasks(self):
        adapter = TerminalBench21Adapter()
        tasks = adapter.load_tasks()
        self.assertGreaterEqual(len(tasks), 80)
        self.assertTrue(adapter.real_loader)
        self.assertTrue(adapter.real_host)
        self.assertTrue(adapter.real_grader)
        self.assertGreater(adapter.official_task_count, 0)
        sample = tasks[0]
        self.assertTrue(sample.instruction.strip())
        self.assertTrue(sample.metadata["official_tests"])
        self.assertIn("task_dir", sample.metadata)

    @unittest.skipUnless(
        (Path(__file__).resolve().parents[3] / ".cache" / "upstream" / "lhtb").is_dir(),
        "LHTB checkout not present",
    )
    def test_lhtb_public_and_private_task_sets(self):
        repo = Path(__file__).resolve().parents[3]
        original = LHTBBenchmarkAdapter(repo / ".cache" / "upstream" / "lhtb",
                                        subdir="tasks")
        new = LHTBBenchmarkAdapter(repo / ".cache" / "upstream" / "lhtb",
                                   subdir="tasks-2.0")
        self.assertEqual(len(original.load_tasks()), 46)
        self.assertEqual(len(new.load_tasks()), 31)
        self.assertTrue(original.real_grader)
        self.assertTrue(new.real_grader)
        self.assertTrue(all(t.metadata["official_tests"] for t in original.load_tasks()))
        self.assertTrue(all(t.metadata["official_tests"] for t in new.load_tasks()))


class OfficialGradingTests(unittest.TestCase):
    def _synthetic_adapter(self, tmp: str, image: str):
        root = Path(tmp) / "tasks"
        task_dir = root / "hello"
        tests = task_dir / "tests"
        tests.mkdir(parents=True)
        (task_dir / "task.toml").write_text(
            'schema_version = "1.1"\n'
            '[environment]\n'
            f'docker_image = "{image}"\n'
            'allow_internet = true\n'
            '[agent]\n'
            'timeout_sec = 60\n'
            '[verifier]\n'
            'timeout_sec = 60\n',
            encoding="utf-8",
        )
        (task_dir / "instruction.md").write_text(
            "Write /app/answer.txt containing hello.\n", encoding="utf-8")
        (tests / "test.sh").write_bytes(
            b'#!/bin/bash\n'
            b'mkdir -p /logs/verifier\n'
            b'if [ -f /app/answer.txt ] && grep -q hello /app/answer.txt; then\n'
            b'  echo 1 > /logs/verifier/reward.txt\n'
            b'else\n'
            b'  echo 0 > /logs/verifier/reward.txt\n'
            b'fi\n'
        )
        adapter = HarborBenchmarkAdapter(root, name="smoke")
        return adapter, adapter.load_tasks()[0]

    @unittest.skipUnless(docker_available(), "docker daemon not available")
    def test_official_reward_is_read_from_test_sh(self):
        image = local_alpine()
        if image is None:
            self.skipTest("no local alpine/busybox image")
        with tempfile.TemporaryDirectory() as tmp:
            adapter, task = self._synthetic_adapter(tmp, image)
            self.assertTrue(task.metadata["official_tests"])
            config = ExperimentConfig(token_budget=1000, max_actions=20)

            good = BaseAgentAdapter(ScriptedAgent([
                Action("write", {"path": "answer.txt", "content": "hello\n"}),
                Action("submit"),
            ]))
            record, grade = run_task(adapter, good, task, config)
            self.assertTrue(grade.valid, grade.detail)
            self.assertTrue(grade.passed, grade.detail)
            self.assertTrue(record.completion)

            bad = BaseAgentAdapter(ScriptedAgent([
                Action("write", {"path": "answer.txt", "content": "nope\n"}),
                Action("submit"),
            ]))
            record, grade = run_task(adapter, bad, task, config)
            self.assertTrue(grade.valid, grade.detail)
            self.assertFalse(grade.passed, grade.detail)
            self.assertFalse(record.completion)

    @unittest.skipUnless(docker_available(), "docker daemon not available")
    def test_planted_reward_is_removed_before_grading(self):
        image = local_alpine()
        if image is None:
            self.skipTest("no local alpine/busybox image")
        with tempfile.TemporaryDirectory() as tmp:
            adapter, task = self._synthetic_adapter(tmp, image)
            config = ExperimentConfig(token_budget=1000, max_actions=20)
            # The method tries to pre-write the verifier's reward file.  The
            # verifier must remove /logs/verifier before running the tests.
            plant = BaseAgentAdapter(ScriptedAgent([
                Action("shell", {"command":
                       "mkdir -p /logs/verifier && echo 1 > /logs/verifier/reward.txt"}),
                Action("write", {"path": "answer.txt", "content": "nope\n"}),
                Action("submit"),
            ]))
            record, grade = run_task(adapter, plant, task, config)
            self.assertTrue(grade.valid, grade.detail)
            self.assertFalse(grade.passed, grade.detail)
            self.assertFalse(record.completion)


if __name__ == "__main__":
    unittest.main()
