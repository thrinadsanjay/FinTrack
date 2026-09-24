"""
Goal <-> investment link math. Pure functions, no database access.

A goal can be funded by:
- recurring rules (SIP, RD, monthly transfer to an investment account): every
  posted instalment counts, and the rule's schedule gives a monthly commitment;
- one-time transactions (lump-sum FD, a stock buy, a bonus parked in MF).
"""

from __future__ import annotations

from datetime import date, datetime

from dateutil.relativedelta import relativedelta

from app.helpers.money import round_money

# Average occurrences per month for each recurring frequency (interval 1).
MONTHLY_FACTOR = {
    "daily": 30.4375,
    "weekly": 52.0 / 12.0,
    "biweekly": 26.0 / 12.0,
    "monthly": 1.0,
    "quarterly": 1.0 / 3.0,
    "halfyearly": 1.0 / 6.0,
    "yearly": 1.0 / 12.0,
}

# Months of one-time history averaged into a pace when no recurring rule is linked.
ONE_TIME_PACE_WINDOW_MONTHS = 6

INVESTMENT_CATEGORY_CODES = frozenset({"investments_expense"})
INVESTMENT_SUBCATEGORY_CODES = frozenset(
    {
        "sip",
        "stocks",
        "savings",
        "fixed_deposit",
        "recurring_deposit",
        "mutual_funds",
        "crypto",
        "gold",
        "bonds",
    }
)


def monthly_equivalent(amount: float | None, frequency: str | None, interval: int | None = 1) -> float:
    factor = MONTHLY_FACTOR.get(str(frequency or "").strip().lower())
    if not factor:
        return 0.0
    every = max(1, int(interval or 1))
    return round_money(float(amount or 0) * factor / every)


def rule_status(rule: dict) -> str:
    if rule.get("ended_at"):
        return "ended"
    if rule.get("is_active") is False:
        return "paused"
    return "active"


def is_investment_like(*, category: dict | None, subcategory: dict | None, account_type: str | None) -> bool:
    """Heuristic used to rank link candidates; users can still link anything they own."""
    if str(account_type or "") == "investment":
        return True
    if str((category or {}).get("code") or "") in INVESTMENT_CATEGORY_CODES:
        return True
    return str((subcategory or {}).get("code") or "") in INVESTMENT_SUBCATEGORY_CODES


def _as_day(value) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return None


def summarize_goal_links(
    *,
    linked_rules: list[dict],
    contributions: list[dict],
    today: date,
    recent_limit: int = 6,
) -> dict:
    """
    linked_rules: rule docs {_id, description, amount, frequency, interval, is_active, ended_at}
    contributions: posted ledger rows {_id, amount, created_at, description, recurring_id}
    """
    posted_by_rule: dict[str, dict] = {}
    one_time_total = 0.0
    one_time_count = 0
    one_time_recent_total = 0.0
    # Current month plus the previous (window - 1) months.
    window_start = date(today.year, today.month, 1) - relativedelta(months=ONE_TIME_PACE_WINDOW_MONTHS - 1)

    for row in contributions:
        amount = float(row.get("amount") or 0)
        rule_id = row.get("recurring_id")
        if rule_id:
            bucket = posted_by_rule.setdefault(str(rule_id), {"total": 0.0, "count": 0})
            bucket["total"] += amount
            bucket["count"] += 1
        else:
            one_time_total += amount
            one_time_count += 1
            day = _as_day(row.get("created_at"))
            if day and day >= window_start:
                one_time_recent_total += amount

    rules = []
    monthly_commitment = 0.0
    for rule in linked_rules:
        rid = str(rule.get("_id"))
        status = rule_status(rule)
        per_month = monthly_equivalent(rule.get("amount"), rule.get("frequency"), rule.get("interval"))
        if status == "active":
            monthly_commitment += per_month
        posted = posted_by_rule.get(rid, {"total": 0.0, "count": 0})
        rules.append(
            {
                "id": rid,
                "name": rule.get("description") or "Recurring investment",
                "amount": round_money(rule.get("amount")),
                "frequency": rule.get("frequency"),
                "interval": int(rule.get("interval") or 1),
                "status": status,
                "monthly_equivalent": per_month,
                "posted_total": round_money(posted["total"]),
                "posted_count": posted["count"],
            }
        )

    recurring_total = sum(r["posted_total"] for r in rules)
    one_time_pace = round_money(one_time_recent_total / ONE_TIME_PACE_WINDOW_MONTHS)
    monthly_commitment = round_money(monthly_commitment)
    has_links = bool(linked_rules) or one_time_count > 0

    recent = sorted(
        contributions,
        key=lambda r: r.get("created_at") or datetime.min,
        reverse=True,
    )[:recent_limit]

    return {
        "has_links": has_links,
        "invested_total": round_money(recurring_total + one_time_total),
        "recurring_total": round_money(recurring_total),
        "one_time_total": round_money(one_time_total),
        "one_time_count": one_time_count,
        "monthly_commitment": monthly_commitment,
        # Scheduled money is the best predictor; fall back to recent lump sums.
        "linked_pace": monthly_commitment if monthly_commitment > 0 else (one_time_pace if one_time_pace > 0 else 0.0),
        "rules": rules,
        "recent": [
            {
                "id": str(r.get("_id")),
                "amount": round_money(r.get("amount")),
                "date": r.get("created_at"),
                "description": r.get("description") or "Contribution",
                "source": "recurring" if r.get("recurring_id") else "one_time",
            }
            for r in recent
        ],
    }


def projected_at_target(*, current: float, monthly_pace: float | None, months_to_target: float) -> float | None:
    if monthly_pace is None or months_to_target <= 0:
        return None
    return round_money(current + monthly_pace * months_to_target)


def goal_health(*, status: str, completed: bool, on_track: bool | None, has_target_date: bool) -> tuple[str, str]:
    """(key, label) used for the card badge."""
    if status == "completed" or completed:
        return "done", "Completed"
    if status == "paused":
        return "paused", "Paused"
    if on_track is True:
        return "on_track", "On track"
    if on_track is False:
        return "behind", "Behind"
    return "neutral", "Needs data" if has_target_date else "No deadline"
