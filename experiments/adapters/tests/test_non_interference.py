"""Audit that the adapter does not change the method or expose hidden data."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from benchmarks.base import TB21Adapter
from benchmarks.core import DEFAULT_DATASET, CoreBenchAdapter
from benchmarks.mle import DEFAULT_ROOT, MLEBenchAdapter
from contract.types import ExperimentConfig, ScriptedAgent
from methods.adapters import METHOD_ADAPTERS

SENSITIVE = {
    "checks", "answers", "gold", "gold_results", "results", "tests",
    "hidden", "hidden_tests", "solution",
}


class NonInterferenceTests(unittest.TestCase):
    def test_core_metadata_has_no_gold_and_guard_is_off(self):
        if not DEFAULT_DATASET.is_file():
            self.skipTest("CORE-Bench checkout not present")
        adapter = CoreBenchAdapter(download=False)
        self.assertFalse(adapter.enforce_submission)
        for task in adapter.load_tasks():
            self.assertFalse(SENSITIVE & set(task.metadata), task.task_id)

    def test_mle_metadata_has_no_answers_and_guard_is_off(self):
        if not DEFAULT_ROOT.is_dir():
            self.skipTest("MLE-bench checkout not present")
        with tempfile.TemporaryDirectory() as tmp:
            adapter = MLEBenchAdapter(data_dir=Path(tmp), metric=None)
            self.assertFalse(adapter.enforce_submission)
            for task in adapter.load_tasks():
                self.assertFalse(SENSITIVE & set(task.metadata), task.task_id)

    def test_host_does_not_expose_checks(self):
        benchmark = TB21Adapter()
        task = benchmark.load_tasks()[0]
        host = benchmark.make_host(task, ExperimentConfig())
        for name in ("checks", "answers", "gold", "hidden_tests"):
            self.assertFalse(hasattr(host, name), name)

    def test_adapter_changes_are_schema_mappings_only(self):
        for cls in METHOD_ADAPTERS:
            method = cls(ScriptedAgent([]))
            for change in method.adapter_changes:
                text = change.lower()
                self.assertNotIn("prompt", text, (method.name, change))
                self.assertNotIn("strategy", text, (method.name, change))
                self.assertNotIn("plan", text, (method.name, change))


if __name__ == "__main__":
    unittest.main()
