# Weblife E-Commerce Data Engineering Assesment

> **Take-Home Assessment — Data & AI Engineer (GCP)**
> End-to-end data platform: Gmail ingestion → BigQuery transformation → plain-English AI chatbot.

---

## Demo & Walkthrough

| | |
|---|---|
| **Video Walkthrough (Loom)** | _[Insert Loom link here]_ |
| **Data Quality Dashboard** | _[Insert dashboard link here]_ |
| **Live Chatbot** | _[Insert Render / Cloud Run URL here]_ |

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Project Structure](#2-project-structure)
3. [Deliverable 1 — Gmail → BigQuery Ingestion Pipeline](#3-deliverable-1--gmail--bigquery-ingestion-pipeline)
4. [Deliverable 2 — Data Quality Checks & Transformations](#4-deliverable-2--data-quality-checks--transformations)
5. [Deliverable 3 — AI Insights Chatbot](#5-deliverable-3--ai-insights-chatbot)
6. [Local Development Setup](#6-local-development-setup)
7. [Deploying to Google Cloud](#7-deploying-to-google-cloud)
8. [Deploying the Chatbot to Render](#8-deploying-the-chatbot-to-render)
9. [Environment Variables Reference](#9-environment-variables-reference)
10. [Alerting System](#10-alerting-system)
11. [What Was Built — Feature Highlights](#11-what-was-built--feature-highlights)
12. [In a Real Production Environment](#12-in-a-real-production-environment)

---

## 1. Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         DAILY AUTOMATED FLOW                            │
│                                                                         │
│   Gmail Inbox          Cloud Function           BigQuery                │
│   ──────────           ──────────────           ────────                │
│   [Sales CSV]  ──────► [Ingest & Validate] ───► [raw_orders]           │
│   (daily email)        (Cloud Scheduler)        (append-only)           │
│                                                      │                  │
│                                                      ▼                  │
│                                                 [stg_orders_cleaned]    │
│                                                 [stg_orders_rejected]   │ (quarantine)
│                                                      │                  │
│                                                      ▼                  │
│                                                 [fct_orders]            │
│                                                 (pre-aggregated mart)   │
└─────────────────────────────────────────────────────────────────────────┘
                                                      │
                                                      ▼
                                         ┌────────────────────┐
                                         │   AI Chatbot        │
                                         │   Chainlit + Claude │
                                         │   (Render / GCP)    │
                                         └────────────────────┘
```

> **Architecture Diagram**
>
> ![Architecture Diagram](docs/images/architecture.png)
> _Insert a draw.io / Lucidchart export here showing the full GCP architecture (Cloud Scheduler → Cloud Functions → BigQuery → Cloud Run)._

---

## 2. Project Structure

```
weblifes-submission-gcp/
│
├── gmail_bigquery_ingestion_pipeline/   # Deliverable 1
│   ├── main.py                          # Cloud Function HTTP entry point
│   ├── requirements.txt
│   └── utils/
│       ├── config.py                    # All env vars via python-dotenv
│       ├── gmail_reader.py              # IMAP client + two-stage filtering
│       ├── attachment_parser.py         # CSV bytes → pandas DataFrame
│       ├── bq_loader.py                 # BigQuery table management & load
│       ├── pipeline.py                  # Orchestrator (fetch → parse → load)
│       ├── alerting.py                  # Gmail SMTP alerts (5 scenarios)
│       ├── date_helpers.py              # Date parsing from subject / filename
│       └── logging_config.py
│
├── bigquery_transformations/            # Deliverable 2
│   ├── create_schema.sql                # DDL for all 4 BigQuery tables
│   ├── data_quality/
│   │   └── dq_checks.sql               # 14 DQ checks (critical / warning / info)
│   ├── sources/
│   │   └── raw_orders.sqlx             # Dataform source declaration
│   ├── staging/
│   │   ├── stg_orders_cleaned.sqlx     # Dedup, type-cast, canonicalize
│   │   └── stg_orders_rejected.sqlx    # Quarantine table
│   └── mart/
│       └── fct_orders.sqlx             # Pre-aggregated daily fact table
│
├── insights_chatbot/                    # Deliverable 3
│   ├── app.py                           # Chainlit entry point
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── .env.example
│   ├── .chainlit/
│   │   └── config.toml                  # Branding & UI settings
│   └── utils/
│       ├── config.py                    # Chatbot env vars
│       ├── llm.py                       # Claude agentic loop + streaming
│       ├── bq_client.py                 # Read-only BigQuery execution
│       └── schema.py                    # Table schema + system prompt
│
├── auth/
│   └── service_account.json             # GCP credentials (gitignored)
│
├── .env                                 # Local secrets (gitignored)
├── render.yaml                          # Render deployment config
└── CLAUDE.md                            # AI coding assistant instructions
```

---

## 3. Deliverable 1 — Gmail → BigQuery Ingestion Pipeline

Fetches the latest daily sales CSV from Gmail, validates it, and loads it into BigQuery. Runs daily via Google Cloud Scheduler → Cloud Functions.

### How It Works

```
Cloud Scheduler (cron)
        │
        ▼
Cloud Function (main.py)
        │
        ├─► gmail_reader.py   ── IMAP search → exact regex match → latest email
        │
        ├─► attachment_parser.py ── CSV bytes → pandas DataFrame (all str)
        │
        ├─► bq_loader.py
        │       ├── ensure_table()          ── create if first run
        │       ├── is_already_ingested()   ── idempotency check by filename
        │       └── load()                  ── PyArrow → BigQuery append
        │
        └─► alerting.py  ── Gmail SMTP alert on each outcome
```

### Key Design Decisions

**Two-stage email filtering**

Emails are first filtered server-side via IMAP `SUBJECT` search (fast, substring match), then a Python regex is applied client-side to rule out partial matches. Both patterns are configurable via env vars.

```python
# Stage 1 — IMAP server-side (fast, permissive)
GMAIL_SUBJECT_FILTER = "[E-Com] Daily Sales Export"

# Stage 2 — Python regex (strict, client-side)
GMAIL_SUBJECT_PATTERN = r"^\[E-Com\] Daily Sales Export\s*[–-]\s*\d{4}-\d{2}-\d{2}$"
```

**Raw schema is all-STRING**

No type coercion at the landing layer. All 17 source columns land as `STRING`. Metadata columns use native Python types so PyArrow maps them correctly. Typing happens in the staging transformation.

**Idempotency**

Before parsing the CSV, the pipeline checks `_source_filename` in BigQuery. If the file is already present, it skips loading and sends an alert. Returns `False` (not ingested) when the table doesn't exist yet — so the very first run works without special handling.

**Credentials**

- **Local dev**: set `GOOGLE_APPLICATION_CREDENTIALS` to the path of your service account JSON
- **GCP Cloud Functions**: leave it unset — the client automatically uses Workload Identity / ADC

### BigQuery Raw Table Schema

| Column | Type | Notes |
|---|---|---|
| `order_id` | STRING | |
| `order_date` | STRING | Raw as-is; cast in staging |
| `customer_id` | STRING | |
| `customer_name` | STRING | |
| `customer_email` | STRING | |
| `customer_city` | STRING | |
| `customer_state` | STRING | |
| `product_name` | STRING | |
| `product_category` | STRING | |
| `quantity` | STRING | |
| `unit_price` | STRING | |
| `discount_amount` | STRING | |
| `revenue` | STRING | |
| `store_name` | STRING | |
| `shipping_method` | STRING | |
| `shipping_status` | STRING | |
| `payment_method` | STRING | |
| `_ingested_at` | TIMESTAMP | Auto-set at load time |
| `_source_filename` | STRING | Used for idempotency check |
| `_pipeline_run_date` | DATE | Partition key (DAY) |
| `_email_received_date` | STRING | From email `Date` header |

---

## 4. Deliverable 2 — Data Quality Checks & Transformations

SQL-based transformation layer using Dataform (`.sqlx` files). Runs daily after ingestion to promote clean data from the raw layer to the analytics mart.

### Transformation Layers

```
raw_orders  (all-STRING, append-only)
     │
     ▼
stg_orders_cleaned  (typed, deduped, canonicalised)
     │
     ├──► stg_orders_rejected  (quarantine: rows that fail DQ)
     │
     ▼
fct_orders  (pre-aggregated daily fact table)
```

### Data Quality Checks

14 checks are defined in `bigquery_transformations/data_quality/dq_checks.sql`, categorised by severity:

**CRITICAL — pipeline is blocked**

| ID | Check | Why |
|---|---|---|
| C1 | Empty batch | Zero rows in today's file |
| C2 | Null `order_id` | Row is untrackable |
| C3 | Null `order_date` | Breaks all time-based reports |
| C4 | Future-dated orders | Clock skew or data-entry error |
| C5 | Null `revenue` | No financial metrics possible |

**WARNING — data lands, investigation needed**

| ID | Check |
|---|---|
| W1 | Exact duplicate rows (source double-send) |
| W2 | Conflicting `order_id` duplicates (retry bug) |
| W3 | Negative quantity |
| W4 | Zero quantity |
| W5 | Revenue mismatch (`qty × price − discount` differs by > $0.02) |
| W6 | Outlier revenue (< $0.01 or > $5,000) |
| W7 | Invalid `customer_state` (not a US 2-letter code) |

**INFO — expected, no action required**

| ID | Check |
|---|---|
| I1 | Null `customer_email` (expected for guest orders) |
| I2 | Malformed email (missing `@`) |

> **Data Quality Dashboard**
>
> ![Data Quality Dashboard](docs/images/dq_dashboard.png)
> _[Insert your Looker Studio / Metabase / BigQuery dashboard screenshot or link here]_

### Staging Transformations (`stg_orders_cleaned`)

1. **Deduplication**: exact duplicates removed; conflicting `order_id`s resolved by keeping the most recent row
2. **Type casting**: `order_date → DATE`, `quantity → INT64`, `unit_price / discount_amount / revenue → NUMERIC`
3. **Canonicalisation**: store names, product names, product categories, and US state codes all mapped to canonical values via regex to handle casing/typo variants
4. **Revenue correction**: if source revenue differs from `qty × price − discount` by more than $0.02, it is recomputed from components and flagged with `_revenue_was_corrected = TRUE`
5. **Quarantine**: rows failing any critical check are written to `stg_orders_rejected` with a pipe-delimited `rejection_reason` column

### Fact Table (`fct_orders`)

Grain: `order_date × store_name × product_category × product_name × shipping_status`

Pre-computed metrics: `total_orders`, `total_units_sold`, `unique_customers`, `total_revenue`, `total_discounts_given`, `discount_rate_pct`

Pre-computed time dimensions: `order_year`, `order_month`, `order_year_month` (YYYY-MM), `order_day_of_week`

Clustered by `store_name`, `product_category` for fast BI queries.

---

## 5. Deliverable 3 — AI Insights Chatbot

A conversational analytics interface built with Chainlit and Claude. Users ask questions in plain English; the agent writes and executes BigQuery SQL, then explains the results conversationally.

> **Chatbot Screenshot**
>
> ![Chatbot UI](docs/images/chatbot_screenshot.png)
> _Chainlit UI showing a sample question and streamed response with SQL query details._

### Features

- **Natural language → SQL**: Claude translates business questions into BigQuery Standard SQL
- **Streaming responses**: answers appear word-by-word as Claude generates them
- **Transparent SQL**: every query run is shown in a collapsible step
- **Conversation memory**: multi-turn context maintained within a session
- **Read-only guardrails**: only `SELECT` statements are allowed; `INSERT`, `UPDATE`, `DELETE`, `DROP` etc. are blocked
- **Auto-LIMIT**: queries without a `LIMIT` clause automatically get `LIMIT 500` applied
- **Quick starters**: four one-click prompt buttons on load

| Starter |
|---|
| How did we do last month? |
| Which product is selling the most? |
| Which store is performing best? |
| Compare revenue across stores this year |

### How It Works

```
User message
     │
     ▼
Claude (tool-use loop, max 5 rounds)
     │
     ├── Yield text_chunk events → stream to UI
     │
     ├── If tool call detected → execute SQL on BigQuery
     │       ├── Yield sql event      → show query in Step
     │       └── Yield result event   → show row count in Step
     │
     └── Loop until end_turn (no more tool calls)
```

Claude uses a single tool: `query_orders` — it takes a SQL string, validates it, and returns a markdown table of results.

---

## 6. Local Development Setup

### Prerequisites

- Python 3.11+
- A Google Cloud project with BigQuery enabled
- A GCP service account with `BigQuery Data Editor` and `BigQuery Job User` roles
- A Gmail account with IMAP enabled and an [App Password](https://support.google.com/accounts/answer/185833) generated
- An [Anthropic API key](https://console.anthropic.com) (for the chatbot)

### Step 1 — Clone the repository

```bash
git clone https://github.com/<your-username>/weblifes-submission-gcp.git
cd weblifes-submission-gcp
```

### Step 2 — Create a virtual environment

```bash
python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS / Linux
source .venv/bin/activate
```

### Step 3 — Place your service account key

Download your GCP service account JSON key and save it as:

```
auth/service_account.json
```

This path is already gitignored. **Never commit credentials.**

### Step 4 — Configure environment variables

Copy the example env file and fill in your values:

```bash
cp .env.example .env   # or create .env manually at repo root
```

Minimum required values in `.env`:

```env
# Gmail IMAP
GMAIL_HOST=imap.gmail.com
GMAIL_PORT=993
GMAIL_EMAIL=your_email@gmail.com
GMAIL_APP_PASSWORD=abcd efgh ijkl mnop

# Email filtering (defaults shown — change if your subject line differs)
GMAIL_SUBJECT_FILTER=[E-Com] Daily Sales Export
GMAIL_SUBJECT_PATTERN=^\[E-Com\] Daily Sales Export\s*[–-]\s*\d{4}-\d{2}-\d{2}$
GMAIL_CSV_PATTERN=^e_com_sales_\d{8}\.csv$

# Google Cloud / BigQuery
GOOGLE_APPLICATION_CREDENTIALS=D:\path\to\weblifes-submission-gcp\auth\service_account.json
BQ_PROJECT_ID=your-gcp-project-id
BQ_DATASET_ID=weblife_ecommerce
BQ_RAW_TABLE=raw_orders

# Alerting — leave empty to disable
ALERT_RECIPIENT_EMAIL=your_email@gmail.com

# Chatbot (Deliverable 3 only)
ANTHROPIC_API_KEY=sk-ant-...
CLAUDE_MODEL=claude-haiku-4-5-20251001
```

### Step 5 — Install dependencies

**Pipeline:**

```bash
cd gmail_bigquery_ingestion_pipeline
pip install -r requirements.txt
```

**Chatbot:**

```bash
cd insights_chatbot
pip install -r requirements.txt
```

### Step 6 — Create BigQuery tables

Run the DDL script once to create all tables in your BigQuery dataset:

```bash
bq query --project_id=your-gcp-project-id \
         --use_legacy_sql=false \
         < bigquery_transformations/create_schema.sql
```

Or paste the contents of [bigquery_transformations/create_schema.sql](bigquery_transformations/create_schema.sql) directly into the BigQuery console.

### Step 7 — Run the ingestion pipeline locally

```bash
# From repo root
cd gmail_bigquery_ingestion_pipeline
python -m utils.pipeline
```

Expected output:

```
INFO  - Pipeline started
INFO  - Fetching email matching subject filter...
INFO  - Found email: [E-Com] Daily Sales Export – 2024-01-15 (received: 2024-01-15)
INFO  - Parsing attachment: e_com_sales_20240115.csv
INFO  - Loaded 4 823 rows into weblife_ecommerce.raw_orders
INFO  - Quality report email sent to your_email@gmail.com
INFO  - Pipeline completed successfully
```

### Step 8 — Run the chatbot locally

```bash
cd insights_chatbot
chainlit run app.py
```

Open [http://localhost:8000](http://localhost:8000) in your browser.

> **Chatbot Local Screenshot**
>
> ![Local Chatbot](docs/images/chatbot_local.png)

---

## 7. Deploying to Google Cloud

### Ingestion Pipeline → Cloud Functions (2nd gen)

#### Prerequisites

- [Google Cloud CLI](https://cloud.google.com/sdk/docs/install) installed and authenticated
- Cloud Functions, Cloud Build, and Cloud Scheduler APIs enabled

#### Deploy the function

```bash
gcloud functions deploy ingest \
  --gen2 \
  --region=us-central1 \
  --runtime=python311 \
  --source=gmail_bigquery_ingestion_pipeline \
  --entry-point=ingest \
  --trigger-http \
  --no-allow-unauthenticated \
  --set-env-vars GMAIL_EMAIL=your@gmail.com,\
GMAIL_APP_PASSWORD="abcd efgh ijkl mnop",\
GMAIL_SUBJECT_FILTER="[E-Com] Daily Sales Export",\
BQ_PROJECT_ID=your-gcp-project-id,\
BQ_DATASET_ID=weblife_ecommerce,\
BQ_RAW_TABLE=raw_orders,\
ALERT_RECIPIENT_EMAIL=your@gmail.com
```

> On GCP, **do not set** `GOOGLE_APPLICATION_CREDENTIALS` — the function uses Workload Identity automatically. Make sure the function's service account has `BigQuery Data Editor` and `BigQuery Job User` roles.

#### Schedule with Cloud Scheduler

```bash
gcloud scheduler jobs create http daily-ingestion \
  --location=us-central1 \
  --schedule="0 7 * * *" \
  --uri="https://REGION-PROJECT_ID.cloudfunctions.net/ingest" \
  --oidc-service-account-email=YOUR_SERVICE_ACCOUNT@PROJECT.iam.gserviceaccount.com \
  --time-zone="UTC"
```

This triggers the pipeline every day at 07:00 UTC.

#### Run BigQuery transformations

After ingestion, run the transformation SQL to promote raw data through staging to the mart:

```bash
# Option A — Dataform (recommended for production)
# Set up Dataform in the GCP console, connect this repo, and run the workflow

# Option B — Direct BigQuery execution
bq query --use_legacy_sql=false < bigquery_transformations/staging/stg_orders_cleaned.sqlx
bq query --use_legacy_sql=false < bigquery_transformations/mart/fct_orders.sqlx
```

---

## 8. Deploying the Chatbot to Render

The chatbot is containerised and can be deployed to [Render](https://render.com) in a few clicks.

### Step 1 — Fork / push this repository to GitHub

Render connects to your GitHub account to pull the source code.

### Step 2 — Create a new Web Service on Render

1. Go to the [Render dashboard](https://dashboard.render.com) → **New → Web Service**
2. Connect your GitHub repository
3. Set **Root Directory** to `insights_chatbot` (or leave blank — `render.yaml` handles it)
4. Render will detect `render.yaml` automatically and pre-fill the settings

### Step 3 — Set secret environment variables

In the Render dashboard for your service, go to **Environment** and add:

| Variable | Value |
|---|---|
| `ANTHROPIC_API_KEY` | Your Anthropic API key |
| `GOOGLE_CREDENTIALS_JSON` | The full contents of `auth/service_account.json` as a single-line JSON string |

The non-secret variables (`BQ_PROJECT_ID`, `CLAUDE_MODEL`) are already set in `render.yaml`.

### Step 4 — Deploy

Click **Deploy** (or push a commit — Render auto-deploys on push).

Once deployed, your chatbot will be live at `https://weblife-insights-chatbot.onrender.com` (or your custom domain).

> **Render Dashboard Screenshot**
>
> ![Render Deploy](docs/images/render_deploy.png)

### Deploying to Cloud Run (Production GCP)

For production, use Cloud Run with Workload Identity instead of a JSON key:

```bash
# Build and push to Artifact Registry
gcloud builds submit insights_chatbot/ \
  --tag=gcr.io/YOUR_PROJECT/weblife-chatbot

# Deploy to Cloud Run
gcloud run deploy weblife-chatbot \
  --image=gcr.io/YOUR_PROJECT/weblife-chatbot \
  --region=us-central1 \
  --platform=managed \
  --allow-unauthenticated \
  --set-env-vars ANTHROPIC_API_KEY=sk-ant-...,BQ_PROJECT_ID=YOUR_PROJECT,CLAUDE_MODEL=claude-haiku-4-5-20251001 \
  --port=8080
```

On Cloud Run, do **not** set `GOOGLE_CREDENTIALS_JSON` or `GOOGLE_APPLICATION_CREDENTIALS` — the service uses Workload Identity automatically (grant the Cloud Run service account `BigQuery Data Viewer` and `BigQuery Job User` roles).

---

## 9. Environment Variables Reference

### Pipeline (`gmail_bigquery_ingestion_pipeline`)

| Variable | Required | Default | Description |
|---|---|---|---|
| `GMAIL_HOST` | No | `imap.gmail.com` | IMAP server |
| `GMAIL_PORT` | No | `993` | IMAP SSL port |
| `GMAIL_EMAIL` | **Yes** | — | Gmail address (also used as SMTP sender for alerts) |
| `GMAIL_APP_PASSWORD` | **Yes** | — | 16-character Gmail App Password |
| `GMAIL_SUBJECT_FILTER` | No | `[E-Com] Daily Sales Export` | IMAP server-side substring search |
| `GMAIL_SUBJECT_PATTERN` | No | See `.env.example` | Python regex for exact subject match |
| `GMAIL_CSV_PATTERN` | No | `^e_com_sales_\d{8}\.csv$` | Regex matched against attachment filenames |
| `GOOGLE_APPLICATION_CREDENTIALS` | Local only | — | Path to service account JSON; omit on GCP |
| `BQ_PROJECT_ID` | **Yes** | — | GCP project ID |
| `BQ_DATASET_ID` | **Yes** | — | BigQuery dataset name |
| `BQ_RAW_TABLE` | No | `raw_orders` | BigQuery table name |
| `ALERT_RECIPIENT_EMAIL` | No | — | Alert destination email; leave blank to disable all alerts |

### Chatbot (`insights_chatbot`)

| Variable | Required | Default | Description |
|---|---|---|---|
| `ANTHROPIC_API_KEY` | **Yes** | — | Anthropic API key |
| `CLAUDE_MODEL` | No | `claude-haiku-4-5-20251001` | Claude model ID |
| `GOOGLE_CREDENTIALS_JSON` | Option 1 | — | Full service account JSON as a string (for Render / PaaS) |
| `GOOGLE_APPLICATION_CREDENTIALS` | Option 2 | — | Path to service account JSON file (for local dev) |
| `BQ_PROJECT_ID` | **Yes** | — | GCP project ID |

**Credential precedence (chatbot):** `GOOGLE_CREDENTIALS_JSON` → `GOOGLE_APPLICATION_CREDENTIALS` → Application Default Credentials (ADC, used on Cloud Run).

---

## 10. Alerting System

All alerts are sent via Gmail SMTP (port 587, STARTTLS) using the same `GMAIL_EMAIL` / `GMAIL_APP_PASSWORD` credentials as the IMAP reader. Alerting is entirely disabled when `ALERT_RECIPIENT_EMAIL` is unset or empty. Alert failures are **non-fatal** — logged as warnings; the pipeline outcome is unaffected.

| Scenario | Function | HTTP Response |
|---|---|---|
| No matching email found in inbox | `send_no_email_alert` | `200 no_email` |
| Email found but no matching CSV attachment | `send_no_attachment_alert` | `200 no_attachment` |
| File already loaded in BigQuery (duplicate run) | `send_already_ingested_alert` | `200 already_ingested` |
| BigQuery / network / system error | `send_failure_alert` | `500 error` |
| Successful load | `send_quality_report` (HTML) | `200 success` |

### Quality Report Email

The success alert is a full HTML email containing:

- File name and number of rows loaded
- Duplicate `order_id` count
- Full duplicate row count
- Per-column empty-value counts and percentages

> **Sample Alert Email**
>
> ![Alert Email Screenshot](docs/images/alert_email.png)

---

## Tech Stack

| Component | Technology |
|---|---|
| Ingestion | Python 3.11, pandas, PyArrow, google-cloud-bigquery |
| Email | Gmail IMAP (imaplib) + SMTP (smtplib, STARTTLS) |
| Transformations | BigQuery Standard SQL, Dataform (.sqlx) |
| Chatbot UI | [Chainlit](https://chainlit.io) 2.x |
| AI / LLM | [Anthropic Claude](https://www.anthropic.com) (tool use + streaming) |
| BQ Auth | Service account JSON / Application Default Credentials |
| Scheduler | Google Cloud Scheduler |
| Compute | Google Cloud Functions (2nd gen) + Cloud Run |
| Deployment | [Render](https://render.com) (Docker) / Google Cloud Run |
| Python env | python-dotenv |

---

## 11. What I'd done If there are no cost constraints, in a Real Production Environment

This prototype demonstrates the full pipeline end-to-end. Below is how each component would be designed for a real production deployment.

---

### Defined SLAs and Ingestion Contracts

Production pipeline reliability starts with a formal SLA agreed with the source system (the team generating the daily sales export):

- **Email delivery SLA**: source system must deliver the CSV email by **06:00 UTC** each day
- **Ingestion SLA**: pipeline completes loading to `raw_orders` within 30 minutes of email arrival — target **06:30 UTC**
- **Transformation SLA**: staging and mart tables are refreshed and query-ready by **07:00 UTC**, giving analysts clean data at the start of their day
- **Late-delivery alert**: if the expected email has not arrived by **06:15 UTC**, an automated alert fires to both the data team and the source system owner — proactively, while there is still time to intervene, not after the SLA has already been breached
- **On-call runbook**: documented steps for each failure scenario (no email, no attachment, BQ load error, transformation failure) so any engineer on rotation can respond, not just the pipeline author

These SLAs would be encoded as Cloud Monitoring alerting policies with explicit breach thresholds, not just narrative documentation.

---

### Ingestion on Cloud Functions + Cloud Scheduler

The ingestion pipeline is already designed for this model. In production:

- Gmail fetch with Gmail API (GCP) instead of IMAP library in python.
- **Cloud Function (2nd gen)** hosts `main.py`, triggered via OIDC-authenticated HTTP
- **Cloud Scheduler** fires at **05:45 UTC** daily — 15 minutes before the email SLA deadline, so if the email has already arrived early the load completes comfortably within the window
- The function's service account is granted only `BigQuery Data Editor` and `BigQuery Job User` — principle of least privilege
- **Cloud Logging** captures all structured log output automatically; log-based metrics (`rows_loaded`, `rows_rejected`, `pipeline_latency_seconds`) feed into a Cloud Monitoring dashboard with 30-day trend views
- Secrets (`GMAIL_APP_PASSWORD`) are stored in **Secret Manager** rather than environment variables, accessed at cold-start via the Secret Manager SDK

```
Cloud Scheduler (05:45 UTC)
        │  OIDC-authenticated HTTP POST
        ▼
Cloud Function — ingest()
        ├── Gmail IMAP fetch
        ├── CSV parse + validate
        └── BigQuery load → raw_orders
```

---

### Dataform on Schedule

The `.sqlx` models would be managed by a **Dataform workflow** triggered by Cloud Scheduler immediately after ingestion completes:

- Dataform handles **DAG dependency ordering** automatically — `stg_orders_cleaned` runs only after `raw_orders` is populated; `fct_orders` only after staging passes
- Each model includes **Dataform assertions** (`not_null`, `unique`, `accepted_values`) that run before a model is materialised — a failed assertion blocks promotion to the mart and fires a Slack alert
- Workflow runs at **06:15 UTC**; mart tables are query-ready by **06:45 UTC**

```
Cloud Scheduler (06:15 UTC)
        ▼
Dataform Workflow
        ├── stg_orders_cleaned   (assertions run first)
        ├── stg_orders_rejected  (quarantine, in parallel)
        └── fct_orders           (only after staging passes)
```

---

### Incremental Mart Updates with Partitioning and Clustering

The current `fct_orders` model does a full table rebuild each run. At scale this is expensive — BigQuery charges per bytes scanned, and a full rebuild reads the entire history daily.

In production, this becomes an **incremental MERGE** touching only today's partition:

```sql
MERGE INTO fct_orders AS target
USING (
    SELECT
        order_date, store_name, product_category,
        product_name, shipping_status,
        COUNT(DISTINCT order_id)    AS total_orders,
        SUM(quantity)               AS total_units_sold,
        COUNT(DISTINCT customer_id) AS unique_customers,
        SUM(revenue)                AS total_revenue,
        SUM(discount_amount)        AS total_discounts_given
    FROM stg_orders_cleaned
    WHERE order_date = CURRENT_DATE()  -- only today's partition
    GROUP BY 1,2,3,4,5
) AS source
ON  target.order_date     = source.order_date
AND target.store_name     = source.store_name
AND target.product_name   = source.product_name
WHEN MATCHED     THEN UPDATE SET ...
WHEN NOT MATCHED THEN INSERT ...;
```

**Partitioning** on `order_date` (DAY) means the MERGE touches only today's partition — the rest of the table is never scanned.

**Clustering** on `(store_name, product_category)` means queries filtering by store or category skip irrelevant storage blocks entirely.

Combined, a daily refresh scans roughly 1/365th of the table compared to a full rebuild, with proportionally lower cost and faster query performance for downstream users.

---

### Data Quality Alerts from BigQuery / Looker to Slack

Instead of SMTP alerts fired from application code, production DQ alerting lives at the data layer — closer to where the checks run and visible to the whole team.

**BigQuery scheduled query + Slack webhook**: a scheduled query runs DQ checks after each Dataform run, writes results to a `dq_results` table, and calls a Slack incoming webhook when any CRITICAL check fails — linking directly to the failing rows in BigQuery.

**Looker data quality dashboard + Looker Alerts**: a Looker dashboard surfaces all 14 DQ check results, rejection rates by day, and per-column empty-value trends. Looker's built-in Alert feature sends Slack or email notifications when any metric crosses a threshold — no custom webhook code, and every alert links directly to the dashboard tile for immediate investigation context.

This approach makes data quality visible to analysts and product managers, not just engineers with access to Cloud Logging.

---

### Chatbot via BigQuery Agents in Looker

The Chainlit + Claude prototype demonstrates the concept well for a standalone deployment. In production within a Weblife analytics stack, the chatbot would be built natively in **Looker**:

- **Looker's semantic layer** already understands metric definitions, dimension labels, and join paths — generated SQL is correct by construction rather than relying on the LLM to infer schema from a docstring
- **BigQuery's Gemini-powered agents** (or the Looker Extension Framework with a custom LLM backend) provide a native natural-language-to-SQL experience without deploying or hosting a separate service
- **Access control is inherited from Looker** — users only query data their Looker role permits, with no separate auth layer needed on the chatbot
- **Conversation context and drill-downs** are handled by Looker's session model, and results can be saved directly to dashboards
- This eliminates the operational burden of running and scaling a separate Chainlit service, and puts the AI interface in the same tool analysts already use daily

The Chainlit prototype in this repo remains the right choice for contexts where Looker is not part of the stack, or for a public-facing product experience.

---

## License

This project is submitted as a take-home assessment and is not licensed for public use.