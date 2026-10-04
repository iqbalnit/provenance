"""First-run smoke test for real Gemini on Vertex. Fails fast with a fix hint.

    set -a; source .env; set +a
    uv run python -m provenance.smoke                # all checks (< ~15 model calls)
    uv run python -m provenance.smoke --only 3       # one check
    uv run python -m provenance.smoke --skip-graph   # skip checks 6-7 (the full agent graph)

Paste the whole output back to whoever is fixing things; it contains no secrets.
"""
from __future__ import annotations

import argparse
import asyncio
import difflib
import json
import logging
import os
import sys
import time
import warnings
from collections import Counter
from collections.abc import Callable

MODELS = ["PROVENANCE_MODEL_FLASH", "PROVENANCE_MODEL_PRO"]
REQUIRED_ENV = {
    "vertex": ["GOOGLE_CLOUD_PROJECT", "GOOGLE_CLOUD_LOCATION", *MODELS],
    "aistudio": ["GOOGLE_API_KEY", *MODELS],
}


def backend_of(env: dict[str, str]) -> str:
    return "vertex" if env.get("GOOGLE_GENAI_USE_VERTEXAI", "").upper() in {"TRUE", "1"} else "aistudio"


class SmokeWarning(Exception):
    """A non-fatal finding: printed as WARN and the remaining checks still run."""


class SmokeFailure(Exception):
    def __init__(self, msg: str, hint: str) -> None:
        super().__init__(msg)
        self.hint = hint


# ---------- pure helpers (unit-tested) ----------

def check_env(env: dict[str, str]) -> list[str]:
    """Returns warnings; raises SmokeFailure on anything that will not work."""
    b = backend_of(env)
    missing = [k for k in REQUIRED_ENV[b] if not env.get(k)]
    if missing:
        hint = ("free path: get a key at aistudio.google.com and set GOOGLE_API_KEY in .env" if "GOOGLE_API_KEY" in missing
                else "cp .env.example .env, fill it in, then: set -a; source .env; set +a")
        raise SmokeFailure(f"backend={b}; missing env: {', '.join(missing)}", hint)
    warns = []
    for k in MODELS:
        v = env[k]
        if v.endswith("-latest"):
            raise SmokeFailure(f"{k}={v} is an alias", "pin an explicit versioned model ID; aliases silently move eval arms")
        if "2.5" in v:
            warns.append(f"{k}={v}: the 2.5 series retires around Oct 16, inside the judging window. Pin a 3.x ID.")
    return warns


def short_name(model_name: str) -> str:
    return model_name.rsplit("/", 1)[-1]


def closest(wanted: str, available: list[str], n: int = 5) -> list[str]:
    names = sorted({short_name(a) for a in available})
    near = difflib.get_close_matches(wanted, names, n=n, cutoff=0.3)
    return near or [x for x in names if "gemini" in x][:n]


# ---------- live checks ----------

def c1_env() -> str:
    env = dict(os.environ)
    warns = check_env(env)
    b = backend_of(env)
    where = (f"project={env['GOOGLE_CLOUD_PROJECT']} location={env['GOOGLE_CLOUD_LOCATION']}" if b == "vertex"
             else "AI Studio API key (no billing account)")
    msg = f"backend={b} {where} flash={env['PROVENANCE_MODEL_FLASH']} pro={env['PROVENANCE_MODEL_PRO']}"
    return msg + ("; " + "; ".join(warns) if warns else "")


def _is_aistudio() -> bool:
    return backend_of(dict(os.environ)) == "aistudio"


def _quota_hint(e: Exception) -> str | None:
    if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
        return ("free-tier rate limit: wait a minute and re-run with --only N" if _is_aistudio()
                else "quota: request a Gemini quota increase for this model and location")
    return None


def c2_adc() -> str:
    if _is_aistudio():
        return "skipped: the AI Studio backend authenticates with GOOGLE_API_KEY, not gcloud credentials"
    import google.auth  # noqa: PLC0415

    try:
        creds, project = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    except Exception as e:
        raise SmokeFailure(f"no Application Default Credentials ({type(e).__name__})",
                           "gcloud auth application-default login && gcloud auth application-default set-quota-project $GOOGLE_CLOUD_PROJECT "
                           "(not needed in Cloud Shell)") from e
    who = getattr(creds, "service_account_email", None) or getattr(creds, "account", None) or type(creds).__name__
    return f"credentials={who} adc_project={project}"


_CLIENT = None


def _client():
    # Keep one client alive: a temporary one is closed on garbage collection while a lazy pager still uses it.
    global _CLIENT
    if _CLIENT is None:
        from provenance import config  # noqa: PLC0415

        _CLIENT = config.genai_client()
    return _CLIENT


def c3_models() -> str:
    try:
        names = [m.name for m in _client().models.list()]
        if not names:
            raise RuntimeError("no models listed")
    except Exception as e:
        hint = ("check GOOGLE_API_KEY is a valid AI Studio key (aistudio.google.com > Get API key)" if _is_aistudio()
                else "gcloud services enable aiplatform.googleapis.com; check the project and that your account has roles/aiplatform.user")
        raise SmokeFailure(f"model listing failed: {str(e)[:200]}", _quota_hint(e) or hint) from e
    have = {short_name(n) for n in names}
    for k in ("PROVENANCE_MODEL_FLASH", "PROVENANCE_MODEL_PRO"):
        want = os.environ[k]
        if want not in have and short_name(want) not in have:
            where = "for this API key" if _is_aistudio() else f"in location {os.environ['GOOGLE_CLOUD_LOCATION']}"
            fix = (f"closest listed: {closest(want, names)}. Re-pin to a listed ID"
                   + ("" if _is_aistudio() else ", or try GOOGLE_CLOUD_LOCATION=global / us-central1"))
            raise SmokeFailure(f"{k}={want} not listed {where}", fix)
    return f"{len(have)} models listed; both pinned IDs present"


def c4_structured() -> str:
    from google.genai import types  # noqa: PLC0415

    from provenance.agents.provenance_agent.agent import TypologyOutput  # noqa: PLC0415

    t0 = time.monotonic()
    try:
        resp = _call_structured(TypologyOutput, types)
    except Exception as e:
        raise SmokeFailure(f"structured-output call failed: {str(e)[:200]}",
                           _quota_hint(e) or "check the model ID supports JSON output (response_schema)") from e
    try:
        out = TypologyOutput.model_validate(json.loads(resp.text))
    except Exception as e:
        raise SmokeFailure(f"structured output did not validate: {resp.text[:200]!r}",
                           "the model may not support response_schema; try another pinned model ID") from e
    return f"typology={out.typology} ({int((time.monotonic() - t0) * 1000)} ms)"


def _call_structured(schema, types):
    return _client().models.generate_content(
        model=os.environ["PROVENANCE_MODEL_FLASH"],
        contents='Classify this AML alert. Typologies: structuring, rapid_movement, high_risk_corridor, sanctions_nexus, '
                 'mule_funnel, round_tripping. Alert: {"rule": "structuring", "deposits": [9000, 9200, 9450]}. '
                 'Return JSON {"typology": ..., "rationale": one sentence}.',
        config=types.GenerateContentConfig(temperature=0, response_mime_type="application/json", response_schema=schema),
    )


def c5_grounding() -> str:
    from google.genai import types  # noqa: PLC0415

    try:
        resp = _client().models.generate_content(
            model=os.environ["PROVENANCE_MODEL_FLASH"],
            contents="What enforcement action did the US Treasury's OFAC announce most recently? Answer in two sentences.",
            config=types.GenerateContentConfig(temperature=0, tools=[types.Tool(google_search=types.GoogleSearch())]),
        )
    except Exception as e:
        if _is_aistudio():
            raise SmokeWarning(f"search grounding call failed ({str(e)[:160]}). It may not be in your free tier; "
                               "adverse media will fall back to 'no supported findings'") from e
        raise SmokeFailure(f"search grounding call failed: {str(e)[:200]}",
                           _quota_hint(e) or "check Google Search grounding is available for this model and location") from e
    gm = resp.candidates[0].grounding_metadata if resp.candidates else None
    chunks = (gm.grounding_chunks if gm else None) or []
    supports = (gm.grounding_supports if gm else None) or []
    if not chunks and _is_aistudio():
        raise SmokeWarning("no grounding chunks returned on the free tier; adverse media will fall back to 'no supported findings'")
    if not chunks:
        raise SmokeFailure("no grounding_metadata.grounding_chunks returned",
                           "check Google Search grounding is available for this model and location, and grounding quota; "
                           "adverse media will fall back to 'no supported findings' until fixed")
    web = chunks[0].web
    return f"{len(chunks)} chunks, {len(supports)} supports; first: {web.title} {web.uri[:80]}"


def _graph(alert: str, snapshot: str, basis: str) -> dict:
    os.environ["PROVENANCE_MODE"] = "gemini"
    from provenance.runtime import from_bundle, get_deps, set_deps  # noqa: PLC0415
    from provenance.service import run as run_mod  # noqa: PLC0415

    set_deps(from_bundle(mode="gemini"))
    run_mod._runners.clear()
    try:
        cid = asyncio.run(run_mod.run_case(alert, snapshot, basis))
    except Exception as e:
        name = type(e).__name__
        hint = {
            "ValidationError": "a model's JSON did not match TypologyOutput/DispositionOutput; paste this output back",
            "ClientError": "the API rejected a call: check model IDs, location and quota (see check 3)",
        }.get(name, "paste this whole output back; the traceback names the failing agent")
        hint = _quota_hint(e) or hint
        raise SmokeFailure(f"agent graph raised {name}: {str(e)[:300]}", hint) from e
    return get_deps().repo.get_case(cid)


def c6_graph() -> str:
    from provenance.core.ledger import InMemoryLedger  # noqa: PLC0415
    from provenance.core.models import Claim  # noqa: PLC0415
    from provenance.core.verifier import verify_narrative  # noqa: PLC0415

    t0 = time.monotonic()
    c = _graph("alt_demo_hero", "live", "source_as_of")
    by_agent = Counter(x["produced_by_agent"] for x in c["claims"])
    drafts = [a["passed"] for a in c.get("attempts", [])]
    failed = [g["name"] for g in c["policy_gate"]["conditions"] if not g["passed"]]
    summary = (f"typology={c.get('typology')} claims={dict(by_agent)} drafts={drafts} decision={c['decision']} "
               f"failed={failed} ({int(time.monotonic() - t0)} s)")
    if "adverse_media_analyst" not in by_agent and "adverse_media" in c.get("evidence_plan", {}).get("required", []):
        raise SmokeFailure(f"no adverse-media claim. {summary}",
                           "steps.AdverseMedia did not see grounding_metadata on any event from media_search; "
                           "paste this output back")
    if "watchlist_analyst" not in by_agent or "txn_analyst" not in by_agent:
        raise SmokeFailure(f"an evidence agent recorded nothing. {summary}",
                           "the model answered without calling its tool; paste this output back (fix: tool_config mode=ANY)")
    if c.get("verified"):
        ledger = InMemoryLedger(Claim.model_validate({k: v for k, v in x.items() if k != "claim_id"}) for x in c["claims"])
        assert verify_narrative(c["attempts"][-1]["narrative"], ledger).coverage == 1.0
    elif drafts:
        summary += " NOTE: no draft passed citation verification, so the case escalated by design; tighten the disposition prompt"
    if c["decision"] != "escalate" or "no_sanctions_or_pep_hit" not in failed:
        raise SmokeFailure(f"hero on the live list should escalate on the sanctions hit. {summary}",
                           "check the watchlist agent screened the exact customer name")
    return summary


def c7_reversal() -> str:
    c = _graph("alt_demo_hero", "archived", "source_as_of")
    failed = [g["name"] for g in c["policy_gate"]["conditions"] if not g["passed"]]
    if c["decision"] != "escalate" or "staleness" not in failed:
        raise SmokeFailure(f"archived list should escalate on staleness; got {c['decision']} failed={failed}",
                           "the staleness gate is deterministic; paste this output back")
    return f"archived list escalates on staleness (failed={failed})"


CHECKS: list[tuple[str, Callable[[], str]]] = [
    ("environment", c1_env), ("application default credentials", c2_adc), ("pinned models exist", c3_models),
    ("structured output", c4_structured), ("google search grounding", c5_grounding),
    ("full agent graph on Gemini (hero, live list)", c6_graph), ("staleness reversal on Gemini", c7_reversal),
]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", type=int, choices=range(1, len(CHECKS) + 1))
    ap.add_argument("--skip-graph", action="store_true")
    a = ap.parse_args()
    warnings.filterwarnings("ignore")
    logging.disable(logging.WARNING)
    for i, (name, fn) in enumerate(CHECKS, 1):
        if a.only and i != a.only:
            continue
        if a.skip_graph and i >= 6:
            break
        try:
            print(f"[{i}/{len(CHECKS)}] PASS  {name}: {fn()}", flush=True)
        except SmokeWarning as e:
            print(f"[{i}/{len(CHECKS)}] WARN  {name}: {e}", flush=True)
        except SmokeFailure as e:
            print(f"[{i}/{len(CHECKS)}] FAIL  {name}: {e}\n        fix: {e.hint}")
            return 1
    print("All checks passed. Next: PROVENANCE_MODE=gemini uv run uvicorn provenance.service.app:app --port 8080")
    return 0


if __name__ == "__main__":
    sys.exit(main())
