import unittest

try:
    from fastapi import HTTPException
    from core.webhook_auth import verify_shared_secret
except ImportError:  # pragma: no cover
    HTTPException = None
    verify_shared_secret = None


@unittest.skipUnless(HTTPException, "fastapi is not installed in this interpreter")
class WebhookAuthTests(unittest.TestCase):
    def test_rejects_missing_config(self):
        with self.assertRaises(HTTPException) as raised:
            verify_shared_secret("token", "", missing_detail="not configured")
        self.assertEqual(raised.exception.status_code, 503)

    def test_rejects_wrong_secret(self):
        with self.assertRaises(HTTPException) as raised:
            verify_shared_secret("wrong", "expected", missing_detail="not configured")
        self.assertEqual(raised.exception.status_code, 403)

    def test_accepts_matching_secret(self):
        verify_shared_secret("expected", "expected", missing_detail="not configured")


if __name__ == "__main__":
    unittest.main()
