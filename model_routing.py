#!/usr/bin/env python3
"""
model_routing.py — Phase 18R1 Deterministic Model-Routing Decision Engine

Advisory only. Dry-run only. No model invocation. No network. No subprocess.
No bridge, no guard, no broker, no provider SDK. Python stdlib only.

Pure function:  decide_model_route(request: dict) -> dict
"""

import hashlib
import json
import os
from pathlib import Path
from typing import Any

# ── Catalog & Policy (loaded lazily, relative to this file) ────────────────

_HERE = Path(__file__).resolve().parent
_MODEL_ROUTING_DIR = _HERE / "docs" / "model-routing"

_CATALOG_PATH = _MODEL_ROUTING_DIR / "MODEL_CATALOG_v0_1.json"
_POLICY_PATH = _MODEL_ROUTING_DIR / "MODEL_ROUTING_POLICY_v0_1.json"

# Approved model IDs (exactly four)
_APPROVED_MODEL_IDS = frozenset({"gpt-5.5", "gpt-5.6-sol", "deepseek-v4-pro", "kimi-k3"})

# Role→model assignments (exact)
_HERMES_DEFAULT_MODEL = "gpt-5.5"
_HERMES_ESCALATION_MODEL = "gpt-5.6-sol"
_OC_DEFAULT_MODEL = "deepseek-v4-pro"
_OC_ESCALATION_MODEL = "kimi-k3"

# Route tier constants
_DEFAULT = "DEFAULT"
_ESCALATION = "ESCALATION"
_HOLD = "HOLD"

# Terminal routing states
_DEFAULT_ROUTE = "DEFAULT_ROUTE"
_ESCALATED_ROUTE = "ESCALATED_ROUTE"

# Hard-stop flags (must all be present in request)
_HARD_STOP_FLAGS = [
    "safety_boundary_violation_detected",
    "protected_file_change_detected",
    "test_weakening_detected",
    "unauthorized_runtime_mutation_detected",
    "credential_exposure_detected",
    "unapproved_network_access_detected",
    "unapproved_model_requested",
    "broker_mutation_requested",
    "h1_access_requested",
    "trading_execution_requested",
    "order_path_requested",
    "approval_path_requested",
    "preflight_path_requested",
    "submission_path_requested",
    "strategy_or_allowlist_change_requested",
]

# Required model availability keys
_REQUIRED_AVAILABILITY = frozenset({"gpt-5.5", "gpt-5.6-sol", "deepseek-v4-pro", "kimi-k3"})

# Permitted request top-level keys
_PERMITTED_REQUEST_KEYS = frozenset({
    "request_schema_version", "role", "task_class",
    "default_failure_count", "escalation_failure_count",
    "manual_escalation_requested", "model_availability",
    "hard_stop_flags",
})

# HERMES escalation task classes
_HERMES_ESCALATION_TASKS = frozenset({
    "PHASE_ARCHITECTURE", "SAFETY_GOVERNANCE", "SPEC_TEST_CONFLICT",
    "FAIL_CLOSED_DIAGNOSIS", "FINAL_CLOSURE_REVIEW",
})

# OC escalation task classes
_OC_ESCALATION_TASKS = frozenset({
    "CROSS_FILE_ARCHITECTURAL_REFACTOR", "REPEATED_CI_RECOVERY",
    "SAFETY_CRITICAL_IMPLEMENTATION", "SPECIFICATION_AMBIGUITY",
    "TOOL_DISCIPLINE_RECOVERY",
})


# ── Canonical hash helpers ──────────────────────────────────────────────────

def _canonical_json(obj: Any) -> str:
    """Deterministic JSON serialization: sorted keys, no whitespace, ensure_ascii."""
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _canonical_hash(obj: Any) -> str:
    """SHA-256 of canonical JSON."""
    return hashlib.sha256(_canonical_json(obj).encode("utf-8")).hexdigest()


def _compute_request_hash(request: dict) -> str:
    """Deterministic request hash: exclude host, path, time, env, pid."""
    return _canonical_hash(request)


def _compute_decision_hash(decision: dict) -> str:
    """Deterministic decision hash: exclude deterministic_decision_hash itself."""
    no_hash = {k: v for k, v in decision.items() if k != "deterministic_decision_hash"}
    return _canonical_hash(no_hash)


# ── Validation ──────────────────────────────────────────────────────────────

def _validate_request(request: dict) -> list[str]:
    """Validate a routing request. Returns list of error strings (empty = valid)."""
    errors: list[str] = []

    if not isinstance(request, dict):
        return ["Request must be a JSON object"]

    # Reject unknown top-level keys
    extra_keys = set(request.keys()) - _PERMITTED_REQUEST_KEYS
    if extra_keys:
        errors.append(f"Unknown top-level keys: {sorted(extra_keys)}")

    # Required fields
    for field in ["request_schema_version", "role", "task_class",
                   "default_failure_count", "escalation_failure_count",
                   "manual_escalation_requested", "model_availability",
                   "hard_stop_flags"]:
        if field not in request:
            errors.append(f"Missing required field: {field}")

    if errors:
        return errors

    # Type checks
    if request.get("request_schema_version") != "0.1":
        errors.append(f"Invalid request_schema_version: {request.get('request_schema_version')}")

    if request.get("role") not in ("HERMES", "OC"):
        errors.append(f"Invalid role: {request.get('role')}")

    if not isinstance(request.get("task_class"), str):
        errors.append("task_class must be a string")

    dfc = request.get("default_failure_count")
    if not isinstance(dfc, int) or dfc < 0:
        errors.append(f"default_failure_count must be non-negative integer, got {dfc}")

    efc = request.get("escalation_failure_count")
    if not isinstance(efc, int) or efc < 0:
        errors.append(f"escalation_failure_count must be non-negative integer, got {efc}")

    if not isinstance(request.get("manual_escalation_requested"), bool):
        errors.append("manual_escalation_requested must be boolean")

    # model_availability validation
    ma = request.get("model_availability")
    if not isinstance(ma, dict):
        errors.append("model_availability must be an object")
    else:
        avail_keys = set(ma.keys())
        if avail_keys != _REQUIRED_AVAILABILITY:
            missing = _REQUIRED_AVAILABILITY - avail_keys
            extra = avail_keys - _REQUIRED_AVAILABILITY
            if missing:
                errors.append(f"model_availability missing keys: {sorted(missing)}")
            if extra:
                errors.append(f"model_availability extra keys: {sorted(extra)}")
        for k, v in ma.items():
            if k in _REQUIRED_AVAILABILITY and not isinstance(v, bool):
                errors.append(f"model_availability.{k} must be boolean")

    # hard_stop_flags validation
    hsf = request.get("hard_stop_flags")
    if not isinstance(hsf, dict):
        errors.append("hard_stop_flags must be an object")
    else:
        for flag in _HARD_STOP_FLAGS:
            if flag not in hsf:
                errors.append(f"hard_stop_flags missing: {flag}")
            elif not isinstance(hsf[flag], bool):
                errors.append(f"hard_stop_flags.{flag} must be boolean")
        extra_flags = set(hsf.keys()) - set(_HARD_STOP_FLAGS)
        if extra_flags:
            errors.append(f"hard_stop_flags unknown keys: {sorted(extra_flags)}")

    return errors


# ── Decision engine ─────────────────────────────────────────────────────────

def _any_hard_stop(hard_stop_flags: dict) -> bool:
    """Return True if any hard-stop safety flag is true."""
    return any(hard_stop_flags.get(f, False) for f in _HARD_STOP_FLAGS)


def _hold_decision(request: dict, rationale_codes: list[str]) -> dict:
    """Build a HOLD decision."""
    base = {
        "decision_schema_version": "0.1",
        "governance_id": "model_routing_governance_v0_1",
        "governance_version": "0.1",
        "routing_state": _HOLD,
        "role": request["role"],
        "task_class": request["task_class"],
        "selected_model_id": None,
        "selected_route_tier": None,
        "rationale_codes": rationale_codes,
        "default_failure_count": request["default_failure_count"],
        "escalation_failure_count": request["escalation_failure_count"],
        "retry_budget": 0,
        "manual_review_required": True,
        "advisory_only": True,
        "human_final_authority": True,
        "runtime_invocation_authorized": False,
        "provider_integration_authorized": False,
        "credentials_authorized": False,
        "network_authorized": False,
        "broker_mutation_authorized": False,
        "trading_execution_authorized": False,
        "trading_autonomy_unchanged": True,
    }
    req_hash = _compute_request_hash(request)
    base["deterministic_request_hash"] = req_hash
    base["deterministic_decision_hash"] = _compute_decision_hash(base)
    return base


def _route_decision(request: dict, model_id: str, route_tier: str,
                    rationale_codes: list[str], retry_budget: int) -> dict:
    """Build a DEFAULT_ROUTE or ESCALATED_ROUTE decision."""
    routing_state = _DEFAULT_ROUTE if route_tier == _DEFAULT else _ESCALATED_ROUTE
    base = {
        "decision_schema_version": "0.1",
        "governance_id": "model_routing_governance_v0_1",
        "governance_version": "0.1",
        "routing_state": routing_state,
        "role": request["role"],
        "task_class": request["task_class"],
        "selected_model_id": model_id,
        "selected_route_tier": route_tier,
        "rationale_codes": rationale_codes,
        "default_failure_count": request["default_failure_count"],
        "escalation_failure_count": request["escalation_failure_count"],
        "retry_budget": retry_budget,
        "manual_review_required": False,
        "advisory_only": True,
        "human_final_authority": True,
        "runtime_invocation_authorized": False,
        "provider_integration_authorized": False,
        "credentials_authorized": False,
        "network_authorized": False,
        "broker_mutation_authorized": False,
        "trading_execution_authorized": False,
        "trading_autonomy_unchanged": True,
    }
    req_hash = _compute_request_hash(request)
    base["deterministic_request_hash"] = req_hash
    base["deterministic_decision_hash"] = _compute_decision_hash(base)
    return base


def decide_model_route(request: dict) -> dict:
    """
    Pure deterministic model-routing decision.

    Args:
        request: A dict conforming to the routing request schema.

    Returns:
        A decision dict with routing_state, selected_model_id, etc.
        HOLD decisions have selected_model_id=null and manual_review_required=True.
    """
    # 0. Non-dict guard
    if not isinstance(request, dict):
        return {
            "decision_schema_version": "0.1",
            "governance_id": "model_routing_governance_v0_1",
            "governance_version": "0.1",
            "routing_state": "HOLD",
            "role": "UNKNOWN",
            "task_class": "UNKNOWN",
            "selected_model_id": None,
            "selected_route_tier": None,
            "rationale_codes": ["VALIDATION_ERROR: Request must be a JSON object"],
            "default_failure_count": 0,
            "escalation_failure_count": 0,
            "retry_budget": 0,
            "manual_review_required": True,
            "advisory_only": True,
            "human_final_authority": True,
            "runtime_invocation_authorized": False,
            "provider_integration_authorized": False,
            "credentials_authorized": False,
            "network_authorized": False,
            "broker_mutation_authorized": False,
            "trading_execution_authorized": False,
            "trading_autonomy_unchanged": True,
            "deterministic_request_hash": hashlib.sha256(b"non-dict-request").hexdigest(),
            "deterministic_decision_hash": "",
        }

    # 1. Validate request
    errors = _validate_request(request)
    if errors:
        return _hold_decision(request, [f"VALIDATION_ERROR: {e}" for e in errors])

    role = request["role"]
    task_class = request["task_class"]
    default_failures = request["default_failure_count"]
    escalation_failures = request["escalation_failure_count"]
    manual_escalation = request["manual_escalation_requested"]
    availability = request["model_availability"]
    hard_stops = request["hard_stop_flags"]

    # 2. Hard-stop check (universal, must produce HOLD)
    if _any_hard_stop(hard_stops):
        triggered = [f for f in _HARD_STOP_FLAGS if hard_stops.get(f)]
        return _hold_decision(request, [f"HARD_STOP: {t}" for t in triggered])

    # 3. Role-specific routing
    if role == "HERMES":
        return _decide_hermes(task_class, default_failures, escalation_failures,
                              manual_escalation, availability, request)
    else:  # OC
        return _decide_oc(task_class, default_failures, escalation_failures,
                          manual_escalation, availability, request)


def _decide_hermes(task_class: str, default_failures: int, escalation_failures: int,
                   manual_escalation: bool, availability: dict, request: dict) -> dict:
    """HERMES role routing logic."""

    # Escalation failure → HOLD
    if escalation_failures >= 1:
        return _hold_decision(request, ["HERMES_ESCALATION_FAILURE_LIMIT"])

    # Escalation model unavailable for escalation-required → HOLD
    escalation_required = (
        task_class in _HERMES_ESCALATION_TASKS or
        default_failures >= 1 or
        manual_escalation
    )
    if escalation_required and not availability.get(_HERMES_ESCALATION_MODEL, False):
        return _hold_decision(request, ["HERMES_ESCALATION_UNAVAILABLE"])

    # Escalation triggers
    if task_class in _HERMES_ESCALATION_TASKS:
        return _route_decision(request, _HERMES_ESCALATION_MODEL, _ESCALATION,
                               [f"HERMES_TASK_ESCALATION: {task_class}"], 1)

    if manual_escalation:
        return _route_decision(request, _HERMES_ESCALATION_MODEL, _ESCALATION,
                               ["HERMES_MANUAL_ESCALATION"], 1)

    if default_failures >= 1:
        return _route_decision(request, _HERMES_ESCALATION_MODEL, _ESCALATION,
                               ["HERMES_DEFAULT_FAILURE_ESCALATION"], 1)

    # Default model unavailable → HOLD (HERMES cannot auto-escalate to gpt-5.6-sol
    # without an escalation trigger)
    if not availability.get(_HERMES_DEFAULT_MODEL, False):
        return _hold_decision(request, ["HERMES_DEFAULT_UNAVAILABLE"])

    # Default route
    return _route_decision(request, _HERMES_DEFAULT_MODEL, _DEFAULT,
                           ["HERMES_DEFAULT_ROUTE"], 1)


def _decide_oc(task_class: str, default_failures: int, escalation_failures: int,
               manual_escalation: bool, availability: dict, request: dict) -> dict:
    """OC role routing logic."""

    # Escalation failure → HOLD
    if escalation_failures >= 1:
        return _hold_decision(request, ["OC_ESCALATION_FAILURE_LIMIT"])

    default_avail = availability.get(_OC_DEFAULT_MODEL, False)
    escalation_avail = availability.get(_OC_ESCALATION_MODEL, False)

    # Both unavailable → HOLD
    if not default_avail and not escalation_avail:
        return _hold_decision(request, ["OC_BOTH_MODELS_UNAVAILABLE"])

    # Escalation required
    escalation_required = (
        task_class in _OC_ESCALATION_TASKS or
        default_failures >= 2 or
        manual_escalation
    )

    # Default unavailable with escalation available → escalate
    if not default_avail and escalation_avail:
        return _route_decision(request, _OC_ESCALATION_MODEL, _ESCALATION,
                               ["OC_DEFAULT_UNAVAILABLE_ESCALATE"], 1)

    # Escalation required but escalation unavailable → HOLD
    if escalation_required and not escalation_avail:
        return _hold_decision(request, ["OC_ESCALATION_UNAVAILABLE"])

    # Escalation triggers
    if task_class in _OC_ESCALATION_TASKS:
        return _route_decision(request, _OC_ESCALATION_MODEL, _ESCALATION,
                               [f"OC_TASK_ESCALATION: {task_class}"], 1)

    if manual_escalation:
        return _route_decision(request, _OC_ESCALATION_MODEL, _ESCALATION,
                               ["OC_MANUAL_ESCALATION"], 1)

    if default_failures >= 2:
        return _route_decision(request, _OC_ESCALATION_MODEL, _ESCALATION,
                               ["OC_DEFAULT_FAILURE_ESCALATION"], 1)

    # Default route
    return _route_decision(request, _OC_DEFAULT_MODEL, _DEFAULT,
                           ["OC_DEFAULT_ROUTE"], 2)


# ── Optional CLI entry point (used for testing, not runtime activation) ─────

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python3 model_routing.py <request.json>", file=sys.stderr)
        sys.exit(2)

    input_path = sys.argv[1]
    if input_path == "-":
        raw = sys.stdin.read()
    else:
        raw = Path(input_path).read_text()

    try:
        request = json.loads(raw)
    except json.JSONDecodeError as e:
        result = _hold_decision(
            {"role": "UNKNOWN", "task_class": "UNKNOWN",
             "default_failure_count": 0, "escalation_failure_count": 0,
             "manual_escalation_requested": False,
             "model_availability": {"gpt-5.5": False, "gpt-5.6-sol": False,
                                    "deepseek-v4-pro": False, "kimi-k3": False},
             "hard_stop_flags": {f: False for f in _HARD_STOP_FLAGS}},
            [f"MALFORMED_JSON: {e}"]
        )
        print(json.dumps(result, indent=2, sort_keys=True))
        sys.exit(1)

    result = decide_model_route(request)
    print(json.dumps(result, indent=2, sort_keys=True))

    if result["routing_state"] == "HOLD":
        sys.exit(1)
    sys.exit(0)
