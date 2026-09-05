"""
Economic Engine — computes P_conv, contribution, incentive cost and EOV for
every candidate that has already been evaluated by the Policy Engine.

LOCKED FORMULA (doc section 4 — do not add risk adjustment, future value,
hidden penalties, or undocumented multipliers):

    ExpectedContribution = (final_price - cost - delivery_cost) * quantity
    IncentiveCost         = cashback
    EOV = P_conv * ExpectedContribution - IncentiveCost

WHY IncentiveCost is cashback-only here (and why this is NOT the same as
the budget check): doc section 5 is explicit that "Budget accounting !=
EOV Incentive Cost" — discount is already reflected inside final_price, so
including it again in IncentiveCost would double-count it. This is
intentionally a different number from the Policy Engine's budget check.
"""

from __future__ import annotations

from typing import Optional, Tuple

from app.core.conversion_heuristic import ConversionInputs, compute_p_conv
from app.core.domain import (
    BuyerIntent,
    Candidate,
    EconomicEvaluation,
    PolicyResult,
    Product,
)


def evaluate_economics(
    candidate: Candidate,
    policy_result: PolicyResult,
    intent: BuyerIntent,
    product: Product,
) -> EconomicEvaluation:
    """Evaluate a single candidate's economics.

    Infeasible candidates are still scored (for audit/diagnostic display —
    doc section 9) but callers (the Optimizer) MUST filter on `.feasible`
    before ranking; a fabricated high EOV on an infeasible candidate must
    never be allowed to win.
    """
    p_conv: Optional[float] = None
    eov: float

    if policy_result.feasible:
        inputs = ConversionInputs(
            buyer_budget_paise=intent.buyer_budget_paise,
            base_price_paise=product.base_price_paise,
            final_price_paise=candidate.final_price_paise,
            cashback_paise=candidate.cashback_paise,
            explicit_delivery_preference=intent.wants_expedited_delivery,
        )
        p_conv = compute_p_conv(inputs)
        eov = p_conv * policy_result.contribution_paise - candidate.cashback_paise
    else:
        # Infeasible candidates carry no meaningful EOV. We use -infinity so
        # they can never accidentally sort above a feasible candidate if a
        # caller forgets to filter (defense in depth, not a substitute for
        # the Optimizer's explicit feasibility filter).
        eov = float("-inf")

    return EconomicEvaluation(
        candidate_id=candidate.candidate_id,
        feasible=policy_result.feasible,
        p_conv=p_conv,
        contribution_paise=policy_result.contribution_paise,
        incentive_cost_paise=candidate.cashback_paise,
        expected_economic_value_paise=eov,
    )


def evaluate_all(
    candidates: Tuple[Candidate, ...],
    policy_results: Tuple[PolicyResult, ...],
    intent: BuyerIntent,
    product: Product,
) -> Tuple[EconomicEvaluation, ...]:
    by_id = {c.candidate_id: c for c in candidates}
    return tuple(
        evaluate_economics(by_id[pr.candidate_id], pr, intent, product)
        for pr in policy_results
    )
