"""Goals page renders every tracking mode through the real handler + templates."""

import re
import unittest
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, patch

from bson import ObjectId
from starlette.requests import Request

from app.web import planning as web_planning
from tests.fake_mongo import FakeDb

UID = ObjectId()
ACCOUNT = ObjectId()


def _request(query: str = "") -> Request:
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "GET",
            "path": "/planning/goals",
            "raw_path": b"/planning/goals",
            "query_string": query.encode(),
            "headers": [(b"accept", b"text/html")],
            "client": ("127.0.0.1", 1),
            "server": ("testserver", 80),
            "scheme": "http",
            "session": {"user": {"user_id": str(UID), "username": "admin", "is_admin": True}},
            "state": {"maintenance_mode": False, "maintenance_message": "", "telegram_default_country": "IN"},
        }
    )


def _goal(**over):
    base = {
        "id": str(ObjectId()),
        "name": "Emergency Fund",
        "goal_type": "emergency_fund",
        "target_amount": 200000.0,
        "current_amount": 86000.0,
        "starting_amount": 50000.0,
        "remaining": 114000.0,
        "progress_pct": 43.0,
        "target_date": date(2028, 3, 1),
        "required_monthly": 6333.33,
        "monthly_pace": 5000.0,
        "eta_label": "At your current savings pace, estimated completion is May 2028.",
        "on_track": False,
        "completed": False,
        "status": "active",
        "linked_account_id": None,
        "notes": "",
        "linked_recurring_ids": [],
        "linked_transaction_ids": [],
        "tracking": "investments",
        "pace_source": "linked",
        "health": "behind",
        "health_label": "Behind",
        "links": {
            "has_links": True,
            "invested_total": 36000.0,
            "one_time_total": 25000.0,
            "one_time_count": 1,
            "monthly_commitment": 5000.0,
            "rules": [{"id": "r1", "name": "Nifty 50 SIP", "status": "active", "monthly_equivalent": 5000.0, "posted_count": 2}],
            "recent": [{"amount": 5000.0, "date": datetime(2026, 9, 5, tzinfo=timezone.utc), "description": "Nifty 50 SIP", "source": "recurring"}],
        },
    }
    base.update(over)
    return base


CANDIDATES = {
    "recurring": [
        {"id": "r1", "name": "Nifty 50 SIP", "amount": 5000.0, "frequency_label": "Monthly", "monthly_equivalent": 5000.0,
         "status": "active", "account_name": "HDFC", "category": "SIP", "is_investment": True, "linked_goal_id": None},
        {"id": "r2", "name": "Rent", "amount": 20000.0, "frequency_label": "Monthly", "monthly_equivalent": 20000.0,
         "status": "active", "account_name": "HDFC", "category": "Rent", "is_investment": False, "linked_goal_id": None},
    ],
    "one_time": [
        {"id": "t1", "description": "FD <booked>", "amount": 25000.0, "date": datetime(2026, 6, 1, tzinfo=timezone.utc),
         "account_name": "HDFC", "category": "Fixed Deposit", "linked_goal_id": None},
    ],
}


class TestGoalsPage(unittest.IsolatedAsyncioTestCase):
    async def render(self, goals, query="", archived=None):
        fake_db = FakeDb(users=[{"_id": UID, "deleted_at": None, "is_active": True, "session_epoch": 0}])
        patches = [
            patch("app.core.guards.db", fake_db),
            patch.object(web_planning, "build_planning_bundle", new=AsyncMock(return_value={"goals": goals})),
            patch.object(web_planning, "get_accounts", new=AsyncMock(return_value=[{"_id": ACCOUNT, "name": "Savings", "type": "savings"}])),
            patch.object(web_planning, "list_link_candidates", new=AsyncMock(return_value=CANDIDATES)),
            patch.object(web_planning, "get_user_notifications", new=AsyncMock(return_value=[])),
            patch.object(web_planning, "list_goals", new=AsyncMock(return_value=archived or [])),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        status = dict(pair.split("=") for pair in query.split("&") if pair).get("status", "all")
        response = await web_planning.goals_page(_request(query), status=status)
        self.assertEqual(response.status_code, 200)
        return response.body.decode()

    async def test_renders_all_tracking_modes(self):
        html = await self.render(
            [
                _goal(),
                _goal(name="Car", goal_type="car", tracking="account", linked_account_id=str(ACCOUNT),
                      pace_source="overall", links=None, health="on_track", health_label="On track", on_track=True),
                _goal(name="Laptop", goal_type="laptop", tracking="manual", pace_source="overall",
                      links=None, health="neutral", health_label="No deadline", target_date=None, on_track=None),
            ]
        )
        self.assertIn("Nifty 50 SIP", html)
        self.assertIn("Invested ₹ 36,000.00", html)
        self.assertIn("Already saved ₹ 50,000.00", html)
        self.assertIn("Progress follows the balance of <strong>Savings</strong>", html)
        self.assertIn("Link a SIP, RD or lump-sum investment", html)  # manual goal empty-link CTA
        self.assertIn('class="gol-badge is-behind"', html)
        # Candidate text is escaped; goal data goes through a JSON script tag.
        self.assertIn("FD &lt;booked&gt;", html)
        self.assertIsNotNone(re.search(r'<script type="application/json" id="goals-data">\{.*"Emergency Fund"', html, re.S))
        # Non-investment rules are available but hidden behind "Show all".
        self.assertIn("Show all recurring rules (1 not categorised as investments)", html)

    async def test_empty_state(self):
        html = await self.render([])
        self.assertIn("Set your first goal", html)

    async def test_archived_tab_offers_restore(self):
        archived = [{"id": str(ObjectId()), "name": "Old trip", "goal_type": "vacation", "target_amount": 1000.0, "status": "archived"}]
        html = await self.render([], query="status=archived", archived=archived)
        self.assertIn("Old trip", html)
        self.assertIn("Restore", html)


if __name__ == "__main__":
    unittest.main()
