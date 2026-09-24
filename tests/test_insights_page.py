"""Single Insights page: feed ranking/dedupe, health drivers, cash outlook, redirects."""

import json
import re
import unittest
from datetime import date, timedelta
from html import unescape
from unittest.mock import AsyncMock, patch


from app.helpers.insights_ui import (
    build_attention_feed,
    build_health_rows,
    missing_health_dimensions,
    summarize_month,
    summarize_outlook,
)
from app.web import planning as web_planning
from tests.fake_mongo import FakeDb
from tests.test_goals_page import UID, _request

TODAY = date(2026, 9, 24)

INSIGHTS = [
    {"key": "dining_up", "category": "attention", "title": "Dining out is up 40% this month.", "detail": "₹8,400 vs ₹6,000 usual.", "priority": 30},
    {"key": "savings_good", "category": "positive", "title": "You saved 25% of income.", "detail": "Above your 3-month average.", "priority": 40},
    {"key": "cash_low", "category": "warning", "title": "Cash may run short before payday.", "detail": "Lowest ₹-2,000 on 28 Sep.", "priority": 10},
]
RECS = [
    {"key": "util_high", "tone": "attention", "title": "Credit utilization is approaching a high range.", "evidence": "72% of limits used.", "href": "/accounts?group=card", "priority": 5},
    # Same message as an insight: must not appear twice.
    {"key": "dup", "tone": "info", "title": "Dining out is up 40% this month!", "evidence": "dup", "href": "/insights", "priority": 1},
]


def _forecast(lowest, start=50000.0):
    daily = [{"date": TODAY + timedelta(days=i), "balance": start - i * 100, "events": [{"label": "Rent's due"}]} for i in range(91)]
    return {
        "today_balance": start,
        "horizons": {"30": start - 3000, "60": start - 6000, "90": start - 9000},
        "lowest_balance": lowest,
        "lowest_date": TODAY + timedelta(days=12),
        "daily": daily,
        "contributing_events": [
            {"label": "Salary", "amount": 80000.0, "date": TODAY + timedelta(days=6), "certainty": "scheduled"},
            {"label": "Rent", "amount": -25000.0, "date": TODAY + timedelta(days=2), "certainty": "scheduled"},
        ],
    }


class TestInsightHelpers(unittest.TestCase):
    def test_feed_ranks_by_urgency_and_dedupes(self):
        feed = build_attention_feed(INSIGHTS, RECS)
        titles = [i["title"] for i in feed["attention"]]
        self.assertEqual(titles[0], "Cash may run short before payday.")  # warning first
        self.assertEqual(sum("Dining out" in t for t in titles), 1)
        self.assertEqual([i["key"] for i in feed["going_well"]], ["savings_good"])
        util = next(i for i in feed["attention"] if i["key"] == "util_high")
        self.assertEqual(util["href"], "/accounts?group=card")
        self.assertFalse(util["explainable"])

    def test_health_rows_weakest_first_with_tips_only_when_needed(self):
        rows = build_health_rows({"dimensions": {"savings": 82, "utilization": 35, "cash_buffer": 60, "emi": None}})
        self.assertEqual([r["key"] for r in rows], ["utilization", "cash_buffer", "savings"])
        self.assertEqual(rows[0]["tone"], "weak")
        self.assertTrue(rows[0]["tip"])
        self.assertEqual(rows[-1]["tip"], "")
        self.assertEqual(missing_health_dimensions({"dimensions": {"emi": None, "savings": 80}}), ["EMI burden"])

    def test_outlook_status_and_totals(self):
        self.assertEqual(summarize_outlook(_forecast(-2000), today=TODAY)["status"], "negative")
        self.assertEqual(summarize_outlook(_forecast(5000), today=TODAY)["status"], "tight")
        o = summarize_outlook(_forecast(30000), today=TODAY)
        self.assertEqual(o["status"], "healthy")
        self.assertEqual((o["inflow_30"], o["outflow_30"]), (80000.0, 25000.0))
        self.assertEqual(o["days_to_lowest"], 12)
        # Chart series carries no free text.
        self.assertEqual(set(o["chart"][0]), {"date", "balance"})


REPORT = {
    "cash_flow": {"income": 90000.0, "expense": 52000.0, "net": 38000.0, "savings_rate": 42.2,
                  "income_change_pct": -10.0, "expense_change_pct": 30.0, "prev_income": 100000.0, "prev_expense": 40000.0},
    "category_changes": [
        {"name": "Dining out", "current": 9000.0, "previous": 5000.0, "change_pct": 80.0},
        {"name": "Fuel", "current": 2000.0, "previous": 4000.0, "change_pct": -50.0},
    ],
}


class TestMonthSummary(unittest.TestCase):
    def test_tones_labels_and_split(self):
        m = summarize_month(REPORT, today=TODAY)
        self.assertEqual((m["period_label"], m["prev_label"], m["days_in_month"]), ("1–24 Sep", "Aug", 30))
        tiles = {t["key"]: t for t in m["tiles"]}
        self.assertEqual(tiles["spent"]["tone"], "bad")      # spending up is bad
        self.assertEqual(tiles["income"]["tone"], "bad")     # income down is bad
        self.assertEqual(tiles["saved"]["prev"], 60000.0)
        self.assertEqual([r["name"] for r in m["rising"]], ["Dining out"])
        self.assertEqual([r["name"] for r in m["falling"]], ["Fuel"])
        self.assertEqual(m["rising"][0]["width"], 100)

    def test_no_data(self):
        self.assertFalse(summarize_month({}, today=TODAY)["has_data"])


class TestInsightsPage(unittest.IsolatedAsyncioTestCase):
    async def render(self, bundle, recs=RECS):
        fake_db = FakeDb(users=[{"_id": UID, "deleted_at": None, "is_active": True, "session_epoch": 0}])
        patches = [
            patch("app.core.guards.db", fake_db),
            patch.object(web_planning, "build_planning_bundle", new=AsyncMock(return_value=bundle)),
            patch.object(web_planning, "get_user_notifications", new=AsyncMock(return_value=[])),
            patch("app.services.ai_finance.recommendations_for_user", new=AsyncMock(return_value=recs)),
            patch("app.services.chat_assistant.ai_available", return_value=False),
            patch.object(web_planning, "app_now", return_value=type("N", (), {"date": lambda self: TODAY})()),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        response = await web_planning.insights_page(_request())
        self.assertEqual(response.status_code, 200)
        return response.body.decode()

    async def test_full_page(self):
        bundle = {
            "insights": INSIGHTS,
            "health": {"score": 64, "band": "FAIR", "previous_score": 60,
                       "dimensions": {"savings": 82, "utilization": 35, "emi": None},
                       "reasons": ["+4 Savings performance improved"]},
            "health_history": [{"month": "2026-08", "score": 60}, {"month": "2026-09", "score": 64}],
            "forecast": _forecast(-2000),
            "today": TODAY, "month_income": 90000.0, "month_expense": 52000.0,
            "prev_month_income": 100000.0, "prev_month_expense": 40000.0, "savings_rate": 42.2,
            "category_changes": REPORT["category_changes"],
        }
        html = await self.render(bundle)
        for text in ("This month vs last month", "1–24 Sep compared with all of Aug", "Spending more on", "Dining out", "Spending less on"):
            self.assertIn(text, html)
        self.assertNotIn("Summarize my month", html)  # AI off
        for text in ("Needs attention", "Cash may run short before payday.", "What drives your health score",
                     "Credit utilization", "Keep card balances under 30%", "Not scored yet (no data): EMI burden",
                     "Cash may run out.", "Going well", "+4 vs last snapshot"):
            self.assertIn(text, html)
        self.assertNotIn("Ask FinTracker", html)
        self.assertIsNone(re.search(r"data-explain\s+data-key", html))  # AI off → no Explain buttons
        # Chart JSON survives HTML attribute escaping (apostrophes in labels can't break it).
        raw = re.search(r'data-forecast-daily="([^"]*)"', html).group(1)
        self.assertEqual(len(json.loads(unescape(raw))), 91)

    async def test_empty_state(self):
        html = await self.render({"insights": [], "health": {"score": None, "dimensions": {}}, "forecast": {}}, recs=[])
        self.assertIn("Nothing needs your attention right now.", html)
        self.assertIn("No outlook yet.", html)

    async def test_old_urls_redirect(self):
        fake_db = FakeDb(users=[{"_id": UID, "deleted_at": None, "is_active": True, "session_epoch": 0}])
        with patch("app.core.guards.db", fake_db):
            self.assertEqual((await web_planning.health_page(_request())).headers["location"], "/insights#health")
            self.assertEqual((await web_planning.forecast_page(_request())).headers["location"], "/insights#cash")
            self.assertEqual((await web_planning.ask_page(_request())).headers["location"], "/insights")
            self.assertEqual((await web_planning.review_page(_request())).headers["location"], "/insights#month")


if __name__ == "__main__":
    unittest.main()
