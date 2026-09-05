"""
Negotiation State Machine (doc section 14, locked):

    OPEN -> EVALUATE
      |- no feasible          -> CLOSED_REJECTED
      |- approval required    -> PENDING_APPROVAL
      \\- candidate            -> AWAITING_BUYER_RESPONSE
    AWAITING_BUYER_RESPONSE -> ACCEPT / REJECT / OPEN(next round)
    PENDING_APPROVAL -> APPROVED / DENIED

Approval flow (doc section 11/13):
    PENDING_APPROVAL -> APPROVED -> CLOSED_ACCEPTED
    PENDING_APPROVAL -> DENIED   -> CLOSED_REJECTED

WHY an explicit transition table instead of ad-hoc `if` statements
scattered through the API layer: doc section 11 requires ESCALATE to be "a
real state, not a dead-end string", and section 15 requires every
transition to be auditable with actor/timestamp/previous/new state. A
single table is the only way to guarantee an invalid transition (e.g.
skipping straight from OPEN to CLOSED_ACCEPTED) is structurally impossible.
"""

from __future__ import annotations

from enum import Enum
from typing import FrozenSet, Tuple


class NegotiationState(str, Enum):
    OPEN = "OPEN"
    AWAITING_BUYER_RESPONSE = "AWAITING_BUYER_RESPONSE"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    CLOSED_ACCEPTED = "CLOSED_ACCEPTED"
    CLOSED_REJECTED = "CLOSED_REJECTED"


_ALLOWED_TRANSITIONS: FrozenSet[Tuple[NegotiationState, NegotiationState]] = frozenset(
    {
        (NegotiationState.OPEN, NegotiationState.CLOSED_REJECTED),
        (NegotiationState.OPEN, NegotiationState.PENDING_APPROVAL),
        (NegotiationState.OPEN, NegotiationState.AWAITING_BUYER_RESPONSE),
        (NegotiationState.AWAITING_BUYER_RESPONSE, NegotiationState.CLOSED_ACCEPTED),
        (NegotiationState.AWAITING_BUYER_RESPONSE, NegotiationState.CLOSED_REJECTED),
        (NegotiationState.AWAITING_BUYER_RESPONSE, NegotiationState.OPEN),  # next round
        (NegotiationState.PENDING_APPROVAL, NegotiationState.APPROVED),
        (NegotiationState.PENDING_APPROVAL, NegotiationState.DENIED),
        (NegotiationState.APPROVED, NegotiationState.CLOSED_ACCEPTED),
        (NegotiationState.DENIED, NegotiationState.CLOSED_REJECTED),
    }
)


class InvalidTransitionError(Exception):
    pass


def transition(
    current: NegotiationState, target: NegotiationState
) -> NegotiationState:
    """Validate and perform a state transition. Raises InvalidTransitionError
    for anything not in the locked table above — callers (the API layer)
    must catch this and audit it as a rejected transition attempt, never
    silently coerce to a valid state.
    """
    if (current, target) not in _ALLOWED_TRANSITIONS:
        raise InvalidTransitionError(
            f"Transition {current.value} -> {target.value} is not permitted"
        )
    return target


def is_terminal(state: NegotiationState) -> bool:
    return state in (NegotiationState.CLOSED_ACCEPTED, NegotiationState.CLOSED_REJECTED)
