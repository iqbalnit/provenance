"""System arms A3 / A4-naive / A4: the full agent graph over an alert split.

    python -m provenance.eval.arms --arm A3 --split golden [--upload]

A3        live list, publisher-date freshness (the product)
A4-naive  archived list, fetch-date freshness (what typical RAG does)
A4        archived list, publisher-date freshness

Rows share the EvalRow schema with A0/A1, so one table compares every arm.
Confidence is converted to "probability the decision is correct" to match A1.
In PROVENANCE_MODE=offline the models are scripted: those numbers test the
plumbing and must never be reported as results.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import time
import uuid

from provenance.eval.baselines import run_a0
from provenance.eval.results import EvalRow, summarize, upload, write_jsonl
from provenance.runtime import get_deps
from provenance.service.run import run_case

ARMS = {
    "A3": ("live", "source_as_of"),
    "A4-naive": ("archived", "retrieved_at"),
    "A4": ("archived", "source_as_of"),
}


def select_alerts(alerts, split: str, limit: int | None = None) -> list[dict]:
    """Labelled alerts in a split, in a deterministic order; optionally the first `limit`."""
    chosen = sorted((x for x in alerts if "truly_suspicious" in x and split in ("all", x.get("split"))),
                    key=lambda x: x["alert_id"])
    return chosen[:limit] if limit else chosen


async def run_arm(arm: str, alerts: list[dict], run_id: str) -> list[EvalRow]:
    snapshot, basis = ARMS[arm]
    d = get_deps()
    rows = []
    for a in alerts:
        t0 = time.monotonic()
        case = d.repo.get_case(await run_case(a["alert_id"], snapshot, basis))
        cfp = case.get("confidence")
        auto = case["decision"] == "auto_close"
        rows.append(EvalRow(
            run_id=run_id, arm=arm, alert_id=a["alert_id"], split=a.get("split", ""),
            decision=case["decision"],
            confidence=None if cfp is None else (cfp if auto else 1 - cfp),
            truly_suspicious=bool(a["truly_suspicious"]),
            citation_coverage=float(case.get("narrative_coverage", 1.0 if case.get("verified") else 0.0)),
            # Not claimed as zero: a cited sentence can still misstate its claim. That is
            # measured by the citation-fidelity judge (Phase 2), not assumed here.
            hallucinated_entity_rate=None,
            narrative="", model_id=d.mode, latency_ms=int((time.monotonic() - t0) * 1000),
        ))
    return rows


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--arm", choices=sorted(ARMS))
    ap.add_argument("--all", action="store_true", help="A0 + every system arm (A1 needs --mode gemini; run it via baselines)")
    ap.add_argument("--split", default="golden", choices=["golden", "eval", "demo", "all"])
    ap.add_argument("--limit", type=int, help="run only the first N alerts (by alert_id) to bound model spend")
    ap.add_argument("--upload", action="store_true")
    a = ap.parse_args()
    if not a.arm and not a.all:
        ap.error("give --arm or --all")
    d = get_deps()
    alerts = select_alerts(d.alerts.values(), a.split, a.limit)
    if d.mode == "offline":
        print("NOTE: offline mode uses scripted models; these numbers test plumbing only.")
    for arm in (["A0", *ARMS] if a.all else [a.arm]):
        run_id = f"{arm}-{a.split}-{d.mode}-{uuid.uuid4().hex[:8]}"
        if arm == "A0":
            rows = run_a0([{**x, "split": x.get("split", "")} for x in alerts], run_id)
            rows = [r.model_copy(update={"model_id": d.mode}) for r in rows]
        else:
            rows = asyncio.run(run_arm(arm, alerts, run_id))
        print(f"{arm}: wrote {write_jsonl(rows)}")
        print(json.dumps(summarize(rows), indent=2))
        if a.upload:
            print(f"loaded into {upload(rows)}")


if __name__ == "__main__":
    main()
