import os
import unittest

from app.core.domain import MerchantPolicy, Product
from app.database import get_connection, init_db
from app.llm.mock_provider import MockLLMProvider
from app.repositories import merchant_repo
from app.services.negotiation_service import handle_buyer_intent


class TestNegotiationServiceIntegration(unittest.TestCase):
    def setUp(self):
        self.db_path = "/tmp/econex_integration_test.db"
        if os.path.exists(self.db_path):
            os.remove(self.db_path)
        init_db(self.db_path)
        self.conn = get_connection(self.db_path)

        merchant_repo.create_merchant(self.conn, "M-demo", "Demo Merchant", "demo-token")
        product = Product(
            product_id="P-earbuds-x200",
            merchant_id="M-demo",
            base_price_paise=800000,
            cost_paise=450000,
            delivery_cost_paise=5000,
            inventory=18,
            delivery_capacity_tomorrow=3,
        )
        merchant_repo.create_product(self.conn, product, "Wireless Earbuds X200")
        policy = MerchantPolicy(
            merchant_id="M-demo",
            margin_floor_paise=200000,
            max_discount_paise=80000,
            max_cashback_paise=50000,
            incentive_budget_paise=1000000,
            incentive_spend_to_date_paise=980000,
            approval_threshold_paise=100000,
            max_rounds=3,
        )
        merchant_repo.upsert_policy(self.conn, policy)
        self.conn.commit()

    def tearDown(self):
        self.conn.close()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def test_full_hero_scenario_through_service(self):
        result = handle_buyer_intent(
            self.conn,
            merchant_id="M-demo",
            product_id="P-earbuds-x200",
            buyer_text="Can you do 6800? That's really my budget.",
            buyer_budget_paise=680000,
            quantity=1,
            requested_price_paise=680000,
            requested_cashback_paise=0,
            context={},
            llm_provider=MockLLMProvider(),
        )
        self.conn.commit()

        self.assertEqual(result["candidate_count"], 19)
        self.assertEqual(result["decision_action"], "COUNTER")
        self.assertEqual(result["buyer_view"]["final_price_paise"], 800000)
        # private fields must never appear in buyer_view
        for private_key in ("contribution_paise", "expected_economic_value_paise", "p_conv", "reason"):
            self.assertNotIn(private_key, result["buyer_view"])
        self.assertIn("contribution_paise", result["merchant_view"])

    def test_audit_trail_has_all_pipeline_stages(self):
        result = handle_buyer_intent(
            self.conn,
            merchant_id="M-demo",
            product_id="P-earbuds-x200",
            buyer_text="6800 please",
            buyer_budget_paise=680000,
            quantity=1,
            requested_price_paise=680000,
            requested_cashback_paise=0,
            context={},
            llm_provider=MockLLMProvider(),
        )
        self.conn.commit()

        from app.audit import timeline_for_session

        timeline = timeline_for_session(self.conn, result["session_id"])
        stages = [entry["stage"] for entry in timeline]
        for expected_stage in (
            "intent",
            "proposal",
            "candidate_generation",
            "policy",
            "economic_evaluation",
            "selection",
            "decision",
        ):
            self.assertIn(expected_stage, stages)

    def test_offers_persisted_for_all_19_candidates(self):
        result = handle_buyer_intent(
            self.conn,
            merchant_id="M-demo",
            product_id="P-earbuds-x200",
            buyer_text="6800 please",
            buyer_budget_paise=680000,
            quantity=1,
            requested_price_paise=680000,
            requested_cashback_paise=0,
            context={},
            llm_provider=MockLLMProvider(),
        )
        self.conn.commit()
        rows = self.conn.execute(
            "SELECT COUNT(*) as c FROM offers WHERE intent_id = ?", (result["intent_id"],)
        ).fetchone()
        self.assertEqual(rows["c"], 19)


if __name__ == "__main__":
    unittest.main()
