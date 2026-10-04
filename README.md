# Provenance — AI Builder Cup 2026

**Problem statement:** BFSI — intelligent risk, fraud, and financial experiences
**Team + product name:** Provenance
**One-liner:** An AML triage agent that can't say anything it can't cite — and escalates the moment its evidence goes stale.

---

A bank's transaction-monitoring system fires alerts at a 95–98% false-positive rate, and an L1
analyst reads every one at ~25 minutes each. Provenance infers an alert's typology, builds an
evidence plan, dispatches parallel specialist agents (transactions, KYC documents, sanctions
lists, live adverse media, counterparty graph), and writes every finding to an immutable claim
ledger carrying source URI, verbatim quote, and two timestamps — when the publisher says the
fact was true, and when we fetched it.

A **deterministic** verifier then rejects the agent's own draft disposition if any assertion
lacks a resolvable claim ID. Auto-close requires clearing a six-condition gate; otherwise the
case escalates with a pre-built file and a SAR draft.

**The demo:** run the same alert against an archived OFAC snapshot and today's. Stale grounding
auto-closes it — fluent, confident, wrong. Live lists fire the staleness auditor, confidence
collapses, the case escalates. Real public data.

---

## Stack

Gemini on Vertex / Agent Platform · ADK (Agent Development Kit) · Cloud Run · Firebase Hosting +
Firestore · BigQuery · Cloud Storage · Cloud Trace · Model Armor

## Repo contents

| Path | What |
|---|---|
| `SUBMISSION.md` | The Hack2skill form field by field, the 1024-character description, billing and repo-visibility steps |
| `STRATEGY.md` | **Start here.** Win thesis, MVP, rebased schedule, owners, kill list, demo script |
| `PLAN.md` | The full 27-day build plan: architecture, agent decomposition, data sourcing, eval design, day-by-day gates, kill list, risks |
| `TEAM.md` | Team description at four lengths (tagline to full), with exact character counts for portal fields |
| `provenance/core/` | Deterministic core: claim ledger, citation verifier, staleness auditor, policy gate, `decide_case()`. No GCP dependencies |
| `provenance/tools/` | OFAC SDN snapshot matcher; parameterized BigQuery templates |
| `provenance/rules/` | Rule engine that generates labelled alerts from SAML-D |
| `provenance/eval/` + `eval/ARMS.md` | Eval metrics (FN-on-auto-close, ECE, hallucinated entities…) and arm definitions |
| `provenance/data/` | SAML-D sampler + BigQuery loader, alert tuner/splitter, OFAC snapshot fetcher |
| `provenance/stores/` | Firestore claim ledger and case writes (`cases/{id}/claims`, `narrative`, gate, staleness) |
| `provenance/agents/provenance_agent/` | The ADK agent graph: typologist, parallel evidence agents, verifier loop, policy gate |
| `provenance/service/` | FastAPI service (API + console) and the single-alert runner |
| `console/` | Analyst console: reversal view, live ledger with both timestamps, rejected drafts, six-condition gate |
| `demo/` | Offline demo bundle. **All names, accounts and media are fictional** |
| `deploy/`, `Dockerfile`, `firebase.json` | Cloud Run + Firebase Hosting deployment |
| `brand/provenance-mark.svg` | Product glyph. Team logo assets (`brand/team/`, `BRAND.md`) still to be added |

## Timeline

**Submission deadline: Sun Oct 18 2026. We submit Fri Oct 16.**

| Phase | Dates | Ends with |
|---|---|---|
| 1 — foundations and baselines | Sep 26 – Oct 1 | A public Cloud Run URL returning a cited disposition (rebased; see `STRATEGY.md`) |
| 2 — core system, submittable | Oct 2–6 | **An entry we'd be content to submit (target Oct 4).** Everything after is upside |
| 3 — depth (closed scope list) | Oct 7–11 | Arms re-run at 1,000 alerts, numbers stable |
| 4 — production | Oct 12–18 | **Oct 12 hard feature freeze.** Video, deck, dress rehearsal, submit Oct 16 |

## Quick start: the whole system on a laptop, no cloud account

Local development lives in `~/Project_Provenance`. First-time setup and staying in sync are covered in
[docs/RUNNING_ON_GEMINI.md](docs/RUNNING_ON_GEMINI.md) (sections A and H).

```bash
cd ~/Project_Provenance
make setup        # uv sync --extra gcp, and creates .env
make dev          # open http://localhost:8080
```

`make help` lists every shortcut (`test`, `dev-gemini`, `smoke`, `eval`, `deploy-offline`, `deploy-gemini`, …).

Press **Run the reversal**. The hero alert runs three ways through the full ADK agent graph:
the archived list with a naive fetch-date clock auto-closes it, the publisher-date clock escalates
it as stale, and the live list escalates it on a sanctions hit. By default this runs in
`PROVENANCE_MODE=offline`: scripted stand-in models on the fictional demo bundle in `demo/`,
labelled as such in the console. For real Gemini, follow **[docs/RUNNING_ON_GEMINI.md](docs/RUNNING_ON_GEMINI.md)**
(setup, a 7-check smoke test `python -m provenance.smoke`, deploy, troubleshooting). In short:

```bash
export GOOGLE_GENAI_USE_VERTEXAI=TRUE GOOGLE_CLOUD_PROJECT=... GOOGLE_CLOUD_LOCATION=global   # model location
export PROVENANCE_MODEL_FLASH=... PROVENANCE_MODEL_PRO=...     # pinned IDs
PROVENANCE_MODE=gemini uv run uvicorn provenance.service.app:app --port 8080
```

Also in the console:
- **Run nightly sweep** re-screens every auto-closed case against today's list. It reopens the naively
  closed hero case and re-runs it, and the re-run escalates.
- **Probe the verifier** adds one uncited sentence to a finished case's narrative, in plain view, and shows the
  deterministic verifier rejecting it. The case's decision is unchanged and the probe is recorded separately.
- **Analyst review** confirms or overrides a decision. The verdict becomes the eval label.
- **"Web result with a prompt injection"** shows the injection guard withholding an instruction-shaped
  web result and escalating the case.
- **Evaluation** (`/eval.html`): every arm side by side, the staleness lift and a calibration chart.
  Populate it with `uv run python -m provenance.eval.arms --all`.

One alert from the CLI: `uv run python -m provenance.service.run alt_demo_hero --snapshot archived`.
Tests: `uv run pytest` (68 tests: core guarantees, data tools, the full graph end to end, sweep, review, injection guard, the API).

## Deploy

```bash
MODE=offline ./deploy/deploy.sh    # public Cloud Run URL, zero model spend
MODE=gemini  ./deploy/deploy.sh    # real Gemini; cases in Firestore
firebase deploy --only hosting     # optional: console on Firebase Hosting, /api/** rewritten to Cloud Run
```

## Data and baseline runbook (Sep 27–28)

Copy `.env.example` to `.env`, fill it in, and `uv sync --extra gcp`. Then:

```bash
# 1. SAML-D: download the Kaggle CSV to data/raw/ (not committed), sample it, load it into BigQuery
uv run python -m provenance.data.saml_d sample --input data/raw/SAML-D.csv
uv run python -m provenance.data.saml_d upload

# 2. Alerts: tune rules to a 95-97% FP rate, pick 300, split into golden/eval/demo, load them
uv run python -m provenance.data.alerts --upload          # read artifacts/tuning_report.json

# 3. OFAC: archived snapshot from the Wayback Machine plus the live list, validated and staged in GCS
uv run python -m provenance.data.ofac fetch --archived 20250301 --live --live-as-of 2026-09-25 --upload

# 4. Baselines: A0 (arithmetic) and A1 (ungrounded Gemini) on the golden set
uv run python -m provenance.eval.baselines --arm A0 --split golden --upload
uv run python -m provenance.eval.baselines --arm A1 --split golden --upload
```

Every step also runs offline without `--upload`. The OFAC URLs could not be tested from the build
container, so check them on the first run.

## Day 0 essentials

Full checklist in `PLAN.md`. The two that bite hardest:

1. **Pin an explicit Gemini 3.x model ID.** The 2.5 series retires around **Oct 16** — inside our
   judging window. A deployed app that 404s while a judge is looking at it scores zero on the
   criterion worth 40%.
2. **Set billing alerts at 50% and 80% of credits.** The burn runs four weeks, not two, and
   `--min-instances 1` left on for a month is real money.

Employer IP review is complete and cleared.
