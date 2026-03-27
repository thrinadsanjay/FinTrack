"""
Dashboard read-only analytics.

Responsibilities:
- Compute balances
- Aggregate transaction stats
- Fetch recent activity

Must NOT:
- Render templates
- Write audit logs
"""

from datetime import datetime, timezone, timedelta
from bson import ObjectId
from app.db.mongo import db
from app.helpers.dashboard_cards import (
    fetch_total_balance,
    fetch_credit_debit_totals_since,
    fetch_account_balances_and_map,
    fetch_top_spending_categories,
    fetch_largest_transactions,
    fetch_daily_trend,
    fetch_monthly_trend_12m,
    build_credit_card_alerts,
)
from app.helpers.dashboard_recurring import fetch_dashboard_recurring_overview
from app.helpers.dashboard_time import start_of_today_utc, start_of_month_utc, start_of_day_utc
from app.helpers.dashboard_upcoming import fetch_upcoming_bills
from app.helpers.dashboard_notifications import persist_dashboard_notifications


async def _fetch_recurring_overview(uid: ObjectId, account_map: dict):
    return await fetch_dashboard_recurring_overview(uid, account_map)


async def _fetch_upcoming_bills(uid: ObjectId, account_map: dict):
    return await fetch_upcoming_bills(uid, account_map)


# ======================================================
# DASHBOARD SUMMARY
# ======================================================

async def get_dashboard_summary(user_id: str):
    uid = ObjectId(user_id)

    today = start_of_today_utc()
    month_start = start_of_month_utc()
    balance = await fetch_total_balance(uid)
    today_credit, today_debit = await fetch_credit_debit_totals_since(uid, today)
    month_credit, month_debit = await fetch_credit_debit_totals_since(uid, month_start)
    account_balances, account_map = await fetch_account_balances_and_map(uid)
    top_spending_categories = await fetch_top_spending_categories(uid, month_start, month_debit)
    largest_transactions = await fetch_largest_transactions(uid, month_start, account_map)

    now_utc = datetime.now(timezone.utc)
    trend_start = start_of_month_utc()
    trend_end = start_of_day_utc(now_utc) + timedelta(days=1)
    trend_daily = await fetch_daily_trend(uid, trend_start, trend_end)
    cashflow_month_label = trend_start.strftime("%b %Y")

    month_anchor = start_of_month_utc()
    trend_monthly, monthly_map, monthly_range_label, monthly_till_label = (
        await fetch_monthly_trend_12m(uid, month_anchor)
    )

    upcoming_bills_7, upcoming_bills_month, required_by_account = (
        await _fetch_upcoming_bills(uid, account_map)
    )
    recurring_overview = await _fetch_recurring_overview(uid, account_map)

    notifications = await _persist_notifications(
        uid=uid,
        required_by_account=required_by_account,
        account_map=account_map,
    )

    savings_rate = None
    if month_credit > 0:
        savings_rate = round(((month_credit - month_debit) / month_credit) * 100, 1)

    prev_month_anchor = month_anchor - timedelta(days=1)
    prev_month_key = prev_month_anchor.strftime("%Y-%m")
    prev_credit = monthly_map.get(prev_month_key, {}).get("credit", 0)
    prev_debit = monthly_map.get(prev_month_key, {}).get("debit", 0)
    savings_rate_change = None
    if savings_rate is not None and prev_credit > 0:
        prev_rate = ((prev_credit - prev_debit) / prev_credit) * 100
        savings_rate_change = round(savings_rate - prev_rate, 1)

    account_alerts = build_credit_card_alerts(account_balances, notifications)

    return {
        "balance": balance,
        "today_credit": today_credit,
        "today_debit": today_debit,
        "today_income": today_credit,
        "today_expense": today_debit,
        "month_net": month_credit - month_debit,
        "month_income": month_credit,
        "month_expense": month_debit,
        "savings_rate": savings_rate,
        "savings_rate_change": savings_rate_change,
        "account_balances": account_balances,
        "top_spending_categories": top_spending_categories,
        "largest_transactions": largest_transactions,
        "trend_daily": trend_daily,
        "cashflow_month_label": cashflow_month_label,
        "trend_monthly": trend_monthly,
        "monthly_range_label": monthly_range_label,
        "monthly_till_label": monthly_till_label,
        "upcoming_bills_7": upcoming_bills_7,
        "upcoming_bills_month": upcoming_bills_month,
        "recurring_overview": recurring_overview,
        "notifications": notifications,
        "account_alerts": account_alerts,
    }


async def get_user_notifications(user_id: str):
    uid = ObjectId(user_id)
    accounts_cursor = (
        db.accounts
        .find(
            {"user_id": uid, "deleted_at": None},
            {"name": 1, "bank_name": 1, "balance": 1, "type": 1},
        )
    )
    account_map = {}
    async for acc in accounts_cursor:
        account_map[str(acc["_id"])] = {
            "name": acc.get("name"),
            "bank_name": acc.get("bank_name"),
            "balance": acc.get("balance", 0),
            "type": acc.get("type"),
        }

    _, _, required_by_account = await _fetch_upcoming_bills(uid, account_map)
    return await _persist_notifications(
        uid=uid,
        required_by_account=required_by_account,
        account_map=account_map,
    )


async def _persist_notifications(
    *,
    uid: ObjectId,
    required_by_account: dict,
    account_map: dict,
):
    return await persist_dashboard_notifications(
        uid=uid,
        required_by_account=required_by_account,
        account_map=account_map,
    )


# ======================================================
# RECENT TRANSACTIONS
# ======================================================

async def get_recent_transactions(user_id: str, limit: int = 5):
    uid = ObjectId(user_id)

    account_cursor = db.accounts.find(
        {"user_id": uid, "deleted_at": None},
        {"name": 1},
    )
    account_map = {}
    async for acc in account_cursor:
        account_map[str(acc["_id"])] = acc.get("name")

    cursor = (
        db.transactions
        .find(
            {
                "user_id": uid,
                "deleted_at": None,
                "is_failed": {"$ne": True},
            }
        )
        .sort("created_at", -1)
        .limit(limit * 3)
    )

    raw = [tx async for tx in cursor]
    merged = []
    seen_transfers = set()

    for tx in raw:
        if len(merged) >= limit:
            break

        transfer_id = tx.get("transfer_id")
        if transfer_id:
            key = str(transfer_id)
            if key in seen_transfers:
                continue

            counterpart = await db.transactions.find_one(
                {
                    "user_id": uid,
                    "deleted_at": None,
                    "is_failed": {"$ne": True},
                    "transfer_id": transfer_id,
                    "type": {"$in": ["transfer_in", "transfer_out"]},
                    "_id": {"$ne": tx["_id"]},
                }
            )

            source_tx = tx if tx["type"] == "transfer_out" else counterpart
            target_tx = counterpart if tx["type"] == "transfer_out" else tx

            if source_tx and target_tx:
                merged.append(
                    {
                        "type": "transfer",
                        "amount": tx.get("amount", 0),
                        "description": tx.get("description", "Transfer"),
                        "created_at": tx.get("created_at"),
                        "transfer": {
                            "source": account_map.get(str(source_tx.get("account_id")), "Source"),
                            "target": account_map.get(str(target_tx.get("account_id")), "Target"),
                        },
                    }
                )
                seen_transfers.add(key)
                continue

            account_name = account_map.get(str(tx.get("account_id")), "Account")
            merged.append(
                {
                    "type": "transfer",
                    "amount": tx.get("amount", 0),
                    "description": tx.get("description", "Transfer"),
                    "created_at": tx.get("created_at"),
                    "transfer": {
                        "source": account_name if tx.get("type") == "transfer_out" else "Unknown",
                        "target": account_name if tx.get("type") == "transfer_in" else "Unknown",
                    },
                }
            )
            seen_transfers.add(key)
            continue

        tx["account_name"] = account_map.get(str(tx.get("account_id")))
        merged.append(tx)

    return merged
