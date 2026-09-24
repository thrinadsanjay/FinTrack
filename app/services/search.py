"""User-scoped global search across FinTracker records."""

from __future__ import annotations

import re
from datetime import datetime, time, timezone

from bson import ObjectId

from app.db.mongo import db
from app.helpers.dashboard_time import app_now
from app.helpers.money import format_inr, round_money
from app.helpers.search_parse import (
    amount_close,
    field_matches,
    in_date_window,
    parse_search_query,
)

GROUP_LIMIT = 8
TX_SCAN = 80


def _oid(user_id: str | ObjectId) -> ObjectId:
    return user_id if isinstance(user_id, ObjectId) else ObjectId(str(user_id))


def _regex(text: str) -> dict:
    return {"$regex": re.escape(text), "$options": "i"}


def _dt_range(date_from, date_to):
    if not date_from and not date_to:
        return None
    start = datetime.combine(date_from, time.min, tzinfo=timezone.utc) if date_from else None
    end = datetime.combine(date_to, time.max, tzinfo=timezone.utc) if date_to else None
    clause: dict = {}
    if start:
        clause["$gte"] = start
    if end:
        clause["$lte"] = end
    return clause


async def search_fintracker(*, user_id: str, query: str, is_admin: bool = False, limit: int | None = None) -> dict:
    parsed = parse_search_query(query, today=app_now().date())
    if not str(query or "").strip():
        return {"query": "", "groups": [], "total": 0}
    cap = max(1, min(int(limit or GROUP_LIMIT), 20))
    uid = _oid(user_id)
    groups = [
        await _search_transactions(uid, parsed, cap),
        await _search_accounts(uid, parsed, cap),
        await _search_recurring(uid, parsed, cap),
        await _search_credit(uid, parsed, cap),
        await _search_goals(uid, parsed, cap),
        await _search_bills_emis(uid, parsed, cap),
        await _search_support(uid, parsed, cap, is_admin=is_admin),
    ]
    groups = [g for g in groups if g["items"]]
    total = sum(len(g["items"]) for g in groups)
    return {"query": parsed["raw"], "groups": groups, "total": total}


async def _search_transactions(uid: ObjectId, parsed: dict, cap: int) -> dict:
    filt: dict = {"user_id": uid, "deleted_at": None, "is_failed": {"$ne": True}}
    and_terms: list = []
    or_terms: list = []
    if parsed.get("text"):
        or_terms.extend(
            [
                {"description": _regex(parsed["text"])},
                {"category.name": _regex(parsed["text"])},
                {"subcategory.name": _regex(parsed["text"])},
            ]
        )
    if parsed.get("amount") is not None:
        or_terms.append({"amount": parsed["amount"]})
        or_terms.append({"amount": round_money(parsed["amount"])})
    window = _dt_range(parsed.get("date_from"), parsed.get("date_to"))
    if window:
        and_terms.append({"$or": [{"created_at": window}, {"transaction_date": window}]})
    if or_terms:
        and_terms.append({"$or": or_terms})
    if and_terms:
        filt["$and"] = and_terms
    cursor = db.transactions.find(filt).sort("created_at", -1).limit(TX_SCAN)
    items = []
    seen = set()
    async for doc in cursor:
        key = str(doc["_id"])
        if key in seen:
            continue
        desc = str(doc.get("description") or "")
        cat = str((doc.get("category") or {}).get("name") or "")
        sub = str((doc.get("subcategory") or {}).get("name") or "")
        when = doc.get("transaction_date") or doc.get("created_at")
        if parsed.get("date_from") and not in_date_window(when, parsed.get("date_from"), parsed.get("date_to")):
            continue
        matched_amount = parsed.get("amount") is not None and amount_close(doc.get("amount"), parsed["amount"])
        matched_text = field_matches(parsed, desc, cat, sub) if parsed.get("tokens") else True
        if parsed.get("tokens") and not matched_text and not matched_amount:
            continue
        seen.add(key)
        q = desc or cat or parsed["raw"]
        items.append(
            {
                "id": key,
                "title": desc or cat or "Transaction",
                "subtitle": f"{format_inr(doc.get('amount'))} · {cat or (doc.get('type') or '')}",
                "href": f"/transactions/all?search={_q(q)}",
                "group": "transactions",
            }
        )
        if len(items) >= cap:
            break
    return {"id": "transactions", "label": "Transactions", "items": items}


async def _search_accounts(uid: ObjectId, parsed: dict, cap: int) -> dict:
    items = []
    cursor = db.accounts.find({"user_id": uid, "deleted_at": None}, {"name": 1, "bank_name": 1, "type": 1, "balance": 1})
    async for doc in cursor:
        name = str(doc.get("name") or doc.get("bank_name") or "Account")
        if parsed.get("tokens") and not field_matches(parsed, name, doc.get("bank_name") or "", doc.get("type") or ""):
            if parsed.get("amount") is None or not amount_close(doc.get("balance"), parsed["amount"]):
                continue
        items.append(
            {
                "id": str(doc["_id"]),
                "title": name,
                "subtitle": f"{doc.get('type') or 'account'} · {format_inr(doc.get('balance'))}",
                "href": "/accounts",
                "group": "accounts",
            }
        )
        if len(items) >= cap:
            break
    return {"id": "accounts", "label": "Accounts", "items": items}


async def _search_recurring(uid: ObjectId, parsed: dict, cap: int) -> dict:
    items = []
    cursor = db.recurring_deposits.find({"user_id": uid}).sort("next_run", 1).limit(60)
    async for doc in cursor:
        desc = str(doc.get("description") or "")
        cat = str((doc.get("category") or {}).get("name") or "")
        if parsed.get("tokens") and not field_matches(parsed, desc, cat):
            if parsed.get("amount") is None or not amount_close(doc.get("amount"), parsed["amount"]):
                continue
        items.append(
            {
                "id": str(doc["_id"]),
                "title": desc or cat or "Recurring",
                "subtitle": f"{format_inr(doc.get('amount'))} · {doc.get('frequency') or ''}",
                "href": "/recurring",
                "group": "recurring",
            }
        )
        if len(items) >= cap:
            break
    return {"id": "recurring", "label": "Recurring", "items": items}


async def _search_credit(uid: ObjectId, parsed: dict, cap: int) -> dict:
    items = []
    seen = set()
    cursor = db.credit_cards.find({"user_id": uid}, {"card_name": 1, "status": 1})
    async for doc in cursor:
        name = str(doc.get("card_name") or "Card")
        if parsed.get("tokens") and not field_matches(parsed, name):
            continue
        seen.add(str(doc["_id"]))
        items.append(
            {
                "id": str(doc["_id"]),
                "title": name,
                "subtitle": str(doc.get("status") or "card"),
                "href": "/accounts?group=card",
                "group": "credit_cards",
            }
        )
        if len(items) >= cap:
            break
    txn_cursor = (
        db.credit_card_transactions.find({"user_id": uid, "deleted_at": None})
        .sort("txn_date", -1)
        .limit(TX_SCAN)
    )
    async for doc in txn_cursor:
        if len(items) >= cap:
            break
        merchant = str(doc.get("merchant") or doc.get("description") or "")
        if parsed.get("tokens") and not field_matches(parsed, merchant, str(doc.get("category") or "")):
            if parsed.get("amount") is None or not amount_close(doc.get("amount"), parsed["amount"]):
                continue
        key = f"ctx:{doc['_id']}"
        if key in seen:
            continue
        items.append(
            {
                "id": str(doc["_id"]),
                "title": merchant or "Card transaction",
                "subtitle": format_inr(doc.get("amount")),
                "href": "/accounts?group=card",
                "group": "credit_cards",
            }
        )
    return {"id": "credit_cards", "label": "Credit Cards", "items": items[:cap]}


async def _search_goals(uid: ObjectId, parsed: dict, cap: int) -> dict:
    items = []
    cursor = db.financial_goals.find({"user_id": uid}).limit(40)
    async for doc in cursor:
        name = str(doc.get("name") or "Goal")
        if parsed.get("tokens") and not field_matches(parsed, name, str(doc.get("notes") or "")):
            continue
        items.append(
            {
                "id": str(doc["_id"]),
                "title": name,
                "subtitle": f"{format_inr(doc.get('current_amount'))} / {format_inr(doc.get('target_amount'))}",
                "href": "/planning/goals",
                "group": "goals",
            }
        )
        if len(items) >= cap:
            break
    return {"id": "goals", "label": "Goals", "items": items}


async def _search_bills_emis(uid: ObjectId, parsed: dict, cap: int) -> dict:
    items = []
    bill_cursor = db.credit_card_bills.find({"user_id": uid}).sort("due_date", -1).limit(40)
    async for doc in bill_cursor:
        label = str(doc.get("cycle_key") or "Bill")
        if parsed.get("tokens") and not field_matches(parsed, label, str(doc.get("payment_status") or "")):
            if parsed.get("amount") is None or not amount_close(doc.get("total_due") or doc.get("amount_due"), parsed["amount"]):
                continue
        items.append(
            {
                "id": str(doc["_id"]),
                "title": f"Bill {label}",
                "subtitle": str(doc.get("payment_status") or "bill"),
                "href": "/planning/calendar",
                "group": "bills",
            }
        )
        if len(items) >= cap:
            break
    emi_cursor = db.credit_card_emis.find({"user_id": uid, "deleted_at": None}).limit(40)
    async for doc in emi_cursor:
        if len(items) >= cap:
            break
        title = str(doc.get("title") or doc.get("merchant") or "EMI")
        if parsed.get("tokens") and not field_matches(parsed, title):
            if parsed.get("amount") is None or not amount_close(doc.get("monthly_amount"), parsed["amount"]):
                continue
        items.append(
            {
                "id": str(doc["_id"]),
                "title": title,
                "subtitle": f"EMI · {format_inr(doc.get('monthly_amount'))}",
                "href": "/accounts?group=card",
                "group": "bills",
            }
        )
    return {"id": "bills", "label": "Bills & EMIs", "items": items[:cap]}


async def _search_support(uid: ObjectId, parsed: dict, cap: int, *, is_admin: bool) -> dict:
    items = []
    filt: dict = {"user_id": uid}
    if parsed.get("text"):
        # Support sessions do not store other users' ledgers.
        cursor = db.support_sessions.find(filt).sort("updated_at", -1).limit(20)
        async for doc in cursor:
            snippet = str(doc.get("last_message") or doc.get("status") or "Support")
            if parsed.get("tokens") and not field_matches(parsed, snippet, str(doc.get("status") or "")):
                continue
            items.append(
                {
                    "id": str(doc["_id"]),
                    "title": "Support conversation",
                    "subtitle": snippet[:80],
                    "href": "/help-support",
                    "group": "support",
                }
            )
            if len(items) >= cap:
                break
    if is_admin and parsed.get("text") and len(items) < cap:
        admin_cursor = (
            db.support_sessions.find({"status": {"$exists": True}})
            .sort("updated_at", -1)
            .limit(20)
        )
        async for doc in admin_cursor:
            if doc.get("user_id") == uid:
                continue
            snippet = str(doc.get("last_message") or doc.get("status") or "")
            if not field_matches(parsed, snippet, str(doc.get("status") or "")):
                continue
            items.append(
                {
                    "id": str(doc["_id"]),
                    "title": "Support request",
                    "subtitle": (snippet or "Open request")[:80],
                    "href": "/admin#support",
                    "group": "support",
                }
            )
            if len(items) >= cap:
                break
    return {"id": "support", "label": "Support", "items": items}


def _q(value: str) -> str:
    from urllib.parse import quote_plus

    return quote_plus(str(value or "")[:80])
