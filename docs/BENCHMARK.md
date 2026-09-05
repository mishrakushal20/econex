# ECONEX — Benchmark

**SYNTHETIC BENCHMARK — SEEDED (42), REPRODUCIBLE, NOT REAL TRANSACTION
DATA.** Run it yourself:

```bash
cd backend
python3 -m app.benchmark
python3 -m unittest tests.test_benchmark -v
```

`tests/test_benchmark.py::test_reproducible_with_same_seed` proves two runs
with the same seed produce byte-identical output.

## What's being compared

- **Baseline A** — full price, no incentive, ever.
- **Baseline B** — naive generous buyer-ask: grant whatever the buyer asks
  for, clipped only by the hard cost floor (deliberately ignores the
  margin floor, discount cap, and incentive budget — this is what an
  *ungoverned* agent looks like).
- **Baseline C** — a plausible simple deterministic rule a merchant ops
  team might actually ship as a first pass: small price gap → half-gap
  discount, medium gap → capped discount, large gap → reject outright. It
  respects the hard policy caps (discount ceiling, margin floor) — it just
  doesn't rank across a candidate grid by expected economic value, and it
  ignores cashback entirely. Deliberately *not* a strawman.
- **ECONEX** — generate → policy → economic evaluation → ranking, exactly
  the same `app.pipeline.run_pipeline()` used by the live API.

500 seeded synthetic buyer scenarios, one product (`base_price=₹8,000`,
`cost=₹4,500`, `delivery_cost=₹50`), one merchant policy
(`margin_floor=₹2,000`, `max_discount=₹800`, `max_cashback=₹500`,
`incentive_budget=₹5,00,000`, `approval_threshold=₹1,000`).

"Conversion" is resolved by drawing a seeded random number against each
strategy's own conversion-heuristic probability for the offer it actually
makes — this keeps the comparison apples-to-apples (same heuristic, same
seed stream) rather than inventing a separate "real" conversion model.

## Results (n=500, seed=42) — unedited output

| Metric | Baseline A (full price) | Baseline B (naive generous) | Baseline C (simple rule) | ECONEX |
|---|---:|---:|---:|---:|
| Conversion rate | 22.0% | 69.0% | 27.4% | 44.0% |
| Revenue | ₹8,80,000.00 | ₹20,74,648.16 | ₹10,10,246.16 | ₹16,16,651.53 |
| **Contribution** | ₹3,79,500.00 | ₹5,04,898.16 | ₹3,86,896.16 | **₹6,15,651.53** |
| Incentive spend | ₹0.00 | ₹6,85,982.77 | ₹85,753.84 | ₹1,43,625.97 |
| Contribution per ₹1 incentive | ∞ (no spend) | 0.74 | **4.51** | 4.29 |
| Policy violations | 0 | **419 / 500** | 0 | **0** |
| Avg. selected EOV | ₹776.22 | ₹998.89 | ₹747.68 | ₹1,235.59 |

**ECONEX vs. best baseline (Baseline B) on the primary metric, total
contribution: +21.9%** — computed dynamically by `run_benchmark()`, not
hardcoded (`result["econex_vs_best_baseline"]`).

## Honest reading — including where ECONEX does NOT win

- **ECONEX wins decisively on the primary metric (total contribution)**
  against all three baselines: +62% vs. full price, +22% vs. the naive
  generous agent, +59% vs. the simple rule engine.
- **Baseline C actually has a slightly *better* contribution-per-incentive-
  rupee ratio (4.51) than ECONEX (4.29).** We're not hiding this. It makes
  sense: Baseline C spends very little on incentives in total (₹85,754
  across 500 scenarios) because it rejects outright anything with a large
  price gap rather than finding a profitable middle ground — a small,
  efficiently-spent budget produces a better *ratio* almost by
  construction, even though it converts far fewer deals and produces much
  less total profit. This is exactly why the doc's own priority ordering
  (primary metric = **total contribution**, secondary =
  contribution-per-incentive-rupee) matters: optimizing for the ratio
  alone would reward a strategy that's too conservative to be a good
  business outcome.
- **Baseline B converts most often** (69% vs. ECONEX's 44%) but **84% of
  its offers (419/500) violate the merchant's own policy** — it is what an
  ungoverned agent would do, shown precisely to make that failure mode
  visible, not a real option.
- We did not tune the scenario generator or the policy fixture to produce
  these numbers after the fact — this is the benchmark's actual output
  against the parameters in `app/benchmark.py`.

## What this benchmark is not

It is not a claim about real buyer behavior, a trained model, or a
production A/B test. Every place this data surfaces (README, dashboard,
this doc) is labelled SYNTHETIC. It exists to demonstrate, reproducibly,
that governed incentive-granting outperforms both extremes (no governance,
no incentives) *and* a plausible simple rule on the metric that actually
matters to a merchant — total contribution — while maintaining zero policy
violations.

## Scope note (upgrade pass)

The original plan called for a much larger benchmark matrix (10,000
scenarios, 5 buyer segments, 3 merchant objectives, 5 budget states,
sensitivity analysis). That full matrix was not built recently — see
`docs/TESTING_AND_CHANGES.md` and `docs/DECISIONS.md` for what was deferred and
why. `run_benchmark(num_scenarios=...)` already accepts an arbitrary
scenario count.
