# Data

Nothing in `data/raw/` or `data/snapshots/` is committed (see `.gitignore`).
Commit loader scripts, not datasets. **Check the licences on SAML-D and IBM AML before anything touches the public repo.**

| Layer | Source | Where it lands |
|---|---|---|
| Transactions | SAML-D (Kaggle `berkanoztas/synthetic-transaction-monitoring-dataset-aml`). Use a sample, not all 9.5M rows | BigQuery `provenance.transactions`, partitioned by `booking_date`, clustered by `account_id` |
| Alerts | `provenance/rules/engine.py` run over the sample | BigQuery `provenance.alerts` with `truly_suspicious` label |
| Watchlist | OFAC SDN `sdn.csv`: **two snapshots**, archived (Wayback capture 2024-03-29, ~30 months old) and live | `gs://<bucket>/ofac/<as_of>/sdn.csv` |
| Adverse media | Live: Google Search grounding. Reproducible: DOJ/SEC press releases | GCS for the offline copies |
| KYC | 50 Gemini-generated onboarding PDFs, **every page watermarked "SYNTHETIC — generated for demonstration"** | `gs://<bucket>/kyc/` |

## Hero persona (pick by Sun Sep 27)

This must be a real OFAC designation dated **after** the archived snapshot and present in the live one.
Link it to one synthetic SAML-D account whose alerts are otherwise benign-looking.
Record the SDN entry number, designation date and press-release URL here once chosen.
Persona linkage: join ~10 synthetic customers to real SDN names and ~10 to DOJ/SEC enforcement subjects, or grounding returns nothing.
