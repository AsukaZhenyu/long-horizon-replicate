"""LHTB 2.0 official task-format loader test."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from benchmarks.lhtb import LHTBBenchmarkAdapter


TOML_TEXT = """schema_version = "1.2"
artifacts = ["/app/workspace"]

[task]
name = "silrlab/demo__01"

[agent]
continue_until_timeout = true
timeout_sec = 5400

[environment]
docker_image = "example/image@sha256:abc"
"""


class LHTBLoaderTests(unittest.TestCase):
    def test_official_task_format(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "lhtb"
            task_dir = root / "tasks-2.0" / "demo__01"
            task_dir.mkdir(parents=True)
            (task_dir / "instruction.md").write_text("do the task", encoding="utf-8")
            (task_dir / "task.toml").write_text(TOML_TEXT, encoding="utf-8")
            adapter = LHTBBenchmarkAdapter(root)
            tasks = adapter.load_tasks()
            self.assertEqual(len(tasks), 1)
            self.assertEqual(tasks[0].task_id, "demo__01")
            self.assertEqual(tasks[0].instruction, "do the task")
            self.assertEqual(tasks[0].metadata["docker_image"],
                             "example/image@sha256:abc")
            self.assertEqual(tasks[0].metadata["timeout_sec"], 5400)
            self.assertFalse(adapter.real_grader)


if __name__ == "__main__":
    unittest.main()
