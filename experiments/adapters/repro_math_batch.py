"""Two-phase formal-math batch runner.

Formal grading loads the whole Mathlib environment and needs about 5.5 GB of
free commit charge; the resident 9B server leaves about 1 GB.  Restarting the
server for every task would dominate a long run, so this runner separates the
two phases:

``collect``
    Run every (task, method) with the model server up.  After each episode the
    edited Lean file is copied to ``solution.lean`` and the pristine file is
    kept as ``pristine.lean``.  No Lean compilation happens here.

``grade``
    Stop the server once (``--release-model``), replay each ``solution.lean``
    into the project, grade it, restore the pristine file, and restart the
    server after the whole batch.

The runner is resumable: a run with ``solution.lean`` is not collected again,
and a run with ``grading/result.json`` is not graded again.

Usage:
    python experiments/adapters/repro_math_batch.py \
        experiments/adapters/protocols/math-batch-smoke.json --phase all \
        --release-model
    python experiments/adapters/repro_math_batch.py \
        experiments/adapters/protocols/math-batch-smoke.json --phase grade
    python experiments/adapters/repro_math_batch.py \
        experiments/adapters/protocols/math-batch-smoke.json --status
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[1]
sys.path.insert(0, str(ROOT))

from agents.base_react import HTTPModelClient
from benchmarks.content import PutnamBenchAdapter
from benchmarks.formal_math import MiniF2FAdapter, ProofNetAdapter
from context_policy import ContextManagedModelClient, ContextPolicyConfig
from contract.types import ExperimentConfig, Grade
from recording import (
    LoopDetected, RecordingHost, RecordingModelClient, TrajectoryRecorder,
)
from repro_math_pilot import (
    build_agent, health, release_model, restore_model,
)
from repro_matrix import termination_reason


def _resolve(path: str | Path) -> Path:
    path = Path(path)
    return path if path.is_absolute() else REPO / path


def build_adapter(spec: dict, protocol: dict):
    name = spec["name"]
    if name == "putnam":
        cfg = protocol.get("putnam", {})
        return PutnamBenchAdapter(
            root=_resolve(cfg.get("root", ".cache/upstream/putnambench")),
            limit=int(spec.get("limit", cfg.get("limit", 20))))
    project = _resolve(protocol.get(
        "formal_project", ".cache/upstream/putnambench/lean4"))
    if name == "minif2f":
        cfg = protocol.get("minif2f", {})
        return MiniF2FAdapter(
            project=project, split=spec.get("split", cfg.get("split", "Test")),
            limit=int(spec.get("limit", cfg.get("limit", 20))))
    if name == "proofnet":
        cfg = protocol.get("proofnet", {})
        return ProofNetAdapter(
            project=project,
            textbook=spec.get("textbook", cfg.get("textbook")),
            limit=int(spec.get("limit", cfg.get("limit", 20))))
    raise SystemExit(f"unknown math benchmark {name}")


def collect_tasks(adapters: dict, protocol: dict) -> dict:
    """Map benchmark -> {task_id: TaskSpec}, honouring explicit tasks."""
    mapping = {}
    explicit = protocol.get("tasks", [])
    for name, adapter in adapters.items():
        loaded = {task.task_id: task for task in adapter.load_tasks()}
        if explicit:
            wanted = [item["task_id"] for item in explicit
                      if item["benchmark"] == name]
            mapping[name] = {task_id: loaded[task_id]
                             for task_id in wanted if task_id in loaded}
        else:
            mapping[name] = loaded
    missing = [item for item in explicit
               if item["task_id"] not in mapping.get(item["benchmark"], {})]
    if missing:
        raise SystemExit(f"unknown tasks: {missing}")
    return mapping


def _client(protocol: dict, recorder: TrajectoryRecorder, deadline: float):
    raw = HTTPModelClient(
        protocol["model_url"], protocol["model"], timeout=300,
        temperature=protocol.get("temperature", 0.2),
        max_tokens=protocol["max_tokens_per_step"])
    use_context = protocol.get("context_management", "shared") != "none"
    managed = None
    if use_context:
        policy = ContextPolicyConfig(**protocol.get("context_policy", {}))
        managed = ContextManagedModelClient(
            raw, policy, event=recorder.event,
            prompt_equivalent_divisor=float(
                protocol.get("prompt_equivalent_divisor", 65.0)),
            equivalent_budget=protocol.get("equivalent_budget"))
    return RecordingModelClient(
        managed if managed is not None else raw, recorder, deadline=deadline,
        log_full_messages=bool(protocol.get("log_full_messages", False)))


def collect_one(adapter, benchmark: str, task, method: str, protocol: dict,
                run_dir: Path, wall_clock_sec: int, fresh: bool) -> str:
    solution = run_dir / "solution.lean"
    result = run_dir / "agent-result.json"
    if not fresh and solution.is_file() and result.is_file():
        return "collected"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "task.json").write_text(json.dumps({
        "benchmark": benchmark, "task_id": task.task_id,
        "instruction": task.instruction, "metadata": task.metadata,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    config = ExperimentConfig(
        token_budget=protocol["token_budget"],
        max_actions=protocol["max_steps"] + 2)
    host = adapter.make_host(task, config)
    source = adapter.source_path(task)
    pristine = source.read_bytes()
    (run_dir / "pristine.lean").write_bytes(pristine)
    recorder = TrajectoryRecorder(
        run_dir / "trajectory.jsonl", heartbeat=run_dir / "heartbeat.json")
    started = time.time()
    agent_error = ""
    termination = "unknown"
    recording_host = RecordingHost(host, recorder, max_identical=5)
    try:
        client = _client(protocol, recorder,
                         deadline=started + wall_clock_sec)
        agent = build_agent(method, client, protocol["max_steps"])
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
        if source.is_file():
            shutil.copy2(source, solution)
        payload = {
            "benchmark": benchmark, "task_id": task.task_id,
            "method": method, "termination": termination,
            "agent_error": agent_error,
            "last_error": (getattr(agent, "last_error", "") or "")[:2000],
            "agent_seconds": round(seconds, 1),
            "tokens": host.tokens_used, "actions": len(host.actions),
            "submitted": recording_host.submitted,
            "solution": str(solution.relative_to(REPO)).replace("\\", "/"),
        }
        (run_dir / "agent-result.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8")
        return "new"
    finally:
        recorder.close()
        host.cleanup()


def grade_one(adapter, benchmark: str, task, method: str,
              run_dir: Path) -> str:
    result_path = run_dir / "grading" / "result.json"
    if result_path.is_file():
        return "graded"
    solution = run_dir / "solution.lean"
    pristine = run_dir / "pristine.lean"
    if not solution.is_file() or not pristine.is_file():
        return "missing"
    source = adapter.source_path(task)
    source.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copy2(pristine, source)
        shutil.copy2(solution, source)
        host = SimpleNamespace(workspace=adapter.project, last_score=None,
                               tokens_used=0, actions=[])
        try:
            grade = adapter.grade(task, host)
        except Exception as exc:
            grade = Grade(
                valid=False, passed=False, checks_passed=0, checks_total=0,
                detail=f"grading error: {type(exc).__name__}: {exc}")
    finally:
        # Leave the project pristine for the next task.
        try:
            shutil.copy2(pristine, source)
        except OSError:
            pass
    (run_dir / "grading").mkdir(exist_ok=True)
    result_path.write_text(json.dumps({
        "valid": grade.valid, "passed": grade.passed,
        "checks_passed": grade.checks_passed,
        "checks_total": grade.checks_total,
        "detail": grade.detail,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return "new"


def summarize(protocol: dict, raw_root: Path, task_map: dict) -> list:
    rows = []
    for benchmark, tasks in task_map.items():
        for task_id, task in tasks.items():
            for method in protocol["methods"]:
                run_dir = raw_root / protocol["round"] / benchmark / task_id / method
                agent = None
                grade = None
                if (run_dir / "agent-result.json").is_file():
                    agent = json.loads((run_dir / "agent-result.json").read_text(
                        encoding="utf-8"))
                if (run_dir / "grading" / "result.json").is_file():
                    grade = json.loads((run_dir / "grading" / "result.json").read_text(
                        encoding="utf-8"))
                rows.append({
                    "benchmark": benchmark, "task_id": task_id,
                    "method": method,
                    "collected": agent is not None,
                    "graded": grade is not None,
                    "termination": (agent or {}).get("termination"),
                    "tokens": (agent or {}).get("tokens"),
                    "actions": (agent or {}).get("actions"),
                    "agent_seconds": (agent or {}).get("agent_seconds"),
                    "valid": (grade or {}).get("valid"),
                    "passed": (grade or {}).get("passed"),
                    "checks": (f"{(grade or {}).get('checks_passed')}/"
                               f"{(grade or {}).get('checks_total')}"
                               if grade else None),
                    "detail_tail": ((grade or {}).get("detail") or "")[-600:],
                    "run_dir": str(run_dir.relative_to(REPO)).replace("\\", "/"),
                })
    return rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("protocol")
    parser.add_argument("--phase", choices=("collect", "grade", "all"),
                        default="all")
    parser.add_argument("--release-model", action="store_true",
                        help="stop the local server for the grade phase and "
                             "restart it afterwards")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--fresh", action="store_true",
                        help="re-collect even when solution.lean exists")
    args = parser.parse_args()

    protocol = json.loads(Path(args.protocol).read_text(encoding="utf-8"))
    out_dir = _resolve(protocol["output_dir"])
    raw_root = _resolve(protocol["raw_dir"])
    out_dir.mkdir(parents=True, exist_ok=True)
    raw_root.mkdir(parents=True, exist_ok=True)
    specs = protocol.get("benchmarks", [])
    adapters = {spec["name"]: build_adapter(spec, protocol) for spec in specs}
    task_map = collect_tasks(adapters, protocol)

    if args.status:
        rows = summarize(protocol, raw_root, task_map)
        print(f"collected {sum(1 for r in rows if r['collected'])}/{len(rows)}, "
              f"graded {sum(1 for r in rows if r['graded'])}/{len(rows)}")
        for row in rows:
            print(f"{row['benchmark']:10} {row['task_id']:34} "
                  f"{row['method']:12} collected={row['collected']} "
                  f"graded={row['graded']} checks={row['checks']}")
        return 0

    if args.phase in ("collect", "all"):
        if not health(protocol["model_url"]):
            print(f"model endpoint not healthy: {protocol['model_url']}")
            return 1
        for benchmark, tasks in task_map.items():
            for task_id, task in tasks.items():
                for method in protocol["methods"]:
                    run_dir = (raw_root / protocol["round"] / benchmark
                               / task_id / method)
                    wall_clock = int(protocol["wall_clock_sec"])
                    status = collect_one(
                        adapters[benchmark], benchmark, task, method, protocol,
                        run_dir, wall_clock, args.fresh)
                    print(f"collect {benchmark}/{task_id}/{method}: {status}",
                          flush=True)

    if args.phase in ("grade", "all"):
        release_info = None
        restore_info = None
        cfg = protocol.get("grading_model_release", {})
        try:
            if args.release_model:
                release_info = release_model(
                    protocol["model_url"], float(cfg.get("min_free_commit_gb", 6.0)),
                    int(cfg.get("wait_sec", 90)))
                print(f"released model: {release_info}", flush=True)
            for benchmark, tasks in task_map.items():
                for task_id, task in tasks.items():
                    for method in protocol["methods"]:
                        run_dir = (raw_root / protocol["round"] / benchmark
                                   / task_id / method)
                        status = grade_one(
                            adapters[benchmark], benchmark, task, method, run_dir)
                        print(f"grade {benchmark}/{task_id}/{method}: {status}",
                              flush=True)
        finally:
            if args.release_model and restore_info is None:
                restore_info = restore_model(
                    cfg, protocol["model_url"],
                    int(cfg.get("health_timeout_sec", 240)))
                print(f"restored model: {restore_info}", flush=True)

    rows = summarize(protocol, raw_root, task_map)
    (out_dir / "summary.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    collected = sum(1 for row in rows if row["collected"])
    graded = sum(1 for row in rows if row["graded"])
    passed = sum(1 for row in rows if row["passed"])
    print(f"wrote {out_dir / 'summary.json'}: "
          f"{len(rows)} runs, {collected} collected, {graded} graded, "
          f"{passed} passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
