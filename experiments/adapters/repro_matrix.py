"""Protocol-driven four-benchmark matrix runner.

One protocol freezes benchmarks, tasks, methods, model, budgets and the shared
context policy.  Raw trajectories stay under the ignored cache; the runner
writes a small digest per run, an append-only ledger (resume-safe) and a
matrix summary.  Claude (or a human) only needs the digests, never the raw
trajectory.

The runner is resumable: a completed ``(round, benchmark, task, method)`` is
skipped on the next invocation.  A crashed run is retried; its old partial
directory is archived first.

Usage:
    python experiments/adapters/repro_matrix.py protocols/coverage-1m.json
    python experiments/adapters/repro_matrix.py protocols/coverage-1m.json --status
    python experiments/adapters/repro_matrix.py protocols/coverage-1m.json --workers 2
    python experiments/adapters/repro_matrix.py protocols/coverage-1m.json --no-context
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import threading
import time
import traceback
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[1]
sys.path.insert(0, str(ROOT))

from agents.base_react import BaseReactAgent, HTTPModelClient
from agents.recuris import RecurisAgent
from agents.rrsi import RRSIPromptAgent
from agents.sentry import SentryAgent
from benchmarks.core import CoreBenchAdapter
from benchmarks.lhtb import LHTBBenchmarkAdapter
from benchmarks.content import (
    AIMEAdapter, ChartMimicAdapter, ChartQAAdapter, DeckBenchAdapter,
    ECHOAdapter, MATH500Adapter, OfficeEditBenchAdapter, Paper2PosterAdapter,
    PPTEvalAdapter, PutnamBenchAdapter,
)
from benchmarks.metr_public import MetrPublicTaskAdapter
from benchmarks.mle import MLEBenchAdapter
from benchmarks.mle_grading import accuracy_metric
from benchmarks.tb import TerminalBench21Adapter
from context_policy import ContextManagedModelClient, ContextPolicyConfig
from contract.types import ExperimentConfig, Grade
from recording import (
    LoopDetected, RecordingHost, RecordingModelClient, TrajectoryRecorder,
)

CONTEXT_ERROR = re.compile(
    r"context|n_ctx|prompt is too long|too many tokens|"
    r"exceed[s]?.*(?:context|window)|input is too long|KV cache|"
    r"maximum context",
    re.IGNORECASE,
)


# --------------------------------------------------------------------- server
def health(url: str) -> bool:
    try:
        with urllib.request.urlopen(url.rstrip("/") + "/health", timeout=5) as response:
            return response.status == 200
    except Exception:
        return False


def server_context_window(url: str) -> Optional[int]:
    """Read llama-server's configured n_ctx, if it reports one."""
    try:
        with urllib.request.urlopen(url.rstrip("/") + "/v1/models", timeout=5) as response:
            data = json.loads(response.read().decode("utf-8"))
        for item in data.get("data", []):
            meta = item.get("meta") or {}
            if meta.get("n_ctx"):
                return int(meta["n_ctx"])
    except Exception:
        return None
    return None


# --------------------------------------------------------------- construction
def _resolve(path: str | Path) -> Path:
    path = Path(path)
    return path if path.is_absolute() else REPO / path


def build_adapters(protocol: Dict[str, Any]) -> Dict[str, Any]:
    adapters: Dict[str, Any] = {}
    enforce = bool(protocol.get("submit_guard", False))
    for name in protocol["benchmarks"]:
        if name == "tb21":
            adapters[name] = TerminalBench21Adapter()
        elif name == "lhtb2":
            adapters[name] = LHTBBenchmarkAdapter(
                subdir=protocol.get("lhtb_subdir", "tasks"))
        elif name == "core":
            cfg = protocol.get("core", {})
            adapters[name] = CoreBenchAdapter(
                dataset=_resolve(cfg.get(
                    "dataset",
                    ".cache/upstream/core-bench/benchmark/dataset/core_test.json")),
                level=cfg.get("level", "codeocean_easy"),
                image=cfg.get("image", "alpine:latest"),
                download=bool(cfg.get("download", True)),
                enforce_submission=enforce,
            )
        elif name == "office_edit":
            cfg = protocol.get("office_edit", {})
            adapters[name] = OfficeEditBenchAdapter(
                root=_resolve(cfg.get(
                    "root", ".cache/upstream/officeeditbench")),
                level=cfg.get("level", "easy"),
                limit=int(cfg.get("limit", 20)),
            )
        elif name == "chartqa":
            cfg = protocol.get("chartqa", {})
            adapters[name] = ChartQAAdapter(
                root=_resolve(cfg.get(
                    "root", ".cache/upstream/chartqa/ChartQA Dataset")),
                split=cfg.get("split", "test"),
                source=cfg.get("source", "test_human"),
                limit=int(cfg.get("limit", 20)),
            )
        elif name == "chartmimic":
            cfg = protocol.get("chartmimic", {})
            adapters[name] = ChartMimicAdapter(
                data_root=(_resolve(cfg["data_root"])
                           if cfg.get("data_root") else None),
                limit=int(cfg.get("limit", 1)),
                vlm_url=protocol["model_url"],
                vlm_model=protocol["model"],
            )
        elif name == "ppteval":
            adapters[name] = PPTEvalAdapter(
                vlm_url=protocol["model_url"], vlm_model=protocol["model"])
        elif name == "paper2poster":
            adapters[name] = Paper2PosterAdapter(
                vlm_url=protocol["model_url"], vlm_model=protocol["model"])
        elif name == "deckbench":
            adapters[name] = DeckBenchAdapter(
                vlm_url=protocol["model_url"], vlm_model=protocol["model"])
        elif name == "echo":
            adapters[name] = ECHOAdapter(
                vlm_url=protocol["model_url"], vlm_model=protocol["model"])
        elif name == "putnam":
            cfg = protocol.get("putnam", {})
            adapters[name] = PutnamBenchAdapter(
                root=_resolve(cfg.get("root", ".cache/upstream/putnambench")),
                limit=int(cfg.get("limit", 20)),
            )
        elif name in ("math500", "aime"):
            cfg = protocol.get(name, {})
            cls = MATH500Adapter if name == "math500" else AIMEAdapter
            adapters[name] = cls(
                path=(_resolve(cfg["path"]) if cfg.get("path") else None),
                limit=int(cfg.get("limit", 20)),
            )
        elif name == "cowthello":
            cfg = protocol.get("cowthello", {})
            adapters[name] = MetrPublicTaskAdapter(
                image=cfg.get("image",
                              "metrevals/public-tasks:cowthello-2.0.2"),
                variant=cfg.get("variant", "main_smooth"),
                timeout=int(cfg.get("timeout", 900)),
            )
        elif name == "mle":
            # The synthetic competition is rebuilt once; it needs no Kaggle
            # credentials and exercises the same adapter/host/grader chain.
            from repro_mle_synthetic import build_root
            data_dir = build_root()
            cfg = protocol.get("mle", {})
            adapters[name] = MLEBenchAdapter(
                root=_resolve(cfg.get("root", ".cache/adapters/mle-synthetic")),
                split=cfg.get("split", "all"),
                data_dir=data_dir,
                image=cfg.get("image", "alpine:latest"),
                metric=accuracy_metric,
                enforce_submission=enforce,
            )
        else:
            raise SystemExit(f"unknown benchmark {name}")
    return adapters


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


# --------------------------------------------------------------- termination
def termination_reason(agent, recording_host, started: float,
                       wall_clock_sec: int, token_budget: int) -> str:
    if recording_host.loop_detected:
        return "loop"
    last_error = getattr(agent, "last_error", "") or ""
    if "equivalent token budget" in last_error:
        return "timeout_equivalent"
    if "token budget exceeded" in last_error:
        return "timeout_tokens"
    if CONTEXT_ERROR.search(last_error):
        return "context_overflow"
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


# --------------------------------------------------------------------- ledger
class Ledger:
    """Append-only run ledger; the source of truth for resume."""

    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def done_keys(self) -> set:
        keys = set()
        if not self.path.is_file():
            return keys
        for line in self.path.read_text(encoding="utf-8").splitlines():
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if record.get("status") == "done":
                keys.add(record.get("key", ""))
        return keys

    def append(self, record: Dict[str, Any]) -> None:
        with self._lock:
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def ledger_key(round_name: str, benchmark: str, task_id: str,
               method: str) -> str:
    return f"{round_name}|{benchmark}|{task_id}|{method}"


# ------------------------------------------------------------------- one run
def _archive_partial(run_dir: Path) -> None:
    if run_dir.exists() and any(run_dir.iterdir()):
        archived = run_dir.with_name(
            f"{run_dir.name}.partial-{int(time.time())}")
        run_dir.rename(archived)


def run_one(adapters: Dict[str, Any], protocol: Dict[str, Any],
            benchmark: str, task, method: str, wall_clock_sec: int,
            raw_root: Path, policy_config: ContextPolicyConfig,
            loop_max_identical: int, use_context: bool
            ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    run_dir = raw_root / protocol["round"] / benchmark / task.task_id / method
    _archive_partial(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    equivalent_divisor = float(protocol.get("prompt_equivalent_divisor", 65.0))
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
        "context_management": "shared" if use_context else "none",
        "context_policy": policy_config.as_dict() if use_context else None,
        "loop_max_identical": loop_max_identical,
        "log_full_messages": bool(protocol.get("log_full_messages", True)),
        "prompt_equivalent_divisor": equivalent_divisor,
        "equivalent_budget": protocol.get("equivalent_budget"),
        "benchmark_config": protocol.get(benchmark, {}),
        "scoring_deviation": (
            "cowthello official extract_metrics zero-time guard "
            "(0/0 -> 1.0, non-zero/0 -> inf)"
            if benchmark == "cowthello" else ""),
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    recorder = TrajectoryRecorder(run_dir / "trajectory.jsonl",
                                  heartbeat=run_dir / "heartbeat.json")
    raw_client = HTTPModelClient(
        protocol["model_url"], protocol["model"], timeout=300,
        temperature=protocol.get("temperature", 0.2),
        max_tokens=protocol["max_tokens_per_step"],
    )
    managed: Optional[ContextManagedModelClient] = None
    if use_context:
        managed = ContextManagedModelClient(
            raw_client, policy_config, event=recorder.event,
            prompt_equivalent_divisor=equivalent_divisor,
            equivalent_budget=protocol.get("equivalent_budget"))
    client = RecordingModelClient(
        managed if managed is not None else raw_client,
        recorder,
        deadline=time.time() + wall_clock_sec,
        log_full_messages=bool(protocol.get("log_full_messages", True)),
    )
    config = ExperimentConfig(
        token_budget=protocol["token_budget"],
        max_actions=protocol["max_steps"] + 2,
    )

    host = None
    agent = None
    started = time.time()
    agent_error = ""
    termination = "unknown"
    try:
        host = adapters[benchmark].make_host(task, config)
        recording_host = RecordingHost(
            host, recorder, max_identical=loop_max_identical)
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
        try:
            grade = adapters[benchmark].grade(task, host)
        except Exception as exc:
            grade = Grade(
                valid=False, passed=False, checks_passed=0, checks_total=0,
                detail=f"grading error: {type(exc).__name__}: {exc}")

        official_score = getattr(host, "last_score", None)
        vlm_tokens = int(getattr(host, "vision_tokens", 0) or 0)
        context_stats = managed.stats() if managed is not None else {
            "compactions": 0, "max_prompt_tokens": 0,
            "last_prompt_tokens": 0, "prompt_tokens_total": 0,
            "completion_tokens": 0, "total_tokens": 0,
            "equivalent_tokens": 0.0,
            "equivalent_budget": protocol.get("equivalent_budget"),
            "prompt_equivalent_divisor": equivalent_divisor,
            "chars_per_token": 0.0, "prompt_tokens": [], "policy": None,
        }
        result = {
            "benchmark": benchmark,
            "task_id": task.task_id,
            "method": method,
            "termination": termination,
            "wall_clock_sec": wall_clock_sec,
            "agent_error": agent_error,
            "last_error": (getattr(agent, "last_error", "") or "")[:4000],
            "agent_seconds": round(seconds, 1),
            "tokens": host.tokens_used,
            "actions": len(host.actions),
            "submitted": recording_host.submitted,
            "grade_valid": grade.valid,
            "grade_passed": grade.passed,
            "checks_passed": grade.checks_passed,
            "checks_total": grade.checks_total,
            "official_score": official_score,
            "vlm_tokens": vlm_tokens,
            "context": context_stats,
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
        digest = {
            "key": ledger_key(protocol["round"], benchmark, task.task_id, method),
            "benchmark": benchmark,
            "task_id": task.task_id,
            "method": method,
            "termination": termination,
            "tokens": host.tokens_used,
            "actions": len(host.actions),
            "submitted": recording_host.submitted,
            "grade": {
                "valid": grade.valid, "passed": grade.passed,
                "checks": f"{grade.checks_passed}/{grade.checks_total}",
            },
            "official_score": official_score,
            "vlm_tokens": vlm_tokens,
            "context": {
                "compactions": context_stats.get("compactions", 0),
                "max_prompt_tokens": context_stats.get("max_prompt_tokens", 0),
                "prompt_tokens_total": context_stats.get(
                    "prompt_tokens_total", 0),
                "completion_tokens": context_stats.get("completion_tokens", 0),
                "equivalent_tokens": context_stats.get(
                    "equivalent_tokens", 0.0),
                "equivalent_budget": context_stats.get("equivalent_budget"),
            },
            "agent_seconds": round(seconds, 1),
            "last_error": (getattr(agent, "last_error", "") or "")[:300],
            "detail_tail": grade.detail[-600:],
            "run_dir": str(run_dir.relative_to(REPO)).replace("\\", "/"),
        }
        (run_dir / "digest.json").write_text(
            json.dumps(digest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8")
        return result, digest
    finally:
        if host is not None:
            host.cleanup()
        recorder.close()


# -------------------------------------------------------------------- matrix
def build_matrix(protocol: Dict[str, Any],
                 digests: List[Dict[str, Any]]) -> Dict[str, Any]:
    by_key = {(item["benchmark"], item["method"]): item for item in digests}
    rows = []
    for task in protocol["tasks"]:
        for method in protocol["methods"]:
            item = by_key.get((task["benchmark"], method))
            if item is None:
                rows.append({
                    "benchmark": task["benchmark"],
                    "task_id": task["task_id"],
                    "method": method,
                    "status": "missing",
                })
                continue
            rows.append({
                "benchmark": task["benchmark"],
                "task_id": task["task_id"],
                "method": method,
                "status": "ok" if item["grade"]["valid"] else "invalid",
                "termination": item["termination"],
                "tokens": item["tokens"],
                "generated_tokens": item["context"].get("completion_tokens", 0),
                "equivalent_tokens": item["context"].get(
                    "equivalent_tokens", 0.0),
                "actions": item["actions"],
                "checks": item["grade"]["checks"],
                "passed": item["grade"]["passed"],
                "official_score": item.get("official_score"),
                "compactions": item["context"]["compactions"],
                "max_prompt_tokens": item["context"]["max_prompt_tokens"],
                "agent_seconds": item["agent_seconds"],
            })
    return {
        "round": protocol["round"],
        "purpose": protocol.get("purpose", ""),
        "model": protocol["model"],
        "token_budget": protocol["token_budget"],
        "context_management": protocol.get("context_management", "shared"),
        "methods": list(protocol["methods"]),
        "rows": rows,
    }


def print_matrix(matrix: Dict[str, Any]) -> None:
    print(f"{'benchmark':10} {'method':13} {'term':16} {'tokens':>9} "
          f"{'gen':>7} {'equiv':>9} {'act':>4} {'checks':>7} {'score':>8} "
          f"{'compact':>7} {'maxprompt':>9}")
    for row in matrix["rows"]:
        if row["status"] == "missing":
            print(f"{row['benchmark']:10} {row['method']:13} {'(missing)':16}")
            continue
        score = row.get("official_score")
        score_text = "-" if score is None else f"{score:.4f}"
        generated = row.get("generated_tokens")
        generated_text = "-" if generated is None else f"{generated:,}"
        equivalent = row.get("equivalent_tokens")
        equivalent_text = "-" if equivalent is None else f"{equivalent:,.0f}"
        print(f"{row['benchmark']:10} {row['method']:13} "
              f"{row['termination']:16} {row['tokens']:>9,} "
              f"{generated_text:>7} {equivalent_text:>9} "
              f"{row['actions']:>4} {row['checks']:>7} "
              f"{score_text:>8} {row['compactions']:>7} "
              f"{row['max_prompt_tokens']:>9}")


def status(output_dir: Path, raw_root: Path, protocol: Dict[str, Any]) -> int:
    summary_path = output_dir / "summary.json"
    run_root = raw_root / protocol["round"]
    digests: List[Dict[str, Any]] = []
    if summary_path.is_file():
        digests = json.loads(summary_path.read_text(encoding="utf-8"))
    if not digests and run_root.is_dir():
        # Mid-batch: the summary is written only at the end, so read the
        # per-run digests that are already complete.
        for path in sorted(run_root.glob("*/*/*/digest.json")):
            try:
                digests.append(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError):
                continue
    if digests:
        print_matrix(build_matrix(protocol, digests))
    else:
        print("no completed runs yet")
    if run_root.is_dir():
        done: set = set()
        ledger_path = output_dir / "run-ledger.jsonl"
        if ledger_path.is_file():
            for line in ledger_path.read_text(encoding="utf-8").splitlines():
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if record.get("status") == "done":
                    done.add(record.get("key", ""))
        now = time.time()
        for heartbeat in sorted(run_root.rglob("heartbeat.json")):
            try:
                data = json.loads(heartbeat.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            rel = heartbeat.parent.relative_to(run_root)
            if any(".partial-" in part for part in rel.parts):
                continue
            key = "|".join([protocol["round"], *rel.parts])
            if key in done:
                continue
            age = now - float(data.get("at", 0))
            print(f"heartbeat {rel}: step={data.get('step')} "
                  f"age={age:.0f}s kind={data.get('kind')}")
    return 0


# ---------------------------------------------------------------------- main
def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("protocol")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--fresh", action="store_true",
                        help="ignore the ledger and rerun completed keys")
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--only", default="",
                        help="comma-separated substring filter, e.g. tb21 or "
                             "tb21/base,lhtb2")
    parser.add_argument("--no-context", action="store_true",
                        help="ablation: run without the shared context policy")
    args = parser.parse_args()

    protocol = json.loads(Path(args.protocol).read_text(encoding="utf-8"))
    output_dir = _resolve(protocol["output_dir"])
    raw_root = _resolve(protocol["raw_dir"])
    if args.status:
        return status(output_dir, raw_root, protocol)

    if not health(protocol["model_url"]):
        print(f"model endpoint not healthy: {protocol['model_url']}")
        return 1
    policy_config = ContextPolicyConfig(**protocol.get("context_policy", {}))
    server_window = server_context_window(protocol["model_url"])
    use_context = not args.no_context
    if use_context:
        print(f"context policy: window={policy_config.window_tokens} "
              f"trigger={policy_config.trigger_tokens} "
              f"target={policy_config.target_tokens}")
        if server_window is not None and server_window != policy_config.window_tokens:
            print(f"warning: server n_ctx={server_window} but policy "
                  f"window={policy_config.window_tokens}")
            if protocol.get("require_window_match", False):
                return 2
    else:
        print("context policy: disabled (native ablation)")

    adapters = build_adapters(protocol)
    output_dir.mkdir(parents=True, exist_ok=True)
    raw_root.mkdir(parents=True, exist_ok=True)
    ledger = Ledger(output_dir / "run-ledger.jsonl")
    done = set() if args.fresh else ledger.done_keys()

    only = [part.strip() for part in args.only.split(",") if part.strip()]
    task_maps = {
        name: {task.task_id: task for task in adapter.load_tasks()}
        for name, adapter in adapters.items()
    }
    if not protocol.get("tasks") and protocol.get("discover", False):
        protocol["tasks"] = [
            {"benchmark": name, "task_id": task_id}
            for name, task_map in task_maps.items()
            for task_id in task_map
        ]
        print(f"discovered {len(protocol['tasks'])} tasks")
    jobs = []
    for item in protocol["tasks"]:
        benchmark = item["benchmark"]
        task_id = item["task_id"]
        if task_id not in task_maps[benchmark]:
            raise SystemExit(f"unknown task {benchmark}/{task_id}")
        for method in protocol["methods"]:
            key = ledger_key(protocol["round"], benchmark, task_id, method)
            if only and not any(part in key for part in only):
                continue
            if key in done:
                print(f"skip done {key}")
                continue
            jobs.append((key, benchmark, task_maps[benchmark][task_id],
                         method, int(item.get("wall_clock_sec",
                                              protocol["wall_clock_sec"]))))
    print(f"{len(jobs)} runs to execute")

    digests: Dict[str, Dict[str, Any]] = {}
    failures: List[Dict[str, Any]] = []
    loop_max = int(protocol.get("loop_max_identical", 5))
    # CORE prepares one environment directory per task, so methods must not
    # run against the same task concurrently.  Different tasks may overlap.
    task_locks: Dict[Tuple[str, str], threading.Lock] = {}

    def task_lock(benchmark: str, task_id: str) -> threading.Lock:
        return task_locks.setdefault((benchmark, task_id), threading.Lock())

    def execute(job):
        key, benchmark, task, method, wall_clock = job
        ledger.append({"key": key, "status": "started", "at": time.time()})
        print(f"run {key}", flush=True)
        try:
            # PutnamBench edits one shared Lean project in place, so all of its
            # tasks must serialize on a single lock even when --workers > 1.
            lock_id = "__project__" if benchmark == "putnam" else task.task_id
            with task_lock(benchmark, lock_id):
                _, digest = run_one(
                    adapters, protocol, benchmark, task, method, wall_clock,
                    raw_root, policy_config, loop_max, use_context)
        except Exception as exc:
            record = {
                "key": key, "status": "failed",
                "error": f"{type(exc).__name__}: {exc}",
                "traceback": traceback.format_exc()[-2000:],
                "at": time.time(),
            }
            ledger.append(record)
            failures.append(record)
            print(f"FAILED {key}: {record['error']}", flush=True)
            return key, None
        ledger.append({
            "key": key, "status": "done", "at": time.time(),
            "termination": digest["termination"],
            "tokens": digest["tokens"],
            "checks": digest["grade"]["checks"],
            "passed": digest["grade"]["passed"],
            "run_dir": digest["run_dir"],
        })
        print(json.dumps({
            "key": key, "termination": digest["termination"],
            "tokens": digest["tokens"],
            "checks": digest["grade"]["checks"],
            "compactions": digest["context"]["compactions"],
        }, ensure_ascii=False), flush=True)
        return key, digest

    if args.workers <= 1:
        for job in jobs:
            key, digest = execute(job)
            if digest is not None:
                digests[key] = digest
    else:
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = [pool.submit(execute, job) for job in jobs]
            for future in as_completed(futures):
                key, digest = future.result()
                if digest is not None:
                    digests[key] = digest

    # Merge with previously completed digests so --only/--fresh stays coherent.
    summary = []
    for item in protocol["tasks"]:
        for method in protocol["methods"]:
            key = ledger_key(protocol["round"], item["benchmark"],
                             item["task_id"], method)
            if key in digests:
                summary.append(digests[key])
                continue
            existing = (raw_root / protocol["round"] / item["benchmark"]
                        / item["task_id"] / method / "digest.json")
            if existing.is_file():
                summary.append(json.loads(existing.read_text(encoding="utf-8")))
    (output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    matrix = build_matrix(protocol, summary)
    (output_dir / "matrix.json").write_text(
        json.dumps(matrix, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    print_matrix(matrix)
    print(f"wrote {output_dir / 'summary.json'} ({len(summary)} runs), "
          f"{len(failures)} failed")
    return 0 if not failures else 3


if __name__ == "__main__":
    raise SystemExit(main())
