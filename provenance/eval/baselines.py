"""Baseline arms A0 and A1. Run these before any agent code exists.

    python -m provenance.eval.baselines --arm A0 --split golden
    python -m provenance.eval.baselines --arm A1 --split golden [--upload]

A0: rules only, so every alert goes to a human. Pure arithmetic.
A1: one ungrounded Gemini call per alert (alert + its transactions in, a
    disposition out, no tools). This is what "just add an LLM" ships, so give
    it a fair prompt. Its citation coverage is ~0 by construction and every
    entity it names that is not in its input counts as hallucinated.
"""
from __future__ import annotations

import argparse
import csv
import json
import time
import uuid
from collections.abc import Callable, Sequence
from pathlib import Path

from pydantic import BaseModel, Field

from provenance.core.ledger import InMemoryLedger
from provenance.core.verifier import verify_narrative
from provenance.eval.metrics import hallucinated_entity_rate
from provenance.eval.results import EvalRow, summarize, upload, write_jsonl

ALERTS_PATH = Path("artifacts/alerts.jsonl")
SAMPLE_PATH = Path("data/raw/saml_d_sample.csv")

A1_PROMPT = """You are an L1 anti-money-laundering analyst at a bank.
A transaction-monitoring rule fired the alert below. Decide whether it can be
closed as a false positive or must be escalated for investigation.

Alert:
{alert}

Transactions in the alert window:
{txns}

Return JSON with: decision ("auto_close" or "escalate"), confidence (0-1, your
probability that the decision is correct), narrative (a short rationale), and
entities_named (every person, company, or account you mention in the narrative).
"""


class A1Output(BaseModel):
    decision: str = Field(pattern="^(auto_close|escalate)$")
    confidence: float = Field(ge=0.0, le=1.0)
    narrative: str
    entities_named: list[str] = Field(default_factory=list)


Generate = Callable[[str], dict]


def load_alerts(path: Path = ALERTS_PATH, split: str | None = None) -> list[dict]:
    rows = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
    return [r for r in rows if split in (None, "all") or r["split"] == split]


def load_txn_index(path: Path = SAMPLE_PATH, wanted: set[str] | None = None) -> dict[str, dict]:
    with open(path, newline="", encoding="utf-8") as f:
        return {
            r["Txn_id"]: r
            for r in csv.DictReader(f)
            if wanted is None or r["Txn_id"] in wanted
        }


def _alert_view(alert: dict) -> dict:
    # Never show the model the label.
    return {k: v for k, v in alert.items() if k not in {"truly_suspicious", "laundering_types", "split"}}


def _txn_view(t: dict) -> dict:
    return {k: v for k, v in t.items() if k not in {"Is_laundering", "Laundering_type"}}


def input_entities(alert: dict, txns: Sequence[dict]) -> set[str]:
    ents = {alert["account_id"]}
    for t in txns:
        ents |= {t["Sender_account"], t["Receiver_account"]}
    return ents


def run_a0(alerts: Sequence[dict], run_id: str) -> list[EvalRow]:
    return [
        EvalRow(run_id=run_id, arm="A0", alert_id=a["alert_id"], split=a["split"], decision="escalate",
                confidence=None, truly_suspicious=a["truly_suspicious"], citation_coverage=0.0,
                hallucinated_entity_rate=None)
        for a in alerts
    ]


def run_a1(alerts: Sequence[dict], txn_index: dict[str, dict], generate: Generate,
           run_id: str, model_id: str | None = None) -> list[EvalRow]:
    empty = InMemoryLedger()
    rows: list[EvalRow] = []
    for a in alerts:
        txns = [txn_index[t] for t in a["txn_ids"] if t in txn_index]
        prompt = A1_PROMPT.format(
            alert=json.dumps(_alert_view(a), indent=2),
            txns=json.dumps([_txn_view(t) for t in txns], indent=2),
        )
        t0 = time.monotonic()
        out = A1Output.model_validate(generate(prompt))
        latency = int((time.monotonic() - t0) * 1000)
        rows.append(
            EvalRow(
                run_id=run_id, arm="A1", alert_id=a["alert_id"], split=a["split"],
                decision=out.decision, confidence=out.confidence,
                truly_suspicious=a["truly_suspicious"],
                citation_coverage=verify_narrative(out.narrative, empty).coverage,
                hallucinated_entity_rate=hallucinated_entity_rate(out.entities_named, input_entities(a, txns)),
                narrative=out.narrative, model_id=model_id, latency_ms=latency,
            )
        )
    return rows


def gemini_generate(model_id: str, max_retries: int = 6) -> Generate:
    """Vertex Gemini call with JSON output and exponential backoff on 429/503."""
    from google.genai import errors, types  # noqa: PLC0415

    from provenance import config  # noqa: PLC0415

    client = config.genai_client()
    cfg = types.GenerateContentConfig(
        temperature=0.0, response_mime_type="application/json", response_schema=A1Output
    )

    def generate(prompt: str) -> dict:
        for attempt in range(max_retries):
            try:
                resp = client.models.generate_content(model=model_id, contents=prompt, config=cfg)
                return json.loads(resp.text)
            except errors.APIError as e:
                if getattr(e, "code", None) not in (429, 503) or attempt == max_retries - 1:
                    raise
                time.sleep(2**attempt)
        raise RuntimeError("unreachable")

    return generate


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--arm", choices=["A0", "A1"], required=True)
    ap.add_argument("--split", default="golden", choices=["golden", "eval", "demo", "all"])
    ap.add_argument("--alerts", type=Path, default=ALERTS_PATH)
    ap.add_argument("--sample", type=Path, default=SAMPLE_PATH)
    ap.add_argument("--model", choices=["flash", "pro"], default="flash")
    ap.add_argument("--upload", action="store_true")
    a = ap.parse_args()

    alerts = load_alerts(a.alerts, a.split)
    run_id = f"{a.arm}-{a.split}-{uuid.uuid4().hex[:8]}"
    if a.arm == "A0":
        rows = run_a0(alerts, run_id)
    else:
        from provenance import config  # noqa: PLC0415

        model_id = config.model(a.model)
        wanted = {t for al in alerts for t in al["txn_ids"]}
        rows = run_a1(alerts, load_txn_index(a.sample, wanted), gemini_generate(model_id), run_id, model_id)
    print(f"wrote {write_jsonl(rows)}")
    print(json.dumps(summarize(rows), indent=2))
    if a.upload:
        print(f"loaded into {upload(rows)}")


if __name__ == "__main__":
    main()
