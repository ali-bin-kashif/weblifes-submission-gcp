# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Purpose

Take-home assessment for a Data & AI Engineer – GCP role at Weblife. Three deliverables:
1. **Gmail → BigQuery ingestion pipeline** (Deliverable 1 — in progress)
2. **Automated data quality checks** with quarantine table (Deliverable 2 — not started)
3. **Plain-English chatbot over BigQuery** using Streamlit + Claude API (Deliverable 3 — not started)

## Running the Pipeline Locally

```bash
# From repo root
cd gmail_bigquery_ingestion_pipeline
python -m utils.pipeline
```

Copy `.env.example` to `.env` and fill in values before running. The `.env` file is gitignored.

## Project Structure

```
gmail_bigquery_ingestion_pipeline/
    main.py              # Cloud Function HTTP entry point (calls pipeline.run)
    utils/
        config.py        # Config dataclass — all env vars loaded via python-dotenv
        gmail_reader.py  # IMAP client; returns EmailFetchResult (latest matched email)
        attachment_parser.py  # CSV bytes → pandas DataFrame (all str, no type casting)
        bq_loader.py     # BigQueryLoader: ensure_table, idempotency check, load
        pipeline.py      # Orchestrator: fetch → idempotency check → parse → load
        date_helpers.py  # parse_date_from_subject / parse_date_from_filename
        logging_config.py
```

## Architecture Decisions

**Two-stage email filtering**: IMAP `SUBJECT` search (server-side substring, fast) → Python regex exact match client-side. Both patterns are configurable via `GMAIL_SUBJECT_FILTER` (IMAP substring) and `GMAIL_SUBJECT_PATTERN` (full regex). Among all matches, the email with the latest `Date` header is selected.

**Raw schema is all-STRING**: No type coercion at the landing layer. `bq_loader.py::RAW_SCHEMA` declares all 17 source columns as `STRING`. Metadata columns use native Python types so PyArrow maps them correctly: `datetime` → `TIMESTAMP`, `date` → `DATE`, `str` → `STRING`. Do not store metadata as formatted strings.

**Idempotency**: Before parsing the CSV, `is_already_ingested(csv_filename)` queries `_source_filename` in BigQuery. Returns `False` (not ingested) if the table doesn't exist yet, so the first-ever run works without special handling.

**Auth**: Local dev uses `GOOGLE_APPLICATION_CREDENTIALS` pointing to a service account JSON. On GCP Cloud Functions, leave it unset — the client falls back to ADC/Workload Identity automatically.

**Deployment target**: Google Cloud Functions (2nd gen), HTTP trigger, invoked by Cloud Scheduler. Not Docker/Cloud Run.

## Key Environment Variables

| Variable | Default | Notes |
|---|---|---|
| `GMAIL_HOST` | `imap.gmail.com` | |
| `GMAIL_PORT` | `993` | |
| `GMAIL_EMAIL` | — | Gmail address |
| `GMAIL_APP_PASSWORD` | — | 16-char app password |
| `GMAIL_SUBJECT_FILTER` | `[E-Com] Daily Sales Export` | IMAP substring search |
| `GMAIL_SUBJECT_PATTERN` | `^\[E-Com\] Daily Sales Export\s*[–-]\s*\d{4}-\d{2}-\d{2}$` | Full regex |
| `GMAIL_CSV_PATTERN` | `^e_com_sales_\d{8}\.csv$` | Attachment filename regex |
| `GOOGLE_APPLICATION_CREDENTIALS` | — | Path to service account JSON; omit on GCP |
| `BQ_PROJECT_ID` | — | GCP project |
| `BQ_DATASET_ID` | — | BigQuery dataset (e.g. `raw`) |
| `BQ_RAW_TABLE` | `raw_orders` | BigQuery table name |

## BigQuery Raw Table Schema

Source columns: `order_id`, `order_date`, `customer_id`, `customer_name`, `customer_email`, `customer_city`, `customer_state`, `product_name`, `product_category`, `quantity`, `unit_price`, `discount_amount`, `revenue`, `store_name`, `shipping_method`, `shipping_status`, `payment_method` — all `STRING`.

Metadata: `_ingested_at` (TIMESTAMP), `_source_filename` (STRING), `_pipeline_run_date` (DATE, partition key), `email_received_date` (STRING).

Table is partitioned DAY on `_pipeline_run_date`.