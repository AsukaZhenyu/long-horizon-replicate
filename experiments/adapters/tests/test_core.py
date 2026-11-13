"""CORE-Bench loader, official grading, and Docker host smoke."""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from benchmarks.core import CoreBenchAdapter, DEFAULT_DATASET, DEFAULT_PROMPTS
from benchmarks.core_grading import eval_result_json
from contract.types import Action, ExperimentConfig, ScriptedAgent
from methods.adapters import BaseAgentAdapter

GOLD = [
    {"What is the numeric answer?": 10.0, "What is the label?": "Foo",
     "What is the list?": [1, 2]},
    {"What is the numeric answer?": 12.0, "What is the label?": "foo",
     "What is the list?": [1, 2]},
    {"What is the numeric answer?": 11.0, "What is the label?": "FOO",
     "What is the list?": [1, 2]},
]


def docker_available() -> bool:
    return bool(shutil.which("docker")) and subprocess.run(
        ["docker", "info"], capture_output=True).returncode == 0


def local_image() -> str | None:
    proc = subprocess.run(
        ["docker", "images", "--format", "{{.Repository}}:{{.Tag}}"],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        return None
    images = [line.strip() for line in proc.stdout.splitlines()]
    for name in ("alpine:latest", "busybox:latest"):
        if name in images:
            return name
    return None


class CoreGradingTests(unittest.TestCase):
    def test_numeric_prediction_interval(self):
        grade = eval_result_json(GOLD, {"What is the numeric answer?": 11})
        self.assertEqual(grade.correct_written_answers, 1)
        self.assertEqual(grade.total_written_questions, 3)
        self.assertFalse(grade.passed)

    def test_string_and_list(self):
        grade = eval_result_json(GOLD, {
            "What is the label?": "foo",
            "What is the list?": [1, 2],
        })
        self.assertEqual(grade.correct_written_answers, 2)
        self.assertEqual(grade.total_written_questions, 3)
        self.assertFalse(grade.passed)

    def test_all_correct_passes(self):
        grade = eval_result_json(GOLD, {
            "What is the numeric answer?": 11,
            "What is the label?": "foo",
            "What is the list?": [1, 2],
        })
        self.assertTrue(grade.passed)
        self.assertEqual(grade.correct_questions, 3)
        self.assertEqual(grade.total_questions, 3)

    def test_numeric_outside_interval_fails(self):
        grade = eval_result_json(GOLD, {
            "What is the numeric answer?": 100,
            "What is the label?": "foo",
            "What is the list?": [1, 2],
        })
        self.assertEqual(grade.correct_written_answers, 2)
        self.assertFalse(grade.passed)

    def test_missing_answer_does_not_pass(self):
        grade = eval_result_json(GOLD, {})
        self.assertEqual(grade.correct_questions, 0)
        self.assertEqual(grade.total_questions, 3)
        self.assertFalse(grade.passed)


class CoreLoaderTests(unittest.TestCase):
    @unittest.skipUnless(DEFAULT_DATASET.is_file() and DEFAULT_PROMPTS.is_file(),
                         "CORE-Bench checkout not present")
    def test_train_split_loads(self):
        adapter = CoreBenchAdapter(download=False)
        tasks = adapter.load_tasks()
        self.assertEqual(len(tasks), 45)
        sample = tasks[0]
        self.assertTrue(sample.task_id.startswith("capsule-"))
        self.assertIn("report.json", sample.instruction)
        self.assertTrue(sample.metadata["questions"])
        self.assertEqual(sample.metadata["level"], "codeocean_easy")
        # Gold results must not be reachable from the method-facing TaskSpec.
        self.assertNotIn("results", sample.metadata)
        self.assertNotIn("gold", sample.metadata)


class CoreDockerTests(unittest.TestCase):
    def _synthetic(self, tmp: str, image: str):
        root = Path(tmp) / "core"
        prompts = root / "benchmark" / "benchmark_prompts.json"
        prompts.parent.mkdir(parents=True)
        prompts.write_text(json.dumps({
            "codeocean_easy": "Read the capsule results and answer {json_fields}.",
            "codeocean_medium": "Reproduce {task_prompt}; answer {json_fields}.",
            "codeocean_hard": "Reproduce {task_prompt}; answer {json_fields}.",
        }), encoding="utf-8")
        dataset = root / "benchmark" / "dataset" / "core_train.json"
        dataset.parent.mkdir(parents=True)
        dataset.write_text(json.dumps([{
            "field": "Test",
            "language": "Python",
            "capsule_title": "Synthetic capsule",
            "capsule_id": "capsule-test",
            "capsule_doi": "",
            "task_prompt": "Read the answer.",
            "results": [
                {"What is the answer?": 42},
                {"What is the answer?": 42},
                {"What is the answer?": 42},
            ],
        }]), encoding="utf-8")
        capsules = root / "capsules"
        results = capsules / "capsule-test" / "results"
        results.mkdir(parents=True)
        (results / "answer.txt").write_text("42\n", encoding="utf-8")
        (capsules / "capsule-test" / "REPRODUCING.md").write_text(
            "no code needed\n", encoding="utf-8")
        env = capsules / "capsule-test" / "environment"
        env.mkdir()
        (env / "Dockerfile").write_text("FROM scratch\n", encoding="utf-8")
        code = capsules / "capsule-test" / "code"
        code.mkdir()
        (code / "run.sh").write_text("echo hi\n", encoding="utf-8")
        adapter = CoreBenchAdapter(
            root=root, dataset=dataset, level="codeocean_easy",
            capsule_dir=capsules, image=image, download=False,
        )
        return adapter, adapter.load_tasks()[0]

    @unittest.skipUnless(docker_available(), "docker daemon not available")
    def test_report_round_trip(self):
        image = local_image()
        if image is None:
            self.skipTest("no local alpine/busybox image")
        with tempfile.TemporaryDirectory() as tmp:
            adapter, task = self._synthetic(tmp, image)
            config = ExperimentConfig(token_budget=1000, max_actions=20)

            host = adapter.make_host(task, config)
            try:
                agent = BaseAgentAdapter(ScriptedAgent([
                    Action("write", {"path": "report.json", "content": json.dumps(
                        {"What is the answer?": 42})}),
                    Action("submit"),
                ]))
                agent.run(task, host)
                grade = adapter.grade(task, host)
                self.assertTrue(grade.valid, grade.detail)
                self.assertTrue(grade.passed, grade.detail)
                self.assertEqual(grade.checks_passed, 1)
            finally:
                host.cleanup()

    @unittest.skipUnless(docker_available(), "docker daemon not available")
    def test_missing_report_is_a_valid_failure(self):
        image = local_image()
        if image is None:
            self.skipTest("no local alpine/busybox image")
        with tempfile.TemporaryDirectory() as tmp:
            adapter, task = self._synthetic(tmp, image)
            config = ExperimentConfig(token_budget=1000, max_actions=20)
            host = adapter.make_host(task, config)
            try:
                agent = BaseAgentAdapter(ScriptedAgent([Action("submit")]))
                agent.run(task, host)
                grade = adapter.grade(task, host)
                self.assertTrue(grade.valid, grade.detail)
                self.assertFalse(grade.passed, grade.detail)
                self.assertEqual(grade.checks_passed, 0)
            finally:
                host.cleanup()


if __name__ == "__main__":
    unittest.main()
