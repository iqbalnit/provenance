"""System arms A3 / A4-naive / A4: the full agent graph over an alert split.

    python -m provenance.eval.arms --arm A3 --split golden [--upload]
    python -m provenance.eval.arms --arm A3 --split golden --resume artifacts/eval/A3/<run_id>.jsonl [--upload]

A3        live list, publisher-date freshness (the product)
A4-naive  archived list, fetch-date freshness (what typical RAG does)
A4        archived list, publisher-date freshness

Rows share the EvalRow schema with A0/A1, so one table compares every arm.
Confidence is converted to "probability the decision is correct" to match A1.
In PROVENANCE_MODE=offline the models are scripted: those numbers test the
plumbing and must never be reported as results.

Each row is appended to the run's jsonl as soon as its case finishes, so an
interrupted run keeps what it did; --resume reruns only missing and errored
alerts under the same run_id. A case that fails on the network (DNS, 503,
connection reset) is retried after a pause; timeouts and model errors are not,
they are results. After 3 alerts in a row fail on the network the run stops,
without summarising or uploading, and prints the --resume command.

Cases are kept in memory (PROVENANCE_STORE=memory): the eval reads them back in
this process, so Firestore would only add latency and a network dependency. Set
PROVENANCE_STORE=firestore to keep eval cases for the console.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
import uuid
from pathlib import Path

from provenance.core.models import EvidenceType
from provenance.core.typologies import FRESHNESS_SLA_DAYS
from provenance.eval.baselines import run_a0
from provenance.eval.results import ARTIFACTS, EvalRow, read_jsonl, summarize, upload, write_jsonl
from provenance.runtime import get_deps
from provenance.service.run import CaseError, run_case

ARMS = {
    "A3": ("live", "source_as_of"),
    "A4-naive": ("archived", "retrieved_at"),
    "A4": ("archived", "source_as_of"),
}


NETWORK_RETRIES = 2
MAX_CONSECUTIVE_NETWORK_FAILURES = 3
RETRY_WAIT_S = float(os.environ.get("PROVENANCE_RETRY_WAIT_S", "30"))
_TRANSIENT = {"ServiceUnavailable", "RetryError", "DeadlineExceeded", "ConnectionError", "ConnectionResetError",
              "gaierror", "_InactiveRpcError", "ConnectError", "ReadError", "RemoteProtocolError"}


def is_transient(exc: BaseException) -> bool:
    """A network or service-availability failure anywhere in the cause chain (not a timeout or model error)."""
    seen = set()
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc))
        if {c.__name__ for c in type(exc).__mro__} & _TRANSIENT:
            return True
        exc = exc.__cause__ or exc.__context__
    return False


class NetworkDown(RuntimeError):
    """Several alerts in a row failed on the network: stop rather than fill the run with error rows."""


def watchlist_check(arm: str, d) -> tuple[str, bool]:
    """(line to print, ok). A live list past its SLA under the publisher clock fails every case on
    staleness, so the run would measure nothing; the archived list is stale on purpose (A4)."""
    snapshot, basis = ARMS[arm]
    snap = d.watchlists[snapshot]
    age = (d.now() - snap.as_of).total_seconds() / 86400
    sla = FRESHNESS_SLA_DAYS[EvidenceType.WATCHLIST]
    line = f"{arm}: {snapshot} watchlist as of {snap.as_of.date()} ({age:.1f} days old; SLA {sla} days, {basis} clock)"
    if basis != "source_as_of" or age <= sla:
        return line, True
    if snapshot == "archived":
        return line + ": stale by design, every case should fail staleness", True
    return (line + f"\nSTOPPED: every {arm} case would escalate on staleness. Refresh the live list "
            "(python -m provenance.data.ofac fetch --live --live-as-of <date> --upload), point "
            "PROVENANCE_OFAC_LIVE_URI at it, and re-export .env (set -a; . ./.env; set +a): editing .env does not "
            "change a variable this shell already exported. --allow-stale runs anyway."), False


def run_path(arm: str, run_id: str) -> Path:
    return ARTIFACTS / arm / f"{run_id}.jsonl"


def select_alerts(alerts, split: str, limit: int | None = None) -> list[dict]:
    """Labelled alerts in a split, in a deterministic order; optionally the first `limit`."""
    chosen = sorted((x for x in alerts if "truly_suspicious" in x and split in ("all", x.get("split"))),
                    key=lambda x: x["alert_id"])
    return chosen[:limit] if limit else chosen


async def run_arm(arm: str, alerts: list[dict], run_id: str, trace=None, sink: Path | None = None) -> list[EvalRow]:
    snapshot, basis = ARMS[arm]
    d = get_deps()
    rows = []

    def keep(row: EvalRow) -> None:
        rows.append(row)
        if sink:  # durable as we go: an interrupted run can --resume
            sink.parent.mkdir(parents=True, exist_ok=True)
            with open(sink, "a") as f:
                f.write(row.model_dump_json() + "\n")

    down = 0
    for i, a in enumerate(alerts, 1):
        t0 = time.monotonic()
        for attempt in range(NETWORK_RETRIES + 1):
            try:
                case = d.repo.get_case(await run_case(a["alert_id"], snapshot, basis, trace=trace))
                err = None
                break
            except Exception as e:  # noqa: BLE001 - one alert must never end the run
                err = e
                if is_transient(e) and attempt < NETWORK_RETRIES:
                    wait = RETRY_WAIT_S * (attempt + 1)
                    print(f"  [{i}/{len(alerts)}] {a['alert_id']} network error ({type(e).__name__}); "
                          f"retrying in {wait:.0f}s", flush=True)
                    await asyncio.sleep(wait)
                    continue
                break
        if err is not None:
            # A case that doesn't finish is recorded, not dropped: decision "error" never counts as auto-close.
            reason = err.reason if isinstance(err, CaseError) else f"{type(err).__name__}: {err}"
            if is_transient(err):
                reason = f"network: {reason}"
            print(f"  [{i}/{len(alerts)}] {a['alert_id']} ERROR {reason[:160]} ({time.monotonic() - t0:.0f}s)", flush=True)
            keep(EvalRow(run_id=run_id, arm=arm, alert_id=a["alert_id"], split=a.get("split", ""),
                         decision="error", confidence=None, truly_suspicious=bool(a["truly_suspicious"]),
                         citation_coverage=0.0, hallucinated_entity_rate=None, narrative=reason[:500],
                         model_id=d.mode, latency_ms=int((time.monotonic() - t0) * 1000)))
            down = down + 1 if is_transient(err) else 0
            if down >= MAX_CONSECUTIVE_NETWORK_FAILURES:
                raise NetworkDown(f"{down} alerts in a row failed on the network")
            continue
        down = 0
        cfp = case.get("confidence")
        auto = case["decision"] == "auto_close"
        print(f"  [{i}/{len(alerts)}] {a['alert_id']} {case['decision']}"
              f"{' (suspicious)' if a['truly_suspicious'] else ''} ({time.monotonic() - t0:.0f}s)", flush=True)
        keep(EvalRow(
            run_id=run_id, arm=arm, alert_id=a["alert_id"], split=a.get("split", ""),
            decision=case["decision"],
            confidence=None if cfp is None else (cfp if auto else 1 - cfp),
            truly_suspicious=bool(a["truly_suspicious"]),
            citation_coverage=float(case.get("narrative_coverage", 1.0 if case.get("verified") else 0.0)),
            # Not claimed as zero: a cited sentence can still misstate its claim. That is
            # measured by the citation-fidelity judge (Phase 2), not assumed here.
            hallucinated_entity_rate=None,
            narrative="", model_id=d.mode, latency_ms=int((time.monotonic() - t0) * 1000),
            gate_failed=[c["name"] for c in (case.get("policy_gate") or {}).get("conditions", []) if not c.get("passed")],
        ))
    return rows


def resume_plan(path: Path, alerts: list[dict]) -> tuple[str, list[EvalRow], list[dict]]:
    """(run_id, finished rows to keep, alerts still to run). Errored alerts are rerun."""
    prior = read_jsonl(path)
    if not prior:
        raise SystemExit(f"{path} has no rows")
    done = {r.alert_id: r for r in prior if r.decision != "error"}  # last finished row per alert wins
    todo = [a for a in alerts if a["alert_id"] not in done]
    return prior[0].run_id, list(done.values()), todo


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--arm", choices=sorted(ARMS))
    ap.add_argument("--all", action="store_true", help="A0 + every system arm (A1 needs --mode gemini; run it via baselines)")
    ap.add_argument("--split", default="golden", choices=["golden", "eval", "demo", "all"])
    ap.add_argument("--limit", type=int, help="run only the first N alerts (by alert_id) to bound model spend")
    ap.add_argument("--trace", action="store_true", help="print every agent step for each case")
    ap.add_argument("--resume", type=Path, help="a run's jsonl: keep its finished cases, rerun missing and errored ones")
    ap.add_argument("--allow-stale", action="store_true", help="run A3 even if the live watchlist is past its SLA")
    ap.add_argument("--upload", action="store_true")
    a = ap.parse_args()
    if not a.arm and not a.all:
        ap.error("give --arm or --all")
    if a.resume and (a.all or not a.arm):
        ap.error("--resume works with one --arm")
    os.environ.setdefault("PROVENANCE_STORE", "memory")
    d = get_deps()
    alerts = select_alerts(d.alerts.values(), a.split, a.limit)
    if d.mode == "offline":
        print("NOTE: offline mode uses scripted models; these numbers test plumbing only.")
    arms_to_run = ["A0", *ARMS] if a.all else [a.arm]
    for arm in (x for x in arms_to_run if x in ARMS):
        line, ok = watchlist_check(arm, d)
        print(line, flush=True)
        if not ok and not a.allow_stale:
            raise SystemExit(2)
    for arm in arms_to_run:
        run_id = f"{arm}-{a.split}-{d.mode}-{uuid.uuid4().hex[:8]}"
        if arm == "A0":
            rows = run_a0([{**x, "split": x.get("split", "")} for x in alerts], run_id)
            rows = [r.model_copy(update={"model_id": d.mode}) for r in rows]
        else:
            kept, todo = [], alerts
            if a.resume:
                run_id, kept, todo = resume_plan(a.resume, alerts)
                print(f"resuming {run_id}: {len(kept)} finished, {len(todo)} to run")
            sink = run_path(arm, run_id)
            print(f"rows are saved as they finish to {sink} (resume with --resume {sink})", flush=True)
            try:
                new = asyncio.run(run_arm(arm, todo, run_id, sink=sink,
                                          trace=(lambda x: print('    ' + x, flush=True)) if a.trace else None))
            except NetworkDown as e:
                raise SystemExit(f"\nSTOPPED: {e}. Nothing was summarised or uploaded; finished cases are saved.\n"
                                 f"Check the network, then rerun with: --resume {sink}") from None
            rows = kept + new
        print(f"{arm}: wrote {write_jsonl(rows)}")
        print(json.dumps(summarize(rows), indent=2))
        if a.upload:
            print(f"loaded into {upload(rows)}")


if __name__ == "__main__":
    main()
