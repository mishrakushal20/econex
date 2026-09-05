import json
import os
import threading
import time
import unittest
import urllib.error
import urllib.request

from app.api.server import create_server
from app.config import Config
from app.core.domain import MerchantPolicy, Product
from app.database import get_connection
from app.repositories import merchant_repo


def _request(method, url, body=None, token=None, headers=None):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    hdrs = {"Content-Type": "application/json"}
    if token:
        hdrs["Authorization"] = f"Bearer {token}"
    if headers:
        hdrs.update(headers)
    req = urllib.request.Request(url, data=data, method=method, headers=hdrs)
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


class TestPaymentAuthorizationHardening(unittest.TestCase):
    """doc upgrade section 4: client cannot reduce or alter the authorized
    payment amount. Authorized decision here settles at ₹8,000 (frozen
    full-price counter, per the hero-scenario budget guardrail)."""

    @classmethod
    def setUpClass(cls):
        cls.db_path = "/tmp/econex_hardening_test.db"
        if os.path.exists(cls.db_path):
            os.remove(cls.db_path)
        cls.port = 8972
        cls.server = create_server(port=cls.port, db_path=cls.db_path)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        time.sleep(0.2)
        cls.base_url = f"http://127.0.0.1:{cls.port}"

        conn = get_connection(cls.db_path)
        merchant_repo.create_merchant(conn, "M-a", "Merchant A", "token-a")
        merchant_repo.create_merchant(conn, "M-b", "Merchant B", "token-b")
        for merchant_id, token in (("M-a", "token-a"), ("M-b", "token-b")):
            product = Product(f"P-{merchant_id}", merchant_id, 800000, 450000, 5000, 18, 3)
            merchant_repo.create_product(conn, product, "Wireless Earbuds X200")
            policy = MerchantPolicy(merchant_id, 200000, 80000, 50000, 1000000, 980000, 100000, 3)
            merchant_repo.upsert_policy(conn, policy)
        conn.commit()
        conn.close()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        if os.path.exists(cls.db_path):
            os.remove(cls.db_path)

    def _authorized_decision(self, merchant="M-a", token="token-a"):
        _, payload = _request(
            "POST", f"{self.base_url}/buyer-intents",
            {
                "product_id": f"P-{merchant}", "buyer_text": "6800 please",
                "buyer_budget_paise": 680000, "quantity": 1, "requested_price_paise": 680000,
            },
            token=token,
        )
        return payload["decision_id"], payload["session_id"], payload["offer"]["final_price_paise"]

    def test_client_supplied_amount_is_rejected_not_silently_ignored(self):
        decision_id, _, authorized_amount = self._authorized_decision()
        self.assertEqual(authorized_amount, 800000)
        for malicious_amount in (1, 100, 680000, 99999):
            status, payload = _request(
                "POST", f"{self.base_url}/payments/order",
                {"decision_id": decision_id, "amount_paise": malicious_amount, "idempotency_key": f"atk-{malicious_amount}"},
                token="token-a",
            )
            self.assertEqual(status, 400, f"amount={malicious_amount} should be rejected outright")

    def test_payment_uses_server_derived_amount_matching_authorized_offer(self):
        decision_id, _, authorized_amount = self._authorized_decision()
        status, payload = _request(
            "POST", f"{self.base_url}/payments/order",
            {"decision_id": decision_id, "idempotency_key": "legit-payment-1"},
            token="token-a",
        )
        self.assertEqual(status, 200)
        self.assertIn(payload["status"], ("simulated", "created"))
        # amount isn't echoed back directly by process_payment's outcome dict,
        # so verify via DB that the stored amount matches the authorized offer.
        conn = get_connection(self.db_path)
        row = conn.execute(
            "SELECT amount_paise FROM payments WHERE payment_id = ?", (payload["payment_id"],)
        ).fetchone()
        conn.close()
        self.assertEqual(row["amount_paise"], authorized_amount)

    def test_payment_amount_scales_with_quantity_greater_than_one(self):
        """Final audit finding #4: the server-side formula is
        `frozen_final_price_paise * frozen_quantity`. This was never
        exercised with quantity > 1 by any prior test — every other test
        in this suite uses quantity=1, which cannot distinguish
        'per-unit price' from 'total price' bugs. This test authorizes a
        decision for quantity=3 and asserts the derived payment amount is
        final_price_paise * 3, not just final_price_paise.
        """
        _, payload = _request(
            "POST", f"{self.base_url}/buyer-intents",
            {
                "product_id": "P-M-a", "buyer_text": "6800 please for 3 units",
                "buyer_budget_paise": 2040000, "quantity": 3, "requested_price_paise": 2040000,
            },
            token="token-a",
        )
        decision_id = payload["decision_id"]
        per_unit_price = payload["offer"]["final_price_paise"]
        offer_quantity = payload["offer"]["quantity"]
        self.assertEqual(offer_quantity, 3)

        status, pay_payload = _request(
            "POST", f"{self.base_url}/payments/order",
            {"decision_id": decision_id, "idempotency_key": "qty3-payment"},
            token="token-a",
        )
        self.assertEqual(status, 200)

        conn = get_connection(self.db_path)
        row = conn.execute(
            "SELECT amount_paise FROM payments WHERE payment_id = ?", (pay_payload["payment_id"],)
        ).fetchone()
        conn.close()
        self.assertEqual(row["amount_paise"], per_unit_price * 3)
        self.assertNotEqual(row["amount_paise"], per_unit_price)  # would catch a per-unit-only bug


class TestMerchantIsolation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db_path = "/tmp/econex_isolation_test.db"
        if os.path.exists(cls.db_path):
            os.remove(cls.db_path)
        cls.port = 8973
        cls.server = create_server(port=cls.port, db_path=cls.db_path)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        time.sleep(0.2)
        cls.base_url = f"http://127.0.0.1:{cls.port}"

        conn = get_connection(cls.db_path)
        merchant_repo.create_merchant(conn, "M-a", "Merchant A", "token-a")
        merchant_repo.create_merchant(conn, "M-b", "Merchant B", "token-b")
        for merchant_id, token in (("M-a", "token-a"), ("M-b", "token-b")):
            product = Product(f"P-{merchant_id}", merchant_id, 800000, 450000, 5000, 18, 3)
            merchant_repo.create_product(conn, product, "Wireless Earbuds X200")
            policy = MerchantPolicy(merchant_id, 200000, 80000, 50000, 1000000, 980000, 100000, 3)
            merchant_repo.upsert_policy(conn, policy)
        conn.commit()
        conn.close()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        if os.path.exists(cls.db_path):
            os.remove(cls.db_path)

    def _decision_for_merchant_a(self):
        _, payload = _request(
            "POST", f"{self.base_url}/buyer-intents",
            {"product_id": "P-M-a", "buyer_text": "6800 please", "buyer_budget_paise": 680000,
             "quantity": 1, "requested_price_paise": 680000},
            token="token-a",
        )
        return payload["decision_id"], payload["session_id"]

    def test_merchant_b_cannot_read_merchant_a_audit(self):
        _, session_id = self._decision_for_merchant_a()
        status, payload = _request("GET", f"{self.base_url}/audit/{session_id}", token="token-b")
        self.assertEqual(status, 200)
        self.assertEqual(payload["timeline"], [])  # scoped query returns nothing, not an error leak

    def test_merchant_b_cannot_read_merchant_a_ledger(self):
        _, session_id = self._decision_for_merchant_a()
        status, payload = _request("GET", f"{self.base_url}/sessions/{session_id}/ledger", token="token-b")
        self.assertEqual(status, 404)

    def test_merchant_b_cannot_pay_for_merchant_a_decision(self):
        decision_id, _ = self._decision_for_merchant_a()
        status, payload = _request(
            "POST", f"{self.base_url}/payments/order",
            {"decision_id": decision_id, "idempotency_key": "cross-tenant-attack"},
            token="token-b",
        )
        self.assertEqual(status, 404)

    def test_merchant_b_cannot_approve_merchant_a_decision(self):
        decision_id, _ = self._decision_for_merchant_a()
        status, payload = _request(
            "POST", f"{self.base_url}/approvals/{decision_id}/approve", {}, token="token-b"
        )
        self.assertEqual(status, 404)

    def test_merchant_a_can_read_own_audit(self):
        _, session_id = self._decision_for_merchant_a()
        status, payload = _request("GET", f"{self.base_url}/audit/{session_id}", token="token-a")
        self.assertEqual(status, 200)
        self.assertGreater(len(payload["timeline"]), 0)


class TestWebhookSecurityHardening(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db_path = "/tmp/econex_webhook_test.db"
        if os.path.exists(cls.db_path):
            os.remove(cls.db_path)
        Config.RAZORPAY_WEBHOOK_SECRET = "test-webhook-secret"
        cls.port = 8974
        cls.server = create_server(port=cls.port, db_path=cls.db_path)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        time.sleep(0.2)
        cls.base_url = f"http://127.0.0.1:{cls.port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        Config.RAZORPAY_WEBHOOK_SECRET = ""
        if os.path.exists(cls.db_path):
            os.remove(cls.db_path)

    def _sign(self, body: bytes) -> str:
        import hashlib
        import hmac

        return hmac.new(b"test-webhook-secret", body, hashlib.sha256).hexdigest()

    def test_valid_signature_accepted(self):
        body = {"event": "payment.captured", "id": "evt_valid_1"}
        raw = json.dumps(body).encode()
        status, payload = _request(
            "POST", f"{self.base_url}/webhooks/razorpay", body,
            headers={"X-Razorpay-Signature": self._sign(raw)},
        )
        self.assertEqual(status, 200)
        self.assertTrue(payload["signature_valid"])

    def test_invalid_signature_rejected_with_401(self):
        body = {"event": "payment.captured", "id": "evt_invalid_1"}
        status, payload = _request(
            "POST", f"{self.base_url}/webhooks/razorpay", body,
            headers={"X-Razorpay-Signature": "forged-signature-not-hmac"},
        )
        self.assertEqual(status, 401)
        self.assertFalse(payload["signature_valid"])

    def test_missing_signature_rejected(self):
        body = {"event": "payment.captured", "id": "evt_missing_sig"}
        status, payload = _request("POST", f"{self.base_url}/webhooks/razorpay", body)
        self.assertEqual(status, 401)

    def test_replayed_event_is_idempotent_not_reprocessed(self):
        body = {"event": "payment.captured", "id": "evt_replay_1"}
        raw = json.dumps(body).encode()
        sig = self._sign(raw)
        status1, payload1 = _request(
            "POST", f"{self.base_url}/webhooks/razorpay", body, headers={"X-Razorpay-Signature": sig}
        )
        status2, payload2 = _request(
            "POST", f"{self.base_url}/webhooks/razorpay", body, headers={"X-Razorpay-Signature": sig}
        )
        self.assertEqual(status1, 200)
        self.assertEqual(status2, 200)
        self.assertTrue(payload2.get("duplicate"))
        self.assertEqual(payload1["webhook_event_id"], payload2["webhook_event_id"])

    def test_modified_payload_with_stale_signature_rejected(self):
        original = {"event": "payment.captured", "id": "evt_tamper_1"}
        sig = self._sign(json.dumps(original).encode())
        tampered = {"event": "payment.captured", "id": "evt_tamper_1", "extra": "injected"}
        status, payload = _request(
            "POST", f"{self.base_url}/webhooks/razorpay", tampered, headers={"X-Razorpay-Signature": sig}
        )
        self.assertEqual(status, 401)


if __name__ == "__main__":
    unittest.main()
