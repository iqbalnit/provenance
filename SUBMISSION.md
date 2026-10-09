# Submission checklist: AI Builder Cup 2026

Taken from the Hack2skill submission page (Prototype Submission module).
**The module closes Sun Oct 18, 11:59 PM IST. We submit Fri Oct 16.**

## The form, field by field

| Field | Requirement on the page | Our answer | Status |
|---|---|---|---|
| Challenge | Select from the list | BFSI: intelligent risk, fraud, and financial experiences | Pick on the form |
| Prototype link | "Deployed on GCP or Cloud Run", publicly accessible, **must stay working through evaluation, with no retries** | Cloud Run URL (or its Firebase Hosting front), Gemini mode, cases in Firestore | Needs a billing account or credits (see below) |
| Deck (PDF, ≤ 5 MB) | **Must use the prescribed template**; other formats "may be subject to disqualification" | Generated *from their template* by `submission/deck/build_deck.py`, then exported to PDF from Google Slides (steps below) | Draft built; A3/A4 numbers pending |
| GitHub repo | Public access, `https://` URL | https://github.com/iqbalnit/provenance | ✅ Public, clean single-commit history (Oct 4) |
| Demo video | Rules say "3 to 4 minutes"; the form field says "up to 3 minutes" | **Exactly 3:00 or just under** satisfies both | Script and shot list in [submission/VIDEO.md](submission/VIDEO.md) |
| Brief description | ≤ 1024 characters; must say how we use **Firebase, Firestore, Cloud Run and Gemini** | Below (995 characters) | Ready |

## Brief description (paste as is, 995/1024 characters)

> Provenance is an AML alert-triage agent that cannot make a claim it cannot cite, and escalates when its evidence goes stale. An ADK multi-agent graph runs on Cloud Run: Gemini classifies the alert name-blind and drives parallel evidence agents (transactions in BigQuery, OFAC sanctions lists, KYC, adverse media via Google Search grounding), then drafts the disposition. Every fact goes to an append-only claim ledger in Firestore with its source and two timestamps: when the publisher says it was true and when we fetched it. Deterministic code, not the model, rejects any uncited sentence, applies a six-condition auto-close gate and blocks stale evidence: on a labelled demo case the same alert auto-closes under a naive clock and escalates under ours. The analyst console, served by Firebase Hosting, shows each case, its ledger and the verifier's rejected drafts. A nightly sweep reopens closed cases whose evidence changed, and a five-arm eval against plain Gemini measures the difference.

Keep it true: every service named must be live in the deployed prototype when judges look.
It says "Gemini" rather than naming Flash or Pro, because quota may push both roles onto one model, and it
places the auto-close reversal on the labelled demo case, which is where it happens.

## The deck

The deck is generated from Hack2skill's template, so the frame, fonts and closing slide are theirs.
Words live in `submission/deck/content.py`, measured numbers in `submission/deck/numbers.json`.

```bash
cd ~/Project_Provenance
python3 submission/deck/build_deck.py \
  --template ~/Downloads/Submission_Template___AI_Builder_Cup.pptx \
  --leader "Your Full Name" --video "https://youtu.be/..." -o ~/Desktop/Provenance_Deck.pptx
```

Standard library only; no install needed. The leader's name and video link are passed in, so they never land in the repo.

**PDF for the form** (≤ 5 MB):
1. drive.google.com → New → File upload → `Provenance_Deck.pptx`.
2. Right-click it → Open with → Google Slides. Slides has the template's Google Sans Flex font.
3. Check every slide: numbers, no "running" left in the benchmark table, the video link.
4. File → Download → PDF document. Check the size is under 5 MB (the draft is about 1 MB).

**Before submitting:** update `numbers.json` with the final A3, A4-naive and A4 golden results and rebuild.
The benchmark table shows "running" for any arm still null.

## The form, what to paste

| Field | Paste |
|---|---|
| Challenge | BFSI: intelligent risk, fraud, and financial experiences |
| Prototype link | https://ai-builder-cup-2579.web.app |
| Deck | the PDF exported above |
| GitHub repo | https://github.com/iqbalnit/provenance |
| Demo video | the unlisted YouTube link (see submission/VIDEO.md) |
| Brief description | the block above |

## Must be true on the deployed prototype

**Deploy for judging:** `MODE=gemini MIN=1 ./deploy/deploy.sh` with the default `DATA=bundle`.
- Judges get the labelled demo alerts, and "Run the reversal" shows all three outcomes.
- `/eval.html` still reads the real-data results from BigQuery `eval_results`, because gemini mode sets `PROVENANCE_EVAL=bigquery`.
- `MIN=1` keeps one instance warm through the judging window, so the first click isn't a cold start. Set it back to 0 afterwards.


The page says the prototype must "inculcate all the tech mentioned":
- **Cloud Run:** the agent, API and console. `make deploy-gemini`.
- **Gemini:** the Flash and Pro agents, plus Google Search grounding. On Vertex (credits) or an AI Studio key, stored in Secret Manager.
- **Firestore:** cases, the claim ledger, narratives and analyst reviews (`PROVENANCE_STORE=firestore`, set automatically in Gemini mode).
- **Firebase:** Hosting serves the console, with `/api/**` rewritten to Cloud Run (`firebase deploy --only hosting`).

## Cost and billing

**Using credit on a second Google account?** See guide section A1 (a separate gcloud profile for that account).

**Cloud Run and Firestore in a GCP project need a billing account.** No setup avoids that for the deployed link.
The cheapest honest path:
1. **Ask for credits first.** Check your registration email and the Hack2skill dashboard for GCP credits or a coupon.
   Otherwise write to support@Hack2skill.com ("AI Builder Cup 2026: GCP credits for prototype deployment").
2. **Until then, develop for free.** Use a Google AI Studio API key (no billing account) with `make dev-gemini` and `make smoke` on your Mac.
3. **If you enable billing yourself**, keep spend near zero:
   - `MIN=0` (Cloud Run scales to zero when idle);
   - the AI Studio key for Gemini, if its free tier covers your volume;
   - a budget alert at a small amount (Billing → Budgets & alerts);
   - eval runs only on small splits.

   Check current pricing and free allowances on Google's pricing pages, because they change.
   Budget alerts notify you but do **not** stop spend. The kill switch is
   `gcloud run services delete provenance --region us-central1`.

## Public repo

**Submit https://github.com/iqbalnit/provenance.** It's public and starts from one clean commit.
`iqbalnit/Project_Provenance` stays private: it's the working repo, and its old history is still reachable by commit ID.

Also before publishing:
- **Secrets:** none found in history (Google keys, private keys, tokens). Re-check after any local commits.
- **Data:** keep `data/raw/` out (gitignored). Check the SAML-D licence before committing any data.
