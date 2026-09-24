"""Authorized, user-scoped tools for optional AI. Never runs raw queries from the model."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from bson import ObjectId

from app.db.mongo import db
from app.helpers.ai_privacy import ALLOWED_TOOL_NAMES, authorize_tool_call, clip_tool_result, hallucination_guard_text
from app.helpers.dashboard_time import start_of_month_utc
from app.helpers.money import format_inr, round_money
from app.helpers.planning_math import as_date
from app.services.planning import build_planning_bundle

OPENAI_TOOLS = [
    {"type": "function", "function": {"name": "get_balance", "description": "Cash-like and account balances for the signed-in user", "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "get_transactions", "description": "Recent ledger transactions for the signed-in user", "parameters": {"type": "object", "properties": {"limit": {"type": "integer"}, "category": {"type": "string"}, "days": {"type": "integer"}}}}},
    {"type": "function", "function": {"name": "get_spending_by_category", "description": "Debit totals grouped by category for a month window", "parameters": {"type": "object", "properties": {"months": {"type": "integer"}, "category": {"type": "string"}}}}},
    {"type": "function", "function": {"name": "get_cash_flow", "description": "This month vs previous month income and expense", "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "get_forecast", "description": "30/60/90 day scheduled cash forecast", "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "get_safe_to_spend", "description": "Safe-to-spend from cash minus reserved obligations", "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "get_net_worth", "description": "Assets minus card outstanding", "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "get_credit_cards", "description": "Credit-card outstanding, utilization, upcoming dues", "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "get_upcoming_bills", "description": "Upcoming calendar bills, recurring, and dues", "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "get_goals", "description": "Active financial goals", "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "get_financial_health", "description": "Health score and reasons when data exists", "parameters": {"type": "object", "properties": {}}}},
]


def tool_names() -> set[str]:
    return set(ALLOWED_TOOL_NAMES)


async def execute_tool(*, user_id: str, name: str, arguments: dict | None = None) -> str:
    denied = authorize_tool_call(user_id=user_id, name=name)
    if denied:
        return json.dumps(denied)
    args = arguments or {}
    handlers = {
        "get_balance": lambda: get_balance(user_id),
        "get_transactions": lambda: get_transactions(user_id, limit=args.get("limit"), category=args.get("category"), days=args.get("days")),
        "get_spending_by_category": lambda: get_spending_by_category(user_id, months=args.get("months"), category=args.get("category")),
        "get_cash_flow": lambda: get_cash_flow(user_id),
        "get_forecast": lambda: get_forecast(user_id),
        "get_safe_to_spend": lambda: get_safe_to_spend(user_id),
        "get_net_worth": lambda: get_net_worth(user_id),
        "get_credit_cards": lambda: get_credit_cards(user_id),
        "get_upcoming_bills": lambda: get_upcoming_bills(user_id),
        "get_goals": lambda: get_goals(user_id),
        "get_financial_health": lambda: get_financial_health(user_id),
    }
    payload = await handlers[name]()
    return json.dumps(clip_tool_result(payload), default=str)


def _uid(user_id: str) -> ObjectId:
    return ObjectId(str(user_id))


async def _bundle(user_id: str) -> dict:
    return await build_planning_bundle(user_id, persist=False)


async def get_balance(user_id: str) -> dict:
    bundle = await _bundle(user_id)
    accounts = []
    for acc in bundle.get("accounts") or []:
        accounts.append(
            {
                "name": acc.get("name"),
                "type": acc.get("type"),
                "balance": round_money(acc.get("balance")),
                "balance_label": format_inr(acc.get("balance")),
            }
        )
    return {
        "available_cash": bundle.get("cash"),
        "available_cash_label": format_inr(bundle.get("cash")),
        "accounts": accounts,
        "note": "Credit-card available limit is not cash.",
    }


async def get_transactions(user_id: str, *, limit: int | None = None, category: str | None = None, days: int | None = None) -> dict:
    cap = max(1, min(int(limit or 10), 25))
    uid = _uid(user_id)
    filt: dict[str, Any] = {"user_id": uid, "deleted_at": None, "is_failed": {"$ne": True}}
    if days:
        start = datetime.now(timezone.utc) - timedelta(days=max(1, min(int(days), 120)))
        filt["created_at"] = {"$gte": start}
    if category:
        filt["$or"] = [
            {"category.name": {"$regex": str(category), "$options": "i"}},
            {"description": {"$regex": str(category), "$options": "i"}},
        ]
    items = []
    cursor = db.transactions.find(filt).sort("created_at", -1).limit(cap)
    async for tx in cursor:
        items.append(
            {
                "id": str(tx["_id"]),
                "amount": round_money(tx.get("amount")),
                "amount_label": format_inr(tx.get("amount")),
                "type": tx.get("type"),
                "description": tx.get("description"),
                "category": (tx.get("category") or {}).get("name"),
                "date": (tx.get("transaction_date") or tx.get("created_at")),
            }
        )
    return {"items": items, "count": len(items)}


async def get_spending_by_category(user_id: str, *, months: int | None = None, category: str | None = None) -> dict:
    uid = _uid(user_id)
    window = max(1, min(int(months or 1), 6))
    start = start_of_month_utc()
    if window > 1:
        start = start - timedelta(days=32 * (window - 1))
    filt: dict[str, Any] = {
        "user_id": uid,
        "deleted_at": None,
        "is_failed": {"$ne": True},
        "type": "debit",
        "created_at": {"$gte": start},
    }
    if category:
        filt["$or"] = [
            {"category.name": {"$regex": str(category), "$options": "i"}},
            {"subcategory.name": {"$regex": str(category), "$options": "i"}},
            {"description": {"$regex": str(category), "$options": "i"}},
        ]
    totals: dict[str, float] = {}
    merchants: dict[str, float] = {}
    cursor = db.transactions.find(filt).limit(2000)
    async for tx in cursor:
        name = str((tx.get("category") or {}).get("name") or "Uncategorized")
        totals[name] = round_money(totals.get(name, 0) + round_money(tx.get("amount")))
        merch = str(tx.get("description") or "Other")
        merchants[merch] = round_money(merchants.get(merch, 0) + round_money(tx.get("amount")))
    top_merchants = sorted(merchants.items(), key=lambda kv: kv[1], reverse=True)[:8]
    return {
        "months": window,
        "categories": [{"name": k, "amount": v, "amount_label": format_inr(v)} for k, v in sorted(totals.items(), key=lambda kv: kv[1], reverse=True)],
        "merchants": [{"name": k, "amount": v, "amount_label": format_inr(v)} for k, v in top_merchants],
        "total": round_money(sum(totals.values())),
    }


async def get_cash_flow(user_id: str) -> dict:
    bundle = await _bundle(user_id)
    return {
        "month_income": bundle.get("month_income"),
        "month_expense": bundle.get("month_expense"),
        "prev_month_income": bundle.get("prev_month_income"),
        "prev_month_expense": bundle.get("prev_month_expense"),
        "savings_rate": bundle.get("savings_rate"),
    }


async def get_forecast(user_id: str) -> dict:
    bundle = await _bundle(user_id)
    forecast = bundle.get("forecast") or {}
    return {
        "today_balance": forecast.get("today_balance"),
        "horizons": forecast.get("horizons"),
        "lowest_balance": forecast.get("lowest_balance"),
        "lowest_date": forecast.get("lowest_date"),
        "contributing": [
            {
                "date": str(as_date(e.get("date")) or ""),
                "amount": e.get("amount"),
                "label": e.get("label") or e.get("description") or e.get("name"),
                "certainty": e.get("certainty"),
            }
            for e in (forecast.get("contributing_events") or [])[:10]
        ],
        "note": "Scheduled path only. Historical estimates are excluded.",
    }


async def get_safe_to_spend(user_id: str) -> dict:
    bundle = await _bundle(user_id)
    safe = bundle.get("safe_to_spend") or {}
    return {
        "safe_to_spend": safe.get("safe_to_spend"),
        "available_cash": safe.get("available_cash"),
        "reserved": safe.get("reserved"),
        "until": str(safe.get("until") or ""),
        "shortfall": safe.get("shortfall"),
        "note": "Credit-card limit is not included.",
    }


async def get_net_worth(user_id: str) -> dict:
    bundle = await _bundle(user_id)
    worth = bundle.get("net_worth") or {}
    return {
        "net_worth": worth.get("net_worth"),
        "assets": worth.get("assets"),
        "liabilities": worth.get("liabilities"),
        "monthly_change": worth.get("monthly_change"),
    }


async def get_credit_cards(user_id: str) -> dict:
    bundle = await _bundle(user_id)
    cards = bundle.get("credit_cards") or {}
    return {
        "outstanding": cards.get("total_outstanding"),
        "utilization": cards.get("overall_utilization"),
        "upcoming_due": cards.get("upcoming_due"),
        "monthly_emi": cards.get("monthly_emi"),
        "card_count": cards.get("card_count"),
        "cards": [
            {
                "name": c.get("name") or c.get("card_name"),
                "outstanding": c.get("outstanding"),
                "utilization": c.get("utilization"),
                "due_date": str(c.get("due_date") or ""),
            }
            for c in (cards.get("cards") or [])[:8]
        ],
    }


async def get_upcoming_bills(user_id: str) -> dict:
    bundle = await _bundle(user_id)
    upcoming = (bundle.get("calendar") or {}).get("upcoming") or []
    return {
        "items": [
            {
                "date": str(as_date(e.get("date")) or ""),
                "label": e.get("label") or e.get("description") or e.get("name"),
                "amount": e.get("amount"),
                "kind": e.get("kind") or e.get("type"),
            }
            for e in upcoming[:12]
        ]
    }


async def get_goals(user_id: str) -> dict:
    bundle = await _bundle(user_id)
    return {
        "items": [
            {
                "name": g.get("name"),
                "progress_pct": g.get("progress_pct"),
                "current_amount": g.get("current_amount"),
                "target_amount": g.get("target_amount"),
                "on_track": g.get("on_track"),
            }
            for g in (bundle.get("goals") or [])
            if g.get("status") == "active"
        ]
    }


async def get_financial_health(user_id: str) -> dict:
    bundle = await _bundle(user_id)
    health = bundle.get("health") or {}
    return {
        "score": health.get("score"),
        "band": health.get("band"),
        "reasons": (health.get("reasons") or [])[:5],
        "insufficient": health.get("score") is None,
        "disclaimer": bundle.get("disclaimer"),
    }


def system_prompt() -> str:
    return (
        "You are FinTracker’s optional finance assistant. "
        + hallucination_guard_text()
        + " Currency is INR. Cite merchants or categories from tool results when practical. "
        "Keep the tone calm and compact. Do not use flashy AI branding."
    )
