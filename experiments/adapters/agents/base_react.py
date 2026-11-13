"""A minimal OpenAI-compatible terminal agent.

It is the base control loop: one shell action per turn, then submit.  It only
talks to the Host; it cannot read hidden checks or call grade().
"""
from __future__ import annotations

import json
import re
import urllib.request
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List

from contract.types import Action, Host, NativeAgent, TaskSpec

ACTION_PROTOCOL = """Return exactly one JSON object per turn, with no markdown.
To run a shell command: {"command": "..."}
To submit the result: {"final": "short report"}
Use the available terminal to inspect the workspace, make the required
artifact, verify it, and then submit."""

SYSTEM = "You are a terminal coding agent. Work in the current directory.\n" + ACTION_PROTOCOL


@dataclass(frozen=True)
class ModelResponse:
    content: str
    total_tokens: int = 0


class ModelClient(ABC):
    @abstractmethod
    def complete(self, messages: List[dict], **kwargs) -> ModelResponse:
        raise NotImplementedError


class HTTPModelClient(ModelClient):
    def __init__(self, base_url: str, model: str, timeout: int = 300):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout

    def complete(self, messages: List[dict], **kwargs) -> ModelResponse:
        temperature = kwargs.get("temperature")
        max_tokens = kwargs.get("max_tokens")
        payload = json.dumps({
            "model": self.model,
            "messages": messages,
            "temperature": 0.2 if temperature is None else temperature,
            "max_tokens": 2048 if max_tokens is None else max_tokens,
        }).encode("utf-8")
        request = urllib.request.Request(
            self.base_url + "/v1/chat/completions", data=payload,
            headers={"Content-Type": "application/json"}, method="POST",
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
        message = data["choices"][0]["message"]
        usage = data.get("usage") or {}
        return ModelResponse(
            content=message.get("content") or "",
            total_tokens=int(usage.get("total_tokens") or 0),
        )


class ListModelClient(ModelClient):
    """Deterministic client for tests."""

    def __init__(self, responses: List[ModelResponse]):
        self.responses = list(responses)

    def complete(self, messages: List[dict], **kwargs) -> ModelResponse:
        if not self.responses:
            return ModelResponse(content='{"final":"out of responses"}')
        return self.responses.pop(0)


def parse_action(text: str) -> dict:
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("no JSON object")
    return json.loads(text[start:end + 1])


class BaseReactAgent(NativeAgent):
    def __init__(self, client: ModelClient, max_steps: int = 40,
                 system_prompt: str | None = None):
        self.client = client
        self.max_steps = max_steps
        self.system_prompt = system_prompt or SYSTEM

    def run(self, task: TaskSpec, host: Host) -> None:
        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": task.instruction},
        ]
        for _ in range(self.max_steps):
            response = self.client.complete(messages)
            try:
                host.charge_tokens(response.total_tokens)  # type: ignore[attr-defined]
            except RuntimeError:
                return
            messages.append({"role": "assistant", "content": response.content})
            try:
                action = parse_action(response.content)
            except (ValueError, json.JSONDecodeError) as exc:
                messages.append({"role": "user", "content": f"Invalid JSON: {exc}"})
                continue
            if "command" in action:
                observation = host.step(Action("shell", {"command": str(action["command"])}))
                messages.append({"role": "user", "content":
                                 f"exit={observation.exit_code}\n{observation.output}\n{observation.error}"})
                continue
            if "final" in action:
                host.submit()
                return
            messages.append({"role": "user", "content": "Use command or final."})
