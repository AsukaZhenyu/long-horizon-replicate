"""miniF2F / ProofNet loaders, per-theorem parsing and optional Lean compile."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from benchmarks.formal_math import (
    MiniF2FAdapter, ProofNetAdapter, parse_theorems, sorry_warning_lines,
)
from contract.types import ExperimentConfig, TaskSpec

REPO = Path(__file__).resolve().parents[3]
PROJECT = REPO / ".cache" / "upstream" / "putnambench" / "lean4"


class FormalMathTests(unittest.TestCase):
    def config(self) -> ExperimentConfig:
        return ExperimentConfig(token_budget=20000, max_actions=8)

    def test_parse_theorems(self):
        text = ("import Mathlib\ntheorem a : True := by trivial\n"
                "lemma b : True := by trivial\n")
        self.assertEqual(parse_theorems(text), [("a", 2), ("b", 3)])

    def test_sorry_warning_lines(self):
        output = (
            "formal/proofnet/Putnam.lean:5:8: warning: declaration uses `sorry`\n"
            "formal/proofnet/Putnam.lean:10:8: warning: declaration uses 'sorry'\n"
            "formal/proofnet/Other.lean:7:8: warning: declaration uses `sorry`\n")
        self.assertEqual(
            sorry_warning_lines(output, "formal/proofnet/Putnam.lean"), [5, 10])

    def test_minif2f_loader(self):
        if not (PROJECT / "formal" / "minif2f" / "Test").is_dir():
            self.skipTest("miniF2F files not prepared")
        tasks = MiniF2FAdapter(limit=3).load_tasks()
        self.assertEqual(len(tasks), 3)
        self.assertEqual(tasks[0].task_id, "test-aime_1983_p1")
        self.assertEqual(tasks[0].metadata["theorem"], "aime_1983_p1")

    def test_proofnet_loader(self):
        if not (PROJECT / "formal" / "proofnet" / "Putnam.lean").is_file():
            self.skipTest("ProofNet files not prepared")
        tasks = ProofNetAdapter(textbook="Putnam", limit=100).load_tasks()
        self.assertEqual(len(tasks), 12)
        self.assertEqual(tasks[0].task_id, "Putnam.exercise_2020_b5")
        self.assertEqual(tasks[0].metadata["line"], 5)

    def test_precheck_excludes_failed_proofnet(self):
        precheck = PROJECT / "formal" / "precheck.json"
        if not precheck.is_file():
            self.skipTest("no precheck.json")
        data = json.loads(precheck.read_text(encoding="utf-8"))
        failed = {item["file"] for item in data.get("files", [])
                  if not item.get("ok")}
        if "formal/proofnet/Artin.lean" not in failed:
            self.skipTest("Artin.lean is not marked incompatible")
        self.assertEqual(
            ProofNetAdapter(textbook="Artin", limit=100).load_tasks(), [])

    def test_precheck_filter(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            folder = project / "formal" / "minif2f" / "Test"
            folder.mkdir(parents=True)
            (folder / "a.lean").write_text(
                "import Mathlib\ntheorem a : True := by sorry\n", encoding="utf-8")
            (folder / "b.lean").write_text(
                "import Mathlib\ntheorem b : True := by sorry\n", encoding="utf-8")
            (project / "formal" / "precheck.json").write_text(json.dumps({
                "files": [{"file": "formal/minif2f/Test/a.lean", "ok": False}],
            }), encoding="utf-8")
            tasks = MiniF2FAdapter(project=project, limit=10).load_tasks()
            self.assertEqual([task.task_id for task in tasks], ["test-b"])

    def test_proofnet_sorry_short_circuit(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            folder = project / "formal" / "proofnet"
            folder.mkdir(parents=True)
            source = folder / "Fixture.lean"
            source.write_text(
                "import Mathlib\n\n"
                "theorem solved_one : (1 : ℕ) = 1 := by rfl\n\n"
                "theorem still_sorry : (2 : ℕ) = 2 := by sorry\n",
                encoding="utf-8")
            adapter = ProofNetAdapter(project=project, textbook="Fixture",
                                      limit=10)
            tasks = {task.metadata["theorem"]: task
                     for task in adapter.load_tasks()}
            task = tasks["still_sorry"]
            grade = adapter.grade(
                task, SimpleNamespace(workspace=project, last_score=None))
            self.assertTrue(grade.valid, grade.detail)
            self.assertFalse(grade.passed, grade.detail)
            self.assertIn("sorry", grade.detail)

    @unittest.skipUnless(
        os.environ.get("RUN_LEAN_TESTS") == "1",
        "set RUN_LEAN_TESTS=1 (stop the model server first)")
    def test_lean_minif2f_and_proofnet(self):
        if not PROJECT.is_dir():
            self.skipTest("Putnam project not present")
        mini = PROJECT / "formal" / "minif2f" / "Test" / "zz_smoke.lean"
        proof = PROJECT / "formal" / "proofnet" / "zz_smoke.lean"
        mini.write_text(
            "import Mathlib\n\ntheorem zz_smoke : (1 : ℕ) = 1 := by\n  rfl\n",
            encoding="utf-8")
        proof.write_text(
            "import Mathlib\n\ntheorem zz_solved : (1 : ℕ) = 1 := by rfl\n\n"
            "theorem zz_sorry : (2 : ℕ) = 2 := by sorry\n",
            encoding="utf-8")
        try:
            mini_adapter = MiniF2FAdapter(limit=10000, min_free_commit_gb=0)
            mini_task = next(task for task in mini_adapter.load_tasks()
                             if task.metadata["file"].endswith("zz_smoke.lean"))
            host = mini_adapter.make_host(mini_task, self.config())
            grade = mini_adapter.grade(mini_task, host)
            self.assertTrue(grade.valid, grade.detail)
            self.assertTrue(grade.passed, grade.detail)

            proof_adapter = ProofNetAdapter(
                textbook="zz_smoke", limit=10, min_free_commit_gb=0)
            proof_tasks = {task.metadata["theorem"]: task
                           for task in proof_adapter.load_tasks()}
            solved = proof_adapter.grade(
                proof_tasks["zz_solved"],
                SimpleNamespace(workspace=PROJECT, last_score=None))
            self.assertTrue(solved.valid, solved.detail)
            self.assertTrue(solved.passed, solved.detail)
            sorry = proof_adapter.grade(
                proof_tasks["zz_sorry"],
                SimpleNamespace(workspace=PROJECT, last_score=None))
            self.assertTrue(sorry.valid, sorry.detail)
            self.assertFalse(sorry.passed, sorry.detail)
        finally:
            for path in (mini, proof):
                path.unlink(missing_ok=True)
                path.with_suffix(".lean.bak").unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
