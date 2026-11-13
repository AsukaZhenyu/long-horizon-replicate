"""MLE-bench adapter skeleton.

MLE-bench tasks are Kaggle competitions: data, a training/submission script,
a submission format, and an official target score/medal.  The public dataset
and Kaggle credentials are not present on this machine, so the adapter reports
the missing data instead of pretending to run.  When ``HW_MLE_ROOT`` points at
a checkout, the next step is to implement the Kaggle data mount, the official
submission validator, and the target-score/medal grade.
"""
from __future__ import annotations

import os
from pathlib import Path

from benchmarks.harbor import MissingDatasetAdapter

REPO = Path(__file__).resolve().parents[3]
DEFAULT_ROOT = REPO / ".cache" / "upstream" / "mle-bench"


class MLEBenchAdapter(MissingDatasetAdapter):
    name = "mle"

    def __init__(self, root: str | Path | None = None):
        root = Path(root or os.environ.get("HW_MLE_ROOT") or DEFAULT_ROOT)
        try:
            shown = root.relative_to(REPO).as_posix()
        except ValueError:
            shown = root.as_posix()
        reason = (
            f"MLE-bench dataset/loader not present at {shown}; "
            "set HW_MLE_ROOT to a checkout to build the Kaggle loader"
        )
        super().__init__("mle", reason)
        self.root = root
