"""The hero demo as a test: the same alert, archived vs live OFAC snapshot.

Uses fictional list entries. Swap in the real hero persona once chosen (data/README.md).
"""
from datetime import UTC, datetime

from provenance.core.decide import decide_case
from provenance.core.ledger import InMemoryLedger
from provenance.core.models import Decision, EvidenceType as E, SourceType, Typology
from provenance.tools.watchlist import check_name, load_sdn_csv
from tests.conftest import FIXTURES, NOW, make_claim

HERO = "Placeholder Persona Hero"
ARCHIVED = load_sdn_csv(
    FIXTURES / "sdn_archived.csv",
    as_of=datetime(2025, 3, 1, tzinfo=UTC),
    source_uri="gs://provenance-snapshots/ofac/2025-03-01/sdn.csv",
)
LIVE = load_sdn_csv(
    FIXTURES / "sdn_live.csv",
    as_of=datetime(2026, 9, 25, tzinfo=UTC),
    source_uri="gs://provenance-snapshots/ofac/2026-09-25/sdn.csv",
)


def _run(snapshot, basis="source_as_of"):
    txn = make_claim("Account received 22,000 and sent 19,500 onward within 30 hours.")
    media = make_claim(
        "No adverse media found for the customer name.",
        evidence_type=E.ADVERSE_MEDIA,
        source_type=SourceType.WEB_SEARCH,
        source_uri="https://www.google.com/search?q=placeholder",
        produced_by_agent="adverse_media_analyst",
        extraction_method="grounding_support",
    )
    wl = check_name(HERO, snapshot, retrieved_at=NOW)
    ledger = InMemoryLedger([txn, media, wl])
    narrative = (
        f"Funds moved in and out within 30 hours [{txn.claim_id}]. "
        f"The customer is not sanctioned [{wl.claim_id}]. "
        f"No adverse media was found [{media.claim_id}]."
    )
    return wl, decide_case(
        typology=Typology.RAPID_MOVEMENT,
        ledger=ledger,
        narrative=narrative,
        confidence=0.96,
        now=NOW,
        staleness_basis=basis,
    )


def test_naive_freshness_auto_closes_on_archived_list():
    """What a typical RAG system does: the list was fetched this morning, so it looks fresh."""
    wl, d = _run(ARCHIVED, basis="retrieved_at")
    assert not wl.sanctions_or_pep_hit
    assert d.decision is Decision.AUTO_CLOSE


def test_source_as_of_catches_the_stale_list_even_without_the_new_designation():
    wl, d = _run(ARCHIVED)
    assert d.decision is Decision.ESCALATE
    assert d.staleness.penalty > 0
    assert [s.claim_id for s in d.staleness.stale_claims] == [wl.claim_id]
    assert [c.name for c in d.gate.failed] == ["staleness"]


def test_live_list_finds_the_designation_and_escalates():
    wl, d = _run(LIVE)
    assert wl.sanctions_or_pep_hit
    assert "10003" in wl.source_uri
    assert d.decision is Decision.ESCALATE
    assert d.staleness.penalty == 0
    assert "no_sanctions_or_pep_hit" in [c.name for c in d.gate.failed]
