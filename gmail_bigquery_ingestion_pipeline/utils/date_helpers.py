import re

_SUBJECT_DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})$")
_FILENAME_DATE_RE = re.compile(r"e_com_sales_(\d{8})\.csv$")


def parse_date_from_subject(subject: str) -> str:
    """Returns YYYY-MM-DD extracted from subject '[E-Com] Daily Sales Export – YYYY-MM-DD'."""
    match = _SUBJECT_DATE_RE.search(subject)
    if not match:
        raise ValueError(f"Could not parse date from subject: {subject!r}")
    return match.group(1)


def parse_date_from_filename(filename: str) -> str:
    """Returns YYYY-MM-DD extracted from filename 'e_com_sales_YYYYMMDD.csv'."""
    match = _FILENAME_DATE_RE.search(filename)
    if not match:
        raise ValueError(f"Could not parse date from filename: {filename!r}")
    raw = match.group(1)
    return f"{raw[:4]}-{raw[4:6]}-{raw[6:]}"