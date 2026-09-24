"""Pure financial-planning calculations.

No database access. Callers supply already-loaded FinTracker records.
Amounts are rounded with ``round_money``. Missing inputs yield ``None``
dimensions rather than invented figures.
"""

from __future__ import annotations

import calendar
import re
from datetime import date, datetime, timedelta
from math import ceil

from dateutil.relativedelta import relativedelta

from app.helpers.money import round_money
from app.helpers.recurring_schedule import VALID_FREQUENCIES, calculate_next_run


CASH_ACCOUNT_TYPES = frozenset({"savings", "current", "cash", "wallet"})
ASSET_ACCOUNT_TYPES = frozenset({"savings", "current", "cash", "wallet", "investment", "other"})
CREDIT_CARD_TYPE = "credit_card"
LOAN_TYPE = "loan"

SAFETY_BUFFER_RATE = 0.10
SAFE_TO_SPEND_DEFAULT_DAYS = 30
SAFE_TO_SPEND_INCOME_HORIZON_DAYS = 45
FORECAST_HORIZONS = (30, 60, 90)

HEALTH_BANDS = (
    (90, "EXCELLENT"),
    (80, "GOOD"),
    (65, "FAIR"),
    (50, "WATCH"),
    (0, "RISK"),
)

DUPLICATE_MIN_CONFIDENCE = 45
GOAL_TYPES = (
    "emergency_fund",
    "laptop",
    "vacation",
    "car",
    "investment",
    "custom",
)


def as_date(value) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        from app.core.time import parse_user_date

        return parse_user_date(value)
    return None


def _account_type(account: dict) -> str:
    return str(account.get("type") or "other").strip().lower()


def _account_name(account: dict) -> str:
    return str(account.get("name") or account.get("bank_name") or "Account")


def credit_card_outstanding(account: dict) -> float:
    if _account_type(account) != CREDIT_CARD_TYPE:
        return 0.0
    balance = round_money(account.get("balance"))
    return round_money(abs(balance)) if balance < 0 else 0.0


def credit_card_available(account: dict) -> float:
    if _account_type(account) != CREDIT_CARD_TYPE:
        return 0.0
    limit = round_money(account.get("credit_limit"))
    if limit <= 0:
        return 0.0
    return round_money(max(0.0, limit - credit_card_outstanding(account)))


def available_cash(accounts: list[dict]) -> float:
    """Spendable cash: cash-like account balances only.

    Credit-card available limit is never treated as cash.
    Investment balances are assets, not spendable cash.
    """
    total = 0.0
    for account in accounts or []:
        if _account_type(account) in CASH_ACCOUNT_TYPES:
            total += round_money(account.get("balance"))
    return round_money(total)


def compute_net_worth(accounts: list[dict]) -> dict:
    """Assets minus credit-card and loan outstanding.

    Loan balances are liabilities and never treated as cash.
    EMI remaining principal on a credit card is already in card outstanding.
    Transfers are ignored (they move value between owned accounts).
    """
    asset_rows: list[dict] = []
    liability_rows: list[dict] = []
    assets_total = 0.0
    liabilities_total = 0.0

    for account in accounts or []:
        acc_type = _account_type(account)
        name = _account_name(account)
        acc_id = str(account.get("id") or account.get("_id") or "")
        balance = round_money(account.get("balance"))

        if acc_type == CREDIT_CARD_TYPE:
            outstanding = credit_card_outstanding(account)
            if outstanding > 0:
                liability_rows.append(
                    {
                        "id": acc_id,
                        "name": name,
                        "type": acc_type,
                        "amount": outstanding,
                    }
                )
                liabilities_total += outstanding
            elif balance > 0:
                asset_rows.append(
                    {
                        "id": acc_id,
                        "name": f"{name} (card credit)",
                        "type": acc_type,
                        "amount": balance,
                    }
                )
                assets_total += balance
            continue

        if acc_type == LOAN_TYPE:
            outstanding = round_money(abs(balance))
            if outstanding > 0:
                liability_rows.append(
                    {
                        "id": acc_id,
                        "name": name,
                        "type": acc_type,
                        "amount": outstanding,
                    }
                )
                liabilities_total += outstanding
            continue

        if acc_type not in ASSET_ACCOUNT_TYPES:
            continue

        asset_rows.append(
            {
                "id": acc_id,
                "name": name,
                "type": acc_type,
                "amount": balance,
            }
        )
        assets_total += balance

    assets_total = round_money(assets_total)
    liabilities_total = round_money(liabilities_total)
    net = round_money(assets_total - liabilities_total)
    return {
        "assets": assets_total,
        "assets_total": assets_total,
        "liabilities": liabilities_total,
        "net_worth": net,
        "asset_rows": asset_rows,
        "liability_rows": liability_rows,
        "account_count": len(accounts or []),
    }


def _last_day(year: int, month: int) -> int:
    return calendar.monthrange(year, month)[1]


def clamp_day(year: int, month: int, day: int) -> date:
    return date(year, month, min(max(1, day), _last_day(year, month)))


def add_months(start: date, months: int) -> date:
    shifted = start + relativedelta(months=months)
    return shifted


def months_between(start: date, end: date) -> float:
    if end <= start:
        return 0.0
    delta = relativedelta(end, start)
    return max(0.0, delta.years * 12 + delta.months + (delta.days / 30.0))


def next_due_on_or_after(*, due_day: int | None, today: date, existing: date | None = None) -> date | None:
    if existing and existing >= today:
        return existing
    if not due_day or due_day < 1:
        return existing
    candidate = clamp_day(today.year, today.month, int(due_day))
    if candidate < today:
        nxt = today + relativedelta(months=1)
        candidate = clamp_day(nxt.year, nxt.month, int(due_day))
    return candidate


def expand_recurring_occurrences(
    *,
    next_run,
    frequency: str,
    until: date,
    start_from: date,
    end_date=None,
    amount: float,
    tx_type: str,
    label: str,
    source_id: str,
    account_id: str | None = None,
    first_certainty: str = "scheduled",
    later_certainty: str = "forecasted",
) -> list[dict]:
    """Expand a recurring rule into dated cash events.

    The stored ``next_run`` is confirmed/scheduled. Later implied dates
    in the horizon are forecasted (still from the rule, not history).
    """
    freq = str(frequency or "").strip().lower()
    if freq not in VALID_FREQUENCIES:
        return []

    current = as_date(next_run)
    if current is None:
        return []

    stop = as_date(end_date)
    signed = round_money(amount)
    if str(tx_type or "").lower() == "debit":
        signed = round_money(-abs(signed))
    else:
        signed = round_money(abs(signed))

    events: list[dict] = []
    is_first = True
    guard = 0
    while current <= until and guard < 400:
        if stop and current > stop:
            break
        if current >= start_from:
            events.append(
                {
                    "date": current,
                    "amount": signed,
                    "label": label,
                    "source": "recurring",
                    "source_id": source_id,
                    "account_id": account_id,
                    "certainty": first_certainty if is_first else later_certainty,
                    "type": "credit" if signed >= 0 else "debit",
                }
            )
            is_first = False
        nxt = calculate_next_run(last_run=current, start_date=current, frequency=freq)
        nxt_date = as_date(nxt)
        if nxt_date is None or nxt_date <= current:
            break
        current = nxt_date
        guard += 1
    return events


def _card_due_amount(account: dict) -> float:
    statement = round_money(account.get("statement_balance"))
    outstanding = credit_card_outstanding(account)
    if statement > 0:
        return statement
    return outstanding


def card_payment_events(
    accounts: list[dict],
    *,
    start_from: date,
    until: date,
) -> list[dict]:
    """Cash outflows when credit-card dues are paid from bank accounts."""
    events: list[dict] = []
    for account in accounts or []:
        if _account_type(account) != CREDIT_CARD_TYPE:
            continue
        amount = _card_due_amount(account)
        if amount <= 0:
            continue
        due_day = account.get("due_day")
        existing = as_date(account.get("payment_due_date"))
        due = next_due_on_or_after(due_day=due_day, today=start_from, existing=existing)
        if due is None or due < start_from or due > until:
            continue
        events.append(
            {
                "date": due,
                "amount": round_money(-amount),
                "label": f"{_account_name(account)} card payment",
                "source": "credit_card",
                "source_id": str(account.get("id") or account.get("_id") or ""),
                "account_id": str(account.get("id") or account.get("_id") or ""),
                "certainty": "scheduled",
                "type": "debit",
            }
        )
    return events


def emi_cash_events(
    emis: list[dict],
    accounts: list[dict],
    *,
    start_from: date,
    until: date,
) -> list[dict]:
    """EMI cash outflows only when the EMI is not billed on a credit card.

    Card EMIs are paid when the card bill is paid, so including both would
    double-count.
    """
    type_by_id = {
        str(acc.get("id") or acc.get("_id") or ""): _account_type(acc) for acc in accounts or []
    }
    events: list[dict] = []
    for emi in emis or []:
        status = str(emi.get("status") or "active").lower()
        if status in {"closed", "cancelled", "paid"}:
            continue
        account_id = str(emi.get("account_id") or "")
        if type_by_id.get(account_id) == CREDIT_CARD_TYPE:
            continue
        amount = round_money(emi.get("monthly_amount"))
        if amount <= 0:
            continue
        due = as_date(emi.get("next_due_date"))
        if due is None or due < start_from or due > until:
            continue
        events.append(
            {
                "date": due,
                "amount": round_money(-amount),
                "label": str(emi.get("merchant") or emi.get("description") or "EMI"),
                "source": "emi",
                "source_id": str(emi.get("id") or emi.get("_id") or ""),
                "account_id": account_id,
                "certainty": "scheduled",
                "type": "debit",
            }
        )
    return events


def walk_forecast(
    *,
    starting_cash: float,
    events: list[dict],
    today: date,
    horizons: tuple[int, ...] = FORECAST_HORIZONS,
    include_estimates: bool = False,
) -> dict:
    """Walk a daily cash path from scheduled/forecasted events.

    Historical estimates are excluded from the primary path unless
    ``include_estimates`` is True. Lowest balance uses the primary path.
    """
    start = round_money(starting_cash)
    by_day: dict[date, list[dict]] = {}
    for event in events or []:
        certainty = str(event.get("certainty") or "scheduled")
        if certainty == "estimate" and not include_estimates:
            continue
        day = as_date(event.get("date"))
        if day is None:
            continue
        by_day.setdefault(day, []).append(event)

    max_horizon = max(horizons) if horizons else 90
    end = today + timedelta(days=max_horizon)

    daily: list[dict] = []
    running = start
    lowest = start
    lowest_date = today
    cursor = today
    while cursor <= end:
        day_events = by_day.get(cursor, [])
        inflow = round_money(sum(e["amount"] for e in day_events if e.get("amount", 0) > 0))
        outflow = round_money(sum(e["amount"] for e in day_events if e.get("amount", 0) < 0))
        running = round_money(running + inflow + outflow)
        if running < lowest:
            lowest = running
            lowest_date = cursor
        daily.append(
            {
                "date": cursor,
                "balance": running,
                "inflow": inflow,
                "outflow": outflow,
                "events": day_events,
            }
        )
        cursor += timedelta(days=1)

    marks = {}
    for days in horizons:
        target = today + timedelta(days=days)
        match = next((row for row in daily if row["date"] == target), None)
        marks[days] = round_money(match["balance"] if match else running)

    contributing = [
        event
        for event in sorted(events or [], key=lambda item: (as_date(item.get("date")) or today, item.get("amount") or 0))
        if as_date(event.get("date")) and today <= as_date(event.get("date")) <= today + timedelta(days=30)
        and str(event.get("certainty") or "") != "estimate"
    ]

    return {
        "today_balance": start,
        "horizons": {str(days): marks[days] for days in horizons},
        "lowest_balance": round_money(lowest),
        "lowest_date": lowest_date,
        "daily": daily,
        "contributing_events": contributing,
        "event_count": len(events or []),
    }


def compute_safe_to_spend(
    *,
    cash: float,
    obligation_groups: dict[str, float],
    next_income: dict | None = None,
    today: date,
    buffer_rate: float = SAFETY_BUFFER_RATE,
    horizon_days: int = SAFE_TO_SPEND_DEFAULT_DAYS,
) -> dict:
    """Cash minus reserved obligations and a visible safety buffer.

    Expected income is shown but not added to the spendable amount.
    """
    groups = {key: round_money(value) for key, value in (obligation_groups or {}).items()}
    reserved_core = round_money(sum(max(0.0, value) for value in groups.values()))
    buffer = round_money(reserved_core * max(0.0, buffer_rate))
    reserved = round_money(reserved_core + buffer)
    raw = round_money(cash - reserved)
    spendable = round_money(max(0.0, raw))
    shortfall = round_money(abs(min(0.0, raw)))

    until = today + timedelta(days=max(1, horizon_days))
    income_amount = None
    income_date = None
    income_label = None
    if next_income:
        income_date = as_date(next_income.get("date"))
        income_amount = round_money(next_income.get("amount"))
        income_label = str(next_income.get("label") or "Expected income")
        if income_date and today < income_date <= today + timedelta(days=SAFE_TO_SPEND_INCOME_HORIZON_DAYS):
            until = income_date

    groups_out = dict(groups)
    groups_out["safety_buffer"] = buffer

    return {
        "safe_to_spend": spendable,
        "raw_amount": raw,
        "shortfall": shortfall,
        "available_cash": round_money(cash),
        "reserved": reserved,
        "until": until,
        "next_income_amount": income_amount,
        "next_income_date": income_date,
        "next_income_label": income_label,
        "breakdown": groups_out,
        "buffer_rate": buffer_rate,
        "income_included": False,
        "credit_limit_included": False,
    }


def _clamp_score(value: float) -> int:
    return int(round(max(0.0, min(100.0, value))))


def score_savings_rate(rate: float | None) -> int | None:
    if rate is None:
        return None
    clamped = max(-20.0, min(40.0, float(rate)))
    return _clamp_score((clamped + 20.0) / 60.0 * 100.0)


def score_expense_control(current: float | None, average: float | None) -> int | None:
    if current is None or average is None or average <= 0:
        return None
    ratio = float(current) / float(average)
    if ratio <= 0.7:
        return 100
    if ratio >= 2.0:
        return 0
    return _clamp_score(100.0 * (2.0 - ratio) / 1.3)


def score_cash_buffer(cash: float | None, monthly_expense: float | None) -> int | None:
    if cash is None or monthly_expense is None or monthly_expense <= 0:
        return None
    months = float(cash) / float(monthly_expense)
    return _clamp_score(months / 3.0 * 100.0)


def score_utilization(outstanding: float | None, limit: float | None) -> int | None:
    if outstanding is None or limit is None or limit <= 0:
        return None
    util_pct = max(0.0, float(outstanding) / float(limit) * 100.0)
    if util_pct >= 100:
        return 0
    return _clamp_score(100.0 - util_pct)


def score_obligation_coverage(cash: float | None, reserved: float | None) -> int | None:
    if cash is None or reserved is None or reserved <= 0:
        return None
    ratio = float(cash) / float(reserved)
    if ratio <= 0:
        return 0
    if ratio >= 2:
        return 100
    if ratio >= 1:
        return _clamp_score(75.0 + (ratio - 1.0) * 25.0)
    return _clamp_score(ratio * 75.0)


def score_recurring_health(failed_count: int | None, scheduled_count: int | None) -> int | None:
    if scheduled_count is None or scheduled_count <= 0:
        return None
    failed = max(0, int(failed_count or 0))
    success = max(0.0, 1.0 - failed / float(scheduled_count))
    return _clamp_score(success * 100.0)


def score_bill_health(overdue_count: int | None, open_count: int | None) -> int | None:
    overdue = int(overdue_count or 0)
    open_bills = int(open_count or 0)
    if open_bills <= 0 and overdue <= 0:
        return None
    if overdue > 0:
        return _clamp_score(max(0, 40 - overdue * 15))
    return 96


def score_emi_burden(monthly_emi: float | None, monthly_income: float | None) -> int | None:
    if monthly_emi is None or monthly_emi <= 0:
        return None
    if monthly_income is None or monthly_income <= 0:
        return 40
    ratio = float(monthly_emi) / float(monthly_income)
    return _clamp_score(max(0.0, (0.40 - ratio) / 0.40 * 100.0))


def health_band(score: int | None) -> str:
    if score is None:
        return "INSUFFICIENT"
    for threshold, label in HEALTH_BANDS:
        if score >= threshold:
            return label
    return "RISK"


def compute_health_score(
    dimensions: dict[str, int | None],
    previous_dimensions: dict[str, int | None] | None = None,
) -> dict:
    available = {key: value for key, value in (dimensions or {}).items() if value is not None}
    if not available:
        return {
            "score": None,
            "band": "INSUFFICIENT",
            "available_count": 0,
            "excluded": list((dimensions or {}).keys()),
            "dimensions": dimensions or {},
            "reasons": ["Not enough recorded activity to compute a score."],
            "disclaimer": "This score is an informational summary of your FinTracker records, not professional financial advice.",
        }

    score = int(round(sum(available.values()) / len(available)))
    excluded = [key for key, value in (dimensions or {}).items() if value is None]
    reasons = explain_health_change(available, previous_dimensions or {})
    if not reasons:
        weakest = min(available.items(), key=lambda item: item[1])
        strongest = max(available.items(), key=lambda item: item[1])
        reasons = [
            f"{_dimension_label(strongest[0])} is supporting the score at {strongest[1]}.",
            f"{_dimension_label(weakest[0])} is the weakest area at {weakest[1]}.",
        ]
    return {
        "score": score,
        "band": health_band(score),
        "available_count": len(available),
        "excluded": excluded,
        "dimensions": dimensions,
        "reasons": reasons[:6],
        "disclaimer": "This score is an informational summary of your FinTracker records, not professional financial advice.",
    }


def _dimension_label(key: str) -> str:
    return {
        "savings": "Savings",
        "expense_control": "Spending control",
        "cash_buffer": "Cash buffer",
        "utilization": "Credit utilization",
        "obligations": "Upcoming obligations",
        "recurring": "Recurring payments",
        "bills": "Bill management",
        "emi": "EMI burden",
    }.get(key, key.replace("_", " ").title())


def explain_health_change(
    current: dict[str, int],
    previous: dict[str, int | None],
) -> list[str]:
    deltas: list[tuple[int, str]] = []
    for key, value in current.items():
        prior = previous.get(key) if previous else None
        if prior is None:
            continue
        delta = int(value) - int(prior)
        if delta == 0:
            continue
        sign = "+" if delta > 0 else ""
        verb = {
            "savings": "Savings performance",
            "expense_control": "Spending control",
            "cash_buffer": "Cash buffer",
            "utilization": "Credit utilization",
            "obligations": "Obligation coverage",
            "recurring": "Recurring payment health",
            "bills": "Bill management",
            "emi": "EMI burden",
        }.get(key, _dimension_label(key))
        direction = "improved" if delta > 0 else "declined"
        deltas.append((delta, f"{sign}{delta} {verb} {direction}"))
    deltas.sort(key=lambda item: abs(item[0]), reverse=True)
    return [text for _, text in deltas]


def credit_card_command_center(accounts: list[dict], emis: list[dict], today: date | None = None) -> dict:
    cards: list[dict] = []
    total_outstanding = 0.0
    total_available = 0.0
    total_limit = 0.0
    upcoming_due = 0.0
    monthly_emi = 0.0
    emis_by_account: dict[str, list[dict]] = {}
    for emi in emis or []:
        if str(emi.get("status") or "active").lower() in {"closed", "cancelled", "paid"}:
            continue
        account_id = str(emi.get("account_id") or "")
        emis_by_account.setdefault(account_id, []).append(emi)
        monthly_emi += round_money(emi.get("monthly_amount"))

    today = today or date.today()
    for account in accounts or []:
        if _account_type(account) != CREDIT_CARD_TYPE:
            continue
        acc_id = str(account.get("id") or account.get("_id") or "")
        outstanding = credit_card_outstanding(account)
        limit = round_money(account.get("credit_limit"))
        available = credit_card_available(account)
        statement = round_money(account.get("statement_balance"))
        due = next_due_on_or_after(
            due_day=account.get("due_day"),
            today=today,
            existing=as_date(account.get("payment_due_date")),
        )
        util = None
        if limit > 0:
            util = round(outstanding / limit * 100.0, 1)
        card_emis = emis_by_account.get(acc_id, [])
        emi_monthly = round_money(sum(round_money(item.get("monthly_amount")) for item in card_emis))
        due_amount = _card_due_amount(account)
        if due_amount > 0:
            upcoming_due += due_amount
        cards.append(
            {
                "id": acc_id,
                "name": _account_name(account),
                "network": str(account.get("card_network") or "").lower() or None,
                "outstanding": outstanding,
                "available": available,
                "limit": limit,
                "utilization": util,
                "statement": statement,
                "due_date": due,
                "due_amount": due_amount,
                "emi_count": len(card_emis),
                "monthly_emi": emi_monthly,
            }
        )
        total_outstanding += outstanding
        total_available += available
        total_limit += limit

    overall_util = None
    if total_limit > 0:
        overall_util = round(total_outstanding / total_limit * 100.0, 1)

    cards.sort(key=lambda item: (item["due_date"] is None, item["due_date"] or date.max, item["name"].lower()))
    return {
        "card_count": len(cards),
        "total_outstanding": round_money(total_outstanding),
        "total_available": round_money(total_available),
        "total_limit": round_money(total_limit),
        "overall_utilization": overall_util,
        "upcoming_due": round_money(upcoming_due),
        "monthly_emi": round_money(monthly_emi),
        "cards": cards,
    }


def calendar_events_from_sources(
    *,
    recurring_events: list[dict],
    card_events: list[dict],
    emi_events: list[dict],
    extra_events: list[dict] | None = None,
) -> list[dict]:
    combined = list(recurring_events or []) + list(card_events or []) + list(emi_events or [])
    if extra_events:
        combined.extend(extra_events)
    combined.sort(key=lambda item: (as_date(item.get("date")) or date.max, item.get("amount") or 0))
    return combined


def events_for_month(events: list[dict], year: int, month: int) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for event in events or []:
        day = as_date(event.get("date"))
        if day is None or day.year != year or day.month != month:
            continue
        key = day.isoformat()
        grouped.setdefault(key, []).append(event)
    return grouped


def day_detail(events: list[dict], day: date, starting_balance: float | None = None) -> dict:
    day_events = [event for event in events or [] if as_date(event.get("date")) == day]
    outflows = [event for event in day_events if round_money(event.get("amount")) < 0]
    inflows = [event for event in day_events if round_money(event.get("amount")) > 0]
    outflow_total = round_money(sum(abs(round_money(event.get("amount"))) for event in outflows))
    inflow_total = round_money(sum(round_money(event.get("amount")) for event in inflows))
    after = None
    if starting_balance is not None:
        after = round_money(starting_balance + inflow_total - outflow_total)
    return {
        "date": day,
        "events": day_events,
        "outflows": outflows,
        "inflows": inflows,
        "outflow_total": outflow_total,
        "inflow_total": inflow_total,
        "expected_balance_after": after,
    }


def percent_change(current: float | None, previous: float | None) -> float | None:
    if current is None or previous is None:
        return None
    if previous == 0:
        return None
    return round((float(current) - float(previous)) / abs(float(previous)) * 100.0, 1)


def generate_insights(payload: dict) -> list[dict]:
    """Rule-based insights. Skip rules when the required numbers are missing."""
    insights: list[dict] = []
    today = as_date(payload.get("today")) or date.today()

    def add(*, key: str, category: str, title: str, detail: str, priority: int) -> None:
        insights.append(
            {
                "key": key,
                "category": category,
                "title": title,
                "detail": detail,
                "priority": priority,
            }
        )

    for item in payload.get("category_changes") or []:
        name = str(item.get("name") or "Spending")
        change = item.get("change_pct")
        if change is None:
            continue
        if abs(change) < 8 or abs(change) >= 200:
            continue
        if change > 0:
            add(
                key=f"cat_up:{name}",
                category="warning",
                title=f"{name} spending is {abs(change):.0f}% higher than your 3-month average.",
                detail=f"This month ₹{round_money(item.get('current')):.2f} vs typical ₹{round_money(item.get('average')):.2f}.",
                priority=20,
            )
        else:
            add(
                key=f"cat_down:{name}",
                category="positive",
                title=f"{name} spending decreased {abs(change):.0f}% compared with last month.",
                detail=f"This month ₹{round_money(item.get('current')):.2f} vs last month ₹{round_money(item.get('previous')):.2f}.",
                priority=40,
            )

    util_now = payload.get("utilization")
    util_prev = payload.get("utilization_previous")
    if util_now is not None and util_prev is not None and abs(util_now - util_prev) >= 5:
        if util_now < util_prev:
            add(
                key="util_drop",
                category="positive",
                title=f"Credit-card utilization dropped from {util_prev:.0f}% to {util_now:.0f}%.",
                detail="Lower utilization generally means more unused card limit.",
                priority=30,
            )
        else:
            add(
                key="util_up",
                category="attention",
                title=f"Credit-card utilization rose from {util_prev:.0f}% to {util_now:.0f}%.",
                detail="A higher share of your card limit is in use.",
                priority=25,
            )

    due_soon = int(payload.get("recurring_due_5_days") or 0)
    if due_soon > 0:
        add(
            key="recurring_soon",
            category="attention",
            title=f"You have {due_soon} recurring payment{'s' if due_soon != 1 else ''} due within the next 5 days.",
            detail="Review Recurring to confirm the source accounts are funded.",
            priority=15,
        )

    cash = payload.get("cash")
    reserved = payload.get("reserved")
    if cash is not None and reserved is not None and reserved > 0:
        if cash >= reserved:
            add(
                key="bills_covered",
                category="positive",
                title="Your current cash position is sufficient to cover upcoming scheduled bills.",
                detail=f"Available cash ₹{round_money(cash):.2f} vs reserved ₹{round_money(reserved):.2f}.",
                priority=45,
            )
        else:
            add(
                key="bills_short",
                category="warning",
                title="Scheduled bills exceed current cash.",
                detail=f"Available cash ₹{round_money(cash):.2f} vs reserved ₹{round_money(reserved):.2f}.",
                priority=10,
            )

    month_expense = payload.get("month_expense")
    prev_expense = payload.get("prev_month_expense")
    spend_change = percent_change(month_expense, prev_expense)
    if spend_change is not None and 10 <= abs(spend_change) < 80:
        if spend_change > 0:
            add(
                key="spend_up",
                category="attention",
                title=f"Spending is {abs(spend_change):.0f}% higher than last month.",
                detail="Month-to-date expenses compared with the previous full month.",
                priority=28,
            )
        else:
            add(
                key="spend_down",
                category="positive",
                title=f"Spending decreased {abs(spend_change):.0f}% compared with last month.",
                detail="Month-to-date expenses compared with the previous full month.",
                priority=42,
            )

    safe = payload.get("safe_to_spend")
    if safe is not None and safe <= 0:
        add(
            key="safe_zero",
            category="warning",
            title="Safe to spend is currently ₹0 after upcoming obligations.",
            detail="Discretionary spending would draw on amounts reserved for bills, cards, or EMIs.",
            priority=8,
        )

    lowest = payload.get("lowest_balance")
    lowest_date = as_date(payload.get("lowest_date"))
    if lowest is not None and lowest < 0:
        when = lowest_date.strftime("%d %b") if lowest_date else "the forecast window"
        add(
            key="forecast_negative",
            category="warning",
            title=f"Forecasted cash goes negative around {when}.",
            detail=f"Scheduled path lowest balance is ₹{round_money(lowest):.2f}.",
            priority=5,
        )

    health_delta = payload.get("health_delta")
    if health_delta is not None and abs(health_delta) >= 8:
        if health_delta < 0:
            add(
                key="health_drop",
                category="attention",
                title=f"Financial health dropped {abs(health_delta):.0f} points versus the last recorded score.",
                detail="Open Financial Health for the dimension breakdown.",
                priority=22,
            )
        else:
            add(
                key="health_up",
                category="positive",
                title=f"Financial health improved {abs(health_delta):.0f} points versus the last recorded score.",
                detail="Open Financial Health for the dimension breakdown.",
                priority=38,
            )

    for goal in payload.get("goals_behind") or []:
        add(
            key=f"goal_behind:{goal.get('id')}",
            category="attention",
            title=f"{goal.get('name') or 'A goal'} is behind the required monthly pace.",
            detail=goal.get("detail") or "Current savings pace is below what the target date requires.",
            priority=26,
        )

    order = {"warning": 0, "attention": 1, "positive": 2, "informational": 3}
    insights.sort(key=lambda item: (order.get(item["category"], 9), item["priority"], item["title"]))
    seen = set()
    unique: list[dict] = []
    for item in insights:
        if item["key"] in seen:
            continue
        seen.add(item["key"])
        unique.append(item)
        if len(unique) >= 8:
            break
    for item in unique:
        item["as_of"] = today.isoformat()
    return unique


def score_duplicate_match(candidate: dict, ledger_row: dict) -> dict | None:
    """Return a confidence + reason payload, or None if not a plausible duplicate."""
    cand_amount = round_money(candidate.get("amount"))
    row_amount = round_money(ledger_row.get("amount"))
    if cand_amount != row_amount or cand_amount == 0:
        return None

    cand_date = as_date(candidate.get("date"))
    row_date = as_date(ledger_row.get("date"))
    if cand_date is None or row_date is None:
        return None
    day_delta = abs((cand_date - row_date).days)
    if day_delta > 1:
        return None

    cand_account = str(candidate.get("account_id") or "")
    row_account = str(ledger_row.get("account_id") or "")
    same_account = bool(cand_account and row_account and cand_account == row_account)

    cand_type = str(candidate.get("type") or "").lower()
    row_type = str(ledger_row.get("type") or "").lower()
    same_type = bool(cand_type and row_type and cand_type == row_type)

    cand_identity = str(candidate.get("identity") or candidate.get("merchant") or "").strip().lower()
    row_identity = str(ledger_row.get("identity") or ledger_row.get("merchant") or "").strip().lower()
    merchant_score = 0
    if cand_identity and row_identity:
        if cand_identity == row_identity:
            merchant_score = 2
        elif cand_identity in row_identity or row_identity in cand_identity:
            merchant_score = 1

    confidence = 40
    reasons: list[str] = ["Same amount"]
    if same_account:
        confidence += 20
        reasons.append("Same account")
    if day_delta == 0:
        confidence += 15
        reasons.append("Same date")
    else:
        confidence += 8
        reasons.append("Date within 1 day")
    if same_type:
        confidence += 10
        reasons.append("Same transaction type")
    if merchant_score == 2:
        confidence += 15
        reasons.append("Same merchant")
    elif merchant_score == 1:
        confidence += 8
        reasons.append("Similar merchant")

    if not same_account and merchant_score == 0 and not same_type:
        return None

    confidence = int(max(0, min(99, confidence)))
    if confidence < DUPLICATE_MIN_CONFIDENCE:
        return None

    return {
        "confidence": confidence,
        "reasons": reasons,
        "existing": {
            "id": str(ledger_row.get("id") or ledger_row.get("_id") or ""),
            "amount": row_amount,
            "date": row_date.isoformat(),
            "description": str(ledger_row.get("description") or ledger_row.get("identity") or ""),
            "type": row_type,
            "account_id": row_account,
        },
    }


def best_duplicate_match(candidate: dict, ledger_rows: list[dict]) -> dict | None:
    best = None
    for row in ledger_rows or []:
        match = score_duplicate_match(candidate, row)
        if not match:
            continue
        if best is None or match["confidence"] > best["confidence"]:
            best = match
    return best


def compute_goal_plan(
    *,
    target_amount: float,
    current_amount: float,
    target_date,
    today: date,
    monthly_pace: float | None,
) -> dict:
    target = round_money(target_amount)
    current = round_money(current_amount)
    remaining = round_money(max(0.0, target - current))
    due = as_date(target_date)
    progress_pct = round((current / target * 100.0), 1) if target > 0 else 0.0
    progress_pct = max(0.0, min(100.0, progress_pct))

    months = months_between(today, due) if due else 0.0
    required_monthly = round_money(remaining / months) if months > 0 else remaining
    pace = round_money(monthly_pace) if monthly_pace is not None else None
    eta = None
    eta_label = None
    on_track = None
    if remaining <= 0:
        eta = today
        eta_label = "Target already reached."
        on_track = True
        required_monthly = 0.0
    elif pace is not None and pace > 0:
        months_needed = remaining / pace
        eta = add_months(today, max(1, int(ceil(months_needed))))
        on_track = required_monthly <= 0 or pace >= required_monthly * 0.95
        if due and eta > due:
            eta_label = (
                f"At your current savings pace, estimated completion is {eta.strftime('%B %Y')}."
            )
        elif due:
            months_early = months_between(eta, due)
            early_months = int(months_early)
            if early_months >= 1:
                eta_label = (
                    f"On track to finish about {early_months} month"
                    f"{'s' if early_months != 1 else ''} early "
                    f"({eta.strftime('%B %Y')})."
                )
            else:
                eta_label = f"On track — you may reach the target around {eta.strftime('%B %Y')}."
        else:
            eta_label = f"At the current pace, estimated completion is {eta.strftime('%B %Y')}."
    elif due:
        eta_label = "Not enough savings history to estimate a completion date."
        on_track = None
    else:
        eta_label = "Add a target date to see the required monthly amount."

    return {
        "target_amount": target,
        "current_amount": current,
        "remaining": remaining,
        "progress_pct": progress_pct,
        "target_date": due,
        "required_monthly": required_monthly,
        "monthly_pace": pace,
        "eta": eta,
        "eta_label": eta_label,
        "on_track": on_track,
        "completed": remaining <= 0,
    }


def net_worth_change(current: float, previous: float | None) -> dict:
    if previous is None:
        return {"monthly_change": None, "percent_change": None}
    change = round_money(current - previous)
    pct = percent_change(current, previous)
    return {"monthly_change": change, "percent_change": pct}


def _norm_spend_label(value) -> str:
    return " ".join(str(value or "").strip().lower().replace("_", " ").split())


TYPICAL_SPEND_LIMIT = 8
TYPICAL_SPEND_MIN_MONTHS = 2
SCHEDULED_TYPICAL_CATEGORIES = frozenset({"loan", "bank transfers", "self transfer"})
SCHEDULED_TYPICAL_SUBCATEGORIES = frozenset(
    {
        "rent",
        "credit card",
        "creditcard",
        "sip",
        "home loan",
        "personal loan",
        "gold loan",
        "car loan",
        "education loan",
        "other loans",
        "interest payment",
        "fixed deposit",
        "recurring deposit",
        "self transfer",
        "transfer",
    }
)


def classify_typical_spend(category: str | None, subcategory: str | None = None) -> str | None:
    cat = _norm_spend_label(category)
    sub = _norm_spend_label(subcategory)
    if _skip_scheduled_typical(cat, sub):
        return None
    if sub in {"groceries", "grocery"} or cat in {"groceries", "grocery"}:
        return "groceries"
    if cat in {"food", "dining", "dining out"}:
        return "food"
    if cat in {"health", "healthcare", "medical"}:
        return "health"
    if cat:
        return cat.replace(" ", "-")
    return None


def normalize_spend_description(value) -> str:
    text = _norm_spend_label(value)
    text = re.sub(r"\b\d{4,}\b", " ", text)
    text = re.sub(r"[^a-z0-9 &./'-]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip(" .-")
    if len(text) < 3:
        return ""
    return text[:42]


def _skip_scheduled_typical(category: str | None, subcategory: str | None = None) -> bool:
    return _norm_spend_label(category) in SCHEDULED_TYPICAL_CATEGORIES or _norm_spend_label(subcategory) in SCHEDULED_TYPICAL_SUBCATEGORIES


def _parse_typical_key(key) -> tuple[str, str, str]:
    if isinstance(key, (tuple, list)):
        category = key[0] if len(key) > 0 else ""
        subcategory = key[1] if len(key) > 1 else ""
        description = key[2] if len(key) > 2 else ""
        return str(category or ""), str(subcategory or ""), str(description or "")
    return str(key or ""), "", ""


def typical_spend_label(category: str | None, subcategory: str | None = None, description: str | None = None) -> str:
    cat = str(category or "").strip()
    sub = str(subcategory or "").strip()
    desc = str(description or "").strip()
    if desc and sub and _norm_spend_label(desc) != _norm_spend_label(sub):
        title = f"{sub} · {desc.title()}"
    elif desc:
        title = desc.title()
    elif sub and _norm_spend_label(sub) != _norm_spend_label(cat):
        title = sub
    else:
        title = cat or "Other"
    if "(est.)" not in title.lower():
        title = f"{title} (est.)"
    return title


def label_typical_spend_items(items: list[dict]) -> list[dict]:
    labeled = []
    for item in items or []:
        if not item:
            continue
        row = dict(item)
        name = (row.get("name") or "").strip()
        if not name:
            name = typical_spend_label(row.get("category"), row.get("subcategory"), row.get("description"))
        elif "(est.)" not in name.lower() and "(estimated)" not in name.lower():
            name = f"{name} (est.)"
        row["name"] = name
        labeled.append(row)
    return labeled


def _typical_item(key: str, name: str, series: dict, *, current_month: str, prior_months: list[str], category="", subcategory="", description="") -> dict | None:
    prior_vals = [float(series.get(month_key) or 0) for month_key in prior_months if float(series.get(month_key) or 0) > 0]
    if len(prior_vals) < TYPICAL_SPEND_MIN_MONTHS:
        return None
    average = round_money(sum(prior_vals) / len(prior_vals))
    spent = round_money(float(series.get(current_month) or 0))
    remaining = round_money(max(0.0, average - spent))
    if remaining <= 0 and spent <= 0:
        return None
    return {
        "key": key,
        "name": name,
        "category": category,
        "subcategory": subcategory,
        "description": description,
        "average": average,
        "spent": spent,
        "remaining": remaining,
    }


def typical_from_category_changes(changes: list | None) -> dict:
    items = []
    remaining_total = 0.0
    for row in changes or []:
        name = row.get("name") or ""
        if _skip_scheduled_typical(name):
            continue
        average = row.get("average")
        if average is None:
            average = row.get("previous")
        if average is None:
            continue
        spent = float(row.get("current") or 0)
        remaining = round_money(max(0.0, float(average) - spent))
        items.append(
            {
                "key": classify_typical_spend(name) or _norm_spend_label(name).replace(" ", "-"),
                "name": typical_spend_label(name),
                "category": name,
                "average": round_money(average),
                "spent": round_money(spent),
                "remaining": remaining,
            }
        )
        remaining_total += remaining
    items.sort(key=lambda item: (-float(item.get("remaining") or 0), item.get("name") or ""))
    items = label_typical_spend_items(items[:TYPICAL_SPEND_LIMIT])
    return {"items": items, "remaining": round_money(remaining_total)}


def typical_variable_spend(
    month_map: dict,
    *,
    current_month: str,
    prior_months: list[str],
) -> dict:
    """Expected leftover spend for categories that repeat in recent months.

    ``month_map`` keys are category names or ``(category, subcategory[, description])``.
    A series is included only when it appears in at least two prior months.
    Remaining is ``max(0, prior-month average − spent so far)``.
    Scheduled rent, loans, card dues and SIPs are omitted so they are not
    double-counted with calendar bills.
    """
    prior_months = list(prior_months or [])
    desc_rows: list[tuple[str, str, str, dict]] = []
    sub_series: dict[tuple[str, str], dict[str, float]] = {}
    cat_series: dict[str, dict[str, float]] = {}

    def add_series(target: dict, key, series: dict) -> None:
        bucket = target.setdefault(key, {})
        for month_key, amount in (series or {}).items():
            bucket[month_key] = bucket.get(month_key, 0.0) + float(amount or 0)

    for raw_key, series in (month_map or {}).items():
        category, subcategory, description = _parse_typical_key(raw_key)
        description = normalize_spend_description(description)
        if _skip_scheduled_typical(category, subcategory):
            continue
        desc_rows.append((category, subcategory, description, dict(series or {})))
        add_series(sub_series, (category, subcategory), series)
        add_series(cat_series, category, series)

    items = []
    leftover_sub = {key: dict(values) for key, values in sub_series.items()}
    leftover_cat = {key: dict(values) for key, values in cat_series.items()}

    def subtract_series(target: dict, key, series: dict) -> None:
        bucket = target.get(key)
        if bucket is None:
            return
        for month_key, amount in (series or {}).items():
            bucket[month_key] = bucket.get(month_key, 0.0) - float(amount or 0)

    for category, subcategory, description, series in desc_rows:
        if not description:
            continue
        item = _typical_item(
            f"desc:{_norm_spend_label(category)}|{_norm_spend_label(subcategory)}|{description}",
            typical_spend_label(category, subcategory, description),
            series,
            current_month=current_month,
            prior_months=prior_months,
            category=category,
            subcategory=subcategory,
            description=description,
        )
        if item is None:
            continue
        items.append(item)
        subtract_series(leftover_sub, (category, subcategory), series)
        subtract_series(leftover_cat, category, series)

    for (category, subcategory), series in leftover_sub.items():
        if not subcategory:
            continue
        item = _typical_item(
            f"sub:{_norm_spend_label(category)}|{_norm_spend_label(subcategory)}",
            typical_spend_label(category, subcategory),
            series,
            current_month=current_month,
            prior_months=prior_months,
            category=category,
            subcategory=subcategory,
        )
        if item is None:
            continue
        items.append(item)
        subtract_series(leftover_cat, category, series)

    for category, series in leftover_cat.items():
        item = _typical_item(
            f"cat:{_norm_spend_label(category)}",
            typical_spend_label(category),
            series,
            current_month=current_month,
            prior_months=prior_months,
            category=category,
        )
        if item is None:
            continue
        items.append(item)

    items.sort(key=lambda item: (-float(item.get("remaining") or 0), item.get("name") or ""))
    items = label_typical_spend_items(items[:TYPICAL_SPEND_LIMIT])
    remaining_total = round_money(sum(float(item.get("remaining") or 0) for item in items))
    return {"items": items, "remaining": remaining_total}


def _compact_overlay_calendar(cal: dict) -> dict:
    upcoming = list((cal or {}).get("upcoming") or [])
    year = (cal or {}).get("year")
    month = (cal or {}).get("month")
    raw_days = dict((cal or {}).get("days") or {})
    if not raw_days:
        for event in upcoming:
            day = as_date(event.get("date"))
            if day is None:
                continue
            if year and month and (day.year != int(year) or day.month != int(month)):
                continue
            raw_days.setdefault(day.isoformat(), []).append(event)
    compact_days = {}
    for key, events in raw_days.items():
        compact_days[str(key)] = [
            {
                "label": event.get("label") or event.get("source") or "Payment",
                "amount": event.get("amount") or 0,
                "source": event.get("source") or "",
                "type": event.get("type") or "",
            }
            for event in (events or [])[:8]
        ]
    return {
        "upcoming": upcoming,
        "year": year,
        "month": month,
        "days": compact_days,
    }


def compact_dashboard_overlay(bundle: dict) -> dict:
    health = bundle.get("health") or {}
    forecast = bundle.get("forecast") or {}
    safe = bundle.get("safe_to_spend") or {}
    net = bundle.get("net_worth") or {}
    cards = bundle.get("credit_cards") or {}
    horizons = forecast.get("horizons") or {}
    contributing = list(forecast.get("contributing") or forecast.get("contributing_events") or [])[:6]
    history_scores = [
        row.get("score")
        for row in (bundle.get("health_history") or [])
        if row.get("score") is not None
    ]
    previous_score = history_scores[-2] if len(history_scores) >= 2 else None
    today = as_date(bundle.get("today")) or date.today()
    month_end_balance = (
        forecast.get("today_balance")
        if forecast.get("today_balance") is not None
        else forecast.get("today")
    )
    remaining_outflow = 0.0
    remaining_inflow = 0.0
    for row in forecast.get("daily") or []:
        row_day = as_date(row.get("date"))
        if row_day is None or row_day.year != today.year or row_day.month != today.month:
            continue
        if row.get("balance") is not None:
            month_end_balance = row.get("balance")
        if row_day < today:
            continue
        remaining_outflow += abs(float(row.get("outflow") or 0))
        remaining_inflow += max(float(row.get("inflow") or 0), 0)
    month_spent = float(bundle.get("month_expense") or 0)
    raw_typical = bundle.get("typical_spend")
    if isinstance(raw_typical, dict):
        typical_items = list(raw_typical.get("items") or [])
        typical_remaining = raw_typical.get("remaining")
    elif isinstance(raw_typical, list):
        typical_items = list(raw_typical)
        typical_remaining = None
    else:
        typical_items = []
        typical_remaining = None
    if not typical_items:
        fallback = typical_from_category_changes(bundle.get("category_changes"))
        typical_items = fallback["items"]
        typical_remaining = fallback["remaining"]
    typical_items = label_typical_spend_items(typical_items)
    if typical_remaining is None:
        typical_remaining = sum(float(item.get("remaining") or 0) for item in typical_items)
    typical_remaining = round_money(typical_remaining)
    projected_month_outflow = round_money(month_spent + remaining_outflow + typical_remaining)
    projected_month_inflow = round_money(remaining_inflow)
    if month_end_balance is not None:
        month_end_balance = round_money(float(month_end_balance) - typical_remaining)
    return {
        "health": {
            "score": health.get("score"),
            "band": health.get("band"),
            "reasons": (health.get("reasons") or [])[:3],
            "insufficient": health.get("score") is None,
            "previous_score": previous_score,
        },
        "safe_to_spend": {
            "amount": safe.get("safe_to_spend"),
            "until": safe.get("until"),
            "reserved": safe.get("reserved"),
            "cash": safe.get("available_cash"),
            "shortfall": safe.get("shortfall"),
        },
        "net_worth": {
            "amount": net.get("net_worth"),
            "assets": net.get("assets"),
            "liabilities": net.get("liabilities"),
            "monthly_change": net.get("monthly_change"),
            "percent_change": net.get("percent_change"),
        },
        "forecast": {
            "today": forecast.get("today_balance") if forecast.get("today_balance") is not None else forecast.get("today"),
            "d30": horizons.get("30", horizons.get(30)),
            "d60": horizons.get("60", horizons.get(60)),
            "d90": horizons.get("90", horizons.get(90)),
            "lowest": forecast.get("lowest_balance") if forecast.get("lowest_balance") is not None else forecast.get("lowest"),
            "lowest_date": forecast.get("lowest_date"),
            "contributing": contributing,
            "month_end_balance": month_end_balance,
            "month_spent": round_money(month_spent),
            "month_remaining_outflow": round_money(remaining_outflow),
            "month_remaining_inflow": round_money(remaining_inflow),
            "month_projected_inflow": projected_month_inflow,
            "month_projected_outflow": projected_month_outflow,
            "month_typical_remaining": typical_remaining,
            "typical_spend": typical_items,
        },
        "credit_cards": {
            "outstanding": cards.get("total_outstanding"),
            "available": cards.get("total_available"),
            "utilization": cards.get("overall_utilization"),
            "upcoming_due": cards.get("upcoming_due"),
            "monthly_emi": cards.get("monthly_emi"),
            "card_count": cards.get("card_count"),
            "cards": (cards.get("cards") or [])[:4],
        },
        "calendar": _compact_overlay_calendar(bundle.get("calendar") or {}),
        "insights": (bundle.get("insights") or [])[:3],
        "goals": [
            {
                "id": goal.get("id"),
                "name": goal.get("name"),
                "current_amount": goal.get("current_amount"),
                "target_amount": goal.get("target_amount"),
                "progress_pct": goal.get("progress_pct"),
                "status": goal.get("status"),
                "target_date": goal.get("target_date"),
                "required_monthly": goal.get("required_monthly"),
                "monthly_pace": goal.get("monthly_pace"),
                "on_track": goal.get("on_track"),
            }
            for goal in (bundle.get("goals") or [])
            if goal.get("status") == "active"
        ][:3],
        "savings_rate": bundle.get("savings_rate"),
        "disclaimer": bundle.get("disclaimer"),
    }
