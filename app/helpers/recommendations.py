"""Evidence-based, non-prescriptive financial recommendations.

Numbers come from existing planning calculations. This module does not
invent reasons, recommend products, or give regulated advice.
"""

from __future__ import annotations

from app.helpers.money import format_inr

DISCLAIMER = (
    "These notes are based on your FinTracker records. They are not financial, "
    "investment, tax, or credit advice."
)


def build_recommendations(payload: dict) -> list[dict]:
    recs: list[dict] = []

    def add(
        *,
        key: str,
        title: str,
        detail: str,
        evidence: str,
        href: str,
        priority: int,
        tone: str = "info",
    ) -> None:
        recs.append(
            {
                "key": key,
                "title": title,
                "detail": detail,
                "evidence": evidence,
                "href": href,
                "priority": priority,
                "tone": tone,
                "optional": True,
            }
        )

    util = payload.get("utilization")
    if util is not None and util >= 70:
        add(
            key="util_high",
            title="Credit utilization is approaching a high range.",
            detail="A larger share of card limit is currently in use.",
            evidence=f"Overall utilization is {float(util):.0f}%.",
            href="/accounts?group=card",
            priority=10,
            tone="attention",
        )
    elif util is not None and util >= 50:
        add(
            key="util_watch",
            title="Credit utilization is in a watch range.",
            detail="You may want to review upcoming card payments.",
            evidence=f"Overall utilization is {float(util):.0f}%.",
            href="/accounts?group=card",
            priority=25,
            tone="info",
        )

    due_soon = int(payload.get("payments_due_10_days") or payload.get("recurring_due_5_days") or 0)
    upcoming_due = payload.get("upcoming_due")
    if due_soon >= 2:
        add(
            key="payments_cluster",
            title="Several payments are due within the next 10 days.",
            detail="Review the calendar so source accounts stay funded.",
            evidence=f"{due_soon} scheduled payments fall in this window.",
            href="/planning/calendar",
            priority=12,
            tone="attention",
        )
    elif upcoming_due:
        add(
            key="card_due",
            title="Card or bill payments are coming up.",
            detail="Upcoming dues are taken from your existing card and bill records.",
            evidence=f"Upcoming dues total {format_inr(upcoming_due)}.",
            href="/accounts?group=card",
            priority=18,
            tone="info",
        )

    for item in payload.get("category_changes") or []:
        change = item.get("change_pct")
        name = str(item.get("name") or "Spending")
        if change is None or change < 15:
            continue
        add(
            key=f"cat_review:{name}",
            title=f"Consider reviewing your {name.lower()} spending.",
            detail="This month is higher than the recent average recorded in FinTracker.",
            evidence=(
                f"{name} is {abs(float(change)):.0f}% higher "
                f"({format_inr(item.get('current'))} vs typical {format_inr(item.get('average') or item.get('previous'))})."
            ),
            href="/insights",
            priority=20,
            tone="info",
        )
        break

    recurring_delta = payload.get("recurring_commitments_change_pct")
    if recurring_delta is not None and recurring_delta >= 10:
        add(
            key="recurring_up",
            title="Recurring commitments increased this month.",
            detail="Active recurring rules now reserve a larger share of cash.",
            evidence=f"Recurring outflows are {abs(float(recurring_delta)):.0f}% higher than last month.",
            href="/recurring",
            priority=22,
            tone="info",
        )

    for goal in payload.get("goals_behind") or []:
        add(
            key=f"goal_behind:{goal.get('id') or goal.get('name')}",
            title=f"{goal.get('name') or 'A goal'} is behind its target pace.",
            detail=str(goal.get("detail") or "Current savings pace is below the amount implied by the target date."),
            evidence="Calculated from the goal’s target amount, current amount, and target date.",
            href="/planning/goals",
            priority=16,
            tone="attention",
        )
        break

    safe = payload.get("safe_to_spend")
    cash = payload.get("cash")
    reserved = payload.get("reserved")
    if safe is not None and safe <= 0 and reserved:
        add(
            key="safe_zero",
            title="There is no unreserved cash after upcoming obligations.",
            detail="Safe-to-spend is calculated from cash-like accounts minus reserved bills.",
            evidence=(
                f"Available cash {format_inr(cash)} vs reserved {format_inr(reserved)}."
            ),
            href="/planning/safe-to-spend",
            priority=8,
            tone="attention",
        )

    recs.sort(key=lambda row: row["priority"])
    for row in recs:
        row["disclaimer"] = DISCLAIMER
    return recs[:6]
