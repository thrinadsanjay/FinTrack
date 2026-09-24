"""HTML pages for Phase 1 planning and intelligence."""

from __future__ import annotations

import asyncio
from calendar import monthrange
from datetime import date

from fastapi import APIRouter, Form, Query, Request
from fastapi.responses import RedirectResponse

from app.core.csrf import verify_csrf_token
from app.core.errors import AppError
from app.core.guards import login_required
from app.helpers.dashboard_time import app_now
from app.helpers.flash import set_flash
from app.helpers.insights_ui import (
    build_attention_feed,
    build_health_rows,
    health_chart,
    summarize_month,
    missing_health_dimensions,
    summarize_outlook,
)
from app.helpers.planning_math import GOAL_TYPES, as_date
from app.services.accounts import get_accounts
from app.services.dashboard import get_user_notifications
from app.services.goal_links import add_goal_links, list_link_candidates, set_goal_links
from app.services.goals import create_goal, list_goals, update_goal
from app.services.planning import build_planning_bundle
from app.web.templates import templates

router = APIRouter()

GOAL_TYPE_LABELS = {
    "emergency_fund": "Emergency Fund",
    "laptop": "New Laptop",
    "vacation": "Vacation",
    "car": "Car",
    "investment": "Investment",
    "custom": "Custom Goal",
}


def _page(request: Request, name: str, active_page: str, extra: dict):
    user = request.session.get("user")
    ctx = {
        "request": request,
        "user": user,
        "active_page": active_page,
        "goal_types": GOAL_TYPE_LABELS,
        **extra,
    }
    return templates.TemplateResponse(request=request, name=name, context=ctx)


def _month_matrix(year: int, month: int) -> list[list[date | None]]:
    first_weekday, days = monthrange(year, month)
    # Monday-first to match finance calendar reading.
    start_pad = (first_weekday) % 7
    cells: list[date | None] = [None] * start_pad
    for day in range(1, days + 1):
        cells.append(date(year, month, day))
    while len(cells) % 7:
        cells.append(None)
    return [cells[i : i + 7] for i in range(0, len(cells), 7)]


# Health, Forecast and Insights used to be three pages; they are now sections of
# /insights. Old URLs redirect so bookmarks and dashboard links keep working.
@router.get("/insights/health")
@login_required
async def health_page(request: Request):
    return RedirectResponse("/insights#health", status_code=303)


@router.get("/insights/forecast")
@login_required
async def forecast_page(request: Request):
    return RedirectResponse("/insights#cash", status_code=303)


@router.get("/insights")
@login_required
async def insights_page(request: Request):
    from app.services.ai_finance import recommendations_for_user, review_from_bundle
    from app.services.chat_assistant import ai_available

    user = request.session.get("user")
    bundle, notifications = await asyncio.gather(
        build_planning_bundle(user["user_id"], persist=True),
        get_user_notifications(user["user_id"]),
    )
    try:
        recs = await recommendations_for_user(user["user_id"])
    except Exception:
        recs = []
    health = bundle.get("health") or {}
    return _page(
        request,
        "pages/planning/insights.html",
        "planning_insights",
        {
            "bundle": bundle,
            "notifications": notifications,
            "feed": build_attention_feed(bundle.get("insights"), recs),
            "health": health,
            "health_rows": build_health_rows(health),
            "health_missing": missing_health_dimensions(health),
            "outlook": summarize_outlook(bundle.get("forecast"), today=app_now().date()),
            "health_series": health_chart(bundle.get("health_history")),
            "month": summarize_month(review_from_bundle(bundle), today=app_now().date()),
            "ai_available": ai_available(),
        },
    )


@router.get("/planning/safe-to-spend")
@login_required
async def safe_to_spend_page(request: Request):
    user = request.session.get("user")
    bundle = await build_planning_bundle(user["user_id"], persist=True)
    notifications = await get_user_notifications(user["user_id"])
    return _page(
        request,
        "pages/planning/safe_to_spend.html",
        "planning_safe",
        {"bundle": bundle, "notifications": notifications},
    )


@router.get("/planning/net-worth")
@login_required
async def net_worth_page(request: Request):
    user = request.session.get("user")
    bundle = await build_planning_bundle(user["user_id"], persist=True)
    notifications = await get_user_notifications(user["user_id"])
    return _page(
        request,
        "pages/planning/net_worth.html",
        "planning_networth",
        {"bundle": bundle, "notifications": notifications},
    )


@router.get("/planning/credit-cards")
@login_required
async def credit_cards_page(request: Request):
    return RedirectResponse("/accounts?group=card", status_code=302)


@router.get("/planning/calendar")
@login_required
async def calendar_page(
    request: Request,
    year: int | None = Query(default=None),
    month: int | None = Query(default=None),
    day: str | None = Query(default=None),
    view: str = Query(default="month"),
    kind: str = Query(default=""),
):
    user = request.session.get("user")
    today = app_now().date()
    selected = as_date(day) or today
    cal_year = year or selected.year
    cal_month = month or selected.month
    if cal_month < 1 or cal_month > 12:
        cal_month = today.month
    bundle = await build_planning_bundle(
        user["user_id"],
        persist=False,
        year=cal_year,
        month=cal_month,
        day=selected,
    )
    days_map = (bundle.get("calendar") or {}).get("days") or {}
    if kind:
        filtered = {}
        for key, events in days_map.items():
            kept = [event for event in events if str(event.get("source") or "") == kind]
            if kept:
                filtered[key] = kept
        days_map = filtered
    if cal_month == 1:
        prev_link = (cal_year - 1, 12)
    else:
        prev_link = (cal_year, cal_month - 1)
    if cal_month == 12:
        next_link = (cal_year + 1, 1)
    else:
        next_link = (cal_year, cal_month + 1)
    notifications = await get_user_notifications(user["user_id"])
    return _page(
        request,
        "pages/planning/calendar.html",
        "planning_calendar",
        {
            "bundle": bundle,
            "notifications": notifications,
            "month_weeks": _month_matrix(cal_year, cal_month),
            "days_map": days_map,
            "view": view if view in {"month", "list"} else "month",
            "kind": kind,
            "prev_link": prev_link,
            "next_link": next_link,
            "month_label": date(cal_year, cal_month, 1).strftime("%B %Y"),
            "today": today,
            "selected": selected,
        },
    )


GOAL_TYPE_ICONS = {
    "emergency_fund": "fa-shield-heart",
    "laptop": "fa-laptop",
    "vacation": "fa-plane-departure",
    "car": "fa-car-side",
    "investment": "fa-chart-line",
    "custom": "fa-bullseye",
}
GOAL_FILTERS = ("all", "active", "paused", "completed", "archived")


def _goal_stats(goals: list[dict]) -> dict:
    live = [g for g in goals if g.get("status") in {"active", "paused"}]
    active = [g for g in goals if g.get("status") == "active"]
    saved = sum(float(g.get("current_amount") or 0) for g in live)
    target = sum(float(g.get("target_amount") or 0) for g in live)
    return {
        "active": len(active),
        "saved": saved,
        "target": target,
        "saved_pct": round(saved / target * 100) if target else 0,
        "monthly_invested": sum(float((g.get("links") or {}).get("monthly_commitment") or 0) for g in active),
        "required_monthly": sum(float(g.get("required_monthly") or 0) for g in active if not g.get("completed")),
        "behind": sum(1 for g in active if g.get("health") == "behind"),
        "completed": sum(1 for g in goals if g.get("status") == "completed" or g.get("completed")),
    }


def _goals_redirect(request: Request, status: str | None = None, *, error: str | None = None, notice: str | None = None):
    url = "/planning/goals"
    if status and status in GOAL_FILTERS and status != "all":
        url += f"?status={status}"
    if error:
        set_flash(request, error, tone="error")
    elif notice:
        set_flash(request, notice)
    return RedirectResponse(url, status_code=303)


@router.get("/planning/goals")
@login_required
async def goals_page(request: Request, status: str = "all", error: str | None = None):
    user = request.session.get("user")
    status = status if status in GOAL_FILTERS else "all"
    bundle, accounts, candidates, notifications = await asyncio.gather(
        build_planning_bundle(user["user_id"], persist=False),
        get_accounts(user["user_id"]),
        list_link_candidates(user["user_id"]),
        get_user_notifications(user["user_id"]),
    )
    goals = bundle.get("goals") or []
    archived = []
    if status == "archived":
        archived = [g for g in await list_goals(user["user_id"], include_archived=True) if g.get("status") == "archived"]
    counts = {
        "all": len(goals),
        "active": sum(1 for g in goals if g.get("status") == "active"),
        "paused": sum(1 for g in goals if g.get("status") == "paused"),
        "completed": sum(1 for g in goals if g.get("status") == "completed"),
    }
    visible = goals if status == "all" else [g for g in goals if g.get("status") == status]
    goal_names = {g["id"]: g["name"] for g in goals}
    cash_accounts = [acc for acc in accounts if acc.get("type") not in {"credit_card", "loan"}]
    # Edit/link dialogs are filled from this (rendered in a JSON script tag, not attributes).
    goals_json = {
        g["id"]: {
            "id": g["id"],
            "name": g["name"],
            "goal_type": g.get("goal_type") or "custom",
            "target_amount": g.get("target_amount"),
            "starting_amount": g.get("starting_amount", g.get("current_amount")),
            "target_date": g["target_date"].isoformat() if g.get("target_date") else "",
            "linked_account_id": g.get("linked_account_id") or "",
            # Used to pre-fill "Already saved" when switching from account to investment tracking.
            "account_balance": g.get("current_amount") if g.get("tracking") == "account" else None,
            "notes": g.get("notes") or "",
            "linked_recurring_ids": g.get("linked_recurring_ids") or [],
            "linked_transaction_ids": g.get("linked_transaction_ids") or [],
        }
        for g in goals
    }
    return _page(
        request,
        "pages/planning/goals.html",
        "planning_goals",
        {
            "goals": visible,
            "archived_goals": archived,
            "goal_counts": counts,
            "goal_filter": status,
            "goal_names": goal_names,
            "goals_json": goals_json,
            "account_names": {str(a["_id"]): a.get("name") or a.get("bank_name") or "Account" for a in accounts},
            "stats": _goal_stats(goals),
            "candidates": candidates,
            "goal_icons": GOAL_TYPE_ICONS,
            "accounts": cash_accounts or accounts,
            "notifications": notifications,
            "error": error,
            "goal_type_keys": GOAL_TYPES,
        },
    )


@router.post("/planning/goals")
@login_required
async def goals_create(
    request: Request,
    csrf_token: str = Form(...),
    name: str = Form(...),
    target_amount: float = Form(...),
    goal_type: str = Form("custom"),
    current_amount: float = Form(0),
    target_date: str = Form(""),
    linked_account_id: str = Form(""),
    notes: str = Form(""),
    recurring_ids: list[str] = Form([]),
    transaction_ids: list[str] = Form([]),
):
    verify_csrf_token(request, csrf_token)
    user = request.session.get("user")
    try:
        await create_goal(
            user["user_id"],
            name=name,
            target_amount=target_amount,
            goal_type=goal_type,
            current_amount=current_amount,
            target_date=target_date or None,
            linked_account_id=linked_account_id or None,
            notes=notes or None,
            linked_recurring_ids=recurring_ids,
            linked_transaction_ids=transaction_ids,
        )
    except AppError as exc:
        return _goals_redirect(request, error=exc.detail)
    return _goals_redirect(request, notice=f"Goal \u201c{name.strip()}\u201d created")


@router.post("/planning/goals/{goal_id}/edit")
@login_required
async def goals_edit(
    request: Request,
    goal_id: str,
    csrf_token: str = Form(...),
    name: str = Form(...),
    target_amount: float = Form(...),
    goal_type: str = Form("custom"),
    current_amount: float = Form(0),
    target_date: str = Form(""),
    linked_account_id: str = Form(""),
    notes: str = Form(""),
    return_status: str = Form("all"),
):
    verify_csrf_token(request, csrf_token)
    user = request.session.get("user")
    try:
        await update_goal(
            user["user_id"],
            goal_id,
            name=name,
            target_amount=target_amount,
            goal_type=goal_type,
            current_amount=current_amount,
            target_date=target_date or None,
            linked_account_id=linked_account_id or None,
            notes=notes,
        )
    except AppError as exc:
        return _goals_redirect(request, return_status, error=exc.detail)
    return _goals_redirect(request, return_status, notice="Goal updated")


def _safe_next(value: str | None, fallback: str = "/planning/goals") -> str:
    # Local paths only: blocks "//evil.com" and "/\\evil.com" open redirects.
    text = str(value or "").strip()
    if not text.startswith("/") or text.startswith("//") or text.startswith("/\\"):
        return fallback
    return text


@router.post("/planning/goals/link-entry")
@login_required
async def goals_link_entry(
    request: Request,
    csrf_token: str = Form(...),
    goal_id: str = Form(...),
    transaction_id: str = Form(""),
    recurring_id: str = Form(""),
    next: str = Form(""),
):
    """Target of the post-save "link to a goal?" prompt: adds one entry to a goal."""
    verify_csrf_token(request, csrf_token)
    user = request.session.get("user")
    target = _safe_next(next)
    try:
        result = await add_goal_links(
            user["user_id"],
            goal_id,
            recurring_ids=[recurring_id] if recurring_id else [],
            transaction_ids=[transaction_id] if transaction_id else [],
        )
    except AppError as exc:
        set_flash(request, exc.detail, tone="error")
        return RedirectResponse(target, status_code=303)
    set_flash(request, f"Linked to \u201c{result['goal_name']}\u201d")
    return RedirectResponse(target, status_code=303)


@router.post("/planning/goals/{goal_id}/links")
@login_required
async def goals_links(
    request: Request,
    goal_id: str,
    csrf_token: str = Form(...),
    recurring_ids: list[str] = Form([]),
    transaction_ids: list[str] = Form([]),
    return_status: str = Form("all"),
):
    verify_csrf_token(request, csrf_token)
    user = request.session.get("user")
    try:
        await set_goal_links(
            user["user_id"],
            goal_id,
            recurring_ids=recurring_ids,
            transaction_ids=transaction_ids,
        )
    except AppError as exc:
        return _goals_redirect(request, return_status, error=exc.detail)
    return _goals_redirect(request, return_status, notice="Linked investments updated")


@router.post("/planning/goals/{goal_id}/status")
@login_required
async def goals_status(
    request: Request,
    goal_id: str,
    csrf_token: str = Form(...),
    status: str = Form(...),
    return_status: str = Form("all"),
):
    verify_csrf_token(request, csrf_token)
    user = request.session.get("user")
    try:
        await update_goal(user["user_id"], goal_id, status=status)
    except AppError as exc:
        return _goals_redirect(request, return_status, error=exc.detail)
    return _goals_redirect(request, return_status)


@router.get("/insights/ask")
@login_required
async def ask_page(request: Request):
    # Ask FinTracker was removed from Insights; the chat assistant covers live questions.
    return RedirectResponse("/insights", status_code=303)


@router.get("/insights/review")
@login_required
async def review_page(request: Request):
    # Reports is now the "This month" section of /insights.
    return RedirectResponse("/insights#month", status_code=303)
