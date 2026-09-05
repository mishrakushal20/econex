"""
Policy Engine — the deterministic financial safety boundary (doc section 11).

HARD RULE: this module must never import anything from app.llm or app.agents.
It must never call an LLM, compute a conversion probability, compute EOV,
rank candidates, authorize a payment, or decide a negotiation action. It
only answers: "is this candidate financially feasible, and if not, why?"

Checks run in the exact documented order (doc Table 4 / section 11). The
FIRST failing check is reported as `first_violation`; all checks are still
run and recorded in `diagnostics` for audit purposes (doc section 15).

LOCKED FINANCIAL INTERPRETATION (superseding an earlier draft of this file
— see docs/DECISIONS.md "Reconciliation" section for the full writeup):

    Incentive budget consumption = discount + cashback
    EOV Incentive_Cost           = cashback only
    Discount is already reflected in final_price and therefore affects
    ExpectedContribution, not EOV's incentive-cost term directly.

These are the two intentionally separate concepts from doc section 5. The
locked budget check is:

    incentive_spend_to_date + discount + cashback <= incentive_budget

An earlier version of this file implemented a cashback-only budget check,
reasoning from the doc's own Table 4 wording and its worked ₹7,600 example
(which is only FEASIBLE under a cashback-only rule). That was a documented-
but-incorrect resolution of a genuine contradiction between the master
prompt and the doc. The product owner has since explicitly locked the
discount+cashback interpretation (doc's Table 3/Table 4 illustrative
numbers are therefore themselves acknowledged as inconsistent with the
locked rule — see docs/DECISIONS.md for the full reconciliation list of
every affected example/test).
"""

from __future__ import annotations

from typing import List, Tuple

from app.core.domain import (
    BuyerIntent,
    Candidate,
    DeliveryOption,
    MerchantPolicy,
    PolicyDiagnostic,
    PolicyResult,
    PolicyViolationCode,
    Product,
)


def _contribution_paise(candidate: Candidate, product: Product) -> int:
    """ExpectedContribution = (final_price - cost - delivery_cost) * quantity
    (doc section 4 — locked formula, single canonical implementation).
    """
    return (
        candidate.final_price_paise - product.cost_paise - product.delivery_cost_paise
    ) * candidate.quantity


def evaluate_candidate(
    candidate: Candidate,
    intent: BuyerIntent,
    product: Product,
    policy: MerchantPolicy,
) -> PolicyResult:
    contribution = _contribution_paise(candidate, product)
    diagnostics: List[PolicyDiagnostic] = []
    first_violation = None

    def record(code: PolicyViolationCode, passed: bool, detail: str) -> None:
        nonlocal first_violation
        diagnostics.append(PolicyDiagnostic(code=code, passed=passed, detail=detail))
        if not passed and first_violation is None:
            first_violation = code

    # 1. PRICE_BELOW_COST
    record(
        PolicyViolationCode.PRICE_BELOW_COST,
        candidate.final_price_paise >= product.cost_paise,
        f"final_price={candidate.final_price_paise} cost={product.cost_paise}",
    )

    # 2. CONTRIBUTION_BELOW_MARGIN_FLOOR
    record(
        PolicyViolationCode.CONTRIBUTION_BELOW_MARGIN_FLOOR,
        contribution >= policy.margin_floor_paise,
        f"contribution={contribution} margin_floor={policy.margin_floor_paise}",
    )

    # 3. MAX_DISCOUNT_EXCEEDED
    record(
        PolicyViolationCode.MAX_DISCOUNT_EXCEEDED,
        candidate.discount_paise <= policy.max_discount_paise,
        f"discount={candidate.discount_paise} max_discount={policy.max_discount_paise}",
    )

    # 4. MAX_CASHBACK_EXCEEDED
    record(
        PolicyViolationCode.MAX_CASHBACK_EXCEEDED,
        candidate.cashback_paise <= policy.max_cashback_paise,
        f"cashback={candidate.cashback_paise} max_cashback={policy.max_cashback_paise}",
    )

    # 5. INCENTIVE_BUDGET_EXCEEDED — LOCKED: discount + cashback (see module
    # docstring "LOCKED FINANCIAL INTERPRETATION" for the reconciliation of
    # why this superseded an earlier cashback-only implementation).
    projected_spend = (
        policy.incentive_spend_to_date_paise
        + candidate.discount_paise
        + candidate.cashback_paise
    )
    record(
        PolicyViolationCode.INCENTIVE_BUDGET_EXCEEDED,
        projected_spend <= policy.incentive_budget_paise,
        f"spend_to_date+discount+cashback={projected_spend} budget={policy.incentive_budget_paise}",
    )

    # 6. INSUFFICIENT_INVENTORY
    record(
        PolicyViolationCode.INSUFFICIENT_INVENTORY,
        candidate.quantity <= product.inventory,
        f"quantity={candidate.quantity} inventory={product.inventory}",
    )

    # 7. DELIVERY_CAPACITY_UNAVAILABLE — expedited requires tomorrow capacity
    expedited_ok = (
        candidate.delivery_option != DeliveryOption.EXPEDITED
        or candidate.quantity <= product.delivery_capacity_tomorrow
    )
    record(
        PolicyViolationCode.DELIVERY_CAPACITY_UNAVAILABLE,
        expedited_ok,
        f"delivery={candidate.delivery_option.value} capacity_tomorrow={product.delivery_capacity_tomorrow}",
    )

    # 8. OFFER_EXPIRED
    record(
        PolicyViolationCode.OFFER_EXPIRED,
        not intent.offer_expired,
        f"offer_expired={intent.offer_expired}",
    )

    # 9. ROUND_LIMIT_EXCEEDED
    record(
        PolicyViolationCode.ROUND_LIMIT_EXCEEDED,
        intent.round_number <= policy.max_rounds,
        f"round_number={intent.round_number} max_rounds={policy.max_rounds}",
    )

    feasible = first_violation is None
    return PolicyResult(
        candidate_id=candidate.candidate_id,
        feasible=feasible,
        contribution_paise=contribution,
        first_violation=first_violation,
        diagnostics=tuple(diagnostics),
    )


def evaluate_all(
    candidates: Tuple[Candidate, ...],
    intent: BuyerIntent,
    product: Product,
    policy: MerchantPolicy,
) -> Tuple[PolicyResult, ...]:
    """Evaluate every candidate. Infeasible ones are kept for diagnostics
    (doc section 9: "Infeasible candidates may be evaluated for diagnostics,
    but MUST NEVER enter the eligible winner set.") — enforced downstream by
    the Optimizer, which filters on `.feasible` before ranking.
    """
    return tuple(evaluate_candidate(c, intent, product, policy) for c in candidates)
