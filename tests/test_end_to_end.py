"""The whole ADK graph, offline: alert in, cited and gated decision out.

Runs with scripted models (PROVENANCE_MODE=offline), so it exercises every
deterministic guarantee and the ADK wiring without network or credentials.
"""
import asyncio
import json

import pytest

pytest.importorskip("google.adk")

from google.adk.runners import Runner  # noqa: E402
from google.adk.sessions import InMemorySessionService  # noqa: E402
from google.genai import types  # noqa: E402

from provenance.agents.provenance_agent import offline  # noqa: E402
from provenance.agents.provenance_agent.agent import APP_NAME, build_app  # noqa: E402
from provenance.core.ledger import InMemoryLedger  # noqa: E402
from provenance.core.models import Claim  # noqa: E402
from provenance.core.verifier import verify_narrative  # noqa: E402
from provenance.runtime import from_bundle, get_deps, set_deps  # noqa: E402
from provenance.service import run as run_mod  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_deps():
    set_deps(from_bundle(mode="offline"))
    run_mod._runners.clear()
    yield


def run(alert, snapshot="live", basis="source_as_of"):
    cid = asyncio.run(run_mod.run_case(alert, snapshot, basis))
    return get_deps().repo.get_case(cid)


def failed(case):
    return [c["name"] for c in case["policy_gate"]["conditions"] if not c["passed"]]


def test_hero_reversal_three_beats():
    naive = run("alt_demo_hero", "archived", "retrieved_at")
    assert naive["decision"] == "auto_close"  # fluent, cited, wrong

    asof = run("alt_demo_hero", "archived", "source_as_of")
    assert asof["decision"] == "escalate" and failed(asof) == ["staleness"]
    stale = asof["staleness"]["stale_claims"]
    assert len(stale) == 1 and stale[0]["evidence_type"] == "watchlist"

    live = run("alt_demo_hero", "live", "source_as_of")
    assert live["decision"] == "escalate"
    assert "no_sanctions_or_pep_hit" in failed(live)
    assert any(c["sanctions_or_pep_hit"] for c in live["claims"])
    assert live["sar_draft"].startswith("DRAFT - NOT FILED")


def test_benign_case_auto_closes_on_fresh_evidence():
    c = run("alt_demo_grocer")
    assert c["decision"] == "auto_close" and c["verified"]
    assert {"transactions", "watchlist", "kyc"} <= {x["evidence_type"] for x in c["claims"]}
    assert "sar_draft" not in c


def test_adverse_media_claims_carry_grounding_citations():
    c = run("alt_demo_freight")
    media = [x for x in c["claims"] if x["evidence_type"] == "adverse_media"]
    assert media and media[0]["source_uri"].startswith("https://")
    assert media[0]["support_span"]["chunk_indices"] == [0]
    assert c["decision"] == "escalate"


def test_the_contract_every_emitted_sentence_resolves_in_the_ledger():
    """PLAN.md verification #3: parse citation_map, every sentence maps to a real claim."""
    for alert in ("alt_demo_hero", "alt_demo_grocer", "alt_demo_freight"):
        c = run(alert)
        ledger = InMemoryLedger(Claim.model_validate({k: v for k, v in x.items() if k != "claim_id"}) for x in c["claims"])
        final = c["attempts"][-1]
        assert final["passed"]
        assert verify_narrative(final["narrative"], ledger).coverage == 1.0


def test_verifier_rejects_first_draft_then_accepts():
    c = run("alt_demo_grocer")
    assert [a["passed"] for a in c["attempts"]] == [False, True]
    assert c["attempts"][0]["failures"][0]["unresolved"] == []  # uncited, not mis-cited


def test_model_that_never_cites_is_escalated_after_three_drafts(monkeypatch):
    """PLAN.md verification #4: force citation failure; the loop retries, then escalates."""
    def never_cites(req):
        return offline._text('{"narrative": "Everything looks fine. Close it.", "confidence_false_positive": 0.99}')

    monkeypatch.setattr(offline, "disposition", never_cites)
    d = get_deps()
    runner = Runner(app=build_app("offline", d.media_cache), session_service=InMemorySessionService())

    async def go():
        s = await runner.session_service.create_session(app_name=APP_NAME, user_id="u", state={
            "case_id": "case_forced", "alert_id": "alt_demo_grocer", "snapshot": "live", "staleness_basis": "source_as_of"})
        async for _ in runner.run_async(user_id="u", session_id=s.id,
                                        new_message=types.Content(role="user", parts=[types.Part(text="go")])):
            pass

    asyncio.run(go())
    c = d.repo.get_case("case_forced")
    assert len(c["attempts"]) == 3 and not any(a["passed"] for a in c["attempts"])
    assert c["decision"] == "escalate" and not c["verified"]
    assert "citation_coverage" in failed(c)
    assert "No draft passed" in c["escalation_note"]


def test_labels_never_reach_the_model_or_case_file():
    c = run("alt_demo_hero")
    assert "truly_suspicious" not in c["alert"] and "label" not in c["alert"]


def test_tools_refuse_accounts_outside_the_alert_scope():
    from provenance.agents.provenance_agent.tools import query_transactions

    class Ctx:
        state = {"scope_accounts": ["8830112040"], "case_id": "c"}

    out = asyncio.run(query_transactions("account_activity_window_v1", "9999999999", "2026-09-01", "2026-09-30", Ctx()))
    assert "outside this alert's scope" in out["error"]


def test_tool_call_limit_stops_loops():
    from provenance.agents.provenance_agent.tools import LIMIT_ERROR, TOOL_CALL_LIMIT, query_transactions

    class Ctx:
        state = {"scope_accounts": ["8830112040"], "case_id": "c"}

    ctx = Ctx()
    outs = [asyncio.run(query_transactions("nope", "1", "2026-09-01", "2026-09-30", ctx))
            for _ in range(TOOL_CALL_LIMIT + 1)]
    assert "unknown template" in outs[0]["error"] and outs[-1] == LIMIT_ERROR


def test_looping_model_is_bounded_and_trace_shows_it(monkeypatch):
    """A model that never stops calling a failing tool ends with the call limit, and the case still finishes."""
    calls = []

    def looping(req):
        calls.append(1)
        return offline._call("query_transactions", {"template_id": "nope", "account_id": "x",
                                                    "start_date": "2026-09-01", "end_date": "2026-09-02"})

    monkeypatch.setattr(offline, "txn_analyst", looping)
    run_mod._runners.clear()
    lines = []
    # A model that ignores even the call-limit message hits the LLM-call cap: the case ends as an
    # error with the reason recorded, instead of hanging.
    with pytest.raises(run_mod.CaseError) as e:
        asyncio.run(run_mod.run_case("alt_demo_hero", "live", case_id="case_loop", trace=lines.append))
    assert "LlmCallsLimitExceeded" in e.value.reason
    assert get_deps().repo.get_case("case_loop")["status"] == "error"
    assert any("CALL query_transactions" in l for l in lines) and any("call limit" in l for l in lines)
    assert len(calls) <= run_mod.MAX_LLM_CALLS


def test_case_timeout_marks_error(monkeypatch):
    import time as _time

    original = offline.typologist

    def slow(req):
        _time.sleep(0.3)
        return original(req)

    monkeypatch.setattr(offline, "typologist", slow)
    monkeypatch.setattr(run_mod, "CASE_TIMEOUT_S", 0.1)
    run_mod._runners.clear()
    with pytest.raises(run_mod.CaseError) as e:
        asyncio.run(run_mod.run_case("alt_demo_grocer", "live", case_id="case_timeout"))
    assert e.value.reason == "timeout"
    assert get_deps().repo.get_case("case_timeout")["status"] == "error"


def test_models_never_see_the_customer_name_for_judgement():
    from provenance.agents.provenance_agent.prompts import name_mask

    m = name_mask("Andrei Gennadyevich TIKHONOV")
    assert m("Andrei Gennadyevich TIKHONOV does not appear on OFAC SDN.") == "the customer does not appear on OFAC SDN."
    assert "TIKHONOV" not in m("matches entry #45815 (TIKHONOV, Andrei Gennadyevich, program RUSSIA-EO14024)")


def test_typologist_and_disposition_prompts_mask_identity():
    from provenance.agents.provenance_agent import prompts

    seen = {}
    orig_t, orig_d = offline.typologist, offline.disposition

    def spy_t(req):
        seen["typologist"] = offline._sys(req)
        return orig_t(req)

    def spy_d(req):
        seen["disposition"] = offline._sys(req)
        return orig_d(req)

    offline.typologist, offline.disposition = spy_t, spy_d
    try:
        run_mod._runners.clear()
        c = run("alt_demo_hero", "live")
    finally:
        offline.typologist, offline.disposition = orig_t, orig_d
    name = "Placeholder Persona Hero"
    assert name not in seen["typologist"] and "PROFILE_JSON" in seen["typologist"]
    assert name not in seen["disposition"] and "the customer" in seen["disposition"]
    assert any(name in x["assertion"] for x in c["claims"])  # the ledger keeps the real claim


def test_retry_config_only_in_gemini_mode(monkeypatch):
    from provenance.agents.provenance_agent.agent import build_root

    monkeypatch.setenv("PROVENANCE_MODEL_FLASH", "gemini-x-flash")
    monkeypatch.setenv("PROVENANCE_MODEL_PRO", "gemini-x-pro")
    g = build_root("gemini").sub_agents[1]
    assert 429 in g.generate_content_config.http_options.retry_options.http_status_codes
    off = build_root("offline").sub_agents[1].generate_content_config
    assert off is None or off.http_options is None
