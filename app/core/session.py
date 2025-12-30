from starlette.middleware.sessions import SessionMiddleware
from app.core.config import settings

def add_session_middleware(app):
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.SESSION_SECRET,
        https_only=False,  # True in prod
        same_site="lax",
    )
