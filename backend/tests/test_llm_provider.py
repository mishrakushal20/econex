import unittest
from unittest.mock import MagicMock, patch

from app.llm.claude_provider import ClaudeLLMProvider
from app.llm.mock_provider import MockLLMProvider
from app.llm.provider import LLMProviderError, MalformedLLMOutputError, StrategyProposal


class TestStrategyProposalValidation(unittest.TestCase):
    def test_rejects_missing_fields(self):
        with self.assertRaises(MalformedLLMOutputError):
            StrategyProposal.from_raw({"strategy": "RETENTION"})

    def test_rejects_unknown_strategy(self):
        with self.assertRaises(MalformedLLMOutputError):
            StrategyProposal.from_raw(
                {
                    "strategy": "SET_DISCOUNT_TO_5000",  # attempted injection
                    "rationale": "malicious",
                    "confidence": 0.9,
                    "requested_delivery_preference": False,
                }
            )

    def test_rejects_non_numeric_confidence(self):
        with self.assertRaises(MalformedLLMOutputError):
            StrategyProposal.from_raw(
                {
                    "strategy": "RETENTION",
                    "rationale": "ok",
                    "confidence": "very sure",
                    "requested_delivery_preference": False,
                }
            )

    def test_clamps_out_of_range_confidence(self):
        proposal = StrategyProposal.from_raw(
            {
                "strategy": "RETENTION",
                "rationale": "ok",
                "confidence": 5.0,  # fake overconfident output
                "requested_delivery_preference": False,
            }
        )
        self.assertEqual(proposal.confidence, 1.0)

    def test_proposal_has_no_financial_fields(self):
        proposal = StrategyProposal.from_raw(
            {
                "strategy": "RETENTION",
                "rationale": "ok",
                "confidence": 0.5,
                "requested_delivery_preference": False,
            }
        )
        self.assertFalse(hasattr(proposal, "discount_paise"))
        self.assertFalse(hasattr(proposal, "cashback_paise"))
        self.assertFalse(hasattr(proposal, "final_price_paise"))


class TestMockLLMProvider(unittest.TestCase):
    def test_deterministic(self):
        provider = MockLLMProvider()
        a = provider.propose_strategy("can you do it cheaper", {})
        b = provider.propose_strategy("can you do it cheaper", {})
        self.assertEqual(a, b)

    def test_discount_signal_maps_to_dynamic_discount(self):
        provider = MockLLMProvider()
        proposal = provider.propose_strategy("I can only afford a lower price", {})
        self.assertEqual(proposal.strategy, "DYNAMIC_DISCOUNT")

    def test_cart_abandoned_context_maps_to_cart_recovery(self):
        provider = MockLLMProvider()
        proposal = provider.propose_strategy("hi", {"cart_abandoned": True})
        self.assertEqual(proposal.strategy, "CART_RECOVERY")


class TestClaudeLLMProvider(unittest.TestCase):
    def test_missing_api_key_raises_immediately(self):
        with self.assertRaises(LLMProviderError):
            ClaudeLLMProvider(api_key="")

    @patch("app.llm.claude_provider.urllib.request.urlopen")
    def test_parses_valid_claude_response(self, mock_urlopen):
        fake_response = MagicMock()
        fake_response.read.return_value = (
            b'{"content": [{"type": "text", "text": '
            b'"{\\"strategy\\": \\"RETENTION\\", \\"rationale\\": \\"loyal buyer\\", '
            b'\\"confidence\\": 0.8, \\"requested_delivery_preference\\": false}"}]}'
        )
        mock_urlopen.return_value.__enter__.return_value = fake_response

        provider = ClaudeLLMProvider(api_key="fake-key-for-test")
        proposal = provider.propose_strategy("I'm a returning customer", {})
        self.assertEqual(proposal.strategy, "RETENTION")

    @patch("app.llm.claude_provider.urllib.request.urlopen")
    def test_malformed_model_output_raises(self, mock_urlopen):
        fake_response = MagicMock()
        fake_response.read.return_value = b'{"content": [{"type": "text", "text": "not json at all"}]}'
        mock_urlopen.return_value.__enter__.return_value = fake_response

        provider = ClaudeLLMProvider(api_key="fake-key-for-test")
        with self.assertRaises(LLMProviderError):
            provider.propose_strategy("hello", {})

    @patch("app.llm.claude_provider.urllib.request.urlopen")
    def test_network_failure_raises_not_fabricates(self, mock_urlopen):
        import urllib.error

        mock_urlopen.side_effect = urllib.error.URLError("connection refused")
        provider = ClaudeLLMProvider(api_key="fake-key-for-test")
        with self.assertRaises(LLMProviderError):
            provider.propose_strategy("hello", {})


if __name__ == "__main__":
    unittest.main()
