"""
Deterministic conversion probability heuristic.

WHY: This is a SYNTHETIC, deterministic heuristic (doc section 8.1) — it is
NOT a trained ML model and must never be represented as one anywhere in
docs, code comments, or UI copy. It exists to give the Economic Engine a
reproducible, bounded, monotonic P_conv so that EOV ranking is fully
explainable and unit-testable.

Formula (locked, do not modify without updating docs/ECONOMIC_MODEL.md):

    budget_fit        = clamp((buyer_budget - final_price) / buyer_budget, -1, 1)
    concession_signal = (base_price - final_price + cashback) / base_price
    urgency_term      = 0 unless an explicit delivery preference is stated
    raw_score         = 2.5*budget_fit + 1.5*concession_signal + 1.0*urgency_term
    P_conv            = 1 / (1 + e^(-2.0 * raw_score))

IMPLEMENTATION DECISION (minor detail, not locked by doc): the doc specifies
urgency_term is 0 unless "a delivery preference is explicitly stated" but
does not give the non-zero magnitude. We use 1.0 when the buyer explicitly
requested expedited delivery, matching the weight class of the other two
signals. This is recorded in docs/DECISIONS.md.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class ConversionInputs:
    buyer_budget_paise: int
    base_price_paise: int
    final_price_paise: int
    cashback_paise: int
    explicit_delivery_preference: bool = False


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def compute_p_conv(inputs: ConversionInputs) -> float:
    """Compute a deterministic conversion probability in the open interval (0, 1).

    Reproducible: same inputs always yield the exact same float output.
    Monotonic: holding cashback/base_price/buyer_budget fixed, P_conv strictly
    decreases as final_price increases (see tests for the property check).
    """
    if inputs.buyer_budget_paise == 0:
        raise ValueError("buyer_budget_paise must be non-zero")
    if inputs.base_price_paise == 0:
        raise ValueError("base_price_paise must be non-zero")

    budget_fit = _clamp(
        (inputs.buyer_budget_paise - inputs.final_price_paise) / inputs.buyer_budget_paise,
        -1.0,
        1.0,
    )
    concession_signal = (
        inputs.base_price_paise - inputs.final_price_paise + inputs.cashback_paise
    ) / inputs.base_price_paise
    urgency_term = 1.0 if inputs.explicit_delivery_preference else 0.0

    raw_score = 2.5 * budget_fit + 1.5 * concession_signal + 1.0 * urgency_term

    # WHY clamp the sigmoid exponent: concession_signal is unbounded (it can
    # grow arbitrarily large for candidates far below cost/base_price), and
    # math.exp overflows around |x| > ~709. Clamping the exponent argument
    # preserves the exact documented formula for all realistic inputs while
    # making the function total (never raises) for adversarial/extreme ones —
    # important because the Candidate Generator may probe extreme grid points
    # during red-team testing.
    exponent = _clamp(-2.0 * raw_score, -700.0, 700.0)
    p_conv = 1.0 / (1.0 + math.exp(exponent))

    # Defensive clamp: sigmoid output is already bounded in (0,1), but we
    # protect against float edge cases (e.g. extreme raw_score -> exactly 0/1)
    # to preserve the documented "bounded in (0,1)" contract strictly.
    epsilon = 1e-12
    return _clamp(p_conv, epsilon, 1.0 - epsilon)
