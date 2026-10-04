"""Function tools for the evidence agents.

Tools write claims to the ledger themselves and return only claim IDs and
assertions to the model. The model chooses what to look up; it can never
author a claim's content or its source.
"""
from __future__ import annotations

from google.adk.tools import ToolContext

from provenance.core.models import Claim, EvidenceType, SourceType
from provenance.core.typologies import FRESHNESS_SLA_DAYS
from provenance.runtime import get_deps
from provenance.sources import txn as txn_source
from provenance.tools.bq_templates import TEMPLATES
from provenance.tools.watchlist import check_name


def _summary(c: Claim) -> dict:
    return {"claim_id": c.claim_id, "assertion": c.assertion}


def query_transactions(
    template_id: str,
    account_id: str,
    start_date: str,
    end_date: str,
    tool_context: ToolContext,
    floor: float = 8000.0,
    threshold: float = 10000.0,
) -> dict:
    """Run a named transaction query template and record its facts as claims.

    Args:
      template_id: one of account_activity_window_v1, sub_threshold_deposits_v1, top_counterparties_v1.
      account_id: the alerted account or one of its counterparties in the alert window.
      start_date: YYYY-MM-DD.
      end_date: YYYY-MM-DD.
      floor: lower bound for sub_threshold_deposits_v1.
      threshold: reporting threshold for sub_threshold_deposits_v1.
    """
    st = tool_context.state
    if template_id not in TEMPLATES:
        return {"error": f"unknown template {template_id}; choose from {sorted(TEMPLATES)}"}
    if account_id not in st["scope_accounts"]:
        return {"error": f"account {account_id} is outside this alert's scope {st['scope_accounts']}"}
    d = get_deps()
    params = txn_source.build_params(template_id, account_id, start_date[:10], end_date[:10], floor, threshold)
    res = d.txns.run(template_id, params)
    ledger = d.repo.ledger(st["case_id"])
    claims = [
        Claim(
            assertion=a,
            evidence_type=EvidenceType.TRANSACTIONS,
            source_type=SourceType.BIGQUERY,
            source_uri=res.source_uri,
            source_as_of=res.as_of,
            retrieved_at=d.now(),
            freshness_sla_days=FRESHNESS_SLA_DAYS[EvidenceType.TRANSACTIONS],
            extraction_method=f"sql_template:{template_id}",
            produced_by_agent="txn_analyst",
        )
        for a in txn_source.facts(template_id, params, res.rows)
    ]
    for c in claims:
        ledger.append(c)
    return {"rows": len(res.rows), "claims": [_summary(c) for c in claims]}


def screen_name(name: str, tool_context: ToolContext) -> dict:
    """Screen a person or company name against the sanctions list and record the result as a claim.

    Args:
      name: full name exactly as it appears in the customer profile or transaction data.
    """
    st = tool_context.state
    d = get_deps()
    snapshot = d.watchlists[st["snapshot"]]
    claim = check_name(name, snapshot, retrieved_at=d.now())
    d.repo.ledger(st["case_id"]).append(claim)
    return {**_summary(claim), "sanctions_hit": claim.sanctions_or_pep_hit,
            "list_as_of": snapshot.as_of.date().isoformat()}
