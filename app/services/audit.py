from datetime import datetime
from bson import ObjectId
from app.db.mongo import db

async def audit_log(
    *,
    action: str,
    request,
    user: dict | None = None,
    meta: dict | None = None,
):
    await db.audit_logs.insert_one({
        "user_id": ObjectId(user["user_id"])
        if user and user.get("user_id")
        else None,
        "username": user.get("username") if user else None,
        "auth_provider": user.get("auth_provider") if user else None,
        "action": action,
        "ip": request.client.host if request.client else None,
        "user_agent": request.headers.get("user-agent"),
        "meta": meta or {},
        "timestamp": datetime.utcnow(),
    })