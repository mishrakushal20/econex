"""
Canonical monetary type for Econex.

WHY: The documentation (section 3, "Financial Source of Truth") locks all
monetary values to integer paise. Floating point is banned from the
financial path because floats introduce silent rounding drift in
comparisons like `contribution >= margin_floor`, which is exactly the kind
of bug that would let an unprofitable offer slip through the Policy Engine.

Every function in this module operates on plain `int` paise values and
raises on non-integer input rather than silently coercing it.
"""

from __future__ import annotations


def to_paise(rupees: float) -> int:
    """Convert a rupee amount (e.g. from a UI form) into integer paise.

    WHY a separate boundary function: this is the ONLY place floating point
    is allowed to touch a monetary value, and only at the edge where a
    human-entered rupee amount crosses into the system. Once converted,
    nothing downstream ever sees a float again.
    """
    if not isinstance(rupees, (int, float)):
        raise TypeError(f"to_paise expects int or float, got {type(rupees)}")
    paise = round(rupees * 100)
    return int(paise)


def paise_to_rupees_str(paise: int) -> str:
    """Render integer paise as a human-readable INR string for display only."""
    require_paise(paise)
    sign = "-" if paise < 0 else ""
    paise = abs(paise)
    rupees, remainder = divmod(paise, 100)
    return f"{sign}\u20b9{rupees:,}.{remainder:02d}"


def require_paise(value: int, field_name: str = "value") -> int:
    """Assert a value is a valid integer paise amount. Raise otherwise.

    WHY: this is called defensively at every module boundary (candidate
    generator, policy engine, economic engine) so that a stray float or
    None can never silently propagate into a financial decision.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field_name} must be an int (paise), got {value!r}")
    return value


def clamp_paise(value: int, low: int, high: int) -> int:
    require_paise(value, "value")
    require_paise(low, "low")
    require_paise(high, "high")
    return max(low, min(high, value))
