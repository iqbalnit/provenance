# Demo video: 3:00 script and shot list

The form allows up to 3 minutes and the rules say 3 to 4, so **3:00 or just under** satisfies both.
The narration below is about 400 words, which is 3 minutes at a calm pace. Read it once against a stopwatch
before recording and cut lines rather than speed up.

## What runs where

| Beat | Screen | Data |
|---|---|---|
| Real hero on Gemini | Local console: `PROVENANCE_DATA=gcp make dev-gemini`, then http://localhost:8080 | Real SAML-D alert, real OFAC lists |
| The reversal | The deployed console, https://ai-builder-cup-2579.web.app | Labelled demo bundle (fictional customer) |
| Eval table | `/eval.html` on either | BigQuery `eval_results` |

**Before recording:**
- Run the real hero once and keep that case open, so the drafts history shows a real rejection. Re-run until
  draft 1 is rejected for a genuine reason; Gemini often writes an uncited judgment sentence on this alert.
  If it never does, use **Probe the verifier** and say that we added the sentence.
- Open the deployed console in a fresh tab so the first Gemini call is warm.
- Browser at 1280×800 or larger, zoom 110%, notifications off, bookmarks bar hidden.

## Script

**0:00–0:20 · The queue** *(screen: deck slide 2, then the console's alert list)*
> Banks' transaction monitoring flags thousands of alerts, and almost all are false positives. We reproduced it:
> a standard rule engine on 1.8 million transactions raised 44,700 alerts, 97 percent of them false.
> Analysts clear every one by hand.

**0:20–0:40 · Plain Gemini** *(screen: `/eval.html`, A1 row; one A1 narrative with an invented name circled)*
> The obvious fix is to ask a model. Here is plain Gemini on our golden alerts: fluent, confident, zero citations,
> and about one in six of the names and accounts it writes appear nowhere in the evidence. A compliance team cannot defend that.

**0:40–1:40 · Provenance on a real alert** *(screen: local console, hero alert, live list, publisher clock; press Run)*
> Provenance is an agent graph on Gemini that must prove every sentence. First it classifies the alert from
> behaviour alone; the customer's name is hidden. Then parallel agents gather evidence: transactions from
> BigQuery, the customer profile, the OFAC sanctions list, adverse media.
> Every fact lands in this claim ledger in Firestore with its source and two dates: when the publisher says it
> was true, and when we fetched it.
> *(scroll to the drafts)* Gemini drafts the disposition. This first draft was rejected. Not by another model,
> by a parser: these two sentences cite nothing. The second draft cites every sentence and is accepted.
> *(point at the gate)* Then six conditions decide. This customer is a real person designated by OFAC this year,
> so the gate escalates with a case file and a draft report. The analyst decides.

**1:40–2:15 · The reversal** *(screen: deployed console, demo hero, press "Run the reversal")*
> Now the part most systems get wrong. Same alert, same model, three runs. With an old sanctions list that we
> fetched this morning, a typical system thinks its evidence is fresh, and auto-closes. Provenance reads the
> publisher's date: the list is 30 months old against a 3-day limit, so it escalates before it ever sees the new
> designation. With the live list, the match appears. It didn't need to know the customer was designated. It only
> needed to know its evidence was too old to trust.

**2:15–2:40 · Results** *(screen: `/eval.html` arm table)*
> On the same golden alerts: plain Gemini auto-closed a suspicious case. Provenance auto-closed none, and every
> sentence it emits is cited. *(Read the final A3 / A4 numbers from the table here; keep it to two numbers.)*

**2:40–3:00 · Close** *(screen: deck architecture slide, then the console)*
> It runs on Cloud Run with Firebase Hosting, Firestore, BigQuery and Gemini on Vertex AI. Provenance: AML
> triage that cannot say what it cannot cite, and knows how old its evidence is.

## Recording and upload

1. **Record:** QuickTime → File → New Screen Recording (or Loom/OBS), 1080p, microphone on. Record each beat
   separately; it is easier to retake one than the whole thing.
2. **Edit:** trim pauses, cut the Gemini wait between Run and the result (say "this takes about a minute on real
   data" once, then cut). iMovie or CapCut is enough. Export 1080p.
3. **Check:** total length ≤ 3:00, audio level steady, no personal email, tabs or notifications visible.
4. **Upload:** YouTube → Create → Upload video → Visibility **Unlisted**. Title: "Provenance: AML triage that
   cannot say what it cannot cite (AI Builder Cup 2026)".
5. **Test:** open the link in a private window, logged out, and play it to the end.
6. **Use the link** in the form, and rebuild the deck with `--video <link>` so slide 13 carries it.
