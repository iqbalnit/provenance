import pytest

from provenance.eval import diagnose as dg
from provenance.eval.results import EvalRow, write_jsonl


def row(i, p_fp, suspicious, decision="escalate", gate=None, coverage=1.0):
    conf = None if p_fp is None else (p_fp if decision == "auto_close" else 1 - p_fp)
    return EvalRow(run_id="r", arm="A3", alert_id=f"a{i}", split="golden", decision=decision, confidence=conf,
                   truly_suspicious=suspicious, citation_coverage=coverage, hallucinated_entity_rate=None,
                   gate_failed=gate)


def test_p_false_positive_inverts_escalation_confidence():
    assert dg.p_false_positive(row(0, 0.3, False)) == pytest.approx(0.3)
    assert dg.p_false_positive(row(1, 0.95, False, decision="auto_close")) == pytest.approx(0.95)
    assert dg.p_false_positive(row(2, None, True, decision="error")) is None


def test_auroc_and_zero_miss_threshold():
    assert dg.auroc([0.6, 0.7], [0.1, 0.2]) == 1.0
    assert dg.auroc([0.1, 0.2], [0.1, 0.2]) == 0.5
    rows = [row(0, 0.7, False), row(1, 0.6, False), row(2, 0.3, False), row(3, 0.4, True), row(4, 0.05, True),
            row(5, None, True, decision="error", coverage=0.0)]
    d = dg.diagnose(rows, {"a0": "structuring", "a3": "structuring"})
    assert d["errors"] == 1 and d["scored"] == 5
    assert d["auroc"] == round(5 / 6, 3)  # 0.3 < 0.4 is the one mis-ordered pair
    best = d["best_zero_miss"]
    assert best["auto_close"] == 2 and best["suspicious_auto_closed"] == 0 and 0.4 < best["theta"] <= 0.6
    assert d["by_rule"]["structuring"]["n"] == 2


def test_gate_failures_are_counted_by_label(tmp_path):
    rows = [row(0, 0.2, False, gate=["confidence"]), row(1, 0.1, True, gate=["confidence", "no_sanctions_or_pep_hit"])]
    d = dg.diagnose(rows)
    assert d["gate_failed"] == {"benign": {"confidence": 1}, "suspicious": {"confidence": 1, "no_sanctions_or_pep_hit": 1}}
    path = write_jsonl(rows, tmp_path)
    assert "AUROC" in dg.render(dg.diagnose(dg.read_jsonl(path)))


def test_gate_failed_never_reaches_the_bigquery_payload():
    import json

    r = row(0, 0.2, False, gate=["confidence"])
    assert "gate_failed" not in json.loads(r.model_dump_json(exclude={"gate_failed"}))


def test_detail_shows_label_source_and_what_stopped_each_row():
    rows = [row(0, 0.95, True, gate=["staleness"]), row(1, 0.92, False, decision="auto_close", gate=[]),
            row(2, 0.10, True, gate=["confidence", "no_sanctions_or_pep_hit"]), row(3, 0.20, False)]
    meta = {"a0": {"rule": "rapid_movement", "label_source": "sanctions_exposure", "designated_after_archive": True},
            "a2": {"rule": "structuring", "label_source": "saml_d"}}
    items = dg.detail(rows, meta, 0.9)
    assert [x["alert_id"] for x in items] == ["a0", "a2", "a1"]  # suspicious first, a3 is neither
    assert items[0]["label_source"] == "sanctions (new)" and items[0]["gate_failed"] == ["staleness"]
    assert "none" in dg.render_detail(items, 0.9)  # a1 passed every condition
