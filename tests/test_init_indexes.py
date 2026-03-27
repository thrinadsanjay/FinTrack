import unittest
from unittest.mock import patch

from app.db.init_db import init_indexes


class _FakeCollection:
    def __init__(self):
        self.created = []
        self.dropped = []

    async def create_index(self, spec, **kwargs):
        self.created.append((spec, kwargs))

    async def drop_index(self, name):
        self.dropped.append(name)

    async def index_information(self):
        return {"name_1": {}}


class _FakeDb:
    def __init__(self):
        self.users = _FakeCollection()
        self.accounts = _FakeCollection()
        self.audit_logs = _FakeCollection()
        self.transactions = _FakeCollection()
        self.notifications = _FakeCollection()
        self.recurring_deposits = _FakeCollection()


class TestInitIndexes(unittest.IsolatedAsyncioTestCase):
    async def test_init_indexes_creates_recurring_and_retry_indexes(self):
        fake_db = _FakeDb()
        with patch("app.db.init_db.db", fake_db):
            await init_indexes()

        created_tx_specs = [spec for spec, _ in fake_db.transactions.created]
        self.assertIn([("recurring_id", 1), ("scheduled_for", 1)], created_tx_specs)
        self.assertIn([("retry_of", 1)], created_tx_specs)
        self.assertIn([("is_failed", 1), ("retry_status", 1)], created_tx_specs)

        created_recurring_specs = [spec for spec, _ in fake_db.recurring_deposits.created]
        self.assertIn([("is_active", 1), ("next_run", 1)], created_recurring_specs)
        self.assertIn([("user_id", 1), ("is_active", 1), ("next_run", 1)], created_recurring_specs)

        self.assertIn("name_1", fake_db.accounts.dropped)


if __name__ == "__main__":
    unittest.main()
