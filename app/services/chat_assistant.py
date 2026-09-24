"""Web chat assistant — guided (rule-based) and optional AI modes."""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from typing import Any

from bson import ObjectId

from app.db.mongo import db
from app.services.categorization_engine import categorize_transaction
from app.services.transactions import create_transaction

SESSION_COLLECTION = "chatbot_sessions"
_AMOUNT_RE = re.compile(r"(?<!\w)(\d+(?:\.\d{1,2})?)(?!\w)")

ROOT_QUICK_AUTH = [
    {"id": "balances", "label": "Show my balances", "icon": "wallet"},
    {"id": "last5", "label": "Last 5 transactions", "icon": "list"},
    {"id": "summary", "label": "Monthly summary", "icon": "chart"},
    {"id": "add_tx", "label": "Add a transaction", "icon": "plus"},
    {"id": "faq_login", "label": "Help with login", "icon": "help"},
    {"id": "support", "label": "Talk to support", "icon": "headset"},
]

ROOT_QUICK_GUEST = [
    {"id": "faq_login", "label": "Help with login", "icon": "help"},
    {"id": "faq_password", "label": "Reset password", "icon": "key"},
    {"id": "support", "label": "Talk to support", "icon": "headset"},
]

FOLLOW_BALANCES = [
    {"id": "spending", "label": "Spending this month", "icon": "chart"},
    {"id": "upcoming", "label": "Upcoming bills", "icon": "calendar"},
    {"id": "cards", "label": "Credit cards", "icon": "card"},
]

FOLLOW_ACTIVITY = [
    {"id": "balances", "label": "Balances", "icon": "wallet"},
    {"id": "summary", "label": "Monthly summary", "icon": "chart"},
    {"id": "add_tx", "label": "Add a transaction", "icon": "plus"},
]

FOLLOW_SUMMARY = [
    {"id": "spending", "label": "Spending this month", "icon": "chart"},
    {"id": "last5", "label": "Last 5 transactions", "icon": "list"},
    {"id": "balances", "label": "Balances", "icon": "wallet"},
]

FAQ = {
    "faq_login": "Use Forgot password on the sign-in page, or Google if your admin enabled it.",
    "faq_password": "Local accounts reset from Forgot password or Profile → Security. Google accounts change the password with Google.",
    "faq_tx": "Edit a transaction from Transactions (within the allowed window), or approve imports in Inbox.",
    "faq_recurring": "Check Recurring for Due soon / Paused. Failed posts show on the board — retry after funding the account.",
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _money(value: float) -> str:
    from app.helpers.money import format_inr

    return format_inr(value)


def _fmt_time(value: datetime | None) -> str:
    if not value:
        return "-"
    dt = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return dt.astimezone().strftime("%d %b %I:%M %p")


def ai_available() -> bool:
    from app.helpers.ai_client import ai_transport_ok, openai_configured

    return openai_configured() and ai_transport_ok()


def welcome_text(*, authenticated: bool, display_name: str | None = None) -> str:
    if authenticated:
        return (
            "Hello! 👋\n"
            "I'm your FinTracker assistant. I can help you check "
            "balances, track spending, add transactions, "
            "get insights, and more."
        )
    return (
        "Hello! 👋\n"
        "I'm your FinTracker assistant. I can help with login, passwords, "
        "or connect you with the team."
    )


def root_quick_replies(*, authenticated: bool) -> list[dict[str, str]]:
    return list(ROOT_QUICK_AUTH if authenticated else ROOT_QUICK_GUEST)


def welcome_menu(*, authenticated: bool) -> dict[str, Any]:
    examples = [
        {"id": "spending", "label": "How much can I spend this month?"},
        {"id": "networth", "label": "What's my net worth?"},
    ]
    if not authenticated:
        return {
            "title": "Things I can help you with",
            "subtitle": "Pick an option or type below.",
            "groups": [
                {
                    "id": "help",
                    "title": "Help & Support",
                    "icon": "bulb",
                    "layout": "stack",
                    "actions": [
                        {"id": "faq_login", "label": "Login", "icon": "help", "prompt": "Help with login"},
                        {"id": "faq_password", "label": "Password", "icon": "key", "prompt": "Reset password"},
                        {"id": "support", "label": "Support", "icon": "headset", "prompt": "Talk to support"},
                    ],
                }
            ],
            "examples": [{"id": "faq_login", "label": "How do I reset my password?"}],
        }
    return {
        "title": "Things I can help you with",
        "subtitle": "Pick an option or type below.",
        "groups": [
            {
                "id": "finances",
                "title": "Your Finances",
                "icon": "coins",
                "layout": "pills",
                "actions": [
                    {"id": "balances", "label": "Balances", "icon": "book", "prompt": "Show my balances"},
                    {"id": "summary", "label": "Summary", "icon": "chart", "prompt": "Monthly summary"},
                    {"id": "spending", "label": "Spending", "icon": "pie", "prompt": "Spending insights"},
                ],
            },
            {
                "id": "transactions",
                "title": "Transactions",
                "icon": "plus",
                "layout": "pills",
                "actions": [
                    {"id": "add_tx", "label": "Add", "icon": "plus", "prompt": "Add a transaction"},
                    {"id": "last5", "label": "Last 5", "icon": "list", "prompt": "Last 5 transactions"},
                    {"id": "activity", "label": "Recent", "icon": "activity", "prompt": "View recent activity"},
                ],
            },
            {
                "id": "upcoming",
                "title": "Upcoming",
                "icon": "calendar",
                "layout": "stack",
                "actions": [
                    {"id": "upcoming", "label": "Bills", "icon": "bell", "prompt": "Upcoming bills"},
                    {"id": "faq_recurring", "label": "Recurring", "icon": "calendar", "prompt": "Recurring payments"},
                ],
            },
            {
                "id": "help",
                "title": "Help & Support",
                "icon": "bulb",
                "layout": "stack",
                "actions": [
                    {"id": "faq_login", "label": "Login", "icon": "help", "prompt": "Help with login"},
                    {"id": "support", "label": "Support", "icon": "headset", "prompt": "Talk to support"},
                ],
            },
        ],
        "examples": examples,
    }


async def _get_session(user_key: str) -> dict:
    doc = await db[SESSION_COLLECTION].find_one({"user_key": user_key})
    if doc:
        return doc
    return {
        "user_key": user_key,
        "mode": "guided",
        "step": None,
        "draft": {},
        "history": [],
        "updated_at": _now(),
    }


async def _save_session(session: dict) -> None:
    session["updated_at"] = _now()
    await db[SESSION_COLLECTION].update_one(
        {"user_key": session["user_key"]},
        {"$set": session},
        upsert=True,
    )


async def _log_bot(user_id: str | None, message: str) -> None:
    doc: dict[str, Any] = {
        "sender": "bot",
        "message": message,
        "channel": "chatbot",
        "timestamp": _now(),
        "resolved": True,
    }
    if user_id:
        doc["user_id"] = user_id
    await db.chat_logs.insert_one(doc)


async def _log_user(user_id: str | None, message: str) -> None:
    doc: dict[str, Any] = {
        "sender": "user",
        "message": message,
        "channel": "chatbot",
        "timestamp": _now(),
        "resolved": False,
    }
    if user_id:
        doc["user_id"] = user_id
    await db.chat_logs.insert_one(doc)


def _result(
    reply: str,
    *,
    quick_replies: list[dict[str, str]] | None = None,
    mode: str = "guided",
    escalate_support: bool = False,
    support_prefill: str | None = None,
    draft: dict | None = None,
    card: dict | None = None,
    suggestions: list[dict[str, str]] | None = None,
    menu: dict | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "reply": reply,
        "quick_replies": quick_replies or [],
        "mode": mode,
        "escalate_support": escalate_support,
        "support_prefill": support_prefill,
        "draft": draft or {},
        "ai_available": ai_available(),
    }
    if card:
        payload["card"] = card
    if suggestions is not None:
        payload["suggestions"] = suggestions
    if menu is not None:
        payload["menu"] = menu
    return payload


async def format_last_transactions(user_id: str, limit: int = 5) -> str:
    uid = ObjectId(user_id)
    txs = await db.transactions.find(
        {"user_id": uid, "deleted_at": None},
        {"type": 1, "amount": 1, "description": 1, "created_at": 1, "account_id": 1, "is_failed": 1},
    ).sort("created_at", -1).limit(limit).to_list(length=limit)
    if not txs:
        return "No transactions found yet. You can add one from the shortcuts."

    account_ids = [t.get("account_id") for t in txs if t.get("account_id")]
    account_map: dict[str, str] = {}
    if account_ids:
        accounts = await db.accounts.find({"_id": {"$in": account_ids}}, {"name": 1}).to_list(length=200)
        account_map = {str(a["_id"]): str(a.get("name") or "Account") for a in accounts}

    lines = [f"Last {len(txs)} transactions:"]
    for idx, tx in enumerate(txs, start=1):
        t = str(tx.get("type") or "").lower()
        label = {"credit": "Income", "debit": "Expense"}.get(t, "Transfer" if "transfer" in t else t or "Txn")
        failed = " (failed)" if tx.get("is_failed") else ""
        lines.append(
            f"{idx}) {label} {_money(tx.get('amount') or 0)} · "
            f"{account_map.get(str(tx.get('account_id') or ''), 'Account')} · "
            f"{(tx.get('description') or '-').strip() or '-'} · {_fmt_time(tx.get('created_at'))}{failed}"
        )
    return "\n".join(lines)


async def format_balances(user_id: str) -> str:
    uid = ObjectId(user_id)
    accounts = await db.accounts.find(
        {"user_id": uid, "deleted_at": None},
        {"name": 1, "balance": 1, "type": 1},
    ).sort("name", 1).to_list(length=200)
    if not accounts:
        return "No accounts yet. Create one under Accounts first."
    total = sum(float(a.get("balance") or 0) for a in accounts)
    lines = [f"Total balance: {_money(total)}", "", "Per account:"]
    for a in accounts:
        lines.append(f"• {a.get('name') or 'Account'}: {_money(a.get('balance') or 0)}")
    return "\n".join(lines)


async def format_month_summary(user_id: str) -> str:
    uid = ObjectId(user_id)
    now = _now()
    month_start = datetime(now.year, now.month, 1, tzinfo=timezone.utc)
    pipeline = [
        {
            "$match": {
                "user_id": uid,
                "deleted_at": None,
                "created_at": {"$gte": month_start},
                "is_failed": {"$ne": True},
            }
        },
        {"$group": {"_id": "$type", "total": {"$sum": {"$ifNull": ["$amount", 0]}}, "count": {"$sum": 1}}},
    ]
    rows = await db.transactions.aggregate(pipeline).to_list(length=10)
    by_type = {str(r.get("_id") or ""): r for r in rows}
    income = float((by_type.get("credit") or {}).get("total") or 0)
    expense = float((by_type.get("debit") or {}).get("total") or 0)
    transfer = float((by_type.get("transfer_out") or {}).get("total") or 0) + float(
        (by_type.get("transfer_in") or {}).get("total") or 0
    )
    count = sum(int(r.get("count") or 0) for r in rows)
    return (
        f"Summary for {month_start.strftime('%b %Y')}:\n"
        f"• Transactions: {count}\n"
        f"• Income: {_money(income)}\n"
        f"• Expense: {_money(expense)}\n"
        f"• Transfers: {_money(transfer)}\n"
        f"• Net: {_money(income - expense)}"
    )


def _account_icon(acc_type: str | None) -> str:
    kind = str(acc_type or "").lower()
    if kind == "credit_card":
        return "card"
    if kind in {"wallet", "cash"}:
        return "wallet"
    return "bank"


async def snapshot_balances(user_id: str) -> dict[str, Any]:
    uid = ObjectId(user_id)
    accounts = await db.accounts.find(
        {"user_id": uid, "deleted_at": None},
        {"name": 1, "balance": 1, "type": 1, "bank_name": 1},
    ).sort("name", 1).to_list(length=200)
    if not accounts:
        return {
            "reply": "You don’t have any accounts yet. Add one under Accounts and I’ll show a live snapshot here.",
            "card": None,
            "quick_replies": [{"id": "add_tx", "label": "Add a transaction", "icon": "plus"}],
        }
    cash_accounts = [a for a in accounts if str(a.get("type") or "") not in {"credit_card", "loan"}]
    rows_source = cash_accounts or accounts
    total = sum(float(a.get("balance") or 0) for a in rows_source)
    card = {
        "type": "balances",
        "title": "Total balance",
        "total": round(total, 2),
        "rows": [
            {
                "name": str(a.get("name") or a.get("bank_name") or "Account"),
                "amount": round(float(a.get("balance") or 0), 2),
                "icon": _account_icon(a.get("type")),
            }
            for a in rows_source[:6]
        ],
    }
    extra = len(rows_source) - len(card["rows"])
    if extra > 0:
        card["footnote"] = f"+{extra} more account{'s' if extra != 1 else ''}"
    return {
        "reply": "",
        "card": card,
        "quick_replies": FOLLOW_BALANCES,
    }


async def snapshot_transactions(user_id: str, limit: int = 5) -> dict[str, Any]:
    uid = ObjectId(user_id)
    txs = await db.transactions.find(
        {"user_id": uid, "deleted_at": None},
        {"type": 1, "amount": 1, "description": 1, "created_at": 1, "account_id": 1, "is_failed": 1},
    ).sort("created_at", -1).to_list(length=limit)
    if not txs:
        return {
            "reply": "No transactions yet. I can walk you through adding the first one.",
            "card": None,
            "quick_replies": [{"id": "add_tx", "label": "Add a transaction", "icon": "plus"}],
        }
    account_ids = [t.get("account_id") for t in txs if t.get("account_id")]
    account_map: dict[str, str] = {}
    if account_ids:
        accounts = await db.accounts.find({"_id": {"$in": account_ids}}, {"name": 1}).to_list(length=200)
        account_map = {str(a["_id"]): str(a.get("name") or "Account") for a in accounts}
    rows = []
    for tx in txs:
        t = str(tx.get("type") or "").lower()
        tone = "credit" if t == "credit" else ("debit" if t == "debit" else "transfer")
        label = (tx.get("description") or "").strip() or {
            "credit": "Income",
            "debit": "Expense",
        }.get(t, "Transfer")
        meta_bits = [account_map.get(str(tx.get("account_id") or ""), "Account"), _fmt_time(tx.get("created_at"))]
        if tx.get("is_failed"):
            meta_bits.append("Failed")
        amount = float(tx.get("amount") or 0)
        rows.append(
            {
                "label": label,
                "meta": " · ".join(meta_bits),
                "amount": round(-amount if tone == "debit" else amount, 2),
                "tone": tone,
            }
        )
    return {
        "reply": f"Here are your last {len(rows)} transactions.",
        "card": {"type": "list", "title": "Recent activity", "rows": rows},
        "quick_replies": FOLLOW_ACTIVITY,
    }


async def snapshot_month_summary(user_id: str) -> dict[str, Any]:
    uid = ObjectId(user_id)
    now = _now()
    month_start = datetime(now.year, now.month, 1, tzinfo=timezone.utc)
    pipeline = [
        {
            "$match": {
                "user_id": uid,
                "deleted_at": None,
                "created_at": {"$gte": month_start},
                "is_failed": {"$ne": True},
            }
        },
        {"$group": {"_id": "$type", "total": {"$sum": {"$ifNull": ["$amount", 0]}}, "count": {"$sum": 1}}},
    ]
    rows = await db.transactions.aggregate(pipeline).to_list(length=10)
    by_type = {str(r.get("_id") or ""): r for r in rows}
    income = float((by_type.get("credit") or {}).get("total") or 0)
    expense = float((by_type.get("debit") or {}).get("total") or 0)
    count = sum(int(r.get("count") or 0) for r in rows)
    net = income - expense
    label = month_start.strftime("%b %Y")
    return {
        "reply": f"Your {label} cashflow at a glance.",
        "card": {
            "type": "summary",
            "title": label,
            "items": [
                {"label": "Income", "value": round(income, 2), "tone": "credit"},
                {"label": "Expense", "value": round(expense, 2), "tone": "debit"},
                {"label": "Net", "value": round(net, 2), "tone": "credit" if net >= 0 else "debit"},
                {"label": "Transactions", "value_label": str(count), "tone": "neutral"},
            ],
        },
        "quick_replies": FOLLOW_SUMMARY,
    }


async def snapshot_spending(user_id: str) -> dict[str, Any]:
    uid = ObjectId(user_id)
    now = _now()
    month_start = datetime(now.year, now.month, 1, tzinfo=timezone.utc)
    pipeline = [
        {
            "$match": {
                "user_id": uid,
                "deleted_at": None,
                "created_at": {"$gte": month_start},
                "is_failed": {"$ne": True},
                "type": "debit",
            }
        },
        {
            "$group": {
                "_id": "$category.name",
                "total": {"$sum": {"$ifNull": ["$amount", 0]}},
            }
        },
        {"$sort": {"total": -1}},
        {"$limit": 5},
    ]
    cats = await db.transactions.aggregate(pipeline).to_list(length=5)
    total_doc = await db.transactions.aggregate(
        [
            {
                "$match": {
                    "user_id": uid,
                    "deleted_at": None,
                    "created_at": {"$gte": month_start},
                    "is_failed": {"$ne": True},
                    "type": "debit",
                }
            },
            {"$group": {"_id": None, "total": {"$sum": {"$ifNull": ["$amount", 0]}}}},
        ]
    ).to_list(length=1)
    total = float((total_doc[0].get("total") if total_doc else 0) or 0)
    if not cats and total <= 0:
        return {
            "reply": "No spending recorded this month yet.",
            "card": None,
            "quick_replies": FOLLOW_ACTIVITY,
        }
    rows = [
        {
            "label": str(c.get("_id") or "Uncategorized"),
            "amount": round(-float(c.get("total") or 0), 2),
            "tone": "debit",
        }
        for c in cats
    ]
    return {
        "reply": f"You’ve spent {_money(total)} this month.",
        "card": {
            "type": "list",
            "title": f"Spending · {month_start.strftime('%b %Y')}",
            "rows": rows,
        },
        "quick_replies": FOLLOW_SUMMARY,
    }


async def snapshot_upcoming(user_id: str) -> dict[str, Any]:
    from app.helpers.dashboard_upcoming import fetch_upcoming_bills

    uid = ObjectId(user_id)
    accounts = await db.accounts.find(
        {"user_id": uid, "deleted_at": None},
        {"name": 1},
    ).to_list(length=200)
    account_map = {str(a["_id"]): {"name": a.get("name") or "Account"} for a in accounts}
    upcoming_7, upcoming_month, _required = await fetch_upcoming_bills(uid, account_map)
    bills = upcoming_7 or upcoming_month
    if not bills:
        return {
            "reply": "Nothing due in the next few days. I’ll flag bills here when they approach.",
            "card": None,
            "quick_replies": FOLLOW_BALANCES,
        }
    rows = []
    for item in bills[:5]:
        due = item.get("due_at")
        due_label = due.strftime("%d %b") if due else "Soon"
        rows.append(
            {
                "label": str(item.get("description") or "Bill"),
                "meta": f"{item.get('account_name') or 'Account'} · {due_label}",
                "amount": round(-float(item.get("amount") or 0), 2) if item.get("type") == "debit" else round(float(item.get("amount") or 0), 2),
                "tone": "debit" if item.get("type") == "debit" else "credit",
            }
        )
    window = "next 7 days" if upcoming_7 else "this month"
    return {
        "reply": f"{len(bills)} bill{'s' if len(bills) != 1 else ''} coming up {window}.",
        "card": {"type": "list", "title": "Upcoming bills", "rows": rows},
        "quick_replies": FOLLOW_BALANCES,
    }


async def snapshot_cards(user_id: str) -> dict[str, Any]:
    uid = ObjectId(user_id)
    cards = await db.accounts.find(
        {"user_id": uid, "deleted_at": None, "type": "credit_card"},
        {"name": 1, "balance": 1, "statement_balance": 1, "payment_due_date": 1, "credit_limit": 1},
    ).sort("name", 1).to_list(length=20)
    if not cards:
        return {
            "reply": "No credit cards on file. Add one under Accounts to track dues here.",
            "card": None,
            "quick_replies": FOLLOW_ACTIVITY,
        }
    rows = []
    for card in cards:
        due = card.get("payment_due_date")
        due_label = due.strftime("%d %b") if due else "No due date"
        outstanding = abs(float(card.get("balance") or 0))
        rows.append(
            {
                "label": str(card.get("name") or "Credit card"),
                "meta": f"Due {due_label}",
                "amount": round(-outstanding, 2),
                "tone": "debit",
            }
        )
    return {
        "reply": f"{len(cards)} card{'s' if len(cards) != 1 else ''} on file.",
        "card": {"type": "list", "title": "Credit cards", "rows": rows},
        "quick_replies": FOLLOW_BALANCES,
    }


def _from_snapshot(snapshot: dict[str, Any], *, mode: str) -> dict:
    return _result(
        snapshot.get("reply") or "",
        quick_replies=snapshot.get("quick_replies") or [],
        mode=mode,
        card=snapshot.get("card"),
    )


async def _list_accounts(user_id: str) -> list[dict]:
    uid = ObjectId(user_id)
    return await db.accounts.find(
        {"user_id": uid, "deleted_at": None},
        {"name": 1, "balance": 1, "type": 1},
    ).sort("name", 1).to_list(length=50)


def _extract_amount(text: str) -> float | None:
    match = _AMOUNT_RE.search(text or "")
    if not match:
        return None
    try:
        value = float(match.group(1))
    except ValueError:
        return None
    return value if value > 0 else None


def _infer_type(text: str) -> str:
    lower = (text or "").lower()
    if any(w in lower for w in ("income", "salary", "received", "credit")):
        return "credit"
    if any(w in lower for w in ("transfer", "moved", "sent to")):
        return "transfer"
    return "debit"


async def _match_account(user_id: str, text: str) -> dict | None:
    accounts = await _list_accounts(user_id)
    if not accounts:
        return None
    needle = (text or "").strip().lower()
    if not needle:
        return None
    for acc in accounts:
        name = str(acc.get("name") or "").lower()
        if name and (name == needle or name in needle or needle in name):
            return acc
    # numeric pick: "1", "2"
    if needle.isdigit():
        idx = int(needle) - 1
        if 0 <= idx < len(accounts):
            return accounts[idx]
    return None


async def _account_quick_replies(user_id: str) -> list[dict[str, str]]:
    accounts = await _list_accounts(user_id)
    replies = [
        {"id": f"acct:{a['_id']}", "label": f"{a.get('name') or 'Account'} ({_money(a.get('balance') or 0)})"}
        for a in accounts[:6]
    ]
    replies.append({"id": "cancel", "label": "Cancel"})
    return replies


async def _begin_add_flow(user_id: str, session: dict, seed: dict | None = None) -> dict:
    draft = dict(seed or {})
    session["step"] = "tx_type"
    session["draft"] = draft
    if draft.get("tx_type") and draft.get("amount"):
        return await _advance_add_flow(user_id, session, "")
    await _save_session(session)
    return _result(
        "Let’s add a transaction. What type is it?",
        quick_replies=[
            {"id": "type:debit", "label": "Expense"},
            {"id": "type:credit", "label": "Income"},
            {"id": "type:transfer", "label": "Transfer"},
            {"id": "cancel", "label": "Cancel"},
        ],
        mode=session.get("mode") or "guided",
        draft=draft,
    )


async def _advance_add_flow(user_id: str, session: dict, text: str) -> dict:
    draft = dict(session.get("draft") or {})
    step = session.get("step")
    raw = (text or "").strip()
    mode = session.get("mode") or "guided"

    if raw.lower() in {"cancel", "stop", "nevermind"} or raw == "cancel":
        session["step"] = None
        session["draft"] = {}
        await _save_session(session)
        return _result(
            "Cancelled. What else can I help with?",
            quick_replies=FOLLOW_ACTIVITY,
            mode=mode,
        )

    if step == "tx_type" or (not draft.get("tx_type") and raw.startswith("type:")):
        if raw.startswith("type:"):
            draft["tx_type"] = raw.split(":", 1)[1]
        elif raw.lower() in {"expense", "debit"}:
            draft["tx_type"] = "debit"
        elif raw.lower() in {"income", "credit"}:
            draft["tx_type"] = "credit"
        elif raw.lower() == "transfer":
            draft["tx_type"] = "transfer"
        else:
            await _save_session(session)
            return _result(
                "Please choose Expense, Income, or Transfer.",
                quick_replies=[
                    {"id": "type:debit", "label": "Expense"},
                    {"id": "type:credit", "label": "Income"},
                    {"id": "type:transfer", "label": "Transfer"},
                    {"id": "cancel", "label": "Cancel"},
                ],
                mode=mode,
                draft=draft,
            )
        session["draft"] = draft
        session["step"] = "tx_amount"
        if draft.get("amount"):
            return await _advance_add_flow(user_id, session, "")
        await _save_session(session)
        return _result(
            "What amount?",
            quick_replies=[{"id": "cancel", "label": "Cancel"}],
            mode=mode,
            draft=draft,
        )

    if step == "tx_amount" or (draft.get("tx_type") and not draft.get("amount")):
        amount = _extract_amount(raw) if raw else draft.get("amount")
        if not amount:
            await _save_session(session)
            return _result(
                "I need a positive amount — for example 250 or 1,499.50.",
                quick_replies=[{"id": "cancel", "label": "Cancel"}],
                mode=mode,
                draft=draft,
            )
        draft["amount"] = float(amount)
        session["draft"] = draft
        session["step"] = "tx_account"
        if draft.get("account_id"):
            return await _advance_add_flow(user_id, session, "")
        await _save_session(session)
        return _result(
            "Which account should I use?",
            quick_replies=await _account_quick_replies(user_id),
            mode=mode,
            draft=draft,
        )

    if step == "tx_account" or (draft.get("amount") and not draft.get("account_id")):
        account = None
        if raw.startswith("acct:"):
            oid = raw.split(":", 1)[1]
            account = await db.accounts.find_one(
                {"_id": ObjectId(oid), "user_id": ObjectId(user_id), "deleted_at": None}
            )
        else:
            account = await _match_account(user_id, raw)
        if not account:
            await _save_session(session)
            return _result(
                "I couldn’t match that account. Pick one below or type the account name.",
                quick_replies=await _account_quick_replies(user_id),
                mode=mode,
                draft=draft,
            )
        draft["account_id"] = str(account["_id"])
        draft["account_name"] = str(account.get("name") or "Account")
        session["draft"] = draft
        if draft.get("tx_type") == "transfer" and not draft.get("target_account_id"):
            session["step"] = "tx_target"
            await _save_session(session)
            return _result(
                "Transfer to which account?",
                quick_replies=await _account_quick_replies(user_id),
                mode=mode,
                draft=draft,
            )
        session["step"] = "tx_description"
        if draft.get("description"):
            return await _advance_add_flow(user_id, session, "")
        await _save_session(session)
        return _result(
            "Add a short description (merchant / note).",
            quick_replies=[{"id": "cancel", "label": "Cancel"}],
            mode=mode,
            draft=draft,
        )

    if step == "tx_target":
        account = None
        if raw.startswith("acct:"):
            oid = raw.split(":", 1)[1]
            account = await db.accounts.find_one(
                {"_id": ObjectId(oid), "user_id": ObjectId(user_id), "deleted_at": None}
            )
        else:
            account = await _match_account(user_id, raw)
        if not account or str(account["_id"]) == draft.get("account_id"):
            await _save_session(session)
            return _result(
                "Pick a different destination account.",
                quick_replies=await _account_quick_replies(user_id),
                mode=mode,
                draft=draft,
            )
        draft["target_account_id"] = str(account["_id"])
        draft["target_account_name"] = str(account.get("name") or "Account")
        session["draft"] = draft
        session["step"] = "tx_description"
        await _save_session(session)
        return _result(
            "Add a short description for this transfer.",
            quick_replies=[{"id": "cancel", "label": "Cancel"}],
            mode=mode,
            draft=draft,
        )

    if step == "tx_description" or (draft.get("account_id") and not draft.get("description")):
        if not raw and not draft.get("description"):
            await _save_session(session)
            return _result(
                "Please enter a description.",
                quick_replies=[{"id": "cancel", "label": "Cancel"}],
                mode=mode,
                draft=draft,
            )
        if raw:
            draft["description"] = raw
        session["draft"] = draft
        session["step"] = "tx_confirm"

        tx_type = draft.get("tx_type") or "debit"
        preview = await categorize_transaction(
            user_id=ObjectId(user_id),
            raw_description=str(draft.get("description") or ""),
            amount=float(draft.get("amount") or 0),
            tx_type=tx_type if tx_type != "transfer" else "debit",
            mode="upi",
        )
        if tx_type == "transfer":
            draft["category_code"] = "transfer"
            draft["subcategory_code"] = "transfer"
            draft["category_name"] = "Self Transfer"
            draft["subcategory_name"] = "Transfer"
        else:
            draft["category_code"] = str(preview.get("suggested_category_code") or "")
            draft["subcategory_code"] = str(preview.get("suggested_subcategory_code") or "")
            draft["category_name"] = str(preview.get("suggested_category") or "Uncategorized")
            draft["subcategory_name"] = str(preview.get("suggested_subcategory") or "-")

        if not draft.get("category_code") or not draft.get("subcategory_code"):
            session["step"] = None
            session["draft"] = {}
            await _save_session(session)
            return _result(
                "I couldn’t categorize that yet. Open Add Transaction to finish it manually, "
                f"or try a clearer description.\n\nDraft: {draft.get('tx_type')} {_money(draft.get('amount') or 0)} "
                f"on {draft.get('account_name')} — {draft.get('description')}",
                quick_replies=root_quick_replies(authenticated=True)
                + [{"id": "add_tx", "label": "Try again"}],
                mode=mode,
            )

        session["draft"] = draft
        await _save_session(session)
        target_bit = ""
        if draft.get("target_account_name"):
            target_bit = f" → {draft['target_account_name']}"
        summary = (
            f"Confirm this {draft.get('tx_type')}?\n"
            f"• Amount: {_money(draft.get('amount') or 0)}\n"
            f"• Account: {draft.get('account_name')}{target_bit}\n"
            f"• Category: {draft.get('category_name')} / {draft.get('subcategory_name')}\n"
            f"• Note: {draft.get('description')}"
        )
        return _result(
            summary,
            quick_replies=[
                {"id": "confirm_tx", "label": "Confirm & save"},
                {"id": "cancel", "label": "Cancel"},
            ],
            mode=mode,
            draft=draft,
        )

    if step == "tx_confirm":
        if raw.lower() not in {"confirm_tx", "confirm", "yes", "save"}:
            await _save_session(session)
            return _result(
                "Tap Confirm & save, or Cancel.",
                quick_replies=[
                    {"id": "confirm_tx", "label": "Confirm & save"},
                    {"id": "cancel", "label": "Cancel"},
                ],
                mode=mode,
                draft=draft,
            )
        try:
            await create_transaction(
                user_id=user_id,
                account_id=str(draft["account_id"]),
                amount=float(draft["amount"]),
                tx_type=str(draft.get("tx_type") or "debit"),
                mode="upi",
                category_code=str(draft["category_code"]),
                subcategory_code=str(draft["subcategory_code"]),
                description=str(draft.get("description") or ""),
                target_account_id=draft.get("target_account_id"),
            )
        except Exception as exc:  # noqa: BLE001
            session["step"] = None
            session["draft"] = {}
            await _save_session(session)
            return _result(
                f"Couldn’t save that transaction: {exc}. Try Add Transaction in the app.",
                quick_replies=root_quick_replies(authenticated=True),
                mode=mode,
            )
        session["step"] = None
        session["draft"] = {}
        await _save_session(session)
        return _result(
            f"Saved — {_money(draft.get('amount') or 0)} posted to {draft.get('account_name')}.",
            quick_replies=FOLLOW_ACTIVITY,
            mode=mode,
        )

    session["step"] = None
    session["draft"] = {}
    await _save_session(session)
    return _result(
        "I lost track of that draft. Let’s start again.",
        quick_replies=root_quick_replies(authenticated=True),
        mode=mode,
    )


async def _handle_guided(
    *,
    user_id: str | None,
    authenticated: bool,
    text: str,
    quick_id: str | None,
    session: dict,
) -> dict:
    mode = session.get("mode") or "guided"
    payload = (quick_id or text or "").strip()
    lower = payload.lower()

    # Mid-flow add transaction
    if authenticated and session.get("step"):
        return await _advance_add_flow(user_id, session, payload)

    if payload in FAQ or lower in FAQ:
        key = payload if payload in FAQ else lower
        return _result(
            FAQ[key],
            quick_replies=[
                {"id": "support", "label": "Talk to support", "icon": "headset"},
                {"id": "faq_password", "label": "Reset password", "icon": "key"},
            ]
            if not authenticated
            else [
                {"id": "support", "label": "Talk to support", "icon": "headset"},
                {"id": "balances", "label": "Show my balances", "icon": "wallet"},
            ],
            mode=mode,
        )

    if lower in {"menu", "help", "hi", "hello", "hey"} or payload == "menu":
        return _result(
            "",
            quick_replies=[],
            mode=mode,
            menu=welcome_menu(authenticated=authenticated),
        )

    if lower in {"support", "talk to support", "human", "agent"} or payload == "support":
        return _result(
            "I’ll open a live support thread with an admin. Describe your issue after this.",
            quick_replies=[],
            mode=mode,
            escalate_support=True,
            support_prefill=text if text and text.lower() not in {"support", "talk to support"} else None,
        )

    if not authenticated:
        return _result(
            "Sign in to load balances and transactions. Meanwhile I can help with login/password or connect support.",
            quick_replies=root_quick_replies(authenticated=False),
            mode=mode,
        )

    assert user_id
    if payload in {"last5", "last 5", "activity"} or "last 5" in lower or lower in {"recent", "transactions", "activity"}:
        return _from_snapshot(await snapshot_transactions(user_id), mode=mode)
    if payload in {"balances", "balance"} or "balance" in lower:
        return _from_snapshot(await snapshot_balances(user_id), mode=mode)
    if payload in {"summary", "month summary", "monthly summary"} or "summary" in lower:
        return _from_snapshot(await snapshot_month_summary(user_id), mode=mode)
    if payload in {"spending", "spend"} or "spending" in lower or re.search(r"\bspend\b", lower):
        return _from_snapshot(await snapshot_spending(user_id), mode=mode)
    if payload in {"upcoming", "bills"} or "upcoming" in lower or "bills" in lower:
        return _from_snapshot(await snapshot_upcoming(user_id), mode=mode)
    if payload in {"cards", "credit cards"} or "credit card" in lower:
        return _from_snapshot(await snapshot_cards(user_id), mode=mode)
    if payload in {"networth", "net worth"} or "net worth" in lower:
        return _from_snapshot(await snapshot_balances(user_id), mode=mode)
    if payload in {"add_tx", "add"} or "add transaction" in lower or lower.startswith("spent") or lower.startswith("paid"):
        seed: dict[str, Any] = {}
        amount = _extract_amount(payload)
        if amount:
            seed["amount"] = amount
            seed["tx_type"] = _infer_type(payload)
            seed["description"] = re.sub(_AMOUNT_RE, "", payload).strip(" -–|,.") or None
            account = await _match_account(user_id, payload)
            if account:
                seed["account_id"] = str(account["_id"])
                seed["account_name"] = str(account.get("name") or "Account")
        return await _begin_add_flow(user_id, session, seed)

    if lower in {"ai", "ai mode", "enable ai"}:
        if not ai_available():
            return _result(
                "AI mode isn’t configured (missing OPENAI_API_KEY). Guided mode still works.",
                quick_replies=root_quick_replies(authenticated=True),
                mode="guided",
            )
        session["mode"] = "ai"
        await _save_session(session)
        return _result(
            "AI mode on — describe what you need in plain language. I’ll turn it into balances, "
            "summaries, or a transaction draft. Say “guided” anytime to switch back.",
            quick_replies=root_quick_replies(authenticated=True) + [{"id": "guided", "label": "Guided mode"}],
            mode="ai",
        )

    if lower in {"guided", "guided mode", "basic"}:
        session["mode"] = "guided"
        await _save_session(session)
        return _result(
            "Back to guided mode. Use the shortcuts or short commands.",
            quick_replies=root_quick_replies(authenticated=True),
            mode="guided",
        )

    # Free text fallback — try amount quick detect
    amount = _extract_amount(payload)
    if amount:
        seed = {
            "amount": amount,
            "tx_type": _infer_type(payload),
            "description": re.sub(_AMOUNT_RE, "", payload).strip(" -–|,.") or None,
        }
        account = await _match_account(user_id, payload)
        if account:
            seed["account_id"] = str(account["_id"])
            seed["account_name"] = str(account.get("name") or "Account")
        return await _begin_add_flow(user_id, session, seed)

    return _result(
        "Try a shortcut, or just tell me what you need.",
        quick_replies=FOLLOW_ACTIVITY,
        mode=mode,
    )


async def _run_tool(user_id: str, name: str, args: dict) -> str:
    if name == "get_balances":
        return await format_balances(user_id)
    if name == "get_recent_transactions":
        limit = int(args.get("limit") or 5)
        return await format_last_transactions(user_id, limit=max(1, min(limit, 10)))
    if name == "get_month_summary":
        return await format_month_summary(user_id)
    if name == "list_accounts":
        accounts = await _list_accounts(user_id)
        if not accounts:
            return "No accounts."
        return "\n".join(
            f"{i+1}. {a.get('name')} id={a['_id']} balance={_money(a.get('balance') or 0)}"
            for i, a in enumerate(accounts)
        )
    if name == "start_transaction_draft":
        # Handled by caller via escalate to guided flow — return structured hint
        return json.dumps(
            {
                "ok": True,
                "hint": "Switch user into guided add flow with these fields",
                "fields": args,
            }
        )
    if name == "escalate_support":
        return json.dumps({"ok": True, "escalate": True, "summary": args.get("summary") or ""})
    from app.services import ai_tools as finance_tools

    if name in finance_tools.tool_names():
        return await finance_tools.execute_tool(user_id=user_id, name=name, arguments=args)
    return f"Unknown tool: {name}"


async def _handle_ai(*, user_id: str, text: str, session: dict) -> dict:
    if not ai_available():
        session["mode"] = "guided"
        await _save_session(session)
        return await _handle_guided(
            user_id=user_id,
            authenticated=True,
            text=text,
            quick_id=None,
            session=session,
        )

    # Quick exits / mode switches stay rule-based
    lower = (text or "").strip().lower()
    if lower in {"guided", "guided mode", "menu"}:
        session["mode"] = "guided"
        await _save_session(session)
        return _result(
            "Switched to guided mode.",
            quick_replies=root_quick_replies(authenticated=True),
            mode="guided",
        )
    if lower in {"support", "talk to support"}:
        return _result(
            "Connecting you with human support.",
            escalate_support=True,
            mode="ai",
        )
    if session.get("step"):
        return await _advance_add_flow(user_id, session, text)

    try:
        from app.helpers.ai_client import openai_client

        client = openai_client()
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "get_balances",
                    "description": "Get the user's account balances",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "get_recent_transactions",
                    "description": "List recent transactions",
                    "parameters": {
                        "type": "object",
                        "properties": {"limit": {"type": "integer"}},
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "get_month_summary",
                    "description": "Income/expense summary for the current month",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "list_accounts",
                    "description": "List account names and ids for drafting transactions",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "start_transaction_draft",
                    "description": "Begin adding a transaction; include any known fields and leave missing ones empty so the app can prompt",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "tx_type": {"type": "string", "enum": ["debit", "credit", "transfer"]},
                            "amount": {"type": "number"},
                            "account_id": {"type": "string"},
                            "account_name": {"type": "string"},
                            "description": {"type": "string"},
                            "target_account_id": {"type": "string"},
                        },
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "escalate_support",
                    "description": "Hand off to a human admin with a short summary",
                    "parameters": {
                        "type": "object",
                        "properties": {"summary": {"type": "string"}},
                    },
                },
            },
        ]
        from app.services import ai_tools as finance_tools

        tools.extend(finance_tools.OPENAI_TOOLS)
        history = list(session.get("history") or [])[-8:]
        messages: list[dict[str, Any]] = [
            {
                "role": "system",
                "content": (
                    "You are FinTracker’s in-app assistant. Prefer tools over guessing. "
                    "Turn vague money talk into concrete actions: balances, recent txs, month summary, "
                    "or a transaction draft. If required fields are missing for a transaction, call "
                    "start_transaction_draft with whatever you know — the app will prompt for the rest. "
                    "Be concise — one short sentence when a data card will appear. "
                    "Do not repeat balances or transactions as a list. Currency is INR (₹). "
                    "Never invent balances or transactions. "
                    "Use get_safe_to_spend, get_forecast, get_net_worth, and related tools for planning questions. "
                    "Do not give investment or product advice."
                ),
            },
            *history,
            {"role": "user", "content": text},
        ]

        first = await client.chat.completions.create(
            model=os.getenv("FT_OPENAI_MODEL", "gpt-4o-mini"),
            messages=messages,
            tools=tools,
            tool_choice="auto",
            temperature=0.2,
        )
        msg = first.choices[0].message
        tool_calls = msg.tool_calls or []

        if not tool_calls:
            reply = (msg.content or "").strip() or "Tell me what you need — balances, recent activity, or log a spend."
            history.extend(
                [
                    {"role": "user", "content": text},
                    {"role": "assistant", "content": reply},
                ]
            )
            session["history"] = history[-12:]
            await _save_session(session)
            return _result(
                reply,
                quick_replies=FOLLOW_ACTIVITY,
                mode="ai",
            )

        tool_results = []
        escalate = False
        support_prefill = None
        start_draft = None
        card = None
        follow_qs: list[dict[str, str]] | None = None

        for call in tool_calls:
            name = call.function.name
            try:
                args = json.loads(call.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            if name == "start_transaction_draft":
                start_draft = args
                result_text = json.dumps({"ok": True, "fields": args})
            elif name == "escalate_support":
                escalate = True
                support_prefill = str(args.get("summary") or text)
                result_text = await _run_tool(user_id, name, args)
            elif name == "get_balances":
                snap = await snapshot_balances(user_id)
                card = snap.get("card") or card
                follow_qs = snap.get("quick_replies") or follow_qs
                result_text = json.dumps({"reply": snap.get("reply"), "has_card": bool(snap.get("card"))})
            elif name == "get_recent_transactions":
                limit = max(1, min(int(args.get("limit") or 5), 10))
                snap = await snapshot_transactions(user_id, limit=limit)
                card = snap.get("card") or card
                follow_qs = snap.get("quick_replies") or follow_qs
                result_text = json.dumps({"reply": snap.get("reply"), "has_card": bool(snap.get("card"))})
            elif name == "get_month_summary":
                snap = await snapshot_month_summary(user_id)
                card = snap.get("card") or card
                follow_qs = snap.get("quick_replies") or follow_qs
                result_text = json.dumps({"reply": snap.get("reply"), "has_card": bool(snap.get("card"))})
            else:
                result_text = await _run_tool(user_id, name, args)
            tool_results.append(
                {
                    "role": "tool",
                    "tool_call_id": call.id,
                    "content": result_text,
                }
            )

        if start_draft is not None:
            seed: dict[str, Any] = {}
            if start_draft.get("tx_type"):
                seed["tx_type"] = start_draft["tx_type"]
            if start_draft.get("amount"):
                seed["amount"] = float(start_draft["amount"])
            if start_draft.get("description"):
                seed["description"] = start_draft["description"]
            if start_draft.get("account_id"):
                seed["account_id"] = start_draft["account_id"]
            if start_draft.get("account_name"):
                seed["account_name"] = start_draft["account_name"]
            if start_draft.get("target_account_id"):
                seed["target_account_id"] = start_draft["target_account_id"]
            if not seed.get("account_id") and start_draft.get("account_name"):
                matched = await _match_account(user_id, str(start_draft["account_name"]))
                if matched:
                    seed["account_id"] = str(matched["_id"])
                    seed["account_name"] = str(matched.get("name") or "Account")
            history.extend(
                [
                    {"role": "user", "content": text},
                    {"role": "assistant", "content": "Starting a transaction draft and asking for any missing details."},
                ]
            )
            session["history"] = history[-12:]
            await _save_session(session)
            return await _begin_add_flow(user_id, session, seed)

        if escalate:
            return _result(
                "I’ve prepared a handoff to human support.",
                escalate_support=True,
                support_prefill=support_prefill,
                mode="ai",
            )

        follow = await client.chat.completions.create(
            model=os.getenv("FT_OPENAI_MODEL", "gpt-4o-mini"),
            messages=[
                *messages,
                {
                    "role": "assistant",
                    "content": msg.content,
                    "tool_calls": [
                        {
                            "id": c.id,
                            "type": "function",
                            "function": {"name": c.function.name, "arguments": c.function.arguments},
                        }
                        for c in tool_calls
                    ],
                },
                *tool_results,
            ],
            temperature=0.2,
        )
        reply = (follow.choices[0].message.content or "").strip()
        if not reply and not card:
            reply = "\n\n".join(t["content"] for t in tool_results if t.get("content"))
        if card and reply:
            reply = reply.split("\n")[0].strip()
        history.extend(
            [
                {"role": "user", "content": text},
                {"role": "assistant", "content": reply},
            ]
        )
        session["history"] = history[-12:]
        await _save_session(session)
        return _result(
            reply,
            quick_replies=follow_qs or FOLLOW_ACTIVITY,
            mode="ai",
            card=card,
        )
    except Exception as exc:  # noqa: BLE001
        from app.helpers.ai_client import is_ai_connect_error, log_ai_failure

        log_ai_failure("Chat AI mode", exc)
        session["mode"] = "guided"
        await _save_session(session)
        message = (
            "AI mode can’t reach the language model right now. Using guided shortcuts instead."
            if is_ai_connect_error(exc)
            else f"AI mode hit an error ({exc}). Falling back to guided shortcuts."
        )
        return _result(
            message,
            quick_replies=root_quick_replies(authenticated=True),
            mode="guided",
        )


async def bootstrap_chat(
    *,
    user_id: str | None,
    authenticated: bool,
    display_name: str | None = None,
    user_key: str | None = None,
) -> dict[str, Any]:
    key = user_key or user_id or "guest"
    session = await _get_session(key)
    mode = session.get("mode") or "guided"
    if mode == "ai" and not ai_available():
        mode = "guided"
        session["mode"] = "guided"
        await _save_session(session)

    welcome = welcome_text(authenticated=authenticated, display_name=display_name)
    return {
        "welcome": welcome,
        "mode": mode,
        "ai_available": ai_available(),
        "quick_replies": [],
        "menu": welcome_menu(authenticated=authenticated),
        "authenticated": authenticated,
        "in_flow": bool(session.get("step")),
    }


async def process_chat_message(
    *,
    user_id: str | None,
    authenticated: bool,
    message: str | None = None,
    quick_id: str | None = None,
    set_mode: str | None = None,
    user_key: str | None = None,
) -> dict[str, Any]:
    key = user_key or user_id or "guest"
    session = await _get_session(key)
    # Keep session document key stable
    session["user_key"] = key
    text = (message or "").strip()
    qid = (quick_id or "").strip() or None

    if set_mode in {"guided", "ai"}:
        if set_mode == "ai" and not ai_available():
            return _result(
                "AI mode isn’t available — add OPENAI_API_KEY, or the provider is unreachable from this host.",
                quick_replies=root_quick_replies(authenticated=authenticated),
                mode="guided",
            )
        if set_mode == "ai" and not authenticated:
            return _result(
                "Sign in to use AI mode.",
                quick_replies=root_quick_replies(authenticated=False),
                mode="guided",
            )
        session["mode"] = set_mode
        await _save_session(session)
        if not text and not qid:
            label = "AI" if set_mode == "ai" else "Guided"
            return _result(
                f"{label} mode is on.",
                quick_replies=root_quick_replies(authenticated=authenticated),
                mode=set_mode,
            )

    if not text and not qid:
        return _result(
            "Send a message or tap a shortcut.",
            quick_replies=root_quick_replies(authenticated=authenticated),
            mode=session.get("mode") or "guided",
        )

    display_for_log = text or qid or ""
    await _log_user(user_id, display_for_log)

    mode = session.get("mode") or "guided"
    guided_quick_ids = {
        "last5",
        "balances",
        "summary",
        "add_tx",
        "menu",
        "guided",
        "ai",
        "support",
        "faq_login",
        "faq_password",
        "faq_recurring",
        "spending",
        "upcoming",
        "cards",
        "activity",
        "networth",
        "confirm_tx",
        "cancel",
    }
    is_guided_quick = bool(
        qid
        and (
            qid in guided_quick_ids
            or qid.startswith(("type:", "acct:"))
        )
    )
    if mode == "ai" and authenticated and user_id and not is_guided_quick:
        result = await _handle_ai(user_id=user_id, text=text or qid or "", session=session)
    else:
        result = await _handle_guided(
            user_id=user_id,
            authenticated=authenticated,
            text=text,
            quick_id=qid,
            session=session,
        )

    if result.get("reply"):
        await _log_bot(user_id, result["reply"])
    return result
