"""
Razorpay Adapter (doc section 13). Lives in app/core per the doc's own repo
layout — it legitimately needs network I/O, which the deterministic core's
"no LLM dependency" rule does not forbid (see docs/DECISIONS.md).

Modes (doc section 13, locked):
    REAL RAZORPAY TEST MODE   — when RAZORPAY_KEY_ID/SECRET are configured.
    EXPLICIT SIMULATION MODE  — when they are not. Always labelled
                                  "[SIMULATION]" in the returned PaymentResult
                                  and never presented as a real payment.

HARD RULE: a failed REAL Razorpay request must never silently fall back to
simulation — it returns status=FAILED with the real error, full stop. This
module implements the REST call directly with `urllib` (Basic Auth over
HTTPS, exactly what the `razorpay` SDK does under the hood) because this
sandbox cannot `pip install razorpay` (see top-level build report). In an
environment with network access, this can be swapped for the official SDK
without changing the PaymentResult contract.

Idempotency: `create_order` requires an explicit idempotency_key. The
in-memory/DB-backed idempotency check lives in the payments repository
(app/repositories/payments_repo.py) — this module is a pure adapter and
does not itself decide "have I seen this key before", it only executes.
"""

from __future__ import annotations

import base64
import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from app.config import Config

RAZORPAY_ORDERS_URL = "https://api.razorpay.com/v1/orders"


class PaymentStatus(str, Enum):
    CREATED = "created"
    CAPTURED = "captured"
    FAILED = "failed"
    DUPLICATE_BLOCKED = "duplicate_blocked"
    SIMULATED = "simulated"


@dataclass(frozen=True)
class PaymentResult:
    status: PaymentStatus
    mode: str  # "real_test_mode" | "simulation"
    amount_paise: int
    razorpay_order_id: Optional[str]
    failure_reason: Optional[str]
    label: str  # human-readable, always prefixed "[SIMULATION]" when simulated


def _simulate_order(amount_paise: int, receipt: str) -> PaymentResult:
    """Explicit simulation mode. Deterministic fake order id so demos are
    reproducible; NEVER claims to be a real Razorpay order."""
    fake_order_id = f"sim_order_{receipt}"
    return PaymentResult(
        status=PaymentStatus.SIMULATED,
        mode="simulation",
        amount_paise=amount_paise,
        razorpay_order_id=fake_order_id,
        failure_reason=None,
        label=f"[SIMULATION] Order simulated (no Razorpay credentials configured): {fake_order_id}",
    )


def _create_real_order(amount_paise: int, receipt: str) -> PaymentResult:
    auth = base64.b64encode(
        f"{Config.RAZORPAY_KEY_ID}:{Config.RAZORPAY_KEY_SECRET}".encode("utf-8")
    ).decode("ascii")
    body = json.dumps(
        {"amount": amount_paise, "currency": "INR", "receipt": receipt, "payment_capture": 1}
    ).encode("utf-8")
    request = urllib.request.Request(
        RAZORPAY_ORDERS_URL,
        data=body,
        method="POST",
        headers={"content-type": "application/json", "authorization": f"Basic {auth}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=15.0) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return PaymentResult(
            status=PaymentStatus.CREATED,
            mode="real_test_mode",
            amount_paise=amount_paise,
            razorpay_order_id=payload.get("id"),
            failure_reason=None,
            label=f"Razorpay Test Mode order created: {payload.get('id')}",
        )
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        # doc section 13: a failed real request MUST NOT silently become simulation.
        return PaymentResult(
            status=PaymentStatus.FAILED,
            mode="real_test_mode",
            amount_paise=amount_paise,
            razorpay_order_id=None,
            failure_reason=f"HTTP {exc.code}: {error_body}",
            label=f"Razorpay Test Mode order FAILED: HTTP {exc.code}",
        )
    except urllib.error.URLError as exc:
        return PaymentResult(
            status=PaymentStatus.FAILED,
            mode="real_test_mode",
            amount_paise=amount_paise,
            razorpay_order_id=None,
            failure_reason=str(exc),
            label=f"Razorpay Test Mode order FAILED: {exc}",
        )


def create_order(amount_paise: int, receipt: str) -> PaymentResult:
    """Entry point. Chooses real vs simulation mode based on whether
    credentials are configured — never on caller preference, so a demo
    cannot accidentally claim a fake order is real."""
    if amount_paise <= 0:
        raise ValueError("amount_paise must be positive")
    if Config.razorpay_configured():
        return _create_real_order(amount_paise, receipt)
    return _simulate_order(amount_paise, receipt)


def verify_webhook_signature(payload_body: bytes, signature: str) -> bool:
    """Verify a Razorpay webhook's HMAC-SHA256 signature against the
    configured webhook secret (doc section 13/22). Returns False (not an
    exception) for an unconfigured secret or a mismatch, so callers can
    uniformly log-and-reject rather than crash on unexpected webhook
    traffic in demo/simulation mode."""
    import hashlib
    import hmac

    if not Config.RAZORPAY_WEBHOOK_SECRET:
        return False
    expected = hmac.new(
        Config.RAZORPAY_WEBHOOK_SECRET.encode("utf-8"), payload_body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature or "")
