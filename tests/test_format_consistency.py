import unittest

from datetime import date

from app.core.time import parse_user_date
from app.helpers.labels import health_band_label, payment_mode_label, user_agent_label
from app.helpers.money import format_inr, format_inr_digits
from app.helpers.planning_math import compact_dashboard_overlay, health_band


class TestFormatInr(unittest.TestCase):
    def test_indian_grouping_with_paise(self):
        self.assertEqual(format_inr(193108), "₹1,93,108.00")
        self.assertEqual(format_inr(784500), "₹7,84,500.00")
        self.assertEqual(format_inr(18650), "₹18,650.00")
        self.assertEqual(format_inr_digits(187108), "1,87,108.00")
        self.assertEqual(format_inr(-1432), "-₹1,432.00")


class TestLabels(unittest.TestCase):
    def test_payment_mode_casing(self):
        self.assertEqual(payment_mode_label("upi"), "UPI")
        self.assertEqual(payment_mode_label("netbanking"), "Net Banking")
        self.assertEqual(payment_mode_label("emi"), "EMI")
        self.assertEqual(payment_mode_label("sip"), "SIP")

    def test_health_band_source(self):
        self.assertEqual(health_band(97), "EXCELLENT")
        self.assertEqual(health_band(82), "GOOD")
        self.assertEqual(health_band_label("EXCELLENT"), "Excellent")
        self.assertEqual(health_band_label("GOOD"), "Good")

    def test_parse_user_date_india_and_iso(self):
        self.assertEqual(parse_user_date("23/09/2026"), date(2026, 9, 23))
        self.assertEqual(parse_user_date("2026-09-23"), date(2026, 9, 23))
        self.assertIsNone(parse_user_date("09/23/2026"))

    def test_scheduled_remaining_skips_past_days(self):
        overlay = compact_dashboard_overlay(
            {
                "today": date(2026, 9, 24),
                "month_expense": 1432,
                "forecast": {
                    "daily": [
                        {"date": "2026-09-04", "outflow": -666, "inflow": 0, "balance": 100},
                        {"date": "2026-09-30", "outflow": -1432, "inflow": 0, "balance": 90},
                    ]
                },
            }
        )
        self.assertEqual(overlay["forecast"]["month_spent"], 1432)
        self.assertEqual(overlay["forecast"]["month_remaining_outflow"], 1432)

    def test_user_agent_readable(self):
        ua = "MOZILLA/5.0 (X11; LINUX X86_64; RV:140.0) GECKO/20100101 FIREFOX/140.0"
        self.assertEqual(user_agent_label(ua), "Firefox on Linux")


if __name__ == "__main__":
    unittest.main()
