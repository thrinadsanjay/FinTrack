from starlette.middleware.sessions import SessionMiddleware
from app.core.config import settings


def add_session_middleware(app):
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.FT_SESSION_SECRET,
        https_only=settings.is_production,
        same_site="lax",
        max_age=60 * 60 * 8,
    )
