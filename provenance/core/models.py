"""Typed data model for cases and the claim ledger.

Mirrors the Firestore layout in PLAN.md (cases/{caseId}/claims/{claimId}).
The two timestamps on Claim carry the whole thesis:
  source_as_of  -- when the publisher says the fact was true
  retrieved_at  -- when we fetched it
Most RAG systems record only the second. The staleness auditor enforces an SLA
on the first.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Typology(StrEnum):
    STRUCTURING = "structuring"
    RAPID_MOVEMENT = "rapid_movement"
    HIGH_RISK_CORRIDOR = "high_risk_corridor"
    SANCTIONS_NEXUS = "sanctions_nexus"
    MULE_FUNNEL = "mule_funnel"
    ROUND_TRIPPING = "round_tripping"


class EvidenceType(StrEnum):
    TRANSACTIONS = "transactions"
    KYC = "kyc"
    WATCHLIST = "watchlist"
    ADVERSE_MEDIA = "adverse_media"
    NETWORK = "network"


class SourceType(StrEnum):
    BIGQUERY = "bigquery"
    KYC_DOC = "kyc_doc"
    SANCTIONS_LIST = "sanctions_list"
    WEB_SEARCH = "web_search"
    GRAPH = "graph"


class Decision(StrEnum):
    AUTO_CLOSE = "auto_close"
    ESCALATE = "escalate"


class SupportSpan(BaseModel):
    """Google Search grounding support span, persisted verbatim from groundingMetadata."""

    start_index: int
    end_index: int
    chunk_indices: list[int] = Field(default_factory=list)
    confidence: float | None = None


class Claim(BaseModel):
    """One immutable entry in the claim ledger."""

    model_config = ConfigDict(frozen=True)

    assertion: str
    evidence_type: EvidenceType
    source_type: SourceType
    source_uri: str
    source_as_of: datetime
    retrieved_at: datetime
    freshness_sla_days: int = Field(gt=0)
    extraction_method: str
    produced_by_agent: str
    verbatim_quote: str | None = None
    support_span: SupportSpan | None = None
    # True when this claim records a sanctions or PEP match at any confidence.
    # The policy gate treats any such claim as an unconditional escalation.
    sanctions_or_pep_hit: bool = False
    match_confidence: float | None = None
    # True for a guardrail claim recording that untrusted content was withheld.
    # The policy gate then treats that evidence type as not gathered.
    withheld: bool = False
    # The name or entity this claim is about, when it was screened by name.
    # Lets the staleness sweep re-screen it later. Not part of the claim ID.
    subject: str | None = None

    @field_validator("source_as_of", "retrieved_at")
    @classmethod
    def _require_tz(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("timestamps must be timezone-aware (UTC)")
        return v

    @property
    def claim_id(self) -> str:
        """Content-addressed ID: the same fact from the same source always gets the same ID."""
        h = hashlib.sha256(
            "\x1f".join(
                [
                    self.assertion,
                    self.source_uri,
                    self.source_as_of.isoformat(),
                    self.verbatim_quote or "",
                    self.produced_by_agent,
                ]
            ).encode()
        ).hexdigest()
        return f"clm_{h[:10]}"

    def age_days(self, now: datetime, basis: str = "source_as_of") -> float:
        """Age of the fact. `basis="retrieved_at"` reproduces what a typical RAG
        system measures (when we fetched it), which is how stale evidence slips through."""
        ref = self.source_as_of if basis == "source_as_of" else self.retrieved_at
        return (now - ref) / timedelta(days=1)

    def is_stale(self, now: datetime, basis: str = "source_as_of") -> bool:
        return self.age_days(now, basis) > self.freshness_sla_days


class EvidencePlan(BaseModel):
    typology: Typology
    required: list[EvidenceType]
    gathered: list[EvidenceType] = Field(default_factory=list)

    @property
    def missing(self) -> list[EvidenceType]:
        return [e for e in self.required if e not in self.gathered]


class Case(BaseModel):
    case_id: str
    alert_id: str
    typology: Typology | None = None
    evidence_plan: EvidencePlan | None = None
    decision: Decision | None = None
    confidence: float | None = None
    trace_id: str | None = None
