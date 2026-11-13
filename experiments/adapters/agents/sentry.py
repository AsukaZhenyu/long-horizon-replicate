"""Sentry native loop: official SentryRunner around a terminal actor.

The actor decodes one ``{"command"}`` / ``{"final"}`` action per turn.  Every
turn is handed to the unchanged Sentry core (``SentryRunner.step``), which can
diagnose a failure, inject a rescue prompt, verify an escape after H cycles,
and write a verified experience to the playbook.  The loop only translates the
terminal action/observation schema; it does not reimplement detector,
verifier, updater or routing.
"""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path
from typing import Any, List

from agents.base_react import SYSTEM, ModelClient, parse_action
from contract.types import Action, Host, NativeAgent, Observation, TaskSpec

REPO = Path(__file__).resolve().parents[3]
SENTRY_SRC = REPO / ".cache" / "upstream" / "sentry"

if SENTRY_SRC.is_dir():
    sys.path.insert(0, str(SENTRY_SRC))

ACTION_SCHEMA = (
    'Return exactly one JSON object. To run a shell command: '
    '{"reasoning": "...", "command": "..."}. To submit: '
    '{"reasoning": "...", "final": "..."}.'
)


def _sentry_imports():
    try:
        from Sentry import SentryConfig, SentryRunner, agent_step_from_parts
        from Sentry.config import LoggingConfig
    except Exception as exc:  # pragma: no cover - depends on optional checkout
        raise RuntimeError(
            "Sentry checkout is not available; clone nuglifeleoji/Sentry into "
            f"{SENTRY_SRC}") from exc
    return SentryConfig, SentryRunner, agent_step_from_parts, LoggingConfig


class SentryModelAdapter:
    """Adapt ModelClient to the callable/generate interface Sentry expects."""

    def __init__(self, client: ModelClient, charge=None, model: str = "Qwen3.5-9B"):
        self.client = client
        self.model = model
        self.charge = charge
        self.phases: Counter = Counter()

    def generate(self, prompt: str, **kwargs: Any) -> str:
        for head, name in (
            ("[SENTRY DETECTOR]", "detector"),
            ("[SENTRY ESCAPE VERIFIER]", "verifier"),
            ("[SENTRY PLAYBOOK UPDATE]", "updater"),
        ):
            if prompt.startswith(head):
                self.phases[name] += 1
                break
        # Sentry's auxiliary decoding (temperature/max_tokens) is forwarded to
        # the client.  response_format is deliberately not forwarded: the local
        # llama.cpp endpoint used here does not guarantee JSON mode, and the
        # prompt already fixes the output schema.
        response = self.client.complete(
            [{"role": "user", "content": prompt}],
            temperature=kwargs.get("temperature"),
            max_tokens=kwargs.get("max_tokens"),
        )
        if self.charge is not None:
            self.charge(response.total_tokens)
        return response.content


class SentryAgent(NativeAgent):
    name = "sentry"
    mechanism = ("detector", "verifier", "updater")

    def __init__(self, client: ModelClient, max_steps: int = 40,
                 config=None):
        self.client = client
        self.max_steps = max_steps
        self.config = config
        self.runner = None
        self.events: List[dict] = []
        self.phases: Counter = Counter()
        self.steps = 0

    def run(self, task: TaskSpec, host: Host) -> None:
        SentryConfig, SentryRunner, agent_step_from_parts, LoggingConfig = _sentry_imports()
        config = self.config or SentryConfig(logging=LoggingConfig(enabled=False))
        model = SentryModelAdapter(
            self.client,
            charge=getattr(host, "charge_tokens", None),
            model=config.model.model,
        )
        self.runner = SentryRunner(
            model=model, config=config, capture_runtime_events=True,
        )
        self.runner.start_task(objective=task.instruction, action_schema=ACTION_SCHEMA)
        messages: List[dict] = [
            {"role": "system", "content": SYSTEM + "\n\n" + ACTION_SCHEMA},
            {"role": "user", "content": task.instruction},
        ]
        try:
            for step_id in range(self.max_steps):
                self.steps = step_id + 1
                response = self.client.complete(messages)
                self._charge(host, response.total_tokens)
                messages.append({"role": "assistant", "content": response.content})
                try:
                    action = parse_action(response.content)
                except (ValueError, TypeError) as exc:
                    step = agent_step_from_parts(
                        step_id=step_id,
                        reasoning="",
                        raw_action=response.content,
                        parsed_ok=False,
                        parser_error=str(exc),
                        observation="",
                    )
                    rescue = self.runner.step(step)
                    messages.append({
                        "role": "user",
                        "content": rescue.prompt_text if rescue is not None
                        else f"Invalid JSON: {exc}",
                    })
                    continue
                if "command" in action:
                    command = str(action["command"])
                    observation = host.step(Action("shell", {"command": command}))
                    rendered = self._render(observation)
                    step = agent_step_from_parts(
                        step_id=step_id,
                        reasoning=str(action.get("reasoning", "")),
                        raw_action=response.content,
                        tool_name="bash",
                        tool_args={"command": command},
                        observation=rendered,
                        accepted_by_environment=True,
                    )
                    rescue = self.runner.step(step)
                    messages.append({"role": "user", "content": rendered})
                    if rescue is not None:
                        messages.append({"role": "user", "content": rescue.prompt_text})
                    continue
                if "final" in action:
                    step = agent_step_from_parts(
                        step_id=step_id,
                        reasoning=str(action.get("reasoning", "")),
                        raw_action=response.content,
                        observation="",
                        accepted_by_environment=True,
                    )
                    self.runner.step(step, terminal=True)
                    host.submit()
                    return
                messages.append({"role": "user", "content": "Use command or final."})
        finally:
            self.runner.finalize()
            self.events = self.runner.guard.drain_runtime_events()
            self.phases = model.phases

    @staticmethod
    def _charge(host: Host, tokens: int) -> None:
        charge = getattr(host, "charge_tokens", None)
        if callable(charge):
            charge(tokens)

    @staticmethod
    def _render(observation: Observation) -> str:
        return f"exit={observation.exit_code}\n{observation.output}\n{observation.error}"
