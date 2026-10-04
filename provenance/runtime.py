"""Runtime dependencies for the agent graph and the service.

PROVENANCE_MODE   offline  scripted models, no network (tests, CI, fallback demo)
                  gemini   real Gemini on Vertex via ADK
PROVENANCE_DATA   bundle   the committed demo bundle in demo/ (default)
                  gcp      BigQuery transactions, GCS snapshots and KYC, Firestore
PROVENANCE_STORE  memory   in-process case store (default for bundle; single instance only)
                  firestore  Firestore (default for gcp; required when Cloud Run scales out)

Any combination works; `gemini` + `bundle` is the quickest way to see the real
model on known data.
"""
from __future__ import annotations

import json
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, time
from pathlib import Path
from typing import Any

from provenance.sources.txn import LocalTxnSource, TxnSource
from provenance.stores.firestore import CaseRepository
from provenance.stores.memory import FakeFirestore
from provenance.tools.watchlist import WatchlistSnapshot, load_sdn_csv

BUNDLE = Path(__file__).resolve().parent.parent / "demo"


@dataclass
class Deps:
    mode: str
    alerts: dict[str, dict]
    customers: dict[str, dict]
    kyc_uri: Callable[[str], str]
    txns: TxnSource
    watchlists: dict[str, WatchlistSnapshot]
    repo: CaseRepository
    now: Callable[[], datetime] = field(default=lambda: datetime.now(UTC))
    media_cache: dict[str, Any] = field(default_factory=dict)  # offline mode only


def _resolve_as_of(v: str, now: datetime) -> datetime:
    """'today' resolves to 00:00 UTC today, so the bundle's live list stays live."""
    if v == "today":
        return datetime.combine(now.date(), time(0), tzinfo=UTC)
    d = datetime.fromisoformat(v)
    return d if d.tzinfo else d.replace(tzinfo=UTC)


def from_bundle(path: Path = BUNDLE, mode: str = "offline", repo: CaseRepository | None = None) -> Deps:
    m = json.loads((path / "manifest.json").read_text())
    now = datetime.now(UTC)
    alerts = {a["alert_id"]: a for a in map(json.loads, (path / "alerts.jsonl").read_text().splitlines()) if a}
    snaps = {
        name: load_sdn_csv(path / s["file"], as_of=_resolve_as_of(s["as_of"], now), source_uri=s["uri"])
        for name, s in m["snapshots"].items()
    }
    return Deps(
        mode=mode,
        alerts=alerts,
        customers=json.loads((path / "customers.json").read_text()),
        kyc_uri=lambda acct: f"{m['kyc_uri_prefix']}/{acct}.json",
        txns=LocalTxnSource(path / "transactions.csv", _resolve_as_of(m["transactions_as_of"], now), m["transactions_uri"]),
        watchlists=snaps,
        repo=repo or CaseRepository(FakeFirestore()),
        media_cache=json.loads((path / "media.json").read_text()),
    )


def from_gcp(mode: str = "gemini") -> Deps:  # pragma: no cover - needs GCP
    """Production wiring. Untested from the build container; exercise it on first deploy."""
    from google.cloud import bigquery, firestore, storage  # noqa: PLC0415

    from provenance import config  # noqa: PLC0415
    from provenance.data.ofac import load_snapshot_from_gcs  # noqa: PLC0415
    from provenance.sources.txn import BigQueryTxnSource  # noqa: PLC0415

    bq = bigquery.Client(project=config.project())
    gcs = storage.Client(project=config.project())
    ds = config.bq_dataset()
    alerts = {r["alert_id"]: _plain(dict(r)) for r in bq.query(
        f"SELECT alert_id, account_id, rule, typology_hint, window_start, window_end, txn_ids, split, "
        f"truly_suspicious FROM `{ds}.alerts`").result()}  # labels are stripped before any model sees them
    bucket = config.gcs_bucket()
    customers = json.loads(gcs.bucket(bucket).blob("kyc/customers.json").download_as_text())
    txn_table = bq.get_table(f"{ds}.transactions")
    return Deps(
        mode=mode,
        alerts=alerts,
        customers=customers,
        kyc_uri=lambda acct: f"gs://{bucket}/kyc/customers.json#{acct}",
        txns=BigQueryTxnSource(ds, txn_table.modified, bq),
        watchlists={
            "archived": load_snapshot_from_gcs(os.environ["PROVENANCE_OFAC_ARCHIVED_URI"], gcs),
            "live": load_snapshot_from_gcs(os.environ["PROVENANCE_OFAC_LIVE_URI"], gcs),
        },
        repo=CaseRepository(firestore.Client(project=config.project())),
    )


def _plain(row: dict) -> dict:
    """BigQuery returns datetimes/dates; the agent graph expects the same ISO strings as alerts.jsonl."""
    out = {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in row.items()}
    for k in ("alert_id", "account_id", "sdn_ent_num"):  # IDs are always strings, whatever the column type
        if out.get(k) is not None:
            out[k] = str(out[k])
    if "txn_ids" in out:
        out["txn_ids"] = [str(t) for t in out["txn_ids"] or []]
    return out


_deps: Deps | None = None


def set_deps(d: Deps) -> None:
    global _deps
    _deps = d


def get_deps() -> Deps:
    global _deps
    if _deps is None:
        mode = os.environ.get("PROVENANCE_MODE", "offline")
        if os.environ.get("PROVENANCE_DATA") == "gcp":
            _deps = from_gcp(mode)
        else:
            repo = None
            if os.environ.get("PROVENANCE_STORE") == "firestore":  # pragma: no cover - needs GCP
                from google.cloud import firestore  # noqa: PLC0415

                repo = CaseRepository(firestore.Client())
            _deps = from_bundle(mode=mode, repo=repo)
    return _deps
