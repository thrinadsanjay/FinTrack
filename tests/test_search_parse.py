import unittest
from datetime import date

from app.helpers.search_parse import (
    amount_close,
    field_matches,
    fuzzy_ratio,
    in_date_window,
    parse_search_query,
)


class TestParseSearchQuery(unittest.TestCase):
    def test_merchant_tokens(self):
        parsed = parse_search_query("Amazon")
        self.assertEqual(parsed["tokens"], ["amazon"])
        self.assertIsNone(parsed["amount"])

    def test_amount_and_month(self):
        parsed = parse_search_query("ICICI August ₹5,000", today=date(2026, 9, 4))
        self.assertEqual(parsed["amount"], 5000.0)
        self.assertEqual(parsed["date_from"], date(2026, 8, 1))
        self.assertEqual(parsed["date_to"], date(2026, 8, 31))
        self.assertIn("icici", parsed["tokens"])

    def test_salary_token(self):
        parsed = parse_search_query("Salary")
        self.assertEqual(parsed["tokens"], ["salary"])

    def test_netflix(self):
        parsed = parse_search_query("Netflix")
        self.assertTrue(field_matches(parsed, "Netflix subscription"))

    def test_empty(self):
        parsed = parse_search_query("  ")
        self.assertEqual(parsed["tokens"], [])

    def test_fuzzy_merchant(self):
        self.assertGreater(fuzzy_ratio("swiggy", "Swiggy Foods"), 0.7)
        self.assertTrue(field_matches(parse_search_query("swiggy"), "Dinner at Swiggy"))

    def test_amount_close(self):
        self.assertTrue(amount_close(5000, 5000.0))
        self.assertFalse(amount_close(5000, 1200))

    def test_date_window(self):
        self.assertTrue(in_date_window(date(2026, 8, 12), date(2026, 8, 1), date(2026, 8, 31)))
        self.assertFalse(in_date_window(date(2026, 7, 12), date(2026, 8, 1), date(2026, 8, 31)))


if __name__ == "__main__":
    unittest.main()
