from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from app.services.chat_assistant import ai_available, process_chat_message

router = APIRouter(tags=["AI Chat"])


class AiChatPayload(BaseModel):
    message: str = Field(min_length=1, max_length=5000)


@router.post("/ai")
@router.post("/chat/ai")
async def ai_chat(payload: AiChatPayload, request: Request):
    """Compatibility endpoint — prefers AI mode when a key is configured."""
    session_user = request.session.get("user") or {}
    user_id = session_user.get("user_id")
    authenticated = bool(user_id)
    if not authenticated:
        return {
            "reply": "Sign in to use the FinTracker assistant.",
            "ai_available": ai_available(),
        }
    result = await process_chat_message(
        user_id=user_id,
        authenticated=True,
        message=payload.message,
        set_mode="ai" if ai_available() else None,
        user_key=str(user_id),
    )
    return {
        "reply": result.get("reply"),
        "quick_replies": result.get("quick_replies") or [],
        "mode": result.get("mode"),
        "ai_available": result.get("ai_available"),
        "escalate_support": result.get("escalate_support"),
    }
