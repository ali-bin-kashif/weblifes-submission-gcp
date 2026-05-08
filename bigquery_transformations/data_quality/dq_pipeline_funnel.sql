-- ============================================================
-- dashboard/02_pipeline_funnel.sql
-- Powers: Raw → Cleaned → Rejected funnel in Looker dashboard
--
-- Shows row counts at each stage of the pipeline for the
-- LATEST ingestion batch (not necessarily today).
--
-- Refresh: daily after 02_staging.sql runs
-- ============================================================

WITH

-- Reusable latest batch date subquery
latest_batch_date AS (
  SELECT
    MAX(_pipeline_run_date)      AS latest_run_date,
    MAX(DATE(_ingested_at))      AS latest_ingestion_date
  FROM `reflected-codex-468204-m7.weblife_ecommerce.raw_orders`
),

raw AS (
  SELECT
    COUNT(*)                                              AS raw_rows,
    COUNTIF(order_id IS NULL OR TRIM(order_id) = '')     AS raw_null_order_id,
    COUNTIF(order_date IS NULL OR TRIM(order_date) = '') AS raw_null_order_date,
    COUNTIF(revenue IS NULL OR TRIM(revenue) = '')       AS raw_null_revenue,
    MAX(_ingested_at)                                    AS latest_ingestion,
    MAX(_pipeline_run_date)                              AS pipeline_run_date
  FROM `reflected-codex-468204-m7.weblife_ecommerce.raw_orders`
  WHERE _pipeline_run_date = (SELECT latest_run_date FROM latest_batch_date)
),

cleaned AS (
  SELECT
    COUNT(*) AS cleaned_rows
  FROM `reflected-codex-468204-m7.weblife_ecommerce.stg_orders_cleaned`
),

rejected AS (
  SELECT
    COUNT(*) AS rejected_rows
  FROM `reflected-codex-468204-m7.weblife_ecommerce.stg_orders_rejected`
  WHERE DATE(_rejected_at) = (SELECT latest_ingestion_date FROM latest_batch_date)
),

rejection_reasons AS (
  SELECT
    TRIM(reason)   AS rejection_reason,
    COUNT(*)       AS affected_rows
  FROM `reflected-codex-468204-m7.weblife_ecommerce.stg_orders_rejected`,
  UNNEST(SPLIT(rejection_reason, '|')) AS reason
  WHERE DATE(_rejected_at) = (SELECT latest_ingestion_date FROM latest_batch_date)
    AND TRIM(reason) != ''
  GROUP BY 1
  ORDER BY 2 DESC
)

-- ── Main funnel scorecard ─────────────────────────────────────
SELECT
  r.pipeline_run_date,
  r.latest_ingestion,

  -- Stage counts
  r.raw_rows                                                AS stage_1_raw,
  c.cleaned_rows                                            AS stage_2_cleaned,
  rj.rejected_rows                                          AS stage_3_rejected,

  -- Rates
  ROUND(SAFE_DIVIDE(c.cleaned_rows,  r.raw_rows) * 100, 2) AS pass_rate_pct,
  ROUND(SAFE_DIVIDE(rj.rejected_rows, r.raw_rows) * 100, 2) AS rejection_rate_pct,

  -- Critical null counts in raw
  r.raw_null_order_id,
  r.raw_null_order_date,
  r.raw_null_revenue,

  -- Pipeline health flag
  CASE
    WHEN ROUND(SAFE_DIVIDE(rj.rejected_rows, r.raw_rows) * 100, 2) < 5  THEN 'HEALTHY'
    WHEN ROUND(SAFE_DIVIDE(rj.rejected_rows, r.raw_rows) * 100, 2) < 10 THEN 'WARNING'
    ELSE 'CRITICAL'
  END                                                       AS pipeline_health

FROM raw r
CROSS JOIN cleaned c
CROSS JOIN rejected rj;