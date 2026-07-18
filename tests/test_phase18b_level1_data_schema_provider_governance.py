"""Tests for Phase 18B — Level 1 Data Schema and Provider Governance Checkpoint.

Covers: Common Record Contract (17 fields), 4 record schemas, Dataset Manifest
Schema (37 fields), 10 Provider Roles, 23 Quality Scenarios, Governance Manifest
(deterministic_governance_hash), Checkpoint Command, and CI invariants.
"""

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
PROPOSALS_DIR = REPO / "docs" / "strategy-proposals"
GOVERNANCE_DIR = PROPOSALS_DIR / "data-governance"
OPERATOR = REPO / "ibkr_operator.py"

# Phase 18B document paths
EQUITY_BAR_SCHEMA = GOVERNANCE_DIR / "EQUITY_BAR_SCHEMA_v0_1.json"
BTC_SPOT_BAR_SCHEMA = GOVERNANCE_DIR / "BTC_SPOT_BAR_SCHEMA_v0_1.json"
CORPORATE_EVENT_SCHEMA = GOVERNANCE_DIR / "CORPORATE_EVENT_SCHEMA_v0_1.json"
OPTION_CHAIN_SNAPSHOT_SCHEMA = GOVERNANCE_DIR / "OPTION_CHAIN_SNAPSHOT_SCHEMA_v0_1.json"
DATASET_MANIFEST_SCHEMA = GOVERNANCE_DIR / "DATASET_MANIFEST_SCHEMA_v0_1.json"
PROVIDER_GOVERNANCE = GOVERNANCE_DIR / "MSTR_BTC_PROVIDER_GOVERNANCE_v0_1.json"
DATA_QUALITY_POLICY = GOVERNANCE_DIR / "MSTR_BTC_DATA_QUALITY_POLICY_v0_1.json"
PHASE18B_MANIFEST = GOVERNANCE_DIR / "mstr_btc_data_governance_v0_1.manifest.json"

PHASE18A_MANIFEST = PROPOSALS_DIR / "mstr_btc_research_v0_1.manifest.json"
CANONICAL_STRATEGY = REPO / "docs" / "STRATEGY.md"

CHECKPOINT = REPO / "level1-data-schema-provider-governance-checkpoint"
CHECKPOINT_ALIASES = [REPO / "phase18b", REPO / "data-schema-provider-governance"]

RECORD_SCHEMAS = [
    ("equity_bar_schema", EQUITY_BAR_SCHEMA),
    ("btc_spot_bar_schema", BTC_SPOT_BAR_SCHEMA),
    ("corporate_event_schema", CORPORATE_EVENT_SCHEMA),
    ("option_chain_snapshot_schema", OPTION_CHAIN_SNAPSHOT_SCHEMA),
]

ALL_GOVERNANCE_DOCS = RECORD_SCHEMAS + [
    ("dataset_manifest_schema", DATASET_MANIFEST_SCHEMA),
    ("provider_governance", PROVIDER_GOVERNANCE),
    ("data_quality_policy", DATA_QUALITY_POLICY),
]

GOVERNED_FILE_LIST = [
    "EQUITY_BAR_SCHEMA_v0_1.json",
    "BTC_SPOT_BAR_SCHEMA_v0_1.json",
    "CORPORATE_EVENT_SCHEMA_v0_1.json",
    "OPTION_CHAIN_SNAPSHOT_SCHEMA_v0_1.json",
    "DATASET_MANIFEST_SCHEMA_v0_1.json",
    "MSTR_BTC_PROVIDER_GOVERNANCE_v0_1.json",
    "MSTR_BTC_DATA_QUALITY_POLICY_v0_1.json",
]

EXPECTED_PROVIDER_ROLES = [
    "EQUITY_BARS_PRIMARY", "EQUITY_BARS_SECONDARY",
    "BTC_SPOT_PRIMARY", "BTC_SPOT_SECONDARY",
    "CORPORATE_EVENTS_PRIMARY", "CORPORATE_EVENTS_SECONDARY",
    "OPTION_SNAPSHOTS_PRIMARY", "OPTION_SNAPSHOTS_SECONDARY",
    "MARKET_CALENDAR_REFERENCE", "CORPORATE_ACTION_REFERENCE",
]

EXPECTED_QUALITY_SCENARIOS = [
    "missing_records", "stale_records", "duplicate_records",
    "conflicting_records", "out_of_order_records", "future_dated_records",
    "revised_records", "malformed_timestamps", "invalid_prices",
    "invalid_volumes", "incomplete_bars", "adjustment_mismatches",
    "provider_disagreement", "venue_disagreement", "missing_corporate_events",
    "ambiguous_event_availability", "invalid_option_markets",
    "missing_point_in_time_option_snapshots", "look_ahead_contamination",
    "cross_track_contamination", "schema_version_mismatch",
    "manifest_hash_mismatch", "source_license_uncertainty",
]

COMMON_REQUIRED_FIELDS = [
    "schema_version", "record_id", "raw_record_hash", "provider_role_id",
    "provider_record_id", "instrument_id", "asset_class", "research_track",
    "execution_eligible", "event_timestamp_utc", "source_timestamp_utc",
    "ingestion_timestamp_utc", "available_at_utc", "revision_number",
    "is_final", "data_quality_state",
]

TIMESTAMP_FIELDS = ["event_timestamp_utc", "source_timestamp_utc", "ingestion_timestamp_utc", "available_at_utc"]

FORBIDDEN_SUBSTRINGS = [
    "broker", "order_id", "account_id", "execution_id", "approval_id",
    "h1_token", "x-h1-token", "credential", "api_key", "api_secret",
    "endpoint_url", "trading_token",
]

CREDENTIAL_FORBIDDEN = ["api_key", "apikey", "api_secret", "passwor", "secret_key",
                         "access_token", "bearer_token"]


# ── Helpers ──────────────────────────────────────────────────────────────────

def _load_manifest() -> dict:
    assert PHASE18B_MANIFEST.exists()
    with open(PHASE18B_MANIFEST) as f:
        return json.load(f)

def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def _load_json(path: Path) -> dict:
    assert path.exists()
    with open(path) as f:
        return json.load(f)

def _compute_deterministic_governance_hash(manifest_path: Path) -> str:
    with open(manifest_path) as f:
        m = json.load(f)
    no_hash = {k: v for k, v in m.items() if k != "deterministic_governance_hash"}
    return hashlib.sha256(json.dumps(no_hash, sort_keys=True, ensure_ascii=False).encode()).hexdigest()

def _run_checkpoint() -> dict:
    result = subprocess.run([sys.executable, str(CHECKPOINT)], capture_output=True, text=True, timeout=30)
    return json.loads(result.stdout)


# ══════════════════════════════════════════════════════════════════════════════
# DOCUMENT EXISTENCE & JSON
# ══════════════════════════════════════════════════════════════════════════════

class TestDocumentExistence:
    @pytest.mark.parametrize("name,path", ALL_GOVERNANCE_DOCS)
    def test_exists(self, name, path): assert path.exists()
    def test_manifest(self): assert PHASE18B_MANIFEST.exists()
    def test_strategy_md(self): assert (REPO / "docs" / "STRATEGY.md").exists()
    def test_strategy_v1(self):
        sv1 = REPO / "docs" / "strategy_v1.md"
        assert sv1.exists() and "Strategy v1" in sv1.read_text()
    def test_18a_intact(self):
        for p in [PROPOSALS_DIR / "MSTR_BTC_RESEARCH_PROPOSAL_v0_1.md",
                   PROPOSALS_DIR / "MSTR_BTC_DATA_REQUIREMENTS_v0_1.md",
                   PHASE18A_MANIFEST]:
            assert p.exists(), f"Missing: {p}"


class TestJsonValidity:
    @pytest.mark.parametrize("name,path", ALL_GOVERNANCE_DOCS)
    def test_valid_json(self, name, path):
        assert isinstance(_load_json(path), dict)
    def test_manifest_valid(self): assert isinstance(_load_manifest(), dict)


# ══════════════════════════════════════════════════════════════════════════════
# GOVERNANCE MANIFEST — STRUCTURE
# ══════════════════════════════════════════════════════════════════════════════

class TestManifestStructure:
    def test_version(self): assert _load_manifest()["manifest_version"] == "1.0.0"
    def test_id(self): assert _load_manifest()["manifest_id"] == "mstr_btc_data_governance_v0_1.manifest"
    def test_governance_id(self): assert _load_manifest()["governance_id"] == "mstr_btc_data_governance_v0_1"
    def test_phase(self): assert _load_manifest()["phase"] == "18B"
    def test_schema_count(self): assert _load_manifest()["schema_count"] == 5
    def test_provider_role_count(self): assert _load_manifest()["provider_role_count"] == 10
    def test_quality_outcomes(self):
        qo = _load_manifest()["quality_outcomes"]
        for o in ["ACCEPT", "ACCEPT_WITH_WARNING", "QUARANTINE", "REJECT", "NO_TRADE"]:
            assert o in qo

    def test_governed_files_count(self): assert len(_load_manifest()["governed_files"]) == 7

    def test_governed_files_order(self):
        actual_order = [g["file"] for g in _load_manifest()["governed_files"]]
        assert actual_order == GOVERNED_FILE_LIST

    def test_governed_files_have_paths(self):
        for g in _load_manifest()["governed_files"]:
            assert g["path"].startswith("docs/strategy-proposals/data-governance/")
            assert "sha256" in g
            assert g["version"] == "0.1"

    def test_phase18a_fields(self):
        m = _load_manifest()
        assert m["phase18a_proposal_id"] == "mstr_btc_research_v0_1"
        assert m["phase18a_proposal_version"] == "0.1"
        assert "phase18a_manifest_path" in m
        assert len(m["phase18a_manifest_sha256"]) == 64

    def test_canonical_strategy_fields(self):
        m = _load_manifest()
        assert m["canonical_strategy_path"] == "docs/STRATEGY.md"
        assert len(m["canonical_strategy_sha256"]) == 64

    def test_non_actions_min_count(self):
        assert len(_load_manifest()["explicit_non_actions"]) >= 20

    def test_blockers(self):
        b = _load_manifest()["blockers"]
        assert isinstance(b, dict)
        assert "active_blockers" in b
        assert isinstance(b["active_blockers"], list)
        assert len(b["active_blockers"]) == 0  # no active blockers

    def test_has_deterministic_governance_hash(self):
        m = _load_manifest()
        h = m["deterministic_governance_hash"]
        assert len(h) == 64 and all(c in "0123456789abcdef" for c in h)


class TestManifestCoreValues:
    MANIFEST_VALUES = {
        "governance_state": "SCHEMA_CONTRACT_READY",
        "strategy_readiness": "S0",
        "data_readiness": "D0",
        "autonomy_level": 1,
        "research_only": True,
        "execution_scope": "NONE",
        "collection_scope": "NONE",
        "provider_integration_scope": "NONE",
        "storage_runtime_scope": "NONE",
        "permitted_activity": "SCHEMA_AND_PROVIDER_CONTRACT_VALIDATION_ONLY",
        "provider_binding_state": "UNBOUND",
        "next_phase_boundary": "PHASE18C_SYNTHETIC_SCHEMA_CONFORMANCE",
        "canonical_strategy_unchanged": True,
        "phase18a_artifacts_unchanged": True,
    }
    @pytest.mark.parametrize("k,v", MANIFEST_VALUES.items())
    def test_value(self, k, v): assert _load_manifest()[k] == v


class TestManifestAuthFlags:
    FLAGS = ["network_access_authorized", "credentials_authorized", "collection_authorized",
              "ingestion_authorized", "storage_runtime_authorized", "scheduler_authorized",
              "backtest_authorized", "modeling_authorized", "forecasting_authorized",
              "candidate_generation_authorized", "execution_authorized",
              "allowlist_change", "rules_change", "broker_change", "guard_change"]
    @pytest.mark.parametrize("f", FLAGS)
    def test_false(self, f): assert _load_manifest()[f] is False


# ══════════════════════════════════════════════════════════════════════════════
# GOVERNANCE MANIFEST — HASHES
# ══════════════════════════════════════════════════════════════════════════════

class TestGovernedFileHashes:
    @pytest.mark.parametrize("file_name", GOVERNED_FILE_LIST)
    def test_hash_matches(self, file_name):
        m = _load_manifest()
        gf_entry = next(g for g in m["governed_files"] if g["file"] == file_name)
        actual_path = GOVERNANCE_DIR / file_name
        actual_hash = _sha256_file(actual_path)
        assert actual_hash == gf_entry["sha256"], f"Hash mismatch for {file_name}"


class TestDeterministicGovernanceHash:
    def test_match(self):
        m = _load_manifest()
        assert m["deterministic_governance_hash"] == _compute_deterministic_governance_hash(PHASE18B_MANIFEST)
    def test_reproducible_10_runs(self):
        stored = _load_manifest()["deterministic_governance_hash"]
        for _ in range(10):
            assert _compute_deterministic_governance_hash(PHASE18B_MANIFEST) == stored

    @pytest.mark.heavy
    def test_reproducible_20(self):
        stored = _load_manifest()["deterministic_governance_hash"]
        for _ in range(20):
            assert _compute_deterministic_governance_hash(PHASE18B_MANIFEST) == stored


class TestUpstreamHashes:
    def test_phase18a_manifest_hash(self):
        m = _load_manifest()
        actual = _sha256_file(PHASE18A_MANIFEST)
        assert actual == m["phase18a_manifest_sha256"]

    def test_canonical_strategy_hash(self):
        m = _load_manifest()
        actual = _sha256_file(CANONICAL_STRATEGY)
        assert actual == m["canonical_strategy_sha256"]


# ══════════════════════════════════════════════════════════════════════════════
# COMMON RECORD CONTRACT
# ══════════════════════════════════════════════════════════════════════════════

class TestCommonRecordContract:
    @pytest.mark.parametrize("sname,spath", RECORD_SCHEMAS)
    @pytest.mark.parametrize("field", COMMON_REQUIRED_FIELDS)
    def test_common_field_required(self, sname, spath, field):
        assert field in _load_json(spath).get("required", []), f"{sname}: missing '{field}'"

    @pytest.mark.parametrize("sname,spath", RECORD_SCHEMAS)
    def test_execution_eligible_const_false(self, sname, spath):
        ee = _load_json(spath)["properties"]["execution_eligible"]
        assert ee.get("const") is False and ee.get("type") == "boolean"

    @pytest.mark.parametrize("sname,spath", RECORD_SCHEMAS)
    def test_additional_properties_false(self, sname, spath):
        assert _load_json(spath).get("additionalProperties") is False

    @pytest.mark.parametrize("sname,spath", RECORD_SCHEMAS)
    def test_schema_version_const(self, sname, spath):
        assert _load_json(spath)["properties"]["schema_version"].get("const") == "0.1"

    @pytest.mark.parametrize("sname,spath", RECORD_SCHEMAS)
    def test_raw_record_hash_sha256(self, sname, spath):
        assert "64" in _load_json(spath)["properties"]["raw_record_hash"].get("pattern", "")

    @pytest.mark.parametrize("sname,spath", RECORD_SCHEMAS)
    def test_data_quality_state_enum(self, sname, spath):
        enums = _load_json(spath)["properties"]["data_quality_state"]["enum"]
        for v in ["PASSED", "FLAGGED", "DEGRADED", "REJECTED"]:
            assert v in enums


# ══════════════════════════════════════════════════════════════════════════════
# CROSS-DOCUMENT GOVERNANCE IDENTITY
# ══════════════════════════════════════════════════════════════════════════════

class TestCrossDocIdentity:
    @pytest.mark.parametrize("name,path", ALL_GOVERNANCE_DOCS)
    def test_gi_present(self, name, path):
        gi = _load_json(path)["governance_identity"]
        assert gi["governance_id"] == "mstr_btc_data_governance_v0_1"
        assert gi["governance_state"] == "SCHEMA_CONTRACT_READY"
        assert gi["execution_scope"] == "NONE"
        assert gi["research_only"] is True

    @pytest.mark.parametrize("name,path", ALL_GOVERNANCE_DOCS)
    def test_version_0_1(self, name, path): assert _load_json(path)["version"] == "0.1"


# ══════════════════════════════════════════════════════════════════════════════
# VENDOR NEUTRALITY / FORBIDDEN CONTENT
# ══════════════════════════════════════════════════════════════════════════════

class TestVendorNeutral:
    @pytest.mark.parametrize("name,path", ALL_GOVERNANCE_DOCS)
    def test_no_credential_strings(self, name, path):
        serialized = json.dumps(_load_json(path)).lower()
        for fb in CREDENTIAL_FORBIDDEN:
            assert fb not in serialized, f"{name}: forbidden credential string '{fb}'"

    @pytest.mark.parametrize("sname,spath", RECORD_SCHEMAS)
    def test_property_names_no_broker(self, sname, spath):
        keys = " ".join(_load_json(spath)["properties"].keys()).lower()
        for fb in FORBIDDEN_SUBSTRINGS:
            assert fb not in keys, f"{sname}: forbidden '{fb}' in property names"

    NEGATION_PATTERNS = ["must not contain", "must not be", "no ", "do not",
                           "must not appear", "must never be"]

    @pytest.mark.parametrize("sname,spath", RECORD_SCHEMAS)
    def test_descriptions_no_forbidden(self, sname, spath):
        for pn, pv in _load_json(spath)["properties"].items():
            desc = pv.get("description", "").lower()
            for fb in FORBIDDEN_SUBSTRINGS:
                if fb not in desc:
                    continue
                if any(pattern in desc for pattern in self.NEGATION_PATTERNS):
                    continue
                assert False, f"{sname}.{pn}: forbidden '{fb}' in description (non-negated)"


# ══════════════════════════════════════════════════════════════════════════════
# TIMESTAMPS
# ══════════════════════════════════════════════════════════════════════════════

class TestTimestamps:
    @pytest.mark.parametrize("sname,spath", RECORD_SCHEMAS)
    @pytest.mark.parametrize("ts", TIMESTAMP_FIELDS)
    def test_date_time(self, sname, spath, ts):
        p = _load_json(spath)["properties"][ts]
        assert p.get("type") == "string" and p.get("format") == "date-time"

    @pytest.mark.parametrize("sname,spath", RECORD_SCHEMAS)
    def test_distinct_descriptions(self, sname, spath):
        props = _load_json(spath)["properties"]
        descs = {tf: props[tf].get("description", "") for tf in TIMESTAMP_FIELDS}
        assert len(set(descs.values())) == 4, f"{sname}: timestamp descriptions not distinct"

    @pytest.mark.parametrize("sname,spath", RECORD_SCHEMAS)
    def test_no_substitution_rule(self, sname, spath):
        assert "no_timestamp_substitution" in _load_json(spath).get("validation_rules", {})


# ══════════════════════════════════════════════════════════════════════════════
# EQUITY BAR SCHEMA
# ══════════════════════════════════════════════════════════════════════════════

class TestEquityBar:
    REQ = ["symbol", "venue", "currency", "bar_interval", "session_type",
            "open", "high", "low", "close", "volume", "adjusted",
            "corporate_action_state", "quote_condition", "bar_completion_state"]
    def test_asset_class(self): assert _load_json(EQUITY_BAR_SCHEMA)["properties"]["asset_class"]["const"] == "equity"
    @pytest.mark.parametrize("f", REQ)
    def test_required(self, f): assert f in _load_json(EQUITY_BAR_SCHEMA)["required"]


# ══════════════════════════════════════════════════════════════════════════════
# BTC SPOT BAR SCHEMA
# ══════════════════════════════════════════════════════════════════════════════

class TestBtcSpotBar:
    def test_asset_class(self): assert _load_json(BTC_SPOT_BAR_SCHEMA)["properties"]["asset_class"]["const"] == "crypto_spot"
    def test_base_btc(self): assert _load_json(BTC_SPOT_BAR_SCHEMA)["properties"]["base_asset"]["const"] == "BTC"
    def test_quote_usd(self): assert _load_json(BTC_SPOT_BAR_SCHEMA)["properties"]["quote_asset"]["const"] == "USD"
    def test_research_track(self): assert _load_json(BTC_SPOT_BAR_SCHEMA)["properties"]["research_track"]["const"] == "TRACK_A_MSTR_BTC"
    def test_boundaries(self):
        bb = _load_json(BTC_SPOT_BAR_SCHEMA)["btc_boundaries"]
        assert bb["btc_execution_scope"] == "NONE"
        assert bb["no_crypto_trading_fields"] is True


# ══════════════════════════════════════════════════════════════════════════════
# CORPORATE EVENT SCHEMA
# ══════════════════════════════════════════════════════════════════════════════

class TestCorporateEvent:
    def test_asset_class(self): assert _load_json(CORPORATE_EVENT_SCHEMA)["properties"]["asset_class"]["const"] == "equity"
    def test_materiality_enum(self):
        enums = _load_json(CORPORATE_EVENT_SCHEMA)["properties"]["materiality_state"]["enum"]
        assert "MATERIAL_CONFIRMED" in enums
    def test_event_status_enum(self):
        enums = _load_json(CORPORATE_EVENT_SCHEMA)["properties"]["event_status"]["enum"]
        for v in ["ANNOUNCED", "AMENDED", "SUPERSEDED"]:
            assert v in enums
    def test_effective_at_utc_not_required(self):
        assert "effective_at_utc" not in _load_json(CORPORATE_EVENT_SCHEMA)["required"]


# ══════════════════════════════════════════════════════════════════════════════
# OPTION CHAIN SNAPSHOT SCHEMA
# ══════════════════════════════════════════════════════════════════════════════

class TestOptionChainSnapshot:
    def test_simulation_only_const_true(self):
        assert _load_json(OPTION_CHAIN_SNAPSHOT_SCHEMA)["properties"]["simulation_only"]["const"] is True
    def test_point_in_time_snapshot_const_true(self):
        assert _load_json(OPTION_CHAIN_SNAPSHOT_SCHEMA)["properties"]["point_in_time_snapshot"]["const"] is True
    def test_option_right_enum(self):
        enums = _load_json(OPTION_CHAIN_SNAPSHOT_SCHEMA)["properties"]["option_right"]["enum"]
        assert enums == ["CALL", "PUT"]


# ══════════════════════════════════════════════════════════════════════════════
# DATASET MANIFEST SCHEMA
# ══════════════════════════════════════════════════════════════════════════════

class TestDatasetManifest:
    def test_raw_data_immutable_const_true(self):
        assert _load_json(DATASET_MANIFEST_SCHEMA)["properties"]["raw_data_immutable"]["const"] is True
    def test_collection_authorized_const_false(self):
        assert _load_json(DATASET_MANIFEST_SCHEMA)["properties"]["collection_authorized"]["const"] is False
    def test_execution_eligible_const_false(self):
        assert _load_json(DATASET_MANIFEST_SCHEMA)["properties"]["execution_eligible"]["const"] is False
    def test_lookahead_detected_const_false(self):
        assert _load_json(DATASET_MANIFEST_SCHEMA)["properties"]["lookahead_detected"]["const"] is False
    def test_additional_properties_false(self):
        assert _load_json(DATASET_MANIFEST_SCHEMA).get("additionalProperties") is False


# ══════════════════════════════════════════════════════════════════════════════
# PROVIDER GOVERNANCE
# ══════════════════════════════════════════════════════════════════════════════

class TestProviderGovernance:
    def test_global_unbound(self):
        pg = _load_json(PROVIDER_GOVERNANCE)
        assert pg["provider_binding_summary"]["global_binding_state"] == "UNBOUND"
        assert "No provider is bound" in pg["provider_binding_summary"]["description"]

    @pytest.mark.parametrize("role_id", EXPECTED_PROVIDER_ROLES)
    def test_role_exists(self, role_id):
        assert role_id in _load_json(PROVIDER_GOVERNANCE)["provider_roles"]

    @pytest.mark.parametrize("role_id", EXPECTED_PROVIDER_ROLES)
    def test_role_unbound(self, role_id):
        role = _load_json(PROVIDER_GOVERNANCE)["provider_roles"][role_id]
        assert role["provider_binding_state"] == "UNBOUND"

    @pytest.mark.parametrize("role_id", EXPECTED_PROVIDER_ROLES)
    def test_role_not_implemented(self, role_id):
        role = _load_json(PROVIDER_GOVERNANCE)["provider_roles"][role_id]
        assert role["integration_state"] == "NOT_IMPLEMENTED"

    @pytest.mark.parametrize("role_id", EXPECTED_PROVIDER_ROLES)
    def test_role_credentials_false(self, role_id):
        role = _load_json(PROVIDER_GOVERNANCE)["provider_roles"][role_id]
        assert role["credentials_authorized"] is False

    @pytest.mark.parametrize("role_id", EXPECTED_PROVIDER_ROLES)
    def test_role_network_false(self, role_id):
        role = _load_json(PROVIDER_GOVERNANCE)["provider_roles"][role_id]
        assert role["network_access_authorized"] is False

    @pytest.mark.parametrize("role_id", EXPECTED_PROVIDER_ROLES)
    def test_role_collection_false(self, role_id):
        role = _load_json(PROVIDER_GOVERNANCE)["provider_roles"][role_id]
        assert role["collection_authorized"] is False

    @pytest.mark.parametrize("role_id", EXPECTED_PROVIDER_ROLES)
    def test_role_human_approval_required(self, role_id):
        role = _load_json(PROVIDER_GOVERNANCE)["provider_roles"][role_id]
        assert role["human_binding_approval_required"] is True
        assert role["licensing_review_required"] is True

    @pytest.mark.parametrize("role_id", EXPECTED_PROVIDER_ROLES)
    def test_role_has_data_domain(self, role_id):
        role = _load_json(PROVIDER_GOVERNANCE)["provider_roles"][role_id]
        assert "data_domain" in role
        assert "priority" in role
        assert "required_or_optional" in role

    def test_role_rules_count(self):
        rules = _load_json(PROVIDER_GOVERNANCE)["provider_role_rules"]["rules"]
        assert len(rules) >= 12

    def test_non_actions(self):
        na = _load_json(PROVIDER_GOVERNANCE)["non_actions"]
        assert len(na) >= 8


# ══════════════════════════════════════════════════════════════════════════════
# DATA QUALITY POLICY
# ══════════════════════════════════════════════════════════════════════════════

class TestDataQualityPolicy:
    def test_real_data_state(self):
        rds = _load_json(DATA_QUALITY_POLICY)["real_data_state"]
        assert rds["real_data_thresholds_frozen"] is False
        assert rds["provider_bindings_frozen"] is False
        assert rds["real_data_use_authorized"] is False

    def test_quality_outcomes(self):
        qo = _load_json(DATA_QUALITY_POLICY)["quality_outcomes"]
        for o in ["ACCEPT", "ACCEPT_WITH_WARNING", "QUARANTINE", "REJECT", "NO_TRADE"]:
            assert o in qo

    @pytest.mark.parametrize("scenario", EXPECTED_QUALITY_SCENARIOS)
    def test_scenario_covered(self, scenario):
        coverage = _load_json(DATA_QUALITY_POLICY)["quality_score_calculation"]["coverage_matrix"]
        assert scenario in coverage, f"Scenario '{scenario}' not covered"

    def test_fail_closed_rules_count(self):
        rules = _load_json(DATA_QUALITY_POLICY)["fail_closed_principle"]["rules"]
        assert len(rules) >= 14

    def test_six_dimensions(self):
        dims = _load_json(DATA_QUALITY_POLICY)["quality_dimensions"]
        for d in ["completeness", "freshness", "accuracy", "consistency", "temporal_integrity", "lineage_and_versioning"]:
            assert d in dims

    def test_non_actions(self):
        na = _load_json(DATA_QUALITY_POLICY)["non_actions"]
        assert len(na) >= 5


# ══════════════════════════════════════════════════════════════════════════════
# CHECKPOINT COMMAND
# ══════════════════════════════════════════════════════════════════════════════

class TestCheckpointCommand:
    def test_exists(self): assert CHECKPOINT.exists()
    def test_executable(self): assert os.access(CHECKPOINT, os.X_OK)

    @pytest.mark.parametrize("alias_path", CHECKPOINT_ALIASES)
    def test_alias_exists(self, alias_path): assert alias_path.exists()

    def test_checkpoint_output_valid_json(self):
        result = _run_checkpoint()
        assert isinstance(result, dict)

    def test_checkpoint_state_ready(self):
        result = _run_checkpoint()
        assert result["governance_state"] == "SCHEMA_CONTRACT_READY"

    def test_checkpoint_all_auth_false(self):
        result = _run_checkpoint()
        assert result["all_authorization_flags_false"] is True

    def test_checkpoint_no_blockers(self):
        result = _run_checkpoint()
        assert result["blockers"] == []

    def test_checkpoint_fields(self):
        result = _run_checkpoint()
        required_fields = [
            "command", "checkpoint_version", "governance_id",
            "governance_state", "strategy_readiness", "data_readiness",
            "autonomy_level", "research_only", "execution_scope",
            "collection_scope", "provider_binding_state",
            "schema_count", "provider_role_count",
            "document_integrity", "schema_integrity",
            "provider_governance_integrity", "quality_policy_integrity",
            "upstream_phase18a_integrity", "canonical_strategy_integrity",
            "point_in_time_governance", "all_authorization_flags_false",
            "deterministic_evidence_hash", "blockers",
            "explicit_non_actions", "next_phase_boundary",
            "output_labels", "diagnosis",
        ]
        for rf in required_fields:
            assert rf in result, f"Missing checkpoint output field: {rf}"

    def test_checkpoint_deterministic_evidence_hash(self):
        result1 = _run_checkpoint()
        result2 = _run_checkpoint()
        assert result1["deterministic_evidence_hash"] == result2["deterministic_evidence_hash"]

    def test_checkpoint_integrity_all_true(self):
        result = _run_checkpoint()
        for k in ["document_integrity", "schema_integrity",
                   "provider_governance_integrity", "quality_policy_integrity",
                   "upstream_phase18a_integrity", "canonical_strategy_integrity"]:
            assert result[k].get("overall") is True, f"{k} integrity failed"

    def test_checkpoint_exit_zero(self):
        cp = subprocess.run([sys.executable, str(CHECKPOINT)], capture_output=True)
        assert cp.returncode == 0

    def test_checkpoint_no_files_written(self):
        mtime_before = {str(g[1]): g[1].stat().st_mtime for g in
                        [(n, GOVERNANCE_DIR / n) for n in GOVERNED_FILE_LIST]}
        _run_checkpoint()
        for name, path in [(n, GOVERNANCE_DIR / n) for n in GOVERNED_FILE_LIST]:
            assert path.stat().st_mtime == mtime_before[str(path)], f"{name} was modified by checkpoint"


class TestCheckpointAliases:
    @pytest.mark.parametrize("alias_name,alias_path", [
        ("phase18b", CHECKPOINT_ALIASES[0]),
        ("data-schema-provider-governance", CHECKPOINT_ALIASES[1]),
    ])
    def test_alias_output(self, alias_name, alias_path):
        result = subprocess.run([sys.executable, str(alias_path)], capture_output=True, text=True, timeout=30)
        assert result.returncode == 0
        d = json.loads(result.stdout)
        assert d["command"] == "level1-data-schema-provider-governance-checkpoint"
        assert d["governance_state"] == "SCHEMA_CONTRACT_READY"


# ══════════════════════════════════════════════════════════════════════════════
# IBKR-OPERATOR CLI REGISTRATION
# ══════════════════════════════════════════════════════════════════════════════

OPERATOR_CLI_COMMANDS = [
    "level1-data-schema-provider-governance-checkpoint",
    "phase18b",
    "data-schema-provider-governance",
]


def _run_operator_cli(command: str) -> dict:
    result = subprocess.run(
        [sys.executable, str(REPO / "ibkr_operator.py"), command, "--json"],
        capture_output=True, text=True, timeout=30,
        cwd=str(REPO),
    )
    assert result.returncode == 0, f"CLI '{command}' failed: {result.stderr}"
    return json.loads(result.stdout)


class TestOperatorCliRegistration:
    @pytest.mark.parametrize("command", OPERATOR_CLI_COMMANDS)
    def test_command_succeeds(self, command):
        result = _run_operator_cli(command)
        assert isinstance(result, dict)

    @pytest.mark.parametrize("command", OPERATOR_CLI_COMMANDS)
    def test_state_ready(self, command):
        result = _run_operator_cli(command)
        assert result["governance_state"] == "SCHEMA_CONTRACT_READY"

    @pytest.mark.parametrize("command", OPERATOR_CLI_COMMANDS)
    def test_execution_scope_none(self, command):
        result = _run_operator_cli(command)
        assert result["execution_scope"] == "NONE"

    @pytest.mark.parametrize("command", OPERATOR_CLI_COMMANDS)
    def test_collection_scope_none(self, command):
        result = _run_operator_cli(command)
        assert result["collection_scope"] == "NONE"

    @pytest.mark.parametrize("command", OPERATOR_CLI_COMMANDS)
    def test_provider_binding_unbound(self, command):
        result = _run_operator_cli(command)
        assert result["provider_binding_state"] == "UNBOUND"

    @pytest.mark.parametrize("command", OPERATOR_CLI_COMMANDS)
    def test_blockers_empty(self, command):
        result = _run_operator_cli(command)
        assert result["blockers"] == []

    def test_all_three_identical_hash(self):
        results = {cmd: _run_operator_cli(cmd) for cmd in OPERATOR_CLI_COMMANDS}
        hashes = [r["deterministic_evidence_hash"] for r in results.values()]
        assert len(set(hashes)) == 1, f"Hashes differ: {dict(zip(OPERATOR_CLI_COMMANDS, hashes))}"

    def test_all_three_valid_json(self):
        for cmd in OPERATOR_CLI_COMMANDS:
            d = _run_operator_cli(cmd)
            assert isinstance(d, dict)
            assert "deterministic_evidence_hash" in d
            assert len(d["deterministic_evidence_hash"]) == 64

    def test_help_lists_canonical_command(self):
        result = subprocess.run(
            [sys.executable, str(REPO / "ibkr_operator.py"), "--help"],
            capture_output=True, text=True, timeout=30,
        )
        assert "level1-data-schema-provider-governance-checkpoint" in result.stdout

    def test_help_lists_phase18b_alias(self):
        result = subprocess.run(
            [sys.executable, str(REPO / "ibkr_operator.py"), "--help"],
            capture_output=True, text=True, timeout=30,
        )
        assert "phase18b" in result.stdout

    def test_help_lists_data_schema_alias(self):
        result = subprocess.run(
            [sys.executable, str(REPO / "ibkr_operator.py"), "--help"],
            capture_output=True, text=True, timeout=30,
        )
        assert "data-schema-provider-governance" in result.stdout

    def test_cli_does_not_mutate_files(self):
        mtimes = {}
        for path in GOVERNANCE_DIR.glob("*.json"):
            mtimes[str(path)] = path.stat().st_mtime
        _run_operator_cli("phase18b")
        _run_operator_cli("level1-data-schema-provider-governance-checkpoint")
        _run_operator_cli("data-schema-provider-governance")
        for path in GOVERNANCE_DIR.glob("*.json"):
            assert path.stat().st_mtime == mtimes[str(path)], f"{path.name} modified by CLI"

    def test_cli_no_duplicate_logic_between_aliases(self):
        # All three command names route to the same dispatch block.
        # Exclude timestamp/checkpoint_id (which vary by second) —
        # verify all semantic governance fields are identical.
        results = {cmd: _run_operator_cli(cmd) for cmd in OPERATOR_CLI_COMMANDS}
        canonical = results["level1-data-schema-provider-governance-checkpoint"]
        exclude = {"timestamp", "checkpoint_id"}
        for cmd in ["phase18b", "data-schema-provider-governance"]:
            for k, v in canonical.items():
                if k in exclude:
                    continue
                assert results[cmd][k] == v, f"{cmd}.{k} differs from canonical"


# ══════════════════════════════════════════════════════════════════════════════
# COMPILE & CI INVARIANTS
# ══════════════════════════════════════════════════════════════════════════════

class TestPhase18aIntegrity:
    def test_hash(self):
        m = _load_json(PHASE18A_MANIFEST)
        stored = m["deterministic_manifest_hash"]
        no_h = {k: v for k, v in m.items() if k != "deterministic_manifest_hash"}
        computed = hashlib.sha256(json.dumps(no_h, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        assert stored == computed


class TestDiagnosisMap:
    def test_ready(self):
        assert _load_manifest()["phase18b_diagnosis"]["ready"] == "phase18b_data_schema_provider_governance_ok"
    def test_active_blockers_empty(self):
        assert _load_manifest()["phase18b_diagnosis"]["active_blockers"] == []


class TestOutputLabels:
    LABELS = ["PHASE18B_DATA_SCHEMA_PROVIDER_GOVERNANCE", "SCHEMA_CONTRACT_READY",
              "RESEARCH_ONLY", "NON_EXECUTABLE", "NO_EXECUTION_SCOPE",
              "NO_COLLECTION_SCOPE", "NO_PROVIDER_BINDING", "NO_NETWORK_ACCESS",
              "NO_ALLOWLIST_CHANGE", "NO_BROKER_MUTATION", "NO_H1_ACCESSED",
              "STRATEGY_V1_UNCHANGED", "PHASE18A_ARTIFACTS_UNCHANGED",
              "S0_READINESS", "D0_DATA_READINESS", "LEVEL1",
              "SCHEMA_AND_PROVIDER_CONTRACT_VALIDATION_ONLY",
              "FAIL_CLOSED_ENFORCED", "TEN_PROVIDER_ROLES_DEFINED",
              "TWENTY_THREE_QUALITY_SCENARIOS_COVERED", "VENDOR_NEUTRAL"]
    @pytest.mark.parametrize("label", LABELS)
    def test_present(self, label): assert label in _load_manifest()["required_output_labels"]


class TestPrinciples:
    def test_section(self):
        dgp = _load_manifest()["data_governance_principles"]
        assert dgp["all_timestamps_utc"] is True
        assert dgp["raw_data_immutable"] is True
        assert dgp["fail_closed_is_default"] is True
        assert dgp["logical_roles_are_not_provider_selections"] is True


class TestCiInvariants:
    def test_forbidden_files_exist(self):
        for rel in ["bridge.py", "guard.py", ".env", "docs/STRATEGY.md"]:
            assert (REPO / rel).exists()

    def test_no_checkpoint_writes_files(self):
        mtimes = {}
        for path in GOVERNANCE_DIR.glob("*.json"):
            mtimes[str(path)] = path.stat().st_mtime
        subprocess.run([sys.executable, str(CHECKPOINT)], capture_output=True, timeout=30)
        for path in GOVERNANCE_DIR.glob("*.json"):
            assert path.stat().st_mtime == mtimes[str(path)], f"{path.name} modified by checkpoint run"


class TestCompileCheck:
    def test_operator(self):
        assert subprocess.run([sys.executable, "-m", "py_compile", str(OPERATOR)], capture_output=True).returncode == 0
    def test_bridge(self):
        assert subprocess.run([sys.executable, "-m", "py_compile", str(REPO / "bridge.py")], capture_output=True).returncode == 0
    def test_guard(self):
        assert subprocess.run([sys.executable, "-m", "py_compile", str(REPO / "guard.py")], capture_output=True).returncode == 0
    def test_checkpoint(self):
        assert subprocess.run([sys.executable, "-m", "py_compile", str(CHECKPOINT)], capture_output=True).returncode == 0
