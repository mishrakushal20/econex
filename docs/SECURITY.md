# ECONEX — Security

While hardening this project I found two real, confirmed bugs —
client-trusted payment amounts and missing merchant scoping on several
lookups (full list in `docs/TESTING_AND_CHANGES.md`). Both are fixed
below, with live regression tests proving the fix
(`tests/test_upgrade_hardening.py`), not just described.

## Payment amount is server-derived, never client-supplied

`POST /payments/order` accepts only `decision_id` and `idempotency_key`.
If a request body contains `amount_paise` at all, it is rejected outright
with `400` — never silently ignored, never used. The server:

1. looks up the decision **scoped to the authenticated merchant**
   (`negotiation_repo.get_decision_scoped`),
2. verifies the decision is in a payment-eligible state
   (`CLOSED_ACCEPTED` or `AWAITING_BUYER_RESPONSE`),
3. verifies the frozen offer hasn't expired (`expires_at`, 15-minute
   default from authorization),
4. computes `amount = frozen_final_price_paise × frozen_quantity` from
   columns written once, at authorization time, on the `decisions` row
   itself — never re-read from the mutable `offers` table.

Verified live: `tests/test_upgrade_hardening.py::TestPaymentAuthorizationHardening`
sends the exact ₹1/₹100/₹6,800/₹99,999 attack amounts from the spec against
a decision authorized at ₹8,000 — all four rejected with `400`, and a
follow-up test confirms the actual stored payment amount in the database
matches the authorized offer exactly.

## Frozen commercial terms

`app/redteam.py::scenario_candidate_mutation_after_authorization`
demonstrates that even a hypothetical tampering of the `offers` table
after authorization cannot change what a buyer is charged, because the
payment path never reads that table — it reads the frozen columns on
`decisions` instead.

## Payment state machine

`app/core/payment_state_machine.py` mirrors the negotiation state
machine's pattern: an explicit `frozenset` of allowed `(from, to)` pairs.

```
CREATED -> CAPTURED
CREATED -> FAILED
```

`CAPTURED -> CREATED`, `CAPTURED -> FAILED`, `FAILED -> CAPTURED`,
`FAILED -> CREATED` are all absent from the set and therefore rejected by
`transition_payment()`. `SIMULATED` and `DUPLICATE_BLOCKED` are terminal
initial states, never transitioned into or out of.

## Webhook security

`_handle_webhook` (`app/api/server.py`):

- **Invalid/missing signature → `401`, no payment state transition, still
  logged** with `signature_valid=0`. Never treated as legitimate.
- **Valid signature → may transition** the matching payment (looked up by
  `razorpay_order_id`) via `payments_repo.transition_payment_status`,
  which itself enforces the state machine above — a forged `payment.captured`
  event for an already-`FAILED` payment is rejected by the transition
  table even if the signature were somehow valid.
- **Idempotent.** Every webhook event is deduped by a `dedupe_key`
  (Razorpay's own entity id when present, else a SHA-256 hash of the raw
  body). A replayed event returns the same `webhook_event_id` and is never
  reprocessed.
- **Modified payload with a stale signature is rejected** — the signature
  is computed over the exact bytes received, so re-signing isn't possible
  without the secret, and reusing an old signature against new bytes fails
  verification.

Verified live: `tests/test_upgrade_hardening.py::TestWebhookSecurityHardening`
— valid signature, invalid signature, missing signature, replayed event,
and modified-payload-with-stale-signature are each exercised against a
real running server.

## Merchant-scoped authorization

Every merchant-facing endpoint requires `Authorization: Bearer <token>`.
`app/api/server.py::_authenticate()` resolves the token to a `merchant_id`
**server-side** — a request body can never say "act as merchant X".

**Fixed recently:** `decisions`, `payments`, and `audit_events` did not
store `merchant_id` before the upgrade, and their lookup functions
(`get_decision`, `timeline_for_session`) had no ownership filter at all —
any authenticated merchant could read any other merchant's decision, audit
trail, or candidate ledger by guessing an ID. All three tables now carry
`merchant_id`, and every API handler uses the scoped variant
(`get_decision_scoped`, `timeline_for_session(..., merchant_id)`, plus an
explicit `merchant_id` filter on the ledger's session lookup). A
cross-tenant request returns `404` (or an empty list for audit), not `403`
— this deliberately avoids leaking *existence* of another merchant's
resource via a 403-vs-404 oracle.

Verified live: `tests/test_upgrade_hardening.py::TestMerchantIsolation` —
Merchant B is confirmed unable to read Merchant A's audit trail, ledger,
pay for Merchant A's decision, or approve Merchant A's decision.

## No LLM in the financial authority path

Structurally enforced, not just documented:
`tests/test_architecture_boundary.py` parses the AST of every file in
`app/core/` and fails if any imports `app.llm`, `app.agents`, `anthropic`,
or `openai`.

## LLM provider mode is explicit, never a silent fallback

`app/api/server.py::_select_llm_provider()` chooses `ClaudeLLMProvider`
only when `ANTHROPIC_API_KEY` is actually configured; otherwise
`MockLLMProvider` (labelled DEMO / SYNTHETIC PROVIDER) is used. This
selection happens once at server startup — there is no code path that
switches modes mid-request. If a configured real provider then fails at
call time (network error, malformed response), `LLMProviderError`
propagates to `negotiation_service.handle_buyer_intent`, which records the
failure (including which mode was in use) to the audit trail and continues
the deterministic pipeline with `strategy="NONE"` — never a fabricated
proposal, and never anything that could change the financial outcome,
since strategy is advisory-only input to begin with.

## Buyer/merchant data boundary

`app/schemas/serializers.py::buyer_view_offer()` is an explicit allowlist.
Private fields — `cost`, `margin_floor`, `incentive_budget`,
`contribution`, `EOV`, internal `P_conv`, policy diagnostics — are never
copied into a buyer-facing payload, because the function doesn't iterate
over an object's fields at all; it names each field it's allowed to
expose. `assert_no_private_leak()` runs as a second gate right before the
API sends a buyer response.

## Schema validation on LLM output

`app/llm/provider.py::StrategyProposal.from_raw()` rejects: missing
fields, an out-of-allowlist `strategy` value (blocks prompt-injection-style
attempts to smuggle e.g. `"strategy": "GRANT_FULL_REFUND"`), non-string
`rationale`, non-numeric `confidence`, non-boolean
`requested_delivery_preference`. Out-of-range `confidence` is clamped, not
rejected — but `confidence` is display-only metadata; it never influences
policy or economics. Critically, `StrategyProposal` **has no financial
fields at all** — `discount_paise`, `cashback_paise`, `final_price_paise`
don't exist on the type, so no amount of "confident" LLM output can ever
become an authoritative number.

## Idempotency

`payments.idempotency_key` has a `UNIQUE` SQL constraint.
`repositories/payments_repo.py::process_payment()` is the single correct
entry point: it checks for an existing row before ever calling the
Razorpay adapter, so a retried/duplicated request is detected and reported
as `duplicate_blocked` without re-executing the payment.

## Negotiation state machine

`app/core/state_machine.py`'s `_ALLOWED_TRANSITIONS` is an explicit
frozenset. There is no `PENDING_APPROVAL -> CLOSED_ACCEPTED` transition —
approval must pass through `APPROVED`. Any other transition raises
`InvalidTransitionError`. This makes "skip the approval gate" structurally
impossible, not just policy-discouraged, and also makes "repeated
authorization" (calling approve/deny twice) fail on the second call, since
the decision is no longer in `PENDING_APPROVAL`.

## Secrets

All secrets (`RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET`,
`RAZORPAY_WEBHOOK_SECRET`, `ANTHROPIC_API_KEY`) come from environment
variables (`app/config.py`) — never hardcoded, never logged, never placed
in an LLM prompt (`app/llm/claude_provider.py`'s prompt only ever includes
buyer text and an explicitly-constructed "safe context" dict — it has no
reference to `app.core` at all, so it structurally cannot see private
economics even if a caller made a mistake upstream). Re-scanned recently
(regex sweep for API-key-shaped strings, private-key headers) — none
found. `.env.example` added with variable names only, no real values.

## Webhook signature verification

`app/core/razorpay_adapter.py::verify_webhook_signature()` does HMAC-SHA256
verification with `hmac.compare_digest` (constant-time comparison, avoids
timing attacks). An unconfigured secret rejects everything rather than
accepting unsigned traffic.

## Razorpay failure handling

A failed real Razorpay request returns `status: FAILED` with the mode
still `real_test_mode` — it never silently falls back to
`SIMULATED`, so a payment failure can never be misreported as a
successful (fake) payment (doc section 13; verified by
`app/redteam.py::scenario_razorpay_failure`).

## Red-team suite (17 scenarios)

`app/redteam.py` runs 17 adversarial scenarios end-to-end against the real
modules (not mocked-out stand-ins): unauthorized cashback, excessive
discount, below-cost offer, below-margin offer, exhausted budget,
malformed LLM output, fake high-confidence LLM output, expired offer,
duplicate payment, client-modified payment amount, Razorpay failure,
forged webhook signature, attempted policy bypass, stale authorization,
malicious strategy proposal, invalid merchant scope, and candidate
mutation after authorization. All 17 are blocked, verified in
`tests/test_redteam.py` and (for the payment/webhook/isolation ones) again
at the live-server level in `tests/test_upgrade_hardening.py`.

## Known MVP limitations

- The API auth token is a static bearer token per merchant, not
  OAuth/JWT/rotating credentials — acceptable for a hackathon MVP, not for
  production.
- No rate limiting on the HTTP API.
- SQLite has no row-level access control of its own; all isolation is
  enforced in the application layer (`_authenticate` + scoped queries).
- LLM provider mode is fixed at server startup, not re-checked per request
  (see `docs/DECISIONS.md` "Upgrade pass" section for the trade-off).
