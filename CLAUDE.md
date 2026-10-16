# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Provenance is an AML alert-triage agent built for the AI Builder Cup 2026 (submission deadline Oct 18 2026). The agent can't
make an assertion it can't cite, and it escalates when its evidence goes stale. The hero demo is the "reversal": one
alert run against an archived OFAC snapshot auto-closes it (wrongly), and run against the live list it escalates.
`STRATEGY.md` (win thesis, kill list, demo script) and `PLAN.md` (full architecture and schedule) are the design docs.
`SUBMISSION.md`, `TEAM.md`, and `submission/` hold the submission pack (form fields, deck generator, video script).
Everything in `demo/` is fictional.

## Commands

Python ≥3.11, managed with `uv`. `make help` lists all targets.

```bash
make setup                 # uv sync --extra gcp; creates .env from .env.example
make test                  # uv run pytest (fully offline, no cloud)
uv run pytest tests/test_verifier.py::test_fully_cited_narrative_passes -q    # single test
make dev                   # console at http://localhost:8080 on scripted models + demo bundle
make dev-gemini            # same on real Gemini (loads .env)
make smoke                 # 7-check first-run test for Gemini: python -m provenance.smoke [--only N]
make eval / eval-gemini    # all eval arms over the demo split
uv run python -m provenance.service.run alt_demo_hero --snapshot archived [--basis retrieved_at]   # one alert from the CLI
MODE=offline|gemini ./deploy/deploy.sh                 # Cloud Run (make deploy-offline / deploy-gemini)
python submission/deck/build_deck.py --template <pptx> --leader "Name"   # deck; stdlib only
```

There is no linter config. The Makefile's `LOAD_ENV` sources `.env` only for the targets that talk to the cloud.

## Runtime switches (`provenance/runtime.py`)

Three independent env vars. Any combination works:

- `PROVENANCE_MODE`: `offline` swaps every LLM for a scripted stand-in (`agents/provenance_agent/offline.py`). Tests, CI,
  and the fallback demo use it. Offline numbers test the plumbing only and must never be reported as results. `gemini`
  uses real Gemini through ADK.
- `PROVENANCE_DATA`: `bundle` (the committed `demo/` with `manifest.json`, alerts, customers, transactions, and two SDN
  snapshots) or `gcp` (BigQuery, GCS, Firestore).
- `PROVENANCE_STORE`: `memory` (`stores/memory.py` FakeFirestore, single instance only) or `firestore`.

The Gemini backend is either Vertex (`GOOGLE_GENAI_USE_VERTEXAI=TRUE`) or an AI Studio key (`config.backend()`).
`PROVENANCE_MODEL_FLASH`/`_PRO` must be pinned IDs: `config.model()` rejects `-latest` aliases.

## Architecture

**The core rule:** LLMs propose and deterministic code decides. `provenance/core/` must never import Google Cloud. It holds
everything that determines whether a case can auto-close, so it can be unit-tested and audited line by line. The `gcp`
extra is optional, and only the core plus pydantic is required.

- `core/models.py`: `Claim` carries two timestamps. `source_as_of` is when the publisher says the fact was true, and
  `retrieved_at` is when we fetched it. The whole thesis depends on keeping these two apart.
- `core/ledger.py`: the append-only claim ledger (`LedgerStore` protocol; Firestore `cases/{id}/claims/{claimId}`).
  Claim IDs are content hashes, and reusing an ID for different content raises `LedgerConflictError`.
- `core/verifier.py`: a regex parser, not an LLM judge. Every narrative sentence needs a `[clm_xxxxxxxxxx]` citation that
  resolves in the ledger, or the draft is rejected.
- `core/staleness.py`: per-evidence-type freshness SLAs measured on `source_as_of`. The `retrieved_at` basis is the "naive
  RAG" arm.
- `core/policy_gate.py`: six-condition auto-close gate (confidence ≥ θ=0.90, mandatory evidence present, zero staleness,
  citation coverage 1.0, no sanctions/PEP hit, typology/rule not in the never-auto-close sets). It evaluates and reports
  every condition, even after one fails, because the console shows all six. `core/typologies.py` maps typology to
  mandatory evidence.
- `core/decide.py` combines verify + staleness + gate. `core/sar.py` drafts a cited SAR on escalation. `core/sweep.py`
  re-screens auto-closed cases. `core/guard.py` is a regex prompt-injection screen on web results. Withheld content
  forces escalation. Model Armor (`sources/guard_modelarmor.py`) runs after it when configured.

**Agent graph** (`agents/provenance_agent/agent.py` has the diagram; google-adk): a SequentialAgent that runs case_init →
typologist (Flash) → evidence_planner (code) → ParallelAgent evidence (txn_analyst, watchlist_analyst, a deterministic
KYC reader, media wrapper) → LoopAgent disposition (Pro, max 3 drafts) + verify_and_gate → finalize.

- `steps.py` holds the deterministic BaseAgents. `tools.py` holds function tools, and **the tools write claims
  themselves**: the model chooses what to look up but never authors a claim. `query_transactions` uses only named
  templates (`tools/bq_templates.py`) and refuses accounts outside the alert's scope.
- `App(name=...)` must match the directory name `provenance_agent`, or ADK fails with "Session not found".
- Adverse media is an LlmAgent whose only tool is `google_search`. `steps.AdverseMedia` converts its
  `grounding_metadata` into verbatim claims, and an offline test pins that contract.

**Around it:** `service/app.py` (FastAPI, the console in `console/`, a JSON API, cases run in background tasks; Cloud Run
needs `--no-cpu-throttling`), `service/run.py` (single-alert runner), `service/sweep.py` (nightly sweep that reopens
cases with a `reopens` link). `stores/firestore.py` is `CaseRepository` with an injected client. `eval/` holds arms
A0/A1 (`baselines.py`) and A3/A4-naive/A4 (`arms.py`, resumable jsonl under `artifacts/eval/`; see `eval/ARMS.md`).
`data/` covers SAML-D sampling, alert tuning/splitting, and OFAC snapshot fetching. `rules/engine.py` generates labelled
alerts.

## Conventions

- Cloud imports inside non-core modules are lazy (function-local, `# noqa: PLC0415`), so offline paths and tests never
  need credentials. Keep them that way.
- Tests use `tests/fixtures/` SDN snapshots and `tests/saml_d_fixture.py`, and run the full graph end to end in offline
  mode. Any change to the core guarantees (verifier, gate, staleness, ledger) needs a test there.
- The deck's numbers live in `submission/deck/numbers.json` and its words in `content.py`. Keep claims in the
  docs, deck, and video script consistent with each other and with real Gemini results.
