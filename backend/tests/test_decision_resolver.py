import unittest
from dataclasses import replace

from app.core.decision_resolver import (
    resolve_decision,
    resolve_merchant_denial,
    resolve_round_limit_or_buyer_rejection,
)
from app.core.domain import Candidate, DeliveryOption, EconomicEvaluation, NegotiationAction
from app.core.state_machine import (
    InvalidTransitionError,
    NegotiationState,
    transition,
)
from tests.fixtures import HERO_INTENT, HERO_POLICY


def _pair(price, discount, cashback, eov=100.0, feasible=True):
    c = Candidate("C1", price, discount, cashback, 1, DeliveryOption.STANDARD)
    e = EconomicEvaluation("C1", feasible, 0.5, 1000, cashback, eov)
    return (c, e)


class TestDecisionResolver(unittest.TestCase):
    def test_no_feasible_candidate_rejects(self):
        decision = resolve_decision(None, HERO_INTENT, HERO_POLICY)
        self.assertEqual(decision.action, NegotiationAction.REJECT)

    def test_escalates_when_incentive_exceeds_approval_threshold(self):
        # approval_threshold is 100000 paise in fixture; discount+cashback=150000 exceeds it
        pair = _pair(price=650000, discount=150000, cashback=0)
        decision = resolve_decision(pair, HERO_INTENT, HERO_POLICY)
        self.assertEqual(decision.action, NegotiationAction.ESCALATE)
        self.assertTrue(decision.requires_approval)

    def test_accepts_when_matches_buyer_ask(self):
        # HERO_INTENT requested_price_paise = 680000, requested_cashback = 0
        pair = _pair(price=680000, discount=120000 if False else 0, cashback=0)
        # keep incentive under threshold
        pair = _pair(price=680000, discount=0, cashback=0)
        decision = resolve_decision(pair, HERO_INTENT, HERO_POLICY)
        self.assertEqual(decision.action, NegotiationAction.ACCEPT)

    def test_counters_when_selected_differs_from_ask(self):
        pair = _pair(price=720000, discount=80000, cashback=0)
        decision = resolve_decision(pair, HERO_INTENT, HERO_POLICY)
        self.assertEqual(decision.action, NegotiationAction.COUNTER)

    def test_buyer_rejection_forces_reject(self):
        decision = resolve_round_limit_or_buyer_rejection(buyer_rejected=True, round_limit_reached=False)
        self.assertEqual(decision.action, NegotiationAction.REJECT)

    def test_round_limit_forces_reject(self):
        decision = resolve_round_limit_or_buyer_rejection(buyer_rejected=False, round_limit_reached=True)
        self.assertEqual(decision.action, NegotiationAction.REJECT)

    def test_merchant_denial_forces_reject(self):
        decision = resolve_merchant_denial()
        self.assertEqual(decision.action, NegotiationAction.REJECT)


class TestStateMachine(unittest.TestCase):
    def test_open_to_closed_rejected_allowed(self):
        self.assertEqual(
            transition(NegotiationState.OPEN, NegotiationState.CLOSED_REJECTED),
            NegotiationState.CLOSED_REJECTED,
        )

    def test_open_to_pending_approval_allowed(self):
        transition(NegotiationState.OPEN, NegotiationState.PENDING_APPROVAL)

    def test_escalate_is_real_state_not_dead_end(self):
        s = transition(NegotiationState.OPEN, NegotiationState.PENDING_APPROVAL)
        s = transition(s, NegotiationState.APPROVED)
        s = transition(s, NegotiationState.CLOSED_ACCEPTED)
        self.assertEqual(s, NegotiationState.CLOSED_ACCEPTED)

    def test_denied_path_closes_rejected(self):
        s = transition(NegotiationState.OPEN, NegotiationState.PENDING_APPROVAL)
        s = transition(s, NegotiationState.DENIED)
        s = transition(s, NegotiationState.CLOSED_REJECTED)
        self.assertEqual(s, NegotiationState.CLOSED_REJECTED)

    def test_invalid_transition_raises(self):
        with self.assertRaises(InvalidTransitionError):
            transition(NegotiationState.OPEN, NegotiationState.CLOSED_ACCEPTED)

    def test_no_llm_can_skip_approval_gate(self):
        # Structurally: there is no transition from PENDING_APPROVAL directly
        # to CLOSED_ACCEPTED — it must pass through APPROVED first.
        with self.assertRaises(InvalidTransitionError):
            transition(NegotiationState.PENDING_APPROVAL, NegotiationState.CLOSED_ACCEPTED)


if __name__ == "__main__":
    unittest.main()
