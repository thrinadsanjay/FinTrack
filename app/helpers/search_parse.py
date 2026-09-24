"""Parse global-search queries into structured filters.

Pure helper: no I/O. Used by the search service and unit tests.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from difflib import SequenceMatcher

from dateutil.relativedelta import relativedelta

_AMOUNT_RE = re.compile(
    r"(?:₹|rs\.?|inr)?\s*([0-9]{1,3}(?:,[0-9]{2,3})+|[0-9]+(?:\.[0-9]{1,2})?)",
    re.IGNORECASE,
)
_ISO_DATE_RE = re.compile(r"\b(20\d{2})-(\d{1,2})-(\d{1,2})\b")
_DAY_MONTH_RE = re.compile(
    r"\b(\d{1,2})\s+(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
    r"jul(?:y)?|aug(?:ust)?|sep(?:t|tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
    r"(?:\s+(20\d{2}))?\b",
    re.IGNORECASE,
)
_MONTH_RE = re.compile(
    r"\b(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
    r"jul(?:y)?|aug(?:ust)?|sep(?:t|tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
    r"(?:\s+(20\d{2}))?\b",
    re.IGNORECASE,
)

_MONTHS = {
    "jan": 1, "january": 1,
    "feb": 2, "february": 2,
    "mar": 3, "march": 3,
    "apr": 4, "april": 4,
    "may": 5,
    "jun": 6, "june": 6,
    "jul": 7, "july": 7,
    "aug": 8, "august": 8,
    "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10,
    "nov": 11, "november": 11,
    "dec": 12, "december": 12,
}

STOPWORDS = {
    "the", "a", "an", "on", "in", "of", "for", "my", "to", "and", "or",
    "from", "this", "that", "last", "with",
}


def _month_num(token: str) -> int | None:
    return _MONTHS.get(token.lower())


def parse_search_query(raw: str, *, today: date | None = None) -> dict:
    """Extract amount, date/month window, and remaining text tokens."""
    today = today or date.today()
    text = str(raw or "").strip()
    amounts: list[float] = []
    used_spans: list[tuple[int, int]] = []

    for match in _AMOUNT_RE.finditer(text):
        raw_num = match.group(1).replace(",", "")
        try:
            amounts.append(float(raw_num))
            used_spans.append(match.span())
        except ValueError:
            continue

    date_from: date | None = None
    date_to: date | None = None

    iso = _ISO_DATE_RE.search(text)
    if iso:
        try:
            parsed = date(int(iso.group(1)), int(iso.group(2)), int(iso.group(3)))
            date_from = parsed
            date_to = parsed
            used_spans.append(iso.span())
        except ValueError:
            pass

    if date_from is None:
        day_month = _DAY_MONTH_RE.search(text)
        if day_month:
            month = _month_num(day_month.group(2))
            year = int(day_month.group(3) or today.year)
            try:
                parsed = date(year, month or today.month, int(day_month.group(1)))
                date_from = parsed
                date_to = parsed
                used_spans.append(day_month.span())
            except ValueError:
                pass

    if date_from is None:
        month_match = _MONTH_RE.search(text)
        if month_match:
            month = _month_num(month_match.group(1))
            year = int(month_match.group(2) or today.year)
            if month:
                date_from = date(year, month, 1)
                date_to = date_from + relativedelta(months=1, days=-1)
                used_spans.append(month_match.span())

    cleaned = text
    for start, end in sorted(used_spans, reverse=True):
        cleaned = cleaned[:start] + " " + cleaned[end:]
    tokens = [
        tok
        for tok in re.findall(r"[a-z0-9]+", cleaned.lower())
        if tok not in STOPWORDS and len(tok) > 1
    ]
    haystack = " ".join(tokens)
    return {
        "raw": text,
        "tokens": tokens,
        "haystack": haystack,
        "amounts": amounts,
        "amount": amounts[0] if len(amounts) == 1 else None,
        "date_from": date_from,
        "date_to": date_to,
        "text": " ".join(tokens) or text,
    }


def fuzzy_ratio(left: str, right: str) -> float:
    a = str(left or "").strip().lower()
    b = str(right or "").strip().lower()
    if not a or not b:
        return 0.0
    if a in b or b in a:
        return 1.0
    return SequenceMatcher(None, a, b).ratio()


def field_matches(query: dict, *fields: str, threshold: float = 0.72) -> bool:
    """True when tokens/haystack match any of the provided string fields."""
    haystack = query.get("haystack") or ""
    tokens = query.get("tokens") or []
    if not haystack and not tokens:
        return bool(query.get("amount") is not None or query.get("date_from"))
    blob = " ".join(str(f or "") for f in fields).lower()
    if not blob:
        return False
    if haystack and haystack in blob:
        return True
    if all(tok in blob for tok in tokens):
        return True
    for field in fields:
        if fuzzy_ratio(haystack, field) >= threshold:
            return True
        for tok in tokens:
            if fuzzy_ratio(tok, field) >= threshold:
                return True
    return False


def amount_close(value, target, *, rupee_tolerance: float = 0.5) -> bool:
    if target is None or value is None:
        return False
    try:
        return abs(float(value) - float(target)) <= rupee_tolerance
    except (TypeError, ValueError):
        return False


def in_date_window(value, date_from: date | None, date_to: date | None) -> bool:
    if not date_from and not date_to:
        return True
    parsed: date | None = None
    if isinstance(value, datetime):
        parsed = value.date()
    elif isinstance(value, date):
        parsed = value
    elif isinstance(value, str) and value:
        try:
            parsed = date.fromisoformat(value[:10])
        except ValueError:
            return False
    if parsed is None:
        return False
    if date_from and parsed < date_from:
        return False
    if date_to and parsed > date_to:
        return False
    return True
