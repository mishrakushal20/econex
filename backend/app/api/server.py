"""
HTTP JSON API (doc section 22 / Table 8), implemented with Python's stdlib
`http.server` — no Flask/FastAPI, because this sandbox cannot install them
(see top-level build report / docs/DECISIONS.md). The endpoint surface and
request/response shapes follow doc Table 8.

Security (doc section 14):
    - merchant-scoped authorization: every merchant-facing endpoint requires
      `Authorization: Bearer <merchant api_token>`, resolved to a specific
      merchant_id — a request can never act on another merchant's data.
    - request/schema validation: `_require_fields` on every POST body.
    - buyer-facing endpoints only ever return `buyer_view` payloads,
      enforced by `assert_no_private_leak` right before sending.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, Optional

from app.audit import record as audit_record
from app.audit import timeline_for_session
from app.config import Config
from app.core.domain import NegotiationAction
from app.core.razorpay_adapter import create_order
from app.core.state_machine import InvalidTransitionError, NegotiationState, transition
from app.database import get_connection, init_db
from app.llm.claude_provider import ClaudeLLMProvider
from app.llm.mock_provider import MockLLMProvider
from app.llm.provider import LLMProvider
from app.repositories import merchant_repo, negotiation_repo, payments_repo
from app.schemas.serializers import assert_no_private_leak
from app.services.negotiation_service import handle_buyer_intent


class ApiError(Exception):
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.message = message


def _require_fields(body: Dict[str, Any], fields: list) -> None:
    missing = [f for f in fields if f not in body]
    if missing:
        raise ApiError(400, f"Missing required fields: {missing}")


def _authenticate(handler: "EconexRequestHandler") -> str:
    auth_header = handler.headers.get("Authorization", "")
    match = re.match(r"^Bearer (.+)$", auth_header)
    if not match:
        raise ApiError(401, "Missing or malformed Authorization header")
    token = match.group(1)
    conn = get_connection(Config.DB_PATH)
    try:
        row = merchant_repo.get_merchant_by_token(conn, token)
    finally:
        conn.close()
    if row is None:
        raise ApiError(401, "Invalid API token")
    return row["merchant_id"]


class EconexRequestHandler(BaseHTTPRequestHandler):
    llm_provider = MockLLMProvider()  # overridden by create_server() when a real provider is configured

    @staticmethod
    def _sanitize_for_json(value):
        """Recursively replace non-finite floats (inf/-inf/nan) with None.

        Python's json.dumps happily emits the literal tokens Infinity /
        -Infinity / NaN, which are NOT valid JSON per spec (RFC 8259) and
        make every browser's JSON.parse() throw. Any float division in this
        codebase that can hit a zero denominator must never reach this
        function un-sanitized, or the response would silently be broken
        JSON. allow_nan=False below turns any value this function misses
        into a loud 500 instead of a silent client-side parse failure.
        """
        if isinstance(value, float):
            return value if value == value and value not in (float("inf"), float("-inf")) else None
        if isinstance(value, dict):
            return {k: EconexRequestHandler._sanitize_for_json(v) for k, v in value.items()}
        if isinstance(value, list):
            return [EconexRequestHandler._sanitize_for_json(v) for v in value]
        return value

    def _send_json(self, status_code: int, payload: Dict[str, Any]) -> None:
        safe_payload = self._sanitize_for_json(payload)
        body = json.dumps(safe_payload, default=str, allow_nan=False).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()

    def _read_json_body(self) -> Dict[str, Any]:
        length = int(self.headers.get("Content-Length", 0) or 0)
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise ApiError(400, f"Invalid JSON body: {exc}")

    def log_message(self, format, *args):
        pass  # keep test/demo output clean; audit_events is the real log

    def do_POST(self):
        try:
            if self.path == "/buyer-intents":
                self._handle_create_intent()
            elif self.path == "/offers/evaluate":
                self._handle_evaluate_offers()
            elif re.match(r"^/approvals/[^/]+/approve$", self.path):
                self._handle_approval(approve=True)
            elif re.match(r"^/approvals/[^/]+/deny$", self.path):
                self._handle_approval(approve=False)
            elif self.path == "/payments/order":
                self._handle_create_payment()
            elif self.path == "/webhooks/razorpay":
                self._handle_webhook()
            elif self.path == "/outcomes/record":
                self._handle_record_outcome()
            else:
                raise ApiError(404, "Not found")
        except ApiError as exc:
            self._send_json(exc.status_code, {"error": exc.message})
        except Exception as exc:  # pragma: no cover - defensive catch-all
            self._send_json(500, {"error": f"Internal error: {exc}"})

    def do_GET(self):
        try:
            audit_match = re.match(r"^/audit/([^/]+)$", self.path)
            ledger_match = re.match(r"^/sessions/([^/]+)/ledger$", self.path)
            if audit_match:
                self._handle_get_audit(audit_match.group(1))
            elif ledger_match:
                self._handle_get_ledger(ledger_match.group(1))
            elif self.path == "/dashboard/summary":
                self._handle_dashboard_summary()
            elif self.path.startswith("/benchmark/run"):
                self._handle_run_benchmark()
            elif self.path.startswith("/redteam/run"):
                self._handle_run_redteam()
            else:
                raise ApiError(404, "Not found")
        except ApiError as exc:
            self._send_json(exc.status_code, {"error": exc.message})
        except Exception as exc:  # pragma: no cover
            self._send_json(500, {"error": f"Internal error: {exc}"})

    # ---- handlers -------------------------------------------------------

    def _handle_create_intent(self):
        merchant_id = _authenticate(self)
        body = self._read_json_body()
        _require_fields(body, ["product_id", "buyer_budget_paise", "quantity"])

        conn = get_connection(Config.DB_PATH)
        try:
            result = handle_buyer_intent(
                conn,
                merchant_id=merchant_id,
                product_id=body["product_id"],
                buyer_text=body.get("buyer_text", ""),
                buyer_budget_paise=body["buyer_budget_paise"],
                quantity=body["quantity"],
                requested_price_paise=body.get("requested_price_paise"),
                requested_cashback_paise=body.get("requested_cashback_paise", 0),
                context=body.get("context", {}),
                llm_provider=self.llm_provider,
            )
            conn.commit()
        finally:
            conn.close()

        buyer_response = result["buyer_view"] or {}
        if buyer_response:
            assert_no_private_leak(buyer_response)
        self._send_json(
            200,
            {
                "session_id": result["session_id"],
                "decision_id": result["decision_id"],
                "state": result["state"],
                "action": result["decision_action"],
                "offer": buyer_response,
            },
        )

    def _handle_evaluate_offers(self):
        # Alias endpoint per doc Table 8 ("Generate/evaluate/optimize") —
        # same underlying flow as /buyer-intents for this MVP.
        self._handle_create_intent()

    def _handle_approval(self, approve: bool):
        merchant_id = _authenticate(self)
        decision_id = self.path.split("/")[2]
        conn = get_connection(Config.DB_PATH)
        try:
            # merchant-scoped lookup — a merchant can never approve/deny
            # another merchant's decision (doc upgrade section 8).
            row = negotiation_repo.get_decision_scoped(conn, decision_id, merchant_id)
            if row is None:
                raise ApiError(404, "Unknown decision_id")
            current_state = NegotiationState(row["state"])
            target_state = NegotiationState.APPROVED if approve else NegotiationState.DENIED
            try:
                transition(current_state, target_state)
            except InvalidTransitionError as exc:
                # covers repeated-authorization / stale-decision attempts too:
                # a decision already CLOSED_ACCEPTED has no valid path back
                # into APPROVED/DENIED.
                raise ApiError(409, str(exc))
            negotiation_repo.update_decision_state(conn, decision_id, target_state.value)
            negotiation_repo.record_authorization(
                conn, decision_id, actor=f"merchant:{merchant_id}",
                previous_state=current_state.value, new_state=target_state.value,
            )
            final_state = target_state
            if target_state == NegotiationState.APPROVED:
                transition(NegotiationState.APPROVED, NegotiationState.CLOSED_ACCEPTED)
                negotiation_repo.update_decision_state(conn, decision_id, NegotiationState.CLOSED_ACCEPTED.value)
                final_state = NegotiationState.CLOSED_ACCEPTED
            else:
                transition(NegotiationState.DENIED, NegotiationState.CLOSED_REJECTED)
                negotiation_repo.update_decision_state(conn, decision_id, NegotiationState.CLOSED_REJECTED.value)
                final_state = NegotiationState.CLOSED_REJECTED
            conn.commit()
        finally:
            conn.close()
        self._send_json(200, {"decision_id": decision_id, "state": final_state.value})

    def _handle_create_payment(self):
        """doc upgrade section 4 (HIGHEST PRIORITY): the client supplies
        ONLY decision_id + idempotency_key. The payment amount is derived
        entirely server-side from the frozen commercial terms captured at
        decision time (section 5). Any client-supplied `amount_paise` is
        REJECTED outright (400) rather than silently ignored, so a
        malicious/buggy client gets an unambiguous error instead of a
        payment for an unexpected amount.
        """
        merchant_id = _authenticate(self)
        body = self._read_json_body()
        _require_fields(body, ["decision_id", "idempotency_key"])
        if "amount_paise" in body:
            raise ApiError(
                400,
                "amount_paise must not be supplied by the client — the payment amount is "
                "always derived server-side from the authorized decision's frozen terms.",
            )

        conn = get_connection(Config.DB_PATH)
        try:
            # merchant-scoped lookup — a merchant can never pay for (or even
            # discover the existence of) another merchant's decision.
            decision_row = negotiation_repo.get_decision_scoped(conn, body["decision_id"], merchant_id)
            if decision_row is None:
                raise ApiError(404, "Unknown decision_id")
            if decision_row["state"] not in (
                NegotiationState.CLOSED_ACCEPTED.value,
                NegotiationState.AWAITING_BUYER_RESPONSE.value,
            ):
                # Payment execution must happen ONLY after deterministic
                # authorization (doc section 13).
                raise ApiError(
                    409,
                    f"Decision {body['decision_id']} is not authorized for payment "
                    f"(state={decision_row['state']})",
                )
            if decision_row["frozen_final_price_paise"] is None:
                # REJECT/no-selection decisions were never frozen with
                # payable terms — nothing to charge.
                raise ApiError(409, "This decision has no payable frozen terms (no candidate was selected)")

            expires_at = decision_row["expires_at"]
            if expires_at is not None and datetime.now(timezone.utc) > datetime.fromisoformat(expires_at):
                raise ApiError(410, f"Authorized offer expired at {expires_at}; re-negotiate")

            # THE server-authoritative amount — never taken from the client.
            server_amount_paise = decision_row["frozen_final_price_paise"] * decision_row["frozen_quantity"]

            outcome = payments_repo.process_payment(
                conn,
                decision_id=body["decision_id"],
                merchant_id=merchant_id,
                idempotency_key=body["idempotency_key"],
                amount_paise=server_amount_paise,
                create_order_fn=create_order,
            )
            conn.commit()
        finally:
            conn.close()
        self._send_json(200, outcome)

    def _handle_webhook(self):
        """doc upgrade section 6: valid signature -> may transition payment
        state, audited. Invalid signature -> rejected outright, NEVER
        transitions anything, still logged (as rejected). Idempotent:
        duplicate/replayed events (same dedupe_key) are recognized and
        skipped rather than re-applied.
        """
        import hashlib

        from app.core.razorpay_adapter import PaymentStatus, verify_webhook_signature

        length = int(self.headers.get("Content-Length", 0) or 0)
        raw_body = self.rfile.read(length) if length else b"{}"
        signature = self.headers.get("X-Razorpay-Signature", "")
        signature_valid = verify_webhook_signature(raw_body, signature)
        try:
            payload = json.loads(raw_body.decode("utf-8"))
        except json.JSONDecodeError:
            raise ApiError(400, "Invalid webhook JSON")

        event_type = payload.get("event", "unknown")
        # Dedupe key: prefer Razorpay's own event/entity id when present;
        # fall back to a content hash so a byte-identical replay is still
        # caught even without an explicit id (doc upgrade section 6/19:
        # 'replayed event', 'duplicate event').
        entity_id = (
            payload.get("payload", {}).get("payment", {}).get("entity", {}).get("id")
            or payload.get("id")
        )
        dedupe_key = entity_id or hashlib.sha256(raw_body).hexdigest()

        conn = get_connection(Config.DB_PATH)
        try:
            existing = conn.execute(
                "SELECT webhook_event_id, processed FROM webhook_events WHERE dedupe_key = ?",
                (dedupe_key,),
            ).fetchone()
            if existing is not None:
                # Idempotent: acknowledge without reprocessing.
                self._send_json(
                    200,
                    {
                        "webhook_event_id": existing["webhook_event_id"],
                        "signature_valid": signature_valid,
                        "duplicate": True,
                    },
                )
                return

            webhook_event_id = f"WH-{uuid.uuid4().hex[:10]}"
            transitioned = False
            reject_reason = None

            if not signature_valid:
                reject_reason = "invalid_or_missing_signature"
            else:
                razorpay_order_id = (
                    payload.get("payload", {}).get("payment", {}).get("entity", {}).get("order_id")
                )
                target_status = None
                if event_type == "payment.captured":
                    target_status = PaymentStatus.CAPTURED
                elif event_type == "payment.failed":
                    target_status = PaymentStatus.FAILED

                if razorpay_order_id and target_status is not None:
                    payment_row = payments_repo.find_by_razorpay_order_id(conn, razorpay_order_id)
                    if payment_row is not None:
                        transitioned = payments_repo.transition_payment_status(
                            conn, payment_row["payment_id"], target_status
                        )
                        if transitioned:
                            audit_record(
                                conn,
                                "payment",
                                {"event": event_type, "payment_id": payment_row["payment_id"], "new_status": target_status.value},
                                merchant_id=payment_row["merchant_id"],
                            )

            conn.execute(
                "INSERT INTO webhook_events (webhook_event_id, event_type, dedupe_key, payload_json, "
                "signature_valid, processed, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    webhook_event_id,
                    event_type,
                    dedupe_key,
                    json.dumps(payload),
                    int(signature_valid),
                    int(transitioned),
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            conn.commit()
        finally:
            conn.close()

        if not signature_valid:
            # NEVER treated as legitimate: HTTP error, no state transition,
            # already logged above with signature_valid=0.
            self._send_json(401, {"webhook_event_id": webhook_event_id, "signature_valid": False, "error": reject_reason})
            return

        self._send_json(
            200,
            {"webhook_event_id": webhook_event_id, "signature_valid": True, "transitioned": transitioned},
        )

    def _handle_record_outcome(self):
        merchant_id = _authenticate(self)
        body = self._read_json_body()
        _require_fields(body, ["decision_id", "actual_converted", "actual_contribution_paise"])
        conn = get_connection(Config.DB_PATH)
        try:
            decision_row = negotiation_repo.get_decision_scoped(conn, body["decision_id"], merchant_id)
            if decision_row is None:
                raise ApiError(404, "Unknown decision_id")
            outcome_id = negotiation_repo.record_outcome(
                conn,
                decision_id=body["decision_id"],
                predicted_p_conv=body.get("predicted_p_conv"),
                predicted_eov_paise=body.get("predicted_eov_paise"),
                actual_converted=bool(body["actual_converted"]),
                actual_contribution_paise=body["actual_contribution_paise"],
            )
            conn.commit()
        finally:
            conn.close()
        self._send_json(200, {"outcome_id": outcome_id})

    def _handle_get_audit(self, session_id: str):
        merchant_id = _authenticate(self)
        conn = get_connection(Config.DB_PATH)
        try:
            timeline = timeline_for_session(conn, session_id, merchant_id)
        finally:
            conn.close()
        self._send_json(200, {"session_id": session_id, "timeline": timeline})

    def _handle_get_ledger(self, session_id: str):
        """Full per-candidate counterfactual ledger for a session — the doc's
        mandated 'primary wow feature' (section 18). Merchant-authenticated
        AND merchant-scoped: the session lookup itself is filtered by
        merchant_id so one merchant can never enumerate another's ledger
        by guessing a session_id (doc upgrade section 8).
        """
        merchant_id = _authenticate(self)
        conn = get_connection(Config.DB_PATH)
        try:
            session_row = conn.execute(
                "SELECT session_id FROM negotiation_sessions WHERE session_id = ? AND merchant_id = ?",
                (session_id, merchant_id),
            ).fetchone()
            if session_row is None:
                raise ApiError(404, "Unknown session_id")
            intent_row = conn.execute(
                "SELECT intent_id FROM buyer_intents WHERE session_id = ? ORDER BY created_at DESC LIMIT 1",
                (session_id,),
            ).fetchone()
            if intent_row is None:
                raise ApiError(404, "No intent found for this session")
            offer_rows = conn.execute(
                "SELECT * FROM offers WHERE intent_id = ? ORDER BY final_price_paise DESC, candidate_id ASC",
                (intent_row["intent_id"],),
            ).fetchall()
            decision_row = conn.execute(
                "SELECT * FROM decisions WHERE intent_id = ? AND merchant_id = ? ORDER BY created_at DESC LIMIT 1",
                (intent_row["intent_id"], merchant_id),
            ).fetchone()
        finally:
            conn.close()

        selected_id = decision_row["selected_candidate_id"] if decision_row else None
        candidates = [
            {
                "candidate_id": row["candidate_id"],
                "final_price_paise": row["final_price_paise"],
                "discount_paise": row["discount_paise"],
                "cashback_paise": row["cashback_paise"],
                "delivery_option": row["delivery_option"],
                "feasible": bool(row["feasible"]),
                "first_violation": row["first_violation"],
                "contribution_paise": row["contribution_paise"],
                "p_conv": row["p_conv"],
                "eov_paise": row["eov_paise"],
                "selected": row["candidate_id"] == selected_id,
            }
            for row in offer_rows
        ]
        self._send_json(200, {"session_id": session_id, "candidates": candidates})

    def _handle_dashboard_summary(self):
        merchant_id = _authenticate(self)
        conn = get_connection(Config.DB_PATH)
        try:
            policy = merchant_repo.get_policy(conn, merchant_id)
            decisions = conn.execute(
                "SELECT action, COUNT(*) as c FROM decisions WHERE merchant_id = ? GROUP BY action",
                (merchant_id,),
            ).fetchall()
        finally:
            conn.close()
        self._send_json(
            200,
            {
                "merchant_id": merchant_id,
                "policy": dict(policy.__dict__) if hasattr(policy, "__dict__") else None,
                "decision_counts": {row["action"]: row["c"] for row in decisions},
            },
        )

    def _handle_run_benchmark(self):
        from urllib.parse import parse_qs, urlparse

        from app.benchmark import run_benchmark

        query = parse_qs(urlparse(self.path).query)
        num_scenarios = int(query.get("n", ["300"])[0])
        seed = int(query.get("seed", ["42"])[0])
        result = run_benchmark(num_scenarios=num_scenarios, seed=seed)
        self._send_json(200, result)

    def _handle_run_redteam(self):
        from app.redteam import run_all

        results = run_all()
        self._send_json(
            200,
            {
                "scenarios": results,
                "all_blocked": all(r["blocked"] for r in results),
                "total": len(results),
            },
        )


def _select_llm_provider() -> LLMProvider:
    """doc upgrade section 9: mode selection is explicit and config-driven,
    never an implicit hardcoded default. Real mode is only ever chosen when
    ANTHROPIC_API_KEY is actually configured; otherwise the mock provider is
    used and clearly labelled 'DEMO / SYNTHETIC PROVIDER' everywhere it
    surfaces (audit records, this docstring). There is no code path that
    silently falls back from real to mock mid-request — a configured-but-
    failing real provider raises LLMProviderError up to the negotiation
    service, which records the failure and continues with strategy=NONE
    (advisory-only; never a fabricated proposal, never a financial action)."""
    if Config.anthropic_configured():
        return ClaudeLLMProvider()
    return MockLLMProvider()  # DEMO / SYNTHETIC PROVIDER


def create_server(host: str = "127.0.0.1", port: int = 8000, db_path: Optional[str] = None):
    if db_path:
        Config.DB_PATH = db_path
    init_db(Config.DB_PATH)
    EconexRequestHandler.llm_provider = _select_llm_provider()
    return ThreadingHTTPServer((host, port), EconexRequestHandler)


if __name__ == "__main__":
    import sys

    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    server = create_server(port=port)
    print(f"ECONEX API listening on http://127.0.0.1:{port} (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()
