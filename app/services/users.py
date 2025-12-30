from bson import ObjectId
from datetime import datetime
from typing import Optional
from app.db.mongo import db
from app.core.security import hash_password
from app.models.user import UserInDB


# ---------- CREATE USERS ----------

async def create_local_user(
    username: str,
    password: str,
    email: str,
    is_admin: bool = False,
    must_reset_password: bool = False,
) -> UserInDB:
    user = UserInDB(
        username=username,
        auth_provider="local",
        password_hash=hash_password(password),
        email=email,
        is_admin=is_admin,
        must_reset_password=must_reset_password,
        created_at=datetime.utcnow(),
    )

    await db.users.insert_one(user.model_dump(exclude={"id"}))
    return user


async def create_oauth_user(
    oauth_sub: str,
    email: str | None,
    username: str | None,
):
    user = {
        "oauth_sub": oauth_sub,
        "email": email,
        "username": username,
        "keycloak_id": oauth_sub,
        "auth_provider": "keycloak",
        "is_admin": False,
        "is_active": True,
        "must_reset_password": False,
        "created_at": datetime.utcnow(),
        "last_login_at": datetime.utcnow(),
    }
    res = await db.users.insert_one(user)
    user["_id"] = res.inserted_id
    return user


# ---------- FIND USERS ----------

async def get_local_user(username: str) -> Optional[dict]:
    return await db.users.find_one({
        "username": username,
        "auth_provider": "local",
        "is_active": True,
    })


async def get_oauth_user_by_sub(oauth_sub: str) -> Optional[dict]:
    return await db.users.find_one({
        "oauth_sub": oauth_sub,
        "auth_provider": "keycloak",
        "is_active": True,
    })

# ---------- UPDATE LAST LOGIN ----------

async def update_last_login(user_id: str):
    await db.users.update_one(
        {"_id": user_id},
        {"$set": {"last_login_at": datetime.utcnow()}}
    )

async def update_oauth_last_login(user_id: str):
    await db.users.update_one(
        {"_id": ObjectId(user_id)},
        {"$set": {"last_login_at": datetime.utcnow()}}
    )

# ---------- LIST USERS ----------
async def list_users() -> list[dict]:
    users = []
    cursor = db.users.find()
    async for user in cursor:
        users.append(user)
    return users

# ---------- DELETE USERS ----------
async def delete_user(user_id: str):
    await db.users.delete_one({"_id": user_id}) 

# ---------- RESET PASSWORD ----------
async def update_user_password(user_id: str, new_password: str):
    result = await db.users.update_one(
        {"_id": ObjectId(user_id)},   # 👈 FIX
        {
            "$set": {
                "password_hash": hash_password(new_password),
                "must_reset_password": False,
                "updated_at": datetime.utcnow(),
            }
        },
    )

    if result.matched_count == 0:
        raise RuntimeError("User not found for password update")