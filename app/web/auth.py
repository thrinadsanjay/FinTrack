"""
Web auth routes.
Handles UI, forms, sessions, redirects.
Login API:
- local     → username/password form
- keycloak  → redirect to Keycloak OAuth2 with callback
Password reset for local users.

Logout user based on auth provider:
- local     → clear session and redirect to /login
- keycloak  → clear session and redirect to Keycloak logout URL
"""

import urllib.parse
import secrets
from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import RedirectResponse, HTMLResponse
from app.core.config import settings
from app.core.csrf import verify_csrf_token
from app.core.http import get_async_http_client
from app.web.templates import templates
from app.services.auth import (
    authenticate_local_user,
    authenticate_oauth_user,
    reset_user_password,
)
from app.services.users import count_active_users_total
from app.services.metrics import (
    mark_user_logged_in,
    mark_user_logged_out,
    set_total_users,
)

router = APIRouter()


async def _sync_user_metrics_on_login(user_id: str):
    # Keep auth flow resilient: metrics failures must not block login.
    try:
        mark_user_logged_in(user_id)
        set_total_users(await count_active_users_total())
    except Exception:
        pass


async def _sync_user_metrics_on_logout(user_id: str | None):
    try:
        if user_id:
            mark_user_logged_out(user_id)
        set_total_users(await count_active_users_total())
    except Exception:
        pass


def _callback_uri_from_request(request: Request) -> str:
    # Prefer the configured public URL so redirects remain correct behind proxies/TLS termination.
    base_url = (settings.FT_BASE_URL or "").strip().rstrip("/")
    if base_url:
        return f"{base_url}/callback"

    forwarded_proto = request.headers.get("x-forwarded-proto")
    forwarded_host = request.headers.get("x-forwarded-host")
    scheme = forwarded_proto or request.url.scheme
    host = forwarded_host or request.headers.get("host") or request.url.netloc
    return f"{scheme}://{host}/callback"


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})


@router.post("/login/local")
async def local_login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    csrf_token: str = Form(...),
):
    verify_csrf_token(request, csrf_token)
    try:
        user = await authenticate_local_user(
            username=username,
            password=password,
            request=request,
        )
    except HTTPException as exc:
        if exc.status_code == 403:
            return RedirectResponse("/account-disabled", status_code=303)
        raise

    if not user:
        return RedirectResponse("/login?auth=failed&error=invalid", status_code=303)

    request.session["user"] = {
        "user_id": str(user["_id"]),
        "auth_provider": "local",
        "username": user["username"],
        "is_admin": user.get("is_admin", False),
    }
    await _sync_user_metrics_on_login(str(user["_id"]))

    if user.get("must_reset_password"):
        request.session["force_pwd_reset"] = True
        return RedirectResponse("/reset-password", status_code=303)

    return RedirectResponse("/?auth=success", status_code=303)


@router.get("/login/oauth")
async def login_oauth(request: Request):
    oauth_state = secrets.token_urlsafe(32)
    request.session["oauth_state"] = oauth_state
    callback_uri = _callback_uri_from_request(request)
    request.session["oauth_callback_uri"] = callback_uri

    params = {
        "client_id": settings.FT_CLIENT_ID,
        "response_type": "code",
        "scope": "openid profile email",
        "redirect_uri": callback_uri,
        "state": oauth_state,
    }

    url = (
        f"{settings.FT_KEYCLOAK_URL}/realms/{settings.FT_KEYCLOAK_REALM}"
        "/protocol/openid-connect/auth?"
        + urllib.parse.urlencode(params)
    )

    return RedirectResponse(url)


@router.get("/callback")
async def callback(request: Request, code: str, state: str | None = None):
    expected_state = request.session.get("oauth_state")
    if not expected_state or not state or state != expected_state:
        return RedirectResponse("/login?auth=failed&error=oauth_state", status_code=303)
    request.session.pop("oauth_state", None)

    token_url = (
        f"{settings.FT_KEYCLOAK_URL}/realms/{settings.FT_KEYCLOAK_REALM}/"
        "protocol/openid-connect/token"
    )
    callback_uri = request.session.pop("oauth_callback_uri", None) or _callback_uri_from_request(request)

    async with get_async_http_client() as client:
        resp = await client.post(
            token_url,
            data={
                "grant_type": "authorization_code",
                "client_id": settings.FT_CLIENT_ID,
                "code": code,
                "redirect_uri": callback_uri,
            },
        )
        resp.raise_for_status()
        token = resp.json()
        id_token = token.get("id_token")
        if not id_token:
            return RedirectResponse("/login?auth=failed&error=oauth_token", status_code=303)

    try:
        user = await authenticate_oauth_user(
            id_token=id_token,
            request=request,
        )
    except HTTPException as exc:
        if exc.status_code == 403:
            return RedirectResponse("/account-disabled", status_code=303)
        raise

    request.session["user"] = {
        "user_id": str(user["_id"]),
        "auth_provider": "keycloak",
        "username": user.get("full_name") or user.get("username"),
        "full_name": user.get("full_name"),
        "email": user.get("email"),
        "is_admin": user.get("is_admin", False),
    }
    await _sync_user_metrics_on_login(str(user["_id"]))

    return RedirectResponse("/?auth=success", status_code=303)


@router.get("/reset-password", response_class=HTMLResponse)
async def reset_password_page(request: Request):
    if not request.session.get("force_pwd_reset"):
        return RedirectResponse("/", status_code=303)

    return templates.TemplateResponse(
        "reset_password.html",
        {"request": request},
    )


@router.get("/account-disabled", response_class=HTMLResponse)
async def account_disabled_page(request: Request):
    # Ensure blocked users are not kept in active session.
    request.session.clear()
    return templates.TemplateResponse(
        "account_disabled.html",
        {"request": request},
    )


@router.post("/reset-password")
async def reset_password_submit(
    request: Request,
    password: str = Form(...),
    confirm_password: str = Form(...),
    csrf_token: str = Form(...),
):
    verify_csrf_token(request, csrf_token)
    if not request.session.get("force_pwd_reset"):
        return RedirectResponse("/", status_code=303)

    if password != confirm_password:
        return templates.TemplateResponse(
            "reset_password.html",
            {"request": request, "error": "Passwords do not match"},
        )

    user = request.session["user"]
    await reset_user_password(
        user=user,
        password=password,
        request=request,
    )

    request.session.pop("force_pwd_reset", None)
    return RedirectResponse("/", status_code=303)

from fastapi import Request
from fastapi.responses import RedirectResponse
from app.services.audit import audit_log
from app.core.config import settings


@router.get("/logout")
async def logout(request: Request):
    user = request.session.get("user")
    user_id = (user or {}).get("user_id")
    auth_provider = user.get("auth_provider") if user else None

    # ---- Audit logout BEFORE clearing session ----
    await audit_log(
        action="LOGOUT",
        request=request,
        user=user,
        meta={
            "logout_type": "keycloak" if auth_provider == "keycloak" else "local",
        },
    )

    # ---- Clear session ----
    request.session.clear()
    await _sync_user_metrics_on_logout(user_id)

    # ---- Redirect logic ----
    if auth_provider == "keycloak":
        logout_url = (
            f"{settings.FT_KEYCLOAK_URL}/realms/{settings.FT_KEYCLOAK_REALM}"
            "/protocol/openid-connect/logout"
            f"?client_id={settings.FT_CLIENT_ID}"
            f"&post_logout_redirect_uri={settings.FT_BASE_URL}/login"
        )
        return RedirectResponse(logout_url, status_code=302)

    return RedirectResponse("/login", status_code=302)
