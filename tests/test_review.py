import asyncio

import pytest

from provenance.eval.results import labels_from_reviews

pytest.importorskip("google.adk")


def test_review_confirm_and_override_become_labels():
    from fastapi.testclient import TestClient

    from provenance.runtime import from_bundle, get_deps, set_deps
    from provenance.service import run as run_mod
    from provenance.service.app import app

    set_deps(from_bundle(mode="offline"))
    run_mod._runners.clear()
    cid = asyncio.run(run_mod.run_case("alt_demo_grocer"))  # auto_close
    with TestClient(app) as c:
        r1 = c.post(f"/api/cases/{cid}/review", json={"verdict": "false_positive", "note": "cash business"}).json()
        r2 = c.post(f"/api/cases/{cid}/review", json={"verdict": "suspicious", "note": "second look"}).json()
        assert c.post("/api/cases/nope/review", json={"verdict": "suspicious"}).status_code == 409
    assert (r1["action"], r1["n"]) == ("confirm", 1)
    assert (r2["action"], r2["n"]) == ("override", 2)
    case = get_deps().repo.get_case(cid)
    assert [h["verdict"] for h in case["human_decisions"]] == ["false_positive", "suspicious"]
    assert labels_from_reviews([case]) == {"alt_demo_grocer": True}
