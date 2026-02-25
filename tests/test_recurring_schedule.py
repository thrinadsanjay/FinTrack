import unittest
from datetime import date

from app.services.recurring_deposit import calculate_next_occurrence


class TestRecurringSchedule(unittest.TestCase):
    def test_past_start_monthly_skips_to_next_cycle(self):
        next_run = calculate_next_occurrence(
            start_date=date(2026, 2, 6),
            frequency="monthly",
            today=date(2026, 2, 13),
            include_today=False,
            skip_missed=True,
        )
        self.assertEqual(next_run.date(), date(2026, 3, 6))

    def test_future_start_runs_on_start_date(self):
        next_run = calculate_next_occurrence(
            start_date=date(2026, 2, 14),
            frequency="monthly",
            today=date(2026, 2, 13),
            include_today=False,
            skip_missed=True,
        )
        self.assertEqual(next_run.date(), date(2026, 2, 14))

    def test_start_today_does_not_run_immediately(self):
        next_run = calculate_next_occurrence(
            start_date=date(2026, 2, 13),
            frequency="daily",
            today=date(2026, 2, 13),
            include_today=False,
            skip_missed=True,
        )
        self.assertEqual(next_run.date(), date(2026, 2, 14))

    def test_month_end_handles_short_months(self):
        next_run = calculate_next_occurrence(
            start_date=date(2026, 1, 31),
            frequency="monthly",
            today=date(2026, 2, 1),
            include_today=False,
            skip_missed=True,
        )
        self.assertEqual(next_run.date(), date(2026, 2, 28))

    def test_leap_year_anchor_for_yearly(self):
        next_run = calculate_next_occurrence(
            start_date=date(2024, 2, 29),
            frequency="yearly",
            today=date(2025, 3, 1),
            include_today=False,
            skip_missed=True,
        )
        self.assertEqual(next_run.date(), date(2026, 2, 28))

    def test_dst_boundary_date_safe(self):
        next_run = calculate_next_occurrence(
            start_date=date(2026, 3, 8),
            frequency="daily",
            today=date(2026, 3, 8),
            include_today=False,
            skip_missed=True,
        )
        self.assertEqual(next_run.date(), date(2026, 3, 9))

    def test_optional_catch_up_mode(self):
        next_run = calculate_next_occurrence(
            start_date=date(2026, 1, 1),
            frequency="weekly",
            today=date(2026, 2, 13),
            include_today=False,
            skip_missed=False,
        )
        self.assertEqual(next_run.date(), date(2026, 1, 1))


if __name__ == "__main__":
    unittest.main()
