"""Shared helpers for transaction list / board UI preparation."""

from __future__ import annotations

from collections import OrderedDict
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from app.core.guards import EDIT_WINDOW_DAYS, can_restore_today, is_within_edit_window
from app.core.time import utc_to_local
from app.helpers.money import round_money
from app.helpers.labels import payment_mode_label
from app.helpers.accounts_ui import type_meta
from app.helpers.bank_brands import resolve_bank_brand


def merge_transfer_rows(transactions: list[dict]) -> list[dict]:
    transfer_groups: dict[str, list] = {}
    merged: list[dict] = []
    for tx in transactions:
        transfer_id = tx.get("transfer_id")
        if not transfer_id:
            merged.append(tx)
            continue
        transfer_groups.setdefault(str(transfer_id), []).append(tx)

    for items in transfer_groups.values():
        source = next((t for t in items if t.get("type") == "transfer_out"), None)
        target = next((t for t in items if t.get("type") == "transfer_in"), None)
        base = source or target or items[0]
        merged.append(
            {
                "_id": base.get("_id"),
                "transfer_id": base.get("transfer_id"),
                "type": "transfer",
                "amount": base.get("amount", 0),
                "description": base.get("description", "Transfer"),
                "created_at": base.get("created_at"),
                "deleted_at": base.get("deleted_at"),
                "restored_at": base.get("restored_at"),
                "category": base.get("category"),
                "subcategory": base.get("subcategory"),
                "mode": base.get("mode"),
                "account_id": (source or base).get("account_id"),
                "from_account": (source or base).get("account_id"),
                "to_account": (target or base).get("account_id") or base.get("target_account_id"),
                "source": base.get("source"),
                "is_failed": bool(base.get("is_failed")),
                "failure_reason": base.get("failure_reason"),
                "retry_status": base.get("retry_status", "pending"),
                "emi_conversion": base.get("emi_conversion"),
            }
        )
    return merged


def enrich_transactions_for_ui(
    *,
    transactions: list[dict],
    account_map: dict[str, str],
    account_type_map: dict[str, str],
    user_tz: ZoneInfo,
    account_docs: dict[str, dict] | None = None,
) -> list[dict]:
    today_local = datetime.now(user_tz).date()

    for tx in transactions:
        created_at = tx.get("created_at")
        if created_at and created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
            tx["created_at"] = created_at

        tx["is_deleted"] = tx.get("deleted_at") is not None
        tx["is_failed"] = bool(tx.get("is_failed"))
        restored_at = tx.get("restored_at")
        if restored_at and getattr(restored_at, "tzinfo", None) is None:
            restored_at = restored_at.replace(tzinfo=timezone.utc)
            tx["restored_at"] = restored_at
        tx["is_restored"] = bool(restored_at) and not tx["is_deleted"]
        tx["retry_status"] = tx.get("retry_status", "pending")
        tx["can_retry"] = (
            tx["is_failed"]
            and tx.get("failure_reason") == "insufficient_funds"
            and tx["retry_status"] != "resolved"
        )
        tx["can_modify"] = (
            not tx["is_deleted"]
            and created_at
            and is_within_edit_window(created_at)
        )
        if tx["is_failed"]:
            tx["can_modify"] = False

        tx["can_restore"] = tx["is_deleted"] and can_restore_today(tx["deleted_at"])
        if tx["is_failed"]:
            tx["can_restore"] = False

        tx["lock_time"] = (
            created_at + timedelta(days=EDIT_WINDOW_DAYS) if created_at else None
        )

        status_bits = []
        if tx["is_deleted"]:
            status_bits.append("Rolled back")
        elif tx["is_restored"] and restored_at:
            local_restored = utc_to_local(restored_at, user_tz)
            if local_restored:
                status_bits.append(
                    "Restored " + local_restored.strftime("%d-%m-%Y %I:%M %p").lstrip("0")
                )
            else:
                status_bits.append("Restored")
        if tx["is_failed"]:
            reason = (tx.get("failure_reason") or "").replace("_", " ").strip()
            status_bits.append(f"Failed{(' · ' + reason) if reason else ''}")
        tx["status_info"] = " · ".join(status_bits)
        tx["display_title"] = (tx.get("description") or "").strip()

        type_label = {
            "credit": "Income",
            "debit": "Expense",
            "transfer": "Transfer",
        }.get(str(tx.get("type") or ""), str(tx.get("type") or "Transaction"))
        tx["type_label"] = type_label
        tx["type_key"] = {
            "credit": "credit",
            "debit": "debit",
            "transfer": "transfer",
        }.get(str(tx.get("type") or ""), "other")

        tx["can_convert_to_emi"] = (
            not tx["is_deleted"]
            and not tx["is_failed"]
            and str(tx.get("type") or "") == "debit"
            and tx.get("source") not in {"emi_processing_fee", "emi_interest_projection"}
            and not bool((tx.get("emi_conversion") or {}).get("converted"))
            and account_type_map.get(str(tx.get("account_id") or "")) == "credit_card"
        )

        if tx.get("type") == "transfer":
            from_name = account_map.get(str(tx.get("from_account") or ""), "Account")
            to_name = account_map.get(str(tx.get("to_account") or ""), "Account")
            tx["account_name"] = f"{from_name} → {to_name}"
            tx["from_account_name"] = from_name
            tx["to_account_name"] = to_name
        else:
            tx["account_name"] = account_map.get(str(tx.get("account_id") or ""), "Account")

        brand_acc = (account_docs or {}).get(str(tx.get("account_id") or tx.get("from_account") or ""))
        if brand_acc:
            meta = type_meta(brand_acc.get("type"))
            tx["logo_url"] = resolve_bank_brand(brand_acc, group=meta["group"])["logo"]
        else:
            tx["logo_url"] = "/static/icons/banks/generic-bank.svg?v=3"
        tx["mode_label"] = payment_mode_label(tx.get("mode")) or "—"

        cat = tx.get("category") or {}
        sub = tx.get("subcategory") or {}
        tx["category_name"] = cat.get("name") if isinstance(cat, dict) else None
        tx["subcategory_name"] = sub.get("name") if isinstance(sub, dict) else None
        tx["category_code"] = cat.get("code") if isinstance(cat, dict) else ""
        tx["subcategory_code"] = sub.get("code") if isinstance(sub, dict) else ""
        tx["is_transfer"] = str(tx.get("type") or "") == "transfer"
        tx["amount"] = round_money(tx.get("amount"))
        tx["has_actions"] = bool(
            tx["can_modify"]
            or tx["can_restore"]
            or tx["can_retry"]
            or tx["can_convert_to_emi"]
        )

        info_lines = [type_label]
        desc = (tx.get("description") or "").strip()
        if desc:
            info_lines.append(f"Description: {desc}")
        if tx.get("mode"):
            info_lines.append(f"Mode: {payment_mode_label(tx.get('mode'))}")
        if tx.get("category_name") and not tx["is_transfer"]:
            cat_line = tx["category_name"]
            if tx.get("subcategory_name"):
                cat_line += f" · {tx['subcategory_name']}"
            info_lines.append(f"Category: {cat_line}")
        if tx.get("account_name"):
            info_lines.append(f"Account: {tx['account_name']}")
        if tx["can_modify"] and tx.get("lock_time"):
            local_lock = utc_to_local(tx["lock_time"], user_tz)
            if local_lock:
                info_lines.append(
                    "Editable until " + local_lock.strftime("%d-%m-%Y %I:%M %p").lstrip("0")
                )
        elif tx["is_deleted"] and tx["can_restore"]:
            info_lines.append("Can be restored within 24 hours of rollback")
        elif not tx["is_deleted"] and not tx["can_modify"]:
            info_lines.append("Edit window closed")
        if tx["status_info"]:
            info_lines.append(tx["status_info"])
        tx["info_text"] = "\n".join(info_lines)

        local_dt = utc_to_local(tx.get("created_at"), user_tz)
        if local_dt is None:
            tx["local_date"] = None
            tx["local_time"] = ""
            tx["local_date_label"] = "Unknown date"
            tx["day_heading"] = None
            tx["day_date_label"] = "Unknown date"
            tx["age_days"] = None
            tx["icon"] = "fa-receipt"
        else:
            day = local_dt.date()
            tx["local_date"] = day.isoformat()
            tx["local_time"] = local_dt.strftime("%I:%M %p").lstrip("0")
            age = (today_local - day).days
            tx["age_days"] = age
            tx["day_date_label"] = f"{day.day} {local_dt.strftime('%b %Y')}"
            if day == today_local:
                tx["day_heading"] = "Today"
                tx["local_date_label"] = f"Today · {tx['day_date_label']}"
            elif day == today_local - timedelta(days=1):
                tx["day_heading"] = "Yesterday"
                tx["local_date_label"] = f"Yesterday · {tx['day_date_label']}"
            else:
                tx["day_heading"] = None
                tx["local_date_label"] = tx["day_date_label"]

            if tx["is_transfer"]:
                tx["icon"] = "fa-right-left"
            elif tx["type_key"] == "credit":
                tx["icon"] = "fa-arrow-down"
            else:
                tx["icon"] = "fa-arrow-up"

        if not tx["display_title"]:
            if tx["is_transfer"]:
                tx["display_title"] = "Transfer"
            elif tx["category_name"]:
                tx["display_title"] = tx["category_name"]
            else:
                tx["display_title"] = type_label

    return transactions


def group_by_local_date(transactions: list[dict], user_tz: ZoneInfo) -> list[dict]:
    today_local = datetime.now(user_tz).date()
    yesterday_local = today_local - timedelta(days=1)
    grouped: OrderedDict[str, dict] = OrderedDict()

    for tx in transactions:
        day_key = tx.get("local_date") or "unknown"
        label = tx.get("local_date_label") or "Unknown date"
        if day_key != "unknown":
            try:
                day = datetime.fromisoformat(day_key).date()
                if day == today_local:
                    label = "Today"
                elif day == yesterday_local:
                    label = "Yesterday"
                else:
                    label = datetime.fromisoformat(day_key).strftime("%A, %d %b %Y")
            except ValueError:
                pass
        bucket = grouped.get(day_key)
        if not bucket:
            bucket = {"key": day_key, "label": label, "rows": []}
            grouped[day_key] = bucket
        bucket["rows"].append(tx)
    return list(grouped.values())


def _column_totals(rows: list[dict]) -> dict:
    income = 0.0
    expense = 0.0
    transfer = 0.0
    for tx in rows:
        amt = round_money(tx.get("amount"))
        key = tx.get("type_key")
        if key == "credit":
            income += amt
        elif key == "debit":
            expense += amt
        elif key == "transfer":
            transfer += amt
    return {
        "count": len(rows),
        "income": round_money(income),
        "expense": round_money(expense),
        "transfer": round_money(transfer),
    }


def _board_week_start(today_local: date) -> date:
    """ISO week starts on Monday (Python weekday 0)."""
    return today_local - timedelta(days=today_local.weekday())


def build_board_columns(transactions: list[dict], user_tz: ZoneInfo) -> list[dict]:
    """
    Split last-30-day transactions into 2 relative columns.

    This Week: current ISO week (Mon–Sun)
    Earlier: other transactions within the last 30 days
    """
    today_local = datetime.now(user_tz).date()
    week_start = _board_week_start(today_local)
    oldest = today_local - timedelta(days=30)

    cols = [
        {
            "id": "week",
            "title": "This Week",
            "icon": "fa-calendar-week",
            "tone": "week",
            "rows": [],
            "day_groups": OrderedDict(),
        },
        {
            "id": "earlier",
            "title": "Earlier",
            "icon": "fa-calendar-days",
            "tone": "earlier",
            "rows": [],
            "day_groups": OrderedDict(),
        },
    ]

    for tx in transactions:
        day_key = tx.get("local_date")
        if not day_key:
            continue
        try:
            day = datetime.fromisoformat(day_key).date()
        except ValueError:
            continue
        if day > today_local or day < oldest:
            continue

        if day >= week_start:
            col = cols[0]
        else:
            col = cols[1]

        col["rows"].append(tx)
        group = col["day_groups"].get(day_key)
        if not group:
            group = {
                "key": day_key,
                "heading": tx.get("day_heading"),
                "label": tx.get("day_date_label") or tx.get("local_date_label") or "Unknown date",
                "rows": [],
            }
            col["day_groups"][day_key] = group
        group["rows"].append(tx)

    result = []
    for col in cols:
        totals = _column_totals(col["rows"])
        result.append(
            {
                "id": col["id"],
                "title": col["title"],
                "icon": col["icon"],
                "tone": col["tone"],
                "count": totals["count"],
                "income": totals["income"],
                "expense": totals["expense"],
                "transfer": totals["transfer"],
                "day_groups": list(col["day_groups"].values()),
                "empty": totals["count"] == 0,
            }
        )
    return result


def transaction_kpis(rows: list[dict]) -> dict:
    income = expense = transfer = 0.0
    count = 0
    for tx in rows:
        if tx.get("is_deleted"):
            continue
        count += 1
        amt = float(tx.get("amount") or 0)
        key = tx.get("type_key")
        if key == "credit":
            income += amt
        elif key == "debit":
            expense += amt
        elif key == "transfer":
            transfer += amt
    return {
        "income": round_money(income),
        "expense": round_money(expense),
        "net": round_money(income - expense),
        "transfer": round_money(transfer),
        "count": count,
    }


def resolve_account_ids_for_search(accounts: list[dict], search: str | None) -> list:
    if not search:
        return []
    needle = search.strip().lower()
    if not needle:
        return []
    matched = []
    for acc in accounts:
        name = str(acc.get("name") or acc.get("bank_name") or "").lower()
        if needle in name:
            matched.append(acc["_id"])
    return matched


def intersect_date_window(
    *,
    date_from: str | None,
    date_to: str | None,
    window_start,
    window_end,
) -> tuple[str, str]:
    """Intersect optional user dates with board window; return ISO date strings."""
    start = window_start
    end = window_end
    if date_from:
        from app.core.time import parse_user_date

        user_from = parse_user_date(date_from)
        if user_from and user_from > start:
            start = user_from
    if date_to:
        from app.core.time import parse_user_date

        user_to = parse_user_date(date_to)
        if user_to and user_to < end:
            end = user_to
    if start > end:
        start = end
    return start.isoformat(), end.isoformat()
