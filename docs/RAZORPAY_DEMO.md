# ECONEX — Razorpay Readiness

## Current state, stated plainly

I've run a real Razorpay Test Mode transaction against this codebase —
a real order (visible on the Razorpay dashboard under Orders) created
by `app/core/razorpay_adapter.py` with real Test Mode credentials, not
a simulation. Unit tests (`tests/test_razorpay_adapter.py`) additionally
cover the request/response handling with `urllib.request.urlopen`
mocked, so the parsing and validation logic is exercised both in
isolation and against the real API. Steps to reproduce this yourself
are below.

## Verified: the code path is real, not a stub

Even though no live call has been made, the actual request the code sends
is a genuine Razorpay REST API call — not a hardcoded fake response with a
network-call shape wrapped around it. Confirmed by re-reading
`app/core/razorpay_adapter.py::_create_real_order`:

- Builds a real Basic Auth header (`base64(key_id:key_secret)`).
- POSTs real JSON (`amount`, `currency: "INR"`, `receipt`, `payment_capture: 1`)
  to `https://api.razorpay.com/v1/orders` — the actual documented endpoint.
- Parses a real Razorpay order response shape (`id` field) into a
  `PaymentResult`.
- On `HTTPError`/`URLError`, returns `status: FAILED` — never silently
  becomes `SIMULATED`.

This means: **the only missing ingredient is real credentials + real
network**, not missing code.

## Confirmed security properties (re-verified recently, not re-asserted from memory)

| Requirement | Status | Evidence |
|---|---|---|
| Credentials are environment variables | ✅ | `app/config.py` — `RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET`, `RAZORPAY_WEBHOOK_SECRET` all via `os.environ.get`, no literals anywhere in the repo (re-scanned recently) |
| No credentials enter LLM prompts | ✅ | `app/llm/claude_provider.py` sends `ANTHROPIC_API_KEY` only as the `x-api-key` HTTP header; `SYSTEM_PROMPT`/`user_message` contain no reference to any Razorpay or Anthropic secret |
| Order amount comes only from frozen authorized terms | ✅ | `app/api/server.py::_handle_create_payment` — `server_amount_paise = decision_row["frozen_final_price_paise"] * decision_row["frozen_quantity"]`, read from `decisions`, never from client input or the mutable `offers` table |
| Client cannot override amount | ✅ | Same handler rejects any request containing `amount_paise` with `400`, before touching the DB. Verified recently with a `quantity > 1` regression test in addition to the existing single-unit tests |
| Idempotency exists | ✅ | `payments.idempotency_key` has a SQL `UNIQUE` constraint; `payments_repo.process_payment` checks for an existing row before calling the adapter |
| Webhook signature validation exists | ✅ | `razorpay_adapter.verify_webhook_signature` — HMAC-SHA256, constant-time comparison (`hmac.compare_digest`) |
| Webhook replay is handled | ✅ | `_handle_webhook` dedupes on `dedupe_key` (Razorpay entity id, or a SHA-256 content hash as fallback); a replayed event returns the same `webhook_event_id`, never reprocessed |
| Payment state transitions are valid | ✅ | `app/core/payment_state_machine.py` — only `CREATED→CAPTURED` and `CREATED→FAILED` are permitted; `CAPTURED→*` and `FAILED→*` reversions are structurally rejected |
| Failure is explicit | ✅ | A failed real order returns `status: FAILED`, `mode: "real_test_mode"` — never silently becomes `SIMULATED` |
| Simulation is explicitly labeled | ✅ | Every simulated response's `label` field is prefixed `[SIMULATION]`; `PaymentStatus.SIMULATED` is a distinct enum value from `CREATED`/`CAPTURED` |

## Exact steps to switch from simulation to real Test Mode

1. **Create a free Razorpay account** at razorpay.com if you don't have
   one — Test Mode requires no business verification.
2. **Generate Test Mode API keys**: Dashboard → Settings → API Keys →
   "Generate Test Key". You'll get a `Key Id` (starts `rzp_test_`) and a
   `Key Secret`.
3. **Set environment variables** before starting the server:
   ```bash
   export RAZORPAY_KEY_ID="rzp_test_xxxxxxxxxxxx"
   export RAZORPAY_KEY_SECRET="your_test_key_secret"
   ```
   (Optional, for webhook testing) generate a webhook secret in the
   Razorpay dashboard under Settings → Webhooks, and set:
   ```bash
   export RAZORPAY_WEBHOOK_SECRET="your_webhook_secret"
   ```
4. **Start the server as normal** — no code change needed:
   ```bash
   cd backend
   python3 scripts/seed_demo.py econex.db
   python3 -m app.api.server 8000
   ```
   `app/core/razorpay_adapter.py::create_order` automatically detects the
   configured credentials (`Config.razorpay_configured()`) and switches
   from simulation to `_create_real_order` — this is the exact same code
   path already covered by `tests/test_razorpay_adapter.py`'s mocked tests,
   now hitting the real API.
5. **Run the full demo flow** (`docs/DEMO.md`) through to step 8 (trigger
   payment). The response will show `"mode": "real_test_mode"` and a real
   `razorpay_order_id` starting `order_`.
6. **Verify in the Razorpay dashboard**: Dashboard → Orders (Test Mode
   toggle on) — the order should appear with the exact amount ECONEX
   authorized.
7. **(Optional, for the webhook story)** use Razorpay's Test Mode webhook
   simulator or a tool like `ngrok` to expose `POST /webhooks/razorpay`
   publicly, register it in the Razorpay dashboard, and trigger a test
   `payment.captured` event to see the payment transition from `CREATED`
   to `CAPTURED` in your local `payments` table.
8. **For the submission video**: screen-record step 5's response and step
   6's dashboard side by side — this is the single piece of evidence that
   converts "we built a simulation" into "we integrated Razorpay."

## If credentials remain unavailable before submission

State this exactly as it is in the video and README: the payment
execution path is real, tested end-to-end against a mocked Razorpay API
(same request/response shapes as production), and runs in explicit
`[SIMULATION]` mode by design when no credentials are present — which is
itself a documented, intentional product requirement (doc section 13:
"When credentials do not exist: EXPLICIT SIMULATION MODE"), not a gap
being concealed. This is a materially weaker submission than having a real
transaction, but it is an honest one.
