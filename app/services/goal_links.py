"""
Link investments (recurring rules and one-time transactions) to financial goals.

Responsibilities:
- Validate and store links on the goal (an investment funds at most one goal)
- Load posted contributions for goals in one batch
- List link candidates for the UI

This module MUST NOT:
- Move money (linking is bookkeeping only)
- Render templates / redirect / access session
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from bson import ObjectId

from app.core.errors import NotFoundError, ValidationError
from app.db.mongo import db
from app.helpers.goal_math import (
    INVESTMENT_CATEGORY_CODES,
    INVESTMENT_SUBCATEGORY_CODES,
    is_investment_like,
    monthly_equivalent,
    rule_status,
    summarize_goal_links,
)
from app.helpers.money import round_money
from app.helpers.recurring_ui import frequency_label

CANDIDATE_LOOKBACK_DAYS = 400
CANDIDATE_LIMIT = 150
MAX_LINKS_PER_KIND = 100


def _oid(value) -> ObjectId:
    try:
        return value if isinstance(value, ObjectId) else ObjectId(str(value))
    except Exception as exc:
        raise ValidationError("Invalid identifier") from exc


def _oids(values) -> list[ObjectId]:
    seen: dict[ObjectId, None] = {}
    for value in values or []:
        if str(value or "").strip():
            seen[_oid(value)] = None
    return list(seen)


def _posted_filter(uid: ObjectId) -> dict:
    return {"user_id": uid, "deleted_at": None, "is_failed": {"$ne": True}}


async def set_goal_links(
    user_id: str,
    goal_id: str,
    *,
    recurring_ids: list[str] | None = None,
    transaction_ids: list[str] | None = None,
) -> dict:
    """
    Replace the goal's linked investments. Items linked to another goal are
    moved here, so an investment is never counted towards two goals.
    """
    uid = _oid(user_id)
    goal_oid = _oid(goal_id)
    goal = await db.financial_goals.find_one({"_id": goal_oid, "user_id": uid}, {"_id": 1})
    if not goal:
        raise NotFoundError("Goal not found")

    rule_oids = _oids(recurring_ids)
    tx_oids = _oids(transaction_ids)
    if len(rule_oids) > MAX_LINKS_PER_KIND or len(tx_oids) > MAX_LINKS_PER_KIND:
        raise ValidationError(f"Link at most {MAX_LINKS_PER_KIND} items of each kind")

    if rule_oids:
        owned = await db.recurring_deposits.find(
            {"_id": {"$in": rule_oids}, "user_id": uid}, {"_id": 1}
        ).to_list(length=None)
        if len(owned) != len(rule_oids):
            raise ValidationError("Some recurring rules were not found")
    if tx_oids:
        owned = await db.transactions.find(
            {"_id": {"$in": tx_oids}, **_posted_filter(uid)}, {"_id": 1, "recurring_id": 1}
        ).to_list(length=None)
        if len(owned) != len(tx_oids):
            raise ValidationError("Some transactions were not found")
        if any(row.get("recurring_id") for row in owned):
            raise ValidationError("Link the recurring rule instead of its individual instalments")

    now = datetime.now(timezone.utc)
    others = {"user_id": uid, "_id": {"$ne": goal_oid}}
    if rule_oids:
        await db.financial_goals.update_many(
            {**others, "linked_recurring_ids": {"$in": rule_oids}},
            {"$pull": {"linked_recurring_ids": {"$in": rule_oids}}, "$set": {"updated_at": now}},
        )
    if tx_oids:
        await db.financial_goals.update_many(
            {**others, "linked_transaction_ids": {"$in": tx_oids}},
            {"$pull": {"linked_transaction_ids": {"$in": tx_oids}}, "$set": {"updated_at": now}},
        )
    await db.financial_goals.update_one(
        {"_id": goal_oid},
        {"$set": {"linked_recurring_ids": rule_oids, "linked_transaction_ids": tx_oids, "updated_at": now}},
    )
    return {"recurring_ids": [str(o) for o in rule_oids], "transaction_ids": [str(o) for o in tx_oids]}


async def load_goal_contributions(user_id: str | ObjectId, goals: list[dict], *, today) -> dict[str, dict]:
    """goal id -> summarize_goal_links() result, for goals that have any links."""
    uid = _oid(user_id)
    rule_ids = {oid for g in goals for oid in _oids(g.get("linked_recurring_ids"))}
    tx_ids = {oid for g in goals for oid in _oids(g.get("linked_transaction_ids"))}
    if not rule_ids and not tx_ids:
        return {}

    rules_by_id: dict[str, dict] = {}
    if rule_ids:
        async for rule in db.recurring_deposits.find({"_id": {"$in": list(rule_ids)}, "user_id": uid}):
            rules_by_id[str(rule["_id"])] = rule

    ors = []
    if rule_ids:
        ors.append({"recurring_id": {"$in": list(rule_ids)}})
    if tx_ids:
        ors.append({"_id": {"$in": list(tx_ids)}})
    rows = await db.transactions.find(
        {**_posted_filter(uid), "$or": ors},
        {"amount": 1, "created_at": 1, "description": 1, "recurring_id": 1},
    ).to_list(length=None)

    out: dict[str, dict] = {}
    for goal in goals:
        g_rules = {str(o) for o in _oids(goal.get("linked_recurring_ids"))}
        g_txs = {str(o) for o in _oids(goal.get("linked_transaction_ids"))}
        if not g_rules and not g_txs:
            continue
        contributions = [
            row
            for row in rows
            if (row.get("recurring_id") and str(row["recurring_id"]) in g_rules)
            or (not row.get("recurring_id") and str(row["_id"]) in g_txs)
        ]
        out[str(goal["id"])] = summarize_goal_links(
            linked_rules=[rules_by_id[r] for r in g_rules if r in rules_by_id],
            contributions=contributions,
            today=today,
        )
    return out


async def list_link_candidates(user_id: str) -> dict:
    """
    Recurring rules (not ended) and recent one-time investment transactions the
    user can link, flagged with the goal they currently fund (if any).
    """
    uid = _oid(user_id)
    accounts = {
        str(a["_id"]): a
        async for a in db.accounts.find({"user_id": uid, "deleted_at": None}, {"name": 1, "bank_name": 1, "type": 1})
    }

    def account_name(account_id) -> str:
        acc = accounts.get(str(account_id)) or {}
        return acc.get("name") or acc.get("bank_name") or "Account"

    def account_type(account_id) -> str:
        return str((accounts.get(str(account_id)) or {}).get("type") or "")

    owner: dict[str, str] = {}
    async for goal in db.financial_goals.find(
        {"user_id": uid, "status": {"$ne": "archived"}},
        {"linked_recurring_ids": 1, "linked_transaction_ids": 1},
    ):
        for oid in (goal.get("linked_recurring_ids") or []) + (goal.get("linked_transaction_ids") or []):
            owner[str(oid)] = str(goal["_id"])

    recurring = []
    async for rule in db.recurring_deposits.find({"user_id": uid, "ended_at": None}):
        rid = str(rule["_id"])
        recurring.append(
            {
                "id": rid,
                "name": rule.get("description") or (rule.get("subcategory") or {}).get("name") or "Recurring",
                "amount": round_money(rule.get("amount")),
                "frequency_label": frequency_label(rule.get("frequency"), rule.get("interval")),
                "monthly_equivalent": monthly_equivalent(rule.get("amount"), rule.get("frequency"), rule.get("interval")),
                "status": rule_status(rule),
                "account_name": account_name(rule.get("account_id")),
                "category": (rule.get("subcategory") or {}).get("name") or (rule.get("category") or {}).get("name") or "",
                "is_investment": is_investment_like(
                    category=rule.get("category"),
                    subcategory=rule.get("subcategory"),
                    account_type=account_type(rule.get("account_id")),
                ),
                "linked_goal_id": owner.get(rid),
            }
        )
    recurring.sort(key=lambda r: (not r["is_investment"], r["status"] != "active", r["name"].lower()))

    since = datetime.now(timezone.utc) - timedelta(days=CANDIDATE_LOOKBACK_DAYS)
    investment_account_ids = [ObjectId(aid) for aid, a in accounts.items() if a.get("type") == "investment"]
    tx_query = {
        **_posted_filter(uid),
        "recurring_id": None,
        "created_at": {"$gte": since},
        "$or": [
            {"category.code": {"$in": ["investments_expense"]}},
            {"subcategory.code": {"$in": ["sip", "fixed_deposit", "recurring_deposit", "mutual_funds", "stocks", "gold", "bonds", "crypto"]}},
            {"account_id": {"$in": investment_account_ids}, "type": {"$in": ["credit", "transfer_in"]}},
        ],
    }
    one_time = []
    cursor = db.transactions.find(
        tx_query,
        {"amount": 1, "created_at": 1, "description": 1, "account_id": 1, "type": 1, "subcategory": 1, "category": 1},
    ).sort("created_at", -1).limit(CANDIDATE_LIMIT)
    async for tx in cursor:
        tid = str(tx["_id"])
        one_time.append(
            {
                "id": tid,
                "description": tx.get("description") or (tx.get("subcategory") or {}).get("name") or "Investment",
                "amount": round_money(tx.get("amount")),
                "date": tx.get("created_at"),
                "account_name": account_name(tx.get("account_id")),
                "category": (tx.get("subcategory") or {}).get("name") or (tx.get("category") or {}).get("name") or "",
                "linked_goal_id": owner.get(tid),
            }
        )

    # Keep already-linked one-time rows visible even if they fall outside the query.
    listed = {row["id"] for row in one_time}
    missing = [ObjectId(t) for t, _ in owner.items() if t not in listed and t not in {r["id"] for r in recurring}]
    if missing:
        async for tx in db.transactions.find({"_id": {"$in": missing}, **_posted_filter(uid), "recurring_id": None}):
            tid = str(tx["_id"])
            one_time.append(
                {
                    "id": tid,
                    "description": tx.get("description") or "Investment",
                    "amount": round_money(tx.get("amount")),
                    "date": tx.get("created_at"),
                    "account_name": account_name(tx.get("account_id")),
                    "category": (tx.get("subcategory") or {}).get("name") or "",
                    "linked_goal_id": owner.get(tid),
                }
            )
    return {"recurring": recurring, "one_time": one_time}


PROMPT_GOAL_LIMIT = 25


def _entry_is_investment(doc: dict, account_type: str, *, inflow_types: set[str]) -> bool:
    """Category says investment, or money moved *into* an investment account."""
    category_code = str((doc.get("category") or {}).get("code") or "")
    subcategory_code = str((doc.get("subcategory") or {}).get("code") or "")
    if category_code in INVESTMENT_CATEGORY_CODES or subcategory_code in INVESTMENT_SUBCATEGORY_CODES:
        return True
    return account_type == "investment" and str(doc.get("type") or "") in inflow_types


async def goal_prompt_for_new_entry(
    user_id: str,
    *,
    transaction_ref: str | ObjectId | None = None,
    recurring_id: str | ObjectId | None = None,
) -> dict | None:
    """
    After a manual add: if the new entry is an investment and the user has open
    goals, return the payload for the "link to a goal?" prompt.

    "goals" lists goals that accept links. Account-tracked goals follow a balance
    and ignore links, so they are listed separately in "account_goals"; when they
    are all the user has, the prompt explains that instead of staying silent.

    transaction_ref may be a transaction id or a transfer id (create_transaction
    returns the transfer id for transfers; the incoming leg is what gets linked).
    """
    uid = _oid(user_id)
    tx = None
    if transaction_ref:
        ref = _oid(transaction_ref)
        tx = await db.transactions.find_one({"_id": ref, "user_id": uid, "deleted_at": None})
        if tx is None:
            tx = await db.transactions.find_one(
                {"transfer_id": ref, "user_id": uid, "type": "transfer_in", "deleted_at": None}
            )
        if tx and (tx.get("is_failed") or tx.get("recurring_id")):
            tx = None

    rule = None
    if recurring_id:
        rule = await db.recurring_deposits.find_one({"_id": _oid(recurring_id), "user_id": uid, "ended_at": None})

    account_ids = [d["account_id"] for d in (tx, rule) if d and d.get("account_id")]
    account_types = {
        str(a["_id"]): str(a.get("type") or "")
        async for a in db.accounts.find({"_id": {"$in": account_ids}, "user_id": uid}, {"type": 1})
    } if account_ids else {}

    if tx and not _entry_is_investment(tx, account_types.get(str(tx.get("account_id")), ""), inflow_types={"credit", "transfer_in"}):
        tx = None
    if rule and not _entry_is_investment(rule, account_types.get(str(rule.get("account_id")), ""), inflow_types={"credit"}):
        rule = None
    if not tx and not rule:
        return None

    open_goals = await db.financial_goals.find(
        {"user_id": uid, "status": {"$in": ["active", "paused"]}},
        {"name": 1, "linked_account_id": 1, "status": 1},
    ).sort("created_at", -1).to_list(length=None)
    goals = [g for g in open_goals if not g.get("linked_account_id")][:PROMPT_GOAL_LIMIT]
    account_goals = [g for g in open_goals if g.get("linked_account_id")][:PROMPT_GOAL_LIMIT]
    if not goals and not account_goals:
        return None

    source = rule or tx
    label = source.get("description") or (source.get("subcategory") or {}).get("name") or "Investment"
    return {
        "transaction_id": str(tx["_id"]) if tx else None,
        "recurring_id": str(rule["_id"]) if rule else None,
        "label": str(label)[:80],
        "amount": round_money(source.get("amount")),
        "frequency_label": frequency_label(rule.get("frequency"), rule.get("interval")) if rule else None,
        "goals": [{"id": str(g["_id"]), "name": str(g.get("name") or "Goal")[:60]} for g in goals],
        "account_goals": [str(g.get("name") or "Goal")[:60] for g in account_goals],
    }


async def add_goal_links(
    user_id: str,
    goal_id: str,
    *,
    recurring_ids: list[str] | None = None,
    transaction_ids: list[str] | None = None,
) -> dict:
    """Add (not replace) investments to a goal's links. Returns the goal name + links."""
    uid = _oid(user_id)
    goal = await db.financial_goals.find_one(
        {"_id": _oid(goal_id), "user_id": uid},
        {"name": 1, "status": 1, "linked_account_id": 1, "linked_recurring_ids": 1, "linked_transaction_ids": 1},
    )
    if not goal:
        raise NotFoundError("Goal not found")
    if goal.get("status") in {"completed", "archived"}:
        raise ValidationError("Reopen the goal before linking new investments")
    if goal.get("linked_account_id"):
        raise ValidationError("This goal tracks an account balance. Switch it to investment tracking to link investments.")

    links = await set_goal_links(
        user_id,
        goal_id,
        recurring_ids=[str(o) for o in goal.get("linked_recurring_ids") or []] + list(recurring_ids or []),
        transaction_ids=[str(o) for o in goal.get("linked_transaction_ids") or []] + list(transaction_ids or []),
    )
    return {"goal_name": goal.get("name") or "Goal", **links}
