"""Staleness sweep (deterministic): should an auto-closed case be reopened?

Nightly, every auto-closed case's watchlist claims are re-screened against the
current list. A case reopens when a subject's designation status has changed,
or when a claim it relied on is now past its freshness SLA by publisher date.
This is the thesis applied after the fact: a decision is only as good as the
evidence under it, and evidence ages.
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from provenance.core.models import Claim, EvidenceType
from provenance.tools.watchlist import WatchlistSnapshot, check_name


class SweepFinding(BaseModel):
    claim_id: str
    kind: str  # "designation_changed" | "stale"
    reason: str


def recheck(claims: list[Claim], live: WatchlistSnapshot, now: datetime) -> list[SweepFinding]:
    findings: list[SweepFinding] = []
    for c in claims:
        if c.evidence_type is not EvidenceType.WATCHLIST or not c.subject:
            continue
        fresh = check_name(c.subject, live, retrieved_at=now)
        if fresh.sanctions_or_pep_hit != c.sanctions_or_pep_hit:
            now_state = "now matches" if fresh.sanctions_or_pep_hit else "no longer matches"
            findings.append(SweepFinding(
                claim_id=c.claim_id, kind="designation_changed",
                reason=f"{c.subject} {now_state} the {live.list_name} list as of "
                       f"{live.as_of.date().isoformat()} ({fresh.source_uri}).",
            ))
        elif c.is_stale(now):
            findings.append(SweepFinding(
                claim_id=c.claim_id, kind="stale",
                reason=f"Screening of {c.subject} used a list as of {c.source_as_of.date().isoformat()}, "
                       f"past its {c.freshness_sla_days}-day SLA.",
            ))
    return findings
