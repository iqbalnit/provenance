"""Words on the deck, kept apart from layout so they can be edited without touching geometry.

`**text**` marks a bold run. Keep every claim true on the deployed prototype and in numbers.json.
"""

TEAM_NAME = "Provenance"
PROBLEM = ("BFSI: AML alert triage. Transaction monitoring flags far more innocent activity than "
           "crime, and analysts clear each alert by hand.")

IDEA_HEADLINE = "An AML triage agent that cannot say what it cannot cite, and knows how old its evidence is"
IDEA_BODY = [
    "**The problem.** Rule engines flag thousands of alerts and almost all are false positives. "
    "An LLM could clear them, but a fluent, uncited answer is not something a compliance team can defend.",
    "**What Provenance does.** A multi-agent graph on Gemini gathers evidence from transactions, KYC, "
    "sanctions lists and the web. Every fact goes into a claim ledger with its source and two timestamps.",
    "**Why it is safe to automate.** Deterministic code, not the model, decides. It rejects any uncited "
    "sentence, applies a six-condition auto-close gate and escalates when evidence is past its freshness SLA.",
]

OPPORTUNITIES_HEADLINE = "Most AI triage tools summarise; Provenance has to prove each sentence"
OPPORTUNITIES = [
    ("How it is different", [
        "Others ask a model for a verdict. We let code decide, from evidence the model had to cite.",
        "Each claim carries **two clocks**: when the publisher says it was true and when we fetched it.",
        "Escalation is a designed success path, not a failure.",
    ]),
    ("How it solves the problem", [
        "Clears an alert only when all six gate conditions pass, including fresh evidence and no sanctions hit.",
        "Hands everything else to an analyst with the case file already built and a SAR draft (never filed automatically).",
        "A nightly sweep reopens closed cases when the evidence changes.",
    ]),
    ("USP", [
        "**Cannot emit an uncited claim**: a parser, not a judge model, rejects the draft.",
        "**Knows how old its evidence is**: a 30-month-old sanctions list fails the gate before the new designation is even seen.",
        "Measured against plain Gemini on the same alerts.",
    ]),
]

FEATURES_HEADLINE = "Six guarantees, each enforced in code the model cannot talk past"
FEATURES = [
    ("Claim ledger", "Append-only, content-addressed facts in Firestore, each with source, verbatim quote and two timestamps."),
    ("Deterministic verifier", "Every sentence must cite a ledger claim. One uncited sentence rejects the whole draft; max 3 drafts."),
    ("Six-condition gate", "Confidence, mandatory evidence, staleness, citation coverage, no sanctions or PEP hit, typology."),
    ("Two-clock staleness", "Freshness SLAs per evidence type, measured from the publisher's date, not our fetch time."),
    ("Nightly sweep", "Re-checks every auto-closed case against the newest lists and reopens what changed."),
    ("Injection guard", "Screens web results before they reach the model; hostile text is withheld and recorded in the ledger."),
]
FEATURES_FOOTER = ("Also: name-blind typology, analyst review that feeds eval labels, SAR drafts, "
                   "and a five-arm eval against plain Gemini.")

REVERSAL_HEADLINE = "Same alert, same model: only the clock changes the outcome"
REVERSAL_TILES = [
    ("1 · Archived list, fetch-date clock", "AUTO-CLOSE", "All six gate conditions pass. A typical RAG system stops here.", "green"),
    ("2 · Archived list, publisher clock", "ESCALATE", "The list is 30 months past a 3-day SLA, so the staleness condition fails.", "amber"),
    ("3 · Live list", "ESCALATE", "The new designation appears: sanctions hit, case file and SAR draft.", "amber"),
]
REVERSAL_CAPTION = "Labelled demo case with a fictional customer, run by the deployed console."

FUTURE_HEADLINE = "From prototype to a bank's alert queue"
FUTURE = [
    ("Next", [
        "Model Armor in front of all web content by default (adapter built).",
        "PEP and commercial adverse-media sources as new evidence types.",
        "Calibrate the confidence threshold per typology on analyst-reviewed labels.",
    ]),
    ("Production path", [
        "Case-management and SAR-filing integration, with the analyst always signing.",
        "Per-list freshness SLAs and alerting when a feed goes stale.",
        "Model-risk pack: eval arms rerun on every model or prompt change.",
    ]),
]

THANKS = "Thank you"
