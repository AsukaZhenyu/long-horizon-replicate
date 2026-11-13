"""RRSI native loop: evaluate a prompt-only candidate harness.

RRSI's coding domain searches over harness edits.  The local adapter implements
the *evaluation* half only: load a candidate system prompt, run the same
terminal actor, and score it with the benchmark's official verifier.  The
search roles (proposer/analyst/critic) need Anthropic Vertex and are not run
here; this module does not pretend to be the full search loop.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from agents.base_react import ACTION_PROTOCOL, BaseReactAgent, ModelClient
from contract.types import Host, NativeAgent, TaskSpec

REPO = Path(__file__).resolve().parents[3]
DEFAULT_PROMPT = (REPO / "experiments" / "tb-eval" / "adapters" / "rrsi"
                  / "harness" / "system_prompt.txt")


class RRSIPromptAgent(NativeAgent):
    """Run one candidate prompt through the frozen terminal actor."""

    name = "rrsi"
    mechanism = ("harness_edit", "search_selection")

    def __init__(self, client: ModelClient, prompt_path: str | Path | None = None,
                 max_steps: int = 40):
        self.client = client
        self.prompt_path = Path(prompt_path or DEFAULT_PROMPT)
        self.max_steps = max_steps
        self.prompt_sha256 = ""
        self.system_prompt = ""

    def run(self, task: TaskSpec, host: Host) -> None:
        if not self.prompt_path.is_file():
            raise FileNotFoundError(f"RRSI candidate prompt missing: {self.prompt_path}")
        data = self.prompt_path.read_bytes().replace(b"\r\n", b"\n")
        self.system_prompt = data.decode("utf-8")
        self.prompt_sha256 = hashlib.sha256(data).hexdigest()
        # The candidate prompt shapes planning; the host still needs the
        # common terminal action protocol, which is not part of the candidate.
        BaseReactAgent(
            self.client, max_steps=self.max_steps,
            system_prompt=self.system_prompt + "\n\n" + ACTION_PROTOCOL,
        ).run(task, host)
