import unittest

from app.core import session as session_module


class TestSessionCookie(unittest.TestCase):
    def test_https_only_enabled_for_https_base_url(self):
        original_env = session_module.settings.FT_ENV
        original_base_url = session_module.settings.FT_BASE_URL
        try:
            session_module.settings.FT_ENV = "development"
            session_module.settings.FT_BASE_URL = "https://example.com"
            self.assertTrue(session_module._session_https_only())
        finally:
            session_module.settings.FT_ENV = original_env
            session_module.settings.FT_BASE_URL = original_base_url

    def test_https_only_disabled_for_plain_http_dev_url(self):
        original_env = session_module.settings.FT_ENV
        original_base_url = session_module.settings.FT_BASE_URL
        try:
            session_module.settings.FT_ENV = "development"
            session_module.settings.FT_BASE_URL = "http://localhost:8000"
            self.assertFalse(session_module._session_https_only())
        finally:
            session_module.settings.FT_ENV = original_env
            session_module.settings.FT_BASE_URL = original_base_url


if __name__ == "__main__":
    unittest.main()
