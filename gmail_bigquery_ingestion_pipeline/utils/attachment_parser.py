import io
import logging

import pandas as pd

logger = logging.getLogger(__name__)


class AttachmentParseError(Exception):
    pass


class NoAttachmentError(AttachmentParseError):
    """Raised when the email is found but has no matching CSV attachment."""
    pass


def parse_csv_attachment(csv_bytes: bytes, filename: str) -> pd.DataFrame:
    """
    Parses raw CSV bytes into a DataFrame.
    All columns are kept as strings — type casting happens in the staging/clean layer.
    Raises AttachmentParseError on any parsing failure.
    """
    try:
        # keep_default_na=False preserves strings like "N/A" or "None" as-is instead
        # of converting them to NaN — required because the raw layer stores everything as text.
        df = pd.read_csv(io.BytesIO(csv_bytes), dtype=str, keep_default_na=False)
    except Exception as exc:
        raise AttachmentParseError(f"Failed to parse '{filename}': {exc}") from exc

    if df.empty:
        raise AttachmentParseError(f"CSV '{filename}' is empty.")

    logger.info("Parsed '%s': %d rows, %d columns", filename, len(df), len(df.columns))
    return df