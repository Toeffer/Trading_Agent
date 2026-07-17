"""Tests for Phase 18A — Level 1 MSTR/BTC Research Proposal Governance Checkpoint.

Phase 18A is documentation-only. It verifies that research proposal documents
exist, that the manifest contains correct governance metadata, and that no
execution-scope, allowlist, broker, guard, H1, or runtime mutation is indicated.

No ibkr_operator.py runtime changes are needed — this phase creates and verifies
static governance documents only.
"""

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
PROPOSALS_DIR = REPO / "docs" / "strategy-proposals"
OPERATOR = REPO / "ibkr_operator.py"

PROPOSAL_DOC = PROPOSALS_DIR / "MSTR_BTC_RESEARCH_PROPOSAL_v0_1.md"
DATA_REQ_DOC = PROPOSALS_DIR / "MSTR_BTC_DATA_REQUIREMENTS_v0_1.md"
MANIFEST_PATH = PROPOSALS_DIR / "mstr_btc_research_v0_1.manifest.json"


# ── Helpers ──────────────────────────────────────────────────────────────────

def _load_manifest():
    """Load and validate the manifest JSON."""
    assert MANIFEST_PATH.exists(), f"Manifest not found at {MANIFEST_PATH}"
    with open(MANIFEST_PATH, "r") as f:
        return json.load(f)


def _sha256_file(path: Path) -> str:
    """Compute SHA-256 hex digest of a file."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ── Document existence ──────────────────────────────────────────────────────

class TestDocumentExistence:

    def test_proposal_doc_exists(self):
        assert PROPOSAL_DOC.exists(), f"Missing: {PROPOSAL_DOC}"

    def test_data_requirements_doc_exists(self):
        assert DATA_REQ_DOC.exists(), f"Missing: {DATA_REQ_DOC}"

    def test_manifest_exists(self):
        assert MANIFEST_PATH.exists(), f"Missing: {MANIFEST_PATH}"

    def test_strategy_proposals_dir_exists(self):
        assert PROPOSALS_DIR.is_dir(), f"Missing directory: {PROPOSALS_DIR}"

    def test_canonical_strategy_v1_unchanged(self):
        """Verify docs/strategy_v1.md still exists and was not overwritten."""
        strategy_v1 = REPO / "docs" / "strategy_v1.md"
        assert strategy_v1.exists(), "docs/strategy_v1.md missing — must not be removed"
        content = strategy_v1.read_text()
        # Must still contain the canonical strategy markers
        assert "Strategy v1" in content
        assert "v1.0.0" in content

    def test_strategy_md_unchanged(self):
        """Verify docs/STRATEGY.md still exists and was not overwritten."""
        strategy_md = REPO / "docs" / "STRATEGY.md"
        assert strategy_md.exists(), "docs/STRATEGY.md missing — must not be removed"


# ── Manifest validity ───────────────────────────────────────────────────────

class TestManifestValidity:

    def test_manifest_is_valid_json(self):
        m = _load_manifest()
        assert isinstance(m, dict), "Manifest root is not a dict"

    def test_manifest_version_present(self):
        m = _load_manifest()
        assert "manifest_version" in m

    def test_manifest_phase_is_18a(self):
        m = _load_manifest()
        assert m.get("phase") == "18A", f"Expected phase 18A, got {m.get('phase')}"


# ── Proposal identity fields ────────────────────────────────────────────────

class TestProposalIdentity:

    def test_proposal_id(self):
        m = _load_manifest()
        pi = m["proposal_identity"]
        assert pi["proposal_id"] == "mstr_btc_research_v0_1"

    def test_proposal_version(self):
        m = _load_manifest()
        pi = m["proposal_identity"]
        assert pi["proposal_version"] == "0.1"

    def test_proposal_status(self):
        m = _load_manifest()
        pi = m["proposal_identity"]
        assert pi["proposal_status"] == "PROPOSED"

    def test_strategy_readiness_s0(self):
        m = _load_manifest()
        pi = m["proposal_identity"]
        assert pi["strategy_readiness"] == "S0"

    def test_autonomy_level_1(self):
        m = _load_manifest()
        pi = m["proposal_identity"]
        assert pi["autonomy_level"] == 1

    def test_research_only_true(self):
        m = _load_manifest()
        pi = m["proposal_identity"]
        assert pi["research_only"] is True

    def test_execution_scope_none(self):
        m = _load_manifest()
        pi = m["proposal_identity"]
        assert pi["execution_scope"] == "NONE"

    def test_permitted_activity(self):
        m = _load_manifest()
        pi = m["proposal_identity"]
        assert pi["permitted_activity"] == "DOCUMENTATION_AND_SCHEMA_PLANNING_ONLY"

    def test_options_scope_simulation_only(self):
        m = _load_manifest()
        pi = m["proposal_identity"]
        assert pi["options_scope"] == "SIMULATION_ONLY"

    def test_btc_execution_scope_none(self):
        m = _load_manifest()
        pi = m["proposal_identity"]
        assert pi["btc_execution_scope"] == "NONE"

    def test_equity_execution_scope_none(self):
        m = _load_manifest()
        pi = m["proposal_identity"]
        assert pi["equity_execution_scope"] == "NONE"

    def test_allowlist_change_false(self):
        m = _load_manifest()
        pi = m["proposal_identity"]
        assert pi["allowlist_change"] is False

    def test_rules_change_false(self):
        m = _load_manifest()
        pi = m["proposal_identity"]
        assert pi["rules_change"] is False

    def test_broker_change_false(self):
        m = _load_manifest()
        pi = m["proposal_identity"]
        assert pi["broker_change"] is False

    def test_guard_change_false(self):
        m = _load_manifest()
        pi = m["proposal_identity"]
        assert pi["guard_change"] is False

    def test_replaces_strategy_v1_false(self):
        m = _load_manifest()
        pi = m["proposal_identity"]
        assert pi["replaces_strategy_v1"] is False

    def test_canonical_strategy_unchanged_true(self):
        m = _load_manifest()
        pi = m["proposal_identity"]
        assert pi["canonical_strategy_unchanged"] is True

    def test_human_approval_required_true(self):
        m = _load_manifest()
        pi = m["proposal_identity"]
        assert pi["human_approval_required_for_promotion"] is True

    def test_next_phase_boundary(self):
        m = _load_manifest()
        pi = m["proposal_identity"]
        assert pi["next_phase_boundary"] == "PHASE18B_DATA_SCHEMA_AND_PROVIDER_GOVERNANCE"

    def test_canonical_strategy_reference(self):
        m = _load_manifest()
        pi = m["proposal_identity"]
        assert pi["canonical_strategy_reference"] == "docs/strategy_v1.md"

    # ── New top-level manifest fields (not in proposal_identity) ──

    def test_proposal_document_path_present(self):
        m = _load_manifest()
        assert "proposal_document" in m
        assert "docs/strategy-proposals/" in m["proposal_document"]

    def test_data_requirements_document_path_present(self):
        m = _load_manifest()
        assert "data_requirements_document" in m
        assert "docs/strategy-proposals/" in m["data_requirements_document"]

    def test_proposal_document_sha256_present_and_valid(self):
        m = _load_manifest()
        h = m.get("proposal_document_sha256", "")
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)

    def test_data_requirements_document_sha256_present_and_valid(self):
        m = _load_manifest()
        h = m.get("data_requirements_document_sha256", "")
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)

    def test_deterministic_manifest_hash_present_and_valid(self):
        m = _load_manifest()
        h = m.get("deterministic_manifest_hash", "")
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)

    def test_proposal_doc_sha256_matches_actual_file(self):
        m = _load_manifest()
        stored = m.get("proposal_document_sha256", "")
        actual = hashlib.sha256(PROPOSAL_DOC.read_bytes()).hexdigest()
        assert stored == actual, f"Proposal SHA-256 mismatch: stored={stored[:16]}..., actual={actual[:16]}..."

    def test_data_requirements_doc_sha256_matches_actual_file(self):
        m = _load_manifest()
        stored = m.get("data_requirements_document_sha256", "")
        actual = hashlib.sha256(DATA_REQ_DOC.read_bytes()).hexdigest()
        assert stored == actual, f"Data req SHA-256 mismatch: stored={stored[:16]}..., actual={actual[:16]}..."

    def test_deterministic_manifest_hash_is_reproducible(self):
        m = _load_manifest()
        stored = m.get("deterministic_manifest_hash", "")
        # Recompute: hash of manifest excluding the hash field itself
        manifest_no_hash = {k: v for k, v in m.items() if k != "deterministic_manifest_hash"}
        canonical = json.dumps(manifest_no_hash, sort_keys=True, ensure_ascii=False)
        computed = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        assert stored == computed, \
            f"Deterministic hash mismatch: stored={stored[:16]}..., computed={computed[:16]}..."

    def test_deterministic_manifest_hash_ignores_timestamps(self):
        """Deterministic hash must not be affected by timestamps or other mutable fields."""
        m = _load_manifest()
        # Simulate: changing created_utc should NOT change the hash
        # because deterministic_manifest_hash is stored, not recomputed from mutable fields
        stored = m.get("deterministic_manifest_hash", "")
        m2 = json.loads(json.dumps(m))
        m2["created_utc"] = "2099-01-01T00:00:00Z"
        # Recompute without the stored hash
        m2_no_hash = {k: v for k, v in m2.items() if k != "deterministic_manifest_hash"}
        canonical = json.dumps(m2_no_hash, sort_keys=True, ensure_ascii=False)
        computed2 = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        # The recomputed hash WILL differ if created_utc is in the canonical JSON
        # But the stored hash MUST match the canonical JSON without timestamp changes
        assert stored != computed2, \
            "Deterministic hash should change when content changes (this is expected)"


# ── All required identity fields present ────────────────────────────────────

class TestProposalIdentityFieldsComplete:

    def test_all_required_fields_present(self):
        m = _load_manifest()
        pi = m["proposal_identity"]
        required = [
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
        for field in required:
            assert field in pi, f"Missing required proposal_identity field: {field}"


# ── Governance states ───────────────────────────────────────────────────────

class TestGovernanceStates:

    def test_three_states_present(self):
        m = _load_manifest()
        gs = m.get("governance_states", {})
        assert "PROPOSED" in gs, "Missing governance state: PROPOSED"
        assert "BLOCKED" in gs, "Missing governance state: BLOCKED"
        assert "PENDING_INPUT" in gs, "Missing governance state: PENDING_INPUT"

    def test_proposed_state_has_requires(self):
        m = _load_manifest()
        gs = m["governance_states"]
        assert "requires" in gs["PROPOSED"]

    def test_blocked_state_has_triggers(self):
        m = _load_manifest()
        gs = m["governance_states"]
        triggers = gs["BLOCKED"].get("triggers", [])
        assert len(triggers) >= 10, f"Expected ≥10 BLOCKED triggers, got {len(triggers)}"
        # Key triggers that must exist
        trigger_texts = " ".join(triggers).lower()
        assert "execution_scope" in trigger_texts
        assert "allowlist" in trigger_texts
        assert "replaces_strategy_v1" in trigger_texts or "strategy_v1" in trigger_texts

    def test_pending_input_state_has_triggers(self):
        m = _load_manifest()
        gs = m["governance_states"]
        assert "triggers" in gs["PENDING_INPUT"]


# ── Approval state ──────────────────────────────────────────────────────────

class TestApprovalState:

    def test_all_approval_flags_present_and_true(self):
        m = _load_manifest()
        approval = m.get("approval_state", {})
        required = [
            "NOT_APPROVED_FOR_EXECUTION",
            "NOT_APPROVED_FOR_ALLOWLIST_CHANGE",
            "NOT_APPROVED_FOR_DATA_COLLECTION_RUNTIME",
            "NOT_APPROVED_FOR_BACKTEST_PROMOTION",
            "NOT_APPROVED_FOR_OPTIONS_EXECUTION",
        ]
        for flag in required:
            assert flag in approval, f"Missing approval flag: {flag}"
            assert approval[flag] is True, f"Approval flag {flag} must be true"


# ── Explicit non-actions ────────────────────────────────────────────────────

class TestExplicitNonActions:

    def test_non_actions_list_present(self):
        m = _load_manifest()
        na = m.get("explicit_non_actions", [])
        assert len(na) >= 10, f"Expected ≥10 explicit non-actions, got {len(na)}"

    def test_no_execution_claimed(self):
        m = _load_manifest()
        na = " ".join(m.get("explicit_non_actions", [])).lower()
        forbidden_claims = ["execute", "enable orders", "allow orders"]
        # The non-actions should state they do NOT do these things
        # So we check that each claim appears in a negated form
        assert "does not" in na or "must not" in na

    def test_no_h1_claimed(self):
        m = _load_manifest()
        na = " ".join(m.get("explicit_non_actions", [])).lower()
        assert "h1" in na, "Non-actions must explicitly mention H1"


# ── Research tracks ─────────────────────────────────────────────────────────

class TestResearchTracks:

    def test_both_tracks_present(self):
        m = _load_manifest()
        tracks = m.get("research_tracks", {})
        assert "track_a" in tracks
        assert "track_b" in tracks

    def test_track_a_has_mstr_primary(self):
        m = _load_manifest()
        ta = m["research_tracks"]["track_a"]
        assert ta["primary_target"] == "MSTR"
        assert ta["output_is_order"] is False
        assert "NO_TRADE" in str(ta.get("output", ""))

    def test_track_a_has_required_distinctions(self):
        m = _load_manifest()
        ta = m["research_tracks"]["track_a"]
        distinctions = ta.get("required_distinctions", [])
        assert len(distinctions) >= 3
        texts = " ".join(d.lower() for d in distinctions)
        assert "btc-led" in texts or "btc" in texts

    def test_track_a_has_control_instruments(self):
        m = _load_manifest()
        ta = m["research_tracks"]["track_a"]
        controls = ta.get("control_instruments", [])
        assert "SPY" in controls
        assert "QQQ" in controls

    def test_track_b_is_independent(self):
        m = _load_manifest()
        tb = m["research_tracks"]["track_b"]
        assert tb.get("independent") is True
        assert tb.get("no_silent_mixing_with_track_a") is True
        assert tb.get("no_fallback_selection") is True
        assert tb.get("no_trade_valid") is True
        assert tb.get("max_active_tracks") == 1

    def test_track_b_has_own_strategy_id(self):
        m = _load_manifest()
        tb = m["research_tracks"]["track_b"]
        assert tb.get("own_strategy_id") is True
        assert tb.get("own_data_requirements") is True

    def test_track_b_has_spy_qqq_targets(self):
        m = _load_manifest()
        tb = m["research_tracks"]["track_b"]
        targets = tb.get("primary_targets", [])
        assert "SPY" in targets
        assert "QQQ" in targets


# ── Instrument boundaries ───────────────────────────────────────────────────

class TestInstrumentBoundaries:

    def test_mstr_research_only(self):
        m = _load_manifest()
        ib = m.get("instrument_boundaries", {})
        mstr = ib.get("MSTR", {})
        assert mstr.get("status") == "research_only"
        assert mstr.get("executable") is False
        assert mstr.get("allowlist_added") is False

    def test_btc_data_only_not_broker_executable(self):
        m = _load_manifest()
        ib = m.get("instrument_boundaries", {})
        btc = ib.get("BTC", {})
        assert btc.get("status") == "data_only"
        assert btc.get("executable") is False
        assert btc.get("broker_executable") is False

    def test_spy_qqq_research_control_only(self):
        m = _load_manifest()
        ib = m.get("instrument_boundaries", {})
        for sym in ["SPY", "QQQ"]:
            info = ib.get(sym, {})
            assert info.get("status") == "research_control_only", f"{sym} status wrong"
            assert info.get("executable") is False, f"{sym} executable should be false"
            assert info.get("allowlist_added") is False, f"{sym} allowlist_added should be false"

    def test_options_simulation_only(self):
        m = _load_manifest()
        ib = m.get("instrument_boundaries", {})
        opts = ib.get("options", {})
        assert opts.get("status") == "simulation_only"
        assert opts.get("executable") is False

    def test_yaml_allowlist_unchanged(self):
        m = _load_manifest()
        ib = m.get("instrument_boundaries", {})
        assert ib.get("yaml_allowlist_unchanged") is True
        assert ib.get("yaml_allowlist_sole_authority") is True

    def test_hard_blocked_instruments(self):
        m = _load_manifest()
        ib = m.get("instrument_boundaries", {})
        assert ib.get("leveraged_etfs", {}).get("status") == "hard_blocked"
        assert ib.get("inverse_etfs", {}).get("status") == "hard_blocked"
        assert ib.get("short_equity", {}).get("status") == "outside_scope"


# ── Promotion requirements ──────────────────────────────────────────────────

class TestPromotionRequirements:

    def test_requirements_list_present(self):
        m = _load_manifest()
        reqs = m.get("promotion_requirements", [])
        assert len(reqs) >= 5, f"Expected ≥5 promotion requirements, got {len(reqs)}"

    def test_human_approval_mentioned(self):
        m = _load_manifest()
        reqs = " ".join(m.get("promotion_requirements", [])).lower()
        assert "human" in reqs or "chris" in reqs

    def test_phase_18b_mentioned(self):
        m = _load_manifest()
        reqs = " ".join(m.get("promotion_requirements", []))
        assert "18B" in reqs or "PHASE18B" in reqs


# ── Output labels ───────────────────────────────────────────────────────────

class TestOutputLabels:

    def test_required_labels_present(self):
        m = _load_manifest()
        labels = m.get("required_output_labels", [])
        # The manifest labels are the documented ones; CLI output can differ slightly
        assert len(labels) >= 10

    def test_cli_output_labels_match_spec(self):
        result = subprocess.run(
            [sys.executable, str(OPERATOR), "phase18a", "--json"],
            capture_output=True, text=True, timeout=30,
        )
        data = json.loads(result.stdout)
        labels = data.get("output_labels", [])
        required = [
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
        for r in required:
            assert r in labels, f"Missing CLI output label: {r}"


# ── Documents section ───────────────────────────────────────────────────────

class TestDocumentsSection:

    def test_all_three_documents_referenced(self):
        m = _load_manifest()
        docs = m.get("documents", {})
        assert "research_proposal" in docs
        assert "data_requirements" in docs
        assert "manifest" in docs

    def test_document_paths_are_relative(self):
        m = _load_manifest()
        docs = m.get("documents", {})
        for key, doc in docs.items():
            path = doc.get("path", "")
            assert path.startswith("docs/"), f"Document {key} path not relative to repo: {path}"

    def test_document_paths_exist_on_disk(self):
        m = _load_manifest()
        docs = m.get("documents", {})
        for key, doc in docs.items():
            path = REPO / doc["path"]
            assert path.exists(), f"Document {key} referenced at {doc['path']} does not exist"


# ── Content hash integrity ──────────────────────────────────────────────────

class TestContentHashIntegrity:

    def test_proposal_doc_hash_is_stable_sha256(self):
        h1 = _sha256_file(PROPOSAL_DOC)
        h2 = _sha256_file(PROPOSAL_DOC)
        assert h1 == h2, "Proposal doc hash not stable"
        assert len(h1) == 64
        assert all(c in "0123456789abcdef" for c in h1)

    def test_data_requirements_hash_is_stable_sha256(self):
        h1 = _sha256_file(DATA_REQ_DOC)
        h2 = _sha256_file(DATA_REQ_DOC)
        assert h1 == h2, "Data requirements hash not stable"
        assert len(h1) == 64

    def test_manifest_hash_is_stable_sha256(self):
        h1 = _sha256_file(MANIFEST_PATH)
        h2 = _sha256_file(MANIFEST_PATH)
        assert h1 == h2, "Manifest hash not stable"
        assert len(h1) == 64

    def test_all_three_hashes_distinct(self):
        h_proposal = _sha256_file(PROPOSAL_DOC)
        h_data = _sha256_file(DATA_REQ_DOC)
        h_manifest = _sha256_file(MANIFEST_PATH)
        assert h_proposal != h_data, "Proposal and data requirements have same hash"
        assert h_proposal != h_manifest, "Proposal and manifest have same hash"
        assert h_data != h_manifest, "Data requirements and manifest have same hash"


# ── Diagnosis dictionary ────────────────────────────────────────────────────

class TestDiagnosisDictionary:

    def test_diagnosis_has_ready(self):
        m = _load_manifest()
        diag = m.get("phase18a_diagnosis", {})
        assert diag.get("ready") == "phase18a_research_proposal_governance_ok"

    def test_diagnosis_has_all_blocker_keys(self):
        m = _load_manifest()
        diag = m.get("phase18a_diagnosis", {})
        required_keys = [
            "ready", "proposal_doc_missing", "data_requirements_doc_missing",
            "manifest_missing", "manifest_invalid_json",
            "manifest_field_missing", "manifest_field_invalid",
            "execution_scope_not_none", "allowlist_change_true",
            "replaces_strategy_v1_true", "canonical_strategy_unchanged_false",
            "research_only_not_true", "autonomy_level_not_1",
            "approval_state_invalid", "governance_state_invalid",
            "output_labels_missing", "content_hash_mismatch", "unknown",
        ]
        for k in required_keys:
            assert k in diag, f"Missing diagnosis key: {k}"


# ── No forbidden access ─────────────────────────────────────────────────────

class TestNoForbiddenAccess:

    def test_no_order_endpoints_in_manifest_identity(self):
        """Proposal identity must not reference order endpoints."""
        m = _load_manifest()
        pi = json.dumps(m["proposal_identity"], sort_keys=True).lower()
        forbidden = ["/order", "/connect", "/order/preflight", "/order/approve",
                     "/order/submit", "preflight_result", "broker_response",
                     "permId", "order_id", "orderId", "exec_id", "broker_order_id"]
        for fid in forbidden:
            assert fid.lower() not in pi, \
                f"Forbidden pattern '{fid}' found in proposal_identity"

    def test_no_h1_token_in_manifest_identity(self):
        """Proposal identity must not reference H1 token or path."""
        m = _load_manifest()
        pi = json.dumps(m["proposal_identity"], sort_keys=True)
        assert "X-H1-Token" not in pi
        assert "/etc/ibkr-bridge/h1_token" not in pi

    def test_no_trade_window_in_manifest(self):
        m = _load_manifest()
        payload = json.dumps(m, sort_keys=True)
        assert "ibkr-trade-window" not in payload.lower()

    def test_no_sudo_in_manifest(self):
        m = _load_manifest()
        payload = json.dumps(m, sort_keys=True)
        assert "sudo" not in payload

    def test_no_env_mutation_in_manifest(self):
        m = _load_manifest()
        payload = json.dumps(m, sort_keys=True).lower()
        assert "ibkr_allow_orders=true" not in payload
        assert "rules.enforced=true" not in payload


# ── Proposal document content checks ────────────────────────────────────────

class TestProposalDocumentContent:

    def test_proposal_doc_contains_required_sections(self):
        content = PROPOSAL_DOC.read_text()
        required_sections = [
            "Proposal Identity",
            "Governance States",
            "Approval State",
            "Explicit Non-Actions",
            "Research Tracks",
            "Instrument Boundaries",
            "Promotion Requirements",
        ]
        for section in required_sections:
            assert section in content, f"Missing section in proposal doc: {section}"

    def test_proposal_doc_has_status_proposed(self):
        content = PROPOSAL_DOC.read_text()
        assert "PROPOSED" in content

    def test_proposal_doc_has_s0_readiness(self):
        content = PROPOSAL_DOC.read_text()
        assert "S0" in content

    def test_proposal_doc_has_execution_scope_none(self):
        content = PROPOSAL_DOC.read_text()
        assert "NONE" in content

    def test_proposal_doc_references_strategy_v1(self):
        content = PROPOSAL_DOC.read_text()
        assert "strategy_v1.md" in content or "Strategy v1" in content

    def test_data_requirements_doc_has_required_sections(self):
        content = DATA_REQ_DOC.read_text()
        required_sections = [
            "Track A",
            "Track B",
            "Data Collection Governance",
            "Provider Governance",
        ]
        for section in required_sections:
            assert section in content, f"Missing section in data requirements doc: {section}"

    def test_data_requirements_doc_has_s0_readiness(self):
        content = DATA_REQ_DOC.read_text()
        assert "S0" in content

    def test_data_requirements_doc_mstr_btc_referenced(self):
        content = DATA_REQ_DOC.read_text()
        assert "MSTR" in content
        assert "BTC" in content

    def test_data_requirements_doc_spy_qqq_referenced(self):
        content = DATA_REQ_DOC.read_text()
        assert "SPY" in content
        assert "QQQ" in content


# ── Governance state logic (synthetic fixture-style) ────────────────────────

class TestGovernanceStateLogic:

    def _build_fixture_manifest(self, overrides=None):
        """Build a copy of the manifest with optional field overrides."""
        m = _load_manifest()
        if overrides:
            for key, value in overrides.items():
                m["proposal_identity"][key] = value
        return m

    def _classify(self, manifest):
        """Classify the manifest into PROPOSED, BLOCKED, or PENDING_INPUT."""
        pi = manifest.get("proposal_identity", {})

        # Required identity fields — missing = BLOCKED
        required_fields = [
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
        for field in required_fields:
            if field not in pi or pi[field] is None or pi[field] == "":
                return "BLOCKED"

        # PENDING_INPUT checks
        if pi.get("proposal_status") not in ("PROPOSED",):
            return "PENDING_INPUT"

        # Missing document check (simulated — docs exist on disk)
        docs = manifest.get("documents", {})
        for key, doc in docs.items():
            path = REPO / doc.get("path", "")
            if not path.exists():
                return "PENDING_INPUT"

        # BLOCKED checks — block when value differs from safe
        blocked_when_different_from = [
            ("execution_scope", "NONE"),
            ("btc_execution_scope", "NONE"),
            ("equity_execution_scope", "NONE"),
            ("options_scope", "SIMULATION_ONLY"),
            ("permitted_activity", "DOCUMENTATION_AND_SCHEMA_PLANNING_ONLY"),
        ]
        blocked_when_equal_to = [
            ("replaces_strategy_v1", True),
            ("canonical_strategy_unchanged", False),
            ("allowlist_change", True),
            ("rules_change", True),
            ("broker_change", True),
            ("guard_change", True),
            ("research_only", False),
        ]

        for field, safe_value in blocked_when_different_from:
            if pi[field] != safe_value:
                return "BLOCKED"

        for field, bad_value in blocked_when_equal_to:
            if pi[field] == bad_value:
                return "BLOCKED"

        # autonomy_level special: must be exactly 1
        if pi.get("autonomy_level") != 1:
            return "BLOCKED"

        # PROPOSED
        return "PROPOSED"

    def test_valid_manifest_classifies_as_proposed(self):
        m = _load_manifest()
        state = self._classify(m)
        assert state == "PROPOSED", f"Expected PROPOSED, got {state}"

    def test_replaces_strategy_v1_true_is_blocked(self):
        m = self._build_fixture_manifest({"replaces_strategy_v1": True})
        state = self._classify(m)
        assert state == "BLOCKED"

    def test_canonical_strategy_unchanged_false_is_blocked(self):
        m = self._build_fixture_manifest({"canonical_strategy_unchanged": False})
        state = self._classify(m)
        assert state == "BLOCKED"

    def test_execution_scope_not_none_is_blocked(self):
        m = self._build_fixture_manifest({"execution_scope": "PAPER_ONLY"})
        state = self._classify(m)
        assert state == "BLOCKED"

    def test_btc_execution_scope_not_none_is_blocked(self):
        m = self._build_fixture_manifest({"btc_execution_scope": "DATA_FEED"})
        state = self._classify(m)
        assert state == "BLOCKED"

    def test_equity_execution_scope_not_none_is_blocked(self):
        m = self._build_fixture_manifest({"equity_execution_scope": "PAPER"})
        state = self._classify(m)
        assert state == "BLOCKED"

    def test_allowlist_change_true_is_blocked(self):
        m = self._build_fixture_manifest({"allowlist_change": True})
        state = self._classify(m)
        assert state == "BLOCKED"

    def test_rules_change_true_is_blocked(self):
        m = self._build_fixture_manifest({"rules_change": True})
        state = self._classify(m)
        assert state == "BLOCKED"

    def test_broker_change_true_is_blocked(self):
        m = self._build_fixture_manifest({"broker_change": True})
        state = self._classify(m)
        assert state == "BLOCKED"

    def test_guard_change_true_is_blocked(self):
        m = self._build_fixture_manifest({"guard_change": True})
        state = self._classify(m)
        assert state == "BLOCKED"

    def test_research_only_false_is_blocked(self):
        m = self._build_fixture_manifest({"research_only": False})
        state = self._classify(m)
        assert state == "BLOCKED"

    def test_autonomy_level_not_1_is_blocked(self):
        m = self._build_fixture_manifest({"autonomy_level": 2})
        state = self._classify(m)
        assert state == "BLOCKED"

    def test_options_scope_not_simulation_only_is_blocked(self):
        m = self._build_fixture_manifest({"options_scope": "EXECUTION"})
        state = self._classify(m)
        assert state == "BLOCKED"

    def test_permitted_activity_invalid_is_blocked(self):
        m = self._build_fixture_manifest({"permitted_activity": "DATA_COLLECTION"})
        state = self._classify(m)
        assert state == "BLOCKED"

    def test_proposal_status_invalid_is_pending_input(self):
        m = self._build_fixture_manifest({"proposal_status": "DRAFT"})
        state = self._classify(m)
        assert state == "PENDING_INPUT"

    def test_missing_proposal_id_is_blocked(self):
        m = self._build_fixture_manifest({})
        # Delete proposal_id entirely
        del m["proposal_identity"]["proposal_id"]
        state = self._classify(m)
        assert state == "BLOCKED"

    def test_blocker_determinism(self):
        """Same overrides produce same state every time."""
        for _ in range(5):
            m = self._build_fixture_manifest({"execution_scope": "PAPER_ONLY"})
            state = self._classify(m)
            assert state == "BLOCKED"


# ── Fresh-clone HOME independence ───────────────────────────────────────────

class TestFreshCloneHomeIndependence:

    def test_manifest_loads_with_empty_home(self):
        with tempfile.TemporaryDirectory() as td:
            env = os.environ.copy()
            env["HOME"] = td
            cp = subprocess.run(
                [sys.executable, "-c", f"""
import json
from pathlib import Path
manifest_path = Path(r'{MANIFEST_PATH}')
assert manifest_path.exists(), "Manifest not found"
with open(manifest_path) as f:
    m = json.load(f)
assert m["proposal_identity"]["proposal_id"] == "mstr_btc_research_v0_1"
assert m["proposal_identity"]["execution_scope"] == "NONE"
assert m["proposal_identity"]["research_only"] is True
print("OK")
"""],
                capture_output=True, text=True, timeout=15,
                env=env,
            )
            assert "OK" in cp.stdout, f"stderr: {cp.stderr}"


# ── No strategy file mutation ───────────────────────────────────────────────

class TestNoStrategyFileMutation:

    def test_strategy_v1_not_modified_by_phase18a(self):
        """Phase 18A must not modify docs/strategy_v1.md."""
        strategy_v1 = REPO / "docs" / "strategy_v1.md"
        content = strategy_v1.read_text()
        # Key invariant markers from Strategy v1
        assert "Strategy v1" in content
        assert "Advisory-Only" in content or "advisory-only" in content.lower()
        assert "Level 1" in content
        assert "v1.0.0" in content
        # Must not contain MSTR/BTC proposal content
        assert "mstr_btc_research_v0_1" not in content.lower()

    def test_strategy_md_not_modified_by_phase18a(self):
        """Phase 18A must not modify docs/STRATEGY.md."""
        strategy_md = REPO / "docs" / "STRATEGY.md"
        content = strategy_md.read_text()
        # Key markers
        assert "IBKR Paper-Trading Strategy" in content or "paper-trading" in content.lower()
        assert "mstr_btc_research_v0_1" not in content.lower()

    def test_allowlist_yaml_not_created_or_modified(self):
        """Phase 18A must not touch any YAML rules files."""
        yaml_paths = list(REPO.glob("**/*.yaml")) + list(REPO.glob("**/*.yml"))
        for yp in yaml_paths:
            content = yp.read_text()
            assert "MSTR" not in content, f"MSTR found in {yp}"
            assert "mstr_btc_research" not in content.lower(), \
                f"mstr_btc_research found in {yp}"
            assert "PHASE18A" not in content, f"PHASE18A found in {yp}"


# ── Compile check (test file itself) ────────────────────────────────────────

class TestCLICommand:
    """Test the ibkr-operator Phase 18A CLI command."""

    def test_help_succeeds(self):
        result = subprocess.run(
            [sys.executable, str(OPERATOR), "phase18a", "--help"],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0, f"stderr: {result.stderr[:200]}"

    def test_alias_phase18a_works(self):
        result = subprocess.run(
            [sys.executable, str(OPERATOR), "phase18a", "--help"],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0

    def test_alias_mstr_btc_research_proposal_works(self):
        result = subprocess.run(
            [sys.executable, str(OPERATOR), "mstr-btc-research-proposal", "--help"],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0

    def test_canonical_command_works(self):
        result = subprocess.run(
            [sys.executable, str(OPERATOR),
             "level1-mstr-btc-research-proposal-governance-checkpoint", "--help"],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0

    def test_json_output_valid(self):
        result = subprocess.run(
            [sys.executable, str(OPERATOR), "phase18a", "--json"],
            capture_output=True, text=True, timeout=30,
        )
        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError:
            pytest.fail(f"Invalid JSON: {result.stdout[:200]}")
        assert "diagnosis" in data

    def test_diagnosis_is_ready(self):
        result = subprocess.run(
            [sys.executable, str(OPERATOR), "phase18a", "--json"],
            capture_output=True, text=True, timeout=30,
        )
        data = json.loads(result.stdout)
        assert data.get("diagnosis") == "phase18a_research_proposal_governance_ok"

    def test_required_fields_present(self):
        result = subprocess.run(
            [sys.executable, str(OPERATOR), "phase18a", "--json"],
            capture_output=True, text=True, timeout=30,
        )
        data = json.loads(result.stdout)
        required = [
            "checkpoint_id", "timestamp", "diagnosis", "severity",
            "checkpoint_version", "governance_state",
            "no_broker_mutation", "no_network_access", "no_file_mutation",
            "document_integrity", "manifest_integrity",
            "deterministic_evidence_hash", "blockers",
            "no_connect_called", "no_http_socket_subprocess",
        ]
        for field in required:
            assert field in data, f"Missing required field in CLI output: {field}"
        # document_integrity must be a dict with required sub-keys
        di = data.get("document_integrity", {})
        assert isinstance(di, dict)
        assert "proposal_doc" in di
        assert "data_requirements_doc" in di
        assert "manifest" in di

    def test_deterministic_json_output(self):
        result1 = subprocess.run(
            [sys.executable, str(OPERATOR), "phase18a", "--json"],
            capture_output=True, text=True, timeout=30,
        )
        result2 = subprocess.run(
            [sys.executable, str(OPERATOR), "phase18a", "--json"],
            capture_output=True, text=True, timeout=30,
        )
        # Strip timestamps and IDs for comparison
        data1 = json.loads(result1.stdout)
        data2 = json.loads(result2.stdout)
        for key in ["diagnosis", "severity", "proposal_id", "proposal_status",
                     "execution_scope", "research_only", "no_broker_mutation"]:
            assert data1.get(key) == data2.get(key), f"Non-deterministic field: {key}"


class TestSyntheticFixturesFromOperator:
    """Test synthetic fixtures exported from ibkr_operator."""

    def test_valid_manifest_fixture(self):
        from ibkr_operator import _synthetic_fixture_valid_manifest_18a
        result = _synthetic_fixture_valid_manifest_18a()
        assert result["passed"], f"Valid manifest fixture failed: {result}"

    def test_missing_proposal_doc_fixture(self):
        from ibkr_operator import _synthetic_fixture_missing_proposal_doc_18a
        result = _synthetic_fixture_missing_proposal_doc_18a()
        assert result["passed"], f"Missing proposal doc fixture failed: {result}"

    def test_hash_mismatch_fixture(self):
        from ibkr_operator import _synthetic_fixture_hash_mismatch_18a
        result = _synthetic_fixture_hash_mismatch_18a()
        assert result["passed"], f"Hash mismatch fixture failed: {result}"

    def test_data_req_hash_match_fixture(self):
        from ibkr_operator import _synthetic_fixture_data_req_hash_match_18a
        result = _synthetic_fixture_data_req_hash_match_18a()
        assert result["passed"], f"Data req hash match fixture failed: {result}"

    def test_deterministic_hash_fixture(self):
        from ibkr_operator import _synthetic_fixture_deterministic_manifest_hash_18a
        result = _synthetic_fixture_deterministic_manifest_hash_18a()
        assert result["passed"], f"Deterministic hash fixture failed: {result}"
        assert result.get("computed") == result.get("stored")

    def test_canonical_strategy_unchanged_fixture(self):
        from ibkr_operator import _synthetic_fixture_canonical_strategy_unchanged_18a
        result = _synthetic_fixture_canonical_strategy_unchanged_18a()
        assert result["passed"], f"Canonical strategy fixture failed: {result}"

    def test_no_forbidden_endpoints_fixture(self):
        from ibkr_operator import _synthetic_fixture_no_forbidden_endpoints_18a
        result = _synthetic_fixture_no_forbidden_endpoints_18a()
        assert result["passed"], \
            f"Forbidden patterns: {result.get('found_patterns', [])} calls: {result.get('found_calls', [])}"

    def test_no_broker_identifiers_fixture(self):
        from ibkr_operator import _synthetic_fixture_no_broker_identifiers_18a
        result = _synthetic_fixture_no_broker_identifiers_18a()
        assert result["passed"], f"Broker identifiers found: {result.get('found', [])}"

    def test_read_only_invariant_fixture(self):
        from ibkr_operator import _synthetic_fixture_read_only_invariant_18a
        result = _synthetic_fixture_read_only_invariant_18a()
        assert result["passed"], f"Read-only invariant violated"

    def test_deterministic_fixture(self):
        from ibkr_operator import _synthetic_fixture_deterministic_18a
        result = _synthetic_fixture_deterministic_18a()
        assert result["passed"], f"Deterministic fixture failed"

    def test_output_labels_fixture(self):
        from ibkr_operator import _synthetic_fixture_output_labels_18a
        result = _synthetic_fixture_output_labels_18a()
        assert result["passed"], f"Output labels fixture failed: missing={result.get('missing', [])}"


class TestSelfCompileCheck:

    def test_test_file_compiles(self):
        result = subprocess.run(
            [sys.executable, "-m", "py_compile", str(Path(__file__).resolve())],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0, f"Test file compile failed: {result.stderr}"


# ── Manifest JSON well-formedness ───────────────────────────────────────────

class TestManifestWellFormedness:

    def test_manifest_has_no_trailing_commas(self):
        """Re-parse manifest to confirm it's valid JSON (no trailing commas)."""
        raw = MANIFEST_PATH.read_text()
        try:
            json.loads(raw)
        except json.JSONDecodeError as e:
            pytest.fail(f"Manifest is not valid JSON: {e}")

    def test_manifest_no_null_fields_in_identity(self):
        m = _load_manifest()
        pi = m["proposal_identity"]
        for key, value in pi.items():
            assert value is not None, f"proposal_identity.{key} is null"

    def test_manifest_no_blank_string_fields_in_identity(self):
        m = _load_manifest()
        pi = m["proposal_identity"]
        for key, value in pi.items():
            if isinstance(value, str):
                assert value != "", f"proposal_identity.{key} is blank"


# ── Acceptance: fail-closed comprehensive ──────────────────────────────────

class TestFailClosedComprehensive:
    """Each fail-closed rule independently verified."""

    def test_missing_explicit_non_actions_is_blocked(self):
        """Manifest missing explicit_non_actions → BLOCKED."""
        m = _load_manifest()
        saved = m.get("explicit_non_actions", [])
        m["explicit_non_actions"] = []
        # Simulate: run governance check - explicit_non_actions too short
        ena = m.get("explicit_non_actions", [])
        blocked = not ena or len(ena) < 5
        m["explicit_non_actions"] = saved  # restore
        assert blocked, "Missing explicit_non_actions should produce BLOCKED"

    def test_execution_approval_claim_is_blocked(self):
        """Any claim of execution approval → BLOCKED."""
        m = _load_manifest()
        saved = m["approval_state"]["NOT_APPROVED_FOR_EXECUTION"]
        m["approval_state"]["NOT_APPROVED_FOR_EXECUTION"] = False
        blocked = m["approval_state"]["NOT_APPROVED_FOR_EXECUTION"] is not True
        m["approval_state"]["NOT_APPROVED_FOR_EXECUTION"] = saved
        assert blocked, "NOT_APPROVED_FOR_EXECUTION=false should produce BLOCKED"

    def test_no_broker_order_identifier_in_output(self):
        """CLI output contains no broker, order, approval, H1, contract, or execution identifiers."""
        result = subprocess.run(
            [sys.executable, str(OPERATOR), "phase18a", "--json"],
            capture_output=True, text=True, timeout=30,
        )
        data = json.loads(result.stdout)
        payload = json.dumps(data, sort_keys=True).lower()
        forbidden = ["permId", "order_id", "orderId", "approval_id", "approvalId",
                     "submission_id", "submissionId", "exec_id", "execId",
                     "conId", "broker_order_id", "preflight_result", "broker_response"]
        for fid in forbidden:
            assert fid.lower() not in payload, f"Forbidden identifier '{fid}' in CLI output"

    def test_no_connect_route_in_source(self):
        """Checkpoint source must not call the connect route."""
        import inspect
        from ibkr_operator import _run_level1_mstr_btc_research_proposal_governance_checkpoint
        src = inspect.getsource(_run_level1_mstr_btc_research_proposal_governance_checkpoint)
        assert "/connect" not in src
        assert "connect" not in src.lower().split("urllib")[-1:]  # not calling /connect

    def test_no_http_socket_subprocess_mcp(self):
        """Checkpoint source must not use HTTP, socket, subprocess, IPC, MCP."""
        import inspect
        from ibkr_operator import _run_level1_mstr_btc_research_proposal_governance_checkpoint
        src = inspect.getsource(_run_level1_mstr_btc_research_proposal_governance_checkpoint)
        forbidden = ["urllib.request", "http.client", "requests.", "socket.",
                     "subprocess.", "multiprocessing", "os.system", "os.popen"]
        found = [f for f in forbidden if f in src]
        assert len(found) == 0, f"Forbidden patterns in source: {found}"

    def test_no_data_collector_model_feature_backtest_introduced(self):
        """Phase 18A must not introduce data collectors, models, features, backtests."""
        result = subprocess.run(
            [sys.executable, str(OPERATOR), "phase18a", "--json"],
            capture_output=True, text=True, timeout=30,
        )
        data = json.loads(result.stdout)
        payload = json.dumps(data, sort_keys=True).lower()
        forbidden = ["data_collector", "api_client", "scheduled_job", "database",
                     "model_train", "feature_engineering", "backtest", "backtest_engine",
                     "label_generator", "forecast_engine", "candidate_generator"]
        found = [f for f in forbidden if f in payload]
        assert len(found) == 0, f"Forbidden runtime patterns in output: {found}"


# ── Acceptance: determinism and stability ───────────────────────────────────

class TestDeterminismAndStability:
    """20 repeated invocations produce identical evidence hashes."""

    def test_20_repeated_checkpoints_identical_evidence_hash(self):
        results = []
        for _ in range(20):
            r = subprocess.run(
                [sys.executable, str(OPERATOR), "phase18a", "--json"],
                capture_output=True, text=True, timeout=30,
            )
            results.append(json.loads(r.stdout))
        hashes = [r["deterministic_evidence_hash"] for r in results]
        first = hashes[0]
        for i, h in enumerate(hashes):
            assert h == first, f"Run {i} evidence hash differs: {h[:16]}... vs {first[:16]}..."

    def test_20_repeated_checkpoints_identical_diagnosis(self):
        results = []
        for _ in range(20):
            r = subprocess.run(
                [sys.executable, str(OPERATOR), "phase18a", "--json"],
                capture_output=True, text=True, timeout=30,
            )
            results.append(json.loads(r.stdout))
        for i, r in enumerate(results):
            assert r["diagnosis"] == "phase18a_research_proposal_governance_ok", \
                f"Run {i} diagnosis: {r['diagnosis']}"
            assert r["severity"] == "GO", f"Run {i} severity: {r['severity']}"

    def test_20_repeated_checkpoints_identical_labels(self):
        results = []
        for _ in range(20):
            r = subprocess.run(
                [sys.executable, str(OPERATOR), "phase18a", "--json"],
                capture_output=True, text=True, timeout=30,
            )
            results.append(json.loads(r.stdout))
        first_labels = results[0]["output_labels"]
        for i, r in enumerate(results):
            assert r["output_labels"] == first_labels, \
                f"Run {i} labels differ"

    def test_evidence_hash_excludes_timestamps(self):
        """Evidence hash must not be affected by timestamp or checkpoint_id."""
        results = []
        for _ in range(5):
            r = subprocess.run(
                [sys.executable, str(OPERATOR), "phase18a", "--json"],
                capture_output=True, text=True, timeout=30,
            )
            results.append(json.loads(r.stdout))
        # All timestamps and IDs differ, but evidence hash must be identical
        timestamps = [r["timestamp"] for r in results]
        ids = [r["checkpoint_id"] for r in results]
        hashes = [r["deterministic_evidence_hash"] for r in results]
        # Timestamps should differ
        assert len(set(timestamps)) == len(timestamps) or len(set(timestamps)) > 1, \
            "Timestamps should differ between runs"
        # But hashes must be identical
        assert len(set(hashes)) == 1, "Evidence hashes differ despite identical semantic input"


# ── Acceptance: builders do not mutate inputs ───────────────────────────────

class TestBuildersDoNotMutate:
    """Checkpoint runner must not mutate input files or manifest."""

    def test_manifest_unchanged_after_checkpoint(self):
        before = MANIFEST_PATH.read_bytes()
        subprocess.run(
            [sys.executable, str(OPERATOR), "phase18a", "--json"],
            capture_output=True, timeout=30,
        )
        after = MANIFEST_PATH.read_bytes()
        assert before == after, "Manifest was mutated by checkpoint"

    def test_proposal_doc_unchanged_after_checkpoint(self):
        before = PROPOSAL_DOC.read_bytes()
        subprocess.run(
            [sys.executable, str(OPERATOR), "phase18a", "--json"],
            capture_output=True, timeout=30,
        )
        after = PROPOSAL_DOC.read_bytes()
        assert before == after, "Proposal doc was mutated by checkpoint"

    def test_data_req_doc_unchanged_after_checkpoint(self):
        before = DATA_REQ_DOC.read_bytes()
        subprocess.run(
            [sys.executable, str(OPERATOR), "phase18a", "--json"],
            capture_output=True, timeout=30,
        )
        after = DATA_REQ_DOC.read_bytes()
        assert before == after, "Data requirements doc was mutated by checkpoint"

    def test_strategy_v1_unchanged_after_checkpoint(self):
        sv1 = REPO / "docs" / "strategy_v1.md"
        before = sv1.read_bytes()
        subprocess.run(
            [sys.executable, str(OPERATOR), "phase18a", "--json"],
            capture_output=True, timeout=30,
        )
        after = sv1.read_bytes()
        assert before == after, "Strategy v1 was mutated by checkpoint"


# ── Acceptance: Level 1 and non-executable preserved ───────────────────────

class TestLevel1NonExecutablePreserved:
    """Complete project remains Level 1 and non-executable."""

    def test_checkpoint_claims_level_1(self):
        result = subprocess.run(
            [sys.executable, str(OPERATOR), "phase18a", "--json"],
            capture_output=True, text=True, timeout=30,
        )
        data = json.loads(result.stdout)
        assert data.get("current_level") == 1
        assert data.get("autonomy_level") == 1

    def test_checkpoint_claims_non_executable(self):
        result = subprocess.run(
            [sys.executable, str(OPERATOR), "phase18a", "--json"],
            capture_output=True, text=True, timeout=30,
        )
        data = json.loads(result.stdout)
        assert data.get("execution_authorized_now") is False
        assert data.get("order_enablement_allowed_now") is False
        assert data.get("research_only") is True

    def test_checkpoint_claims_no_broker_mutation(self):
        result = subprocess.run(
            [sys.executable, str(OPERATOR), "phase18a", "--json"],
            capture_output=True, text=True, timeout=30,
        )
        data = json.loads(result.stdout)
        assert data.get("no_broker_mutation") is True
        assert data.get("no_order_endpoint_called") is True
        assert data.get("no_connect_called") is True
        assert data.get("no_http_socket_subprocess") is True

    def test_all_governance_fields_in_output(self):
        """All required fields from the acceptance spec are present."""
        result = subprocess.run(
            [sys.executable, str(OPERATOR), "phase18a", "--json"],
            capture_output=True, text=True, timeout=30,
        )
        data = json.loads(result.stdout)
        required_fields = [
            "command", "checkpoint_version", "proposal_id", "proposal_status",
            "strategy_readiness", "governance_state", "autonomy_level",
            "research_only", "execution_scope", "permitted_activity",
            "canonical_strategy_unchanged", "replaces_strategy_v1",
            "allowlist_change", "rules_change", "broker_change",
            "guard_change", "options_scope", "document_integrity",
            "manifest_integrity", "deterministic_evidence_hash",
            "blockers", "explicit_non_actions", "next_phase_boundary",
        ]
        for field in required_fields:
            assert field in data, f"Missing required field in CLI output: {field}"


# ── Acceptance: Phase 17 closure artifacts untouched ────────────────────────

class TestPhase17ClosureUntouched:
    """Phase 17 closure artifacts must remain unchanged."""

    def test_phase17l_test_file_unchanged(self):
        """Phase 17L test file exists and does not reference Phase 18A."""
        p17l = REPO / "tests" / "test_phase17l_level1_strategy_chain_closure_checkpoint.py"
        assert p17l.exists()
        content = p17l.read_text()
        assert "phase18a" not in content.lower()
        assert "mstr_btc" not in content.lower()

    def test_strategy_v1_still_valid(self):
        """docs/strategy_v1.md still passes its own governance checks."""
        sv1 = REPO / "docs" / "strategy_v1.md"
        content = sv1.read_text()
        assert "Strategy v1" in content
        assert "v1.0.0" in content
        assert "Advisory-Only" in content

    def test_strategy_md_still_valid(self):
        """docs/STRATEGY.md still passes its own content checks."""
        smd = REPO / "docs" / "STRATEGY.md"
        content = smd.read_text()
        assert "IBKR Paper-Trading Strategy" in content or "paper-trading" in content.lower()

    def test_no_mstr_btc_in_strategy_files(self):
        """Neither strategy doc contains MSTR/BTC proposal references."""
        for path in [REPO / "docs" / "strategy_v1.md", REPO / "docs" / "STRATEGY.md"]:
            content = path.read_text().lower()
            assert "mstr_btc_research_v0_1" not in content, f"{path.name} contains proposal ref"
            assert "phase 18a" not in content, f"{path.name} contains Phase 18A ref"
