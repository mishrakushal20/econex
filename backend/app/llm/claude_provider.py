"""
Real Claude LLM provider, implemented with stdlib `urllib.request` instead
of the `anthropic` SDK package. WHY: this sandbox has no network access to
`pip install anthropic`, and the doc's own scope governance (section 32)
says "no technology added only for resume keywords" — the SDK is a thin
convenience wrapper around a plain HTTPS POST, so we call the REST API
directly. This also means the file has zero third-party dependencies.

SECURITY: no merchant private economics (cost, margin floor, incentive
budget, EOV, policy diagnostics) are ever placed in the prompt sent here —
callers (agents/*.py) are responsible for passing only buyer-safe context.
This module also does not import anything from app.core, structurally
preventing it from ever seeing that data by accident.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Dict

from app.config import Config
from app.llm.provider import LLMProvider, LLMProviderError, StrategyProposal

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"

SYSTEM_PROMPT = """You classify a buyer's negotiation message into exactly one \
growth strategy. Respond with ONLY a JSON object, no markdown fences, no \
preamble, matching this exact shape:
{"strategy": "CART_RECOVERY" | "RETENTION" | "DYNAMIC_DISCOUNT" | "NONE", \
"rationale": "<one sentence, no private merchant financial data>", \
"confidence": <float 0-1>, "requested_delivery_preference": <true|false>}
You are a language/strategy classifier only. You do not set prices, \
discounts, cashback amounts, or authorize any payment — those are handled \
by a separate deterministic system that will ignore any such fields."""


class ClaudeLLMProvider(LLMProvider):
    def __init__(self, api_key: str = None, model: str = None, timeout_seconds: float = 15.0):
        self.api_key = api_key or Config.ANTHROPIC_API_KEY
        self.model = model or Config.ANTHROPIC_MODEL
        self.timeout_seconds = timeout_seconds
        if not self.api_key:
            raise LLMProviderError("ANTHROPIC_API_KEY is not configured")

    def propose_strategy(self, buyer_text: str, context: Dict[str, Any]) -> StrategyProposal:
        user_message = (
            f"Buyer message: {buyer_text!r}\n"
            f"Safe context (no financial internals): {json.dumps(context)}"
        )
        body = json.dumps(
            {
                "model": self.model,
                "max_tokens": 300,
                "system": SYSTEM_PROMPT,
                "messages": [{"role": "user", "content": user_message}],
            }
        ).encode("utf-8")

        request = urllib.request.Request(
            ANTHROPIC_API_URL,
            data=body,
            method="POST",
            headers={
                "content-type": "application/json",
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
            },
        )

        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                response_body = json.loads(response.read().decode("utf-8"))
        except urllib.error.URLError as exc:
            raise LLMProviderError(f"Anthropic API request failed: {exc}") from exc
        except TimeoutError as exc:
            raise LLMProviderError(f"Anthropic API request timed out: {exc}") from exc

        return self._parse_response(response_body)

    @staticmethod
    def _parse_response(response_body: Dict[str, Any]) -> StrategyProposal:
        try:
            content_blocks = response_body["content"]
            text = "".join(
                block["text"] for block in content_blocks if block.get("type") == "text"
            )
        except (KeyError, TypeError) as exc:
            raise LLMProviderError(f"Unexpected Anthropic response shape: {response_body}") from exc

        text = text.strip()
        try:
            raw = json.loads(text)
        except json.JSONDecodeError as exc:
            raise LLMProviderError(f"Claude did not return valid JSON: {text!r}") from exc

        # StrategyProposal.from_raw does the actual schema validation, so
        # malformed/adversarial model output is caught in one place.
        return StrategyProposal.from_raw(raw)
