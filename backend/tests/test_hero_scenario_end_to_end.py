"""
Full pipeline integration test using the doc's own hero-scenario fixture
(Table 10 / section 25) end-to-end: generate -> policy -> economics ->
select -> decide. This is the authoritative reproduction of "what the
system actually does" under the LOCKED financial interpretation, and is
what the final report's "exact resulting candidate feasibility" section is
based on.
"""

import unittest

from app.core.candidate_generator import generate_candidates
from app.core.decision_resolver import resolve_decision
from app.core.domain import DeliveryOption, NegotiationAction
from app.core.economic_engine import evaluate_all as economic_evaluate_all
from app.core.optimizer import select_best
from app.core.policy_engine import evaluate_all as policy_evaluate_all
from tests.fixtures import HERO_INTENT, HERO_POLICY, HERO_PRODUCT


class TestHeroScenarioEndToEnd(unittest.TestCase):
    def setUp(self):
        self.candidates = generate_candidates(HERO_INTENT, HERO_PRODUCT, HERO_POLICY)
        self.policy_results = policy_evaluate_all(
            self.candidates, HERO_INTENT, HERO_PRODUCT, HERO_POLICY
        )
        self.evaluations = economic_evaluate_all(
            self.candidates, self.policy_results, HERO_INTENT, HERO_PRODUCT
        )

    def test_generates_19_candidates(self):
        self.assertEqual(len(self.candidates), 19)

    def test_only_zero_incentive_candidates_are_feasible(self):
        """Under the locked discount+cashback budget rule and the doc's own
        spend_to_date=9800/budget=10000, remaining headroom is only 200
        rupees — less than any non-zero grid step for discount (400/800) or
        cashback (250/500). Only the base-price, zero-discount,
        zero-cashback candidates survive the budget check."""
        feasible = [e for e in self.evaluations if e.feasible]
        by_id = {c.candidate_id: c for c in self.candidates}
        feasible_candidates = [by_id[e.candidate_id] for e in feasible]

        for c in feasible_candidates:
            self.assertEqual(c.final_price_paise, 800000)
            self.assertEqual(c.discount_paise, 0)
            self.assertEqual(c.cashback_paise, 0)

        # exactly the standard + expedited zero-incentive variants
        self.assertEqual(len(feasible_candidates), 2)

    def test_selected_candidate_is_full_price_no_incentive(self):
        winner = select_best(self.candidates, self.evaluations)
        self.assertIsNotNone(winner)
        candidate, evaluation = winner
        self.assertEqual(candidate.final_price_paise, 800000)
        self.assertEqual(candidate.discount_paise, 0)
        self.assertEqual(candidate.cashback_paise, 0)
        self.assertEqual(candidate.delivery_option, DeliveryOption.STANDARD)  # tie-break winner
        self.assertEqual(evaluation.contribution_paise, 345000)

    def test_final_decision_is_counter_at_full_price(self):
        winner = select_best(self.candidates, self.evaluations)
        decision = resolve_decision(winner, HERO_INTENT, HERO_POLICY)
        self.assertEqual(decision.action, NegotiationAction.COUNTER)
        self.assertFalse(decision.requires_approval)  # incentive_total=0, well under threshold

    def test_previously_advertised_7200_candidate_is_present_but_infeasible(self):
        by_price_discount = [
            c
            for c in self.candidates
            if c.final_price_paise == 720000 and c.discount_paise == 80000 and c.cashback_paise == 0
        ]
        # both the standard and expedited delivery variants at this price point
        self.assertEqual(len(by_price_discount), 2)
        from app.core.domain import PolicyViolationCode

        for candidate in by_price_discount:
            result = next(r for r in self.policy_results if r.candidate_id == candidate.candidate_id)
            self.assertFalse(result.feasible)
            self.assertEqual(result.first_violation, PolicyViolationCode.INCENTIVE_BUDGET_EXCEEDED)


if __name__ == "__main__":
    unittest.main()
