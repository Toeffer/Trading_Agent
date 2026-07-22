#!/usr/bin/env python3
"""
openclaw_routing_adapter.py — Phase 18R2 OpenClaw Model-Routing Adapter

SHADOW_ONLY mode. Connects Phase 18R1 logical routing decisions to existing
CODEX/OPENCODE transport bindings. Does not invoke models, change live routing,
or access credentials. Advisory only. Python stdlib only.

Accepts both the original routing request AND the Phase 18R1 routing decision,
validates their mutual integrity, then resolves transport bindings in shadow mode.

Pure function:  resolve_shadow_route(routing_request: dict, routing_decision: dict) -> dict

No prompts, no source code, no provider payloads, no credentials, no orders, no
broker data. No cross-transport fallback. No silent model/transport substitution.
"""

import hashlib
import json
from pathlib import Path
from typing import Any, Optional, Tuple

# ── Transport bindings (repository-tracked, zero secrets) ───────────────────

_HERE = Path(__file__).resolve().parent

# Logical model → (transport, runtime_alias, binding_state)
_LOGICAL_TO_BINDING: dict[str, Tuple[str, str, str]] = {
    "gpt-5.5":         ("CODEX",    "gpt-5.5",         "BOUND_EXISTING_ALIAS"),
    "gpt-5.6-sol":     ("CODEX",    "gpt-5.6-sol",     "UNBOUND"),
    "deepseek-v4-pro": ("OPENCODE", "deepseek-v4-pro",  "UNBOUND"),
    "kimi-k3":         ("OPENCODE", "kimi-k3",          "UNBOUND"),
}

_APPROVED_MODEL_IDS = frozenset(_LOGICAL_TO_BINDING.keys())

# Role → (default_model, escalation_model)
_ROLE_MODEL_MAP = {
    "HERMES": ("gpt-5.5", "gpt-5.6-sol"),
    "OC":     ("deepseek-v4-pro", "kimi-k3"),
}

# Permitted routing states
_VALID_ROUTING_STATES = frozenset({"DEFAULT_ROUTE", "ESCALATED_ROUTE", "HOLD"})

# Phase 18R1 auth flags that must be false
_R1_AUTH_FIELDS = (
    "runtime_invocation_authorized",
    "provider_integration_authorized",
    "credentials_authorized",
    "network_authorized",
    "broker_mutation_authorized",
    "trading_execution_authorized",
)

# Forbidden fields in adapter input (fail-closed if present in decision)
_FORBIDDEN_DECISION_FIELDS = frozenset({
    "prompt", "source_code", "provider_payload", "credentials",
    "order_data", "broker_data", "h1_data", "runtime_alias_override",
    "transport_override", "model_override", "api_key", "access_token",
    "account_id", "credential_path",
})


# ── Canonical hash helpers ──────────────────────────────────────────────────

def _canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _canonical_hash(obj: Any) -> str:
    return hashlib.sha256(_canonical_json(obj).encode("utf-8")).hexdigest()


def _compute_request_hash(request: dict) -> str:
    return _canonical_hash(request)


# ── Validation ──────────────────────────────────────────────────────────────

def _validate_request_decision_pair(
    routing_request: dict,
    routing_decision: dict,
) -> Tuple[bool, list[str]]:
    """
    Validate that the routing_request and routing_decision form a valid,
    un-tampered pair from Phase 18R1.

    Returns (passed, reasons).
    """
    reasons: list[str] = []

    # ── Structural validation ───────────────────────────────────────────────

    if not isinstance(routing_request, dict):
        reasons.append("REQUEST_NOT_DICT")
        return False, reasons
    if not isinstance(routing_decision, dict):
        reasons.append("DECISION_NOT_DICT")
        return False, reasons

    # ── Phase 18R1 governance ID ────────────────────────────────────────────
    gov_id = routing_decision.get("governance_id")
    if gov_id != "model_routing_governance_v0_1":
        reasons.append(f"GOVERNANCE_ID_MISMATCH: got={gov_id}")
    if routing_decision.get("governance_version") != "0.1":
        reasons.append(f"GOVERNANCE_VERSION_MISMATCH: got={routing_decision.get('governance_version')}")

    # ── Deterministic request hash validation ────────────────────────────────
    expected_req_hash = _compute_request_hash(routing_request)
    actual_req_hash = routing_decision.get("deterministic_request_hash", "")
    if len(actual_req_hash) == 64 and actual_req_hash != expected_req_hash:
        reasons.append("REQUEST_HASH_MISMATCH: decision was not computed from this request")

    # ── Decision hash structural check ───────────────────────────────────────
    decision_hash = routing_decision.get("deterministic_decision_hash", "")
    if len(decision_hash) != 64 or not all(c in "0123456789abcdef" for c in decision_hash):
        reasons.append("DECISION_HASH_INVALID")

    # ── Routing state ───────────────────────────────────────────────────────
    routing_state = routing_decision.get("routing_state")
    if routing_state not in _VALID_ROUTING_STATES:
        reasons.append(f"ROUTING_STATE_INVALID: got={routing_state}")

    # ── Forbidden fields (fail-closed) ────────────────────────────────────
    for field in _FORBIDDEN_DECISION_FIELDS:
        if field in routing_decision:
            reasons.append(f"FORBIDDEN_FIELD: {field}")

    # ── Role match ──────────────────────────────────────────────────────────
    rq_role = routing_request.get("role")
    dc_role = routing_decision.get("role")
    if rq_role != dc_role:
        reasons.append(f"ROLE_MISMATCH: request={rq_role} decision={dc_role}")
    if rq_role not in ("HERMES", "OC"):
        reasons.append(f"ROLE_NOT_APPROVED: {rq_role}")

    # ── Task class match ────────────────────────────────────────────────────
    rq_tc = routing_request.get("task_class")
    dc_tc = routing_decision.get("task_class")
    if rq_tc != dc_tc:
        reasons.append(f"TASK_CLASS_MISMATCH: request={rq_tc} decision={dc_tc}")

    # ── Failure counts match ────────────────────────────────────────────────
    for field in ("default_failure_count", "escalation_failure_count"):
        rq_val = routing_request.get(field)
        dc_val = routing_decision.get(field)
        if rq_val != dc_val:
            reasons.append(f"{field.upper()}_MISMATCH: request={rq_val} decision={dc_val}")

    # ── All R1 authorization flags must be false ────────────────────────────
    for field in _R1_AUTH_FIELDS:
        if routing_decision.get(field) is not False:
            reasons.append(f"R1_AUTH_FLAG_TRUE: {field}")

    # ── Advisory and human authority must be true ───────────────────────────
    if routing_decision.get("advisory_only") is not True:
        reasons.append("R1_ADVISORY_ONLY_FALSE")
    if routing_decision.get("human_final_authority") is not True:
        reasons.append("R1_HUMAN_FINAL_AUTHORITY_FALSE")

    # ── Trading autonomy ────────────────────────────────────────────────────
    if routing_decision.get("trading_autonomy_unchanged") is not True:
        reasons.append("R1_TRADING_AUTONOMY_CHANGED")

    # ── Selected model approved ─────────────────────────────────────────────
    selected_model = routing_decision.get("selected_model_id")
    if routing_state in ("DEFAULT_ROUTE", "ESCALATED_ROUTE"):
        if selected_model not in _APPROVED_MODEL_IDS:
            reasons.append(f"SELECTED_MODEL_NOT_APPROVED: {selected_model}")
        # Model must match role and route tier
        if rq_role in _ROLE_MODEL_MAP:
            default_m, escal_m = _ROLE_MODEL_MAP[rq_role]
            route_tier = routing_decision.get("selected_route_tier")
            if route_tier == "DEFAULT" and selected_model != default_m:
                reasons.append(f"DEFAULT_MODEL_MISMATCH: expected={default_m} got={selected_model}")
            elif route_tier == "ESCALATION" and selected_model != escal_m:
                reasons.append(f"ESCALATION_MODEL_MISMATCH: expected={escal_m} got={selected_model}")

    # ── Cross-transport check ───────────────────────────────────────────────
    if selected_model in _LOGICAL_TO_BINDING:
        expected_transport = _LOGICAL_TO_BINDING[selected_model][0]
        if rq_role == "HERMES" and expected_transport != "CODEX":
            reasons.append(f"CROSS_TRANSPORT_BLOCKED: hermes model {selected_model} maps to {expected_transport}")
        if rq_role == "OC" and expected_transport != "OPENCODE":
            reasons.append(f"CROSS_TRANSPORT_BLOCKED: oc model {selected_model} maps to {expected_transport}")

    return (len(reasons) == 0, reasons)


# ── Adapter decision engine ─────────────────────────────────────────────────

def _build_adapter_decision(
    adapter_state: str,
    routing_request: dict,
    routing_decision: dict,
    validation_passed: bool,
    validation_reasons: list[str],
    transport: Optional[str],
    runtime_alias: Optional[str],
    binding_state: Optional[str],
    selected_model_id: Optional[str],
) -> dict:
    """Build a canonical adapter decision."""

    r1_routing_state = routing_decision.get("routing_state", "UNKNOWN")
    route_tier = routing_decision.get("selected_route_tier")
    role = routing_decision.get("role", routing_request.get("role", "UNKNOWN"))
    task_class = routing_decision.get("task_class", routing_request.get("task_class", "UNKNOWN"))

    # Inherit Phase 18R1 rationale codes when validation passes
    rationale_codes: list[Any] = []
    if validation_passed:
        rationale_codes = list(routing_decision.get("rationale_codes", []))
        # Include adapter-level reasons for HOLD states
        if adapter_state == "HOLD":
            rationale_codes.extend(validation_reasons)
    else:
        rationale_codes = ["ADAPTER_VALIDATION_FAILURE"] + validation_reasons

    base = {
        "adapter_schema_version": "0.1",
        "governance_id": "openclaw_routing_adapter_v0_1",
        "governance_version": "0.1",
        "adapter_state": adapter_state,
        "adapter_mode": "SHADOW_ONLY",
        "phase18r1_routing_state": r1_routing_state,
        "role": role,
        "task_class": task_class,
        "logical_model_id": selected_model_id,
        "selected_route_tier": route_tier,
        "selected_transport": transport,
        "selected_runtime_alias": runtime_alias,
        "binding_state": binding_state,
        "rationale_codes": rationale_codes,
        "shadow_resolution_only": True,
        "live_routing_changed": False,
        "human_activation_required": True,
        "human_final_authority": True,
        "adapter_invocation_authorized": False,
        "runtime_invocation_authorized": False,
        "direct_provider_integration_authorized": False,
        "direct_credentials_authorized": False,
        "direct_network_authorized": False,
        "broker_mutation_authorized": False,
        "trading_execution_authorized": False,
        "trading_autonomy_unchanged": True,
        "deterministic_request_hash": routing_decision.get("deterministic_request_hash",
                                                           _compute_request_hash(routing_request)),
        "upstream_decision_hash": routing_decision.get("deterministic_decision_hash", ""),
    }

    # adapter-specific hashing (self-exclusion)
    no_hash = {k: v for k, v in base.items() if k != "deterministic_adapter_hash"}
    base["deterministic_adapter_hash"] = _canonical_hash(no_hash)

    return base


def resolve_shadow_route(
    routing_request: dict,
    routing_decision: dict,
) -> dict:
    """
    Resolve a Phase 18R1 logical routing decision to a transport binding in
    SHADOW_ONLY mode. No model invocation. No live routing change.

    Args:
        routing_request: The original Phase 18R1 routing request dict.
        routing_decision: The Phase 18R1 decision dict from decide_model_route().

    Returns:
        An adapter decision with adapter_state (SHADOW_ROUTE_RESOLVED | HOLD),
        transport binding, and all authorization flags.
    """
    r1_routing_state = routing_decision.get("routing_state", "HOLD")
    selected_model_id = routing_decision.get("selected_model_id")

    # ── Validate request-decision pair ──────────────────────────────────────
    valid, reasons = _validate_request_decision_pair(routing_request, routing_decision)

    if not valid:
        return _build_adapter_decision(
            adapter_state="HOLD",
            routing_request=routing_request,
            routing_decision=routing_decision,
            validation_passed=False,
            validation_reasons=reasons,
            transport=None,
            runtime_alias=None,
            binding_state=None,
            selected_model_id=selected_model_id if selected_model_id in _APPROVED_MODEL_IDS else None,
        )

    # ── Phase 18R1 HOLD → adapter HOLD (must not resolve) ──────────────────
    if r1_routing_state == "HOLD":
        return _build_adapter_decision(
            adapter_state="HOLD",
            routing_request=routing_request,
            routing_decision=routing_decision,
            validation_passed=True,
            validation_reasons=[],
            transport=None,
            runtime_alias=None,
            binding_state=None,
            selected_model_id=None,
        )

    # ── Resolve transport binding ──────────────────────────────────────────
    if selected_model_id and selected_model_id in _LOGICAL_TO_BINDING:
        transport, runtime_alias, binding_state = _LOGICAL_TO_BINDING[selected_model_id]
    else:
        # Should not reach here after validation, but fail-closed
        return _build_adapter_decision(
            adapter_state="HOLD",
            routing_request=routing_request,
            routing_decision=routing_decision,
            validation_passed=True,
            validation_reasons=[f"UNRESOLVABLE_MODEL: {selected_model_id}"],
            transport=None,
            runtime_alias=None,
            binding_state=None,
            selected_model_id=None,
        )

    # ── UNBOUND → HOLD ────────────────────────────────────────────────────
    if binding_state == "UNBOUND":
        return _build_adapter_decision(
            adapter_state="HOLD",
            routing_request=routing_request,
            routing_decision=routing_decision,
            validation_passed=True,
            validation_reasons=[f"MODEL_NOT_BOUND: {selected_model_id} binding_state=UNBOUND, not directly observed in transport registry"],
            transport=transport,
            runtime_alias=None,
            binding_state="UNBOUND",
            selected_model_id=selected_model_id,
        )

    # ── SHADOW_ROUTE_RESOLVED (BOUND_EXISTING_ALIAS only) ──────────────────
    return _build_adapter_decision(
        adapter_state="SHADOW_ROUTE_RESOLVED",
        routing_request=routing_request,
        routing_decision=routing_decision,
        validation_passed=True,
        validation_reasons=[],
        transport=transport,
        runtime_alias=runtime_alias,
        binding_state=binding_state,
        selected_model_id=selected_model_id,
    )


# ── CLI entry ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    if len(sys.argv) != 3:
        print("Usage: python3 openclaw_routing_adapter.py <request.json> <decision.json>", file=sys.stderr)
        print("       Use '-' for either file to read from stdin.", file=sys.stderr)
        sys.exit(2)

    def _read_arg(arg: str) -> str:
        if arg == "-":
            return sys.stdin.read()
        return Path(arg).read_text()

    try:
        request = json.loads(_read_arg(sys.argv[1]))
        decision = json.loads(_read_arg(sys.argv[2]))
    except json.JSONDecodeError as e:
        print(json.dumps({"adapter_state": "HOLD", "error": f"Malformed JSON: {e}"}, indent=2, sort_keys=True))
        sys.exit(1)

    result = resolve_shadow_route(request, decision)
    print(json.dumps(result, indent=2, sort_keys=True))
    sys.exit(0 if result["adapter_state"] == "SHADOW_ROUTE_RESOLVED" else 1)
