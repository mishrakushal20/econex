"""
Payment State Machine (upgrade master prompt section 7). Lives in
app/core because it is a pure, deterministic transition table with no I/O
and no LLM dependency — same rationale as app/core/state_machine.py.

Locked transitions:

    NONE -> CREATED -> CAPTURED
    NONE -> SIMULATED               (explicit simulation mode, terminal)
    CREATED -> FAILED
    NONE -> FAILED                  (real order creation itself failed)

Explicitly NOT allowed (doc section 7's own examples):
    CAPTURED -> CREATED, CAPTURED -> FAILED, FAILED -> CAPTURED, FAILED -> CREATED

A payment's status column is written exactly once per real transition;
`payments_repo.transition_payment_status` is the only function permitted to
call this and persist the result.
"""

from __future__ import annotations

from typing import FrozenSet, Tuple

from app.core.razorpay_adapter import PaymentStatus


class InvalidPaymentTransitionError(Exception):
    pass


_ALLOWED_PAYMENT_TRANSITIONS: FrozenSet[Tuple[PaymentStatus, PaymentStatus]] = frozenset(
    {
        (PaymentStatus.CREATED, PaymentStatus.CAPTURED),
        (PaymentStatus.CREATED, PaymentStatus.FAILED),
    }
)

# States a payment can be created directly INTO (the "NONE -> X" edges);
# these are produced by razorpay_adapter.create_order, never by a webhook.
INITIAL_STATES: FrozenSet[PaymentStatus] = frozenset(
    {PaymentStatus.CREATED, PaymentStatus.SIMULATED, PaymentStatus.FAILED, PaymentStatus.DUPLICATE_BLOCKED}
)


def transition_payment(current: PaymentStatus, target: PaymentStatus) -> PaymentStatus:
    if (current, target) not in _ALLOWED_PAYMENT_TRANSITIONS:
        raise InvalidPaymentTransitionError(
            f"Payment transition {current.value} -> {target.value} is not permitted"
        )
    return target


def is_terminal_payment_state(status: PaymentStatus) -> bool:
    return status in (
        PaymentStatus.CAPTURED,
        PaymentStatus.FAILED,
        PaymentStatus.SIMULATED,
        PaymentStatus.DUPLICATE_BLOCKED,
    )
