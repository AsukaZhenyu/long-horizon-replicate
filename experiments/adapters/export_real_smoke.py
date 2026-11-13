"""Write the 9B real-smoke summary from the local run records.

Raw per-run JSON/logs live in the ignored ``.cache/adapters/real-smoke/``.
This script keeps only the small, reviewable summary in ``results/``.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[1]
SMOKE = REPO / ".cache" / "adapters" / "real-smoke"
OUT = ROOT / "results" / "real-smoke-9b.json"

KEEP = (
    "method", "benchmark", "task", "label", "max_steps", "max_tokens",
    "enforce_submission", "agent_seconds", "tokens", "actions", "turns",
    "grade_valid", "grade_passed", "checks_passed", "checks_total", "phases",
    "bounces", "action_log",
)


def main():
    runs = []
    if SMOKE.is_dir():
        for path in sorted(SMOKE.glob("*.json")):
            if path.name in ("batch-summary.json",):
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            runs.append({key: data[key] for key in KEEP if key in data})
    payload = {
        "model": "qwen3.5-9b",
        "conditions": {
            "context": 16384,
            "gpu_layers": 26,
            "temperature": 0.2,
            "reasoning": "off",
            "max_tokens_per_step": 512,
            "max_steps": 6,
        },
        "runs": runs,
        "notes": {
            "budget": "6 steps x 512 tokens; wiring smoke, not the formal budget",
            "tb_regex_log_first_attempt": (
                "official grading aborted during apt-get update; recorded as "
                "D-apt environment failure and not used as a method result"),
            "core_task": "capsule-1854976, codeocean_easy, 3 questions",
            "submit_guard": (
                "guard is off by default.  Runs labelled 'guard' used "
                "enforce_submission=True; they are separate conditions from "
                "the default no-guard runs"),
            "interpretation": (
                "single-task descriptions only; do not read as method benefit "
                "or completion-rate evidence"),
        },
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")
    print(f"wrote {OUT} with {len(runs)} runs")
    for run in runs:
        print(run["method"], run["benchmark"], run["task"],
              f"{run.get('checks_passed')}/{run.get('checks_total')}",
              "valid" if run.get("grade_valid") else "invalid",
              "passed" if run.get("grade_passed") else "failed")


if __name__ == "__main__":
    main()
