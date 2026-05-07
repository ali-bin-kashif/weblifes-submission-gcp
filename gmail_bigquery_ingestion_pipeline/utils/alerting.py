"""
Email alerting via Gmail SMTP.
Uses the same credentials (GMAIL_EMAIL / GMAIL_APP_PASSWORD) as the IMAP reader.
All send functions are non-fatal — failures are logged as warnings so they never
mask the original pipeline outcome.
"""

import logging
import smtplib
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import pandas as pd

from utils.config import Config

logger = logging.getLogger(__name__)

_SMTP_HOST = "smtp.gmail.com"
_SMTP_PORT = 587  # STARTTLS

_COLOR_OK   = "#2e7d32"
_COLOR_WARN = "#c62828"
_COLOR_INFO = "#1a73e8"
_TD = "padding:8px;border:1px solid #ddd;text-align:left"


# ---------------------------------------------------------------------------
# Public alert functions
# ---------------------------------------------------------------------------

def send_no_email_alert(config: Config) -> None:
    """Alert when no email matching the subject filter is found in the inbox."""
    subject = "[ALERT] E-Com Ingestion — No Sales Email Found"
    body = (
        f"Pipeline run at {_utc_now()} found no emails matching the subject filter:\n\n"
        f"  Filter  : {config.GMAIL_SUBJECT_FILTER}\n"
        f"  Pattern : {config.GMAIL_SUBJECT_PATTERN}\n\n"
        "The daily sales export email may not have been sent yet, "
        "or the subject format may have changed."
    )
    _send(config, subject, body, html=False)


def send_no_attachment_alert(config: Config, email_subject: str) -> None:
    """Alert when a matching email is found but has no valid CSV attachment (or an empty one)."""
    subject = "[WARNING] E-Com Ingestion — Missing or Empty CSV Attachment"
    body = (
        f"Pipeline run at {_utc_now()} found a matching email but could not extract a valid CSV.\n\n"
        f"  Email subject : {email_subject}\n"
        f"  Expected file : {config.GMAIL_CSV_PATTERN}\n\n"
        "The attachment may be missing, named differently, or the CSV may be empty."
    )
    _send(config, subject, body, html=False)


def send_already_ingested_alert(config: Config, filename: str) -> None:
    """Notification when the pipeline skips because the file is already loaded into BigQuery."""
    subject = f"[INFO] E-Com Ingestion — Already Loaded: {filename}"
    body = (
        f"Pipeline run at {_utc_now()} skipped — file already exists in BigQuery.\n\n"
        f"  File  : {filename}\n"
        f"  Table : {config.BQ_PROJECT_ID}.{config.BQ_DATASET_ID}.{config.BQ_RAW_TABLE}\n\n"
        "No rows were written. This is expected if the pipeline was re-triggered manually."
    )
    _send(config, subject, body, html=False)


def send_failure_alert(config: Config, error: Exception) -> None:
    """Alert for unexpected pipeline failures (BigQuery errors, network issues, etc.)."""
    subject = "[CRITICAL] E-Com Sales Ingestion Failed"
    body = (
        f"Pipeline run failed at {_utc_now()}.\n\n"
        f"Error: {type(error).__name__}: {error}\n\n"
        "Check Cloud Logging for the full traceback."
    )
    _send(config, subject, body, html=False)


def send_quality_report(
    config: Config,
    df: pd.DataFrame,
    filename: str,
    run_date: str,
    rows_loaded: int,
) -> None:
    """Sends an HTML quality summary after a successful load."""
    subject = f"[REPORT] E-Com Sales Ingestion — {run_date} ({rows_loaded:,} rows)"
    _send(config, subject, _build_report_html(df, filename, run_date, rows_loaded), html=True)


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

def _send(config: Config, subject: str, body: str, *, html: bool) -> None:
    if not config.ALERT_RECIPIENT_EMAIL:
        logger.debug("ALERT_RECIPIENT_EMAIL not set — skipping alert")
        return

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = config.GMAIL_EMAIL
    msg["To"] = config.ALERT_RECIPIENT_EMAIL
    msg.attach(MIMEText(body, "html" if html else "plain"))

    try:
        with smtplib.SMTP(_SMTP_HOST, _SMTP_PORT) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.login(config.GMAIL_EMAIL, config.GMAIL_APP_PASSWORD)
            smtp.sendmail(config.GMAIL_EMAIL, config.ALERT_RECIPIENT_EMAIL, msg.as_string())
        logger.info("Alert sent to %s: %s", config.ALERT_RECIPIENT_EMAIL, subject)
    except Exception as exc:
        logger.warning("Failed to send alert email: %s", exc)


def _build_report_html(df: pd.DataFrame, filename: str, run_date: str, rows_loaded: int) -> str:
    dup_order_ids = int(df.duplicated(subset=["order_id"]).sum())
    full_dups     = int(df.duplicated().sum())

    # Raw layer stores everything as strings; empty string is the null sentinel.
    empty_per_col = {
        col: int((df[col] == "").sum())
        for col in df.columns
        if (df[col] == "").any()
    }

    all_clean    = dup_order_ids == 0 and full_dups == 0 and not empty_per_col
    status_msg   = "All checks passed." if all_clean else "Issues detected — review below."
    status_color = _COLOR_OK if all_clean else _COLOR_WARN

    null_section = (
        _null_table_html(empty_per_col, rows_loaded)
        if empty_per_col
        else f'<p style="color:{_COLOR_OK}">No empty values found across all columns.</p>'
    )

    summary = _kv_table([
        ("File",                 filename),
        ("Run Date",             run_date),
        ("Rows Loaded",          f"{rows_loaded:,}"),
        ("Duplicate order_ids",  _colored(f"{dup_order_ids:,}", _COLOR_WARN if dup_order_ids else _COLOR_OK)),
        ("Full Duplicate Rows",  _colored(f"{full_dups:,}",     _COLOR_WARN if full_dups     else _COLOR_OK)),
        ("Columns with Empties", f"{len(empty_per_col)} / {len(df.columns)}"),
    ])

    return f"""<html>
<body style="font-family:Arial,sans-serif;color:#333;max-width:680px;margin:auto">
  <h2 style="color:{_COLOR_INFO};border-bottom:2px solid {_COLOR_INFO};padding-bottom:6px">
    Daily Sales Ingestion Report
  </h2>
  <p style="font-weight:bold;color:{status_color}">{status_msg}</p>

  <h3>Summary</h3>
  {summary}

  <h3>Empty Values by Column</h3>
  {null_section}

  <hr style="margin-top:28px">
  <p style="color:#888;font-size:12px">E-Com Sales Ingestion Pipeline &mdash; {_utc_now()}</p>
</body>
</html>"""


def _kv_table(rows: list[tuple]) -> str:
    cells = ""
    for i, (key, val) in enumerate(rows):
        bg = ' style="background:#f5f5f5"' if i % 2 == 0 else ""
        cells += f'<tr{bg}><td style="{_TD}"><b>{key}</b></td><td style="{_TD}">{val}</td></tr>'
    return f'<table style="border-collapse:collapse;width:100%">{cells}</table>'


def _null_table_html(empty_per_col: dict, total_rows: int) -> str:
    header = (
        f'<tr style="background:#f5f5f5">'
        f'<th style="{_TD}">Column</th>'
        f'<th style="{_TD}">Empty Count</th>'
        f'<th style="{_TD}">% of Rows</th></tr>'
    )
    rows = ""
    for col, count in sorted(empty_per_col.items(), key=lambda x: -x[1]):
        pct = count / total_rows * 100 if total_rows else 0
        rows += (
            f'<tr><td style="{_TD}">{col}</td>'
            f'<td style="{_TD};color:{_COLOR_WARN}">{count:,}</td>'
            f'<td style="{_TD};color:{_COLOR_WARN}">{pct:.1f}%</td></tr>'
        )
    return f'<table style="border-collapse:collapse;width:100%">{header}{rows}</table>'


def _colored(text: str, color: str) -> str:
    return f'<span style="color:{color}">{text}</span>'


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")