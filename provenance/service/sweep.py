"""Nightly staleness sweep: Cloud Scheduler -> Pub/Sub -> POST /trigger/sweep.

Reopens auto-closed cases whose evidentiary basis changed and re-runs them on
the live list with the publisher-date clock. The original case keeps its
record; the new case links back with `reopens`.
"""
from __future__ import annotations

import asyncio
from typing import Any

from provenance.core.models import EvidenceType
from provenance.core.sweep import recheck
from provenance.runtime import Deps
from provenance.service.run import new_case_id, run_case


async def sweep(d: Deps, wait: bool = False) -> dict[str, Any]:
    checked, reopened, reruns = 0, [], []
    for case in d.repo.list_cases():
        if case.get("decision") != "auto_close" or case.get("status") != "done":
            continue
        checked += 1
        case_id = case["case_id"]
        claims = [c for c in d.repo.ledger(case_id).all() if c.evidence_type is EvidenceType.WATCHLIST]
        findings = recheck(claims, d.watchlists["live"], d.now())
        if not findings:
            continue
        alert_id = case["alert_id"]
        new_id = new_case_id(alert_id, "live", "source_as_of")
        d.repo.update(case_id, {
            "status": "reopened", "reopened_by": "staleness_sweep", "reopened_as": new_id,
            "reopened_at": d.now().isoformat(), "reopen_findings": [f.model_dump() for f in findings],
        })
        reopened.append({"case_id": case_id, "new_case_id": new_id, "findings": [f.reason for f in findings]})

        async def rerun(alert_id: str = alert_id, new_id: str = new_id, old: str = case_id) -> None:
            await run_case(alert_id, "live", "source_as_of", case_id=new_id)
            d.repo.update(new_id, {"reopens": old})

        reruns.append(rerun())
    if wait:
        await asyncio.gather(*reruns)
    else:
        for r in reruns:
            asyncio.ensure_future(r)
    return {"checked": checked, "reopened": reopened}
