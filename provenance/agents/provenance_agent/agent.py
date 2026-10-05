"""The Provenance agent graph (ADK).

  provenance_agent        SequentialAgent
    case_init             deterministic: load alert + customer, scope accounts, open case
    typologist            LlmAgent (Flash), output_schema -> typology + rationale
    evidence_planner      deterministic: typology -> mandatory evidence (code, not model)
    evidence              ParallelAgent
      txn_analyst         LlmAgent + query_transactions (named templates only)
      watchlist_analyst   LlmAgent + screen_name (list version + as_of on every claim)
      kyc (planned)       deterministic: structured KYC profile -> claims
      media (planned)     deterministic wrapper around media_search, an LlmAgent whose ONLY
                          tool is google_search; groundingMetadata -> claims, verbatim
    disposition_loop      LoopAgent, max 3 drafts
      disposition         LlmAgent (Pro), output_schema -> cited narrative + confidence
      verify_and_gate     deterministic: citation verifier, staleness auditor, policy gate
    finalize              deterministic: persist decision; SAR draft on escalation

PROVENANCE_MODE=offline swaps every model for a scripted stand-in (offline.py).
App(name=...) must match this directory name, or ADK eval fails with "Session not found".
"""
from __future__ import annotations

from google.adk.agents import LlmAgent, LoopAgent, ParallelAgent, SequentialAgent
from google.adk.apps import App
from google.adk.tools import google_search
from google.genai import types
from pydantic import BaseModel, Field

from provenance.agents.provenance_agent import prompts, steps
from provenance.agents.provenance_agent.tools import query_transactions, screen_name

APP_NAME = "provenance_agent"


class TypologyOutput(BaseModel):
    typology: str = Field(description="one of the listed typology values")
    rationale: str


class DispositionOutput(BaseModel):
    narrative: str
    confidence_false_positive: float = Field(ge=0.0, le=1.0)


def build_root(mode: str, media_cache: dict | None = None):
    if mode == "offline":
        from provenance.agents.provenance_agent.offline import model_for  # noqa: PLC0415

        def m(agent: str, _kind: str):
            return model_for(agent, media_cache or {})
    else:
        from provenance import config  # noqa: PLC0415

        def m(_agent: str, kind: str):
            return config.model(kind)

    # Back off and retry on quota (429) and transient server errors: preview models have low RPM.
    gen = None if mode == "offline" else types.GenerateContentConfig(http_options=types.HttpOptions(
        retry_options=types.HttpRetryOptions(attempts=6, initial_delay=2.0, max_delay=60.0, jitter=1.0,
                                             http_status_codes=[429, 500, 503])))

    typologist = LlmAgent(name="typologist", model=m("typologist", "flash"),
                          instruction=prompts.typologist, output_schema=TypologyOutput,
                          output_key="typology_out", include_contents="none", generate_content_config=gen)
    txn = LlmAgent(name="txn_analyst", model=m("txn_analyst", "flash"),
                   instruction=prompts.txn_analyst, tools=[query_transactions], include_contents="none",
                   generate_content_config=gen)
    watch = LlmAgent(name="watchlist_analyst", model=m("watchlist_analyst", "flash"),
                     instruction=prompts.watchlist_analyst, tools=[screen_name], include_contents="none",
                     generate_content_config=gen)
    media_search = LlmAgent(name="media_search", model=m("media_search", "flash"),
                            instruction=prompts.media_search, include_contents="none",
                            tools=[] if mode == "offline" else [google_search], generate_content_config=gen)
    evidence = ParallelAgent(name="evidence", sub_agents=[
        txn,
        watch,
        steps.Planned(name="kyc", evidence_type=steps.KYC, sub_agents=[steps.KycReader(name="kyc_analyst")]),
        steps.Planned(name="media", evidence_type=steps.MEDIA,
                      sub_agents=[steps.AdverseMedia(name="adverse_media_analyst", sub_agents=[media_search])]),
    ])
    disposition = LlmAgent(name="disposition", model=m("disposition", "pro"),
                           instruction=prompts.disposition, output_schema=DispositionOutput,
                           output_key="disposition_out", include_contents="none", generate_content_config=gen)
    return SequentialAgent(name=APP_NAME, sub_agents=[
        steps.CaseInit(name="case_init"),
        typologist,
        steps.EvidencePlanner(name="evidence_planner"),
        evidence,
        LoopAgent(name="disposition_loop", max_iterations=steps.MAX_DRAFTS,
                  sub_agents=[disposition, steps.VerifyAndGate(name="verify_and_gate")]),
        steps.Finalize(name="finalize"),
    ])


def build_app(mode: str, media_cache: dict | None = None) -> App:
    return App(name=APP_NAME, root_agent=build_root(mode, media_cache))


def __getattr__(name: str):
    # `adk web` / `adk eval` look for root_agent / app; build lazily from the environment.
    if name in {"root_agent", "app"}:
        from provenance.runtime import get_deps  # noqa: PLC0415

        d = get_deps()
        a = build_app(d.mode, d.media_cache)
        return a if name == "app" else a.root_agent
    raise AttributeError(name)
