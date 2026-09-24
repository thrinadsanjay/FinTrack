"""User-owned financial automations. Never transfers money."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from bson import ObjectId

from app.db.mongo import db
from app.helpers.dashboard_time import app_now
from app.helpers.money import format_inr, round_money
from app.helpers.rules_math import (
    ACTION_TYPES,
    CONDITION_TYPES,
    EVENT_SALARY,
    actions_for_rules,
    looks_like_salary,
    normalize_action,
    normalize_condition,
    select_rules_for_event,
    snapshot_dedupe_key,
)
from app.services.audit import audit_log
from app.services.categories import get_categories_by_type, get_subcategories
from app.services.notifications import upsert_notification

logger = logging.getLogger(__name__)

COL_RULES = "financial_rules"
COL_RUNS = "financial_rule_runs"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _uid(user_id: str | ObjectId) -> ObjectId:
    return user_id if isinstance(user_id, ObjectId) else ObjectId(str(user_id))


def _public_rule(doc: dict) -> dict:
    return {
        "id": str(doc["_id"]),
        "name": doc.get("name") or "Rule",
        "enabled": bool(doc.get("enabled", True)),
        "priority": int(doc.get("priority") or 0),
        "conditions": doc.get("conditions") or [],
        "actions": doc.get("actions") or [],
        "created_at": doc.get("created_at"),
        "updated_at": doc.get("updated_at"),
    }


async def list_rules(user_id: str) -> list[dict]:
    rows = []
    cursor = db[COL_RULES].find({"user_id": _uid(user_id)}).sort([("priority", -1), ("created_at", -1)])
    async for doc in cursor:
        rows.append(_public_rule(doc))
    return rows


async def get_rule(user_id: str, rule_id: str) -> dict | None:
    if not ObjectId.is_valid(rule_id):
        return None
    doc = await db[COL_RULES].find_one({"_id": ObjectId(rule_id), "user_id": _uid(user_id)})
    return _public_rule(doc) if doc else None


def _validate_payload(payload: dict) -> dict:
    name = str(payload.get("name") or "").strip()[:120]
    if not name:
        raise ValueError("Rule name is required")
    conditions = [c for c in (normalize_condition(c) for c in (payload.get("conditions") or [])) if c]
    actions = [a for a in (normalize_action(a) for a in (payload.get("actions") or [])) if a]
    if not conditions:
        raise ValueError("Add at least one valid condition")
    if not actions:
        raise ValueError("Add at least one valid action")
    if any(a["type"] == "transfer" for a in actions):
        raise ValueError("Automatic transfers are not supported")
    return {
        "name": name,
        "enabled": bool(payload.get("enabled", True)),
        "priority": int(payload.get("priority") or 0),
        "conditions": conditions,
        "actions": actions,
    }


async def create_rule(user_id: str, payload: dict, *, request=None) -> dict:
    body = _validate_payload(payload)
    doc = {
        "user_id": _uid(user_id),
        **body,
        "created_at": _now(),
        "updated_at": _now(),
    }
    result = await db[COL_RULES].insert_one(doc)
    doc["_id"] = result.inserted_id
    await audit_log(
        action="FINANCIAL_RULE_CREATED",
        request=request,
        user={"user_id": str(user_id)},
        meta={"rule_id": str(result.inserted_id), "name": body["name"]},
    )
    return _public_rule(doc)


async def update_rule(user_id: str, rule_id: str, payload: dict, *, request=None) -> dict:
    existing = await get_rule(user_id, rule_id)
    if not existing:
        raise LookupError("Rule not found")
    body = _validate_payload({**existing, **payload, "name": payload.get("name", existing["name"])})
    await db[COL_RULES].update_one(
        {"_id": ObjectId(rule_id), "user_id": _uid(user_id)},
        {"$set": {**body, "updated_at": _now()}},
    )
    await audit_log(
        action="FINANCIAL_RULE_UPDATED",
        request=request,
        user={"user_id": str(user_id)},
        meta={"rule_id": rule_id},
    )
    return await get_rule(user_id, rule_id)


async def set_rule_enabled(user_id: str, rule_id: str, enabled: bool, *, request=None) -> dict | None:
    if not ObjectId.is_valid(rule_id):
        return None
    result = await db[COL_RULES].update_one(
        {"_id": ObjectId(rule_id), "user_id": _uid(user_id)},
        {"$set": {"enabled": bool(enabled), "updated_at": _now()}},
    )
    if result.matched_count == 0:
        return None
    await audit_log(
        action="FINANCIAL_RULE_TOGGLED",
        request=request,
        user={"user_id": str(user_id)},
        meta={"rule_id": rule_id, "enabled": bool(enabled)},
    )
    return await get_rule(user_id, rule_id)


async def delete_rule(user_id: str, rule_id: str, *, request=None) -> bool:
    if not ObjectId.is_valid(rule_id):
        return False
    result = await db[COL_RULES].delete_one({"_id": ObjectId(rule_id), "user_id": _uid(user_id)})
    if result.deleted_count:
        await audit_log(
            action="FINANCIAL_RULE_DELETED",
            request=request,
            user={"user_id": str(user_id)},
            meta={"rule_id": rule_id},
        )
    return result.deleted_count > 0


async def list_rule_runs(user_id: str, *, rule_id: str | None = None, limit: int = 50) -> list[dict]:
    filt: dict[str, Any] = {"user_id": _uid(user_id)}
    if rule_id and ObjectId.is_valid(rule_id):
        filt["rule_id"] = ObjectId(rule_id)
    rows = []
    cursor = db[COL_RUNS].find(filt).sort("created_at", -1).limit(max(1, min(limit, 100)))
    async for doc in cursor:
        rows.append(
            {
                "id": str(doc["_id"]),
                "rule_id": str(doc.get("rule_id") or ""),
                "rule_name": doc.get("rule_name"),
                "event_type": doc.get("event_type"),
                "actions": doc.get("actions") or [],
                "status": doc.get("status") or "ok",
                "created_at": doc.get("created_at"),
            }
        )
    return rows


async def _enabled_rules(user_id: ObjectId) -> list[dict]:
    rows = []
    cursor = db[COL_RULES].find({"user_id": user_id, "enabled": True})
    async for doc in cursor:
        public = _public_rule(doc)
        rows.append(public)
    return rows


async def _log_run(*, user_id: ObjectId, rule: dict, event_type: str, actions: list[dict], status: str, dedupe_key: str | None = None) -> None:
    doc = {
        "user_id": user_id,
        "rule_id": ObjectId(rule["id"]) if ObjectId.is_valid(rule.get("id")) else None,
        "rule_name": rule.get("name"),
        "event_type": event_type,
        "actions": [{"type": a.get("type"), "code": a.get("code")} for a in actions],
        "status": status,
        "created_at": _now(),
    }
    if dedupe_key:
        doc["dedupe_key"] = dedupe_key
    try:
        await db[COL_RUNS].insert_one(doc)
    except Exception:
        logger.exception("Failed to record rule run")


async def apply_transaction_rules(*, user_id: ObjectId | str, transaction_id) -> None:
    if not transaction_id:
        return
    uid = _uid(user_id)
    tx = await db.transactions.find_one({"_id": transaction_id if isinstance(transaction_id, ObjectId) else ObjectId(str(transaction_id)), "user_id": uid})
    if not tx:
        return
    rules = await _enabled_rules(uid)
    if not rules:
        return
    event = {
        "event_type": EVENT_SALARY if looks_like_salary({"tx_type": tx.get("type"), "description": tx.get("description"), "category": tx.get("category")}) else "transaction_created",
        "tx_type": tx.get("type"),
        "type": tx.get("type"),
        "amount": tx.get("amount"),
        "description": tx.get("description"),
        "merchant": tx.get("description"),
        "account_id": str(tx.get("account_id") or ""),
        "category": tx.get("category") or {},
        "is_recurring": bool(tx.get("recurring_id")),
        "recurring_id": tx.get("recurring_id"),
        "applied_rule_ids": list(tx.get("applied_rule_ids") or []),
        "source": tx.get("source"),
    }
    matched = select_rules_for_event(rules, event)
    if not matched:
        return
    actions = actions_for_rules(matched)
    applied_ids = list(event["applied_rule_ids"])
    updates: dict[str, Any] = {}
    for rule in matched:
        applied_ids.append(rule["id"])
    for action in actions:
        try:
            await _perform_action(uid, tx, action, updates)
            await _log_run(user_id=uid, rule={"id": action.get("rule_id"), "name": action.get("rule_name")}, event_type=event["event_type"], actions=[action], status="ok")
        except Exception:
            logger.exception("Rule action failed")
            await _log_run(user_id=uid, rule={"id": action.get("rule_id"), "name": action.get("rule_name")}, event_type=event["event_type"], actions=[action], status="error")
    updates["applied_rule_ids"] = applied_ids
    updates["updated_at"] = _now()
    await db.transactions.update_one({"_id": tx["_id"], "user_id": uid}, {"$set": updates})
    await audit_log(
        action="FINANCIAL_RULE_EXECUTED",
        user={"user_id": str(uid)},
        meta={"transaction_id": str(tx["_id"]), "rule_ids": applied_ids},
    )


async def evaluate_snapshot_rules(user_id: str) -> None:
    uid = _uid(user_id)
    rules = await _enabled_rules(uid)
    snapshot_needed = any(
        any(c.get("type") in {"balance_lt", "utilization_gt", "due_within_days"} for c in (r.get("conditions") or []))
        for r in rules
    )
    if not snapshot_needed:
        return
    accounts = await db.accounts.find({"user_id": uid, "deleted_at": None}).to_list(length=200)
    cash = 0.0
    util = None
    card_limit = 0.0
    outstanding = 0.0
    today = app_now().date()
    day_key = today.isoformat()
    for acc in accounts:
        acc_type = str(acc.get("type") or "")
        bal = round_money(acc.get("balance"))
        if acc_type in {"savings", "current", "cash", "wallet"}:
            cash += bal
            event = {
                "event_type": "account_snapshot",
                "balance": bal,
                "account_id": str(acc["_id"]),
                "today": today,
                "source": "snapshot",
            }
            await _run_snapshot_event(uid, rules, event, day_key, str(acc["_id"]))
        if acc_type == "credit_card":
            limit = round_money(acc.get("credit_limit"))
            card_limit += limit
            if bal < 0:
                outstanding += abs(bal)
    if card_limit > 0:
        util = round((outstanding / card_limit) * 100, 1)
        event = {
            "event_type": "account_snapshot",
            "utilization": util,
            "balance": cash,
            "today": today,
            "source": "snapshot",
        }
        await _run_snapshot_event(uid, rules, event, day_key, "utilization")

    due_cursor = db.credit_card_bills.find(
        {"user_id": uid, "payment_status": {"$nin": ["paid", "settled"]}},
        {"due_date": 1, "total_due": 1, "amount_due": 1},
    ).limit(20)
    async for bill in due_cursor:
        event = {
            "event_type": "account_snapshot",
            "due_date": bill.get("due_date"),
            "today": today,
            "amount": bill.get("total_due") or bill.get("amount_due"),
            "source": "snapshot",
        }
        await _run_snapshot_event(uid, rules, event, day_key, str(bill["_id"]))


async def _run_snapshot_event(uid: ObjectId, rules: list[dict], event: dict, day_key: str, scope: str) -> None:
    matched = select_rules_for_event(rules, event)
    for rule in matched:
        dedupe = snapshot_dedupe_key(rule_id=rule["id"], event_type=event.get("event_type") or "snapshot", day_key=day_key, account_id=scope)
        existing = await db[COL_RUNS].find_one({"user_id": uid, "dedupe_key": dedupe})
        if existing:
            continue
        actions = actions_for_rules([rule])
        status = "ok"
        for action in actions:
            try:
                await _perform_action(uid, None, action, {})
            except Exception:
                logger.exception("Snapshot rule action failed")
                status = "error"
        await _log_run(user_id=uid, rule=rule, event_type=event.get("event_type") or "snapshot", actions=actions, status=status, dedupe_key=dedupe)


async def _perform_action(uid: ObjectId, tx: dict | None, action: dict, updates: dict) -> None:
    kind = action.get("type")
    if kind == "set_category" and tx is not None:
        code = action.get("code")
        name = action.get("name") or code
        tx_type = str(tx.get("type") or "debit")
        categories = await get_categories_by_type(tx_type)
        match = next((c for c in categories if c.get("code") == code or str(c.get("name") or "").lower() == str(name or "").lower()), None)
        if match:
            updates["category"] = {"code": match["code"], "name": match["name"]}
        elif code:
            updates["category"] = {"code": code, "name": name or code}
        return
    if kind == "set_subcategory" and tx is not None:
        code = action.get("code")
        name = action.get("name") or code
        cat_code = (updates.get("category") or tx.get("category") or {}).get("code")
        if cat_code:
            subs = await get_subcategories(category_code=cat_code, tx_type=str(tx.get("type") or "debit")) or []
            match = next((s for s in subs if s.get("code") == code or str(s.get("name") or "").lower() == str(name or "").lower()), None)
            if match:
                updates["subcategory"] = {"code": match.get("code"), "name": match.get("name")}
                return
        updates["subcategory"] = {"code": code, "name": name or code}
        return
    if kind == "mark_review" and tx is not None:
        updates["needs_review"] = True
        updates["review_reason"] = action.get("message") or "Flagged by automation"
        return
    if kind in {"notify", "telegram_notify", "add_insight", "goal_allocation_hint"}:
        title = action.get("title") or action.get("rule_name") or "FinTracker alert"
        message = action.get("message") or _default_message(kind, tx)
        key = f"rule:{action.get('rule_id')}:{kind}"
        notif_type = "info" if kind in {"add_insight", "goal_allocation_hint"} else "warning"
        await upsert_notification(
            user_id=uid,
            key=key,
            notif_type=notif_type,
            title=title,
            message=message,
        )
        return


def _default_message(kind: str, tx: dict | None) -> str:
    if kind == "goal_allocation_hint":
        return "Salary was recorded. Review Goals if you want to allocate part of it — FinTracker will not move money automatically."
    if tx:
        return f"A matching transaction of {format_inr(tx.get('amount'))} was recorded."
    return "A financial rule matched your latest account snapshot."


def catalog() -> dict:
    return {"conditions": list(CONDITION_TYPES), "actions": list(ACTION_TYPES)}
