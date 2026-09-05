import unittest

from app.core.candidate_generator import generate_candidates
from app.core.domain import DeliveryOption
from tests.fixtures import HERO_INTENT, HERO_POLICY, HERO_PRODUCT


class TestCandidateGenerator(unittest.TestCase):
    def test_hero_scenario_yields_19_candidates(self):
        """doc section 9 explicitly states the hero scenario yields
        19 bounded candidates: 3 price steps x 3 cashback steps x 2 delivery
        options (18) + 1 buyer-ask anchor."""
        candidates = generate_candidates(HERO_INTENT, HERO_PRODUCT, HERO_POLICY)
        self.assertEqual(len(candidates), 19)

    def test_no_candidate_below_cost(self):
        candidates = generate_candidates(HERO_INTENT, HERO_PRODUCT, HERO_POLICY)
        for c in candidates:
            self.assertGreaterEqual(c.final_price_paise, HERO_PRODUCT.cost_paise)

    def test_deterministic_reproducible(self):
        a = generate_candidates(HERO_INTENT, HERO_PRODUCT, HERO_POLICY)
        b = generate_candidates(HERO_INTENT, HERO_PRODUCT, HERO_POLICY)
        self.assertEqual(a, b)

    def test_selected_candidate_present_in_grid(self):
        """doc hero scenario: 7200 price / 800 discount / 0 cashback / standard delivery
        must appear in the generated grid (it is exactly base - max_discount)."""
        candidates = generate_candidates(HERO_INTENT, HERO_PRODUCT, HERO_POLICY)
        matches = [
            c
            for c in candidates
            if c.final_price_paise == 720000
            and c.cashback_paise == 0
            and c.delivery_option == DeliveryOption.STANDARD
        ]
        self.assertEqual(len(matches), 1)

    def test_no_expedited_option_without_tomorrow_capacity(self):
        from dataclasses import replace

        zero_capacity_product = replace(HERO_PRODUCT, delivery_capacity_tomorrow=0)
        candidates = generate_candidates(HERO_INTENT, zero_capacity_product, HERO_POLICY)
        self.assertTrue(all(c.delivery_option == DeliveryOption.STANDARD for c in candidates))

    def test_anchor_excluded_when_structurally_invalid(self):
        from dataclasses import replace

        bad_intent = replace(HERO_INTENT, requested_price_paise=-5)
        candidates = generate_candidates(bad_intent, HERO_PRODUCT, HERO_POLICY)
        self.assertFalse(any(c.final_price_paise == -5 for c in candidates))

    def test_rejected_prices_excluded_on_later_rounds(self):
        from dataclasses import replace

        round2_intent = replace(HERO_INTENT, round_number=2)
        rejected = frozenset({720000})
        candidates = generate_candidates(
            round2_intent, HERO_PRODUCT, HERO_POLICY, previously_rejected_final_prices_paise=rejected
        )
        self.assertFalse(any(c.final_price_paise == 720000 for c in candidates))

    def test_candidate_ids_deterministic_and_unique(self):
        candidates = generate_candidates(HERO_INTENT, HERO_PRODUCT, HERO_POLICY)
        ids = [c.candidate_id for c in candidates]
        self.assertEqual(len(ids), len(set(ids)))


if __name__ == "__main__":
    unittest.main()
