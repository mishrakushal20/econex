"""CartRecoveryAgent — checkout-stage recovery (doc Table 2)."""

from __future__ import annotations

from typing import Any, Dict

from app.agents.base_agent import BaseGrowthAgent


class CartRecoveryAgent(BaseGrowthAgent):
    strategy_name = "CART_RECOVERY"

    def is_relevant(self, context: Dict[str, Any]) -> bool:
        return bool(context.get("cart_abandoned"))
