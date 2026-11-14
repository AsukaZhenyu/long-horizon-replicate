"""Select the two-TB trajectory corpus (deterministic, stratified).

Rules are frozen in docs/plan/2026-11-13-two-tb-trajectory-design.md.
Run: python experiments/tb-corpus/select_tasks.py
"""
from __future__ import annotations

import json
import random
import tomllib
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent / "selection.json"
SEED = 20261113
TB_ROOT = REPO / ".cache" / "upstream" / "terminal-bench-2-1" / "tasks"
LHTB_ROOT = REPO / ".cache" / "upstream" / "lhtb" / "tasks"


def read_task(path: Path) -> dict:
    data = tomllib.loads((path / "task.toml").read_text(encoding="utf-8"))
    meta = data.get("metadata") or {}
    return {
        "task_id": path.name,
        "difficulty": meta.get("difficulty", "?"),
        "category": meta.get("category", "?"),
        "expert_min": meta.get("expert_time_estimate_min"),
        "agent_timeout": (data.get("agent") or {}).get("timeout_sec"),
        "instruction": (path / "instruction.md").read_text(encoding="utf-8")[:200],
    }


def load(root: Path) -> list[dict]:
    return [read_task(p) for p in sorted(root.iterdir()) if (p / "task.toml").is_file()]


def stratified_pick(pool: list[dict], count: int, rng: random.Random,
                    key=lambda row: row["category"]) -> list[dict]:
    groups = defaultdict(list)
    for row in pool:
        groups[key(row)].append(row)
    for values in groups.values():
        rng.shuffle(values)
    picked = []
    keys = sorted(groups)
    while len(picked) < count and keys:
        for key in list(keys):
            if len(picked) >= count:
                break
            if groups[key]:
                picked.append(groups[key].pop())
            if not groups[key]:
                keys.remove(key)
    return picked


def main():
    rng = random.Random(SEED)
    tb_all = load(TB_ROOT)
    tb_excluded = []
    tb_pool = []
    for row in tb_all:
        expert = row["expert_min"]
        timeout = row["agent_timeout"] or 0
        if expert is not None and expert >= 180:
            tb_excluded.append({**row, "reason": "expert_time_estimate_min >= 180"})
        elif timeout > 3600:
            tb_excluded.append({**row, "reason": "agent_timeout > 3600"})
        else:
            tb_pool.append(row)
    easy = [r for r in tb_pool if r["difficulty"] == "easy"]
    medium = [r for r in tb_pool if r["difficulty"] == "medium"]
    hard = [r for r in tb_pool if r["difficulty"] == "hard"]
    tb_selected = list(easy) + stratified_pick(medium, 15, rng) + stratified_pick(hard, 6, rng)

    lh_all = load(LHTB_ROOT)
    lh_excluded = []
    lh_pool = []
    for row in lh_all:
        timeout = row["agent_timeout"] or 0
        if timeout > 5400:
            lh_excluded.append({**row, "reason": "agent_timeout > 5400; long-horizon extension only"})
        else:
            lh_pool.append(row)
    lh_selected = stratified_pick(
        lh_pool, 25, rng,
        key=lambda row: (row["category"], int(row["agent_timeout"] or 0)),
    )

    def mark(rows, benchmark, reason):
        return [{**row, "benchmark": benchmark, "reason": reason} for row in rows]

    tasks = mark(tb_selected, "tb21", "stratified: easy all / medium 15 / hard 6") + \
            mark(lh_selected, "lhtb2", "stratified: category x official timeout")
    payload = {
        "seed": SEED,
        "purpose": "two-TB trajectory corpus; see docs/plan/2026-11-13-two-tb-trajectory-design.md",
        "benchmarks": {
            "tb21": {
                "total": len(tb_all),
                "selected": len(tb_selected),
                "excluded": tb_excluded,
            },
            "lhtb2": {
                "total": len(lh_all),
                "selected": len(lh_selected),
                "excluded": lh_excluded,
            },
        },
        "tasks": tasks,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")
    print(f"wrote {OUT}: TB {len(tb_selected)} + LHTB {len(lh_selected)} = {len(tasks)}")
    for bench in ("tb21", "lhtb2"):
        rows = [r for r in tasks if r["benchmark"] == bench]
        print(f"--- {bench} ({len(rows)})")
        for row in rows:
            print(f"{row['difficulty']:6} {str(row['category']):24} "
                  f"{int(row['agent_timeout'] or 0):5}s {row['task_id']}")


if __name__ == "__main__":
    main()
