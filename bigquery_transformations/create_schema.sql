-- ============================================================
-- create_tables.sql
-- DDL statements for all Weblife e-commerce tables
-- Run once to create tables before pipeline executes
-- Project: reflected-codex-468204-m7
-- Dataset: weblife_ecommerce
-- ============================================================


-- ── 1. raw_orders ─────────────────────────────────────────────
-- Append-only. Partitioned by _pipeline_run_date.
-- All source fields STRING — never coerce at ingest.

CREATE TABLE IF NOT EXISTS `reflected-codex-468204-m7.weblife_ecommerce.raw_orders`
(
  order_id              STRING,
  order_date            STRING,
  customer_id           STRING,
  customer_name         STRING,
  customer_email        STRING,
  customer_city         STRING,
  customer_state        STRING,
  product_name          STRING,
  product_category      STRING,
  quantity              STRING,
  unit_price            STRING,
  discount_amount       STRING,
  revenue               STRING,
  store_name            STRING,
  shipping_method       STRING,
  shipping_status       STRING,
  payment_method        STRING,
  _ingested_at          TIMESTAMP,
  _source_filename      STRING,
  _pipeline_run_date    DATE,
  _email_received_date  STRING
)
PARTITION BY _pipeline_run_date
OPTIONS (
  require_partition_filter = false
);


-- ── 2. stg_orders_cleaned ─────────────────────────────────────
-- Full overwrite daily. Typed, deduped, normalised.
-- CREATE OR REPLACE used by pipeline — this DDL is for reference.

CREATE TABLE IF NOT EXISTS `reflected-codex-468204-m7.weblife_ecommerce.stg_orders_cleaned`
(
  order_id                STRING,
  order_date              DATE,
  customer_id             STRING,
  customer_name           STRING,
  customer_email          STRING,
  customer_city           STRING,
  customer_state          STRING,
  store_name              STRING,
  product_name            STRING,
  product_category        STRING,
  quantity                INTEGER,
  unit_price              NUMERIC,
  discount_amount         NUMERIC,
  revenue                 NUMERIC,
  _revenue_was_corrected  BOOLEAN,
  shipping_method         STRING,
  shipping_status         STRING,
  payment_method          STRING,
  _ingested_at            TIMESTAMP,
  _source_filename        STRING,
  _pipeline_run_date      DATE,
  _email_received_date    STRING
);


-- ── 3. stg_orders_rejected ────────────────────────────────────
-- Quarantine table. Full overwrite daily.
-- All source fields kept as STRING — raw values preserved for debugging.

CREATE TABLE IF NOT EXISTS `reflected-codex-468204-m7.weblife_ecommerce.stg_orders_rejected`
(
  order_id          STRING,
  order_date        STRING,
  customer_id       STRING,
  customer_name     STRING,
  customer_email    STRING,
  customer_city     STRING,
  customer_state    STRING,
  product_name      STRING,
  product_category  STRING,
  store_name        STRING,
  quantity          STRING,
  unit_price        STRING,
  discount_amount   STRING,
  revenue           STRING,
  shipping_method   STRING,
  shipping_status   STRING,
  payment_method    STRING,
  _ingested_at      TIMESTAMP,
  _source_filename  STRING,
  rejection_reason  STRING,
  _rejected_at      TIMESTAMP
);


-- ── 4. fct_orders ─────────────────────────────────────────────
-- Mart fact table. Clustered by store_name, product_category.
-- Partition commented out — causes empty table in sandbox.
-- Uncomment PARTITION BY when billing is enabled.

CREATE TABLE IF NOT EXISTS `reflected-codex-468204-m7.weblife_ecommerce.fct_orders`
(
  order_date            DATE        OPTIONS (description = 'Date of orders in this aggregate row.'),
  store_name            STRING      OPTIONS (description = 'Canonical store name. One of 5 stores.'),
  product_category      STRING      OPTIONS (description = 'Canonical product category. One of 5 categories.'),
  product_name          STRING      OPTIONS (description = 'Canonical product name. One of 20 products.'),
  shipping_status       STRING      OPTIONS (description = 'Canonical shipping status.'),
  total_orders          INT64       OPTIONS (description = 'COUNT DISTINCT order_id — unique orders in this group.'),
  total_units_sold      INT64       OPTIONS (description = 'SUM of quantity across all orders in this group.'),
  unique_customers      INT64       OPTIONS (description = 'COUNT DISTINCT customer_id in this group.'),
  total_revenue         NUMERIC     OPTIONS (description = 'SUM of revenue in USD. Rounded to 2dp.'),
  total_discounts_given NUMERIC     OPTIONS (description = 'SUM of discount_amount applied in this group.'),
  discount_rate_pct     NUMERIC     OPTIONS (description = 'total_discounts_given / total_revenue × 100.'),
  order_year            INT64       OPTIONS (description = 'EXTRACT YEAR from order_date. For year filtering.'),
  order_month           INT64       OPTIONS (description = 'EXTRACT MONTH from order_date. For month filtering.'),
  order_year_month      STRING      OPTIONS (description = 'FORMAT YYYY-MM. For time-series grouping.'),
  order_day_of_week     STRING      OPTIONS (description = 'Day name e.g. Monday. For day-of-week analysis.'),
  _last_updated         DATE        OPTIONS (description = 'Date this mart was last rebuilt.')
)
-- PARTITION BY order_date  -- uncomment when billing enabled
CLUSTER BY store_name, product_category
OPTIONS (
  require_partition_filter = false
);