"""
Decision Resolver — the only module allowed to turn a selected candidate
into a negotiation action (doc section 13, Table 5). No LLM can override
this. Pure function of (selection, buyer intent, policy) -> Decision.

Table 5 (locked):
    No feasible candidate              -> REJECT
    Approval threshold exceeded        -> ESCALATE
    Best feasible executable candidate -> APPROVE / COUNTER
    Buyer rejects / limit reached      -> REJECT
    Merchant denies escalation         -> REJECT

IMPLEMENTATION DECISION (minor detail not spelled out verbatim in the doc,
recorded in docs/DECISIONS.md): "approval threshold exceeded" is defined as
`(discount + cashback) > approval_threshold_paise` for the selected
candidate — i.e. the total incentive value the merchant is giving away,
which is the natural reading of an "approval threshold" gate on a
discretionary spend. ACCEPT vs COUNTER is decided by whether the selected
candidate's price/cashback/delivery exactly match what the buyer asked for.
"""

from __future__ import annotations

from typing import Optional, Tuple

from app.core.domain import (
    BuyerIntent,
    Candidate,
    Decision,
    EconomicEvaluation,
    MerchantPolicy,
    NegotiationAction,
)


def resolve_decision(
    selection: Optional[Tuple[Candidate, EconomicEvaluation]],
    intent: BuyerIntent,
    policy: MerchantPolicy,
) -> Decision:
    if selection is None:
        return Decision(
            action=NegotiationAction.REJECT,
            selected_candidate_id=None,
            reason="No feasible candidate satisfies merchant policy for this request.",
            requires_approval=False,
        )

    candidate, evaluation = selection
    incentive_total = candidate.discount_paise + candidate.cashback_paise

    if incentive_total > policy.approval_threshold_paise:
        return Decision(
            action=NegotiationAction.ESCALATE,
            selected_candidate_id=candidate.candidate_id,
            reason=(
                f"Selected candidate's total incentive (discount+cashback="
                f"{incentive_total}) exceeds the merchant approval threshold "
                f"({policy.approval_threshold_paise}); requires human approval."
            ),
            requires_approval=True,
        )

    matches_buyer_ask = (
        intent.requested_price_paise is not None
        and candidate.final_price_paise == intent.requested_price_paise
        and candidate.cashback_paise >= intent.requested_cashback_paise
    )

    if matches_buyer_ask:
        return Decision(
            action=NegotiationAction.ACCEPT,
            selected_candidate_id=candidate.candidate_id,
            reason="Selected candidate matches the buyer's requested terms.",
            requires_approval=False,
        )

    return Decision(
        action=NegotiationAction.COUNTER,
        selected_candidate_id=candidate.candidate_id,
        reason="Selected candidate is the highest-EOV feasible alternative to the buyer's ask.",
        requires_approval=False,
    )


def resolve_round_limit_or_buyer_rejection(
    buyer_rejected: bool, round_limit_reached: bool
) -> Decision:
    """Table 5: 'Buyer rejects / limit reached -> REJECT'."""
    if buyer_rejected or round_limit_reached:
        reason = "Buyer rejected the offer." if buyer_rejected else "Negotiation round limit reached."
        return Decision(
            action=NegotiationAction.REJECT,
            selected_candidate_id=None,
            reason=reason,
            requires_approval=False,
        )
    raise ValueError("Called without buyer_rejected or round_limit_reached being true")


def resolve_merchant_denial() -> Decision:
    """Table 5: 'Merchant denies escalation -> REJECT'."""
    return Decision(
        action=NegotiationAction.REJECT,
        selected_candidate_id=None,
        reason="Merchant denied the escalated offer.",
        requires_approval=False,
    )
