# Running Provenance on Gemini, and deploying it

This covers the first real-Gemini run through to a public URL. Budget about 45 minutes.
Commands are copy-paste. **Paste any failing output back to Claude**: the smoke test output contains no secrets.

**Where you develop: `~/Project_Provenance` on your Mac.** Claude works in a cloud session and pushes to the branch
`claude/upbeat-davinci-tdyw3g`. You pull into that folder and run everything there (section H covers staying in sync).
Google Cloud Shell works as a fallback (see the box at the end of A2).

Every command below has a `make` shortcut. Run `make` targets from `~/Project_Provenance`.

---

## 0. No billing account? Start here (free)

You can build and test everything on your Mac **without a billing account**, using a free Google AI Studio API key
for Gemini. Only the **deployed link** (Cloud Run + Firestore, which the submission rules require) needs billing
or credits. SUBMISSION.md covers that decision.

1. **Code:** do A2 below (clone into `~/Project_Provenance`, `make setup`, `make test`, `make dev`). No Google account is needed for this.
2. **Key:** get a free API key at https://aistudio.google.com → **Get API key**. Put it in `.env`, never in chat or git:
   ```bash
   GOOGLE_GENAI_USE_VERTEXAI=FALSE
   GOOGLE_API_KEY=<your key>
   PROVENANCE_MODEL_FLASH=<a 3.x Flash ID your key can use>
   PROVENANCE_MODEL_PRO=<a 3.x Pro ID your key can use; or the Flash ID again if Pro isn't free>
   ```
   AI Studio shows which models and how many requests per minute and per day your free tier allows. Those limits change,
   so read them there. `make smoke` check 3 lists the model IDs your key can actually call.
3. **Smoke test:** `make smoke`. On the free backend:
   - Check 2 (gcloud credentials) is skipped.
   - If Search grounding isn't in your free tier, check 5 prints **WARN** instead of failing. Adverse media then records
     "no supported findings", and everything else still runs.
   - A `429` means you hit the free rate limit. Wait a minute and use `--only N`.
4. **Watch it on real Gemini:** run `make dev-gemini` and open http://localhost:8080.
5. **Eval on Gemini:** `make eval-gemini` makes a few dozen requests in total, so space runs out if you hit limits.

**Note:** on the free tier, Google may use your prompts to improve its products. Everything we send is fictional demo data
or public lists, so that's acceptable here. Don't send real customer data on a free key.

You can skip A1's `gcloud` and billing steps until you're ready to deploy.

---

## A. One-time setup on your Mac (about 15 minutes)

### A1. Tools and Google login

> **Is the project under a different Google account?** For example, a second Gmail account that has the free credit.
> Give that account its own gcloud profile so nothing mixes with your other account:
> ```bash
> gcloud config configurations create provenance
> gcloud auth login                       # pick the account that owns the project, in the browser
> gcloud config list account              # confirm it's that account
> gcloud projects list                    # its PROJECT_ID
> gcloud config set project <project-id>
> gcloud billing projects describe <project-id>        # expect billingEnabled: true (the credit)
> gcloud auth application-default login   # pick the SAME account again: this is what the Python code uses
> gcloud auth application-default set-quota-project <project-id>
> ```
> - **Switch profiles:** `gcloud config configurations activate provenance` (or `default`).
> - **Credentials are shared:** the Python code's credentials (`application-default`) are shared by all profiles. If you
>   later run `application-default login` with the other account, re-run the last two lines before using Provenance.
> - **Set a budget alert on the credit's billing account** (Billing → Budgets & alerts). When the credit runs out, an
>   account with a card attached starts billing.


```bash
brew install uv
brew install --cask google-cloud-sdk        # gives you gcloud

gcloud auth login
gcloud config set project <your-project-id>
gcloud auth application-default login        # lets the Python code call Vertex as you
gcloud auth application-default set-quota-project <your-project-id>
export GOOGLE_CLOUD_PROJECT=<your-project-id>   # needed in every new shell for the commands below

gcloud services enable aiplatform.googleapis.com run.googleapis.com cloudbuild.googleapis.com \
  artifactregistry.googleapis.com firestore.googleapis.com bigquery.googleapis.com storage.googleapis.com
```

Type the real project ID in place of `<your-project-id>`. If `set-quota-project` says *"Cannot find a quota project"*,
it was given an empty value, so re-run it with the ID typed out.

### A2. The code in `~/Project_Provenance`

**If the folder doesn't exist yet, or is empty:**

```bash
git clone https://github.com/iqbalnit/Project_Provenance.git ~/Project_Provenance
cd ~/Project_Provenance
git checkout claude/upbeat-davinci-tdyw3g
make setup                                   # uv sync --extra gcp, and creates .env from .env.example
```

**If the folder already has files in it** (git says *"destination path already exists and is not an empty directory"*),
move it aside, clone fresh, then bring back anything that only existed in the old folder:

```bash
mv ~/Project_Provenance ~/Project_Provenance.old
git clone https://github.com/iqbalnit/Project_Provenance.git ~/Project_Provenance
cd ~/Project_Provenance
git checkout claude/upbeat-davinci-tdyw3g
ls Makefile                                  # must exist; otherwise the clone did not work
make setup

diff -rq ~/Project_Provenance.old ~/Project_Provenance | grep "Project_Provenance.old"   # files only in the old copy
```

What the `diff` shows:
- **Same-named files** (PLAN.md, TEAM.md, README.md) are already in the repo, and the repo versions are newer.
- **Anything else listed** can be copied back if you still need it.
- **Once you're happy,** delete `~/Project_Provenance.old`.

If the repo is private, `gh auth login` (Homebrew: `brew install gh`) or a GitHub personal access token handles the clone.

Check that everything works before touching the cloud:

```bash
make test        # all tests should pass
make dev         # open http://localhost:8080 and press "Run the reversal" (scripted models, no cloud)
```

> **Alternative: Google Cloud Shell** (shell.cloud.google.com). `gcloud` and your login are already there.
> - Skip the `brew` lines and the two `application-default` commands.
> - A conda `(base)` prompt on the Mac is fine: uv uses its own `.venv`. If `python` or `uv` misbehave, run `conda deactivate` first.
> - Install uv with `curl -LsSf https://astral.sh/uv/install.sh | sh && source $HOME/.local/bin/env`.
> - Clone into `~/Project_Provenance` as above.
> - To see the console, use **Web preview → port 8080** instead of localhost.

### A3. Pin the models

List what Vertex serves your project in each location:

```bash
for LOC in global us-central1; do echo "== $LOC"; uv run python -c "
from google import genai; import os
c = genai.Client(vertexai=True, project=os.environ['GOOGLE_CLOUD_PROJECT'], location='$LOC')
print('\n'.join(sorted(m.name.rsplit('/',1)[-1] for m in c.models.list() if 'gemini' in m.name)))"; done
```

Rules for choosing:
- Choose a **3.x Flash** and a **3.x Pro**, using an **explicit versioned ID**, never one ending in `-latest`.
- **Avoid 2.5.** That series retires around Oct 16, inside the judging window.
- Note **which location** lists them. That value is `GOOGLE_CLOUD_LOCATION`, the *model* location.
  It's often `global` for newer models, and it's separate from where Cloud Run runs.

### A4. The `.env` file

```bash
cp .env.example .env
```

Edit `.env`:

```bash
GOOGLE_CLOUD_PROJECT=<your-project-id>
GOOGLE_CLOUD_LOCATION=<location from A3, e.g. global>
GOOGLE_GENAI_USE_VERTEXAI=TRUE
PROVENANCE_MODEL_FLASH=<pinned flash id>
PROVENANCE_MODEL_PRO=<pinned pro id>
```

The `make` targets load `.env` for you. For raw commands, load it into each new shell with `set -a; source .env; set +a`.
`.env` is gitignored, so never commit it.

### A5. Guardrails (do these once, now)

- **Billing alerts at 50% and 80% of credits:** Console → Billing → Budgets & alerts.
- **Gemini quota:** Console → IAM & Admin → Quotas. Filter on the pinned model and your model location,
  and request an increase for requests per minute. Credits don't raise quota.

---

## B. First Gemini run: the smoke test (about 5 minutes)

```bash
make smoke          # same as: set -a; source .env; set +a; uv run python -m provenance.smoke
```

Seven checks run in order, stopping at the first failure with a `fix:` line:

| # | Check | What a failure usually means |
|---|---|---|
| 1 | Environment | `.env` not loaded, or a `-latest`/2.5 model ID |
| 2 | Application Default Credentials | Laptop: run the `application-default` commands in A1 |
| 3 | Pinned models exist | Wrong ID or wrong location. The output lists the closest matching names |
| 4 | Structured output (JSON schema) | The model or location doesn't support `response_schema`. Try the other location |
| 5 | Google Search grounding | Grounding isn't available for that model or location, or it's out of quota |
| 6 | Full agent graph, hero alert, live list | Something in the agent wiring. **Paste the output back** |
| 7 | Staleness reversal on Gemini | Should never fail (the gate is deterministic). Paste it back if it does |

Useful flags:
- `--only 5` runs one check.
- `--skip-graph` runs checks 1–5 only. Checks 6–7 run the whole graph twice, about 25 model calls.

**Known risks the smoke test is designed to surface** (all fixable in minutes once seen):
- **An evidence agent answers without calling its tool.** The fix is `tool_config` mode `ANY` on that agent.
- **Search grounding arrives on a different event field than expected.** The fix is in `steps.AdverseMedia`.
- **The disposition model keeps leaving a sentence uncited.** The case escalates by design, and the fix is prompt tightening.
  Check 6 notes this rather than failing.

---

## C. The console on real Gemini (no deploy needed)

```bash
make dev-gemini     # same as: set -a; source .env; set +a; PROVENANCE_MODE=gemini uv run uvicorn provenance.service.app:app --port 8080
```

To open it:
- **Mac:** open http://localhost:8080.
- **Cloud Shell:** click **Web preview → Preview on port 8080**.

The badge in the header should read **"Live: Gemini on Vertex"**. Then press **Run the reversal**.

What looks different from the offline replay:
- **Typology rationale:** now the model's own sentence.
- **Drafts:** often only one. The scripted model always failed its first draft; a real model may pass first time. Both are correct behaviour.
- **Adverse media:** comes from live Google Search. The demo names are fictional, so **"no supported findings" is the expected
  result** for most alerts. Real hits come once you link personas to real OFAC or DOJ subjects (data/README.md).
- **Each case** takes 20–60 seconds instead of 1.

Other things to try:
- **Run nightly sweep.**
- **Web result with a prompt injection.** Offline, the injected text comes from the fixture. On Gemini, live search is used,
  so the guard will only fire if a real page contains an injection.
- **Evaluation:** to fill the page with Gemini numbers, run `make eval-gemini`.

---

## D. Deploy to a public URL

### D1. The insurance URL, with no model spend

```bash
make deploy-offline     # same as: MODE=offline ./deploy/deploy.sh
```

This deploys the scripted-model demo, labelled as such in the console, to Cloud Run.
- **First-time prompts:** the first `--source` deploy asks to create an Artifact Registry repo. Answer **Y**.
- **Output:** the script ends by printing the URL and a health check.
- **Check it:** open the URL on your phone.
- **If the portal allows updating a submission, file this URL now.**

### D2. The real thing on Gemini

```bash
make deploy-gemini      # same as: MODE=gemini MODEL_LOCATION=$GOOGLE_CLOUD_LOCATION ./deploy/deploy.sh (with .env loaded)
```

What changes from D1:
- **Firestore:** the script creates the Firestore database if none exists (location `nam5`; override with `FIRESTORE_LOCATION`),
  and stores cases there.
- **Scaling:** it allows up to 5 instances.
- **Environment:** `REGION` (default `us-central1`) is the Cloud Run region. `MODEL_LOCATION` is passed to the container as
  `GOOGLE_CLOUD_LOCATION`.

Other options:
- `SWEEP=1` also schedules the nightly staleness sweep: Cloud Scheduler → Pub/Sub → `/trigger/sweep`, 02:17 IST.
- `MIN=1` keeps one instance warm. **Use it only for recording and the judging window.** It costs money for as long as it's on.

Verify:

```bash
URL=$(gcloud run services describe provenance --region us-central1 --format 'value(status.url)')
curl $URL/api/health          # {"ok":true,"mode":"gemini"}
```

### D3. Firebase Hosting (optional second surface)

```bash
npm i -g firebase-tools && firebase login
firebase projects:addfirebase $GOOGLE_CLOUD_PROJECT     # once
firebase deploy --only hosting --project $GOOGLE_CLOUD_PROJECT
```

Hosting serves `console/`, and `/api/**` is rewritten to the Cloud Run service `provenance` in `us-central1`
(see `firebase.json`). Say both surfaces out loud in the video.

---

## E. Real data (after Gemini works)

Follow the "Data and baseline runbook" in the README (SAML-D → BigQuery, alerts, OFAC snapshots, A0/A1).
Then point the service at it:

```bash
export PROVENANCE_DATA=gcp PROVENANCE_GCS_BUCKET=<bucket>
export PROVENANCE_OFAC_ARCHIVED_URI=gs://<bucket>/ofac/<archived-date>/sdn.csv
export PROVENANCE_OFAC_LIVE_URI=gs://<bucket>/ofac/<live-date>/sdn.csv
# customer profiles: gs://<bucket>/kyc/customers.json, same shape as demo/customers.json
MODE=gemini DATA=gcp MODEL_LOCATION=$GOOGLE_CLOUD_LOCATION ./deploy/deploy.sh
```

---

## F. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `git clone`: destination path already exists | The folder has files but isn't a git repo | A2, "If the folder already has files in it": move aside, clone fresh, diff |
| `make: No rule to make target 'setup'` | You're in a folder without the repo (no Makefile) | `cd ~/Project_Provenance && ls Makefile`. If it's missing, redo A2 |
| `Cannot find a quota project to add to ADC` | `set-quota-project` got an empty project | `gcloud auth application-default set-quota-project <your-project-id>` with the ID typed out |
| `403 PERMISSION_DENIED ... aiplatform` | API off or missing role | `gcloud services enable aiplatform.googleapis.com`. Grant yourself (or the `provenance-run` service account) `roles/aiplatform.user` |
| `404 ... model ... not found` | Wrong ID or wrong location | Re-run A3. Set `GOOGLE_CLOUD_LOCATION` to where the ID is listed |
| `429 RESOURCE_EXHAUSTED` | Per-minute quota | Request a quota increase (A5). Run eval arms on smaller splits. The A1 runner already backs off |
| `Session not found` in ADK eval | App name mismatch | `App(name=...)` must equal the agent directory `provenance_agent` (it does, so don't rename either) |
| `ValidationError` on TypologyOutput / DispositionOutput | Model returned off-schema JSON | Paste the output back. The fix is prompt or schema tightening |
| Adverse media always "no supported findings" | Fictional names, or grounding off | Expected on the demo bundle. Smoke check 5 tells you whether grounding works at all |
| Build fails with `PERMISSION_DENIED` during `deploy.sh` | Cloud Build identity lacks rights | Grant the Compute Engine default service account `roles/cloudbuild.builds.builder`, then re-run |
| `--allow-unauthenticated` fails | Org policy blocks public services | Use a personal (non-org) project for the competition, or ask the org admin |
| Case stuck at "queued" on Cloud Run | Several instances with the in-memory store | Offline mode pins `--max-instances 1`; Gemini mode uses Firestore. Re-deploy with the script, not by hand |
| `database (default) does not exist` | Firestore not created | Re-run `deploy.sh` (it creates it), or `gcloud firestore databases create --location=nam5` |
| 503 or timeout on the first request | Cold start plus a long agent turn | The deploy already sets `--timeout 900`. Use `MIN=1` while recording |

---

## G. Cost guardrails

- **Per case:** about 8 Flash calls (typologist, the transaction and watchlist tool loops, and one grounded search) plus 1–3 Pro
  calls (disposition drafts). The deterministic parts (verifier, gate, staleness, SAR template) cost nothing.
- **Per eval arm:** one case per alert. A 40-alert golden run of A3 is about 400 model calls. Run arms overnight,
  and **never run an eval live on stage**.
- **Cloud Run:** costs nothing at `--min-instances 0`. It bills while `MIN=1` is on.
- **BigQuery:** every transaction query is a named template with a 2 GiB `maximum_bytes_billed` cap.

---

## H. Staying in sync with Claude's changes

Claude pushes to `claude/upbeat-davinci-tdyw3g`. Each day, or whenever Claude says it pushed:

```bash
cd ~/Project_Provenance
git pull origin claude/upbeat-davinci-tdyw3g
make setup          # picks up any new dependencies; leaves your .env alone
make test
```

**Local edits:**
- **Shared changes:** commit and push to the same branch (`git push origin claude/upbeat-davinci-tdyw3g`). The next
  Claude session starts from what you pushed.
- **Experiments:** keep them on your own branch and merge when ready.

**What stays on your Mac only** (gitignored, never pushed):
- `.env`
- `data/raw/`
- `data/snapshots/`
- `artifacts/`

Datasets and eval outputs live here, and the code that produces them lives in git.

| Shortcut | What it does |
|---|---|
| `make setup` | Install dependencies; create `.env` if missing |
| `make test` | Run the test suite |
| `make dev` | Console on scripted models, http://localhost:8080 |
| `make dev-gemini` | Console on real Gemini |
| `make smoke` | Seven-check Gemini first-run test |
| `make eval` / `make eval-gemini` | All eval arms (scripted / Gemini) |
| `make deploy-offline` / `make deploy-gemini` | Deploy to Cloud Run |
