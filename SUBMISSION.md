# Submission checklist: AI Builder Cup 2026

Taken from the Hack2skill submission page (Prototype Submission module).
**The module closes Sun Oct 18, 11:59 PM IST. We submit Fri Oct 16.**

## The form, field by field

| Field | Requirement on the page | Our answer | Status |
|---|---|---|---|
| Challenge | Select from the list | BFSI: intelligent risk, fraud, and financial experiences | Pick on the form |
| Prototype link | "Deployed on GCP or Cloud Run", publicly accessible, **must stay working through evaluation, with no retries** | Cloud Run URL (or its Firebase Hosting front), Gemini mode, cases in Firestore | Needs a billing account or credits (see below) |
| Deck (PDF, ≤ 5 MB) | **Must use the prescribed template**; other formats "may be subject to disqualification" | Build the deck *in their Google Slides template*, then export to PDF | Not started |
| GitHub repo | Public access, `https://` URL | https://github.com/iqbalnit/Project_Provenance | **Currently private.** Clean the history first (see below) |
| Demo video | Rules say "3 to 4 minutes"; the form field says "up to 3 minutes" | **Exactly 3:00 or just under** satisfies both | Script in STRATEGY.md §4 |
| Brief description | ≤ 1024 characters; must say how we use **Firebase, Firestore, Cloud Run and Gemini** | Draft below (990 characters) | Ready |

## Brief description (paste as is, 990/1024 characters)

> Provenance is an AML alert-triage agent that cannot make a claim it cannot cite, and escalates when its evidence goes stale. An ADK multi-agent graph runs on Cloud Run: Gemini Flash classifies the alert and drives parallel evidence agents (transactions, sanctions list, KYC, adverse media via Google Search grounding); Gemini Pro drafts the disposition. Every fact goes to an append-only claim ledger in Firestore with its source and two timestamps: when the publisher says it was true and when we fetched it. Deterministic code, not the model, rejects any uncited sentence, applies a six-condition auto-close gate and blocks stale evidence: the same alert auto-closes on an 18-month-old sanctions list under a naive clock and escalates under ours. The analyst console, served by Firebase Hosting, shows each case as the agents write it to Firestore. A nightly sweep reopens closed cases whose evidence changed, an injection guard screens web results, and a five-arm eval measures the lift.

Keep it true: every service named must be live in the deployed prototype when judges look.

## Must be true on the deployed prototype

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

## Before making the repo public

The history was squashed into a single clean commit on Oct 4. To make it public:
GitHub → Settings → General → Danger Zone → Change visibility → Public.

Also before publishing:
- **Secrets:** none found in history (Google keys, private keys, tokens). Re-check after any local commits.
- **Data:** keep `data/raw/` out (gitignored). Check the SAML-D licence before committing any data.
