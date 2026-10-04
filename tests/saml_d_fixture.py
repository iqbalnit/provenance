"""Build a small SAML-D-shaped CSV with a known false-positive structure.

Structuring rule (threshold 10k, floor 80%, 7-day window):
- `n_laundering` accounts get 3 sub-threshold deposits, labelled laundering
- `n_benign3` accounts get 3 sub-threshold deposits, benign
- `n_benign2` accounts get 2 sub-threshold deposits, benign

So min_count=3 gives FP = b3 / (b3 + L), and min_count=2 gives FP = (b3 + b2) / (b3 + b2 + L).
"""
from __future__ import annotations

import csv
from datetime import datetime, timedelta
from pathlib import Path

from provenance.data.saml_d import RAW_COLUMNS

T0 = datetime(2026, 1, 5, 9, 0)


def _row(i, day, sender, receiver, amount, laundering):
    ts = T0 + timedelta(days=day, minutes=i)
    return {
        "Time": ts.strftime("%H:%M:%S"), "Date": ts.date().isoformat(),
        "Sender_account": sender, "Receiver_account": receiver, "Amount": f"{amount:.2f}",
        "Payment_currency": "UK pounds", "Received_currency": "UK pounds",
        "Sender_bank_location": "UK", "Receiver_bank_location": "UK",
        "Payment_type": "Cash Deposit", "Is_laundering": "1" if laundering else "0",
        "Laundering_type": "Structuring" if laundering else "Normal_Cash_Deposits",
    }


def build(path: Path, n_laundering=4, n_benign3=46, n_benign2=50) -> Path:
    rows, i = [], 0
    groups = [("L", n_laundering, 3, True), ("B3_", n_benign3, 3, False), ("B2_", n_benign2, 2, False)]
    for prefix, count, deposits, laundering in groups:
        for a in range(count):
            for d in range(deposits):
                rows.append(_row(i, d * 2.5, f"src{i}", f"{prefix}{a}", 9_000 + d, laundering))
                i += 1
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=RAW_COLUMNS)
        w.writeheader()
        w.writerows(rows)
    return path
