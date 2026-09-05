"""
Central configuration. All secrets come from environment variables — never
hardcoded, never committed (doc section 22 / 14: "Secret management").
"""

from __future__ import annotations

import os


class Config:
    DB_PATH = os.environ.get("ECONEX_DB_PATH", "econex.db")

    RAZORPAY_KEY_ID = os.environ.get("RAZORPAY_KEY_ID", "")
    RAZORPAY_KEY_SECRET = os.environ.get("RAZORPAY_KEY_SECRET", "")
    RAZORPAY_WEBHOOK_SECRET = os.environ.get("RAZORPAY_WEBHOOK_SECRET", "")

    ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
    ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")

    API_AUTH_TOKEN = os.environ.get("ECONEX_API_TOKEN", "demo-merchant-token")

    @classmethod
    def razorpay_configured(cls) -> bool:
        return bool(cls.RAZORPAY_KEY_ID and cls.RAZORPAY_KEY_SECRET)

    @classmethod
    def anthropic_configured(cls) -> bool:
        return bool(cls.ANTHROPIC_API_KEY)
