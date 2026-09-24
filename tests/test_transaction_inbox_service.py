import unittest
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, patch

from bson import ObjectId

from app.services.transaction_inbox import (
    _confidence_ratio,
    _needs_attention_fields,
    _serialize_inbox_row,
    _insert_rows_to_buffer,
    _is_soft_ledger_match,
    _normalize_sms_message,
    normalize_csv_row,
    detect_mode,
    generate_fingerprint,
)


UTC = timezone.utc


class TestTransactionInboxService(unittest.TestCase):
    def test_fingerprint_uses_date_and_amount(self):
        left = generate_fingerprint(date(2026, 5, 1), 120.0)
        right = generate_fingerprint(date(2026, 5, 1), 120.00)
        other = generate_fingerprint(date(2026, 5, 2), 120.0)

        self.assertEqual(left, right)
        self.assertNotEqual(left, other)

    def test_fingerprint_includes_account_and_identity(self):
        acc_a = generate_fingerprint(date(2026, 5, 1), 120.0, "SWIGGY ORDER", "debit", "acc-1")
        acc_b = generate_fingerprint(date(2026, 5, 1), 120.0, "SWIGGY ORDER", "debit", "acc-2")
        self.assertNotEqual(acc_a, acc_b)

    def test_fingerprint_differs_for_distinct_rows(self):
        amazon = generate_fingerprint(date(2026, 5, 1), 120.0, "AMAZON PAY UPI", "debit")
        swiggy = generate_fingerprint(date(2026, 5, 1), 120.0, "SWIGGY ORDER", "debit")
        credit = generate_fingerprint(date(2026, 5, 1), 120.0, "AMAZON PAY UPI", "credit")

        self.assertNotEqual(amazon, swiggy)
        self.assertNotEqual(amazon, credit)

    def test_mode_detection_prefers_known_bank_channels(self):
        self.assertEqual(detect_mode("UPI/PAYTM/123"), "upi")
        self.assertEqual(detect_mode("POS VISA SWIPE"), "card")
        self.assertEqual(detect_mode("salary credit"), "unknown")

    def test_normalize_csv_row_uses_raw_text_for_upi_mode_and_cleaned_description(self):
        row = {
            "date": "2026-05-10",
            "amount": "23.00",
            "description": "UPI/DR/123456/SWIGGY ORDER/Ref 998877",
        }

        normalized = normalize_csv_row(row)

        self.assertIsNotNone(normalized)
        self.assertEqual(normalized["mode"], "upi")
        self.assertIn("swiggy", normalized["description"])
        self.assertNotIn("upi", normalized["description"])
        self.assertNotIn("123456", normalized["description"])

    def test_normalize_csv_uses_debit_credit_amount_columns(self):
        debit_row = normalize_csv_row(
            {
                "date": "2026-05-10",
                "description": "RENT PAYMENT",
                "debit": "15000.00",
                "credit": "",
            }
        )
        credit_row = normalize_csv_row(
            {
                "date": "2026-05-10",
                "description": "SALARY CREDIT",
                "debit": "",
                "credit": "50000",
            }
        )
        self.assertEqual(debit_row["amount"], 15000.0)
        self.assertEqual(debit_row["type"], "debit")
        self.assertEqual(credit_row["amount"], 50000.0)
        self.assertEqual(credit_row["type"], "credit")

    def test_soft_ledger_match_detects_similar_merchant(self):
        candidate = {
            "date": date(2026, 5, 10),
            "amount": 120.0,
            "type": "debit",
            "identity": "swiggy",
        }
        ledger = [
            {
                "date": date(2026, 5, 11),
                "amount": 120.0,
                "type": "debit",
                "identity": "swiggy bangalore",
            }
        ]
        self.assertTrue(_is_soft_ledger_match(candidate, ledger))

    def test_sms_infers_type_from_raw_body(self):
        credited = _normalize_sms_message(
            {
                "body": "INR 500.00 credited to A/c XX1234 on 10-05-26. Avl Bal INR 1000",
                "timestamp": 1746873600000,
            }
        )
        debited = _normalize_sms_message(
            {
                "body": "INR 99.00 debited from A/c XX1234 for UPI/SWIGGY. Avl Bal INR 900",
                "timestamp": 1746873600000,
            }
        )
        self.assertEqual(credited["type"], "credit")
        self.assertEqual(debited["type"], "debit")
        self.assertGreater(credited["amount"], 0)
        self.assertIn("swiggy", debited["description"].lower())

    def test_confidence_ratio_accepts_percent_or_ratio(self):
        self.assertEqual(_confidence_ratio(85), 0.85)
        self.assertEqual(_confidence_ratio(0.62), 0.62)

    def test_needs_attention_includes_missing_category_and_low_confidence(self):
        fields = _needs_attention_fields(
            {
                "category_code": None,
                "subcategory_code": None,
                "confidence": 0.62,
            }
        )
        self.assertEqual(fields, ["category", "confidence"])

    def test_serialize_inbox_row_matches_new_review_api_shape(self):
        payload = _serialize_inbox_row(
            {
                "_id": ObjectId(),
                "source": "pdf",
                "account_id": ObjectId(),
                "date": datetime(2026, 5, 12, 12, tzinfo=UTC),
                "amount": 540.0,
                "type": "debit",
                "description": "amazon marketplace",
                "raw_description": "AMAZON MARKETPLACE 44332211",
                "mode": "card",
                "category": "Shopping",
                "category_code": "expense",
                "subcategory_code": "online",
                "subcategory_name": "Online",
                "merchant_keyword": "amazon",
                "detected_merchant": "Amazon",
                "cleaned_key": "amazon",
                "confidence": 0.62,
                "status": "pending",
                "needs_attention": ["confidence"],
            },
            "Main Account",
        )

        self.assertEqual(payload["source"], "pdf")
        self.assertEqual(payload["txn_date"], "2026-05-12T12:00:00+00:00")
        self.assertEqual(payload["raw_description"], "AMAZON MARKETPLACE 44332211")
        self.assertEqual(payload["suggested_category"], "Shopping")
        self.assertEqual(payload["suggested_subcategory"], "Online")
        self.assertEqual(payload["confidence_percent"], 62)
        self.assertEqual(payload["needs_attention"], ["confidence"])


class TestTransactionInboxImportIntegration(unittest.IsolatedAsyncioTestCase):
    async def test_insert_rows_calls_shared_categorizer_for_each_row(self):
        user_oid = ObjectId()
        account_oid = ObjectId()
        normalized_rows = [
            {
                "date": date(2026, 5, 10),
                "amount": 120.0,
                "type": "debit",
                "description": "AMZN PAY INDIA",
                "mode": "upi",
                "raw_data": {"body": "UPI/DR/991122/AMZN PAY INDIA/Ref 991122"},
            },
            {
                "date": date(2026, 5, 10),
                "amount": 120.0,
                "type": "debit",
                "description": "SWIGGY BANGALORE",
                "mode": "upi",
                "raw_data": {"body": "UPI/DR/881100/SWIGGY BANGALORE/Ref 881100"},
            },
        ]

        categorize_results = [
            {
                "cleaned_key": "amazon",
                "detected_merchant": "Amazon",
                "suggested_category": "Shopping",
                "suggested_category_code": "expense",
                "suggested_subcategory": "Online",
                "suggested_subcategory_code": "online",
                "confidence_ratio": 0.92,
                "matched_by": ["merchant_memory"],
            },
            {
                "cleaned_key": "swiggy",
                "detected_merchant": "Swiggy",
                "suggested_category": "Food",
                "suggested_category_code": "expense",
                "suggested_subcategory": "Delivery",
                "suggested_subcategory_code": "delivery",
                "confidence_ratio": 0.9,
                "matched_by": ["merchant_rules"],
            },
        ]

        with patch("app.services.transaction_inbox._ledger_match_index", new=AsyncMock(return_value={"fingerprints": set(), "rows": []})), \
            patch("app.services.transaction_inbox._existing_inbox_fingerprints", new=AsyncMock(return_value=set())), \
            patch("app.services.transaction_inbox.categorize_transaction", new=AsyncMock(side_effect=categorize_results)) as categorize_mock, \
            patch("app.services.transaction_inbox.db") as db_mock:
            db_mock.transaction_inbox.insert_many = AsyncMock()

            result = await _insert_rows_to_buffer(
                user_oid=user_oid,
                account_oid=account_oid,
                source="pdf",
                normalized_rows=normalized_rows,
            )

            self.assertEqual(categorize_mock.await_count, 2)
            self.assertEqual(result["inserted_count"], 2)
            self.assertEqual(result["duplicate_count"], 0)
            self.assertEqual(result["needs_attention_count"], 0)

            db_mock.transaction_inbox.insert_many.assert_awaited_once()
            inserted_docs = db_mock.transaction_inbox.insert_many.await_args.args[0]
            self.assertEqual(len(inserted_docs), 2)

            first_doc = inserted_docs[0]
            second_doc = inserted_docs[1]

            self.assertEqual(first_doc["cleaned_key"], "amazon")
            self.assertEqual(first_doc["detected_merchant"], "Amazon")
            self.assertEqual(first_doc["category_code"], "expense")
            self.assertEqual(first_doc["subcategory_code"], "online")
            self.assertAlmostEqual(float(first_doc["confidence"]), 0.92)

            self.assertEqual(second_doc["cleaned_key"], "swiggy")
            self.assertEqual(second_doc["detected_merchant"], "Swiggy")
            self.assertEqual(second_doc["category_code"], "expense")
            self.assertEqual(second_doc["subcategory_code"], "delivery")
            self.assertAlmostEqual(float(second_doc["confidence"]), 0.9)

            # Same date+amount should remain separate rows when description differs.
            self.assertNotEqual(first_doc["fingerprint"], second_doc["fingerprint"])


if __name__ == "__main__":
    unittest.main()
