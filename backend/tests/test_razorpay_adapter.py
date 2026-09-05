import unittest
from unittest.mock import MagicMock, patch

from app.config import Config
from app.core.razorpay_adapter import (
    PaymentStatus,
    create_order,
    verify_webhook_signature,
)


class TestRazorpaySimulationMode(unittest.TestCase):
    def setUp(self):
        self._orig_id = Config.RAZORPAY_KEY_ID
        self._orig_secret = Config.RAZORPAY_KEY_SECRET
        Config.RAZORPAY_KEY_ID = ""
        Config.RAZORPAY_KEY_SECRET = ""

    def tearDown(self):
        Config.RAZORPAY_KEY_ID = self._orig_id
        Config.RAZORPAY_KEY_SECRET = self._orig_secret

    def test_simulation_mode_when_no_credentials(self):
        result = create_order(720000, "receipt-1")
        self.assertEqual(result.status, PaymentStatus.SIMULATED)
        self.assertEqual(result.mode, "simulation")
        self.assertIn("[SIMULATION]", result.label)

    def test_simulation_never_claims_real(self):
        result = create_order(720000, "receipt-2")
        self.assertNotEqual(result.mode, "real_test_mode")

    def test_rejects_non_positive_amount(self):
        with self.assertRaises(ValueError):
            create_order(0, "receipt-3")


class TestRazorpayRealMode(unittest.TestCase):
    def setUp(self):
        self._orig_id = Config.RAZORPAY_KEY_ID
        self._orig_secret = Config.RAZORPAY_KEY_SECRET
        Config.RAZORPAY_KEY_ID = "rzp_test_fake"
        Config.RAZORPAY_KEY_SECRET = "fake_secret"

    def tearDown(self):
        Config.RAZORPAY_KEY_ID = self._orig_id
        Config.RAZORPAY_KEY_SECRET = self._orig_secret

    @patch("app.core.razorpay_adapter.urllib.request.urlopen")
    def test_successful_real_order(self, mock_urlopen):
        fake_response = MagicMock()
        fake_response.read.return_value = b'{"id": "order_abc123"}'
        mock_urlopen.return_value.__enter__.return_value = fake_response

        result = create_order(720000, "receipt-4")
        self.assertEqual(result.status, PaymentStatus.CREATED)
        self.assertEqual(result.mode, "real_test_mode")
        self.assertEqual(result.razorpay_order_id, "order_abc123")

    @patch("app.core.razorpay_adapter.urllib.request.urlopen")
    def test_http_failure_never_becomes_simulation(self, mock_urlopen):
        import urllib.error
        import io

        mock_urlopen.side_effect = urllib.error.HTTPError(
            "url", 401, "Unauthorized", {}, io.BytesIO(b'{"error":"bad key"}')
        )
        result = create_order(720000, "receipt-5")
        self.assertEqual(result.status, PaymentStatus.FAILED)
        self.assertEqual(result.mode, "real_test_mode")  # NOT simulation
        self.assertIsNotNone(result.failure_reason)

    @patch("app.core.razorpay_adapter.urllib.request.urlopen")
    def test_network_failure_never_becomes_simulation(self, mock_urlopen):
        import urllib.error

        mock_urlopen.side_effect = urllib.error.URLError("timed out")
        result = create_order(720000, "receipt-6")
        self.assertEqual(result.status, PaymentStatus.FAILED)
        self.assertEqual(result.mode, "real_test_mode")


class TestWebhookSignature(unittest.TestCase):
    def setUp(self):
        self._orig_secret = Config.RAZORPAY_WEBHOOK_SECRET
        Config.RAZORPAY_WEBHOOK_SECRET = "whsec_test"

    def tearDown(self):
        Config.RAZORPAY_WEBHOOK_SECRET = self._orig_secret

    def test_valid_signature_accepted(self):
        import hashlib
        import hmac

        body = b'{"event": "payment.captured"}'
        sig = hmac.new(b"whsec_test", body, hashlib.sha256).hexdigest()
        self.assertTrue(verify_webhook_signature(body, sig))

    def test_invalid_signature_rejected(self):
        self.assertFalse(verify_webhook_signature(b"{}", "not-a-real-signature"))

    def test_unconfigured_secret_rejects_everything(self):
        Config.RAZORPAY_WEBHOOK_SECRET = ""
        self.assertFalse(verify_webhook_signature(b"{}", "anything"))


if __name__ == "__main__":
    unittest.main()
