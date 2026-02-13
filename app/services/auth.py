"""
Authentication business logic.

Responsibilities:
- Local login validation
- OAuth login handling
- Password reset
- Audit logging

Must NOT:
- Render templates
- Redirect responses
"""

from jose import JWTError
from fastapi import HTTPException, Request
from app.core.security import verify_password
from app.services.users import (
    get_local_user,
    update_last_login,
    update_user_password,
    get_oauth_user_by_sub,
    create_oauth_user,
    update_oauth_last_login,
    update_oauth_profile,
    get_user_by_id,
)
from app.services.audit import audit_log
from app.services.keycloak import keycloak_service


# ======================================================
# LOCAL LOGIN
# ======================================================

async def authenticate_local_user(
    *,
    username: str,
    password: str,
    request: Request,
):
    user = await get_local_user(username)
    if not user or not verify_password(password, user["password_hash"]):
        await audit_log(
            action="LOGIN_FAILED",
            request=request,
            user={"username": username, "auth_provider": "local"},
        )
        return None

    await audit_log(
        action="LOGIN_SUCCESS",
        request=request,
        user={
            "user_id": str(user["_id"]),
            "username": user["username"],
            "auth_provider": "local",
        },
    )

    await update_last_login(user["_id"])
    return user


# ======================================================
# OAUTH LOGIN
# ======================================================

async def authenticate_oauth_user(
    *,
    id_token: str,
    request: Request,
):
    try:
        claims = keycloak_service.verify_id_token(id_token)
    except JWTError as exc:
        await audit_log(
            action="OAUTH_TOKEN_VERIFY_FAILED",
            request=request,
            meta={"error": str(exc)},
        )
        raise HTTPException(status_code=401, detail="Invalid ID token")

    oauth_sub = claims["sub"]
    email = claims.get("email")
    username = claims.get("preferred_username") or email
    full_name = (
        claims.get("name")
        or " ".join(
            p for p in [claims.get("given_name"), claims.get("family_name")] if p
        ).strip()
        or username
    )

    user = await get_oauth_user_by_sub(oauth_sub)
    if not user:
        user = await create_oauth_user(
            oauth_sub=oauth_sub,
            email=email,
            username=username,
            full_name=full_name,
        )
    else:
        await update_oauth_last_login(str(user["_id"]))
        await update_oauth_profile(
            user_id=str(user["_id"]),
            username=username,
            email=email,
            full_name=full_name,
        )
        user["username"] = username
        user["email"] = email
        user["full_name"] = full_name

    await audit_log(
        action="OAUTH_LOGIN_SUCCESS",
        request=request,
        user={
            "user_id": str(user["_id"]),
            "username": user.get("full_name") or user.get("username"),
            "auth_provider": "keycloak",
        },
        meta={"email": email},
    )

    return user


# ======================================================
# PASSWORD RESET
# ======================================================

async def reset_user_password(
    *,
    user: dict,
    password: str,
    request: Request,
):
    await update_user_password(user["user_id"], password)

    await audit_log(
        action="PASSWORD_RESET",
        request=request,
        user=user,
    )


async def change_local_password(
    *,
    user_id: str,
    current_password: str,
    new_password: str,
    request: Request,
):
    user = await get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.get("auth_provider") != "local":
        raise HTTPException(status_code=400, detail="Password managed by external provider")

    if not verify_password(current_password, user.get("password_hash", "")):
        await audit_log(
            action="PASSWORD_CHANGE_FAILED",
            request=request,
            user={
                "user_id": str(user.get("_id")),
                "username": user.get("username"),
                "auth_provider": user.get("auth_provider"),
            },
            meta={"reason": "invalid_current_password"},
        )
        raise HTTPException(status_code=400, detail="Current password is incorrect")

    await update_user_password(str(user["_id"]), new_password)
    await audit_log(
        action="PASSWORD_CHANGED",
        request=request,
        user={
            "user_id": str(user.get("_id")),
            "username": user.get("username"),
            "auth_provider": user.get("auth_provider"),
        },
    )
