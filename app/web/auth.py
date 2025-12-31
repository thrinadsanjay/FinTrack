import httpx
import urllib.parse
from fastapi import APIRouter, Request, Form
from fastapi.responses import RedirectResponse, HTMLResponse
from app.core.config import settings
from app.core.security import verify_password
from app.core.http import get_async_http_client
from app.web.templates import templates
from app.services.users import get_local_user, update_last_login, update_user_password, update_oauth_last_login, get_oauth_user_by_sub, create_oauth_user
from app.services.audit import audit_log
# from app.services.keycloak import verify_id_token, decode_id_token # Disable in dev mode
# from app.services.keycloak import decode_id_token # Disable in Prod mode
from app.services.keycloak import keycloak_service
from jose import JWTError

router = APIRouter()

@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse(
        "login.html",
        {"request": request},
    )

@router.post("/login/local")
async def local_login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
):
    user = await get_local_user(username)
    if not user or not verify_password(password, user["password_hash"]):
        await audit_log(
            action="LOGIN_FAILED",
            request=request,
            user={"username": username, "auth_provider": "local"},
        )
        return RedirectResponse("/login?error=invalid", status_code=303)

    request.session["user"] = {
        "user_id": str(user["_id"]),
        "auth_provider": "local",
        "username": user["username"],
        "is_admin": user.get("is_admin", False),
    }
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

    if user.get("must_reset_password"):
        request.session["force_pwd_reset"] = True
        await audit_log(
            action="REQUIRE_PASSWORD_RESET",
            request=request,
            user=request.session["user"],
        )
        return RedirectResponse("/reset-password", status_code=303)   

    return RedirectResponse("/", status_code=303)


@router.get("/login/oauth")
async def login_oauth(request: Request):
    params = {
        "client_id": settings.KEYCLOAK_CLIENT_ID,
        "response_type": "code",
        "scope": "openid profile email",
        "redirect_uri": f"{settings.APP_BASE_URL}/callback",
    }

    url = (
        f"{settings.KEYCLOAK_URL}/realms/{settings.KEYCLOAK_REALM}"
        "/protocol/openid-connect/auth?"
        + urllib.parse.urlencode(params)
    )

    return RedirectResponse(url)

@router.get("/callback")
async def callback(request: Request, code: str):
    token_url = (
        f"{settings.KEYCLOAK_URL}/realms/{settings.KEYCLOAK_REALM}/"
        "protocol/openid-connect/token"
    )

    async with get_async_http_client() as client:
        resp = await client.post(
            token_url,
            data={
                "grant_type": "authorization_code",
                "client_id": settings.KEYCLOAK_CLIENT_ID,
                #"client_secret": settings.KEYCLOAK_CLIENT_SECRET,
                "code": code,
               # "redirect_uri": "http://localhost:8000/callback",
               "redirect_uri": f"{settings.APP_BASE_URL}/callback",
            },
        )
        token = resp.json()

    id_token = token["id_token"]

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

    # ✅ Store minimal session data
    request.session["user"] = {
        "user_id": str(user["_id"]),
        "auth_provider": "keycloak",
        "username": user.get("username"),
        "email": user.get("email"),
        "is_admin": user.get("is_admin", False),
    }

    await audit_log(
        action="OAUTH_LOGIN_SUCCESS",
        request=request,
        user={
            "user_id": str(user["_id"]),
            "username": user.get("username"),
            "auth_provider": "keycloak",
        },
        meta={"email": user.get("email")},
    )

    return RedirectResponse("/", status_code=303)

@router.get("/logout")
async def logout(request: Request):
    """
    Logout user based on auth provider:
    - local     → clear session and go to /login
    - keycloak  → clear session and redirect to Keycloak logout
    """

    # ---- Capture data BEFORE clearing session ----
    auth_provider = request.session.get("auth_provider")
    user = request.session.get("user")

    audit_user = None
    audit_meta = {}

    if user:
        audit_user = {
            "user_id": str(user.get("_id") or user.get("user_id")),
            "username": user.get("username"),
            "auth_provider": auth_provider,
        }
        audit_meta = {
            "email": user.get("email"),
            "logout_type": "global_idp" if auth_provider == "keycloak" else "local_only",
        }

    # ---- Audit logout (common for all providers) ----
    await audit_log(
        action="LOGOUT",
        request=request,
        user=audit_user,
        meta=audit_meta,
    )

    # ---- Clear session ----
    request.session.clear()

    # ---- Redirect logic ----
    if auth_provider == "local":
        return RedirectResponse("/login", status_code=302)

    if auth_provider == "keycloak":
        logout_url = (
            f"{settings.KEYCLOAK_URL}/realms/{settings.KEYCLOAK_REALM}"
            "/protocol/openid-connect/logout"
            f"?client_id={settings.KEYCLOAK_CLIENT_ID}"
            f"&post_logout_redirect_uri={settings.APP_BASE_URL}/login"
        )
        return RedirectResponse(logout_url, status_code=302)

    # Fallback
    return RedirectResponse("/login", status_code=302)


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
        return RedirectResponse("/", status_code=301)

    if password != confirm_password:
        return templates.TemplateResponse(
            "reset_password.html",
            {
                "request": request,
                "error": "Passwords do not match",
            },
            await audit_log(
                action="PASSWORD_RESET_FAILED",
                request=request,
                user=request.session.get("user"),
            )
        )

    user = request.session.get("user")
    await audit_log(
        action="PASSWORD_RESET",
        request=request,
        user=request.session["user"],
    )
    await update_user_password(user["user_id"], password)

    # 🔑 IMPORTANT: restore session user
    request.session["user"] = {
        "user_id": user["user_id"],
        "auth_provider": user["auth_provider"],
        "username": user.get("username"),
        "is_admin": user.get("is_admin", False),
    }

    # Clear reset flag
    request.session.pop("force_pwd_reset", None)

    return RedirectResponse("/", status_code=303)