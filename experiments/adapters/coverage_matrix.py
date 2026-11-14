"""Summarize the four-benchmark x four-method coverage pilot.

The point is execution coverage: every implemented method must reach a valid
grade on every benchmark.  Passing the task is recorded separately.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[1]
SMOKE = REPO / ".cache" / "adapters" / "real-smoke"
OUT = ROOT / "results" / "method-benchmark-coverage.json"
METHODS = ("base", "sentry", "recuris-gate", "rrsi")
BENCHMARKS = ("tb21", "lhtb2", "core", "mle")
TASKS = {
    "tb21": "regex-log",
    "lhtb2": "2048",
    "core": "capsule-4180912",
    "mle": "synthetic",
}
NOTES = {
    "tb21": "Terminal-Bench 2.1, real task, official test.sh",
    "lhtb2": "LHTB 2.0, real task, official test.sh",
    "core": "CORE-Bench official test split, real task, official report.json grading",
    "mle": "MLE-bench synthetic competition; real Kaggle data not available",
}


def find(benchmark: str, method: str) -> Path | None:
    if benchmark == "tb21":
        path = SMOKE / f"{method}-tb21-regex-log-coverage.json"
        if path.is_file():
            return path
        if method == "base":
            return SMOKE / "base-tb21-regex-log.json"
        return None
    if benchmark == "lhtb2":
        path = SMOKE / f"{method}-lhtb-2048-lhtb.json"
        if path.is_file():
            return path
        if method == "recuris-gate":
            return SMOKE / "recuris-lhtb-2048-lhtb.json"
        return None
    if benchmark == "core":
        return ROOT / "results" / "core-test-pilot" / f"{method}-{TASKS['core']}.json"
    if benchmark == "mle":
        return ROOT / "results" / "mle-synthetic-pilot" / f"{method}-{TASKS['mle']}.json"
    return None


def main():
    rows = []
    for benchmark in BENCHMARKS:
        for method in METHODS:
            path = find(benchmark, method)
            if path is None or not path.is_file():
                rows.append({
                    "benchmark": benchmark, "method": method,
                    "task": TASKS[benchmark], "status": "missing",
                })
                continue
            data = json.loads(path.read_text(encoding="utf-8"))
            rows.append({
                "benchmark": benchmark,
                "method": method,
                "task": data.get("task", TASKS[benchmark]),
                "status": "ok" if data.get("grade_valid") else "invalid",
                "valid": bool(data.get("grade_valid")),
                "passed": bool(data.get("grade_passed")),
                "checks": f"{data.get('checks_passed')}/{data.get('checks_total')}",
                "tokens": data.get("tokens"),
                "actions": data.get("actions"),
                "max_steps": data.get("max_steps"),
                "agent_seconds": data.get("agent_seconds"),
                "agent_error": data.get("agent_error", ""),
                "last_error": data.get("last_error", ""),
                "source": str(path.relative_to(REPO)).replace("\\", "/"),
            })
    complete = all(
        row.get("status") == "ok" and not row.get("agent_error")
        for row in rows)
    payload = {
        "purpose": "4 benchmarks x 4 implemented methods execution coverage",
        "methods": list(METHODS),
        "benchmarks": list(BENCHMARKS),
        "notes": NOTES,
        "contract_only_methods": [
            "spine (official Pi/Node plugin not bridged)",
            "openjiuwen", "lhh", "opera",
        ],
        "coverage_complete": complete,
        "valid_count": sum(1 for row in rows if row.get("status") == "ok"),
        "total": len(rows),
        "rows": rows,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")
    print(f"wrote {OUT}: valid {payload['valid_count']}/{payload['total']}")
    for row in rows:
        print(f"{row['benchmark']:6} {row['method']:12} {row.get('status','?'):8} "
              f"checks={row.get('checks','-')} tokens={row.get('tokens','-')}")
    return 0 if complete else 1


if __name__ == "__main__":
    raise SystemExit(main())
