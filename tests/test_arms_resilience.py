"""An eval run must survive a network drop: retry transient failures, keep rows as they finish, resume."""
import asyncio

import pytest

pytest.importorskip("google.adk")

from provenance.eval import arms  # noqa: E402
from provenance.eval.results import read_jsonl  # noqa: E402
from provenance.runtime import from_bundle, get_deps, set_deps  # noqa: E402
from provenance.service import run as run_mod  # noqa: E402


class ServiceUnavailable(Exception):  # same name as google.api_core's, matched by name
    pass


def _dns_failure(case_id: str = "c") -> run_mod.CaseError:
    try:
        raise ServiceUnavailable("503 errors resolving firestore.googleapis.com: DNS query cancelled")
    except ServiceUnavailable as cause:
        try:
            raise run_mod.CaseError(case_id, f"RetryError: {cause}") from cause
        except run_mod.CaseError as e:
            return e


@pytest.fixture
def deps(monkeypatch):
    set_deps(from_bundle(mode="offline"))
    run_mod._runners.clear()
    monkeypatch.setattr(arms, "RETRY_WAIT_S", 0)
    return get_deps()


def test_transient_is_found_anywhere_in_the_cause_chain():
    assert arms.is_transient(_dns_failure())
    assert not arms.is_transient(run_mod.CaseError("c", "timeout"))
    assert not arms.is_transient(ValueError("bad json from the model"))


def test_network_error_is_retried_and_rows_are_saved_as_they_finish(deps, monkeypatch, tmp_path):
    real = run_mod.run_case
    calls = {"n": 0}

    async def flaky(alert_id, *a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            raise _dns_failure()
        return await real(alert_id, *a, **k)

    monkeypatch.setattr(arms, "run_case", flaky)
    alerts = sorted(deps.alerts.values(), key=lambda x: x["alert_id"])[:2]
    sink = tmp_path / "A3" / "run.jsonl"
    rows = asyncio.run(arms.run_arm("A3", alerts, "run", sink=sink))
    assert calls["n"] == 3  # first alert retried once, second ran once
    assert all(r.decision != "error" for r in rows)
    assert [r.alert_id for r in read_jsonl(sink)] == [a["alert_id"] for a in alerts]


def test_persistent_network_failure_becomes_an_error_row_not_a_crash(deps, monkeypatch):
    async def down(*a, **k):
        raise _dns_failure()

    monkeypatch.setattr(arms, "run_case", down)
    alerts = list(deps.alerts.values())[:2]
    rows = asyncio.run(arms.run_arm("A3", alerts, "run"))
    assert [r.decision for r in rows] == ["error", "error"]
    assert rows[0].narrative.startswith("network:")


def test_model_errors_are_not_retried(deps, monkeypatch):
    calls = {"n": 0}

    async def broken(*a, **k):
        calls["n"] += 1
        raise run_mod.CaseError("c", "LlmCallsLimitExceeded")

    monkeypatch.setattr(arms, "run_case", broken)
    asyncio.run(arms.run_arm("A3", list(deps.alerts.values())[:1], "run"))
    assert calls["n"] == 1


def test_resume_keeps_finished_rows_and_reruns_errors(deps, tmp_path):
    alerts = sorted(deps.alerts.values(), key=lambda x: x["alert_id"])
    sink = tmp_path / "run.jsonl"
    first = asyncio.run(arms.run_arm("A3", alerts[:2], "A3-golden-x", sink=sink))
    with open(sink, "a") as f:  # third alert errored on the network
        f.write(first[0].model_copy(update={"alert_id": alerts[2]["alert_id"], "decision": "error"}).model_dump_json() + "\n")
    run_id, kept, todo = arms.resume_plan(sink, alerts)
    assert run_id == "A3-golden-x"
    assert {r.alert_id for r in kept} == {a["alert_id"] for a in alerts[:2]}
    assert [a["alert_id"] for a in todo] == [a["alert_id"] for a in alerts[2:]]


def test_store_outage_mid_case_raises_a_retryable_case_error(deps, monkeypatch):
    # Exactly the field failure: Firestore unreachable mid-case, and again while recording the error.
    def unreachable(*a, **k):
        raise ServiceUnavailable("firestore unreachable")

    monkeypatch.setattr(deps.repo, "update", unreachable)
    with pytest.raises(run_mod.CaseError) as e:
        asyncio.run(run_mod.run_case("alt_demo_grocer", "live", case_id="case_outage"))
    assert "ServiceUnavailable" in e.value.reason
    assert arms.is_transient(e.value)
