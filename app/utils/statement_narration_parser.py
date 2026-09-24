"""
Bank statement narration parser.

This module is intentionally focused on narration/description strings that
come from bank statements after row extraction. It does not parse dates,
amounts, or SMS-style free-form text.
"""

from __future__ import annotations

import re
from typing import Final

SEPARATOR_RE: Final[re.Pattern[str]] = re.compile(r"[\/\-,|]+")
WHITESPACE_RE: Final[re.Pattern[str]] = re.compile(r"\s+")
REFERENCE_RE: Final[re.Pattern[str]] = re.compile(r"\b\d{6,}\b")
WORD_RE: Final[re.Pattern[str]] = re.compile(r"[a-z0-9]+")

MODE_PATTERNS: Final[dict[str, tuple[str, ...]]] = {
    "upi": ("upi",),
    "card": ("pos", "card"),
    "transfer": ("neft", "imps"),
    "cash": ("atm",),
}

TYPE_HINT_PATTERNS: Final[dict[str, tuple[str, ...]]] = {
    "debit": ("dr", "debit", "debited"),
    "credit": ("cr", "credit", "credited"),
}

# Easy extension point for new narration noise tokens.
BANKING_JUNK_WORDS: Final[set[str]] = {
    "upi",
    "dr",
    "cr",
    "txn",
    "tx",
    "ref",
    "refno",
    "p2a",
    "atm",
    "to",
    "by",
    "from",
    "neft",
    "imps",
    "pos",
    "card",
    "payment",
    "at",
    "no",
    "ltd",
    "pvt",
    "private",
    "limited",
    "india",
    "ind",
    "co",
}


def _normalize_text(value: str) -> str:
    text = WHITESPACE_RE.sub(" ", str(value or "").strip())
    return text


def _detect_mode(lowered: str) -> str:
    for mode, hints in MODE_PATTERNS.items():
        if any(hint in lowered for hint in hints):
            return mode
    return "unknown"


def _detect_type_hint(tokens: list[str]) -> str | None:
    lowered_tokens = {token.lower() for token in tokens}
    for hint, markers in TYPE_HINT_PATTERNS.items():
        if any(marker in lowered_tokens for marker in markers):
            return hint
    return None


def _extract_reference(narration: str) -> str | None:
    match = REFERENCE_RE.search(narration)
    if not match:
        return None
    return match.group(0)


def _split_tokens(narration: str) -> list[str]:
    preprocessed = SEPARATOR_RE.sub(" ", narration.lower())
    return WORD_RE.findall(preprocessed)


def _meaningful_tokens(tokens: list[str]) -> list[str]:
    return [
        token
        for token in tokens
        if token not in BANKING_JUNK_WORDS
        and not token.isdigit()
        and len(token) > 1
    ]


def parse_narration(narration: str) -> dict:
    """
    Parse a bank statement narration string into structured components.

    Returns:
        {
            "clean_description": str,
            "merchant": str | None,
            "location": str | None,
            "mode": str,
            "type_hint": str | None,
            "reference": str | None,
            "tokens": list[str],
        }
    """

    normalized = _normalize_text(narration)
    if not normalized:
        return {
            "clean_description": "",
            "merchant": None,
            "location": None,
            "mode": "unknown",
            "type_hint": None,
            "reference": None,
            "tokens": [],
        }

    lowered = normalized.lower()
    raw_tokens = _split_tokens(normalized)
    meaningful_tokens = _meaningful_tokens(raw_tokens)

    merchant = meaningful_tokens[0] if meaningful_tokens else None
    location = meaningful_tokens[-1] if len(meaningful_tokens) > 1 else None

    return {
        "clean_description": " ".join(meaningful_tokens),
        "merchant": merchant,
        "location": location,
        "mode": _detect_mode(lowered),
        "type_hint": _detect_type_hint(raw_tokens),
        "reference": _extract_reference(normalized),
        "tokens": meaningful_tokens,
    }
