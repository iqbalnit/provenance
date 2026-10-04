"""Transaction evidence: run a named template, turn rows into claims.

The agent chooses the template and parameters; this module runs it and writes
the facts. The LLM never writes SQL and never writes a claim's text.

Two backends with identical semantics:
  LocalTxnSource     SAML-D-shaped CSV (offline demo, tests)
  BigQueryTxnSource  provenance/tools/bq_templates.py against BigQuery

source_as_of for transaction facts is when our copy of the bank's ledger was
last refreshed (the extract time), not the transaction dates: the question the
staleness auditor asks is "could newer activity have changed this fact?".
"""
from __future__ import annotations

import csv
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Protocol

from provenance.data.saml_d import to_account_rows
from provenance.tools import bq_templates


@dataclass(frozen=True)
class TxnResult:
    rows: list[dict[str, Any]]
    source_uri: str
    as_of: datetime


class TxnSource(Protocol):
    def run(self, template_id: str, params: dict[str, Any]) -> TxnResult: ...


def build_params(template_id: str, account_id: str, start_date: str, end_date: str,
                 floor: float | None = None, threshold: float | None = None) -> dict[str, Any]:
    p: dict[str, Any] = {"account_id": account_id, "start_date": start_date, "end_date": end_date}
    if template_id == "sub_threshold_deposits_v1":
        p |= {"floor": floor if floor is not None else 8_000.0, "threshold": threshold if threshold is not None else 10_000.0}
    bq_templates.validate(template_id, p)
    return p


class LocalTxnSource:
    def __init__(self, csv_path: Path, as_of: datetime, uri_prefix: str = "local://transactions") -> None:
        self.as_of = as_of
        self.uri_prefix = uri_prefix
        self._by_account: dict[str, list[dict]] = defaultdict(list)
        with open(csv_path, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                for row in to_account_rows(r):
                    row["amount"] = float(row["amount"])
                    self._by_account[row["account_id"]].append(row)
        for rows in self._by_account.values():
            rows.sort(key=lambda r: r["ts"])

    def _window(self, p: dict) -> list[dict]:
        lo, hi = date.fromisoformat(str(p["start_date"])), date.fromisoformat(str(p["end_date"]))
        return [r for r in self._by_account.get(p["account_id"], [])
                if lo <= date.fromisoformat(r["booking_date"]) <= hi]

    def run(self, template_id: str, params: dict[str, Any]) -> TxnResult:
        bq_templates.validate(template_id, params)
        rows = self._window(params)
        if template_id == "account_activity_window_v1":
            out = [{k: r[k] for k in ("booking_date", "amount", "currency", "direction", "counterparty_account", "payment_type")} for r in rows][:500]
        elif template_id == "sub_threshold_deposits_v1":
            daily: dict[str, list[float]] = defaultdict(list)
            for r in rows:
                if r["direction"] == "credit" and params["floor"] <= r["amount"] <= params["threshold"]:
                    daily[r["booking_date"]].append(r["amount"])
            out = [{"booking_date": d, "n": len(v), "total": sum(v)} for d, v in sorted(daily.items())]
        elif template_id == "top_counterparties_v1":
            agg: dict[str, dict] = {}
            for r in rows:
                a = agg.setdefault(r["counterparty_account"], {"counterparty_account": r["counterparty_account"], "n": 0, "total": 0.0,
                                                               "first_seen": r["booking_date"], "last_seen": r["booking_date"]})
                a["n"] += 1
                a["total"] += r["amount"]
                a["last_seen"] = r["booking_date"]
            out = sorted(agg.values(), key=lambda a: -a["total"])[:20]
        else:  # validate() already rejected unknown ids
            raise KeyError(template_id)
        fp = bq_templates.fingerprint(template_id, params)
        return TxnResult(out, f"{self.uri_prefix}?template={template_id}&fingerprint={fp}", self.as_of)


class BigQueryTxnSource:
    def __init__(self, dataset: str, as_of: datetime, client: Any = None) -> None:
        self.dataset, self.as_of, self.client = dataset, as_of, client

    def run(self, template_id: str, params: dict[str, Any]) -> TxnResult:
        rows, uri = bq_templates.run(template_id, params, dataset=self.dataset, client=self.client)
        return TxnResult(rows, uri, self.as_of)


def _money(x: float) -> str:
    return f"{x:,.2f}"


def facts(template_id: str, params: dict[str, Any], rows: list[dict]) -> list[str]:
    """Deterministic assertions from template output. One claim per string."""
    acct, lo, hi = params["account_id"], params["start_date"], params["end_date"]
    if template_id == "account_activity_window_v1":
        cr = [r for r in rows if r["direction"] == "credit"]
        db = [r for r in rows if r["direction"] == "debit"]
        return [
            f"Account {acct} had {len(rows)} transactions between {lo} and {hi}: "
            f"{len(cr)} credits totalling {_money(sum(float(r['amount']) for r in cr))} and "
            f"{len(db)} debits totalling {_money(sum(float(r['amount']) for r in db))}."
        ]
    if template_id == "sub_threshold_deposits_v1":
        n = sum(r["n"] for r in rows)
        total = sum(float(r["total"]) for r in rows)
        return [
            f"Account {acct} received {n} credits between {_money(params['floor'])} and "
            f"{_money(params['threshold'])} on {len(rows)} distinct days between {lo} and {hi}, "
            f"totalling {_money(total)}."
        ]
    if template_id == "top_counterparties_v1":
        if not rows:
            return [f"Account {acct} had no counterparties between {lo} and {hi}."]
        return [
            f"Counterparty {r['counterparty_account']} transacted with account {acct} {r['n']} times "
            f"totalling {_money(float(r['total']))} between {r['first_seen']} and {r['last_seen']}."
            for r in rows[:3]
        ]
    raise KeyError(template_id)
