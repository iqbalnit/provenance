"""Instruction providers. Each embeds machine-readable lines (ALERT_JSON, CLAIM ...)
that the model reads and the offline scripted model parses."""
from __future__ import annotations

import re

from google.adk.agents.readonly_context import ReadonlyContext

from provenance.core.models import Typology
from provenance.runtime import get_deps


def typologist(ctx: ReadonlyContext) -> str:
    return f"""You classify anti-money-laundering alerts.
Choose exactly one typology from: {', '.join(t.value for t in Typology)}.
The rule's hint is a starting point, not the answer; use the alert and the declared customer profile.
Classify from transaction behaviour only. You are not told the customer's name and must not guess
identity: sanctions and identity screening happen in a separate, cited step.
Return JSON {{"typology": ..., "rationale": one sentence}}.

ALERT_JSON: {ctx.state['alert_json']}
PROFILE_JSON: {ctx.state.get('profile_json', '{{}}')}"""


def txn_analyst(ctx: ReadonlyContext) -> str:
    return f"""You are the transactions analyst for an AML alert. Gather transaction evidence using
query_transactions. Query only the alerted account (account_id in ALERT_JSON); do not explore
counterparty accounts. Run account_activity_window_v1 and top_counterparties_v1 over the alert
window (dates as YYYY-MM-DD). For typology "structuring" also run sub_threshold_deposits_v1.
You have at most 3 queries; do not repeat one. Accounts in scope: {ctx.state['scope_accounts']}.
When done, reply with one line listing the claim IDs you recorded. Do not add facts of your own.

TYPOLOGY: {ctx.state['typology']}
ALERT_JSON: {ctx.state['alert_json']}"""


def watchlist_analyst(ctx: ReadonlyContext) -> str:
    return f"""You are the sanctions screening analyst. Call screen_name for the customer's name
exactly as written in the profile. When done, reply with one line listing the claim IDs.

CUSTOMER_JSON: {ctx.state['customer_json']}"""


def media_search(ctx: ReadonlyContext) -> str:
    return f"""Search the web for adverse media (fraud, money laundering, sanctions, enforcement
actions, criminal charges) about the subject below. Report only what sources state, in short
factual sentences. If nothing relevant is found, say so.

SUBJECT: {ctx.state['customer']['name']}"""


def name_mask(name: str):
    """Hide the customer's identity from a model that should judge evidence, not recall names.

    The full name becomes "the customer"; any remaining name token (e.g. the SDN-format
    "SURNAME, Given" inside a list-hit claim) becomes "[name]". Claims in the ledger are untouched.
    """
    tokens = sorted({t for t in re.split(r"[^\w]+", name) if len(t) >= 3}, key=len, reverse=True)
    if not tokens:
        return lambda text: text
    full = re.compile(re.escape(name), re.I) if name else None
    each = re.compile(r"\b(" + "|".join(re.escape(t) for t in tokens) + r")\b", re.I)

    def apply(text: str) -> str:
        text = full.sub("the customer", text) if full else text
        return each.sub("[name]", text)

    return apply


def disposition(ctx: ReadonlyContext) -> str:
    st = ctx.state
    claims = get_deps().repo.ledger(st["case_id"]).all()
    mask = name_mask(st.get("customer", {}).get("name", ""))
    lines = []
    for c in sorted(claims, key=lambda c: (c.evidence_type.value, c.claim_id)):
        flag = " SANCTIONS_HIT" if c.sanctions_or_pep_hit else ""
        lines.append(f"CLAIM [{c.claim_id}] ({c.evidence_type.value}, source_as_of "
                     f"{c.source_as_of.date().isoformat()}){flag}: {mask(c.assertion)}")
    feedback = st.get("verifier_feedback")
    fb = f"\nVERIFIER FEEDBACK on your previous draft (fix exactly these):\n{feedback}\n" if feedback else ""
    return f"""You write the disposition for an AML alert. Use ONLY the claims below.
Rules:
- Every sentence must end with one or more citations in the form [clm_xxxxxxxxxx] taken from the list,
  e.g. [clm_a] or [clm_a, clm_b]. A judgment sentence needs a citation too: cite the claims it rests on.
- Never state a fact that is not in a cited claim. Never invent names, accounts or amounts.
- confidence_false_positive is your probability (0-1) that this alert is a false positive that
  can safely be closed. Any sanctions hit or credible adverse media means it is low.
- Your confidence must rest only on the claims listed. The customer's name is masked on purpose:
  do not use anything you may know or guess about any person or company.
Return JSON {{"narrative": ..., "confidence_false_positive": ...}}.
{fb}
TYPOLOGY: {st['typology']}
ALERT_JSON: {st['alert_json']}
{chr(10).join(lines)}"""
