"""Verify that the adapter layer runs without benchmark reproduction tests.

This is the single command for the current milestone: run the adapter contract
suite, refresh the 32-combination matrix and readiness report, and write a
small verification record.  It deliberately does not run TB/LHTB/CORE/MLE
task tests.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[1]
OUT = ROOT / "results" / "adapter-verification.json"


def _run(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(args, cwd=str(REPO), capture_output=True, text=True)


def main() -> int:
    matrix_proc = _run([sys.executable, "experiments/adapters/export_matrix.py"])
    preflight_proc = _run([sys.executable, "experiments/adapters/preflight.py"])
    test_proc = _run([
        sys.executable, "-m", "unittest", "discover",
        "-s", "experiments/adapters/tests", "-t", "experiments/adapters",
    ])
    combined = (test_proc.stdout or "") + (test_proc.stderr or "")
    lines = [line for line in combined.strip().splitlines() if line.strip()]
    matrix = json.loads(
        (ROOT / "results" / "adapter-matrix.json").read_text(encoding="utf-8"))
    readiness = json.loads(
        (ROOT / "results" / "adapter-readiness.json").read_text(encoding="utf-8"))
    contract_ok = (
        len(matrix) == 32
        and all(row.get("completion") for row in matrix)
        and all(not row.get("hidden_test_access") for row in matrix)
        and all(row.get("grade_calls_during_run") == 0 for row in matrix)
    )
    tests_ok = test_proc.returncode == 0
    payload = {
        "tests": {
            "returncode": test_proc.returncode,
            "ok": tests_ok,
            "tail": lines[-3:],
        },
        "contract_matrix": {
            "rows": len(matrix),
            "ok": contract_ok,
        },
        "readiness": {
            "rows": len(readiness),
            "contract_ready": sum(1 for row in readiness if row["contract_ready"]),
            "real_ready": sum(1 for row in readiness if row["real_ready"]),
        },
        "non_interference": [
            "adapter maps actions/observations only; no add/drop/reorder",
            "same model, token budget, tools and grading for every method",
            "TaskSpec metadata has no checks/answers/gold/tests",
            "Host exposes no checks/answers/gold/hidden_tests",
            "submit guard is off by default; strict submission is opt-in",
            "Spine reimplementation is separated from the official plugin",
        ],
        "benchmark_reproduction_tests": (
            "not run; this milestone verifies adapter execution only"),
        "matrix_refresh_rc": matrix_proc.returncode,
        "preflight_refresh_rc": preflight_proc.returncode,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")
    print(f"tests: {'OK' if tests_ok else 'FAILED'} "
          f"({payload['tests']['tail']})")
    print(f"contract matrix: {len(matrix)} rows, ok={contract_ok}")
    print(f"readiness: contract_ready={payload['readiness']['contract_ready']}"
          f"/{len(readiness)}, real_ready={payload['readiness']['real_ready']}")
    print(f"wrote {OUT}")
    return 0 if tests_ok and contract_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
