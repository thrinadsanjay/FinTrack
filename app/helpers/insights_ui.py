"""
View shaping for the single Insights page. Pure functions, no database access.

The page deliberately skips what the Dashboard already shows (score tile,
month-end forecast, spend by category) and focuses on:
- what needs attention (rule insights + suggestions, de-duplicated),
- why the health score is what it is (per-dimension, weakest first),
- the 90-day cash outlook (lowest point, horizons, next 30 days).
"""

from __future__ import annotations

import re
from datetime import date, timedelta

from app.helpers.money import round_money

# What each health dimension measures and the most useful lever to move it.
DIMENSION_HELP = {
    "savings": ("Savings", "Share of income you keep each month.", "Automate a transfer or SIP right after payday."),
    "expense_control": ("Spending control", "How this month's spending compares with your usual.", "Review the categories that grew the most."),
    "cash_buffer": ("Cash buffer", "Months of expenses your cash could cover.", "Build towards 3–6 months of expenses in savings."),
    "utilization": ("Credit utilization", "Card balances as a share of their limits.", "Keep card balances under 30% of the limit."),
    "obligations": ("Upcoming obligations", "Whether cash covers bills and EMIs due soon.", "Keep enough cash aside for the next 30 days of dues."),
    "recurring": ("Recurring payments", "How reliably scheduled payments went through.", "Fund the account before recurring debits run."),
    "bills": ("Bill management", "Card bills paid on time and in full.", "Pay card bills before the due date."),
    "emi": ("EMI burden", "EMIs as a share of monthly income.", "Aim to keep EMIs under 40% of income."),
}

# Lower = more urgent. Insight categories and suggestion tones share one scale.
TONE_RANK = {"warning": 0, "risk": 0, "attention": 1, "info": 2, "positive": 3}
TONE_ICON = {
    "warning": "fa-triangle-exclamation",
    "attention": "fa-circle-exclamation",
    "info": "fa-lightbulb",
    "positive": "fa-circle-check",
}


def _norm_title(value: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", "", str(value or "").lower()).strip()


def build_attention_feed(insights: list[dict] | None, recommendations: list[dict] | None) -> dict:
    """
    Merge rule insights and suggestions into one ranked feed.
    Returns {"attention": [...], "going_well": [...]}; duplicates (same key or
    same title) keep the first, most urgent occurrence.
    """
    items: list[dict] = []
    for row in insights or []:
        tone = str(row.get("category") or "info").lower()
        items.append(
            {
                "key": row.get("key") or "",
                "tone": tone if tone in TONE_ICON else "info",
                "title": row.get("title") or "",
                "detail": row.get("detail") or "",
                "href": None,
                "priority": int(row.get("priority") or 50),
                "explainable": True,
                "category": row.get("category") or "",
            }
        )
    for row in recommendations or []:
        tone = str(row.get("tone") or "info").lower()
        items.append(
            {
                "key": row.get("key") or "",
                "tone": tone if tone in TONE_ICON else "info",
                "title": row.get("title") or "",
                "detail": row.get("evidence") or row.get("detail") or "",
                "href": row.get("href") if row.get("href") not in (None, "", "/insights") else None,
                "priority": int(row.get("priority") or 50),
                "explainable": False,
                "category": tone,
            }
        )

    items.sort(key=lambda it: (TONE_RANK.get(it["tone"], 2), it["priority"]))
    seen_keys: set[str] = set()
    seen_titles: set[str] = set()
    attention, going_well = [], []
    for item in items:
        title_key = _norm_title(item["title"])
        if not title_key or title_key in seen_titles or (item["key"] and item["key"] in seen_keys):
            continue
        seen_titles.add(title_key)
        if item["key"]:
            seen_keys.add(item["key"])
        item["icon"] = TONE_ICON.get(item["tone"], TONE_ICON["info"])
        (going_well if item["tone"] == "positive" else attention).append(item)
    return {"attention": attention, "going_well": going_well}


def build_health_rows(health: dict | None) -> list[dict]:
    """Available dimensions, weakest first, with plain-language meaning and a tip."""
    rows = []
    for key, value in ((health or {}).get("dimensions") or {}).items():
        label, meaning, tip = DIMENSION_HELP.get(key, (key.replace("_", " ").title(), "", ""))
        if value is None:
            continue
        score = int(value)
        tone = "good" if score >= 75 else "ok" if score >= 50 else "weak"
        rows.append(
            {
                "key": key,
                "label": label,
                "score": score,
                "tone": tone,
                "meaning": meaning,
                # Tips only where there is room to improve.
                "tip": tip if score < 75 else "",
            }
        )
    rows.sort(key=lambda r: r["score"])
    return rows


def missing_health_dimensions(health: dict | None) -> list[str]:
    dims = (health or {}).get("dimensions") or {}
    return [DIMENSION_HELP.get(k, (k.replace("_", " ").title(),))[0] for k, v in dims.items() if v is None]


def summarize_outlook(forecast: dict | None, *, today: date, event_limit: int = 8) -> dict:
    """90-day cash outlook numbers the dashboard does not show."""
    f = forecast or {}
    horizons = f.get("horizons") or {}
    events = sorted(f.get("contributing_events") or [], key=lambda e: _iso(e.get("date")))
    inflow = round_money(sum(float(e.get("amount") or 0) for e in events if float(e.get("amount") or 0) > 0))
    outflow = round_money(sum(-float(e.get("amount") or 0) for e in events if float(e.get("amount") or 0) < 0))
    lowest = f.get("lowest_balance")
    start = f.get("today_balance")
    lowest_date = f.get("lowest_date")
    if lowest is None:
        status = "unknown"
    elif lowest < 0:
        status = "negative"
    elif start and lowest < 0.25 * float(start):
        status = "tight"
    else:
        status = "healthy"
    days_to_lowest = (lowest_date - today).days if isinstance(lowest_date, date) else None
    return {
        "has_data": bool(f.get("daily")),
        "lowest": lowest,
        "lowest_date": lowest_date,
        "days_to_lowest": days_to_lowest,
        "status": status,
        "h30": horizons.get("30"),
        "h60": horizons.get("60"),
        "h90": horizons.get("90"),
        "start": start,
        "inflow_30": inflow,
        "outflow_30": outflow,
        "events": events[:event_limit],
        "more_events": max(0, len(events) - event_limit),
        # Chart series only: no free-text labels, so it is safe inside an HTML attribute.
        "chart": [
            {"date": _iso(row.get("date")), "balance": round_money(row.get("balance"))}
            for row in f.get("daily") or []
        ],
    }


def health_chart(history: list[dict] | None) -> list[dict]:
    return [
        {"date": _iso(row.get("date") or row.get("month")), "score": row.get("score")}
        for row in history or []
        if row.get("score") is not None
    ]


def _iso(value) -> str:
    if isinstance(value, date):
        return value.isoformat()
    return str(value or "")[:10]


def summarize_month(report: dict | None, *, today: date) -> dict:
    """
    This month so far vs all of last month. Category rows are split into what went
    up and what came down; tones say whether a change is good for the user.
    """
    r = report or {}
    cf = r.get("cash_flow") or {}
    first = today.replace(day=1)
    prev_last = first - timedelta(days=1)

    def tile(key, label, value, prev, change, *, up_is_good):
        tone = "neutral"
        if change is not None and abs(change) >= 1:
            tone = "good" if (change > 0) == up_is_good else "bad"
        return {"key": key, "label": label, "value": value, "prev": prev, "change": change, "tone": tone}

    income, expense = cf.get("income"), cf.get("expense")
    prev_income, prev_expense = cf.get("prev_income"), cf.get("prev_expense")
    prev_net = None
    if prev_income is not None or prev_expense is not None:
        prev_net = round_money((prev_income or 0) - (prev_expense or 0))

    rows = r.get("category_changes") or []
    scale = max([abs(float(x.get("change_pct") or 0)) for x in rows] + [1.0])
    shaped = [
        {
            "name": x.get("name") or "Other",
            "current": x.get("current"),
            "previous": x.get("previous"),
            "change_pct": x.get("change_pct"),
            "width": min(100, round(abs(float(x.get("change_pct") or 0)) / scale * 100)),
        }
        for x in rows
    ]
    return {
        "has_data": income is not None or expense is not None,
        "period_label": f"{first.day}–{today.day} {today.strftime('%b')}" if today.day > 1 else today.strftime("%d %b"),
        "prev_label": prev_last.strftime("%b"),
        "days_elapsed": today.day,
        "days_in_month": (first.replace(month=first.month % 12 + 1, year=first.year + (first.month == 12)) - first).days,
        "tiles": [
            tile("income", "Income", income, prev_income, cf.get("income_change_pct"), up_is_good=True),
            tile("spent", "Spent", expense, prev_expense, cf.get("expense_change_pct"), up_is_good=False),
            {"key": "saved", "label": "Saved", "value": cf.get("net"), "prev": prev_net, "change": None,
             "tone": "good" if (cf.get("net") or 0) > 0 else "bad" if (cf.get("net") or 0) < 0 else "neutral",
             "rate": cf.get("savings_rate")},
        ],
        "rising": [x for x in shaped if (x["change_pct"] or 0) > 0],
        "falling": [x for x in shaped if (x["change_pct"] or 0) < 0],
    }
