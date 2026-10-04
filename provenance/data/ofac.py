"""Fetch archived and live OFAC SDN snapshots, validate them, and stage them in GCS.

    python -m provenance.data.ofac fetch --archived 20250301 \
        --live --live-as-of 2026-09-25 [--upload]

- Archived: Wayback Machine raw capture of treasury.gov/ofac/downloads/sdn.csv.
  source_as_of = the capture timestamp Wayback redirects to (an upper bound on
  the list's publication date, which is the conservative direction for us).
- Live: the OFAC Sanctions List Service export. Its CSV carries no reliable
  publication date, so pass the date shown on the OFAC "Recent Actions" page
  as --live-as-of.

Both URLs are unverified from the build container (egress blocked); check them
on first run. Every snapshot is parsed with load_sdn_csv() and must contain
MIN_ENTRIES rows, which catches HTML error pages saved as CSV.
"""
from __future__ import annotations

import argparse
import gzip
import re
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

from provenance.tools.watchlist import WatchlistSnapshot, load_sdn_csv

LIVE_URL = "https://sanctionslistservice.ofac.treas.gov/api/PublicationPreview/exports/SDN.CSV"
TREASURY_SDN = "https://www.treasury.gov/ofac/downloads/sdn.csv"
SNAPSHOT_DIR = Path("data/snapshots/ofac")
MIN_ENTRIES = 1_000
_WAYBACK_TS = re.compile(r"/web/(\d{14})id_/")


def wayback_url(yyyymmdd: str) -> str:
    if not re.fullmatch(r"\d{8}(\d{6})?", yyyymmdd):
        raise ValueError("expected YYYYMMDD or YYYYMMDDhhmmss")
    return f"https://web.archive.org/web/{yyyymmdd}id_/{TREASURY_SDN}"


def capture_time(final_url: str) -> datetime:
    m = _WAYBACK_TS.search(final_url)
    if not m:
        raise ValueError(f"no Wayback capture timestamp in {final_url!r}")
    return datetime.strptime(m.group(1), "%Y%m%d%H%M%S").replace(tzinfo=UTC)


def _maybe_gunzip(body: bytes) -> bytes:
    """Some servers (and Wayback captures) return gzip bodies even when asked not to."""
    return gzip.decompress(body) if body[:2] == b"\x1f\x8b" else body


def _download(url: str, dest: Path, timeout: int = 120) -> str:
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "provenance-ai-builder-cup/0.1",
                                               "Accept-Encoding": "identity"})
    with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 (fixed https URLs)
        dest.write_bytes(_maybe_gunzip(r.read()))
        return r.geturl()


def gcs_uri(bucket: str, as_of: datetime) -> str:
    return f"gs://{bucket}/ofac/{as_of.date().isoformat()}/sdn.csv"


def validate(path: Path, as_of: datetime, source_uri: str) -> WatchlistSnapshot:
    snap = load_sdn_csv(path, as_of=as_of, source_uri=source_uri)
    if len(snap.entries) < MIN_ENTRIES:
        raise ValueError(f"{path} parsed to {len(snap.entries)} entries (< {MIN_ENTRIES}); not a real SDN list?")
    return snap


def fetch_archived(yyyymmdd: str, out_dir: Path = SNAPSHOT_DIR) -> tuple[Path, datetime]:
    tmp = out_dir / f"archived-{yyyymmdd}.csv"
    final = _download(wayback_url(yyyymmdd), tmp)
    as_of = capture_time(final)
    dest = out_dir / as_of.date().isoformat() / "sdn.csv"
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp.replace(dest)
    return dest, as_of


def fetch_live(as_of: datetime, out_dir: Path = SNAPSHOT_DIR) -> Path:
    dest = out_dir / as_of.date().isoformat() / "sdn.csv"
    _download(LIVE_URL, dest)
    return dest


def upload(path: Path, as_of: datetime, bucket: str, client=None) -> str:
    """Upload with as_of stored as object metadata so readers never guess it."""
    if client is None:
        from google.cloud import storage  # noqa: PLC0415

        client = storage.Client()
    uri = gcs_uri(bucket, as_of)
    blob = client.bucket(bucket).blob(uri.removeprefix(f"gs://{bucket}/"))
    blob.metadata = {"as_of": as_of.isoformat()}
    blob.upload_from_filename(str(path), content_type="text/csv")
    return uri


def load_snapshot_from_gcs(uri: str, client=None, cache_dir: Path = SNAPSHOT_DIR / "cache") -> WatchlistSnapshot:
    if client is None:
        from google.cloud import storage  # noqa: PLC0415

        client = storage.Client()
    bucket, _, name = uri.removeprefix("gs://").partition("/")
    blob = client.bucket(bucket).get_blob(name)
    if blob is None:
        raise FileNotFoundError(uri)
    as_of = datetime.fromisoformat((blob.metadata or {})["as_of"])
    local = cache_dir / name
    local.parent.mkdir(parents=True, exist_ok=True)
    blob.download_to_filename(str(local))
    return load_sdn_csv(local, as_of=as_of, source_uri=uri)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fetch")
    f.add_argument("--archived", help="Wayback date YYYYMMDD for the stale snapshot")
    f.add_argument("--live", action="store_true")
    f.add_argument("--live-as-of", help="publication date of the live list, YYYY-MM-DD")
    f.add_argument("--upload", action="store_true")
    a = ap.parse_args()

    staged: list[tuple[Path, datetime, str]] = []
    if a.archived:
        path, as_of = fetch_archived(a.archived)
        staged.append((path, as_of, "archived"))
    if a.live:
        if not a.live_as_of:
            ap.error("--live requires --live-as-of")
        as_of = datetime.fromisoformat(a.live_as_of).replace(tzinfo=UTC)
        staged.append((fetch_live(as_of), as_of, "live"))
    from provenance import config  # noqa: PLC0415

    for path, as_of, label in staged:
        uri = gcs_uri(config.gcs_bucket(), as_of) if a.upload else str(path)
        snap = validate(path, as_of, uri)
        print(f"{label}: {len(snap.entries)} entries, as_of {as_of.isoformat()}, {path}")
        if a.upload:
            print(f"  uploaded {upload(path, as_of, config.gcs_bucket())}")


if __name__ == "__main__":
    main()
