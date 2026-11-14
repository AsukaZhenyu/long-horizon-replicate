"""Trajectory recording for real runs.

The recorder is a transparent wrapper: it logs model requests/responses,
actions and observations, and detects a repeated action/observation loop.  It
does not change the method's loop or the host's grading.
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, List

from agents.base_react import ModelClient, ModelRequestError, ModelResponse
from contract.types import Action, Grade, Host, Observation


class LoopDetected(RuntimeError):
    """The run repeated the same action/observation too many times."""


class TrajectoryRecorder:
    def __init__(self, path: str | Path, heartbeat: str | Path | None = None):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.heartbeat = Path(heartbeat) if heartbeat is not None else None
        if self.heartbeat is not None:
            self.heartbeat.parent.mkdir(parents=True, exist_ok=True)
        self.step = 0

    def event(self, event_kind: str, **fields: Any) -> None:
        record = {
            "at": time.time(),
            "step": self.step,
            "kind": event_kind,
            **fields,
        }
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        if self.heartbeat is not None:
            self.heartbeat.write_text(
                json.dumps({"at": record["at"], "step": self.step,
                            "kind": event_kind}, ensure_ascii=False) + "\n",
                encoding="utf-8")

    def close(self) -> None:
        pass


def _content(message: dict) -> str:
    content = message.get("content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(
            str(part.get("text", "")) if isinstance(part, dict) else str(part)
            for part in content)
    return str(content)


class RecordingModelClient(ModelClient):
    def __init__(self, client: ModelClient, recorder: TrajectoryRecorder,
                 deadline: float | None = None,
                 log_full_messages: bool = True):
        self.client = client
        self.recorder = recorder
        self.deadline = deadline
        # Multi-million-token runs cannot afford O(n^2) trajectory logs.  With
        # this off, the raw request is recorded as a digest; the exact prompt
        # still appears in ``model_request_sent`` from the context policy.
        self.log_full_messages = log_full_messages

    def complete(self, messages: List[dict], **kwargs) -> ModelResponse:
        if self.deadline is not None and time.time() >= self.deadline:
            error = "wall-clock deadline reached"
            self.recorder.event("model_error", error=error)
            raise ModelRequestError(error)
        if self.log_full_messages:
            self.recorder.event("model_request", messages=messages)
        else:
            last = messages[-1] if messages else {}
            last_text = _content(last)
            self.recorder.event(
                "model_request",
                message_count=len(messages),
                chars=sum(len(_content(message)) for message in messages),
                last_role=str(last.get("role", "")),
                last_chars=len(last_text),
                last_head=last_text[:300],
            )
        try:
            response = self.client.complete(messages, **kwargs)
        except ModelRequestError as exc:
            self.recorder.event("model_error", error=str(exc))
            raise
        self.recorder.event(
            "model_response",
            content=response.content,
            total_tokens=response.total_tokens,
            prompt_tokens=response.prompt_tokens,
            completion_tokens=response.completion_tokens,
        )
        return response


class RecordingHost(Host):
    def __init__(self, host: Host, recorder: TrajectoryRecorder,
                 max_identical: int = 5):
        self.host = host
        self.recorder = recorder
        self.max_identical = max_identical
        self._recent: List[str] = []
        self.loop_detected = False
        self._step = 0

    @property
    def tokens_used(self) -> int:
        return self.host.tokens_used

    @property
    def actions(self) -> List[Action]:
        return self.host.actions

    @property
    def submitted(self) -> bool:
        return bool(getattr(self.host, "submitted", False))

    def charge_tokens(self, n: int) -> None:
        charge = getattr(self.host, "charge_tokens", None)
        if callable(charge):
            charge(n)

    def step(self, action: Action) -> Observation:
        self._step += 1
        self.recorder.step = self._step
        if action.kind == "submit":
            self.recorder.event("submit")
        self.recorder.event("action", action_kind=action.kind, payload=action.payload)
        observation = self.host.step(action)
        self.recorder.event(
            "observation",
            output=observation.output,
            error=observation.error,
            exit_code=observation.exit_code,
        )
        digest = hashlib.sha1(json.dumps(
            [action.kind, action.payload, observation.output,
             observation.error, observation.exit_code],
            sort_keys=True, default=str,
        ).encode("utf-8")).hexdigest()
        self._recent.append(digest)
        self._recent = self._recent[-self.max_identical:]
        if (len(self._recent) == self.max_identical
                and len(set(self._recent)) == 1):
            self.loop_detected = True
            raise LoopDetected(
                f"same action/observation repeated {self.max_identical} times")
        return observation

    def submit(self) -> Observation:
        self.recorder.event("submit")
        observation = self.host.submit()
        self.recorder.event(
            "submit_observation",
            output=observation.output,
            error=observation.error,
            exit_code=observation.exit_code,
        )
        return observation

    def grade(self) -> Grade:
        return self.host.grade()

    def cleanup(self) -> None:
        cleanup = getattr(self.host, "cleanup", None)
        if callable(cleanup):
            cleanup()
