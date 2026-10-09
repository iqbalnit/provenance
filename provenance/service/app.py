"""HTTP service: the analyst console plus a small JSON API. Deployed to Cloud Run.

    uv run uvicorn provenance.service.app:app --port 8080

Cases run in the background so the console can watch the ledger fill. On
Cloud Run, deploy with --no-cpu-throttling so background runs keep CPU after
the POST returns (see deploy/deploy.sh).
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from provenance.eval import report
from provenance.runtime import get_deps
from provenance.service.run import new_case_id, run_case
from provenance.service.sweep import sweep

CONSOLE = Path(__file__).resolve().parent.parent.parent / "console"
log = logging.getLogger("provenance")

app = FastAPI(title="Provenance", version="0.1.0")
_tasks: set[asyncio.Task] = set()


class CaseRequest(BaseModel):
    alert_id: str
    snapshot: Literal["archived", "live"] = "live"
    staleness_basis: Literal["source_as_of", "retrieved_at"] = "source_as_of"


def _jsonable(v: Any) -> Any:
    if isinstance(v, dict):
        return {k: _jsonable(x) for k, x in v.items()}
    if isinstance(v, list | tuple):
        return [_jsonable(x) for x in v]
    if isinstance(v, datetime | date):
        return v.isoformat()
    if hasattr(v, "value") and not isinstance(v, str | int | float | bool):
        return v.value
    return v


@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "mode": get_deps().mode}


@app.get("/api/alerts")
def alerts() -> dict:
    d = get_deps()
    return {
        "mode": d.mode,
        "snapshots": {k: {"as_of": s.as_of.isoformat(), "uri": s.source_uri, "entries": len(s.entries)}
                      for k, s in d.watchlists.items()},
        "alerts": [
            {"alert_id": a["alert_id"], "label": a.get("label") or a["rule"], "rule": a["rule"],
             "account_id": a["account_id"], "customer": d.customers.get(a["account_id"], {}).get("name")}
            for a in d.alerts.values()
        ],
    }


@app.post("/api/cases", status_code=202)
async def create_case(req: CaseRequest) -> dict:
    d = get_deps()
    if req.alert_id not in d.alerts:
        raise HTTPException(404, f"unknown alert {req.alert_id}")
    case_id = new_case_id(req.alert_id, req.snapshot, req.staleness_basis)

    async def go() -> None:
        try:
            await run_case(req.alert_id, req.snapshot, req.staleness_basis, case_id=case_id)
        except Exception:  # recorded on the case by run_case
            log.exception("case %s failed", case_id)

    t = asyncio.create_task(go())
    _tasks.add(t)
    t.add_done_callback(_tasks.discard)
    return {"case_id": case_id}


@app.get("/api/cases/{case_id}")
def get_case(case_id: str) -> dict:
    case = get_deps().repo.get_case(case_id)
    if case is None:
        # The background task may not have opened the case yet.
        return {"case_id": case_id, "status": "queued", "stage": "queued", "claims": []}
    return _jsonable(case)


class ReviewRequest(BaseModel):
    verdict: Literal["suspicious", "false_positive"]
    note: str = ""
    reviewer: str = "analyst"


@app.post("/api/cases/{case_id}/review")
def review_case(case_id: str, req: ReviewRequest) -> dict:
    d = get_deps()
    case = d.repo.get_case(case_id)
    if case is None or case.get("status") not in {"done", "reopened"}:
        raise HTTPException(409, "case is not finished")
    agrees = (req.verdict == "suspicious") == (case.get("decision") == "escalate")
    review = {**req.model_dump(), "action": "confirm" if agrees else "override",
              "system_decision": case.get("decision"), "reviewed_at": d.now().isoformat()}
    n = d.repo.add_review(case_id, review)
    return {"n": n, **review}


PROBE_SENTENCE = "The customer's activity is consistent with their stated business."


@app.post("/api/cases/{case_id}/probe")
def probe_verifier(case_id: str) -> dict:
    """Append one uncited sentence to the accepted narrative and re-run the deterministic verifier and gate.

    A demonstration of the guarantee on real output: it never changes the case's decision, and it is
    recorded separately as a probe so it is never mistaken for the agent's own draft.
    """
    from provenance.core.decide import decide_case  # noqa: PLC0415
    from provenance.core.models import Typology  # noqa: PLC0415

    d = get_deps()
    case = d.repo.get_case(case_id)
    if case is None:
        raise HTTPException(404, f"unknown case {case_id}")
    if case.get("status") not in {"done", "reopened"} or not case.get("attempts"):
        raise HTTPException(409, "case is not finished")
    narrative = f"{case['attempts'][-1]['narrative'].rstrip()} {PROBE_SENTENCE}"
    result = decide_case(
        typology=Typology(case["typology"]),
        ledger=d.repo.ledger(case_id),
        narrative=narrative,
        confidence=float(case.get("confidence") or 0.0),
        now=d.now(),
        staleness_basis=case.get("staleness_basis", "source_as_of"),
    )
    v = result.verification
    probe = {
        "kind": "verifier_probe",
        "added_sentence": PROBE_SENTENCE,
        "passed": v.passed,
        "coverage": v.coverage,
        "sentences": [{"text": x.text, "ok": x.ok} for x in v.sentences],
        "failures": [f.text for f in v.failures],
        "gate_decision": result.decision.value,
        "gate_failed": [c.name for c in result.gate.failed],
        "probed_at": d.now().isoformat(),
    }
    d.repo.update(case_id, {"probes": [*case.get("probes", []), probe]})
    return probe


@app.post("/api/sweep")
async def run_sweep() -> dict:
    return await sweep(get_deps())


@app.post("/trigger/sweep")
async def trigger_sweep(envelope: dict) -> dict:
    """Pub/Sub push endpoint (Cloud Scheduler -> Pub/Sub -> here). The message body is ignored."""
    msg = (envelope or {}).get("message") or {}
    if "data" in msg:
        try:
            json.loads(base64.b64decode(msg["data"]) or b"{}")
        except ValueError:
            log.warning("sweep trigger with non-JSON payload")
    return await sweep(get_deps())


@app.get("/api/eval")
def eval_report() -> dict:
    # The deployed demo serves the bundle but still shows the real eval: PROVENANCE_EVAL=bigquery.
    runs = None
    if os.environ.get("PROVENANCE_DATA") == "gcp" or os.environ.get("PROVENANCE_EVAL") == "bigquery":
        try:  # pragma: no cover - needs GCP
            from provenance import config  # noqa: PLC0415

            runs = report.latest_bigquery_runs(f"{config.bq_dataset()}.eval_results")
        except Exception:  # noqa: BLE001 - an empty eval page beats a 500
            log.exception("eval_results unavailable; falling back to local runs")
    if runs is None:
        runs = report.latest_local_runs()
    return _jsonable({**report.build_report(runs), "generated_at": datetime.now(UTC)})


# The console is plain static files: served here, or by Firebase Hosting with /api/** rewritten to this service.
app.mount("/", StaticFiles(directory=CONSOLE, html=True), name="console")
