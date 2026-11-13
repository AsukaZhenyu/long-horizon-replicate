"""Contract, workflow-invariance and fairness tests for all adapters."""
from __future__ import annotations

import unittest

from benchmarks.base import (
    CoreAdapter, LHTB2Adapter, MLEAdapter, TB21Adapter, run_native, run_task,
)
from contract.fairness import FairnessLedger, workflow_preserved
from contract.readiness import build_matrix
from contract.types import Action, ExperimentConfig, ScriptedAgent
from methods.adapters import (
    BaseAgentAdapter, LHHAdapter, METHOD_ADAPTERS, OpenJiuwenAdapter,
    OperaAdapter, RecurisAdapter, RRSIAdapter, SentryAdapter, SpineAdapter,
)


def actions_for_task() -> list[Action]:
    return [
        Action("write", {"path": "answer.txt", "content": "hello\n"}),
        Action("write", {"path": "result.txt", "content": "42\n"}),
        Action("submit"),
    ]


class AdapterContractTests(unittest.TestCase):
    def setUp(self):
        self.config = ExperimentConfig(token_budget=1000, max_actions=50)
        self.benchmarks = [TB21Adapter(), LHTB2Adapter(), CoreAdapter(), MLEAdapter()]
        self.method_classes = [
            SentryAdapter, SpineAdapter, RecurisAdapter, RRSIAdapter,
            OpenJiuwenAdapter, LHHAdapter, OperaAdapter,
        ]

    def test_four_benchmarks_run_base_agent(self):
        for benchmark in self.benchmarks:
            tasks = benchmark.load_tasks()
            self.assertGreaterEqual(len(tasks), 2)
            base = BaseAgentAdapter(ScriptedAgent(actions_for_task()))
            for task in tasks:
                record, grade = run_task(benchmark, base, task, self.config)
                self.assertTrue(grade.valid, (benchmark.name, task.task_id))
                self.assertTrue(grade.passed, (benchmark.name, task.task_id))
                self.assertTrue(record.completion)

    def test_seven_methods_run_on_four_benchmarks(self):
        for benchmark in self.benchmarks:
            task = benchmark.load_tasks()[0]
            for method_cls in self.method_classes:
                method = method_cls(ScriptedAgent(actions_for_task()))
                record, grade = run_task(benchmark, method, task, self.config)
                self.assertTrue(record.completion, (benchmark.name, method.name))
                self.assertTrue(grade.valid)
                self.assertTrue(method.mechanism, method.name)
                self.assertTrue(method.adapter_changes, method.name)

    def test_workflow_invariance(self):
        for benchmark in self.benchmarks:
            task = benchmark.load_tasks()[0]
            native_actions, native_tokens, native_grade = run_native(
                benchmark, ScriptedAgent(actions_for_task()), task, self.config
            )
            for method_cls in self.method_classes:
                method = method_cls(ScriptedAgent(actions_for_task()))
                record, grade = run_task(benchmark, method, task, self.config)
                self.assertTrue(
                    workflow_preserved(native_actions, record.actions),
                    (benchmark.name, method.name,
                     native_actions, record.actions),
                )
                self.assertEqual(native_tokens, record.tokens)
                self.assertEqual(native_grade.passed, grade.passed)

    def test_no_hidden_test_access_and_no_grade_call(self):
        for benchmark in self.benchmarks:
            task = benchmark.load_tasks()[0]
            host = benchmark.make_host(task, self.config)
            self.assertFalse(hasattr(host, "hidden_tests"))
            method = SentryAdapter(ScriptedAgent(actions_for_task()))
            method.run(task, host)
            self.assertEqual(host.grade_calls, 0)
            record, _ = run_task(benchmark, method, task, self.config)
            self.assertEqual(record.grade_calls_during_run, 0)
            self.assertFalse(record.hidden_test_access)

    def test_same_budget_and_config(self):
        ledger = FairnessLedger()
        for benchmark in self.benchmarks:
            task = benchmark.load_tasks()[0]
            for method_cls in self.method_classes:
                method = method_cls(ScriptedAgent(actions_for_task()))
                record, _ = run_task(benchmark, method, task, self.config)
                ledger.add(record)
        self.assertTrue(ledger.same_budget(self.config))
        self.assertTrue(ledger.same_model(self.config))
        self.assertEqual(ledger.violations(self.config), [])
        self.assertTrue(all(r.tokens <= self.config.token_budget for r in ledger.records))

    def test_base_adapter_control(self):
        for benchmark in self.benchmarks:
            task = benchmark.load_tasks()[0]
            ledger = FairnessLedger()
            base = BaseAgentAdapter(ScriptedAgent(actions_for_task()))
            record, _ = run_task(benchmark, base, task, self.config)
            ledger.add(record)
            method = SentryAdapter(ScriptedAgent(actions_for_task()))
            record, _ = run_task(benchmark, method, task, self.config)
            ledger.add(record)
            self.assertEqual(ledger.base_control_delta("sentry", benchmark.name), 0.0)

    def test_matrix_complete(self):
        pairs = set()
        for benchmark in self.benchmarks:
            task = benchmark.load_tasks()[0]
            for method_cls in METHOD_ADAPTERS:
                method = method_cls(ScriptedAgent(actions_for_task()))
                record, _ = run_task(benchmark, method, task, self.config)
                pairs.add((record.benchmark, record.method))
        expected = {(b.name, m.name) for b in self.benchmarks for m in
                    [c(ScriptedAgent([])) for c in METHOD_ADAPTERS]}
        self.assertEqual(pairs, expected)
        self.assertEqual(len(pairs), 4 * len(METHOD_ADAPTERS))

    def test_mechanism_declared(self):
        for method_cls in METHOD_ADAPTERS:
            method = method_cls(ScriptedAgent([]))
            if method.name == "base":
                self.assertEqual(method.mechanism, ())
            else:
                self.assertTrue(method.mechanism, method.name)

    def test_readiness_matrix_is_honest(self):
        methods = [cls(ScriptedAgent([])) for cls in METHOD_ADAPTERS]
        rows = build_matrix(self.benchmarks, methods, model_endpoint="")
        by_method = {m.name: m for m in methods}
        self.assertEqual(len(rows), 32)
        self.assertTrue(all(r.contract_ready for r in rows))
        self.assertFalse(any(r.real_ready for r in rows))
        self.assertTrue(all(r.missing for r in rows))
        self.assertTrue(all("benchmark data loader" in r.missing for r in rows))
        for row in rows:
            ready = by_method[row.method].native_loop_ready
            self.assertEqual(
                "method native loop" not in row.missing, ready,
                (row.method, row.missing),
            )
        self.assertFalse(by_method["spine"].native_loop_ready)
        self.assertFalse(by_method["openjiuwen"].native_loop_ready)
        self.assertTrue(by_method["sentry"].native_loop_ready)
        self.assertTrue(by_method["recuris"].native_loop_ready)
        self.assertTrue(by_method["rrsi"].native_loop_ready)


if __name__ == "__main__":
    unittest.main()
