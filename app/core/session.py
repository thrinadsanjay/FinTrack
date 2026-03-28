from starlette.middleware.sessions import SessionMiddleware
from app.core.config import settings


def add_session_middleware(app):
    session_cookie = "__Host-fintrack_session" if settings.is_production else "fintrack_session"
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.FT_SESSION_SECRET,
        session_cookie=session_cookie,
        https_only=settings.is_production,
        same_site="lax",
        max_age=settings.FT_SESSION_MAX_AGE_SECONDS,
    )
