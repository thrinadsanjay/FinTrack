import asyncio
import os
import unittest
from unittest.mock import AsyncMock, patch

from app.schedulers import job_lock
from app.services import admin_settings
from tests.fake_mongo import FakeDb


class TestSingletonJob(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.db = FakeDb(scheduler_locks=[])
        stack = [
            patch("app.db.mongo.db", self.db),
            patch.dict(os.environ, {"FT_SCHEDULER_LOCKS": "on"}),
        ]
        for p in stack:
            p.start()
            self.addCleanup(p.stop)

    async def test_concurrent_processes_run_job_once(self):
        runs = []

        @job_lock.singleton_job("demo-job", lease_seconds=60)
        async def job():
            runs.append(1)
            await asyncio.sleep(0.01)

        # Three "workers" fire the same tick.
        await asyncio.gather(job(), job(), job())
        self.assertEqual(len(runs), 1)

    async def test_lease_is_released_for_next_tick(self):
        runs = []

        @job_lock.singleton_job("demo-job", lease_seconds=60)
        async def job():
            runs.append(1)

        await job()
        await job()
        self.assertEqual(len(runs), 2)

    async def test_lease_released_even_when_job_fails(self):
        @job_lock.singleton_job("demo-job", lease_seconds=60)
        async def job():
            raise RuntimeError("boom")

        with self.assertRaises(RuntimeError):
            await job()
        token = await job_lock.acquire_lease("demo-job", 60)
        self.assertIsNotNone(token)


class TestAdminSettingsCache(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        admin_settings.invalidate_admin_settings_cache()
        self.addCleanup(admin_settings.invalidate_admin_settings_cache)

    async def test_settings_read_once_within_ttl_and_copies_are_isolated(self):
        fetch = AsyncMock(return_value={"values": {"application": {"app_name": "X"}}})
        with patch.object(admin_settings, "get_admin_settings_doc", fetch):
            first = await admin_settings.get_admin_settings()
            first["application"]["app_name"] = "mutated"
            second = await admin_settings.get_admin_settings()
        self.assertEqual(fetch.await_count, 1)
        self.assertEqual(second["application"]["app_name"], "X")

    async def test_save_invalidates_cache(self):
        fetch = AsyncMock(return_value=None)
        with patch.object(admin_settings, "get_admin_settings_doc", fetch), \
             patch.object(admin_settings, "db", FakeDb(app_settings=[])):
            await admin_settings.get_admin_settings()
            await admin_settings.save_admin_settings({"application": {}})
            await admin_settings.get_admin_settings()
        self.assertEqual(fetch.await_count, 2)


if __name__ == "__main__":
    unittest.main()
