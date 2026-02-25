import unittest

from app.web.profile import _external_password_reset_url
from app.core.config import settings


class TestProfilePasswordResetUrl(unittest.TestCase):
    def test_configured_override_url_takes_precedence(self):
        original = settings.FT_EXTERNAL_PASSWORD_RESET_URL
        settings.FT_EXTERNAL_PASSWORD_RESET_URL = "https://myaccount.google.com/security"
        try:
            url = _external_password_reset_url({"identity_provider": "github"})
        finally:
            settings.FT_EXTERNAL_PASSWORD_RESET_URL = original
        self.assertEqual(url, "https://myaccount.google.com/security")

    def test_google_idp_uses_google_account_page(self):
        original = settings.FT_EXTERNAL_PASSWORD_RESET_URL
        settings.FT_EXTERNAL_PASSWORD_RESET_URL = None
        try:
            url = _external_password_reset_url({"identity_provider": "google"})
        finally:
            settings.FT_EXTERNAL_PASSWORD_RESET_URL = original
        self.assertEqual(url, "https://myaccount.google.com/security")

    def test_non_google_idp_falls_back_to_keycloak_account_page(self):
        original = settings.FT_EXTERNAL_PASSWORD_RESET_URL
        settings.FT_EXTERNAL_PASSWORD_RESET_URL = None
        try:
            url = _external_password_reset_url({"identity_provider": "github"})
        finally:
            settings.FT_EXTERNAL_PASSWORD_RESET_URL = original
        self.assertEqual(
            url,
            f"{settings.FT_KEYCLOAK_URL.rstrip('/')}/realms/{settings.FT_KEYCLOAK_REALM}/account/#/security/signingin",
        )


if __name__ == "__main__":
    unittest.main()
