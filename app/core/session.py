from starlette.middleware.sessions import SessionMiddleware
from app.core.config import settings

def add_session_middleware(app):
    app.add_middleware(
        SessionMiddleware,
<<<<<<< HEAD
        secret_key=settings.FT_SESSION_SECRET,
=======
        secret_key=settings.SESSION_SECRET,
>>>>>>> 8266f8b43a3760f7716449025947c72b4e670271
        https_only=False,  # True in prod
        same_site="lax",
    )
