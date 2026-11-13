"""CORE-Bench adapter skeleton.

CORE-Bench tasks are code capsules: a repository, data, dependency install,
a run command, and a result extracted into a tolerance window.  The public
dataset is not present on this machine, so the adapter reports the missing
data instead of pretending to run.  When ``HW_CORE_ROOT`` points at a checkout,
the next step is to implement ``load_tasks``/``make_host``/``grade`` for the
capsule layout and the official tolerance checker.
"""
from __future__ import annotations

import os
from pathlib import Path

from benchmarks.harbor import MissingDatasetAdapter

REPO = Path(__file__).resolve().parents[3]
DEFAULT_ROOT = REPO / ".cache" / "upstream" / "core-bench"


class CoreBenchAdapter(MissingDatasetAdapter):
    name = "core"

    def __init__(self, root: str | Path | None = None):
        root = Path(root or os.environ.get("HW_CORE_ROOT") or DEFAULT_ROOT)
        try:
            shown = root.relative_to(REPO).as_posix()
        except ValueError:
            shown = root.as_posix()
        reason = (
            f"CORE-Bench dataset/loader not present at {shown}; "
            "set HW_CORE_ROOT to a checkout to build the capsule loader"
        )
        super().__init__("core", reason)
        self.root = root
