import unittest
from urllib.parse import urlparse, parse_qs

from starlette.requests import Request
from starlette.responses import RedirectResponse

from app.web.auth import login_oauth, callback


def _make_request() -> Request:
    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "GET",
        "path": "/login/oauth",
        "raw_path": b"/login/oauth",
        "query_string": b"",
        "headers": [],
        "client": ("127.0.0.1", 12345),
        "server": ("testserver", 80),
        "scheme": "http",
        "session": {},
    }
    return Request(scope)


class TestOAuthState(unittest.IsolatedAsyncioTestCase):
    async def test_login_oauth_sets_state_and_redirect_contains_it(self):
        request = _make_request()
        response = await login_oauth(request)

        self.assertIsInstance(response, RedirectResponse)
        self.assertIn("oauth_state", request.session)

        location = response.headers.get("location", "")
        query = parse_qs(urlparse(location).query)
        self.assertEqual(query.get("state", [None])[0], request.session["oauth_state"])

    async def test_callback_rejects_invalid_state(self):
        request = _make_request()
        request.session["oauth_state"] = "expected-state"

        response = await callback(request, code="dummy-code", state="wrong-state")
        self.assertIsInstance(response, RedirectResponse)
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers.get("location"), "/login?error=oauth_state")


if __name__ == "__main__":
    unittest.main()
