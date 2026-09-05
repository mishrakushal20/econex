"""Merchant, product, and policy repositories — simple CRUD over sqlite3."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Optional

from app.core.domain import MerchantPolicy, Product


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_merchant(conn: sqlite3.Connection, merchant_id: str, name: str, api_token: str) -> None:
    conn.execute(
        "INSERT INTO merchants (merchant_id, name, api_token, created_at) VALUES (?, ?, ?, ?)",
        (merchant_id, name, api_token, _now()),
    )


def get_merchant_by_token(conn: sqlite3.Connection, api_token: str) -> Optional[sqlite3.Row]:
    return conn.execute("SELECT * FROM merchants WHERE api_token = ?", (api_token,)).fetchone()


def create_product(conn: sqlite3.Connection, product: Product, name: str) -> None:
    conn.execute(
        """INSERT INTO products
           (product_id, merchant_id, name, base_price_paise, cost_paise, delivery_cost_paise,
            inventory, delivery_capacity_tomorrow)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            product.product_id,
            product.merchant_id,
            name,
            product.base_price_paise,
            product.cost_paise,
            product.delivery_cost_paise,
            product.inventory,
            product.delivery_capacity_tomorrow,
        ),
    )


def get_product(conn: sqlite3.Connection, product_id: str) -> Optional[Product]:
    row = conn.execute("SELECT * FROM products WHERE product_id = ?", (product_id,)).fetchone()
    if row is None:
        return None
    return Product(
        product_id=row["product_id"],
        merchant_id=row["merchant_id"],
        base_price_paise=row["base_price_paise"],
        cost_paise=row["cost_paise"],
        delivery_cost_paise=row["delivery_cost_paise"],
        inventory=row["inventory"],
        delivery_capacity_tomorrow=row["delivery_capacity_tomorrow"],
    )


def upsert_policy(conn: sqlite3.Connection, policy: MerchantPolicy) -> None:
    conn.execute(
        """INSERT INTO merchant_policies
           (merchant_id, margin_floor_paise, max_discount_paise, max_cashback_paise,
            incentive_budget_paise, incentive_spend_to_date_paise, approval_threshold_paise, max_rounds)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(merchant_id) DO UPDATE SET
             margin_floor_paise=excluded.margin_floor_paise,
             max_discount_paise=excluded.max_discount_paise,
             max_cashback_paise=excluded.max_cashback_paise,
             incentive_budget_paise=excluded.incentive_budget_paise,
             incentive_spend_to_date_paise=excluded.incentive_spend_to_date_paise,
             approval_threshold_paise=excluded.approval_threshold_paise,
             max_rounds=excluded.max_rounds""",
        (
            policy.merchant_id,
            policy.margin_floor_paise,
            policy.max_discount_paise,
            policy.max_cashback_paise,
            policy.incentive_budget_paise,
            policy.incentive_spend_to_date_paise,
            policy.approval_threshold_paise,
            policy.max_rounds,
        ),
    )


def get_policy(conn: sqlite3.Connection, merchant_id: str) -> Optional[MerchantPolicy]:
    row = conn.execute(
        "SELECT * FROM merchant_policies WHERE merchant_id = ?", (merchant_id,)
    ).fetchone()
    if row is None:
        return None
    return MerchantPolicy(
        merchant_id=row["merchant_id"],
        margin_floor_paise=row["margin_floor_paise"],
        max_discount_paise=row["max_discount_paise"],
        max_cashback_paise=row["max_cashback_paise"],
        incentive_budget_paise=row["incentive_budget_paise"],
        incentive_spend_to_date_paise=row["incentive_spend_to_date_paise"],
        approval_threshold_paise=row["approval_threshold_paise"],
        max_rounds=row["max_rounds"],
    )


def increment_spend(conn: sqlite3.Connection, merchant_id: str, amount_paise: int) -> None:
    """Called only after a decision is actually CLOSED_ACCEPTED (doc section 8/9:
    budget accounting reflects committed spend, not merely proposed spend)."""
    conn.execute(
        "UPDATE merchant_policies SET incentive_spend_to_date_paise = "
        "incentive_spend_to_date_paise + ? WHERE merchant_id = ?",
        (amount_paise, merchant_id),
    )
