# ECONEX — Testing notes & what I fixed along the way

This documents what I actually tested, what I found broken while
hardening the project, and what's still a known limitation. Everything
below reflects commands I ran myself, not assumptions.

## Bugs I found and fixed during development

**1. Client-supplied payment amount.** Early on, `POST /payments/order`
accepted `amount_paise` directly from the request body and trusted it.
That meant a client could authorize a ₹8,000 negotiation and then pay
₹1 for it. I fixed this by making the server derive the amount itself
from a frozen snapshot on the `decisions` row (`final_price_paise ×
quantity`, captured at authorization time) and rejecting any request
that even includes `amount_paise` at all, with a `400`. Covered by
`tests/test_upgrade_hardening.py::TestPaymentAuthorizationHardening`,
which fires the exact ₹1 / ₹100 / ₹6,800 / ₹99,999 attack amounts
against a decision authorized at ₹8,000 and confirms all four are
rejected.

**2. Missing merchant scoping.** `decisions`, `payments`, and
`audit_events` didn't store `merchant_id`, and the lookup functions had
no ownership filter — any authenticated merchant could read another
merchant's decision, audit trail, or ledger by guessing an ID. I added
`merchant_id` to all three tables and scoped every lookup
(`get_decision_scoped`, `timeline_for_session(..., merchant_id)`, plus a
filter on the ledger endpoint). Covered by
`tests/test_upgrade_hardening.py::TestMerchantIsolation`.

**3. Webhook handler didn't transition payment state.** It verified
the signature and logged the event, but never actually updated a
payment's status, and there was no payment state machine at all. I
added `app/core/payment_state_machine.py` (mirroring the existing
negotiation state machine) and wired the webhook handler to it, gated
on signature verification and idempotent by dedupe key. Covered by
`tests/test_upgrade_hardening.py::TestWebhookSecurityHardening`.

**4. LLM provider mode was an implicit hardcoded default**, with no
config-driven switch between the mock and a real Claude call, and no
mode label surfaced anywhere. I made the selection explicit
(`_select_llm_provider()`, driven by whether `ANTHROPIC_API_KEY` is
set) and made sure the active mode is recorded in the audit trail.

**5. Quantity > 1 was never tested on the payment path.** The
server-derived amount formula is `final_price_paise × quantity`, but
every existing test used `quantity=1`, which would have silently
masked a per-unit-vs-total bug. I added
`test_payment_amount_scales_with_quantity_greater_than_one` to close
that gap.

**6. Two stale numbers in the docs.** `docs/ARCHITECTURE.md` said the
red-team suite had 12 scenarios and the database had 11 tables; the
actual counts (verified by `len(app.redteam.ALL_SCENARIOS)` and
counting `CREATE TABLE` statements) are 17 and 12. Fixed in the docs
and in the frontend copy, which had the same stale "12 scenarios" line.

## What I verified live before submitting

```
cd backend && python3 -m unittest discover -s tests -v
```
**Ran 133 tests — OK** (0 failures, 0 errors).

```
python3 -m app.benchmark
```
500 seeded scenarios, labelled `SYNTHETIC BENCHMARK — SEEDED,
REPRODUCIBLE, NOT REAL TRANSACTION DATA`:

| | Baseline A | Baseline B | Baseline C | ECONEX |
|---|---:|---:|---:|---:|
| Contribution | ₹3,79,500 | ₹5,04,898 | ₹3,86,896 | ₹6,15,651 |
| Contribution/incentive ₹ | ∞ | 0.74 | **4.51** | 4.29 |
| Policy violations | 0 | 419 | 0 | **0** |

I'm reporting the incentive-efficiency number honestly even though
Baseline C beats ECONEX on that one metric — it's a real trade-off,
not something I wanted to hide.

```
python3 -m app.redteam
```
**All 17 adversarial scenarios blocked.**

```
python3 -m unittest tests.test_architecture_boundary -v
```
**2/2 passing** — confirms `app/core/` has zero imports of `app.llm`,
`app.agents`, `anthropic`, or `openai`, checked by parsing the AST of
every file in that directory, not just by inspection.

A real Razorpay Test Mode order (see `docs/RAZORPAY_DEMO.md`) and a
live end-to-end negotiation through the frontend were both run
manually and confirmed working.

## Honesty note on "type checking"

I don't have `mypy` (or any type checker) installed. "Typecheck" in
this project has always meant the AST-import-boundary check described
above, not real static type analysis — stated plainly here rather than
implied.

## Known MVP limitations

- The API auth token is a static bearer token per merchant, not
  OAuth/JWT/rotating credentials — fine for a hackathon MVP, not for
  production.
- No rate limiting on the HTTP API.
- SQLite has no row-level access control of its own; isolation is
  enforced entirely in the application layer.
- `Config.API_AUTH_TOKEN` is defined but unused — actual merchant auth
  uses per-merchant tokens seeded by `scripts/seed_demo.py`. Harmless,
  left as-is rather than risk touching auth this close to submission.
- The full 10,000-scenario / 5-buyer-segment benchmark matrix described
  as a stretch goal wasn't built — I ran a smaller but real 500-scenario
  benchmark instead and documented the reduction rather than skipping
  it silently.
- A policy simulator UI (re-run the pipeline against a hypothetically
  modified policy) isn't built, though the underlying pure function
  already supports it — a frontend-only addition for later.
