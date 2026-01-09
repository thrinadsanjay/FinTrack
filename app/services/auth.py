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
    username = claims.get("preferred_username")

    user = await get_oauth_user_by_sub(oauth_sub)
    if not user:
        user = await create_oauth_user(
            oauth_sub=oauth_sub,
            email=email,
            username=username,
        )
    else:
        await update_oauth_last_login(str(user["_id"]))

    await audit_log(
        action="OAUTH_LOGIN_SUCCESS",
        request=request,
        user={
            "user_id": str(user["_id"]),
            "username": user.get("username"),
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
