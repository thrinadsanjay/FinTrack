from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.core.csrf import verify_csrf_token
from app.routers.deps import get_current_user_valid as get_current_user
from app.services.ai_finance import ask_fintracker, explain_insight, monthly_review, recommendations_for_user
from app.services.chat_assistant import ai_available

router = APIRouter()


class AskPayload(BaseModel):
    question: str = Field(min_length=1, max_length=2000)


class ExplainPayload(BaseModel):
    key: str = ""
    title: str = Field(min_length=1, max_length=300)
    detail: str = ""
    category: str = ""


def _uid(user: dict) -> str:
    user_id = user.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid session")
    return str(user_id)


@router.get("/status")
async def ai_status(user=Depends(get_current_user)):
    return {"ai_available": ai_available()}


@router.post("/ask")
async def ask(payload: AskPayload, request: Request, user=Depends(get_current_user)):
    verify_csrf_token(request, request.headers.get("X-CSRF-Token"))
    return await ask_fintracker(user_id=_uid(user), question=payload.question)


@router.post("/explain")
async def explain(payload: ExplainPayload, request: Request, user=Depends(get_current_user)):
    verify_csrf_token(request, request.headers.get("X-CSRF-Token"))
    return await explain_insight(
        user_id=_uid(user),
        insight={"key": payload.key, "title": payload.title, "detail": payload.detail, "category": payload.category},
    )


@router.get("/review")
async def review(user=Depends(get_current_user)):
    return await monthly_review(user_id=_uid(user))


@router.get("/recommendations")
async def recommendations(user=Depends(get_current_user)):
    return {"recommendations": await recommendations_for_user(_uid(user))}
