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
import re

from app.db.mongo import db
from app.core.security import hash_password
from app.services.audit import audit_log


# ======================================================
# HELPERS
# ======================================================

def _now():
    return datetime.now(timezone.utc)


def _email_match_query(email: str) -> dict:
    value = str(email or "").strip()
    if not value:
        return {"email": ""}
    return {"email": {"$regex": f"^{re.escape(value)}$", "$options": "i"}}


# ======================================================
# CREATE USERS
# ======================================================

async def create_local_user(
    *,
    username: str,
    password: str,
    email: str | None = None,
    first_name: str | None = None,
    last_name: str | None = None,
    phone: str | None = None,
    is_admin: bool = False,
    must_reset_password: bool = False,
):
    first = str(first_name or "").strip()
    last = str(last_name or "").strip()
    email_value = str(email or "").strip()
    phone_value = str(phone or "").strip()
    user = {
        "username": username,
        "auth_provider": "local",
        "password_hash": hash_password(password),
        "first_name": first,
        "last_name": last,
        "full_name": compose_full_name(first, last),
        "is_admin": is_admin,
        "is_active": True,
        "must_reset_password": must_reset_password,
        "created_at": _now(),
        "last_login_at": None,
        "deleted_at": None,
    }
    if email_value:
        user["email"] = email_value
    if phone_value:
        user["phone"] = phone_value

    result = await db.users.insert_one(user)
    user["_id"] = result.inserted_id

    await audit_log(
        action="USER_CREATED_LOCAL",
        user={"user_id": str(result.inserted_id), "username": username},
        meta={"email": email_value or None},
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
        "linked_oauth_subs": [oauth_sub],
        "google_id": oauth_sub,
        "auth_provider": "google",
        "username": username,
        "full_name": full_name,
        "identity_provider": identity_provider,
        "linked_identity_providers": [identity_provider] if identity_provider else [],
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
    value = str(username or "").strip()
    if not value:
        return None
    return await db.users.find_one({
        "auth_provider": "local",
        "$or": [
            {"username": value},
            _email_match_query(value),
        ],
    })


async def get_oauth_user_by_sub(oauth_sub: str) -> Optional[dict]:
    value = str(oauth_sub or "").strip()
    return await db.users.find_one({
        "$or": [
            {"oauth_sub": value},
            {"linked_oauth_subs": value},
        ],
        "is_active": True,
        "deleted_at": None,
    })


async def get_oauth_user_by_sub_any(oauth_sub: str) -> Optional[dict]:
    value = str(oauth_sub or "").strip()
    return await db.users.find_one({
        "$or": [
            {"oauth_sub": value},
            {"linked_oauth_subs": value},
        ],
    })


async def get_user_by_email_any(email: str) -> Optional[dict]:
    query = _email_match_query(email)
    return await db.users.find_one({
        **query,
        "deleted_at": None,
    })


async def get_user_by_username_any(username: str) -> Optional[dict]:
    value = str(username or "").strip()
    if not value:
        return None
    return await db.users.find_one({
        "deleted_at": None,
        "username": {"$regex": f"^{re.escape(value)}$", "$options": "i"},
    })


async def get_user_by_mobile_any(mobile: str) -> Optional[dict]:
    value = str(mobile or "").strip()
    if not value:
        return None
    return await db.users.find_one({
        "$or": [
            {"telegram_mobile": value},
            {"phone": value},
        ],
        "deleted_at": None,
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

    update_op: dict = {"$set": update_fields}
    if identity_provider:
        update_op["$addToSet"] = {"linked_identity_providers": identity_provider}

    await db.users.update_one(
        {"_id": ObjectId(user_id), "deleted_at": None},
        update_op,
    )


async def link_oauth_identity_to_user(
    *,
    user_id: str,
    oauth_sub: str,
    identity_provider: str | None,
    email: str | None,
    username: str | None,
    full_name: str | None,
    is_admin: bool | None = None,
    sync_admin_from_oauth: bool = False,
    auth_provider: str | None = None,
) -> None:
    update_set = {
        "oauth_sub": oauth_sub,
        "google_id": oauth_sub,
        "updated_at": _now(),
    }
    if email:
        update_set["email"] = email
    if username:
        update_set["username"] = username
    if full_name:
        update_set["full_name"] = full_name
    if sync_admin_from_oauth and is_admin is not None:
        update_set["is_admin"] = bool(is_admin)
    if auth_provider:
        update_set["auth_provider"] = auth_provider

    update_op: dict = {
        "$set": update_set,
        "$addToSet": {
            "linked_oauth_subs": oauth_sub,
        },
    }
    if identity_provider:
        update_op["$addToSet"]["linked_identity_providers"] = identity_provider

    await db.users.update_one(
        {"_id": ObjectId(user_id), "deleted_at": None},
        update_op,
    )


# ======================================================
# PASSWORD RESET
# ======================================================

def split_person_name(user_doc: dict | None) -> tuple[str, str]:
    doc = user_doc or {}
    first = str(doc.get("first_name") or "").strip()
    last = str(doc.get("last_name") or "").strip()
    if first or last:
        return first, last
    full = str(doc.get("full_name") or "").strip()
    if not full:
        return "", ""
    parts = full.split(None, 1)
    return parts[0], (parts[1] if len(parts) > 1 else "")


def compose_full_name(first_name: str | None, last_name: str | None) -> str:
    return " ".join(part for part in [str(first_name or "").strip(), str(last_name or "").strip()] if part)


async def get_tx_preferred_view(user_id: str) -> str:
    if not ObjectId.is_valid(user_id):
        return "list"
    doc = await db.users.find_one({"_id": ObjectId(user_id), "deleted_at": None}, {"tx_preferred_view": 1})
    view = str((doc or {}).get("tx_preferred_view") or "list").strip().lower()
    return view if view in {"list", "board"} else "list"


async def set_tx_preferred_view(user_id: str, view: str) -> str:
    chosen = str(view or "").strip().lower()
    if chosen not in {"list", "board"}:
        raise RuntimeError("Choose List or Board.")
    if not ObjectId.is_valid(user_id):
        raise RuntimeError("Invalid user.")
    await db.users.update_one(
        {"_id": ObjectId(user_id), "deleted_at": None},
        {"$set": {"tx_preferred_view": chosen, "updated_at": _now()}},
    )
    return chosen


async def update_user_account(
    *,
    user_id: str,
    first_name: str | None = None,
    last_name: str | None = None,
    email: str | None = None,
    phone: str | None = None,
):
    if not ObjectId.is_valid(user_id):
        raise RuntimeError("Invalid user.")

    first = str(first_name or "").strip()
    last = str(last_name or "").strip()
    email_value = str(email or "").strip()
    phone_value = str(phone or "").strip()
    update_set: dict = {
        "first_name": first,
        "last_name": last,
        "full_name": compose_full_name(first, last),
        "updated_at": _now(),
    }
    update_unset: dict = {}
    if email_value:
        update_set["email"] = email_value
    else:
        update_unset["email"] = ""
    if phone_value:
        update_set["phone"] = phone_value
    else:
        update_unset["phone"] = ""

    update_op: dict = {"$set": update_set}
    if update_unset:
        update_op["$unset"] = update_unset

    result = await db.users.update_one(
        {"_id": ObjectId(user_id), "deleted_at": None},
        update_op,
    )
    if result.matched_count == 0:
        raise RuntimeError("User not found.")

    await audit_log(
        action="USER_ACCOUNT_UPDATED",
        user={"user_id": user_id},
        meta={
            "first_name": first,
            "last_name": last,
            "email": email_value or None,
            "phone": phone_value or None,
        },
    )


async def update_user_password(user_id: str, new_password: str, *, must_reset_password: bool = False):
    result = await db.users.update_one(
        {"_id": ObjectId(user_id), "deleted_at": None},
        {
            "$set": {
                "password_hash": hash_password(new_password),
                "must_reset_password": must_reset_password,
                "updated_at": _now(),
            }
        },
    )

    if result.matched_count == 0:
        raise RuntimeError("User not found for password update")

    await audit_log(
        action="USER_PASSWORD_RESET",
        user={"user_id": user_id},
        meta={"must_reset_password": must_reset_password},
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
