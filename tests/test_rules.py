from datetime import datetime, timedelta

from provenance.rules.engine import Txn, generate_alerts, measure_fp_rate

T0 = datetime(2026, 1, 1, 9)


def tx(i, sender, receiver, amount, hours, laundering=False, loc="UK"):
    return Txn(f"t{i}", T0 + timedelta(hours=hours), sender, receiver, amount, "UK", loc, "Cash", laundering)


def test_structuring_and_labels():
    txns = [tx(i, f"s{i}", "A", 9_500, i * 24, laundering=(i == 0)) for i in range(3)]
    alerts = [a for a in generate_alerts(txns) if a.rule == "structuring"]
    assert len(alerts) == 1 and alerts[0].account_id == "A"
    assert alerts[0].truly_suspicious
    assert alerts[0].alert_id.startswith("alt_")


def test_rapid_movement_and_fp_rate():
    txns = [tx(0, "X", "B", 25_000, 0), tx(1, "B", "Y", 21_000, 10)]
    alerts = [a for a in generate_alerts(txns) if a.rule == "rapid_movement"]
    assert len(alerts) == 1
    assert measure_fp_rate(alerts) == 1.0
