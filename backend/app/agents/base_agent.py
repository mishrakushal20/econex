"""
Base class for the three growth agents (doc section 12, Table 2).

Agents wrap an LLMProvider and translate its StrategyProposal into a
buyer-facing rationale string. They NEVER touch app.core.policy_engine,
app.core.economic_engine, or app.core.optimizer directly to set a number —
they only ever produce a strategy label + rationale + delivery-preference
signal, which is then handed to the deterministic
candidate_generator/policy_engine pipeline as ordinary BuyerIntent fields.
"""

from __future__ import annotations

from typing import Any, Dict

from app.llm.provider import LLMProvider, StrategyProposal


class BaseGrowthAgent:
    strategy_name = "NONE"

    def __init__(self, llm_provider: LLMProvider):
        self.llm_provider = llm_provider

    def is_relevant(self, context: Dict[str, Any]) -> bool:
        raise NotImplementedError

    def propose(self, buyer_text: str, context: Dict[str, Any]) -> StrategyProposal:
        """Delegates to the LLM provider. Raises LLMProviderError upward on
        failure — callers must not catch this and substitute a fabricated
        proposal (doc section 12)."""
        return self.llm_provider.propose_strategy(buyer_text, context)
