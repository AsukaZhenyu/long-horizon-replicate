"""Recuris native loop: fixed Skill Memory + optional completion gate.

This is the m0 / m0-gate half of Recuris, the same mechanism the TB8 adapter
used.  The method's own ``TerminalSkillBridge`` renders working memory before
each model call, receives terminal receipts, and can bounce a premature final
answer through the package's ``DRAFT_READY`` checkers.  The meta-agent patch
loop (``tta``) is not implemented here.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Dict, List

from agents.base_react import SYSTEM, ModelClient, parse_action
from contract.types import Action, Host, NativeAgent, Observation, TaskSpec

REPO = Path(__file__).resolve().parents[3]
RECURIS_SRC = REPO / ".cache" / "upstream" / "recuris" / "src"
DEFAULT_MEMORY = REPO / ".cache" / "upstream" / "recuris" / "skill_memories" / "tb21_seed"

if RECURIS_SRC.is_dir():
    sys.path.insert(0, str(RECURIS_SRC))


def _bridge_class():
    try:
        from recuris.adapters.tb21.runtime_bridge import TerminalSkillBridge
    except Exception as exc:  # pragma: no cover - depends on optional checkout
        raise RuntimeError(
            "Recuris checkout is not available; clone Gen-Verse/Recuris into "
            f"{RECURIS_SRC.parent}") from exc
    return TerminalSkillBridge


class RecurisAgent(NativeAgent):
    """Run a terminal task with Recuris working memory.

    ``completion_gate=False`` reproduces m0 (memory only); ``True`` reproduces
    m0-gate (memory + ``check_completion`` bounce).
    """

    name = "recuris"
    mechanism = ("memory_retrieve", "memory_update", "completion_gate")

    def __init__(self, client: ModelClient, memory: str | Path | None = None,
                 max_steps: int = 40, completion_gate: bool = True,
                 max_bounces: int = 3):
        self.client = client
        self.memory = Path(memory or DEFAULT_MEMORY)
        self.max_steps = max_steps
        self.completion_gate = completion_gate
        self.max_bounces = max_bounces
        self.counters: Dict[str, int] = {}
        self.bounces = 0
        self.turns = 0

    def run(self, task: TaskSpec, host: Host) -> None:
        if not self.memory.is_dir():
            raise FileNotFoundError(f"Recuris memory package missing: {self.memory}")
        bridge = _bridge_class()(str(self.memory), "")
        bridge.start(task.instruction)
        messages: List[dict] = [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": task.instruction},
        ]
        correction = ""
        for _ in range(self.max_steps):
            prefix = SYSTEM + (("\n\n" + correction) if correction else "")
            messages[0]["content"] = bridge.prepare_prompt(prefix)
            response = self.client.complete(messages)
            self._charge(host, response.total_tokens)
            self.turns += 1
            messages.append({"role": "assistant", "content": response.content})
            try:
                action = parse_action(response.content)
            except (ValueError, TypeError) as exc:  # json.JSONDecodeError is a ValueError
                messages.append({"role": "user", "content": f"Invalid JSON: {exc}"})
                continue
            if "command" in action:
                command = str(action["command"])
                observation = host.step(Action("shell", {"command": command}))
                bridge.observe_commands(
                    [SimpleNamespace(keystrokes=command)],
                    (observation.output or "") + (observation.error or ""),
                    timed_out=False,
                )
                messages.append({"role": "user", "content": self._render(observation)})
                continue
            if "final" in action:
                if self.completion_gate and self.bounces < self.max_bounces:
                    bounce = bridge.check_completion([], str(action["final"]))
                    if bounce is not None:
                        self.bounces += 1
                        correction = bounce.correction or bounce.reason
                        messages.append({
                            "role": "user",
                            "content": "The completion gate rejected that final answer. "
                                       "Address the correction and continue.",
                        })
                        continue
                host.submit()
                break
            messages.append({"role": "user", "content": "Use command or final."})
        self.counters = dict(bridge.state.fp.counters)

    @staticmethod
    def _charge(host: Host, tokens: int) -> None:
        charge = getattr(host, "charge_tokens", None)
        if callable(charge):
            charge(tokens)

    @staticmethod
    def _render(observation: Observation) -> str:
        return f"exit={observation.exit_code}\n{observation.output}\n{observation.error}"
