import unittest
from datetime import date

from app.helpers.rules_math import (
    MAX_ACTIONS_PER_EVENT,
    actions_for_rules,
    condition_matches,
    looks_like_salary,
    rule_matches,
    select_rules_for_event,
    would_loop,
)


def _rule(**kwargs):
    row = {
        "id": kwargs.pop("id", "r1"),
        "enabled": True,
        "priority": 10,
        "conditions": [{"type": "merchant_contains", "value": "Swiggy"}],
        "actions": [{"type": "set_category", "code": "food", "name": "Food"}],
    }
    row.update(kwargs)
    return row


class TestRuleMatching(unittest.TestCase):
    def test_merchant_contains(self):
        event = {"description": "Swiggy order", "amount": 420, "tx_type": "debit"}
        self.assertTrue(rule_matches(_rule(), event))
        self.assertFalse(rule_matches(_rule(), {"description": "Uber"}))

    def test_amount_and_balance(self):
        self.assertTrue(condition_matches({"type": "amount_gte", "value": 1000}, {"amount": 1500}))
        self.assertTrue(condition_matches({"type": "balance_lt", "value": 10000}, {"balance": 8500}))
        self.assertFalse(condition_matches({"type": "balance_lt", "value": 10000}, {"balance": 12000}))

    def test_utilization(self):
        self.assertTrue(condition_matches({"type": "utilization_gt", "value": 70}, {"utilization": 81}))
        self.assertFalse(condition_matches({"type": "utilization_gt", "value": 70}, {"utilization": 27}))

    def test_salary_received(self):
        self.assertTrue(looks_like_salary({"tx_type": "credit", "description": "Monthly salary"}))
        self.assertFalse(looks_like_salary({"tx_type": "debit", "description": "salary deduction joke"}))
        event = {"tx_type": "credit", "description": "Salary"}
        self.assertTrue(rule_matches(_rule(conditions=[{"type": "salary_received"}]), event))

    def test_due_within_days(self):
        cond = {"type": "due_within_days", "value": 10}
        self.assertTrue(
            condition_matches(cond, {"due_date": date(2026, 9, 10), "today": date(2026, 9, 4)})
        )
        self.assertFalse(
            condition_matches(cond, {"due_date": date(2026, 9, 30), "today": date(2026, 9, 4)})
        )

    def test_empty_conditions_never_match(self):
        self.assertFalse(rule_matches({"conditions": []}, {"description": "Swiggy"}))

    def test_priority_and_loop_guard(self):
        event = {"description": "Swiggy", "applied_rule_ids": ["r1"]}
        rules = [_rule(id="r1", priority=50), _rule(id="r2", priority=1)]
        chosen = select_rules_for_event(rules, event)
        self.assertEqual([c["id"] for c in chosen], ["r2"])

    def test_source_rule_event_is_ignored(self):
        self.assertTrue(would_loop(rule=_rule(), event={"source": "financial_rule"}, applied_rule_ids=[]))

    def test_disabled_rules_skipped(self):
        event = {"description": "Swiggy"}
        chosen = select_rules_for_event([_rule(enabled=False)], event)
        self.assertEqual(chosen, [])

    def test_action_cap(self):
        rule = _rule(
            actions=[{"type": "notify", "title": f"n{i}"} for i in range(20)]
        )
        actions = actions_for_rules([rule])
        self.assertLessEqual(len(actions), MAX_ACTIONS_PER_EVENT)

    def test_no_transfer_action_type(self):
        from app.helpers.rules_math import ACTION_TYPES, normalize_action

        self.assertNotIn("transfer", ACTION_TYPES)
        self.assertIsNone(normalize_action({"type": "transfer", "amount": 100}))


if __name__ == "__main__":
    unittest.main()
