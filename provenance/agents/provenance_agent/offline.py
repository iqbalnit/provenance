"""Scripted stand-in models for PROVENANCE_MODE=offline.

They let the full ADK graph run with no network: CI, tests, and a fallback demo.
They are deliberately simple and deterministic, and they are labelled as scripted
everywhere they surface. They never stand in for Gemini in any reported eval number.

The disposition script's first draft leaves its closing summary sentence uncited,
so offline runs always exercise the verifier's reject-and-retry path.
"""
from __future__ import annotations

import json
import re
from collections.abc import AsyncGenerator, Callable
from typing import Any

from google.adk.models import BaseLlm, LlmCapabilities, LlmRequest, LlmResponse
from google.genai import types

Script = Callable[[LlmRequest], LlmResponse]


class ScriptedLlm(BaseLlm):
    script: Any = None

    @property
    def capabilities(self) -> LlmCapabilities:
        return LlmCapabilities(output_schema_and_tools=True)

    async def generate_content_async(self, llm_request: LlmRequest, stream: bool = False) -> AsyncGenerator[LlmResponse, None]:
        yield self.script(llm_request)


def _sys(req: LlmRequest) -> str:
    si = req.config.system_instruction if req.config else None
    if si is None:
        return ""
    if isinstance(si, str):
        return si
    return "".join(p.text or "" for p in getattr(si, "parts", []) or [])


def _line(req: LlmRequest, key: str) -> str:
    m = re.search(rf"^{key}: (.*)$", _sys(req), re.M)
    return m.group(1) if m else ""


def _text(t: str, grounding: types.GroundingMetadata | None = None) -> LlmResponse:
    return LlmResponse(content=types.Content(role="model", parts=[types.Part(text=t)]), grounding_metadata=grounding)


def _call(name: str, args: dict) -> LlmResponse:
    return LlmResponse(content=types.Content(role="model", parts=[
        types.Part(function_call=types.FunctionCall(name=name, args=args))]))


def _responses(req: LlmRequest) -> int:
    return sum(1 for c in req.contents for p in (c.parts or []) if p.function_response)


def typologist(req: LlmRequest) -> LlmResponse:
    alert = json.loads(_line(req, "ALERT_JSON"))
    return _text(json.dumps({"typology": alert["typology_hint"],
                             "rationale": f"Scripted: follows the {alert['rule']} rule that fired."}))


def txn_analyst(req: LlmRequest) -> LlmResponse:
    alert = json.loads(_line(req, "ALERT_JSON"))
    base = {"account_id": alert["account_id"], "start_date": alert["window_start"][:10], "end_date": alert["window_end"][:10]}
    plan = ["account_activity_window_v1", "top_counterparties_v1"]
    if _line(req, "TYPOLOGY") == "structuring":
        plan.append("sub_threshold_deposits_v1")
    n = _responses(req)
    if n < len(plan):
        return _call("query_transactions", {"template_id": plan[n], **base})
    return _text("Transaction evidence recorded.")


def watchlist_analyst(req: LlmRequest) -> LlmResponse:
    if _responses(req) == 0:
        return _call("screen_name", {"name": json.loads(_line(req, "CUSTOMER_JSON"))["name"]})
    return _text("Screening recorded.")


def media_search(cache: dict) -> Script:
    def run(req: LlmRequest) -> LlmResponse:
        hit = cache.get(_line(req, "SUBJECT"))
        if not hit:
            return _text("No relevant adverse media found.")
        return _text(hit["text"], types.GroundingMetadata.model_validate(
            {k: hit[k] for k in ("grounding_chunks", "grounding_supports")}))
    return run


def disposition(req: LlmRequest) -> LlmResponse:
    sys = _sys(req)
    claims = re.findall(r"^CLAIM \[(clm_[0-9a-f]{10})\] \(([a-z_]+), [^)]*\)( SANCTIONS_HIT)?: (.*)$", sys, re.M)
    hit = any(h for _, _, h, _ in claims)
    media = any(t == "adverse_media" and re.search(r"fined|charged|launder|sanction|fraud|convicted", a, re.I)
                for _, t, _, a in claims)
    conf = 0.03 if hit else 0.15 if media else 0.94
    sentences = [f"{a.rstrip('.')} [{cid}]." for cid, _, _, a in claims]
    closing = ("The evidence does not support closing this alert" if conf < 0.5
               else "Taken together, the activity is consistent with the customer profile")
    ids = "".join(f"[{cid}]" for cid, *_ in claims)
    first_draft = "VERIFIER FEEDBACK" not in sys
    sentences.append(f"{closing}." if first_draft else f"{closing} {ids}.")
    return _text(json.dumps({"narrative": " ".join(sentences), "confidence_false_positive": conf}))


def model_for(agent: str, media_cache: dict) -> ScriptedLlm:
    scripts: dict[str, Script] = {
        "typologist": typologist,
        "txn_analyst": txn_analyst,
        "watchlist_analyst": watchlist_analyst,
        "media_search": media_search(media_cache),
        "disposition": disposition,
    }
    return ScriptedLlm(model=f"offline-scripted/{agent}", script=scripts[agent])
