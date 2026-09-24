"""Unit tests for recurring page grouping, filters, and labels."""

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from app.helpers.recurring_ui import (
    build_recurring_columns,
    compute_recurring_stats,
    enrich_recurring_rule,
    filter_recurring_rules,
    frequency_label,
    relative_due_label,
)

TZ = ZoneInfo("Asia/Kolkata")
TODAY = date(2026, 8, 12)


def _rule(
    *,
    rid: str,
    status: str = "active",
    tx_type: str = "debit",
    amount: float = 500,
    next_day: date | None = None,
    description: str = "Rent",
    account_id: str = "acc-1",
    account_name: str = "ICICI",
    frequency: str = "monthly",
    interval: int = 1,
) -> dict:
    next_run = None
    if next_day:
        next_run = datetime(next_day.year, next_day.month, next_day.day, 0, 0, tzinfo=timezone.utc)
    return {
        "id": rid,
        "account_id": account_id,
        "account_name": account_name,
        "bank_name": "",
        "type": tx_type,
        "mode": "upi",
        "amount": amount,
        "description": description,
        "category": {"code": "bills", "name": "Bills"},
        "subcategory": {"code": "other", "name": "Other"},
        "frequency": frequency,
        "interval": interval,
        "next_run": next_run,
        "last_run": None,
        "status": status,
    }


def test_frequency_and_relative_labels():
    assert frequency_label("monthly", 1) == "Monthly"
    assert frequency_label("monthly", 2) == "Every 2 months"
    assert relative_due_label(TODAY, TODAY) == ("Due today", False)
    assert relative_due_label(date(2026, 8, 10), TODAY) == ("2 days overdue", True)
    assert relative_due_label(date(2026, 8, 13), TODAY) == ("Tomorrow", False)


def test_columns_split_soon_scheduled_and_inactive():
    rules = [
        enrich_recurring_rule(
            _rule(rid="1", description="Soon", next_day=date(2026, 8, 15)),
            user_tz=TZ,
            today=TODAY,
        ),
        enrich_recurring_rule(
            _rule(rid="2", description="Later", next_day=date(2026, 9, 12), amount=1000),
            user_tz=TZ,
            today=TODAY,
        ),
        enrich_recurring_rule(
            _rule(rid="3", description="Hold", status="paused", next_day=date(2026, 8, 20)),
            user_tz=TZ,
            today=TODAY,
        ),
        enrich_recurring_rule(
            _rule(rid="4", description="Done", status="ended", tx_type="credit", amount=200),
            user_tz=TZ,
            today=TODAY,
        ),
    ]

    cols = {c["id"]: c for c in build_recurring_columns(rules, user_tz=TZ, today=TODAY)}

    assert cols["soon"]["count"] == 1
    assert cols["soon"]["rows"][0]["display_title"] == "Soon"
    assert cols["soon"]["expense"] == 500

    assert cols["scheduled"]["count"] == 1
    assert cols["scheduled"]["rows"][0]["display_title"] == "Later"

    assert cols["inactive"]["count"] == 2
    assert [item["display_title"] for item in cols["inactive"]["rows"]] == ["Hold", "Done"]


def test_overdue_counts_as_due_soon():
    rule = enrich_recurring_rule(
        _rule(rid="late", next_day=date(2026, 8, 1)),
        user_tz=TZ,
        today=TODAY,
    )
    assert rule["is_overdue"] is True
    assert rule["column_id"] == "soon"


def test_filters_and_stats():
    rules = [
        _rule(rid="a", tx_type="debit", amount=500, next_day=date(2026, 8, 15), description="Rent"),
        _rule(
            rid="b",
            tx_type="credit",
            amount=2000,
            next_day=date(2026, 8, 18),
            description="Salary",
            account_id="acc-2",
            account_name="HDFC",
        ),
        _rule(rid="c", status="paused", amount=100, next_day=date(2026, 8, 18), description="Gym"),
    ]

    stats = compute_recurring_stats(rules, user_tz=TZ, today=TODAY)
    assert stats["active"] == 2
    assert stats["paused"] == 1
    assert stats["due_soon"] == 2
    assert stats["month_out"] == 500
    assert stats["month_in"] == 2000

    only_income = filter_recurring_rules(rules, tx_type="credit")
    assert [r["id"] for r in only_income] == ["b"]

    search_rent = filter_recurring_rules(rules, search="rent")
    assert [r["id"] for r in search_rent] == ["a"]

    search_salary = filter_recurring_rules(rules, search="salary")
    assert [r["id"] for r in search_salary] == ["b"]


def test_month_stats_include_due_soon_next_month_and_income_alias():
    today = date(2026, 9, 24)
    rules = [
        enrich_recurring_rule(
            _rule(rid="sip", tx_type="expense", amount=1000, next_day=date(2026, 9, 12), description="SIP"),
            user_tz=TZ,
            today=today,
        ),
        enrich_recurring_rule(
            _rule(rid="pay", tx_type="income", amount=145780, next_day=date(2026, 10, 1), description="Salary"),
            user_tz=TZ,
            today=today,
        ),
        enrich_recurring_rule(
            _rule(rid="xfer", tx_type="transfer", amount=5000, next_day=date(2026, 9, 29), description="Move"),
            user_tz=TZ,
            today=today,
        ),
        enrich_recurring_rule(
            _rule(rid="later", tx_type="debit", amount=100, next_day=date(2026, 10, 4), description="Later"),
            user_tz=TZ,
            today=today,
        ),
    ]
    stats = compute_recurring_stats(rules, user_tz=TZ, today=today)
    assert stats["month_out"] == 1000
    assert stats["month_in"] == 145780
    assert stats["month_transfer"] == 5000
    assert stats["due_soon"] == 3
