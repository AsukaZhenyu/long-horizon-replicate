"""Dependency-free copy of CORE-Bench's official answer grading.

The official implementation is ``benchmark/evaluations.py::eval_result_json``
in ``siegelz/core-bench``.  It uses numpy/scipy for the mean, sample standard
deviation, and the 95% t prediction interval.  This module reproduces that
logic with the standard library so the adapter tests do not need numpy/scipy;
the t-quantile table matches ``scipy.stats.t.ppf(0.975, df)`` for df <= 30 and
falls back to the normal quantile above that.

Numeric answers pass inside the 95% prediction interval of the three gold runs,
string answers are compared case-insensitively, and list answers are compared
exactly.  A task passes only when every question is correct.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict, List

# scipy.stats.t.ppf(0.975, df) for df = 1..30.
_T975 = {
    1: 12.7062047361747,
    2: 4.30265272974946,
    3: 3.18244630528426,
    4: 2.77644510519779,
    5: 2.57058183563631,
    6: 2.44691185114497,
    7: 2.36462425159278,
    8: 2.30600413520417,
    9: 2.26215716279820,
    10: 2.22813885198627,
    11: 2.20098516009164,
    12: 2.17881282966723,
    13: 2.16036865646101,
    14: 2.14478668791693,
    15: 2.13144954555932,
    16: 2.11990529922101,
    17: 2.10981557783318,
    18: 2.10092204024096,
    19: 2.09302405440831,
    20: 2.08596344726584,
    21: 2.07961384472766,
    22: 2.07387306790401,
    23: 2.06865761041904,
    24: 2.06389856162802,
    25: 2.05953855275329,
    26: 2.05552943864287,
    27: 2.05183051648028,
    28: 2.04840714179524,
    29: 2.04522964213270,
    30: 2.04227245630124,
}
_NORMAL_975 = 1.959963984540054


def _t975(df: int) -> float:
    return _T975.get(df, _NORMAL_975)


@dataclass(frozen=True)
class CoreGrade:
    correct_written_answers: int
    correct_vision_answers: int
    total_written_questions: int
    total_vision_questions: int

    @property
    def correct_questions(self) -> int:
        return self.correct_written_answers + self.correct_vision_answers

    @property
    def total_questions(self) -> int:
        return self.total_written_questions + self.total_vision_questions

    @property
    def passed(self) -> bool:
        return (self.total_questions > 0
                and self.correct_questions == self.total_questions)


def _mean(values: List[float]) -> float:
    return sum(values) / len(values)


def _sample_std(values: List[float]) -> float:
    if len(values) < 2:
        return 0.0
    average = _mean(values)
    variance = sum((value - average) ** 2 for value in values) / (len(values) - 1)
    return math.sqrt(variance)


def eval_result_json(gt_result: List[Dict[str, Any]],
                     reported_result: Dict[str, Any]) -> CoreGrade:
    """Grade one CORE-Bench ``report.json`` against the three gold runs."""
    if not gt_result:
        raise ValueError("CORE-Bench gold results are empty")
    first = gt_result[0]
    numeric_keys = [key for key, value in first.items()
                    if isinstance(value, (int, float))]
    list_keys = [key for key, value in first.items() if isinstance(value, list)]
    string_keys = [key for key, value in first.items() if isinstance(value, str)]

    counted = set(numeric_keys) | set(list_keys) | set(string_keys)
    total_written = sum(1 for key in counted if "fig" not in key)
    total_vision = sum(1 for key in counted if "fig" in key)

    correct_written = 0
    correct_vision = 0
    reported = dict(reported_result or {})

    # The official grader first tries to coerce every reported value to float.
    for key, value in list(reported.items()):
        try:
            if "%" in value:
                value = value.replace("%", "")
            reported[key] = float(value)
        except (TypeError, ValueError):
            pass

    try:
        means = {key: _mean([float(result[key]) for result in gt_result])
                 for key in numeric_keys}
        stds = {key: _sample_std([float(result[key]) for result in gt_result])
                for key in numeric_keys}
        sample_size = len(gt_result)
        t_value = _t975(sample_size - 1)
        bounds = {
            key: (
                means[key] - t_value * stds[key] * math.sqrt(1 + 1 / sample_size),
                means[key] + t_value * stds[key] * math.sqrt(1 + 1 / sample_size),
            )
            for key in numeric_keys
        }
        for key, value in reported.items():
            if key in numeric_keys:
                try:
                    numeric = float(value)
                except (TypeError, ValueError):
                    continue
                lower, upper = bounds[key]
                if lower <= numeric <= upper:
                    if "fig" in key:
                        correct_vision += 1
                    else:
                        correct_written += 1
            elif key in list_keys:
                if value == first[key]:
                    if "fig" in key:
                        correct_vision += 1
                    else:
                        correct_written += 1
            elif key in string_keys:
                if str(value).lower() == str(first[key]).lower():
                    if "fig" in key:
                        correct_vision += 1
                    else:
                        correct_written += 1
    except Exception:
        # Match the official grader: an evaluation error leaves the counters
        # at whatever was accumulated instead of inventing a pass.
        pass

    return CoreGrade(
        correct_written_answers=correct_written,
        correct_vision_answers=correct_vision,
        total_written_questions=total_written,
        total_vision_questions=total_vision,
    )
