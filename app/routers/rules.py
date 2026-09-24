from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.core.csrf import verify_csrf_token
from app.routers.deps import get_current_user_valid as get_current_user
from app.services import rules as rules_service

router = APIRouter()


class RulePayload(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    enabled: bool = True
    priority: int = 0
    conditions: list[dict] = Field(default_factory=list)
    actions: list[dict] = Field(default_factory=list)


class TogglePayload(BaseModel):
    enabled: bool


def _uid(user: dict) -> str:
    user_id = user.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid session")
    return str(user_id)


@router.get("")
async def list_rules(user=Depends(get_current_user)):
    return {"rules": await rules_service.list_rules(_uid(user)), "catalog": rules_service.catalog()}


@router.get("/runs")
async def list_runs(rule_id: str | None = None, user=Depends(get_current_user)):
    return {"runs": await rules_service.list_rule_runs(_uid(user), rule_id=rule_id)}


@router.post("")
async def create_rule(payload: RulePayload, request: Request, user=Depends(get_current_user)):
    verify_csrf_token(request, request.headers.get("X-CSRF-Token"))
    try:
        rule = await rules_service.create_rule(_uid(user), payload.model_dump(), request=request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"rule": rule}


@router.patch("/{rule_id}")
async def update_rule(rule_id: str, payload: RulePayload, request: Request, user=Depends(get_current_user)):
    verify_csrf_token(request, request.headers.get("X-CSRF-Token"))
    try:
        rule = await rules_service.update_rule(_uid(user), rule_id, payload.model_dump(), request=request)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"rule": rule}


@router.post("/{rule_id}/toggle")
async def toggle_rule(rule_id: str, payload: TogglePayload, request: Request, user=Depends(get_current_user)):
    verify_csrf_token(request, request.headers.get("X-CSRF-Token"))
    rule = await rules_service.set_rule_enabled(_uid(user), rule_id, payload.enabled, request=request)
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    return {"rule": rule}


@router.delete("/{rule_id}")
async def delete_rule(rule_id: str, request: Request, user=Depends(get_current_user)):
    verify_csrf_token(request, request.headers.get("X-CSRF-Token"))
    ok = await rules_service.delete_rule(_uid(user), rule_id, request=request)
    if not ok:
        raise HTTPException(status_code=404, detail="Rule not found")
    return {"ok": True}
