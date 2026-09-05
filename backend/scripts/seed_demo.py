"""
Demo reset/seed script (doc section 22: 'demo must work repeatedly after
reset'). Wipes and recreates the SQLite DB with the doc's exact Table 10
hero fixture, so the 5-minute demo script is byte-for-byte reproducible.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.config import Config
from app.core.domain import MerchantPolicy, Product
from app.database import get_connection, init_db
from app.repositories import merchant_repo


def seed(db_path: str = None):
    db_path = db_path or Config.DB_PATH
    if os.path.exists(db_path):
        os.remove(db_path)
    init_db(db_path)
    conn = get_connection(db_path)

    merchant_repo.create_merchant(conn, "M-demo", "Demo Electronics Store", "demo-merchant-token")

    product = Product(
        product_id="P-earbuds-x200",
        merchant_id="M-demo",
        base_price_paise=800000,
        cost_paise=450000,
        delivery_cost_paise=5000,
        inventory=18,
        delivery_capacity_tomorrow=3,
    )
    merchant_repo.create_product(conn, product, "Wireless Earbuds X200")

    policy = MerchantPolicy(
        merchant_id="M-demo",
        margin_floor_paise=200000,
        max_discount_paise=80000,
        max_cashback_paise=50000,
        incentive_budget_paise=1000000,
        incentive_spend_to_date_paise=980000,
        approval_threshold_paise=100000,
        max_rounds=3,
    )
    merchant_repo.upsert_policy(conn, policy)

    conn.commit()
    conn.close()
    print(f"Seeded {db_path} with demo merchant M-demo, token=demo-merchant-token")


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "econex.db"
    seed(target)
