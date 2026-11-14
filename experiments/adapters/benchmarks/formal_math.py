"""Formal math adapters: miniF2F and ProofNet on the pinned Lean 4.33.1.

Both datasets are evaluated in the same Lean project as PutnamBench so every
formal task uses one toolchain and one Mathlib build.  The upstream Lean 4
ports pin older toolchains (miniF2F v4.24.0, ProofNet v4.20.0); their
statements are copied into the v4.33.1 project by ``prepare_formal_math.py``
and any file that no longer compiles is excluded from the loader.

miniF2F has one theorem per file.  ProofNet has many theorems per file, so a
task is one theorem: grading compiles the file and maps Lean's
``declaration uses `sorry'`` warnings back to the target declaration.
``prepare_formal_math.py`` records the upstream commits and copies.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import List, Optional, Tuple

from benchmarks.content import (
    LocalContentHost, _free_commit_gb, _proof_cheat, resolve_lean_bin,
)
from contract.types import (
    BenchmarkAdapter, ExperimentConfig, Grade, Host, TaskSpec,
)

REPO = Path(__file__).resolve().parents[3]
PUTNAM_PROJECT = REPO / ".cache" / "upstream" / "putnambench" / "lean4"
MINIF2F_SUBDIR = "formal/minif2f"
PROOFNET_SUBDIR = "formal/proofnet"

THEOREM_RE = re.compile(
    r"^[ \t]*(?:theorem|lemma)[ \t]+([A-Za-z0-9_'.]+)", re.MULTILINE)
SORRY_WARNING = re.compile(
    r":(?P<line>\d+):\d+:\s+warning:\s+declaration uses [`']sorry[`']")


def parse_theorems(text: str) -> List[Tuple[str, int]]:
    """Return ``(theorem_name, 1-based declaration line)`` in source order."""
    return [(match.group(1), text.count("\n", 0, match.start()) + 1)
            for match in THEOREM_RE.finditer(text)]


def sorry_warning_lines(output: str, rel_file: str) -> List[int]:
    """Line numbers of ``declaration uses `sorry'`` warnings for one file."""
    wanted = Path(rel_file).as_posix()
    lines: List[int] = []
    for line in output.splitlines():
        match = SORRY_WARNING.search(line)
        if not match:
            continue
        prefix = line[: match.start()]
        if Path(prefix).as_posix().endswith(wanted) or wanted in prefix:
            lines.append(int(match.group("line")))
    return lines


def _first_theorem(text: str) -> str:
    theorems = parse_theorems(text)
    return theorems[0][0] if theorems else ""


class LeanProjectAdapter(BenchmarkAdapter):
    """Shared host/toolchain for the formal math projects."""

    name = "lean_project"
    mock_only = False
    real_loader = True
    real_host = True
    real_grader = True
    MIN_FREE_COMMIT_GB = 5.5

    def __init__(self, project: str | Path | None = None,
                 subdir: str = "", limit: int = 20,
                 lean_bin: str | Path | None = None,
                 min_free_commit_gb: Optional[float] = None,
                 command_timeout: int = 3600):
        self.project = Path(project) if project is not None else PUTNAM_PROJECT
        self.subdir = subdir
        self.limit = limit
        self.lean_bin = Path(lean_bin) if lean_bin is not None else None
        self.min_free_commit_gb = (
            self.MIN_FREE_COMMIT_GB if min_free_commit_gb is None
            else float(min_free_commit_gb))
        self.command_timeout = command_timeout

    def _lake(self) -> Optional[Path]:
        return resolve_lean_bin(self.lean_bin)

    def _failed_files(self) -> set:
        """Files marked incompatible by ``prepare_formal_math.py --precheck``."""
        path = self.project / "formal" / "precheck.json"
        if not path.is_file():
            return set()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return set()
        return {item.get("file", "") for item in data.get("files", [])
                if not item.get("ok")}

    def source_path(self, task: TaskSpec) -> Path:
        return self.project / task.metadata["file"]

    def make_host(self, task: TaskSpec, config: ExperimentConfig) -> Host:
        source = self.source_path(task)
        if not source.is_file():
            raise FileNotFoundError(f"missing Lean source {source}")
        backup = source.with_suffix(source.suffix + ".bak")
        if backup.is_file():
            shutil.copy2(backup, source)
        else:
            shutil.copy2(source, backup)
        lake = self._lake()
        return LocalContentHost(
            task, config, self.project, command_timeout=self.command_timeout,
            cleanup_workspace=False,
            extra_path=lake.parent if lake is not None else None,
            install_tools=False)

    def _run_lean(self, rel_file: str) -> Tuple[int, str, float, Optional[float]]:
        lake = self._lake()
        if lake is None:
            return 127, "Lean toolchain missing", 0.0, None
        free_gb = _free_commit_gb()
        if free_gb is not None and free_gb < self.min_free_commit_gb:
            return 126, (
                f"Lean grading needs about {self.min_free_commit_gb:.1f} GB of "
                f"commit headroom, only {free_gb:.1f} GB free; stop the local "
                "model server first"), 0.0, free_gb
        env = os.environ.copy()
        env["PATH"] = str(lake.parent) + os.pathsep + env.get("PATH", "")
        started = time.time()
        try:
            proc = subprocess.run(
                [str(lake), "env", "lean", rel_file],
                cwd=str(self.project), env=env, capture_output=True,
                encoding="utf-8", errors="replace",
                timeout=self.command_timeout)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return 125, f"lake env lean error: {exc}", time.time() - started, free_gb
        output = (proc.stdout or "") + (proc.stderr or "")
        return proc.returncode, output, time.time() - started, free_gb


class MiniF2FAdapter(LeanProjectAdapter):
    """One theorem per Lean file (miniF2F Test or Valid split)."""

    name = "minif2f"

    def __init__(self, project: str | Path | None = None, split: str = "Test",
                 limit: int = 20, **kwargs):
        if split not in ("Test", "Valid"):
            raise ValueError("split must be Test or Valid")
        self.split = split
        super().__init__(project=project,
                         subdir=f"{MINIF2F_SUBDIR}/{split}", limit=limit,
                         **kwargs)

    def load_tasks(self, path: str | None = None) -> List[TaskSpec]:
        root = self.project / self.subdir
        failed = self._failed_files()
        tasks = []
        for source in sorted(root.glob("*.lean")):
            rel = source.relative_to(self.project).as_posix()
            if rel in failed:
                continue
            text = source.read_text(encoding="utf-8", errors="replace")
            theorem = _first_theorem(text)
            tasks.append(TaskSpec(
                task_id=f"{self.split.lower()}-{source.stem}",
                benchmark=self.name,
                instruction=(
                    "The Lean 4 project is the current directory. Prove "
                    f"`theorem {theorem}` in `{rel}` by replacing `sorry`. "
                    f"Run `lake env lean {rel}` in the current directory to "
                    "check the kernel; the file must not contain `sorry`, "
                    "`admit`, or a new axiom. Do not use a GUI."),
                metadata={
                    "file": rel, "theorem": theorem, "split": self.split,
                    "upstream": "yangky11/miniF2F-lean4",
                }))
            if len(tasks) >= self.limit:
                break
        return tasks

    def grade(self, task: TaskSpec, host: Host) -> Grade:
        source = self.source_path(task)
        if not source.is_file():
            return Grade(valid=False, passed=False, checks_passed=0,
                         checks_total=1, detail=f"missing {source}")
        text = source.read_text(encoding="utf-8", errors="replace")
        cheat = _proof_cheat(text)
        if cheat:
            return Grade(valid=True, passed=False, checks_passed=0,
                         checks_total=1,
                         detail=f"{cheat}; Lean would accept it with only a "
                                "warning or an extra axiom")
        rel = task.metadata["file"]
        rc, output, seconds, free_gb = self._run_lean(rel)
        if rc in (125, 126, 127):
            return Grade(valid=False, passed=False, checks_passed=0,
                         checks_total=1,
                         detail=output + (f" ({seconds:.1f}s)" if seconds else ""))
        sorry = sorry_warning_lines(output, rel)
        passed = rc == 0 and not sorry
        if hasattr(host, "last_score"):
            host.last_score = 1.0 if passed else 0.0
        return Grade(valid=True, passed=passed,
                     checks_passed=1 if passed else 0, checks_total=1,
                     detail=(f"lake env lean exit={rc} in {seconds:.1f}s "
                             f"sorry_warnings={len(sorry)}"
                             + (f" free_commit_gb={free_gb:.1f}" if free_gb else "")
                             + "\n" + output[-1200:]))


class ProofNetAdapter(LeanProjectAdapter):
    """One task per theorem inside a shared ProofNet textbook file."""

    name = "proofnet"

    def __init__(self, project: str | Path | None = None,
                 textbook: str | None = None, limit: int = 20, **kwargs):
        self.textbook = textbook
        super().__init__(project=project, subdir=PROOFNET_SUBDIR,
                         limit=limit, **kwargs)

    def _files(self) -> List[Path]:
        files = sorted((self.project / self.subdir).glob("*.lean"))
        if self.textbook:
            files = [path for path in files
                     if path.stem.lower() == self.textbook.lower()]
        return files

    def load_tasks(self, path: str | None = None) -> List[TaskSpec]:
        tasks = []
        failed = self._failed_files()
        for source in self._files():
            rel = source.relative_to(self.project).as_posix()
            if rel in failed:
                continue
            text = source.read_text(encoding="utf-8", errors="replace")
            for name, line in parse_theorems(text):
                tasks.append(TaskSpec(
                    task_id=f"{source.stem}.{name}", benchmark=self.name,
                    instruction=(
                        "The Lean 4 project is the current directory. Prove "
                        f"`theorem {name}` at `{rel}:{line}` by replacing its "
                        "`sorry`. Leave the other theorems unchanged. Run "
                        f"`lake env lean {rel}` in the current directory to "
                        "check the kernel. Do not use a GUI."),
                    metadata={
                        "file": rel, "theorem": name, "line": line,
                        "textbook": source.stem,
                        "upstream": "rahul3613/ProofNet-lean4",
                    }))
                if len(tasks) >= self.limit:
                    return tasks
        return tasks

    def grade(self, task: TaskSpec, host: Host) -> Grade:
        source = self.source_path(task)
        if not source.is_file():
            return Grade(valid=False, passed=False, checks_passed=0,
                         checks_total=1, detail=f"missing {source}")
        text = source.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()
        theorems = parse_theorems(text)
        index = next((i for i, (name, _) in enumerate(theorems)
                      if name == task.metadata["theorem"]), None)
        if index is None:
            return Grade(valid=False, passed=False, checks_passed=0,
                         checks_total=1,
                         detail=f"theorem {task.metadata['theorem']} not found")
        start = theorems[index][1]
        end = (theorems[index + 1][1] - 1
               if index + 1 < len(theorems) else len(lines))
        block = "\n".join(lines[start - 1:end])
        cheat = _proof_cheat(block)
        if cheat:
            return Grade(valid=True, passed=False, checks_passed=0,
                         checks_total=1,
                         detail=f"{cheat} in {task.metadata['theorem']}; other "
                                "theorems may still contain `sorry`")
        rel = task.metadata["file"]
        rc, output, seconds, free_gb = self._run_lean(rel)
        if rc in (125, 126, 127):
            return Grade(valid=False, passed=False, checks_passed=0,
                         checks_total=1,
                         detail=output + (f" ({seconds:.1f}s)" if seconds else ""))
        warnings = sorry_warning_lines(output, rel)
        target_sorry = [line for line in warnings if start <= line <= end]
        passed = rc == 0 and not target_sorry
        if hasattr(host, "last_score"):
            host.last_score = 1.0 if passed else 0.0
        return Grade(valid=True, passed=passed,
                     checks_passed=1 if passed else 0, checks_total=1,
                     detail=(f"lake env lean exit={rc} in {seconds:.1f}s "
                             f"target_sorry={bool(target_sorry)} "
                             f"other_sorry={len(warnings) - len(target_sorry)}"
                             + (f" free_commit_gb={free_gb:.1f}" if free_gb else "")
                             + "\n" + output[-1200:]))
