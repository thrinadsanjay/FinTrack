"""Single-page Profile: profile card + actions, account & security, real active sessions.
Security Center stays application-level (status, sessions overview, activity)."""

import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

from bson import ObjectId

from app.services import users as users_service
from app.web import profile as web_profile
from app.web import security as web_security
from tests.fake_mongo import FakeDb
from tests.test_goals_page import _request

UID = ObjectId()


def _user(**over):
    doc = {
        "_id": UID, "username": "admin", "first_name": "Sanjay", "last_name": "C", "full_name": "Sanjay C",
        "email": "admin@example.com", "auth_provider": "local", "password_hash": "x", "is_admin": True,
        "is_active": True, "deleted_at": None, "session_epoch": 0,
        "created_at": datetime(2026, 1, 5, tzinfo=timezone.utc),
        "last_login_at": datetime(2026, 9, 24, 8, 0, tzinfo=timezone.utc),
        "password_changed_at": datetime(2026, 3, 1, tzinfo=timezone.utc),
        "passkeys": [], "biometric_enabled": True,
    }
    doc.update(over)
    return doc


class PageCase(unittest.IsolatedAsyncioTestCase):
    def patch_all(self, user_doc, telegram_enabled=False):
        db = FakeDb(users=[user_doc], accounts=[], transactions=[], recurring_deposits=[], notifications=[],
                    auth_sessions=[{"_id": ObjectId(), "user_id": UID, "revoked_at": None, "sid": "s1"},
                                   {"_id": ObjectId(), "user_id": UID, "revoked_at": None, "sid": "s2"}],
                    audit_logs=[])
        patches = [
            patch("app.core.guards.db", db),
            patch.object(web_profile, "db", db),
            patch("app.services.sessions.db", db),
            patch("app.services.security_center.db", db),
            patch.object(web_profile, "get_user_by_id", new=AsyncMock(return_value=user_doc)),
            patch.object(web_profile, "get_admin_settings", new=AsyncMock(return_value={"telegram": {"enabled": telegram_enabled}})),
            patch.object(web_profile, "get_user_notifications", new=AsyncMock(return_value=[])),
            patch.object(web_security, "get_user_notifications", new=AsyncMock(return_value=[])),
            patch("app.services.security_center.touch_session", new=AsyncMock()),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def request(self):
        req = _request()
        req.session["user"] = {"user_id": str(UID), "username": "admin", "is_admin": True}
        return req


CHROME_WIN = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/116.0.5845.97 Safari/537.36"
FIREFOX_LINUX = "Mozilla/5.0 (X11; Linux x86_64; rv:117.0) Gecko/20100101 Firefox/117.0"


def _sessions():
    return [
        {"_id": ObjectId(), "user_id": UID, "revoked_at": None, "sid": "other", "ip": "103.12.45.67",
         "user_agent": CHROME_WIN, "last_seen_at": datetime(2026, 9, 24, 11, 0, tzinfo=timezone.utc)},
        {"_id": ObjectId(), "user_id": UID, "revoked_at": None, "sid": "mine", "ip": "192.168.1.10",
         "user_agent": FIREFOX_LINUX, "last_seen_at": datetime(2026, 9, 24, 9, 0, tzinfo=timezone.utc)},
    ]


class TestProfilePage(PageCase):
    def request(self):
        req = super().request()
        req.session["sid"] = "mine"
        return req

    def patch_all(self, user_doc, telegram_enabled=False):
        super().patch_all(user_doc, telegram_enabled=telegram_enabled)
        # Replace the generic session docs with realistic ones.
        from app.services import sessions as sessions_service
        sessions_service.db.auth_sessions.docs = _sessions()

    async def render(self, **kw):
        return (await web_profile.edit_profile_page(self.request())).body.decode()

    async def test_single_page_structure(self):
        self.patch_all(_user())
        html = await self.render()
        for text in ("Manage your account, security and preferences", "Account &amp; Security",
                     "Manage your login credentials and security settings.", "Active Sessions",
                     "Transactions this month", "Recurring plans", "Unread alerts",
                     "Link Telegram", "Disable account", "Delete account", 'aria-label="Edit profile"'):
            self.assertIn(text, html)
        # No tabs, no Telegram/Danger-zone sections.
        for gone in ("data-profile-tab", "data-profile-panel", "Danger zone", 'id="telegram"'):
            self.assertNotIn(gone, html)

    async def test_password_form_only_inside_reset_dialog(self):
        self.patch_all(_user())
        html = await self.render()
        self.assertIn("••••••••••••", html)
        self.assertIn('data-dialog-open="password"', html)
        dialog = html[html.index('data-dialog="password"'):]
        dialog = dialog[:dialog.index("</dialog>")]
        self.assertIn('name="current_password"', dialog)
        self.assertEqual(html.count('name="current_password"'), 1)
        # Never pre-filled by the server, and the old password isn't offered for autofill.
        import re
        for field in re.findall(r'<input[^>]*name="(?:current|new|confirm)_password"[^>]*>', dialog):
            self.assertNotIn("value=", field)
        current = re.search(r'<input[^>]*name="current_password"[^>]*>', dialog).group(0)
        self.assertIn('autocomplete="off"', current)
        self.assertIn("data-clear-on-open", dialog)

    async def test_sessions_table_uses_real_data(self):
        self.patch_all(_user())
        html = await self.render()
        table = html[html.index('class="prf-table"'):html.index("</table>")]
        # Current session first, parsed browser/OS, real IPs.
        self.assertLess(table.index("Firefox 117.0 (Linux)"), table.index("Chrome 116.0 (Windows)"))
        self.assertIn("192.168.1.10", table)
        self.assertIn("103.12.45.67", table)
        self.assertEqual(table.count('ft-badge--positive">Current<'), 1)
        self.assertEqual(table.count("/revoke"), 1)  # only the other device can be signed out
        self.assertNotIn("Location", table)          # no location data stored -> column omitted

    async def test_passkey_state(self):
        self.patch_all(_user())
        html = await self.render()
        card = html[html.index('id="prf-pk-title"'):html.index('id="sessions"')]
        self.assertIn("Not registered", card)
        self.assertIn("Add passkey", card)
        self.assertNotIn("ft-badge--positive", card)
        self.patch_all(_user(passkeys=[{"credential_id": "a"}, {"credential_id": "b"}]))
        html = await self.render()
        card = html[html.index('id="prf-pk-title"'):html.index('id="sessions"')]
        self.assertIn("2 passkeys", card)
        self.assertIn("Biometric login is enabled.", card)

    async def test_telegram_disabled_has_tooltip_and_no_dialog(self):
        self.patch_all(_user(), telegram_enabled=False)
        html = await self.render()
        self.assertIn('aria-disabled="true"', html)
        self.assertIn("Telegram integration is not enabled by the administrator.", html)
        self.assertNotIn('data-dialog="telegram"', html)

    async def test_telegram_enabled_opens_linking_dialog(self):
        self.patch_all(_user(), telegram_enabled=True)
        html = await self.render()
        self.assertIn('data-dialog-open="telegram"', html)
        dialog = html[html.index('data-dialog="telegram"'):]
        self.assertIn("data-telegram-send", dialog[:dialog.index("</dialog>")])

    async def test_destructive_actions_require_confirmation(self):
        self.patch_all(_user())
        html = await self.render()
        for name, gate in (("disable", "data-confirm-check"), ("delete", 'data-confirm-text="DELETE"')):
            dialog = html[html.index(f'data-dialog="{name}"'):]
            dialog = dialog[:dialog.index("</dialog>")]
            self.assertIn(gate, dialog)
            self.assertIn("data-confirm-submit disabled", dialog)


class TestSessionRevoke(PageCase):
    async def test_revoke_other_session_and_refuse_current(self):
        from app.services import sessions as sessions_service

        self.patch_all(_user())
        sessions_service.db.auth_sessions.docs = _sessions()
        other, mine = sessions_service.db.auth_sessions.docs
        self.assertTrue(await sessions_service.revoke_session(str(UID), str(other["_id"]), current_sid="mine"))
        self.assertIsNotNone(other["revoked_at"])
        with self.assertRaises(ValueError):
            await sessions_service.revoke_session(str(UID), str(mine["_id"]), current_sid="mine")
        # Someone else's session id is simply not found.
        self.assertFalse(await sessions_service.revoke_session(str(ObjectId()), str(mine["_id"]), current_sid=None))
        self.assertTrue(await sessions_service.is_sid_revoked("other"))
        self.assertFalse(await sessions_service.is_sid_revoked("mine"))

    async def test_web_guard_rejects_revoked_cookie(self):
        from app.services import sessions as sessions_service

        self.patch_all(_user())
        sessions_service.db.auth_sessions.docs = _sessions()
        sessions_service.db.auth_sessions.docs[0]["revoked_at"] = datetime.now(timezone.utc)
        req = self.request()
        req.session["sid"] = "other"
        resp = await web_profile.edit_profile_page(req)
        self.assertEqual(resp.headers.get("location"), "/login")


class TestSecurityCenter(PageCase):
    async def test_security_center_is_app_level_and_links_to_profile(self):
        self.patch_all(_user())
        html = (await web_security.security_center_page(self.request())).body.decode()
        for gone in ('name="current_password"', "data-passkey-register", "data-biometric-toggle", "/static/js/profile.js"):
            self.assertNotIn(gone, html)
        self.assertIn('href="/profile#password"', html)
        self.assertIn('id="sessions"', html)


class TestPasswordAndProfileEdits(unittest.IsolatedAsyncioTestCase):
    async def test_password_mismatch_returns_to_account_access(self):
        req = _request()
        req.session["user"] = {"user_id": str(UID)}
        req.session["csrf_token"] = "tok"
        fake = FakeDb(users=[_user()])
        with patch("app.core.guards.db", fake), \
             patch.object(web_profile, "get_user_by_id", new=AsyncMock(return_value=_user())):
            resp = await web_profile.reset_password_submit(
                req, current_password="a", new_password="abcdefgh", confirm_password="different", csrf_token="tok")
        self.assertEqual(resp.headers["location"], "/profile#password")
        self.assertEqual(req.session["ft_flash"]["tone"], "error")

    async def test_update_own_profile_validates_and_keeps_password_date(self):
        fake = FakeDb(users=[_user(updated_at=datetime(2026, 3, 1, tzinfo=timezone.utc))])
        with patch.object(users_service, "db", fake), patch.object(users_service, "audit_log", new=AsyncMock()):
            with self.assertRaises(ValueError):
                await users_service.update_own_profile(user_id=str(UID), first_name="", last_name="", phone="")
            with self.assertRaises(ValueError):
                await users_service.update_own_profile(user_id=str(UID), first_name="A", last_name="", phone="call me")
            out = await users_service.update_own_profile(user_id=str(UID), first_name="Sanjay", last_name="Kumar", phone="+91 98765 43210")
        doc = fake.users.docs[0]
        self.assertEqual(out["full_name"], "Sanjay Kumar")
        self.assertEqual(doc["phone"], "+91 98765 43210")
        self.assertEqual(doc["updated_at"], datetime(2026, 3, 1, tzinfo=timezone.utc))  # untouched

    async def test_password_change_records_timestamp(self):
        fake = FakeDb(users=[_user(password_changed_at=None)])
        with patch.object(users_service, "db", fake), patch.object(users_service, "audit_log", new=AsyncMock()):
            await users_service.update_user_password(str(UID), "new-password-123")
        self.assertIsNotNone(fake.users.docs[0]["password_changed_at"])


if __name__ == "__main__":
    unittest.main()
