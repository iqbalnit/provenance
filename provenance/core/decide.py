"""The deterministic tail of every case: verify, audit freshness, gate.

The disposition agent proposes (narrative, confidence). This function decides.
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from provenance.core.ledger import LedgerStore, evidence_types, has_sanctions_or_pep_hit, withheld_evidence
from provenance.core.models import Decision, Typology
from provenance.core.policy_gate import DEFAULT_THETA, GateInput, GateResult, evaluate_gate
from provenance.core.staleness import Basis, StalenessReport, audit_staleness
from provenance.core.verifier import VerificationResult, verify_narrative


class CaseDecision(BaseModel):
    decision: Decision
    verification: VerificationResult
    staleness: StalenessReport
    gate: GateResult


def decide_case(
    *,
    typology: Typology,
    ledger: LedgerStore,
    narrative: str,
    confidence: float,
    now: datetime,
    theta: float = DEFAULT_THETA,
    staleness_basis: Basis = "source_as_of",
) -> CaseDecision:
    verification = verify_narrative(narrative, ledger)
    staleness = audit_staleness(ledger, now, basis=staleness_basis)
    gate = evaluate_gate(
        GateInput(
            typology=typology,
            confidence=confidence,
            gathered_evidence=evidence_types(ledger),
            staleness_penalty=staleness.penalty,
            citation_coverage=verification.coverage,
            sanctions_or_pep_hit=has_sanctions_or_pep_hit(ledger),
            withheld_evidence=withheld_evidence(ledger),
            theta=theta,
        )
    )
    return CaseDecision(decision=gate.decision, verification=verification, staleness=staleness, gate=gate)
