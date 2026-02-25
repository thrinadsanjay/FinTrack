"""
User management service.

Responsibilities:
- Create local and OAuth users
- Fetch users
- Update login metadata
- Reset passwords
- Soft delete users
- Emit audit logs

Must NOT:
- Handle sessions
- Render templates
- Perform auth redirects
"""

from bson import ObjectId
from datetime import datetime, timezone
from typing import Optional

from app.db.mongo import db
from app.core.security import hash_password
from app.services.audit import audit_log


# ======================================================
# HELPERS
# ======================================================

def _now():
    return datetime.now(timezone.utc)


# ======================================================
# CREATE USERS
# ======================================================

async def create_local_user(
    *,
    username: str,
    password: str,
    email: str,
    is_admin: bool = False,
    must_reset_password: bool = False,
):
    user = {
        "username": username,
        "auth_provider": "local",
        "password_hash": hash_password(password),
        "email": email,
        "is_admin": is_admin,
        "is_active": True,
        "must_reset_password": must_reset_password,
        "created_at": _now(),
        "last_login_at": None,
        "deleted_at": None,
    }

    result = await db.users.insert_one(user)
    user["_id"] = result.inserted_id

    await audit_log(
        action="USER_CREATED_LOCAL",
        user={"user_id": str(result.inserted_id), "username": username},
        meta={"email": email},
    )

    return user


async def create_oauth_user(
    *,
    oauth_sub: str,
    email: str | None,
    username: str | None,
    full_name: str | None = None,
    identity_provider: str | None = None,
    is_admin: bool = False,
):
    user = {
        "oauth_sub": oauth_sub,
        "keycloak_id": oauth_sub,
        "auth_provider": "keycloak",
        "username": username,
        "full_name": full_name,
        "identity_provider": identity_provider,
        "email": email,
        "is_admin": is_admin,
        "is_active": True,
        "must_reset_password": False,
        "created_at": _now(),
        "last_login_at": _now(),
        "deleted_at": None,
    }

    result = await db.users.insert_one(user)
    user["_id"] = result.inserted_id

    await audit_log(
        action="USER_CREATED_OAUTH",
        user={"user_id": str(result.inserted_id), "username": username},
        meta={"email": email},
    )

    return user


# ======================================================
# FETCH USERS
# ======================================================

async def get_local_user(username: str) -> Optional[dict]:
    return await db.users.find_one({
        "username": username,
        "auth_provider": "local",
        "is_active": True,
        "deleted_at": None,
    })


async def get_local_user_any(username: str) -> Optional[dict]:
    return await db.users.find_one({
        "username": username,
        "auth_provider": "local",
    })


async def get_oauth_user_by_sub(oauth_sub: str) -> Optional[dict]:
    return await db.users.find_one({
        "oauth_sub": oauth_sub,
        "auth_provider": "keycloak",
        "is_active": True,
        "deleted_at": None,
    })


async def get_oauth_user_by_sub_any(oauth_sub: str) -> Optional[dict]:
    return await db.users.find_one({
        "oauth_sub": oauth_sub,
        "auth_provider": "keycloak",
    })


async def list_users() -> list[dict]:
    cursor = db.users.find({"deleted_at": None})
    return [user async for user in cursor]


async def count_active_users_total() -> int:
    return await db.users.count_documents(
        {
            "deleted_at": None,
            "is_active": True,
        }
    )


async def get_user_by_id(user_id: str) -> Optional[dict]:
    if not ObjectId.is_valid(user_id):
        return None
    return await db.users.find_one(
        {
            "_id": ObjectId(user_id),
            "is_active": True,
            "deleted_at": None,
        }
    )


# ======================================================
# LOGIN METADATA
# ======================================================

async def update_last_login(user_id: str):
    await db.users.update_one(
        {"_id": ObjectId(user_id)},
        {"$set": {"last_login_at": _now()}}
    )


async def update_oauth_last_login(user_id: str):
    await update_last_login(user_id)


async def update_oauth_profile(
    *,
    user_id: str,
    username: str | None,
    email: str | None,
    full_name: str | None,
    identity_provider: str | None = None,
    is_admin: bool | None = None,
):
    update_fields = {
        "username": username,
        "email": email,
        "full_name": full_name,
        "identity_provider": identity_provider,
        "updated_at": _now(),
    }
    if is_admin is not None:
        update_fields["is_admin"] = is_admin

    await db.users.update_one(
        {"_id": ObjectId(user_id), "auth_provider": "keycloak", "deleted_at": None},
        {"$set": update_fields},
    )


# ======================================================
# PASSWORD RESET
# ======================================================

async def update_user_password(user_id: str, new_password: str):
    result = await db.users.update_one(
        {"_id": ObjectId(user_id), "deleted_at": None},
        {
            "$set": {
                "password_hash": hash_password(new_password),
                "must_reset_password": False,
                "updated_at": _now(),
            }
        },
    )

    if result.matched_count == 0:
        raise RuntimeError("User not found for password update")

    await audit_log(
        action="USER_PASSWORD_RESET",
        user={"user_id": user_id},
    )


# ======================================================
# SOFT DELETE USER
# ======================================================

async def delete_user(user_id: str):
    result = await db.users.update_one(
        {"_id": ObjectId(user_id), "deleted_at": None},
        {"$set": {"deleted_at": _now(), "is_active": False}},
    )

    if result.matched_count == 0:
        raise RuntimeError("User not found or already deleted")

    await audit_log(
        action="USER_DELETED",
        user={"user_id": user_id},
    )
