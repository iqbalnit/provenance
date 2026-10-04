"""OFAC SDN snapshot loading and name matching. Deterministic; no GCP needed.

Every check returns a Claim, including a *no-hit*, because "not on the list"
is itself an assertion whose truth depends on how old the list is. That no-hit
claim is exactly what the staleness auditor catches in the hero demo.

The SDN CSV (sanctionslist.ofac.treas.gov, sdn.csv) has no header row; columns:
ent_num, SDN_Name, SDN_Type, Program, Title, Call_Sign, Vess_type, Tonnage,
GRT, Vess_flag, Vess_owner, Remarks. Missing values are "-0-".
"""
from __future__ import annotations

import csv
import io
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from provenance.core.models import Claim, EvidenceType, SourceType
from provenance.core.typologies import FRESHNESS_SLA_DAYS

AGENT = "watchlist_analyst"
PARTIAL_MATCH_THRESHOLD = 0.8


@dataclass(frozen=True)
class SdnEntry:
    ent_num: str
    name: str
    sdn_type: str
    program: str


@dataclass(frozen=True)
class WatchlistSnapshot:
    list_name: str
    source_uri: str  # e.g. gs://provenance-snapshots/ofac/2025-03-01/sdn.csv
    as_of: datetime  # the publisher's date for this version of the list
    entries: tuple[SdnEntry, ...]


def load_sdn_csv(path: str | Path, *, as_of: datetime, source_uri: str) -> WatchlistSnapshot:
    entries = []
    raw = Path(path).read_bytes()
    for enc in ("utf-8-sig", "cp1252", "latin-1"):  # OFAC files are not always strict UTF-8
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    for row in csv.reader(io.StringIO(text, newline="")):
        if len(row) < 4 or not row[0].strip().isdigit():
            continue
        entries.append(
            SdnEntry(
                ent_num=row[0].strip(),
                name=row[1].strip(),
                sdn_type=_clean(row[2]),
                program=_clean(row[3]),
            )
        )
    return WatchlistSnapshot("OFAC SDN", source_uri, as_of, tuple(entries))


def _clean(v: str) -> str:
    v = v.strip()
    return "" if v == "-0-" else v


def _tokens(name: str) -> frozenset[str]:
    n = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return frozenset(t for t in re.split(r"[^A-Z0-9]+", n.upper()) if t)


def _score(a: frozenset[str], b: frozenset[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def check_name(name: str, snapshot: WatchlistSnapshot, *, retrieved_at: datetime) -> Claim:
    q = _tokens(name)
    best: tuple[float, SdnEntry | None] = (0.0, None)
    for e in snapshot.entries:
        s = _score(q, _tokens(e.name))
        if s > best[0]:
            best = (s, e)
    score, entry = best
    as_of = snapshot.as_of.date().isoformat()
    common = dict(
        evidence_type=EvidenceType.WATCHLIST,
        source_type=SourceType.SANCTIONS_LIST,
        source_as_of=snapshot.as_of,
        retrieved_at=retrieved_at,
        freshness_sla_days=FRESHNESS_SLA_DAYS[EvidenceType.WATCHLIST],
        extraction_method="token_set_jaccard_v1",
        produced_by_agent=AGENT,
        subject=name,
    )
    if entry is not None and score >= PARTIAL_MATCH_THRESHOLD:
        return Claim(
            assertion=(
                f"{name} matches {snapshot.list_name} entry #{entry.ent_num} "
                f"({entry.name}, program {entry.program or 'n/a'}) with score {score:.2f}, "
                f"list version as of {as_of}."
            ),
            source_uri=f"{snapshot.source_uri}#ent_num={entry.ent_num}",
            verbatim_quote=entry.name,
            sanctions_or_pep_hit=True,
            match_confidence=round(score, 4),
            **common,
        )
    return Claim(
        assertion=f"{name} does not appear on {snapshot.list_name}, list version as of {as_of}.",
        source_uri=snapshot.source_uri,
        match_confidence=round(score, 4),
        **common,
    )
