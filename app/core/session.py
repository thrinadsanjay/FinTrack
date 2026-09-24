from starlette.middleware.sessions import SessionMiddleware
from app.core.config import settings


def _session_https_only() -> bool:
    base_url = str(settings.FT_BASE_URL or "").strip().lower()
    return settings.is_production or base_url.startswith("https://")


def add_session_middleware(app):
    session_cookie = "__Host-fintrack_session" if settings.is_production else "fintrack_session"
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.FT_SESSION_SECRET,
        session_cookie=session_cookie,
        https_only=_session_https_only(),
        same_site="lax",
        max_age=settings.FT_SESSION_MAX_AGE_SECONDS,
    )
