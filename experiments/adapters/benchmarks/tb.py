"""Terminal-Bench 2.1 adapter.

Terminal-Bench 2.1 is published as a Harbor-layout dataset
(``harbor-framework/terminal-bench-2-1``).  The task set is cloned into the
ignored cache by::

    git clone --depth 1 https://github.com/harbor-framework/terminal-bench-2-1.git \
        .cache/upstream/terminal-bench-2-1

The adapter contains no task logic of its own: it reuses the generic Harbor
loader and the official ``tests/test.sh`` verifier.
"""
from __future__ import annotations

import os
from pathlib import Path

from benchmarks.harbor import HarborBenchmarkAdapter

REPO = Path(__file__).resolve().parents[3]
DEFAULT_ROOT = REPO / ".cache" / "upstream" / "terminal-bench-2-1" / "tasks"


class TerminalBench21Adapter(HarborBenchmarkAdapter):
    name = "tb21"

    def __init__(self, root: str | Path | None = None, name: str | None = None):
        root = Path(root or os.environ.get("HW_TB21_ROOT") or DEFAULT_ROOT)
        super().__init__(root, name=name or self.name)
