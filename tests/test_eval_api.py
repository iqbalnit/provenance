import asyncio

import pytest

pytest.importorskip("google.adk")


def test_eval_report_from_offline_arms(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from provenance.eval import report, results
    from provenance.eval.arms import run_arm
    from provenance.eval.baselines import run_a0
    from provenance.runtime import from_bundle, get_deps, set_deps
    from provenance.service import run as run_mod
    from provenance.service.app import app

    set_deps(from_bundle(mode="offline"))
    run_mod._runners.clear()
    alerts = list(get_deps().alerts.values())
    for arm in ("A3", "A4-naive", "A4"):
        results.write_jsonl(asyncio.run(run_arm(arm, alerts, f"{arm}-t")), tmp_path)
    results.write_jsonl([r.model_copy(update={"model_id": "offline"}) for r in run_a0(alerts, "A0-t")], tmp_path)
    monkeypatch.setattr(report, "ARTIFACTS", tmp_path)
    monkeypatch.setattr(report.latest_local_runs, "__defaults__", (tmp_path,))

    with TestClient(app) as c:
        r = c.get("/api/eval").json()
    assert [a["arm"] for a in r["arms"]] == ["A0", "A3", "A4-naive", "A4"]
    assert r["plumbing_only"] and all(a["plumbing_only"] for a in r["arms"])
    lift = r["staleness_lift"]
    assert lift["naive_tp_auto_closes"] > lift["asof_tp_auto_closes"] == 0
    a3 = next(a for a in r["arms"] if a["arm"] == "A3")
    assert a3["summary"]["tp_auto_closes"] == 0 and a3["reliability"]
