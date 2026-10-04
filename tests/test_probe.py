import asyncio

import pytest

pytest.importorskip("google.adk")


def test_probe_rejects_uncited_sentence_without_changing_the_case():
    from fastapi.testclient import TestClient

    from provenance.runtime import from_bundle, get_deps, set_deps
    from provenance.service import run as run_mod
    from provenance.service.app import PROBE_SENTENCE, app

    set_deps(from_bundle(mode="offline"))
    run_mod._runners.clear()
    cid = asyncio.run(run_mod.run_case("alt_demo_grocer"))
    before = get_deps().repo.get_case(cid)
    assert before["decision"] == "auto_close"
    with TestClient(app) as c:
        r = c.post(f"/api/cases/{cid}/probe")
        assert r.status_code == 200
        probe = r.json()
        assert c.post("/api/cases/nope/probe").status_code == 404
    assert not probe["passed"] and probe["coverage"] < 1.0
    assert probe["failures"] == [PROBE_SENTENCE]
    assert "citation_coverage" in probe["gate_failed"] and probe["gate_decision"] == "escalate"
    after = get_deps().repo.get_case(cid)
    assert after["decision"] == "auto_close" and after["attempts"] == before["attempts"]
    assert [p["kind"] for p in after["probes"]] == ["verifier_probe"]


def test_probe_needs_a_finished_case():
    from fastapi.testclient import TestClient

    from provenance.core.models import Case
    from provenance.runtime import from_bundle, get_deps, set_deps
    from provenance.service.app import app

    set_deps(from_bundle(mode="offline"))
    get_deps().repo.create_case(Case(case_id="c_running", alert_id="alt_demo_hero"), status="running")
    with TestClient(app) as c:
        assert c.post("/api/cases/c_running/probe").status_code == 409
