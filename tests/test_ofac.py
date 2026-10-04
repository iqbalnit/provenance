from datetime import UTC, datetime

import pytest

from provenance.data import ofac
from tests.conftest import FIXTURES
from provenance.stores.memory import FakeGCS


def test_wayback_url_and_capture_time():
    assert ofac.wayback_url("20250301") == (
        "https://web.archive.org/web/20250301id_/https://www.treasury.gov/ofac/downloads/sdn.csv"
    )
    with pytest.raises(ValueError):
        ofac.wayback_url("2025-03-01")
    final = "https://web.archive.org/web/20250228193012id_/https://www.treasury.gov/ofac/downloads/sdn.csv"
    assert ofac.capture_time(final) == datetime(2025, 2, 28, 19, 30, 12, tzinfo=UTC)


def test_validate_rejects_tiny_or_html_files(tmp_path):
    p = tmp_path / "sdn.csv"
    p.write_text("<html>rate limited</html>")
    with pytest.raises(ValueError):
        ofac.validate(p, datetime(2025, 3, 1, tzinfo=UTC), "x")


def test_gcs_round_trip_preserves_as_of(tmp_path):
    gcs = FakeGCS()
    as_of = datetime(2025, 3, 1, tzinfo=UTC)
    uri = ofac.upload(FIXTURES / "sdn_archived.csv", as_of, "bkt", client=gcs)
    assert uri == "gs://bkt/ofac/2025-03-01/sdn.csv"
    snap = ofac.load_snapshot_from_gcs(uri, client=gcs, cache_dir=tmp_path)
    assert snap.as_of == as_of and snap.source_uri == uri and len(snap.entries) == 2
