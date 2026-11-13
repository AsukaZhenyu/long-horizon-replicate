"""Long-Horizon-Terminal-Bench 2.0 adapter.

Two task sets live in the public LHTB checkout:

``tasks/``      46 original tasks whose ``tests/`` directory is public.  The
                official ``tests/test.sh`` can be run locally, so these are
                eligible for real grading.
``tasks-2.0``   31 new reconstruction tasks.  Their verifier is private
                (``tests/private`` is not shipped), so the loader can read the
                tasks but ``grade()`` returns an invalid grade with the reason
                instead of inventing a score.

The default subdirectory is ``tasks-2.0`` to keep the existing loader contract
stable.  Pass ``subdir="tasks"`` for the real-grading task set.
"""
from __future__ import annotations

import os
from pathlib import Path

from benchmarks.harbor import HarborBenchmarkAdapter

REPO = Path(__file__).resolve().parents[3]
DEFAULT_ROOT = REPO / ".cache" / "upstream" / "lhtb"


class LHTBBenchmarkAdapter(HarborBenchmarkAdapter):
    name = "lhtb2"

    def __init__(self, root: str | Path | None = None, subdir: str = "tasks-2.0",
                 name: str | None = None):
        root = Path(root or os.environ.get("HW_LHTB_ROOT") or DEFAULT_ROOT)
        super().__init__(root / subdir, name=name or self.name)
        self.subdir = subdir

    def load_tasks(self, path: str | None = None):
        tasks = super().load_tasks(path)
        # Preserve the keys the original LHTB loader exposed.
        for task in tasks:
            task.metadata.setdefault("timeout_sec", task.metadata.get("agent_timeout_sec"))
            task.metadata.setdefault("continue_until_timeout", False)
        return tasks
