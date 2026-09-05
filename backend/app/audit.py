"""
Audit trail (doc section 15). Every important stage is recorded so a judge
can reconstruct "what exactly happened from buyer request to Razorpay
execution". Entries are append-only (no UPDATE/DELETE path exists anywhere
in this module) — that is the MVP's definition of "immutable".
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

STAGES = (
    "intent",
    "proposal",
    "candidate_generation",
    "policy",
    "economic_evaluation",
    "selection",
    "decision",
    "authorization",
    "payment",
    "outcome",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def record(
    conn: sqlite3.Connection,
    stage: str,
    payload: Dict[str, Any],
    session_id: Optional[str] = None,
    merchant_id: Optional[str] = None,
) -> str:
    if stage not in STAGES:
        raise ValueError(f"Unknown audit stage '{stage}', must be one of {STAGES}")
    audit_id = f"audit-{uuid.uuid4().hex[:12]}"
    conn.execute(
        "INSERT INTO audit_events (audit_id, merchant_id, session_id, stage, payload_json, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (audit_id, merchant_id, session_id, stage, json.dumps(payload, default=str), _now()),
    )
    return audit_id


def timeline_for_session(
    conn: sqlite3.Connection, session_id: str, merchant_id: Optional[str] = None
):
    """`merchant_id` should always be supplied by API callers (doc upgrade
    section 8: merchant isolation). It is optional only for internal/test
    callers that already trust the session_id (e.g. a same-request
    read-after-write within a handler that already authenticated)."""
    if merchant_id is not None:
        rows = conn.execute(
            "SELECT audit_id, stage, payload_json, created_at FROM audit_events "
            "WHERE session_id = ? AND merchant_id = ? ORDER BY created_at ASC",
            (session_id, merchant_id),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT audit_id, stage, payload_json, created_at FROM audit_events "
            "WHERE session_id = ? ORDER BY created_at ASC",
            (session_id,),
        ).fetchall()
    return [
        {
            "audit_id": row["audit_id"],
            "stage": row["stage"],
            "payload": json.loads(row["payload_json"]),
            "created_at": row["created_at"],
        }
        for row in rows
    ]
