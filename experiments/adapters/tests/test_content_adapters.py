"""Content-generation adapters: local host, real Office/ChartQA, fixtures."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from benchmarks.content import (
    AIMEAdapter, ChartMimicAdapter, ChartQAAdapter, ECHOAdapter,
    LocalContentHost, MATH500Adapter, OfficeEditBenchAdapter, PPTEvalAdapter,
    PutnamBenchAdapter, _answers_match, _math_answers_match, _proof_cheat,
    _proof_has_sorry,
)
from contract.types import Action, ExperimentConfig, ScriptedAgent, TaskSpec

REPO = Path(__file__).resolve().parents[3]
OFFICE = REPO / ".cache" / "upstream" / "officeeditbench"
CHARTQA = REPO / ".cache" / "upstream" / "chartqa" / "ChartQA Dataset"
PUTNAM = REPO / ".cache" / "upstream" / "putnambench"


class ContentAdapterTests(unittest.TestCase):
    def config(self) -> ExperimentConfig:
        return ExperimentConfig(token_budget=200000, max_actions=20)

    def test_answer_normalization(self):
        self.assertTrue(_answers_match('"14"', "14"))
        self.assertTrue(_answers_match("14.0", "14"))
        self.assertTrue(_answers_match("$1,234", "1234"))
        self.assertFalse(_answers_match("15", "14"))

    def test_local_host_tools(self):
        with tempfile.TemporaryDirectory() as tmp:
            host = LocalContentHost(
                TaskSpec(task_id="x", benchmark="content", instruction="test"),
                self.config(), Path(tmp))
            self.assertTrue((Path(tmp) / "vision.py").is_file())
            host.step(Action("write", {"path": "a.txt", "content": "hello"}))
            read = host.step(Action("read", {"path": "a.txt"}))
            self.assertEqual(read.output, "hello")
            shell = host.step(Action("shell", {"command": "python -c \"print(7)\""}))
            self.assertEqual(shell.exit_code, 0, shell.error)
            self.assertIn("7", shell.output)
            host.step(Action("submit"))
            self.assertTrue(host.submitted)
            host.cleanup()

    def test_office_easy_verifier(self):
        task_json = OFFICE / "easy" / "tasks" / "E2-001_order_date" / "task.json"
        if not task_json.is_file():
            self.skipTest("OfficeEditBench checkout not present")
        adapter = OfficeEditBenchAdapter(OFFICE, level="easy", limit=1)
        task = adapter.load_tasks()[0]
        host = adapter.make_host(task, self.config())
        try:
            ScriptedAgent([
                Action("write", {"path": "solve.py", "content": (
                    "import openpyxl, datetime\n"
                    "wb = openpyxl.load_workbook('input.xlsx')\n"
                    "ws = wb['Data']\n"
                    "ws['B2'] = datetime.date(2025, 1, 3)\n"
                    "ws['B2'].number_format = 'yyyy-mm-dd'\n"
                    "wb.save('edited.xlsx')\n")}),
                Action("shell", {"command": "python solve.py"}),
                Action("submit"),
            ]).run(task, host)
            grade = adapter.grade(task, host)
            self.assertTrue(grade.valid, grade.detail)
            self.assertTrue(grade.passed, grade.detail)
        finally:
            host.cleanup()

    def test_chartqa_sample(self):
        data = CHARTQA / "test" / "test_human.json"
        if not data.is_file():
            self.skipTest("ChartQA checkout not present")
        adapter = ChartQAAdapter(CHARTQA, split="test", limit=1)
        task = adapter.load_tasks()[0]
        label = task.metadata["label"]
        host = adapter.make_host(task, self.config())
        try:
            ScriptedAgent([
                Action("write", {"path": "answer.txt", "content": label}),
                Action("submit"),
            ]).run(task, host)
            grade = adapter.grade(task, host)
            self.assertTrue(grade.valid, grade.detail)
            self.assertTrue(grade.passed, grade.detail)
        finally:
            host.cleanup()

    def test_chartmimic_fixture(self):
        adapter = ChartMimicAdapter(
            judge=lambda target, output: {"score": 4, "issues": []})
        task = adapter.load_tasks()[0]
        host = adapter.make_host(task, self.config())
        try:
            ScriptedAgent([
                Action("write", {"path": "solution.py", "content": (
                    "import matplotlib\n"
                    "matplotlib.use('Agg')\n"
                    "import matplotlib.pyplot as plt\n"
                    "fig, ax = plt.subplots(figsize=(6, 4))\n"
                    "ax.bar(['A', 'B', 'C', 'D'], [3, 7, 5, 2], color='#4C78A8')\n"
                    "ax.set_title('Example Bar Chart')\n"
                    "ax.set_ylabel('Value')\n"
                    "fig.tight_layout()\n"
                    "fig.savefig('output.png', dpi=120)\n")}),
                Action("shell", {"command": "python solution.py"}),
                Action("submit"),
            ]).run(task, host)
            grade = adapter.grade(task, host)
            self.assertTrue(grade.valid, grade.detail)
            self.assertTrue(grade.passed, grade.detail)
        finally:
            host.cleanup()

    def test_ppteval_fixture(self):
        from PIL import Image

        def fake_render(deck, outdir):
            outdir.mkdir(parents=True, exist_ok=True)
            images = []
            for index in range(3):
                path = outdir / f"slide{index}.png"
                Image.new("RGB", (640, 360), "white").save(path)
                images.append(path)
            return images

        def fake_judge(images, prompt):
            return {"content": 4, "design": 4, "coherence": 4, "issues": []}

        adapter = PPTEvalAdapter(render=fake_render, judge=fake_judge)
        task = adapter.load_tasks()[0]
        host = adapter.make_host(task, self.config())
        try:
            ScriptedAgent([
                Action("write", {"path": "make_deck.py", "content": (
                    "import shutil\n"
                    "shutil.copy('template.pptx', 'deck.pptx')\n")}),
                Action("shell", {"command": "python make_deck.py"}),
                Action("submit"),
            ]).run(task, host)
            grade = adapter.grade(task, host)
            self.assertTrue(grade.valid, grade.detail)
            self.assertTrue(grade.passed, grade.detail)
        finally:
            host.cleanup()

    def test_echo_coedit_fixture(self):
        adapter = ECHOAdapter()
        task = adapter.load_tasks()[0]
        host = adapter.make_host(task, self.config())
        try:
            actions = [
                Action("write", {"path": "edit1.py", "content": (
                    "from pptx import Presentation\n"
                    "from pptx.dml.color import RGBColor\n"
                    "prs = Presentation('deck.pptx')\n"
                    "slide = prs.slides[0]\n"
                    "for paragraph in slide.shapes.title.text_frame.paragraphs:\n"
                    "    for run in paragraph.runs:\n"
                    "        run.font.bold = True\n"
                    "        run.font.color.rgb = RGBColor(0xC0, 0, 0)\n"
                    "prs.save('deck.pptx')\n")}),
                Action("shell", {"command": "python edit1.py"}),
                Action("submit"),
                Action("write", {"path": "edit2.py", "content": (
                    "from pptx import Presentation\n"
                    "from pptx.util import Inches\n"
                    "prs = Presentation('deck.pptx')\n"
                    "slide = prs.slides[0]\n"
                    "box = slide.shapes.add_textbox(Inches(1), Inches(4), Inches(6), Inches(1))\n"
                    "box.text_frame.text = 'Prepared by the team'\n"
                    "prs.save('deck.pptx')\n")}),
                Action("shell", {"command": "python edit2.py"}),
                Action("submit"),
            ]
            # ScriptedAgent stops at the first submit; ECHO deliberately rejects
            # a submit to inject the next user instruction, so step manually.
            for action in actions:
                host.step(action)
            grade = adapter.grade(task, host)
            self.assertTrue(grade.valid, grade.detail)
            self.assertTrue(grade.passed, grade.detail)
        finally:
            host.cleanup()

    def test_math_answer_matching(self):
        self.assertTrue(_math_answers_match(r"\boxed{5}", "5"))
        self.assertTrue(_math_answers_match(r"\frac{11}{12}", "11/12"))
        self.assertTrue(_math_answers_match("0.9166667", "11/12"))
        self.assertTrue(_math_answers_match("$5$", "5"))
        self.assertFalse(_math_answers_match("5", "6"))
        self.assertFalse(_math_answers_match(r"\frac{1}{2}", "2/3"))

    def test_math500_fixture(self):
        adapter = MATH500Adapter(limit=1)
        task = adapter.load_tasks()[0]
        host = adapter.make_host(task, self.config())
        try:
            ScriptedAgent([
                Action("write", {"path": "answer.txt",
                                 "content": task.metadata["answer"]}),
                Action("submit"),
            ]).run(task, host)
            grade = adapter.grade(task, host)
            self.assertTrue(grade.valid, grade.detail)
            self.assertTrue(grade.passed, grade.detail)
        finally:
            host.cleanup()

    def test_aime_fixture_rejects_bad_answer(self):
        adapter = AIMEAdapter(limit=1)
        task = adapter.load_tasks()[0]
        host = adapter.make_host(task, self.config())
        try:
            ScriptedAgent([
                Action("write", {"path": "answer.txt", "content": "999"}),
                Action("submit"),
            ]).run(task, host)
            grade = adapter.grade(task, host)
            self.assertTrue(grade.valid, grade.detail)
            self.assertFalse(grade.passed, grade.detail)
        finally:
            host.cleanup()

    def test_putnam_sorry_detection(self):
        self.assertTrue(_proof_has_sorry(
            "theorem x : 1 = 1 := by sorry"))
        self.assertFalse(_proof_has_sorry(
            "theorem x : 1 = 1 := by rfl"))

    def test_putnam_cheat_detection(self):
        self.assertIn("sorry", _proof_cheat("theorem x : 1 = 1 := by sorry"))
        self.assertIn("admit", _proof_cheat("theorem x : 1 = 1 := by admit"))
        self.assertIn("axiom", _proof_cheat(
            "axiom cheat : False\ntheorem x : 1 = 1 := by rfl"))
        self.assertIn("constant", _proof_cheat(
            "constant cheat : False\ntheorem x : 1 = 1 := by rfl"))
        self.assertEqual(_proof_cheat(
            "theorem x : (1 : ℕ) = 1 := by rfl"), "")

    def test_putnam_loader(self):
        if not (PUTNAM / "lean4" / "src").is_dir():
            self.skipTest("PutnamBench checkout not present")
        adapter = PutnamBenchAdapter(PUTNAM, limit=1)
        tasks = adapter.load_tasks()
        self.assertEqual(len(tasks), 1)
        self.assertTrue(tasks[0].task_id.startswith("putnam_"))
        self.assertEqual(tasks[0].metadata["year"], "1962")
        self.assertEqual(tasks[0].metadata["problem"], "a1")

    @unittest.skipUnless(
        os.environ.get("RUN_LEAN_TESTS") == "1",
        "set RUN_LEAN_TESTS=1 (stop the model server first; Mathlib needs "
        "about 5.5 GB of free commit charge)")
    def test_putnam_lean_grade_trivial(self):
        src = PUTNAM / "lean4" / "src"
        if not src.is_dir():
            self.skipTest("PutnamBench checkout not present")
        name = "putnam_zz_smoke"
        source = src / f"{name}.lean"
        backup = source.with_suffix(".lean.bak")
        source.write_text(
            "import Mathlib\n\ntheorem putnam_zz_smoke : (1 : ℕ) = 1 := by\n"
            "  rfl\n", encoding="utf-8")
        adapter = PutnamBenchAdapter(PUTNAM, limit=10000,
                                     min_free_commit_gb=0)
        try:
            task = next(task for task in adapter.load_tasks()
                        if task.task_id == name)
            host = adapter.make_host(task, self.config())
            grade = adapter.grade(task, host)
            self.assertTrue(grade.valid, grade.detail)
            self.assertTrue(grade.passed, grade.detail)
        finally:
            source.unlink(missing_ok=True)
            backup.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
