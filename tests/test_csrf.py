import unittest

from app.core.csrf import CsrfValidationError, get_csrf_token, verify_csrf_token


class _DummyRequest:
    def __init__(self):
        self.session = {}


class TestCsrfHelpers(unittest.TestCase):
    def test_get_csrf_token_creates_and_reuses_token(self):
        request = _DummyRequest()
        first = get_csrf_token(request)
        second = get_csrf_token(request)
        self.assertTrue(first)
        self.assertEqual(first, second)

    def test_verify_csrf_token_accepts_valid_token(self):
        request = _DummyRequest()
        token = get_csrf_token(request)
        verify_csrf_token(request, token)

    def test_verify_csrf_token_rejects_missing_or_invalid_token(self):
        request = _DummyRequest()
        token = get_csrf_token(request)
        with self.assertRaises(CsrfValidationError):
            verify_csrf_token(request, None)
        with self.assertRaises(CsrfValidationError):
            verify_csrf_token(request, token + "-bad")


if __name__ == "__main__":
    unittest.main()
