from datetime import datetime, timezone, timedelta
from bson import ObjectId

from app.db.mongo import db
from app.services.telegram import send_notification_alert
from app.services.web_push import send_push_notification_alert

TELEGRAM_MIRROR_COOLDOWN_MINUTES = 5


async def upsert_notification(
    *,
    user_id: ObjectId,
    key: str,
    notif_type: str,
    title: str,
    message: str,
    is_read: bool | None = None,
):
    now = datetime.now(timezone.utc)
    existing = await db.notifications.find_one(
        {"user_id": user_id, "key": key},
        {"type": 1, "title": 1, "message": 1, "channels": 1, "updated_at": 1},
    )

    set_payload = {
        "type": notif_type,
        "title": title,
        "message": message,
        "updated_at": now,
    }

    content_changed = (
        not existing
        or existing.get("type") != notif_type
        or existing.get("title") != title
        or existing.get("message") != message
    )

    if is_read is not None:
        set_payload["is_read"] = is_read
    else:
        # Keep read state when content is unchanged; mark unread only for new/updated alerts.
        if content_changed:
            set_payload["is_read"] = False

    await db.notifications.update_one(
        {"user_id": user_id, "key": key},
        {
            "$set": set_payload,
            "$setOnInsert": {"created_at": now},
        },
        upsert=True,
    )

    if content_changed:
        channels = dict((existing or {}).get("channels") or {})
        tg = dict(channels.get("telegram") or {})
        last_sent_at = tg.get("last_sent_at")
        can_send_telegram = True
        if last_sent_at and isinstance(last_sent_at, datetime):
            if (now - last_sent_at) < timedelta(minutes=TELEGRAM_MIRROR_COOLDOWN_MINUTES):
                can_send_telegram = False

        if can_send_telegram:
            sent = await send_notification_alert(
                user_id=user_id,
                key=key,
                notif_type=notif_type,
                title=title,
                message=message,
            )
            telegram_state = {
                "last_attempt_at": now,
                "last_sent_at": now if sent else tg.get("last_sent_at"),
                "status": "sent" if sent else "failed",
                "error": None if sent else "delivery_failed_or_not_eligible",
            }
        else:
            telegram_state = {
                "last_attempt_at": now,
                "last_sent_at": tg.get("last_sent_at"),
                "status": "skipped_cooldown",
                "error": None,
            }

        push_result = await send_push_notification_alert(
            user_id=user_id,
            key=key,
            notif_type=notif_type,
            title=title,
            message=message,
        )
        push_state = {
            "last_attempt_at": now,
            "status": str(push_result.get("status") or "failed"),
            "error": push_result.get("error"),
            "sent": int(push_result.get("sent") or 0),
            "failed": int(push_result.get("failed") or 0),
        }

        channels["telegram"] = telegram_state
        channels["push"] = push_state
        channels["in_app"] = {
            "last_updated_at": now,
            "status": "sent",
        }
        await db.notifications.update_one(
            {"user_id": user_id, "key": key},
            {"$set": {"channels": channels, "updated_at": now}},
            upsert=True,
        )
    else:
        await db.notifications.update_one(
            {"user_id": user_id, "key": key},
            {
                "$set": {
                    "channels.in_app.last_updated_at": now,
                    "channels.in_app.status": "sent",
                    "updated_at": now,
                }
            },
            upsert=True,
        )


async def list_notifications(
    *,
    user_id: ObjectId,
    unread_only: bool = False,
    limit: int = 20,
    since: datetime | None = None,
    include_unread_outside_since: bool = False,
):
    query = {"user_id": user_id}
    if unread_only:
        query["is_read"] = False
    if since is not None and include_unread_outside_since and not unread_only:
        query["$or"] = [
            {"updated_at": {"$gte": since}},
            {"is_read": False},
        ]
    elif since is not None:
        query["updated_at"] = {"$gte": since}

    cursor = (
        db.notifications
        .find(query)
        .sort("updated_at", -1)
        .limit(limit)
    )
    return [n async for n in cursor]


async def mark_all_read(*, user_id: ObjectId | str):
    uid = ObjectId(user_id)
    await db.notifications.update_many(
        {"user_id": uid, "is_read": False},
        {"$set": {"is_read": True, "updated_at": datetime.now(timezone.utc)}},
    )


async def mark_read_by_ids(*, user_id: ObjectId | str, ids: list[str]):
    uid = ObjectId(user_id)
    object_ids = [ObjectId(i) for i in ids if ObjectId.is_valid(i)]
    if not object_ids:
        return
    await db.notifications.update_many(
        {"user_id": uid, "_id": {"$in": object_ids}},
        {"$set": {"is_read": True, "updated_at": datetime.now(timezone.utc)}},
    )
