"""
SYNTHETIC / SEEDED / REPRODUCIBLE benchmark (doc section 17, locked seed 42).

Compares three strategies over a batch of randomly-generated (but seeded,
so fully reproducible) buyer negotiation scenarios:

    BASELINE A: full price / no incentive
    BASELINE B: naive generous buyer-ask strategy (always grant exactly
                what the buyer asked for, clipped only by hard cost floor)
    ECONEX:     generate -> policy -> economic evaluation -> ranking

"Conversion" is itself synthetic: we resolve it by drawing a uniform random
number against each strategy's own P_conv-equivalent (for Econex we reuse
the real conversion_heuristic; for the baselines we compute the same
heuristic on their fixed offer so the comparison is apples-to-apples). This
is clearly labeled synthetic and must never be described as measuring real
buyer behavior.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import List

from app.core.conversion_heuristic import ConversionInputs, compute_p_conv
from app.core.domain import BuyerIntent, MerchantPolicy, Product
from app.pipeline import run_pipeline

SEED = 42


@dataclass
class ScenarioResult:
    converted: bool
    revenue_paise: int
    contribution_paise: int
    incentive_spend_paise: int
    policy_violation: bool
    eov_paise: float


def _make_scenario(rng: random.Random, product: Product) -> BuyerIntent:
    # Buyer budget somewhere between cost and base price, with some noise.
    budget = rng.randint(product.cost_paise, product.base_price_paise)
    requested_price = rng.randint(int(budget * 0.9), int(budget * 1.05))
    return BuyerIntent(
        session_id=f"bench-{rng.randint(0, 10**9)}",
        product_id=product.product_id,
        buyer_budget_paise=budget,
        quantity=1,
        requested_price_paise=requested_price,
        requested_cashback_paise=0,
        wants_expedited_delivery=rng.random() < 0.2,
        round_number=1,
        offer_expired=False,
    )


def _resolve_conversion(rng: random.Random, p_conv: float) -> bool:
    return rng.random() < p_conv


def run_baseline_a(intent: BuyerIntent, product: Product, rng: random.Random) -> ScenarioResult:
    """Full price / no incentive."""
    price = product.base_price_paise
    contribution = price - product.cost_paise - product.delivery_cost_paise
    p_conv = compute_p_conv(
        ConversionInputs(intent.buyer_budget_paise, product.base_price_paise, price, 0, False)
    )
    converted = _resolve_conversion(rng, p_conv)
    return ScenarioResult(
        converted=converted,
        revenue_paise=price if converted else 0,
        contribution_paise=contribution if converted else 0,
        incentive_spend_paise=0,
        policy_violation=False,
        eov_paise=p_conv * contribution,
    )


def run_baseline_b(
    intent: BuyerIntent, product: Product, policy: MerchantPolicy, rng: random.Random
) -> ScenarioResult:
    """Naive generous buyer-ask strategy: grant exactly what the buyer asked,
    clipped only by the hard cost floor (NOT by margin floor / discount cap
    / budget — this is deliberately naive, to demonstrate what an
    ungoverned agent could do)."""
    price = max(intent.requested_price_paise or product.base_price_paise, product.cost_paise)
    discount = max(0, product.base_price_paise - price)
    contribution = price - product.cost_paise - product.delivery_cost_paise
    policy_violation = (
        discount > policy.max_discount_paise
        or contribution < policy.margin_floor_paise
    )
    p_conv = compute_p_conv(
        ConversionInputs(intent.buyer_budget_paise, product.base_price_paise, price, 0, False)
    )
    converted = _resolve_conversion(rng, p_conv)
    return ScenarioResult(
        converted=converted,
        revenue_paise=price if converted else 0,
        contribution_paise=contribution if converted else 0,
        incentive_spend_paise=discount if converted else 0,
        policy_violation=policy_violation,
        eov_paise=p_conv * contribution,
    )


def run_baseline_c(
    intent: BuyerIntent, product: Product, policy: MerchantPolicy, rng: random.Random
) -> ScenarioResult:
    """Baseline C: a plausible simple deterministic rule engine (doc upgrade
    section 16) — NOT deliberately dumb. A commercially reasonable merchant
    ops team could actually ship this as a first pass:

        gap = base_price - buyer's requested price
        small gap  (<= 10% of base) -> grant a small discount (half the gap)
        medium gap (<= 25% of base) -> grant a capped discount (policy max)
        large gap  (> 25% of base)  -> reject outright, no counter

    Unlike Baseline B, this rule respects the hard policy caps (discount
    ceiling, margin floor) — it just doesn't do EOV-based ranking across a
    candidate grid, and it doesn't consider cashback at all. It exists to
    show ECONEX's advantage isn't just "vs an agent with no guardrails" but
    also "vs a sane-looking simple rule a merchant might otherwise ship."
    """
    requested = intent.requested_price_paise or product.base_price_paise
    gap = product.base_price_paise - requested
    gap_ratio = gap / product.base_price_paise if product.base_price_paise else 0

    if gap_ratio <= 0:
        price = product.base_price_paise
    elif gap_ratio <= 0.10:
        discount = min(gap // 2, policy.max_discount_paise)
        price = product.base_price_paise - discount
    elif gap_ratio <= 0.25:
        price = product.base_price_paise - policy.max_discount_paise
    else:
        # large gap -> reject outright, no sale at all
        return ScenarioResult(False, 0, 0, 0, False, 0.0)

    price = max(price, product.cost_paise)  # never below cost
    discount = max(0, product.base_price_paise - price)
    contribution = price - product.cost_paise - product.delivery_cost_paise
    policy_violation = discount > policy.max_discount_paise or contribution < policy.margin_floor_paise
    p_conv = compute_p_conv(
        ConversionInputs(intent.buyer_budget_paise, product.base_price_paise, price, 0, False)
    )
    converted = _resolve_conversion(rng, p_conv)
    return ScenarioResult(
        converted=converted,
        revenue_paise=price if converted else 0,
        contribution_paise=contribution if converted else 0,
        incentive_spend_paise=discount if converted else 0,
        policy_violation=policy_violation,
        eov_paise=p_conv * contribution,
    )


def run_econex(
    intent: BuyerIntent, product: Product, policy: MerchantPolicy, rng: random.Random
) -> ScenarioResult:
    result = run_pipeline(intent, product, policy)
    if result.selection is None:
        return ScenarioResult(False, 0, 0, 0, False, 0.0)
    candidate, evaluation = result.selection
    p_conv = evaluation.p_conv or 0.0
    converted = _resolve_conversion(rng, p_conv)
    return ScenarioResult(
        converted=converted,
        revenue_paise=candidate.final_price_paise if converted else 0,
        contribution_paise=evaluation.contribution_paise if converted else 0,
        incentive_spend_paise=(candidate.discount_paise + candidate.cashback_paise) if converted else 0,
        policy_violation=False,  # Econex candidates are policy-feasible by construction
        eov_paise=evaluation.expected_economic_value_paise,
    )


def _summarize(name: str, results: List[ScenarioResult]) -> dict:
    n = len(results)
    conversions = sum(1 for r in results if r.converted)
    revenue = sum(r.revenue_paise for r in results)
    contribution = sum(r.contribution_paise for r in results)
    incentive_spend = sum(r.incentive_spend_paise for r in results)
    violations = sum(1 for r in results if r.policy_violation)
    avg_eov = sum(r.eov_paise for r in results) / n if n else 0.0
    contribution_per_incentive_rupee = (
        contribution / incentive_spend if incentive_spend > 0 else None
    )
    return {
        "strategy": name,
        "scenarios": n,
        "conversion_rate": conversions / n if n else 0.0,
        "revenue_paise": revenue,
        "contribution_paise": contribution,
        "incentive_spend_paise": incentive_spend,
        "contribution_per_incentive_rupee": contribution_per_incentive_rupee,
        "policy_violations": violations,
        "avg_selected_eov_paise": avg_eov,
    }


def run_benchmark(num_scenarios: int = 500, seed: int = SEED) -> dict:
    """SYNTHETIC / SEEDED / REPRODUCIBLE — NOT REAL TRANSACTION DATA.
    Running this twice with the same seed and num_scenarios yields
    byte-identical output."""
    rng_a = random.Random(seed)
    rng_b = random.Random(seed)
    rng_c = random.Random(seed)
    rng_e = random.Random(seed)
    scenario_rng = random.Random(seed)

    product = Product("P-bench", "M-bench", 800000, 450000, 5000, 10_000, 500)
    policy = MerchantPolicy("M-bench", 200000, 80000, 50000, 50_000_000, 0, 100000, 3)

    intents = [_make_scenario(scenario_rng, product) for _ in range(num_scenarios)]

    results_a = [run_baseline_a(intent, product, rng_a) for intent in intents]
    results_b = [run_baseline_b(intent, product, policy, rng_b) for intent in intents]
    results_c = [run_baseline_c(intent, product, policy, rng_c) for intent in intents]
    results_e = [run_econex(intent, product, policy, rng_e) for intent in intents]

    econex_summary = _summarize("ECONEX", results_e)
    baseline_summaries = {
        "baseline_a": _summarize("BASELINE_A_FULL_PRICE", results_a),
        "baseline_b": _summarize("BASELINE_B_NAIVE_GENEROUS", results_b),
        "baseline_c": _summarize("BASELINE_C_SIMPLE_RULE_ENGINE", results_c),
    }
    best_baseline_name, best_baseline = max(
        baseline_summaries.items(), key=lambda kv: kv[1]["contribution_paise"]
    )
    pct_vs_best = (
        (econex_summary["contribution_paise"] - best_baseline["contribution_paise"])
        / best_baseline["contribution_paise"]
        * 100
        if best_baseline["contribution_paise"] > 0
        else None
    )

    return {
        "seed": seed,
        "label": "SYNTHETIC BENCHMARK — SEEDED, REPRODUCIBLE, NOT REAL TRANSACTION DATA",
        "num_scenarios": num_scenarios,
        **baseline_summaries,
        "econex": econex_summary,
        "econex_vs_best_baseline": {
            "best_baseline": best_baseline_name,
            "contribution_pct_improvement": pct_vs_best,
        },
    }


if __name__ == "__main__":
    import json

    print(json.dumps(run_benchmark(), indent=2, default=str))
