"""RetentionAgent — high-risk/high-value retention (doc Table 2)."""

from __future__ import annotations

from typing import Any, Dict

from app.agents.base_agent import BaseGrowthAgent


class RetentionAgent(BaseGrowthAgent):
    strategy_name = "RETENTION"

    def is_relevant(self, context: Dict[str, Any]) -> bool:
        return bool(context.get("is_repeat_customer") or context.get("churn_risk"))
