"""MLE-bench medal thresholds and a dependency-free synthetic metric.

The official medal logic is ``mlebench.grade_helpers.Grader.rank_score``:
thresholds come from the competition leaderboard, and a submission earns the
best medal it clears.  This module reproduces that logic with the standard
library so the adapter can be tested without pandas/scikit-learn.

Real MLE-bench competitions use their own ``mlebench.competitions.<id>.grade``
metric, which needs pandas and the prepared Kaggle answers.  The adapter uses
that official path only when the ``mlebench`` package and data are available;
otherwise it reports the missing dependency rather than inventing a score.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, List, Sequence


@dataclass(frozen=True)
class MedalReport:
    score: float | None
    gold_threshold: float
    silver_threshold: float
    bronze_threshold: float
    median_threshold: float
    gold_medal: bool
    silver_medal: bool
    bronze_medal: bool
    above_median: bool

    @property
    def any_medal(self) -> bool:
        return self.gold_medal or self.silver_medal or self.bronze_medal


def read_leaderboard(path: str | Path) -> List[float]:
    """Read the ``score`` column in leaderboard order (best first)."""
    with Path(path).open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None or "score" not in reader.fieldnames:
            raise ValueError(f"{path}: leaderboard has no 'score' column")
        return [float(row["score"]) for row in reader]


def is_lower_better(scores: Sequence[float]) -> bool:
    return bool(scores[0] < scores[-1])


def _thresholds(scores: Sequence[float]) -> tuple[float, float, float, float]:
    num_teams = len(scores)
    if num_teams < 1:
        raise ValueError("leaderboard must not be empty")

    def at(position: int) -> float:
        if position < 1 or position > len(scores):
            raise IndexError("leaderboard position out of bounds")
        return float(scores[position - 1])

    if num_teams < 100:
        gold = at(max(1, int(num_teams * 0.1)))
        silver = at(max(1, int(num_teams * 0.2)))
        bronze = at(max(1, int(num_teams * 0.4)))
    elif num_teams < 250:
        gold = at(10)
        silver = at(max(1, int(num_teams * 0.2)))
        bronze = at(max(1, int(num_teams * 0.4)))
    elif num_teams < 1000:
        gold = at(10 + int(num_teams * 0.002))
        silver = at(50)
        bronze = at(100)
    else:
        gold = at(10 + int(num_teams * 0.002))
        silver = at(max(1, int(num_teams * 0.05)))
        bronze = at(max(1, int(num_teams * 0.1)))
    ordered = sorted(scores)
    median = ordered[len(ordered) // 2] if len(ordered) % 2 else (
        ordered[len(ordered) // 2 - 1] + ordered[len(ordered) // 2]) / 2
    return gold, silver, bronze, float(median)


def rank_score(score: float | None, scores: Sequence[float]) -> MedalReport:
    gold, silver, bronze, median = _thresholds(scores)
    lower = is_lower_better(scores)
    if score is None:
        return MedalReport(None, gold, silver, bronze, median,
                           False, False, False, False)
    gold_medal = score <= gold if lower else score >= gold
    silver_medal = (not gold_medal and
                    (score <= silver if lower else score >= silver))
    bronze_medal = (not gold_medal and not silver_medal and
                    (score <= bronze if lower else score >= bronze))
    above_median = score < median if lower else score > median
    return MedalReport(score, gold, silver, bronze, median,
                       gold_medal, silver_medal, bronze_medal, above_median)


def read_csv_rows(text_or_path: str | Path) -> List[dict]:
    if isinstance(text_or_path, Path):
        with text_or_path.open(newline="", encoding="utf-8") as handle:
            return list(csv.DictReader(handle))
    return list(csv.DictReader(text_or_path.splitlines()))


def accuracy_metric(submission_csv: str, answers_path: Path) -> float | None:
    """Synthetic metric: exact match of ``prediction`` against ``answer`` by id.

    This is only for the adapter smoke test.  Real competitions use the
    official competition ``grade.py`` functions.
    """
    try:
        submission = read_csv_rows(submission_csv)
        answers = read_csv_rows(Path(answers_path))
    except (csv.Error, KeyError, ValueError):
        return None
    if not submission or not answers:
        return None
    answer_by_id = {row["id"]: row["answer"] for row in answers}
    common = [row for row in submission if row.get("id") in answer_by_id]
    if not common:
        return None
    correct = sum(1 for row in common
                  if str(row.get("prediction", "")).strip()
                  == str(answer_by_id[row["id"]]).strip())
    return correct / len(common)
