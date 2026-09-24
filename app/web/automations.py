from fastapi import APIRouter, Request

from app.core.guards import login_required
from app.services.dashboard import get_user_notifications
from app.services.rules import catalog, list_rule_runs, list_rules
from app.web.templates import templates

router = APIRouter()


@router.get("/settings/automations")
@login_required
async def automations_page(request: Request):
    user = request.session.get("user")
    rules = await list_rules(user["user_id"])
    runs = await list_rule_runs(user["user_id"], limit=30)
    notifications = await get_user_notifications(user["user_id"])
    return templates.TemplateResponse(
        request=request,
        name="pages/settings/automations.html",
        context={
            "request": request,
            "user": user,
            "active_page": "automations",
            "rules": rules,
            "runs": runs,
            "catalog": catalog(),
            "notifications": notifications,
        },
    )
