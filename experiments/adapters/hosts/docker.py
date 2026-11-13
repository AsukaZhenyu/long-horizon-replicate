"""A real Docker host: one container per task, shell/read/write/submit."""
from __future__ import annotations

import subprocess
import uuid
from pathlib import Path
from typing import Dict, List

from contract.types import (
    Action, ExperimentConfig, Grade, Host, Observation, TaskSpec,
)


class ContainerCommandVerifier:
    def __init__(self, host: "DockerHost", command: str, timeout: int = 120):
        self.host = host
        self.command = command
        self.timeout = timeout

    def grade(self) -> Grade:
        proc = self.host._exec(self.command, timeout=self.timeout)
        passed = proc.returncode == 0
        return Grade(valid=True, passed=passed,
                     checks_passed=1 if passed else 0, checks_total=1,
                     detail=(proc.stdout + proc.stderr)[-2000:])


class DockerHost(Host):
    def __init__(self, task: TaskSpec, config: ExperimentConfig, image: str,
                 verifier_command: str, container_workdir: str = "/app",
                 docker_args: List[str] | None = None, start: bool = True):
        self.task = task
        self.config = config
        self.image = image
        self.container_workdir = container_workdir
        self.name = f"adapter-{uuid.uuid4().hex[:10]}"
        self._actions: List[Action] = []
        self._tokens = 0
        self.grade_calls = 0
        self.submitted = False
        if start:
            command = ["docker", "run", "-d", "--name", self.name,
                       "--workdir", container_workdir]
            command.extend(docker_args or [])
            command.extend([image, "sleep", "infinity"])
            subprocess.run(command, check=True, capture_output=True, text=True)
        self.verifier = ContainerCommandVerifier(self, verifier_command)
        for path, content in task.initial_files.items():
            self.step(Action("write", {"path": path, "content": content}))

    @property
    def tokens_used(self) -> int:
        return self._tokens

    @property
    def actions(self) -> List[Action]:
        return list(self._actions)

    def charge_tokens(self, n: int) -> None:
        self._tokens += max(0, int(n))
        if self._tokens > self.config.token_budget:
            raise RuntimeError(f"token budget exceeded: {self._tokens}")

    def _exec(self, command: str, timeout: int = 120, input_text: str | None = None):
        return subprocess.run(
            ["docker", "exec", "-i", self.name, "sh", "-c", command],
            capture_output=True, text=True, timeout=timeout, input=input_text,
        )

    def exec(self, argv: List[str], timeout: int = 120,
             env: Dict[str, str] | None = None,
             workdir: str | None = None):
        """Run a command without an intervening shell."""
        command = ["docker", "exec"]
        if workdir:
            command.extend(["-w", workdir])
        for key, value in (env or {}).items():
            command.extend(["-e", f"{key}={value}"])
        command.append(self.name)
        command.extend(argv)
        return subprocess.run(
            command, capture_output=True, text=True, timeout=timeout,
        )

    def copy_in(self, source: Path, destination: str) -> None:
        """Copy a local file or directory into the container.

        For a directory, its *contents* are copied, matching ``docker cp
        source/. container:destination``.
        """
        src = Path(source)
        if src.is_dir():
            src_arg = str(src) + "/."
        else:
            src_arg = str(src)
        subprocess.run(
            ["docker", "cp", src_arg, f"{self.name}:{destination}"],
            check=True, capture_output=True, text=True,
        )

    def read_container_file(self, path: str, timeout: int = 30) -> str | None:
        proc = self._exec(f"cat '{path}'", timeout=timeout)
        return proc.stdout if proc.returncode == 0 else None

    def _path(self, path: str) -> str:
        return f"{self.container_workdir.rstrip('/')}/{path.lstrip('/')}"

    def step(self, action: Action) -> Observation:
        if len(self._actions) >= self.config.max_actions:
            return Observation(error="max actions reached", exit_code=1)
        self._actions.append(action)
        if action.kind == "write":
            target = self._path(action.payload.get("path", ""))
            command = f"mkdir -p \"$(dirname '{target}')\" && cat > '{target}'"
            proc = self._exec(command, input_text=str(action.payload.get("content", "")))
            return Observation(output=proc.stdout, error=proc.stderr, exit_code=proc.returncode)
        if action.kind == "read":
            proc = self._exec(f"cat '{self._path(action.payload.get('path',''))}'")
            return Observation(output=proc.stdout, error=proc.stderr, exit_code=proc.returncode)
        if action.kind == "shell":
            proc = self._exec(str(action.payload.get("command", "")))
            return Observation(output=proc.stdout[-8000:], error=proc.stderr[-8000:],
                               exit_code=proc.returncode)
        if action.kind == "submit":
            self.submitted = True
            return Observation(output="submitted")
        return Observation(error=f"unknown action {action.kind}", exit_code=1)

    def submit(self) -> Observation:
        return self.step(Action("submit"))

    def grade(self) -> Grade:
        self.grade_calls += 1
        return self.verifier.grade()

    def cleanup(self) -> None:
        subprocess.run(["docker", "rm", "-f", self.name],
                       capture_output=True, text=True)
