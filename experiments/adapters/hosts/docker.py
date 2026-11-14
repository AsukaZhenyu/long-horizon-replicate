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
        try:
            proc = self.host._exec(self.command, timeout=self.timeout)
        except (subprocess.TimeoutExpired, OSError) as exc:
            return Grade(valid=False, passed=False, checks_passed=0,
                         checks_total=0,
                         detail=f"verifier error: {type(exc).__name__}: {exc}")
        passed = proc.returncode == 0
        return Grade(valid=True, passed=passed,
                     checks_passed=1 if passed else 0, checks_total=1,
                     detail=(proc.stdout + proc.stderr)[-2000:])


class DockerHost(Host):
    def __init__(self, task: TaskSpec, config: ExperimentConfig, image: str,
                 verifier_command: str, container_workdir: str = "/app",
                 docker_args: List[str] | None = None, start: bool = True,
                 command: List[str] | None = None):
        self.task = task
        self.config = config
        self.image = image
        self.container_workdir = container_workdir
        self.name = f"adapter-{uuid.uuid4().hex[:10]}"
        self._actions: List[Action] = []
        self._tokens = 0
        self.grade_calls = 0
        self.submitted = False
        # Optional benchmark-side submission validation.  It may return an
        # error string to reject the submit without revealing hidden checks.
        self.submit_guard = None
        if start:
            run_command = ["docker", "run", "-d", "--name", self.name,
                           "--workdir", container_workdir]
            run_command.extend(docker_args or [])
            run_command.extend([image, *(command or ["sleep", "infinity"])])
            subprocess.run(run_command, check=True, capture_output=True, encoding="utf-8", errors="replace")
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
        # Benchmark output is arbitrary bytes; never let the locale codec
        # (GBK on this Windows host) crash the subprocess reader thread.
        return subprocess.run(
            ["docker", "exec", "-i", self.name, "sh", "-c", command],
            capture_output=True, encoding="utf-8", errors="replace",
            timeout=timeout, input=input_text,
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
            command, capture_output=True, encoding="utf-8", errors="replace", timeout=timeout,
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
            check=True, capture_output=True, encoding="utf-8", errors="replace",
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
        try:
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
                if self.submit_guard is not None:
                    error = self.submit_guard()
                    if error:
                        return Observation(error=str(error), exit_code=1)
                self.submitted = True
                return Observation(output="submitted")
            return Observation(error=f"unknown action {action.kind}", exit_code=1)
        except subprocess.TimeoutExpired as exc:
            return Observation(error=f"command timed out: {exc}", exit_code=124)
        except OSError as exc:
            return Observation(error=f"host error: {exc}", exit_code=1)

    def submit(self) -> Observation:
        return self.step(Action("submit"))

    def grade(self) -> Grade:
        self.grade_calls += 1
        return self.verifier.grade()

    def cleanup(self) -> None:
        subprocess.run(["docker", "rm", "-f", self.name],
                       capture_output=True, encoding="utf-8", errors="replace")
