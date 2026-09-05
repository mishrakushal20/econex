import unittest

from app.core.conversion_heuristic import ConversionInputs, compute_p_conv


class TestConversionHeuristic(unittest.TestCase):
    def test_hero_scenario_matches_documentation(self):
        """Doc section 25: candidate 7200, base 8000, cashback 0, buyer budget 6800
        must yield P_conv ~= 0.5015 (documented illustrative value)."""
        inputs = ConversionInputs(
            buyer_budget_paise=680000,
            base_price_paise=800000,
            final_price_paise=720000,
            cashback_paise=0,
            explicit_delivery_preference=False,
        )
        p_conv = compute_p_conv(inputs)
        self.assertAlmostEqual(p_conv, 0.5015, places=3)

    def test_bounded_open_interval(self):
        extreme = ConversionInputs(
            buyer_budget_paise=100,
            base_price_paise=100,
            final_price_paise=10_000_000,
            cashback_paise=0,
        )
        p = compute_p_conv(extreme)
        self.assertGreater(p, 0.0)
        self.assertLess(p, 1.0)

    def test_monotonic_decreasing_with_price(self):
        base = dict(buyer_budget_paise=700000, base_price_paise=800000, cashback_paise=0)
        prices = [600000, 650000, 700000, 750000, 800000]
        probs = [
            compute_p_conv(ConversionInputs(final_price_paise=p, **base)) for p in prices
        ]
        for earlier, later in zip(probs, probs[1:]):
            self.assertGreater(earlier, later)

    def test_deterministic_reproducible(self):
        inputs = ConversionInputs(680000, 800000, 720000, 0, False)
        self.assertEqual(compute_p_conv(inputs), compute_p_conv(inputs))

    def test_explicit_delivery_preference_increases_conversion(self):
        base = ConversionInputs(680000, 800000, 720000, 0, explicit_delivery_preference=False)
        urgent = ConversionInputs(680000, 800000, 720000, 0, explicit_delivery_preference=True)
        self.assertGreater(compute_p_conv(urgent), compute_p_conv(base))

    def test_rejects_zero_budget(self):
        with self.assertRaises(ValueError):
            compute_p_conv(ConversionInputs(0, 800000, 720000, 0))


if __name__ == "__main__":
    unittest.main()
