"""Natural-language Telegram replies using Phase 1 planning data."""

from __future__ import annotations

from datetime import datetime, timezone

from bson import ObjectId

from app.db.mongo import db
from app.helpers.dashboard_time import start_of_month_utc
from app.helpers.money import format_inr, round_money
from app.helpers.planning_math import as_date, percent_change
from app.helpers.telegram_intents import (
    INTENT_BALANCE,
    INTENT_BILLS,
    INTENT_CREDIT_CARDS,
    INTENT_FORECAST,
    INTENT_GOALS,
    INTENT_HEALTH,
    INTENT_NET_WORTH,
    INTENT_SAFE_TO_SPEND,
    INTENT_SPENDING,
    INTENT_SUMMARY,
)
from app.services.audit import audit_log
from app.services.planning import get_planning_overlay, build_planning_bundle


def _next_salary(overlay: dict) -> str:
    for event in (overlay.get("forecast") or {}).get("contributing") or []:
        label = str(event.get("label") or event.get("description") or event.get("name") or "").lower()
        amount = event.get("amount") or 0
        if amount > 0 and ("salary" in label or "income" in label or "payroll" in label):
            day = event.get("date")
            return str(day) if day else "—"
    for event in (overlay.get("calendar") or {}).get("upcoming") or []:
        label = str(event.get("label") or event.get("description") or "").lower()
        if "salary" in label:
            day = as_date(event.get("date"))
            return day.strftime("%b %d") if day else "—"
    return "—"


async def answer_finance_query(*, user_id: ObjectId, intent: dict) -> str:
    kind = intent.get("intent")
    overlay = await get_planning_overlay(str(user_id))
    if kind == INTENT_SAFE_TO_SPEND:
        safe = overlay.get("safe_to_spend") or {}
        return (
            "SAFE TO SPEND\n"
            f"{format_inr(safe.get('amount'))}\n\n"
            f"Available cash\n{format_inr(safe.get('cash'))}\n\n"
            f"Reserved\n{format_inr(safe.get('reserved'))}\n\n"
            f"Next salary\n{_next_salary(overlay)}"
        )
    if kind == INTENT_NET_WORTH:
        worth = overlay.get("net_worth") or {}
        return (
            "Net Worth\n"
            f"{format_inr(worth.get('amount'))}\n\n"
            f"Assets\n{format_inr(worth.get('assets'))}\n\n"
            f"Liabilities\n{format_inr(worth.get('liabilities'))}"
        )
    if kind == INTENT_CREDIT_CARDS:
        cards = overlay.get("credit_cards") or {}
        util = cards.get("utilization")
        util_label = f"{float(util):.0f}%" if util is not None else "—"
        return (
            "Credit Cards\n\n"
            f"Total outstanding\n{format_inr(cards.get('outstanding'))}\n\n"
            f"Utilization\n{util_label}\n\n"
            f"Upcoming dues\n{format_inr(cards.get('upcoming_due'))}"
        )
    if kind == INTENT_FORECAST:
        forecast = overlay.get("forecast") or {}
        return (
            "Forecast\n"
            f"Today {format_inr(forecast.get('today'))}\n"
            f"30 days {format_inr(forecast.get('d30'))}\n"
            f"60 days {format_inr(forecast.get('d60'))}\n"
            f"90 days {format_inr(forecast.get('d90'))}\n"
            f"Lowest {format_inr(forecast.get('lowest'))}"
            + (f" on {forecast.get('lowest_date')}" if forecast.get("lowest_date") else "")
        )
    if kind == INTENT_GOALS:
        goals = overlay.get("goals") or []
        if not goals:
            return "No active goals."
        lines = ["Goals"]
        for goal in goals:
            lines.append(
                f"{goal.get('name')}\n{format_inr(goal.get('current_amount'))} / {format_inr(goal.get('target_amount'))}"
            )
        return "\n\n".join(lines)
    if kind == INTENT_HEALTH:
        health = overlay.get("health") or {}
        if health.get("insufficient") or health.get("score") is None:
            return "Financial health\nINSUFFICIENT DATA"
        reasons = "\n".join(f"- {r}" for r in (health.get("reasons") or [])[:3])
        return f"Financial health\n{health.get('score')} {health.get('band') or ''}\n{reasons}".strip()
    if kind == INTENT_BILLS:
        upcoming = (overlay.get("calendar") or {}).get("upcoming") or []
        if not upcoming:
            return "No upcoming bills in the next few weeks."
        lines = ["Upcoming bills"]
        for event in upcoming[:6]:
            day = as_date(event.get("date"))
            label = event.get("label") or event.get("description") or event.get("name") or "Item"
            lines.append(f"{day.strftime('%d %b') if day else '—'} · {label} · {format_inr(event.get('amount'))}")
        return "\n".join(lines)
    if kind == INTENT_SPENDING:
        return await _spending_reply(user_id, category=intent.get("category"))
    if kind == INTENT_SUMMARY:
        bundle = await build_planning_bundle(str(user_id), persist=False)
        return (
            "This month\n"
            f"Income {format_inr(bundle.get('month_income'))}\n"
            f"Expenses {format_inr(bundle.get('month_expense'))}\n"
            f"Savings rate {bundle.get('savings_rate') if bundle.get('savings_rate') is not None else '—'}"
        )
    if kind == INTENT_BALANCE:
        from app.services.chat_assistant import format_balances

        return await format_balances(str(user_id))
    return "I can help with balance, spending, forecast, safe-to-spend, net worth, credit cards, goals, bills, and financial health."


async def _spending_reply(user_id: ObjectId, *, category: str | None) -> str:
    start = start_of_month_utc()
    prev_start = datetime(start.year if start.month > 1 else start.year - 1, start.month - 1 if start.month > 1 else 12, 1, tzinfo=timezone.utc)
    filt: dict = {
        "user_id": user_id,
        "deleted_at": None,
        "is_failed": {"$ne": True},
        "type": "debit",
        "created_at": {"$gte": start},
    }
    if category:
        needles = {
            "food": "food|dining|restaurant|swiggy|zomato|grocery|groceries",
            "shopping": "shop|amazon|flipkart|myntra",
            "travel": "travel|uber|ola|fuel|petrol",
            "subscriptions": "subscription|netflix|spotify",
            "bills": "rent|electric|wifi|utility",
        }
        rx = needles.get(category, category)
        filt["$or"] = [
            {"category.name": {"$regex": rx, "$options": "i"}},
            {"subcategory.name": {"$regex": rx, "$options": "i"}},
            {"description": {"$regex": rx, "$options": "i"}},
        ]
    merchants: dict[str, float] = {}
    total = 0.0
    cursor = db.transactions.find(filt).limit(1500)
    async for tx in cursor:
        amount = round_money(tx.get("amount"))
        total += amount
        label = str((tx.get("subcategory") or {}).get("name") or tx.get("description") or "Other")
        merchants[label] = round_money(merchants.get(label, 0) + amount)
    prev_filt = {**filt, "created_at": {"$gte": prev_start, "$lt": start}}
    prev_total = 0.0
    async for tx in db.transactions.find(prev_filt).limit(1500):
        prev_total += round_money(tx.get("amount"))
    title = f"{category.title()} spending" if category else "Spending"
    lines = [title, format_inr(total), ""]
    for name, amount in sorted(merchants.items(), key=lambda kv: kv[1], reverse=True)[:4]:
        lines.append(f"{name}\n{format_inr(amount)}")
        lines.append("")
    change = percent_change(total, prev_total if prev_total else None)
    if change is not None:
        direction = "higher" if change > 0 else "lower"
        prev_label = prev_start.strftime("%B")
        lines.append(f"{abs(change):.0f}% {direction} than {prev_label}.")
    elif total == 0:
        lines.append("No matching expenses recorded this month.")
    return "\n".join(lines).strip()


async def log_bot_query(*, user_id: ObjectId, intent: str, chat_id: str) -> None:
    await audit_log(
        action="TELEGRAM_FINANCE_QUERY",
        user={"user_id": str(user_id)},
        meta={"intent": intent, "chat_id": str(chat_id)[:24]},
    )
