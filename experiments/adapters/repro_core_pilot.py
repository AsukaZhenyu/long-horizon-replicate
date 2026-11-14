"""Run the CORE-Bench test-split method-reproduction pilot.

The protocol is frozen in ``protocols/core-test-pilot.json``.  The default
submit guard is off; this is the no-extra-feedback reproduction condition.
"""
from __future__ import annotations

import json
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[1]
sys.path.insert(0, str(ROOT))

from agents.base_react import BaseReactAgent, HTTPModelClient
from agents.recuris import RecurisAgent
from agents.rrsi import RRSIPromptAgent
from agents.sentry import SentryAgent
from benchmarks.core import CoreBenchAdapter
from contract.types import ExperimentConfig

PROTOCOL_PATH = ROOT / "protocols" / "core-test-pilot.json"
OUT = ROOT / "results" / "core-test-pilot"
RAW = REPO / ".cache" / "adapters" / "core-test-pilot"


def health(url: str) -> bool:
    try:
        with urllib.request.urlopen(url.rstrip("/") + "/health", timeout=5) as response:
            return response.status == 200
    except Exception:
        return False


def build_agent(method: str, client, max_steps: int):
    if method == "base":
        return BaseReactAgent(client, max_steps=max_steps)
    if method == "sentry":
        return SentryAgent(client, max_steps=max_steps)
    if method == "recuris":
        return RecurisAgent(client, completion_gate=False, max_steps=max_steps)
    if method == "recuris-gate":
        return RecurisAgent(client, completion_gate=True, max_steps=max_steps)
    if method == "rrsi":
        return RRSIPromptAgent(client, max_steps=max_steps)
    raise SystemExit(f"unknown method {method}")


def main() -> int:
    protocol = json.loads(PROTOCOL_PATH.read_text(encoding="utf-8"))
    model_url = protocol["model_url"]
    if not health(model_url):
        print(f"model endpoint not healthy: {model_url}; start llama-server first")
        return 1
    OUT.mkdir(parents=True, exist_ok=True)
    RAW.mkdir(parents=True, exist_ok=True)
    dataset_path = Path(protocol["dataset"])
    if not dataset_path.is_absolute():
        dataset_path = REPO / dataset_path
    adapter = CoreBenchAdapter(
        dataset=dataset_path,
        level=protocol["level"],
        image=protocol["image"],
        download=True,
        enforce_submission=False,
    )
    tasks = {task.task_id: task for task in adapter.load_tasks()}
    missing = [task_id for task_id in protocol["tasks"] if task_id not in tasks]
    if missing:
        raise SystemExit(f"unknown CORE tasks: {missing}")
    client = HTTPModelClient(
        model_url, protocol["model"], timeout=300,
        temperature=protocol["temperature"],
        max_tokens=protocol["max_tokens_per_step"],
    )
    config = ExperimentConfig(
        token_budget=protocol["token_budget"],
        max_actions=protocol["max_steps"] + 2,
    )
    summary = []
    for method in protocol["methods"]:
        for task_id in protocol["tasks"]:
            out_path = OUT / f"{method}-{task_id}.json"
            if out_path.is_file():
                summary.append(json.loads(out_path.read_text(encoding="utf-8")))
                print(f"skip existing {method} {task_id}", flush=True)
                continue
            task = tasks[task_id]
            agent = build_agent(method, client, protocol["max_steps"])
            host = adapter.make_host(task, config)
            started = time.time()
            try:
                agent.run(task, host)
                agent_seconds = time.time() - started
                grade = adapter.grade(task, host)
                payload = {
                    "benchmark": "core",
                    "dataset": "core_test",
                    "level": protocol["level"],
                    "method": method,
                    "task": task_id,
                    "attempt": 1,
                    "agent_seconds": round(agent_seconds, 1),
                    "tokens": host.tokens_used,
                    "actions": len(host.actions),
                    "grade_valid": grade.valid,
                    "grade_passed": grade.passed,
                    "checks_passed": grade.checks_passed,
                    "checks_total": grade.checks_total,
                    "detail": grade.detail[-2000:],
                    "action_log": [
                        {"kind": action.kind, "payload": action.payload}
                        for action in host.actions
                    ],
                }
                if hasattr(agent, "turns"):
                    payload["turns"] = agent.turns
                if hasattr(agent, "bounces"):
                    payload["bounces"] = agent.bounces
                if hasattr(agent, "phases"):
                    payload["phases"] = dict(agent.phases)
                out_path.write_text(
                    json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")
                summary.append(payload)
                print(json.dumps({
                    "method": method, "task": task_id,
                    "checks": f"{grade.checks_passed}/{grade.checks_total}",
                    "valid": grade.valid, "passed": grade.passed,
                    "tokens": host.tokens_used,
                }, ensure_ascii=False), flush=True)
            finally:
                host.cleanup()
    (OUT / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    print(f"wrote {OUT / 'summary.json'} with {len(summary)} runs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
