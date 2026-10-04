import csv
import re

from provenance.data.saml_d import BQ_SCHEMA, keep_benign, sample, to_account_rows
from provenance.tools.bq_templates import TEMPLATES
from tests.saml_d_fixture import build


def test_sampling_keeps_all_laundering_and_is_deterministic(tmp_path):
    raw = build(tmp_path / "raw.csv")
    s1 = sample(raw, tmp_path / "s1.csv", benign_frac=0.1)
    s2 = sample(raw, tmp_path / "s2.csv", benign_frac=0.1)
    assert (tmp_path / "s1.csv").read_text() == (tmp_path / "s2.csv").read_text()
    assert s1 == s2
    assert s1["laundering_rows_out"] == 12  # 4 accounts x 3 deposits, all kept
    assert s1["rows_out"] < s1["rows_in"]
    with open(tmp_path / "s1.csv") as f:
        ids = [r["Txn_id"] for r in csv.DictReader(f)]
    assert len(ids) == len(set(ids)) and all(i.startswith("t") for i in ids)


def test_keep_benign_bounds():
    assert not keep_benign("x", 0.0)
    assert keep_benign("x", 1.0)


def test_account_rows_match_schema_and_templates(tmp_path):
    raw = build(tmp_path / "raw.csv", 1, 0, 0)
    sample(raw, tmp_path / "s.csv", benign_frac=0.0)
    with open(tmp_path / "s.csv") as f:
        r = next(csv.DictReader(f))
    debit, credit = to_account_rows(r)
    cols = [n for n, _ in BQ_SCHEMA]
    assert set(debit) == set(credit) == set(cols)
    assert (debit["direction"], credit["direction"]) == ("debit", "credit")
    assert debit["account_id"] == credit["counterparty_account"]
    # Every column a BigQuery template selects or filters on must exist in the table.
    for t in TEMPLATES.values():
        used = set(re.findall(r"\b([a-z_]+)\b", t.sql)) & {
            "booking_date", "amount", "currency", "direction", "counterparty_account",
            "payment_type", "account_id", "ts", "txn_id",
        }
        assert used <= set(cols), (t.id, used - set(cols))
