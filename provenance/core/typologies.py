"""Typology -> mandatory evidence, and typologies that may never auto-close.

Validate these with the AML SME session (STRATEGY.md, Phase 3). Until then they
are conservative: every typology needs transactions and a watchlist check.
"""
from __future__ import annotations

from provenance.core.models import EvidenceType as E
from provenance.core.models import Typology as T

MANDATORY_EVIDENCE: dict[T, list[E]] = {
    T.STRUCTURING: [E.TRANSACTIONS, E.WATCHLIST, E.KYC],
    T.RAPID_MOVEMENT: [E.TRANSACTIONS, E.WATCHLIST, E.ADVERSE_MEDIA],
    T.HIGH_RISK_CORRIDOR: [E.TRANSACTIONS, E.WATCHLIST, E.ADVERSE_MEDIA],
    T.SANCTIONS_NEXUS: [E.TRANSACTIONS, E.WATCHLIST, E.ADVERSE_MEDIA],
    T.MULE_FUNNEL: [E.TRANSACTIONS, E.WATCHLIST, E.NETWORK],
    T.ROUND_TRIPPING: [E.TRANSACTIONS, E.WATCHLIST, E.NETWORK],
}

# MVP starts with these three; the other three join in Phase 3.
MVP_TYPOLOGIES: frozenset[T] = frozenset(
    {T.STRUCTURING, T.SANCTIONS_NEXUS, T.RAPID_MOVEMENT}
)

NEVER_AUTO_CLOSE: frozenset[T] = frozenset({T.SANCTIONS_NEXUS})

# Freshness SLA per evidence type, in days.
FRESHNESS_SLA_DAYS: dict[E, int] = {
    E.WATCHLIST: 3,  # OFAC SDN updates on business days; 3 covers a weekend
    E.ADVERSE_MEDIA: 30,
    E.TRANSACTIONS: 30,
    E.NETWORK: 30,
    E.KYC: 365,
}
