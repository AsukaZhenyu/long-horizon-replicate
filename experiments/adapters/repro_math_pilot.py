"""Run the PutnamBench math pilot and grade with the model server released.

Formal grading loads the whole Mathlib environment (about 5.5 GB of commit
charge on this host).  The resident 9B server consumes most of the remaining
commit, so ``lake env lean`` fails on a random ``.olean.private`` read unless
the server is stopped first.  This runner makes that deployment step explicit:

* the agent runs with the normal local server;
* ``--release-model`` stops ``llama`` and waits for commit headroom;
* the adapter grades the Lean file;
* the server is restarted from the protocol's start script and health-checked.

``--grade-only`` re-grades the current Lean project without running an agent,
which is useful after a crashed or interrupted episode.

Usage:
    python experiments/adapters/repro_math_pilot.py \
        experiments/adapters/protocols/math-smoke.json --release-model
    python experiments/adapters/repro_math_pilot.py \
        experiments/adapters/protocols/math-smoke.json --grade-only --release-model
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[1]
sys.path.insert(0, str(ROOT))

from agents.base_react import BaseReactAgent, HTTPModelClient
from agents.recuris import RecurisAgent
from agents.rrsi import RRSIPromptAgent
from agents.sentry import SentryAgent
from benchmarks.content import PutnamBenchAdapter, _free_commit_gb
from contract.types import ExperimentConfig, Grade
from recording import RecordingHost, TrajectoryRecorder


def health(url: str) -> bool:
    try:
        with urllib.request.urlopen(url.rstrip("/") + "/health", timeout=5) as response:
            return response.status == 200
    except Exception:
        return False


def _resolve(path: str | Path) -> Path:
    path = Path(path)
    return path if path.is_absolute() else REPO / path


def _local(url: str) -> bool:
    return any(host in url for host in ("127.0.0.1", "localhost", "::1"))


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
    if method == "spine-reimpl":
        from agents.spine import SpineAgent
        return SpineAgent(client, max_steps=max_steps)
    raise SystemExit(f"unknown method {method}")


def release_model(url: str, min_free_gb: float, wait_sec: int) -> dict:
    """Stop the local llama server and wait for Lean grading headroom."""
    if not _local(url):
        raise SystemExit("--release-model only supports a local model server")
    before = _free_commit_gb()
    proc = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "Get-Process llama -ErrorAction SilentlyContinue | Stop-Process -Force"],
        capture_output=True, encoding="utf-8", errors="replace", timeout=120)
    started = time.time()
    free = before
    while time.time() - started < wait_sec:
        free = _free_commit_gb()
        if free is not None and free >= min_free_gb:
            break
        time.sleep(2)
    return {
        "released": True,
        "stopped_rc": proc.returncode,
        "before_gb": round(before, 2) if before is not None else None,
        "after_gb": round(free, 2) if free is not None else None,
        "waited_sec": round(time.time() - started, 1),
        "enough": bool(free is not None and free >= min_free_gb),
    }


def restore_model(config: dict, url: str, timeout_sec: int) -> dict:
    """Restart the local model server from the protocol's start script."""
    script = _resolve(config["restart_script"])
    args = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
            "-File", str(script)] + [str(arg) for arg in config.get(
                "restart_args", [])]
    proc = subprocess.Popen(args, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)
    started = time.time()
    ready = False
    while time.time() - started < timeout_sec:
        if health(url):
            ready = True
            break
        time.sleep(2)
    return {
        "restarted": True,
        "ready": ready,
        "waited_sec": round(time.time() - started, 1),
        "pid": proc.pid,
    }


def run_one(adapter: PutnamBenchAdapter, task, method: str, protocol: dict,
            raw_root: Path, release: bool, grade_only: bool) -> dict:
    run_dir = raw_root / protocol["round"] / "putnam" / task.task_id / method
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "task.json").write_text(json.dumps({
        "benchmark": "putnam", "task_id": task.task_id,
        "instruction": task.instruction, "metadata": task.metadata,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    config = ExperimentConfig(
        token_budget=protocol["token_budget"],
        max_actions=protocol["max_steps"] + 2,
    )
    recorder = TrajectoryRecorder(run_dir / "trajectory.jsonl")
    agent_error = ""
    termination = "grade_only"
    seconds = 0.0
    host = None
    try:
        if grade_only:
            host = SimpleNamespace(workspace=adapter.project, last_score=None,
                                   actions=[], tokens_used=0)
        else:
            host = adapter.make_host(task, config)
            client = HTTPModelClient(
                protocol["model_url"], protocol["model"], timeout=300,
                temperature=protocol.get("temperature", 0.2),
                max_tokens=protocol["max_tokens_per_step"],
            )
            recording_host = RecordingHost(host, recorder, max_identical=5)
            agent = build_agent(method, client, protocol["max_steps"])
            started = time.time()
            try:
                agent.run(task, recording_host)
                termination = ("submitted" if recording_host.submitted
                               else "max_steps")
            except Exception as exc:
                agent_error = f"{type(exc).__name__}: {exc}"
                termination = "crash"
            seconds = time.time() - started

        release_info = None
        restore_info = None
        cfg = protocol["grading_model_release"]
        try:
            if release:
                release_info = release_model(
                    protocol["model_url"], float(cfg["min_free_commit_gb"]),
                    int(cfg["wait_sec"]))
            try:
                grade = adapter.grade(task, host)
            except Exception as exc:
                grade = Grade(
                    valid=False, passed=False, checks_passed=0,
                    checks_total=0,
                    detail=f"grading error: {type(exc).__name__}: {exc}")
        finally:
            # Never leave the user's model server stopped.
            if release:
                restore_info = restore_model(
                    cfg, protocol["model_url"],
                    int(cfg["health_timeout_sec"]))

        payload = {
            "benchmark": "putnam",
            "task": task.task_id,
            "method": method,
            "termination": termination,
            "agent_error": agent_error,
            "agent_seconds": round(seconds, 1),
            "tokens": int(getattr(host, "tokens_used", 0) or 0),
            "actions": len(getattr(host, "actions", []) or []),
            "grade_valid": grade.valid,
            "grade_passed": grade.passed,
            "checks_passed": grade.checks_passed,
            "checks_total": grade.checks_total,
            "detail": grade.detail[-4000:],
            "model_release": release_info,
            "model_restore": restore_info,
        }
        (run_dir / "agent-result.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8")
        (run_dir / "grading").mkdir(exist_ok=True)
        (run_dir / "grading" / "result.json").write_text(
            json.dumps({
                "valid": grade.valid, "passed": grade.passed,
                "checks_passed": grade.checks_passed,
                "checks_total": grade.checks_total,
                "detail": grade.detail,
            }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return payload
    finally:
        recorder.close()
        if host is not None and not grade_only:
            cleanup = getattr(host, "cleanup", None)
            if callable(cleanup):
                cleanup()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("protocol")
    parser.add_argument("--release-model", action="store_true",
                        help="stop the local server before Lean grading and "
                             "restart it afterwards")
    parser.add_argument("--grade-only", action="store_true",
                        help="grade the current Lean project without an agent")
    args = parser.parse_args()

    protocol = json.loads(Path(args.protocol).read_text(encoding="utf-8"))
    if not args.grade_only and not health(protocol["model_url"]):
        print(f"model endpoint not healthy: {protocol['model_url']}")
        return 1
    out_dir = REPO / protocol["output_dir"]
    raw_root = REPO / protocol["raw_dir"]
    out_dir.mkdir(parents=True, exist_ok=True)
    raw_root.mkdir(parents=True, exist_ok=True)
    cfg = protocol.get("putnam", {})
    adapter = PutnamBenchAdapter(
        root=_resolve(cfg.get("root", ".cache/upstream/putnambench")),
        limit=int(cfg.get("limit", 20)),
    )
    tasks = {task.task_id: task for task in adapter.load_tasks()}
    summary = []
    for item in protocol["tasks"]:
        task = tasks.get(item["task_id"])
        if task is None:
            raise SystemExit(f"unknown Putnam task {item['task_id']}")
        for method in protocol["methods"]:
            print(f"run putnam/{task.task_id}/{method}"
                  + (" (grade only)" if args.grade_only else ""), flush=True)
            result = run_one(adapter, task, method, protocol, raw_root,
                             args.release_model, args.grade_only)
            summary.append(result)
            print(json.dumps({
                "task": task.task_id, "method": method,
                "termination": result["termination"],
                "valid": result["grade_valid"],
                "passed": result["grade_passed"],
                "checks": f"{result['checks_passed']}/{result['checks_total']}",
                "tokens": result["tokens"],
                "free_after_gb": (result["model_release"] or {}).get("after_gb"),
            }, ensure_ascii=False), flush=True)
    (out_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    print(f"wrote {out_dir / 'summary.json'} with {len(summary)} runs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
