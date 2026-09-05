# ECONEX — 5-Minute Demo Script

All numbers below are real output from this exact codebase, not
illustrative placeholders. Reset and re-run as many times as you like —
every step is deterministic.

## Reset flow

```bash
cd backend
python3 scripts/seed_demo.py econex.db   # wipes and recreates the DB
python3 -m app.api.server 8000 &          # start the API
open ../frontend/index.html               # or just double-click it
```

The dashboard defaults to `http://127.0.0.1:8000` / token
`demo-merchant-token` — no configuration needed.

## Script

1. **State the thesis.** "AUTHORIZED ≠ OPTIMAL" is the dashboard's hero
   line. An agent could grant almost any discount; the question is whether
   it should.

2. **Enter the buyer ask.** The form defaults to exactly the doc's Table 10
   hero fixture: buyer budget ₹6,800, asks for ₹6,800, on a ₹8,000 pair of
   Wireless Earbuds X200 with a merchant policy that has almost no
   incentive budget left (₹9,800 of ₹10,000 already spent). Click **Run
   negotiation**.

3. **Watch the Decision panel.** It resolves to **COUNTER at ₹8,000**
   (full price) — not the discount the buyer asked for. This is the point:
   the merchant's remaining budget headroom (₹200) is smaller than the
   smallest possible discount or cashback step, so every incentivized
   candidate is blocked, and the system correctly falls back to a
   full-price counter rather than pretending it can't afford to concede.

4. **Open the Counterfactual Ledger.** All 19 generated candidates are
   listed. 17 of them show **BLOCKED — INCENTIVE_BUDGET_EXCEEDED** in red,
   struck through. The 2 feasible candidates (standard/expedited delivery
   at full price) are shown normally, with the winner marked **★
   SELECTED**. This is the "PRIMARY WOW FEATURE" — the judge can see
   exactly why every rejected option was rejected, in one screen, in
   seconds.

5. **Open the Audit Timeline.** Every stage — intent, proposal, candidate
   generation, policy, economic evaluation, selection, decision — is
   listed with a timestamp, reconstructable end to end.

6. **Click Run benchmark.** Shows ECONEX beating all three baselines on the
   primary metric (total contribution): full price (+62%), a naive
   generous agent (+22%, while that agent violates policy on 419/500
   offers), and a plausible simple rule engine (+59%) — with **zero**
   policy violations of its own. See `docs/BENCHMARK.md` for the full,
   unedited numbers, including where ECONEX does *not* win (Baseline C has
   a slightly better contribution-per-incentive-rupee ratio).

7. **Click Run red-team suite.** All 17 adversarial scenarios — unauthorized
   cashback, excessive discount, below-cost offers, below-margin offers,
   exhausted budget, malformed/fake-confident LLM output, expired offers,
   duplicate payments, client-modified payment amounts, Razorpay failures,
   forged webhook signatures, policy-bypass attempts, stale authorization,
   malicious strategy injection, cross-merchant scope attacks, and
   candidate mutation after authorization — show **✅ BLOCKED**.

8. **Trigger payment.** With the selected decision's `decision_id`,
   `POST /payments/order` with a fresh `idempotency_key`. With
   `RAZORPAY_KEY_ID`/`SECRET` set (see `docs/RAZORPAY_DEMO.md`), this
   creates a real Razorpay Test Mode order — I verified this against
   the live Razorpay dashboard before submitting. Without those
   variables set, the response is explicitly labelled `[SIMULATION]`
   instead. Either way, re-POSTing the same `idempotency_key` comes
   back `duplicate_blocked` instead of creating a second order.

9. **Reset and repeat.** `python3 scripts/seed_demo.py econex.db` restores
   the exact starting state for the next run.

## Why this demo is stronger than the originally-planned narrative

An earlier draft of this fixture (before the incentive-budget formula was
reconciled — see `docs/DECISIONS.md`) would have shown the system granting
a ₹1,200 discount. The corrected, locked financial rule reveals that the
merchant's incentive budget was actually already exhausted for this
scenario — and the system correctly refuses to grant a concession it can't
afford, even though that concession would have looked profitable in
isolation. That is a *more* convincing demonstration of "AUTHORIZED ≠
OPTIMAL" than the original script would have been: it shows the guardrail
holding under real pressure, not just in the easy case.
