import unittest
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.core.csrf import CsrfValidationError
from app.main import csrf_exception_handler


def _make_request(*, accept: str) -> Request:
    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "GET",
        "path": "/test",
        "raw_path": b"/test",
        "query_string": b"",
        "headers": [(b"accept", accept.encode("utf-8"))],
        "client": ("127.0.0.1", 12345),
        "server": ("testserver", 80),
        "scheme": "http",
        "session": {},
    }
    return Request(scope)


class TestErrorHandlers(unittest.IsolatedAsyncioTestCase):
    async def test_csrf_handler_returns_json_for_non_html_accept(self):
        request = _make_request(accept="application/json")
        response = await csrf_exception_handler(request, CsrfValidationError("Invalid CSRF token"))
        self.assertIsInstance(response, JSONResponse)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.body, b'{"detail":"Invalid CSRF token"}')

    async def test_csrf_handler_returns_html_for_html_accept(self):
        request = _make_request(accept="text/html")
        response = await csrf_exception_handler(request, CsrfValidationError("Invalid CSRF token"))
        self.assertEqual(response.status_code, 403)
        self.assertIn("text/html", response.media_type or "")


if __name__ == "__main__":
    unittest.main()
