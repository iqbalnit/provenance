from datetime import UTC, datetime

import pytest

from provenance.data import ofac, personas
from provenance.tools.watchlist import SdnEntry, WatchlistSnapshot, check_name

NOW = datetime(2026, 10, 4, tzinfo=UTC)


def snap(entries, as_of):
    return WatchlistSnapshot("OFAC SDN", "x", as_of, tuple(entries))


OLD = [SdnEntry("100", "KNOWN TRADING LLC", "", "SDGT"), SdnEntry("101", "OLDHAND, Viktor", "individual", "RUSSIA")]
NEW = [SdnEntry("200", "FRESHLY DESIGNATED HOLDINGS", "", "RUSSIA-EO14024"),
       SdnEntry("201", "NEWNAME, Aleksandr Petrovich", "individual", "RUSSIA-EO14024"),
       SdnEntry("202", "EXAMPLE VESSEL", "vessel", "IRAN")]
ARCHIVED = snap(OLD, datetime(2024, 3, 29, tzinfo=UTC))
LIVE = snap(OLD + NEW, datetime(2026, 10, 4, tzinfo=UTC))


def alerts():
    out = []
    for i in range(30):
        out.append({"alert_id": f"alt_{i:03d}", "account_id": f"acct{i}", "rule": "structuring" if i % 3 == 0 else "rapid_movement",
                    "split": "golden" if i < 10 else "eval", "truly_suspicious": i in (1, 15), "txn_ids": []})
    return out


@pytest.fixture(autouse=True)
def small_cohorts(monkeypatch):
    monkeypatch.setattr(personas, "N_NEW", 2)
    monkeypatch.setattr(personas, "N_OLD", 1)
    monkeypatch.setattr(personas, "GOLDEN_LINKS", {"new": 1, "old": 1})


def test_diff_lists_only_new_designations():
    assert [e.ent_num for e in ofac.new_designations(ARCHIVED, LIVE)] == ["200", "201", "202"]


def test_build_links_labels_and_hero():
    out, customers, manifest = personas.build(alerts(), ARCHIVED, LIVE, hero="201", now=NOW)
    linked = {x["account_id"]: x for x in manifest["linked"]}
    assert len(linked) == 3 and {x["cohort"] for x in linked.values()} == {"new", "old"}
    hero = next(x for x in manifest["linked"] if x["hero"])
    assert hero["ent_num"] == "201" and hero["split"] == "golden"
    hero_alert = next(a for a in out if a["alert_id"] == hero["alert_id"])
    assert hero_alert["rule"] == "structuring"
    assert hero_alert["truly_suspicious"] and hero_alert["label_source"] == "sanctions_exposure"
    assert hero_alert["designated_after_archive"] is True
    # never links an alert SAML-D already labels suspicious; vessels are never personas
    assert all(not a["truly_suspicious"] for a in alerts() if a["account_id"] in linked)
    assert "202" not in {x["ent_num"] for x in manifest["linked"]}
    # unlinked labels untouched
    assert sum(a["truly_suspicious"] for a in out) == 2 + 3
    # hero name screens as a hit on live, a miss on archived: the reversal on real names
    name = customers[hero["account_id"]]["name"]
    assert name == "Aleksandr Petrovich NEWNAME"
    assert check_name(name, LIVE, retrieved_at=NOW).sanctions_or_pep_hit
    assert not check_name(name, ARCHIVED, retrieved_at=NOW).sanctions_or_pep_hit


def test_synthetic_customers_never_match_the_live_list_and_are_deterministic():
    out1, c1, _ = personas.build(alerts(), ARCHIVED, LIVE, now=NOW)
    out2, c2, _ = personas.build(alerts(), ARCHIVED, LIVE, now=NOW)
    assert c1 == c2 and out1 == out2
    linked = {a["account_id"] for a in out1 if a["label_source"] == "sanctions_exposure"}
    for acct, prof in c1.items():
        if acct not in linked:
            assert not check_name(prof["name"], LIVE, retrieved_at=NOW).sanctions_or_pep_hit
            assert {"occupation", "expected_monthly_volume", "source_of_funds", "kyc_reviewed_at"} <= set(prof)


def test_hero_must_be_a_new_designation():
    with pytest.raises(SystemExit):
        personas.build(alerts(), ARCHIVED, LIVE, hero="100", now=NOW)


def test_load_any_local_path_takes_as_of_from_folder(tmp_path):
    p = tmp_path / "2024-03-29" / "sdn.csv"
    p.parent.mkdir()
    p.write_text('100,"KNOWN TRADING LLC","-0-","SDGT"\n')
    s = ofac.load_any(str(p))
    assert s.as_of == datetime(2024, 3, 29, tzinfo=UTC) and len(s.entries) == 1
