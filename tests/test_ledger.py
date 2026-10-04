import pytest

from provenance.core.ledger import InMemoryLedger, LedgerConflictError
from provenance.core.models import Claim
from tests.conftest import make_claim


def test_claim_ids_are_content_addressed_and_idempotent():
    a = make_claim()
    led = InMemoryLedger()
    assert led.append(a) == led.append(make_claim()) == a.claim_id
    assert len(led) == 1


def test_claims_are_immutable():
    with pytest.raises(Exception):
        make_claim().assertion = "changed"  # type: ignore[misc]


def test_naive_timestamps_rejected():
    from datetime import datetime

    with pytest.raises(ValueError):
        make_claim(as_of=datetime(2026, 1, 1))


def test_conflict_detected(monkeypatch):
    a, b = make_claim("x."), make_claim("y.")
    monkeypatch.setattr(Claim, "claim_id", property(lambda self: "clm_0000000000"))
    led = InMemoryLedger([a])
    with pytest.raises(LedgerConflictError):
        led.append(b)
