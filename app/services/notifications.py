from datetime import datetime, timezone
from bson import ObjectId
from app.db.mongo import db


async def upsert_notification(
    *,
    user_id: ObjectId,
    key: str,
    notif_type: str,
    title: str,
    message: str,
):
    now = datetime.now(timezone.utc)
    await db.notifications.update_one(
        {"user_id": user_id, "key": key},
        {
            "$set": {
                "type": notif_type,
                "title": title,
                "message": message,
                "updated_at": now,
                "is_read": False,
            },
            "$setOnInsert": {
                "created_at": now,
            },
        },
        upsert=True,
    )


async def list_notifications(
    *,
    user_id: ObjectId,
    unread_only: bool = True,
    limit: int = 20,
):
    query = {"user_id": user_id}
    if unread_only:
        query["is_read"] = False

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
    object_ids = [ObjectId(i) for i in ids]
    await db.notifications.update_many(
        {"user_id": uid, "_id": {"$in": object_ids}},
        {"$set": {"is_read": True, "updated_at": datetime.now(timezone.utc)}},
    )
