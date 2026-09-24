"""Planning and intelligence orchestration.

Loads existing FinTracker records once, then runs pure calculations from
``planning_math``. Does not invent balances, bills, or transactions.
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone

from bson import ObjectId
from dateutil.relativedelta import relativedelta

from app.db.mongo import db
from app.helpers.dashboard_cards import fetch_monthly_trend_12m
from app.helpers.dashboard_time import APP_TIMEZONE, app_now, start_of_month_utc
from app.helpers.money import round_money
from app.helpers.planning_math import (
    SAFETY_BUFFER_RATE,
    as_date,
    available_cash,
    best_duplicate_match,
    calendar_events_from_sources,
    card_payment_events,
    compute_goal_plan,
    months_between,
    compute_health_score,
    compute_net_worth,
    compute_safe_to_spend,
    credit_card_command_center,
    day_detail,
    emi_cash_events,
    events_for_month,
    expand_recurring_occurrences,
    generate_insights,
    net_worth_change,
    walk_forecast,
    percent_change,
    score_bill_health,
    score_cash_buffer,
    score_emi_burden,
    score_expense_control,
    score_obligation_coverage,
    score_recurring_health,
    score_savings_rate,
    score_utilization,
    compact_dashboard_overlay,
    typical_variable_spend,
    normalize_spend_description,
)
from app.helpers.recurring_schedule import VALID_FREQUENCIES
from app.helpers.goal_math import goal_health, projected_at_target
from app.services.goal_links import load_goal_contributions
from app.services.goals import list_goals
from app.services.notifications import upsert_notification


def _uid(user_id: str | ObjectId) -> ObjectId:
    return user_id if isinstance(user_id, ObjectId) else ObjectId(str(user_id))


def _norm_account(doc: dict) -> dict:
    return {
        "id": str(doc["_id"]),
        "_id": str(doc["_id"]),
        "name": doc.get("name") or doc.get("bank_name") or "Account",
        "bank_name": doc.get("bank_name"),
        "type": doc.get("type") or "other",
        "balance": round_money(doc.get("balance")),
        "credit_limit": round_money(doc.get("credit_limit")),
        "statement_balance": round_money(doc.get("statement_balance")),
        "payment_due_date": doc.get("payment_due_date"),
        "due_day": doc.get("due_day"),
        "card_network": doc.get("card_network"),
    }


def _norm_emi(doc: dict) -> dict:
    return {
        "id": str(doc["_id"]),
        "_id": str(doc["_id"]),
        "account_id": str(doc.get("account_id") or ""),
        "monthly_amount": round_money(doc.get("monthly_amount")),
        "next_due_date": doc.get("next_due_date"),
        "status": doc.get("status") or "active",
        "merchant": doc.get("merchant") or doc.get("description") or "EMI",
        "description": doc.get("description") or doc.get("merchant") or "EMI",
        "remaining_installments": doc.get("remaining_installments"),
    }


async def _load_accounts(uid: ObjectId) -> list[dict]:
    cursor = db.accounts.find({"user_id": uid, "deleted_at": None})
    return [_norm_account(doc) async for doc in cursor]


async def _load_recurring(uid: ObjectId) -> list[dict]:
    cursor = db.recurring_deposits.find(
        {
            "user_id": uid,
            "is_active": True,
            "ended_at": None,
        }
    )
    rows = []
    async for doc in cursor:
        rows.append(
            {
                "id": str(doc["_id"]),
                "account_id": str(doc.get("account_id") or ""),
                "amount": round_money(doc.get("amount")),
                "type": doc.get("type") or "debit",
                "description": doc.get("description") or "Recurring",
                "frequency": doc.get("frequency"),
                "next_run": doc.get("next_run"),
                "end_date": doc.get("end_date"),
            }
        )
    return rows


async def _load_emis(uid: ObjectId) -> list[dict]:
    cursor = db.credit_card_emis.find(
        {"user_id": uid, "deleted_at": None, "status": {"$ne": "closed"}}
    )
    return [_norm_emi(doc) async for doc in cursor]


async def _failed_recurring_counts(uid: ObjectId, since: datetime) -> tuple[int, int]:
    failed = await db.transactions.count_documents(
        {
            "user_id": uid,
            "deleted_at": None,
            "is_failed": True,
            "recurring_id": {"$ne": None},
            "created_at": {"$gte": since},
        }
    )
    scheduled = await db.transactions.count_documents(
        {
            "user_id": uid,
            "deleted_at": None,
            "recurring_id": {"$ne": None},
            "created_at": {"$gte": since},
        }
    )
    return int(failed), int(scheduled)


async def _category_month_map(uid: ObjectId, since: datetime) -> tuple[dict[str, dict[str, float]], dict[tuple[str, str], dict[str, float]], dict[tuple[str, str, str], dict[str, float]]]:
    cursor = db.transactions.aggregate(
        [
            {
                "$match": {
                    "user_id": uid,
                    "deleted_at": None,
                    "is_failed": {"$ne": True},
                    "created_at": {"$gte": since},
                    "type": "debit",
                }
            },
            {
                "$group": {
                    "_id": {
                        "month": {
                            "$dateToString": {
                                "format": "%Y-%m",
                                "date": "$created_at",
                                "timezone": APP_TIMEZONE,
                            }
                        },
                        "category": {"$ifNull": ["$category.name", "Uncategorized"]},
                        "subcategory": {"$ifNull": ["$subcategory.name", ""]},
                        "description": {"$ifNull": ["$description", ""]},
                    },
                    "total": {"$sum": "$amount"},
                }
            },
        ]
    )
    category_map: dict[str, dict[str, float]] = {}
    subcategory_map: dict[tuple[str, str], dict[str, float]] = {}
    description_map: dict[tuple[str, str, str], dict[str, float]] = {}
    async for row in cursor:
        month = row["_id"]["month"]
        category = row["_id"].get("category") or "Uncategorized"
        subcategory = row["_id"].get("subcategory") or ""
        description = normalize_spend_description(row["_id"].get("description") or "")
        total = float(row.get("total") or 0)
        category_map.setdefault(category, {})
        category_map[category][month] = category_map[category].get(month, 0) + total
        sub_key = (category, subcategory)
        subcategory_map.setdefault(sub_key, {})
        subcategory_map[sub_key][month] = subcategory_map[sub_key].get(month, 0) + total
        desc_key = (category, subcategory, description)
        description_map.setdefault(desc_key, {})
        description_map[desc_key][month] = description_map[desc_key].get(month, 0) + total
    return category_map, subcategory_map, description_map


async def _load_snapshots(uid: ObjectId, *, days: int = 180) -> tuple[list[dict], list[dict]]:
    since_key = (app_now().date() - timedelta(days=days)).isoformat()
    health = [
        doc
        async for doc in db.financial_health_snapshots.find(
            {"user_id": uid, "date_key": {"$gte": since_key}}
        ).sort("date_key", 1)
    ]
    worth = [
        doc
        async for doc in db.net_worth_snapshots.find(
            {"user_id": uid, "date_key": {"$gte": since_key}}
        ).sort("date_key", 1)
    ]
    return health, worth


def _next_income_event(events: list[dict], today: date) -> dict | None:
    future = [
        event
        for event in events
        if round_money(event.get("amount")) > 0 and (as_date(event.get("date")) or today) >= today
    ]
    future.sort(key=lambda event: as_date(event.get("date")) or today)
    if not future:
        return None
    event = future[0]
    return {
        "date": as_date(event.get("date")),
        "amount": round_money(event.get("amount")),
        "label": event.get("label") or "Expected income",
    }


def _obligation_groups(events: list[dict], today: date, until: date) -> dict[str, float]:
    groups = {"bills": 0.0, "credit_cards": 0.0, "recurring": 0.0, "emis": 0.0}
    for event in events:
        day = as_date(event.get("date"))
        amount = round_money(event.get("amount"))
        if day is None or amount >= 0 or day < today or day > until:
            continue
        source = str(event.get("source") or "")
        if source == "credit_card":
            groups["credit_cards"] += abs(amount)
        elif source == "emi":
            groups["emis"] += abs(amount)
        elif source == "recurring":
            groups["recurring"] += abs(amount)
        else:
            groups["bills"] += abs(amount)
    return {key: round_money(value) for key, value in groups.items()}


def _horizon_end(today: date, next_income: dict | None) -> date:
    default = today + timedelta(days=30)
    if not next_income:
        return default
    income_date = as_date(next_income.get("date"))
    if income_date and today < income_date <= today + timedelta(days=45):
        return income_date
    return default


def _dedupe_history(rows: list[dict]) -> list[dict]:
    by_key: dict[str, dict] = {}
    for row in rows or []:
        key = str(row.get("date_key") or "")
        if key:
            by_key[key] = row
    return [by_key[key] for key in sorted(by_key)]


async def _persist_snapshots(
    uid: ObjectId,
    today: date,
    health: dict,
    net_worth: dict,
    *,
    utilization=None,
) -> None:
    now = datetime.now(timezone.utc)
    date_key = today.isoformat()
    if health.get("score") is not None:
        await db.financial_health_snapshots.update_one(
            {"user_id": uid, "date_key": date_key},
            {
                "$set": {
                    "score": health["score"],
                    "band": health["band"],
                    "dimensions": health.get("dimensions") or {},
                    "utilization": utilization,
                    "updated_at": now,
                },
                "$setOnInsert": {"created_at": now, "user_id": uid, "date_key": date_key},
            },
            upsert=True,
        )
    await db.net_worth_snapshots.update_one(
        {"user_id": uid, "date_key": date_key},
        {
            "$set": {
                "net_worth": net_worth["net_worth"],
                "assets": net_worth["assets"],
                "liabilities": net_worth["liabilities"],
                "updated_at": now,
            },
            "$setOnInsert": {"created_at": now, "user_id": uid, "date_key": date_key},
        },
        upsert=True,
    )


async def persist_planning_notifications(uid: ObjectId, bundle: dict) -> None:
    forecast = bundle.get("forecast") or {}
    health = bundle.get("health") or {}
    safe = bundle.get("safe_to_spend") or {}
    today_key = (as_date(bundle.get("today")) or date.today()).isoformat()

    lowest = forecast.get("lowest_balance")
    if lowest is not None and lowest < 0:
        await upsert_notification(
            user_id=uid,
            key="forecast_low",
            notif_type="warning",
            title="Forecasted low balance",
            message=(
                f"Scheduled cash is projected to reach ₹ {round_money(lowest):.2f} "
                f"around {forecast.get('lowest_date') or 'an upcoming date'}."
            ),
        )
    else:
        await db.notifications.delete_many({"user_id": uid, "key": "forecast_low"})

    if safe.get("safe_to_spend") is not None and safe.get("safe_to_spend") <= 0 and (safe.get("reserved") or 0) > 0:
        await upsert_notification(
            user_id=uid,
            key="safe_to_spend_zero",
            notif_type="warning",
            title="Safe to spend is ₹0",
            message="Upcoming obligations currently reserve all available cash.",
        )
    else:
        await db.notifications.delete_many({"user_id": uid, "key": "safe_to_spend_zero"})

    history = bundle.get("health_history") or []
    prev_score = None
    if len(history) >= 2:
        prev_score = history[-2].get("score")
    elif len(history) == 1 and history[0].get("date_key") != today_key:
        prev_score = history[0].get("score")
    score = health.get("score")
    if score is not None and prev_score is not None and (prev_score - score) >= 10:
        await upsert_notification(
            user_id=uid,
            key="health_drop",
            notif_type="warning",
            title="Financial health dropped",
            message=f"Your health score moved from {prev_score} to {score}.",
        )
    else:
        await db.notifications.delete_many({"user_id": uid, "key": "health_drop"})

    active_goal_keys = set()
    for goal in bundle.get("goals") or []:
        if goal.get("status") != "active":
            continue
        if goal.get("on_track") is False:
            key = f"goal_behind:{goal.get('id')}"
            active_goal_keys.add(key)
            await upsert_notification(
                user_id=uid,
                key=key,
                notif_type="warning",
                title="Goal falling behind",
                message=goal.get("eta_label")
                or f"{goal.get('name')} is behind the required monthly pace.",
            )
    stale = {"user_id": uid, "key": {"$regex": r"^goal_behind:"}}
    if active_goal_keys:
        stale["key"]["$nin"] = list(active_goal_keys)
    await db.notifications.delete_many(stale)


def _goal_current_amount(goal: dict, accounts: list[dict]) -> float:
    linked = goal.get("linked_account_id")
    if linked:
        for account in accounts:
            if account["id"] == linked:
                return round_money(max(0.0, account.get("balance") or 0))
    return round_money(goal.get("current_amount"))


async def build_planning_bundle(
    user_id: str,
    *,
    persist: bool = True,
    year: int | None = None,
    month: int | None = None,
    day: date | None = None,
    buffer_rate: float = SAFETY_BUFFER_RATE,
) -> dict:
    uid = _uid(user_id)
    today = app_now().date()
    month_anchor = start_of_month_utc()
    since_30 = datetime.now(timezone.utc) - timedelta(days=30)

    accounts, recurring, emis, monthly_pack, failed_pack, spend_maps, snapshots, goals = await asyncio.gather(
        _load_accounts(uid),
        _load_recurring(uid),
        _load_emis(uid),
        fetch_monthly_trend_12m(uid, month_anchor),
        _failed_recurring_counts(uid, since_30),
        _category_month_map(uid, month_anchor - relativedelta(months=6)),
        _load_snapshots(uid),
        list_goals(user_id, include_archived=False),
    )
    category_map, subcategory_map, description_map = spend_maps
    trend_monthly, monthly_map, _, _ = monthly_pack
    failed_count, scheduled_count = failed_pack
    health_history, worth_history = snapshots

    current_month_key = app_now().strftime("%Y-%m")
    prev_local = app_now().replace(day=1) - timedelta(days=1)
    prev_month_key = prev_local.strftime("%Y-%m")
    month_credit = float(monthly_map.get(current_month_key, {}).get("credit") or 0)
    month_debit = float(monthly_map.get(current_month_key, {}).get("debit") or 0)
    prev_credit = float(monthly_map.get(prev_month_key, {}).get("credit") or 0)
    prev_debit = float(monthly_map.get(prev_month_key, {}).get("debit") or 0)

    complete_keys = [
        row["month"]
        for row in trend_monthly
        if row["month"] != current_month_key and (row.get("expense") or row.get("income"))
    ]
    recent_expense = [float(monthly_map.get(key, {}).get("debit") or 0) for key in complete_keys[-3:]]
    expense_avg = (sum(recent_expense) / len(recent_expense)) if len(recent_expense) >= 2 else None

    savings_rate = None
    if month_credit > 0:
        savings_rate = round(((month_credit - month_debit) / month_credit) * 100, 1)

    cash = available_cash(accounts)
    net_worth = compute_net_worth(accounts)
    cards = credit_card_command_center(accounts, emis, today=today)

    until = today + timedelta(days=90)
    recurring_events: list[dict] = []
    for rule in recurring:
        if (rule.get("frequency") or "") not in VALID_FREQUENCIES:
            continue
        recurring_events.extend(
            expand_recurring_occurrences(
                next_run=rule.get("next_run"),
                frequency=rule.get("frequency"),
                until=until,
                start_from=today,
                end_date=rule.get("end_date"),
                amount=rule.get("amount") or 0,
                tx_type=rule.get("type") or "debit",
                label=rule.get("description") or "Recurring",
                source_id=rule["id"],
                account_id=rule.get("account_id"),
            )
        )
    card_events = card_payment_events(accounts, start_from=today, until=until)
    cash_emi_events = emi_cash_events(emis, accounts, start_from=today, until=until)
    # Calendar still shows card EMIs as events even though they are not cash outflows.
    calendar_emi_events = []
    for emi in emis:
        due = as_date(emi.get("next_due_date"))
        if due is None or due < today or due > until:
            continue
        calendar_emi_events.append(
            {
                "date": due,
                "amount": round_money(-(emi.get("monthly_amount") or 0)),
                "label": emi.get("merchant") or "EMI",
                "source": "emi",
                "source_id": emi["id"],
                "account_id": emi.get("account_id"),
                "certainty": "scheduled",
                "type": "debit",
            }
        )

    cash_events = recurring_events + card_events + cash_emi_events
    forecast = walk_forecast(starting_cash=cash, events=cash_events, today=today)

    next_income = _next_income_event(recurring_events, today)
    horizon_end = _horizon_end(today, next_income)
    groups = _obligation_groups(cash_events, today, horizon_end)
    safe = compute_safe_to_spend(
        cash=cash,
        obligation_groups=groups,
        next_income=next_income,
        today=today,
        buffer_rate=buffer_rate,
        horizon_days=(horizon_end - today).days or 30,
    )

    total_limit = cards.get("total_limit") or 0
    utilization = cards.get("overall_utilization")
    overdue = 0
    open_cards = 0
    for card in cards.get("cards") or []:
        if (card.get("outstanding") or 0) > 0:
            open_cards += 1
            due = as_date(card.get("due_date"))
            if due and due < today:
                overdue += 1

    prev_health_dims = {}
    if health_history:
        prev_health_dims = health_history[-1].get("dimensions") or {}
        if health_history[-1].get("date_key") == today.isoformat() and len(health_history) >= 2:
            prev_health_dims = health_history[-2].get("dimensions") or {}

    dimensions = {
        "savings": score_savings_rate(savings_rate),
        "expense_control": score_expense_control(month_debit if month_debit > 0 else None, expense_avg),
        "cash_buffer": score_cash_buffer(cash, expense_avg or (month_debit if month_debit > 0 else None)),
        "utilization": score_utilization(cards.get("total_outstanding"), total_limit if total_limit > 0 else None),
        "obligations": score_obligation_coverage(cash, safe.get("reserved")),
        "recurring": score_recurring_health(failed_count, scheduled_count),
        "bills": score_bill_health(overdue, open_cards),
        "emi": score_emi_burden(cards.get("monthly_emi"), month_credit if month_credit > 0 else None),
    }
    health = compute_health_score(dimensions, prev_health_dims)

    prev_worth = None
    month_start_key = today.replace(day=1).isoformat()
    for row in reversed(worth_history):
        if row.get("date_key") and row["date_key"] < month_start_key:
            prev_worth = row.get("net_worth")
            break
    worth_delta = net_worth_change(net_worth["net_worth"], prev_worth)

    monthly_pace = round_money(month_credit - month_debit) if month_credit or month_debit else None
    if monthly_pace is not None and monthly_pace < 0:
        monthly_pace = 0.0

    enriched_goals = []
    goals_behind = []
    goal_links = await load_goal_contributions(uid, goals, today=today)
    for goal in goals:
        links = goal_links.get(goal["id"])
        starting_amount = round_money(goal.get("current_amount"))
        if goal.get("linked_account_id"):
            # Account-tracked goal: the account balance is the saved amount.
            current_amount = _goal_current_amount(goal, accounts)
            goal_pace, pace_source = monthly_pace, "overall"
        elif links:
            # Investment-tracked goal: what was already saved + everything the links posted.
            current_amount = round_money(starting_amount + links["invested_total"])
            goal_pace, pace_source = links["linked_pace"], "linked"
        else:
            current_amount = starting_amount
            goal_pace, pace_source = monthly_pace, "overall"
        plan = compute_goal_plan(
            target_amount=goal["target_amount"],
            current_amount=current_amount,
            target_date=goal.get("target_date"),
            today=today,
            monthly_pace=goal_pace,
        )
        due = plan.get("target_date")
        health_key, health_label = goal_health(
            status=goal.get("status") or "active",
            completed=bool(plan.get("completed")),
            on_track=plan.get("on_track"),
            has_target_date=bool(due),
        )
        row = {
            **goal,
            **plan,
            "current_amount": current_amount,
            "starting_amount": starting_amount,
            "tracking": "account" if goal.get("linked_account_id") else ("investments" if links else "manual"),
            "pace_source": pace_source,
            "links": links,
            "projected_at_target": projected_at_target(
                current=current_amount,
                monthly_pace=goal_pace,
                months_to_target=months_between(today, due) if due else 0.0,
            ),
            "health": health_key,
            "health_label": health_label,
        }
        enriched_goals.append(row)
        if row.get("status") == "active" and row.get("on_track") is False:
            goals_behind.append(
                {
                    "id": row["id"],
                    "name": row["name"],
                    "detail": row.get("eta_label"),
                }
            )

    category_changes = []
    for name, months in category_map.items():
        current = months.get(current_month_key)
        previous = months.get(prev_month_key)
        prior_vals = [months[key] for key in complete_keys[-3:] if key in months]
        average = (sum(prior_vals) / len(prior_vals)) if len(prior_vals) >= 2 else None
        change_vs_avg = percent_change(current, average) if current is not None else None
        change_vs_prev = percent_change(current, previous) if current is not None else None
        category_changes.append(
            {
                "name": name,
                "current": current,
                "previous": previous,
                "average": average,
                "change_pct": change_vs_avg if change_vs_avg is not None else change_vs_prev,
            }
        )

    typical_spend = typical_variable_spend(
        description_map or subcategory_map,
        current_month=current_month_key,
        prior_months=complete_keys[-3:],
    )

    prev_util = None
    if health_history:
        sample = health_history[-1]
        if sample.get("date_key") == today.isoformat() and len(health_history) >= 2:
            sample = health_history[-2]
        prev_util = sample.get("utilization")

    due_5 = sum(
        1
        for event in recurring_events
        if event.get("certainty") == "scheduled"
        and event.get("type") == "debit"
        and today <= (as_date(event.get("date")) or today) <= today + timedelta(days=5)
    )

    health_delta = None
    prev_score = None
    if health_history:
        candidate = health_history[-1]
        if candidate.get("date_key") == today.isoformat() and len(health_history) >= 2:
            candidate = health_history[-2]
        prev_score = candidate.get("score")
        if health.get("score") is not None and prev_score is not None:
            health_delta = health["score"] - prev_score

    insights = generate_insights(
        {
            "today": today,
            "category_changes": category_changes,
            "utilization": utilization,
            "utilization_previous": prev_util,
            "recurring_due_5_days": due_5,
            "cash": cash,
            "reserved": safe.get("reserved"),
            "month_expense": month_debit if month_debit else None,
            "prev_month_expense": prev_debit if prev_debit else None,
            "safe_to_spend": safe.get("safe_to_spend"),
            "lowest_balance": forecast.get("lowest_balance"),
            "lowest_date": forecast.get("lowest_date"),
            "health_delta": health_delta,
            "goals_behind": goals_behind,
        }
    )

    cal_year = int(year or today.year)
    cal_month = int(month or today.month)
    all_calendar = calendar_events_from_sources(
        recurring_events=recurring_events,
        card_events=card_events,
        emi_events=calendar_emi_events,
    )
    month_groups = events_for_month(all_calendar, cal_year, cal_month)
    selected_day = day or today
    selected_detail = day_detail(all_calendar, selected_day, starting_balance=cash)

    upcoming_calendar = [
        event
        for event in all_calendar
        if as_date(event.get("date")) and today <= as_date(event.get("date")) <= today + timedelta(days=21)
    ][:10]

    if persist:
        await _persist_snapshots(
            uid,
            today,
            health,
            net_worth,
            utilization=utilization,
        )
        health_history = _dedupe_history(
            health_history
            + [
                {
                    "date_key": today.isoformat(),
                    "score": health.get("score"),
                    "band": health.get("band"),
                    "dimensions": health.get("dimensions"),
                    "utilization": utilization,
                }
            ]
        )
        worth_history = _dedupe_history(
            worth_history
            + [
                {
                    "date_key": today.isoformat(),
                    "net_worth": net_worth["net_worth"],
                    "assets": net_worth["assets"],
                    "liabilities": net_worth["liabilities"],
                }
            ]
        )

    bundle = {
        "today": today,
        "cash": cash,
        "savings_rate": savings_rate,
        "month_income": round_money(month_credit),
        "month_expense": round_money(month_debit),
        "prev_month_income": round_money(prev_credit) if prev_credit else None,
        "prev_month_expense": round_money(prev_debit) if prev_debit else None,
        "category_changes": category_changes,
        "typical_spend": typical_spend,
        "health": health,
        "health_history": [
            {"date_key": row.get("date_key"), "score": row.get("score"), "band": row.get("band")}
            for row in health_history
            if row.get("score") is not None
        ],
        "net_worth": {**net_worth, **worth_delta},
        "net_worth_history": [
            {
                "date_key": row.get("date_key"),
                "net_worth": row.get("net_worth"),
                "assets": row.get("assets"),
                "liabilities": row.get("liabilities"),
            }
            for row in worth_history
        ],
        "forecast": forecast,
        "safe_to_spend": safe,
        "credit_cards": cards,
        "calendar": {
            "year": cal_year,
            "month": cal_month,
            "days": month_groups,
            "upcoming": upcoming_calendar,
            "selected": selected_detail,
            "events": all_calendar,
        },
        "insights": insights,
        "goals": enriched_goals,
        "accounts": accounts,
        "disclaimer": health.get("disclaimer"),
    }

    if persist:
        await persist_planning_notifications(uid, bundle)

    return bundle


overlay_from_bundle = compact_dashboard_overlay


async def get_planning_overlay(user_id: str) -> dict:
    bundle = await build_planning_bundle(user_id, persist=True)
    return overlay_from_bundle(bundle)


async def enrich_inbox_duplicates(user_id: str, rows: list[dict]) -> list[dict]:
    if not rows:
        return rows
    uid = _uid(user_id)
    dates = [as_date(row.get("date_key") or row.get("date")) for row in rows]
    dates = [item for item in dates if item]
    if not dates:
        return rows
    start = datetime.combine(min(dates) - timedelta(days=2), datetime.min.time(), tzinfo=timezone.utc)
    end = datetime.combine(max(dates) + timedelta(days=2), datetime.max.time(), tzinfo=timezone.utc)
    ledger: list[dict] = []
    cursor = db.transactions.find(
        {
            "user_id": uid,
            "deleted_at": None,
            "is_failed": {"$ne": True},
            "type": {"$in": ["debit", "credit"]},
            "$or": [
                {"transaction_date": {"$gte": start, "$lte": end}},
                {"created_at": {"$gte": start, "$lte": end}},
            ],
        },
        {"transaction_date": 1, "created_at": 1, "amount": 1, "description": 1, "type": 1, "account_id": 1},
    ).limit(2500)
    async for tx in cursor:
        raw_date = tx.get("transaction_date") or tx.get("created_at")
        ledger.append(
            {
                "id": str(tx["_id"]),
                "date": as_date(raw_date),
                "amount": round_money(tx.get("amount")),
                "description": tx.get("description") or "",
                "identity": str(tx.get("description") or "").strip().lower(),
                "type": tx.get("type"),
                "account_id": str(tx.get("account_id") or ""),
            }
        )

    for row in rows:
        if row.get("duplicate_match"):
            continue
        candidate = {
            "amount": row.get("amount"),
            "date": as_date(row.get("date_key") or row.get("date")),
            "account_id": row.get("account_id"),
            "type": row.get("type"),
            "identity": str(row.get("detected_merchant") or row.get("description") or "").strip().lower(),
        }
        match = best_duplicate_match(candidate, ledger)
        if match:
            row["possible_duplicate"] = True
            row["duplicate_match"] = match
            needs = list(row.get("needs_attention") or [])
            if "possible_duplicate" not in needs:
                needs.append("possible_duplicate")
            row["needs_attention"] = needs
    return rows
