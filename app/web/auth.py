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
from fastapi import APIRouter, Request, Form
from fastapi.responses import RedirectResponse, HTMLResponse
from app.core.config import settings
from app.core.http import get_async_http_client
from app.web.templates import templates
from app.services.auth import (
    authenticate_local_user,
    authenticate_oauth_user,
    reset_user_password,
)

router = APIRouter()


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})


@router.post("/login/local")
async def local_login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
):
    user = await authenticate_local_user(
        username=username,
        password=password,
        request=request,
    )

    if not user:
        return RedirectResponse("/login?error=invalid", status_code=303)

    request.session["user"] = {
        "user_id": str(user["_id"]),
        "auth_provider": "local",
        "username": user["username"],
        "is_admin": user.get("is_admin", False),
    }

    if user.get("must_reset_password"):
        request.session["force_pwd_reset"] = True
        return RedirectResponse("/reset-password", status_code=303)

    return RedirectResponse("/", status_code=303)


@router.get("/login/oauth")
async def login_oauth(request: Request):
    params = {
        "client_id": settings.FT_CLIENT_ID,
        "response_type": "code",
        "scope": "openid profile email",
        "redirect_uri": f"{settings.FT_BASE_URL}/callback",
    }

    url = (
        f"{settings.FT_KEYCLOAK_URL}/realms/{settings.FT_KEYCLOAK_REALM}"
        "/protocol/openid-connect/auth?"
        + urllib.parse.urlencode(params)
    )

    return RedirectResponse(url)


@router.get("/callback")
async def callback(request: Request, code: str):
    token_url = (
        f"{settings.FT_KEYCLOAK_URL}/realms/{settings.FT_KEYCLOAK_REALM}/"
        "protocol/openid-connect/token"
    )

    async with get_async_http_client() as client:
        resp = await client.post(
            token_url,
            data={
                "grant_type": "authorization_code",
                "client_id": settings.FT_CLIENT_ID,
                "code": code,
                "redirect_uri": f"{settings.FT_BASE_URL}/callback",
            },
        )
        token = resp.json()

    user = await authenticate_oauth_user(
        id_token=token["id_token"],
        request=request,
    )

    request.session["user"] = {
        "user_id": str(user["_id"]),
        "auth_provider": "keycloak",
        "username": user.get("username"),
        "email": user.get("email"),
        "is_admin": user.get("is_admin", False),
    }

    return RedirectResponse("/", status_code=303)


@router.get("/reset-password", response_class=HTMLResponse)
async def reset_password_page(request: Request):
    if not request.session.get("force_pwd_reset"):
        return RedirectResponse("/", status_code=303)

    return templates.TemplateResponse(
        "reset_password.html",
        {"request": request},
    )


@router.post("/reset-password")
async def reset_password_submit(
    request: Request,
    password: str = Form(...),
    confirm_password: str = Form(...),
):
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
