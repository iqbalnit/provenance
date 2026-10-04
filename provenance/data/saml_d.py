"""Sample SAML-D and load it into BigQuery as account-perspective rows.

Download the raw CSV from Kaggle (berkanoztas/synthetic-transaction-monitoring-dataset-aml)
into data/raw/ first; the dataset is not committed.

    python -m provenance.data.saml_d sample --input data/raw/SAML-D.csv
    python -m provenance.data.saml_d upload            # needs the gcp extra + ADC

Sampling keeps every account that touches a laundering transaction, plus a
deterministic hash-sample of benign accounts, then keeps every transaction
where either side is a kept account. Streams the file; never loads 9.5M rows.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

RAW_COLUMNS = [
    "Time", "Date", "Sender_account", "Receiver_account", "Amount",
    "Payment_currency", "Received_currency", "Sender_bank_location",
    "Receiver_bank_location", "Payment_type", "Is_laundering", "Laundering_type",
]
SAMPLE_PATH = Path("data/raw/saml_d_sample.csv")
ROWS_PATH = Path("data/raw/transactions.ndjson")

# Account-perspective table queried by provenance/tools/bq_templates.py.
BQ_SCHEMA = [
    ("txn_id", "STRING"), ("account_id", "STRING"), ("booking_date", "DATE"),
    ("ts", "TIMESTAMP"), ("amount", "NUMERIC"), ("currency", "STRING"),
    ("direction", "STRING"), ("counterparty_account", "STRING"),
    ("payment_type", "STRING"), ("sender_location", "STRING"),
    ("receiver_location", "STRING"), ("is_laundering", "BOOL"),
    ("laundering_type", "STRING"),
]


def _is_laundering(row: dict) -> bool:
    return str(row["Is_laundering"]).strip() in {"1", "True", "true"}


def keep_benign(account: str, frac: float) -> bool:
    h = int(hashlib.sha256(account.encode()).hexdigest()[:8], 16)
    return h / 0xFFFFFFFF < frac


def _read(path: Path) -> Iterator[tuple[int, dict]]:
    with open(path, newline="", encoding="utf-8") as f:
        yield from enumerate(csv.DictReader(f))


def sample(input_path: Path, output_path: Path = SAMPLE_PATH, benign_frac: float = 0.02) -> dict:
    laundering_accounts: set[str] = set()
    for _, r in _read(input_path):
        if _is_laundering(r):
            laundering_accounts.update((r["Sender_account"], r["Receiver_account"]))

    def kept(a: str) -> bool:
        return a in laundering_accounts or keep_benign(a, benign_frac)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    n_in = n_out = n_laundering = 0
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["Txn_id", *RAW_COLUMNS])
        w.writeheader()
        for idx, r in _read(input_path):
            n_in += 1
            if kept(r["Sender_account"]) or kept(r["Receiver_account"]):
                w.writerow({"Txn_id": f"t{idx}", **{c: r[c] for c in RAW_COLUMNS}})
                n_out += 1
                n_laundering += _is_laundering(r)
    return {
        "rows_in": n_in,
        "rows_out": n_out,
        "laundering_rows_out": n_laundering,
        "laundering_accounts": len(laundering_accounts),
        "benign_frac": benign_frac,
    }


def to_account_rows(r: dict) -> list[dict]:
    """One debit row for the sender and one credit row for the receiver."""
    ts = datetime.fromisoformat(f"{r['Date']}T{r['Time']}")
    common = {
        "txn_id": r["Txn_id"],
        "booking_date": ts.date().isoformat(),
        "ts": ts.isoformat(),
        "amount": str(r["Amount"]),
        "payment_type": r["Payment_type"],
        "sender_location": r["Sender_bank_location"],
        "receiver_location": r["Receiver_bank_location"],
        "is_laundering": _is_laundering(r),
        "laundering_type": r["Laundering_type"],
    }
    return [
        {**common, "account_id": r["Sender_account"], "direction": "debit",
         "counterparty_account": r["Receiver_account"], "currency": r["Payment_currency"]},
        {**common, "account_id": r["Receiver_account"], "direction": "credit",
         "counterparty_account": r["Sender_account"], "currency": r["Received_currency"]},
    ]


def write_account_rows(sample_path: Path = SAMPLE_PATH, out: Path = ROWS_PATH) -> int:
    n = 0
    with open(out, "w", encoding="utf-8") as f:
        for _, r in _read(sample_path):
            for row in to_account_rows(r):
                f.write(json.dumps(row) + "\n")
                n += 1
    return n


def upload(rows_path: Path = ROWS_PATH, table: str = "transactions") -> str:
    from google.cloud import bigquery  # noqa: PLC0415

    from provenance import config  # noqa: PLC0415

    client = bigquery.Client(project=config.project())
    table_id = f"{config.bq_dataset()}.{table}"
    job_config = bigquery.LoadJobConfig(
        source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
        schema=[bigquery.SchemaField(n, t) for n, t in BQ_SCHEMA],
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
        time_partitioning=bigquery.TimePartitioning(field="booking_date"),
        clustering_fields=["account_id"],
    )
    with open(rows_path, "rb") as f:
        client.load_table_from_file(f, table_id, job_config=job_config).result()
    return table_id


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sample")
    s.add_argument("--input", type=Path, required=True)
    s.add_argument("--output", type=Path, default=SAMPLE_PATH)
    s.add_argument("--benign-frac", type=float, default=0.02)
    u = sub.add_parser("upload")
    u.add_argument("--sample", type=Path, default=SAMPLE_PATH)
    a = ap.parse_args()
    if a.cmd == "sample":
        print(json.dumps(sample(a.input, a.output, a.benign_frac), indent=2))
    else:
        n = write_account_rows(a.sample)
        print(f"wrote {n} account rows; loaded into {upload()}")


if __name__ == "__main__":
    main()
