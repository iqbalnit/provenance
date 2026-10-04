"""Adverse media claims from Google Search grounding metadata.

groundingMetadata IS the citation trail: we persist chunk URIs and support
spans verbatim instead of inventing a format. Each grounding support becomes
one claim, citing its first grounding chunk.

Notes:
- On Vertex, chunk URIs are grounding-api redirect links; the chunk title
  carries the publisher domain. Both are stored.
- Grounding chunks carry no publication date, so source_as_of is set to the
  retrieval time (the search index is live) and extraction_method says so.
- An empty result is itself a claim ("no adverse media found"), because the
  disposition will rely on it.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any
from urllib.parse import quote_plus

from provenance.core.guard import GuardResult, screen_untrusted
from provenance.core.models import Claim, EvidenceType, SourceType, SupportSpan
from provenance.core.typologies import FRESHNESS_SLA_DAYS
from provenance.sources import guard_modelarmor

AGENT = "adverse_media_analyst"


def _get(obj: Any, name: str, default: Any = None) -> Any:
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def screen(text: str) -> GuardResult:
    r = screen_untrusted(text)
    if r.allowed and guard_modelarmor.enabled():
        r = guard_modelarmor.screen(text)
    return r


def claims_from_grounding(subject: str, grounding: Any, retrieved_at: datetime) -> list[Claim]:
    chunks = _get(grounding, "grounding_chunks") or []
    supports = _get(grounding, "grounding_supports") or []
    common = dict(
        evidence_type=EvidenceType.ADVERSE_MEDIA,
        source_type=SourceType.WEB_SEARCH,
        source_as_of=retrieved_at,
        retrieved_at=retrieved_at,
        freshness_sla_days=FRESHNESS_SLA_DAYS[EvidenceType.ADVERSE_MEDIA],
        produced_by_agent=AGENT,
    )
    claims: list[Claim] = []
    withheld: list[tuple[str, list[str]]] = []  # (chunk uri, reasons)
    for s in supports:
        seg = _get(s, "segment")
        text = (_get(seg, "text") or "").strip()
        idx = list(_get(s, "grounding_chunk_indices") or [])
        if not text or not idx or idx[0] >= len(chunks):
            continue  # an unsupported sentence never becomes a claim
        web = _get(chunks[idx[0]], "web")
        uri = _get(web, "uri")
        if not uri:
            continue
        verdict = screen(text)
        if not verdict.allowed:
            withheld.append((uri, verdict.reasons))
            continue  # untrusted instruction-shaped text never becomes a claim
        scores = list(_get(s, "confidence_scores") or [])
        claims.append(
            Claim(
                assertion=f"Web source ({_get(web, 'title') or 'unknown'}) on {subject}: {text}",
                source_uri=uri,
                verbatim_quote=text,
                extraction_method="grounding_support_v1(source_as_of=retrieved_at)",
                support_span=SupportSpan(
                    start_index=_get(seg, "start_index") or 0,
                    end_index=_get(seg, "end_index") or len(text),
                    chunk_indices=idx,
                    confidence=max(scores) if scores else None,
                ),
                **common,
            )
        )
    if withheld:
        reasons = sorted({r for _, rs in withheld for r in rs})
        claims.append(
            Claim(
                assertion=(f"The injection guard withheld {len(withheld)} web result(s) about {subject} "
                           f"({', '.join(reasons)}); adverse media needs human review."),
                source_uri=withheld[0][0],
                extraction_method="injection_guard_v1",
                withheld=True,
                **common,
            )
        )
    if not claims:
        claims.append(
            Claim(
                assertion=f"A live web search for adverse media on {subject} returned no supported findings.",
                source_uri=f"google_search:q={quote_plus(subject)}",
                extraction_method="grounding_empty_v1",
                **common,
            )
        )
    return claims
