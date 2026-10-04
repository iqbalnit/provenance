"""Build the /eval page payload: latest run per arm, summaries, calibration, staleness lift."""
from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from provenance.eval.metrics import reliability_curve
from provenance.eval.results import ARTIFACTS, EvalRow, read_jsonl, summarize

ARM_ORDER = ["A0", "A1", "A2", "A3", "A4-naive", "A4"]
ARM_LABELS = {
    "A0": "Rules only, every alert to a human",
    "A1": "Ungrounded single Gemini call",
    "A2": "Grounded, auto-close on confidence alone",
    "A3": "Provenance: full system, live list",
    "A4-naive": "Archived list, fetch-date clock (typical RAG)",
    "A4": "Archived list, publisher-date clock",
}


def latest_local_runs(root: Path = ARTIFACTS) -> dict[str, list[EvalRow]]:
    runs: dict[str, list[EvalRow]] = {}
    if not root.exists():
        return runs
    for arm_dir in root.iterdir():
        files = sorted(arm_dir.glob("*.jsonl"), key=lambda p: p.stat().st_mtime)
        if files:
            runs[arm_dir.name] = read_jsonl(files[-1])
    return runs


def latest_bigquery_runs(table: str, client: Any = None) -> dict[str, list[EvalRow]]:  # pragma: no cover - needs GCP
    from google.cloud import bigquery  # noqa: PLC0415

    client = client or bigquery.Client()
    sql = f"""
    SELECT * EXCEPT(rn) FROM (
      SELECT *, DENSE_RANK() OVER (PARTITION BY arm ORDER BY run_started DESC) AS rn
      FROM (SELECT *, MIN(created_at) OVER (PARTITION BY run_id) AS run_started FROM `{table}`)
    ) WHERE rn = 1"""
    runs: dict[str, list[EvalRow]] = {}
    for r in client.query(sql).result():
        row = {k: v for k, v in dict(r).items() if k != "run_started"}
        runs.setdefault(row["arm"], []).append(EvalRow.model_validate(row))
    return runs


def build_report(runs: dict[str, list[EvalRow]]) -> dict[str, Any]:
    arms = []
    for arm in [a for a in ARM_ORDER if a in runs] + sorted(set(runs) - set(ARM_ORDER)):
        rows: Sequence[EvalRow] = runs[arm]
        scored = [r for r in rows if r.confidence is not None]
        model_ids = sorted({r.model_id or "" for r in rows})
        arms.append({
            "arm": arm,
            "label": ARM_LABELS.get(arm, arm),
            "run_id": rows[0].run_id if rows else None,
            "model_ids": model_ids,
            "plumbing_only": "offline" in model_ids,
            "summary": summarize(rows),
            "reliability": [
                {"confidence": c, "accuracy": a, "n": n}
                for c, a, n in reliability_curve([r.confidence for r in scored], [r.correct for r in scored])
            ],
        })
    by = {a["arm"]: a["summary"] for a in arms}
    lift = None
    if "A4-naive" in by and "A4" in by:
        lift = {
            "naive_tp_auto_closes": by["A4-naive"]["tp_auto_closes"],
            "asof_tp_auto_closes": by["A4"]["tp_auto_closes"],
            "naive_fn_rate": by["A4-naive"]["fn_rate_on_auto_close"],
            "asof_fn_rate": by["A4"]["fn_rate_on_auto_close"],
        }
    return {"arms": arms, "staleness_lift": lift, "plumbing_only": any(a["plumbing_only"] for a in arms)}
