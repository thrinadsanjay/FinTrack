"""Mobile shell: Inbox page, bottom nav + account sheet, PWA manifest and service worker."""

import json
import re
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

from bson import ObjectId

from app.web import notifications as web_notifications
from tests.fake_mongo import FakeDb
from tests.test_goals_page import UID, _request

STATIC = Path("app/frontend/static")
NOW = datetime(2026, 9, 24, 10, 0, tzinfo=timezone.utc)


def _notification(title, is_read=False):
    return {"_id": ObjectId(), "title": title, "message": f"{title} details", "is_read": is_read, "created_at": NOW}


class TestInboxPage(unittest.IsolatedAsyncioTestCase):
    async def render(self, rows, pending=0):
        fake_db = FakeDb(users=[{"_id": UID, "deleted_at": None, "is_active": True, "session_epoch": 0}])
        patches = [
            patch("app.core.guards.db", fake_db),
            patch.object(web_notifications, "list_notifications", new=AsyncMock(return_value=rows)),
            patch.object(web_notifications, "count_pending_review", new=AsyncMock(return_value=pending)),
            patch.object(web_notifications, "get_user_notifications", new=AsyncMock(return_value=rows)),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        response = await web_notifications.inbox_page(_request())
        self.assertEqual(response.status_code, 200)
        return response.body.decode()

    async def test_lists_notifications_and_review_card(self):
        html = await self.render([_notification("Rent due"), _notification("Large spend", is_read=True)], pending=3)
        self.assertIn("Rent due", html)
        self.assertIn("Large spend", html)
        self.assertIn("3 transactions to review", html)
        self.assertIn('href="/transaction-inbox"', html)
        self.assertIn("data-ibx-read-all", html)

    async def test_empty_state_hides_review_and_mark_all(self):
        html = await self.render([], pending=0)
        self.assertNotIn("to review", html)
        self.assertRegex(html, r"data-ibx-read-all\s+hidden")

    async def test_bottom_nav_and_account_sheet(self):
        html = await self.render([_notification("Rent due")])
        nav = re.search(r'<nav class="ft-mobile-nav".*?</nav>', html, re.S).group(0)
        hrefs = re.findall(r'href="([^"]+)"', nav)
        self.assertEqual(hrefs, ["/", "/transactions/list", "/transactions/list?add=1", "/accounts", "/notifications"])
        self.assertNotIn("/admin", nav)  # Admin lives in the account menu only
        self.assertRegex(nav, r'href="/notifications"[^>]*is-active|is-active[^>]*href="/notifications"')
        self.assertIn("data-account-sheet ", html)
        for needle in ('href="/profile"', 'href="/help-support"', 'data-theme-pref="system"', 'href="/logout"', 'href="/admin'):
            self.assertIn(needle, html)


class TestPwaAssets(unittest.TestCase):
    def test_manifest_is_installable(self):
        manifest = json.loads((STATIC / "manifest.json").read_text(encoding="utf-8"))
        for key in ("name", "short_name", "start_url", "display", "icons", "theme_color", "background_color"):
            self.assertIn(key, manifest)
        self.assertEqual(manifest["display"], "standalone")
        sizes = {i["sizes"] for i in manifest["icons"]}
        self.assertTrue({"192x192", "512x512"} <= sizes, sizes)
        for icon in manifest["icons"]:
            self.assertTrue(icon["src"].startswith("/static/"), icon["src"])
            self.assertTrue((STATIC / icon["src"][len("/static/"):]).is_file(), icon["src"])

    def test_service_worker_never_caches_pages_or_api(self):
        sw = (STATIC / "sw.js").read_text(encoding="utf-8")
        # Navigations are network-only (offline page fallback); only /static/ assets are cached.
        self.assertIn('req.mode === "navigate"', sw)
        self.assertIn("/static/", sw)
        self.assertNotRegex(sw, r"cache\.put\([^)]*/api")
        self.assertIn('"clear"', sw)


class TestServiceWorkerRoute(unittest.IsolatedAsyncioTestCase):
    async def test_served_from_root_without_long_cache(self):
        from app.main import service_worker

        response = await service_worker()
        self.assertEqual(response.headers["service-worker-allowed"], "/")
        self.assertEqual(response.headers["cache-control"], "no-cache")
        self.assertEqual(response.media_type, "application/javascript")


if __name__ == "__main__":
    unittest.main()
