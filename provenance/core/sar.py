"""Templated SAR draft for escalated cases (MVP; the LLM drafter is Phase 3).

Every sentence cites the ledger, so the draft passes the same verifier as the
disposition. Watermarked DRAFT; never filed automatically.
"""
from __future__ import annotations

from provenance.core.ledger import LedgerStore
from provenance.core.models import EvidenceType
from provenance.core.policy_gate import GateResult

WATERMARK = "DRAFT - NOT FILED - requires analyst review."


def draft_sar(*, subject: str, account_id: str, typology: str, gate: GateResult, ledger: LedgerStore) -> str:
    claims = ledger.all()
    by_type: dict[EvidenceType, list] = {}
    for c in claims:
        by_type.setdefault(c.evidence_type, []).append(c)
    lines = [WATERMARK]
    order = [EvidenceType.WATCHLIST, EvidenceType.ADVERSE_MEDIA, EvidenceType.TRANSACTIONS,
             EvidenceType.KYC, EvidenceType.NETWORK]
    lines.append(f"Subject: {subject}, account {account_id}; suspected typology: {typology}.")
    for et in order:
        for c in by_type.get(et, []):
            lines.append(f"{c.assertion.rstrip('.')} [{c.claim_id}].")
    failed = ", ".join(c.name for c in gate.failed) or "none"
    lines.append(f"Escalation reason: policy gate conditions not met: {failed}.")
    return "\n".join(lines)
