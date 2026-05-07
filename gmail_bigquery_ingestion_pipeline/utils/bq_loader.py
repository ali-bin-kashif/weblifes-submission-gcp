import logging
from datetime import datetime, timezone

import pandas as pd
from google.cloud import bigquery
from google.oauth2 import service_account

from utils.config import Config

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Raw schema: all source columns are STRING — no type coercion at landing.
# Casting and business logic belong in the staging/clean layer downstream.
# Metadata columns are appended at ingest time by this loader.
# ---------------------------------------------------------------------------
RAW_SCHEMA = [
    bigquery.SchemaField("order_id",          "STRING"),
    bigquery.SchemaField("order_date",         "STRING"),
    bigquery.SchemaField("customer_id",        "STRING"),
    bigquery.SchemaField("customer_name",      "STRING"),
    bigquery.SchemaField("customer_email",     "STRING"),
    bigquery.SchemaField("customer_city",      "STRING"),
    bigquery.SchemaField("customer_state",     "STRING"),
    bigquery.SchemaField("product_name",       "STRING"),
    bigquery.SchemaField("product_category",   "STRING"),
    bigquery.SchemaField("quantity",           "STRING"),
    bigquery.SchemaField("unit_price",         "STRING"),
    bigquery.SchemaField("discount_amount",    "STRING"),
    bigquery.SchemaField("revenue",            "STRING"),
    bigquery.SchemaField("store_name",         "STRING"),
    bigquery.SchemaField("shipping_method",    "STRING"),
    bigquery.SchemaField("shipping_status",    "STRING"),
    bigquery.SchemaField("payment_method",     "STRING"),
    # Ingestion metadata
    bigquery.SchemaField("_ingested_at",       "TIMESTAMP"),
    bigquery.SchemaField("_source_filename",   "STRING"),
    bigquery.SchemaField("_pipeline_run_date", "DATE"),
    bigquery.SchemaField("_email_received_date", "STRING"),
]

_SOURCE_COLUMNS = {f.name for f in RAW_SCHEMA if not f.name.startswith("_")}


class BQLoadError(Exception):
    pass


class BigQueryLoader:
    def __init__(self, config: Config):
        if config.GOOGLE_APPLICATION_CREDENTIALS:
            credentials = service_account.Credentials.from_service_account_file(
                config.GOOGLE_APPLICATION_CREDENTIALS
            )
            self._client = bigquery.Client(project=config.BQ_PROJECT_ID, credentials=credentials)
        else:
            # On GCP (Cloud Functions) — uses Workload Identity / ADC automatically
            self._client = bigquery.Client(project=config.BQ_PROJECT_ID)

        self._table_ref = (
            f"{config.BQ_PROJECT_ID}.{config.BQ_DATASET_ID}.{config.BQ_RAW_TABLE}"
        )

    def is_already_ingested(self, source_filename: str) -> bool:
        """Returns True if this filename has already been loaded into the raw table.

        Returns False on any query error (e.g. table doesn't exist yet on first run)
        so the caller can proceed without special-casing the initial load.
        """
        query = f"""
            SELECT 1
            FROM `{self._table_ref}`
            WHERE _source_filename = @filename
            LIMIT 1
        """
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("filename", "STRING", source_filename)
            ]
        )
        try:
            results = self._client.query(query, job_config=job_config).result()
            return results.total_rows > 0
        except Exception:
            return False

    def ensure_table_exists(self) -> None:
        table = bigquery.Table(self._table_ref, schema=RAW_SCHEMA)
        # Partition by ingestion date so daily scans only touch one partition
        table.time_partitioning = bigquery.TimePartitioning(
            type_=bigquery.TimePartitioningType.DAY,
            field="_pipeline_run_date",
        )
        self._client.create_table(table, exists_ok=True)
        logger.info("Ensured table: %s", self._table_ref)

    def load(self, df: pd.DataFrame, source_filename: str, run_date: str, email_received_at: datetime) -> int:
        """
        Aligns df columns to RAW_SCHEMA, appends metadata, and appends to BigQuery.

        Schema alignment: extra CSV columns are dropped (with a warning); missing
        expected columns are back-filled with empty strings. This keeps the load
        schema-safe even when the upstream CSV format drifts slightly.

        Returns the number of rows written.
        """
        df = df.copy()

        extra = set(df.columns) - _SOURCE_COLUMNS
        missing = _SOURCE_COLUMNS - set(df.columns)
        if extra:
            logger.warning("Dropping unexpected CSV columns: %s", sorted(extra))
            df.drop(columns=list(extra), inplace=True)
        if missing:
            logger.warning("Filling missing CSV columns with empty string: %s", sorted(missing))
            for col in missing:
                df[col] = ""

        # Native Python types are required here — PyArrow maps them to BigQuery types:
        # datetime (tz-aware) → TIMESTAMP, date → DATE, str → STRING.
        # Storing these as formatted strings would cause schema mismatches.
        now = datetime.now(timezone.utc)
        df["_ingested_at"] = now
        df["_source_filename"] = source_filename
        df["_pipeline_run_date"] = datetime.strptime(run_date, "%Y-%m-%d").date()
        df["_email_received_date"] = email_received_at.strftime("%Y-%m-%d")
        

        job_config = bigquery.LoadJobConfig(
            schema=RAW_SCHEMA,
            write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
        )

        try:
            job = self._client.load_table_from_dataframe(df, self._table_ref, job_config=job_config)
            job.result()
            logger.info("Loaded %d rows → %s", len(df), self._table_ref)
            return len(df)
        except Exception as exc:
            raise BQLoadError(f"BigQuery load failed: {exc}") from exc