"""
Optimizer (Selector) — chooses the single best FEASIBLE candidate.

Ranking (locked, doc section 10/12):
    1. EOV descending
    2. Expected contribution descending
    3. Final price ascending
    4. candidateId ascending

The Optimizer does NOT decide ACCEPT/COUNTER/REJECT/ESCALATE — that is the
Decision Resolver's job (doc section 10: "Selector does NOT decide...").
It only ever considers candidates where policy_result.feasible is True;
this is the single enforcement point that guarantees an infeasible
candidate can never win regardless of a fabricated EOV.
"""

from __future__ import annotations

from typing import Optional, Tuple

from app.core.domain import Candidate, EconomicEvaluation


def select_best(
    candidates: Tuple[Candidate, ...],
    evaluations: Tuple[EconomicEvaluation, ...],
) -> Optional[Tuple[Candidate, EconomicEvaluation]]:
    by_id = {c.candidate_id: c for c in candidates}

    feasible_pairs = [
        (by_id[e.candidate_id], e) for e in evaluations if e.feasible
    ]
    if not feasible_pairs:
        return None

    def sort_key(pair):
        candidate, evaluation = pair
        return (
            -evaluation.expected_economic_value_paise,  # EOV descending
            -evaluation.contribution_paise,  # contribution descending
            candidate.final_price_paise,  # final price ascending
            candidate.candidate_id,  # candidateId ascending
        )

    feasible_pairs.sort(key=sort_key)
    return feasible_pairs[0]


def rank_all(
    candidates: Tuple[Candidate, ...],
    evaluations: Tuple[EconomicEvaluation, ...],
) -> Tuple[Tuple[Candidate, EconomicEvaluation], ...]:
    """Return ALL candidates (feasible and infeasible) in display order for
    the counterfactual simulator UI (doc section 9). Infeasible candidates
    are pushed to the bottom, deterministically, but are never eligible to
    be `select_best`'s winner.
    """
    by_id = {c.candidate_id: c for c in candidates}
    pairs = [(by_id[e.candidate_id], e) for e in evaluations]

    def sort_key(pair):
        candidate, evaluation = pair
        feasible_rank = 0 if evaluation.feasible else 1
        eov = evaluation.expected_economic_value_paise
        return (
            feasible_rank,
            -eov if evaluation.feasible else 0,
            -evaluation.contribution_paise if evaluation.feasible else 0,
            candidate.final_price_paise,
            candidate.candidate_id,
        )

    pairs.sort(key=sort_key)
    return tuple(pairs)
