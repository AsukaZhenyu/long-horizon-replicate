"""RRSI Domain adapter: evaluate a prompt-only harness on TB8.

RRSI's own coding domain is Terminal-Bench 2.1 through Harbor.  This adapter
reuses RRSI's Domain interface but points evaluation at the local TB8 harness:
the candidate harness is ``domains/tb8/harness/system_prompt.txt`` and the Pi
host is the runner.  It is intentionally prompt-only: the candidate may edit
the appended system prompt, but not the Pi/Spine/Sentry code.

The RRSI *search* roles (proposer/analyst/critic) still call AnthropicVertex in
upstream ``rrsi/llm.py``; this adapter does not make the search loop local-only.
It makes the Evaluate() half runnable on this machine, so a candidate harness
can be scored against TB8 with the same frozen model and grading as the AB
smoke.

Install:
    copy this directory to <rrsi>/domains/tb8/ and run RRSI with ``--domain tb8``.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from rrsi.domain import Domain
from rrsi.evaluate import TaskResult

TASKS = [
    "sqlite-db-truncate",
    "jq-data-processing",
    "hello-world",
    "regex-log",
    "cprofiling-python",
    "fix-permissions",
    "log-summary",
    "cancel-async-tasks",
]
TASKSET = set(TASKS)
DEFAULT_REPO = Path(os.environ.get("HW_TB_EVAL_ROOT", "")).resolve() if os.environ.get("HW_TB_EVAL_ROOT") else None


def repo_root() -> Path:
    override = os.environ.get("HW_TB_EVAL_ROOT")
    if override:
        return Path(override).resolve()
    # The adapter is copied under <rrsi>/domains/tb8; the TB8 harness lives in
    # the sibling evidence repo.  Require the explicit env var on other machines.
    raise RuntimeError("set HW_TB_EVAL_ROOT to the long-horizon-replicate checkout")


def read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None


class TB8Domain(Domain):
    name = "tb8"
    harness_path = "harness"
    source_exts = {".txt", ".json", ".md"}
    critic_patterns = [
        (r"/tests\b", "verifier tests path in diff"),
        (r"test_outputs", "verifier test file reference in diff"),
        (r"/solution\b", "oracle solution path in diff"),
    ]
    component_signals = [
        ("prompt", [r"system_prompt", r"prompt"]),
        ("control_flow", [r"max_steps", r"timeout", r"budget"]),
    ]
    briefs = {
        "analyst": (
            "The benchmark is TB8: eight Terminal-Bench 0.2.18 development tasks run "
            "in isolated Docker clients with a 300 s agent budget and hidden original "
            "tests. The harness is a system prompt appended to a Pi 1.1.0 coding agent; "
            "it can change how the agent plans, validates and submits, but not the "
            "task environment or grading."
        ),
        "digester": (
            "Summarise the failed trajectory by the harness prompt component that could "
            "have prevented it: planning, command construction, validation, or completion."
        ),
        "proposer": (
            "Propose a minimal edit to domains/tb8/harness/system_prompt.txt. Keep the "
            "task instruction and hidden-test boundary untouched."
        ),
        "critic": (
            "Reject any edit that names a TB8 task, references /tests or test_outputs, "
            "hard-codes a solution, or changes the frozen model/budget."
        ),
    }

    # ---- task sets ---------------------------------------------------------
    def evolve_ids(self):
        return list(TASKS)

    def heldout_ids(self):
        return []

    def smoke_ids(self, incumbent_per_task=None):
        return ["hello-world", "fix-permissions"]

    # ---- Evaluate ----------------------------------------------------------
    def run(self, root: Path, runs_dir: Path, job: str, ids, k: int, log_prefix: str = ""):
        if k != 1:
            raise ValueError("TB8 adapter currently supports k=1 (one fresh attempt per task)")
        repo = repo_root()
        ids = [t for t in ids if t in TASKSET]
        job_dir = (Path(runs_dir) / "jobs" / job).resolve()
        cases = job_dir / "pi" / "cases"
        pending = [t for t in ids if not (cases / t / "result.json").exists()]
        if not pending:
            return
        harness = (Path(root) / "domains" / "tb8" / "harness" / "system_prompt.txt").resolve()
        if not harness.is_file():
            raise FileNotFoundError(f"candidate harness prompt missing: {harness}")
        env = {
            **os.environ,
            "HW_TB_EVAL_ROOT": str(repo),
            "HW_ROUND_DIR": str(repo / ".cache" / "round8"),
            "HW_RUNS": str(job_dir),
            "HW_APPEND_SYSTEM_PROMPT": str(harness),
            "HW_ADAPTER": "rrsi-tb8-prompt-only",
            "HW_PYTHON": os.environ.get("HW_PYTHON", str(repo / ".cache" / "venv" / "Scripts" / "python.exe")),
        }
        log = Path(runs_dir) / "logs" / f"{log_prefix or job}.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("a", encoding="utf-8") as handle:
            handle.write(f"[tb8] tasks={pending}\n")
            handle.flush()
            proc = subprocess.run(
                ["node", str(repo / "experiments" / "tb-eval" / "harness" / "spine" / "run.mjs"),
                 "--pi-only", "--tasks", ",".join(pending)],
                cwd=str(repo), env=env, stdout=handle, stderr=subprocess.STDOUT,
            )
        if proc.returncode != 0:
            print(f"[tb8] runner rc={proc.returncode} (see {log})", flush=True)

    def score(self, runs_dir: Path, job: str, ids, k: int):
        job_dir = (Path(runs_dir) / "jobs" / job).resolve()
        per = {}
        total = 0
        for task in ids:
            result = read_json(job_dir / "pi" / "cases" / task / "result.json")
            if result is None:
                per[task] = TaskResult(rewards=[0.0], tokens=[None], missing=1,
                                       extra={"reason": "no result"})
                continue
            reward = 1.0 if result.get("Y") == 1 else 0.0
            total += int(reward)
            tokens = (result.get("usage") or {}).get("total_tokens")
            per[task] = TaskResult(rewards=[reward], tokens=[tokens], missing=0,
                                   extra={"A": result.get("A"), "V": result.get("V"),
                                          "stop": result.get("finalStopReason")})
        return per, {"total_passes": total, "n_trials": len(ids), "pass_rate": total / max(1, len(ids))}

    # ---- evidence ----------------------------------------------------------
    def load_trial(self, runs_dir, job, task_id, trial):
        result = read_json(Path(runs_dir) / "jobs" / job / "pi" / "cases" / task_id / "result.json")
        if result is None or trial != 0:
            return None
        return {"task_id": task_id, "result": result}

    def render_trace(self, rec, detail: bool = False):
        result = (rec or {}).get("result") or {}
        return (
            f"task={rec.get('task_id')} A={result.get('A')} V={result.get('V')} "
            f"Y={result.get('Y')} stop={result.get('finalStopReason')} "
            f"tools={json.dumps(result.get('toolCounts') or {}, ensure_ascii=False)}\n"
            f"final={str(result.get('finalAnswer') or '')[:1200]}"
        )

    def task_row(self, task_id, rec, tr):
        return f"{task_id} | rewards={tr.rewards if tr else '?'} | missing={tr.missing if tr else '?'}"

    # ---- gates -------------------------------------------------------------
    def smoke(self, root, runs_dir, job, ids):
        repo = repo_root()
        images = read_json(repo / ".cache" / "round8" / "base-images.json")
        if not images or len(images) != 8:
            return False, {"stage": "images", "detail": "round8/base-images.json missing or incomplete"}
        harness = (Path(root) / "domains" / "tb8" / "harness" / "system_prompt.txt").resolve()
        if not harness.is_file():
            return False, {"stage": "harness", "detail": str(harness)}
        return True, {"stage": "ok", "images": len(images), "harness": str(harness)}

    def constitution(self, root: Path):
        d = Path(root) / "domains" / "tb8"
        return (d / "SKILL.md").read_text(encoding="utf-8"), (d / "PATTERNS.md").read_text(encoding="utf-8")


DOMAIN = TB8Domain()
