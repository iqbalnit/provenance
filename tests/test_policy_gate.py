import pytest

from provenance.core.models import Decision, EvidenceType as E, Typology as T
from provenance.core.policy_gate import GateInput, evaluate_gate

PASSING = dict(
    typology=T.STRUCTURING,
    confidence=0.95,
    gathered_evidence={E.TRANSACTIONS, E.WATCHLIST, E.KYC},
    staleness_penalty=0.0,
    citation_coverage=1.0,
    sanctions_or_pep_hit=False,
)


def test_all_conditions_pass_auto_closes():
    r = evaluate_gate(GateInput(**PASSING))
    assert r.decision is Decision.AUTO_CLOSE
    assert len(r.conditions) == 6 and not r.failed


@pytest.mark.parametrize(
    "override, failing",
    [
        ({"confidence": 0.89}, "confidence"),
        ({"gathered_evidence": {E.TRANSACTIONS, E.WATCHLIST}}, "mandatory_evidence"),
        ({"staleness_penalty": 0.01}, "staleness"),
        ({"citation_coverage": 0.99}, "citation_coverage"),
        ({"sanctions_or_pep_hit": True}, "no_sanctions_or_pep_hit"),
        (
            {"typology": T.SANCTIONS_NEXUS, "gathered_evidence": {E.TRANSACTIONS, E.WATCHLIST, E.ADVERSE_MEDIA}},
            "typology_allows_auto_close",
        ),
    ],
)
def test_each_condition_alone_forces_escalation(override, failing):
    r = evaluate_gate(GateInput(**{**PASSING, **override}))
    assert r.decision is Decision.ESCALATE
    assert [c.name for c in r.failed] == [failing]


def test_all_conditions_reported_even_after_failure():
    r = evaluate_gate(GateInput(**{**PASSING, "confidence": 0.1, "citation_coverage": 0.0}))
    assert {c.name for c in r.failed} == {"confidence", "citation_coverage"}
    assert len(r.conditions) == 6
