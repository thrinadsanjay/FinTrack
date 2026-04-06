import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from app.schedulers.recurring_scheduler import run_recurring_transactions


class _AsyncCursor:
    def __init__(self, items):
        self._iter = iter(items)

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self._iter)
        except StopIteration:
            raise StopAsyncIteration


class _Collection:
    def __init__(self, *, find_items=None, find_one_result=None):
        self.find_items = find_items or []
        self.find_one_result = find_one_result
        self.inserted = []
        self.updated = []
        self.find_one_calls = []

    def find(self, _query):
        return _AsyncCursor(self.find_items)

    async def find_one(self, query, _projection=None):
        self.find_one_calls.append(query)
        return self.find_one_result

    async def insert_one(self, doc):
        self.inserted.append(doc)
        return None

    async def update_one(self, query, update):
        self.updated.append((query, update))
        return None


class _FakeDb:
    def __init__(self, recurring_collection, transactions_collection, accounts_collection):
        self.recurring_deposits = recurring_collection
        self.transactions = transactions_collection
        self.accounts = accounts_collection
        self._by_name = {
            "recurring_deposits": recurring_collection,
            "transactions": transactions_collection,
            "accounts": accounts_collection,
        }

    def __getitem__(self, name):
        return self._by_name[name]


class TestSchedulerIdempotency(unittest.IsolatedAsyncioTestCase):
    async def test_existing_transaction_prevents_duplicate_insert(self):
        now = datetime.now(timezone.utc)
        scheduled_for = now - timedelta(minutes=1)
        recurring_rule = {
            "_id": "rid-1",
            "user_id": "uid-1",
            "account_id": "aid-1",
            "type": "debit",
            "mode": "online",
            "amount": 100.0,
            "description": "Rent",
            "category": {"code": "expense", "name": "Expense"},
            "subcategory": {"code": "rent", "name": "Rent"},
            "frequency": "monthly",
            "start_date": now,
            "next_run": scheduled_for,
            "is_active": True,
        }

        recurring = _Collection(find_items=[recurring_rule])
        transactions = _Collection(find_one_result={"_id": "existing-tx"})
        accounts = _Collection(find_one_result={"balance": 1000.0, "name": "Main"})
        fake_db = _FakeDb(recurring, transactions, accounts)

        with patch("app.schedulers.recurring_scheduler.db", fake_db):
            await run_recurring_transactions()

        self.assertEqual(len(transactions.inserted), 0)
        self.assertEqual(len(accounts.updated), 0)
        self.assertEqual(len(recurring.updated), 0)


    async def test_due_transaction_is_inserted_and_rule_advanced(self):
        now = datetime.now(timezone.utc)
        scheduled_for = now - timedelta(minutes=1)
        recurring_rule = {
            "_id": "rid-2",
            "user_id": "uid-1",
            "account_id": "aid-1",
            "type": "debit",
            "mode": "online",
            "amount": 100.0,
            "description": "Rent",
            "category": {"code": "expense", "name": "Expense"},
            "subcategory": {"code": "rent", "name": "Rent"},
            "frequency": "monthly",
            "start_date": now,
            "next_run": scheduled_for,
            "is_active": True,
        }

        recurring = _Collection(find_items=[recurring_rule])
        transactions = _Collection(find_one_result=None)
        accounts = _Collection(find_one_result={"balance": 1000.0, "name": "Main"})
        fake_db = _FakeDb(recurring, transactions, accounts)

        with patch("app.schedulers.recurring_scheduler.db", fake_db), \
             patch("app.schedulers.recurring_scheduler.calculate_next_run", return_value=datetime(2100, 1, 1, tzinfo=timezone.utc)):
            await run_recurring_transactions()

        self.assertEqual(len(transactions.inserted), 1)
        inserted = transactions.inserted[0]
        self.assertEqual(inserted["recurring_id"], "rid-2")
        self.assertEqual(inserted["account_id"], "aid-1")
        self.assertEqual(inserted["scheduled_for"], scheduled_for)
        self.assertEqual(inserted["source"], "recurring")

        self.assertEqual(len(accounts.updated), 2)
        self.assertEqual(
            accounts.updated[0],
            ({"_id": "aid-1"}, {"$inc": {"balance": -100.0}}),
        )

        self.assertEqual(len(recurring.updated), 1)
        update_query, update_doc = recurring.updated[0]
        self.assertEqual(update_query, {"_id": "rid-2"})
        self.assertEqual(update_doc["$set"]["last_run"], scheduled_for)
        self.assertEqual(update_doc["$set"]["next_run"], datetime(2100, 1, 1, tzinfo=timezone.utc))

if __name__ == "__main__":
    unittest.main()
