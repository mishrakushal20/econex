"""Negotiation session / intent / offer / decision persistence."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Optional, Tuple

from app.core.domain import BuyerIntent, Candidate, Decision, EconomicEvaluation, PolicyResult


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_session(conn: sqlite3.Connection, merchant_id: str, product_id: str) -> str:
    session_id = f"S-{uuid.uuid4().hex[:10]}"
    now = _now()
    conn.execute(
        "INSERT INTO negotiation_sessions (session_id, merchant_id, product_id, state, "
        "round_number, created_at, updated_at) VALUES (?, ?, ?, 'OPEN', 1, ?, ?)",
        (session_id, merchant_id, product_id, now, now),
    )
    return session_id


def get_session(conn: sqlite3.Connection, session_id: str) -> Optional[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM negotiation_sessions WHERE session_id = ?", (session_id,)
    ).fetchone()


def update_session_state(conn: sqlite3.Connection, session_id: str, new_state: str) -> None:
    conn.execute(
        "UPDATE negotiation_sessions SET state = ?, updated_at = ? WHERE session_id = ?",
        (new_state, _now(), session_id),
    )


def record_intent(
    conn: sqlite3.Connection,
    session_id: str,
    intent: BuyerIntent,
    raw_text: Optional[str],
    agent_strategy: Optional[str],
    agent_rationale: Optional[str],
) -> str:
    intent_id = f"I-{uuid.uuid4().hex[:10]}"
    conn.execute(
        """INSERT INTO buyer_intents
           (intent_id, session_id, raw_text, buyer_budget_paise, quantity, requested_price_paise,
            requested_cashback_paise, wants_expedited_delivery, agent_strategy, agent_rationale, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            intent_id,
            session_id,
            raw_text,
            intent.buyer_budget_paise,
            intent.quantity,
            intent.requested_price_paise,
            intent.requested_cashback_paise,
            int(intent.wants_expedited_delivery),
            agent_strategy,
            agent_rationale,
            _now(),
        ),
    )
    return intent_id


def record_offers(
    conn: sqlite3.Connection,
    intent_id: str,
    candidates: Tuple[Candidate, ...],
    policy_results: Tuple[PolicyResult, ...],
    evaluations: Tuple[EconomicEvaluation, ...],
) -> None:
    by_candidate = {c.candidate_id: c for c in candidates}
    by_policy = {p.candidate_id: p for p in policy_results}
    for evaluation in evaluations:
        candidate = by_candidate[evaluation.candidate_id]
        policy_result = by_policy[evaluation.candidate_id]
        eov = evaluation.expected_economic_value_paise
        conn.execute(
            """INSERT INTO offers
               (candidate_id, intent_id, final_price_paise, discount_paise, cashback_paise, quantity,
                delivery_option, feasible, first_violation, contribution_paise, p_conv,
                incentive_cost_paise, eov_paise)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                candidate.candidate_id,
                intent_id,
                candidate.final_price_paise,
                candidate.discount_paise,
                candidate.cashback_paise,
                candidate.quantity,
                candidate.delivery_option.value,
                int(evaluation.feasible),
                policy_result.first_violation.value if policy_result.first_violation else None,
                evaluation.contribution_paise,
                evaluation.p_conv,
                evaluation.incentive_cost_paise,
                None if eov == float("-inf") else eov,
            ),
        )


def record_decision(
    conn: sqlite3.Connection,
    intent_id: str,
    merchant_id: str,
    decision: Decision,
    state: str,
    frozen_candidate: Optional[Candidate],
    expires_in_seconds: int = 900,
) -> str:
    """Records the decision AND freezes the authorized commercial terms
    (doc upgrade section 5: AUTHORIZED DECISION -> FROZEN COMMERCIAL TERMS
    -> PAYMENT). `frozen_candidate` is None for REJECT/no-selection
    decisions, which can never be paid for."""
    from datetime import timedelta

    decision_id = f"D-{uuid.uuid4().hex[:10]}"
    now_dt = datetime.now(timezone.utc)
    expires_at = (now_dt + timedelta(seconds=expires_in_seconds)).isoformat()
    conn.execute(
        """INSERT INTO decisions
           (decision_id, intent_id, merchant_id, action, selected_candidate_id, reason,
            requires_approval, state, frozen_final_price_paise, frozen_discount_paise,
            frozen_cashback_paise, frozen_quantity, frozen_delivery_option, expires_at, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            decision_id,
            intent_id,
            merchant_id,
            decision.action.value,
            decision.selected_candidate_id,
            decision.reason,
            int(decision.requires_approval),
            state,
            frozen_candidate.final_price_paise if frozen_candidate else None,
            frozen_candidate.discount_paise if frozen_candidate else None,
            frozen_candidate.cashback_paise if frozen_candidate else None,
            frozen_candidate.quantity if frozen_candidate else None,
            frozen_candidate.delivery_option.value if frozen_candidate else None,
            expires_at,
            now_dt.isoformat(),
        ),
    )
    return decision_id


def get_decision(conn: sqlite3.Connection, decision_id: str) -> Optional[sqlite3.Row]:
    """UNSCOPED lookup — internal use only (e.g. webhook processing, which
    has no merchant bearer token). API handlers MUST use
    get_decision_scoped instead; see docs/SECURITY.md 'merchant isolation'."""
    return conn.execute("SELECT * FROM decisions WHERE decision_id = ?", (decision_id,)).fetchone()


def get_decision_scoped(
    conn: sqlite3.Connection, decision_id: str, merchant_id: str
) -> Optional[sqlite3.Row]:
    """The correct lookup for every merchant-authenticated API handler.
    Returns None (never another merchant's row) if the decision exists but
    belongs to a different merchant — the caller cannot distinguish
    'not found' from 'not yours', which is deliberate (doc upgrade section 8)."""
    return conn.execute(
        "SELECT * FROM decisions WHERE decision_id = ? AND merchant_id = ?",
        (decision_id, merchant_id),
    ).fetchone()


def update_decision_state(conn: sqlite3.Connection, decision_id: str, new_state: str) -> None:
    conn.execute("UPDATE decisions SET state = ? WHERE decision_id = ?", (new_state, decision_id))


def record_authorization(
    conn: sqlite3.Connection, decision_id: str, actor: str, previous_state: str, new_state: str
) -> str:
    authorization_id = f"AUTH-{uuid.uuid4().hex[:10]}"
    conn.execute(
        """INSERT INTO authorizations
           (authorization_id, decision_id, actor, previous_state, new_state, created_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (authorization_id, decision_id, actor, previous_state, new_state, _now()),
    )
    return authorization_id


def record_outcome(
    conn: sqlite3.Connection,
    decision_id: str,
    predicted_p_conv: Optional[float],
    predicted_eov_paise: Optional[float],
    actual_converted: bool,
    actual_contribution_paise: int,
) -> str:
    outcome_id = f"OUT-{uuid.uuid4().hex[:10]}"
    prediction_error = None
    if predicted_p_conv is not None:
        prediction_error = abs(predicted_p_conv - (1.0 if actual_converted else 0.0))
    conn.execute(
        """INSERT INTO outcomes
           (outcome_id, decision_id, predicted_p_conv, predicted_eov_paise, actual_converted,
            actual_contribution_paise, prediction_error, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            outcome_id,
            decision_id,
            predicted_p_conv,
            predicted_eov_paise,
            int(actual_converted),
            actual_contribution_paise,
            prediction_error,
            _now(),
        ),
    )
    return outcome_id
