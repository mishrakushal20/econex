import unittest

from app.core.razorpay_adapter import PaymentResult, PaymentStatus
from app.database import get_connection, init_db
from app.repositories.payments_repo import find_by_idempotency_key, process_payment


def _fake_success(amount_paise, receipt):
    return PaymentResult(
        status=PaymentStatus.SIMULATED,
        mode="simulation",
        amount_paise=amount_paise,
        razorpay_order_id=f"sim_{receipt}",
        failure_reason=None,
        label=f"[SIMULATION] {receipt}",
    )


def _fake_failure(amount_paise, receipt):
    return PaymentResult(
        status=PaymentStatus.FAILED,
        mode="real_test_mode",
        amount_paise=amount_paise,
        razorpay_order_id=None,
        failure_reason="simulated network failure",
        label="FAILED",
    )


class TestPaymentsIdempotency(unittest.TestCase):
    def setUp(self):
        self.db_path = ":memory:"
        # :memory: databases are per-connection in sqlite3, so use a
        # single shared connection for this test instead of init_db's own.
        import sqlite3

        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        from app.database import SCHEMA

        self.conn.executescript(SCHEMA)
        self.conn.execute(
            "INSERT INTO merchants (merchant_id, name, api_token, created_at) VALUES ('M1','demo','tok','now')"
        )
        self.conn.execute(
            "INSERT INTO products (product_id, merchant_id, name, base_price_paise, cost_paise, "
            "delivery_cost_paise, inventory, delivery_capacity_tomorrow) VALUES "
            "('P1','M1','earbuds',800000,450000,5000,18,3)"
        )
        self.conn.execute(
            "INSERT INTO negotiation_sessions (session_id, merchant_id, product_id, state, "
            "round_number, created_at, updated_at) VALUES ('S1','M1','P1','OPEN',1,'now','now')"
        )
        self.conn.execute(
            "INSERT INTO buyer_intents (intent_id, session_id, buyer_budget_paise, quantity, "
            "requested_price_paise, created_at) VALUES ('I1','S1',680000,1,680000,'now')"
        )
        self.conn.execute(
            "INSERT INTO decisions (decision_id, intent_id, merchant_id, action, selected_candidate_id, reason, "
            "requires_approval, state, created_at) VALUES ('D1','I1','M1','COUNTER','C1','x',0,'OPEN','now')"
        )
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def test_first_payment_succeeds(self):
        outcome = process_payment(self.conn, "D1", "M1", "idem-1", 800000, _fake_success)
        self.assertFalse(outcome["duplicate"])
        self.assertEqual(outcome["status"], "simulated")

    def test_duplicate_key_is_blocked_not_reexecuted(self):
        first = process_payment(self.conn, "D1", "M1", "idem-2", 800000, _fake_success)
        second = process_payment(self.conn, "D1", "M1", "idem-2", 800000, _fake_success)
        self.assertFalse(first["duplicate"])
        self.assertTrue(second["duplicate"])
        self.assertEqual(second["status"], "duplicate_blocked")
        # only one row was actually inserted
        rows = self.conn.execute("SELECT COUNT(*) as c FROM payments").fetchone()
        self.assertEqual(rows["c"], 1)

    def test_failed_payment_recorded_as_failed_not_hidden(self):
        outcome = process_payment(self.conn, "D1", "M1", "idem-3", 800000, _fake_failure)
        self.assertEqual(outcome["status"], "failed")
        self.assertIsNotNone(outcome["failure_reason"])

    def test_find_by_idempotency_key_returns_none_when_absent(self):
        self.assertIsNone(find_by_idempotency_key(self.conn, "never-seen"))


if __name__ == "__main__":
    unittest.main()
