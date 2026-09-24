"""Goals funded by linked investments: math, linking rules, contribution totals."""

import unittest
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

from bson import ObjectId

from app.core.errors import NotFoundError, ValidationError
from app.helpers.goal_math import goal_health, monthly_equivalent, summarize_goal_links
from app.services import goal_links
from tests.fake_mongo import FakeDb

TODAY = date(2026, 9, 24)


def _dt(y, m, d):
    return datetime(y, m, d, 12, tzinfo=timezone.utc)


class TestGoalMath(unittest.TestCase):
    def test_monthly_equivalent_handles_frequency_and_interval(self):
        self.assertEqual(monthly_equivalent(5000, "monthly"), 5000.0)
        self.assertEqual(monthly_equivalent(30000, "quarterly"), 10000.0)
        self.assertEqual(monthly_equivalent(12000, "yearly"), 1000.0)
        self.assertEqual(monthly_equivalent(10000, "monthly", 2), 5000.0)
        self.assertEqual(monthly_equivalent(1200, "weekly"), 5200.0)
        self.assertEqual(monthly_equivalent(100, "unknown"), 0.0)

    def test_summary_totals_and_pace_prefer_active_recurring(self):
        sip, rd = ObjectId(), ObjectId()
        rules = [
            {"_id": sip, "description": "Nifty SIP", "amount": 5000, "frequency": "monthly", "is_active": True},
            {"_id": rd, "description": "Old RD", "amount": 2000, "frequency": "monthly", "is_active": False, "paused_at": _dt(2026, 1, 1)},
        ]
        contributions = [
            {"_id": ObjectId(), "amount": 5000, "created_at": _dt(2026, 7, 5), "recurring_id": sip},
            {"_id": ObjectId(), "amount": 5000, "created_at": _dt(2026, 8, 5), "recurring_id": sip},
            {"_id": ObjectId(), "amount": 2000, "created_at": _dt(2025, 12, 5), "recurring_id": rd},
            {"_id": ObjectId(), "amount": 25000, "created_at": _dt(2026, 6, 1), "description": "FD"},
        ]
        s = summarize_goal_links(linked_rules=rules, contributions=contributions, today=TODAY)
        self.assertEqual(s["invested_total"], 37000.0)
        self.assertEqual(s["recurring_total"], 12000.0)
        self.assertEqual(s["one_time_total"], 25000.0)
        # Paused RD doesn't count towards the monthly commitment.
        self.assertEqual(s["monthly_commitment"], 5000.0)
        self.assertEqual(s["linked_pace"], 5000.0)
        by_id = {r["id"]: r for r in s["rules"]}
        self.assertEqual(by_id[str(sip)]["posted_count"], 2)
        self.assertEqual(by_id[str(rd)]["status"], "paused")
        self.assertEqual(s["recent"][0]["amount"], 5000.0)  # newest first

    def test_one_time_only_pace_averages_last_six_months(self):
        contributions = [
            {"_id": ObjectId(), "amount": 60000, "created_at": _dt(2026, 5, 1)},   # in window (Apr–Sep)
            {"_id": ObjectId(), "amount": 90000, "created_at": _dt(2025, 1, 1)},   # outside window
        ]
        s = summarize_goal_links(linked_rules=[], contributions=contributions, today=TODAY)
        self.assertEqual(s["invested_total"], 150000.0)
        self.assertEqual(s["linked_pace"], 10000.0)

    def test_goal_health(self):
        self.assertEqual(goal_health(status="active", completed=True, on_track=None, has_target_date=True)[0], "done")
        self.assertEqual(goal_health(status="paused", completed=False, on_track=True, has_target_date=True)[0], "paused")
        self.assertEqual(goal_health(status="active", completed=False, on_track=False, has_target_date=True)[0], "behind")
        self.assertEqual(goal_health(status="active", completed=False, on_track=None, has_target_date=False)[1], "No deadline")


class GoalLinksDbCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.uid = ObjectId()
        self.other_uid = ObjectId()
        self.goal_a, self.goal_b = ObjectId(), ObjectId()
        self.sip = ObjectId()
        self.foreign_rule = ObjectId()
        self.fd = ObjectId()
        self.instalment = ObjectId()
        now = datetime.now(timezone.utc)
        self.db = FakeDb(
            financial_goals=[
                {"_id": self.goal_a, "user_id": self.uid, "status": "active", "linked_recurring_ids": [], "linked_transaction_ids": []},
                {"_id": self.goal_b, "user_id": self.uid, "status": "active", "linked_recurring_ids": [self.sip], "linked_transaction_ids": []},
            ],
            recurring_deposits=[
                {"_id": self.sip, "user_id": self.uid, "description": "SIP", "amount": 5000, "frequency": "monthly",
                 "is_active": True, "ended_at": None, "account_id": ObjectId(),
                 "category": {"code": "investments_expense", "name": "Investments"}, "subcategory": {"code": "sip", "name": "SIP"}},
                {"_id": self.foreign_rule, "user_id": self.other_uid, "amount": 1, "frequency": "monthly", "ended_at": None},
            ],
            transactions=[
                {"_id": self.fd, "user_id": self.uid, "amount": 50000, "created_at": now - timedelta(days=10),
                 "deleted_at": None, "recurring_id": None, "description": "FD",
                 "category": {"code": "investments_expense"}, "subcategory": {"code": "fixed_deposit", "name": "Fixed Deposit"}},
                {"_id": self.instalment, "user_id": self.uid, "amount": 5000, "created_at": now - timedelta(days=5),
                 "deleted_at": None, "recurring_id": self.sip, "description": "SIP"},
                {"_id": ObjectId(), "user_id": self.uid, "amount": 5000, "created_at": now - timedelta(days=35),
                 "deleted_at": now, "recurring_id": self.sip, "description": "SIP (deleted)"},
                {"_id": ObjectId(), "user_id": self.uid, "amount": 5000, "created_at": now - timedelta(days=65),
                 "deleted_at": None, "is_failed": True, "recurring_id": self.sip, "description": "SIP (failed)"},
            ],
            accounts=[],
        )
        p = patch.object(goal_links, "db", self.db)
        p.start()
        self.addCleanup(p.stop)

    def goal(self, oid):
        return next(g for g in self.db.financial_goals.docs if g["_id"] == oid)


class TestSetGoalLinks(GoalLinksDbCase):
    async def test_linking_moves_item_from_other_goal(self):
        await goal_links.set_goal_links(str(self.uid), str(self.goal_a), recurring_ids=[str(self.sip)], transaction_ids=[str(self.fd)])
        self.assertEqual(self.goal(self.goal_a)["linked_recurring_ids"], [self.sip])
        self.assertEqual(self.goal(self.goal_a)["linked_transaction_ids"], [self.fd])
        self.assertEqual(self.goal(self.goal_b)["linked_recurring_ids"], [])

    async def test_rejects_other_users_rule(self):
        with self.assertRaises(ValidationError):
            await goal_links.set_goal_links(str(self.uid), str(self.goal_a), recurring_ids=[str(self.foreign_rule)])

    async def test_rejects_individual_recurring_instalment(self):
        with self.assertRaises(ValidationError):
            await goal_links.set_goal_links(str(self.uid), str(self.goal_a), transaction_ids=[str(self.instalment)])

    async def test_rejects_unknown_goal(self):
        with self.assertRaises(NotFoundError):
            await goal_links.set_goal_links(str(self.other_uid), str(self.goal_a), recurring_ids=[])

    async def test_empty_selection_unlinks_everything(self):
        await goal_links.set_goal_links(str(self.uid), str(self.goal_b))
        self.assertEqual(self.goal(self.goal_b)["linked_recurring_ids"], [])


class TestContributions(GoalLinksDbCase):
    async def test_only_posted_instalments_and_linked_one_time_count(self):
        goals = [
            {"id": str(self.goal_a), "linked_recurring_ids": [], "linked_transaction_ids": [str(self.fd)]},
            {"id": str(self.goal_b), "linked_recurring_ids": [str(self.sip)], "linked_transaction_ids": []},
            {"id": "unlinked", "linked_recurring_ids": [], "linked_transaction_ids": []},
        ]
        out = await goal_links.load_goal_contributions(self.uid, goals, today=TODAY)
        self.assertEqual(out[str(self.goal_a)]["invested_total"], 50000.0)
        # Deleted and failed SIP runs are excluded.
        self.assertEqual(out[str(self.goal_b)]["invested_total"], 5000.0)
        self.assertEqual(out[str(self.goal_b)]["monthly_commitment"], 5000.0)
        self.assertNotIn("unlinked", out)

    async def test_candidates_flag_investments_and_owner(self):
        c = await goal_links.list_link_candidates(str(self.uid))
        rule = next(r for r in c["recurring"] if r["id"] == str(self.sip))
        self.assertTrue(rule["is_investment"])
        self.assertEqual(rule["linked_goal_id"], str(self.goal_b))
        self.assertEqual([t["id"] for t in c["one_time"]], [str(self.fd)])
        # Other users' rules never leak into candidates.
        self.assertNotIn(str(self.foreign_rule), [r["id"] for r in c["recurring"]])


if __name__ == "__main__":
    unittest.main()
