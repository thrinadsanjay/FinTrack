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
        self.transaction_inbox = _FakeCollection()
        self.sms_buffer = _FakeCollection()
        self.notifications = _FakeCollection()
        self.recurring_deposits = _FakeCollection()
        self.credit_card_emis = _FakeCollection()
        self.credit_cards = _FakeCollection()
        self.credit_card_transactions = _FakeCollection()
        self.credit_card_bills = _FakeCollection()
        self.credit_card_bill_items = _FakeCollection()
        self.credit_card_payments = _FakeCollection()
        self.credit_card_emi_schedule = _FakeCollection()
        self.credit_alerts = _FakeCollection()
        self.push_subscriptions = _FakeCollection()
        self.chat_logs = _FakeCollection()
        self.support_sessions = _FakeCollection()
        self.telegram_otp_verifications = _FakeCollection()
        self.telegram_register_intents = _FakeCollection()
        self.telegram_tx_sessions = _FakeCollection()
    def __getattr__(self, name):
        coll = _FakeCollection()
        setattr(self, name, coll)
        return coll


class TestInitIndexes(unittest.IsolatedAsyncioTestCase):
    async def test_init_indexes_creates_recurring_and_retry_indexes(self):
        fake_db = _FakeDb()
        with patch("app.db.init_db.db", fake_db):
            await init_indexes()

        created_tx_specs = [spec for spec, _ in fake_db.transactions.created]
        self.assertIn([("recurring_id", 1), ("scheduled_for", 1)], created_tx_specs)
        self.assertIn([("retry_of", 1)], created_tx_specs)
        self.assertIn([("is_failed", 1), ("retry_status", 1)], created_tx_specs)

        created_inbox_specs = [spec for spec, _ in fake_db.transaction_inbox.created]
        self.assertIn([("user_id", 1), ("fingerprint", 1)], created_inbox_specs)
        self.assertIn([("user_id", 1), ("needs_attention", 1), ("status", 1)], created_inbox_specs)

        created_sms_specs = [spec for spec, _ in fake_db.sms_buffer.created]
        self.assertIn([("parsed", 1), ("created_at", 1)], created_sms_specs)

        created_recurring_specs = [spec for spec, _ in fake_db.recurring_deposits.created]
        self.assertIn([("is_active", 1), ("next_run", 1)], created_recurring_specs)
        self.assertIn([("user_id", 1), ("is_active", 1), ("next_run", 1)], created_recurring_specs)

        created_health = [spec for spec, _ in fake_db.financial_health_snapshots.created]
        self.assertIn([("user_id", 1), ("date_key", 1)], created_health)
        created_goals = [spec for spec, _ in fake_db.financial_goals.created]
        self.assertIn([("user_id", 1), ("status", 1), ("created_at", -1)], created_goals)

        created_sessions = [spec for spec, _ in fake_db.auth_sessions.created]
        self.assertIn([("sid", 1)], created_sessions)
        created_rules = [spec for spec, _ in fake_db.financial_rules.created]
        self.assertIn([("user_id", 1), ("enabled", 1), ("priority", -1)], created_rules)

        self.assertIn("name_1", fake_db.accounts.dropped)


if __name__ == "__main__":
    unittest.main()
