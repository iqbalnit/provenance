import asyncio
import base64
import json
from datetime import UTC, datetime

import pytest

from provenance.core.sweep import recheck
from provenance.tools.watchlist import check_name, load_sdn_csv
from tests.conftest import FIXTURES, NOW

ARCHIVED = load_sdn_csv(FIXTURES / "sdn_archived.csv", as_of=datetime(2025, 3, 1, tzinfo=UTC), source_uri="a")
LIVE = load_sdn_csv(FIXTURES / "sdn_live.csv", as_of=datetime(2026, 9, 26, tzinfo=UTC), source_uri="l")


def test_recheck_flags_new_designation():
    old = check_name("Placeholder Persona Hero", ARCHIVED, retrieved_at=NOW)
    f = recheck([old], LIVE, NOW)
    assert [x.kind for x in f] == ["designation_changed"] and "now matches" in f[0].reason


def test_recheck_flags_stale_without_change_and_passes_fresh():
    old = check_name("Nobody In Particular", ARCHIVED, retrieved_at=NOW)
    assert [x.kind for x in recheck([old], LIVE, NOW)] == ["stale"]
    fresh = check_name("Nobody In Particular", LIVE, retrieved_at=NOW)
    assert recheck([fresh], LIVE, NOW) == []


@pytest.fixture
def svc():
    pytest.importorskip("google.adk")
    from provenance.runtime import from_bundle, get_deps, set_deps
    from provenance.service import run as run_mod

    set_deps(from_bundle(mode="offline"))
    run_mod._runners.clear()
    return get_deps, run_mod


def test_sweep_reopens_the_naively_closed_hero(svc):
    from provenance.service.sweep import sweep

    get_deps, run_mod = svc
    d = get_deps()
    closed = asyncio.run(run_mod.run_case("alt_demo_hero", "archived", "retrieved_at"))
    fine = asyncio.run(run_mod.run_case("alt_demo_grocer", "live", "source_as_of"))
    assert d.repo.get_case(closed)["decision"] == "auto_close"

    out = asyncio.run(sweep(d, wait=True))
    assert out["checked"] == 2 and [r["case_id"] for r in out["reopened"]] == [closed]
    old = d.repo.get_case(closed)
    assert old["status"] == "reopened" and old["reopen_findings"][0]["kind"] == "designation_changed"
    new = d.repo.get_case(out["reopened"][0]["new_case_id"])
    assert new["decision"] == "escalate" and new["reopens"] == closed
    assert d.repo.get_case(fine)["status"] == "done"
    # Idempotent: a second sweep does not reopen again.
    assert asyncio.run(sweep(d, wait=True))["reopened"] == []


def test_pubsub_push_envelope(svc):
    from fastapi.testclient import TestClient

    from provenance.service.app import app

    body = {"message": {"data": base64.b64encode(json.dumps({"source": "scheduler"}).encode()).decode(), "messageId": "1"},
            "subscription": "projects/p/subscriptions/s"}
    with TestClient(app) as c:
        r = c.post("/trigger/sweep", json=body)
    assert r.status_code == 200 and r.json()["checked"] == 0
