# Demo video: 3:00 script and shot list

The form allows up to 3 minutes and the rules say 3 to 4, so **3:00 or just under** satisfies both.

## What runs where

| Beat | Screen | Data |
|---|---|---|
| Real hero on Gemini | Local console: `PROVENANCE_DATA=gcp make dev-gemini`, then http://localhost:8080 | Real SAML-D alert, real OFAC lists |
| The reversal | The deployed console, https://ai-builder-cup-2579.web.app | Labelled demo bundle (fictional customer) |
| Eval table | `/eval.html` on either | BigQuery `eval_results` |

**Before recording:**
- Run the real hero once and keep that case open, so the drafts history shows a real rejection. Re-run until
  draft 1 is rejected for a genuine reason; Gemini often writes an uncited judgment sentence on this alert.
  If it never does, use **Demo: add an uncited sentence** and say that we added the sentence.
- Deploy with `MIN=1` first, then open the deployed console once so it is warm; otherwise the first load shows
  a "server can take up to 30 seconds" note while Cloud Run starts.
- Browser at 1280×800 or larger, zoom 110%, notifications off, bookmarks bar hidden.

## Script

About 400 words: 3:00 at a calm pace. Read it once against a stopwatch before recording, and cut lines
(see the end of this section) rather than speed up. A pause mark ( / ) means take a breath.

**0:00–0:20 · The problem** *(screen: deck slide 2)*
> Every bank runs rules that flag suspicious transactions. / Almost all of those alerts are innocent, but an
> analyst still has to clear each one by hand. / We reproduced it on 1.8 million transactions: 44,700 alerts,
> and 97 percent of them false positives.

**0:20–0:35 · Plain AI** *(screen: `/eval.html`, the A1 row)*
> The obvious fix is to ask an AI. / Plain Gemini is fluent and confident, but it cites nothing, and about one
> in six of the names and accounts it mentions don't exist in the evidence. / No compliance team can defend that.

**0:35–1:35 · Provenance on a real alert** *(screen: local console, hero alert `alt_95bf5f09d5`, live list,
publisher date; press Run, cut the wait)*
> This is Provenance, an agent system on Gemini that cannot say what it cannot cite. / This is a real alert.
> Gemini first classifies the pattern from behaviour alone; the customer's name is hidden on purpose. / Then
> agents gather evidence in parallel: transactions from BigQuery, the customer profile, the OFAC sanctions list,
> and a web search for adverse news.
>
> *(scroll to the ledger)* Every fact goes into this ledger, with its source and two dates: when the publisher
> says it was true, and when we fetched it.
>
> *(scroll to the drafts)* Now Gemini drafts the decision. / The first draft is rejected. Not by another AI, by a
> parser: these two sentences cite nothing. / The second draft cites every sentence, and passes.
>
> *(point at the gate)* Then six fixed rules decide. / This customer is a real person OFAC sanctioned after our
> older list was published, so the case goes to an analyst, with the evidence and a draft report ready.

*If draft 1 passed on the run you recorded, press **Demo: add an uncited sentence** and say instead:* "Here we add one
sentence with no citation, and the parser rejects it. We added that sentence, not the model."

**1:35–2:10 · The reversal** *(screen: deployed console, demo hero, press "Same alert, old vs live sanctions list")*
> Now the part most systems get wrong. / Same alert, same model, three runs. / With an old sanctions list
> downloaded this morning, a typical system thinks its evidence is fresh, and closes the alert. / Provenance
> reads the publisher's date instead: the list is nineteen months old against a three-day limit, so it
> escalates, before it has even seen the new sanction. / With the live list, the match appears. / It didn't need
> to know the customer was sanctioned. It only needed to know its evidence was too old to trust.

**2:10–2:42 · Results** *(screen: `/eval.html` arm table)*
> We measured this on real alerts, and we report the misses. / On a thirty-month-old list, a naive clock made six
> closing decisions; Provenance refused all six. / Plain Gemini wrongly closed one laundering case, and so did
> ours, on a pattern Gemini can't tell apart. / So those closes now need an analyst's confirmation, and the
> riskiest alert type never closes automatically. / On a hundred unseen alerts, it cleared eleven percent, with no
> suspicious case among them.

**2:42–3:00 · Close** *(screen: deck architecture slide, then the console)*
> Provenance runs on Cloud Run, with Firebase Hosting, Firestore, BigQuery and Gemini on Vertex AI. / AML triage
> that cannot say what it cannot cite, and knows how old its evidence is.

**Saying it:**
- OFAC: "oh-fack". KYC: "K-Y-C". Gemini: "JEM-in-eye". 44,700: "forty-four thousand seven hundred".
- The demo list is **nineteen** months old (2025-03-01); the real-data list is **thirty** months old (2024-03-29).
  Don't swap them.
- Slow down on the two lines that carry the idea: "Not by another AI, by a parser" and "It only needed to know
  its evidence was too old to trust."

**If you run over 3:00, cut in this order:**
1. ", and a web search for adverse news" (0:35 section).
2. "Gemini first classifies the pattern from behaviour alone; the customer's name is hidden on purpose."
3. "On a thirty-month-old list, a naive clock made six closing decisions; Provenance refused all six."

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
