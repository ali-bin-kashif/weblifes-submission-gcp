
WITH

-- ── Scope: today's ingestion batch only ──────────────────────
-- We check only the rows loaded in the latest pipeline run
-- so we don't re-flag issues from previous days.

today_batch AS (
  SELECT *
  FROM `reflected-codex-468204-m7.weblife_ecommerce.raw_orders`
  WHERE DATE(_ingested_at) = CURRENT_DATE()
),

total AS (
  SELECT COUNT(*) AS n FROM today_batch
),

-- ════════════════════════════════════════════════════════════
-- CRITICAL CHECKS — these block the pipeline
-- ════════════════════════════════════════════════════════════

-- C1: Empty file — nothing was loaded
c1 AS (
  SELECT
    'C1' AS check_id,
    'CRITICAL' AS severity,
    'Empty batch' AS check_name,
    'No rows found for todays ingestion batch. File may be missing or empty.' AS description,
    (SELECT n FROM total) AS total_rows,
    CASE WHEN (SELECT n FROM total) = 0 THEN 0 ELSE NULL END AS failed_rows,
    CASE WHEN (SELECT n FROM total) = 0 THEN 'FAIL' ELSE 'PASS' END AS status
),

-- C2: Null order_id — rows with no primary key are untrackable
c2 AS (
  SELECT
    'C2' AS check_id,
    'CRITICAL' AS severity,
    'Null order_id' AS check_name,
    'Rows missing order_id cannot be tracked, deduplicated or linked to customers.' AS description,
    (SELECT n FROM total) AS total_rows,
    COUNTIF(order_id IS NULL OR TRIM(order_id) = '') AS failed_rows,
    CASE
      WHEN COUNTIF(order_id IS NULL OR TRIM(order_id) = '') > 0 THEN 'FAIL'
      ELSE 'PASS'
    END AS status
  FROM today_batch
),

-- C3: Null order_date — missing dates break all time-based reporting
c3 AS (
  SELECT
    'C3' AS check_id,
    'CRITICAL' AS severity,
    'Null order_date' AS check_name,
    'Rows with null order_date cannot be partitioned or used in time-series analysis.' AS description,
    (SELECT n FROM total) AS total_rows,
    COUNTIF(order_date IS NULL OR TRIM(order_date) = '') AS failed_rows,
    CASE
      WHEN COUNTIF(order_date IS NULL OR TRIM(order_date) = '') > 0 THEN 'FAIL'
      ELSE 'PASS'
    END AS status
  FROM today_batch
),

-- C4: Future-dated orders — clock skew or data corruption
c4 AS (
  SELECT
    'C4' AS check_id,
    'CRITICAL' AS severity,
    'Future-dated orders' AS check_name,
    'Orders dated beyond today indicate clock skew or source system corruption.' AS description,
    (SELECT n FROM total) AS total_rows,
    COUNTIF(
      SAFE.PARSE_DATE('%Y-%m-%d', order_date) > CURRENT_DATE()
    ) AS failed_rows,
    CASE
      WHEN COUNTIF(SAFE.PARSE_DATE('%Y-%m-%d', order_date) > CURRENT_DATE()) > 0
      THEN 'FAIL' ELSE 'PASS'
    END AS status
  FROM today_batch
),

-- C5: Null revenue — cannot compute any financial metric
c5 AS (
  SELECT
    'C5' AS check_id,
    'CRITICAL' AS severity,
    'Null revenue' AS check_name,
    'Rows with null revenue cannot contribute to any financial reporting.' AS description,
    (SELECT n FROM total) AS total_rows,
    COUNTIF(revenue IS NULL OR TRIM(revenue) = '') AS failed_rows,
    CASE
      WHEN COUNTIF(revenue IS NULL OR TRIM(revenue) = '') > 0 THEN 'FAIL'
      ELSE 'PASS'
    END AS status
  FROM today_batch
),

-- ════════════════════════════════════════════════════════════
-- WARNING CHECKS — log and continue, flag for review
-- ════════════════════════════════════════════════════════════

-- W1: Exact duplicate rows
w1 AS (
  SELECT
    'W1' AS check_id,
    'WARNING' AS severity,
    'Exact duplicate rows' AS check_name,
    'Identical rows across all columns — source system likely double-sent the file.' AS description,
    (SELECT n FROM total) AS total_rows,
    (SELECT n FROM total) - COUNT(*) AS failed_rows,
    CASE
      WHEN (SELECT n FROM total) - COUNT(*) > 0 THEN 'FAIL'
      ELSE 'PASS'
    END AS status
  FROM (
    SELECT DISTINCT * FROM today_batch
  )
),

-- W2: Duplicate order_id with different content (conflict)
w2 AS (
  SELECT
    'W2' AS check_id,
    'WARNING' AS severity,
    'Conflicting order_id duplicates' AS check_name,
    'Same order_id appears multiple times with different values — retry/resend bug in source.' AS description,
    (SELECT n FROM total) AS total_rows,
    COUNT(*) - COUNT(DISTINCT order_id) AS failed_rows,
    CASE
      WHEN COUNT(*) - COUNT(DISTINCT order_id) > 0 THEN 'FAIL'
      ELSE 'PASS'
    END AS status
  FROM today_batch
  WHERE order_id IS NOT NULL
),

-- W3: Negative quantity
w3 AS (
  SELECT
    'W3' AS check_id,
    'WARNING' AS severity,
    'Negative quantity' AS check_name,
    'Negative quantities indicate data-entry errors or unprocessed returns.' AS description,
    (SELECT n FROM total) AS total_rows,
    COUNTIF(SAFE_CAST(quantity AS INT64) < 0) AS failed_rows,
    CASE
      WHEN COUNTIF(SAFE_CAST(quantity AS INT64) < 0) > 0 THEN 'FAIL'
      ELSE 'PASS'
    END AS status
  FROM today_batch
),

-- W4: Zero quantity
w4 AS (
  SELECT
    'W4' AS check_id,
    'WARNING' AS severity,
    'Zero quantity' AS check_name,
    'Orders with zero quantity generate no revenue and should not exist.' AS description,
    (SELECT n FROM total) AS total_rows,
    COUNTIF(SAFE_CAST(quantity AS INT64) = 0) AS failed_rows,
    CASE
      WHEN COUNTIF(SAFE_CAST(quantity AS INT64) = 0) > 0 THEN 'FAIL'
      ELSE 'PASS'
    END AS status
  FROM today_batch
),

-- W5: Revenue mismatch — revenue ≠ (qty × unit_price) - discount
w5 AS (
  SELECT
    'W5' AS check_id,
    'WARNING' AS severity,
    'Revenue mismatch (revenue ≠ qty × price - discount)' AS check_name,
    'Revenue does not match expected calculation — source system computation bug.' AS description,
    (SELECT n FROM total) AS total_rows,
    COUNTIF(
      ABS(
        SAFE_CAST(revenue AS NUMERIC)
        - (SAFE_CAST(quantity AS INT64) * SAFE_CAST(unit_price AS NUMERIC))
        + IFNULL(SAFE_CAST(discount_amount AS NUMERIC), 0)
      ) > 0.02
    ) AS failed_rows,
    CASE
      WHEN COUNTIF(
        ABS(
          SAFE_CAST(revenue AS NUMERIC)
          - (SAFE_CAST(quantity AS INT64) * SAFE_CAST(unit_price AS NUMERIC))
          + IFNULL(SAFE_CAST(discount_amount AS NUMERIC), 0)
        ) > 0.02
      ) > 0 THEN 'FAIL'
      ELSE 'PASS'
    END AS status
  FROM today_batch
),

-- W6: Outlier revenue — suspiciously low (≤ $0.01) or high (> $5,000)
w6 AS (
  SELECT
    'W6' AS check_id,
    'WARNING' AS severity,
    'Outlier revenue values' AS check_name,
    'Revenue ≤ $0.01 or > $5,000 per row — likely decimal point error in source.' AS description,
    (SELECT n FROM total) AS total_rows,
    COUNTIF(
      SAFE_CAST(revenue AS NUMERIC) <= 0.01
      OR SAFE_CAST(revenue AS NUMERIC) > 5000
    ) AS failed_rows,
    CASE
      WHEN COUNTIF(
        SAFE_CAST(revenue AS NUMERIC) <= 0.01
        OR SAFE_CAST(revenue AS NUMERIC) > 5000
      ) > 0 THEN 'FAIL'
      ELSE 'PASS'
    END AS status
  FROM today_batch
),

-- W7: Invalid customer_state codes
w7 AS (
  SELECT
    'W7' AS check_id,
    'WARNING' AS severity,
    'Invalid customer_state codes' AS check_name,
    'State codes not matching valid US 2-letter codes — bad validation at entry point.' AS description,
    (SELECT n FROM total) AS total_rows,
    COUNTIF(
      customer_state IS NOT NULL
      AND TRIM(customer_state) NOT IN (
        'AL','AK','AZ','AR','CA','CO','CT','DE','FL','GA','HI','ID',
        'IL','IN','IA','KS','KY','LA','ME','MD','MA','MI','MN','MS',
        'MO','MT','NE','NV','NH','NJ','NM','NY','NC','ND','OH','OK',
        'OR','PA','RI','SC','SD','TN','TX','UT','VT','VA','WA','WV','WI','WY'
      )
    ) AS failed_rows,
    CASE
      WHEN COUNTIF(
        customer_state IS NOT NULL
        AND TRIM(customer_state) NOT IN (
          'AL','AK','AZ','AR','CA','CO','CT','DE','FL','GA','HI','ID',
          'IL','IN','IA','KS','KY','LA','ME','MD','MA','MI','MN','MS',
          'MO','MT','NE','NV','NH','NJ','NM','NY','NC','ND','OH','OK',
          'OR','PA','RI','SC','SD','TN','TX','UT','VT','VA','WA','WV','WI','WY'
        )
      ) > 0 THEN 'FAIL'
      ELSE 'PASS'
    END AS status
  FROM today_batch
),

-- ════════════════════════════════════════════════════════════
-- INFO CHECKS — informational, never block
-- ════════════════════════════════════════════════════════════

-- I1: Null customer_email
i1 AS (
  SELECT
    'I1' AS check_id,
    'INFO' AS severity,
    'Null customer_email' AS check_name,
    'Expected for guest checkouts. High rates may indicate a collection issue.' AS description,
    (SELECT n FROM total) AS total_rows,
    COUNTIF(customer_email IS NULL OR TRIM(customer_email) = '') AS failed_rows,
    'INFO' AS status
  FROM today_batch
),

-- I2: Malformed email — missing @
i2 AS (
  SELECT
    'I2' AS check_id,
    'INFO' AS severity,
    'Malformed customer_email (missing @)' AS check_name,
    'Email address does not contain @ — frontend validation gap.' AS description,
    (SELECT n FROM total) AS total_rows,
    COUNTIF(
      customer_email IS NOT NULL
      AND TRIM(customer_email) != ''
      AND NOT REGEXP_CONTAINS(customer_email, r'@')
    ) AS failed_rows,
    'INFO' AS status
  FROM today_batch
),

-- I3: Null customer_name
i3 AS (
  SELECT
    'I3' AS check_id,
    'INFO' AS severity,
    'Null customer_name' AS check_name,
    'Expected for guest checkouts. Monitor for unexpected spikes.' AS description,
    (SELECT n FROM total) AS total_rows,
    COUNTIF(customer_name IS NULL OR TRIM(customer_name) = '') AS failed_rows,
    'INFO' AS status
  FROM today_batch
),

-- I4: Null shipping_method
i4 AS (
  SELECT
    'I4' AS check_id,
    'INFO' AS severity,
    'Null shipping_method' AS check_name,
    'Shipping method not captured — may be store pickup or system gap.' AS description,
    (SELECT n FROM total) AS total_rows,
    COUNTIF(shipping_method IS NULL OR TRIM(shipping_method) = '') AS failed_rows,
    'INFO' AS status
  FROM today_batch
),

-- I5: Null payment_method
i5 AS (
  SELECT
    'I5' AS check_id,
    'INFO' AS severity,
    'Null payment_method' AS check_name,
    'Payment method not captured for some orders.' AS description,
    (SELECT n FROM total) AS total_rows,
    COUNTIF(payment_method IS NULL OR TRIM(payment_method) = '') AS failed_rows,
    'INFO' AS status
  FROM today_batch
),

-- I6: Inconsistent store_name values
i6 AS (
  SELECT
    'I6' AS check_id,
    'INFO' AS severity,
    'Inconsistent store_name values' AS check_name,
    'Store names have casing/spacing variants — normalisation needed in staging.' AS description,
    (SELECT n FROM total) AS total_rows,
    COUNT(DISTINCT TRIM(LOWER(store_name))) AS failed_rows,
    'INFO' AS status
  FROM today_batch
  WHERE store_name IS NOT NULL
)

-- ── Union all checks into single report ───────────────────────
SELECT *, CURRENT_TIMESTAMP() AS checked_at FROM c1
UNION ALL SELECT *, CURRENT_TIMESTAMP() FROM c2
UNION ALL SELECT *, CURRENT_TIMESTAMP() FROM c3
UNION ALL SELECT *, CURRENT_TIMESTAMP() FROM c4
UNION ALL SELECT *, CURRENT_TIMESTAMP() FROM c5
UNION ALL SELECT *, CURRENT_TIMESTAMP() FROM w1
UNION ALL SELECT *, CURRENT_TIMESTAMP() FROM w2
UNION ALL SELECT *, CURRENT_TIMESTAMP() FROM w3
UNION ALL SELECT *, CURRENT_TIMESTAMP() FROM w4
UNION ALL SELECT *, CURRENT_TIMESTAMP() FROM w5
UNION ALL SELECT *, CURRENT_TIMESTAMP() FROM w6
UNION ALL SELECT *, CURRENT_TIMESTAMP() FROM w7
UNION ALL SELECT *, CURRENT_TIMESTAMP() FROM i1
UNION ALL SELECT *, CURRENT_TIMESTAMP() FROM i2
UNION ALL SELECT *, CURRENT_TIMESTAMP() FROM i3
UNION ALL SELECT *, CURRENT_TIMESTAMP() FROM i4
UNION ALL SELECT *, CURRENT_TIMESTAMP() FROM i5
UNION ALL SELECT *, CURRENT_TIMESTAMP() FROM i6
ORDER BY
  CASE severity WHEN 'CRITICAL' THEN 1 WHEN 'WARNING' THEN 2 ELSE 3 END,
  check_id;
