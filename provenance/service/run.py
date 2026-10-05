"""Run one alert through the agent graph. Used by the API and the CLI.

    uv run python -m provenance.service.run alt_demo_hero --snapshot archived --basis retrieved_at
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
import uuid
from collections.abc import Callable
from typing import Literal

from google.adk.agents import RunConfig
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from provenance.agents.provenance_agent.agent import APP_NAME, build_app
from provenance.runtime import get_deps

Snapshot = Literal["archived", "live"]
Basis = Literal["source_as_of", "retrieved_at"]

# Every case is bounded: a tool-error loop or a stalled call ends the case instead of hanging it.
MAX_LLM_CALLS = int(os.environ.get("PROVENANCE_MAX_LLM_CALLS", "40"))
CASE_TIMEOUT_S = float(os.environ.get("PROVENANCE_CASE_TIMEOUT_S", "360"))
HEARTBEAT_S = float(os.environ.get("PROVENANCE_HEARTBEAT_S", "15"))

Trace = Callable[[str], None]

_sessions = InMemorySessionService()
_runners: dict[str, Runner] = {}


def _runner() -> Runner:
    d = get_deps()
    if d.mode not in _runners:
        _runners[d.mode] = Runner(app=build_app(d.mode, d.media_cache), session_service=_sessions)
    return _runners[d.mode]


def new_case_id(alert_id: str, snapshot: str, basis: str) -> str:
    return f"case_{alert_id}_{snapshot}_{'naive' if basis == 'retrieved_at' else 'asof'}_{uuid.uuid4().hex[:6]}"


def _clip(v, n: int = 160) -> str:
    s = v if isinstance(v, str) else json.dumps(v, default=str)
    return s if len(s) <= n else s[: n - 1] + "…"


def describe(ev, t0: float) -> list[str]:
    """One line per interesting part of an ADK event, for --trace."""
    head = f"{time.monotonic() - t0:6.1f}s {ev.author:<22}"
    lines = [f"{head} CALL {fc.name}({_clip(fc.args)})" for fc in ev.get_function_calls()]
    lines += [f"{head} RESULT {fr.name} -> {_clip(fr.response)}" for fr in ev.get_function_responses()]
    if ev.content and ev.content.parts:
        text = "".join(p.text or "" for p in ev.content.parts if not getattr(p, "thought", False))
        if text.strip():
            lines.append(f"{head} TEXT {_clip(text.strip(), 120)}")
    if ev.error_message:
        lines.append(f"{head} ERROR {_clip(ev.error_message)}")
    return lines


async def run_case(alert_id: str, snapshot: Snapshot = "live", basis: Basis = "source_as_of",
                   case_id: str | None = None, trace: Trace | None = None) -> str:
    d = get_deps()
    if alert_id not in d.alerts:
        raise KeyError(f"unknown alert {alert_id}")
    case_id = case_id or new_case_id(alert_id, snapshot, basis)
    session = await _sessions.create_session(
        app_name=APP_NAME, user_id="analyst",
        state={"case_id": case_id, "alert_id": alert_id, "snapshot": snapshot, "staleness_basis": basis},
    )
    msg = types.Content(role="user", parts=[types.Part(text=f"Triage alert {alert_id}.")])
    t0 = time.monotonic()
    last = {"agent": "case_init", "at": t0}

    async def drive() -> None:
        async for ev in _runner().run_async(user_id="analyst", session_id=session.id, new_message=msg,
                                            run_config=RunConfig(max_llm_calls=MAX_LLM_CALLS)):
            last.update(agent=ev.author, at=time.monotonic())
            if trace:
                for line in describe(ev, t0):
                    trace(line)

    async def heartbeat() -> None:
        # Gemini retries (e.g. 429 back-off) happen inside one HTTP call and emit no events,
        # so without this a waiting run looks exactly like a hung one.
        while True:
            await asyncio.sleep(HEARTBEAT_S)
            now = time.monotonic()
            trace(f"{now - t0:6.1f}s … still running; {now - last['at']:.0f}s since the last event from "
                  f"{last['agent']} (a Gemini call may be backing off on quota)")

    beat = asyncio.ensure_future(heartbeat()) if trace else None
    try:
        await asyncio.wait_for(drive(), timeout=CASE_TIMEOUT_S)
    except TimeoutError as e:
        d.repo.update(case_id, {"status": "error", "stage": "error",
                                "error": f"timed out after {CASE_TIMEOUT_S:.0f}s (PROVENANCE_CASE_TIMEOUT_S)"})
        raise CaseError(case_id, "timeout") from e
    except Exception as e:
        d.repo.update(case_id, {"status": "error", "stage": "error", "error": f"{type(e).__name__}: {e}"})
        raise CaseError(case_id, f"{type(e).__name__}: {e}") from e
    finally:
        if beat:
            beat.cancel()
    return case_id


class CaseError(RuntimeError):
    """A case that did not finish: timed out, hit the LLM-call cap, or raised. The case doc has the reason."""

    def __init__(self, case_id: str, reason: str) -> None:
        super().__init__(f"{case_id}: {reason}")
        self.case_id, self.reason = case_id, reason


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("alert_id")
    ap.add_argument("--snapshot", choices=["archived", "live"], default="live")
    ap.add_argument("--basis", choices=["source_as_of", "retrieved_at"], default="source_as_of")
    ap.add_argument("--trace", action="store_true", help="print every agent step, tool call and tool result")
    a = ap.parse_args()
    try:
        case_id = asyncio.run(run_case(a.alert_id, a.snapshot, a.basis,
                                       trace=(lambda s: print(s, flush=True)) if a.trace else None))
    except CaseError as e:
        print(f"CASE DID NOT FINISH: {e}")
        raise SystemExit(1) from e
    case = get_deps().repo.get_case(case_id)
    print(json.dumps({k: case.get(k) for k in ("case_id", "typology", "decision", "confidence", "verified", "attempts",
                                                "policy_gate", "staleness", "escalation_note")}, indent=2, default=str))
    print(f"{len(case['claims'])} claims in ledger")


if __name__ == "__main__":
    main()
