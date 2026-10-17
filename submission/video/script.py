"""Narration for the demo video, split into beats. One beat = one shot on screen + the words spoken over it.

`make_video.py` speaks each beat, holds its shot for exactly that long, and writes the subtitles from the same text,
so picture, voice and captions cannot drift apart. Keep every claim true against submission/deck/numbers.json.

Beats whose text depends on what the live run actually did (which draft was rejected, what the gate decided)
are functions of the captured facts, so the narration never describes something the screen does not show.
"""

# Spoken forms for the text-to-speech voice only; subtitles keep the written form.
SAY = {
    "OFAC": "Oh-fack",
    "KYC": "K Y C",
    "BigQuery": "Big Query",
    "Firestore": "Fire store",
    "1.8 million": "one point eight million",
    "44,700": "forty-four thousand seven hundred",
}

NUMBER_WORDS = ("zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen "
                "sixteen seventeen eighteen nineteen").split()
TENS = "_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()


def words(n: int) -> str:
    if n < 20:
        return NUMBER_WORDS[n]
    t, u = divmod(n, 10)
    return TENS[t] + (f"-{NUMBER_WORDS[u]}" if u else "")


def agent_intro(f: dict) -> str:
    where = ("This is a real alert." if f["real"]
             else "This alert is from our demo set, with a fictional customer.")
    sources = ("transactions from BigQuery, the customer profile, the OFAC sanctions list, and a web search for "
               "adverse news." if f["real"] else
               "transactions, the customer profile, the OFAC sanctions list, and a web search for adverse news.")
    return (f"This is Provenance, an agent system on Gemini that cannot say what it cannot cite. {where} "
            "Gemini first classifies the pattern from behaviour alone; the customer's name is hidden on purpose. "
            f"Then agents gather evidence in parallel: {sources}")


def agent_drafts(f: dict) -> str:
    if f["rejected_uncited"]:
        n = f["rejected_uncited"]
        what = "this sentence cites" if n == 1 else f"these {words(n)} sentences cite"
        return ("Now Gemini drafts the decision. The first draft is rejected. Not by another AI, by a parser: "
                f"{what} nothing. The next draft cites every sentence, and passes.")
    return ("Now Gemini drafts the decision, and this time every sentence is cited. So we add one sentence with no "
            "citation ourselves, and it is rejected. Not by another AI, by a parser.")


def agent_gate(f: dict) -> str:
    if f["decision"] == "auto_close":
        return "Then six fixed rules decide. All six pass, so this alert closes without an analyst."
    if f["real"] and f["sanctions_hit"]:
        why = "This customer is a real person OFAC sanctioned after our older list was published"
    elif f["sanctions_hit"]:
        why = "Today's sanctions list names this customer"
    else:
        why = "Not every rule passes"
    return f"Then six fixed rules decide. {why}, so the case goes to an analyst, with the evidence and a draft report ready."


def rev_publisher(f: dict) -> str:
    return (f"Provenance reads the publisher's date instead: the list is {words(f['archived_months'])} months old "
            "against a three-day limit, so it escalates, before it has even seen the new sanction.")


# (beat id, shot, text or function of facts). Voice files, if you record your own, are voice/<beat id>.<ext>.
BEATS = [
    ("01-problem", "card:problem",
     "Every bank runs rules that flag suspicious transactions. Almost all of those alerts are innocent, but an "
     "analyst still has to clear each one by hand. We reproduced it on 1.8 million transactions: 44,700 alerts, "
     "and 97 percent of them false positives."),
    ("02-plain-ai", "eval:a1",
     "The obvious fix is to ask an AI. Plain Gemini is fluent and confident, but it cites nothing, and about one in "
     "six of the names and accounts it mentions don't exist in the evidence. No compliance team can defend that."),
    ("03-agent-intro", "agent:overview", agent_intro),
    ("04-agent-ledger", "agent:ledger",
     "Every fact goes into this ledger, with its source and two dates: when the publisher says it was true, and "
     "when we fetched it."),
    ("05-agent-drafts", "agent:drafts", agent_drafts),
    ("06-agent-gate", "agent:gate", agent_gate),
    ("07-rev-intro", "rev:tiles", "Now the part most systems get wrong. Same alert, same model, three runs."),
    ("08-rev-naive", "rev:t0",
     "With an old sanctions list downloaded this morning, a typical system thinks its evidence is fresh, and "
     "closes the alert."),
    ("09-rev-publisher", "rev:t1", rev_publisher),
    ("10-rev-live", "rev:t2",
     "With the live list, the match appears. It didn't need to know the customer was sanctioned. It only needed "
     "to know its evidence was too old to trust."),
    ("11-results-clock", "card:clock",
     "We measured this on real alerts, and we report the misses. On a thirty-month-old list, a naive clock made "
     "six closing decisions; Provenance refused all six."),
    ("12-results-miss", "eval:arms",
     "Plain Gemini wrongly closed one laundering case, and so did ours, on a pattern Gemini can't tell apart. So "
     "those closes now need an analyst's confirmation, and the riskiest alert type never closes automatically."),
    ("13-results-heldout", "card:heldout",
     "On a hundred unseen alerts, it cleared eleven percent, with no suspicious case among them."),
    ("14-close", "card:close",
     "Provenance runs on Cloud Run, with Firebase Hosting, Firestore, BigQuery and Gemini on Vertex AI. AML triage "
     "that cannot say what it cannot cite, and knows how old its evidence is."),
]


def spoken(text: str) -> str:
    for k, v in SAY.items():
        text = text.replace(k, v)
    return text
