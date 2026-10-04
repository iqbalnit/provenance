# Provenance: how we win the AI Builder Cup

PLAN.md is the full design. This document covers how we win: what we build first, the order we build it in, what we cut, and how we present it.
If the two conflict, **this document governs the schedule and PLAN.md governs the design.**

> Status, Sun Oct 4: **live on real Gemini.** Firebase Hosting → Cloud Run (ADK agent graph) → Gemini on Vertex with Search grounding, cases in Firestore. The smoke test passes all 7 checks, and the insurance milestone is met on the day. Next: real data and real eval numbers (Oct 5–8), then the video and deck.
> We start five days behind PLAN.md. The deadline, freeze and submission dates **do not move**. Phase 1 compresses instead.

---

## 1. The win thesis

Most BFSI entries will be "an LLM reads the alert and writes a summary", and judges have seen fifty of those.
We win by showing a system that is **structurally incapable** of emitting an uncited claim, and that
**knows how old its evidence is**. Both properties are enforced in deterministic code the model cannot talk its way past.

The table maps each judging weight to what earns it and where that lives in the repo:

| Weight | What earns it | Where it lives |
|---|---|---|
| **Technical 40%** | A deterministic verifier that *rejects the model's own draft*. A six-condition policy gate. A five-arm eval with a calibration curve. Grounding metadata persisted verbatim. Model Armor on untrusted web content | `provenance/core/verifier.py`, `policy_gate.py`, `provenance/eval/metrics.py` |
| **Innovation 25%** | **The staleness reversal.** Each claim carries two timestamps (`source_as_of` vs `retrieved_at`) with an SLA enforced between them | `provenance/core/staleness.py`, `tests/test_staleness_reversal.py` |
| **Impact 25%** | We reproduce the 95% false-positive rate ourselves with a rule engine. **Zero** true-positive auto-closes. Analyst-hours are converted to money | `provenance/rules/engine.py`, eval arms |
| **UX 10%** | A live ledger view where claims stream in via Firestore listeners. It exists to make the 40% *visible* | Firebase console |

### Three moves nobody else will make

1. **Baseline first.** Arm A1 (plain Gemini, no tools) fails on camera: zero citations and a hallucinated counterparty circled in red. We measure it before writing any agent code.
2. **The reversal**, which comes out stronger than PLAN.md describes (see §4). Our system escalates a stale case **before the new designation is even in hand**, because it knows the list is 30 months old.
3. **Guarantees, not averages.** "Citation coverage is 1.0 by construction" and "zero true-positive auto-closes" are the two numbers we lead with.

### Words we use and avoid

- **Say:** "evidence contract", "cannot emit an uncited assertion", "escalation is a designed success path", "it knows how old its evidence is".
- **Never say:** "AI triages alerts", "we used AI to summarize", "reduces false positives". We don't reduce them. We *clear* them safely and hand the rest to a human.

---

## 2. MVP: the submittable entry (target **Sun Oct 4**, Tue Oct 6 at the latest)

These are the five never-cut items, each with a binary acceptance test:

| # | Item | Done when | Status |
|---|---|---|---|
| 1 | **Public URL** (Cloud Run agent + Firebase console) | A device that has never logged in pastes an alert ID and gets a cited disposition | ✅ Live on Firebase Hosting + Cloud Run, Gemini mode (Oct 4) |
| 2 | **Citation verifier** in the loop | A forced uncited draft is rejected, retried up to 2×, then escalated | ✅ In the ADK loop; e2e-tested |
| 3 | **Policy gate** | All six conditions are shown per case in the console | ✅ In the graph and the console |
| 4 | **Staleness toggle** | Hero alert: naive clock → auto-close; `source_as_of` → escalate; live list → escalate on a sanctions hit | ✅ One-click "Run the reversal"; e2e-tested offline |
| 5 | **Eval table** | A0, A1, A3, A4-naive and A4 render on `/eval` from BigQuery | ✅ `/eval.html` with arm table, staleness lift and calibration chart. Real runs still to do |

**Next, in order** (step-by-step commands in [docs/RUNNING_ON_GEMINI.md](docs/RUNNING_ON_GEMINI.md)):
1. `MODE=offline ./deploy/deploy.sh` today for a public URL with zero model spend. That's the insurance.
2. Real Gemini on the demo bundle, then fix whatever schema or grounding issues show up.
3. Load real data (runbook), then run A1/A3/A4 on real data.

**Also built ahead of Phase 3** (works offline, tested):
- the nightly staleness sweep that reopens cases (Cloud Scheduler wiring is opt-in in `deploy.sh`);
- the analyst review loop that feeds eval labels;
- the adverse-media injection guard (deterministic first layer, with a Model Armor adapter behind it).

The video can now show all three.

**What the MVP includes:**
- **3 evidence agents:** transactions, watchlist, adverse media.
- **3 typologies:** structuring, sanctions nexus, rapid movement.
- **SAR output:** a templated summary, not an LLM draft yet.
- **Corpus:** 300 alerts.

**What waits:**
- KYC multimodal agent: Phase 2 tail.
- Scheduler sweep, network_analyst, 6 typologies, 1,000 alerts, CI/CD, LLM SAR drafter: Phase 3, from the closed list below.

---

## 3. Rebased schedule

Every day has a **gate**: a binary, checkable outcome. Standup is at 22:00 IST. **If a gate slips two days, something comes off the kill list that evening.**

### Phase 1: foundations and baselines (compressed from 7 days to 6)

| Date | Gate | Owner |
|---|---|---|
| **Sat Sep 26** ✅ | GCP project, billing alerts, pinned 3.x model, quota request, hero persona. Repo scaffold, data loaders, A1 runner and Firestore ledger merged | Cloud (lead), all |
| **Sun Sep 27** | Run README runbook steps 1–3: the SAML-D sample is in BigQuery, alerts at a **measured** FP rate in the industry's 95–98% range (measured Oct 4: **97.36%** over 44,700 rule alerts on 1.8M transactions), and archived + live OFAC snapshots are in GCS. The hero persona's account is linked in the data | Cloud (data), Iqbal (persona) |
| **Mon Sep 28** | Hand-review the 40 golden alerts, then **A0 + A1 baselines** (runbook step 4). Screenshot the A1 failures: this opens the video | Iqbal |
| **Tue Sep 29** | The Typologist writes an evidence plan to Firestore. `txn_analyst` + `watchlist_analyst` write claims through the ledger | Agent eng |
| **Wed Sep 30** | `adverse_media_analyst` is isolated behind `AgentTool`. **At least one claim's `source_uri` is a real news URL from `groundingChunks`** (budget the whole afternoon for this). The console skeleton is on Firebase | Agent eng, Frontend |
| **Thu Oct 1** | **DEPLOY HARD GATE:** the public URL returns a cited disposition through the verifier loop and the gate. *Slipping to Oct 3 means cutting from the kill list* | Cloud, Agent eng |

### Phase 2: core system, submittable

| Date | Gate | Owner |
|---|---|---|
| **Fri Oct 2** | The staleness toggle reproduces on at least 3 alerts including the hero. A3 runs on 200 alerts. `eval compare` A1 vs A3 | Iqbal, Agent eng |
| **Sat Oct 3** | A4-naive + A4 run. All arms are in BigQuery. `/eval` page and ledger view are live. **Zero TP auto-closes on golden** | Iqbal, Frontend |
| **Sun Oct 4** | **Insurance entry.** Rough 3-minute cut, README, public repo tidy. **File it if the portal allows updating later** | All |
| Mon–Tue Oct 5–6 | Buffer for Phase 1/2 slippage. Otherwise: KYC agent, HITL override, Model Armor | — |

### Phase 3: depth (Oct 7–11), a closed list in priority order

Anything not on this list does not get built.

1. **Eval cycles:** 15+ rounds of generate → grade → analyze → fix. This is where the 40% lives.
2. KYC multimodal agent (if not done in the buffer) plus HITL override persisted as an eval label.
3. **Staleness sweep:** Cloud Scheduler → Pub/Sub → reopens an auto-closed case whose basis changed.
4. Corpus 300 → 1,000 alerts, 6 typologies; golden set 40 → 100.
5. network_analyst: 2-hop counterparty graph with cycle detection.
6. **AML SME session** (3–4 hours) to validate `MANDATORY_EVIDENCE` and the SAR structure.
7. Cost and latency benchmark: $/alert and p95.

**Phase gate, Sun Oct 11:** arms re-run at 1,000 alerts with stable numbers, and the sweep visibly reopens a case.

### Phase 4: production (unchanged)

- **Mon Oct 12: HARD FEATURE FREEZE.** Bug fixes only, and only for a broken gate.
- Oct 12–14: video (script, 8+ takes, real edit).
- Oct 13–15: deck (eval table on slide 2), README, architecture doc.
- **Thu Oct 15:** dress rehearsal. Clone the public repo into a **fresh GCP project** and run it end to end. `grep -r "2\.5"` for model references.
- **Fri Oct 16: SUBMIT.**
- Oct 17–18: hold. Turn `--min-instances 1` on for the judging window.

---

## 4. The demo: the reversal in three beats

Sharper than PLAN.md's version, and already proven in `tests/test_staleness_reversal.py`:

1. **Naive clock.** The archived OFAC list was fetched this morning, so a typical RAG system believes it is fresh. The agent confidently auto-closes. *Fluent, cited, wrong.*
2. **Our clock.** Same list, but we read the publisher's date: `source_as_of = 2024-03-29` (the Wayback capture), 30 months past a 3-day SLA. The staleness auditor fires and the case escalates, **before we have even seen the new list.** Point at the two timestamp fields on screen.
3. **Live list.** Refresh the list and the designation appears. There's a sanctions hit, a hard escalation and a case file with the SAR draft.

The line to say: *"It didn't need to know the customer was designated. It only needed to know its evidence was too old to trust."*

### Video (3:00)

| Time | Beat |
|---|---|
| 0:00–0:20 | The queue: 97 of 100 alerts are noise, at 25 minutes each. We reproduced it ourselves: a standard rule engine on 1.8M transactions fired 44,700 alerts, 97.4% of them false positives |
| 0:20–0:40 | A1: fluent, zero citations, a hallucinated counterparty circled |
| 0:40–1:40 | Provenance live on Gemini: typology → evidence plan → parallel agents → ledger filling → Gemini cites every sentence first time → gate (six ticks) → auto-close. Then press **Probe the verifier**: one uncited sentence is added in plain view, the deterministic verifier rejects it and the gate would escalate. Say "we added that sentence, not the model". If a real draft rejection happens while recording, show that instead (it's in the drafts history). 3 seconds of the Cloud Trace waterfall |
| 1:40–2:15 | The reversal, in three beats |
| (optional) | 10 s of the sweep reopening the naively closed case, or of the injection guard withholding a hostile web page |
| 2:15–2:40 | Eval table: **0 TP auto-closes**, X% auto-close, Y analyst-hours/month, calibration curve |
| 2:40–3:00 | Architecture card with the Google stack, then the tagline |

---

## 5. Owners

Fill in names at tonight's standup. Every row needs a name by end of day.

| Seat | Name | Owns |
|---|---|---|
| Architect, eval, narrative | **Iqbal** | Schemas and gate (done), hero persona, golden set, A1 baseline, eval runs, video VO, deck. **Not the React.** |
| Cloud/data | _TBD_ | GCP bootstrap, quota, billing alerts, BigQuery loads, rule-engine tuning (measured 97.36% FP), Cloud Run deploy, `agents-cli` scaffold, Secret Manager |
| Agent/backend | _TBD_ | `provenance/agents/`: evidence agents, grounding isolation, Firestore `LedgerStore`, `VerifyAndGate` wiring, Model Armor |
| Frontend/Firebase | _TBD_ | Console: alert input, live ledger view (show both timestamps), six-condition gate panel, staleness toggle, `/eval` page |

**Contracts are already in code.** Frontend builds against `Claim` / `GateResult` / `CaseDecision` in `provenance/core/`.
The agent engineer calls `decide_case()`; they never reimplement it.

---

## 6. Kill list (cut from the top when a gate slips)

1. Arm A2 (A1 → A3 → A4 carries the story)
2. KYC multimodal agent → KYC facts from a structured JSON profile
3. LLM SAR drafter → templated summary (already the MVP default)
4. HITL override persistence → show the button, describe the loop
5. Three typologies → two (keep sanctions nexus and structuring)

**Never cut:** the citation verifier, the policy gate, the staleness toggle, the eval table, the public URL.

---

## 7. Risks that could lose the cup

| Risk | Mitigation | Trigger |
|---|---|---|
| Live URL dead during judging (the 2.5 model series retires ~Oct 16) | Pin 3.x on day 0; grep before dress rehearsal; `--min-instances 1` for the judging window | Oct 15 |
| We're 5 days behind | Deterministic core already done. Deploy gate Oct 1. Buffer days Oct 5–6 | Any gate slips 2 days |
| Grounding returns nothing | Persona linkage to real SDN/DOJ subjects; cached-evidence feature flag for recording | Wed Sep 30 |
| Gemini quota 429s during eval | Request increase today; exponential backoff; run arms overnight | Oct 2 |
| "It's a wrapper" | Open with A1 failing; show the verifier *rejecting* the model; eval table on slide 2 | Script review Oct 12 |
| Data credibility | Say it plainly: transactions are published research data, watchlists and media are real and live, and KYC docs are synthetic and watermarked | Deck |
| **Too few suspicious alerts to prove "zero TP auto-closes"**: at ~96% FP, 300 alerts contain only ~12 true positives | The golden set is positive-enriched (up to 8, never more than half). Report the FN rate across *all* positives in every split, not just golden. Pull the 1,000-alert corpus (~40 positives) forward if Phase 2 has slack | Sun Sep 27 (read `tuning_report.json`) |
| **No billing account** (the trial ended); the rules require a working Cloud Run + Firestore link through evaluation | Develop free on an AI Studio key now. Ask the organisers for credits. If none by **Oct 10**, enable billing at near-zero settings (see SUBMISSION.md) | Oct 10 |
| **Video length rule conflicts** (3–4 min in the rules, "up to 3 minutes" on the form) | Cut to exactly 3:00 or just under | Oct 12 |
| **Deck must use the prescribed template** | Build it in their Google Slides template, export a PDF ≤ 5 MB | Oct 13 |
| Licence issue with public repo | OFAC is primary (public domain). Check SAML-D licence; ship a loader, never the data | Sun Sep 27 |

---

## 8. Judge Q&A we should be ready for

- **"Isn't this just RAG?"** RAG records when it fetched something. We also record when the source says the fact was true, and we refuse to act when the gap exceeds an SLA. And a parser, not a model, decides whether the narrative is allowed out.
- **"What if the model mis-cites a real claim?"** Coverage is structural. *Fidelity* is measured separately by an LLM judge, and we report it rather than hide it.
- **"What's your false-negative rate?"** Zero true-positive auto-closes on the golden set, because the gate is conservative by design. Escalation precision shows it isn't escalating everything.
- **"Production path?"** Document AI for page-level KYC provenance, field-level authz on the service account, and the nightly staleness sweep that reopens closed cases.
