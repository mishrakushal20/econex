"""
Candidate Generator — the authoritative source of financial candidate numbers.

WHY this module exists and what it must never become: doc section 7/10
states the LLM/agent layer may propose STRATEGY but must never become the
authoritative source of financial candidate numbers. This module has NO
import of any LLM/agent code and never will — that boundary is checked by
tests/test_architecture_boundary.py.

Grid (locked, doc section 10):
    price_steps    = [base_price, base_price - max_discount/2, base_price - max_discount]
    cashback_steps = [0, max_cashback/2, max_cashback]
    delivery_steps = ["standard"] + (["expedited"] if tomorrow_capacity > 0 else [])
    buyer-stated price is inserted as an anchor candidate when structurally valid.

For the doc's hero scenario (max_discount=800, max_cashback=500,
tomorrow_capacity=3) this yields exactly 3*3*2 + 1 anchor = 19 candidates,
matching doc section 9's "19 bounded candidates" claim.
"""

from __future__ import annotations

from typing import FrozenSet, Iterable, List, Optional, Set, Tuple

from app.core.domain import BuyerIntent, Candidate, DeliveryOption, MerchantPolicy, Product


def _price_steps(product: Product, policy: MerchantPolicy) -> List[int]:
    base = product.base_price_paise
    half = policy.max_discount_paise // 2
    full = policy.max_discount_paise
    return [base, base - half, base - full]


def _cashback_steps(policy: MerchantPolicy) -> List[int]:
    half = policy.max_cashback_paise // 2
    full = policy.max_cashback_paise
    return [0, half, full]


def _delivery_steps(product: Product) -> List[DeliveryOption]:
    steps = [DeliveryOption.STANDARD]
    if product.delivery_capacity_tomorrow > 0:
        steps.append(DeliveryOption.EXPEDITED)
    return steps


def _is_structurally_valid_anchor(intent: BuyerIntent, product: Product) -> bool:
    """A buyer-stated price is only inserted as an anchor if it is a sane,
    positive, non-absurd number — structural validity, not economic
    feasibility (that is the Policy Engine's job, per doc section 10:
    "Generation does not enforce economic feasibility; Policy Engine does.")
    """
    price = intent.requested_price_paise
    if price is None:
        return False
    if price <= 0:
        return False
    # Reject obviously malformed/adversarial anchors (e.g. negative-adjacent
    # overflow attempts) far outside any sane multiple of base price. This is
    # defense-in-depth, not the margin/discount policy check.
    if price > product.base_price_paise * 10:
        return False
    return True


def generate_candidates(
    intent: BuyerIntent,
    product: Product,
    policy: MerchantPolicy,
    previously_rejected_final_prices_paise: Optional[FrozenSet[int]] = None,
) -> Tuple[Candidate, ...]:
    """Generate the bounded, deterministic, deduplicated candidate set.

    `previously_rejected_final_prices_paise`: doc section 10 — "Rejected grid
    prices may be excluded on later rounds." Only applied when
    intent.round_number > 1, so a first-round buyer ask is never pre-filtered
    by history that doesn't exist yet.
    """
    rejected = previously_rejected_final_prices_paise or frozenset()

    seen: Set[Tuple[int, int, DeliveryOption]] = set()
    ordered_keys: List[Tuple[int, int, DeliveryOption]] = []

    prices = _price_steps(product, policy)
    cashbacks = _cashback_steps(policy)
    deliveries = _delivery_steps(product)

    for price in prices:
        for cashback in cashbacks:
            for delivery in deliveries:
                key = (price, cashback, delivery)
                if key in seen:
                    continue
                if price < product.cost_paise:
                    # doc section 10: "No candidate below cost is emitted."
                    continue
                if intent.round_number > 1 and price in rejected:
                    continue
                seen.add(key)
                ordered_keys.append(key)

    if _is_structurally_valid_anchor(intent, product):
        anchor_price = intent.requested_price_paise
        anchor_cashback = min(intent.requested_cashback_paise, policy.max_cashback_paise)
        anchor_delivery = (
            DeliveryOption.EXPEDITED
            if intent.wants_expedited_delivery and product.delivery_capacity_tomorrow > 0
            else DeliveryOption.STANDARD
        )
        anchor_key = (anchor_price, anchor_cashback, anchor_delivery)
        if anchor_key not in seen and anchor_price >= product.cost_paise:
            seen.add(anchor_key)
            ordered_keys.append(anchor_key)

    candidates: List[Candidate] = []
    for index, (price, cashback, delivery) in enumerate(ordered_keys, start=1):
        discount = max(0, product.base_price_paise - price)
        candidates.append(
            Candidate(
                candidate_id=f"C{index}",
                final_price_paise=price,
                discount_paise=discount,
                cashback_paise=cashback,
                quantity=intent.quantity,
                delivery_option=delivery,
            )
        )
    return tuple(candidates)
