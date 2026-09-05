"""
SQLite persistence layer (doc section 16/21). Uses only the stdlib
`sqlite3` module — no ORM dependency needed for a hackathon-scale schema,
and it keeps the whole backend installable with zero third-party packages.

Transactional writes: every write path in repositories/ uses a single
connection `with conn:` block so a crash mid-write can never leave two
related tables (e.g. Payments + AuditEvents) inconsistent.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager

from app.config import Config

SCHEMA = """
CREATE TABLE IF NOT EXISTS merchants (
    merchant_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    api_token TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS products (
    product_id TEXT PRIMARY KEY,
    merchant_id TEXT NOT NULL REFERENCES merchants(merchant_id),
    name TEXT NOT NULL,
    base_price_paise INTEGER NOT NULL,
    cost_paise INTEGER NOT NULL,
    delivery_cost_paise INTEGER NOT NULL,
    inventory INTEGER NOT NULL,
    delivery_capacity_tomorrow INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS merchant_policies (
    merchant_id TEXT PRIMARY KEY REFERENCES merchants(merchant_id),
    margin_floor_paise INTEGER NOT NULL,
    max_discount_paise INTEGER NOT NULL,
    max_cashback_paise INTEGER NOT NULL,
    incentive_budget_paise INTEGER NOT NULL,
    incentive_spend_to_date_paise INTEGER NOT NULL DEFAULT 0,
    approval_threshold_paise INTEGER NOT NULL,
    max_rounds INTEGER NOT NULL DEFAULT 3
);

CREATE TABLE IF NOT EXISTS negotiation_sessions (
    session_id TEXT PRIMARY KEY,
    merchant_id TEXT NOT NULL REFERENCES merchants(merchant_id),
    product_id TEXT NOT NULL REFERENCES products(product_id),
    state TEXT NOT NULL,
    round_number INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS buyer_intents (
    intent_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES negotiation_sessions(session_id),
    raw_text TEXT,
    buyer_budget_paise INTEGER NOT NULL,
    quantity INTEGER NOT NULL,
    requested_price_paise INTEGER,
    requested_cashback_paise INTEGER NOT NULL DEFAULT 0,
    wants_expedited_delivery INTEGER NOT NULL DEFAULT 0,
    agent_strategy TEXT,
    agent_rationale TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS offers (
    candidate_id TEXT NOT NULL,
    intent_id TEXT NOT NULL REFERENCES buyer_intents(intent_id),
    final_price_paise INTEGER NOT NULL,
    discount_paise INTEGER NOT NULL,
    cashback_paise INTEGER NOT NULL,
    quantity INTEGER NOT NULL,
    delivery_option TEXT NOT NULL,
    feasible INTEGER NOT NULL,
    first_violation TEXT,
    contribution_paise INTEGER NOT NULL,
    p_conv REAL,
    incentive_cost_paise INTEGER NOT NULL,
    eov_paise REAL,
    PRIMARY KEY (candidate_id, intent_id)
);

CREATE TABLE IF NOT EXISTS decisions (
    decision_id TEXT PRIMARY KEY,
    intent_id TEXT NOT NULL REFERENCES buyer_intents(intent_id),
    merchant_id TEXT NOT NULL REFERENCES merchants(merchant_id),
    action TEXT NOT NULL,
    selected_candidate_id TEXT,
    reason TEXT NOT NULL,
    requires_approval INTEGER NOT NULL,
    state TEXT NOT NULL,
    -- FROZEN COMMERCIAL TERMS (doc upgrade section 5): captured at decision
    -- creation time so a payment can never be computed from a candidate row
    -- that was mutated or re-generated after authorization.
    frozen_final_price_paise INTEGER,
    frozen_discount_paise INTEGER,
    frozen_cashback_paise INTEGER,
    frozen_quantity INTEGER,
    frozen_delivery_option TEXT,
    expires_at TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS authorizations (
    authorization_id TEXT PRIMARY KEY,
    decision_id TEXT NOT NULL REFERENCES decisions(decision_id),
    actor TEXT NOT NULL,
    previous_state TEXT NOT NULL,
    new_state TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS payments (
    payment_id TEXT PRIMARY KEY,
    decision_id TEXT NOT NULL REFERENCES decisions(decision_id),
    merchant_id TEXT NOT NULL REFERENCES merchants(merchant_id),
    idempotency_key TEXT NOT NULL UNIQUE,
    amount_paise INTEGER NOT NULL,
    status TEXT NOT NULL,
    mode TEXT NOT NULL,
    razorpay_order_id TEXT,
    razorpay_payment_id TEXT,
    failure_reason TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS outcomes (
    outcome_id TEXT PRIMARY KEY,
    decision_id TEXT NOT NULL REFERENCES decisions(decision_id),
    predicted_p_conv REAL,
    predicted_eov_paise REAL,
    actual_converted INTEGER,
    actual_contribution_paise INTEGER,
    prediction_error REAL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_events (
    audit_id TEXT PRIMARY KEY,
    merchant_id TEXT,
    session_id TEXT,
    stage TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS webhook_events (
    webhook_event_id TEXT PRIMARY KEY,
    event_type TEXT NOT NULL,
    dedupe_key TEXT UNIQUE,
    payload_json TEXT NOT NULL,
    signature_valid INTEGER NOT NULL,
    processed INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
"""


def get_connection(db_path: str = None) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path or Config.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(db_path: str = None) -> None:
    conn = get_connection(db_path)
    try:
        with conn:
            conn.executescript(SCHEMA)
    finally:
        conn.close()


@contextmanager
def transaction(db_path: str = None):
    conn = get_connection(db_path)
    try:
        with conn:
            yield conn
    finally:
        conn.close()
