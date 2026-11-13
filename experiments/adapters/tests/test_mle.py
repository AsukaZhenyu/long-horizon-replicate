"""MLE-bench loader, medal thresholds, and synthetic submission round-trip.

Real MLE-bench data needs Kaggle credentials and the official ``mlebench``
package (pandas et al.).  The loader test uses the public registry; the
grading/host tests use a synthetic competition and the dependency-free
accuracy metric so the adapter contract is exercised offline.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from benchmarks.mle import DEFAULT_ROOT, MLEBenchAdapter
from benchmarks.mle_grading import (
    accuracy_metric, is_lower_better, rank_score, read_leaderboard,
)
from contract.types import Action, ExperimentConfig, ScriptedAgent
from methods.adapters import BaseAgentAdapter


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


class MLEMedalTests(unittest.TestCase):
    def test_thresholds_and_medals(self):
        scores = [1.0, 0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3, 0.2, 0.1]
        self.assertFalse(is_lower_better(scores))
        gold = rank_score(1.0, scores)
        self.assertTrue(gold.gold_medal)
        self.assertTrue(gold.any_medal)
        silver = rank_score(0.9, scores)
        self.assertTrue(silver.silver_medal)
        self.assertFalse(silver.gold_medal)
        bronze = rank_score(0.7, scores)
        self.assertTrue(bronze.bronze_medal)
        none = rank_score(0.65, scores)
        self.assertFalse(none.any_medal)
        self.assertTrue(none.above_median)
        self.assertFalse(rank_score(0.2, scores).above_median)

    def test_lower_is_better(self):
        scores = [0.1, 0.2, 0.3, 0.4, 0.5]
        self.assertTrue(is_lower_better(scores))
        report = rank_score(0.1, scores)
        self.assertTrue(report.gold_medal)

    def test_leaderboard_csv(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "leaderboard.csv"
            path.write_text("team,score\nA,1.0\nB,0.5\n", encoding="utf-8")
            self.assertEqual(read_leaderboard(path), [1.0, 0.5])


class MLELoaderTests(unittest.TestCase):
    @unittest.skipUnless(DEFAULT_ROOT.is_dir(), "MLE-bench checkout not present")
    def test_low_split_loads(self):
        with tempfile.TemporaryDirectory() as tmp:
            adapter = MLEBenchAdapter(data_dir=Path(tmp), metric=None)
            tasks = adapter.load_tasks()
            self.assertEqual(len(tasks), 22)
            sample = tasks[0]
            self.assertTrue(sample.instruction.startswith("You are participating"))
            self.assertIn("Competition:", sample.instruction)
            self.assertTrue(sample.metadata["competition_id"])
            self.assertTrue(sample.metadata["metric_name"])
            self.assertTrue(adapter.dataset_missing)
            self.assertFalse(adapter.real_grader)


class MLEDockerTests(unittest.TestCase):
    def _synthetic(self, tmp: str, image: str,
                   enforce_submission: bool = False):
        root = Path(tmp) / "mle"
        (root / "environment").mkdir(parents=True)
        (root / "environment" / "instructions.txt").write_text(
            "You are participating in *MLE-bench*.\n", encoding="utf-8")
        comp = root / "mlebench" / "competitions" / "synthetic"
        comp.mkdir(parents=True)
        (comp / "description.md").write_text(
            "Predict the label for each test row.\n", encoding="utf-8")
        (comp / "config.yaml").write_text(
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
            "preparer: benchmark.synthetic:prepare\n",
            encoding="utf-8",
        )
        (comp / "leaderboard.csv").write_text(
            "team,score\nA,1.0\nB,0.8\nC,0.6\nD,0.4\nE,0.2\n",
            encoding="utf-8",
        )
        data = root / "data"
        public = data / "synthetic" / "prepared" / "public"
        private = data / "synthetic" / "prepared" / "private"
        public.mkdir(parents=True)
        private.mkdir(parents=True)
        (public / "test.csv").write_text("id\n1\n2\n", encoding="utf-8")
        (public / "sample_submission.csv").write_text(
            "id,prediction\n1,a\n2,b\n", encoding="utf-8")
        (private / "answers.csv").write_text(
            "id,answer\n1,a\n2,b\n", encoding="utf-8")
        adapter = MLEBenchAdapter(
            root=root, split="all", data_dir=data, image=image,
            metric=accuracy_metric, enforce_submission=enforce_submission,
        )
        return adapter, adapter.load_tasks()[0]

    @unittest.skipUnless(docker_available(), "docker daemon not available")
    def test_perfect_submission_earns_medal(self):
        image = local_image()
        if image is None:
            self.skipTest("no local alpine/busybox image")
        with tempfile.TemporaryDirectory() as tmp:
            adapter, task = self._synthetic(tmp, image)
            config = ExperimentConfig(token_budget=1000, max_actions=20)
            host = adapter.make_host(task, config)
            try:
                agent = BaseAgentAdapter(ScriptedAgent([
                    Action("write", {"path": "submission/submission.csv",
                                     "content": "id,prediction\n1,a\n2,b\n"}),
                    Action("submit"),
                ]))
                agent.run(task, host)
                grade = adapter.grade(task, host)
                self.assertTrue(grade.valid, grade.detail)
                self.assertTrue(grade.passed, grade.detail)
                self.assertIn("score=1.0", grade.detail)
            finally:
                host.cleanup()

    @unittest.skipUnless(docker_available(), "docker daemon not available")
    def test_wrong_submission_has_no_medal(self):
        image = local_image()
        if image is None:
            self.skipTest("no local alpine/busybox image")
        with tempfile.TemporaryDirectory() as tmp:
            adapter, task = self._synthetic(tmp, image)
            config = ExperimentConfig(token_budget=1000, max_actions=20)
            host = adapter.make_host(task, config)
            try:
                agent = BaseAgentAdapter(ScriptedAgent([
                    Action("write", {"path": "submission/submission.csv",
                                     "content": "id,prediction\n1,c\n2,d\n"}),
                    Action("submit"),
                ]))
                agent.run(task, host)
                grade = adapter.grade(task, host)
                self.assertTrue(grade.valid, grade.detail)
                self.assertFalse(grade.passed, grade.detail)
                self.assertIn("score=0.0", grade.detail)
            finally:
                host.cleanup()

    @unittest.skipUnless(docker_available(), "docker daemon not available")
    def test_submit_guard_is_off_by_default(self):
        image = local_image()
        if image is None:
            self.skipTest("no local alpine/busybox image")
        with tempfile.TemporaryDirectory() as tmp:
            adapter, task = self._synthetic(tmp, image)
            config = ExperimentConfig(token_budget=1000, max_actions=20)
            host = adapter.make_host(task, config)
            try:
                self.assertIsNone(host.submit_guard)
                accepted = host.step(Action("submit"))
                self.assertEqual(accepted.exit_code, 0, accepted.error)
                self.assertTrue(host.submitted)
            finally:
                host.cleanup()

    @unittest.skipUnless(docker_available(), "docker daemon not available")
    def test_submit_guard_requires_submission(self):
        image = local_image()
        if image is None:
            self.skipTest("no local alpine/busybox image")
        with tempfile.TemporaryDirectory() as tmp:
            adapter, task = self._synthetic(tmp, image, enforce_submission=True)
            config = ExperimentConfig(token_budget=1000, max_actions=20)
            host = adapter.make_host(task, config)
            try:
                rejected = host.step(Action("submit"))
                self.assertNotEqual(rejected.exit_code, 0)
                self.assertIn("submission.csv", rejected.error)
                self.assertFalse(host.submitted)
                host.step(Action("write", {
                    "path": "submission/submission.csv",
                    "content": "id,prediction\n1,a\n2,b\n",
                }))
                accepted = host.step(Action("submit"))
                self.assertEqual(accepted.exit_code, 0, accepted.error)
                self.assertTrue(host.submitted)
                grade = adapter.grade(task, host)
                self.assertTrue(grade.valid, grade.detail)
                self.assertTrue(grade.passed, grade.detail)
            finally:
                host.cleanup()

    @unittest.skipUnless(docker_available(), "docker daemon not available")
    def test_missing_submission_is_a_valid_failure(self):
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
                self.assertIn("missing", grade.detail)
            finally:
                host.cleanup()


if __name__ == "__main__":
    unittest.main()
