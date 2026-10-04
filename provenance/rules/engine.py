"""Deterministic transaction-monitoring rule engine that generates our alerts.

We generate alerts ourselves rather than quote an industry statistic: run a
standard rule set over SAML-D, take ground truth from its laundering labels,
and tune THRESHOLDS until the measured false-positive rate is 95–97%. That buys
the line "we reproduced the industry's false-positive rate, then measured what
our agent does to it".
"""
from __future__ import annotations

import hashlib
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from itertools import takewhile


@dataclass(frozen=True)
class Txn:
    txn_id: str
    ts: datetime
    sender: str
    receiver: str
    amount: float
    sender_location: str
    receiver_location: str
    payment_type: str
    is_laundering: bool
    laundering_type: str = ""

    @classmethod
    def from_saml_d(cls, row: dict, idx: int) -> Txn:
        """SAML-D columns: Time, Date, Sender_account, Receiver_account, Amount,
        Payment_currency, Received_currency, Sender_bank_location,
        Receiver_bank_location, Payment_type, Is_laundering, Laundering_type."""
        return cls(
            txn_id=row.get("Txn_id") or f"t{idx}",
            ts=datetime.fromisoformat(f"{row['Date']}T{row['Time']}"),
            sender=str(row["Sender_account"]),
            receiver=str(row["Receiver_account"]),
            amount=float(row["Amount"]),
            sender_location=row["Sender_bank_location"],
            receiver_location=row["Receiver_bank_location"],
            payment_type=row["Payment_type"],
            is_laundering=str(row["Is_laundering"]) in {"1", "True", "true"},
            laundering_type=row.get("Laundering_type", ""),
        )


# Tune these until measure_fp_rate() lands at 0.95–0.97. Record the final values
# and the measured rate in the README; that number opens the video.
THRESHOLDS = {
    "structuring": {"threshold": 10_000.0, "floor_pct": 0.8, "min_count": 3, "window_days": 7},
    "rapid_movement": {"min_inflow": 20_000.0, "outflow_pct": 0.8, "window_hours": 48},
    "high_risk_corridor": {"locations": {"Mexico", "Turkey", "Morocco", "Nigeria", "UAE"}, "min_amount": 5_000.0},
}

# Rule -> the typology the alert is initially hinted as. The Typologist agent
# re-infers typology from evidence; this is only the rule's label.
RULE_TYPOLOGY = {
    "structuring": "structuring",
    "rapid_movement": "rapid_movement",
    "high_risk_corridor": "high_risk_corridor",
}


@dataclass
class Alert:
    account_id: str
    rule: str
    window_start: datetime
    window_end: datetime
    txn_ids: list[str] = field(default_factory=list)
    truly_suspicious: bool = False
    laundering_types: set[str] = field(default_factory=set)

    @property
    def alert_id(self) -> str:
        h = hashlib.sha256(f"{self.account_id}|{self.rule}|{self.window_start.isoformat()}".encode())
        return f"alt_{h.hexdigest()[:10]}"


def _by_account(txns: Iterable[Txn]) -> dict[str, list[Txn]]:
    acc: dict[str, list[Txn]] = defaultdict(list)
    for t in txns:
        acc[t.sender].append(t)
        if t.receiver != t.sender:
            acc[t.receiver].append(t)
    for v in acc.values():
        v.sort(key=lambda t: t.ts)
    return acc


def _label(alert: Alert, txns: Sequence[Txn]) -> Alert:
    alert.txn_ids = [t.txn_id for t in txns]
    alert.truly_suspicious = any(t.is_laundering for t in txns)
    alert.laundering_types = {t.laundering_type for t in txns if t.is_laundering and t.laundering_type}
    return alert


Thresholds = dict[str, dict]


def rule_structuring(account: str, txns: Sequence[Txn], p: dict) -> list[Alert]:
    lo, hi = p["threshold"] * p["floor_pct"], p["threshold"]
    credits = [t for t in txns if t.receiver == account and lo <= t.amount < hi]
    win = timedelta(days=p["window_days"])
    out: list[Alert] = []
    i = 0
    while i < len(credits):
        group = list(takewhile(lambda t: t.ts - credits[i].ts <= win, credits[i:]))
        if len(group) >= p["min_count"]:
            out.append(_label(Alert(account, "structuring", group[0].ts, group[-1].ts), group))
            i += len(group)
        else:
            i += 1
    return out


def rule_rapid_movement(account: str, txns: Sequence[Txn], p: dict) -> list[Alert]:
    win = timedelta(hours=p["window_hours"])
    out: list[Alert] = []
    last_end: datetime | None = None
    for i, t in enumerate(txns):
        if t.receiver != account or (last_end and t.ts <= last_end):
            continue
        window = list(takewhile(lambda x: x.ts - t.ts <= win, txns[i:]))
        inflow = sum(x.amount for x in window if x.receiver == account)
        outflow = sum(x.amount for x in window if x.sender == account)
        if inflow >= p["min_inflow"] and outflow >= p["outflow_pct"] * inflow:
            out.append(_label(Alert(account, "rapid_movement", window[0].ts, window[-1].ts), window))
            last_end = window[-1].ts
    return out


def rule_high_risk_corridor(account: str, txns: Sequence[Txn], p: dict) -> list[Alert]:
    hits = [
        t
        for t in txns
        if t.sender == account
        and t.amount >= p["min_amount"]
        and t.receiver_location in p["locations"]
    ]
    return [_label(Alert(account, "high_risk_corridor", t.ts, t.ts), [t]) for t in hits]


RULES = {
    "structuring": rule_structuring,
    "rapid_movement": rule_rapid_movement,
    "high_risk_corridor": rule_high_risk_corridor,
}


def generate_alerts(txns: Iterable[Txn], thresholds: Thresholds | None = None) -> list[Alert]:
    thresholds = thresholds or THRESHOLDS
    alerts: list[Alert] = []
    for account, acc_txns in _by_account(txns).items():
        for name, rule in RULES.items():
            alerts.extend(rule(account, acc_txns, thresholds[name]))
    return alerts


def measure_fp_rate(alerts: Sequence[Alert]) -> float:
    return sum(not a.truly_suspicious for a in alerts) / len(alerts) if alerts else 0.0
