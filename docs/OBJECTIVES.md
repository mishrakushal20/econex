# ECONEX — Objectives

## Problem

AI agents can now negotiate, discount, and check out on a merchant's
behalf. Being *capable* of granting a discount or cashback is not the same
as that concession being *worthwhile*. Left ungoverned, an agent
optimizing purely for "close the sale" will happily give away margin the
merchant can't afford — there is currently no standard layer that stops
this.

## Core thesis

**AUTHORIZED ≠ OPTIMAL.** An action an AI agent is technically allowed to
take is not automatically the economically correct one. ECONEX is the
control plane that sits between AI-generated commercial intent and actual
financial execution.

## Objectives

1. **Prove the architectural separation is real, not aspirational.** The
   LLM/agent layer proposes strategy; a deterministic core with zero LLM
   dependency evaluates, ranks, and authorizes. This is structurally
   enforced (an automated test parses the codebase and fails the build if
   the boundary is ever crossed), not just described in a diagram.

2. **Make the decision explainable, not a black box.** Every buyer
   negotiation produces a full counterfactual ledger — every candidate
   price/incentive combination the system considered, which ones were
   blocked and why, and which one won and why — reconstructable from an
   immutable audit trail.

3. **Enforce real financial safety boundaries**, not just a demo-time
   guardrail: margin floor, discount/cashback caps, incentive budget
   exhaustion, inventory/delivery capacity, offer expiry, negotiation round
   limits — nine ordered checks a candidate must pass before it's even
   eligible to be economically evaluated.

4. **Integrate with Razorpay correctly and honestly**: real Test Mode order
   creation when credentials are available, explicit `[SIMULATION]]` mode
   when they aren't — never one silently pretending to be the other — with
   idempotency, webhook signature verification, and a payment state
   machine that makes invalid transitions (e.g. a captured payment
   reverting to created) structurally impossible.

5. **Prove the economic value with an honest, reproducible benchmark** —
   not cherry-picked numbers. ECONEX is compared against three baselines
   (full price, a naive/ungoverned generous agent, and a plausible simple
   rule engine) on total contribution as the primary metric, with the
   result reported exactly as computed — including the one metric where a
   baseline actually beats ECONEX (Baseline C's incentive-efficiency
   ratio), rather than hiding it.

6. **Demonstrate the security boundary under real adversarial pressure**,
   not just claim it: a 17-scenario red-team suite covering payment
   tampering, webhook forgery/replay, cross-merchant data access, stale
   authorization, and candidate mutation after authorization, run live
   against the actual API — not asserted in prose.

## Non-objectives (deliberately out of scope)

- ECONEX is not a general-purpose negotiation chatbot or a coupon
  generator — the LLM's only job is understanding buyer intent and
  proposing a strategy label; it never sets a number.
- The conversion-probability model is a synthetic, deterministic heuristic
  — explicitly never presented as a trained ML model.
- No multi-agent swarm, no blockchain, no unnecessary infrastructure —
  SQLite and a single deterministic pipeline are sufficient for the
  problem this solves.
