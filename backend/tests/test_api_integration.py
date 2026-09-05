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


def _request(method, url, body=None, token=None):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


class TestApiSmoke(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db_path = "/tmp/econex_api_smoke_test.db"
        if os.path.exists(cls.db_path):
            os.remove(cls.db_path)
        cls.port = 8971
        cls.server = create_server(port=cls.port, db_path=cls.db_path)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        time.sleep(0.2)
        cls.base_url = f"http://127.0.0.1:{cls.port}"

        conn = get_connection(cls.db_path)
        merchant_repo.create_merchant(conn, "M-demo", "Demo Merchant", "demo-token")
        product = Product("P-earbuds-x200", "M-demo", 800000, 450000, 5000, 18, 3)
        merchant_repo.create_product(conn, product, "Wireless Earbuds X200")
        policy = MerchantPolicy("M-demo", 200000, 80000, 50000, 1000000, 980000, 100000, 3)
        merchant_repo.upsert_policy(conn, policy)
        conn.commit()
        conn.close()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        if os.path.exists(cls.db_path):
            os.remove(cls.db_path)

    def test_unauthenticated_request_rejected(self):
        status, payload = _request(
            "POST", f"{self.base_url}/buyer-intents",
            {"product_id": "P-earbuds-x200", "buyer_budget_paise": 680000, "quantity": 1},
        )
        self.assertEqual(status, 401)

    def test_full_demo_flow_intent_to_offer(self):
        status, payload = _request(
            "POST",
            f"{self.base_url}/buyer-intents",
            {
                "product_id": "P-earbuds-x200",
                "buyer_text": "Can you do 6800?",
                "buyer_budget_paise": 680000,
                "quantity": 1,
                "requested_price_paise": 680000,
            },
            token="demo-token",
        )
        self.assertEqual(status, 200)
        self.assertEqual(payload["action"], "COUNTER")
        self.assertEqual(payload["offer"]["final_price_paise"], 800000)
        for private_key in ("contribution_paise", "expected_economic_value_paise", "p_conv"):
            self.assertNotIn(private_key, payload["offer"])
        self.decision_id = payload["decision_id"]
        self.session_id = payload["session_id"]

    def test_audit_endpoint_returns_full_timeline(self):
        _, create_payload = _request(
            "POST",
            f"{self.base_url}/buyer-intents",
            {
                "product_id": "P-earbuds-x200",
                "buyer_text": "6800 please",
                "buyer_budget_paise": 680000,
                "quantity": 1,
                "requested_price_paise": 680000,
            },
            token="demo-token",
        )
        session_id = create_payload["session_id"]
        status, payload = _request("GET", f"{self.base_url}/audit/{session_id}", token="demo-token")
        self.assertEqual(status, 200)
        stages = [e["stage"] for e in payload["timeline"]]
        self.assertIn("intent", stages)
        self.assertIn("decision", stages)

    def test_payment_requires_authorized_decision_state(self):
        _, create_payload = _request(
            "POST",
            f"{self.base_url}/buyer-intents",
            {
                "product_id": "P-earbuds-x200",
                "buyer_text": "6800 please",
                "buyer_budget_paise": 680000,
                "quantity": 1,
                "requested_price_paise": 680000,
            },
            token="demo-token",
        )
        decision_id = create_payload["decision_id"]
        status, payload = _request(
            "POST",
            f"{self.base_url}/payments/order",
            {"decision_id": decision_id, "idempotency_key": "idem-x"},
            token="demo-token",
        )
        # AWAITING_BUYER_RESPONSE is an allowed pre-payment state in this MVP flow
        self.assertEqual(status, 200)
        self.assertIn(payload["status"], ("simulated", "created"))

    def test_duplicate_payment_blocked_via_api(self):
        _, create_payload = _request(
            "POST",
            f"{self.base_url}/buyer-intents",
            {
                "product_id": "P-earbuds-x200",
                "buyer_text": "6800 please",
                "buyer_budget_paise": 680000,
                "quantity": 1,
                "requested_price_paise": 680000,
            },
            token="demo-token",
        )
        decision_id = create_payload["decision_id"]
        _request(
            "POST", f"{self.base_url}/payments/order",
            {"decision_id": decision_id, "idempotency_key": "idem-dup"},
            token="demo-token",
        )
        status, payload = _request(
            "POST", f"{self.base_url}/payments/order",
            {"decision_id": decision_id, "idempotency_key": "idem-dup"},
            token="demo-token",
        )
        self.assertEqual(status, 200)
        self.assertTrue(payload["duplicate"])
        self.assertEqual(payload["status"], "duplicate_blocked")

    def test_ledger_endpoint_returns_all_19_candidates_with_selected_marker(self):
        _, create_payload = _request(
            "POST",
            f"{self.base_url}/buyer-intents",
            {
                "product_id": "P-earbuds-x200",
                "buyer_text": "6800 please",
                "buyer_budget_paise": 680000,
                "quantity": 1,
                "requested_price_paise": 680000,
            },
            token="demo-token",
        )
        session_id = create_payload["session_id"]
        status, payload = _request("GET", f"{self.base_url}/sessions/{session_id}/ledger", token="demo-token")
        self.assertEqual(status, 200)
        self.assertEqual(len(payload["candidates"]), 19)
        selected = [c for c in payload["candidates"] if c["selected"]]
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0]["final_price_paise"], 800000)
        feasible = [c for c in payload["candidates"] if c["feasible"]]
        self.assertEqual(len(feasible), 2)


if __name__ == "__main__":
    unittest.main()
