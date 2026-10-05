"""Deterministic steps of the agent graph (ADK BaseAgents, no LLM inside).

These are the parts auditability demands be code: case setup, the evidence
plan, KYC reading, the verifier + policy gate, and finalisation.
"""
from __future__ import annotations

import asyncio

import json
from collections.abc import AsyncGenerator
from typing import Any

from google.adk.agents import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event, EventActions
from google.genai import types

from provenance.core.decide import CaseDecision, decide_case
from provenance.core.models import Case, EvidenceType, Typology
from provenance.core.sar import draft_sar
from provenance.core.typologies import MANDATORY_EVIDENCE
from provenance.runtime import get_deps
from provenance.sources.kyc import claims_from_profile
from provenance.sources.media import claims_from_grounding

MAX_DRAFTS = 3
# Ground-truth and bookkeeping fields never reach a model or the case file.
HIDDEN_ALERT_FIELDS = {"label", "split", "truly_suspicious", "laundering_types"}


def _event(agent: BaseAgent, ctx: InvocationContext, text: str | None = None, **actions: Any) -> Event:
    return Event(
        author=agent.name,
        invocation_id=ctx.invocation_id,
        branch=ctx.branch,
        content=types.Content(role="model", parts=[types.Part(text=text)]) if text else None,
        actions=EventActions(**actions),
    )


def _stage(case_id: str, stage: str) -> None:
    get_deps().repo.update(case_id, {"stage": stage})


class CaseInit(BaseAgent):
    """Loads the alert and customer, scopes which accounts tools may touch, opens the case."""

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        d = get_deps()
        st = ctx.session.state
        alert = {k: v for k, v in d.alerts[st["alert_id"]].items() if k not in HIDDEN_ALERT_FIELDS}
        alert["account_id"] = str(alert["account_id"])
        customer = d.customers.get(alert["account_id"], {"name": f"account {alert['account_id']}"})
        # Tools may only query the alerted account and its counterparties in the alert window.
        scope = {alert["account_id"]}
        window = await asyncio.to_thread(d.txns.run, "account_activity_window_v1", {  # BigQuery is blocking
            "account_id": alert["account_id"],
            "start_date": alert["window_start"][:10], "end_date": alert["window_end"][:10],
        })
        for r in window.rows:
            scope.add(str(r["counterparty_account"]))
        d.repo.create_case(
            Case(case_id=st["case_id"], alert_id=alert["alert_id"]),
            alert=alert, customer=customer, snapshot=st["snapshot"],
            staleness_basis=st["staleness_basis"], mode=d.mode, stage="typology",
            status="running", attempts=[], started_at=d.now().isoformat(),
        )
        yield _event(self, ctx, state_delta={
            "alert": alert, "customer": customer, "scope_accounts": sorted(scope),
            "alert_json": json.dumps(alert),
            "customer_json": json.dumps(customer),
            # What the typologist sees: behaviour and declared profile, never the name.
            "profile_json": json.dumps({k: v for k, v in customer.items() if k != "name"}),
        })


class EvidencePlanner(BaseAgent):
    """The LLM names the typology; code decides what evidence that typology requires."""

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        st = ctx.session.state
        out = st.get("typology_out") or {}
        try:
            typology = Typology(out.get("typology"))
        except ValueError:
            typology = Typology(st["alert"]["typology_hint"])  # fall back to the rule's label
        required = [e.value for e in MANDATORY_EVIDENCE[typology]]
        plan = {"typology": typology.value, "required": required}
        d = get_deps()
        d.repo.update(st["case_id"], {
            "typology": typology.value, "typology_rationale": out.get("rationale", ""),
            "evidence_plan": plan, "stage": "evidence",
        })
        yield _event(self, ctx, state_delta={"typology": typology.value, "evidence_plan": plan})


class Planned(BaseAgent):
    """Runs its sub-agent only if the evidence plan requires that evidence type."""

    evidence_type: str

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        if self.evidence_type not in ctx.session.state["evidence_plan"]["required"]:
            return
        async for ev in self.sub_agents[0].run_async(ctx):
            yield ev


class KycReader(BaseAgent):
    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        d = get_deps()
        st = ctx.session.state
        acct = st["alert"]["account_id"]
        profile = d.customers.get(acct)
        ledger = d.repo.ledger(st["case_id"])
        if profile:
            for c in claims_from_profile(acct, profile, d.kyc_uri(acct), d.now()):
                ledger.append(c)
        yield _event(self, ctx, text=f"KYC profile {'read' if profile else 'missing'} for {acct}.")


class AdverseMedia(BaseAgent):
    """Runs the isolated google_search agent and turns its groundingMetadata into claims.

    The search agent has google_search as its ONLY tool: mixing it with function
    tools in one agent disables automatic function calling for all of them.
    """

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        d = get_deps()
        st = ctx.session.state
        subject = st["customer"]["name"]
        grounding = None
        async for ev in self.sub_agents[0].run_async(ctx):
            if ev.grounding_metadata is not None:
                grounding = ev.grounding_metadata
            yield ev
        ledger = d.repo.ledger(st["case_id"])
        for c in claims_from_grounding(subject, grounding, d.now()):
            ledger.append(c)


class VerifyAndGate(BaseAgent):
    """Deterministic verifier + staleness auditor + policy gate on each draft.

    A draft that fails citation verification is rejected back to the disposition
    agent with the exact failing sentences. A draft that passes ends the loop,
    whatever the gate decides.
    """

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        d = get_deps()
        st = ctx.session.state
        draft = st.get("disposition_out") or {}
        attempt = int(st.get("attempt", 0)) + 1
        ledger = d.repo.ledger(st["case_id"])
        result = decide_case(
            typology=Typology(st["typology"]),
            ledger=ledger,
            narrative=draft.get("narrative", ""),
            confidence=float(draft.get("confidence_false_positive", 0.0)),
            now=d.now(),
            staleness_basis=st["staleness_basis"],
        )
        v = result.verification
        record = {
            "attempt": attempt, "passed": v.passed, "coverage": v.coverage,
            "narrative": draft.get("narrative", ""),
            "sentences": [{"text": x.text, "ok": x.ok} for x in v.sentences],
            "failures": [{"index": f.index, "text": f.text, "unresolved": f.unresolved_ids} for f in v.failures],
        }
        attempts = [*st.get("attempts", []), record]
        d.repo.update(st["case_id"], {"attempts": attempts, "stage": "verify"})
        delta: dict[str, Any] = {"attempt": attempt, "attempts": attempts,
                                 "last_result": result.model_dump(mode="json")}
        if v.passed:
            delta["verified"] = True
            yield _event(self, ctx, text=f"Draft {attempt} verified.", state_delta=delta, escalate=True)
        else:
            delta["verifier_feedback"] = v.feedback()
            yield _event(self, ctx, text=f"Draft {attempt} rejected:\n{v.feedback()}", state_delta=delta)


class Finalize(BaseAgent):
    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        d = get_deps()
        st = ctx.session.state
        case_id = st["case_id"]
        result = CaseDecision.model_validate(st["last_result"])
        draft = st.get("disposition_out") or {}
        d.repo.write_decision(case_id, result, draft.get("narrative", ""), version=int(st.get("attempt", 1)))
        fields: dict[str, Any] = {
            "confidence": draft.get("confidence_false_positive"),
            "verified": bool(st.get("verified")),
            "narrative_coverage": result.verification.coverage,
            "status": "done", "stage": "done", "finished_at": d.now().isoformat(),
        }
        if not st.get("verified"):
            fields["escalation_note"] = f"No draft passed citation verification after {MAX_DRAFTS} attempts."
        if result.decision.value == "escalate":
            fields["sar_draft"] = draft_sar(
                subject=st["customer"]["name"], account_id=st["alert"]["account_id"],
                typology=st["typology"], gate=result.gate, ledger=d.repo.ledger(case_id),
            )
        d.repo.update(case_id, fields)
        yield _event(self, ctx, text=f"Case {case_id}: {result.decision.value}.")


# Evidence types referenced by Planned wrappers.
KYC, MEDIA = EvidenceType.KYC.value, EvidenceType.ADVERSE_MEDIA.value
