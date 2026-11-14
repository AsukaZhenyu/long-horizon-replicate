"""METR cowthello adapter: official task extraction, agent user, official score."""
from __future__ import annotations

import shutil
import subprocess
import unittest

from benchmarks.metr_public import MetrPublicTaskAdapter
from contract.types import Action, ExperimentConfig

IMAGE = "metrevals/public-tasks:cowthello-2.0.2"


def docker_available() -> bool:
    return bool(shutil.which("docker")) and subprocess.run(
        ["docker", "info"], capture_output=True).returncode == 0


def image_available() -> bool:
    return subprocess.run(
        ["docker", "image", "inspect", IMAGE],
        capture_output=True).returncode == 0


class CowthelloAdapterTests(unittest.TestCase):
    @unittest.skipUnless(
        docker_available() and image_available(),
        "cowthello image not available",
    )
    def test_task_loads_and_official_score_returns(self):
        adapter = MetrPublicTaskAdapter()
        tasks = adapter.load_tasks()
        self.assertEqual(tasks[0].task_id, "main_smooth")
        self.assertIn("Cowthello", tasks[0].instruction)
        self.assertEqual(tasks[0].metadata["variant"], "main_smooth")

        config = ExperimentConfig(token_budget=20000, max_actions=10)
        host = adapter.make_host(tasks[0], config)
        try:
            observation = host.step(Action("shell", {
                "command": "id -u; test -x ai_advanced && echo advanced-ok; "
                           "test -f ai_submission && echo submission-ok",
            }))
            self.assertEqual(observation.exit_code, 0, observation.error)
            self.assertIn("1000", observation.output)
            self.assertIn("advanced-ok", observation.output)
            self.assertIn("submission-ok", observation.output)

            grade = adapter.grade(tasks[0], host)
            self.assertTrue(grade.valid, grade.detail)
            self.assertIn("official score=", grade.detail)
            self.assertIsNotNone(host.last_score)
            self.assertGreaterEqual(host.last_score, 0.0)
            self.assertLessEqual(host.last_score, 1.0)
        finally:
            host.cleanup()


if __name__ == "__main__":
    unittest.main()
