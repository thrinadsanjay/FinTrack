"""Bank/transaction description cleaner for the merchant memory layer."""

from __future__ import annotations

import re
from typing import Any

WHITESPACE_RE = re.compile(r"\s+")
NON_WORD_RE = re.compile(r"[^a-z0-9 ]+")
LONG_NUMBER_RE = re.compile(r"\b[a-z]*\d[a-z0-9]{5,}\b", re.IGNORECASE)
DATE_RE = re.compile(r"\b\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?\b")

NOISE_WORDS = {
    # Transaction/Banking terms
    "upi",
    "txn",
    "tx",
    "txnid",
    "txnid",
    "utr",
    "rrn",
    "ref",
    "refno",
    "reference",
    "id",
    "imps",
    "neft",
    "rtgs",
    "pos",
    "card",
    "debit",
    "credit",
    "debited",
    "credited",
    "dr",
    "cr",
    "payment",
    "payments",
    "transfer",
    "transfers",
    "received",
    "sent",
    "from",
    "to",
    "by",
    "via",
    "at",
    "bank",
    "acct",
    "account",
    "a",
    "c",
    "no",
    "number",
    "mobile",
    "mb",
    "inb",
    "paid",
    "pay",
    "pays",
    "sent",
    "ybl",
    "okhdfcbank",
    "okicicibank",
    "okaxis",
    "oksbi",
    "ibl",
    "upi",
    "bankl",
    "mahi",
    "sm",
    "lite",
    "online",
    "services",
    "india",
    "pvt",
    "ltd",
    "private",
    "limited",
    "technologies",
    "tech",
    "solutions",
    "enterprises",
    "international",
    # Payment apps/platforms
    "paytm",
    "cred",
    "gpay",
    "googlepay",
    "google",
    "pay",
    "phonepay",
    "phonepe",
    "whatsapp",
    "stripe",
    "razorpay",
    "paypal",
    # Bank names (India major banks)
    "hdfc",
    "icici",
    "axis",
    "sbi",
    "kotak",
    "yes",
    "indusind",
    "rbl",
    "dbs",
    "hsbc",
    "stan",
    "standardchartered",
    "citibank",
    "citi",
    "federal",
    "bob",
    "boi",
    "union",
    "canara",
    "central",
    "pnb",
    "idbi",
    "uco",
    # Payment/fintech services (apps, not merchants)
    # Note: Do NOT include merchant names (amazon, swiggy, starbucks, etc.)
    # Only include payment platforms and gateways
}


def _normalize_text(value: Any) -> str:
    return WHITESPACE_RE.sub(" ", str(value or "").strip().lower())


def clean_description(description: str) -> str:
    """
    Normalize a transaction description into a stable merchant-memory key.

    This intentionally strips noisy banking tokens, long references, and
    digits-heavy fragments while preserving meaningful merchant words.
    """

    text = _normalize_text(description)
    if not text:
        return ""

    text = DATE_RE.sub(" ", text)
    text = LONG_NUMBER_RE.sub(" ", text)
    text = NON_WORD_RE.sub(" ", text)

    tokens: list[str] = []
    for token in text.split():
        if token.isdigit():
            continue
        if len(token) == 1 and token not in {"e"}:
            continue
        if token in NOISE_WORDS:
            continue
        if any(char.isdigit() for char in token):
            continue
        tokens.append(token)

    return " ".join(tokens)


__all__ = ["clean_description"]
