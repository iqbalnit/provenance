"""Deterministic citation verifier.

Not an LLM judging an LLM: a parser that fails the draft. Every sentence of a
disposition narrative must carry at least one citation token `[clm_xxxxxxxxxx]`
that resolves in the ledger. If any sentence fails, the draft is rejected and
the disposition agent's LoopAgent retries (max 2) before escalating.

That makes citation coverage 1.0 a structural guarantee for anything we emit,
not a measured average.
"""
from __future__ import annotations

import re

from pydantic import BaseModel

from provenance.core.ledger import LedgerStore

CITATION_RE = re.compile(r"\[(clm_[0-9a-f]{10})\]")
# Split after sentence-ending punctuation (optionally followed by citations/quotes).
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])(?:\s*\[clm_[0-9a-f]{10}\])*\s+(?=[A-Z0-9\"'(])")


class SentenceCheck(BaseModel):
    index: int
    text: str
    claim_ids: list[str]
    unresolved_ids: list[str]

    @property
    def ok(self) -> bool:
        return bool(self.claim_ids) and not self.unresolved_ids


class VerificationResult(BaseModel):
    passed: bool
    coverage: float
    sentences: list[SentenceCheck]
    # sentence index -> resolvable claim ids; persisted as narrative.citation_map
    citation_map: dict[int, list[str]]

    @property
    def failures(self) -> list[SentenceCheck]:
        return [s for s in self.sentences if not s.ok]

    def feedback(self) -> str:
        """Rejection message handed back to the disposition agent on retry."""
        lines = []
        for s in self.failures:
            if not s.claim_ids:
                lines.append(f"Sentence {s.index} has no citation: {s.text!r}")
            else:
                lines.append(
                    f"Sentence {s.index} cites unknown claim(s) {s.unresolved_ids}: {s.text!r}"
                )
        return "\n".join(lines)


def split_sentences(text: str) -> list[str]:
    text = text.strip()
    if not text:
        return []
    # Keep trailing citations attached to the sentence they follow.
    parts: list[str] = []
    last = 0
    for m in _SENTENCE_SPLIT_RE.finditer(text):
        parts.append(text[last : m.end()].strip())
        last = m.end()
    parts.append(text[last:].strip())
    return [p for p in parts if p]


def verify_narrative(narrative: str, ledger: LedgerStore) -> VerificationResult:
    sentences = split_sentences(narrative)
    checks: list[SentenceCheck] = []
    for i, s in enumerate(sentences):
        ids = list(dict.fromkeys(CITATION_RE.findall(s)))
        unresolved = [cid for cid in ids if ledger.get(cid) is None]
        checks.append(SentenceCheck(index=i, text=s, claim_ids=ids, unresolved_ids=unresolved))

    ok = [c for c in checks if c.ok]
    coverage = len(ok) / len(checks) if checks else 0.0
    return VerificationResult(
        passed=bool(checks) and len(ok) == len(checks),
        coverage=coverage,
        sentences=checks,
        citation_map={c.index: [x for x in c.claim_ids if x not in c.unresolved_ids] for c in checks},
    )
