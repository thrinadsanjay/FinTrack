import unittest
from datetime import date

from app.helpers.planning_math import (
    available_cash,
    best_duplicate_match,
    calendar_events_from_sources,
    compute_goal_plan,
    compute_health_score,
    compute_net_worth,
    compute_safe_to_spend,
    credit_card_command_center,
    day_detail,
    emi_cash_events,
    expand_recurring_occurrences,
    generate_insights,
    score_bill_health,
    score_cash_buffer,
    score_duplicate_match,
    score_emi_burden,
    score_expense_control,
    score_savings_rate,
    score_utilization,
    walk_forecast,
)


def _acc(**kwargs):
    row = {"id": kwargs.pop("id", "a1"), "name": kwargs.pop("name", "Acme"), "type": "savings", "balance": 0}
    row.update(kwargs)
    return row


class TestNetWorth(unittest.TestCase):
    def test_empty_accounts(self):
        result = compute_net_worth([])
        self.assertEqual(result["net_worth"], 0)
        self.assertEqual(result["assets"], 0)
        self.assertEqual(result["liabilities"], 0)

    def test_assets_minus_card_outstanding(self):
        result = compute_net_worth(
            [
                _acc(id="s", type="savings", balance=100000),
                _acc(id="c", type="current", balance=20000),
                _acc(id="cc", type="credit_card", balance=-15000, credit_limit=50000),
                _acc(id="inv", type="investment", balance=5000),
            ]
        )
        self.assertEqual(result["assets"], 125000)
        self.assertEqual(result["liabilities"], 15000)
        self.assertEqual(result["net_worth"], 110000)

    def test_credit_card_not_counted_as_cash_or_double_counted(self):
        accounts = [
            _acc(id="s", type="savings", balance=10000),
            _acc(id="cc", type="credit_card", balance=-8000, credit_limit=40000),
        ]
        self.assertEqual(available_cash(accounts), 10000)
        nw = compute_net_worth(accounts)
        self.assertEqual(nw["liabilities"], 8000)
        self.assertEqual(len(nw["liability_rows"]), 1)

    def test_positive_card_balance_is_asset_not_liability(self):
        result = compute_net_worth([_acc(id="cc", type="credit_card", balance=500, credit_limit=40000)])
        self.assertEqual(result["liabilities"], 0)
        self.assertEqual(result["assets"], 500)

    def test_negative_cash_reduces_assets(self):
        result = compute_net_worth([_acc(type="current", balance=-2000)])
        self.assertEqual(result["net_worth"], -2000)

    def test_loan_is_liability_not_cash(self):
        accounts = [
            _acc(id="s", type="savings", balance=193108),
            _acc(id="ln", type="loan", balance=840000),
        ]
        self.assertEqual(available_cash(accounts), 193108)
        nw = compute_net_worth(accounts)
        self.assertEqual(nw["assets"], 193108)
        self.assertEqual(nw["liabilities"], 840000)
        self.assertEqual(nw["net_worth"], 193108 - 840000)

    def test_wallet_and_cash_included(self):
        result = compute_net_worth(
            [
                _acc(id="w", type="wallet", balance=300),
                _acc(id="k", type="cash", balance=700),
            ]
        )
        self.assertEqual(result["assets"], 1000)


class TestForecastAndSafeToSpend(unittest.TestCase):
    def test_no_events_forecast_is_flat(self):
        today = date(2026, 9, 4)
        result = walk_forecast(starting_cash=48850, events=[], today=today)
        self.assertEqual(result["today_balance"], 48850)
        self.assertEqual(result["horizons"]["30"], 48850)
        self.assertEqual(result["lowest_balance"], 48850)
        self.assertEqual(result["lowest_date"], today)

    def test_scheduled_salary_and_rent(self):
        today = date(2026, 9, 4)
        events = [
            {
                "date": date(2026, 9, 30),
                "amount": 50000,
                "label": "Salary",
                "certainty": "scheduled",
                "type": "credit",
            },
            {
                "date": date(2026, 9, 5),
                "amount": -18000,
                "label": "Rent",
                "certainty": "scheduled",
                "type": "debit",
            },
        ]
        result = walk_forecast(starting_cash=48850, events=events, today=today)
        self.assertEqual(result["lowest_date"], date(2026, 9, 5))
        self.assertEqual(result["lowest_balance"], 30850)
        self.assertEqual(result["horizons"]["30"], 80850)

    def test_estimates_excluded_from_primary_path(self):
        today = date(2026, 9, 4)
        events = [
            {
                "date": date(2026, 9, 10),
                "amount": -5000,
                "label": "Typical spend",
                "certainty": "estimate",
                "type": "debit",
            }
        ]
        primary = walk_forecast(starting_cash=10000, events=events, today=today)
        with_est = walk_forecast(starting_cash=10000, events=events, today=today, include_estimates=True)
        self.assertEqual(primary["horizons"]["30"], 10000)
        self.assertEqual(with_est["lowest_balance"], 5000)

    def test_expand_recurring_marks_later_occurrences_forecasted(self):
        events = expand_recurring_occurrences(
            next_run=date(2026, 9, 5),
            frequency="monthly",
            until=date(2026, 12, 5),
            start_from=date(2026, 9, 1),
            amount=18000,
            tx_type="debit",
            label="Rent",
            source_id="r1",
        )
        self.assertGreaterEqual(len(events), 3)
        self.assertEqual(events[0]["certainty"], "scheduled")
        self.assertEqual(events[1]["certainty"], "forecasted")
        self.assertEqual(events[0]["amount"], -18000)

    def test_safe_to_spend_reserves_obligations_and_buffer(self):
        result = compute_safe_to_spend(
            cash=48850,
            obligation_groups={"bills": 18000, "credit_cards": 6500, "recurring": 2400, "emis": 999},
            next_income={"date": date(2026, 9, 30), "amount": 50000, "label": "Salary"},
            today=date(2026, 9, 4),
            buffer_rate=0.10,
        )
        self.assertEqual(result["reserved"], 30688.9)
        self.assertEqual(result["safe_to_spend"], 18161.1)
        self.assertFalse(result["income_included"])
        self.assertFalse(result["credit_limit_included"])
        self.assertEqual(result["next_income_amount"], 50000)
        self.assertEqual(result["until"], date(2026, 9, 30))

    def test_safe_to_spend_negative_shows_zero_and_shortfall(self):
        result = compute_safe_to_spend(
            cash=1000,
            obligation_groups={"bills": 5000},
            today=date(2026, 9, 4),
            buffer_rate=0.10,
        )
        self.assertEqual(result["safe_to_spend"], 0)
        self.assertGreater(result["shortfall"], 0)
        self.assertLess(result["raw_amount"], 0)

    def test_safe_to_spend_no_obligations(self):
        result = compute_safe_to_spend(
            cash=10000,
            obligation_groups={},
            today=date(2026, 9, 4),
        )
        self.assertEqual(result["safe_to_spend"], 10000)
        self.assertEqual(result["reserved"], 0)

    def test_emi_on_credit_card_not_cash_event(self):
        accounts = [_acc(id="cc1", type="credit_card", balance=-10000, credit_limit=50000)]
        emis = [{"id": "e1", "account_id": "cc1", "monthly_amount": 4000, "next_due_date": date(2026, 9, 8), "status": "active"}]
        events = emi_cash_events(emis, accounts, start_from=date(2026, 9, 1), until=date(2026, 9, 30))
        self.assertEqual(events, [])

    def test_emi_on_bank_account_is_cash_event(self):
        accounts = [_acc(id="s1", type="savings", balance=20000)]
        emis = [{"id": "e1", "account_id": "s1", "monthly_amount": 4000, "next_due_date": date(2026, 9, 8), "status": "active"}]
        events = emi_cash_events(emis, accounts, start_from=date(2026, 9, 1), until=date(2026, 9, 30))
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["amount"], -4000)


class TestHealthScore(unittest.TestCase):
    def test_insufficient_when_no_dimensions(self):
        result = compute_health_score({"savings": None, "cash_buffer": None})
        self.assertIsNone(result["score"])
        self.assertEqual(result["band"], "INSUFFICIENT")

    def test_equal_weight_available_only(self):
        result = compute_health_score({"savings": 88, "cash_buffer": 74, "utilization": 91, "mystery": None})
        self.assertEqual(result["score"], 84)
        self.assertEqual(result["band"], "GOOD")
        self.assertIn("mystery", result["excluded"])

    def test_reasons_from_previous(self):
        result = compute_health_score(
            {"savings": 88, "utilization": 91},
            {"savings": 80, "utilization": 96},
        )
        self.assertTrue(any("+8" in row for row in result["reasons"]))
        self.assertTrue(any("-5" in row or "declined" in row for row in result["reasons"]))

    def test_savings_rate_none(self):
        self.assertIsNone(score_savings_rate(None))

    def test_expense_control_requires_average(self):
        self.assertIsNone(score_expense_control(1000, None))
        self.assertIsNone(score_expense_control(1000, 0))

    def test_cash_buffer_three_months_is_100(self):
        self.assertEqual(score_cash_buffer(30000, 10000), 100)

    def test_utilization_zero_is_100(self):
        self.assertEqual(score_utilization(0, 50000), 100)

    def test_bill_health_unavailable_without_bills(self):
        self.assertIsNone(score_bill_health(0, 0))

    def test_emi_burden_excluded_without_emi(self):
        self.assertIsNone(score_emi_burden(0, 50000))
        self.assertIsNone(score_emi_burden(None, 50000))


class TestCreditCalendarInsightsGoalsDuplicates(unittest.TestCase):
    def test_credit_card_aggregation(self):
        overview = credit_card_command_center(
            [
                _acc(
                    id="icici",
                    name="ICICI",
                    type="credit_card",
                    balance=-18450,
                    credit_limit=50000,
                    statement_balance=18450,
                    due_day=18,
                    payment_due_date=date(2026, 9, 18),
                ),
                _acc(
                    id="hdfc",
                    name="HDFC",
                    type="credit_card",
                    balance=-24400,
                    credit_limit=80000,
                    statement_balance=0,
                    due_day=12,
                    payment_due_date=date(2026, 9, 12),
                ),
            ],
            [
                {"account_id": "icici", "monthly_amount": 4820, "status": "active"},
                {"account_id": "icici", "monthly_amount": 0, "status": "closed"},
            ],
        )
        self.assertEqual(overview["card_count"], 2)
        self.assertEqual(overview["total_outstanding"], 42850)
        self.assertEqual(overview["monthly_emi"], 4820)
        self.assertIsNotNone(overview["overall_utilization"])

    def test_calendar_day_detail(self):
        events = calendar_events_from_sources(
            recurring_events=[
                {"date": date(2026, 9, 18), "amount": -999, "label": "Internet", "source": "recurring"}
            ],
            card_events=[
                {"date": date(2026, 9, 18), "amount": -18450, "label": "ICICI Card", "source": "credit_card"}
            ],
            emi_events=[],
        )
        detail = day_detail(events, date(2026, 9, 18), starting_balance=48850)
        self.assertEqual(detail["outflow_total"], 19449)
        self.assertEqual(detail["expected_balance_after"], 29401)

    def test_insights_skip_when_insufficient(self):
        insights = generate_insights({"today": date(2026, 9, 4)})
        self.assertEqual(insights, [])

    def test_insights_cash_covers_bills(self):
        insights = generate_insights(
            {
                "today": date(2026, 9, 4),
                "cash": 50000,
                "reserved": 12000,
                "recurring_due_5_days": 3,
            }
        )
        keys = {item["key"] for item in insights}
        self.assertIn("bills_covered", keys)
        self.assertIn("recurring_soon", keys)

    def test_duplicate_same_account_amount_date(self):
        match = score_duplicate_match(
            {"amount": 1499, "date": date(2026, 8, 12), "account_id": "a1", "type": "debit", "identity": "amazon"},
            {"amount": 1499, "date": date(2026, 8, 12), "account_id": "a1", "type": "debit", "identity": "amazon", "description": "Amazon", "id": "tx1"},
        )
        self.assertIsNotNone(match)
        self.assertGreaterEqual(match["confidence"], 80)
        self.assertIn("Same amount", match["reasons"])

    def test_duplicate_different_amount_not_matched(self):
        match = best_duplicate_match(
            {"amount": 1499, "date": date(2026, 8, 12), "account_id": "a1", "type": "debit"},
            [{"amount": 1500, "date": date(2026, 8, 12), "account_id": "a1", "type": "debit"}],
        )
        self.assertIsNone(match)

    def test_goal_pace_and_eta(self):
        plan = compute_goal_plan(
            target_amount=200000,
            current_amount=85000,
            target_date=date(2026, 12, 1),
            today=date(2026, 9, 4),
            monthly_pace=19500,
        )
        self.assertEqual(plan["remaining"], 115000)
        self.assertGreater(plan["required_monthly"], 0)
        self.assertFalse(plan["on_track"])
        self.assertIn("2027", plan["eta_label"] or "")

    def test_goal_already_reached(self):
        plan = compute_goal_plan(
            target_amount=1000,
            current_amount=1200,
            target_date=date(2026, 12, 1),
            today=date(2026, 9, 4),
            monthly_pace=100,
        )
        self.assertTrue(plan["completed"])
        self.assertEqual(plan["required_monthly"], 0)


if __name__ == "__main__":
    unittest.main()
