"""
Payments repository — enforces idempotency (doc section 13/22: "Use
idempotency protection... Handle: duplicate requests, retry, timeout, API
failure, webhook updates, inconsistent state").

The `idempotency_key` column has a UNIQUE constraint (see app/database.py
schema). This module relies on that constraint rather than an in-memory
cache, so idempotency survives process restarts and works correctly even
under concurrent requests (SQLite serializes writes).
"""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Optional

from app.core.payment_state_machine import (
    InvalidPaymentTransitionError,
    transition_payment,
)
from app.core.razorpay_adapter import PaymentResult, PaymentStatus


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def find_by_idempotency_key(conn: sqlite3.Connection, idempotency_key: str) -> Optional[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM payments WHERE idempotency_key = ?", (idempotency_key,)
    ).fetchone()


def get_payment_scoped(
    conn: sqlite3.Connection, payment_id: str, merchant_id: str
) -> Optional[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM payments WHERE payment_id = ? AND merchant_id = ?",
        (payment_id, merchant_id),
    ).fetchone()


def find_by_razorpay_order_id(conn: sqlite3.Connection, razorpay_order_id: str) -> Optional[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM payments WHERE razorpay_order_id = ?", (razorpay_order_id,)
    ).fetchone()


def record_payment(
    conn: sqlite3.Connection,
    decision_id: str,
    merchant_id: str,
    idempotency_key: str,
    result: PaymentResult,
) -> str:
    """Insert a new payment row. Raises sqlite3.IntegrityError if
    idempotency_key already exists — callers MUST check
    find_by_idempotency_key first and return DUPLICATE_BLOCKED instead of
    calling this twice for the same key (see process_payment below for the
    correct pattern)."""
    payment_id = f"pay-{uuid.uuid4().hex[:12]}"
    now = _now()
    conn.execute(
        """INSERT INTO payments
           (payment_id, decision_id, merchant_id, idempotency_key, amount_paise, status, mode,
            razorpay_order_id, razorpay_payment_id, failure_reason, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            payment_id,
            decision_id,
            merchant_id,
            idempotency_key,
            result.amount_paise,
            result.status.value,
            result.mode,
            result.razorpay_order_id,
            None,
            result.failure_reason,
            now,
            now,
        ),
    )
    return payment_id


def transition_payment_status(
    conn: sqlite3.Connection, payment_id: str, target_status: PaymentStatus
) -> bool:
    """The ONLY function permitted to move a payment out of CREATED (doc
    upgrade section 7). Returns False (never raises) on an invalid
    transition attempt, so a forged/replayed webhook event can be rejected
    and audited without crashing the handler."""
    row = conn.execute("SELECT status FROM payments WHERE payment_id = ?", (payment_id,)).fetchone()
    if row is None:
        return False
    current_status = PaymentStatus(row["status"])
    try:
        new_status = transition_payment(current_status, target_status)
    except InvalidPaymentTransitionError:
        return False
    conn.execute(
        "UPDATE payments SET status = ?, updated_at = ? WHERE payment_id = ?",
        (new_status.value, _now(), payment_id),
    )
    return True


def process_payment(
    conn: sqlite3.Connection,
    decision_id: str,
    merchant_id: str,
    idempotency_key: str,
    amount_paise: int,
    create_order_fn,
) -> dict:
    """The single correct entry point for creating a payment with
    idempotency protection. `amount_paise` MUST already be the
    server-derived, frozen-terms amount — callers must never pass through
    a client-supplied value (doc upgrade section 4). `create_order_fn` is
    typically `app.core.razorpay_adapter.create_order`, injected so tests
    can use a fake without touching the network.

    Returns a dict describing the outcome, including whether this call was
    a duplicate (doc red-team scenario: 'duplicate payment').
    """
    existing = find_by_idempotency_key(conn, idempotency_key)
    if existing is not None:
        return {
            "payment_id": existing["payment_id"],
            "status": PaymentStatus.DUPLICATE_BLOCKED.value,
            "duplicate": True,
            "original_status": existing["status"],
        }

    result = create_order_fn(amount_paise, receipt=idempotency_key)
    payment_id = record_payment(conn, decision_id, merchant_id, idempotency_key, result)
    return {
        "payment_id": payment_id,
        "status": result.status.value,
        "duplicate": False,
        "label": result.label,
        "razorpay_order_id": result.razorpay_order_id,
        "failure_reason": result.failure_reason,
    }
