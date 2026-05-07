import re
import imaplib
import email
import email.utils
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from email.header import decode_header
from typing import Optional

from utils.config import Config
from utils.date_helpers import parse_date_from_subject

logger = logging.getLogger(__name__)


class NoMatchingEmailError(Exception):
    pass


@dataclass
class EmailFetchResult:
    subject: str
    sender: str
    date_header: str
    email_received_at: datetime   # parsed from Date header, timezone-aware
    body: str
    csv_filename: Optional[str]
    csv_bytes: Optional[bytes]
    run_date: str  # YYYY-MM-DD parsed from subject


class GmailReader:
    def __init__(self, config: Config):
        self._host = config.GMAIL_HOST
        self._port = config.GMAIL_PORT
        self._email = config.GMAIL_EMAIL
        self._password = config.GMAIL_APP_PASSWORD
        self._subject_filter = config.GMAIL_SUBJECT_FILTER
        self._subject_pattern = re.compile(config.GMAIL_SUBJECT_PATTERN)
        self._csv_pattern = re.compile(config.GMAIL_CSV_PATTERN)

    def fetch_latest_sales_email(self) -> EmailFetchResult:
        """
        Connects via IMAP, applies two-stage subject filtering, and returns the
        most recently received matching email. Raises NoMatchingEmailError if none match.

        Stage 1 — server-side: IMAP SUBJECT search (substring, fast).
        Stage 2 — client-side: full regex match to reject near-misses.
        """
        logger.info("Connecting to %s:%d as %s", self._host, self._port, self._email)

        with imaplib.IMAP4_SSL(self._host, self._port) as mail:
            mail.login(self._email, self._password)
            mail.select("INBOX")

            _, msg_ids = mail.search(None, f'SUBJECT "{self._subject_filter}"')
            ids = msg_ids[0].split()

            if not ids:
                raise NoMatchingEmailError(f"No emails found matching subject: '{self._subject_filter}'.")

            matches = []
            for msg_id in ids[-20:]:  # cap at 20 to avoid fetching an unbounded history
                result = self._process_message(mail, msg_id)
                if result is not None:
                    matches.append(result)

        if not matches:
            raise NoMatchingEmailError("No emails matched the exact subject pattern.")

        latest = max(matches, key=lambda r: r.email_received_at)
        logger.info(
            "Picked latest of %d match(es): subject=%r received=%s",
            len(matches), latest.subject, latest.email_received_at.isoformat(),
        )
        return latest

    def _process_message(self, mail: imaplib.IMAP4_SSL, msg_id: bytes) -> Optional[EmailFetchResult]:
        _, msg_data = mail.fetch(msg_id, "(RFC822)")
        raw = msg_data[0][1]
        msg = email.message_from_bytes(raw)

        subject = _decode_str(msg.get("Subject", ""))
        if not self._subject_pattern.match(subject):
            return None

        run_date = parse_date_from_subject(subject)
        csv_filename, csv_bytes = self._extract_csv_attachment(msg)
        email_received_at = _parse_date_header(msg.get("Date", ""))

        return EmailFetchResult(
            subject=subject,
            sender=msg.get("From", ""),
            date_header=msg.get("Date", ""),
            email_received_at=email_received_at,
            body=_get_plain_body(msg),
            csv_filename=csv_filename,
            csv_bytes=csv_bytes,
            run_date=run_date,
        )

    def _extract_csv_attachment(self, msg: email.message.Message) -> tuple[Optional[str], Optional[bytes]]:
        for part in msg.walk():
            if part.get_content_disposition() == "attachment":
                filename = part.get_filename()
                if filename and self._csv_pattern.match(_decode_str(filename)):
                    return _decode_str(filename), part.get_payload(decode=True)
        return None, None


# ---------------------------------------------------------------------------
# Module-level helpers (pure functions, no state)
# ---------------------------------------------------------------------------

def _parse_date_header(date_str: str) -> datetime:
    """Parses an email Date header into a timezone-aware datetime. Falls back to UTC now on failure."""
    try:
        return email.utils.parsedate_to_datetime(date_str)
    except Exception:
        return datetime.now(timezone.utc)


def _decode_str(value: str) -> str:
    # Email headers may use MIME encoded-word format (e.g. =?utf-8?b?...?=).
    # decode_header returns a list of (decoded, charset) pairs; we only need the first.
    decoded, charset = decode_header(value)[0]
    if isinstance(decoded, bytes):
        return decoded.decode(charset or "utf-8", errors="ignore")
    return decoded


def _get_plain_body(msg: email.message.Message) -> str:
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain" and not part.get_filename():
                payload = part.get_payload(decode=True)
                return payload.decode("utf-8", errors="ignore") if payload else ""
    else:
        payload = msg.get_payload(decode=True)
        return payload.decode("utf-8", errors="ignore") if payload else ""
    return ""

