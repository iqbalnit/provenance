import pytest

from provenance.core.decide import decide_case
from provenance.core.ledger import LedgerConflictError
from provenance.core.models import Case, Claim, EvidenceType as E, Typology
from provenance.stores.firestore import CaseRepository, FirestoreLedger
from tests.conftest import NOW, make_claim
from provenance.stores.memory import FakeFirestore


def test_round_trip_and_idempotent_append():
    db = FakeFirestore()
    led = FirestoreLedger(db, "case1")
    c = make_claim()
    assert led.append(c) == led.append(make_claim()) == c.claim_id
    assert led.get(c.claim_id) == c
    assert led.all() == [c]
    assert led.get("clm_missing000") is None
    assert "cases/case1/claims/" + c.claim_id in db.store


def test_conflict_raises(monkeypatch):
    db = FakeFirestore()
    led = FirestoreLedger(db, "case1")
    a, b = make_claim("x."), make_claim("y.")
    monkeypatch.setattr(Claim, "claim_id", property(lambda self: "clm_0000000000"))
    led.append(a)
    with pytest.raises(LedgerConflictError):
        led.append(b)


def test_decide_and_write_over_firestore():
    db = FakeFirestore()
    repo = CaseRepository(db)
    repo.create_case(Case(case_id="case1", alert_id="alt_1", typology=Typology.STRUCTURING))
    led = repo.ledger("case1")
    claims = [
        make_claim("Deposits fact.", evidence_type=E.TRANSACTIONS),
        make_claim("Watchlist fact.", evidence_type=E.WATCHLIST, sla=3),
        make_claim("KYC fact.", evidence_type=E.KYC, sla=365),
    ]
    for c in claims:
        led.append(c)
    narrative = " ".join(f"Fact {i} [{c.claim_id}]." for i, c in enumerate(claims))
    d = decide_case(typology=Typology.STRUCTURING, ledger=led, narrative=narrative, confidence=0.95, now=NOW)
    assert d.decision.value == "auto_close"
    repo.write_decision("case1", d, narrative, version=1)
    case = db.store["cases/case1"]
    assert case["decision"] == "auto_close" and case["policy_gate"]["passed"]
    assert len(case["policy_gate"]["conditions"]) == 6
    assert case["alert_id"] == "alt_1"
    assert db.store["cases/case1/narrative/v1"]["citation_map"]["0"] == [claims[0].claim_id]
