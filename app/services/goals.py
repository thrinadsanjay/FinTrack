"""Financial goals CRUD. Does not move money automatically.

Investment links (recurring rules / one-time transactions) live in app.services.goal_links.
"""

from __future__ import annotations

from datetime import datetime, timezone

from bson import ObjectId

from app.core.errors import NotFoundError, ValidationError
from app.db.mongo import db
from app.helpers.money import round_money
from app.helpers.planning_math import GOAL_TYPES, as_date


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _oid(value: str | ObjectId) -> ObjectId:
    try:
        return ObjectId(str(value))
    except Exception as exc:
        raise ValidationError("Invalid identifier") from exc


def serialize_goal(doc: dict) -> dict:
    return {
        "id": str(doc.get("_id")),
        "name": doc.get("name") or "Goal",
        "goal_type": doc.get("goal_type") or "custom",
        "target_amount": round_money(doc.get("target_amount")),
        "current_amount": round_money(doc.get("current_amount")),
        "target_date": doc.get("target_date"),
        "linked_account_id": str(doc["linked_account_id"]) if doc.get("linked_account_id") else None,
        "linked_category_code": doc.get("linked_category_code") or None,
        "linked_recurring_ids": [str(o) for o in doc.get("linked_recurring_ids") or []],
        "linked_transaction_ids": [str(o) for o in doc.get("linked_transaction_ids") or []],
        "notes": doc.get("notes") or "",
        "status": doc.get("status") or "active",
        "created_at": doc.get("created_at"),
        "updated_at": doc.get("updated_at"),
        "completed_at": doc.get("completed_at"),
        "paused_at": doc.get("paused_at"),
        "archived_at": doc.get("archived_at"),
    }


def _normalize_type(value: str | None) -> str:
    raw = str(value or "custom").strip().lower().replace(" ", "_")
    aliases = {
        "emergency": "emergency_fund",
        "new_laptop": "laptop",
        "holiday": "vacation",
    }
    raw = aliases.get(raw, raw)
    if raw not in GOAL_TYPES:
        raise ValidationError("Unsupported goal type")
    return raw


def _normalize_status(value: str | None) -> str:
    raw = str(value or "active").strip().lower()
    if raw not in {"active", "paused", "completed", "archived"}:
        raise ValidationError("Unsupported goal status")
    return raw


async def _owned_account(user_id: ObjectId, account_id: str | None) -> ObjectId | None:
    if not account_id:
        return None
    oid = _oid(account_id)
    account = await db.accounts.find_one(
        {"_id": oid, "user_id": user_id, "deleted_at": None},
        {"_id": 1, "type": 1},
    )
    if not account:
        raise ValidationError("Linked account was not found")
    if str(account.get("type") or "") in {"credit_card", "loan"}:
        raise ValidationError("Credit cards and loans cannot be linked as a goal balance")
    return oid


async def list_goals(user_id: str, *, include_archived: bool = False) -> list[dict]:
    uid = _oid(user_id)
    query: dict = {"user_id": uid}
    if not include_archived:
        query["status"] = {"$ne": "archived"}
    cursor = db.financial_goals.find(query).sort([("status", 1), ("created_at", -1)])
    return [serialize_goal(doc) async for doc in cursor]


async def get_goal(user_id: str, goal_id: str) -> dict:
    uid = _oid(user_id)
    doc = await db.financial_goals.find_one({"_id": _oid(goal_id), "user_id": uid})
    if not doc:
        raise NotFoundError("Goal not found")
    return serialize_goal(doc)


async def create_goal(
    user_id: str,
    *,
    name: str,
    target_amount: float,
    goal_type: str = "custom",
    current_amount: float = 0,
    target_date: str | None = None,
    linked_account_id: str | None = None,
    linked_category_code: str | None = None,
    notes: str | None = None,
    linked_recurring_ids: list[str] | None = None,
    linked_transaction_ids: list[str] | None = None,
) -> dict:
    uid = _oid(user_id)
    label = str(name or "").strip()
    if not label:
        raise ValidationError("Goal name is required")
    target = round_money(target_amount)
    if target <= 0:
        raise ValidationError("Target amount must be greater than zero")
    due = as_date(target_date)
    linked = await _owned_account(uid, linked_account_id)
    now = _now()
    doc = {
        "user_id": uid,
        "name": label[:120],
        "goal_type": _normalize_type(goal_type),
        "target_amount": target,
        "current_amount": round_money(max(0.0, current_amount)),
        "target_date": datetime(due.year, due.month, due.day, tzinfo=timezone.utc) if due else None,
        "linked_account_id": linked,
        "linked_category_code": (linked_category_code or "").strip() or None,
        "notes": (notes or "").strip()[:500],
        "linked_recurring_ids": [],
        "linked_transaction_ids": [],
        "status": "active",
        "created_at": now,
        "updated_at": now,
        "completed_at": None,
        "paused_at": None,
        "archived_at": None,
    }
    result = await db.financial_goals.insert_one(doc)
    doc["_id"] = result.inserted_id
    if linked_recurring_ids or linked_transaction_ids:
        from app.services.goal_links import set_goal_links

        await set_goal_links(
            user_id,
            str(result.inserted_id),
            recurring_ids=linked_recurring_ids,
            transaction_ids=linked_transaction_ids,
        )
        return await get_goal(user_id, str(result.inserted_id))
    return serialize_goal(doc)


async def update_goal(user_id: str, goal_id: str, **fields) -> dict:
    uid = _oid(user_id)
    existing = await db.financial_goals.find_one({"_id": _oid(goal_id), "user_id": uid})
    if not existing:
        raise NotFoundError("Goal not found")

    updates: dict = {"updated_at": _now()}
    if "name" in fields and fields["name"] is not None:
        label = str(fields["name"]).strip()
        if not label:
            raise ValidationError("Goal name is required")
        updates["name"] = label[:120]
    if "goal_type" in fields and fields["goal_type"] is not None:
        updates["goal_type"] = _normalize_type(fields["goal_type"])
    if "target_amount" in fields and fields["target_amount"] is not None:
        target = round_money(fields["target_amount"])
        if target <= 0:
            raise ValidationError("Target amount must be greater than zero")
        updates["target_amount"] = target
    if "current_amount" in fields and fields["current_amount"] is not None:
        updates["current_amount"] = round_money(max(0.0, fields["current_amount"]))
    if "target_date" in fields:
        due = as_date(fields["target_date"]) if fields["target_date"] else None
        updates["target_date"] = (
            datetime(due.year, due.month, due.day, tzinfo=timezone.utc) if due else None
        )
    if "linked_account_id" in fields:
        updates["linked_account_id"] = await _owned_account(uid, fields["linked_account_id"] or None)
    if "linked_category_code" in fields:
        updates["linked_category_code"] = (fields["linked_category_code"] or "").strip() or None
    if "notes" in fields and fields["notes"] is not None:
        updates["notes"] = str(fields["notes"]).strip()[:500]
    if "status" in fields and fields["status"] is not None:
        status = _normalize_status(fields["status"])
        updates["status"] = status
        if status == "completed":
            updates["completed_at"] = _now()
            updates["paused_at"] = None
        elif status == "paused":
            updates["paused_at"] = _now()
        elif status == "archived":
            updates["archived_at"] = _now()
        elif status == "active":
            updates["paused_at"] = None
            updates["archived_at"] = None

    await db.financial_goals.update_one({"_id": existing["_id"]}, {"$set": updates})
    return await get_goal(user_id, goal_id)
