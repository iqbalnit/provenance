"""Generate, tune, select and split the alert corpus.

    python -m provenance.data.alerts --input data/raw/saml_d_sample.csv [--upload]

1. tune(): grid over rule thresholds; report FP rate per config; pick the one
   closest to TARGET_FP inside the 95–97% band.
2. select(): stratified pick of N alerts by (rule, label) that keeps the FP rate.
3. split(): deterministic golden / eval / demo split. The golden set is
   positive-enriched (see GOLDEN_MIN_POSITIVES) because at ~96% FP a 40-alert
   golden set at natural prevalence holds one or two suspicious cases, too few
   to back "zero true-positive auto-closes".

Writes artifacts/alerts.jsonl and artifacts/tuning_report.json. The measured FP
rate in the report is the number the video opens with.
"""
from __future__ import annotations

import argparse
import copy
import csv
import hashlib
import itertools
import json
from collections import defaultdict
from collections.abc import Sequence
from pathlib import Path

from provenance.rules.engine import (
    RULE_TYPOLOGY,
    THRESHOLDS,
    Alert,
    Thresholds,
    Txn,
    generate_alerts,
    measure_fp_rate,
)

TARGET_FP = 0.96
FP_BAND = (0.95, 0.97)
N_ALERTS = 300
SPLIT_SIZES = {"golden": 40, "eval": 200, "demo": 60}
GOLDEN_MIN_POSITIVES = 8
ARTIFACTS = Path("artifacts")

# "rule.param" -> candidate values. Kept small: every config re-runs the engine.
DEFAULT_GRID: dict[str, list] = {
    "structuring.min_count": [2, 3, 4],
    "rapid_movement.outflow_pct": [0.7, 0.8, 0.9],
    "high_risk_corridor.min_amount": [2_000.0, 5_000.0, 10_000.0],
}


def load_txns(path: Path) -> list[Txn]:
    with open(path, newline="", encoding="utf-8") as f:
        return [Txn.from_saml_d(r, i) for i, r in enumerate(csv.DictReader(f))]


def _apply(base: Thresholds, overrides: dict[str, object]) -> Thresholds:
    t = copy.deepcopy(base)
    for key, v in overrides.items():
        rule, param = key.split(".", 1)
        t[rule][param] = v
    return t


def tune(
    txns: Sequence[Txn],
    grid: dict[str, list] | None = None,
    base: Thresholds | None = None,
    target: float = TARGET_FP,
    band: tuple[float, float] = FP_BAND,
) -> tuple[Thresholds, list[dict]]:
    grid = grid if grid is not None else DEFAULT_GRID
    base = base or THRESHOLDS
    keys = list(grid)
    report: list[dict] = []
    best: tuple[tuple, Thresholds] | None = None
    for values in itertools.product(*(grid[k] for k in keys)) if keys else [()]:
        overrides = dict(zip(keys, values))
        th = _apply(base, overrides)
        alerts = generate_alerts(txns, th)
        fp = measure_fp_rate(alerts)
        in_band = band[0] <= fp <= band[1]
        report.append({"overrides": overrides, "n_alerts": len(alerts), "fp_rate": round(fp, 4), "in_band": in_band})
        # Prefer in-band, then closest to target, then more alerts.
        score = (not in_band, abs(fp - target), -len(alerts))
        if len(alerts) and (best is None or score < best[0]):
            best = (score, th)
    if best is None:
        raise ValueError("no configuration produced any alerts")
    return best[1], report


def _h(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def _largest_remainder(weights: dict, total: int) -> dict:
    s = sum(weights.values())
    if not s:
        return {k: 0 for k in weights}
    raw = {k: w * total / s for k, w in weights.items()}
    out = {k: int(v) for k, v in raw.items()}
    for k in sorted(raw, key=lambda k: raw[k] - out[k], reverse=True)[: total - sum(out.values())]:
        out[k] += 1
    return out


def select(alerts: Sequence[Alert], n: int = N_ALERTS) -> list[Alert]:
    """Stratified by (rule, label), proportional to the population, so the FP rate holds."""
    strata: dict[tuple, list[Alert]] = defaultdict(list)
    for a in alerts:
        strata[(a.rule, a.truly_suspicious)].append(a)
    quotas = _largest_remainder({k: len(v) for k, v in strata.items()}, min(n, len(alerts)))
    picked: list[Alert] = []
    for k, group in strata.items():
        picked.extend(sorted(group, key=lambda a: _h(a.alert_id))[: quotas[k]])
    return sorted(picked, key=lambda a: _h(a.alert_id))


def split(alerts: Sequence[Alert], sizes: dict[str, int] | None = None,
          golden_min_pos: int = GOLDEN_MIN_POSITIVES) -> dict[str, str]:
    sizes = sizes or SPLIT_SIZES
    ordered = sorted(alerts, key=lambda a: _h("split:" + a.alert_id))
    pos = [a for a in ordered if a.truly_suspicious]
    neg = [a for a in ordered if not a.truly_suspicious]
    # Positive-enrich golden, but never take more than half the positives.
    g_pos = min(golden_min_pos, len(pos) // 2, sizes["golden"])
    golden = pos[:g_pos] + neg[: sizes["golden"] - g_pos]
    rest_pos, rest_neg = pos[g_pos:], neg[sizes["golden"] - g_pos :]
    eval_share = sizes["eval"] / (sizes["eval"] + sizes["demo"])
    e_pos = round(len(rest_pos) * eval_share)
    e_neg = min(len(rest_neg), max(0, sizes["eval"] - e_pos))
    out = {a.alert_id: "golden" for a in golden}
    out |= {a.alert_id: "eval" for a in rest_pos[:e_pos] + rest_neg[:e_neg]}
    out |= {a.alert_id: "demo" for a in rest_pos[e_pos:] + rest_neg[e_neg:]}
    return out


def to_record(a: Alert, split_name: str) -> dict:
    return {
        "alert_id": a.alert_id,
        "account_id": a.account_id,
        "rule": a.rule,
        "typology_hint": RULE_TYPOLOGY[a.rule],
        "window_start": a.window_start.isoformat(),
        "window_end": a.window_end.isoformat(),
        "txn_ids": a.txn_ids,
        "truly_suspicious": a.truly_suspicious,
        "laundering_types": sorted(a.laundering_types),
        "split": split_name,
    }


def build(input_path: Path, n: int = N_ALERTS, out_dir: Path = ARTIFACTS,
          grid: dict[str, list] | None = None) -> dict:
    txns = load_txns(input_path)
    thresholds, report = tune(txns, grid)
    population = generate_alerts(txns, thresholds)
    chosen = select(population, n)
    splits = split(chosen, _scaled_sizes(len(chosen)))
    records = [to_record(a, splits[a.alert_id]) for a in chosen]
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / "alerts.jsonl", "w") as f:
        f.writelines(json.dumps(r) + "\n" for r in records)
    summary = {
        "population_alerts": len(population),
        "population_fp_rate": round(measure_fp_rate(population), 4),
        "selected_alerts": len(chosen),
        "selected_fp_rate": round(measure_fp_rate(chosen), 4),
        "selected_positives": sum(a.truly_suspicious for a in chosen),
        "split_counts": {s: sum(1 for r in records if r["split"] == s) for s in SPLIT_SIZES},
        "split_positives": {s: sum(r["truly_suspicious"] for r in records if r["split"] == s) for s in SPLIT_SIZES},
        "thresholds": _jsonable(thresholds),
        "grid": report,
    }
    (out_dir / "tuning_report.json").write_text(json.dumps(summary, indent=2))
    return summary


def _scaled_sizes(n: int) -> dict[str, int]:
    total = sum(SPLIT_SIZES.values())
    return _largest_remainder(SPLIT_SIZES, n) if n < total else {
        "golden": SPLIT_SIZES["golden"], "demo": SPLIT_SIZES["demo"],
        "eval": n - SPLIT_SIZES["golden"] - SPLIT_SIZES["demo"],
    }


def _jsonable(t: Thresholds) -> dict:
    return {r: {k: sorted(v) if isinstance(v, set) else v for k, v in p.items()} for r, p in t.items()}


def upload(path: Path = ARTIFACTS / "alerts.jsonl", table: str = "alerts") -> str:
    from google.cloud import bigquery  # noqa: PLC0415

    from provenance import config  # noqa: PLC0415

    client = bigquery.Client(project=config.project())
    table_id = f"{config.bq_dataset()}.{table}"
    job_config = bigquery.LoadJobConfig(
        source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
        autodetect=True,
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
    )
    with open(path, "rb") as f:
        client.load_table_from_file(f, table_id, job_config=job_config).result()
    return table_id


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--input", type=Path, default=Path("data/raw/saml_d_sample.csv"))
    ap.add_argument("--n", type=int, default=N_ALERTS)
    ap.add_argument("--out", type=Path, default=ARTIFACTS)
    ap.add_argument("--upload", action="store_true")
    a = ap.parse_args()
    s = build(a.input, a.n, a.out)
    print(json.dumps({k: v for k, v in s.items() if k != "grid"}, indent=2))
    if not FP_BAND[0] <= s["selected_fp_rate"] <= FP_BAND[1]:
        print(f"WARNING: FP rate {s['selected_fp_rate']} outside {FP_BAND}; widen DEFAULT_GRID or resample.")
    if a.upload:
        print(f"loaded into {upload(a.out / 'alerts.jsonl')}")


if __name__ == "__main__":
    main()
