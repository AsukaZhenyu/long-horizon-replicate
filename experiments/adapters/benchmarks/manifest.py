"""Manifest-driven benchmark adapter backed by a real LocalHost."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List

from contract.types import BenchmarkAdapter, ExperimentConfig, Grade, Host, TaskSpec
from hosts.local import FileCheckVerifier, LocalHost


class ManifestBenchmarkAdapter(BenchmarkAdapter):
    """Load tasks from a JSON manifest.

    Manifest item:
      {"task_id": "...", "instruction": "...",
       "initial_files": {"path": "content"},
       "checks": {"path": "expected content"},
       "metadata": {...}}
    """

    name = "manifest"
    mock_only = False
    real_loader = True
    real_host = True
    real_grader = True

    def __init__(self, manifest: str | Path):
        self.manifest = Path(manifest)
        if not self.manifest.is_file():
            raise FileNotFoundError(self.manifest)
        self._verifiers: Dict[str, FileCheckVerifier] = {}
        self._tasks = self._load()

    def _load(self) -> List[TaskSpec]:
        raw = json.loads(self.manifest.read_text(encoding="utf-8"))
        tasks = []
        for item in raw:
            task = TaskSpec(
                task_id=item["task_id"],
                benchmark=item.get("benchmark", self.name),
                instruction=item["instruction"],
                initial_files=item.get("initial_files", {}),
                metadata=item.get("metadata", {}),
            )
            self._verifiers[task.task_id] = FileCheckVerifier(item.get("checks", {}))
            tasks.append(task)
        return tasks

    def load_tasks(self, path: str | None = None) -> List[TaskSpec]:
        if path is not None:
            self.manifest = Path(path)
            self._tasks = self._load()
        return list(self._tasks)

    def make_host(self, task: TaskSpec, config: ExperimentConfig) -> Host:
        return LocalHost(task, self._verifiers[task.task_id], config)

    def grade(self, task: TaskSpec, host: Host) -> Grade:
        return host.grade()
