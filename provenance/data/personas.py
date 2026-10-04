"""Customer identities for alerted accounts, with a small set linked to real OFAC SDN entries.

    python -m provenance.data.personas [--hero ENT_NUM] [--upload]

Why this exists
---------------
SAML-D transactions are synthetic and carry no names, and their laundering labels
know nothing about sanctions. Without names the watchlist and adverse-media agents
have nothing to check, and the staleness thesis cannot show up in the eval.

What it does
------------
1. Gives every alerted account a deterministic synthetic customer profile. Each
   synthetic name is checked against the live SDN list and regenerated if it
   could match, so no synthetic customer is an accidental hit.
2. Links a small, documented set of accounts on benign-looking alerts (SAML-D
   label false) to real SDN names:
     new  designated after the archived snapshot: the staleness thesis
     old  on both lists: a control that must escalate in every arm
   One "new" persona is the hero, placed on a golden structuring alert.
   Structuring alerts require transactions + watchlist + KYC but not adverse
   media, so the hero's outcome isolates the freshness of the watchlist itself.
3. Augments labels honestly: a linked alert becomes truly_suspicious with
   label_source="sanctions_exposure" (a sanctions match is reportable whatever
   the transaction pattern). All other labels stay as SAML-D defines them.

Outputs: artifacts/customers.json (-> gs://<bucket>/kyc/customers.json),
artifacts/alerts.jsonl (rewritten; -> BigQuery `alerts`), artifacts/personas.json.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path

from provenance.tools.watchlist import PARTIAL_MATCH_THRESHOLD, SdnEntry, WatchlistSnapshot, _score, _tokens

ARTIFACTS = Path("artifacts")
N_NEW, N_OLD = 10, 4
GOLDEN_LINKS = {"new": 4, "old": 1}  # how many of each land in the golden split (hero included in "new")

FIRST = ["Aarav", "Bianca", "Chen", "Dmitri", "Elena", "Farah", "Gabriel", "Hana", "Ivan", "Jasmine", "Kofi",
         "Leila", "Mateo", "Nadia", "Oliver", "Priya", "Quentin", "Rosa", "Samuel", "Tara", "Umar", "Vera",
         "William", "Ximena", "Yusuf", "Zara", "Arjun", "Beatrix", "Callum", "Daria", "Emeka", "Freya"]
LAST = ["Whitfield", "Okonkwo", "Lindqvist", "Marchetti", "Haddad", "Fairbanks", "Novak", "Castellano",
        "Pemberton", "Achebe", "Sorensen", "Takahashi", "Delacroix", "Mbeki", "Grantham", "Oyelaran",
        "Vasquez", "Thornbury", "Kowalczyk", "Ashworth", "Brennan", "Fitzgerald", "Hollister", "Iverson"]
BIZ_A = ["Northgate", "Riverside", "Bluebell", "Kestrel", "Harbourline", "Meadowbrook", "Silverleaf",
         "Copperfield", "Juniper", "Oakhurst", "Larkspur", "Westmere", "Cobalt", "Thistle", "Ambergate"]
BIZ_B = ["Trading", "Logistics", "Catering", "Motors", "Textiles", "Pharmacy", "Builders", "Imports",
         "Florists", "Electrical", "Bakery", "Couriers", "Interiors", "Hardware", "Opticians"]
BIZ_C = ["Ltd", "LLP", "& Co", "Group", "Holdings"]
OCCUPATIONS = {"person": ["Software engineer", "Nurse", "Self-employed electrician", "Teacher", "Retail manager",
                          "Accountant", "Taxi driver", "Pharmacist", "Restaurant owner", "Consultant"],
               "business": ["Retail (cash-intensive)", "Wholesale trading", "Logistics", "Hospitality",
                            "Construction", "Import/export", "Professional services"]}
VOLUMES = ["2,000-5,000", "5,000-15,000", "15,000-40,000", "40,000-100,000"]
FUNDS = {"person": ["Salary", "Self-employment income", "Pension", "Savings"],
         "business": ["Trading revenue", "Contract income", "Retail sales"]}


def _h(*parts: str) -> int:
    return int(hashlib.sha256("|".join(parts).encode()).hexdigest()[:12], 16)


def _pick(seq: list, *parts: str):
    return seq[_h(*parts) % len(seq)]


class SdnIndex:
    """Token index over a snapshot so name checks don't scan 19k entries each time."""

    def __init__(self, snap: WatchlistSnapshot) -> None:
        self.by_token: dict[str, list[frozenset[str]]] = defaultdict(list)
        for e in snap.entries:
            t = _tokens(e.name)
            for tok in t:
                self.by_token[tok].append(t)

    def could_match(self, name: str) -> bool:
        q = _tokens(name)
        seen = {c for tok in q for c in self.by_token.get(tok, [])}
        return any(_score(q, c) >= PARTIAL_MATCH_THRESHOLD for c in seen)


def synthetic_name(account: str, index: SdnIndex) -> tuple[str, str]:
    kind = "business" if _h(account, "kind") % 3 == 0 else "person"
    for salt in range(50):
        s = str(salt)
        name = (f"{_pick(BIZ_A, account, s, 'a')} {_pick(BIZ_B, account, s, 'b')} {_pick(BIZ_C, account, s, 'c')}"
                if kind == "business" else f"{_pick(FIRST, account, s, 'f')} {_pick(LAST, account, s, 'l')}")
        if not index.could_match(name):
            return kind, name
    raise RuntimeError(f"could not find a non-matching synthetic name for {account}")


def profile(account: str, name: str, kind: str, now: datetime) -> dict:
    reviewed = now - timedelta(days=30 + _h(account, "rev") % 300)
    return {
        "name": name,
        "occupation": _pick(OCCUPATIONS[kind], account, "occ"),
        "expected_monthly_volume": _pick(VOLUMES, account, "vol"),
        "source_of_funds": _pick(FUNDS[kind], account, "funds"),
        "country": "UK",
        "kyc_reviewed_at": reviewed.replace(microsecond=0).isoformat(),
    }


def display_name(e: SdnEntry) -> str:
    """'SURNAME, Given' (SDN individual format) -> 'Given SURNAME'; entities unchanged."""
    if e.sdn_type == "individual" and "," in e.name:
        last, first = e.name.split(",", 1)
        return f"{first.strip()} {last.strip()}"
    return e.name


INSTITUTIONAL = ("DIRECTORATE", "MINISTRY", "GOVERNMENT", "ARMED FORCES", "CENTRAL BANK", "INTELLIGENCE",
                 "REVOLUTIONARY GUARD", "NAVY", "ARMY", "AIR FORCE", "PARTY", "COMMITTEE")


def _institutional(name: str) -> bool:
    """State bodies are not plausible retail-bank customers, so they never become personas."""
    up = name.upper()
    return any(w in up for w in INSTITUTIONAL)


def _usable(e: SdnEntry) -> bool:
    return (2 <= len(_tokens(e.name)) <= 6 and e.sdn_type in {"individual", ""}  # skip vessels/aircraft
            and not _institutional(e.name))


def choose_sdn(archived: WatchlistSnapshot, live: WatchlistSnapshot, hero: str | None) -> tuple[list, list]:
    old_nums = {e.ent_num for e in archived.entries}
    new = sorted((e for e in live.entries if e.ent_num not in old_nums and _usable(e)), key=lambda e: _h(e.ent_num, "new"))
    old = sorted((e for e in live.entries if e.ent_num in old_nums and _usable(e)), key=lambda e: _h(e.ent_num, "old"))
    if hero:
        match = [e for e in new if e.ent_num == hero]
        if not match:
            raise SystemExit(f"--hero {hero} is not a usable new designation (absent from archived, present in "
                             f"live, an individual or company, not a state body)")
    else:  # default hero: a private individual is the most plausible retail customer
        match = [e for e in new if e.sdn_type == "individual"][:1] or new[:1]
    new = match + [e for e in new if e not in match]
    return new[:N_NEW], old[:N_OLD]


def link(alerts: list[dict], new: list, old: list) -> dict[str, dict]:
    """account_id -> {entry, cohort, hero}. Benign alerts only; hero on a golden structuring alert."""
    benign = sorted((a for a in alerts if not a["truly_suspicious"]), key=lambda a: _h(a["alert_id"], "link"))
    by_split = defaultdict(list)
    for a in benign:
        by_split[a["split"]].append(a)
    used: set[str] = set()
    plan: dict[str, dict] = {}

    def take(split: str, prefer_rule: str | None = None) -> dict:
        pool = by_split[split] or [a for v in by_split.values() for a in v]
        for want in ([prefer_rule] if prefer_rule else []) + [None]:
            for a in pool:
                if a["account_id"] not in used and (want is None or a["rule"] == want):
                    used.add(a["account_id"])
                    return a
        raise RuntimeError("not enough benign alerts to link")

    hero_alert = take("golden", prefer_rule="structuring")
    plan[hero_alert["account_id"]] = {"entry": new[0], "cohort": "new", "hero": True, "alert_id": hero_alert["alert_id"]}
    for i, e in enumerate(new[1:], start=1):
        a = take("golden" if i < GOLDEN_LINKS["new"] else "eval")
        plan[a["account_id"]] = {"entry": e, "cohort": "new", "hero": False, "alert_id": a["alert_id"]}
    for i, e in enumerate(old):
        a = take("golden" if i < GOLDEN_LINKS["old"] else "eval")
        plan[a["account_id"]] = {"entry": e, "cohort": "old", "hero": False, "alert_id": a["alert_id"]}
    return plan


def build(alerts: list[dict], archived: WatchlistSnapshot, live: WatchlistSnapshot,
          hero: str | None = None, now: datetime | None = None) -> tuple[list[dict], dict, dict]:
    now = now or datetime.now(UTC)
    # Idempotent re-runs: undo a previous linkage first. Only SAML-D-benign alerts are ever linked,
    # so the original label of a sanctions_exposure alert is False.
    alerts = [
        {**{k: v for k, v in a.items() if k not in {"label_source", "sdn_ent_num", "designated_after_archive"}},
         **({"truly_suspicious": False} if a.get("label_source") == "sanctions_exposure" else {})}
        for a in alerts
    ]
    index = SdnIndex(live)
    new, old = choose_sdn(archived, live, hero)
    plan = link(alerts, new, old)
    customers: dict[str, dict] = {}
    for acct in sorted({a["account_id"] for a in alerts}):
        if acct in plan:
            e = plan[acct]["entry"]
            kind = "person" if e.sdn_type == "individual" else "business"
            customers[acct] = profile(acct, display_name(e), kind, now)
        else:
            kind, name = synthetic_name(acct, index)
            customers[acct] = profile(acct, name, kind, now)
    out_alerts = []
    for a in alerts:
        a = {k: v for k, v in a.items() if k not in {"label_source", "sdn_ent_num", "designated_after_archive"}}
        link_ = plan.get(a["account_id"])
        a["label_source"] = "saml_d"
        a["sdn_ent_num"] = None
        a["designated_after_archive"] = None
        if link_:
            a["truly_suspicious"] = True
            a["label_source"] = "sanctions_exposure"
            a["sdn_ent_num"] = link_["entry"].ent_num
            a["designated_after_archive"] = link_["cohort"] == "new"
        out_alerts.append(a)
    manifest = {
        "archived_as_of": archived.as_of.isoformat(), "live_as_of": live.as_of.isoformat(),
        "linked": [
            {"account_id": acct, "alert_id": v["alert_id"], "cohort": v["cohort"], "hero": v["hero"],
             "ent_num": v["entry"].ent_num, "sdn_name": v["entry"].name, "program": v["entry"].program,
             "split": next(a["split"] for a in alerts if a["alert_id"] == v["alert_id"])}
            for acct, v in plan.items()
        ],
    }
    return out_alerts, customers, manifest


def main() -> None:
    from provenance.data import ofac  # noqa: PLC0415

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--alerts", type=Path, default=ARTIFACTS / "alerts.jsonl")
    ap.add_argument("--hero", help="ent_num of the hero (must be a new designation); default: deterministic pick")
    ap.add_argument("--archived-ref")
    ap.add_argument("--live-ref")
    ap.add_argument("--upload", action="store_true", help="customers.json -> GCS, alerts -> BigQuery")
    a = ap.parse_args()
    archived_ref, live_ref = ofac._refs(a)
    archived, live = ofac.load_any(archived_ref), ofac.load_any(live_ref)
    alerts = [json.loads(line) for line in a.alerts.read_text().splitlines() if line.strip()]
    out_alerts, customers, manifest = build(alerts, archived, live, a.hero)

    a.alerts.write_text("".join(json.dumps(x) + "\n" for x in out_alerts))
    (ARTIFACTS / "customers.json").write_text(json.dumps(customers, indent=1))
    (ARTIFACTS / "personas.json").write_text(json.dumps(manifest, indent=2))
    hero = next(x for x in manifest["linked"] if x["hero"])
    by_split = defaultdict(lambda: [0, 0])
    for x in out_alerts:
        by_split[x["split"]][0] += 1
        by_split[x["split"]][1] += bool(x["truly_suspicious"])
    print(f"customers: {len(customers)}; linked to SDN: {len(manifest['linked'])} "
          f"({sum(x['cohort'] == 'new' for x in manifest['linked'])} new, "
          f"{sum(x['cohort'] == 'old' for x in manifest['linked'])} old)")
    print(f"HERO: {hero['sdn_name']} (#{hero['ent_num']}, {hero['program']}) on alert {hero['alert_id']} "
          f"[{hero['split']}], account {hero['account_id']}")
    print("alerts / suspicious by split:", {k: tuple(v) for k, v in by_split.items()})
    if a.upload:
        from google.cloud import storage  # noqa: PLC0415

        from provenance import config  # noqa: PLC0415
        from provenance.data import alerts as alerts_mod  # noqa: PLC0415

        blob = storage.Client(project=config.project()).bucket(config.gcs_bucket()).blob("kyc/customers.json")
        blob.upload_from_filename(str(ARTIFACTS / "customers.json"), content_type="application/json")
        print(f"uploaded gs://{config.gcs_bucket()}/kyc/customers.json")
        print(f"loaded into {alerts_mod.upload(a.alerts)}")


if __name__ == "__main__":
    main()
