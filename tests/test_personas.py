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


def test_alerts_schema_covers_every_persona_key_and_ids_are_strings():
    from provenance.data.alerts import ALERTS_SCHEMA
    from provenance.runtime import _plain

    out, _, _ = personas.build(alerts(), ARCHIVED, LIVE, now=NOW)
    cols = {n for n, _, _ in ALERTS_SCHEMA}
    assert set().union(*(a.keys() for a in out)) <= cols
    assert {n: t for n, t, _ in ALERTS_SCHEMA}["account_id"] == "STRING"
    row = _plain({"alert_id": "a", "account_id": 1234567, "sdn_ent_num": 99, "txn_ids": [1, "t2"]})
    assert row["account_id"] == "1234567" and row["sdn_ent_num"] == "99" and row["txn_ids"] == ["1", "t2"]


def test_rerun_is_idempotent():
    out1, c1, m1 = personas.build(alerts(), ARCHIVED, LIVE, now=NOW)
    out2, c2, m2 = personas.build(out1, ARCHIVED, LIVE, now=NOW)
    assert out2 == out1 and c2 == c1 and m2 == m1
    assert sum(a["truly_suspicious"] for a in out2) == sum(a["truly_suspicious"] for a in out1)


def test_institutions_excluded_and_default_hero_is_an_individual(monkeypatch):
    live = snap(OLD + NEW + [SdnEntry("300", "DIRECTORATE OF INTELLIGENCE OF EXAMPLELAND", "", "X")], LIVE.as_of)
    _, _, manifest = personas.build(alerts(), ARCHIVED, live, now=NOW)
    assert "300" not in {x["ent_num"] for x in manifest["linked"]}
    hero = next(x for x in manifest["linked"] if x["hero"])
    assert hero["ent_num"] == "201"  # the only new individual
    with pytest.raises(SystemExit):
        personas.build(alerts(), ARCHIVED, live, hero="300", now=NOW)


def test_hero_gets_the_smallest_structuring_alert():
    rows = alerts()
    for a in rows:
        a["txn_ids"] = [f"t{j}" for j in range(10 + int(a["alert_id"][-3:]))]
    rows[9]["txn_ids"] = ["t1", "t2", "t3", "t4"]  # alt_009: golden, structuring (9 % 3 == 0), benign
    _, _, manifest = personas.build(rows, ARCHIVED, LIVE, now=NOW)
    assert next(x for x in manifest["linked"] if x["hero"])["alert_id"] == "alt_009"


def test_declared_volume_comes_from_pre_alert_history(tmp_path):
    csv_path = tmp_path / "s.csv"
    head = "Time,Date,Sender_account,Receiver_account,Amount,Payment_currency,Received_currency," \
           "Sender_bank_location,Receiver_bank_location,Payment_type,Is_laundering,Laundering_type\n"
    rows = [f"10:00:00,2022-{m:02d}-05,999,acct0,9000,UK pounds,UK pounds,UK,UK,Cash Deposit,0,Normal\n"
            for m in (1, 2, 3)]
    rows.append("10:00:00,2022-04-02,999,acct0,500000,UK pounds,UK pounds,UK,UK,Cash Deposit,0,Normal\n")  # in window
    csv_path.write_text(head + "".join(rows))
    al = [{"account_id": "acct0", "window_start": "2022-04-01T00:00:00"},
          {"account_id": "acct1", "window_start": "2022-04-01T00:00:00"}]
    base = personas.baseline_monthly(csv_path, al)
    assert set(base) == {"acct0"}  # acct1 has no history
    assert 5_000 < base["acct0"] < 15_000  # the in-window 500k never sets the baseline
    assert personas.volume_band(base["acct0"]) == "5,000-15,000"
    assert personas.volume_band(300_000) == "250,000-1,000,000"
    prof = personas.profile("acct0", "X", "person", NOW, base["acct0"])
    assert prof["expected_monthly_volume"] == "5,000-15,000"
