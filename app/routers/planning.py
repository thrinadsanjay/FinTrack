"""JSON APIs for Phase 1 planning and intelligence."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.encoders import jsonable_encoder

from app.core.errors import AppError
from app.routers.deps import get_current_user
from app.schemas.planning import GoalCreate, GoalLinks, GoalUpdate
from app.services.goal_links import list_link_candidates, set_goal_links
from app.services.goals import create_goal, list_goals, update_goal
from app.services.planning import build_planning_bundle, overlay_from_bundle

router = APIRouter()


def _user_id(user: dict) -> str:
    user_id = user.get("user_id") or user.get("_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid session user")
    return str(user_id)


def _ok(payload):
    return jsonable_encoder(payload, custom_encoder={date: lambda value: value.isoformat()})


def _forecast_public(forecast: dict) -> dict:
    daily = []
    for row in (forecast or {}).get("daily") or []:
        daily.append(
            {
                "date": row.get("date"),
                "balance": row.get("balance"),
                "inflow": row.get("inflow"),
                "outflow": row.get("outflow"),
                "event_count": len(row.get("events") or []),
            }
        )
    return {
        "today_balance": (forecast or {}).get("today_balance"),
        "horizons": (forecast or {}).get("horizons"),
        "lowest_balance": (forecast or {}).get("lowest_balance"),
        "lowest_date": (forecast or {}).get("lowest_date"),
        "contributing_events": (forecast or {}).get("contributing_events") or [],
        "daily": daily,
    }


@router.get("/dashboard")
async def planning_dashboard(user=Depends(get_current_user)):
    bundle = await build_planning_bundle(_user_id(user), persist=True)
    return _ok(overlay_from_bundle(bundle))


@router.get("/health")
async def planning_health(user=Depends(get_current_user)):
    bundle = await build_planning_bundle(_user_id(user), persist=True)
    return _ok(
        {
            "health": bundle.get("health"),
            "history": bundle.get("health_history"),
            "disclaimer": bundle.get("disclaimer"),
        }
    )


@router.get("/forecast")
async def planning_forecast(user=Depends(get_current_user)):
    bundle = await build_planning_bundle(_user_id(user), persist=True)
    return _ok({"forecast": _forecast_public(bundle.get("forecast") or {}), "cash": bundle.get("cash")})


@router.get("/safe-to-spend")
async def planning_safe_to_spend(user=Depends(get_current_user)):
    bundle = await build_planning_bundle(_user_id(user), persist=True)
    return _ok({"safe_to_spend": bundle.get("safe_to_spend")})


@router.get("/net-worth")
async def planning_net_worth(user=Depends(get_current_user)):
    bundle = await build_planning_bundle(_user_id(user), persist=True)
    return _ok({"net_worth": bundle.get("net_worth"), "history": bundle.get("net_worth_history")})


@router.get("/credit-cards")
async def planning_credit_cards(user=Depends(get_current_user)):
    bundle = await build_planning_bundle(_user_id(user), persist=False)
    return _ok({"credit_cards": bundle.get("credit_cards")})


@router.get("/calendar")
async def planning_calendar(
    year: int | None = Query(default=None),
    month: int | None = Query(default=None),
    day: date | None = Query(default=None),
    user=Depends(get_current_user),
):
    bundle = await build_planning_bundle(
        _user_id(user),
        persist=False,
        year=year,
        month=month,
        day=day,
    )
    calendar = dict(bundle.get("calendar") or {})
    calendar.pop("events", None)
    return _ok({"calendar": calendar, "cash": bundle.get("cash")})


@router.get("/insights")
async def planning_insights(user=Depends(get_current_user)):
    bundle = await build_planning_bundle(_user_id(user), persist=True)
    return _ok({"insights": bundle.get("insights")})


@router.get("/goals")
async def planning_goals(user=Depends(get_current_user)):
    bundle = await build_planning_bundle(_user_id(user), persist=False)
    return _ok({"goals": bundle.get("goals")})


@router.post("/goals")
async def planning_create_goal(payload: GoalCreate, user=Depends(get_current_user)):
    try:
        goal = await create_goal(
            _user_id(user),
            name=payload.name,
            target_amount=payload.target_amount,
            goal_type=payload.goal_type,
            current_amount=payload.current_amount,
            target_date=payload.target_date.isoformat() if payload.target_date else None,
            linked_account_id=payload.linked_account_id,
            linked_category_code=payload.linked_category_code,
            notes=payload.notes,
            linked_recurring_ids=payload.linked_recurring_ids,
            linked_transaction_ids=payload.linked_transaction_ids,
        )
        return _ok({"goal": goal})
    except AppError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.patch("/goals/{goal_id}")
async def planning_update_goal(goal_id: str, payload: GoalUpdate, user=Depends(get_current_user)):
    try:
        data = payload.model_dump(exclude_unset=True)
        if "target_date" in data and data["target_date"] is not None:
            data["target_date"] = data["target_date"].isoformat()
        goal = await update_goal(_user_id(user), goal_id, **data)
        return _ok({"goal": goal})
    except AppError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.get("/goals/link-candidates")
async def planning_goal_link_candidates(user=Depends(get_current_user)):
    return _ok(await list_link_candidates(_user_id(user)))


@router.put("/goals/{goal_id}/links")
async def planning_set_goal_links(goal_id: str, payload: GoalLinks, user=Depends(get_current_user)):
    try:
        links = await set_goal_links(
            _user_id(user),
            goal_id,
            recurring_ids=payload.recurring_ids,
            transaction_ids=payload.transaction_ids,
        )
        return _ok({"links": links})
    except AppError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.get("/goals/list")
async def planning_goals_raw(user=Depends(get_current_user)):
    return _ok({"goals": await list_goals(_user_id(user))})
