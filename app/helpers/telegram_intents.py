"""Detect natural-language finance intents for the Telegram assistant.

Guided transaction entry is unchanged. Intents are only used when the
message looks like a question or status request, not a new spend.
"""

from __future__ import annotations

import re

INTENT_SAFE_TO_SPEND = "safe_to_spend"
INTENT_SPENDING = "spending"
INTENT_CREDIT_CARDS = "credit_cards"
INTENT_NET_WORTH = "net_worth"
INTENT_FORECAST = "forecast"
INTENT_BALANCE = "balance"
INTENT_GOALS = "goals"
INTENT_BILLS = "bills"
INTENT_HEALTH = "health"
INTENT_SUMMARY = "summary"

_AMOUNT_RE = re.compile(r"(?:₹|rs\.?)?\s*\d[\d,]*(?:\.\d{1,2})?", re.IGNORECASE)

CATEGORY_HINTS = {
    "food": ("food", "dining", "restaurant", "restaurants", "swiggy", "zomato", "grocery", "groceries"),
    "shopping": ("shopping", "amazon", "flipkart", "myntra"),
    "travel": ("travel", "uber", "ola", "fuel", "petrol"),
    "subscriptions": ("subscription", "subscriptions", "netflix", "spotify", "hotstar"),
    "bills": ("rent", "electricity", "wifi", "broadband", "utility", "utilities"),
}


def looks_like_question(text: str) -> bool:
    raw = str(text or "").strip().lower()
    if not raw:
        return False
    if raw.endswith("?"):
        return True
    starters = (
        "how ", "what ", "what's", "whats ", "show ", "tell ", "can i",
        "do i", "am i", "is my", "are my", "where ", "when ",
    )
    return raw.startswith(starters)


def looks_like_quick_transaction(text: str) -> bool:
    """True when the text is likely a spend to log, not a question."""
    raw = str(text or "").strip()
    if looks_like_question(raw):
        return False
    if not _AMOUNT_RE.search(raw):
        return False
    lower = raw.lower()
    question_bits = ("how much", "safe to spend", "net worth", "forecast", "credit card")
    if any(bit in lower for bit in question_bits):
        return False
    return True


def category_hint(text: str) -> str | None:
    lower = str(text or "").lower()
    for name, needles in CATEGORY_HINTS.items():
        if any(n in lower for n in needles):
            return name
    return None


def detect_finance_intent(text: str) -> dict | None:
    raw = str(text or "").strip()
    if not raw:
        return None
    if looks_like_quick_transaction(raw):
        return None
    lower = raw.lower()

    def hit(*needles: str) -> bool:
        return any(n in lower for n in needles)

    if hit("safe to spend", "safetospend", "can i spend", "how much can i spend", "afford"):
        return {"intent": INTENT_SAFE_TO_SPEND, "category": None}
    if hit("net worth", "networth", "assets and liabilities"):
        return {"intent": INTENT_NET_WORTH, "category": None}
    if hit("credit card", "credit cards", "outstanding", "utilization", "card dues"):
        return {"intent": INTENT_CREDIT_CARDS, "category": None}
    if hit("forecast", "end of the month", "end of this month", "will my balance"):
        return {"intent": INTENT_FORECAST, "category": None}
    if hit("financial health", "health score", "how am i doing"):
        return {"intent": INTENT_HEALTH, "category": None}
    if hit("goal", "emergency fund", "saving for"):
        return {"intent": INTENT_GOALS, "category": None}
    if hit("upcoming bill", "upcoming dues", "bills due", "what's due", "whats due"):
        return {"intent": INTENT_BILLS, "category": None}
    if hit("how much did i spend", "spent on", "spending on", "spend on", "where did my money"):
        return {"intent": INTENT_SPENDING, "category": category_hint(lower)}
    if hit("month summary", "this month") and hit("summary", "income", "expense", "spent"):
        return {"intent": INTENT_SUMMARY, "category": category_hint(lower)}
    if hit("what's my balance", "whats my balance", "show balance", "my balances", "account balance"):
        return {"intent": INTENT_BALANCE, "category": None}
    if looks_like_question(raw) and hit("balance"):
        return {"intent": INTENT_BALANCE, "category": None}
    if looks_like_question(raw) and hit("spend", "spent", "spending"):
        return {"intent": INTENT_SPENDING, "category": category_hint(lower)}
    if looks_like_question(raw) and hit("card"):
        return {"intent": INTENT_CREDIT_CARDS, "category": None}
    return None
