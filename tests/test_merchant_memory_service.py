import unittest
from types import SimpleNamespace
from unittest.mock import patch

from bson import ObjectId

from app.services.categorization.description_cleaner import clean_description
from app.services.categorization.merchant_extractor import extract_merchant_key
from app.services.categorization.merchant_memory_service import add_alias, learn, lookup
import app.services.categorization.merchant_extractor as merchant_extractor_module
import app.services.categorization.merchant_memory_service as merchant_memory_module


class FakeUpdateResult:
    def __init__(self, modified_count=1):
        self.modified_count = modified_count


class FakeInsertResult:
    def __init__(self, inserted_id):
        self.inserted_id = inserted_id


class FakeCollection:
    def __init__(self):
        self.docs = []

    @staticmethod
    def _match_value(actual, expected):
        if isinstance(expected, dict):
            if "$in" in expected:
                return actual in expected["$in"]
            return False
        return actual == expected

    def _match(self, doc, query):
        for key, expected in query.items():
            if not self._match_value(doc.get(key), expected):
                return False
        return True

    async def find_one(self, query, projection=None, sort=None):
        matches = [doc for doc in self.docs if self._match(doc, query)]
        if not matches:
            return None
        if sort:
            for field, direction in reversed(sort):
                matches.sort(key=lambda item: item.get(field), reverse=direction < 0)
        doc = dict(matches[0])
        if projection:
            include_keys = {key for key, value in projection.items() if value}
            if include_keys:
                doc = {key: value for key, value in doc.items() if key in include_keys}
        return doc

    async def update_one(self, query, update, upsert=False):
        target = None
        for doc in self.docs:
            if self._match(doc, query):
                target = doc
                break
        if target is None:
            if not upsert:
                return FakeUpdateResult(0)
            target = dict(query)
            self.docs.append(target)

        for key, value in update.get("$set", {}).items():
            target[key] = value
        for key, value in update.get("$setOnInsert", {}).items():
            target.setdefault(key, value)
        for key, value in update.get("$inc", {}).items():
            target[key] = target.get(key, 0) + value
        return FakeUpdateResult(1)

    async def insert_one(self, doc):
        stored = dict(doc)
        stored.setdefault("_id", ObjectId())
        self.docs.append(stored)
        return FakeInsertResult(stored["_id"])


class TestMerchantMemoryService(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.fake_db = SimpleNamespace(
            merchant_memory=FakeCollection(),
            merchant_aliases=FakeCollection(),
            categorization_feedback=FakeCollection(),
        )
        self.user_id = ObjectId()
        self.patches = [
            patch.object(merchant_memory_module, "db", self.fake_db),
            patch.object(merchant_extractor_module, "db", self.fake_db),
        ]
        for patcher in self.patches:
            patcher.start()

    def tearDown(self):
        for patcher in reversed(self.patches):
            patcher.stop()

    def test_clean_description_removes_noise(self):
        cleaned = clean_description("UPI/DR/736262/AMZN PAY INDIA/RefNo 736262")
        # "pay" and "india" are deliberate NOISE_WORDS so the memory key stays stable.
        self.assertEqual(cleaned, "amzn")

    def test_clean_description_removes_txn_ids_and_dates(self):
        cleaned = clean_description("POS CARD TXN 12/05/2026 AMAZON 44332211")
        self.assertEqual(cleaned, "amazon")

    async def test_add_alias_and_extract_merchant_key(self):
        await add_alias(user_id=self.user_id, alias_key="amzn pay", cleaned_key="amazon")
        merchant_key = await extract_merchant_key(
            user_id=self.user_id,
            cleaned_description="amzn pay india",
        )
        self.assertEqual(merchant_key, "amazon")

    async def test_learn_and_lookup_returns_category_info(self):
        await learn(
            user_id=self.user_id,
            cleaned_key="amazon",
            merchant_name="Amazon",
            category="Shopping",
            subcategory="Online",
            category_code="expense",
            subcategory_code="online",
        )

        memory = await lookup(user_id=self.user_id, cleaned_key="amazon")
        self.assertIsNotNone(memory)
        self.assertEqual(memory["merchant_name"], "Amazon")
        self.assertEqual(memory["category"], "Shopping")
        self.assertEqual(memory["subcategory"], "Online")
        self.assertEqual(memory["category_code"], "expense")
        self.assertEqual(memory["subcategory_code"], "online")

    async def test_lookup_updates_usage_count(self):
        await learn(
            user_id=self.user_id,
            cleaned_key="swiggy",
            merchant_name="Swiggy",
            category="Food",
            subcategory="Delivery",
        )
        before = self.fake_db.merchant_memory.docs[0]["usage_count"]

        await lookup(user_id=self.user_id, cleaned_key="swiggy")

        after = self.fake_db.merchant_memory.docs[0]["usage_count"]
        self.assertGreater(after, before)


if __name__ == "__main__":
    unittest.main()
