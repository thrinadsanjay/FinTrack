import unittest

from bson import ObjectId

from app.helpers.transaction_queries import build_transactions_query, resolve_transactions_sort


class TestTransactionQueries(unittest.TestCase):
    def test_build_transactions_query_transfer_filter(self):
        user_id = str(ObjectId())
        account_id = str(ObjectId())
        query = build_transactions_query(
            user_id=user_id,
            account_id=account_id,
            tx_type="transfer",
            search="rent",
        )
        self.assertEqual(str(query["user_id"]), user_id)
        self.assertEqual(str(query["account_id"]), account_id)
        self.assertEqual(query["type"], {"$in": ["transfer_in", "transfer_out"]})
        self.assertIn("description", query)

    def test_resolve_transactions_sort_defaults_and_amount(self):
        self.assertEqual(resolve_transactions_sort(None, None), ("created_at", -1))
        self.assertEqual(resolve_transactions_sort("amount", "asc"), ("amount", 1))


if __name__ == "__main__":
    unittest.main()
