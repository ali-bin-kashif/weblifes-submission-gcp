"""
Fact table schema, business context, and tool definition for the Claude agent.

BUSINESS_CONTEXT and _SCHEMA_DESCRIPTION are injected into the system prompt so
Claude understands what the data represents and how to query it correctly.
Update BUSINESS_CONTEXT if the store list, product range, or date range changes.
"""

from datetime import date

TABLE_ID = "reflected-codex-468204-m7.weblife_ecommerce.fct_orders"

BUSINESS_CONTEXT = """
E-commerce company with 5 retail stores across the US.
Sells indoor and outdoor tools and peripherals.
Operates 2022–present. Data refreshed daily via the ingestion pipeline.

Stores: PatioWorld, OutdoorHub, NatureGoods, GardenPlus, HomeNest
"""

# Full column-level description sent to the LLM as part of the system prompt.
# Includes explicit SQL rules to steer Claude toward efficient, correct queries
# (e.g. filter on pre-computed integer columns rather than calling EXTRACT()).
_SCHEMA_DESCRIPTION = f"""
Table: `{TABLE_ID}`

Pre-aggregated fact table. Each row = unique (order_date, store_name, product_category, product_name, shipping_status) combination.
Aggregate metrics (SUM, COUNT) are pre-computed — do NOT aggregate further unless grouping by fewer dimensions.

Columns:
  order_date            DATE     Date of the orders
  store_name            STRING   One of 5 stores (see business context)
  product_category      STRING   One of 5 product categories
  product_name          STRING   One of 20 products
  shipping_status       STRING   Shipped | Returned | Delivered | Cancelled | Processing
  total_orders          INT      COUNT DISTINCT order_id
  total_units_sold      INT      SUM of quantity
  unique_customers      INT      COUNT DISTINCT customer_id
  total_revenue         NUMERIC  SUM of revenue in USD, 2dp
  total_discounts_given NUMERIC  SUM of discount_amount
  discount_rate_pct     NUMERIC  total_discounts_given / total_revenue × 100
  order_year            INT      EXTRACT(YEAR FROM order_date)
  order_month           INT      EXTRACT(MONTH FROM order_date)  — 1=Jan … 12=Dec
  order_year_month      STRING   'YYYY-MM' — use for time-series grouping
  order_day_of_week     STRING   'Monday', 'Tuesday', etc.
  _last_updated         DATE     Date this mart was last rebuilt

SQL RULES:
  - BigQuery Standard SQL only. Always use backtick-quoted table name.
  - Filter by order_year / order_month (integers) rather than date functions — they're pre-computed.
  - Use order_year_month for time-series GROUP BY.
  - Exclude shipping_status IN ('Returned', 'Cancelled') for revenue/sales performance unless asked.
  - LIMIT 20 for detail queries; no LIMIT for aggregations.
"""


def get_system_prompt() -> str:
    """
    Build the full system prompt injected at the start of every Claude request.

    Includes today's date and the last complete month so Claude can resolve
    relative time references ('last month', 'this year') correctly without
    relying on its training data cutoff.
    """
    today = date.today()
    return f"""\
You are a business intelligence assistant. Help non-technical stakeholders understand \
sales performance in plain English — no SQL jargon, no raw tables.

Use the query_orders tool to fetch data from BigQuery, then answer conversationally.
You may run multiple queries if needed to fully answer the question.

Today's date: {today.isoformat()}
Last complete month: {_last_month()}

BUSINESS CONTEXT:
{BUSINESS_CONTEXT.strip()}

SCHEMA:
{_SCHEMA_DESCRIPTION.strip()}

RESPONSE STYLE:
- Lead with the direct answer and specific numbers.
- Use $ formatting for revenue (e.g. $12,345.67).
- Highlight anomalies or trends if the data shows them.
- Keep it to 3–6 sentences or a short bullet list. No filler.
- End with one useful follow-up question unless the conversation is clearly wrapping up.
"""


# Tool definition passed to the Anthropic API.
# Claude uses this schema to know when and how to call query_orders.
TOOLS = [
    {
        "name": "query_orders",
        "description": (
            "Execute a BigQuery Standard SQL SELECT query against the fct_orders fact table. "
            "Returns results as a formatted string. Use this whenever you need data to answer "
            "the user's question. Only SELECT statements are permitted."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "sql": {
                    "type": "string",
                    "description": "Valid BigQuery Standard SQL SELECT query.",
                }
            },
            "required": ["sql"],
        },
    }
]


def _last_month() -> str:
    """Return the last complete month as 'YYYY-MM', handling January correctly."""
    today = date.today()
    month = today.month - 1 or 12
    year = today.year if today.month > 1 else today.year - 1
    return f"{year}-{month:02d}"