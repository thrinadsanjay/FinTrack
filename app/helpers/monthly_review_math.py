"""Deterministic monthly financial review numbers.

AI may only write narrative around these facts. Missing inputs stay missing.
"""

from __future__ import annotations

from datetime import date

from app.helpers.money import format_inr, round_money
from app.helpers.planning_math import as_date, percent_change


def build_monthly_review(payload: dict) -> dict:
    today = as_date(payload.get("today")) or date.today()
    month_label = today.strftime("%B %Y")
    income = _opt_money(payload.get("month_income"))
    expense = _opt_money(payload.get("month_expense"))
    prev_income = _opt_money(payload.get("prev_month_income"))
    prev_expense = _opt_money(payload.get("prev_month_expense"))

    net = None
    if income is not None or expense is not None:
        net = round_money((income or 0) - (expense or 0))
    savings_rate = payload.get("savings_rate")
    if savings_rate is None and income and income > 0 and expense is not None:
        savings_rate = round(((income - expense) / income) * 100, 1)

    highlights: list[str] = []
    attention: list[str] = []
    for item in payload.get("insights") or []:
        category = str(item.get("category") or "")
        title = str(item.get("title") or "").strip()
        if not title:
            continue
        if category == "positive":
            highlights.append(title)
        elif category in {"warning", "attention"}:
            attention.append(title)

    category_changes = []
    for item in payload.get("category_changes") or []:
        change = item.get("change_pct")
        if change is None or abs(float(change)) < 8:
            continue
        category_changes.append(
            {
                "name": item.get("name"),
                "current": round_money(item.get("current")),
                "previous": _opt_money(item.get("previous")),
                "change_pct": round(float(change), 1),
            }
        )
    category_changes.sort(key=lambda row: abs(row["change_pct"]), reverse=True)

    cards = payload.get("credit_cards") or {}
    goals = []
    for goal in payload.get("goals") or []:
        if goal.get("status") and goal.get("status") != "active":
            continue
        goals.append(
            {
                "name": goal.get("name"),
                "progress_pct": goal.get("progress_pct"),
                "current_amount": round_money(goal.get("current_amount")),
                "target_amount": round_money(goal.get("target_amount")),
                "on_track": goal.get("on_track"),
            }
        )

    upcoming = list(payload.get("upcoming") or [])[:8]
    cash_flow = {
        "income": income,
        "expense": expense,
        "net": net,
        "savings_rate": savings_rate,
        "income_change_pct": percent_change(income, prev_income),
        "expense_change_pct": percent_change(expense, prev_expense),
        "prev_income": prev_income,
        "prev_expense": prev_expense,
    }

    return {
        "month_label": month_label,
        "today": today.isoformat(),
        "cash_flow": cash_flow,
        "highlights": highlights[:5],
        "attention": attention[:5],
        "category_changes": category_changes[:8],
        "credit_cards": {
            "outstanding": _opt_money(cards.get("total_outstanding") or cards.get("outstanding")),
            "utilization": cards.get("overall_utilization") if cards.get("overall_utilization") is not None else cards.get("utilization"),
            "upcoming_due": _opt_money(cards.get("upcoming_due")),
            "card_count": cards.get("card_count"),
        },
        "goals": goals[:8],
        "upcoming": upcoming,
        "upcoming_count": len(payload.get("upcoming") or upcoming),
        "suggested_review": [row["name"] for row in category_changes[:3] if row.get("change_pct", 0) > 0],
        "disclaimer": (
            "Figures are calculated from your FinTracker records for this month. "
            "This is not financial advice."
        ),
        "narrative": None,
    }


def explanation_facts(*, insight: dict, category_changes: list[dict] | None = None) -> dict:
    """Facts the explainer is allowed to use. No inferred causes."""
    title = str(insight.get("title") or "")
    detail = str(insight.get("detail") or "")
    key = str(insight.get("key") or "")
    matching = []
    for item in category_changes or []:
        name = str(item.get("name") or "")
        if name and name.lower() in title.lower():
            matching.append(
                {
                    "name": name,
                    "current": item.get("current"),
                    "previous": item.get("previous"),
                    "average": item.get("average"),
                    "change_pct": item.get("change_pct"),
                    "merchants": item.get("merchants") or [],
                }
            )
    return {
        "insight_key": key,
        "title": title,
        "detail": detail,
        "category": insight.get("category"),
        "related_categories": matching,
        "can_explain_cause": bool(matching and any((row.get("merchants") or row.get("previous") is not None) for row in matching)),
    }


def fallback_explanation(facts: dict) -> str:
    title = str(facts.get("title") or "This figure changed")
    related = facts.get("related_categories") or []
    if related:
        row = related[0]
        name = row.get("name") or "this category"
        current = row.get("current")
        previous = row.get("previous")
        merchants = row.get("merchants") or []
        if current is not None and previous is not None and merchants:
            top = ", ".join(str(m.get("name") or m) for m in merchants[:3])
            return (
                f"{title} {name} went from {format_inr(previous)} "
                f"to {format_inr(current)}. "
                f"The largest recorded merchants were {top}."
            )
        if current is not None and previous is not None:
            return (
                f"{title} Recorded spending in {name} moved from "
                f"{format_inr(previous)} to {format_inr(current)}."
            )
    change_bit = title.rstrip(".")
    return (
        f"{change_bit}, but the available transaction data does not show a clear reason."
    )


def _opt_money(value):
    if value is None:
        return None
    return round_money(value)
