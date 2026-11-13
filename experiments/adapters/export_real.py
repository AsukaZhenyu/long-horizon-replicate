"""Write the real-integration evidence summary.

Combines the dataset inventory, the readiness matrix, the offline native-loop
test status, and the TB 2.1 oracle grading log into one small JSON file.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from methods.adapters import METHOD_ADAPTERS

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[1]
RESULTS = ROOT / "results"
OUT = RESULTS / "real-integration.json"


def _read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def _smoke(log_name: str, benchmark: str, task: str, kind: str,
           expected: str) -> dict:
    log = REPO / ".cache" / "adapters" / log_name
    item = {
        "benchmark": benchmark,
        "task": task,
        "kind": kind,
        "expected": expected,
        "status": "not_run",
        "source": log.relative_to(REPO).as_posix() if log.is_file() else "",
    }
    if not log.is_file():
        return item
    text = log.read_text(encoding="utf-8", errors="replace")
    match = re.search(
        r"grade valid (\w+) passed (\w+) checks (\d+) / (\d+)"
        r"(?: seconds ([\d.]+))?", text)
    if not match:
        item["status"] = "unparsed"
        return item
    valid = match.group(1) == "True"
    passed = match.group(2) == "True"
    reward = re.search(r"reward=([0-9.]+)", text)
    item.update({
        "valid": valid,
        "passed": passed,
        "checks": f"{match.group(3)}/{match.group(4)}",
        "reward": float(reward.group(1)) if reward else None,
        "status": "as_expected" if (passed == (expected == "pass")) else "unexpected",
    })
    if match.group(5):
        item["seconds"] = float(match.group(5))
    return item


def _official_smokes() -> list[dict]:
    return [
        _smoke(
            "oracle-regex-log.log", "tb21", "regex-log",
            "oracle solution, not an agent result", "pass"),
        _smoke(
            "lhtb-2048-smoke.log", "lhtb2", "2048",
            "blank submission (no moves), official verifier failure path", "fail"),
    ]


def _test_status():
    log = REPO / ".cache" / "adapters" / "test-output.txt"
    item = {"status": "not_run", "tests": None}
    if not log.is_file():
        return item
    text = log.read_text(encoding="utf-8", errors="replace")
    match = re.search(r"Ran (\d+) tests? in [\d.]+s\s*\n\s*(OK|FAILED)", text)
    if match:
        item.update({"tests": int(match.group(1)),
                     "status": "passed" if match.group(2) == "OK" else "failed"})
    return item


def main():
    datasets = _read_json(RESULTS / "adapter-datasets.json", [])
    readiness = _read_json(RESULTS / "adapter-readiness.json", [])
    methods = []
    for cls in METHOD_ADAPTERS:
        method = cls.__new__(cls)
        methods.append({
            "method": method.name,
            "native_loop_ready": method.native_loop_ready,
            "mechanism": list(method.mechanism),
        })
    real_ready = sum(1 for row in readiness if row.get("real_ready"))
    payload = {
        "contract_ready": f"{len(readiness)}/{len(readiness)}" if readiness else "0/0",
        "real_ready": f"{real_ready}/{len(readiness)}" if readiness else "0/0",
        "real_ready_note": "no model endpoint configured in this offline round",
        "datasets": datasets,
        "methods": methods,
        "offline_tests": _test_status(),
        "official_grading_smoke": _official_smokes(),
    }
    OUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
                   encoding="utf-8")
    print(f"wrote {OUT}")
    print(json.dumps({k: payload[k] for k in
                      ("contract_ready", "real_ready", "offline_tests",
                       "official_grading_smoke")},
                     indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
