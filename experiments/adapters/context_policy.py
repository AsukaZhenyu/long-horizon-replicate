"""Shared context-window management for long-horizon reproduction runs.

The policy is harness infrastructure, applied identically to every method at
the ModelClient boundary.  It is not part of any method's native loop; the
protocol records it so the condition is auditable and can be ablated later
(native runs simply do not wrap the client).

What it does
------------
- caps each non-task message at ``max_message_chars`` (head+tail);
- preserves system messages and the first user message (the task) intact,
  up to ``max_system_chars`` / ``max_task_chars``;
- when the estimated prompt exceeds ``trigger_ratio * window_tokens``, folds
  the oldest messages into one deterministic digest message;
- keeps the most recent ``keep_recent_messages`` messages verbatim;
- never calls the model to compact, so it adds no token cost beyond the
  requests the method would already make.

The raw prompt the method built is still logged by the outer recorder; this
module logs the compacted prompt as ``model_request_sent`` and a
``context_compact`` event with before/after estimates.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from agents.base_react import (
    ModelClient, ModelRequestError, ModelResponse, parse_action,
)

EventFn = Callable[..., None]


@dataclass(frozen=True)
class ContextPolicyConfig:
    """Frozen knobs for the shared context policy."""

    window_tokens: int = 16384
    trigger_ratio: float = 0.72
    target_ratio: float = 0.55
    keep_recent_messages: int = 8
    max_messages_before_compact: int = 24
    max_message_chars: int = 4000
    max_system_chars: int = 16000
    max_task_chars: int = 16000
    summary_chars: int = 2400
    min_messages_to_compact: int = 6
    chars_per_token: float = 2.0

    def __post_init__(self) -> None:
        if self.window_tokens <= 0:
            raise ValueError("window_tokens must be positive")
        if not 0 < self.trigger_ratio < 1:
            raise ValueError("trigger_ratio must be in (0, 1)")
        if not 0 < self.target_ratio < self.trigger_ratio:
            raise ValueError("target_ratio must be in (0, trigger_ratio)")
        if self.keep_recent_messages < 2:
            raise ValueError("keep_recent_messages must be >= 2")
        if self.max_messages_before_compact <= self.keep_recent_messages:
            raise ValueError(
                "max_messages_before_compact must exceed keep_recent_messages")

    @property
    def trigger_tokens(self) -> int:
        return max(1, int(self.window_tokens * self.trigger_ratio))

    @property
    def target_tokens(self) -> int:
        return max(1, int(self.window_tokens * self.target_ratio))

    def as_dict(self) -> Dict[str, Any]:
        return {
            "window_tokens": self.window_tokens,
            "trigger_ratio": self.trigger_ratio,
            "target_ratio": self.target_ratio,
            "keep_recent_messages": self.keep_recent_messages,
            "max_messages_before_compact": self.max_messages_before_compact,
            "max_message_chars": self.max_message_chars,
            "max_system_chars": self.max_system_chars,
            "max_task_chars": self.max_task_chars,
            "summary_chars": self.summary_chars,
            "min_messages_to_compact": self.min_messages_to_compact,
            "chars_per_token": self.chars_per_token,
        }


@dataclass(frozen=True)
class CompactionStats:
    before_tokens: int
    after_tokens: int
    dropped_messages: int
    kept_recent: int
    digest_chars: int


def _content(message: Dict[str, Any]) -> str:
    content = message.get("content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, dict):
                parts.append(str(part.get("text", "")))
            else:
                parts.append(str(part))
        return " ".join(parts)
    return str(content)


def estimate_tokens(messages: Sequence[Dict[str, Any]],
                    chars_per_token: float = 3.5) -> int:
    """Conservative char-based estimate; calibrated after each response."""
    chars = sum(len(_content(message)) for message in messages)
    return int(chars / max(chars_per_token, 0.5)) + 4 * len(messages)


def _one_line(text: Any) -> str:
    return " ".join(str(text).split())


def _truncate(text: str, limit: int) -> str:
    if limit <= 0 or len(text) <= limit:
        return text
    marker = f"\n... [{len(text) - limit} chars omitted] ...\n"
    keep = max(0, limit - len(marker))
    head = keep * 2 // 3
    tail = keep - head
    return text[:head] + marker + (text[-tail:] if tail else "")


def _digest_line(index: int, message: Dict[str, Any]) -> str:
    role = str(message.get("role", "user"))
    text = _content(message)
    if role == "assistant":
        try:
            action = parse_action(text)
        except Exception:
            action = None
        if isinstance(action, dict):
            if "command" in action:
                return f"s{index} cmd: {_one_line(action['command'])[:120]}"
            if "final" in action:
                return f"s{index} final: {_one_line(action['final'])[:120]}"
            for key, value in action.items():
                if str(key).startswith("spine_"):
                    payload = _one_line(json.dumps(value, ensure_ascii=False,
                                                   default=str))
                    return f"s{index} {key}: {payload[:100]}"
        return f"s{index} asst: {_one_line(text)[:120]}"
    if role == "system":
        return f"s{index} system: {_one_line(text)[:100]}"
    return f"s{index} user: {_one_line(text)[:160]}"


def _build_digest(messages: Sequence[Dict[str, Any]], limit: int) -> str:
    lines = [_digest_line(index, message)
             for index, message in enumerate(messages)]
    if not lines:
        return "[compacted history]"
    kept: List[str] = []
    used = 0
    for line in reversed(lines):
        cost = len(line) + 1
        if used + cost > limit:
            break
        kept.append(line)
        used += cost
    kept.reverse()
    omitted = len(lines) - len(kept)
    header = "[compacted history]"
    if omitted:
        header += f" ({omitted} earlier messages omitted)"
    return header + "\n" + "\n".join(kept)


def _prepare_messages(messages: Sequence[Dict[str, Any]],
                      config: ContextPolicyConfig) -> List[Dict[str, str]]:
    prepared: List[Dict[str, str]] = []
    task_seen = False
    for message in messages:
        role = str(message.get("role", "user"))
        if role == "system":
            limit = config.max_system_chars
        elif role == "user" and not task_seen:
            # The first user message is the frozen task instruction.  It is
            # never dropped and only capped by its own, larger limit.
            limit = config.max_task_chars
            task_seen = True
        else:
            limit = config.max_message_chars
        prepared.append({"role": role, "content": _truncate(_content(message), limit)})
    return prepared


def compile_view(
    messages: Sequence[Dict[str, Any]],
    config: ContextPolicyConfig,
    chars_per_token: Optional[float] = None,
    floor_tokens: int = 0,
) -> Tuple[List[Dict[str, str]], int, Optional[CompactionStats]]:
    """Return ``(view, estimated_tokens, stats_or_none)``.

    ``floor_tokens`` is the previous request's actual prompt size; it forces a
    compaction when the estimator would otherwise under-count.
    """
    cpt = config.chars_per_token if chars_per_token is None else chars_per_token
    prepared = _prepare_messages(messages, config)
    before = estimate_tokens(prepared, cpt)
    trigger = config.trigger_tokens
    # The message cap is a safety net: char-based estimation under-counts
    # prompts made of many short messages (the model's chat template adds
    # per-message tokens), so never let the raw view grow past this count.
    if (before <= trigger and floor_tokens <= trigger
            and len(prepared) <= config.max_messages_before_compact):
        return prepared, before, None
    if len(prepared) <= config.keep_recent_messages + 2:
        return prepared, before, None

    system = [m for m in prepared if m.get("role") == "system"]
    body = [m for m in prepared if m.get("role") != "system"]
    task: List[Dict[str, str]] = []
    if body and body[0].get("role") == "user":
        task = [body[0]]
        body = body[1:]

    keep = min(config.keep_recent_messages, len(body))
    while keep > 2 and len(body) - keep < config.min_messages_to_compact:
        keep -= 1
    recent = body[-keep:] if keep > 0 else []
    dropped = body[:-keep] if keep > 0 else list(body)
    if not dropped:
        return prepared, before, None

    digest = _build_digest(dropped, config.summary_chars)
    compiled = system + task + [{"role": "user", "content": digest}] + recent
    after = estimate_tokens(compiled, cpt)

    # Still above target: fold the oldest recent messages too, but never
    # below two messages (the latest observation must reach the model).
    while after > config.target_tokens and len(recent) > 2:
        dropped.append(recent.pop(0))
        digest = _build_digest(dropped, config.summary_chars)
        compiled = system + task + [{"role": "user", "content": digest}] + recent
        after = estimate_tokens(compiled, cpt)

    stats = CompactionStats(
        before_tokens=max(before, floor_tokens),
        after_tokens=after,
        dropped_messages=len(dropped),
        kept_recent=len(recent),
        digest_chars=len(digest),
    )
    return compiled, after, stats


class ContextManagedModelClient(ModelClient):
    """A transparent ModelClient wrapper that bounds the prompt size.

    The wrapped client sees the compacted view.  The method still holds its
    own full history; only the request is windowed.
    """

    def __init__(self, client: ModelClient,
                 config: Optional[ContextPolicyConfig] = None,
                 event: Optional[EventFn] = None,
                 prompt_equivalent_divisor: float = 65.0,
                 equivalent_budget: Optional[float] = None):
        self.client = client
        self.config = config or ContextPolicyConfig()
        self.event = event
        self.compactions = 0
        self.last_prompt_tokens = 0
        self.max_prompt_tokens = 0
        self.total_prompt_tokens = 0
        self.total_completion_tokens = 0
        self.total_tokens = 0
        # E = P/rho + G, rho = prefill_tps / decode_tps.  E is proportional
        # to LLM time (T ~= E / decode_tps), so it is a time-equivalent
        # token budget that does not depend on the P:G mix.
        self.prompt_equivalent_divisor = max(
            float(prompt_equivalent_divisor), 1e-6)
        self.equivalent_budget = (
            None if equivalent_budget is None else float(equivalent_budget))
        self.equivalent_tokens = 0.0
        self.chars_per_token = self.config.chars_per_token
        self.prompt_tokens_curve: List[int] = []

    def complete(self, messages: List[dict], **kwargs) -> ModelResponse:
        view, estimate, stats = compile_view(
            messages, self.config, self.chars_per_token,
            floor_tokens=self.last_prompt_tokens)
        if stats is not None:
            self.compactions += 1
            if self.event is not None:
                self.event("context_compact",
                           before_tokens=stats.before_tokens,
                           after_tokens=stats.after_tokens,
                           dropped_messages=stats.dropped_messages,
                           kept_recent=stats.kept_recent,
                           digest_chars=stats.digest_chars)
        if estimate > self.config.window_tokens:
            raise ModelRequestError(
                "context window exceeded before request: "
                f"estimated {estimate} > {self.config.window_tokens}")
        if self.event is not None:
            self.event("model_request_sent", messages=view,
                       estimated_tokens=estimate)
        response = self.client.complete(view, **kwargs)
        completion_tokens = int(response.completion_tokens or 0)
        self.total_completion_tokens += completion_tokens
        self.total_tokens += int(response.total_tokens or 0)
        prompt_tokens = int(response.prompt_tokens or 0)
        self.total_prompt_tokens += prompt_tokens
        self.equivalent_tokens += (
            prompt_tokens / self.prompt_equivalent_divisor + completion_tokens)
        if (self.equivalent_budget is not None
                and self.equivalent_tokens > self.equivalent_budget):
            raise ModelRequestError(
                "equivalent token budget exceeded: "
                f"{self.equivalent_tokens:.1f} > "
                f"{self.equivalent_budget:.1f}")
        if prompt_tokens:
            self.last_prompt_tokens = prompt_tokens
            self.max_prompt_tokens = max(self.max_prompt_tokens, prompt_tokens)
            self.prompt_tokens_curve.append(prompt_tokens)
            chars = sum(len(_content(message)) for message in view)
            observed = chars / prompt_tokens
            if 1.0 <= observed <= 10.0:
                # Clamp conservative: the server charges chat-template
                # overhead that a char estimate cannot see, and a high
                # chars/token ratio under-counts prompts with many short
                # messages.  Staying near 2.0 makes the policy err toward
                # compacting rather than overflowing the window.
                smoothed = 0.7 * self.chars_per_token + 0.3 * observed
                self.chars_per_token = min(2.5, max(1.2, smoothed))
        return response

    def stats(self) -> Dict[str, Any]:
        return {
            "compactions": self.compactions,
            "max_prompt_tokens": self.max_prompt_tokens,
            "last_prompt_tokens": self.last_prompt_tokens,
            "prompt_tokens_total": self.total_prompt_tokens,
            "completion_tokens": self.total_completion_tokens,
            "total_tokens": self.total_tokens,
            "equivalent_tokens": round(self.equivalent_tokens, 1),
            "equivalent_budget": self.equivalent_budget,
            "prompt_equivalent_divisor": self.prompt_equivalent_divisor,
            "chars_per_token": round(self.chars_per_token, 3),
            "prompt_tokens": list(self.prompt_tokens_curve),
            "policy": self.config.as_dict(),
        }
