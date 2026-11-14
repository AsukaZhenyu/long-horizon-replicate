"""Trajectory recording: model/action/observation events and loop detection."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agents.base_react import ListModelClient, ModelResponse
from benchmarks.manifest import ManifestBenchmarkAdapter
from contract.types import Action, ExperimentConfig, ScriptedAgent
from recording import (
    LoopDetected, RecordingHost, RecordingModelClient, TrajectoryRecorder,
)

MANIFEST = [{
    "task_id": "hello",
    "instruction": "Write answer.txt containing hello.",
    "initial_files": {},
    "checks": {"answer.txt": "hello"},
}]


class RecordingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        manifest = Path(self.tmp.name) / "manifest.json"
        manifest.write_text(json.dumps(MANIFEST), encoding="utf-8")
        self.benchmark = ManifestBenchmarkAdapter(manifest)
        self.task = self.benchmark.load_tasks()[0]
        self.config = ExperimentConfig(token_budget=1000, max_actions=20)
        self.trajectory = Path(self.tmp.name) / "trajectory.jsonl"

    def tearDown(self):
        self.tmp.cleanup()

    def events(self):
        return [json.loads(line) for line in
                self.trajectory.read_text(encoding="utf-8").splitlines()]

    def test_records_action_observation_and_submit(self):
        recorder = TrajectoryRecorder(self.trajectory)
        host = RecordingHost(
            self.benchmark.make_host(self.task, self.config), recorder)
        try:
            ScriptedAgent([
                Action("write", {"path": "answer.txt", "content": "hello"}),
                Action("submit"),
            ]).run(self.task, host)
        finally:
            host.cleanup()
        kinds = [event["kind"] for event in self.events()]
        self.assertIn("action", kinds)
        self.assertIn("observation", kinds)
        self.assertIn("submit", kinds)

    def test_model_request_and_response_are_recorded(self):
        recorder = TrajectoryRecorder(self.trajectory)
        client = RecordingModelClient(
            ListModelClient([ModelResponse('{"final":"done"}', 7)]), recorder)
        client.complete([{"role": "user", "content": "hi"}])
        kinds = [event["kind"] for event in self.events()]
        self.assertEqual(kinds, ["model_request", "model_response"])

    def test_compact_model_request_logging(self):
        recorder = TrajectoryRecorder(self.trajectory)
        client = RecordingModelClient(
            ListModelClient([ModelResponse('{"final":"done"}', 7)]), recorder,
            log_full_messages=False)
        client.complete([
            {"role": "system", "content": "SYS"},
            {"role": "user", "content": "hello"},
        ])
        request = self.events()[0]
        self.assertEqual(request["kind"], "model_request")
        self.assertNotIn("messages", request)
        self.assertEqual(request["message_count"], 2)
        self.assertEqual(request["last_role"], "user")
        self.assertEqual(request["last_head"], "hello")

    def test_identical_action_observation_detects_loop(self):
        recorder = TrajectoryRecorder(self.trajectory)
        host = RecordingHost(
            self.benchmark.make_host(self.task, self.config), recorder,
            max_identical=5)
        try:
            with self.assertRaises(LoopDetected):
                ScriptedAgent([
                    Action("shell", {"command": "echo same"})
                    for _ in range(5)
                ]).run(self.task, host)
            self.assertTrue(host.loop_detected)
            observations = [event for event in self.events()
                            if event["kind"] == "observation"]
            self.assertEqual(len(observations), 5)
        finally:
            host.cleanup()


if __name__ == "__main__":
    unittest.main()
