"""Deterministic eval metrics. Wire these into tests/eval/eval_config.yaml as
custom_function entries once agents-cli has scaffolded the eval harness.

Lead with false_negative_rate_on_auto_close: it is the only metric that gets a
bank fined, and the target is exactly zero.
"""
from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

ANALYST_MINUTES_PER_ALERT = 25


@dataclass(frozen=True)
class Outcome:
    alert_id: str
    auto_closed: bool
    truly_suspicious: bool  # ground truth from the dataset's laundering label
    confidence: float | None = None
    correct: bool | None = None  # did the disposition match ground truth


def false_negative_rate_on_auto_close(outcomes: Sequence[Outcome]) -> float:
    """Share of truly suspicious alerts that were auto-closed without a human."""
    positives = [o for o in outcomes if o.truly_suspicious]
    if not positives:
        return 0.0
    return sum(o.auto_closed for o in positives) / len(positives)


def auto_close_rate(outcomes: Sequence[Outcome]) -> float:
    return sum(o.auto_closed for o in outcomes) / len(outcomes) if outcomes else 0.0


def escalation_precision(outcomes: Sequence[Outcome]) -> float:
    """Of the alerts we escalated, how many were truly suspicious. Shows escalation isn't a cop-out."""
    esc = [o for o in outcomes if not o.auto_closed]
    return sum(o.truly_suspicious for o in esc) / len(esc) if esc else 0.0


def analyst_hours_saved(outcomes: Sequence[Outcome], minutes_per_alert: int = ANALYST_MINUTES_PER_ALERT) -> float:
    return sum(o.auto_closed for o in outcomes) * minutes_per_alert / 60


def _norm(entity: str) -> str:
    return " ".join(re.split(r"[^a-z0-9]+", entity.lower())).strip()


def hallucinated_entity_rate(narrative_entities: Iterable[str], ledger_entities: Iterable[str]) -> float:
    """Share of entities named in the narrative that appear nowhere in the ledger.

    Deterministic set difference. Entity extraction happens upstream (NER or a
    Flash call); this function only compares.
    """
    named = {_norm(e) for e in narrative_entities if _norm(e)}
    if not named:
        return 0.0
    known = {_norm(e) for e in ledger_entities}
    return len(named - known) / len(named)


def expected_calibration_error(
    confidences: Sequence[float], correct: Sequence[bool], n_bins: int = 10
) -> float:
    """Standard ECE with equal-width bins over [0, 1]."""
    if len(confidences) != len(correct):
        raise ValueError("confidences and correct must be the same length")
    n = len(confidences)
    if n == 0:
        return 0.0
    bins: list[list[int]] = [[] for _ in range(n_bins)]
    for i, c in enumerate(confidences):
        if not 0.0 <= c <= 1.0:
            raise ValueError(f"confidence out of range: {c}")
        bins[min(int(c * n_bins), n_bins - 1)].append(i)
    ece = 0.0
    for idx in bins:
        if not idx:
            continue
        acc = sum(correct[i] for i in idx) / len(idx)
        conf = sum(confidences[i] for i in idx) / len(idx)
        ece += len(idx) / n * abs(acc - conf)
    return ece


def reliability_curve(
    confidences: Sequence[float], correct: Sequence[bool], n_bins: int = 10
) -> list[tuple[float, float, int]]:
    """(mean confidence, accuracy, count) per non-empty bin, for the /eval calibration chart."""
    bins: list[list[int]] = [[] for _ in range(n_bins)]
    for i, c in enumerate(confidences):
        bins[min(int(c * n_bins), n_bins - 1)].append(i)
    return [
        (
            sum(confidences[i] for i in idx) / len(idx),
            sum(correct[i] for i in idx) / len(idx),
            len(idx),
        )
        for idx in bins
        if idx
    ]
