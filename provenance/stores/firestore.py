"""Firestore implementations: the claim ledger and case writes.

Layout (PLAN.md):
  cases/{caseId}                       typology, evidence_plan, disposition, confidence,
                                       policy_gate{conditions[], passed}, staleness{…}
  cases/{caseId}/claims/{claimId}      THE LEDGER, append-only
  cases/{caseId}/narrative/{version}   text + citation_map

Timestamps are stored as native Firestore timestamps so the console's realtime
listeners can render source_as_of / retrieved_at directly.

The client is injected (google.cloud.firestore.Client in production, a fake in
tests), so this module never imports google-cloud at load time.
"""
from __future__ import annotations

from typing import Any

from provenance.core.decide import CaseDecision
from provenance.core.ledger import LedgerConflictError
from provenance.core.models import Case, Claim

CASES = "cases"


def _claim_to_doc(c: Claim) -> dict[str, Any]:
    return {**c.model_dump(mode="python"), "claim_id": c.claim_id}


def _doc_to_claim(d: dict[str, Any]) -> Claim:
    return Claim.model_validate({k: v for k, v in d.items() if k != "claim_id"})


def _is_already_exists(e: Exception) -> bool:
    return type(e).__name__ in {"AlreadyExists", "Conflict"}


class FirestoreLedger:
    """LedgerStore backed by cases/{case_id}/claims."""

    def __init__(self, client: Any, case_id: str) -> None:
        self._col = client.collection(CASES).document(case_id).collection("claims")

    def append(self, claim: Claim) -> str:
        cid = claim.claim_id
        ref = self._col.document(cid)
        try:
            ref.create(_claim_to_doc(claim))  # fails if it exists: append-only
        except Exception as e:
            if not _is_already_exists(e):
                raise
            existing = _doc_to_claim(ref.get().to_dict())
            if existing != claim:
                raise LedgerConflictError(cid) from e
        return cid

    def get(self, claim_id: str) -> Claim | None:
        snap = self._col.document(claim_id).get()
        return _doc_to_claim(snap.to_dict()) if snap.exists else None

    def all(self) -> list[Claim]:
        return [_doc_to_claim(s.to_dict()) for s in self._col.stream()]


class CaseRepository:
    def __init__(self, client: Any) -> None:
        self._client = client

    def _case(self, case_id: str):
        return self._client.collection(CASES).document(case_id)

    def ledger(self, case_id: str) -> FirestoreLedger:
        return FirestoreLedger(self._client, case_id)

    def create_case(self, case: Case, **extra: Any) -> None:
        self._case(case.case_id).set({**case.model_dump(mode="json", exclude_none=True), **extra}, merge=True)

    def update(self, case_id: str, fields: dict[str, Any]) -> None:
        self._case(case_id).set(fields, merge=True)

    def list_cases(self) -> list[dict[str, Any]]:
        """All case documents. Fine at hackathon scale; production adds a where() on decision."""
        return [s.to_dict() for s in self._client.collection(CASES).stream()]

    def add_review(self, case_id: str, review: dict[str, Any]) -> int:
        """Analyst decision, appended to cases/{id}/human_decisions and mirrored on the case."""
        col = self._case(case_id).collection("human_decisions")
        n = sum(1 for _ in col.stream()) + 1
        col.document(f"{n:04d}").set({**review, "n": n})
        self._case(case_id).set({"human_decision": {**review, "n": n}}, merge=True)
        return n

    def get_case(self, case_id: str) -> dict[str, Any] | None:
        """Case document plus its claims, for the console API."""
        snap = self._case(case_id).get()
        if not snap.exists:
            return None
        doc = snap.to_dict()
        doc["claims"] = [c.to_dict() for c in self._case(case_id).collection("claims").stream()]
        doc["human_decisions"] = [h.to_dict() for h in self._case(case_id).collection("human_decisions").stream()]
        return doc

    def write_decision(self, case_id: str, d: CaseDecision, narrative: str, version: int) -> None:
        case = self._case(case_id)
        case.collection("narrative").document(f"v{version}").set(
            {
                "text": narrative,
                "passed": d.verification.passed,
                "coverage": d.verification.coverage,
                # Firestore map keys must be strings.
                "citation_map": {str(k): v for k, v in d.verification.citation_map.items()},
            }
        )
        case.set(
            {
                "decision": d.decision.value,
                "policy_gate": {
                    "passed": d.gate.passed,
                    "conditions": [c.model_dump() for c in d.gate.conditions],
                },
                "staleness": {
                    "penalty": d.staleness.penalty,
                    "stale_claims": [s.model_dump(mode="python") for s in d.staleness.stale_claims],
                },
                "narrative_version": version,
            },
            merge=True,
        )
