import unittest

from app.core.domain import Candidate, Decision, DeliveryOption, EconomicEvaluation, NegotiationAction
from app.schemas.serializers import (
    assert_no_private_leak,
    buyer_view_offer,
    merchant_view_offer,
)


class TestSerializers(unittest.TestCase):
    def setUp(self):
        self.candidate = Candidate("C1", 720000, 80000, 0, 1, DeliveryOption.STANDARD)
        self.evaluation = EconomicEvaluation("C1", True, 0.5015, 265000, 0, 132890.0)
        self.decision = Decision(NegotiationAction.COUNTER, "C1", "internal margin_floor=200000 reason", False)

    def test_buyer_view_excludes_private_fields(self):
        payload = buyer_view_offer(self.candidate, self.decision)
        for private_key in ("contribution_paise", "p_conv", "expected_economic_value_paise", "reason"):
            self.assertNotIn(private_key, payload)

    def test_buyer_view_passes_allowlist_check(self):
        payload = buyer_view_offer(self.candidate, self.decision)
        assert_no_private_leak(payload)  # should not raise

    def test_buyer_view_message_never_contains_internal_reason_text(self):
        payload = buyer_view_offer(self.candidate, self.decision)
        self.assertNotIn("margin_floor", payload["message"])

    def test_merchant_view_includes_full_economics(self):
        payload = merchant_view_offer(self.candidate, self.evaluation, self.decision)
        self.assertIn("contribution_paise", payload)
        self.assertIn("expected_economic_value_paise", payload)
        self.assertIn("p_conv", payload)
        self.assertEqual(payload["reason"], self.decision.reason)

    def test_assert_no_private_leak_catches_injected_field(self):
        payload = buyer_view_offer(self.candidate, self.decision)
        payload["contribution_paise"] = 265000  # simulate a bug leaking a private field
        with self.assertRaises(ValueError):
            assert_no_private_leak(payload)


if __name__ == "__main__":
    unittest.main()
