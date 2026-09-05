import unittest

from app.agents.router import route_and_propose
from app.llm.mock_provider import MockLLMProvider
from app.llm.provider import LLMProvider, LLMProviderError


class AlwaysFailsProvider(LLMProvider):
    def propose_strategy(self, buyer_text, context):
        raise LLMProviderError("simulated outage")


class TestAgentRouting(unittest.TestCase):
    def setUp(self):
        self.provider = MockLLMProvider()

    def test_cart_abandoned_routes_to_cart_recovery(self):
        name, proposal = route_and_propose("hi", {"cart_abandoned": True}, self.provider)
        self.assertEqual(name, "CART_RECOVERY")

    def test_repeat_customer_routes_to_retention(self):
        name, proposal = route_and_propose("hi", {"is_repeat_customer": True}, self.provider)
        self.assertEqual(name, "RETENTION")

    def test_default_routes_to_dynamic_discount_agent(self):
        name, proposal = route_and_propose("can you go lower", {}, self.provider)
        self.assertEqual(name, "DYNAMIC_DISCOUNT")

    def test_llm_failure_propagates_never_fabricated(self):
        with self.assertRaises(LLMProviderError):
            route_and_propose("hi", {}, AlwaysFailsProvider())

    def test_proposal_never_carries_financial_fields(self):
        _, proposal = route_and_propose("cheaper please", {}, self.provider)
        self.assertFalse(hasattr(proposal, "discount_paise"))
        self.assertFalse(hasattr(proposal, "final_price_paise"))


if __name__ == "__main__":
    unittest.main()
