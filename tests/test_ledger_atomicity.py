"""
Balance/ledger consistency under concurrency (standalone-Mongo fallback path).

These exercise the real service functions against tests/fake_mongo.py, whose
operations interleave under asyncio.gather like a real server.
"""

import asyncio
import unittest
from contextlib import ExitStack
from unittest.mock import AsyncMock, patch

from bson import ObjectId

from app.core.errors import ConflictError
from app.services import transactions as tx_service
from tests.fake_mongo import FakeDb

CATEGORY = {"code": "food", "name": "Food"}
SUBCATEGORY = {"code": "groceries", "name": "Groceries"}


class LedgerTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.user_id = ObjectId()
        self.bank_id = ObjectId()
        self.wallet_id = ObjectId()
        self.db = FakeDb(
            accounts=[
                {"_id": self.bank_id, "user_id": self.user_id, "name": "Bank", "type": "bank", "balance": 100.0, "deleted_at": None},
                {"_id": self.wallet_id, "user_id": self.user_id, "name": "Wallet", "type": "wallet", "balance": 0.0, "deleted_at": None},
            ],
            transactions=[],
        )
        stack = ExitStack()
        for target in ("app.services.transactions.db", "app.db.mongo.db"):
            stack.enter_context(patch(target, self.db))
        for target in (
            "app.services.transactions.audit_log",
            "app.services.audit.audit_log",
            "app.services.transactions.upsert_notification",
            "app.services.rules.apply_transaction_rules",
        ):
            stack.enter_context(patch(target, new=AsyncMock()))
        stack.enter_context(patch("app.services.transactions.increment_transaction"))
        stack.enter_context(
            patch(
                "app.services.transactions.validate_category",
                new=AsyncMock(return_value=(CATEGORY, SUBCATEGORY)),
            )
        )
        self.addCleanup(stack.close)

    def balance(self, account_id):
        return next(a for a in self.db.accounts.docs if a["_id"] == account_id)["balance"]

    def live_rows(self):
        return [t for t in self.db.transactions.docs if not t.get("is_failed") and t.get("deleted_at") is None]

    async def debit(self, amount, account_id=None):
        return await tx_service.create_transaction(
            user_id=str(self.user_id),
            account_id=str(account_id or self.bank_id),
            amount=amount,
            tx_type="debit",
            mode="upi",
            category_code="food",
            subcategory_code="groceries",
            description="Groceries",
        )


class TestCreate(LedgerTestCase):
    async def test_debit_updates_balance_and_ledger(self):
        await self.debit(40)
        self.assertEqual(self.balance(self.bank_id), 60.0)
        self.assertEqual(len(self.live_rows()), 1)

    async def test_insufficient_funds_records_failed_row_without_moving_money(self):
        await self.debit(150)
        self.assertEqual(self.balance(self.bank_id), 100.0)
        self.assertEqual(self.live_rows(), [])
        failed = [t for t in self.db.transactions.docs if t.get("is_failed")]
        self.assertEqual(len(failed), 1)
        self.assertEqual(failed[0]["failure_reason"], "insufficient_funds")

    async def test_concurrent_debits_cannot_overdraw(self):
        # Old read-then-write code let both through (balance -60).
        await asyncio.gather(self.debit(80), self.debit(80))
        self.assertEqual(self.balance(self.bank_id), 20.0)
        self.assertEqual(len(self.live_rows()), 1)

    async def test_transfer_moves_both_sides(self):
        await tx_service.create_transaction(
            user_id=str(self.user_id),
            account_id=str(self.bank_id),
            target_account_id=str(self.wallet_id),
            amount=30,
            tx_type="transfer",
            mode="upi",
            category_code="transfer",
            subcategory_code="self",
            description="Top up",
        )
        self.assertEqual(self.balance(self.bank_id), 70.0)
        self.assertEqual(self.balance(self.wallet_id), 30.0)
        self.assertEqual(len(self.live_rows()), 2)


class TestDeleteRestoreEdit(LedgerTestCase):
    async def test_double_delete_reverses_once(self):
        tx_id = await self.debit(40)
        results = await asyncio.gather(
            tx_service.delete_transaction(user_id=str(self.user_id), transaction_id=str(tx_id)),
            tx_service.delete_transaction(user_id=str(self.user_id), transaction_id=str(tx_id)),
            return_exceptions=True,
        )
        self.assertEqual(sum(isinstance(r, ConflictError) for r in results), 1)
        self.assertEqual(self.balance(self.bank_id), 100.0)

    async def test_double_restore_applies_once(self):
        tx_id = await self.debit(40)
        await tx_service.delete_transaction(user_id=str(self.user_id), transaction_id=str(tx_id))
        await asyncio.gather(
            tx_service.restore_transaction(user_id=str(self.user_id), transaction_id=str(tx_id)),
            tx_service.restore_transaction(user_id=str(self.user_id), transaction_id=str(tx_id)),
            return_exceptions=True,
        )
        self.assertEqual(self.balance(self.bank_id), 60.0)

    async def test_edit_moving_account_moves_full_amount(self):
        self.db.accounts.docs[1]["balance"] = 50.0
        tx_id = await self.debit(40)
        await tx_service.edit_transaction(
            user_id=str(self.user_id),
            transaction_id=str(tx_id),
            new_account_id=str(self.wallet_id),
            new_amount=25,
            new_category_code="food",
            new_subcategory_code="groceries",
            new_description="Groceries",
        )
        self.assertEqual(self.balance(self.bank_id), 100.0)
        self.assertEqual(self.balance(self.wallet_id), 25.0)

    async def test_edit_same_account_applies_difference(self):
        tx_id = await self.debit(40)
        await tx_service.edit_transaction(
            user_id=str(self.user_id),
            transaction_id=str(tx_id),
            new_account_id=str(self.bank_id),
            new_amount=10,
            new_category_code="food",
            new_subcategory_code="groceries",
            new_description="Groceries",
        )
        self.assertEqual(self.balance(self.bank_id), 90.0)


class TestRetry(LedgerTestCase):
    async def test_retry_posts_once_when_funds_arrive(self):
        failed_id = await self.debit(150)
        self.db.accounts.docs[0]["balance"] = 500.0
        results = await asyncio.gather(
            tx_service.retry_failed_recurring_transaction(user_id=str(self.user_id), failed_transaction_id=str(failed_id)),
            tx_service.retry_failed_recurring_transaction(user_id=str(self.user_id), failed_transaction_id=str(failed_id)),
            return_exceptions=True,
        )
        self.assertIn(True, results)
        self.assertEqual(self.balance(self.bank_id), 350.0)
        self.assertEqual(len(self.live_rows()), 1)
        failed = next(t for t in self.db.transactions.docs if t["_id"] == failed_id)
        self.assertEqual(failed["retry_status"], "resolved")

    async def test_retry_without_funds_stays_pending(self):
        failed_id = await self.debit(150)
        ok = await tx_service.retry_failed_recurring_transaction(
            user_id=str(self.user_id), failed_transaction_id=str(failed_id)
        )
        self.assertFalse(ok)
        self.assertEqual(self.balance(self.bank_id), 100.0)
        failed = next(t for t in self.db.transactions.docs if t["_id"] == failed_id)
        self.assertEqual(failed["retry_status"], "pending")


if __name__ == "__main__":
    unittest.main()
