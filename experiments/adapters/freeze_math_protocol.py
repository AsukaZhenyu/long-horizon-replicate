"""Freeze the math task sets and write runnable protocols.

The design is in ``docs/plan/Math-Experimental-Design.md``.  This script makes
its L1/L2 subsets explicit and deterministic: every protocol carries a frozen
task-id list, so a later run cannot silently pick different tasks.

Usage:
    python experiments/adapters/freeze_math_protocol.py --seed 20261115
    python experiments/adapters/freeze_math_protocol.py --seed 20261115 --check-putnam
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Callable, Iterable, List

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[1]
sys.path.insert(0, str(ROOT))

from benchmarks.content import AIMEAdapter, MATH500Adapter, PutnamBenchAdapter
from benchmarks.formal_math import MiniF2FAdapter, ProofNetAdapter

PROTOCOLS = ROOT / "protocols"
MATH500 = REPO / ".cache" / "upstream" / "math500" / "test.jsonl"
AIME = REPO / ".cache" / "upstream" / "aime" / "aime_2024.jsonl"
PUTNAM = REPO / ".cache" / "upstream" / "putnambench"
PROJECT = REPO / ".cache" / "upstream" / "putnambench" / "lean4"
METHODS = ["base", "sentry", "recuris-gate", "rrsi"]
CONTEXT = {
    "window_tokens": 16384,
    "trigger_ratio": 0.72,
    "target_ratio": 0.55,
    "keep_recent_messages": 8,
    "max_messages_before_compact": 24,
    "max_message_chars": 4000,
    "max_system_chars": 16000,
    "max_task_chars": 16000,
    "summary_chars": 2400,
    "min_messages_to_compact": 6,
    "chars_per_token": 2.0,
}


def _hash(seed: int, task_id: str) -> str:
    return hashlib.sha1(f"{seed}|{task_id}".encode("utf-8")).hexdigest()


def stratified(tasks: Iterable, stratum: Callable, count: int,
               seed: int) -> List:
    groups: dict = defaultdict(list)
    for task in tasks:
        groups[str(stratum(task))].append(task)
    for key in groups:
        groups[key].sort(key=lambda task: _hash(seed, task.task_id))
    keys = sorted(groups)
    chosen = []
    while len(chosen) < count:
        progressed = False
        for key in keys:
            if groups[key]:
                chosen.append(groups[key].pop(0))
                progressed = True
                if len(chosen) >= count:
                    break
        if not progressed:
            break
    return sorted(chosen, key=lambda task: task.task_id)


def load_sets() -> dict:
    math = MATH500Adapter(path=MATH500, limit=10000).load_tasks()
    aime = AIMEAdapter(path=AIME, limit=10000).load_tasks()
    mini_test = MiniF2FAdapter(split="Test", limit=10000).load_tasks()
    mini_valid = MiniF2FAdapter(split="Valid", limit=10000).load_tasks()
    putnam = PutnamBenchAdapter(root=PUTNAM, limit=10000).load_tasks()
    proofnet = ProofNetAdapter(limit=10000).load_tasks()
    return {
        "math500": math, "aime": aime, "minif2f_test": mini_test,
        "minif2f_valid": mini_valid, "putnam": putnam, "proofnet": proofnet,
    }


def math_stratum(task) -> tuple:
    return (task.metadata.get("subject", ""), str(task.metadata.get("level", "")))


def mini_stratum(task) -> str:
    stem = task.task_id.split("-", 1)[1] if "-" in task.task_id else task.task_id
    return stem.split("_")[0]


def putnam_stratum(task) -> str:
    year = int(task.metadata.get("year") or 0)
    bucket = ("1962-1979" if year < 1980 else "1980-1999" if year < 2000
              else "2000-2019" if year < 2020 else "2020-2025")
    return f"{bucket}-{(task.metadata.get('problem') or '')[:1]}"


def _base(round_name: str, purpose: str, output: str, raw: str,
          token_budget: int, equivalent_budget: int, max_steps: int,
          wall_clock: int, methods: List[str] | None = None) -> dict:
    return {
        "round": round_name,
        "purpose": purpose,
        "model": "qwen3.5-9b",
        "model_url": "http://127.0.0.1:8080",
        "temperature": 0.2,
        "max_tokens_per_step": 4096,
        "max_steps": max_steps,
        "token_budget": token_budget,
        "equivalent_budget": equivalent_budget,
        "wall_clock_sec": wall_clock,
        "submit_guard": False,
        "log_full_messages": False,
        "context_management": "shared",
        "context_policy": dict(CONTEXT),
        "methods": methods or list(METHODS),
        "output_dir": f"experiments/adapters/results/{output}",
        "raw_dir": f".cache/adapters/{raw}",
    }


def informal(round_name, tasks_math, tasks_aime, purpose, output, raw,
             token_budget, equivalent_budget, max_steps, wall_clock,
             methods=None) -> dict:
    protocol = _base(round_name, purpose, output, raw, token_budget,
                     equivalent_budget, max_steps, wall_clock, methods)
    protocol["benchmarks"] = ["math500", "aime"]
    protocol["discover"] = False
    protocol["tasks"] = (
        [{"benchmark": "math500", "task_id": task.task_id}
         for task in tasks_math]
        + [{"benchmark": "aime", "task_id": task.task_id}
           for task in tasks_aime])
    protocol["math500"] = {"path": str(MATH500.relative_to(REPO)).replace(
        "\\", "/"), "limit": 10000}
    protocol["aime"] = {"path": str(AIME.relative_to(REPO)).replace(
        "\\", "/"), "limit": 10000}
    return protocol


def formal(round_name, specs, tasks, purpose, output, raw, token_budget,
           equivalent_budget, max_steps, wall_clock, methods=None) -> dict:
    protocol = _base(round_name, purpose, output, raw, token_budget,
                     equivalent_budget, max_steps, wall_clock, methods)
    protocol["benchmarks"] = specs
    protocol["tasks"] = tasks
    protocol["formal_project"] = str(PROJECT.relative_to(REPO)).replace(
        "\\", "/")
    protocol["putnam"] = {
        "root": str(PUTNAM.relative_to(REPO)).replace("\\", "/"),
        "limit": 10000}
    protocol["minif2f"] = {"split": "Test", "limit": 10000}
    protocol["proofnet"] = {"limit": 10000}
    return protocol


def write(protocol: dict) -> Path:
    # The round includes the date; keep a stable file name for the frozen set.
    path = PROTOCOLS / (protocol["round"].replace("20261115-", "") + ".json")
    path.write_text(json.dumps(protocol, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")
    return path


def check_putnam(tasks, seed: int) -> None:
    """Compile the selected Putnam files with their original `sorry`."""
    import os
    import subprocess

    adapter = PutnamBenchAdapter(root=PUTNAM, limit=10000)
    lake = adapter._lake()
    if lake is None:
        raise SystemExit("Lean toolchain not found for --check-putnam")
    env = os.environ.copy()
    env["PATH"] = str(lake.parent) + os.pathsep + env.get("PATH", "")
    failures = []
    for index, task in enumerate(tasks, 1):
        rel = f"src/{task.metadata['file']}"
        proc = subprocess.run(
            [str(lake), "env", "lean", rel], cwd=str(adapter.project),
            env=env, capture_output=True, text=True, errors="replace",
            timeout=600)
        ok = proc.returncode == 0
        if not ok:
            failures.append((task.task_id,
                             (proc.stdout or proc.stderr or "")[-300:]))
        print(f"[{index}/{len(tasks)}] {task.task_id} rc={proc.returncode}",
              flush=True)
    if failures:
        print("Putnam precheck failures:")
        for task_id, detail in failures:
            print(f"  {task_id}: {detail.replace(chr(10), ' | ')}")
    else:
        print("Putnam precheck: all selected tasks compile with sorry")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=20261115)
    parser.add_argument("--check-putnam", action="store_true")
    args = parser.parse_args()
    sets = load_sets()
    seed = args.seed

    math50 = stratified(sets["math500"], math_stratum, 50, seed)
    aime30 = sets["aime"]
    mini50 = stratified(sets["minif2f_test"], mini_stratum, 50, seed)
    mini_valid50 = stratified(sets["minif2f_valid"], mini_stratum, 50, seed)
    putnam100 = stratified(sets["putnam"], putnam_stratum, 100, seed)
    proofnet66 = sets["proofnet"]

    # L1 main gate.
    write(informal(
        "20261115-math-l1-informal", math50, aime30,
        "L1 gate: 50 MATH-500 + 30 AIME 2024, 30k E",
        "math-l1-informal", "math-l1-informal",
        100000, 30000, 60, 1800))
    write(formal(
        "20261115-math-l1-formal",
        [{"name": "minif2f", "split": "Test", "limit": 10000}],
        [{"benchmark": "minif2f", "task_id": task.task_id}
         for task in mini50],
        "L1 gate: 50 miniF2F Test, 30k E",
        "math-l1-formal", "math-l1-formal",
        100000, 30000, 60, 1800))
    write(formal(
        "20261115-math-l1-valid",
        [{"name": "minif2f", "split": "Valid", "limit": 10000}],
        [{"benchmark": "minif2f", "task_id": task.task_id}
         for task in mini_valid50],
        "L1 reliability: 50 miniF2F Valid, 30k E",
        "math-l1-valid", "math-l1-valid",
        100000, 30000, 60, 1800,
        methods=["base", "recuris-gate", "rrsi"]))

    # L2 calibration and main.
    cal_putnam = stratified(putnam100, putnam_stratum, 20, seed)
    cal_proofnet = stratified(proofnet66, lambda t: t.metadata["textbook"],
                              20, seed)
    write(formal(
        "20261115-math-l2-calibration",
        [{"name": "putnam", "limit": 10000},
         {"name": "proofnet", "limit": 10000}],
        [{"benchmark": "putnam", "task_id": task.task_id}
         for task in cal_putnam]
        + [{"benchmark": "proofnet", "task_id": task.task_id}
           for task in cal_proofnet],
        "L2 calibration: 20 Putnam + 20 ProofNet at 50k E",
        "math-l2-calibration", "math-l2-calibration",
        250000, 50000, 120, 3600,
        methods=["base", "recuris-gate"]))
    write(formal(
        "20261115-math-l2",
        [{"name": "putnam", "limit": 10000},
         {"name": "proofnet", "limit": 10000}],
        [{"benchmark": "putnam", "task_id": task.task_id}
         for task in putnam100]
        + [{"benchmark": "proofnet", "task_id": task.task_id}
           for task in proofnet66],
        "L2 main: 100 Putnam + 66 ProofNet, 100k E",
        "math-l2", "math-l2",
        500000, 100000, 200, 7200))
    stress = stratified(putnam100, putnam_stratum, 10, seed)
    write(formal(
        "20261115-math-l2-stress",
        [{"name": "putnam", "limit": 10000}],
        [{"benchmark": "putnam", "task_id": task.task_id}
         for task in stress],
        "L2 stress: 10 Putnam, 2M E / 10h",
        "math-l2-stress", "math-l2-stress",
        2000000, 2000000, 2000, 36000,
        methods=["base", "recuris-gate"]))

    # Budget scaling (50 L1 tasks; 40 L2 tasks).
    scale_math = stratified(math50, math_stratum, 20, seed)
    scale_aime = stratified(aime30, mini_stratum, 10, seed)
    scale_mini = stratified(mini50, mini_stratum, 20, seed)
    for label, e_budget, raw in (("5k", 5000, 30000),
                                 ("15k", 15000, 60000),
                                 ("30k", 30000, 100000)):
        write(informal(
            f"20261115-math-l1-scale-informal-{label}",
            scale_math, scale_aime,
            f"L1 scaling: 20 MATH + 10 AIME at {e_budget} E",
            f"math-l1-scale-informal-{label}",
            f"math-l1-scale-informal-{label}",
            raw, e_budget, 60, 1800,
            methods=["base", "recuris-gate", "rrsi"]))
        write(formal(
            f"20261115-math-l1-scale-formal-{label}",
            [{"name": "minif2f", "split": "Test", "limit": 10000}],
            [{"benchmark": "minif2f", "task_id": task.task_id}
             for task in scale_mini],
            f"L1 formal scaling: 20 miniF2F at {e_budget} E",
            f"math-l1-scale-formal-{label}",
            f"math-l1-scale-formal-{label}",
            raw, e_budget, 60, 1800,
            methods=["base", "recuris-gate", "rrsi"]))
    scale_putnam = stratified(putnam100, putnam_stratum, 20, seed)
    scale_proofnet = stratified(proofnet66, lambda t: t.metadata["textbook"],
                                20, seed)
    for label, e_budget, raw in (("25k", 25000, 125000),
                                 ("50k", 50000, 250000),
                                 ("100k", 100000, 500000)):
        write(formal(
            f"20261115-math-l2-scale-{label}",
            [{"name": "putnam", "limit": 10000},
             {"name": "proofnet", "limit": 10000}],
            [{"benchmark": "putnam", "task_id": task.task_id}
             for task in scale_putnam]
            + [{"benchmark": "proofnet", "task_id": task.task_id}
               for task in scale_proofnet],
            f"L2 scaling: 20 Putnam + 20 ProofNet at {e_budget} E",
            f"math-l2-scale-{label}", f"math-l2-scale-{label}",
            raw, e_budget, 200, 7200,
            methods=["base", "recuris-gate"]))

    # 30-task reliability subset.
    rel_math = stratified(math50, math_stratum, 10, seed)
    rel_putnam = stratified(putnam100, putnam_stratum, 10, seed)
    rel_proofnet = stratified(proofnet66, lambda t: t.metadata["textbook"],
                              10, seed)
    write(informal(
        "20261115-math-reliability-informal", rel_math, [],
        "Reliability: 10 MATH-500, 3 runs planned, 30k E",
        "math-reliability-informal", "math-reliability-informal",
        100000, 30000, 60, 1800,
        methods=["base", "recuris-gate", "rrsi"]))
    write(formal(
        "20261115-math-reliability-formal",
        [{"name": "putnam", "limit": 10000},
         {"name": "proofnet", "limit": 10000}],
        [{"benchmark": "putnam", "task_id": task.task_id}
         for task in rel_putnam]
        + [{"benchmark": "proofnet", "task_id": task.task_id}
           for task in rel_proofnet],
        "Reliability: 10 Putnam + 10 ProofNet, 3 runs planned, 100k E",
        "math-reliability-formal", "math-reliability-formal",
        500000, 100000, 200, 7200,
        methods=["base", "recuris-gate", "rrsi"]))

    print(f"seed={seed} frozen task counts:")
    print(f"  MATH-500 {len(math50)}, AIME {len(aime30)}, "
          f"miniF2F Test {len(mini50)}, Valid {len(mini_valid50)}")
    print(f"  Putnam {len(putnam100)}, ProofNet {len(proofnet66)}")
    print(f"  protocols written to {PROTOCOLS}")
    if args.check_putnam:
        check_putnam(putnam100, seed)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
