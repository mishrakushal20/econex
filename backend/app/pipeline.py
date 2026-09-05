"""
Deterministic pipeline orchestrator (doc section 1's core loop, the
GENERATE -> POLICY -> EVALUATE -> RANK/SELECT portion). Pure function of
(intent, product, policy) -> PipelineResult. No DB, no LLM, no I/O — this
is what tests/test_hero_scenario_end_to_end.py exercises directly, and what
both the API layer and the benchmark/red-team harnesses call identically,
guaranteeing they can never drift apart.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import FrozenSet, Optional, Tuple

from app.core.candidate_generator import generate_candidates
from app.core.decision_resolver import resolve_decision
from app.core.domain import BuyerIntent, Candidate, Decision, EconomicEvaluation, MerchantPolicy, PolicyResult, Product
from app.core.economic_engine import evaluate_all as economic_evaluate_all
from app.core.optimizer import rank_all, select_best
from app.core.policy_engine import evaluate_all as policy_evaluate_all


@dataclass(frozen=True)
class PipelineResult:
    candidates: Tuple[Candidate, ...]
    policy_results: Tuple[PolicyResult, ...]
    evaluations: Tuple[EconomicEvaluation, ...]
    ranked: Tuple[Tuple[Candidate, EconomicEvaluation], ...]
    selection: Optional[Tuple[Candidate, EconomicEvaluation]]
    decision: Decision


def run_pipeline(
    intent: BuyerIntent,
    product: Product,
    policy: MerchantPolicy,
    previously_rejected_final_prices_paise: Optional[FrozenSet[int]] = None,
) -> PipelineResult:
    candidates = generate_candidates(intent, product, policy, previously_rejected_final_prices_paise)
    policy_results = policy_evaluate_all(candidates, intent, product, policy)
    evaluations = economic_evaluate_all(candidates, policy_results, intent, product)
    ranked = rank_all(candidates, evaluations)
    selection = select_best(candidates, evaluations)
    decision = resolve_decision(selection, intent, policy)
    return PipelineResult(
        candidates=candidates,
        policy_results=policy_results,
        evaluations=evaluations,
        ranked=ranked,
        selection=selection,
        decision=decision,
    )
