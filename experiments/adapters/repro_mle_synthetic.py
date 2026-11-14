"""Coverage pilot: MLE-bench adapter + four methods on a synthetic competition.

Real MLE-bench needs Kaggle data and the official metric.  This script uses the
same adapter and host path with a synthetic prepared competition and the
dependency-free accuracy metric, proving that the MLE execution/grading chain
is wired.  It is not a real MLE-bench score.
"""
from __future__ import annotations

import json
import shutil
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[1]
sys.path.insert(0, str(ROOT))

from agents.base_react import BaseReactAgent, HTTPModelClient
from agents.recuris import RecurisAgent
from agents.rrsi import RRSIPromptAgent
from agents.sentry import SentryAgent
from benchmarks.mle import MLEBenchAdapter
from benchmarks.mle_grading import accuracy_metric
from contract.types import ExperimentConfig

BASE = REPO / ".cache" / "adapters" / "mle-synthetic"
OUT = ROOT / "results" / "mle-synthetic-pilot"
MODEL_URL = "http://127.0.0.1:8080"
METHODS = ("base", "sentry", "recuris-gate", "rrsi")


def health() -> bool:
    try:
        with urllib.request.urlopen(MODEL_URL + "/health", timeout=5) as response:
            return response.status == 200
    except Exception:
        return False


def build_root():
    shutil.rmtree(BASE, ignore_errors=True)
    env = BASE / "environment"
    env.mkdir(parents=True)
    env.joinpath("instructions.txt").write_text(
        "You are participating in MLE-bench. The competition data is in "
        "/home/data. Write your submission to /home/submission/submission.csv "
        "with columns id,prediction.\n", encoding="utf-8")
    comp = BASE / "mlebench" / "competitions" / "synthetic"
    comp.mkdir(parents=True)
    comp.joinpath("description.md").write_text(
        "Predict the label for each id. The public test file is "
        "/home/data/test.csv; it contains id,prediction for this synthetic "
        "smoke. Write id,prediction to the submission path.\n", encoding="utf-8")
    comp.joinpath("config.yaml").write_text(
        "id: synthetic\n"
        "name: Synthetic Competition\n"
        "competition_type: code\n"
        "description: mlebench/competitions/synthetic/description.md\n"
        "dataset:\n"
        "  answers: synthetic/prepared/private/answers.csv\n"
        "  sample_submission: synthetic/prepared/public/sample_submission.csv\n"
        "grader:\n"
        "  name: accuracy\n"
        "  grade_fn: benchmarks.mle_grading:accuracy_metric\n"
        "preparer: synthetic:prepare\n", encoding="utf-8")
    comp.joinpath("leaderboard.csv").write_text(
        "team,score\nA,1.0\nB,0.8\nC,0.6\nD,0.4\nE,0.2\n", encoding="utf-8")
    data = BASE / "data"
    public = data / "synthetic" / "prepared" / "public"
    private = data / "synthetic" / "prepared" / "private"
    public.mkdir(parents=True)
    private.mkdir(parents=True)
    public.joinpath("test.csv").write_text(
        "id,prediction\n1,a\n2,b\n", encoding="utf-8")
    public.joinpath("sample_submission.csv").write_text(
        "id,prediction\n1,a\n2,b\n", encoding="utf-8")
    private.joinpath("answers.csv").write_text(
        "id,answer\n1,a\n2,b\n", encoding="utf-8")
    return data


def build_agent(method: str, client, max_steps: int):
    if method == "base":
        return BaseReactAgent(client, max_steps=max_steps)
    if method == "sentry":
        return SentryAgent(client, max_steps=max_steps)
    if method == "recuris-gate":
        return RecurisAgent(client, completion_gate=True, max_steps=max_steps)
    if method == "rrsi":
        return RRSIPromptAgent(client, max_steps=max_steps)
    raise SystemExit(f"unknown method {method}")


def main() -> int:
    if not health():
        print(f"model endpoint not healthy: {MODEL_URL}")
        return 1
    OUT.mkdir(parents=True, exist_ok=True)
    data = build_root()
    adapter = MLEBenchAdapter(
        root=BASE, split="all", data_dir=data, image="alpine:latest",
        metric=accuracy_metric, enforce_submission=False)
    tasks = {task.task_id: task for task in adapter.load_tasks()}
    task = tasks["synthetic"]
    client = HTTPModelClient(MODEL_URL, "qwen3.5-9b", timeout=300,
                             temperature=0.2, max_tokens=512)
    config = ExperimentConfig(token_budget=50_000, max_actions=10)
    summary = []
    for method in METHODS:
        agent = build_agent(method, client, 8)
        host = adapter.make_host(task, config)
        started = time.time()
        try:
            agent.run(task, host)
            seconds = time.time() - started
            grade = adapter.grade(task, host)
            payload = {
                "benchmark": "mle",
                "dataset": "synthetic",
                "method": method,
                "task": "synthetic",
                "agent_seconds": round(seconds, 1),
                "tokens": host.tokens_used,
                "actions": len(host.actions),
                "grade_valid": grade.valid,
                "grade_passed": grade.passed,
                "checks_passed": grade.checks_passed,
                "checks_total": grade.checks_total,
                "detail": grade.detail[-2000:],
                "action_log": [
                    {"kind": action.kind, "payload": action.payload}
                    for action in host.actions
                ],
            }
            if hasattr(agent, "turns"):
                payload["turns"] = agent.turns
            if hasattr(agent, "phases"):
                payload["phases"] = dict(agent.phases)
            summary.append(payload)
            (OUT / f"{method}-synthetic.json").write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8")
            print(json.dumps({
                "method": method,
                "checks": f"{grade.checks_passed}/{grade.checks_total}",
                "valid": grade.valid, "passed": grade.passed,
                "tokens": host.tokens_used,
            }, ensure_ascii=False), flush=True)
        finally:
            host.cleanup()
    (OUT / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    print(f"wrote {OUT / 'summary.json'} with {len(summary)} runs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
