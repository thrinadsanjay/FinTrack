from fastapi import Request
from app.db.mongo import db
from datetime import datetime, timezone

async def create_audit_log(
    user: dict,
    action: str,
    request: Request,
    resource: str | None = None,
):
    log = {
        "user_id": user["_id"],
        "user_email": user.get("email"),
        "action": action,
        "resource": resource,
        "ip_address": request.client.host if request.client else None,
        "user_agent": request.headers.get("user-agent"),
        "timestamp": datetime.now(timezone.utc),
    }

    await db.audit_logs.insert_one(log)
