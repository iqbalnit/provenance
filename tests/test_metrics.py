import pytest

from provenance.eval.metrics import (
    Outcome,
    analyst_hours_saved,
    auto_close_rate,
    escalation_precision,
    expected_calibration_error,
    false_negative_rate_on_auto_close,
    hallucinated_entity_rate,
)


def test_ece_hand_computed():
    # bin 0.9: conf .9,.9 acc 1/2 -> |0.5-0.9|=0.4 weight .5 ; bin 0.6: conf .6,.6 acc 1 -> 0.4 weight .5
    assert expected_calibration_error([0.9, 0.9, 0.6, 0.6], [True, False, True, True]) == pytest.approx(0.4)


def test_perfect_calibration_is_zero():
    assert expected_calibration_error([1.0, 1.0, 0.0], [True, True, False]) == pytest.approx(0.0)


def test_outcome_metrics():
    o = [
        Outcome("a", auto_closed=True, truly_suspicious=False),
        Outcome("b", auto_closed=True, truly_suspicious=True),
        Outcome("c", auto_closed=False, truly_suspicious=True),
        Outcome("d", auto_closed=False, truly_suspicious=False),
    ]
    assert false_negative_rate_on_auto_close(o) == 0.5
    assert auto_close_rate(o) == 0.5
    assert escalation_precision(o) == 0.5
    assert analyst_hours_saved(o) == pytest.approx(50 / 60)


def test_hallucinated_entities():
    assert hallucinated_entity_rate(["ACME Ltd", "Globex"], ["acme ltd.", "Initech"]) == 0.5
    assert hallucinated_entity_rate([], ["x"]) == 0.0
