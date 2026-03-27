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
from collections.abc import Iterable
from app.core.security import verify_password
from app.core.config import settings
from app.services.users import (
    get_local_user_any,
    update_last_login,
    update_user_password,
    get_oauth_user_by_sub_any,
    create_oauth_user,
    update_oauth_last_login,
    update_oauth_profile,
    get_user_by_id,
    get_user_by_email_any,
    link_oauth_identity_to_user,
)
from app.services.audit import audit_log
from app.services.keycloak import keycloak_service


def _csv_to_set(csv_value: str) -> set[str]:
    return {item.strip() for item in (csv_value or "").split(",") if item.strip()}


def _extract_admin_flag_from_claims(claims: dict) -> bool:
    admin_roles = _csv_to_set(settings.FT_KEYCLOAK_ADMIN_ROLES)
    admin_groups = _csv_to_set(settings.FT_KEYCLOAK_ADMIN_GROUPS)
    if not admin_roles and not admin_groups:
        return False

    found_roles: set[str] = set()
    realm_roles = ((claims.get("realm_access") or {}).get("roles") or [])
    if isinstance(realm_roles, Iterable) and not isinstance(realm_roles, (str, bytes)):
        found_roles.update(str(role).strip() for role in realm_roles if str(role).strip())

    resource_access = claims.get("resource_access") or {}
    if isinstance(resource_access, dict):
        for _, access in resource_access.items():
            roles = (access or {}).get("roles") or []
            if isinstance(roles, Iterable) and not isinstance(roles, (str, bytes)):
                found_roles.update(str(role).strip() for role in roles if str(role).strip())

    found_groups: set[str] = set()
    groups = claims.get("groups") or []
    if isinstance(groups, Iterable) and not isinstance(groups, (str, bytes)):
        for group in groups:
            group_name = str(group).strip()
            if not group_name:
                continue
            found_groups.add(group_name)
            found_groups.add(group_name.split("/")[-1])

    return bool((found_roles & admin_roles) or (found_groups & admin_groups))


# ======================================================
# LOCAL LOGIN
# ======================================================

async def authenticate_local_user(
    *,
    username: str,
    password: str,
    request: Request,
):
    user = await get_local_user_any(username)
    if not user:
        await audit_log(
            action="LOGIN_FAILED",
            request=request,
            user={"username": username, "auth_provider": "local"},
        )
        return None
    if user.get("deleted_at") is not None or not user.get("is_active", True):
        await audit_log(
            action="LOGIN_BLOCKED_DISABLED",
            request=request,
            user={"username": username, "auth_provider": "local"},
        )
        raise HTTPException(status_code=403, detail="Account disabled")
    password_hash = str(user.get("password_hash") or "").strip()
    if not password_hash or not verify_password(password, password_hash):
        await audit_log(
            action="LOGIN_FAILED",
            request=request,
            user={"username": username, "auth_provider": "local"},
            meta={"reason": "invalid_password_or_hash"},
        )
        return None

    await audit_log(
        action="LOGIN_SUCCESS",
        request=request,
        user={
            "user_id": str(user.get("_id") or ""),
            "username": user.get("username") or username,
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

    oauth_sub = str(claims.get("sub") or "").strip()
    if not oauth_sub:
        raise HTTPException(status_code=401, detail="Invalid ID token")

    email = str(claims.get("email") or "").strip() or None
    username = claims.get("preferred_username") or email
    identity_provider = claims.get("identity_provider") or claims.get("idp")
    full_name = (
        claims.get("name")
        or " ".join(
            p for p in [claims.get("given_name"), claims.get("family_name")] if p
        ).strip()
        or username
    )
    claims_is_admin = _extract_admin_flag_from_claims(claims)
    email_verified_raw = claims.get("email_verified")
    email_verified = str(email_verified_raw).strip().lower() in {"true", "1", "yes"}

    user = await get_oauth_user_by_sub_any(oauth_sub)
    linked_existing = False

    if not user and email and email_verified:
        canonical = await get_user_by_email_any(email)
        if canonical:
            user = canonical
            linked_existing = True
            await link_oauth_identity_to_user(
                user_id=str(user["_id"]),
                oauth_sub=oauth_sub,
                identity_provider=identity_provider,
                email=email,
                username=username,
                full_name=full_name,
                is_admin=claims_is_admin,
                sync_admin_from_oauth=(str(user.get("auth_provider") or "") == "keycloak"),
            )

    if not user:
        is_admin = claims_is_admin
        user = await create_oauth_user(
            oauth_sub=oauth_sub,
            email=email,
            username=username,
            full_name=full_name,
            identity_provider=identity_provider,
            is_admin=is_admin,
        )
    else:
        if user.get("deleted_at") is not None or not user.get("is_active", True):
            await audit_log(
                action="OAUTH_LOGIN_BLOCKED_DISABLED",
                request=request,
                user={"oauth_sub": oauth_sub, "auth_provider": "keycloak"},
            )
            raise HTTPException(status_code=403, detail="Account disabled")

        is_admin = bool(user.get("is_admin"))
        if str(user.get("auth_provider") or "") == "keycloak":
            # Keycloak roles/groups are source-of-truth only for external-provider canonical accounts.
            is_admin = claims_is_admin

        await update_oauth_last_login(str(user["_id"]))
        await link_oauth_identity_to_user(
            user_id=str(user["_id"]),
            oauth_sub=oauth_sub,
            identity_provider=identity_provider,
            email=email,
            username=username,
            full_name=full_name,
            is_admin=is_admin,
            sync_admin_from_oauth=(str(user.get("auth_provider") or "") == "keycloak"),
        )
        await update_oauth_profile(
            user_id=str(user["_id"]),
            username=username,
            email=email,
            full_name=full_name,
            identity_provider=identity_provider,
            is_admin=is_admin if str(user.get("auth_provider") or "") == "keycloak" else None,
        )

    user = await get_user_by_id(str(user["_id"])) or user

    if linked_existing:
        await audit_log(
            action="OAUTH_IDENTITY_LINKED",
            request=request,
            user={
                "user_id": str(user["_id"]),
                "username": user.get("username") or user.get("full_name"),
                "auth_provider": user.get("auth_provider") or "local",
            },
            meta={
                "oauth_sub": oauth_sub,
                "identity_provider": identity_provider,
                "email": email,
                "email_verified": email_verified,
            },
        )

    await audit_log(
        action="OAUTH_LOGIN_SUCCESS",
        request=request,
        user={
            "user_id": str(user["_id"]),
            "username": user.get("full_name") or user.get("username"),
            "auth_provider": user.get("auth_provider") or "keycloak",
        },
        meta={
            "email": email,
            "is_admin": bool(user.get("is_admin")),
            "identity_provider": identity_provider,
            "linked_existing": linked_existing,
        },
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
