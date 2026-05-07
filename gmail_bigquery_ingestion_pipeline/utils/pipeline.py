"""
Orchestrator for the daily sales ingestion pipeline.

Flow: Gmail (IMAP) → BigQuery raw layer

Usage (local):
    cd gmail_bigquery_ingestion_pipeline
    python -m utils.pipeline
"""

import logging
import sys

from utils.alerting import (
    send_already_ingested_alert,
    send_failure_alert,
    send_no_attachment_alert,
    send_no_email_alert,
    send_quality_report,
)
from utils.attachment_parser import AttachmentParseError, NoAttachmentError, parse_csv_attachment
from utils.bq_loader import BQLoadError, BigQueryLoader
from utils.config import Config
from utils.gmail_reader import GmailReader, NoMatchingEmailError
from utils.logging_config import setup_logging

logger = logging.getLogger(__name__)


def run(config: Config) -> None:
    """
    Executes one pipeline run: fetch email → idempotency check → parse CSV → load to BQ.
    Idempotency is keyed on the CSV filename (_source_filename); re-running with the
    same file is safe and exits early without touching BigQuery writes.
    """
    reader = GmailReader(config)
    loader = BigQueryLoader(config)

    result = reader.fetch_latest_sales_email()

    if result.csv_bytes is None or result.csv_filename is None:
        send_no_attachment_alert(config, result.subject)
        raise NoAttachmentError(
            f"No valid CSV attachment found in email: {result.subject!r}"
        )

    # Exit early if this file has already been loaded — prevents duplicate rows.
    if loader.is_already_ingested(result.csv_filename):
        logger.info(
            "Skipping — '%s' already exists in %s.%s.%s",
            result.csv_filename, config.BQ_PROJECT_ID, config.BQ_DATASET_ID, config.BQ_RAW_TABLE,
        )
        send_already_ingested_alert(config, result.csv_filename)
        return

    df = parse_csv_attachment(result.csv_bytes, result.csv_filename)

    print(df.head())  # TODO: remove before production

    loader.ensure_table_exists()
    rows_loaded = loader.load(df, result.csv_filename, result.run_date, result.email_received_at)

    logger.info(
        "Pipeline complete. run_date=%s source=%s rows=%d table=%s.%s.%s",
        result.run_date,
        result.csv_filename,
        rows_loaded,
        config.BQ_PROJECT_ID,
        config.BQ_DATASET_ID,
        config.BQ_RAW_TABLE,
    )

    send_quality_report(config, df, result.csv_filename, result.run_date, rows_loaded)


def _print_config(config: Config) -> None:
    # Show first 4 chars of secrets to confirm the right value is loaded without exposing it.
    mask = lambda v: (v[:4] + "****") if len(v) > 4 else ("****" if v else "NOT SET")
    print("--- Config ---")
    print(f"  GMAIL_HOST           : {config.GMAIL_HOST or 'NOT SET'}")
    print(f"  GMAIL_PORT           : {config.GMAIL_PORT}")
    print(f"  GMAIL_EMAIL          : {config.GMAIL_EMAIL or 'NOT SET'}")
    print(f"  GMAIL_APP_PASSWORD   : {mask(config.GMAIL_APP_PASSWORD)}")
    print(f"  GMAIL_SUBJECT_FILTER : {config.GMAIL_SUBJECT_FILTER or 'NOT SET'}")
    print(f"  GMAIL_SUBJECT_PATTERN: {config.GMAIL_SUBJECT_PATTERN or 'NOT SET'}")
    print(f"  GMAIL_CSV_PATTERN    : {config.GMAIL_CSV_PATTERN or 'NOT SET'}")
    print(f"  GOOGLE_APPLICATION_CREDENTIALS: {config.GOOGLE_APPLICATION_CREDENTIALS or 'NOT SET (using ADC)'}")
    print(f"  BQ_PROJECT_ID        : {config.BQ_PROJECT_ID or 'NOT SET'}")
    print(f"  BQ_DATASET_ID        : {config.BQ_DATASET_ID or 'NOT SET'}")
    print(f"  BQ_RAW_TABLE         : {config.BQ_RAW_TABLE or 'NOT SET'}")
    print(f"  ALERT_RECIPIENT_EMAIL: {config.ALERT_RECIPIENT_EMAIL or 'NOT SET (alerts disabled)'}")
    print("--------------")


def main() -> None:
    setup_logging()
    config = None
    try:
        config = Config.from_env()
        _print_config(config)
        run(config)
    except NoMatchingEmailError as exc:
        logger.error("Pipeline failed: %s", exc)
        if config:
            send_no_email_alert(config)
        sys.exit(1)
    except NoAttachmentError as exc:
        # send_no_attachment_alert was already called inside run() — don't double-alert.
        logger.error("Pipeline failed: %s", exc)
        sys.exit(1)
    except (AttachmentParseError, BQLoadError, EnvironmentError) as exc:
        logger.error("Pipeline failed: %s", exc)
        if config:
            send_failure_alert(config, exc)
        sys.exit(1)
    except Exception as exc:
        logger.exception("Unexpected pipeline failure")
        if config:
            send_failure_alert(config, exc)
        sys.exit(1)


if __name__ == "__main__":
    main()