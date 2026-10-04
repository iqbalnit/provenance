"""Deterministic core. No Google Cloud imports allowed in this package.

Everything that decides whether a case may auto-close lives here, so it can be
unit-tested offline and audited line by line. The LLM agents produce inputs to
these modules; they never override them.
"""
from provenance.core.ledger import InMemoryLedger, LedgerStore
from provenance.core.models import (
    Case,
    Claim,
    Decision,
    EvidencePlan,
    EvidenceType,
    SourceType,
    SupportSpan,
    Typology,
)
from provenance.core.policy_gate import GateInput, GateResult, evaluate_gate
from provenance.core.staleness import StalenessReport, audit_staleness
from provenance.core.verifier import VerificationResult, verify_narrative

__all__ = [
    "Case",
    "Claim",
    "Decision",
    "EvidencePlan",
    "EvidenceType",
    "GateInput",
    "GateResult",
    "InMemoryLedger",
    "LedgerStore",
    "SourceType",
    "StalenessReport",
    "SupportSpan",
    "Typology",
    "VerificationResult",
    "audit_staleness",
    "evaluate_gate",
    "verify_narrative",
]
