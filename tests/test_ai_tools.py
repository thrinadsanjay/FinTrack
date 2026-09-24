import unittest

from app.helpers.ai_privacy import ALLOWED_TOOL_NAMES, authorize_tool_call
from app.helpers.rules_math import would_loop


class TestAiToolBoundaries(unittest.TestCase):
    def test_unknown_tool_rejected(self):
        self.assertEqual(
            authorize_tool_call(user_id="507f1f77bcf86cd799439011", name="eval_mongo"),
            {"error": "unknown_tool"},
        )

    def test_empty_user_rejected(self):
        self.assertEqual(authorize_tool_call(user_id="", name="get_balance"), {"error": "unauthorized"})

    def test_allowlist(self):
        for expected in (
            "get_balance",
            "get_transactions",
            "get_spending_by_category",
            "get_cash_flow",
            "get_forecast",
            "get_safe_to_spend",
            "get_net_worth",
            "get_credit_cards",
            "get_upcoming_bills",
            "get_goals",
            "get_financial_health",
        ):
            self.assertIn(expected, ALLOWED_TOOL_NAMES)
        self.assertIsNone(authorize_tool_call(user_id="u1", name="get_balance"))


class TestRuleLoopAuthorization(unittest.TestCase):
    def test_rule_cannot_reenter_from_own_event(self):
        self.assertTrue(
            would_loop(
                rule={"id": "r1"},
                event={"source": "financial_rule", "caused_by_rule_id": "r1"},
                applied_rule_ids=[],
            )
        )


if __name__ == "__main__":
    unittest.main()
