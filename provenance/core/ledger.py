"""Append-only claim ledger.

The ledger writer is deliberately not an LLM. Agents propose claims; this code
records them. `LedgerStore` is the seam where the Firestore implementation plugs
in (cases/{caseId}/claims/{claimId}).
"""
from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol

from provenance.core.models import Claim, EvidenceType


class LedgerConflictError(Exception):
    """Raised when a claim ID is reused for different content. Should be impossible."""


class LedgerStore(Protocol):
    def append(self, claim: Claim) -> str: ...
    def get(self, claim_id: str) -> Claim | None: ...
    def all(self) -> list[Claim]: ...


class InMemoryLedger:
    def __init__(self, claims: Iterable[Claim] = ()) -> None:
        self._claims: dict[str, Claim] = {}
        for c in claims:
            self.append(c)

    def append(self, claim: Claim) -> str:
        cid = claim.claim_id
        existing = self._claims.get(cid)
        if existing is not None and existing != claim:
            raise LedgerConflictError(cid)
        self._claims[cid] = claim  # idempotent for identical claims
        return cid

    def get(self, claim_id: str) -> Claim | None:
        return self._claims.get(claim_id)

    def all(self) -> list[Claim]:
        return list(self._claims.values())

    def __contains__(self, claim_id: object) -> bool:
        return claim_id in self._claims

    def __len__(self) -> int:
        return len(self._claims)


def evidence_types(ledger: LedgerStore) -> set[EvidenceType]:
    return {c.evidence_type for c in ledger.all()}


def has_sanctions_or_pep_hit(ledger: LedgerStore) -> bool:
    return any(c.sanctions_or_pep_hit for c in ledger.all())


def withheld_evidence(ledger: LedgerStore) -> set[EvidenceType]:
    return {c.evidence_type for c in ledger.all() if c.withheld}
