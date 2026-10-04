import time

import pytest

pytest.importorskip("google.adk")
from fastapi.testclient import TestClient  # noqa: E402

from provenance.runtime import from_bundle, set_deps  # noqa: E402
from provenance.service import run as run_mod  # noqa: E402
from provenance.service.app import app  # noqa: E402


def test_api_runs_a_case_and_serves_the_console():
    set_deps(from_bundle(mode="offline"))
    run_mod._runners.clear()
    with TestClient(app) as client:
        meta = client.get("/api/alerts").json()
        assert meta["mode"] == "offline" and len(meta["alerts"]) == 4
        assert "truly_suspicious" not in meta["alerts"][0]
        cid = client.post("/api/cases", json={"alert_id": "alt_demo_hero", "snapshot": "archived",
                                              "staleness_basis": "source_as_of"}).json()["case_id"]
        for _ in range(100):
            c = client.get(f"/api/cases/{cid}").json()
            if c.get("status") == "done":
                break
            time.sleep(0.05)
        assert c["decision"] == "escalate" and isinstance(c["claims"][0]["source_as_of"], str)
        assert client.post("/api/cases", json={"alert_id": "nope"}).status_code == 404
        assert "Provenance" in client.get("/").text
