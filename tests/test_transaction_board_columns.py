"""Unit tests for transactions board column grouping."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from app.helpers.transaction_list_ui import build_board_columns


TZ = ZoneInfo("Asia/Kolkata")


def _tx(
    day: date,
    *,
    amount: float = 100.0,
    type_key: str = "debit",
    title: str = "Tx",
    today: date | None = None,
) -> dict:
    created = datetime(day.year, day.month, day.day, 12, 0, tzinfo=TZ).astimezone(timezone.utc)
    day_date_label = f"{day.day} {day.strftime('%b %Y')}"
    heading = None
    if today is not None:
        if day == today:
            heading = "Today"
        elif day == today - timedelta(days=1):
            heading = "Yesterday"
    return {
        "_id": f"{day.isoformat()}-{type_key}-{amount}",
        "amount": amount,
        "type_key": type_key,
        "local_date": day.isoformat(),
        "day_heading": heading,
        "day_date_label": day_date_label,
        "local_date_label": day_date_label,
        "display_title": title,
        "created_at": created,
    }


def test_board_columns_week_and_earlier(monkeypatch):
    # Wednesday so This Week has Mon slots beyond yesterday.
    class _FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            base = datetime(2026, 5, 20, 15, 0, tzinfo=TZ)
            return base if tz is None else base.astimezone(tz)

    monkeypatch.setattr("app.helpers.transaction_list_ui.datetime", _FixedDateTime)

    today = date(2026, 5, 20)
    yesterday = today - timedelta(days=1)
    week_monday = today - timedelta(days=today.weekday())
    earlier_day = week_monday - timedelta(days=1)
    too_old = today - timedelta(days=31)

    rows = [
        _tx(today, amount=50000, type_key="credit", title="Salary", today=today),
        _tx(yesterday, amount=150, type_key="debit", title="Food", today=today),
        _tx(week_monday, amount=1000, type_key="transfer", title="Move", today=today),
        _tx(earlier_day, amount=200, type_key="debit", title="Old", today=today),
        _tx(too_old, amount=999, type_key="debit", title="Excluded", today=today),
    ]

    cols = {c["id"]: c for c in build_board_columns(rows, TZ)}

    assert set(cols) == {"week", "earlier"}
    assert cols["week"]["count"] == 3
    assert cols["week"]["income"] == 50000
    assert cols["week"]["expense"] == 150
    assert cols["week"]["transfer"] == 1000
    assert cols["earlier"]["count"] == 1
    assert cols["earlier"]["expense"] == 200
    assert all(
        tx["display_title"] != "Excluded"
        for c in cols.values()
        for g in c["day_groups"]
        for tx in g["rows"]
    )


def test_board_columns_monday_keeps_sunday_in_earlier(monkeypatch):
    class _FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            base = datetime(2026, 5, 18, 10, 0, tzinfo=TZ)
            return base if tz is None else base.astimezone(tz)

    monkeypatch.setattr("app.helpers.transaction_list_ui.datetime", _FixedDateTime)

    monday = date(2026, 5, 18)
    sunday = date(2026, 5, 17)
    prev_friday = date(2026, 5, 15)

    cols = {
        c["id"]: c
        for c in build_board_columns(
            [
                _tx(monday, today=monday),
                _tx(sunday, today=monday),
                _tx(prev_friday, today=monday),
            ],
            TZ,
        )
    }

    assert cols["week"]["count"] == 1
    assert cols["earlier"]["count"] == 2
