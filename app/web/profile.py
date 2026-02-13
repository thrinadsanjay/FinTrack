from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse
from datetime import datetime, timezone
from bson import ObjectId
from app.core.csrf import verify_csrf_token
from app.core.guards import login_required
from app.db.mongo import db
from app.services.auth import change_local_password
from app.services.dashboard import get_user_notifications
from app.services.users import get_user_by_id
from app.web.templates import templates

router = APIRouter()


def _profile_identity(db_user: dict | None, session_user: dict) -> dict:
    return {
        "username": (db_user or {}).get("username") or session_user.get("username") or "",
        "full_name": (db_user or {}).get("full_name") or (db_user or {}).get("username") or session_user.get("username") or "",
        "email": (db_user or {}).get("email") or session_user.get("email") or "",
    }


@router.get("/profile")
@login_required
async def edit_profile_page(request: Request):
    session_user = request.session.get("user")
    if not session_user:
        return RedirectResponse("/login", status_code=303)

    db_user = await get_user_by_id(session_user["user_id"])
    source = (db_user or {}).get("auth_provider") or session_user.get("auth_provider") or "local"
    is_external = source != "local"
    now = datetime.now(timezone.utc)
    month_start = datetime(now.year, now.month, 1, tzinfo=timezone.utc)
    uid = ObjectId(session_user["user_id"])

    accounts_count = await db.accounts.count_documents({"user_id": uid, "deleted_at": None})
    tx_this_month = await db.transactions.count_documents(
        {
            "user_id": uid,
            "deleted_at": None,
            "created_at": {"$gte": month_start},
            "is_failed": {"$ne": True},
        }
    )
    recurring_active = await db.recurring_deposits.count_documents(
        {
            "user_id": uid,
            "is_active": True,
            "$or": [{"end_date": None}, {"end_date": {"$gte": now}}],
            "ended_at": None,
        }
    )
    unread_count = await db.notifications.count_documents({"user_id": uid, "is_read": False})

    identity = _profile_identity(db_user, session_user)
    profile = {
        "user_id": session_user.get("user_id"),
        "username": identity["username"],
        "full_name": identity["full_name"],
        "email": identity["email"],
        "phone": (db_user or {}).get("phone") or "",
        "auth_provider": source,
        "auth_source_label": "External user" if is_external else "Local user",
        "external_id": (db_user or {}).get("oauth_sub") or (db_user or {}).get("keycloak_id") or "",
        "is_external": is_external,
        "is_admin": bool((db_user or {}).get("is_admin") or session_user.get("is_admin")),
        "is_active": bool((db_user or {}).get("is_active", True)),
        "member_since": (db_user or {}).get("created_at"),
        "last_login_at": (db_user or {}).get("last_login_at"),
        "password_updated_at": (db_user or {}).get("updated_at"),
        "timezone": request.session.get("timezone", "Asia/Kolkata"),
        "theme": request.session.get("theme", "auto"),
        "notifications_enabled": True,
        "stats": {
            "accounts_count": accounts_count,
            "tx_this_month": tx_this_month,
            "recurring_active": recurring_active,
            "unread_notifications": unread_count,
        },
    }

    notifications = await get_user_notifications(session_user["user_id"])

    return templates.TemplateResponse(
        "profile.html",
        {
            "request": request,
            "user": session_user,
            "profile": profile,
            "notifications": notifications,
            "active_page": "profile",
        }
    )


@router.get("/profile/reset-password")
@login_required
async def reset_password_page(request: Request):
    session_user = request.session.get("user")
    if not session_user:
        return RedirectResponse("/login", status_code=303)

    db_user = await get_user_by_id(session_user["user_id"])
    if not db_user or db_user.get("auth_provider") != "local":
        return RedirectResponse("/profile", status_code=303)

    notifications = await get_user_notifications(session_user["user_id"])
    identity = _profile_identity(db_user, session_user)
    return templates.TemplateResponse(
        "profile_reset_password.html",
        {
            "request": request,
            "user": session_user,
            "profile": identity,
            "notifications": notifications,
            "active_page": "profile",
        },
    )


@router.post("/profile/reset-password")
@login_required
async def reset_password_submit(
    request: Request,
    current_password: str = Form(...),
    new_password: str = Form(...),
    confirm_password: str = Form(...),
    csrf_token: str = Form(...),
):
    verify_csrf_token(request, csrf_token)
    session_user = request.session.get("user")
    if not session_user:
        return RedirectResponse("/login", status_code=303)

    db_user = await get_user_by_id(session_user["user_id"])
    if not db_user or db_user.get("auth_provider") != "local":
        return RedirectResponse("/profile", status_code=303)

    notifications = await get_user_notifications(session_user["user_id"])
    identity = _profile_identity(db_user, session_user)

    if new_password != confirm_password:
        return templates.TemplateResponse(
            "profile_reset_password.html",
            {
                "request": request,
                "user": session_user,
                "profile": identity,
                "notifications": notifications,
                "active_page": "profile",
                "error": "New password and confirm password do not match.",
            },
            status_code=400,
        )
    if len(new_password) < 8:
        return templates.TemplateResponse(
            "profile_reset_password.html",
            {
                "request": request,
                "user": session_user,
                "profile": identity,
                "notifications": notifications,
                "active_page": "profile",
                "error": "Password must be at least 8 characters.",
            },
            status_code=400,
        )

    try:
        await change_local_password(
            user_id=session_user["user_id"],
            current_password=current_password,
            new_password=new_password,
            request=request,
        )
    except Exception as exc:
        msg = getattr(exc, "detail", str(exc))
        return templates.TemplateResponse(
            "profile_reset_password.html",
            {
                "request": request,
                "user": session_user,
                "profile": identity,
                "notifications": notifications,
                "active_page": "profile",
                "error": msg,
            },
            status_code=400,
        )

    return RedirectResponse("/profile/reset-password?updated=1", status_code=303)
