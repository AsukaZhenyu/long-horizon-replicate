"""Build docs/plan/Math-Experimental-Design.docx from its Markdown source."""
from __future__ import annotations

from pathlib import Path

import build_report

REPO = Path(__file__).resolve().parents[2]
build_report.SOURCE = REPO / "docs" / "plan" / "Math-Experimental-Design.md"
build_report.TARGET = REPO / "docs" / "plan" / "Math-Experimental-Design.docx"


def main() -> int:
    build_report.build()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
