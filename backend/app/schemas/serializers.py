"""
Buyer-view vs merchant-view serializers (doc section 19: "Buyer vs Merchant
Data Boundary").

HARD RULE: buyer_view() is an ALLOWLIST, not a denylist. It only ever copies
named fields it explicitly knows are safe. Adding a new private field to
Candidate/EconomicEvaluation in the future can never leak automatically
into a buyer response, because this function does not iterate over the
object's fields — it names each one.

Private fields that must NEVER cross into buyer_view (doc section 14/19):
cost, margin floor, incentive budget, contribution, EOV, internal P_conv,
policy diagnostics.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from app.core.domain import Candidate, Decision, EconomicEvaluation


def buyer_view_offer(
    candidate: Candidate, decision: Decision
) -> Dict[str, Any]:
    """Everything a buyer is allowed to see about the selected offer."""
    return {
        "final_price_paise": candidate.final_price_paise,
        "discount_paise": candidate.discount_paise,
        "cashback_paise": candidate.cashback_paise,
        "quantity": candidate.quantity,
        "delivery_option": candidate.delivery_option.value,
        "action": decision.action.value,
        "message": _safe_explanation(decision),
    }


def _safe_explanation(decision: Decision) -> str:
    """A buyer-safe rendering of the decision reason. Never leaks internal
    reasoning like 'EOV=...' or 'margin_floor=...' — those only ever appear
    in `decision.reason`, which is merchant-facing only.
    """
    from app.core.domain import NegotiationAction

    messages = {
        NegotiationAction.ACCEPT: "Your offer has been accepted.",
        NegotiationAction.COUNTER: "We can offer you the following terms.",
        NegotiationAction.REJECT: "We're unable to offer these terms right now.",
        NegotiationAction.ESCALATE: "Your offer is under review by the merchant.",
    }
    return messages.get(decision.action, "Your request has been processed.")


def merchant_view_offer(
    candidate: Candidate, evaluation: EconomicEvaluation, decision: Decision
) -> Dict[str, Any]:
    """Full internal economics — merchant-authenticated endpoints only."""
    return {
        "candidate_id": candidate.candidate_id,
        "final_price_paise": candidate.final_price_paise,
        "discount_paise": candidate.discount_paise,
        "cashback_paise": candidate.cashback_paise,
        "delivery_option": candidate.delivery_option.value,
        "contribution_paise": evaluation.contribution_paise,
        "incentive_cost_paise": evaluation.incentive_cost_paise,
        "p_conv": evaluation.p_conv,
        "expected_economic_value_paise": evaluation.expected_economic_value_paise,
        "action": decision.action.value,
        "reason": decision.reason,
        "requires_approval": decision.requires_approval,
    }


BUYER_ALLOWED_KEYS = frozenset(
    {
        "final_price_paise",
        "discount_paise",
        "cashback_paise",
        "quantity",
        "delivery_option",
        "action",
        "message",
    }
)


def assert_no_private_leak(payload: Dict[str, Any]) -> None:
    """Defense-in-depth: called by the API layer right before serializing a
    buyer-facing HTTP response. Raises if any key outside the allowlist is
    present, so a future code change that accidentally merges merchant
    fields into a buyer payload fails loudly instead of shipping a leak.
    """
    leaked = set(payload.keys()) - BUYER_ALLOWED_KEYS
    if leaked:
        raise ValueError(f"Private fields leaked into buyer-facing payload: {leaked}")
