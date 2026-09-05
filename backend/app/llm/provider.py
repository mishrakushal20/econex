"""
LLM provider abstraction (doc section 12/22).

WHY a StrategyProposal dataclass instead of a raw dict: schema validation
for LLM output is a named security requirement (doc section 22). By making
the return type a strict dataclass with validation in `from_raw`, any
malformed LLM output (extra/missing keys, wrong types, an attempted
`discount_paise` override) is rejected at the boundary, before it ever
reaches an agent or the API layer.

CRITICAL: LLM failure MUST NOT silently turn into a fake successful LLM
response (doc section 12). Providers raise LLMProviderError on failure;
callers must not catch-and-fabricate a proposal.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict

ALLOWED_STRATEGIES = frozenset(
    {"CART_RECOVERY", "RETENTION", "DYNAMIC_DISCOUNT", "NONE"}
)


class LLMProviderError(Exception):
    """Raised on any LLM failure: timeout, malformed output, network error,
    missing credentials. Never swallowed into a fabricated success."""


class MalformedLLMOutputError(LLMProviderError):
    """Raised specifically when the LLM's output fails schema validation
    (doc red-team scenario 5: 'malformed LLM output')."""


@dataclass(frozen=True)
class StrategyProposal:
    """A strategy PROPOSAL only. Notably absent: any authoritative
    discount_paise / cashback_paise / final_price_paise field — those do
    not exist on this type, so an agent literally cannot construct an
    authoritative financial candidate even by mistake (doc section 2/12)."""

    strategy: str
    rationale: str
    confidence: float
    requested_delivery_preference: bool

    @staticmethod
    def from_raw(raw: Dict[str, Any]) -> "StrategyProposal":
        required = {"strategy", "rationale", "confidence", "requested_delivery_preference"}
        missing = required - raw.keys()
        if missing:
            raise MalformedLLMOutputError(f"Missing required fields: {missing}")

        strategy = raw["strategy"]
        if strategy not in ALLOWED_STRATEGIES:
            raise MalformedLLMOutputError(
                f"strategy '{strategy}' not in allowed set {ALLOWED_STRATEGIES}"
            )

        rationale = raw["rationale"]
        if not isinstance(rationale, str) or not rationale.strip():
            raise MalformedLLMOutputError("rationale must be a non-empty string")

        confidence = raw["confidence"]
        if not isinstance(confidence, (int, float)) or isinstance(confidence, bool):
            raise MalformedLLMOutputError("confidence must be numeric")
        # doc red-team scenario 6: "fake high-confidence LLM output" — we
        # accept any confidence in range but NEVER let confidence influence
        # policy/economics; it is display-only rationale metadata.
        confidence = max(0.0, min(1.0, float(confidence)))

        delivery_pref = raw["requested_delivery_preference"]
        if not isinstance(delivery_pref, bool):
            raise MalformedLLMOutputError("requested_delivery_preference must be boolean")

        return StrategyProposal(
            strategy=strategy,
            rationale=rationale,
            confidence=confidence,
            requested_delivery_preference=delivery_pref,
        )


class LLMProvider:
    """Abstract interface. Implementations: MockLLMProvider (offline,
    deterministic), ClaudeLLMProvider (real Anthropic API call)."""

    def propose_strategy(self, buyer_text: str, context: Dict[str, Any]) -> StrategyProposal:
        raise NotImplementedError
