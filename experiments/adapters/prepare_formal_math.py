"""Copy miniF2F / ProofNet Lean files into the pinned PutnamBench project.

The upstream Lean 4 ports pin older toolchains (miniF2F v4.24.0, ProofNet
v4.20.0).  To keep one Lean/Mathlib version across all formal benchmarks, the
statements are compiled with the v4.33.1 project already used by PutnamBench.
This script is idempotent: it copies the sources and writes ``README.json``
with the upstream commits.  ``--precheck`` optionally compiles every copied
file (with its original ``sorry``) and records incompatibilities; the adapters
skip files listed as failed when ``precheck.json`` exists.

Usage:
    python experiments/adapters/prepare_formal_math.py
    python experiments/adapters/prepare_formal_math.py --precheck --limit 20
    python experiments/adapters/prepare_formal_math.py --precheck --only proofnet
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[1]
sys.path.insert(0, str(ROOT))

from benchmarks.content import _free_commit_gb, resolve_lean_bin

UPSTREAM = REPO / ".cache" / "upstream"
MINIF2F = UPSTREAM / "minif2f-lean4"
PROOFNET = UPSTREAM / "proofnet-lean4"
PROJECT = UPSTREAM / "putnambench" / "lean4"
FORMAL = PROJECT / "formal"


def _commit(repo: Path) -> str:
    try:
        return subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD"],
            capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return ""


def copy_sources() -> dict:
    if not MINIF2F.is_dir() or not PROOFNET.is_dir():
        raise SystemExit(
            "missing upstream checkouts; clone yangky11/miniF2F-lean4 and "
            "rahul3613/ProofNet-lean4 under .cache/upstream")
    minif2f_dst = FORMAL / "minif2f"
    proofnet_dst = FORMAL / "proofnet"
    minif2f_dst.mkdir(parents=True, exist_ok=True)
    proofnet_dst.mkdir(parents=True, exist_ok=True)
    for split in ("Test", "Valid"):
        src = MINIF2F / "MiniF2F" / split
        dst = minif2f_dst / split
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src, dst)
    for source in sorted((PROOFNET / "formal").glob("*.lean")):
        shutil.copy2(source, proofnet_dst / source.name)
    counts = {
        split: len(list((minif2f_dst / split).glob("*.lean")))
        for split in ("Test", "Valid")
    }
    counts["proofnet_files"] = len(list(proofnet_dst.glob("*.lean")))
    record = {
        "target_project": str(PROJECT.relative_to(REPO)).replace("\\", "/"),
        "target_toolchain": "leanprover/lean4:v4.33.1",
        "prepared_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "miniF2F": {
            "url": "https://github.com/yangky11/miniF2F-lean4",
            "commit": _commit(MINIF2F),
            "upstream_toolchain": "leanprover/lean4:v4.24.0",
            "files": counts["Test"] + counts["Valid"],
            "test": counts["Test"],
            "valid": counts["Valid"],
        },
        "proofnet": {
            "url": "https://github.com/rahul3613/ProofNet-lean4",
            "commit": _commit(PROOFNET),
            "upstream_toolchain": "leanprover/lean4:v4.20.0",
            "files": counts["proofnet_files"],
        },
    }
    (FORMAL / "README.json").write_text(
        json.dumps(record, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    return record


def _lean_files(only: str = "all") -> list[Path]:
    files = []
    patterns = []
    if only in ("all", "minif2f"):
        patterns += ["minif2f/Test/*.lean", "minif2f/Valid/*.lean"]
    if only in ("all", "proofnet"):
        patterns += ["proofnet/*.lean"]
    for pattern in patterns:
        files.extend(sorted((FORMAL / pattern).parent.glob(
            pattern.split("/")[-1])))
    return files


def precheck(limit: int = 0, only: str = "all") -> dict:
    lake = resolve_lean_bin()
    if lake is None:
        raise SystemExit("Lean toolchain not found")
    free_gb = _free_commit_gb()
    if free_gb is not None and free_gb < 6.5:
        raise SystemExit(
            f"precheck needs about 6.5 GB of free commit charge, only "
            f"{free_gb:.1f} GB available; stop the model server and Docker "
            "Desktop first so a kernel read error is not mistaken for an "
            "incompatible file")
    files = _lean_files(only)
    if limit:
        files = files[:limit]
    results = []
    for index, source in enumerate(files, 1):
        rel = source.relative_to(PROJECT).as_posix()
        proc = subprocess.run(
            [str(lake), "env", "lean", rel], cwd=str(PROJECT),
            capture_output=True, text=True, errors="replace", timeout=3600)
        output = (proc.stdout or "") + (proc.stderr or "")
        if proc.returncode == 0:
            errors = []
        else:
            lines = [line for line in output.splitlines()
                     if "error" in line.lower()]
            errors = "\n".join(lines[:20])[:2000] if lines else output[:2000]
        results.append({
            "file": rel, "ok": proc.returncode == 0, "errors": errors,
        })
        print(f"[{index}/{len(files)}] {rel} rc={proc.returncode}", flush=True)
    # Merge with earlier partial prechecks so an --only/--limit run does not
    # discard results already collected.
    merged = {}
    path = FORMAL / "precheck.json"
    if path.is_file():
        try:
            for item in json.loads(path.read_text(encoding="utf-8")).get(
                    "files", []):
                merged[item.get("file", "")] = item
        except (OSError, json.JSONDecodeError):
            pass
    merged.update({item["file"]: item for item in results})
    results = sorted(merged.values(), key=lambda item: item.get("file", ""))
    payload = {
        "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "total": len(results),
        "ok": sum(1 for item in results if item["ok"]),
        "failed": sum(1 for item in results if not item["ok"]),
        "files": results,
    }
    (FORMAL / "precheck.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    print(f"precheck: {payload['ok']}/{payload['total']} ok, "
          f"{payload['failed']} failed")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--precheck", action="store_true")
    parser.add_argument("--limit", type=int, default=0,
                        help="precheck only the first N files (0 = all)")
    parser.add_argument("--only", choices=("all", "minif2f", "proofnet"),
                        default="all", help="restrict the precheck")
    args = parser.parse_args()
    record = copy_sources()
    print(json.dumps(record, ensure_ascii=False, indent=2))
    if args.precheck:
        precheck(limit=args.limit, only=args.only)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
