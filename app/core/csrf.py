import secrets

from fastapi import Request

CSRF_SESSION_KEY = "csrf_token"


class CsrfValidationError(Exception):
    pass


def get_csrf_token(request: Request) -> str:
    token = request.session.get(CSRF_SESSION_KEY)
    if not token:
        token = secrets.token_urlsafe(32)
        request.session[CSRF_SESSION_KEY] = token
    return token


def verify_csrf_token(request: Request, submitted_token: str | None) -> None:
    expected = request.session.get(CSRF_SESSION_KEY)
    if not expected or not submitted_token or submitted_token != expected:
        raise CsrfValidationError("Invalid CSRF token")
