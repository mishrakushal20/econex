"""
Shared domain types for the deterministic core.

WHY a separate module: candidate_generator, policy_engine, economic_engine,
optimizer and decision_resolver all need the same shapes. Defining them once
prevents drift between modules (doc section 24: "Every financial formula
should have one canonical implementation" — the same discipline applies to
the data shapes those formulas operate on).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


@dataclass(frozen=True)
class MerchantPolicy:
    merchant_id: str
    margin_floor_paise: int
    max_discount_paise: int
    max_cashback_paise: int
    incentive_budget_paise: int
    incentive_spend_to_date_paise: int
    approval_threshold_paise: int
    max_rounds: int = 3


@dataclass(frozen=True)
class Product:
    product_id: str
    merchant_id: str
    base_price_paise: int
    cost_paise: int
    delivery_cost_paise: int
    inventory: int
    delivery_capacity_tomorrow: int


@dataclass(frozen=True)
class BuyerIntent:
    session_id: str
    product_id: str
    buyer_budget_paise: int
    quantity: int
    requested_price_paise: Optional[int]
    requested_cashback_paise: int = 0
    wants_expedited_delivery: bool = False
    round_number: int = 1
    offer_expired: bool = False


class DeliveryOption(str, Enum):
    STANDARD = "standard"
    EXPEDITED = "expedited"


@dataclass(frozen=True)
class Candidate:
    candidate_id: str
    final_price_paise: int
    discount_paise: int
    cashback_paise: int
    quantity: int
    delivery_option: DeliveryOption


class PolicyViolationCode(str, Enum):
    PRICE_BELOW_COST = "PRICE_BELOW_COST"
    CONTRIBUTION_BELOW_MARGIN_FLOOR = "CONTRIBUTION_BELOW_MARGIN_FLOOR"
    MAX_DISCOUNT_EXCEEDED = "MAX_DISCOUNT_EXCEEDED"
    MAX_CASHBACK_EXCEEDED = "MAX_CASHBACK_EXCEEDED"
    INCENTIVE_BUDGET_EXCEEDED = "INCENTIVE_BUDGET_EXCEEDED"
    INSUFFICIENT_INVENTORY = "INSUFFICIENT_INVENTORY"
    DELIVERY_CAPACITY_UNAVAILABLE = "DELIVERY_CAPACITY_UNAVAILABLE"
    OFFER_EXPIRED = "OFFER_EXPIRED"
    ROUND_LIMIT_EXCEEDED = "ROUND_LIMIT_EXCEEDED"


@dataclass(frozen=True)
class PolicyDiagnostic:
    """One evaluated constraint's outcome. Kept even when passed, for audit."""
    code: PolicyViolationCode
    passed: bool
    detail: str


@dataclass(frozen=True)
class PolicyResult:
    candidate_id: str
    feasible: bool
    contribution_paise: int
    first_violation: Optional[PolicyViolationCode]
    diagnostics: tuple  # tuple[PolicyDiagnostic, ...] — ordered per doc section 8/11


@dataclass(frozen=True)
class EconomicEvaluation:
    candidate_id: str
    feasible: bool
    p_conv: Optional[float]
    contribution_paise: int
    incentive_cost_paise: int
    expected_economic_value_paise: float


class NegotiationAction(str, Enum):
    ACCEPT = "ACCEPT"
    COUNTER = "COUNTER"
    REJECT = "REJECT"
    ESCALATE = "ESCALATE"


@dataclass(frozen=True)
class Decision:
    action: NegotiationAction
    selected_candidate_id: Optional[str]
    reason: str
    requires_approval: bool
