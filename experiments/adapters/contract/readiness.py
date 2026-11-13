"""Per-combination readiness: contract vs real benchmark run.

Contract-ready means the adapter maps actions/observations and passes the
fairness tests.  Real-ready additionally needs real task loading, a real host,
official grading, the method's native loop, and a model endpoint.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence, Tuple

from .types import BenchmarkAdapter, MethodAdapter


@dataclass(frozen=True)
class AdapterStatus:
    benchmark: str
    method: str
    contract_ready: bool
    real_ready: bool
    missing: Tuple[str, ...]
    note: str = ""


def benchmark_missing(benchmark: BenchmarkAdapter) -> Tuple[str, ...]:
    missing = []
    if not benchmark.real_loader:
        missing.append("benchmark data loader")
    if not benchmark.real_host:
        missing.append("benchmark host")
    if not benchmark.real_grader:
        missing.append("official grading")
    return tuple(missing)


def method_missing(method: MethodAdapter) -> Tuple[str, ...]:
    missing = []
    if not method.native_loop_ready:
        missing.append("method native loop")
    return tuple(missing)


def build_matrix(benchmarks: Sequence[BenchmarkAdapter],
                 methods: Sequence[MethodAdapter],
                 model_endpoint: str = "") -> list[AdapterStatus]:
    rows = []
    for benchmark in benchmarks:
        b_missing = benchmark_missing(benchmark)
        dataset_note = getattr(benchmark, "dataset_missing", "") or ""
        for method in methods:
            m_missing = method_missing(method)
            missing = list(b_missing) + list(m_missing)
            if not model_endpoint:
                missing.append("model endpoint")
            note = dataset_note or ("contract/mock only" if benchmark.mock_only else "")
            rows.append(AdapterStatus(
                benchmark=benchmark.name,
                method=method.name,
                contract_ready=True,
                real_ready=not missing,
                missing=tuple(missing),
                note=note,
            ))
    return rows
