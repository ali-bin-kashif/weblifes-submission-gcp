-- ============================================================
-- dashboard/02b_rejection_reasons.sql
-- Powers: Rejection reason breakdown bar chart in Looker
--
-- Splits pipe-delimited rejection_reason into individual rows
-- so each reason can be counted and charted separately.
--
-- Refresh: daily after 02_staging.sql runs
-- ============================================================

SELECT
  TRIM(reason)     AS rejection_reason,
  COUNT(*)         AS affected_rows,
  ROUND(
    SAFE_DIVIDE(COUNT(*),
      SUM(COUNT(*)) OVER ()
    ) * 100, 2
  )                AS pct_of_all_rejections
FROM `reflected-codex-468204-m7.weblife_ecommerce.stg_orders_rejected`,
UNNEST(SPLIT(rejection_reason, '|')) AS reason
WHERE DATE(_rejected_at) = CURRENT_DATE()
  AND TRIM(reason) != ''
GROUP BY 1
ORDER BY 2 DESC;