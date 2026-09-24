import unittest

from app.helpers.monthly_review_math import build_monthly_review, explanation_facts, fallback_explanation
from app.helpers.recommendations import DISCLAIMER, build_recommendations
from app.helpers.ai_privacy import clip_tool_result, hallucination_guard_text, sanitize_for_ai
from app.helpers.money import format_inr


class TestRecommendations(unittest.TestCase):
    def test_empty_payload(self):
        self.assertEqual(build_recommendations({}), [])

    def test_utilization_and_goal(self):
        recs = build_recommendations(
            {
                "utilization": 72,
                "goals_behind": [{"id": "g1", "name": "Emergency Fund", "detail": "Behind pace"}],
                "payments_due_10_days": 3,
            }
        )
        keys = {r["key"] for r in recs}
        self.assertIn("util_high", keys)
        self.assertTrue(any(k.startswith("goal_behind") for k in keys))
        self.assertIn("payments_cluster", keys)
        self.assertTrue(all(r["optional"] for r in recs))
        self.assertEqual(recs[0]["disclaimer"], DISCLAIMER)

    def test_no_product_pitch(self):
        recs = build_recommendations({"utilization": 80})
        blob = " ".join(r["title"] + r["detail"] for r in recs).lower()
        self.assertNotIn("mutual fund", blob)
        self.assertNotIn("personal loan", blob)


class TestMonthlyReview(unittest.TestCase):
    def test_numbers_are_deterministic(self):
        report = build_monthly_review(
            {
                "today": "2026-08-31",
                "month_income": 50000,
                "month_expense": 14320,
                "savings_rate": 71.4,
                "insights": [
                    {"category": "positive", "title": "Savings improved"},
                    {"category": "attention", "title": "Shopping increased"},
                ],
                "category_changes": [
                    {"name": "Shopping", "current": 4000, "previous": 2000, "change_pct": 100},
                ],
                "goals": [{"name": "Emergency Fund", "progress_pct": 42, "status": "active", "current_amount": 42000, "target_amount": 100000}],
                "upcoming": [{}, {}, {}],
                "credit_cards": {"total_outstanding": 12000, "overall_utilization": 20, "upcoming_due": 5000},
            }
        )
        self.assertEqual(report["cash_flow"]["income"], 50000)
        self.assertEqual(report["cash_flow"]["expense"], 14320)
        self.assertEqual(report["cash_flow"]["net"], 35680)
        self.assertIsNone(report["narrative"])
        self.assertIn("Savings improved", report["highlights"])
        self.assertIn("Shopping increased", report["attention"])

    def test_missing_data(self):
        report = build_monthly_review({})
        self.assertIsNone(report["cash_flow"]["income"])
        self.assertEqual(report["highlights"], [])

    def test_explanation_without_cause(self):
        facts = explanation_facts(insight={"title": "Food spending increased 28%.", "detail": "x", "key": "cat_up:Food"})
        text = fallback_explanation(facts)
        self.assertIn("does not show a clear reason", text)

    def test_explanation_with_merchants(self):
        facts = explanation_facts(
            insight={"title": "Food spending increased 28%.", "key": "cat_up:Food"},
            category_changes=[
                {
                    "name": "Food",
                    "current": 4850,
                    "previous": 3200,
                    "merchants": [{"name": "Restaurants"}],
                }
            ],
        )
        text = fallback_explanation(facts)
        self.assertIn("3200", text.replace(",", ""))
        self.assertIn("Restaurants", text)


class TestAiPrivacy(unittest.TestCase):
    def test_strips_secrets(self):
        cleaned = sanitize_for_ai(
            {
                "balance": 100,
                "password": "secret",
                "bot_token": "123:abc",
                "accounts": [{"name": "SBI", "token": "nope"}],
            }
        )
        self.assertEqual(cleaned["balance"], 100)
        self.assertNotIn("password", cleaned)
        self.assertNotIn("bot_token", cleaned)
        self.assertNotIn("token", cleaned["accounts"][0])

    def test_clips_long_lists(self):
        payload = clip_tool_result({"items": [{"n": i} for i in range(80)]})
        self.assertLessEqual(len(payload["items"]), 40)

    def test_guard_text(self):
        self.assertIn("Never invent", hallucination_guard_text())


class TestFormatInr(unittest.TestCase):
    def test_indian_grouping(self):
        self.assertEqual(format_inr(784500), "₹7,84,500.00")
        self.assertEqual(format_inr(18650), "₹18,650.00")


if __name__ == "__main__":
    unittest.main()
