from datetime import datetime, timezone, timedelta
from bson import ObjectId

from app.db.mongo import db
from app.helpers.dashboard_time import start_of_today_utc, app_now
from app.services.notifications import upsert_notification, list_notifications


async def persist_dashboard_notifications(
    *,
    uid: ObjectId,
    required_by_account: dict,
    account_map: dict,
):
    active_low_balance_keys = set()

    for account_id, required in required_by_account.items():
        account_info = account_map.get(account_id, {})
        balance_value = account_info.get("balance", 0)
        if balance_value < required:
            key = f"low_balance:{account_id}"
            active_low_balance_keys.add(key)
            await upsert_notification(
                user_id=uid,
                key=key,
                notif_type="warning",
                title="Low balance for upcoming bills",
                message=(
                    f"{account_info.get('name', 'Account')} needs ₹ {required} "
                    f"for pending recurring bills this month, but has ₹ {balance_value}."
                ),
            )

    active_balance_threshold_keys = set()
    for account_id, account_info in account_map.items():
        if account_info.get("type") == "credit_card":
            continue
        balance_value = account_info.get("balance", 0)
        notif_type = None
        title = None
        if balance_value <= 500:
            notif_type = "critical"
            title = "Critical low balance"
        elif balance_value <= 1000:
            notif_type = "warning"
            title = "Low balance warning"

        if not notif_type:
            continue

        key = f"balance_threshold:{account_id}"
        active_balance_threshold_keys.add(key)
        await upsert_notification(
            user_id=uid,
            key=key,
            notif_type=notif_type,
            title=title,
            message=(
                f"{account_info.get('name', 'Account')} has ₹ {balance_value}. "
                "Try adding funds soon."
            ),
        )

    today_start = start_of_today_utc()
    tomorrow_start = today_start + timedelta(days=1)
    recurring_today_cursor = db.recurring_deposits.find(
        {
            "user_id": uid,
            "is_active": True,
            "ended_at": None,
            "$and": [
                {"$or": [{"end_date": None}, {"end_date": {"$gte": today_start}}]},
                {
                    "$or": [
                        {"next_run": {"$gte": today_start, "$lt": tomorrow_start}},
                        {"last_run": {"$gte": today_start, "$lt": tomorrow_start}},
                    ]
                },
            ],
        }
    ).sort("next_run", 1)

    active_scheduled_today_keys = set()
    today_key = app_now().strftime("%Y-%m-%d")

    async for rule in recurring_today_cursor:
        rule_id = str(rule.get("_id"))
        account_id = str(rule.get("account_id"))
        account_name = account_map.get(account_id, {}).get("name", "Account")
        key = f"scheduled_today:{rule_id}:{today_key}"
        active_scheduled_today_keys.add(key)
        await upsert_notification(
            user_id=uid,
            key=key,
            notif_type="info",
            title="Payment due today",
            message=(
                f"{rule.get('description', 'Recurring transaction')} for ₹ {rule.get('amount', 0)} "
                f"is scheduled today in {account_name}."
            ),
        )

    stale_low_balance_query = {"user_id": uid, "key": {"$regex": r"^low_balance:"}}
    if active_low_balance_keys:
        stale_low_balance_query["key"]["$nin"] = list(active_low_balance_keys)
    await db.notifications.delete_many(stale_low_balance_query)

    stale_balance_threshold_query = {"user_id": uid, "key": {"$regex": r"^balance_threshold:"}}
    if active_balance_threshold_keys:
        stale_balance_threshold_query["key"]["$nin"] = list(active_balance_threshold_keys)
    await db.notifications.delete_many(stale_balance_threshold_query)

    stale_scheduled_today_query = {"user_id": uid, "key": {"$regex": r"^scheduled_today:"}}
    if active_scheduled_today_keys:
        stale_scheduled_today_query["key"]["$nin"] = list(active_scheduled_today_keys)
    await db.notifications.delete_many(stale_scheduled_today_query)

    cutoff = datetime.now(timezone.utc) - timedelta(days=10)
    notifications = await list_notifications(
        user_id=uid,
        unread_only=False,
        limit=500,
        since=cutoff,
        include_unread_outside_since=True,
    )
    for n in notifications:
        n["id"] = str(n["_id"])
    return notifications
