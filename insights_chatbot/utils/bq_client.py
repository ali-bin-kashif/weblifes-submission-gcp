"""
BigQuery query execution for the insights chatbot.
Read-only: only SELECT statements are allowed.
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

_MAX_ROWS = 500  # hard cap on rows returned to the LLM
_QUERY_TIMEOUT = 30  # seconds


class BQQueryError(Exception):
    pass


class BigQueryClient:
    def __init__(self, config: Config):
        if config.GOOGLE_CREDENTIALS_JSON:
            # Render / PaaS: full service account JSON stored as an env var string
            credentials = service_account.Credentials.from_service_account_info(
                json.loads(config.GOOGLE_CREDENTIALS_JSON)
            )
            self._client = bigquery.Client(project=config.BQ_PROJECT_ID, credentials=credentials)
        elif config.GOOGLE_APPLICATION_CREDENTIALS:
            # Local dev: path to service account JSON file
            credentials = service_account.Credentials.from_service_account_file(
                config.GOOGLE_APPLICATION_CREDENTIALS
            )
            self._client = bigquery.Client(project=config.BQ_PROJECT_ID, credentials=credentials)
        else:
            # Cloud Run / GCP: Application Default Credentials via Workload Identity
            self._client = bigquery.Client(project=config.BQ_PROJECT_ID)

    def run_query(self, sql: str) -> str:
        """
        Validates and executes a SQL query, returns results as a markdown table string.
        Raises BQQueryError on validation failure or BigQuery errors.
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
# Internals
# ---------------------------------------------------------------------------

def _validate_select_only(sql: str) -> None:
    first_token = sql.split()[0].upper() if sql.split() else ""
    if first_token != "SELECT":
        raise BQQueryError("Only SELECT queries are allowed.")

    # Block any statement that could mutate data
    forbidden = re.compile(
        r"\b(INSERT|UPDATE|DELETE|DROP|CREATE|ALTER|TRUNCATE|MERGE|CALL)\b",
        re.IGNORECASE,
    )
    if forbidden.search(sql):
        raise BQQueryError("Query contains a forbidden keyword.")


def _inject_limit(sql: str) -> str:
    """Appends LIMIT if not already present, to prevent accidentally large result sets."""
    if not re.search(r"\bLIMIT\b", sql, re.IGNORECASE):
        return f"{sql}\nLIMIT {_MAX_ROWS}"
    return sql


def _format_results(df: pd.DataFrame) -> str:
    if df.empty:
        return "Query returned no results."

    row_count = len(df)

    # Round numeric columns to 2dp for cleaner LLM context
    for col in df.select_dtypes(include="number").columns:
        df[col] = df[col].round(2)

    # Markdown table (LLM reads this well)
    table = df.head(50).to_markdown(index=False)

    note = f"\n\n_{row_count} row(s) returned" + (
        f"; showing first 50._" if row_count > 50 else "._"
    )
    return table + note