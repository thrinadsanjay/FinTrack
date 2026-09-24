import unittest

from app.helpers.telegram_intents import (
    INTENT_BALANCE,
    INTENT_CREDIT_CARDS,
    INTENT_FORECAST,
    INTENT_NET_WORTH,
    INTENT_SAFE_TO_SPEND,
    INTENT_SPENDING,
    category_hint,
    detect_finance_intent,
    looks_like_quick_transaction,
)


class TestTelegramIntents(unittest.TestCase):
    def test_safe_to_spend(self):
        result = detect_finance_intent("How much can I spend?")
        self.assertEqual(result["intent"], INTENT_SAFE_TO_SPEND)

    def test_food_spending(self):
        result = detect_finance_intent("How much did I spend on food this month?")
        self.assertEqual(result["intent"], INTENT_SPENDING)
        self.assertEqual(result["category"], "food")

    def test_credit_cards(self):
        result = detect_finance_intent("How are my credit cards?")
        self.assertEqual(result["intent"], INTENT_CREDIT_CARDS)

    def test_net_worth(self):
        result = detect_finance_intent("What's my net worth?")
        self.assertEqual(result["intent"], INTENT_NET_WORTH)

    def test_balance_question(self):
        result = detect_finance_intent("What's my balance?")
        self.assertEqual(result["intent"], INTENT_BALANCE)

    def test_forecast(self):
        result = detect_finance_intent("What will my balance look like at the end of this month?")
        self.assertEqual(result["intent"], INTENT_FORECAST)

    def test_quick_transaction_not_intent(self):
        self.assertTrue(looks_like_quick_transaction("100 swiggy order from kotak"))
        self.assertIsNone(detect_finance_intent("100 swiggy order from kotak"))

    def test_unlinked_style_empty(self):
        self.assertIsNone(detect_finance_intent(""))

    def test_category_hint(self):
        self.assertEqual(category_hint("swiggy and zomato"), "food")


if __name__ == "__main__":
    unittest.main()
