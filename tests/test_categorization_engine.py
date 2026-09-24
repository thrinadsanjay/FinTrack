import unittest
from unittest.mock import AsyncMock, patch

from bson import ObjectId

from app.services.categorization_engine import MatchResult, _categorize_payload, _match_builtin_keywords, categorize_transaction


class TestCategorizationEngineBuiltinFallback(unittest.IsolatedAsyncioTestCase):
    async def test_builtin_keyword_match_for_swiggy(self):
        with patch(
            "app.services.categorization_engine._resolve_category_pair",
            new=AsyncMock(
                return_value=(
                    {"code": "food", "name": "Food"},
                    {"code": "dining_out", "name": "Dining Out"},
                )
            ),
        ):
            match = await _match_builtin_keywords(
                clean_description="swiggy",
                keywords=["swiggy"],
                tx_type="debit",
            )

        self.assertIsNotNone(match)
        self.assertEqual(match.layer, "builtin_keywords")
        self.assertEqual(match.category.get("code"), "food")
        self.assertEqual(match.subcategory.get("code"), "dining_out")

    async def test_payload_uses_builtin_when_other_layers_miss(self):
        with patch("app.services.categorization_engine._match_merchant_memory", new=AsyncMock(return_value=None)), \
            patch("app.services.categorization_engine._match_past_transactions", new=AsyncMock(return_value=None)), \
            patch("app.services.categorization_engine._match_merchant_rules", new=AsyncMock(return_value=None)), \
            patch("app.services.categorization_engine._match_self_transfer", new=AsyncMock(return_value=None)), \
            patch(
                "app.services.categorization_engine._resolve_category_pair",
                new=AsyncMock(
                    return_value=(
                        {"code": "food", "name": "Food"},
                        {"code": "dining_out", "name": "Dining Out"},
                    )
                ),
            ):
            result = await _categorize_payload(
                user_id=ObjectId(),
                payload={
                    "clean_description": "swiggy",
                    "merchant": "swiggy",
                    "tokens": ["swiggy"],
                    "mode": "upi",
                    "amount": 23.0,
                    "type": "debit",
                },
            )

        self.assertEqual(result.get("category", {}).get("code"), "food")
        self.assertEqual(result.get("subcategory", {}).get("code"), "dining_out")
        self.assertIn("builtin_keywords", result.get("matched_by") or [])
        self.assertEqual(result.get("confidence"), 20)

    async def test_builtin_keyword_match_for_personal_loan_phrase(self):
        with patch(
            "app.services.categorization_engine._resolve_category_pair",
            new=AsyncMock(
                return_value=(
                    {"code": "loan", "name": "Loan"},
                    {"code": "personal_loan", "name": "Personal Loan"},
                )
            ),
        ):
            match = await _match_builtin_keywords(
                clean_description="hdfc personal loan emi",
                keywords=["hdfc", "personal", "loan", "emi"],
                tx_type="debit",
            )

        self.assertIsNotNone(match)
        self.assertEqual(match.category.get("code"), "loan")
        self.assertEqual(match.subcategory.get("code"), "personal_loan")

    async def test_payload_uses_self_transfer_layer(self):
        self_match = MatchResult(
            layer="self_transfer",
            category={"code": "others_expense", "name": "Others"},
            subcategory={"code": "miscellaneous", "name": "Miscellaneous"},
            score=0.6,
            metadata={"matched_name_tokens": ["sanjay"]},
        )

        with patch("app.services.categorization_engine._match_merchant_memory", new=AsyncMock(return_value=None)), \
            patch("app.services.categorization_engine._match_past_transactions", new=AsyncMock(return_value=None)), \
            patch("app.services.categorization_engine._match_merchant_rules", new=AsyncMock(return_value=None)), \
            patch("app.services.categorization_engine._match_self_transfer", new=AsyncMock(return_value=self_match)), \
            patch("app.services.categorization_engine._match_builtin_keywords", new=AsyncMock(return_value=None)):
            result = await _categorize_payload(
                user_id=ObjectId(),
                payload={
                    "clean_description": "transfer to sanjay",
                    "merchant": "sanjay",
                    "tokens": ["transfer", "sanjay"],
                    "mode": "upi",
                    "amount": 500.0,
                    "type": "debit",
                },
            )

        self.assertEqual(result.get("category", {}).get("code"), "others_expense")
        self.assertEqual(result.get("subcategory", {}).get("code"), "miscellaneous")
        self.assertIn("self_transfer", result.get("matched_by") or [])

    async def test_categorize_transaction_auto_learns_merchant_memory(self):
        with patch(
            "app.services.categorization_engine._categorize_payload",
            new=AsyncMock(
                return_value={
                    "category": {"code": "entertainment", "name": "Entertainment"},
                    "subcategory": {"code": "movies", "name": "Movies"},
                    "confidence": 20,
                    "needs_attention": True,
                    "matched_by": ["builtin_keywords"],
                    "explanations": {},
                }
            ),
        ), \
            patch("app.services.categorization_engine.extract_merchant_key", new=AsyncMock(return_value="bookmyshow")), \
            patch("app.services.categorization_engine.parse_narration", return_value={"clean_description": "bookmyshow", "merchant": "bookmyshow", "tokens": ["bookmyshow"], "mode": "upi"}), \
            patch("app.services.categorization_engine.learn_merchant_memory", new=AsyncMock()) as learn_mock:
            result = await categorize_transaction(
                user_id=ObjectId(),
                raw_description="BMS BOOKMYSHOW",
                amount=450.0,
                tx_type="debit",
                mode="upi",
            )

        self.assertEqual(result.get("suggested_category_code"), "entertainment")
        self.assertEqual(result.get("suggested_subcategory_code"), "movies")
        learn_mock.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
