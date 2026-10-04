"""Parameterized BigQuery templates for txn_analyst. Never free-form SQL.

The agent picks a template by name and supplies typed parameters; it never
writes SQL. Each result is recorded with a fingerprint (template id + params)
that becomes the claim's source_uri: bq://<table>?template=<id>&fingerprint=<sha>.

Keep every query partition-pruned (booking_date filter) and column-explicit:
BigQuery bills per byte scanned and this runs inside an agent loop.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Template:
    id: str
    sql: str
    params: dict[str, str]  # name -> BigQuery type


TEMPLATES: dict[str, Template] = {
    t.id: t
    for t in [
        Template(
            id="account_activity_window_v1",
            sql="""
SELECT booking_date, amount, currency, direction, counterparty_account, payment_type
FROM `{dataset}.transactions`
WHERE account_id = @account_id
  AND booking_date BETWEEN @start_date AND @end_date
ORDER BY booking_date
LIMIT 500""",
            params={"account_id": "STRING", "start_date": "DATE", "end_date": "DATE"},
        ),
        Template(
            id="sub_threshold_deposits_v1",
            sql="""
SELECT booking_date, COUNT(*) AS n, SUM(amount) AS total
FROM `{dataset}.transactions`
WHERE account_id = @account_id
  AND direction = 'credit'
  AND amount BETWEEN @floor AND @threshold
  AND booking_date BETWEEN @start_date AND @end_date
GROUP BY booking_date
ORDER BY booking_date""",
            params={
                "account_id": "STRING",
                "floor": "NUMERIC",
                "threshold": "NUMERIC",
                "start_date": "DATE",
                "end_date": "DATE",
            },
        ),
        Template(
            id="top_counterparties_v1",
            sql="""
SELECT counterparty_account, COUNT(*) AS n, SUM(amount) AS total,
       MIN(booking_date) AS first_seen, MAX(booking_date) AS last_seen
FROM `{dataset}.transactions`
WHERE account_id = @account_id
  AND booking_date BETWEEN @start_date AND @end_date
GROUP BY counterparty_account
ORDER BY total DESC
LIMIT 20""",
            params={"account_id": "STRING", "start_date": "DATE", "end_date": "DATE"},
        ),
    ]
}


def fingerprint(template_id: str, params: dict[str, Any]) -> str:
    blob = json.dumps({"t": template_id, "p": params}, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def validate(template_id: str, params: dict[str, Any]) -> Template:
    t = TEMPLATES.get(template_id)
    if t is None:
        raise KeyError(f"unknown template {template_id!r}")
    if set(params) != set(t.params):
        raise ValueError(f"{template_id} expects params {sorted(t.params)}, got {sorted(params)}")
    return t


def _typed(bq_type: str, v: Any) -> Any:
    """The BigQuery client wants date / Decimal objects for DATE / NUMERIC parameters, not strings or floats."""
    from datetime import date  # noqa: PLC0415
    from decimal import Decimal  # noqa: PLC0415

    if bq_type == "DATE" and isinstance(v, str):
        return date.fromisoformat(v[:10])
    if bq_type == "NUMERIC" and not isinstance(v, Decimal):
        return Decimal(str(v))
    return v


def run(template_id: str, params: dict[str, Any], *, dataset: str, client: Any = None):
    """Execute a template. Imports BigQuery lazily so the module loads without GCP deps."""
    from google.cloud import bigquery  # noqa: PLC0415

    t = validate(template_id, params)
    client = client or bigquery.Client()
    cfg = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter(k, t.params[k], _typed(t.params[k], v)) for k, v in params.items()],
        maximum_bytes_billed=2 * 1024**3,  # hard cap per query: 2 GiB
    )
    rows = [dict(r) for r in client.query(t.sql.format(dataset=dataset), job_config=cfg).result()]
    return rows, f"bq://{dataset}.transactions?template={template_id}&fingerprint={fingerprint(template_id, params)}"
