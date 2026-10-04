"""One result schema for every eval arm, plus summary and writers.

Rows go to artifacts/eval/<arm>/<run_id>.jsonl and optionally BigQuery
`eval_results` (partitioned by created_at, clustered by arm), which the
console's /eval page reads.
"""
from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, Field

from provenance.eval.metrics import (
    Outcome,
    analyst_hours_saved,
    auto_close_rate,
    escalation_precision,
    expected_calibration_error,
    false_negative_rate_on_auto_close,
)

ARTIFACTS = Path("artifacts/eval")


class EvalRow(BaseModel):
    run_id: str
    arm: str
    alert_id: str
    split: str
    decision: str  # "auto_close" | "escalate"
    confidence: float | None
    truly_suspicious: bool
    citation_coverage: float
    hallucinated_entity_rate: float | None
    narrative: str = ""
    model_id: str | None = None
    latency_ms: int | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @property
    def auto_closed(self) -> bool:
        return self.decision == "auto_close"

    @property
    def correct(self) -> bool:
        # Auto-closing a benign alert or escalating a suspicious one is correct.
        return self.auto_closed != self.truly_suspicious


def summarize(rows: Sequence[EvalRow]) -> dict:
    outcomes = [Outcome(r.alert_id, r.auto_closed, r.truly_suspicious) for r in rows]
    scored = [r for r in rows if r.confidence is not None]
    halluc = [r.hallucinated_entity_rate for r in rows if r.hallucinated_entity_rate is not None]
    lat = sorted(r.latency_ms for r in rows if r.latency_ms is not None)
    return {
        "n": len(rows),
        "positives": sum(r.truly_suspicious for r in rows),
        "fn_rate_on_auto_close": false_negative_rate_on_auto_close(outcomes),
        "tp_auto_closes": sum(r.auto_closed and r.truly_suspicious for r in rows),
        "auto_close_rate": auto_close_rate(outcomes),
        "escalation_precision": escalation_precision(outcomes),
        "analyst_hours_saved": round(analyst_hours_saved(outcomes), 2),
        "citation_coverage_mean": sum(r.citation_coverage for r in rows) / len(rows) if rows else 0.0,
        "hallucinated_entity_rate_mean": sum(halluc) / len(halluc) if halluc else None,
        "ece": expected_calibration_error([r.confidence for r in scored], [r.correct for r in scored])
        if scored else None,
        "latency_p50_ms": lat[len(lat) // 2] if lat else None,
        "latency_p95_ms": lat[min(len(lat) - 1, int(len(lat) * 0.95))] if lat else None,
    }


def write_jsonl(rows: Sequence[EvalRow], out_dir: Path = ARTIFACTS) -> Path:
    if not rows:
        raise ValueError("no rows")
    path = out_dir / rows[0].arm / f"{rows[0].run_id}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        f.writelines(r.model_dump_json() + "\n" for r in rows)
    return path


def read_jsonl(path: Path) -> list[EvalRow]:
    return [EvalRow.model_validate_json(line) for line in path.read_text().splitlines() if line.strip()]


def upload(rows: Sequence[EvalRow], table: str = "eval_results") -> str:
    from google.cloud import bigquery  # noqa: PLC0415

    from provenance import config  # noqa: PLC0415

    client = bigquery.Client(project=config.project())
    table_id = f"{config.ensure_bq_dataset(client)}.{table}"
    job_config = bigquery.LoadJobConfig(
        source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
        schema=[
            bigquery.SchemaField("run_id", "STRING"), bigquery.SchemaField("arm", "STRING"),
            bigquery.SchemaField("alert_id", "STRING"), bigquery.SchemaField("split", "STRING"),
            bigquery.SchemaField("decision", "STRING"), bigquery.SchemaField("confidence", "FLOAT"),
            bigquery.SchemaField("truly_suspicious", "BOOL"),
            bigquery.SchemaField("citation_coverage", "FLOAT"),
            bigquery.SchemaField("hallucinated_entity_rate", "FLOAT"),
            bigquery.SchemaField("narrative", "STRING"), bigquery.SchemaField("model_id", "STRING"),
            bigquery.SchemaField("latency_ms", "INT64"), bigquery.SchemaField("created_at", "TIMESTAMP"),
        ],
        write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
        time_partitioning=bigquery.TimePartitioning(field="created_at"),
        clustering_fields=["arm"],
    )
    payload = [json.loads(r.model_dump_json()) for r in rows]
    client.load_table_from_json(payload, table_id, job_config=job_config).result()
    return table_id


def labels_from_reviews(cases: Sequence[dict]) -> dict[str, bool]:
    """alert_id -> truly_suspicious, from the latest analyst review of each alert.

    Analyst overrides become ground truth for the next eval run (PLAN.md HITL node).
    """
    latest: dict[str, tuple[str, bool]] = {}
    for c in cases:
        r = c.get("human_decision")
        if not r:
            continue
        key = (r.get("reviewed_at", ""), r["verdict"] == "suspicious")
        if c["alert_id"] not in latest or key[0] >= latest[c["alert_id"]][0]:
            latest[c["alert_id"]] = key
    return {a: v for a, (_, v) in latest.items()}
