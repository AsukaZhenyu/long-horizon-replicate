"""Run the 4 x 8 adapter matrix on mock tasks and write evidence JSON."""
from __future__ import annotations

import json
from pathlib import Path

from benchmarks.base import CoreAdapter, LHTB2Adapter, MLEAdapter, TB21Adapter, run_task
from contract.types import Action, ExperimentConfig, ScriptedAgent
from methods.adapters import METHOD_ADAPTERS

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "results" / "adapter-matrix.json"


def actions():
    return [
        Action("write", {"path": "answer.txt", "content": "hello\n"}),
        Action("write", {"path": "result.txt", "content": "42\n"}),
        Action("submit"),
    ]


def main():
    config = ExperimentConfig(token_budget=1000, max_actions=50)
    benchmarks = [TB21Adapter(), LHTB2Adapter(), CoreAdapter(), MLEAdapter()]
    rows = []
    for benchmark in benchmarks:
        task = benchmark.load_tasks()[0]
        for method_cls in METHOD_ADAPTERS:
            method = method_cls(ScriptedAgent(actions()))
            record, grade = run_task(benchmark, method, task, config)
            rows.append({
                "benchmark": benchmark.name,
                "method": method.name,
                "contract": "ok",
                "completion": record.completion,
                "grade_valid": grade.valid,
                "checks": f"{grade.checks_passed}/{grade.checks_total}",
                "tokens": record.tokens,
                "token_budget": config.token_budget,
                "hidden_test_access": record.hidden_test_access,
                "grade_calls_during_run": record.grade_calls_during_run,
                "mechanism": list(method.mechanism),
                "native_loop": "ready" if method.native_loop_ready else "pending",
            })
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(rows, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {OUT} with {len(rows)} rows")


if __name__ == "__main__":
    main()
