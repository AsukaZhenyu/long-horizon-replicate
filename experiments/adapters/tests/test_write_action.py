"""Harness v2: the uniform write action reaches the host for every method."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agents.base_react import (
    ACTION_PROTOCOL, BaseReactAgent, ModelClient, ModelResponse, parse_action,
    write_action,
)
from agents.sentry import ACTION_SCHEMA
from benchmarks.content import LocalContentHost
from contract.types import Action, ExperimentConfig, TaskSpec


class _ScriptedClient(ModelClient):
    def __init__(self, responses):
        self.responses = list(responses)

    def complete(self, messages, **kwargs):
        return self.responses.pop(0)


class WriteActionTests(unittest.TestCase):
    def config(self) -> ExperimentConfig:
        return ExperimentConfig(token_budget=1000, max_actions=5)

    def test_write_action_mapping(self):
        action = write_action({"path": "src/a.lean", "content": "theorem a : True := by trivial"})
        self.assertIsNotNone(action)
        self.assertEqual(action.kind, "write")
        self.assertEqual(action.payload["path"], "src/a.lean")
        self.assertIsNone(write_action({"command": "ls"}))
        self.assertIsNone(write_action({"final": "done"}))

    def test_prompts_advertise_write(self):
        self.assertIn('"path"', ACTION_PROTOCOL)
        self.assertIn('"path"', ACTION_SCHEMA)

    def test_fenced_write_parse(self):
        text = ('{"path": "src/a.lean"}\n```lean\n'
                'theorem a : True := by trivial\n```')
        action = parse_action(text)
        self.assertEqual(action["path"], "src/a.lean")
        self.assertEqual(action["content"],
                         "theorem a : True := by trivial\n")

    def test_base_agent_writes_and_submits(self):
        with tempfile.TemporaryDirectory() as tmp:
            task = TaskSpec(task_id="write-test", benchmark="test",
                            instruction="write answer.txt")
            host = LocalContentHost(task, self.config(), Path(tmp),
                                    install_tools=False)
            client = _ScriptedClient([
                ModelResponse(content=(
                    '{"path": "answer.txt"}\n```text\n5\n```'),
                    total_tokens=8),
                ModelResponse(content='{"final": "done"}', total_tokens=8),
            ])
            BaseReactAgent(client, max_steps=2).run(task, host)
            self.assertEqual((Path(tmp) / "answer.txt").read_text().strip(), "5")
            self.assertTrue(host.submitted)
            host.cleanup()


if __name__ == "__main__":
    unittest.main()
