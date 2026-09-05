import unittest

from app.core.domain import Candidate, DeliveryOption
from app.core.economic_engine import evaluate_economics
from app.core.policy_engine import evaluate_candidate
from tests.fixtures import HERO_INTENT, HERO_POLICY, HERO_PRODUCT


class TestEconomicEngine(unittest.TestCase):
    def test_hero_candidate_eov_formula_with_available_budget(self):
        """doc section 25: candidate 7200/800 discount/0 cashback -> EOV ~= 1328.90
        (paise: 132890). This verifies the EOV FORMULA itself is correct
        (P_conv * contribution - cashback) using a policy variant with fresh
        incentive budget (spend_to_date=0), since under the LOCKED
        discount+cashback budget rule the doc's own spend_to_date=9800
        fixture makes this specific candidate budget-infeasible (see
        test_hero_candidate_infeasible_under_locked_budget_with_doc_spend
        below, and docs/DECISIONS.md)."""
        from dataclasses import replace

        fresh_policy = replace(HERO_POLICY, incentive_spend_to_date_paise=0)
        candidate = Candidate(
            candidate_id="C-hero",
            final_price_paise=720000,
            discount_paise=80000,
            cashback_paise=0,
            quantity=1,
            delivery_option=DeliveryOption.STANDARD,
        )
        policy_result = evaluate_candidate(candidate, HERO_INTENT, HERO_PRODUCT, fresh_policy)
        self.assertTrue(policy_result.feasible)
        evaluation = evaluate_economics(candidate, policy_result, HERO_INTENT, HERO_PRODUCT)
        self.assertTrue(evaluation.feasible)
        self.assertAlmostEqual(evaluation.expected_economic_value_paise, 132890, delta=50)

    def test_hero_candidate_infeasible_under_locked_budget_with_doc_spend(self):
        """With the doc's OWN spend_to_date=9800 (Table 10) and the LOCKED
        discount+cashback budget rule, this candidate is budget-infeasible:
        9800 + 800 + 0 = 10600 > 10000. EOV must be -inf and never win
        selection. This is the transparent, corrected hero-scenario outcome
        (see docs/DECISIONS.md)."""
        candidate = Candidate(
            candidate_id="C-hero",
            final_price_paise=720000,
            discount_paise=80000,
            cashback_paise=0,
            quantity=1,
            delivery_option=DeliveryOption.STANDARD,
        )
        policy_result = evaluate_candidate(candidate, HERO_INTENT, HERO_PRODUCT, HERO_POLICY)
        evaluation = evaluate_economics(candidate, policy_result, HERO_INTENT, HERO_PRODUCT)
        self.assertFalse(evaluation.feasible)
        self.assertEqual(evaluation.expected_economic_value_paise, float("-inf"))

    def test_infeasible_candidate_never_gets_finite_eov(self):
        below_cost = Candidate(
            candidate_id="C-bad",
            final_price_paise=100000,
            discount_paise=700000,
            cashback_paise=0,
            quantity=1,
            delivery_option=DeliveryOption.STANDARD,
        )
        policy_result = evaluate_candidate(below_cost, HERO_INTENT, HERO_PRODUCT, HERO_POLICY)
        evaluation = evaluate_economics(below_cost, policy_result, HERO_INTENT, HERO_PRODUCT)
        self.assertFalse(evaluation.feasible)
        self.assertEqual(evaluation.expected_economic_value_paise, float("-inf"))

    def test_incentive_cost_is_cashback_only_not_discount(self):
        candidate = Candidate(
            candidate_id="C-cashback",
            final_price_paise=760000,
            discount_paise=40000,
            cashback_paise=30000,
            quantity=1,
            delivery_option=DeliveryOption.STANDARD,
        )
        policy_result = evaluate_candidate(candidate, HERO_INTENT, HERO_PRODUCT, HERO_POLICY)
        evaluation = evaluate_economics(candidate, policy_result, HERO_INTENT, HERO_PRODUCT)
        self.assertEqual(evaluation.incentive_cost_paise, 30000)  # cashback only, not +discount


if __name__ == "__main__":
    unittest.main()
