from provenance.core.ledger import InMemoryLedger
from provenance.core.verifier import split_sentences, verify_narrative
from tests.conftest import make_claim


def _ledger():
    a = make_claim("Account A received 14 sub-threshold deposits in 9 days.")
    b = make_claim("Customer states occupation as software engineer.", produced_by_agent="kyc_analyst")
    return InMemoryLedger([a, b]), a.claim_id, b.claim_id


def test_fully_cited_narrative_passes():
    led, a, b = _ledger()
    text = f"The account received 14 deposits just under the threshold [{a}]. Stated occupation does not explain this [{b}][{a}]."
    r = verify_narrative(text, led)
    assert r.passed
    assert r.coverage == 1.0
    assert r.citation_map == {0: [a], 1: [b, a]}


def test_one_uncited_sentence_rejects_the_draft():
    led, a, _ = _ledger()
    text = f"The account received 14 deposits [{a}]. The customer is also linked to a shell company."
    r = verify_narrative(text, led)
    assert not r.passed
    assert r.coverage == 0.5
    assert [f.index for f in r.failures] == [1]
    assert "no citation" in r.feedback()


def test_unresolvable_claim_id_rejects_the_draft():
    led, a, _ = _ledger()
    text = f"The account received 14 deposits [{a}][clm_deadbeef00]."
    r = verify_narrative(text, led)
    assert not r.passed
    assert r.failures[0].unresolved_ids == ["clm_deadbeef00"]


def test_empty_narrative_fails():
    led, _, _ = _ledger()
    assert not verify_narrative("   ", led).passed


def test_citation_after_period_stays_with_its_sentence():
    assert split_sentences("One fact. [clm_0123456789] Two fact [clm_abcdefabcd].") == [
        "One fact. [clm_0123456789]",
        "Two fact [clm_abcdefabcd].",
    ]
