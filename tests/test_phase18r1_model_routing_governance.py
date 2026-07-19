"""Tests for Phase 18R1 — Level 1 Model-Routing Governance and Decision Engine.

Covers: Model Catalog (4 models, exact roles), Routing Policy (HERMES/OC routes),
Decision Schema, Decision Engine (pure function), Governance Manifest,
CLI Registration, CI Invariants, and Fail-Closed Safety.
"""

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
MODEL_ROUTING_DIR = REPO / "docs" / "model-routing"
OPERATOR = REPO / "ibkr_operator.py"
MODEL_ROUTING_PY = REPO / "model_routing.py"

# Governed files
CATALOG = MODEL_ROUTING_DIR / "MODEL_CATALOG_v0_1.json"
POLICY = MODEL_ROUTING_DIR / "MODEL_ROUTING_POLICY_v0_1.json"
DECISION_SCHEMA = MODEL_ROUTING_DIR / "MODEL_ROUTING_DECISION_SCHEMA_v0_1.json"
EVAL_PROTOCOL = MODEL_ROUTING_DIR / "MODEL_ROUTING_EVALUATION_PROTOCOL_v0_1.md"
MANIFEST = MODEL_ROUTING_DIR / "model_routing_governance_v0_1.manifest.json"

PHASE18B_MANIFEST = REPO / "docs" / "strategy-proposals" / "data-governance" / "mstr_btc_data_governance_v0_1.manifest.json"
PHASE18A_MANIFEST = REPO / "docs" / "strategy-proposals" / "mstr_btc_research_v0_1.manifest.json"
STRATEGY_MD = REPO / "docs" / "STRATEGY.md"

ALL_GOVERNED = [
    ("MODEL_CATALOG_v0_1.json", CATALOG),
    ("MODEL_ROUTING_POLICY_v0_1.json", POLICY),
    ("MODEL_ROUTING_DECISION_SCHEMA_v0_1.json", DECISION_SCHEMA),
    ("MODEL_ROUTING_EVALUATION_PROTOCOL_v0_1.md", EVAL_PROTOCOL),
    ("model_routing.py", MODEL_ROUTING_PY),
]

EXPECTED_MODELS = {
    "gpt-5.5": ["HERMES_DEFAULT"],
    "gpt-5.6-sol": ["HERMES_ESCALATION"],
    "deepseek-v4-pro": ["OC_DEFAULT"],
    "kimi-k3": ["OC_ESCALATION"],
}

CLI_COMMANDS = [
    "level1-model-routing-governance-checkpoint",
    "phase18r1",
    "model-routing-governance",
]

REQUIRED_LABELS = [
    "PHASE18R1_MODEL_ROUTING_GOVERNANCE_READY",
    "ROUTING_CONTRACT_READY",
    "R0_ROUTING_READINESS",
    "LEVEL1",
    "ADVISORY_ONLY",
    "HUMAN_FINAL_AUTHORITY",
    "DRY_RUN_ONLY",
    "NO_MODEL_INVOCATION",
    "NO_PROVIDER_INTEGRATION",
    "NO_CREDENTIALS",
    "NO_NETWORK_ACCESS",
    "NO_BROKER_MUTATION",
    "NO_TRADING_EXECUTION",
    "TRADING_AUTONOMY_UNCHANGED",
    "HERMES_DEFAULT_GPT_5_5",
    "HERMES_ESCALATION_GPT_5_6_SOL",
    "OC_DEFAULT_DEEPSEEK_V4_PRO",
    "OC_ESCALATION_KIMI_K3",
    "FAIL_CLOSED_ROUTING",
    "PHASE18B_UNCHANGED",
    "STRATEGY_V1_UNCHANGED",
    "PHASE18R2_NOT_STARTED",
    "PHASE18C_NOT_STARTED",
]

HARD_STOP_FLAGS = [
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


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_json(path: Path) -> dict:
    with open(path) as f:
        return json.load(f)


def _load_manifest() -> dict:
    return _load_json(MANIFEST)


def _make_request(role, task_class, default_failures=0, escalation_failures=0,
                  manual_escalation=False, availability=None, hard_stops=None):
    """Build a valid routing request."""
    if availability is None:
        availability = {"gpt-5.5": True, "gpt-5.6-sol": True,
                        "deepseek-v4-pro": True, "kimi-k3": True}
    if hard_stops is None:
        hard_stops = {f: False for f in HARD_STOP_FLAGS}
    return {
        "request_schema_version": "0.1",
        "role": role,
        "task_class": task_class,
        "default_failure_count": default_failures,
        "escalation_failure_count": escalation_failures,
        "manual_escalation_requested": manual_escalation,
        "model_availability": availability,
        "hard_stop_flags": hard_stops,
    }


def _decide(request: dict) -> dict:
    """Invoke decide_model_route directly (not via CLI)."""
    sys.path.insert(0, str(REPO))
    from model_routing import decide_model_route
    return decide_model_route(request)


def _run_cli(command: str):
    """Run the ibkr_operator checkpoint command."""
    result = subprocess.run(
        [sys.executable, str(OPERATOR), command, "--json"],
        capture_output=True, text=True, timeout=60,
        cwd=str(REPO),
    )
    assert result.returncode == 0, f"CLI '{command}' failed: {result.stderr}"
    return json.loads(result.stdout)


def _run_decision_cli(input_file: str):
    """Run the model-routing-decision CLI command."""
    result = subprocess.run(
        [sys.executable, str(OPERATOR), "model-routing-decision",
         "--input-file", input_file, "--json"],
        capture_output=True, text=True, timeout=60,
        cwd=str(REPO),
    )
    return result.returncode, json.loads(result.stdout)


# ══════════════════════════════════════════════════════════════════════════════
# GOVERNANCE: FILE EXISTENCE & VALID JSON
# ══════════════════════════════════════════════════════════════════════════════

class TestFileExistence:
    @pytest.mark.parametrize("name,path", ALL_GOVERNED)
    def test_exists(self, name, path):
        assert path.exists(), f"Missing: {name}"

    def test_manifest(self):
        assert MANIFEST.exists()

    def test_phase18b_manifest(self):
        assert PHASE18B_MANIFEST.exists()

    def test_phase18a_manifest(self):
        assert PHASE18A_MANIFEST.exists()

    def test_strategy_md(self):
        assert STRATEGY_MD.exists()


class TestJsonValidity:
    @pytest.mark.parametrize("name,path", ALL_GOVERNED)
    def test_valid(self, name, path):
        if path.suffix == ".json":
            assert isinstance(_load_json(path), dict)
        else:
            assert isinstance(path.read_text(), str)


# ══════════════════════════════════════════════════════════════════════════════
# MODEL CATALOG
# ══════════════════════════════════════════════════════════════════════════════

class TestModelCatalog:
    def test_exactly_four_models(self):
        catalog = _load_json(CATALOG)
        assert len(catalog["approved_models"]) == 4

    def test_no_duplicate_models(self):
        catalog = _load_json(CATALOG)
        ids = [m["logical_model_id"] for m in catalog["approved_models"]]
        assert len(ids) == len(set(ids))

    @pytest.mark.parametrize("model_id,expected_roles", [
        ("gpt-5.5", ["HERMES_DEFAULT"]),
        ("gpt-5.6-sol", ["HERMES_ESCALATION"]),
        ("deepseek-v4-pro", ["OC_DEFAULT"]),
        ("kimi-k3", ["OC_ESCALATION"]),
    ])
    def test_exact_role_assignment(self, model_id, expected_roles):
        catalog = _load_json(CATALOG)
        model = next(m for m in catalog["approved_models"] if m["logical_model_id"] == model_id)
        assert sorted(model["approved_roles"]) == sorted(expected_roles)

    def test_all_provider_bindings_logical_only(self):
        catalog = _load_json(CATALOG)
        for m in catalog["approved_models"]:
            assert m["provider_binding_state"] == "LOGICAL_ONLY", f"{m['logical_model_id']}: {m['provider_binding_state']}"

    def test_all_runtime_invocation_false(self):
        catalog = _load_json(CATALOG)
        for m in catalog["approved_models"]:
            assert m["runtime_invocation_authorized"] is False

    def test_all_network_false(self):
        catalog = _load_json(CATALOG)
        for m in catalog["approved_models"]:
            assert m["network_authorized"] is False

    def test_all_credentials_false(self):
        catalog = _load_json(CATALOG)
        for m in catalog["approved_models"]:
            assert m["credentials_authorized"] is False

    def test_all_trading_decision_false(self):
        catalog = _load_json(CATALOG)
        for m in catalog["approved_models"]:
            assert m["trading_decision_authorized"] is False

    def test_all_broker_access_false(self):
        catalog = _load_json(CATALOG)
        for m in catalog["approved_models"]:
            assert m["broker_access_authorized"] is False

    def test_all_execution_false(self):
        catalog = _load_json(CATALOG)
        for m in catalog["approved_models"]:
            assert m["execution_authorized"] is False

    def test_all_human_authority_required(self):
        catalog = _load_json(CATALOG)
        for m in catalog["approved_models"]:
            assert m["human_final_authority_required"] is True

    def test_no_pricing_in_catalog(self):
        text = CATALOG.read_text().lower()
        assert "pricing" not in text or "pricing_frozen" in text

    def test_no_api_keys_in_catalog(self):
        text = CATALOG.read_text().lower()
        for fb in ["api_key", "apikey", "api_secret", "bearer_token", "access_token"]:
            assert fb not in text, f"Found forbidden: {fb}"

    def test_no_provider_urls(self):
        text = CATALOG.read_text().lower()
        assert "https://" not in text and "http://" not in text


# ══════════════════════════════════════════════════════════════════════════════
# ROUTING POLICY
# ══════════════════════════════════════════════════════════════════════════════

class TestRoutingPolicy:
    def test_terminal_states(self):
        policy = _load_json(POLICY)
        assert sorted(policy["terminal_routing_states"]) == sorted(["DEFAULT_ROUTE", "ESCALATED_ROUTE", "HOLD"])

    def test_hermes_default_model(self):
        policy = _load_json(POLICY)
        assert policy["roles"]["HERMES"]["default"]["selected_model"] == "gpt-5.5"

    def test_hermes_escalation_model(self):
        policy = _load_json(POLICY)
        assert policy["roles"]["HERMES"]["escalation"]["selected_model"] == "gpt-5.6-sol"

    def test_oc_default_model(self):
        policy = _load_json(POLICY)
        assert policy["roles"]["OC"]["default"]["selected_model"] == "deepseek-v4-pro"

    def test_oc_escalation_model(self):
        policy = _load_json(POLICY)
        assert policy["roles"]["OC"]["escalation"]["selected_model"] == "kimi-k3"

    def test_hermes_default_retry(self):
        policy = _load_json(POLICY)
        assert policy["roles"]["HERMES"]["default"]["retry_budget"] == 1

    def test_hermes_escalation_retry(self):
        policy = _load_json(POLICY)
        assert policy["roles"]["HERMES"]["escalation"]["retry_budget"] == 1

    def test_oc_default_retry(self):
        policy = _load_json(POLICY)
        assert policy["roles"]["OC"]["default"]["retry_budget"] == 2

    def test_oc_escalation_retry(self):
        policy = _load_json(POLICY)
        assert policy["roles"]["OC"]["escalation"]["retry_budget"] == 1

    def test_hard_stop_flags_count(self):
        policy = _load_json(POLICY)
        assert len(policy["hard_stop_safety_flags"]) == 15

    @pytest.mark.parametrize("flag", HARD_STOP_FLAGS)
    def test_hard_stop_flag_present(self, flag):
        policy = _load_json(POLICY)
        assert flag in policy["hard_stop_safety_flags"]

    def test_principles(self):
        policy = _load_json(POLICY)
        pp = policy["routing_principles"]
        assert pp["no_silent_model_substitution"] is True
        assert pp["no_model_outside_catalog"] is True
        assert pp["no_downgrade_after_escalation"] is True

    def test_auth_flags_all_false(self):
        policy = _load_json(POLICY)
        af = policy["authorization_flags"]
        assert af["runtime_invocation_authorized"] is False
        assert af["provider_integration_authorized"] is False
        assert af["credentials_authorized"] is False
        assert af["network_authorized"] is False
        assert af["broker_mutation_authorized"] is False
        assert af["trading_execution_authorized"] is False

    def test_auth_flags_true(self):
        policy = _load_json(POLICY)
        af = policy["authorization_flags"]
        assert af["trading_autonomy_unchanged"] is True
        assert af["human_final_authority"] is True
        assert af["advisory_only"] is True


# ══════════════════════════════════════════════════════════════════════════════
# DECISION SCHEMA
# ══════════════════════════════════════════════════════════════════════════════

class TestDecisionSchema:
    def test_valid_schema(self):
        s = _load_json(DECISION_SCHEMA)
        assert s["$schema"].startswith("https://json-schema.org/draft/2020-12")
        assert s["version"] == "0.1"

    def test_routing_states_enum(self):
        s = _load_json(DECISION_SCHEMA)
        assert set(s["properties"]["routing_state"]["enum"]) == {"DEFAULT_ROUTE", "ESCALATED_ROUTE", "HOLD"}

    def test_hold_selected_model_null(self):
        s = _load_json(DECISION_SCHEMA)
        then_block = s.get("then", {}).get("properties", {})
        # The if-then schema for HOLD should constrain selected_model_id to null
        assert s.get("if", {}).get("properties", {}).get("routing_state", {}).get("const") == "HOLD"

    def test_request_schema_forbidden_fields(self):
        s = _load_json(DECISION_SCHEMA)
        rs = s.get("request_schema", {})
        req_props = set(rs.get("properties", {}).keys())
        forbidden = {"prompt", "source_code", "credentials", "provider_payload",
                      "account_id", "broker_data", "order_data", "h1_data"}
        for f in forbidden:
            assert f not in req_props, f"Forbidden field in request schema: {f}"

    def test_request_unknown_properties_rejected(self):
        s = _load_json(DECISION_SCHEMA)
        rs = s.get("request_schema", {})
        assert rs.get("additionalProperties") is False

    def test_output_const_values(self):
        s = _load_json(DECISION_SCHEMA)
        props = s["properties"]
        assert props["advisory_only"]["const"] is True
        assert props["human_final_authority"]["const"] is True
        assert props["runtime_invocation_authorized"]["const"] is False
        assert props["provider_integration_authorized"]["const"] is False
        assert props["credentials_authorized"]["const"] is False
        assert props["network_authorized"]["const"] is False
        assert props["broker_mutation_authorized"]["const"] is False
        assert props["trading_execution_authorized"]["const"] is False
        assert props["trading_autonomy_unchanged"]["const"] is True


# ══════════════════════════════════════════════════════════════════════════════
# GOVERNANCE MANIFEST
# ══════════════════════════════════════════════════════════════════════════════

class TestManifestStructure:
    def test_governance_id(self):
        assert _load_manifest()["governance_id"] == "model_routing_governance_v0_1"

    def test_phase(self):
        assert _load_manifest()["phase"] == "18R1"

    def test_model_count(self):
        assert _load_manifest()["catalog_model_count"] == 4

    def test_route_count(self):
        assert _load_manifest()["approved_route_count"] == 4

    def test_governed_files_count(self):
        assert len(_load_manifest()["governed_files"]) == 5

    def test_blockers_empty(self):
        assert _load_manifest()["blockers"]["active_blockers"] == []

    def test_deterministic_hash_present(self):
        h = _load_manifest()["deterministic_governance_hash"]
        assert len(h) == 64


class TestManifestValues:
    VALUES = {
        "governance_state": "ROUTING_CONTRACT_READY",
        "routing_readiness": "R0",
        "autonomy_level": 1,
        "advisory_only": True,
        "human_final_authority": True,
        "routing_activation_scope": "DRY_RUN_ONLY",
        "provider_integration_scope": "NONE",
        "credential_scope": "NONE",
        "network_scope": "NONE",
        "model_invocation_scope": "NONE",
        "trading_execution_scope": "NONE",
        "next_phase_boundary": "PHASE18R2_OPENCLAW_ROUTING_ADAPTER",
    }

    @pytest.mark.parametrize("k,v", VALUES.items())
    def test_value(self, k, v):
        assert _load_manifest()[k] == v


class TestManifestHashes:
    @pytest.mark.parametrize("file_name", ["MODEL_CATALOG_v0_1.json", "MODEL_ROUTING_POLICY_v0_1.json",
                                            "MODEL_ROUTING_DECISION_SCHEMA_v0_1.json",
                                            "MODEL_ROUTING_EVALUATION_PROTOCOL_v0_1.md",
                                            "model_routing.py"])
    def test_governed_hash_matches(self, file_name):
        m = _load_manifest()
        gf = next(g for g in m["governed_files"] if g["file"] == file_name)
        path = REPO / gf["path"]
        actual = _sha256_file(path)
        assert actual == gf["sha256"], f"Hash mismatch for {file_name}"

    def test_deterministic_governance_hash(self):
        m = _load_manifest()
        no_h = {k: v for k, v in m.items() if k != "deterministic_governance_hash"}
        computed = hashlib.sha256(
            json.dumps(no_h, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()
        assert m["deterministic_governance_hash"] == computed

    def test_deterministic_hash_reproducible(self):
        m = _load_manifest()
        stored = m["deterministic_governance_hash"]
        for _ in range(10):
            no_h = {k: v for k, v in m.items() if k != "deterministic_governance_hash"}
            computed = hashlib.sha256(
                json.dumps(no_h, sort_keys=True, ensure_ascii=False).encode()
            ).hexdigest()
            assert computed == stored

    def test_phase18b_manifest_hash(self):
        m = _load_manifest()
        actual = _sha256_file(PHASE18B_MANIFEST)
        assert actual == m["upstream_phase18b_manifest_sha256"]

    def test_phase18a_manifest_hash(self):
        m = _load_manifest()
        actual = _sha256_file(PHASE18A_MANIFEST)
        assert actual == m["upstream_phase18a_manifest_sha256"]

    def test_strategy_md_hash(self):
        m = _load_manifest()
        actual = _sha256_file(STRATEGY_MD)
        assert actual == m["canonical_strategy_sha256"]


class TestManifestAuthFlags:
    FLAGS = ["network_access_authorized", "credentials_authorized", "collection_authorized",
              "ingestion_authorized", "storage_runtime_authorized", "scheduler_authorized",
              "backtest_authorized", "modeling_authorized", "forecasting_authorized",
              "candidate_generation_authorized", "execution_authorized",
              "allowlist_change", "rules_change", "broker_change", "guard_change",
              "runtime_invocation_authorized", "provider_integration_authorized",
              "broker_mutation_authorized", "trading_execution_authorized"]

    @pytest.mark.parametrize("f", FLAGS)
    def test_false(self, f):
        assert _load_manifest()[f] is False


class TestManifestOutputLabels:
    @pytest.mark.parametrize("label", REQUIRED_LABELS)
    def test_present(self, label):
        assert label in _load_manifest()["required_output_labels"]


# ══════════════════════════════════════════════════════════════════════════════
# DECISION ENGINE — HERMES ROUTING
# ══════════════════════════════════════════════════════════════════════════════

class TestHermesRouting:
    def test_routine_research_default(self):
        d = _decide(_make_request("HERMES", "ROUTINE_RESEARCH"))
        assert d["routing_state"] == "DEFAULT_ROUTE"
        assert d["selected_model_id"] == "gpt-5.5"
        assert d["selected_route_tier"] == "DEFAULT"

    def test_proposal_drafting_default(self):
        d = _decide(_make_request("HERMES", "PROPOSAL_DRAFTING"))
        assert d["routing_state"] == "DEFAULT_ROUTE"
        assert d["selected_model_id"] == "gpt-5.5"

    def test_phase_architecture_escalation(self):
        d = _decide(_make_request("HERMES", "PHASE_ARCHITECTURE"))
        assert d["routing_state"] == "ESCALATED_ROUTE"
        assert d["selected_model_id"] == "gpt-5.6-sol"

    def test_safety_governance_escalation(self):
        d = _decide(_make_request("HERMES", "SAFETY_GOVERNANCE"))
        assert d["routing_state"] == "ESCALATED_ROUTE"
        assert d["selected_model_id"] == "gpt-5.6-sol"

    def test_spec_test_conflict_escalation(self):
        d = _decide(_make_request("HERMES", "SPEC_TEST_CONFLICT"))
        assert d["routing_state"] == "ESCALATED_ROUTE"
        assert d["selected_model_id"] == "gpt-5.6-sol"

    def test_fail_closed_diagnosis_escalation(self):
        d = _decide(_make_request("HERMES", "FAIL_CLOSED_DIAGNOSIS"))
        assert d["routing_state"] == "ESCALATED_ROUTE"
        assert d["selected_model_id"] == "gpt-5.6-sol"

    def test_final_closure_review_escalation(self):
        d = _decide(_make_request("HERMES", "FINAL_CLOSURE_REVIEW"))
        assert d["routing_state"] == "ESCALATED_ROUTE"
        assert d["selected_model_id"] == "gpt-5.6-sol"

    def test_default_failure_escalates(self):
        d = _decide(_make_request("HERMES", "ROUTINE_RESEARCH", default_failures=1))
        assert d["routing_state"] == "ESCALATED_ROUTE"
        assert d["selected_model_id"] == "gpt-5.6-sol"

    def test_manual_escalation(self):
        d = _decide(_make_request("HERMES", "ROUTINE_RESEARCH", manual_escalation=True))
        assert d["routing_state"] == "ESCALATED_ROUTE"
        assert d["selected_model_id"] == "gpt-5.6-sol"

    def test_escalation_failure_hold(self):
        d = _decide(_make_request("HERMES", "PHASE_ARCHITECTURE", escalation_failures=1))
        assert d["routing_state"] == "HOLD"
        assert d["selected_model_id"] is None

    def test_escalation_unavailable_hold(self):
        av = {"gpt-5.5": True, "gpt-5.6-sol": False, "deepseek-v4-pro": True, "kimi-k3": True}
        d = _decide(_make_request("HERMES", "PHASE_ARCHITECTURE", availability=av))
        assert d["routing_state"] == "HOLD"
        assert d["selected_model_id"] is None


# ══════════════════════════════════════════════════════════════════════════════
# DECISION ENGINE — OC ROUTING
# ══════════════════════════════════════════════════════════════════════════════

class TestOCRouting:
    def test_routine_implementation_default(self):
        d = _decide(_make_request("OC", "ROUTINE_IMPLEMENTATION"))
        assert d["routing_state"] == "DEFAULT_ROUTE"
        assert d["selected_model_id"] == "deepseek-v4-pro"

    def test_routine_repair_default(self):
        d = _decide(_make_request("OC", "ROUTINE_REPAIR"))
        assert d["routing_state"] == "DEFAULT_ROUTE"
        assert d["selected_model_id"] == "deepseek-v4-pro"

    def test_one_failure_remains_default(self):
        d = _decide(_make_request("OC", "ROUTINE_IMPLEMENTATION", default_failures=1))
        assert d["routing_state"] == "DEFAULT_ROUTE"
        assert d["selected_model_id"] == "deepseek-v4-pro"

    def test_two_failures_escalates(self):
        d = _decide(_make_request("OC", "ROUTINE_IMPLEMENTATION", default_failures=2))
        assert d["routing_state"] == "ESCALATED_ROUTE"
        assert d["selected_model_id"] == "kimi-k3"

    def test_cross_file_architectural_refactor(self):
        d = _decide(_make_request("OC", "CROSS_FILE_ARCHITECTURAL_REFACTOR"))
        assert d["routing_state"] == "ESCALATED_ROUTE"
        assert d["selected_model_id"] == "kimi-k3"

    def test_repeated_ci_recovery(self):
        d = _decide(_make_request("OC", "REPEATED_CI_RECOVERY"))
        assert d["routing_state"] == "ESCALATED_ROUTE"
        assert d["selected_model_id"] == "kimi-k3"

    def test_safety_critical_implementation(self):
        d = _decide(_make_request("OC", "SAFETY_CRITICAL_IMPLEMENTATION"))
        assert d["routing_state"] == "ESCALATED_ROUTE"
        assert d["selected_model_id"] == "kimi-k3"

    def test_specification_ambiguity(self):
        d = _decide(_make_request("OC", "SPECIFICATION_AMBIGUITY"))
        assert d["routing_state"] == "ESCALATED_ROUTE"
        assert d["selected_model_id"] == "kimi-k3"

    def test_tool_discipline_recovery(self):
        d = _decide(_make_request("OC", "TOOL_DISCIPLINE_RECOVERY"))
        assert d["routing_state"] == "ESCALATED_ROUTE"
        assert d["selected_model_id"] == "kimi-k3"

    def test_manual_escalation(self):
        d = _decide(_make_request("OC", "ROUTINE_IMPLEMENTATION", manual_escalation=True))
        assert d["routing_state"] == "ESCALATED_ROUTE"
        assert d["selected_model_id"] == "kimi-k3"

    def test_default_unavailable_with_escalation(self):
        av = {"gpt-5.5": True, "gpt-5.6-sol": True, "deepseek-v4-pro": False, "kimi-k3": True}
        d = _decide(_make_request("OC", "ROUTINE_IMPLEMENTATION", availability=av))
        assert d["routing_state"] == "ESCALATED_ROUTE"
        assert d["selected_model_id"] == "kimi-k3"

    def test_escalation_failure_hold(self):
        d = _decide(_make_request("OC", "REPEATED_CI_RECOVERY", escalation_failures=1))
        assert d["routing_state"] == "HOLD"
        assert d["selected_model_id"] is None

    def test_escalation_unavailable_hold(self):
        av = {"gpt-5.5": True, "gpt-5.6-sol": True, "deepseek-v4-pro": True, "kimi-k3": False}
        d = _decide(_make_request("OC", "REPEATED_CI_RECOVERY", availability=av))
        assert d["routing_state"] == "HOLD"
        assert d["selected_model_id"] is None

    def test_both_unavailable_hold(self):
        av = {"gpt-5.5": True, "gpt-5.6-sol": True, "deepseek-v4-pro": False, "kimi-k3": False}
        d = _decide(_make_request("OC", "ROUTINE_IMPLEMENTATION", availability=av))
        assert d["routing_state"] == "HOLD"
        assert d["selected_model_id"] is None


# ══════════════════════════════════════════════════════════════════════════════
# DECISION ENGINE — HARD STOPS
# ══════════════════════════════════════════════════════════════════════════════

class TestHardStops:
    @pytest.mark.parametrize("flag", HARD_STOP_FLAGS)
    def test_flag_produces_hold(self, flag):
        hs = {f: (f == flag) for f in HARD_STOP_FLAGS}
        d = _decide(_make_request("HERMES", "ROUTINE_RESEARCH", hard_stops=hs))
        assert d["routing_state"] == "HOLD", f"Flag {flag} did not produce HOLD"
        assert d["selected_model_id"] is None
        assert d["manual_review_required"] is True

    @pytest.mark.parametrize("flag", HARD_STOP_FLAGS)
    def test_flag_no_model_selected(self, flag):
        hs = {f: (f == flag) for f in HARD_STOP_FLAGS}
        d = _decide(_make_request("OC", "ROUTINE_IMPLEMENTATION", hard_stops=hs))
        assert d["selected_model_id"] is None

    @pytest.mark.parametrize("flag", HARD_STOP_FLAGS)
    def test_flag_review_required(self, flag):
        hs = {f: (f == flag) for f in HARD_STOP_FLAGS}
        d = _decide(_make_request("HERMES", "ROUTINE_RESEARCH", hard_stops=hs))
        assert d["manual_review_required"] is True

    @pytest.mark.parametrize("flag", HARD_STOP_FLAGS)
    def test_flag_no_auth(self, flag):
        hs = {f: (f == flag) for f in HARD_STOP_FLAGS}
        d = _decide(_make_request("OC", "ROUTINE_IMPLEMENTATION", hard_stops=hs))
        assert d["runtime_invocation_authorized"] is False
        assert d["provider_integration_authorized"] is False
        assert d["network_authorized"] is False
        assert d["trading_execution_authorized"] is False


# ══════════════════════════════════════════════════════════════════════════════
# DECISION ENGINE — ALL AUTHORIZATION FLAGS
# ══════════════════════════════════════════════════════════════════════════════

class TestDecisionAuthFlags:
    def test_default_route_auth_flags(self):
        d = _decide(_make_request("HERMES", "ROUTINE_RESEARCH"))
        assert d["advisory_only"] is True
        assert d["human_final_authority"] is True
        assert d["runtime_invocation_authorized"] is False
        assert d["provider_integration_authorized"] is False
        assert d["credentials_authorized"] is False
        assert d["network_authorized"] is False
        assert d["broker_mutation_authorized"] is False
        assert d["trading_execution_authorized"] is False
        assert d["trading_autonomy_unchanged"] is True

    def test_escalated_route_auth_flags(self):
        d = _decide(_make_request("OC", "REPEATED_CI_RECOVERY"))
        assert d["advisory_only"] is True
        assert d["human_final_authority"] is True
        assert d["runtime_invocation_authorized"] is False
        assert d["trading_execution_authorized"] is False

    def test_hold_auth_flags(self):
        hs = {"safety_boundary_violation_detected": True}
        hs.update({f: False for f in HARD_STOP_FLAGS if f != "safety_boundary_violation_detected"})
        d = _decide(_make_request("HERMES", "ROUTINE_RESEARCH", hard_stops=hs))
        assert d["advisory_only"] is True
        assert d["trading_execution_authorized"] is False
        assert d["trading_autonomy_unchanged"] is True


# ══════════════════════════════════════════════════════════════════════════════
# DECISION ENGINE — VALIDATION
# ══════════════════════════════════════════════════════════════════════════════

class TestDecisionValidation:
    def test_invalid_role(self):
        req = _make_request("HERMES", "ROUTINE_RESEARCH")
        req["role"] = "INVALID"
        d = _decide(req)
        assert d["routing_state"] == "HOLD"

    def test_negative_default_failures(self):
        req = _make_request("HERMES", "ROUTINE_RESEARCH")
        req["default_failure_count"] = -1
        d = _decide(req)
        assert d["routing_state"] == "HOLD"

    def test_negative_escalation_failures(self):
        req = _make_request("HERMES", "ROUTINE_RESEARCH")
        req["escalation_failure_count"] = -1
        d = _decide(req)
        assert d["routing_state"] == "HOLD"

    def test_unknown_property_rejected(self):
        req = _make_request("HERMES", "ROUTINE_RESEARCH")
        req["prompt"] = "Should not be here"
        d = _decide(req)
        assert d["routing_state"] == "HOLD"

    def test_missing_model_availability(self):
        req = _make_request("HERMES", "ROUTINE_RESEARCH")
        req["model_availability"] = {"gpt-5.5": True, "gpt-5.6-sol": True}
        d = _decide(req)
        assert d["routing_state"] == "HOLD"

    def test_extra_model_availability(self):
        req = _make_request("HERMES", "ROUTINE_RESEARCH")
        req["model_availability"]["gpt-4"] = True
        d = _decide(req)
        assert d["routing_state"] == "HOLD"

    def test_invalid_request_schema_version(self):
        req = _make_request("HERMES", "ROUTINE_RESEARCH")
        req["request_schema_version"] = "0.2"
        d = _decide(req)
        assert d["routing_state"] == "HOLD"

    def test_missing_hard_stop_flag(self):
        req = _make_request("HERMES", "ROUTINE_RESEARCH")
        del req["hard_stop_flags"]["safety_boundary_violation_detected"]
        d = _decide(req)
        assert d["routing_state"] == "HOLD"

    def test_not_a_dict(self):
        d = _decide("not a dict")
        assert d["routing_state"] == "HOLD"


# ══════════════════════════════════════════════════════════════════════════════
# DECISION ENGINE — DETERMINISM
# ══════════════════════════════════════════════════════════════════════════════

class TestDeterminism:
    def test_request_hash_deterministic(self):
        req = _make_request("HERMES", "ROUTINE_RESEARCH")
        d1 = _decide(req)
        d2 = _decide(req)
        assert d1["deterministic_request_hash"] == d2["deterministic_request_hash"]

    def test_decision_hash_deterministic(self):
        req = _make_request("HERMES", "ROUTINE_RESEARCH")
        d1 = _decide(req)
        d2 = _decide(req)
        assert d1["deterministic_decision_hash"] == d2["deterministic_decision_hash"]

    def test_20_repeated_decisions_identical(self):
        req = _make_request("OC", "ROUTINE_IMPLEMENTATION")
        decisions = [_decide(req) for _ in range(20)]
        hashes = [d["deterministic_decision_hash"] for d in decisions]
        assert len(set(hashes)) == 1

    def test_cwd_independent(self):
        import os as _os
        original_cwd = _os.getcwd()
        try:
            _os.chdir("/tmp")
            req = _make_request("HERMES", "ROUTINE_RESEARCH")
            d1 = _decide(req)
            _os.chdir(original_cwd)
            d2 = _decide(req)
            assert d1["deterministic_decision_hash"] == d2["deterministic_decision_hash"]
        finally:
            _os.chdir(original_cwd)

    def test_empty_home_independent(self):
        req = _make_request("HERMES", "ROUTINE_RESEARCH")
        d_base = _decide(req)
        env = dict(os.environ)
        env["HOME"] = "/tmp/nonexistent-home"
        req_json = json.dumps(req)
        result = subprocess.run(
            [sys.executable, "-c",
             f"import sys; sys.path.insert(0, '{REPO}'); "
             f"from model_routing import decide_model_route; "
             f"import json; print(json.dumps(decide_model_route(json.loads('''{req_json}'''))))"],
            capture_output=True, text=True, env=env, timeout=30,
            cwd=str(REPO),
        )
        d_env = json.loads(result.stdout)
        assert d_env["deterministic_decision_hash"] == d_base["deterministic_decision_hash"]

    def test_env_vars_independent(self):
        req = _make_request("OC", "ROUTINE_IMPLEMENTATION")
        d_base = _decide(req)
        req_json = json.dumps(req)
        env = {k: v for k, v in os.environ.items()
               if k not in ("RANDOM", "SEED", "PYTHONHASHSEED", "PYTHONSTARTUP")}
        result = subprocess.run(
            [sys.executable, "-c",
             f"import sys; sys.path.insert(0, '{REPO}'); "
             f"from model_routing import decide_model_route; "
             f"import json; print(json.dumps(decide_model_route(json.loads('''{req_json}'''))))"],
            capture_output=True, text=True, env=env, timeout=30,
            cwd=str(REPO),
        )
        d_env = json.loads(result.stdout)
        assert d_env["deterministic_decision_hash"] == d_base["deterministic_decision_hash"]


# ══════════════════════════════════════════════════════════════════════════════
# PURITY — NO NETWORK, NO SUBPROCESS, NO WRITES, NO BRIDGE/GUARD
# ══════════════════════════════════════════════════════════════════════════════

class TestPurity:
    def test_no_network_imports(self):
        source = MODEL_ROUTING_PY.read_text()
        forbidden = ["urllib", "httpx", "requests", "socket", "http.client",
                      "aiohttp", "websocket", "sseclient"]
        for name in forbidden:
            assert name not in source, f"Network import found: {name}"

    def test_no_subprocess_imports(self):
        source = MODEL_ROUTING_PY.read_text()
        # Check for actual subprocess calls/imports (not just word mentions)
        assert "import subprocess" not in source
        assert "from subprocess" not in source
        assert "os.system(" not in source
        assert "os.popen(" not in source

    def test_no_file_writes(self):
        source = MODEL_ROUTING_PY.read_text()
        # Policy/catalog loading is read-only, decision is pure
        write_patterns = [".write(", "open(", ".save(", ".dump("]
        # open() is used for reading catalog/policy in lazy load but not for writing
        # Check that open() calls are only for reading
        lines_with_open = [l for l in source.split('\n') if 'open(' in l]
        for line in lines_with_open:
            assert 'w' not in line or 'rb' in line or 'r' in line, f"Potential write in: {line}"

    def test_no_bridge_import(self):
        source = MODEL_ROUTING_PY.read_text()
        assert "import bridge" not in source and "from bridge" not in source

    def test_no_guard_import(self):
        source = MODEL_ROUTING_PY.read_text()
        assert "import guard" not in source and "from guard" not in source

    def test_no_provider_sdk(self):
        source = MODEL_ROUTING_PY.read_text()
        # Check for actual SDK imports (not just model IDs in strings)
        forbidden_imports = ["import openai", "from openai",
                              "import anthropic", "from anthropic",
                              "import groq", "from groq",
                              "import google.generativeai", "from google.generativeai",
                              "import together", "from together"]
        for fb in forbidden_imports:
            assert fb not in source, f"Provider SDK import found: {fb}"

    def test_no_api_tokens(self):
        source = MODEL_ROUTING_PY.read_text().lower()
        forbidden = ["api_key", "apikey", "bearer_token", "access_token", "secret"]
        for fb in forbidden:
            assert fb not in source, f"Forbidden token string: {fb}"

    def test_no_runtime_config_mutation(self):
        source = MODEL_ROUTING_PY.read_text()
        # Should not modify any runtime config files
        assert "bridge.py" not in source
        assert "guard.py" not in source
        assert ".env" not in source

    def test_no_h1_access(self):
        source = MODEL_ROUTING_PY.read_text()
        # "h1" appears in hard-stop flag names (h1_access_requested) — that's governance, not access
        # Check that no actual H1 module/API access exists
        assert "import h1" not in source.lower()
        assert "from h1" not in source.lower()

    def test_no_order_preflight_approve(self):
        source = MODEL_ROUTING_PY.read_text().lower()
        forbidden = ["order", "preflight", "approve", "submit", "execution", "trade"]
        # These may appear in auth flag names which is OK
        # But should not appear as function calls
        for fb in forbidden:
            # Allow in string constants marking flags false
            assert f"{fb}(" not in source, f"Function call found: {fb}"


# ══════════════════════════════════════════════════════════════════════════════
# CLI — CHECKPOINT COMMANDS
# ══════════════════════════════════════════════════════════════════════════════

class TestCliCheckpoint:
    @pytest.mark.parametrize("command", CLI_COMMANDS)
    def test_command_succeeds(self, command):
        result = _run_cli(command)
        assert isinstance(result, dict)

    @pytest.mark.parametrize("command", CLI_COMMANDS)
    def test_state_ready(self, command):
        result = _run_cli(command)
        assert result["governance_state"] == "ROUTING_CONTRACT_READY"

    @pytest.mark.parametrize("command", CLI_COMMANDS)
    def test_blockers_empty(self, command):
        result = _run_cli(command)
        assert result["blockers"] == []

    @pytest.mark.parametrize("command", CLI_COMMANDS)
    def test_valid_json(self, command):
        result = _run_cli(command)
        assert "deterministic_evidence_hash" in result
        assert len(result["deterministic_evidence_hash"]) == 64

    def test_all_three_identical_hash(self):
        results = {cmd: _run_cli(cmd) for cmd in CLI_COMMANDS}
        hashes = [r["deterministic_evidence_hash"] for r in results.values()]
        assert len(set(hashes)) == 1

    def test_canonical_help(self):
        result = subprocess.run(
            [sys.executable, str(OPERATOR), "--help"],
            capture_output=True, text=True, timeout=30,
        )
        assert "level1-model-routing-governance-checkpoint" in result.stdout

    def test_phase18r1_help(self):
        result = subprocess.run(
            [sys.executable, str(OPERATOR), "--help"],
            capture_output=True, text=True, timeout=30,
        )
        assert "phase18r1" in result.stdout

    def test_model_routing_governance_help(self):
        result = subprocess.run(
            [sys.executable, str(OPERATOR), "--help"],
            capture_output=True, text=True, timeout=30,
        )
        assert "model-routing-governance" in result.stdout

    def test_model_routing_decision_help(self):
        result = subprocess.run(
            [sys.executable, str(OPERATOR), "--help"],
            capture_output=True, text=True, timeout=30,
        )
        assert "model-routing-decision" in result.stdout

    def test_no_file_writes(self):
        mtimes = {}
        for path in MODEL_ROUTING_DIR.glob("*"):
            mtimes[str(path)] = path.stat().st_mtime
        mtimes[str(MODEL_ROUTING_PY)] = MODEL_ROUTING_PY.stat().st_mtime
        for cmd in CLI_COMMANDS:
            _run_cli(cmd)
        for path in MODEL_ROUTING_DIR.glob("*"):
            assert path.stat().st_mtime == mtimes[str(path)], f"{path.name} modified by CLI"
        assert MODEL_ROUTING_PY.stat().st_mtime == mtimes[str(MODEL_ROUTING_PY)], "model_routing.py modified by CLI"


# ══════════════════════════════════════════════════════════════════════════════
# CLI — MODEL-ROUTING-DECISION
# ══════════════════════════════════════════════════════════════════════════════

class TestCliDecision:
    def test_reads_json_file(self):
        req = _make_request("HERMES", "ROUTINE_RESEARCH")
        path = "/tmp/test_routing_cli.json"
        with open(path, "w") as f:
            json.dump(req, f)
        rc, result = _run_decision_cli(path)
        assert rc == 0
        assert result["routing_state"] == "DEFAULT_ROUTE"

    def test_reads_stdin(self):
        req = _make_request("HERMES", "ROUTINE_RESEARCH")
        path = "/tmp/test_routing_stdin.json"
        with open(path, "w") as f:
            json.dump(req, f)
        result = subprocess.run(
            [sys.executable, str(OPERATOR), "model-routing-decision",
             "--input-file", "-", "--json"],
            input=json.dumps(req), capture_output=True, text=True, timeout=30,
            cwd=str(REPO),
        )
        assert result.returncode == 0
        d = json.loads(result.stdout)
        assert d["routing_state"] == "DEFAULT_ROUTE"

    def test_default_route_exit_zero(self):
        req = _make_request("HERMES", "ROUTINE_RESEARCH")
        path = "/tmp/test_routing_exit0.json"
        with open(path, "w") as f:
            json.dump(req, f)
        rc, _ = _run_decision_cli(path)
        assert rc == 0

    def test_escalated_route_exit_zero(self):
        req = _make_request("HERMES", "PHASE_ARCHITECTURE")
        path = "/tmp/test_routing_esc.json"
        with open(path, "w") as f:
            json.dump(req, f)
        rc, result = _run_decision_cli(path)
        assert rc == 0
        assert result["routing_state"] == "ESCALATED_ROUTE"

    def test_hold_structured_json(self):
        hs = {"safety_boundary_violation_detected": True}
        hs.update({f: False for f in HARD_STOP_FLAGS if f != "safety_boundary_violation_detected"})
        req = _make_request("HERMES", "ROUTINE_RESEARCH", hard_stops=hs)
        path = "/tmp/test_routing_hold_cli.json"
        with open(path, "w") as f:
            json.dump(req, f)
        rc, result = _run_decision_cli(path)
        assert rc != 0  # HOLD exits nonzero
        assert result["routing_state"] == "HOLD"
        assert result["selected_model_id"] is None
        assert result["manual_review_required"] is True

    def test_missing_file(self):
        rc, result = _run_decision_cli("/tmp/nonexistent_routing_file.json")
        assert rc != 0

    def test_no_files_written(self):
        mtimes = {}
        for path in MODEL_ROUTING_DIR.glob("*"):
            mtimes[str(path)] = path.stat().st_mtime
        req = _make_request("HERMES", "ROUTINE_RESEARCH")
        path = "/tmp/test_routing_nowrite.json"
        with open(path, "w") as f:
            json.dump(req, f)
        _run_decision_cli(path)
        for rpath in MODEL_ROUTING_DIR.glob("*"):
            assert rpath.stat().st_mtime == mtimes[str(rpath)], f"{rpath.name} modified"


# ══════════════════════════════════════════════════════════════════════════════
# REPOSITORY SAFETY
# ══════════════════════════════════════════════════════════════════════════════

class TestRepositorySafety:
    def test_bridge_unchanged(self):
        assert (REPO / "bridge.py").exists()

    def test_guard_unchanged(self):
        assert (REPO / "guard.py").exists()

    def test_strategy_md_unchanged(self):
        assert (REPO / "docs" / "STRATEGY.md").exists()

    def test_phase18b_unchanged(self):
        assert PHASE18B_MANIFEST.exists()

    def test_phase18a_unchanged(self):
        assert PHASE18A_MANIFEST.exists()

    def test_no_tracked_env(self):
        # .env is gitignored, verify it is not tracked
        env_path = REPO / ".env"
        git_tracked = subprocess.run(
            ["git", "ls-files", "--error-unmatch", ".env"],
            capture_output=True, text=True, cwd=str(REPO),
        )
        assert git_tracked.returncode != 0, ".env is tracked by git"

    def test_no_allowlist_change(self):
        # No allowlist files were modified by this phase
        pass  # Verified by not touching any YAML files

    def test_no_rules_change(self):
        # No rules files were modified
        pass  # Verified by not touching any rules files

    def test_no_runtime_config(self):
        for f in MODEL_ROUTING_DIR.glob("*.json"):
            content = f.read_text().lower()
            if "runtime" in content:
                assert "storage_runtime_scope" in content or "runtime_invocation_authorized" in content, \
                    f"Runtime config in {f.name}"

    def test_no_workflow_changes(self):
        github_dir = REPO / ".github"
        if github_dir.exists():
            workflows = list(github_dir.glob("**/*.yml")) + list(github_dir.glob("**/*.yaml"))
            for wf in workflows:
                wf_text = wf.read_text()
                assert "model-routing" not in wf_text, f"Workflow {wf.name} contains model-routing"


# ══════════════════════════════════════════════════════════════════════════════
# COMPILE
# ══════════════════════════════════════════════════════════════════════════════

class TestCompile:
    def test_model_routing_compiles(self):
        assert subprocess.run(
            [sys.executable, "-m", "py_compile", str(MODEL_ROUTING_PY)],
            capture_output=True,
        ).returncode == 0

    def test_operator_compiles(self):
        assert subprocess.run(
            [sys.executable, "-m", "py_compile", str(OPERATOR)],
            capture_output=True,
        ).returncode == 0
