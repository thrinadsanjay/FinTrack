import unittest
from datetime import date

from app.helpers.planning_math import compact_dashboard_overlay, typical_from_category_changes, typical_variable_spend


class TestPlanningOverlay(unittest.TestCase):
    def test_overlay_is_compact(self):
        bundle = {
            "health": {"score": 82, "band": "GOOD", "reasons": ["+8 Savings", "+1 extra", "noise"]},
            "forecast": {
                "today_balance": 100,
                "horizons": {"30": 110, "60": 90, "90": 120},
                "lowest_balance": 80,
                "lowest_date": date(2026, 9, 18),
                "contributing_events": [{"label": "Rent", "amount": -18000}],
            },
            "safe_to_spend": {"safe_to_spend": 50, "until": date(2026, 9, 30), "reserved": 40, "available_cash": 90, "shortfall": 0},
            "net_worth": {"net_worth": 784500, "assets": 920000, "liabilities": 135500, "monthly_change": 1000, "percent_change": 0.1},
            "credit_cards": {"total_outstanding": 1, "total_available": 2, "overall_utilization": 10, "upcoming_due": 3, "monthly_emi": 4, "card_count": 1, "cards": []},
            "calendar": {"upcoming": [{"label": "Rent"}]},
            "insights": [{"title": "a"}, {"title": "b"}, {"title": "c"}, {"title": "d"}],
            "goals": [
                {"id": "1", "name": "EF", "current_amount": 1, "target_amount": 2, "progress_pct": 50, "status": "active"},
                {"id": "2", "name": "Old", "status": "archived"},
            ],
            "savings_rate": 12.5,
            "disclaimer": "not advice",
        }
        overlay = compact_dashboard_overlay(bundle)
        self.assertEqual(overlay["health"]["score"], 82)
        self.assertEqual(len(overlay["health"]["reasons"]), 3)
        self.assertEqual(overlay["forecast"]["d30"], 110)
        self.assertEqual(overlay["forecast"]["contributing"][0]["label"], "Rent")
        self.assertEqual(overlay["safe_to_spend"]["amount"], 50)
        self.assertEqual(overlay["net_worth"]["amount"], 784500)
        self.assertEqual(len(overlay["insights"]), 3)
        self.assertEqual(len(overlay["goals"]), 1)
        self.assertFalse("accounts" in overlay)
        self.assertEqual(overlay["calendar"]["upcoming"][0]["label"], "Rent")
        self.assertEqual(overlay["calendar"]["days"], {})

    def test_overlay_calendar_days_are_compact(self):
        bundle = {
            "calendar": {
                "year": 2026,
                "month": 9,
                "days": {
                    "2026-09-22": [
                        {"label": "Rent", "amount": -18000, "source": "recurring", "type": "debit", "date": date(2026, 9, 22)}
                    ]
                },
                "upcoming": [{"label": "Rent", "amount": -18000, "date": date(2026, 9, 22)}],
            }
        }
        overlay = compact_dashboard_overlay(bundle)
        self.assertEqual(overlay["calendar"]["year"], 2026)
        self.assertEqual(overlay["calendar"]["month"], 9)
        self.assertEqual(overlay["calendar"]["days"]["2026-09-22"][0]["label"], "Rent")
        self.assertEqual(overlay["calendar"]["days"]["2026-09-22"][0]["amount"], -18000)
        self.assertNotIn("date", overlay["calendar"]["days"]["2026-09-22"][0])

    def test_overlay_forecast_contributing_defaults_empty(self):
        overlay = compact_dashboard_overlay({})
        self.assertEqual(overlay["forecast"]["contributing"], [])
        self.assertIsNone(overlay["forecast"]["d30"])
        self.assertIsNone(overlay["forecast"]["month_end_balance"])

    def test_overlay_forecast_summarizes_current_month(self):
        bundle = {
            "today": date(2026, 9, 23),
            "month_expense": 1432,
            "forecast": {
                "today_balance": 193108,
                "daily": [
                    {"date": date(2026, 9, 23), "balance": 193108, "inflow": 0, "outflow": 0},
                    {"date": date(2026, 9, 25), "balance": 191676, "inflow": 5000, "outflow": -1432},
                    {"date": date(2026, 9, 30), "balance": 190676, "inflow": 0, "outflow": -1000},
                    {"date": date(2026, 10, 1), "balance": 190176, "inflow": 0, "outflow": -500},
                ],
            },
        }
        forecast = compact_dashboard_overlay(bundle)["forecast"]
        self.assertEqual(forecast["month_spent"], 1432)
        self.assertEqual(forecast["month_remaining_outflow"], 2432)
        self.assertEqual(forecast["month_remaining_inflow"], 5000)
        self.assertEqual(forecast["month_projected_inflow"], 5000)
        self.assertEqual(forecast["month_projected_outflow"], 3864)
        self.assertEqual(forecast["month_end_balance"], 190676)
        self.assertEqual(forecast["month_typical_remaining"], 0)
        self.assertEqual(forecast["typical_spend"], [])

    def test_overlay_forecast_adds_typical_variable_spend(self):
        bundle = {
            "today": date(2026, 9, 23),
            "month_expense": 1432,
            "forecast": {
                "today_balance": 193108,
                "daily": [
                    {"date": date(2026, 9, 23), "balance": 193108, "inflow": 0, "outflow": 0},
                    {"date": date(2026, 9, 30), "balance": 190676, "inflow": 0, "outflow": -2432},
                ],
            },
            "typical_spend": {
                "items": [
                    {"key": "groceries", "name": "Groceries", "average": 8000, "spent": 3000, "remaining": 5000},
                    {"key": "food", "name": "Food", "average": 2000, "spent": 500, "remaining": 1500},
                    {"key": "health", "name": "Health", "average": 1200, "spent": 0, "remaining": 1200},
                ],
                "remaining": 7700,
            },
        }
        forecast = compact_dashboard_overlay(bundle)["forecast"]
        self.assertEqual(forecast["month_remaining_outflow"], 2432)
        self.assertEqual(forecast["month_typical_remaining"], 7700)
        self.assertEqual(forecast["month_projected_outflow"], 11564)
        self.assertEqual(forecast["month_end_balance"], 182976)
        self.assertEqual(len(forecast["typical_spend"]), 3)

    def test_typical_variable_spend_uses_prior_averages(self):
        result = typical_variable_spend(
            {
                ("Food", "Groceries"): {"2026-06": 9000, "2026-07": 7000, "2026-09": 3000},
                ("Food", "Dining Out"): {"2026-06": 2000, "2026-07": 2000, "2026-09": 400},
                ("Health", "Medicines"): {"2026-06": 800, "2026-07": 1000, "2026-09": 0},
                ("Utilities", "Electricity"): {"2026-07": 1500},
            },
            current_month="2026-09",
            prior_months=["2026-06", "2026-07"],
        )
        by_name = {item["name"]: item for item in result["items"]}
        self.assertEqual(by_name["Groceries (est.)"]["average"], 8000)
        self.assertEqual(by_name["Groceries (est.)"]["remaining"], 5000)
        self.assertEqual(by_name["Dining Out (est.)"]["average"], 2000)
        self.assertEqual(by_name["Dining Out (est.)"]["remaining"], 1600)
        self.assertEqual(by_name["Medicines (est.)"]["average"], 900)
        self.assertEqual(by_name["Medicines (est.)"]["remaining"], 900)
        self.assertNotIn("Electricity (est.)", by_name)
        self.assertEqual(result["remaining"], 7500)

    def test_typical_variable_spend_uses_repeating_descriptions(self):
        result = typical_variable_spend(
            {
                ("Food", "Groceries", "DMart 8821"): {"2026-06": 4000, "2026-07": 4200, "2026-09": 1000},
                ("Transport", "Fuel", "HP Petrol"): {"2026-06": 3000, "2026-07": 3000, "2026-09": 800},
                ("Housing", "Rent", "Landlord"): {"2026-06": 18000, "2026-07": 18000, "2026-09": 0},
                ("Shopping", "Clothing", "One-off sale"): {"2026-07": 5000},
            },
            current_month="2026-09",
            prior_months=["2026-06", "2026-07"],
        )
        names = [item["name"] for item in result["items"]]
        self.assertIn("Groceries · Dmart (est.)", names)
        self.assertIn("Fuel · Hp Petrol (est.)", names)
        self.assertNotIn("Rent · Landlord (est.)", names)
        self.assertNotIn("Clothing · One-off Sale (est.)", names)

    def test_typical_from_category_changes_includes_common_categories(self):
        result = typical_from_category_changes(
            [
                {"name": "Food", "current": 3000, "average": 8000},
                {"name": "Health", "current": 200, "previous": 1500},
                {"name": "Utilities", "current": 1200, "average": 1100},
                {"name": "Loan", "current": 4000, "average": 4000},
            ]
        )
        names = [item["name"] for item in result["items"]]
        self.assertEqual(names, ["Food (est.)", "Health (est.)", "Utilities (est.)"])
        self.assertEqual(result["items"][0]["remaining"], 5000)
        self.assertEqual(result["items"][1]["remaining"], 1300)
        self.assertEqual(result["remaining"], 6300)

    def test_overlay_forecast_uses_category_change_averages(self):
        forecast = compact_dashboard_overlay(
            {
                "today": date(2026, 9, 23),
                "month_expense": 1432,
                "forecast": {"today_balance": 100000, "daily": []},
                "category_changes": [
                    {"name": "Food", "current": 1432, "average": 8000},
                ],
            }
        )["forecast"]
        self.assertEqual(forecast["typical_spend"][0]["name"], "Food (est.)")
        self.assertEqual(forecast["typical_spend"][0]["remaining"], 6568)
        self.assertEqual(forecast["month_typical_remaining"], 6568)
        self.assertEqual(forecast["month_end_balance"], 93432)

    def test_typical_variable_spend_omits_categories_without_history(self):
        result = typical_variable_spend(
            {("Food", "Groceries"): {"2026-09": 1200}},
            current_month="2026-09",
            prior_months=["2026-07", "2026-08"],
        )
        self.assertEqual(result["items"], [])
        self.assertEqual(result["remaining"], 0)


if __name__ == "__main__":
    unittest.main()
