"""
Deterministic mock LLM provider. Used for offline testing and as the
default in this sandbox (no network access to call a real LLM API — see
docs/DECISIONS.md). It uses simple keyword heuristics, not a model, and is
clearly labelled as such everywhere it is referenced.
"""

from __future__ import annotations

from typing import Any, Dict

from app.llm.provider import LLMProvider, StrategyProposal


class MockLLMProvider(LLMProvider):
    """NOT an ML model. Deterministic keyword rules only, so tests and demos
    are 100% reproducible without network access."""

    def propose_strategy(self, buyer_text: str, context: Dict[str, Any]) -> StrategyProposal:
        text = (buyer_text or "").lower()

        if context.get("cart_abandoned"):
            strategy = "CART_RECOVERY"
            rationale = "Buyer has an abandoned cart; recovery incentive is contextually relevant."
        elif context.get("is_repeat_customer") or "again" in text or "loyal" in text:
            strategy = "RETENTION"
            rationale = "Buyer has prior purchase history; retention framing is contextually relevant."
        elif any(word in text for word in ("cheaper", "discount", "lower", "pay", "budget", "afford")):
            strategy = "DYNAMIC_DISCOUNT"
            rationale = "Buyer language signals price sensitivity; margin-aware discount strategy fits."
        else:
            strategy = "NONE"
            rationale = "No clear growth strategy signal in buyer message."

        wants_expedited = any(word in text for word in ("tomorrow", "urgent", "asap", "fast", "expedite"))

        raw = {
            "strategy": strategy,
            "rationale": rationale,
            "confidence": 0.75,
            "requested_delivery_preference": wants_expedited,
        }
        return StrategyProposal.from_raw(raw)
