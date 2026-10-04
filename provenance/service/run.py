"""Run one alert through the agent graph. Used by the API and the CLI.

    uv run python -m provenance.service.run alt_demo_hero --snapshot archived --basis retrieved_at
"""
from __future__ import annotations

import argparse
import asyncio
import json
import uuid
from typing import Literal

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from provenance.agents.provenance_agent.agent import APP_NAME, build_app
from provenance.runtime import get_deps

Snapshot = Literal["archived", "live"]
Basis = Literal["source_as_of", "retrieved_at"]

_sessions = InMemorySessionService()
_runners: dict[str, Runner] = {}


def _runner() -> Runner:
    d = get_deps()
    if d.mode not in _runners:
        _runners[d.mode] = Runner(app=build_app(d.mode, d.media_cache), session_service=_sessions)
    return _runners[d.mode]


def new_case_id(alert_id: str, snapshot: str, basis: str) -> str:
    return f"case_{alert_id}_{snapshot}_{'naive' if basis == 'retrieved_at' else 'asof'}_{uuid.uuid4().hex[:6]}"


async def run_case(alert_id: str, snapshot: Snapshot = "live", basis: Basis = "source_as_of",
                   case_id: str | None = None) -> str:
    d = get_deps()
    if alert_id not in d.alerts:
        raise KeyError(f"unknown alert {alert_id}")
    case_id = case_id or new_case_id(alert_id, snapshot, basis)
    session = await _sessions.create_session(
        app_name=APP_NAME, user_id="analyst",
        state={"case_id": case_id, "alert_id": alert_id, "snapshot": snapshot, "staleness_basis": basis},
    )
    msg = types.Content(role="user", parts=[types.Part(text=f"Triage alert {alert_id}.")])
    try:
        async for _ in _runner().run_async(user_id="analyst", session_id=session.id, new_message=msg):
            pass
    except Exception as e:
        d.repo.update(case_id, {"status": "error", "error": f"{type(e).__name__}: {e}"})
        raise
    return case_id


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("alert_id")
    ap.add_argument("--snapshot", choices=["archived", "live"], default="live")
    ap.add_argument("--basis", choices=["source_as_of", "retrieved_at"], default="source_as_of")
    a = ap.parse_args()
    case_id = asyncio.run(run_case(a.alert_id, a.snapshot, a.basis))
    case = get_deps().repo.get_case(case_id)
    print(json.dumps({k: case.get(k) for k in ("case_id", "typology", "decision", "confidence", "verified", "attempts",
                                                "policy_gate", "staleness", "escalation_note")}, indent=2, default=str))
    print(f"{len(case['claims'])} claims in ledger")


if __name__ == "__main__":
    main()
