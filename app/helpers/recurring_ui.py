"""Presentation helpers for the Recurring rules page."""

from __future__ import annotations

from datetime import date, datetime, timezone
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from app.core.time import utc_to_local
from app.helpers.money import round_money
from app.helpers.labels import payment_mode_label

TYPE_META = {
    "credit": {"label": "Income", "class": "credit", "icon": "fa-arrow-down"},
    "income": {"label": "Income", "class": "credit", "icon": "fa-arrow-down"},
    "debit": {"label": "Expense", "class": "debit", "icon": "fa-arrow-up"},
    "expense": {"label": "Expense", "class": "debit", "icon": "fa-arrow-up"},
    "transfer": {"label": "Transfer", "class": "transfer", "icon": "fa-right-left"},
    "card_payment": {"label": "Transfer", "class": "transfer", "icon": "fa-right-left"},
}

FREQUENCY_META = {
    "daily": ("Daily", "day"),
    "weekly": ("Weekly", "week"),
    "biweekly": ("Every 2 weeks", "biweek"),
    "monthly": ("Monthly", "month"),
    "quarterly": ("Quarterly", "quarter"),
    "halfyearly": ("Every 6 months", "half-year"),
    "yearly": ("Yearly", "year"),
}

SOON_WINDOW_DAYS = 7


def frequency_label(frequency: str | None, interval: int | None = 1) -> str:
    freq = (frequency or "").strip().lower()
    count = int(interval or 1)
    base, unit = FREQUENCY_META.get(freq, ((frequency or "Custom").title(), "period"))
    if count <= 1:
        return base
    return f"Every {count} {unit}s"


def type_meta(tx_type: str | None) -> dict:
    return TYPE_META.get((tx_type or "").strip().lower(), TYPE_META["debit"])


def _as_utc(dt: datetime | None) -> datetime | None:
    if not dt:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _local_date(dt: datetime | None, user_tz: ZoneInfo) -> date | None:
    local = utc_to_local(_as_utc(dt), user_tz) if dt else None
    return local.date() if local else None


def _iso_date(dt: datetime | None, user_tz: ZoneInfo) -> str:
    local = utc_to_local(_as_utc(dt), user_tz) if dt else None
    return local.date().isoformat() if local else ""


def relative_due_label(next_local: date | None, today: date) -> tuple[str, bool]:
    if not next_local:
        return "No next run", False
    delta = (next_local - today).days
    if delta < 0:
        days = abs(delta)
        unit = "day" if days == 1 else "days"
        return f"{days} {unit} overdue", True
    if delta == 0:
        return "Due today", False
    if delta == 1:
        return "Tomorrow", False
    if delta < 14:
        return f"In {delta} days", False
    return next_local.strftime("%d %b %Y"), False


def category_label(rule: dict) -> str:
    category = rule.get("category") or {}
    subcategory = rule.get("subcategory") or {}
    cat_name = (category.get("name") or "").strip()
    sub_name = (subcategory.get("name") or "").strip()
    if cat_name and sub_name and sub_name.lower() != cat_name.lower():
        return f"{cat_name} · {sub_name}"
    return cat_name or sub_name or ""


def enrich_recurring_rule(rule: dict, *, user_tz: ZoneInfo, today: date | None = None) -> dict:
    row = dict(rule)
    today = today or datetime.now(user_tz).date()
    meta = type_meta(row.get("type"))
    next_local = _local_date(row.get("next_run"), user_tz)
    last_local = _local_date(row.get("last_run"), user_tz)
    relative, overdue = relative_due_label(next_local, today)
    status = row.get("status") or "active"

    row["id"] = str(row.get("id") or row.get("_id") or "")
    row["display_title"] = (row.get("description") or "").strip() or "Recurring rule"
    row["type_key"] = meta["class"]
    row["type_label"] = meta["label"]
    row["type_icon"] = meta["icon"]
    row["frequency_label"] = frequency_label(row.get("frequency"), row.get("interval"))
    row["mode_label"] = payment_mode_label(row.get("mode"))
    row["category_label"] = category_label(row)
    row["account_label"] = row.get("account_name") or "Account"
    if row.get("bank_name") and row["bank_name"] not in row["account_label"]:
        row["account_label"] = f"{row['account_label']} · {row['bank_name']}"
    row["next_local_date"] = next_local
    row["next_date_label"] = next_local.strftime("%d %b %Y") if next_local else ""
    row["last_date_label"] = last_local.strftime("%d %b %Y") if last_local else ""
    row["relative_due"] = relative
    row["is_overdue"] = overdue and status == "active"
    row["end_date_iso"] = _iso_date(row.get("end_date"), user_tz)
    row["start_date_iso"] = _iso_date(row.get("start_date"), user_tz)
    row["amount"] = round_money(row.get("amount") or 0)
    row["column_id"] = _column_id(status=status, next_local=next_local, today=today)
    return row


def _column_id(*, status: str, next_local: date | None, today: date) -> str:
    if status in {"paused", "ended"}:
        return "inactive"
    if next_local and (next_local - today).days <= SOON_WINDOW_DAYS:
        return "soon"
    return "scheduled"


def filter_recurring_rules(
    rules: list[dict],
    *,
    status: str = "all",
    tx_type: str = "",
    account_id: str = "",
    search: str = "",
) -> list[dict]:
    query = (search or "").strip().lower()
    wanted_type = (tx_type or "").strip().lower()
    wanted_account = (account_id or "").strip()
    wanted_status = (status or "all").strip().lower()
    filtered: list[dict] = []

    for rule in rules:
        if wanted_status != "all" and (rule.get("status") or "") != wanted_status:
            continue
        rule_type = rule.get("type_key") or type_meta(rule.get("type"))["class"]
        if wanted_type:
            wanted_class = type_meta(wanted_type)["class"]
            if rule_type != wanted_class:
                continue
        if wanted_account and str(rule.get("account_id") or "") != wanted_account:
            continue
        if query:
            hay = " ".join(
                [
                    str(rule.get("description") or ""),
                    str(rule.get("account_name") or ""),
                    str(rule.get("bank_name") or ""),
                    str(rule.get("amount") or ""),
                    str((rule.get("category") or {}).get("name") or ""),
                    str((rule.get("subcategory") or {}).get("name") or ""),
                    str(rule.get("frequency") or ""),
                    str(rule.get("mode") or ""),
                    str(rule.get("status") or ""),
                ]
            ).lower()
            if query not in hay:
                continue
        filtered.append(rule)
    return filtered


def compute_recurring_stats(
    rules: list[dict],
    *,
    user_tz: ZoneInfo,
    today: date | None = None,
) -> dict:
    today = today or datetime.now(user_tz).date()
    active = paused = ended = 0
    month_out = 0.0
    month_in = 0.0
    month_transfer = 0.0
    due_soon = 0
    next_due: date | None = None

    for rule in rules:
        status = rule.get("status")
        if status == "active":
            active += 1
        elif status == "paused":
            paused += 1
        else:
            ended += 1

        next_local = rule.get("next_local_date") or _local_date(rule.get("next_run"), user_tz)
        amount = float(rule.get("amount") or 0)
        kind = rule.get("type_key") or type_meta(rule.get("type"))["class"]

        if status == "active" and next_local:
            due_delta = (next_local - today).days
            in_month = next_local.year == today.year and next_local.month == today.month
            is_soon = due_delta <= SOON_WINDOW_DAYS
            if is_soon:
                due_soon += 1
            if in_month or is_soon:
                if kind == "credit":
                    month_in += amount
                elif kind == "transfer":
                    month_transfer += amount
                else:
                    month_out += amount
            if next_due is None or next_local < next_due:
                next_due = next_local

    return {
        "active": active,
        "paused": paused,
        "ended": ended,
        "due_soon": due_soon,
        "month_out": round_money(month_out),
        "month_in": round_money(month_in),
        "month_transfer": round_money(month_transfer),
        "month_pending": round_money(month_out),
        "next_due_label": next_due.strftime("%d %b") if next_due else None,
        "total": len(rules),
    }


def _empty_column(col_id: str, title: str, icon: str, tone: str, empty_copy: str) -> dict:
    return {
        "id": col_id,
        "title": title,
        "icon": icon,
        "tone": tone,
        "empty_copy": empty_copy,
        "rows": [],
        "count": 0,
        "income": 0.0,
        "expense": 0.0,
        "transfer": 0.0,
        "empty": True,
    }


def build_recurring_columns(
    rules: list[dict],
    *,
    user_tz: ZoneInfo,
    today: date | None = None,
) -> list[dict]:
    today = today or datetime.now(user_tz).date()
    columns = [
        _empty_column(
            "soon",
            "Due soon",
            "fa-clock",
            "soon",
            "Nothing due in the next 7 days.",
        ),
        _empty_column(
            "scheduled",
            "Scheduled",
            "fa-calendar-days",
            "scheduled",
            "No later recurring rules.",
        ),
        _empty_column(
            "inactive",
            "Paused & ended",
            "fa-pause",
            "inactive",
            "No paused or ended rules.",
        ),
    ]
    by_id = {col["id"]: col for col in columns}

    for rule in rules:
        enriched = rule if "column_id" in rule else enrich_recurring_rule(rule, user_tz=user_tz, today=today)
        col = by_id.get(enriched.get("column_id") or "scheduled")
        if not col:
            col = by_id["scheduled"]
        col["rows"].append(enriched)
        col["count"] += 1
        amount = float(enriched.get("amount") or 0)
        type_key = enriched.get("type_key") or type_meta(enriched.get("type"))["class"]
        if type_key == "credit":
            col["income"] += amount
        elif type_key == "transfer":
            col["transfer"] += amount
        else:
            col["expense"] += amount

    for col in columns:
        col["rows"].sort(
            key=lambda item: item.get("next_local_date") or date.max,
        )
        if col["id"] == "inactive":
            col["rows"].sort(
                key=lambda item: (
                    0 if item.get("status") == "paused" else 1,
                    item.get("next_local_date") or date.max,
                )
            )
        col["income"] = round_money(col["income"])
        col["expense"] = round_money(col["expense"])
        col["transfer"] = round_money(col["transfer"])
        col["empty"] = col["count"] == 0

    return columns


def recurring_query_string(
    *,
    status: str = "all",
    tx_type: str = "",
    account_id: str = "",
    search: str = "",
) -> str:
    params: dict[str, str] = {}
    if status and status != "all":
        params["status"] = status
    if tx_type:
        params["tx_type"] = tx_type
    if account_id:
        params["account_id"] = account_id
    if search:
        params["search"] = search
    return urlencode(params)
