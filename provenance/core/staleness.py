"""Staleness auditor (deterministic half).

A claim is stale when the publisher's own timestamp (source_as_of) is older than
the freshness SLA for its evidence type, measured against `now`. Any stale claim
makes the penalty non-zero, and a non-zero penalty blocks auto-close.
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from provenance.core.ledger import LedgerStore


class StaleClaim(BaseModel):
    claim_id: str
    evidence_type: str
    source_uri: str
    source_as_of: datetime
    age_days: float
    sla_days: int


class StalenessReport(BaseModel):
    penalty: float
    stale_claims: list[StaleClaim]

    @property
    def is_clean(self) -> bool:
        return self.penalty == 0


Basis = Literal["source_as_of", "retrieved_at"]


def audit_staleness(
    ledger: LedgerStore, now: datetime, basis: Basis = "source_as_of"
) -> StalenessReport:
    """`basis="retrieved_at"` exists only to reproduce the naive behaviour for the
    demo and eval arm A4: an 18-month-old list fetched this morning looks fresh."""
    stale: list[StaleClaim] = []
    for c in ledger.all():
        if c.is_stale(now, basis):
            stale.append(
                StaleClaim(
                    claim_id=c.claim_id,
                    evidence_type=c.evidence_type.value,
                    source_uri=c.source_uri,
                    source_as_of=c.source_as_of,
                    age_days=round(c.age_days(now, basis), 2),
                    sla_days=c.freshness_sla_days,
                )
            )
    claims = ledger.all()
    penalty = len(stale) / len(claims) if claims else 0.0
    return StalenessReport(penalty=penalty, stale_claims=stale)
