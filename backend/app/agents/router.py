"""
Agent router (doc section 12, Table 2). Selects the contextually relevant
agent(s) and delegates to the LLM provider for a StrategyProposal. This is
the ONLY place that decides which agent's context is "relevant"; it is a
deterministic, rule-based router (not an LLM call itself) — the LLM is
called once, inside `agent.propose(...)`, by whichever agent is selected.

WHY this file has no fallback-to-fake-success path: doc section 12 —
"LLM failure MUST NOT silently turn into a fake successful LLM response."
`route_and_propose` re-raises LLMProviderError; callers (the API layer)
must handle it explicitly (e.g. falling back to NONE strategy with a
clearly-labeled "LLM unavailable" reason — never a fabricated proposal).
"""

from __future__ import annotations

from typing import Any, Dict, Tuple

from app.agents.cart_recovery_agent import CartRecoveryAgent
from app.agents.dynamic_discount_agent import DynamicDiscountAgent
from app.agents.retention_agent import RetentionAgent
from app.llm.provider import LLMProvider, StrategyProposal


def build_agents(llm_provider: LLMProvider):
    return [
        CartRecoveryAgent(llm_provider),
        RetentionAgent(llm_provider),
        DynamicDiscountAgent(llm_provider),
    ]


def route_and_propose(
    buyer_text: str, context: Dict[str, Any], llm_provider: LLMProvider
) -> Tuple[str, StrategyProposal]:
    """Pick the first relevant agent (deterministic order: CartRecovery,
    Retention, DynamicDiscount) and get its strategy proposal. If none are
    contextually relevant, we still classify via the LLM (it may return
    NONE), because buyer language alone (e.g. "cheaper please") can signal
    a strategy even without special context flags.

    Returns (selected_agent_name, proposal). Raises LLMProviderError on
    failure — never fabricates a proposal.
    """
    agents = build_agents(llm_provider)
    selected_agent = next((a for a in agents if a.is_relevant(context)), agents[-1])
    proposal = selected_agent.propose(buyer_text, context)
    return selected_agent.strategy_name, proposal
