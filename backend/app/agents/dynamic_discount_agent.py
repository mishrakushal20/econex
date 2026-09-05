"""DynamicDiscountAgent — margin-aware price optimization (doc Table 2)."""

from __future__ import annotations

from typing import Any, Dict

from app.agents.base_agent import BaseGrowthAgent


class DynamicDiscountAgent(BaseGrowthAgent):
    strategy_name = "DYNAMIC_DISCOUNT"

    def is_relevant(self, context: Dict[str, Any]) -> bool:
        return bool(context.get("buyer_stated_lower_price"))
