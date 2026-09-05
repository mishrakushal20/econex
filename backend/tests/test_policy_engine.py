import unittest
from dataclasses import replace

from app.core.domain import Candidate, DeliveryOption, PolicyViolationCode
from app.core.policy_engine import evaluate_candidate
from tests.fixtures import HERO_INTENT, HERO_POLICY, HERO_PRODUCT


def _cand(**kwargs):
    defaults = dict(
        candidate_id="X",
        final_price_paise=720000,
        discount_paise=80000,
        cashback_paise=0,
        quantity=1,
        delivery_option=DeliveryOption.STANDARD,
    )
    defaults.update(kwargs)
    return Candidate(**defaults)


class TestPolicyEngine(unittest.TestCase):
    def test_below_cost_blocked(self):
        c = _cand(final_price_paise=400000, discount_paise=400000)
        result = evaluate_candidate(c, HERO_INTENT, HERO_PRODUCT, HERO_POLICY)
        self.assertFalse(result.feasible)
        self.assertEqual(result.first_violation, PolicyViolationCode.PRICE_BELOW_COST)

    def test_6800_blocked_on_discount_limit(self):
        """doc Table 3: candidate 6800 -> BLOCK, discount limit."""
        c = _cand(final_price_paise=680000, discount_paise=120000, cashback_paise=0)
        result = evaluate_candidate(c, HERO_INTENT, HERO_PRODUCT, HERO_POLICY)
        self.assertFalse(result.feasible)
        self.assertEqual(result.first_violation, PolicyViolationCode.MAX_DISCOUNT_EXCEEDED)

    def test_7300_plus_500_cashback_blocked_on_budget(self):
        """doc Table 3: candidate 7300 + 500 cashback -> BLOCK, budget.
        Under the LOCKED discount+cashback formula:
        spend_to_date(9800) + discount(700) + cashback(500) = 11000 > budget(10000)."""
        c = _cand(final_price_paise=730000, discount_paise=70000, cashback_paise=50000)
        result = evaluate_candidate(c, HERO_INTENT, HERO_PRODUCT, HERO_POLICY)
        self.assertFalse(result.feasible)
        self.assertEqual(result.first_violation, PolicyViolationCode.INCENTIVE_BUDGET_EXCEEDED)

    def test_7600_blocked_on_budget_under_locked_formula(self):
        """doc Table 3 illustratively lists candidate 7600 as FEASIBLE, but that
        was only true under the earlier (superseded) cashback-only budget
        interpretation. Under the LOCKED discount+cashback formula:
        spend_to_date(9800) + discount(400) + cashback(0) = 10200 > budget(10000)
        -> BLOCKED. This is a documented, transparent correction — see
        docs/DECISIONS.md reconciliation list, item for doc Table 3 row 3."""
        c = _cand(final_price_paise=760000, discount_paise=40000, cashback_paise=0)
        result = evaluate_candidate(c, HERO_INTENT, HERO_PRODUCT, HERO_POLICY)
        self.assertFalse(result.feasible)
        self.assertEqual(result.first_violation, PolicyViolationCode.INCENTIVE_BUDGET_EXCEEDED)
        # contribution is still computed/reported for diagnostics even though blocked
        self.assertEqual(result.contribution_paise, 305000)

    def test_7200_selected_candidate_now_blocked_on_budget_under_locked_formula(self):
        """doc section 25's hero "SELECTED" candidate (7200/800 discount/0 cashback)
        is ALSO only feasible under the superseded cashback-only formula.
        Under the LOCKED discount+cashback formula:
        spend_to_date(9800) + discount(800) + cashback(0) = 10600 > budget(10000)
        -> BLOCKED. See docs/DECISIONS.md for the full reconciliation and the
        resulting change in which candidate the pipeline actually selects."""
        c = _cand(final_price_paise=720000, discount_paise=80000, cashback_paise=0)
        result = evaluate_candidate(c, HERO_INTENT, HERO_PRODUCT, HERO_POLICY)
        self.assertFalse(result.feasible)
        self.assertEqual(result.first_violation, PolicyViolationCode.INCENTIVE_BUDGET_EXCEEDED)

    def test_full_price_zero_incentive_candidate_is_feasible(self):
        """Under the locked formula and the doc's own spend_to_date=9800/budget=10000
        fixture, the ONLY candidates from the generator's grid that pass the
        budget check are full-price, zero-discount, zero-cashback ones:
        spend_to_date(9800) + discount(0) + cashback(0) = 9800 <= 10000."""
        c = _cand(final_price_paise=800000, discount_paise=0, cashback_paise=0)
        result = evaluate_candidate(c, HERO_INTENT, HERO_PRODUCT, HERO_POLICY)
        self.assertTrue(result.feasible)
        self.assertEqual(result.contribution_paise, 345000)

    def test_margin_floor_violation(self):
        low_margin_policy = replace(HERO_POLICY, margin_floor_paise=10_000_000)
        c = _cand(final_price_paise=720000, discount_paise=80000, cashback_paise=0)
        result = evaluate_candidate(c, HERO_INTENT, HERO_PRODUCT, low_margin_policy)
        self.assertFalse(result.feasible)
        self.assertEqual(result.first_violation, PolicyViolationCode.CONTRIBUTION_BELOW_MARGIN_FLOOR)

    def test_max_cashback_exceeded(self):
        c = _cand(final_price_paise=760000, discount_paise=40000, cashback_paise=60000)
        result = evaluate_candidate(c, HERO_INTENT, HERO_PRODUCT, HERO_POLICY)
        self.assertFalse(result.feasible)
        self.assertEqual(result.first_violation, PolicyViolationCode.MAX_CASHBACK_EXCEEDED)

    def test_insufficient_inventory(self):
        """Isolate this check from the budget check using a policy with
        ample incentive-budget headroom (spend_to_date=0), since HERO_POLICY's
        near-exhausted budget would otherwise trip INCENTIVE_BUDGET_EXCEEDED
        first for a discounted candidate."""
        ample_budget_policy = replace(HERO_POLICY, incentive_spend_to_date_paise=0)
        c = _cand(final_price_paise=720000, discount_paise=80000, quantity=999)
        result = evaluate_candidate(c, HERO_INTENT, HERO_PRODUCT, ample_budget_policy)
        self.assertFalse(result.feasible)
        self.assertEqual(result.first_violation, PolicyViolationCode.INSUFFICIENT_INVENTORY)

    def test_delivery_capacity_unavailable(self):
        ample_budget_policy = replace(HERO_POLICY, incentive_spend_to_date_paise=0)
        c = _cand(
            final_price_paise=720000,
            discount_paise=80000,
            quantity=5,
            delivery_option=DeliveryOption.EXPEDITED,
        )
        result = evaluate_candidate(c, HERO_INTENT, HERO_PRODUCT, ample_budget_policy)
        self.assertFalse(result.feasible)
        self.assertEqual(result.first_violation, PolicyViolationCode.DELIVERY_CAPACITY_UNAVAILABLE)

    def test_offer_expired(self):
        ample_budget_policy = replace(HERO_POLICY, incentive_spend_to_date_paise=0)
        expired_intent = replace(HERO_INTENT, offer_expired=True)
        c = _cand(final_price_paise=720000, discount_paise=80000)
        result = evaluate_candidate(c, expired_intent, HERO_PRODUCT, ample_budget_policy)
        self.assertFalse(result.feasible)
        self.assertEqual(result.first_violation, PolicyViolationCode.OFFER_EXPIRED)

    def test_round_limit_exceeded(self):
        ample_budget_policy = replace(HERO_POLICY, incentive_spend_to_date_paise=0)
        over_round_intent = replace(HERO_INTENT, round_number=99)
        c = _cand(final_price_paise=720000, discount_paise=80000)
        result = evaluate_candidate(c, over_round_intent, HERO_PRODUCT, ample_budget_policy)
        self.assertFalse(result.feasible)
        self.assertEqual(result.first_violation, PolicyViolationCode.ROUND_LIMIT_EXCEEDED)

    def test_all_nine_diagnostics_always_recorded(self):
        """Every check runs and is recorded even after the first failure
        (doc section 15: full diagnostics retained for audit)."""
        c = _cand(final_price_paise=100000, discount_paise=700000, cashback_paise=999999, quantity=999)
        result = evaluate_candidate(c, HERO_INTENT, HERO_PRODUCT, HERO_POLICY)
        self.assertEqual(len(result.diagnostics), 9)


if __name__ == "__main__":
    unittest.main()
