# Provenance — AI Builder Cup 2026 build plan

## Context

Syed Iqbal Nasim is registered for the Google Cloud **AI Builder Cup 2026**. Six problem statements are open; a team of 2–4 must build and deploy a *functional* AI solution on GCP (Cloud Run or Firebase) using Google AI models or an agentic platform. $30K prize pool; Grand Finale in Singapore, Dec 4 2026.

This plan fixes the three decisions that gate everything else — problem statement, concept, team identity — and lays out a 27-day build in four phases, ending at the confirmed **Oct 18** submission deadline.

**Why these choices.** The team lead brings 19 years' experience, over a decade of it building payroll, money-movement and ERP systems at scale, with a current focus on agentic AI. The genuine differentiators are grounding architecture, evaluation harnesses, guardrails, and human-in-the-loop governance — not front-end polish or ML modelling. The identity line is *"We make agentic AI trustworthy enough to run money."* The plan is built to make that sentence literally demonstrable on camera.

The one material gap: **limited Google Cloud experience** (the team's cloud background is mostly AWS). The schedule front-loads GCP setup and assigns the team lead architecture, evals, and narrative rather than implementation.

---

## Decisions locked

| | |
|---|---|
| **Problem statement** | BFSI — intelligent risk, fraud, and financial experiences |
| **Team + product name** | **Provenance** |
| **One-liner** | An AML triage agent that can't say anything it can't cite — and escalates the moment its evidence goes stale. |
| **Team** | 3–4, all working professionals aged 21+ (a single student disqualifies the team) |
| **Deadline** | **Sun Oct 18 2026, confirmed.** Submit Fri Oct 16 — never on deadline day |
| **Cleared** | Employer IP reviewed and approved; build proceeds |

**Why BFSI over the alternatives.** It's the only track where a decade of fintech lets us say things a judge can tell we didn't learn from a blog post. *Future of work / enterprise productivity* was the tempting wrong answer — it overlaps the team's day-job product surface, which is precisely why it's off-limits.

**Judging weights (published):** technical merit & GenAI implementation **40%**, problem alignment & impact 25%, innovation & creativity 25%, UX & solution design **10%**. The grounding architecture and eval harness are worth 40 points. Budget effort accordingly — the console matters mainly as the lens through which judges perceive the 40%.

**Deliverables:** deployed prototype URL, public GitHub repo, sub-3-minute video, deck.

---

## The pitch

A bank's transaction-monitoring system fires alerts at a 95–98% false-positive rate. An L1 analyst reads every one, ~25 minutes each. Provenance ingests an alert, infers its typology, builds an **evidence plan**, dispatches parallel specialist agents (transactions, KYC documents, sanctions lists, live adverse media, counterparty graph), and writes every finding to an immutable **claim ledger** carrying source URI, verbatim quote, and two timestamps. A deterministic verifier then rejects the agent's own draft disposition if any assertion lacks a resolvable claim ID. Auto-close requires clearing a six-condition gate; otherwise the case escalates with a pre-built file and a SAR draft.

**The demo moment — this is what makes it un-copyable.** Run the same alert against an **archived** OFAC snapshot and against **today's**. With stale grounding the agent confidently auto-closes: fluent, well-structured, wrong. Flip to live lists — the customer was designated after the archive date — the staleness auditor fires, confidence collapses, the case escalates. Real public data, ~25 seconds of video, and it proves the thesis rather than asserting it.

Do **not** pitch "AI triages alerts" — that reads as a wrapper and kills the 25% innovation score. Pitch the **evidence contract**: a system structurally incapable of emitting an uncited assertion.

---

## Architecture

```
Cloud Scheduler ──► Pub/Sub (alerts) ──┐
                                       ▼
Firebase Hosting            ┌──────────────────────────────┐
  analyst console ──HTTPS──►│ Cloud Run: provenance-agent  │
  (Firestore realtime       │ ADK FastAPI app              │
   listeners)               └───┬──────────────────────────┘
        ▲                       ├─► Gemini on Vertex / Agent Platform
        │ realtime              ├─► google_search grounding (isolated sub-agent)
   ┌────┴─────┐                 ├─► BigQuery (txns, alerts, eval results)
   │ Firestore│◄────────────────┤   Cloud Storage (KYC PDFs, list snapshots)
   │ cases +  │                 ├─► Secret Manager
   │ claims   │                 └─► Cloud Trace / Logging (auto via ADK)
   └──────────┘
```

Two deployment surfaces, both satisfying the requirement: **Cloud Run** for the agent, **Firebase Hosting + Firestore** for the console. Say both aloud in the video.

**Framework: ADK (Agent Development Kit), not LangGraph.** LangGraph experience makes it a one-day translation, the judging criterion names agentic platforms explicitly, and `agents-cli` scaffolds Terraform, Dockerfile, CI/CD **and an eval harness** — three GCP gaps closed by one command. Use the classic composites (`SequentialAgent`, `ParallelAgent`, `LoopAgent`) rather than the newer graph `Workflow` API; lower risk under time pressure.

**Deploy to Cloud Run, not Agent Runtime.** Principled, not preference: Agent Runtime does not support Pub/Sub, Eventarc, or Cloud Scheduler triggers, and the nightly staleness sweep needs them. ADK gives trigger endpoints via `get_fast_api_app(trigger_sources=["pubsub", "eventarc"])`.

**Models — verify IDs on day 0, then pin them.** Do not trust remembered model names; 2026 naming churned. Run `client.models.list()` (see checklist) and pin explicit versions — `gemini-flash-latest` style aliases will silently invalidate eval arms mid-competition. Allocation: Pro model for disposition + SAR narrative; Flash for evidence extraction, KYC reading, typology classification; Flash-Lite for dedup. Avoid the 2.5 series — retirement dates land around Oct 16 2026.

**Google Search grounding — the gotcha that costs half a day.** ADK's `google_search` is model-internal grounding, not a function tool, and **mixing it with FunctionTools in the same agent disables Automatic Function Calling for all of them**. The adverse-media agent must be an isolated sub-agent invoked via `AgentTool`, no other tools attached. Clone the `deep-search` sample from `google/adk-samples` on day 0. The response's `groundingMetadata` (`groundingChunks` URIs, `groundingSupports` text spans with confidence) **is** the citation trail — persist it verbatim, don't invent a format.

**State split.** Firestore (Native mode) is the system of record for cases, claims, and analyst decisions — chosen specifically because realtime snapshot listeners give the "watch the agent think" console with no websockets. BigQuery holds transactions, alerts, and all eval results (partition by date, cluster by account ID or credits burn). Cloud Storage holds KYC PDFs and list snapshots. **Skip Cloud SQL** (`--session-type in_memory`) and **skip Document AI** — mention Document AI in the deck as the production path for page-level provenance.

**Guardrails: Model Armor.** Adverse media is untrusted web content flowing into an agent that takes consequential actions — textbook indirect prompt injection. The `safety-plugins` ADK sample has a ready `model_armor.py`. Thirty seconds on the threat model in the video is a disproportionate technical-merit signal.

### Where an AWS mental model will mislead

| Assumption (AWS) | Reality (GCP) |
|---|---|
| Services are just there | **APIs must be enabled per project** — `gcloud services enable …`. The #1 day-0 stumble. |
| Assume roles, instance profiles | **Service accounts are identities.** Cloud Run *runs as* one. No `sts:AssumeRole`. |
| Env/metadata credentials | **Application Default Credentials** — `gcloud auth application-default login`, or everything 403s with a misleading message. |
| Lambda | **Cloud Run ≈ Fargate**, listens on `$PORT`. Agent turns are long — raise request timeout or the agent is killed mid-reasoning. |
| DynamoDB | **Firestore** — no GSIs; composite indexes are declared, and the error hands you the creation link. |
| Athena/Redshift | **BigQuery** bills per byte scanned. `SELECT *` inside an agent loop is how credits vanish. |
| X-Ray / CloudWatch / ECR / CFN | Cloud Trace / Cloud Logging / Artifact Registry / Terraform |
| Region is wherever | **`us-central1`.** `asia-south1` is closer but model availability lags. |
| Quota is generous | **Per-project, per-region QPM limits on Gemini; credits do not raise quota.** Request an increase day 0; build in backoff. Five eval arms × 300 alerts will hit it. |

---

## Agent decomposition

The honest test of "is this agentic": would one prompt with all the data pasted in do the job? No, for four reasons, each mapping to a component — the evidence needed isn't known in advance (it depends on an inferred typology); gathering is heterogeneous and parallel; the system must decide whether it has *enough*; and the correct output is sometimes "a human takes this."

| # | Component | Type | Owns |
|---|---|---|---|
| 1 | Typologist | LlmAgent (Flash), `output_schema` | Classifies typology (structuring / rapid movement / high-risk corridor / sanctions nexus / mule funnel / round-tripping); emits typed **evidence plan** with *mandatory* evidence types |
| 2 | txn_analyst | LlmAgent + FunctionTool | BigQuery history via **parameterized query templates, never free-form SQL**; returns facts + query fingerprint |
| 3 | kyc_analyst | LlmAgent (multimodal) | Reads KYC PDFs from GCS — stated occupation, expected activity, source of funds — with page + verbatim quote |
| 4 | watchlist_analyst | FunctionTool + LlmAgent | OFAC / OpenSanctions match, returning **list version and as-of timestamp** with the hit |
| 5 | adverse_media_analyst | **Isolated** LlmAgent with `google_search`, wrapped as `AgentTool` | Live web claims + grounding chunk URIs and support spans |
| 6 | network_analyst | FunctionTool (BQ self-join + NetworkX) | 2-hop counterparty graph, shared address/device edges, cycle detection |
| 7 | Ledger writer | **Deterministic Python** | Writes claims to Firestore. Not an LLM — auditability demands determinism |
| 8 | Staleness auditor | Deterministic + LLM | Per-source freshness SLA; emits staleness penalty + stale claim list |
| 9 | Disposition agent | LlmAgent (Pro), `output_schema` | Disposition + calibrated confidence + rationale where every sentence carries claim IDs |
| 10 | Citation verifier | **Deterministic Python** | Parses the narrative; **rejects the agent's own draft** if any assertion lacks a resolvable claim ID → LoopAgent retries (max 2) → escalate |
| 11 | Policy gate | Deterministic Python | The auto-close decision (below) |
| 12 | SAR drafter | LlmAgent (Pro) | Escalation only. 5-W narrative, watermarked DRAFT, fully cited, never auto-filed |
| 13 | HITL node | `RequestInput` + `ResumabilityConfig(is_resumable=True)` | Analyst approve/override; decision written back as a new eval label |
| 14 | Staleness sweep | Cloud Scheduler → Pub/Sub → `/trigger/pubsub` | Nightly re-check of auto-closed cases; **reopens** any whose evidentiary basis changed |

Two components are the difference between a demo and a system:

**The citation verifier is deterministic and rejects the model.** Not an LLM judging an LLM — a parser that fails the draft. That makes "100% citation coverage" a structural guarantee, not a measured average. Judges who've seen fifty LLM-grades-LLM demos will notice.

**The policy gate encodes "escalation is a designed success path":**

```
auto_close  IFF  confidence ≥ θ
             AND all mandatory evidence types for this typology PRESENT
             AND staleness_penalty == 0
             AND citation_coverage == 1.0
             AND no sanctions/PEP hit at any confidence
             AND typology ∉ NEVER_AUTO_CLOSE
else escalate_with_case_file
```

Six conditions, five deterministic, one a model score. That's one slide, and it's what "trustworthy enough to run money" looks like in code.

### The claim ledger (Firestore) — the heart of the data model

```
cases/{caseId}
  ├─ typology, evidence_plan{required[], gathered[]}
  ├─ disposition, confidence, policy_gate{conditions[], passed}
  ├─ staleness{penalty, stale_claims[]}
  ├─ trace_id                    ← joins to Cloud Trace
  ├─ claims/{claimId}            ← THE LEDGER
  │    ├─ assertion              "Counterparty ACME received 14 transfers of ₹4.8L over 9 days"
  │    ├─ source_type            bigquery | kyc_doc | sanctions_list | web_search | graph
  │    ├─ source_uri             bq://…?fingerprint=… | gs://…/kyc_8821.pdf#page=3 | https://…
  │    ├─ source_as_of           2026-09-19T00:00Z   ← publisher's own timestamp
  │    ├─ retrieved_at           2026-10-02T14:22Z   ← when WE fetched it
  │    ├─ freshness_sla_days     1 | 30 | 365
  │    ├─ is_stale               derived
  │    ├─ extraction_method      sql_template_v3 | gemini_multimodal | grounding_support
  │    ├─ support_span           {startIndex, endIndex, chunkIndices[], confidence}
  │    ├─ verbatim_quote
  │    └─ produced_by_agent
  ├─ narrative/{version}         text + citation_map{sentence_idx → [claim_id]}
  └─ human_decisions/{id}
```

**`source_as_of` vs `retrieved_at` carry the entire thesis.** Almost every RAG system records only the second. Recording both, and enforcing an SLA between them, *is* the staleness defence. Point at those two fields on camera. Mirror the ledger to BigQuery for eval.

---

## Data — a credible labeled corpus in two days

No bank data needed: **synthetic transactions + real watchlists + real adverse media**, plus labeled *alerts*, which is a different thing from labeled transactions.

| Layer | Source | Notes |
|---|---|---|
| Transactions (primary) | **SAML-D** (Kaggle, `berkanoztas/synthetic-transaction-monitoring-dataset-aml`) | 9.5M txns, **28 typologies**, 0.1039% suspicious. The typology labels justify the evidence-plan branch and enable stratified eval. Sample it down. |
| Transactions (secondary) | **IBM Transactions for AML** (Kaggle `ealtman2019/…`, mirror `github.com/IBM/AML-Data`) | Use **HI-Small**. Labels laundering many hops from the illicit source — good for network_analyst. |
| Sanctions / PEP | **OFAC SDN** (`sanctionslist.ofac.treas.gov`, daily, US public domain) primary; OpenSanctions enrichment | **Take two snapshots — archived and today's.** This is the staleness demo. |
| Adverse media (live) | **Google Search grounding** | Don't scrape news; live grounding *is* the Google tech being judged. |
| Adverse media (reproducible) | DOJ press releases, SEC litigation releases | Real, citable, stable text for offline eval so numbers reproduce. |
| KYC documents | **Generate with Gemini** | 50 onboarding profiles as PDFs, deliberately consistent or inconsistent with transaction behaviour. **Watermark every page "SYNTHETIC — generated for demonstration."** |

**The move that makes the eval real: generate the alerts yourself.** Write a deterministic rule engine (structuring below threshold, velocity spikes, round numbers, high-risk corridors, rapid in-and-out, dormant-then-active), run it over the transactions, and take ground truth from the underlying laundering labels. **Tune thresholds until the false-positive rate lands at 95–97%.** One day's work, and it buys the sentence *"we reproduced the industry's 95% false-positive rate with a standard rule engine, then measured what our agent does to it"* — which separates this from every team quoting a McKinsey statistic.

**Persona linkage — do not skip.** Join ~10 synthetic customers to **real** OFAC/OpenSanctions entity names and ~10 to real DOJ/SEC enforcement subjects, or Google Search grounding returns nothing and the adverse-media agent is theatre. **Pick the hero persona specifically as someone designated *after* the archived snapshot date.**

**Corpus: 300 alerts** stratified across 6 typologies at ~95% FP — 40 hand-reviewed golden cases, 200 for eval arms, 60 held out for live demo.

---

## Eval harness — this is the 40%

The signature move (measure the ungrounded baseline *first*) happens **on day 3, before any agent code exists.** Non-negotiable ordering.

| Arm | What | Proves |
|---|---|---|
| **A0** | Rules only, everything to a human | Status quo cost baseline |
| **A1** | **Ungrounded single Gemini call** — alert JSON in, disposition out, no tools | What "just add an LLM" produces. This is what competitors will ship |
| **A2** | Grounded evidence agents + citations, auto-close on confidence alone | Isolates grounding value from governance value |
| **A3** | **Full system** — A2 + citation verifier + staleness auditor + policy gate + HITL | The product |
| **A4** | **A3 on an 18-month-stale snapshot** | The thesis |

A1→A3 is the grounding lift. A2→A3 is the governance lift. **A3→A4 is the staleness lift, and nobody else will have it.**

**Metrics.** (1) **False-negative rate on auto-close** — true positives closed without a human. *The only metric that gets a bank fined. Target zero, and lead with it.* (2) Auto-close rate (realistic 40–60%). (3) Analyst-hours saved = rate × N × 25 min, converted to money. (4) **Citation coverage** — A1 ≈ 0–20%, A3 = 100% by construction. (5) Citation fidelity — LLM judge confirms the source actually supports the claim; guards against citation theatre. (6) **Hallucinated-entity rate** — set-difference against the ledger; deterministic, and A1 fails it visibly. (7) **Confidence calibration (ECE)** — one afternoon, and almost no hackathon shows a calibration curve. (8) Staleness-induced error rate, A3 vs A4. (9) Escalation precision — proves escalation isn't a cop-out. (10) $/alert and p50/p95 latency. Plus ADK built-ins (`multi_turn_tool_use_quality`, `hallucination`, `safety`).

**Mechanics.** `agents-cli eval generate` → `eval grade` → **`eval compare`** (a built-in baseline-vs-candidate diff — run it on camera) → `eval analyze --top-k 5`. Custom metrics go in `tests/eval/eval_config.yaml` as `custom_function` entries (deterministic ones) and `prompt_template` (citation fidelity). Two gotchas: **`App(name=…)` must match the agent directory name** or eval fails with "Session not found"; and models with thinking enabled may skip tool calls — use `tool_config` with `mode="ANY"` where deterministic trajectories matter.

**Demo rule: live = one alert, precomputed = the population.** Never run a 300-alert eval on stage. Precompute all arms into BigQuery; the console's `/eval` page renders the comparison table, calibration curve, and A3-vs-A4 delta. Run exactly one alert end-to-end live.

---

## Schedule — 27 days, four phases

Deadline confirmed: **Sun Oct 18 2026.** Submit **Fri Oct 16** — two days of margin against portal problems, and never on deadline day.

The extra fortnight is not open runway, it's a second build phase with a **pre-committed scope list and its own freeze**. At 27 days alongside a day job the dominant risk stops being "can we finish" and becomes scope creep; the Oct 12 hard freeze is what prevents it. Every day still has a **gate** — a binary, checkable thing.

### Phase 1 — foundations and baselines (Sep 21–27)

| Day | Date | Work | Gate |
|---|---|---|---|
| 0 | Mon Sep 21 | GCP project + credits, `gcloud services enable`, ADC login, `agents-cli setup`. **Run the model listing and pin a 3.x ID.** **Set billing alerts at 50% and 80% of credits.** Scaffold. Clone `deep-search` + `safety-plugins`. Request Gemini quota increase. | ADK agent answers locally on Vertex with a pinned model |
| 1 | Tue Sep 22 | SAML-D + IBM AML into BigQuery (partitioned, clustered). Rule engine. 300 labeled alerts. | `alerts` table with labels and a **measured** FP rate ~95% |
| 2 | Wed Sep 23 | OFAC + OpenSanctions, two snapshots into GCS. Link 20 personas to real entities. 50 watermarked KYC PDFs via Gemini. | A query joining an alert to a watchlist hit; hero persona designated after the archive date |
| 3 | Thu Sep 24 | **BASELINES FIRST.** A0 + A1. 40-case golden dataset. `eval generate` + `eval grade`. | Ungrounded citation coverage ≈ 0 and hallucinated entities > 0. **Screenshot it — this opens the video** |
| 4 | Fri Sep 25 | Typologist + evidence-plan schema + Firestore model + deterministic ledger writer | One alert → typed evidence plan + empty ledger in Firestore |
| 5 | Sat Sep 26 | All four evidence agents. **Budget the whole afternoon for the `google_search`/AFC isolation gotcha.** | A claim whose `source_uri` is a real news URL from `groundingChunks` |
| 6 | **Sun Sep 27** | **DEPLOY DAY — HARD GATE.** Disposition agent + citation verifier + policy gate v1. `agents-cli deploy` to Cloud Run. Console skeleton on Firebase Hosting. | **A public URL: paste an alert ID, get a cited disposition.** Slips past Sep 29 → start cutting |

### Phase 2 — the core system, submittable (Sep 28 – Oct 4)

| Day | Date | Work | Gate |
|---|---|---|---|
| 7 | Mon Sep 28 | Staleness auditor + archived/live toggle + SAR drafter | Stale-vs-fresh divergence reproduces on ≥3 alerts including the hero persona |
| 8 | Tue Sep 29 | Eval harness proper. Custom metrics. Run A2, A3. `eval compare` vs A1. | A real lift table with real numbers |
| 9 | Wed Sep 30 | Fix what eval exposed. Expect 5–10 generate→grade→analyze→fix cycles. | **Zero true-positive auto-closes on the golden set** |
| 10 | Thu Oct 1 | HITL loop, Model Armor on adverse-media results, console polish, Cloud Trace capture | Analyst can override a disposition and it persists |
| 11 | Fri Oct 2 | Run A4. All five arms into BigQuery. `/eval` dashboard page. | Five-arm table renders in the deployed console |
| 12 | Sat Oct 3 | Rough-cut video, draft README + architecture doc | A 3-minute cut exists, however ugly |
| 13 | **Sun Oct 4** | Tidy the public repo, commit eval artifacts | **Phase gate: a complete entry you would be content to submit today** |

**Oct 4 is the insurance milestone.** Everything after it is upside — if weeks 3 and 4 go badly you still have a strong entry. **Check whether the portal allows updating a submission after filing; if it does, file on Oct 4 and update later.**

### Phase 3 — depth (Oct 5–11)

Pre-committed scope, in priority order. **Anything not on this list does not get built.**

1. **Staleness sweep** — Cloud Scheduler → Pub/Sub, nightly re-check that *reopens* auto-closed cases whose evidentiary basis changed. Was kill-list item #1; it's the strongest story left on the table, and it closes the loop on the thesis.
2. **More eval iteration.** Cycles of generate→grade→analyze→fix are where the 40% actually lives. Target 15+ cycles, not 5. This outranks every remaining feature.
3. **Corpus 300 → 1,000 alerts**, six typologies fully stratified; golden set 40 → 100. Bigger n, tighter confidence intervals, more credible numbers.
4. **network_analyst** — 2-hop counterparty graph, shared-address/device edges, cycle detection. Plays directly to the knowledge-graph credibility.
5. **SME review session** (3–4 hrs) — validate typologies and SAR narrative structure. Highest leverage per hour on the team.
6. **Cost and latency benchmark** at 1,000 alerts → real $/alert and p95. Judges love unit economics.
7. **CI/CD** via `agents-cli infra cicd`.

**Phase gate, Sun Oct 11:** all five arms re-run at 1,000 alerts, numbers stable, staleness sweep demonstrably reopening a case.

### Phase 4 — production (Oct 12–18)

- **Mon Oct 12 — HARD FEATURE FREEZE.** No new code. Bug fixes only, and only ones that break a gate.
- **Oct 12–14 — the video.** Script, storyboard, 8+ takes, real edit. A well-produced three minutes outscores any remaining feature; this is the artifact most judges actually experience.
- **Oct 13–15 — deck** (eval table on slide 2), README, architecture doc, repo judge-proofing.
- **Thu Oct 15 — dress rehearsal.** Clone the public repo into a **fresh GCP project** and run it end to end. Proves reproducibility and catches "works on my machine" before a judge does.
- **Fri Oct 16 — submit.**
- **Oct 17–18 — hold.** Fix only what is broken. Turn `--min-instances 1` back on for the judging window.

### The 3-minute video, shot by shot

- **0:00–0:25** — The queue. One number: *97 of 100 alerts are noise; 25 minutes each; this bank runs 4,000 a month.*
- **0:25–0:45** — A1 disposing an alert. Fluent, confident, zero citations, one hallucinated counterparty circled in red. *"This is what 'just add an LLM' does to a regulated process."*
- **0:45–1:45** — Provenance live: typology → evidence plan → agents in parallel → ledger filling with cited claims → **the verifier rejecting the agent's own first draft** → policy gate → auto-close at 100% coverage. Three seconds of the Cloud Trace span waterfall.
- **1:45–2:15** — **The reversal.** Stale snapshot: confident auto-close. Flip to live OFAC: designated in 2025 → staleness auditor fires → escalates with case file and SAR draft. Say the line.
- **2:15–2:40** — Five-arm table. Zero true-positive auto-closes. X% auto-close. Y analyst-hours. Calibration curve.
- **2:40–3:00** — Architecture card: Gemini on Agent Platform, ADK, Cloud Run, Firebase, BigQuery, Firestore, Cloud Trace, Model Armor. Close on *"I make agentic AI trustworthy enough to run money."*

---

## Team roles (3–4 set)

Map people to these; every role has a named owner by end of day 0.

- **Iqbal — architect, eval owner, narrative.** The agent graph, claim-ledger schema, policy gate, eval design, data/labeling strategy, demo script, deck, video VO. Owns the 40% and the 25% innovation. **Should not be writing the React.**
- **Cloud/data engineer.** BigQuery loading and tuning, Terraform/IAM, Cloud Run deploy, Secret Manager, Pub/Sub, quota firefighting. Absorbs the highest volume of non-differentiated work and deletes the largest risk.
- **Frontend/Firebase engineer.** Analyst console, Firestore realtime listeners, evidence-ledger view, `/eval` dashboard, stale/live toggle. Makes the agent's reasoning *visible*, which is how judges perceive the 40%.
- **Fourth seat — agent/backend engineer** (if available), owning evidence agents 2–6 and the grounding integration. If the fourth seat is instead an **AML/financial-crime SME** at 3–4 hours total, that's the highest leverage per hour on the team: validates typologies, sanity-checks the SAR structure, and de-risks "this domain is invented."

**Rhythm:** all-IST is an advantage. 30-minute standup at 22:00 IST daily, shared board with the day-gates above, and one rule — **if a gate slips two days, something comes off the kill list that evening, not next week.**

---

## Kill list (Phases 1–2 only — cut from the top when behind)

1. Cloud Scheduler staleness sweep → describe it in the deck
2. network_analyst
3. CI/CD pipeline — deploy by hand
4. Arm A2 — A1→A3→A4 carries the whole story
5. SAR drafter → templated summary
6. Six typologies → three

**Never cut, at any cost:** the citation verifier, the policy gate, the staleness toggle, the five-arm comparison table, the deployed public URL. Those five *are* the submission.

Items 1 and 2 come back as Phase 3 work — cutting them in week 2 costs nothing now that the deadline is Oct 18.

---

## Risks

1. **The Gemini 2.5 retirement date now sits inside the competition window.** Retirements land around **Oct 16 2026** — which, under the old assumed Oct 4 deadline, was harmless, and under the real Oct 18 deadline is not. Judges may open the deployed app *after* that date. **Pin an explicit 3.x model ID on day 0** and grep the whole repo for any 2.5 reference before the Oct 15 dress rehearsal. A submission whose live URL 404s during judging scores zero on the thing worth 40%.
2. **Scope creep across 27 days.** With the pressure off, the failure mode inverts: the team keeps building instead of polishing. Mitigate with the closed Phase 3 list, the **absolute Oct 12 freeze**, and the Oct 4 submittable milestone that makes everything after it optional. If someone proposes a feature in week 4, the answer is no regardless of merit.
3. **Credits and burn over four weeks, not two.** `--min-instances 1` for 27 days is real money — turn it on only for recording and the judging window. Untuned BigQuery scans inside an agent loop are the other drain. **Set billing alerts at 50% and 80% of credits on day 0**, and check spend at every phase gate.
4. **GCP learning curve eats days 1–3.** Mitigate with scaffold-first (`agents-cli` writes the Terraform, Dockerfile, CI), the cloud engineer carrying IAM and deployment, and front-loading all tedium on day 0. Hard rule: not on Cloud Run by Sep 29 → start cutting.
5. **Demo fragility.** Grounding is non-deterministic and network-dependent; quota returns 429s under eval load; Cloud Run cold-starts. Mitigate with `--min-instances 1` before recording, a cached-evidence mode behind a feature flag, never running eval live, exponential backoff, and a known-good take held in reserve.
6. **"It's a wrapper"** — 25% of the score and the default perception of any LLM-reads-document demo. Mitigate by opening with the baseline *failing*, centring the staleness reversal, showing the **deterministic** verifier reject the model, and putting the eval table on slide 2. Never say "we used AI to summarize" — say "the system cannot emit an uncited assertion."
7. **Data-credibility challenge from a judge.** Answer proactively: transactions are **published research datasets**; watchlists and adverse media are **real and live**; KYC documents are synthetic and watermarked. Never imply real customer data.

**Employer IP: cleared.** The design choices that came out of that review stay anyway, because they were the better calls under time pressure regardless — fixed Pydantic schemas rather than an ontology/terminology-normalization layer, and a single service account with "production adds field-level authz" on the architecture slide rather than authorization reasoning inside the agent. Keep the build clean-roomed on personal accounts and hardware as a matter of hygiene.

---

## Verify on day 0 (in order)

- [ ] Exact Gemini model IDs in `us-central1`, and whether `-latest` aliases resolve on Vertex. **Pin a 3.x ID — 2.5 retires ~Oct 16, inside the judging window:**
  ```bash
  uv run --with google-genai python -c "from google import genai; c=genai.Client(vertexai=True, location='global'); [print(m.name) for m in c.models.list()]"
  ```
- [ ] **Billing alerts at 50% and 80% of credits** — the burn runs four weeks, not two
- [ ] Whether the portal allows **updating a submission after filing**. If yes, file the Oct 4 build as insurance and update it on Oct 16
- [ ] Whether the chosen Pro model supports `google_search` grounding **and** thinking in `us-central1`
- [ ] Grounding pricing/quota, and whether hackathon credits cover Search grounding
- [ ] **OpenSanctions licensing** — free for non-commercial only, and a prize-bearing competition is arguably commercial. Make OFAC SDN the primary path
- [ ] Kaggle licenses on SAML-D and IBM AML before committing data to a public repo — ship a loader script if restrictive
- [ ] `agents-cli` version and whether `--bq-analytics` exists at scaffold time
- [ ] Model Armor availability and pricing in-region
- [ ] Firebase project linked to the same GCP project (easy to miss)
- [ ] Every team member is a working professional aged 21+

---

## Logo asset

Save as `brand/provenance-mark.svg`. The mark reads as a claim node grounded in three sources — a lineage tree, and at small sizes a clean abstract glyph. Ink `#101826`, amber `#D97706` (amber doubles as the alert/flag colour of the domain).

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 128 128" width="128" height="128" role="img" aria-label="Provenance">
  <circle cx="64" cy="26" r="11" fill="#D97706"/>
  <path d="M64 37 L64 66 M26 66 L102 66 M26 66 L26 90 M64 66 L64 90 M102 66 L102 90"
        stroke="#101826" stroke-width="7" fill="none" stroke-linecap="round"/>
  <circle cx="26" cy="99" r="9" fill="#FFFFFF" stroke="#101826" stroke-width="7"/>
  <circle cx="64" cy="99" r="9" fill="#FFFFFF" stroke="#101826" stroke-width="7"/>
  <circle cx="102" cy="99" r="9" fill="#FFFFFF" stroke="#101826" stroke-width="7"/>
</svg>
```

For dark backgrounds, swap `#101826` → `#F8FAFC` and the circle fills → `#101826`. Wordmark: "Provenance" in the deck's sans at weight 500, mark to the left at cap-height ×1.6.

---

## Verification — how to know it works, end to end

1. **Data layer.** `bq query` the alerts table: confirm row count ≈ 300, label distribution across 6 typologies, and a computed FP rate of 95–97%. Confirm the hero persona joins to an OFAC entry present in the live snapshot and **absent** from the archived one.
2. **Single-alert trace.** POST an alert ID to the deployed Cloud Run URL. Assert: a `cases/{id}` doc exists in Firestore; its `claims` subcollection is non-empty; every claim has a non-null `source_uri`, `source_as_of`, and `retrieved_at`; at least one claim's `source_uri` is an external news URL from `groundingChunks`.
3. **The contract holds.** Programmatically parse `narrative.citation_map` and assert every sentence index maps to ≥1 claim ID that resolves in the ledger. This assertion is the product — put it in CI.
4. **The verifier actually rejects.** Force a failure (temporarily drop a claim before the disposition step) and confirm the LoopAgent retries and then escalates rather than emitting an uncited narrative.
5. **The staleness reversal.** Run the hero alert twice, once per snapshot. Assert the disposition flips from `auto_close` to `escalate`, `staleness_penalty` goes non-zero, and the stale claim is named.
6. **Eval arms.** `agents-cli eval compare artifacts/grade_results/A1.json artifacts/grade_results/A3.json` and confirm citation coverage moves ≈0 → 1.0 and hallucinated-entity rate → 0. Separately confirm **zero** true-positive auto-closes on the 40 golden cases.
7. **Deployment proof.** Open the public Firebase URL from a device that has never authenticated, run one alert, and watch the Firestore listener stream claims in live. Capture the Cloud Trace span waterfall showing parallel evidence agents.
8. **Cold path.** Scale Cloud Run to zero, wait, then hit it — confirm the first request completes within the raised timeout rather than dying mid-reasoning.
