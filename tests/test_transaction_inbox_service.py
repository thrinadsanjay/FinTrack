import unittest
from datetime import date

from app.services.transaction_inbox import (
    detect_mode,
    generate_fingerprint,
    is_unclear_description,
    normalize_statement_row,
)


class TestTransactionInboxService(unittest.TestCase):
    def test_fingerprint_uses_date_amount_and_description_tail(self):
        left = generate_fingerprint(date(2026, 5, 1), 120.0, "UPI/Swiggy Order 123456")
        right = generate_fingerprint(date(2026, 5, 1), 120.0, "something 123456")
        other = generate_fingerprint(date(2026, 5, 2), 120.0, "something 123456")

        self.assertEqual(left, right)
        self.assertNotEqual(left, other)

    def test_mode_detection_prefers_known_bank_channels(self):
        self.assertEqual(detect_mode("UPI/PAYTM/123"), "upi")
        self.assertEqual(detect_mode("POS VISA SWIPE"), "card")
        self.assertEqual(detect_mode("salary credit"), "unknown")

    def test_unclear_description_flags_generic_rows(self):
        self.assertTrue(is_unclear_description("debit transaction"))
        self.assertFalse(is_unclear_description("Amazon marketplace order"))

    def test_normalize_statement_row_reads_debit_credit_headers(self):
        row = normalize_statement_row(
            {
                "date": "07/05/2026",
                "description": "UPI to Grofers",
                "debit": "145.25",
                "credit": "",
            }
        )

        self.assertIsNotNone(row)
        self.assertEqual(row["type"], "debit")
        self.assertEqual(row["amount"], 145.25)
        self.assertEqual(row["mode"], "upi")


if __name__ == "__main__":
    unittest.main()
