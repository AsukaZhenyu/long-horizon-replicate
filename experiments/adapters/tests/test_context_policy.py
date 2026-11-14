"""Shared context policy: bounds the prompt without touching method logic."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agents.base_react import (
    BaseReactAgent, ModelClient, ModelRequestError, ModelResponse,
)
from benchmarks.manifest import ManifestBenchmarkAdapter
from context_policy import (
    ContextManagedModelClient, ContextPolicyConfig, compile_view,
    estimate_tokens,
)
from contract.types import ExperimentConfig

MANIFEST = [{
    "task_id": "hello",
    "instruction": "Write answer.txt containing hello.",
    "initial_files": {},
    "checks": {"answer.txt": "hello"},
}]


class FixedClient(ModelClient):
    def __init__(self, responses):
        self.responses = list(responses)
        self.seen = []

    def complete(self, messages, **kwargs):
        self.seen.append(messages)
        if self.responses:
            return self.responses.pop(0)
        return ModelResponse('{"final":"done"}', total_tokens=50)


def conversation(pairs: int, observation_chars: int = 150):
    messages = [
        {"role": "system", "content": "SYS"},
        {"role": "user", "content": "TASK"},
    ]
    for index in range(pairs):
        messages.append({
            "role": "assistant",
            "content": json.dumps({"command": f"echo {index}"}),
        })
        messages.append({
            "role": "user",
            "content": "exit=0 " + ("x" * observation_chars),
        })
    return messages


class ContextPolicyTests(unittest.TestCase):
    def test_no_compaction_under_trigger(self):
        config = ContextPolicyConfig(window_tokens=1000)
        messages = conversation(1, observation_chars=10)
        view, estimate, stats = compile_view(messages, config)
        self.assertIsNone(stats)
        self.assertEqual(view, [
            {"role": "system", "content": "SYS"},
            {"role": "user", "content": "TASK"},
            {"role": "assistant", "content": '{"command": "echo 0"}'},
            {"role": "user", "content": "exit=0 " + ("x" * 10)},
        ])
        self.assertLess(estimate, config.trigger_tokens)

    def test_compaction_preserves_system_task_and_recent(self):
        config = ContextPolicyConfig(
            window_tokens=1000, trigger_ratio=0.5, target_ratio=0.3,
            keep_recent_messages=4, max_message_chars=200,
            summary_chars=300, min_messages_to_compact=4)
        messages = conversation(20)
        view, _, stats = compile_view(messages, config)
        self.assertIsNotNone(stats)
        self.assertGreater(stats.dropped_messages, 0)
        self.assertEqual(view[0], {"role": "system", "content": "SYS"})
        self.assertEqual(view[1], {"role": "user", "content": "TASK"})
        self.assertTrue(view[2]["content"].startswith("[compacted history]"))
        self.assertGreaterEqual(stats.kept_recent, 2)
        self.assertEqual(view[3:], messages[-stats.kept_recent:])
        self.assertEqual(len(view), 3 + stats.kept_recent)

    def test_digest_is_deterministic(self):
        config = ContextPolicyConfig(
            window_tokens=800, trigger_ratio=0.5, target_ratio=0.3,
            keep_recent_messages=4, max_message_chars=200,
            summary_chars=250)
        messages = conversation(15)
        first, _, _ = compile_view(messages, config)
        second, _, _ = compile_view(messages, config)
        self.assertEqual(json.dumps(first, sort_keys=True),
                         json.dumps(second, sort_keys=True))

    def test_task_instruction_not_capped_by_message_limit(self):
        config = ContextPolicyConfig(
            window_tokens=100000, max_message_chars=200,
            max_task_chars=10000)
        task = "T" * 5000
        messages = [
            {"role": "system", "content": "SYS"},
            {"role": "user", "content": task},
            {"role": "assistant", "content": '{"command": "ls"}'},
            {"role": "user", "content": "exit=0"},
        ]
        view, _, stats = compile_view(messages, config)
        self.assertIsNone(stats)
        self.assertEqual(view[1]["content"], task)

    def test_long_observation_is_truncated(self):
        config = ContextPolicyConfig(
            window_tokens=100000, max_message_chars=500)
        messages = conversation(1, observation_chars=10000)
        view, _, _ = compile_view(messages, config)
        observation = view[-1]["content"]
        self.assertLessEqual(len(observation), 500)
        self.assertIn("chars omitted", observation)

    def test_client_raises_when_prompt_cannot_be_reduced(self):
        config = ContextPolicyConfig(window_tokens=200)
        client = ContextManagedModelClient(FixedClient([]), config)
        messages = [
            {"role": "system", "content": "S" * 1000},
            {"role": "user", "content": "T" * 1000},
        ]
        with self.assertRaises(ModelRequestError):
            client.complete(messages)

    def test_client_emits_events_and_calibrates(self):
        events = []
        config = ContextPolicyConfig(
            window_tokens=1000, trigger_ratio=0.5, target_ratio=0.3,
            keep_recent_messages=4, max_message_chars=300,
            summary_chars=300)
        inner = FixedClient([
            ModelResponse('{"command": "ls"}', total_tokens=140,
                          prompt_tokens=120, completion_tokens=20),
        ])
        client = ContextManagedModelClient(
            inner, config, event=lambda kind, **fields: events.append((kind, fields)))
        messages = conversation(20)
        client.complete(messages)
        kinds = [kind for kind, _ in events]
        self.assertIn("context_compact", kinds)
        self.assertIn("model_request_sent", kinds)
        self.assertEqual(client.compactions, 1)
        self.assertEqual(client.max_prompt_tokens, 120)
        self.assertEqual(client.last_prompt_tokens, 120)
        self.assertNotEqual(client.chars_per_token, config.chars_per_token)
        self.assertLess(len(inner.seen[0]), len(messages))
        stats = client.stats()
        self.assertEqual(stats["prompt_tokens_total"], 120)
        self.assertEqual(stats["completion_tokens"], 20)
        self.assertAlmostEqual(stats["equivalent_tokens"],
                               round(120 / 65.0 + 20, 1))
        self.assertEqual(stats["prompt_equivalent_divisor"], 65.0)

    def test_base_react_runs_through_managed_client(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest = Path(tmp) / "manifest.json"
            manifest.write_text(json.dumps(MANIFEST), encoding="utf-8")
            benchmark = ManifestBenchmarkAdapter(manifest)
            task = benchmark.load_tasks()[0]
            host = benchmark.make_host(
                task, ExperimentConfig(token_budget=100000, max_actions=30))
            responses = [
                ModelResponse('{"command": "echo step %d"}' % index, 50)
                for index in range(12)
            ]
            managed = ContextManagedModelClient(
                FixedClient(responses),
                ContextPolicyConfig(
                    window_tokens=400, trigger_ratio=0.6, target_ratio=0.4,
                    keep_recent_messages=4, max_message_chars=200,
                    summary_chars=200, min_messages_to_compact=2))
            try:
                BaseReactAgent(managed, max_steps=12).run(task, host)
            finally:
                host.cleanup()
            self.assertGreater(managed.compactions, 0)
            self.assertGreater(len(host.actions), 0)

    def test_message_cap_forces_compaction_even_when_tokens_are_low(self):
        config = ContextPolicyConfig(
            window_tokens=100000, trigger_ratio=0.9, target_ratio=0.5,
            keep_recent_messages=4, max_messages_before_compact=10,
            max_message_chars=200, summary_chars=200,
            min_messages_to_compact=2)
        messages = conversation(9, observation_chars=10)
        view, _, stats = compile_view(messages, config)
        self.assertIsNotNone(stats)
        self.assertEqual(stats.kept_recent, 4)
        self.assertEqual(len(view), 1 + 1 + 1 + 4)  # system, task, digest, recent
        self.assertLess(len(view), len(messages))

    def test_equivalent_budget_stops_the_client(self):
        client = ContextManagedModelClient(
            FixedClient([
                ModelResponse('{"final":"x"}', total_tokens=200,
                              prompt_tokens=130, completion_tokens=10),
            ]),
            prompt_equivalent_divisor=65.0, equivalent_budget=10.0)
        with self.assertRaises(ModelRequestError):
            client.complete([{"role": "user", "content": "hi"}])
        self.assertGreater(client.equivalent_tokens, 10.0)

    def test_config_rejects_bad_ratios(self):
        with self.assertRaises(ValueError):
            ContextPolicyConfig(trigger_ratio=1.2)
        with self.assertRaises(ValueError):
            ContextPolicyConfig(trigger_ratio=0.5, target_ratio=0.6)
        with self.assertRaises(ValueError):
            ContextPolicyConfig(keep_recent_messages=1)
        with self.assertRaises(ValueError):
            ContextPolicyConfig(keep_recent_messages=8,
                                max_messages_before_compact=8)


if __name__ == "__main__":
    unittest.main()
