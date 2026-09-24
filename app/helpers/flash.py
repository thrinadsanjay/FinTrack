from fastapi import Request
from fastapi.responses import RedirectResponse

FLASH_KEY = "ft_flash"


def set_flash(request: Request | None, message: str, *, tone: str = "success") -> None:
    if request is None:
        return
    session = getattr(request, "session", None)
    if session is None:
        return
    text = str(message or "").strip()
    if not text:
        return
    session[FLASH_KEY] = {"message": text[:240], "tone": tone or "success"}


def pop_flash(request: Request | None) -> dict | None:
    if request is None:
        return None
    session = getattr(request, "session", None)
    if session is None:
        return None
    data = session.pop(FLASH_KEY, None)
    if not isinstance(data, dict):
        return None
    message = str(data.get("message") or "").strip()
    if not message:
        return None
    return {"message": message, "tone": str(data.get("tone") or "success")}


def flash_redirect(
    request: Request,
    url: str,
    message: str,
    *,
    tone: str = "success",
    status_code: int = 303,
) -> RedirectResponse:
    set_flash(request, message, tone=tone)
    return RedirectResponse(url, status_code=status_code)
