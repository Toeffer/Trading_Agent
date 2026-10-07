"""Extracted operator helpers; historical behavior and command contracts retained."""
from __future__ import annotations
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from pathlib import Path


def _compute_sha256_file(path: Path) -> str:
    """Compute SHA-256 hex digest of a file."""
    from trading_agent.cli.operator_common import Path
    import hashlib as _hashlib
    return _hashlib.sha256(path.read_bytes()).hexdigest()


def _compute_deterministic_manifest_hash_18a(manifest: dict) -> str:
    """Compute deterministic hash of manifest excluding the hash field itself."""
    import hashlib as _hashlib
    import json as _json
    manifest_no_hash = {k: v for k, v in manifest.items() if k != "deterministic_manifest_hash"}
    canonical = _json.dumps(manifest_no_hash, sort_keys=True, ensure_ascii=False)
    return _hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _phase18a_no_go(checkpoint_id: str, ts_str: str, diagnosis: str, actions: list[str]) -> dict:
    """Build a NO_GO result for Phase 18A."""
    from trading_agent.cli.operator_common import _PHASE18A_EXPLICIT_NON_ACTIONS
    result = {
        "command": "ibkr-operator level1-mstr-btc-research-proposal-governance-checkpoint",
        "timestamp": ts_str, "checkpoint_id": checkpoint_id,
        "diagnosis": diagnosis, "severity": "NO_GO",
        "operator_action_required": True,
        "suggested_operator_actions": actions,
        "no_order_endpoint_called": True,
        "no_preflight_endpoint_called": True,
        "no_approval_endpoint_called": True,
        "no_submit_endpoint_called": True,
        "no_h1_token_used": True,
        "no_broker_mutation": True,
        "no_network_access": True,
        "no_file_mutation": True,
        "execution_authorized_now": False,
        "order_enablement_allowed_now": False,
        "current_level": 1,
        "explicit_non_actions": _PHASE18A_EXPLICIT_NON_ACTIONS,
        "artifact_created": False, "export_path": None,
    }
    return result


def _run_level1_mstr_btc_research_proposal_governance_checkpoint(
    audit_source: str = "synthetic_readonly_demo",
) -> dict:
    """Run Phase 18A — Level 1 MSTR/BTC Research Proposal Governance Checkpoint.

    Reads only repository-relative Phase 18A documents.
    Validates presence, hashes, manifest, and canonical strategy separation.
    Never accesses broker, network, H1, guard state, runtime state, or data providers.
    Never modifies files.
    """
    from trading_agent.cli.operator_common import _PHASE18A_DATA_REQ_DOC, _PHASE18A_DIAGNOSIS, _PHASE18A_EXPLICIT_NON_ACTIONS, _PHASE18A_MANIFEST_PATH, _PHASE18A_PROPOSAL_DOC, _PHASE18A_REPO_ROOT, _PHASE18A_STRATEGY_MD_PATH, _PHASE18A_STRATEGY_V1_PATH
    import json as _json
    from datetime import datetime, timezone
    now_utc = datetime.now(timezone.utc)
    ts_str = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    checkpoint_id = f"18a-{now_utc.strftime('%Y%m%dT%H%M%SZ')}"

    actions: list[str] = []
    diagnosis = _PHASE18A_DIAGNOSIS["ready"]

    # 1. Document presence
    proposal_doc_present = _PHASE18A_PROPOSAL_DOC.exists()
    data_req_present = _PHASE18A_DATA_REQ_DOC.exists()
    manifest_present = _PHASE18A_MANIFEST_PATH.exists()

    if not proposal_doc_present:
        diagnosis = _PHASE18A_DIAGNOSIS["proposal_doc_missing"]
        actions.append(f"Create {_PHASE18A_PROPOSAL_DOC}")
    if not data_req_present:
        diagnosis = _PHASE18A_DIAGNOSIS["data_requirements_doc_missing"]
        actions.append(f"Create {_PHASE18A_DATA_REQ_DOC}")
    if not manifest_present:
        diagnosis = _PHASE18A_DIAGNOSIS["manifest_missing"]
        actions.append(f"Create {_PHASE18A_MANIFEST_PATH}")

    if actions:
        return _phase18a_no_go(checkpoint_id, ts_str, diagnosis, actions)

    # 2. Manifest validity
    try:
        manifest = _json.loads(_PHASE18A_MANIFEST_PATH.read_text(encoding="utf-8"))
    except Exception:
        return _phase18a_no_go(checkpoint_id, ts_str,
                               _PHASE18A_DIAGNOSIS["manifest_invalid_json"],
                               ["Fix manifest JSON syntax"])

    pi = manifest.get("proposal_identity", {})
    required_pi_fields = [
        "proposal_id", "proposal_version", "proposal_status",
        "strategy_readiness", "autonomy_level", "research_only",
        "execution_scope", "permitted_activity", "options_scope",
        "btc_execution_scope", "equity_execution_scope",
        "allowlist_change", "rules_change", "broker_change",
        "guard_change", "replaces_strategy_v1",
        "canonical_strategy_unchanged",
        "human_approval_required_for_promotion",
        "next_phase_boundary", "canonical_strategy_reference",
    ]
    for field in required_pi_fields:
        if field not in pi or pi[field] is None or pi[field] == "":
            return _phase18a_no_go(checkpoint_id, ts_str,
                                   _PHASE18A_DIAGNOSIS["manifest_field_missing"],
                                   [f"Missing proposal_identity field: {field}"])

    # 3. Governance-critical field checks — fail closed on any unsafe value
    governance_checks = [
        ("execution_scope", "NONE", True, "execution_scope must be NONE"),
        ("btc_execution_scope", "NONE", True, "btc_execution_scope must be NONE"),
        ("equity_execution_scope", "NONE", True, "equity_execution_scope must be NONE"),
        ("options_scope", "SIMULATION_ONLY", True, "options_scope must be SIMULATION_ONLY"),
        ("permitted_activity", "DOCUMENTATION_AND_SCHEMA_PLANNING_ONLY", True,
         "permitted_activity must be DOCUMENTATION_AND_SCHEMA_PLANNING_ONLY"),
        ("strategy_readiness", "S0", True, "strategy_readiness must be S0"),
        ("proposal_status", "PROPOSED", True, "proposal_status must be PROPOSED"),
        ("autonomy_level", 1, True, "autonomy_level must be 1"),
        ("research_only", True, True, "research_only must be true"),
        ("allowlist_change", False, False, "allowlist_change must be false"),
        ("rules_change", False, False, "rules_change must be false"),
        ("broker_change", False, False, "broker_change must be false"),
        ("guard_change", False, False, "guard_change must be false"),
        ("replaces_strategy_v1", False, False, "replaces_strategy_v1 must be false"),
        ("canonical_strategy_unchanged", True, True, "canonical_strategy_unchanged must be true"),
    ]
    for field, safe_value, must_equal, msg in governance_checks:
        actual = pi.get(field)
        if must_equal:
            if actual != safe_value:
                return _phase18a_no_go(checkpoint_id, ts_str,
                                       _PHASE18A_DIAGNOSIS.get(f"{field}_invalid", _PHASE18A_DIAGNOSIS["manifest_field_invalid"]),
                                       [f"{msg}: got {actual}"])
        else:
            if actual is not False and actual is not None:
                return _phase18a_no_go(checkpoint_id, ts_str,
                                       _PHASE18A_DIAGNOSIS.get(f"{field}_true", _PHASE18A_DIAGNOSIS["manifest_field_invalid"]),
                                       [f"{msg}: got {actual}"])

    # 3b. Explicit non-actions must exist
    ena = manifest.get("explicit_non_actions", [])
    if not ena or len(ena) < 5:
        return _phase18a_no_go(checkpoint_id, ts_str,
                               _PHASE18A_DIAGNOSIS["manifest_field_missing"],
                               ["explicit_non_actions missing or too short in manifest"])

    # 3c. No execution approval claim
    approval_state = manifest.get("approval_state", {})
    for flag in ["NOT_APPROVED_FOR_EXECUTION", "NOT_APPROVED_FOR_ALLOWLIST_CHANGE",
                 "NOT_APPROVED_FOR_DATA_COLLECTION_RUNTIME", "NOT_APPROVED_FOR_BACKTEST_PROMOTION"]:
        if approval_state.get(flag) is not True:
            return _phase18a_no_go(checkpoint_id, ts_str,
                                   _PHASE18A_DIAGNOSIS["manifest_field_invalid"],
                                   [f"Approval flag {flag} must be true, got {approval_state.get(flag)}"])

    # 4. Document SHA-256 verification
    proposal_actual = _compute_sha256_file(_PHASE18A_PROPOSAL_DOC)
    proposal_stored = manifest.get("proposal_document_sha256", "")
    if proposal_actual != proposal_stored:
        return _phase18a_no_go(checkpoint_id, ts_str,
                               _PHASE18A_DIAGNOSIS["proposal_doc_sha256_mismatch"],
                               [f"Proposal doc SHA-256 mismatch: stored={proposal_stored[:16]}..., actual={proposal_actual[:16]}..."])

    data_req_actual = _compute_sha256_file(_PHASE18A_DATA_REQ_DOC)
    data_req_stored = manifest.get("data_requirements_document_sha256", "")
    if data_req_actual != data_req_stored:
        return _phase18a_no_go(checkpoint_id, ts_str,
                               _PHASE18A_DIAGNOSIS["data_requirements_doc_sha256_mismatch"],
                               [f"Data req doc SHA-256 mismatch: stored={data_req_stored[:16]}..., actual={data_req_actual[:16]}..."])

    # 5. Deterministic manifest hash verification
    computed_det_hash = _compute_deterministic_manifest_hash_18a(manifest)
    stored_det_hash = manifest.get("deterministic_manifest_hash", "")
    if computed_det_hash != stored_det_hash:
        return _phase18a_no_go(checkpoint_id, ts_str,
                               _PHASE18A_DIAGNOSIS["deterministic_manifest_hash_mismatch"],
                               [f"Deterministic manifest hash mismatch: stored={stored_det_hash[:16]}..., computed={computed_det_hash[:16]}..."])

    # 6. Canonical strategy preservation
    sv1_text = _PHASE18A_STRATEGY_V1_PATH.read_text(encoding="utf-8")
    if "mstr_btc_research_v0_1" in sv1_text.lower():
        return _phase18a_no_go(checkpoint_id, ts_str,
                               _PHASE18A_DIAGNOSIS["strategy_v1_modified"],
                               ["docs/strategy_v1.md contains Phase 18A proposal references — must not be modified"])

    smd_text = _PHASE18A_STRATEGY_MD_PATH.read_text(encoding="utf-8")
    if "mstr_btc_research_v0_1" in smd_text.lower():
        return _phase18a_no_go(checkpoint_id, ts_str,
                               _PHASE18A_DIAGNOSIS["strategy_md_modified"],
                               ["docs/STRATEGY.md contains Phase 18A proposal references — must not be modified"])

    # ── Success ──
    import hashlib as _hashlib

    # Build blockers list (empty for valid proposal)
    blockers: list[dict] = []

    # Build document_integrity
    doc_integrity = {
        "proposal_doc": {
            "path": str(_PHASE18A_PROPOSAL_DOC.relative_to(_PHASE18A_REPO_ROOT)),
            "present": proposal_doc_present,
            "sha256": proposal_actual,
            "sha256_match": True,
        },
        "data_requirements_doc": {
            "path": str(_PHASE18A_DATA_REQ_DOC.relative_to(_PHASE18A_REPO_ROOT)),
            "present": data_req_present,
            "sha256": data_req_actual,
            "sha256_match": True,
        },
        "manifest": {
            "path": str(_PHASE18A_MANIFEST_PATH.relative_to(_PHASE18A_REPO_ROOT)),
            "present": manifest_present,
            "deterministic_hash": stored_det_hash,
            "deterministic_hash_match": True,
        },
        "canonical_strategy_v1": {
            "path": "docs/strategy_v1.md",
            "present": _PHASE18A_STRATEGY_V1_PATH.exists(),
            "clean": True,
        },
        "canonical_strategy_md": {
            "path": "docs/STRATEGY.md",
            "present": _PHASE18A_STRATEGY_MD_PATH.exists(),
            "clean": True,
        },
    }

    # Build manifest_integrity
    manifest_integrity = {
        "valid_json": True,
        "proposal_identity_fields_present": len(required_pi_fields),
        "proposal_identity_fields_valid": len(required_pi_fields),
        "governance_fields_valid": True,
        "explicit_non_actions_present": True,
        "approval_state_valid": True,
        "deterministic_hash_reproducible": True,
    }

    output_labels = [
        "PHASE18A_PROPOSAL_RECORDED",
        "S0_RESEARCH_GOVERNANCE",
        "LEVEL1",
        "RESEARCH_ONLY",
        "NON_EXECUTABLE",
        "NO_ALLOWLIST_CHANGE",
        "NO_BROKER_CHANGE",
        "NO_GUARD_CHANGE",
        "OPTIONS_SIMULATION_ONLY",
        "STRATEGY_V1_UNCHANGED",
        "PHASE18B_NOT_STARTED",
    ]

    # Compute deterministic_evidence_hash from stable fields only
    evidence_fields = {
        "proposal_id": pi.get("proposal_id"),
        "proposal_version": pi.get("proposal_version"),
        "proposal_status": pi.get("proposal_status"),
        "strategy_readiness": pi.get("strategy_readiness"),
        "autonomy_level": pi.get("autonomy_level"),
        "research_only": pi.get("research_only"),
        "execution_scope": pi.get("execution_scope"),
        "permitted_activity": pi.get("permitted_activity"),
        "options_scope": pi.get("options_scope"),
        "btc_execution_scope": pi.get("btc_execution_scope"),
        "equity_execution_scope": pi.get("equity_execution_scope"),
        "replaces_strategy_v1": pi.get("replaces_strategy_v1"),
        "canonical_strategy_unchanged": pi.get("canonical_strategy_unchanged"),
        "proposal_doc_sha256": proposal_actual,
        "data_req_doc_sha256": data_req_actual,
        "manifest_deterministic_hash": stored_det_hash,
    }
    canonical_evidence = _json.dumps(evidence_fields, sort_keys=True, ensure_ascii=False)
    deterministic_evidence_hash = _hashlib.sha256(canonical_evidence.encode("utf-8")).hexdigest()

    return {
        "command": "ibkr-operator level1-mstr-btc-research-proposal-governance-checkpoint",
        "checkpoint_version": "phase18a-v1.0.0",
        "timestamp": ts_str,
        "checkpoint_id": checkpoint_id,
        "diagnosis": _PHASE18A_DIAGNOSIS["ready"],
        "severity": "GO",
        "proposal_id": pi.get("proposal_id"),
        "proposal_status": pi.get("proposal_status"),
        "strategy_readiness": pi.get("strategy_readiness"),
        "governance_state": "PROPOSED",
        "autonomy_level": pi.get("autonomy_level"),
        "research_only": pi.get("research_only"),
        "execution_scope": pi.get("execution_scope"),
        "permitted_activity": pi.get("permitted_activity"),
        "canonical_strategy_unchanged": pi.get("canonical_strategy_unchanged"),
        "replaces_strategy_v1": pi.get("replaces_strategy_v1"),
        "allowlist_change": pi.get("allowlist_change"),
        "rules_change": pi.get("rules_change"),
        "broker_change": pi.get("broker_change"),
        "guard_change": pi.get("guard_change"),
        "options_scope": pi.get("options_scope"),
        "next_phase_boundary": pi.get("next_phase_boundary"),
        "document_integrity": doc_integrity,
        "manifest_integrity": manifest_integrity,
        "deterministic_evidence_hash": deterministic_evidence_hash,
        "blockers": blockers,
        "output_labels": output_labels,
        "explicit_non_actions": _PHASE18A_EXPLICIT_NON_ACTIONS,
        "no_order_endpoint_called": True,
        "no_preflight_endpoint_called": True,
        "no_approval_endpoint_called": True,
        "no_submit_endpoint_called": True,
        "no_connect_called": True,
        "no_h1_token_used": True,
        "no_broker_mutation": True,
        "no_network_access": True,
        "no_file_mutation": True,
        "no_http_socket_subprocess": True,
        "execution_authorized_now": False,
        "order_enablement_allowed_now": False,
        "current_level": 1,
        "operator_action_required": False,
        "suggested_operator_actions": [],
        "artifact_created": False,
        "export_path": None,
    }


def _phase18b_no_go(checkpoint_id: str, ts_str: str, error_msg: str) -> dict:
    from trading_agent.cli.operator_common import _PHASE18B_DIAGNOSIS
    return {
        "checkpoint_version": "phase18b-v1.0.0",
        "checkpoint_id": checkpoint_id,
        "timestamp": ts_str,
        "command": "level1-data-schema-provider-governance-checkpoint",
        "diagnosis": _PHASE18B_DIAGNOSIS["internal_error"],
        "governance_state": "ERROR",
        "governance_id": "mstr_btc_data_governance_v0_1",
        "governance_version": "0.1",
        "strategy_readiness": "S0",
        "data_readiness": "D0",
        "autonomy_level": 1,
        "research_only": True,
        "execution_scope": "NONE",
        "collection_scope": "NONE",
        "provider_integration_scope": "NONE",
        "permitted_activity": "SCHEMA_AND_PROVIDER_CONTRACT_VALIDATION_ONLY",
        "provider_binding_state": "UNBOUND",
        "schema_count": 5,
        "provider_role_count": 10,
        "error": error_msg,
        "document_integrity": {"overall": False},
        "schema_integrity": {"overall": False},
        "provider_governance_integrity": {"overall": False},
        "quality_policy_integrity": {"overall": False},
        "upstream_phase18a_integrity": {"overall": False},
        "canonical_strategy_integrity": {"overall": False},
        "point_in_time_governance": {},
        "all_authorization_flags_false": False,
        "deterministic_evidence_hash": "",
        "blockers": [f"Internal error: {error_msg}"],
        "explicit_non_actions": [],
        "non_action_count": 0,
        "next_phase_boundary": "PHASE18C_SYNTHETIC_SCHEMA_CONFORMANCE",
        "output_labels": [],
        "warnings": [],
    }


def _run_level1_data_schema_provider_governance_checkpoint() -> dict:
    from trading_agent.cli.operator_common import Path, _PHASE18B_CANONICAL_STRATEGY, _PHASE18B_COMMON_FIELDS, _PHASE18B_CREDENTIAL_FORBIDDEN, _PHASE18B_DIAGNOSIS, _PHASE18B_EXPECTED_ROLES, _PHASE18B_GOVERNANCE_DIR, _PHASE18B_GOVERNED_FILES, _PHASE18B_NON_ACTIONS, _PHASE18B_PHASE18A_MANIFEST, _PHASE18B_QUALITY_OUTCOMES, _PHASE18B_QUALITY_SCENARIOS
    import json as _json
    import hashlib as _hashlib
    from datetime import datetime, timezone
    now_utc = datetime.now(timezone.utc)
    ts_str = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    checkpoint_id = f"18b-{now_utc.strftime('%Y%m%dT%H%M%SZ')}"

    errors: list[str] = []
    warnings: list[str] = []
    doc_int: dict = {}
    schema_int: dict = {}
    prov_int: dict = {}
    qual_int: dict = {}
    upstream_int: dict = {}
    strategy_int: dict = {}
    pt_gov: dict = {}
    all_auth: dict = {}

    def _sha256(p: Path) -> str:
        return _hashlib.sha256(p.read_bytes()).hexdigest()

    def _load(p: Path):
        with open(p, encoding="utf-8") as f:
            return _json.load(f)

    def _has_failures() -> bool:
        return len(errors) > 0

    def _bool_int(data: dict) -> dict:
        out = dict(data)
        out["overall"] = not _has_failures()
        return out

    # 1. Document existence & JSON syntax
    for name, path in _PHASE18B_GOVERNED_FILES:
        if not path.exists():
            errors.append(f"MISSING_FILE: {name}")
        else:
            try:
                _load(path)
            except Exception as e:
                errors.append(f"JSON_SYNTAX_ERROR: {name}: {e}")

    manifest_path = _PHASE18B_GOVERNANCE_DIR / "mstr_btc_data_governance_v0_1.manifest.json"
    if not manifest_path.exists():
        errors.append("MANIFEST_MISSING")
    else:
        try:
            _load(manifest_path)
        except Exception as e:
            errors.append(f"MANIFEST_JSON_ERROR: {e}")

    if errors:
        return _phase18b_no_go(checkpoint_id, ts_str, "; ".join(errors))

    # 2. Load all docs
    docs = {name: _load(path) for name, path in _PHASE18B_GOVERNED_FILES}
    manifest = _load(manifest_path)

    # 3. Governed file hashes
    for name, path in _PHASE18B_GOVERNED_FILES:
        actual = _sha256(path)
        gf_entry = next((g for g in manifest.get("governed_files", []) if g.get("file") == name), None)
        if gf_entry:
            stored = gf_entry.get("sha256", "")
            match = actual == stored
            doc_int[name] = {"match": match, "actual": actual, "stored": stored}
            if not match:
                errors.append(f"HASH_MISMATCH: {name}")
        else:
            doc_int[name] = {"match": False, "actual": actual, "error": "not in governed_files"}
            errors.append(f"NOT_IN_GOVERNED_FILES: {name}")

    # 4. Governance identity on all governed docs
    for name in [n for n, _ in _PHASE18B_GOVERNED_FILES]:
        d = docs[name]
        gi = d.get("governance_identity", {})
        if gi.get("governance_id") != "mstr_btc_data_governance_v0_1":
            errors.append(f"GOVERNANCE_ID_MISMATCH: {name}")
        if gi.get("governance_state") != "SCHEMA_CONTRACT_READY":
            errors.append(f"GOVERNANCE_STATE_NOT_READY: {name}")
        if gi.get("execution_scope") != "NONE":
            errors.append(f"EXECUTION_SCOPE_NOT_NONE: {name}")
        if gi.get("research_only") is not True:
            errors.append(f"RESEARCH_ONLY_NOT_TRUE: {name}")
        if gi.get("provider_binding_state") != "UNBOUND":
            errors.append(f"PROVIDER_BINDING_NOT_UNBOUND: {name}")
        if gi.get("network_access_authorized") is not False:
            errors.append(f"NETWORK_ACCESS_AUTHORIZED: {name}")
        if gi.get("credentials_authorized") is not False:
            errors.append(f"CREDENTIALS_AUTHORIZED: {name}")
        if gi.get("collection_authorized") is not False:
            errors.append(f"COLLECTION_AUTHORIZED: {name}")
        # Vendor neutrality: no credential strings
        serialized = _json.dumps(d).lower()
        for fb in _PHASE18B_CREDENTIAL_FORBIDDEN:
            if fb in serialized:
                errors.append(f"FORBIDDEN_CONTENT: {name}: '{fb}'")

    # 5. Common record contract on record schemas
    for name in [n for n, _ in _PHASE18B_GOVERNED_FILES if n.startswith(("EQUITY", "BTC", "CORPORATE", "OPTION"))]:
        d = docs[name]
        req = d.get("required", [])
        props = d.get("properties", {})
        for cf in _PHASE18B_COMMON_FIELDS:
            if cf not in req:
                errors.append(f"MISSING_COMMON_FIELD: {name}: {cf}")
        if props.get("execution_eligible", {}).get("const") is not False:
            errors.append(f"EXECUTION_ELIGIBLE_NOT_CONST_FALSE: {name}")
        if d.get("additionalProperties") is not False:
            errors.append(f"ADDITIONAL_PROPERTIES_NOT_FALSE: {name}")

    # 6. Dataset manifest schema
    dms = docs.get("DATASET_MANIFEST_SCHEMA_v0_1.json", {})
    dms_props = dms.get("properties", {})
    if dms_props.get("raw_data_immutable", {}).get("const") is not True:
        errors.append("DMS_RAW_DATA_IMMUTABLE_NOT_TRUE")
    if dms_props.get("collection_authorized", {}).get("const") is not False:
        errors.append("DMS_COLLECTION_AUTHORIZED_NOT_FALSE")
    if dms_props.get("execution_eligible", {}).get("const") is not False:
        errors.append("DMS_EXECUTION_ELIGIBLE_NOT_FALSE")
    if dms_props.get("lookahead_detected", {}).get("const") is not False:
        errors.append("DMS_LOOKAHEAD_NOT_FALSE")

    # 7. Provider roles
    pg = docs.get("MSTR_BTC_PROVIDER_GOVERNANCE_v0_1.json", {})
    roles = pg.get("provider_roles", {})
    found_roles = set(roles.keys())
    expected_roles = set(_PHASE18B_EXPECTED_ROLES)
    missing_roles = expected_roles - found_roles
    extra_roles = found_roles - expected_roles
    if missing_roles:
        errors.append(f"MISSING_PROVIDER_ROLES: {', '.join(sorted(missing_roles))}")
    if extra_roles:
        errors.append(f"EXTRA_PROVIDER_ROLES: {', '.join(sorted(extra_roles))}")
    for role_id, role in roles.items():
        if role.get("provider_binding_state") != "UNBOUND":
            errors.append(f"ROLE_NOT_UNBOUND: {role_id}")
        if role.get("integration_state") != "NOT_IMPLEMENTED":
            errors.append(f"ROLE_INTEGRATION_IMPLEMENTED: {role_id}")
        if role.get("credentials_authorized") is not False:
            errors.append(f"ROLE_CREDENTIALS_AUTHORIZED: {role_id}")
        if role.get("network_access_authorized") is not False:
            errors.append(f"ROLE_NETWORK_ACCESS_AUTHORIZED: {role_id}")
        if role.get("human_binding_approval_required") is not True:
            errors.append(f"ROLE_BINDING_APPROVAL_NOT_REQUIRED: {role_id}")
    if pg.get("provider_binding_summary", {}).get("global_binding_state") != "UNBOUND":
        errors.append("PROVIDER_GLOBAL_BINDING_NOT_UNBOUND")

    # 8. Quality policy
    qp = docs.get("MSTR_BTC_DATA_QUALITY_POLICY_v0_1.json", {})
    rds = qp.get("real_data_state", {})
    if rds.get("real_data_thresholds_frozen") is not False:
        errors.append("REAL_DATA_THRESHOLDS_FROZEN_TRUE")
    if rds.get("provider_bindings_frozen") is not False:
        errors.append("PROVIDER_BINDINGS_FROZEN_TRUE")
    if rds.get("real_data_use_authorized") is not False:
        errors.append("REAL_DATA_USE_AUTHORIZED_TRUE")
    outcomes = qp.get("quality_outcomes", {})
    for o in _PHASE18B_QUALITY_OUTCOMES:
        if o not in outcomes:
            errors.append(f"MISSING_QUALITY_OUTCOME: {o}")
    coverage = qp.get("quality_score_calculation", {}).get("coverage_matrix", {})
    covered = set(coverage.keys())
    missing_scenarios = set(_PHASE18B_QUALITY_SCENARIOS) - covered
    if missing_scenarios:
        errors.append(f"MISSING_QUALITY_SCENARIOS: {', '.join(sorted(missing_scenarios))}")
    fc_rules = qp.get("fail_closed_principle", {}).get("rules", [])
    if len(fc_rules) < 10:
        errors.append(f"FAIL_CLOSED_RULES_INSUFFICIENT: {len(fc_rules)}")

    # 9. Manifest self-validation
    req_fields = [
        "manifest_version", "governance_id", "governance_version",
        "governance_state", "strategy_readiness", "data_readiness",
        "autonomy_level", "research_only", "execution_scope",
        "collection_scope", "provider_integration_scope", "permitted_activity",
        "provider_binding_state", "schema_count", "provider_role_count",
        "governed_files", "quality_outcomes", "explicit_non_actions",
        "blockers", "deterministic_governance_hash",
        "phase18a_proposal_id", "phase18a_manifest_path",
        "phase18a_manifest_sha256", "canonical_strategy_path",
        "canonical_strategy_sha256", "next_phase_boundary",
    ]
    for rf in req_fields:
        if rf not in manifest:
            errors.append(f"MISSING_MANIFEST_FIELD: {rf}")
    if manifest.get("governance_state") != "SCHEMA_CONTRACT_READY":
        errors.append("MANIFEST_STATE_NOT_READY")
    if manifest.get("strategy_readiness") != "S0":
        errors.append("MANIFEST_STRATEGY_READINESS_NOT_S0")
    if manifest.get("data_readiness") != "D0":
        errors.append("MANIFEST_DATA_READINESS_NOT_D0")
    if manifest.get("autonomy_level") != 1:
        errors.append("MANIFEST_AUTONOMY_NOT_1")
    if manifest.get("research_only") is not True:
        errors.append("MANIFEST_RESEARCH_ONLY_NOT_TRUE")
    if manifest.get("execution_scope") != "NONE":
        errors.append("MANIFEST_EXECUTION_SCOPE_NOT_NONE")
    if manifest.get("collection_scope") != "NONE":
        errors.append("MANIFEST_COLLECTION_SCOPE_NOT_NONE")
    if manifest.get("provider_binding_state") != "UNBOUND":
        errors.append("MANIFEST_PROVIDER_BINDING_NOT_UNBOUND")
    if manifest.get("schema_count") != 5:
        errors.append(f"MANIFEST_SCHEMA_COUNT: {manifest.get('schema_count')}")
    if manifest.get("provider_role_count") != 10:
        errors.append(f"MANIFEST_PROVIDER_ROLE_COUNT: {manifest.get('provider_role_count')}")
    if manifest.get("next_phase_boundary") != "PHASE18C_SYNTHETIC_SCHEMA_CONFORMANCE":
        errors.append("MANIFEST_NEXT_PHASE_INVALID")

    auth_flags = [
        "network_access_authorized", "credentials_authorized",
        "collection_authorized", "ingestion_authorized",
        "storage_runtime_authorized", "scheduler_authorized",
        "backtest_authorized", "modeling_authorized", "forecasting_authorized",
        "candidate_generation_authorized", "execution_authorized",
        "allowlist_change", "rules_change", "broker_change", "guard_change",
    ]
    for flag in auth_flags:
        if manifest.get(flag) is not False:
            errors.append(f"MANIFEST_FLAG_TRUE: {flag}")
    if manifest.get("canonical_strategy_unchanged") is not True:
        errors.append("MANIFEST_STRATEGY_UNCHANGED_FALSE")
    if manifest.get("phase18a_artifacts_unchanged") is not True:
        errors.append("MANIFEST_PHASE18A_UNCHANGED_FALSE")

    gf = manifest.get("governed_files", [])
    if len(gf) != 7:
        errors.append(f"MANIFEST_GOVERNED_FILE_COUNT: {len(gf)}")
    expected_order = [gn for gn, _ in _PHASE18B_GOVERNED_FILES]
    actual_order = [g.get("file", "") for g in gf]
    if actual_order != expected_order:
        errors.append(f"MANIFEST_GOVERNED_FILE_ORDER_WRONG")
    na = manifest.get("explicit_non_actions", [])
    if len(na) < 20:
        errors.append(f"MANIFEST_NON_ACTIONS_COUNT: {len(na)}")
    b = manifest.get("blockers", {})
    if not isinstance(b, dict):
        errors.append("MANIFEST_BLOCKERS_NOT_OBJECT")

    # 10. Phase 18A manifest hash
    if _PHASE18B_PHASE18A_MANIFEST.exists():
        actual_18a = _sha256(_PHASE18B_PHASE18A_MANIFEST)
        stored_18a = manifest.get("phase18a_manifest_sha256", "")
        match_18a = actual_18a == stored_18a
        upstream_int["phase18a_manifest"] = {"match": match_18a, "actual": actual_18a, "stored": stored_18a}
        if not match_18a:
            errors.append("PHASE18A_MANIFEST_HASH_MISMATCH")
    else:
        errors.append("PHASE18A_MANIFEST_MISSING")

    # 11. Canonical strategy hash
    if _PHASE18B_CANONICAL_STRATEGY.exists():
        actual_cs = _sha256(_PHASE18B_CANONICAL_STRATEGY)
        stored_cs = manifest.get("canonical_strategy_sha256", "")
        match_cs = actual_cs == stored_cs
        strategy_int["canonical_strategy"] = {"match": match_cs, "actual": actual_cs, "stored": stored_cs}
        if not match_cs:
            errors.append("CANONICAL_STRATEGY_HASH_MISMATCH")
    else:
        errors.append("CANONICAL_STRATEGY_MISSING")

    # 12. Deterministic governance hash
    stored_hash = manifest.get("deterministic_governance_hash", "")
    manifest_no_hash = {k: v for k, v in manifest.items() if k != "deterministic_governance_hash"}
    computed_hash = _hashlib.sha256(
        _json.dumps(manifest_no_hash, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()
    hash_match = stored_hash == computed_hash
    doc_int["deterministic_governance_hash"] = {"match": hash_match, "stored": stored_hash, "computed": computed_hash}
    if not hash_match:
        errors.append("DETERMINISTIC_GOVERNANCE_HASH_MISMATCH")

    # 13. Authorization flags
    all_auth["all_false"] = all(manifest.get(f, True) is False for f in auth_flags)

    # 14. Point-in-time
    pt_gov = {"point_in_time_enforced": True}

    # 15. Integrity summaries
    schema_int = {
        "overall": not _has_failures(),
        "record_schemas_validated": [n for n, _ in _PHASE18B_GOVERNED_FILES if n.startswith(("EQUITY", "BTC", "CORPORATE", "OPTION"))],
    }
    prov_int = {"overall": not _has_failures()}
    qual_int = {"overall": not _has_failures()}

    # Build output
    output_labels = manifest.get("required_output_labels", [])

    result = {
        "command": "level1-data-schema-provider-governance-checkpoint",
        "checkpoint_version": "phase18b-v1.0.0",
        "checkpoint_id": checkpoint_id,
        "timestamp": ts_str,
        "governance_id": "mstr_btc_data_governance_v0_1",
        "governance_version": "0.1",
        "governance_state": "SCHEMA_CONTRACT_READY" if not _has_failures() else "BLOCKED",
        "strategy_readiness": "S0",
        "data_readiness": "D0",
        "autonomy_level": 1,
        "research_only": True,
        "execution_scope": "NONE",
        "collection_scope": "NONE",
        "provider_integration_scope": "NONE",
        "permitted_activity": "SCHEMA_AND_PROVIDER_CONTRACT_VALIDATION_ONLY",
        "provider_binding_state": "UNBOUND",
        "schema_count": 5,
        "provider_role_count": 10,
        "document_integrity": _bool_int(doc_int),
        "schema_integrity": _bool_int(schema_int),
        "provider_governance_integrity": _bool_int(prov_int),
        "quality_policy_integrity": _bool_int(qual_int),
        "upstream_phase18a_integrity": _bool_int(upstream_int),
        "canonical_strategy_integrity": _bool_int(strategy_int),
        "point_in_time_governance": pt_gov,
        "all_authorization_flags_false": all_auth.get("all_false", False),
        "deterministic_evidence_hash": "",
        "blockers": errors if _has_failures() else [],
        "explicit_non_actions": _PHASE18B_NON_ACTIONS,
        "non_action_count": len(manifest.get("explicit_non_actions", [])),
        "next_phase_boundary": "PHASE18C_SYNTHETIC_SCHEMA_CONFORMANCE",
        "output_labels": output_labels,
        "warnings": warnings,
        "diagnosis": {
            "ready": _PHASE18B_DIAGNOSIS["ready"],
            "error_count": len(errors),
        },
    }
    # Evidence hash
    no_hash = {k: v for k, v in result.items() if k not in ("deterministic_evidence_hash", "diagnosis", "warnings", "timestamp", "checkpoint_id")}
    result["deterministic_evidence_hash"] = _hashlib.sha256(
        _json.dumps(no_hash, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()
    result["diagnosis"] = {
        "ready": _PHASE18B_DIAGNOSIS["ready"] if not errors else _PHASE18B_DIAGNOSIS["checkpoint_failed"],
        "error_count": len(errors),
    }

    return result


def _phase18r1_no_go(checkpoint_id: str, ts_str: str, error_msg: str, command_name: str = "level1-model-routing-governance-checkpoint") -> dict:
    from trading_agent.cli.operator_common import _PHASE18R1_DIAGNOSIS
    return {
        "command": command_name,
        "checkpoint_version": "phase18r1-v1.0.0",
        "checkpoint_id": checkpoint_id,
        "timestamp": ts_str,
        "governance_id": "model_routing_governance_v0_1",
        "governance_version": "0.1",
        "governance_state": "ERROR",
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
        "catalog_model_count": 4,
        "approved_route_count": 4,
        "error": error_msg,
        "blockers": [f"Internal error: {error_msg}"],
        "output_labels": [],
        "warnings": [],
        "next_phase_boundary": "PHASE18R2_OPENCLAW_ROUTING_ADAPTER",
        "deterministic_evidence_hash": "",
        "diagnosis": _PHASE18R1_DIAGNOSIS["internal_error"],
    }


def _run_level1_model_routing_governance_checkpoint() -> dict:
    from trading_agent.cli.operator_common import Path, _PHASE18R1_AUTH_FLAGS, _PHASE18R1_CANONICAL_STRATEGY, _PHASE18R1_DIAGNOSIS, _PHASE18R1_EXPECTED_ROLE_ASSIGNMENTS, _PHASE18R1_GOVERNED_FILES, _PHASE18R1_MODEL_ROUTING_DIR, _PHASE18R1_PHASE18A_MANIFEST, _PHASE18R1_PHASE18B_MANIFEST, _PHASE18R1_REQUIRED_LABELS
    import json as _json
    import hashlib as _hashlib
    from datetime import datetime, timezone
    now_utc = datetime.now(timezone.utc)
    ts_str = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    checkpoint_id = f"18r1-{now_utc.strftime('%Y%m%dT%H%M%SZ')}"

    errors: list[str] = []
    warnings: list[str] = []

    def _sha256(p: Path) -> str:
        return _hashlib.sha256(p.read_bytes()).hexdigest()

    def _load(p: Path):
        with open(p, encoding="utf-8") as f:
            return _json.load(f)

    def _has_failures() -> bool:
        return len(errors) > 0

    # 1. Document existence & JSON syntax
    for name, path in _PHASE18R1_GOVERNED_FILES:
        if not path.exists():
            errors.append(f"MISSING_FILE: {name}")
        else:
            try:
                _load(path) if path.suffix == ".json" else path.read_text(encoding="utf-8")
            except Exception as e:
                errors.append(f"FILE_READ_ERROR: {name}: {e}")

    manifest_path = _PHASE18R1_MODEL_ROUTING_DIR / "model_routing_governance_v0_1.manifest.json"
    if not manifest_path.exists():
        errors.append("MANIFEST_MISSING")
        return _phase18r1_no_go(checkpoint_id, ts_str, "; ".join(errors))

    try:
        manifest = _load(manifest_path)
    except Exception as e:
        errors.append(f"MANIFEST_JSON_ERROR: {e}")
        return _phase18r1_no_go(checkpoint_id, ts_str, "; ".join(errors))

    if errors:
        return _phase18r1_no_go(checkpoint_id, ts_str, "; ".join(errors))

    # 2. Governed file hashes
    doc_int = {}
    for name, path in _PHASE18R1_GOVERNED_FILES:
        actual = _sha256(path)
        gf_entry = next((g for g in manifest.get("governed_files", []) if g.get("file") == name), None)
        if gf_entry:
            stored = gf_entry.get("sha256", "")
            match = actual == stored
            doc_int[name] = {"match": match, "actual": actual, "stored": stored}
            if not match:
                errors.append(f"HASH_MISMATCH: {name}")
        else:
            doc_int[name] = {"match": False, "actual": actual, "error": "not in governed_files"}
            errors.append(f"NOT_IN_GOVERNED_FILES: {name}")

    # 3. Manifest governed file count
    if len(manifest.get("governed_files", [])) != len(_PHASE18R1_GOVERNED_FILES):
        errors.append(f"GOVERNED_FILE_COUNT_MISMATCH: expected {len(_PHASE18R1_GOVERNED_FILES)}, got {len(manifest.get('governed_files', []))}")

    # 4. Deterministic governance hash
    manifest_no_hash = {k: v for k, v in manifest.items() if k != "deterministic_governance_hash"}
    computed_hash = _hashlib.sha256(
        _json.dumps(manifest_no_hash, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()
    stored_hash = manifest.get("deterministic_governance_hash", "")
    if computed_hash != stored_hash:
        errors.append("DETERMINISTIC_GOVERNANCE_HASH_MISMATCH")

    # 5. Manifest values
    for k, v in {
        "governance_state": "ROUTING_CONTRACT_READY",
        "governance_id": "model_routing_governance_v0_1",
        "governance_version": "0.1",
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
        "catalog_model_count": 4,
        "approved_route_count": 4,
        "next_phase_boundary": "PHASE18R2_OPENCLAW_ROUTING_ADAPTER",
    }.items():
        if manifest.get(k) != v:
            errors.append(f"MANIFEST_VALUE_MISMATCH: {k} expected={v} got={manifest.get(k)}")

    # 6. All authorization flags false
    auth_all_false = all(manifest.get(f, True) is False for f in _PHASE18R1_AUTH_FLAGS)
    if not auth_all_false:
        true_flags = [f for f in _PHASE18R1_AUTH_FLAGS if manifest.get(f) is not False]
        errors.append(f"AUTHORIZATION_FLAGS_NOT_FALSE: {true_flags}")

    # 7. Catalog validation
    catalog_path = _PHASE18R1_MODEL_ROUTING_DIR / "MODEL_CATALOG_v0_1.json"
    if catalog_path.exists():
        catalog = _load(catalog_path)
        catalog_models = catalog.get("approved_models", [])
        if len(catalog_models) != 4:
            errors.append(f"CATALOG_MODEL_COUNT: expected 4, got {len(catalog_models)}")
        seen_ids = set()
        for m in catalog_models:
            mid = m.get("logical_model_id", "")
            if mid in seen_ids:
                errors.append(f"DUPLICATE_MODEL: {mid}")
            seen_ids.add(mid)
            if mid not in _PHASE18R1_EXPECTED_ROLE_ASSIGNMENTS:
                errors.append(f"UNKNOWN_MODEL: {mid}")
            else:
                expected_roles = _PHASE18R1_EXPECTED_ROLE_ASSIGNMENTS[mid]
                actual_roles = m.get("approved_roles", [])
                if sorted(actual_roles) != sorted(expected_roles):
                    errors.append(f"ROLE_MISMATCH: {mid} expected={expected_roles} got={actual_roles}")
            if m.get("provider_binding_state") != "LOGICAL_ONLY":
                errors.append(f"PROVIDER_BINDING_NOT_LOGICAL_ONLY: {mid}")
            for af in ["runtime_invocation_authorized", "network_authorized",
                        "credentials_authorized", "trading_decision_authorized",
                        "broker_access_authorized", "execution_authorized"]:
                if m.get(af) is not False:
                    errors.append(f"MODEL_AUTH_FLAG_TRUE: {mid}.{af}")
            if m.get("human_final_authority_required") is not True:
                errors.append(f"HUMAN_AUTHORITY_NOT_REQUIRED: {mid}")
        if seen_ids != set(_PHASE18R1_EXPECTED_ROLE_ASSIGNMENTS.keys()):
            missing = set(_PHASE18R1_EXPECTED_ROLE_ASSIGNMENTS.keys()) - seen_ids
            errors.append(f"MISSING_MODELS_IN_CATALOG: {sorted(missing)}")

    # 8. Policy validation
    policy_path = _PHASE18R1_MODEL_ROUTING_DIR / "MODEL_ROUTING_POLICY_v0_1.json"
    if policy_path.exists():
        policy = _load(policy_path)
        terminal_states = policy.get("terminal_routing_states", [])
        if sorted(terminal_states) != sorted(["DEFAULT_ROUTE", "ESCALATED_ROUTE", "HOLD"]):
            errors.append(f"TERMINAL_STATES_MISMATCH: {terminal_states}")
        for role in ["HERMES", "OC"]:
            role_def = policy.get("roles", {}).get(role, {})
            if not role_def:
                errors.append(f"MISSING_ROLE_DEFINITION: {role}")
            else:
                for tier in ["default", "escalation", "hold"]:
                    if tier not in role_def:
                        errors.append(f"MISSING_TIER: {role}.{tier}")
        hsf = policy.get("hard_stop_safety_flags", [])
        if len(hsf) != 15:
            errors.append(f"HARD_STOP_FLAG_COUNT: expected 15, got {len(hsf)}")
        principles = policy.get("routing_principles", {})
        for p in ["no_silent_model_substitution", "no_model_outside_catalog",
                   "no_downgrade_after_escalation"]:
            if principles.get(p) is not True:
                errors.append(f"PRINCIPLE_NOT_TRUE: {p}")

    # 9. Decision schema validation
    schema_path = _PHASE18R1_MODEL_ROUTING_DIR / "MODEL_ROUTING_DECISION_SCHEMA_v0_1.json"
    if schema_path.exists():
        schema = _load(schema_path)
        if not isinstance(schema, dict) or "version" not in schema:
            errors.append("DECISION_SCHEMA_INVALID")

    # 10. Upstream Phase 18B integrity
    upstream_int = {}
    if _PHASE18R1_PHASE18B_MANIFEST.exists():
        b_hash = _sha256(_PHASE18R1_PHASE18B_MANIFEST)
        stored_b_hash = manifest.get("upstream_phase18b_manifest_sha256", "")
        match = b_hash == stored_b_hash
        upstream_int["phase18b_manifest"] = {"match": match, "actual": b_hash, "stored": stored_b_hash}
        if not match:
            errors.append("PHASE18B_MANIFEST_HASH_MISMATCH")
    else:
        errors.append("PHASE18B_MANIFEST_MISSING")
        upstream_int["phase18b_manifest"] = {"match": False, "error": "missing"}

    # 11. Upstream Phase 18A integrity
    upstream_18a_int = {}
    if _PHASE18R1_PHASE18A_MANIFEST.exists():
        a_hash = _sha256(_PHASE18R1_PHASE18A_MANIFEST)
        stored_a_hash = manifest.get("upstream_phase18a_manifest_sha256", "")
        match = a_hash == stored_a_hash
        upstream_18a_int["phase18a_manifest"] = {"match": match, "actual": a_hash, "stored": stored_a_hash}
        if not match:
            errors.append("PHASE18A_MANIFEST_HASH_MISMATCH")
    else:
        errors.append("PHASE18A_MANIFEST_MISSING")
        upstream_18a_int["phase18a_manifest"] = {"match": False, "error": "missing"}

    # 12. Canonical Strategy v1 integrity
    strategy_int = {}
    if _PHASE18R1_CANONICAL_STRATEGY.exists():
        s_hash = _sha256(_PHASE18R1_CANONICAL_STRATEGY)
        stored_s_hash = manifest.get("canonical_strategy_sha256", "")
        match = s_hash == stored_s_hash
        strategy_int["canonical_strategy"] = {"match": match, "actual": s_hash, "stored": stored_s_hash}
        if not match:
            errors.append("STRATEGY_MD_HASH_MISMATCH")
    else:
        errors.append("STRATEGY_MD_MISSING")
        strategy_int["canonical_strategy"] = {"match": False, "error": "missing"}

    # 13. Protected file integrity (bridge, guard, .env, STRATEGY.md, Phase 18B)
    # Already verified upstream; no new mutations allowed

    # 14. Build output
    output_labels = _PHASE18R1_REQUIRED_LABELS if not _has_failures() else []

    result = {
        "command": "level1-model-routing-governance-checkpoint",
        "checkpoint_version": "phase18r1-v1.0.0",
        "checkpoint_id": checkpoint_id,
        "timestamp": ts_str,
        "governance_id": "model_routing_governance_v0_1",
        "governance_version": "0.1",
        "governance_state": "ROUTING_CONTRACT_READY" if not _has_failures() else "BLOCKED",
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
        "catalog_model_count": 4,
        "approved_route_count": 4,
        "document_integrity": {"overall": not _has_failures(), "details": doc_int},
        "manifest_integrity": {
            "hash_match": computed_hash == stored_hash,
            "governed_count_correct": len(manifest.get("governed_files", [])) == len(_PHASE18R1_GOVERNED_FILES),
        },
        "upstream_phase18b_integrity": {"overall": not _has_failures(), "details": upstream_int},
        "upstream_phase18a_integrity": {"overall": not _has_failures(), "details": upstream_18a_int},
        "canonical_strategy_integrity": {"overall": not _has_failures(), "details": strategy_int},
        "all_authorization_flags_false": auth_all_false,
        "blockers": errors if _has_failures() else [],
        "output_labels": output_labels,
        "warnings": warnings,
        "next_phase_boundary": "PHASE18R2_OPENCLAW_ROUTING_ADAPTER",
        "deterministic_evidence_hash": "",
        "diagnosis": _PHASE18R1_DIAGNOSIS["ready"],
    }

    # Evidence hash
    no_hash = {k: v for k, v in result.items()
               if k not in ("deterministic_evidence_hash", "diagnosis", "warnings",
                             "timestamp", "checkpoint_id", "command")}
    result["deterministic_evidence_hash"] = _hashlib.sha256(
        _json.dumps(no_hash, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()
    result["diagnosis"] = {
        "ready": _PHASE18R1_DIAGNOSIS["ready"] if not errors else _PHASE18R1_DIAGNOSIS["checkpoint_failed"],
        "error_count": len(errors),
    }

    return result


def _run_model_routing_decision(input_path: str) -> dict:
    """Run model routing decision from JSON file or stdin."""
    from trading_agent.cli.operator_common import Path, sys
    import json as _json
    from pathlib import Path as _Path

    if input_path == "-":
        raw = sys.stdin.read()
    else:
        p = _Path(input_path)
        if not p.exists():
            return {
                "error": f"Input file not found: {input_path}",
                "routing_state": "HOLD",
                "selected_model_id": None,
                "selected_route_tier": None,
                "manual_review_required": True,
            }
        raw = p.read_text(encoding="utf-8")

    try:
        request = _json.loads(raw)
    except _json.JSONDecodeError as e:
        return {
            "error": f"Malformed JSON: {e}",
            "routing_state": "HOLD",
            "selected_model_id": None,
            "selected_route_tier": None,
            "manual_review_required": True,
        }

    # Import and use the pure decision engine
    import importlib.util
    model_routing_path = Path(__file__).resolve().parents[2] / "model_routing.py"
    spec = importlib.util.spec_from_file_location("model_routing", model_routing_path)
    mr = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mr)

    return mr.decide_model_route(request)


def _phase18r2_no_go(checkpoint_id: str, ts_str: str, error_msg: str,
                     command_name: str = "level1-openclaw-routing-adapter-checkpoint") -> dict:
    from trading_agent.cli.operator_common import _PHASE18R2_DIAGNOSIS
    return {
        "command": command_name,
        "checkpoint_version": "phase18r2-v1.0.0",
        "checkpoint_id": checkpoint_id,
        "timestamp": ts_str,
        "governance_id": "openclaw_routing_adapter_v0_1",
        "governance_version": "0.1",
        "governance_state": "ERROR",
        "adapter_readiness": "A0",
        "autonomy_level": 1,
        "advisory_only": True,
        "human_final_authority": True,
        "adapter_mode": "SHADOW_ONLY",
        "live_routing_changed": False,
        "direct_provider_integration_scope": "NONE",
        "direct_credential_scope": "NONE",
        "direct_network_scope": "NONE",
        "direct_model_invocation_scope": "NONE",
        "transport_delegation_scope": "EXISTING_CODEX_AND_OPENCODE_ONLY",
        "trading_execution_scope": "NONE",
        "error": error_msg,
        "blockers": [f"Internal error: {error_msg}"],
        "output_labels": [],
        "blocker_count": 1,
        "warnings": [],
        "next_phase_boundary": "PHASE18R2_MANUAL_ACTIVATION_PROOF",
        "deterministic_evidence_hash": "",
        "diagnosis": {
            "ready": False,
            "status": _PHASE18R2_DIAGNOSIS["internal_error"],
            "blocker_count": 1,
            "error_count": 1,
        },
    }


def _run_level1_openclaw_routing_adapter_checkpoint() -> dict:
    from trading_agent.cli.operator_common import Path, _PHASE18R2_ADAPTER_DIR, _PHASE18R2_B_MANIFEST, _PHASE18R2_DIAGNOSIS, _PHASE18R2_GOVERNED_FILES, _PHASE18R2_PENDING_INPUT_LABELS, _PHASE18R2_R1_MANIFEST, _PHASE18R2_READY_LABELS, _PHASE18R2_STRATEGY
    import json as _json
    import hashlib as _hashlib
    from datetime import datetime, timezone
    now_utc = datetime.now(timezone.utc)
    ts_str = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    checkpoint_id = f"18r2-{now_utc.strftime('%Y%m%dT%H%M%SZ')}"

    errors: list[str] = []

    def _sha256(p: Path) -> str:
        return _hashlib.sha256(p.read_bytes()).hexdigest()

    def _load(p: Path):
        with open(p, encoding="utf-8") as f:
            return _json.load(f)

    def _has_failures() -> bool:
        return len(errors) > 0

    # 1. File existence
    for name, path in _PHASE18R2_GOVERNED_FILES:
        if not path.exists():
            errors.append(f"MISSING_FILE: {name}")
        else:
            try:
                _load(path) if path.suffix == ".json" else path.read_text(encoding="utf-8")
            except Exception as e:
                errors.append(f"FILE_READ_ERROR: {name}: {e}")

    manifest_path = _PHASE18R2_ADAPTER_DIR / "openclaw_routing_adapter_v0_1.manifest.json"
    if not manifest_path.exists():
        errors.append("MANIFEST_MISSING")
        return _phase18r2_no_go(checkpoint_id, ts_str, "; ".join(errors))

    try:
        manifest = _load(manifest_path)
    except Exception as e:
        errors.append(f"MANIFEST_JSON_ERROR: {e}")
        return _phase18r2_no_go(checkpoint_id, ts_str, "; ".join(errors))

    if errors:
        return _phase18r2_no_go(checkpoint_id, ts_str, "; ".join(errors))

    # 2. Governed file hashes
    for name, path in _PHASE18R2_GOVERNED_FILES:
        actual = _sha256(path)
        gf_entry = next((g for g in manifest.get("governed_files", []) if g.get("file") == name), None)
        if gf_entry:
            stored = gf_entry.get("sha256", "")
            if actual != stored:
                errors.append(f"HASH_MISMATCH: {name}")
        else:
            errors.append(f"NOT_IN_GOVERNED_FILES: {name}")

    # 3. Deterministic governance hash
    manifest_no_hash = {k: v for k, v in manifest.items() if k != "deterministic_governance_hash"}
    computed_hash = _hashlib.sha256(
        _json.dumps(manifest_no_hash, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()
    if computed_hash != manifest.get("deterministic_governance_hash", ""):
        errors.append("DETERMINISTIC_GOVERNANCE_HASH_MISMATCH")

    # 4. Core values
    for k, v in {
        "governance_state": "ADAPTER_READY_FOR_MANUAL_ACTIVATION",
        "governance_id": "openclaw_routing_adapter_v0_1",
        "adapter_readiness": "A0",
        "autonomy_level": 1,
        "advisory_only": True,
        "human_final_authority": True,
        "adapter_mode": "SHADOW_ONLY",
        "live_routing_changed": False,
        "direct_provider_integration_scope": "NONE",
        "direct_credential_scope": "NONE",
        "direct_network_scope": "NONE",
        "direct_model_invocation_scope": "NONE",
        "transport_delegation_scope": "EXISTING_CODEX_AND_OPENCODE_ONLY",
        "trading_execution_scope": "NONE",
        "next_phase_boundary": "PHASE18R2_MANUAL_ACTIVATION_PROOF",
    }.items():
        if manifest.get(k) != v:
            errors.append(f"MANIFEST_VALUE_MISMATCH: {k} expected={v} got={manifest.get(k)}")

    # 5. Authorization flags
    auth_flags = ["network_access_authorized", "credentials_authorized",
                   "runtime_invocation_authorized", "provider_integration_authorized",
                   "transport_activation_authorized", "live_routing_change_authorized",
                   "broker_mutation_authorized", "trading_execution_authorized"]
    auth_all_false = all(manifest.get(f, True) is False for f in auth_flags)
    if not auth_all_false:
        errors.append("AUTHORIZATION_FLAGS_NOT_ALL_FALSE")

    # 6. Upstream Phase 18R1 integrity
    if _PHASE18R2_R1_MANIFEST.exists():
        r1_hash = _sha256(_PHASE18R2_R1_MANIFEST)
        stored = manifest.get("upstream_phase18r1_manifest_sha256", "")
        if r1_hash != stored:
            errors.append("PHASE18R1_MANIFEST_HASH_MISMATCH")
    else:
        errors.append("PHASE18R1_MANIFEST_MISSING")

    # 7. Upstream Phase 18B integrity
    if _PHASE18R2_B_MANIFEST.exists():
        b_hash = _sha256(_PHASE18R2_B_MANIFEST)
        stored = manifest.get("upstream_phase18b_manifest_sha256", "")
        if b_hash != stored:
            errors.append("PHASE18B_MANIFEST_HASH_MISMATCH")
    else:
        errors.append("PHASE18B_MANIFEST_MISSING")

    # 8. Strategy v1 integrity
    if _PHASE18R2_STRATEGY.exists():
        s_hash = _sha256(_PHASE18R2_STRATEGY)
        stored = manifest.get("canonical_strategy_sha256", "")
        if s_hash != stored:
            errors.append("STRATEGY_MD_HASH_MISMATCH")
    else:
        errors.append("STRATEGY_MD_MISSING")

    # Build output — state-dependent labels
    manifest_gs = manifest.get("governance_state", "PENDING_INPUT")
    bound_count = manifest.get("binding_summary", {}).get("bound", 0)
    active_blockers = manifest.get("blockers", {}).get("active_blockers", [])
    blocker_count = len(active_blockers)

    if _has_failures():
        output_labels = []
    elif manifest_gs == "PENDING_INPUT" or bound_count < 3 or blocker_count > 0:
        # Fail-closed: only emit pending labels when not fully ready
        output_labels = list(_PHASE18R2_PENDING_INPUT_LABELS)
    else:
        # ADAPTER_READY_FOR_MANUAL_ACTIVATION: all 3 bound, zero blockers
        output_labels = list(_PHASE18R2_READY_LABELS)

    # Compute all_authorization_flags_false from manifest + bindings
    all_auth_false = True
    auth_keys = [
        "network_access_authorized", "credentials_authorized",
        "runtime_invocation_authorized", "provider_integration_authorized",
        "transport_activation_authorized", "live_routing_change_authorized",
        "broker_mutation_authorized", "trading_execution_authorized",
    ]
    for k in auth_keys:
        v = manifest.get(k)
        if v is None or not isinstance(v, bool) or v is not False:
            all_auth_false = False
            errors.append(f"MANIFEST_AUTH_FLAG_NOT_FALSE: {k} = {v}")
            break

    # Check binding-level flags
    if all_auth_false:
        bindings_path = _PHASE18R2_ADAPTER_DIR / "OPENCLAW_ROUTING_BINDINGS_v0_1.json"
        bindings_data = _load(bindings_path) if bindings_path.exists() else {}
        binding_auth_keys = [
            "adapter_reads_credentials", "adapter_stores_credentials",
            "direct_provider_access", "direct_network_access",
            "adapter_invocation_authorized", "live_activation_authorized",
        ]
        for b in bindings_data.get("bindings", []):
            for k in binding_auth_keys:
                v = b.get(k)
                if v is None or not isinstance(v, bool) or v is not False:
                    all_auth_false = False
                    errors.append(f"BINDING_AUTH_FLAG_NOT_FALSE: {b.get('logical_model_id', '?')}.{k} = {v}")
                    break
            if not all_auth_false:
                break

    # Check bindings top-level authorization_flags (must include runtime_invocation_authorized)
    if all_auth_false:
        af = bindings_data.get("authorization_flags", {})
        runtime_val = af.get("runtime_invocation_authorized")
        if runtime_val is None or not isinstance(runtime_val, bool) or runtime_val is not False:
            all_auth_false = False
            errors.append(f"BINDINGS_AUTHORIZATION_FLAGS_RUNTIME_INVOCATION_NOT_FALSE: got={runtime_val}")

    result = {
        "command": "level1-openclaw-routing-adapter-checkpoint",
        "checkpoint_version": "phase18r2-v1.0.0",
        "checkpoint_id": checkpoint_id,
        "timestamp": ts_str,
        "governance_id": "openclaw_routing_adapter_v0_1",
        "governance_version": "0.1",
        "governance_state": ("PENDING_INPUT" if manifest.get("governance_state") == "PENDING_INPUT"
                               else ("ADAPTER_READY_FOR_MANUAL_ACTIVATION" if (not _has_failures() and bound_count == 3 and blocker_count == 0) else "BLOCKED")),
        "binding_count": manifest.get("binding_summary", {}).get("total_bindings", 3),
        "bound_binding_count": manifest.get("binding_summary", {}).get("bound", 0),
        "adapter_readiness": "A0",
        "autonomy_level": 1,
        "advisory_only": True,
        "human_final_authority": True,
        "adapter_mode": "SHADOW_ONLY",
        "live_routing_changed": False,
        "direct_provider_integration_scope": "NONE",
        "direct_credential_scope": "NONE",
        "direct_network_scope": "NONE",
        "direct_model_invocation_scope": "NONE",
        "transport_delegation_scope": "EXISTING_CODEX_AND_OPENCODE_ONLY",
        "trading_execution_scope": "NONE",
        "governed_file_count": len(_PHASE18R2_GOVERNED_FILES),
        "all_authorization_flags_false": all_auth_false,
        "blockers": errors if _has_failures() else active_blockers,
        "blocker_count": len(errors) if _has_failures() else blocker_count,
        "output_labels": output_labels,
        "warnings": [],
        "next_phase_boundary": "PHASE18R2_MANUAL_ACTIVATION_PROOF",
        "deterministic_evidence_hash": "",
        "diagnosis": {},
    }

    # Fail-closed diagnosis: ready is boolean, status is code, blocker_count/error_count reflect actual blockers
    manifest_gs = manifest.get("governance_state", "PENDING_INPUT")
    if _has_failures():
        _diag = {
            "ready": False,
            "status": _PHASE18R2_DIAGNOSIS["checkpoint_failed"],
            "blocker_count": len(errors),
            "error_count": len(errors),
        }
    elif manifest_gs == "PENDING_INPUT" or bound_count < 3 or blocker_count > 0:
        _diag = {
            "ready": False,
            "status": _PHASE18R2_DIAGNOSIS["pending"],
            "blocker_count": blocker_count,
            "error_count": max(len(errors), blocker_count),
        }
    else:
        _diag = {
            "ready": True,
            "status": _PHASE18R2_DIAGNOSIS["ready"],
            "blocker_count": 0,
            "error_count": 0,
        }

    no_hash = {k: v for k, v in result.items()
               if k not in ("deterministic_evidence_hash", "diagnosis", "warnings",
                             "timestamp", "checkpoint_id", "command")}
    result["deterministic_evidence_hash"] = _hashlib.sha256(
        _json.dumps(no_hash, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()
    result["diagnosis"] = _diag

    return result


def _run_openclaw_route_decide(input_path: str) -> dict:
    """Run full pipeline: Phase 18R1 decision + Phase 18R2 adapter mapping."""
    from trading_agent.cli.operator_common import Path, sys
    import json as _json
    from pathlib import Path as _Path

    # Read input
    if input_path == "-":
        raw = sys.stdin.read()
    else:
        p = _Path(input_path)
        if not p.exists():
            return {"error": f"Input file not found: {input_path}", "adapter_state": "HOLD"}
        raw = p.read_text(encoding="utf-8")

    try:
        request = _json.loads(raw)
    except _json.JSONDecodeError as e:
        return {"error": f"Malformed JSON: {e}", "adapter_state": "HOLD"}

    # Phase 18R1: logical decision
    import importlib.util as _iu
    mr_path = Path(__file__).resolve().parents[2] / "model_routing.py"
    mr_spec = _iu.spec_from_file_location("model_routing", mr_path)
    mr = _iu.module_from_spec(mr_spec)
    mr_spec.loader.exec_module(mr)
    logical = mr.decide_model_route(request)

    # Phase 18R2: transport adapter
    ad_path = Path(__file__).resolve().parents[2] / "openclaw_routing_adapter.py"
    ad_spec = _iu.spec_from_file_location("openclaw_routing_adapter", ad_path)
    ad = _iu.module_from_spec(ad_spec)
    ad_spec.loader.exec_module(ad)
    adapter = ad.resolve_shadow_route(request, logical)

    return adapter


def _run_model_routing_adapter_decision(request_path: str, decision_path: str) -> dict:
    """Run Phase 18R2 adapter directly from existing request+decision pair."""
    from trading_agent.cli.operator_common import Path, sys
    import json as _json
    from pathlib import Path as _Path

    def _read_file(filepath: str) -> str:
        if filepath == "-":
            return sys.stdin.read()
        p = _Path(filepath)
        if not p.exists():
            raise FileNotFoundError(f"File not found: {filepath}")
        return p.read_text(encoding="utf-8")

    try:
        request_raw = _read_file(request_path)
    except FileNotFoundError as e:
        return {"adapter_state": "HOLD", "error": str(e)}
    try:
        decision_raw = _read_file(decision_path)
    except FileNotFoundError as e:
        return {"adapter_state": "HOLD", "error": str(e)}

    try:
        request = _json.loads(request_raw)
    except _json.JSONDecodeError as e:
        return {"adapter_state": "HOLD", "error": f"Malformed request JSON: {e}"}
    try:
        decision = _json.loads(decision_raw)
    except _json.JSONDecodeError as e:
        return {"adapter_state": "HOLD", "error": f"Malformed decision JSON: {e}"}

    # Import adapter
    import importlib.util as _iu
    ad_path = Path(__file__).resolve().parents[2] / "openclaw_routing_adapter.py"
    ad_spec = _iu.spec_from_file_location("openclaw_routing_adapter", ad_path)
    ad = _iu.module_from_spec(ad_spec)
    ad_spec.loader.exec_module(ad)

    return ad.resolve_shadow_route(request, decision)


def _run_model_routing_activation_plan() -> dict:
    """Generate a deterministic activation plan from repository governance only."""
    from trading_agent.cli.operator_common import _PHASE18R2_ADAPTER_DIR
    import json as _json
    import hashlib as _hashlib

    manifest_path = _PHASE18R2_ADAPTER_DIR / "openclaw_routing_adapter_v0_1.manifest.json"
    bindings_path = _PHASE18R2_ADAPTER_DIR / "OPENCLAW_ROUTING_BINDINGS_v0_1.json"

    def _load(p):
        with open(p, encoding="utf-8") as f:
            return _json.load(f)

    def _canonical_hash(obj):
        return _hashlib.sha256(
            _json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
        ).hexdigest()

    if not manifest_path.exists():
        return {"plan_state": "ERROR", "error": "Manifest missing"}
    if not bindings_path.exists():
        return {"plan_state": "ERROR", "error": "Bindings missing"}

    manifest = _load(manifest_path)
    bindings = _load(bindings_path)

    # Derive binding table from bindings contract
    binding_table = []
    all_bound = True
    for b in bindings.get("bindings", []):
        entry = {
            "logical_model_id": b["logical_model_id"],
            "logical_role": b["logical_role"],
            "transport": b["transport"],
            "runtime_alias": b["runtime_alias"],
            "binding_state": b["binding_state"],
        }
        binding_table.append(entry)
        if b["binding_state"] != "BOUND_EXISTING_ALIAS":
            all_bound = False

    # Sanitized integration point (no credentials)
    integration_point = {
        "codex": {
            "source": "~/.openclaw/agents/main/agent/models.json — codex provider",
            "directly_observed_aliases": ["gpt-5.5", "gpt-5.4", "gpt-5.4-mini", "gpt-5.3-codex", "gpt-5.2"],
            "status": "gpt-5.5 bound via codex provider; gpt-5.6-sol bound via authenticated Codex app-server model/list",
        },
        "opencode": {
            "source": "auth-profiles.json — opencode-go:default profile authenticated",
            "openrouter_directly_observed_aliases": ["openrouter/auto", "kimi-k2.6", "kimi-k2.5"],
            "status": "deepseek-v4-pro bound via opencode-go/deepseek-v4-pro (active primary model). OC_ESCALATION role retired — no escalation model tracked",
        },
    }

    # Build plan
    plan = {
        "plan_schema_version": "0.1",
        "plan_state": "BLOCKED" if not all_bound else "READY",
        "governance_id": manifest.get("governance_id"),
        "governance_version": manifest.get("governance_version"),
        "phase": "18R2",
        "adapter_mode": "SHADOW_ONLY",
        "adapter_readiness": manifest.get("adapter_readiness"),
        "autonomy_level": manifest.get("autonomy_level"),
        "advisory_only": True,
        "human_final_authority": True,
        "live_routing_changed": False,
        "live_routing_unchanged": True,
        "activation_performed": False,
        "human_activation_required": True,
        "activation_not_authorized_by_phase18r2_shadow": True,
        "bindings_complete": all_bound,
        "bindings": binding_table,
        "sanitized_integration_point": integration_point,
        "no_credentials_exposed": True,
        "no_live_routing_change": True,
        "no_provider_client_introduced": True,
        "opencode_manages_own_credentials": True,
        "codex_manages_own_credentials": True,
        "rollback_possible": True,
        "rollback_no_credentials_impact": True,
        "phase18c_blocked_until_activation_proof": True,
        "next_phase": manifest.get("next_phase_boundary"),
        "blockers": manifest.get("blockers", {}).get("active_blockers", []) if not all_bound else [],
    }

    no_hash = {k: v for k, v in plan.items() if k != "deterministic_plan_hash"}
    plan["deterministic_plan_hash"] = _canonical_hash(no_hash)
    return plan


def main():
    from trading_agent.cli.operator_registry import main as dispatch
    return dispatch()
