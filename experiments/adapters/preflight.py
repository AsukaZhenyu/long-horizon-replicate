"""Write the 4 x 8 adapter readiness matrix.

The matrix keeps two layers separate:

* contract-ready: the adapter maps actions/observations and passes the
  fairness tests (all 32 combinations);
* real-ready: the benchmark has a public dataset loader, a real host, official
  grading, the method has a native loop, and a model endpoint is configured.

The benchmark side now uses the real TB 2.1 and LHTB 2.0 adapters when their
checkouts are present.  CORE-Bench and MLE-bench are reported as missing data
rather than silently mocked.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from benchmarks.core import (
    DEFAULT_DATASET as CORE_DATASET, DEFAULT_PROMPTS as CORE_PROMPTS,
    DEFAULT_ROOT as CORE_ROOT, CoreBenchAdapter,
)
from benchmarks.harbor import MissingDatasetAdapter
from benchmarks.lhtb import DEFAULT_ROOT as LHTB_ROOT, LHTBBenchmarkAdapter
from benchmarks.mle import MLEBenchAdapter
from benchmarks.tb import DEFAULT_ROOT as TB21_ROOT, TerminalBench21Adapter
from contract.readiness import build_matrix
from methods.adapters import METHOD_ADAPTERS

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[1]
OUT = ROOT / "results" / "adapter-readiness.json"
DATASETS_OUT = ROOT / "results" / "adapter-datasets.json"


def build_benchmarks():
    if TB21_ROOT.is_dir():
        tb = TerminalBench21Adapter()
    else:
        tb = MissingDatasetAdapter(
            "tb21", f"Terminal-Bench 2.1 checkout not present at {TB21_ROOT}")
    if (LHTB_ROOT / "tasks").is_dir():
        lhtb = LHTBBenchmarkAdapter(subdir="tasks")
    else:
        lhtb = MissingDatasetAdapter(
            "lhtb2", f"LHTB checkout not present at {LHTB_ROOT}")
    if CORE_DATASET.is_file() and CORE_PROMPTS.is_file():
        core = CoreBenchAdapter()
    else:
        core = MissingDatasetAdapter(
            "core", f"CORE-Bench checkout not present at {CORE_ROOT}")
    return [tb, lhtb, core, MLEBenchAdapter()]


def dataset_rows(benchmarks):
    rows = []
    for benchmark in benchmarks:
        item = {
            "benchmark": benchmark.name,
            "adapter": type(benchmark).__name__,
            "real_loader": benchmark.real_loader,
            "real_host": benchmark.real_host,
            "real_grader": benchmark.real_grader,
            "dataset_missing": getattr(benchmark, "dataset_missing", ""),
        }
        if isinstance(benchmark, MissingDatasetAdapter):
            item["tasks"] = 0
            item["official_tasks"] = 0
        else:
            tasks = benchmark.load_tasks()
            item["tasks"] = len(tasks)
            item["official_tasks"] = benchmark.official_task_count
            try:
                item["root"] = benchmark.root.relative_to(REPO).as_posix()
            except ValueError:
                item["root"] = benchmark.root.as_posix()
        rows.append(item)
    return rows


def main():
    benchmarks = build_benchmarks()
    methods = [cls.__new__(cls) for cls in METHOD_ADAPTERS]
    # __new__ is enough for class-level readiness flags/names; no native loop is run.
    for method in methods:
        if method.name == "":
            method.name = method.__class__.__name__.lower()
    rows = build_matrix(benchmarks, methods, os.environ.get("HW_MODEL_URL", ""))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps([r.__dict__ for r in rows], indent=2, ensure_ascii=False) + "\n",
                   encoding="utf-8")
    DATASETS_OUT.write_text(
        json.dumps(dataset_rows(benchmarks), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8")
    ready = sum(r.real_ready for r in rows)
    print(f"wrote {OUT}: {len(rows)} combinations, real-ready {ready}/{len(rows)}")
    print(f"wrote {DATASETS_OUT}")
    for row in dataset_rows(benchmarks):
        print(f"{row['benchmark']:8} tasks={row['tasks']:3} "
              f"official={row['official_tasks']:3} "
              f"loader={row['real_loader']} host={row['real_host']} "
              f"grader={row['real_grader']} {row['dataset_missing']}")
    for r in rows[:16]:
        print(f"{r.benchmark:8} {r.method:12} contract={r.contract_ready} "
              f"real={r.real_ready} missing={','.join(r.missing)}")


if __name__ == "__main__":
    main()
