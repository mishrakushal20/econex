"""
Negotiation service — the orchestration layer used by the HTTP API. This is
where DB reads/writes, audit-trail recording, and the (optional,
best-effort, non-authoritative) LLM strategy proposal all happen. The
actual financial decision is 100% delegated to app.pipeline.run_pipeline,
which never sees the LLM.
"""

from __future__ import annotations

import sqlite3
from typing import Any, Dict, Optional

from app.agents.router import route_and_propose
from app.audit import record as audit_record
from app.core.domain import BuyerIntent
from app.llm.claude_provider import ClaudeLLMProvider
from app.llm.provider import LLMProvider, LLMProviderError
from app.pipeline import run_pipeline
from app.repositories import merchant_repo, negotiation_repo
from app.schemas.serializers import buyer_view_offer, merchant_view_offer


def handle_buyer_intent(
    conn: sqlite3.Connection,
    merchant_id: str,
    product_id: str,
    buyer_text: str,
    buyer_budget_paise: int,
    quantity: int,
    requested_price_paise: Optional[int],
    requested_cashback_paise: int,
    context: Dict[str, Any],
    llm_provider: LLMProvider,
) -> Dict[str, Any]:
    """Full doc-section-1 loop for one buyer message:
    UNDERSTAND -> PROPOSE STRATEGY -> GENERATE -> POLICY -> EVALUATE ->
    RANK/SELECT -> DECISION, with every stage audited.

    Returns a dict with BOTH buyer_view and merchant_view payloads; the API
    layer is responsible for only ever returning buyer_view to buyer-facing
    endpoints (doc section 14/19 privacy boundary).
    """
    product = merchant_repo.get_product(conn, product_id)
    if product is None:
        raise ValueError(f"Unknown product {product_id}")
    policy = merchant_repo.get_policy(conn, merchant_id)
    if policy is None:
        raise ValueError(f"No policy configured for merchant {merchant_id}")

    session_id = negotiation_repo.create_session(conn, merchant_id, product_id)
    audit_record(conn, "intent", {"buyer_text": buyer_text, "buyer_budget_paise": buyer_budget_paise}, session_id, merchant_id)

    # PROPOSE STRATEGY — best-effort, non-authoritative. LLM failure never
    # fabricates a proposal (doc section 12); we fall back to a clearly
    # labeled "NONE" strategy and continue the deterministic pipeline
    # regardless, because a strategy label is advisory context only.
    # WHICH provider is in use is itself audited (doc upgrade section 9:
    # LLM failure semantics must never be silent).
    provider_mode = "real_claude" if isinstance(llm_provider, ClaudeLLMProvider) else "demo_synthetic_provider"
    try:
        agent_name, proposal = route_and_propose(buyer_text, context, llm_provider)
        strategy_label = proposal.strategy
        rationale = proposal.rationale
        wants_expedited = proposal.requested_delivery_preference
        llm_failed = False
    except LLMProviderError as exc:
        agent_name, strategy_label, rationale = "NONE", "NONE", f"LLM unavailable ({provider_mode}): {exc}"
        wants_expedited = bool(context.get("wants_expedited_delivery", False))
        llm_failed = True

    audit_record(
        conn,
        "proposal",
        {
            "agent": agent_name,
            "strategy": strategy_label,
            "rationale": rationale,
            "provider_mode": provider_mode,
            "llm_failed": llm_failed,
        },
        session_id,
        merchant_id,
    )

    intent = BuyerIntent(
        session_id=session_id,
        product_id=product_id,
        buyer_budget_paise=buyer_budget_paise,
        quantity=quantity,
        requested_price_paise=requested_price_paise,
        requested_cashback_paise=requested_cashback_paise,
        wants_expedited_delivery=wants_expedited,
        round_number=1,
        offer_expired=False,
    )
    intent_id = negotiation_repo.record_intent(conn, session_id, intent, buyer_text, strategy_label, rationale)

    result = run_pipeline(intent, product, policy)

    audit_record(conn, "candidate_generation", {"count": len(result.candidates)}, session_id, merchant_id)
    audit_record(
        conn,
        "policy",
        {"feasible_count": sum(1 for p in result.policy_results if p.feasible)},
        session_id,
        merchant_id,
    )
    audit_record(conn, "economic_evaluation", {"evaluated": len(result.evaluations)}, session_id, merchant_id)
    audit_record(
        conn,
        "selection",
        {"selected": result.selection[0].candidate_id if result.selection else None},
        session_id,
        merchant_id,
    )
    audit_record(
        conn,
        "decision",
        {"action": result.decision.action.value, "reason": result.decision.reason},
        session_id,
        merchant_id,
    )

    negotiation_repo.record_offers(conn, intent_id, result.candidates, result.policy_results, result.evaluations)

    from app.core.state_machine import NegotiationState

    new_state = (
        NegotiationState.PENDING_APPROVAL.value
        if result.decision.requires_approval
        else (
            NegotiationState.CLOSED_REJECTED.value
            if result.selection is None
            else NegotiationState.AWAITING_BUYER_RESPONSE.value
        )
    )
    frozen_candidate = result.selection[0] if result.selection else None
    decision_id = negotiation_repo.record_decision(
        conn, intent_id, merchant_id, result.decision, new_state, frozen_candidate
    )
    negotiation_repo.update_session_state(conn, session_id, new_state)

    buyer_payload = None
    merchant_payload = None
    if result.selection:
        candidate, evaluation = result.selection
        buyer_payload = buyer_view_offer(candidate, result.decision)
        merchant_payload = merchant_view_offer(candidate, evaluation, result.decision)

    return {
        "session_id": session_id,
        "intent_id": intent_id,
        "decision_id": decision_id,
        "state": new_state,
        "decision_action": result.decision.action.value,
        "buyer_view": buyer_payload,
        "merchant_view": merchant_payload,
        "candidate_count": len(result.candidates),
        "feasible_count": sum(1 for e in result.evaluations if e.feasible),
    }
