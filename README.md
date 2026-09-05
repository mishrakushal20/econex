# ECONEX — Economic Control Plane for Agentic Commerce

Built for the Razorpay AI Buildathon 2026 (AI Growth & Agentic Commerce track).

Standalone submission artifacts: [`docs/OBJECTIVES.md`](docs/OBJECTIVES.md) ·
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) ·
[`docs/DEMO.md`](docs/DEMO.md) ·
[`docs/SUBMISSION_CHECKLIST.md`](docs/SUBMISSION_CHECKLIST.md)

## The problem

AI agents can now negotiate, discount, and check out on a merchant's behalf.
Being *capable* of granting a discount or cashback is not the same as that
concession being *worthwhile*. Left ungoverned, an agent optimizing for
"close the sale" will happily give away margin the merchant can't afford.

## The thesis

**AUTHORIZED ≠ OPTIMAL.**

ECONEX sits between AI-generated commercial intent and financial execution.
An LLM may understand what a buyer wants and propose a growth strategy. It
never sets a price, a discount, a cashback amount, or authorizes a payment.
A deterministic core does that — and it can prove, candidate by candidate,
exactly why it said yes or no.

## Architecture

```
Buyer message
     │
     ▼
 LLM strategy classifier  (app/llm, app/agents)  ── proposes a label only
     │
     ▼
 Candidate Generator  (app/core/candidate_generator.py)
     │   deterministic bounded price/cashback/delivery grid
     ▼
 Policy Engine  (app/core/policy_engine.py)
     │   9 ordered financial safety checks — the hard boundary
     ▼
 Economic Engine  (app/core/economic_engine.py)
     │   P_conv × contribution − cashback = EOV, feasible candidates only
     ▼
 Optimizer / Selector  (app/core/optimizer.py)
     │   deterministic ranking, no LLM input
     ▼
 Decision Resolver + State Machine  (app/core/decision_resolver.py, state_machine.py)
     │   ACCEPT / COUNTER / REJECT / ESCALATE
     ▼
 Razorpay Adapter  (app/core/razorpay_adapter.py)
     │   real Test Mode order, or explicit [SIMULATION]
     ▼
 Audit Trail + Outcome Recording  (app/audit.py, repositories/)
```
![architecture diagram](architecture.jpeg)

**Why the LLM is never the financial authority**: `app/core/` has zero
imports from `app.llm` or `app.agents` — this is not just a design
statement, it's enforced by `tests/test_architecture_boundary.py`, which
parses every core module's AST and fails the build if that boundary is
ever violated. The LLM's only output type, `StrategyProposal`
(`app/llm/provider.py`), has no `discount_paise`, `cashback_paise`, or
`final_price_paise` field — it is structurally impossible for an agent to
construct an authoritative financial candidate.

Full detail: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## The economic formula

```
ExpectedContribution = (finalPrice − cost − deliveryCost) × quantity
EOV = P_conv × ExpectedContribution − cashback
Incentive budget consumption = discount + cashback   (a separate, larger number)
```

Full detail, including a documented contradiction between an earlier draft
of the budget rule and the final locked version, and its exact effect on
the worked example: [`docs/ECONOMIC_MODEL.md`](docs/ECONOMIC_MODEL.md) and
[`docs/DECISIONS.md`](docs/DECISIONS.md).

## Tech stack — and why it's stdlib-only

This entire backend is built on the **Python standard library only**
(`sqlite3`, `http.server`, `urllib`, `unittest`) and the frontend is
**vanilla HTML/JS/CSS** — no FastAPI, SQLAlchemy, `razorpay` SDK, React, or
`npm`/`pip` third-party packages. This was a deliberate choice; see
`docs/DECISIONS.md` for the full reasoning. The main benefit:
`git clone` + `python3` is the entire setup story,
with zero dependency-version risk for judges running this after the fact.

If you have network access, swapping in FastAPI/SQLAlchemy/the `razorpay`
SDK is a mechanical refactor — the module boundaries (`app/core`,
`app/api`, `app/repositories`) are already SDK-shaped.

## Setup

```bash
cd backend
python3 --version   # 3.9+ recommended, tested on 3.12
python3 scripts/seed_demo.py econex.db     # reset/seed the demo merchant + product + policy
python3 -m app.api.server 8000             # start the API on http://127.0.0.1:8000
```

Then open `frontend/index.html` directly in a browser (no build step) and
point it at `http://127.0.0.1:8000` with token `demo-merchant-token`
(both are pre-filled defaults).

## Environment variables

| Variable | Purpose | Default |
|---|---|---|
| `ECONEX_DB_PATH` | SQLite file path | `econex.db` |
| `ECONEX_API_TOKEN` | (unused directly — tokens are per-merchant, seeded via `scripts/seed_demo.py`) | `demo-merchant-token` |
| `RAZORPAY_KEY_ID` / `RAZORPAY_KEY_SECRET` | Razorpay Test Mode credentials | unset → simulation mode |
| `RAZORPAY_WEBHOOK_SECRET` | HMAC secret for webhook signature verification | unset → all webhooks rejected |
| `ANTHROPIC_API_KEY` | Enables the real Claude strategy classifier | unset → uses the deterministic mock provider |
| `ANTHROPIC_MODEL` | Claude model string | `claude-sonnet-4-6` |

**No secrets are committed.** `.env.example` (not present, since there is
nothing to template beyond the table above) — just export these in your
shell before running the server.

## Razorpay Test Mode vs. Simulation Mode

If `RAZORPAY_KEY_ID`/`RAZORPAY_KEY_SECRET` are set, `POST /payments/order`
calls Razorpay's real `/v1/orders` REST endpoint (Test Mode) via
`urllib` — no SDK dependency needed, it's a plain HTTPS POST with Basic
Auth, same as the SDK does internally. If they are unset, every order is
created in **explicit simulation mode**, always labelled `[SIMULATION]` in
the response and never presented as a real Razorpay object. A failed real
request returns `status: "failed"` — it never silently becomes a
simulated success.

## Tests

```bash
cd backend
python3 -m unittest discover -s tests -v
```

132 tests, 0 third-party dependencies required to run them. Covers money
arithmetic, the conversion heuristic, candidate generation, all 9 policy
boundaries, the economic formula, ranking, the decision state machine,
authorization, idempotency, payment failure, the buyer/merchant privacy
boundary, the architecture boundary (no LLM in core), benchmark
reproducibility, the full red-team suite, and — added in the security
hardening pass — payment-amount tampering, webhook forgery/replay, and
cross-merchant isolation, each exercised against a real running server and
a real SQLite DB (`tests/test_upgrade_hardening.py`).

## Benchmark

```bash
cd backend
python3 -m app.benchmark
```

SYNTHETIC / SEEDED (42) / REPRODUCIBLE. Compares Baseline A (full price),
Baseline B (naive generous buyer-ask), Baseline C (a plausible simple
deterministic rule engine), and ECONEX. ECONEX beats the best of the three
baselines by a dynamically-computed contribution improvement — not
hardcoded. Full writeup and honest numbers (not cherry-picked):
[`docs/BENCHMARK.md`](docs/BENCHMARK.md).

## Red-team suite

```bash
cd backend
python3 -m app.redteam
```

12 adversarial scenarios (doc section 19), expanded to **17** in the
security-hardening pass to cover the payment/webhook attack surface (see
`docs/TESTING_AND_CHANGES.md` and `docs/SECURITY.md`). All 17 blocked by the
deterministic boundary — no LLM guardrail involved.

## Demo

5-minute deterministic demo script, reset flow, and exact API calls:
[`docs/DEMO.md`](docs/DEMO.md).

## Security hardening pass

A follow-up audit (`docs/TESTING_AND_CHANGES.md`) found and fixed two real,
confirmed bugs beyond the original MVP: client-trusted payment amounts and
missing merchant scoping on several lookups. Full detail:
[`docs/SECURITY.md`](docs/SECURITY.md). Every fix has a live regression
test in `backend/tests/test_upgrade_hardening.py` that spins up a real
server and actually attempts the attack, rather than asserting behavior in
the abstract.

## Limitations

- Conversion probability is a synthetic, deterministic heuristic — not a
  trained model, never claimed as one.
- Single-process SQLite; fine for a hackathon demo, not a production
  concurrency story.
- The HTTP API is a minimal `http.server`-based JSON API, not a
  production-grade framework — no rate limiting, no OpenAPI schema.
- Quantity-grid exploration is not implemented; candidates use the buyer's
  requested quantity as-is (see `docs/DECISIONS.md`).
- The real Claude LLM provider is implemented and unit-tested with
  mocked HTTP responses, but I haven't yet made a live call against the
  Anthropic API from this repo — it isn't on the financial path either
  way (see `docs/SECURITY.md`). The real Razorpay integration, by
  contrast, has been verified against a live Test Mode order (see
  `docs/RAZORPAY_DEMO.md`).

## Future work

- Swap the stdlib HTTP layer for FastAPI + Pydantic for OpenAPI docs
  and stricter request validation.
- Multi-round negotiation loop wired fully into the API (the state machine
  and `round_number` plumbing already support it; the API's `/buyer-intents`
  endpoint currently always starts a fresh round-1 session).
- Real outcome-driven calibration of the conversion heuristic's
  coefficients against actual observed conversion data.
