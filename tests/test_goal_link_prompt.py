"""Post-save "link this investment to a goal?" prompt."""

import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

from bson import ObjectId

from app.core.errors import ValidationError
from app.helpers.goal_prompt import GOAL_PROMPT_KEY, pop_goal_prompt, set_goal_prompt
from app.services import goal_links
from app.web import planning as web_planning
from app.web import transactions as web_transactions
from tests.fake_mongo import FakeDb
from tests.test_goals_page import _request

INVEST = {"code": "investments_expense", "name": "Investments"}
SIP = {"code": "sip", "name": "SIP"}
FOOD = {"code": "food", "name": "Food"}


class PromptDbCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.uid = ObjectId()
        self.bank, self.demat = ObjectId(), ObjectId()
        self.goal, self.acct_goal, self.done_goal = ObjectId(), ObjectId(), ObjectId()
        self.sip_tx, self.food_tx, self.failed_tx = ObjectId(), ObjectId(), ObjectId()
        self.transfer_id, self.rule = ObjectId(), ObjectId()
        now = datetime.now(timezone.utc)
        base = {"user_id": self.uid, "deleted_at": None, "created_at": now, "amount": 5000.0}
        self.db = FakeDb(
            financial_goals=[
                {"_id": self.goal, "user_id": self.uid, "name": "House", "status": "active", "created_at": now,
                 "linked_recurring_ids": [], "linked_transaction_ids": [ObjectId()]},
                {"_id": self.acct_goal, "user_id": self.uid, "name": "Car", "status": "active", "created_at": now,
                 "linked_account_id": self.bank},
                {"_id": self.done_goal, "user_id": self.uid, "name": "Old", "status": "completed", "created_at": now},
            ],
            accounts=[
                {"_id": self.bank, "user_id": self.uid, "type": "savings"},
                {"_id": self.demat, "user_id": self.uid, "type": "investment"},
            ],
            transactions=[
                {**base, "_id": self.sip_tx, "account_id": self.bank, "type": "debit", "category": INVEST, "subcategory": SIP, "description": "Nifty SIP"},
                {**base, "_id": self.food_tx, "account_id": self.bank, "type": "debit", "category": FOOD, "subcategory": {"code": "groceries"}},
                {**base, "_id": self.failed_tx, "account_id": self.bank, "type": "debit", "category": INVEST, "is_failed": True},
                {**base, "_id": ObjectId(), "transfer_id": self.transfer_id, "account_id": self.bank, "type": "transfer_out", "category": {"code": "transfer"}},
                {**base, "_id": ObjectId(), "transfer_id": self.transfer_id, "account_id": self.demat, "type": "transfer_in", "category": {"code": "transfer"}},
            ],
            recurring_deposits=[
                {"_id": self.rule, "user_id": self.uid, "account_id": self.bank, "type": "debit", "amount": 3000.0,
                 "frequency": "monthly", "interval": 1, "category": INVEST, "subcategory": SIP, "description": "ELSS SIP", "ended_at": None},
            ],
        )
        p = patch.object(goal_links, "db", self.db)
        p.start()
        self.addCleanup(p.stop)


class TestPromptEligibility(PromptDbCase):
    async def test_investment_transaction_prompts_with_linkable_goals_only(self):
        payload = await goal_links.goal_prompt_for_new_entry(str(self.uid), transaction_ref=self.sip_tx)
        self.assertEqual(payload["transaction_id"], str(self.sip_tx))
        self.assertEqual(payload["label"], "Nifty SIP")
        # Account-tracked and completed goals are not offered.
        self.assertEqual([g["name"] for g in payload["goals"]], ["House"])

    async def test_non_investment_and_failed_rows_do_not_prompt(self):
        self.assertIsNone(await goal_links.goal_prompt_for_new_entry(str(self.uid), transaction_ref=self.food_tx))
        self.assertIsNone(await goal_links.goal_prompt_for_new_entry(str(self.uid), transaction_ref=self.failed_tx))

    async def test_transfer_into_investment_account_links_incoming_leg(self):
        payload = await goal_links.goal_prompt_for_new_entry(str(self.uid), transaction_ref=self.transfer_id)
        leg = next(t for t in self.db.transactions.docs if t.get("type") == "transfer_in")
        self.assertEqual(payload["transaction_id"], str(leg["_id"]))

    async def test_recurring_rule_prompt(self):
        payload = await goal_links.goal_prompt_for_new_entry(str(self.uid), recurring_id=self.rule)
        self.assertEqual(payload["recurring_id"], str(self.rule))
        self.assertEqual(payload["frequency_label"], "Monthly")
        self.assertEqual(payload["amount"], 3000.0)

    async def test_only_account_tracked_goals_still_prompts_with_explanation(self):
        self.db.financial_goals.docs = [g for g in self.db.financial_goals.docs if g["_id"] != self.goal]
        payload = await goal_links.goal_prompt_for_new_entry(str(self.uid), transaction_ref=self.sip_tx)
        self.assertEqual(payload["goals"], [])
        self.assertEqual(payload["account_goals"], ["Car"])
        # The session helper keeps an explanation-only prompt.
        req = _request()
        set_goal_prompt(req, payload)
        self.assertIsNotNone(pop_goal_prompt(req))

    async def test_no_open_goals_no_prompt(self):
        self.db.financial_goals.docs = [g for g in self.db.financial_goals.docs if g["status"] == "completed"]
        self.assertIsNone(await goal_links.goal_prompt_for_new_entry(str(self.uid), transaction_ref=self.sip_tx))

    async def test_mixed_goals_lists_account_goals_separately(self):
        payload = await goal_links.goal_prompt_for_new_entry(str(self.uid), transaction_ref=self.sip_tx)
        self.assertEqual(payload["account_goals"], ["Car"])


class TestAddGoalLinks(PromptDbCase):
    async def test_adds_without_dropping_existing_links(self):
        existing = self.db.financial_goals.docs[0]["linked_transaction_ids"][0]
        self.db.transactions.docs.append({"_id": existing, "user_id": self.uid, "deleted_at": None, "amount": 1.0})
        result = await goal_links.add_goal_links(str(self.uid), str(self.goal), transaction_ids=[str(self.sip_tx)])
        self.assertEqual(result["goal_name"], "House")
        self.assertEqual(set(result["transaction_ids"]), {str(existing), str(self.sip_tx)})

    async def test_rejects_completed_and_account_tracked_goals(self):
        with self.assertRaises(ValidationError):
            await goal_links.add_goal_links(str(self.uid), str(self.done_goal), transaction_ids=[str(self.sip_tx)])
        with self.assertRaises(ValidationError):
            await goal_links.add_goal_links(str(self.uid), str(self.acct_goal), transaction_ids=[str(self.sip_tx)])


class TestPromptPlumbing(unittest.IsolatedAsyncioTestCase):
    def test_session_prompt_is_one_shot(self):
        req = _request()
        set_goal_prompt(req, {"transaction_id": "t", "goals": [{"id": "g", "name": "G"}]})
        self.assertIsNotNone(pop_goal_prompt(req))
        self.assertIsNone(pop_goal_prompt(req))

    async def test_queue_swallows_errors_and_sets_payload(self):
        req = _request()
        with patch.object(web_transactions, "goal_prompt_for_new_entry", new=AsyncMock(side_effect=RuntimeError("db down"))):
            await web_transactions._queue_goal_link_prompt(req, user_id="u", transaction_ref="t", recurring_id=None)
        self.assertNotIn(GOAL_PROMPT_KEY, req.session)
        payload = {"transaction_id": "t", "goals": [{"id": "g", "name": "G"}]}
        with patch.object(web_transactions, "goal_prompt_for_new_entry", new=AsyncMock(return_value=payload)):
            await web_transactions._queue_goal_link_prompt(req, user_id="u", transaction_ref="t", recurring_id=None)
        self.assertEqual(req.session[GOAL_PROMPT_KEY], payload)

    def test_prompt_template_explains_account_tracked_goals(self):
        from app.web.templates import templates

        req = _request()
        base = {"transaction_id": "t", "recurring_id": None, "label": "FD", "amount": 10000.0, "frequency_label": None}
        html = templates.env.get_template("layout/goal-link-prompt.html").render(
            request=req, goal_prompt={**base, "goals": [], "account_goals": ["Emergency Funds"]}
        )
        self.assertIn("“Emergency Funds” tracks", html)
        self.assertIn('href="/planning/goals"', html)
        self.assertNotIn('name="goal_id"', html)
        html = templates.env.get_template("layout/goal-link-prompt.html").render(
            request=req, goal_prompt={**base, "goals": [{"id": "g", "name": "House"}], "account_goals": ["Emergency Funds"]}
        )
        self.assertIn('name="goal_id"', html)
        self.assertIn("Not listed: Emergency Funds", html)

    def test_safe_next_blocks_open_redirects(self):
        self.assertEqual(web_planning._safe_next("/transactions/list?view=board"), "/transactions/list?view=board")
        for bad in ("https://evil.com", "//evil.com", "/\\evil.com", "", None):
            self.assertEqual(web_planning._safe_next(bad), "/planning/goals")


if __name__ == "__main__":
    unittest.main()
