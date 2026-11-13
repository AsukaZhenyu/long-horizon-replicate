"""Offline smoke for the Spine subtask-tree reimplementation.

This is not the official Pi/Node plugin.  It verifies that the common contract
can observe the Spine protocol: branches open/close/next, closed branch history
is replaced by its memory, and terminal actions still go through the Host.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agents.base_react import ListModelClient, ModelResponse
from benchmarks.base import run_task
from benchmarks.manifest import ManifestBenchmarkAdapter
from contract.types import ExperimentConfig
from methods.adapters import SpineReimplementationAdapter, build_spine_reimpl

MANIFEST = [{
    "task_id": "hello",
    "instruction": "Write answer.txt containing hello.",
    "initial_files": {},
    "checks": {"answer.txt": "hello"},
}]


def trace(*actions):
    return [ModelResponse(json.dumps(action), 10) for action in actions]


class SpineReimplementationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        manifest = Path(self.tmp.name) / "manifest.json"
        manifest.write_text(json.dumps(MANIFEST), encoding="utf-8")
        self.benchmark = ManifestBenchmarkAdapter(manifest)
        self.task = self.benchmark.load_tasks()[0]
        self.config = ExperimentConfig(token_budget=10_000, max_actions=20)

    def tearDown(self):
        self.tmp.cleanup()

    def test_open_command_close_final(self):
        client = ListModelClient(trace(
            {"spine_open": {"goal": "inspect"}},
            {"command": "echo hello > answer.txt"},
            {"spine_close": {"memory": "wrote answer"}},
            {"final": "done"},
        ))
        agent = build_spine_reimpl(client)
        self.assertIsInstance(agent, SpineReimplementationAdapter)
        record, grade = run_task(self.benchmark, agent, self.task, self.config)
        self.assertTrue(grade.valid, grade.detail)
        self.assertTrue(grade.passed, grade.detail)
        self.assertEqual(agent.native.spine_actions["spine_open"], 1)
        self.assertEqual(agent.native.spine_actions["spine_close"], 1)
        nodes = agent.native.tree_snapshot["nodes"]
        closed = [n for n in nodes if n["closed"]]
        self.assertEqual(len(closed), 1)
        self.assertEqual(closed[0]["memory"], "wrote answer")
        self.assertEqual(record.grade_calls_during_run, 0)

    def test_next_closes_and_opens_sibling(self):
        client = ListModelClient(trace(
            {"spine_open": {"goal": "A"}},
            {"spine_next": {"memory": "memA", "goal": "B"}},
            {"command": "echo hello > answer.txt"},
            {"spine_close": {"memory": "memB"}},
            {"final": "done"},
        ))
        agent = build_spine_reimpl(client)
        record, grade = run_task(self.benchmark, agent, self.task, self.config)
        self.assertTrue(grade.valid, grade.detail)
        self.assertTrue(grade.passed, grade.detail)
        self.assertEqual(agent.native.spine_actions["spine_next"], 1)
        self.assertEqual(agent.native.spine_actions["spine_close"], 1)
        memories = [n["memory"] for n in agent.native.tree_snapshot["nodes"]
                    if n["closed"]]
        self.assertEqual(memories, ["memA", "memB"])

    def test_root_cannot_close(self):
        client = ListModelClient(trace(
            {"spine_close": {"memory": "bad"}},
            {"spine_open": {"goal": "A"}},
            {"command": "echo hello > answer.txt"},
            {"spine_close": {"memory": "memA"}},
            {"final": "done"},
        ))
        agent = build_spine_reimpl(client)
        record, grade = run_task(self.benchmark, agent, self.task, self.config)
        self.assertTrue(grade.valid, grade.detail)
        self.assertTrue(grade.passed, grade.detail)
        self.assertEqual(agent.native.spine_actions["spine_close"], 1)
        self.assertEqual(agent.native.tree_snapshot["active"], "1")

    def test_spawn_is_recognized_but_not_executed(self):
        client = ListModelClient(trace(
            {"spine_spawn": {"tasks": [{"goal": "A"}, {"goal": "B"}]}},
            {"spine_open": {"goal": "A"}},
            {"command": "echo hello > answer.txt"},
            {"spine_close": {"memory": "memA"}},
            {"final": "done"},
        ))
        agent = build_spine_reimpl(client)
        record, grade = run_task(self.benchmark, agent, self.task, self.config)
        self.assertTrue(grade.valid, grade.detail)
        self.assertTrue(grade.passed, grade.detail)
        self.assertEqual(agent.native.spine_actions["spine_spawn_unsupported"], 1)


if __name__ == "__main__":
    unittest.main()
