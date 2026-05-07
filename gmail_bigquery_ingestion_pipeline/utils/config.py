import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()

@dataclass
class Config:
    # Gmail IMAP
    GMAIL_HOST: str
    GMAIL_PORT: int
    GMAIL_EMAIL: str
    GMAIL_APP_PASSWORD: str
    # Two-stage filtering: FILTER is the coarse IMAP server-side substring search;
    # PATTERN is the exact Python regex applied client-side to rule out partial matches.
    GMAIL_SUBJECT_FILTER: str
    GMAIL_SUBJECT_PATTERN: str
    GMAIL_CSV_PATTERN: str      # regex matched against attachment filenames

    # BigQuery
    # Empty string → ADC (Workload Identity on GCP); set to a key file path for local dev.
    GOOGLE_APPLICATION_CREDENTIALS: str
    BQ_PROJECT_ID: str
    BQ_DATASET_ID: str
    BQ_RAW_TABLE: str

    # Alerting — leave empty to disable all email alerts
    ALERT_RECIPIENT_EMAIL: str

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            GMAIL_HOST=os.getenv("GMAIL_HOST", "imap.gmail.com"),
            GMAIL_PORT=int(os.getenv("GMAIL_PORT", "993")),
            GMAIL_EMAIL=os.getenv("GMAIL_EMAIL", ""),
            GMAIL_APP_PASSWORD=os.getenv("GMAIL_APP_PASSWORD", ""),
            GMAIL_SUBJECT_FILTER=os.getenv("GMAIL_SUBJECT_FILTER", "[E-Com] Daily Sales Export"),
            GMAIL_SUBJECT_PATTERN=os.getenv("GMAIL_SUBJECT_PATTERN", r"^\[E-Com\] Daily Sales Export\s*[–-]\s*\d{4}-\d{2}-\d{2}$"),
            GMAIL_CSV_PATTERN=os.getenv("GMAIL_CSV_PATTERN", r"^e_com_sales_\d{8}\.csv$"),
            GOOGLE_APPLICATION_CREDENTIALS=os.getenv("GOOGLE_APPLICATION_CREDENTIALS", ""),
            BQ_PROJECT_ID=os.getenv("BQ_PROJECT_ID", ""),
            BQ_DATASET_ID=os.getenv("BQ_DATASET_ID", ""),
            BQ_RAW_TABLE=os.getenv("BQ_RAW_TABLE", "raw_orders"),
            ALERT_RECIPIENT_EMAIL=os.getenv("ALERT_RECIPIENT_EMAIL", ""),
        )