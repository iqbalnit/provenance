import json
from datetime import datetime

from provenance.data.alerts import build as build_alerts
from provenance.data.alerts import load_txns, select, split, tune
from provenance.data.saml_d import sample
from provenance.rules.engine import Alert, measure_fp_rate
from tests.saml_d_fixture import build


def _alerts(n, positives):
    out = []
    for i in range(n):
        a = Alert(f"acc{i}", "structuring" if i % 2 else "rapid_movement", datetime(2026, 1, 1), datetime(2026, 1, 2))
        a.truly_suspicious = i < positives
        out.append(a)
    return out


def test_tune_picks_config_closest_to_target(tmp_path):
    txns = load_txns(sample(build(tmp_path / "raw.csv"), tmp_path / "s.csv", 1.0) and tmp_path / "s.csv")
    th, report = tune(txns, {"structuring.min_count": [2, 3]})
    fps = {r["overrides"]["structuring.min_count"]: r["fp_rate"] for r in report}
    assert fps == {2: 0.96, 3: 0.92}
    assert th["structuring"]["min_count"] == 2


def test_select_preserves_fp_rate():
    pop = _alerts(1000, 40)
    chosen = select(pop, 300)
    assert len(chosen) == 300
    assert abs(measure_fp_rate(chosen) - measure_fp_rate(pop)) <= 0.01
    assert [a.alert_id for a in select(pop, 300)] == [a.alert_id for a in chosen]


def test_split_sizes_and_golden_enrichment():
    chosen = _alerts(300, 12)
    s = split(chosen)
    counts = {k: list(s.values()).count(k) for k in ("golden", "eval", "demo")}
    assert counts == {"golden": 40, "eval": 200, "demo": 60}
    pos = {a.alert_id for a in chosen if a.truly_suspicious}
    assert sum(1 for k, v in s.items() if v == "golden" and k in pos) == 6  # min(8, 12 // 2)
    assert split(chosen) == s


def test_build_end_to_end(tmp_path):
    sample(build(tmp_path / "raw.csv"), tmp_path / "s.csv", 1.0)
    summary = build_alerts(tmp_path / "s.csv", n=100, out_dir=tmp_path, grid={"structuring.min_count": [2, 3]})
    assert summary["selected_fp_rate"] == 0.96
    lines = (tmp_path / "alerts.jsonl").read_text().splitlines()
    assert len(lines) == 100
    rec = json.loads(lines[0])
    assert {"alert_id", "txn_ids", "truly_suspicious", "split", "typology_hint"} <= set(rec)
    assert json.loads((tmp_path / "tuning_report.json").read_text())["thresholds"]["structuring"]["min_count"] == 2


def test_thousand_alert_split_gives_golden_eight_positives():
    from provenance.data.alerts import _scaled_sizes

    chosen = _alerts(1000, 27)
    s = split(chosen, _scaled_sizes(1000))
    counts = {k: list(s.values()).count(k) for k in ("golden", "eval", "demo")}
    assert counts == {"golden": 40, "eval": 900, "demo": 60}
    pos = {a.alert_id for a in chosen if a.truly_suspicious}
    assert sum(1 for k, v in s.items() if v == "golden" and k in pos) == 8


def test_arms_select_alerts_limit_is_deterministic():
    from provenance.eval.arms import select_alerts

    rows = [{"alert_id": f"a{i}", "split": "eval", "truly_suspicious": i % 2 == 0} for i in (3, 1, 2)]
    rows.append({"alert_id": "unlabelled", "split": "eval"})
    assert [r["alert_id"] for r in select_alerts(rows, "eval", 2)] == ["a1", "a2"]
    assert len(select_alerts(rows, "all")) == 3
