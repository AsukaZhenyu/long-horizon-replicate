"""Fairness and workflow-invariance checks for adapter runs."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, List, Sequence, Tuple

from .types import Action, ExperimentConfig, RunRecord


def action_key(action: Action) -> Tuple[str, Tuple[Tuple[str, str], ...]]:
    return (action.kind, tuple(sorted((str(k), str(v)) for k, v in action.payload.items())))


def workflow_preserved(native: Sequence[Action], adapted: Sequence[Action]) -> bool:
    """The adapter must not add, drop or reorder actions."""
    return [action_key(a) for a in native] == [action_key(a) for a in adapted]


@dataclass
class FairnessLedger:
    records: List[RunRecord] = field(default_factory=list)

    def add(self, record: RunRecord) -> None:
        self.records.append(record)

    def violations(self, config: ExperimentConfig) -> List[str]:
        out: List[str] = []
        for r in self.records:
            tag = f"{r.method}/{r.benchmark}/{r.task_id}"
            if r.config != config:
                out.append(f"{tag}: config differs from the common config")
            if r.tokens > config.token_budget:
                out.append(f"{tag}: tokens {r.tokens} exceed budget {config.token_budget}")
            if r.hidden_test_access:
                out.append(f"{tag}: method touched hidden tests")
            if r.grade_calls_during_run:
                out.append(f"{tag}: method called grade() before the runner did")
        return out

    def same_budget(self, config: ExperimentConfig) -> bool:
        return all(r.config.token_budget == config.token_budget for r in self.records)

    def same_model(self, config: ExperimentConfig) -> bool:
        return all(r.config.model == config.model for r in self.records)

    def base_control_delta(self, method: str, benchmark: str) -> float:
        """Completion(method) - Completion(base) on the same benchmark."""
        method_scores = [r.completion for r in self.records
                         if r.method == method and r.benchmark == benchmark]
        base_scores = [r.completion for r in self.records
                       if r.method == "base" and r.benchmark == benchmark]
        if not method_scores or not base_scores:
            raise KeyError("need both method and base records")
        return (sum(method_scores) / len(method_scores)
                - sum(base_scores) / len(base_scores))
