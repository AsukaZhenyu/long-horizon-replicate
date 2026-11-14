"""Download MATH-500 and AIME 2024 into the ignored upstream cache.

The adapters can also run on their tiny offline fixtures; this script fetches
the real data used by ``protocols/math-informal-real.json``.  It uses only the
standard library and optionally an HTTP proxy (e.g. the local FlClash proxy).

Usage:
    python experiments/adapters/prepare_informal_data.py
    python experiments/adapters/prepare_informal_data.py --proxy http://127.0.0.1:7890
"""
from __future__ import annotations

import argparse
import json
import os
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / ".cache" / "upstream"
MATH_URL = ("https://huggingface.co/datasets/HuggingFaceH4/MATH-500/"
            "resolve/main/test.jsonl")
AIME_ROWS_URL = ("https://datasets-server.huggingface.co/rows?"
                 "dataset=Maxwell-Jia%2FAIME_2024&config=default&split=train"
                 "&offset=0&length=100")


def _fetch(url: str, proxy: str | None) -> bytes:
    handlers = []
    if proxy:
        handlers.append(urllib.request.ProxyHandler(
            {"http": proxy, "https": proxy}))
    opener = urllib.request.build_opener(*handlers)
    with opener.open(url, timeout=120) as response:
        return response.read()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--proxy", default=os.environ.get("HTTPS_PROXY", ""))
    args = parser.parse_args()

    math_dir = OUT / "math500"
    math_dir.mkdir(parents=True, exist_ok=True)
    raw = _fetch(MATH_URL, args.proxy).decode("utf-8")
    lines = [line for line in raw.splitlines() if line.strip()]
    (math_dir / "test.jsonl").write_text("\n".join(lines) + "\n",
                                         encoding="utf-8")
    print(f"MATH-500: {len(lines)} problems -> {math_dir / 'test.jsonl'}")

    aime_dir = OUT / "aime"
    aime_dir.mkdir(parents=True, exist_ok=True)
    data = json.loads(_fetch(AIME_ROWS_URL, args.proxy).decode("utf-8"))
    rows = [item["row"] for item in data.get("rows", [])]
    out = []
    for row in rows:
        out.append({
            "id": row.get("ID", ""),
            "problem": row.get("Problem", ""),
            "answer": str(row.get("Answer", "")),
            "solution": row.get("Solution", ""),
        })
    (aime_dir / "aime_2024.jsonl").write_text(
        "\n".join(json.dumps(item, ensure_ascii=False) for item in out) + "\n",
        encoding="utf-8")
    print(f"AIME 2024: {len(out)} problems -> {aime_dir / 'aime_2024.jsonl'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
