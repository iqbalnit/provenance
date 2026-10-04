from provenance.eval.baselines import A1_PROMPT, run_a0, run_a1
from provenance.eval.results import summarize

ALERTS = [
    {"alert_id": "alt_1", "account_id": "A", "rule": "structuring", "typology_hint": "structuring",
     "window_start": "2026-01-01", "window_end": "2026-01-05", "txn_ids": ["t1"],
     "truly_suspicious": True, "laundering_types": ["Structuring"], "split": "golden"},
    {"alert_id": "alt_2", "account_id": "B", "rule": "structuring", "typology_hint": "structuring",
     "window_start": "2026-01-01", "window_end": "2026-01-05", "txn_ids": ["t2"],
     "truly_suspicious": False, "laundering_types": [], "split": "golden"},
]
TXNS = {
    "t1": {"Txn_id": "t1", "Sender_account": "S1", "Receiver_account": "A", "Amount": "9000",
           "Is_laundering": "1", "Laundering_type": "Structuring"},
    "t2": {"Txn_id": "t2", "Sender_account": "S2", "Receiver_account": "B", "Amount": "9000",
           "Is_laundering": "0", "Laundering_type": "Normal"},
}


def test_a0_escalates_everything():
    s = summarize(run_a0(ALERTS, "r"))
    assert s["auto_close_rate"] == 0 and s["fn_rate_on_auto_close"] == 0


def test_a1_uncited_and_hallucinating_baseline_is_scored():
    prompts = []

    def fake_generate(prompt):
        prompts.append(prompt)
        return {"decision": "auto_close", "confidence": 0.93,
                "narrative": "Deposits are consistent with a small retail business. Counterparty ACME Holdings is a known supplier.",
                "entities_named": ["A", "ACME Holdings"]}

    rows = run_a1(ALERTS, TXNS, fake_generate, "r", "pinned-model")
    s = summarize(rows)
    assert s["citation_coverage_mean"] == 0.0
    # alt_1: "ACME Holdings" invented (1/2). alt_2: both invented, "A" is not in its input (2/2).
    assert s["hallucinated_entity_rate_mean"] == 0.75
    assert s["tp_auto_closes"] == 1 and s["fn_rate_on_auto_close"] == 1.0
    # The label never reaches the model.
    assert all("Is_laundering" not in p and "truly_suspicious" not in p and "Structuring\"" not in p for p in prompts)
    assert "{alert}" in A1_PROMPT
