"""JSON API for transactions: validation, service wiring, serialization."""

import unittest
from unittest.mock import AsyncMock, patch

from bson import ObjectId
from fastapi.testclient import TestClient

from app.main import app
from app.routers.deps import get_current_user_valid

USER = {"user_id": str(ObjectId()), "is_admin": False}


class TestTransactionsApi(unittest.TestCase):
    def setUp(self):
        app.dependency_overrides[get_current_user_valid] = lambda: USER
        self.addCleanup(app.dependency_overrides.clear)
        # No `with`: skip lifespan (indexes, schedulers) — these are unit tests.
        self.client = TestClient(app)
        settings_patch = patch("app.main.get_admin_settings", new=AsyncMock(return_value={}))
        maint_patch = patch(
            "app.main.get_maintenance_state",
            new=AsyncMock(return_value={"enabled": False, "message": ""}),
        )
        for p in (settings_patch, maint_patch):
            p.start()
            self.addCleanup(p.stop)

    def test_transfer_without_target_is_rejected(self):
        resp = self.client.post(
            "/api/transactions/",
            json={
                "account_id": str(ObjectId()),
                "amount": 10,
                "tx_type": "transfer",
                "category_code": "transfer",
                "subcategory_code": "self",
            },
        )
        self.assertEqual(resp.status_code, 422)

    def test_non_positive_amount_is_rejected(self):
        resp = self.client.post(
            "/api/transactions/",
            json={
                "account_id": str(ObjectId()),
                "amount": 0,
                "tx_type": "debit",
                "category_code": "food",
                "subcategory_code": "groceries",
            },
        )
        self.assertEqual(resp.status_code, 422)

    def test_create_passes_full_payload_to_service(self):
        tx_id = ObjectId()
        create = AsyncMock(return_value=tx_id)
        account_id, target_id = str(ObjectId()), str(ObjectId())
        with patch("app.routers.transactions.create_transaction", create):
            resp = self.client.post(
                "/api/transactions/",
                json={
                    "account_id": account_id,
                    "target_account_id": target_id,
                    "amount": 250.5,
                    "tx_type": "card_payment",
                    "mode": "upi",
                    "category_code": "transfer",
                    "subcategory_code": "card",
                    "credit_bill_id": "bill-1",
                    "transaction_date": "2026-09-01",
                },
            )
        self.assertEqual(resp.status_code, 201, resp.text)
        self.assertEqual(resp.json(), {"id": str(tx_id), "recurring_rule_only": False})
        kwargs = create.await_args.kwargs
        self.assertEqual(kwargs["user_id"], USER["user_id"])
        self.assertEqual(kwargs["target_account_id"], target_id)
        self.assertEqual(kwargs["transfer_kind"], "card_payment")
        self.assertEqual(kwargs["credit_bill_id"], "bill-1")
        self.assertEqual(str(kwargs["transaction_date"]), "2026-09-01")

    def test_list_serializes_object_ids_and_pages(self):
        row = {
            "_id": ObjectId(),
            "account_id": ObjectId(),
            "amount": 10.0,
            "category": {"code": "food", "name": "Food"},
        }
        listing = AsyncMock(return_value=[row])
        with patch("app.routers.transactions.get_user_transactions", listing):
            resp = self.client.get("/api/transactions/?limit=5&skip=10")
        self.assertEqual(resp.status_code, 200, resp.text)
        item = resp.json()["items"][0]
        self.assertEqual(item["id"], str(row["_id"]))
        self.assertEqual(item["account_id"], str(row["account_id"]))
        self.assertEqual(listing.await_args.kwargs["limit"], 5)
        self.assertEqual(listing.await_args.kwargs["skip"], 10)

    def test_delete_maps_to_service(self):
        delete = AsyncMock()
        tx_id = str(ObjectId())
        with patch("app.routers.transactions.delete_transaction", delete):
            resp = self.client.delete(f"/api/transactions/{tx_id}")
        self.assertEqual(resp.status_code, 204)
        self.assertEqual(delete.await_args.kwargs["transaction_id"], tx_id)


if __name__ == "__main__":
    unittest.main()
