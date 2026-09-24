"""Pure matching and loop-prevention for the financial rules engine.

No money is moved. Actions are limited to categorization, review flags,
notifications, Telegram alerts, and insight notes.
"""

from __future__ import annotations

from datetime import date, datetime

from app.helpers.money import round_money

CONDITION_TYPES = (
    "merchant_contains",
    "amount_gte",
    "amount_lte",
    "amount_eq",
    "account_id",
    "category_code",
    "tx_type",
    "balance_lt",
    "utilization_gt",
    "due_within_days",
    "is_recurring",
    "salary_received",
)

ACTION_TYPES = (
    "set_category",
    "set_subcategory",
    "notify",
    "telegram_notify",
    "mark_review",
    "add_insight",
    "goal_allocation_hint",
)

EVENT_TRANSACTION = "transaction_created"
EVENT_SNAPSHOT = "account_snapshot"
EVENT_SALARY = "salary_received"

MAX_ACTIONS_PER_EVENT = 8
MAX_RULES_PER_EVENT = 20


def normalize_condition(raw: dict | None) -> dict | None:
    if not isinstance(raw, dict):
        return None
    kind = str(raw.get("type") or "").strip()
    if kind not in CONDITION_TYPES:
        return None
    return {
        "type": kind,
        "value": raw.get("value"),
        "account_id": str(raw.get("account_id") or "") or None,
    }


def normalize_action(raw: dict | None) -> dict | None:
    if not isinstance(raw, dict):
        return None
    kind = str(raw.get("type") or "").strip()
    if kind not in ACTION_TYPES:
        return None
    if kind in {"set_category", "set_subcategory"} and not str(raw.get("code") or "").strip():
        return None
    return {
        "type": kind,
        "code": str(raw.get("code") or "").strip() or None,
        "name": str(raw.get("name") or "").strip() or None,
        "message": str(raw.get("message") or "").strip() or None,
        "title": str(raw.get("title") or "").strip() or None,
    }


def looks_like_salary(event: dict) -> bool:
    if event.get("event_type") == EVENT_SALARY:
        return True
    tx_type = str(event.get("tx_type") or event.get("type") or "").lower()
    if tx_type != "credit":
        return False
    blob = " ".join(
        [
            str(event.get("description") or ""),
            str(event.get("merchant") or ""),
            str((event.get("category") or {}).get("name") or ""),
            str((event.get("category") or {}).get("code") or ""),
        ]
    ).lower()
    return "salary" in blob or "payroll" in blob or blob.startswith("income")


def _merchant_blob(event: dict) -> str:
    return " ".join(
        [
            str(event.get("merchant") or ""),
            str(event.get("description") or ""),
            str(event.get("narration") or ""),
        ]
    ).lower()


def condition_matches(condition: dict, event: dict) -> bool:
    kind = condition.get("type")
    value = condition.get("value")
    if kind == "merchant_contains":
        needle = str(value or "").strip().lower()
        return bool(needle) and needle in _merchant_blob(event)
    if kind == "amount_gte":
        try:
            return round_money(event.get("amount")) >= float(value)
        except (TypeError, ValueError):
            return False
    if kind == "amount_lte":
        try:
            return round_money(event.get("amount")) <= float(value)
        except (TypeError, ValueError):
            return False
    if kind == "amount_eq":
        try:
            return abs(round_money(event.get("amount")) - float(value)) < 0.005
        except (TypeError, ValueError):
            return False
    if kind == "account_id":
        expected = str(condition.get("account_id") or value or "")
        actual = str(event.get("account_id") or "")
        return bool(expected) and expected == actual
    if kind == "category_code":
        expected = str(value or "").strip().lower()
        cat = event.get("category") or {}
        return expected in {
            str(cat.get("code") or "").lower(),
            str(cat.get("name") or "").lower(),
        }
    if kind == "tx_type":
        expected = str(value or "").strip().lower()
        actual = str(event.get("tx_type") or event.get("type") or "").lower()
        return bool(expected) and expected == actual
    if kind == "balance_lt":
        try:
            balance = event.get("balance")
            if balance is None:
                return False
            return float(balance) < float(value)
        except (TypeError, ValueError):
            return False
    if kind == "utilization_gt":
        try:
            util = event.get("utilization")
            if util is None:
                return False
            return float(util) > float(value)
        except (TypeError, ValueError):
            return False
    if kind == "due_within_days":
        try:
            days = int(value)
        except (TypeError, ValueError):
            return False
        due = event.get("due_date")
        today = event.get("today")
        due_d = _as_date(due)
        today_d = _as_date(today) or date.today()
        if not due_d:
            return False
        delta = (due_d - today_d).days
        return 0 <= delta <= days
    if kind == "is_recurring":
        wanted = bool(value) if value is not None else True
        return bool(event.get("is_recurring") or event.get("recurring_id")) == wanted
    if kind == "salary_received":
        return looks_like_salary(event)
    return False


def rule_matches(rule: dict, event: dict) -> bool:
    conditions = [c for c in (rule.get("conditions") or []) if isinstance(c, dict)]
    if not conditions:
        return False
    return all(condition_matches(c, event) for c in conditions)


def would_loop(*, rule: dict, event: dict, applied_rule_ids: list[str] | None) -> bool:
    """Skip a rule that already ran on this record, or that would re-enter itself."""
    rule_id = str(rule.get("id") or rule.get("_id") or "")
    applied = {str(x) for x in (applied_rule_ids or [])}
    if rule_id and rule_id in applied:
        return True
    if event.get("source") == "financial_rule":
        return True
    if event.get("caused_by_rule_id") and str(event.get("caused_by_rule_id")) == rule_id:
        return True
    return False


def select_rules_for_event(rules: list[dict], event: dict) -> list[dict]:
    ranked = sorted(
        [r for r in rules if r.get("enabled", True)],
        key=lambda item: (-int(item.get("priority") or 0), str(item.get("id") or "")),
    )
    chosen: list[dict] = []
    applied = list(event.get("applied_rule_ids") or [])
    for rule in ranked:
        if len(chosen) >= MAX_RULES_PER_EVENT:
            break
        if would_loop(rule=rule, event=event, applied_rule_ids=applied):
            continue
        if not rule_matches(rule, event):
            continue
        chosen.append(rule)
        rid = str(rule.get("id") or rule.get("_id") or "")
        if rid:
            applied.append(rid)
    return chosen


def actions_for_rules(rules: list[dict]) -> list[dict]:
    actions: list[dict] = []
    for rule in rules:
        for action in rule.get("actions") or []:
            if len(actions) >= MAX_ACTIONS_PER_EVENT:
                return actions
            normalized = normalize_action(action)
            if not normalized:
                continue
            normalized["rule_id"] = str(rule.get("id") or rule.get("_id") or "")
            normalized["rule_name"] = str(rule.get("name") or "Rule")
            actions.append(normalized)
    return actions


def snapshot_dedupe_key(*, rule_id: str, event_type: str, day_key: str, account_id: str | None) -> str:
    return f"{rule_id}:{event_type}:{day_key}:{account_id or '-'}"


def _as_date(value) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value:
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None
