"""
Read-only BigQuery client for the insights chatbot.

Only SELECT statements are permitted. All queries are validated before execution
and automatically capped at _MAX_ROWS to prevent accidentally large result sets
being passed back to the LLM.
"""

import json
import logging
import re

import pandas as pd
from google.cloud import bigquery
from google.oauth2 import service_account

from utils.config import Config
from utils.schema import TABLE_ID

logger = logging.getLogger(__name__)

_MAX_ROWS = 500      # hard cap on rows returned to the LLM
_QUERY_TIMEOUT = 30  # seconds before a hung query is abandoned


class BQQueryError(Exception):
    """Raised for validation failures or BigQuery execution errors."""
    pass


class BigQueryClient:
    def __init__(self, config: Config):
        """
        Initialise the BigQuery client using the first available credential source:

          1. GOOGLE_CREDENTIALS_JSON  — service account JSON pasted as a string
                                        (used on Render and other PaaS platforms)
          2. GOOGLE_APPLICATION_CREDENTIALS — path to a service account JSON file
                                        (used for local development)
          3. Neither set              — falls back to Application Default Credentials
                                        (used on Cloud Run via Workload Identity)
        """
        if config.GOOGLE_CREDENTIALS_JSON:
            credentials = service_account.Credentials.from_service_account_info(
                json.loads(config.GOOGLE_CREDENTIALS_JSON)
            )
            self._client = bigquery.Client(project=config.BQ_PROJECT_ID, credentials=credentials)
        elif config.GOOGLE_APPLICATION_CREDENTIALS:
            credentials = service_account.Credentials.from_service_account_file(
                config.GOOGLE_APPLICATION_CREDENTIALS
            )
            self._client = bigquery.Client(project=config.BQ_PROJECT_ID, credentials=credentials)
        else:
            # No explicit credentials — BigQuery SDK picks up ADC automatically
            self._client = bigquery.Client(project=config.BQ_PROJECT_ID)

    def run_query(self, sql: str) -> str:
        """
        Validate and execute a SQL query, returning results as a markdown table string.

        Validation rejects anything that isn't a SELECT statement.
        A LIMIT clause is appended if the query doesn't include one.

        Raises:
            BQQueryError: if validation fails or BigQuery returns an error.
        """
        sql = sql.strip()
        _validate_select_only(sql)
        sql = _inject_limit(sql)

        logger.info("Running BQ query:\n%s", sql)
        try:
            job = self._client.query(sql)
            df = job.result(timeout=_QUERY_TIMEOUT).to_dataframe()
        except Exception as exc:
            raise BQQueryError(f"BigQuery error: {exc}") from exc

        return _format_results(df)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _validate_select_only(sql: str) -> None:
    """
    Reject any query that is not a plain SELECT statement.

    Two-pass check:
      1. First token must be SELECT — catches most non-SELECT statements quickly.
      2. Regex scan for forbidden keywords — catches SELECT ... DELETE FROM subqueries
         or other injection attempts that pass the first check.
    """
    first_token = sql.split()[0].upper() if sql.split() else ""
    if first_token != "SELECT":
        raise BQQueryError("Only SELECT queries are allowed.")

    forbidden = re.compile(
        r"\b(INSERT|UPDATE|DELETE|DROP|CREATE|ALTER|TRUNCATE|MERGE|CALL)\b",
        re.IGNORECASE,
    )
    if forbidden.search(sql):
        raise BQQueryError("Query contains a forbidden keyword.")


def _inject_limit(sql: str) -> str:
    """
    Append LIMIT _MAX_ROWS if the query has no LIMIT clause.

    Prevents Claude from accidentally pulling the entire table into the
    context window when it writes an open-ended aggregation query.
    """
    if not re.search(r"\bLIMIT\b", sql, re.IGNORECASE):
        return f"{sql}\nLIMIT {_MAX_ROWS}"
    return sql


def _format_results(df: pd.DataFrame) -> str:
    """
    Convert a query result DataFrame into a markdown table string for the LLM.

    Shows at most 50 rows in the table (to keep context token count reasonable),
    but reports the true total row count in a trailing note.
    Numeric columns are rounded to 2 decimal places before formatting.
    """
    if df.empty:
        return "Query returned no results."

    row_count = len(df)

    for col in df.select_dtypes(include="number").columns:
        df[col] = df[col].round(2)

    table = df.head(50).to_markdown(index=False)

    note = f"\n\n_{row_count} row(s) returned" + (
        f"; showing first 50._" if row_count > 50 else "._"
    )
    return table + note