"""Protocol-driven real run with full trajectory recording.

The protocol freezes benchmark tasks, methods, model and budgets.  Raw
trajectories live under the ignored cache; the small summary is written to
``results/``.  This runner is deliberately separate from the adapter tests and
does not run benchmark tests by itself.
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
from benchmarks.lhtb import LHTBBenchmarkAdapter
from benchmarks.tb import TerminalBench21Adapter
from contract.types import ExperimentConfig
from recording import (
    LoopDetected, RecordingHost, RecordingModelClient, TrajectoryRecorder,
)


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
    if method == "recuris-gate":
        return RecurisAgent(client, completion_gate=True, max_steps=max_steps)
    if method == "rrsi":
        return RRSIPromptAgent(client, max_steps=max_steps)
    if method == "spine-reimpl":
        from agents.spine import SpineAgent
        return SpineAgent(client, max_steps=max_steps)
    raise SystemExit(f"unknown method {method}")


def termination_reason(agent, recording_host, started, wall_clock_sec,
                       token_budget) -> str:
    if recording_host.loop_detected:
        return "loop"
    last_error = getattr(agent, "last_error", "")
    if "token budget exceeded" in last_error:
        return "timeout_tokens"
    if "deadline" in last_error:
        return "timeout_wall"
    if last_error:
        return "model_error"
    if recording_host.submitted:
        return "submitted"
    if time.time() - started >= wall_clock_sec:
        return "timeout_wall"
    if recording_host.tokens_used > token_budget:
        return "timeout_tokens"
    return "max_steps"


def run_one(adapter, benchmark: str, task, method: str, protocol: dict,
            raw_root: Path, wall_clock_sec: int) -> dict:
    run_dir = raw_root / protocol["round"] / benchmark / task.task_id / method
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "task.json").write_text(json.dumps({
        "benchmark": benchmark,
        "task_id": task.task_id,
        "instruction": task.instruction,
        "metadata": task.metadata,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (run_dir / "run-config.json").write_text(json.dumps({
        "round": protocol["round"],
        "benchmark": benchmark,
        "task_id": task.task_id,
        "method": method,
        "model": protocol["model"],
        "model_url": protocol["model_url"],
        "max_steps": protocol["max_steps"],
        "max_tokens_per_step": protocol["max_tokens_per_step"],
        "token_budget": protocol["token_budget"],
        "wall_clock_sec": wall_clock_sec,
        "submit_guard": protocol.get("submit_guard", False),
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    recorder = TrajectoryRecorder(run_dir / "trajectory.jsonl")
    client = RecordingModelClient(
        HTTPModelClient(
            protocol["model_url"], protocol["model"], timeout=300,
            temperature=protocol.get("temperature", 0.2),
            max_tokens=protocol["max_tokens_per_step"],
        ),
        recorder,
        deadline=time.time() + wall_clock_sec,
    )
    config = ExperimentConfig(
        token_budget=protocol["token_budget"],
        max_actions=protocol["max_steps"] + 2,
    )
    host = adapter.make_host(task, config)
    recording_host = RecordingHost(host, recorder, max_identical=5)
    agent = build_agent(method, client, protocol["max_steps"])
    started = time.time()
    agent_error = ""
    termination = "unknown"
    try:
        try:
            agent.run(task, recording_host)
        except LoopDetected:
            termination = "loop"
        except Exception as exc:
            agent_error = f"{type(exc).__name__}: {exc}"
            termination = "crash"
        if termination == "unknown":
            termination = termination_reason(
                agent, recording_host, started, wall_clock_sec,
                protocol["token_budget"])
        seconds = time.time() - started
        grade = adapter.grade(task, host)
        result = {
            "benchmark": benchmark,
            "task_id": task.task_id,
            "method": method,
            "termination": termination,
            "wall_clock_sec": wall_clock_sec,
            "agent_error": agent_error,
            "last_error": getattr(agent, "last_error", ""),
            "agent_seconds": round(seconds, 1),
            "tokens": host.tokens_used,
            "actions": len(host.actions),
            "submitted": recording_host.submitted,
            "grade_valid": grade.valid,
            "grade_passed": grade.passed,
            "checks_passed": grade.checks_passed,
            "checks_total": grade.checks_total,
            "detail": grade.detail[-2000:],
        }
        (run_dir / "agent-result.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8")
        (run_dir / "grading").mkdir(exist_ok=True)
        (run_dir / "grading" / "result.json").write_text(
            json.dumps({
                "valid": grade.valid, "passed": grade.passed,
                "checks_passed": grade.checks_passed,
                "checks_total": grade.checks_total,
                "detail": grade.detail,
            }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (run_dir / "cleanup.json").write_text(
            json.dumps({"cleaned": True}) + "\n", encoding="utf-8")
        return result
    finally:
        host.cleanup()
        recorder.close()


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: repro_runner.py <protocol.json>")
    protocol_path = Path(sys.argv[1])
    protocol = json.loads(protocol_path.read_text(encoding="utf-8"))
    if not health(protocol["model_url"]):
        print(f"model endpoint not healthy: {protocol['model_url']}")
        return 1
    output_dir = REPO / protocol["output_dir"]
    raw_root = REPO / protocol["raw_dir"]
    output_dir.mkdir(parents=True, exist_ok=True)
    adapters = {
        "tb21": TerminalBench21Adapter(),
        "lhtb2": LHTBBenchmarkAdapter(subdir="tasks"),
    }
    task_maps = {name: {task.task_id: task for task in adapter.load_tasks()}
                 for name, adapter in adapters.items()}
    summary = []
    for item in protocol["tasks"]:
        benchmark = item["benchmark"]
        task_id = item["task_id"]
        task = task_maps[benchmark].get(task_id)
        if task is None:
            raise SystemExit(f"unknown task {benchmark}/{task_id}")
        for method in protocol["methods"]:
            print(f"run {benchmark}/{task_id}/{method}", flush=True)
            wall_clock = int(item.get("wall_clock_sec",
                                      protocol["wall_clock_sec"]))
            result = run_one(adapters[benchmark], benchmark, task, method,
                             protocol, raw_root, wall_clock)
            summary.append(result)
            print(json.dumps({
                "benchmark": benchmark, "task": task_id, "method": method,
                "termination": result["termination"],
                "valid": result["grade_valid"], "passed": result["grade_passed"],
                "checks": f"{result['checks_passed']}/{result['checks_total']}",
                "tokens": result["tokens"],
            }, ensure_ascii=False), flush=True)
    (output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    print(f"wrote {output_dir / 'summary.json'} with {len(summary)} runs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
