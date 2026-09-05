"""Hero scenario fixture from doc Table 10 / section 25 (Wireless Earbuds X200).

NOTE: under the LOCKED discount+cashback incentive-budget formula (see
docs/DECISIONS.md reconciliation), the near-exhausted incentive_spend_to_date
(₹9,800 of a ₹10,000 budget) makes every non-zero discount/cashback
candidate infeasible for this exact fixture. This is intentional and
verified in tests/test_hero_scenario_end_to_end.py — not a bug.
"""

from app.core.domain import BuyerIntent, MerchantPolicy, Product

HERO_PRODUCT = Product(
    product_id="P-earbuds-x200",
    merchant_id="M-demo",
    base_price_paise=800000,
    cost_paise=450000,
    delivery_cost_paise=5000,
    inventory=18,
    delivery_capacity_tomorrow=3,
)

HERO_POLICY = MerchantPolicy(
    merchant_id="M-demo",
    margin_floor_paise=200000,
    max_discount_paise=80000,
    max_cashback_paise=50000,
    incentive_budget_paise=1000000,
    incentive_spend_to_date_paise=980000,
    approval_threshold_paise=100000,
    max_rounds=3,
)

HERO_INTENT = BuyerIntent(
    session_id="S-1",
    product_id="P-earbuds-x200",
    buyer_budget_paise=680000,
    quantity=1,
    requested_price_paise=680000,
    requested_cashback_paise=0,
    wants_expedited_delivery=False,
    round_number=1,
    offer_expired=False,
)
