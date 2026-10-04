# Eval arms

Measure the ungrounded baseline **first**, before any agent code exists (Mon Sep 28).
All arms run over the same alert set and write to BigQuery `eval.results`,
one row per (arm, alert_id). The console's `/eval` page reads from there.
**Never run an eval live on stage.**

| Arm | What | Proves | MVP? |
|---|---|---|---|
| A0 | Rules only; every alert goes to a human | Status-quo cost baseline (arithmetic, no model) | yes |
| A1 | Ungrounded single Gemini call: alert JSON in, disposition out, no tools | What "just add an LLM" produces | **yes** |
| A2 | Grounded evidence agents + citations, auto-close on confidence alone | Isolates grounding lift from governance lift | optional (kill list #4) |
| A3 | Full system: A2 + citation verifier + staleness auditor + policy gate | The product | **yes** |
| A4 | A3 on the archived (~18-month) OFAC snapshot, run twice: **A4-naive** measures freshness by `retrieved_at` (what typical RAG does) and **A4** by `source_as_of` | The thesis. A4-naive auto-closes cases it should not; A4 escalates them | **yes** |

A1→A3 is the grounding + governance lift. A2→A3 is the governance lift.
**A4-naive → A4 is the staleness lift, and nobody else will have it.**

## Running the arms

```bash
uv run python -m provenance.eval.baselines --arm A0 --split golden
uv run python -m provenance.eval.baselines --arm A1 --split golden
PROVENANCE_MODE=gemini uv run python -m provenance.eval.arms --arm A3 --split golden
PROVENANCE_MODE=gemini uv run python -m provenance.eval.arms --arm A4-naive --split golden
PROVENANCE_MODE=gemini uv run python -m provenance.eval.arms --arm A4 --split golden
```

`--all` runs A0 plus every system arm in one go. The console's `/eval.html` reads the latest run per arm from `artifacts/eval/` (or BigQuery `eval_results` with `PROVENANCE_DATA=gcp`).

All arms write the same `EvalRow` schema. Offline-mode arm runs use scripted models and are plumbing checks only.

## Metrics (in `provenance/eval/metrics.py`)

1. `false_negative_rate_on_auto_close`: lead with it; target 0 on the golden set
2. `auto_close_rate`: realistic 40–60%
3. `analyst_hours_saved`: rate × N × 25 min, then converted to money
4. Citation coverage: from `provenance.core.verifier` (A3 = 1.0 by construction)
5. Citation fidelity: an LLM judge (`prompt_template` metric) checks the source supports the claim
6. `hallucinated_entity_rate`: a deterministic set difference against the ledger
7. `expected_calibration_error` + `reliability_curve`
8. Staleness-induced error rate (A4-naive vs A4)
9. `escalation_precision`
10. $/alert, p50/p95 latency (from Cloud Trace)

## Corpus split (300 alerts, ~95% FP)

40 hand-reviewed golden · 200 eval · 60 held out for the live demo.
Phase 3 expands this to 1,000 alerts / 100 golden.
