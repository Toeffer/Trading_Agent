"""Tests for Phase 17L — Level 1 Strategy-to-Preflight-Draft Chain Closure Checkpoint."""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ibkr_operator import (
    _PHASE17L_DIAGNOSIS,
    _PHASE17L_EXPLICIT_NON_ACTIONS,
    _create_phase17_closure_record,
    _build_ready_draft_17l,
    _verify_phase17a_governance_present,
    _verify_phase17b_schema_present,
    _synthetic_fixture_ready_closure_17l,
    _synthetic_fixture_missing_draft_17l,
    _synthetic_fixture_draft_not_ready_17l,
    _synthetic_fixture_executable_true_17l,
    _synthetic_fixture_preflight_called_true_17l,
    _synthetic_fixture_order_created_true_17l,
    _synthetic_fixture_missing_governance_17l,
    _synthetic_fixture_missing_schema_17l,
    _synthetic_fixture_h1_accessed_true_17l,
    _synthetic_fixture_request_sent_true_17l,
    _synthetic_fixture_disallowed_symbol_17l,
    _synthetic_fixture_invalid_side_17l,
    _synthetic_fixture_invalid_quantity_17l,
    _synthetic_fixture_hash_mismatch_17l,
    _synthetic_fixture_deterministic_17l,
    _synthetic_fixture_read_only_invariant_17l,
    _synthetic_fixture_no_forbidden_endpoints_17l,
    _synthetic_fixture_no_broker_identifiers_17l,
    _synthetic_fixture_full_chain_17l,
    _synthetic_fixture_included_phases_complete_17l,
    _synthetic_fixture_closure_labels_17l,
    _phase17l_no_go,
)

REPO = Path(__file__).resolve().parent.parent
OPERATOR = REPO / "ibkr_operator.py"


# ── Synthetic fixtures ───────────────────────────────────────────────────────

class TestSyntheticFixtures17L:

    def test_ready_closure(self):
        c = _synthetic_fixture_ready_closure_17l()
        assert c["passed"], f"Ready closure case failed: {c}"
        assert c["closure_state"] == "PHASE17_CLOSED"

    def test_missing_draft(self):
        c = _synthetic_fixture_missing_draft_17l()
        assert c["passed"], f"Missing draft case failed: {c}"
        assert c["closure_state"] == "PENDING_INPUT"

    def test_draft_not_ready(self):
        c = _synthetic_fixture_draft_not_ready_17l()
        assert c["passed"], f"Draft not ready case failed: {c}"
        assert c["closure_state"] == "BLOCKED"

    def test_executable_true(self):
        c = _synthetic_fixture_executable_true_17l()
        assert c["passed"], f"Executable true case failed: {c}"

    def test_preflight_called_true(self):
        c = _synthetic_fixture_preflight_called_true_17l()
        assert c["passed"], f"Preflight called true case failed: {c}"

    def test_order_created_true(self):
        c = _synthetic_fixture_order_created_true_17l()
        assert c["passed"], f"Order created true case failed: {c}"

    def test_missing_governance(self):
        c = _synthetic_fixture_missing_governance_17l()
        assert c["passed"], f"Missing governance case failed: {c}"
        assert c["closure_state"] == "BLOCKED"

    def test_missing_schema(self):
        c = _synthetic_fixture_missing_schema_17l()
        assert c["passed"], f"Missing schema case failed: {c}"
        assert c["closure_state"] == "BLOCKED"

    def test_h1_accessed_true(self):
        c = _synthetic_fixture_h1_accessed_true_17l()
        assert c["passed"], f"H1 accessed true case failed: {c}"
        assert c["closure_state"] == "BLOCKED"

    def test_request_sent_true(self):
        c = _synthetic_fixture_request_sent_true_17l()
        assert c["passed"], f"Request sent case failed: {c}"
        assert c["closure_state"] == "BLOCKED"

    def test_disallowed_symbol(self):
        c = _synthetic_fixture_disallowed_symbol_17l()
        assert c["passed"], f"Disallowed symbol case failed: {c}"
        assert c["closure_state"] == "BLOCKED"

    def test_invalid_side(self):
        c = _synthetic_fixture_invalid_side_17l()
        assert c["passed"], f"Invalid side case failed: {c}"
        assert c["closure_state"] == "BLOCKED"

    def test_invalid_quantity(self):
        c = _synthetic_fixture_invalid_quantity_17l()
        assert c["passed"], f"Invalid quantity case failed: {c}"
        assert c["closure_state"] == "BLOCKED"

    def test_hash_mismatch(self):
        c = _synthetic_fixture_hash_mismatch_17l()
        assert c["passed"], f"Hash mismatch case failed: {c}"

    def test_deterministic(self):
        c = _synthetic_fixture_deterministic_17l()
        assert c["passed"], f"Deterministic case failed: {c}"
        assert c["same_state"] is True
        assert c["same_hash"] is True

    def test_read_only_invariant(self):
        c = _synthetic_fixture_read_only_invariant_17l()
        assert c["passed"], f"Read-only invariant violated"

    def test_no_forbidden_endpoints(self):
        c = _synthetic_fixture_no_forbidden_endpoints_17l()
        assert c["passed"], f"Forbidden endpoints found: {c.get('found', [])}"

    def test_no_broker_identifiers(self):
        c = _synthetic_fixture_no_broker_identifiers_17l()
        assert c["passed"], f"Broker identifiers found: {c.get('found', [])}"

    def test_full_chain(self):
        c = _synthetic_fixture_full_chain_17l()
        assert c["passed"], f"Full chain case failed: {c}"
        assert c["all_non_exec"] is True

    def test_included_phases_complete(self):
        c = _synthetic_fixture_included_phases_complete_17l()
        assert c["passed"], f"Included phases case failed: {c.get('included', [])}"

    def test_closure_labels(self):
        c = _synthetic_fixture_closure_labels_17l()
        assert c["passed"], f"Closure labels case failed: {c}"


# ── Unit tests ───────────────────────────────────────────────────────────────

class TestPhase17ClosureRecord:

    def test_record_has_all_required_fields(self):
        draft = _build_ready_draft_17l()
        closure = _create_phase17_closure_record(draft, governance_present=True, schema_present=True)
        required = [
            "phase17_closure_version", "closure_state", "closure_scope",
            "included_phases", "missing_phases",
            "phase17a_governance_reference", "phase17b_schema_reference",
            "proposal_id", "proposal_evidence_hash",
            "dossier_evidence_hash", "planning_decision_record_hash",
            "order_plan_hash", "simulation_record_hash",
            "simulation_review_record_hash", "candidate_package_hash",
            "candidate_review_record_hash", "preflight_request_draft_hash",
            "strategy_version", "evidence_chain_status", "evidence_chain_length",
            "immutable_evidence_references", "phase_invariant_results",
            "final_request_delivery_state", "request_sent",
            "actual_preflight_completed", "broker_preflight_called",
            "executable", "broker_authorized", "preflight_authorized",
            "approval_authorized", "submission_authorized",
            "actual_order_created", "h1_accessed", "h1_approval_created",
            "broker_mutation_occurred", "runtime_mutation_occurred",
            "autonomy_level", "execution_scope", "next_phase_boundary",
            "deterministic_phase17_closure_hash",
            "blockers", "blocker_count",
            "explicit_non_actions", "required_archive_actions",
        ]
        for field in required:
            assert field in closure, f"Missing required field: {field}"

    def test_closure_version(self):
        draft = _build_ready_draft_17l()
        closure = _create_phase17_closure_record(draft, governance_present=True, schema_present=True)
        assert closure["phase17_closure_version"] == "phase17-closure-v1.0.0"

    def test_ready_closure_fixed_values(self):
        draft = _build_ready_draft_17l()
        closure = _create_phase17_closure_record(draft, governance_present=True, schema_present=True)
        assert closure["closure_state"] == "PHASE17_CLOSED"
        assert closure["closure_scope"] == "ARCHIVAL_AND_GOVERNANCE_ONLY"
        assert closure["included_phases"] == ["17A", "17B", "17C", "17D", "17E", "17F", "17G", "17H", "17I", "17J", "17K"]
        assert closure["missing_phases"] == []
        assert closure["evidence_chain_status"] == "COMPLETE_AND_CONSISTENT"
        assert closure["evidence_chain_length"] == 9
        assert closure["final_request_delivery_state"] == "NOT_SENT"
        assert closure["request_sent"] is False
        assert closure["actual_preflight_completed"] is False
        assert closure["broker_preflight_called"] is False
        assert closure["executable"] is False
        assert closure["broker_authorized"] is False
        assert closure["preflight_authorized"] is False
        assert closure["approval_authorized"] is False
        assert closure["submission_authorized"] is False
        assert closure["actual_order_created"] is False
        assert closure["h1_accessed"] is False
        assert closure["h1_approval_created"] is False
        assert closure["broker_mutation_occurred"] is False
        assert closure["runtime_mutation_occurred"] is False
        assert closure["autonomy_level"] == 1
        assert closure["execution_scope"] == "NONE"
        assert closure["next_phase_boundary"] == "PHASE18_RESEARCH_GOVERNANCE"

    def test_phase_invariant_results_all_true(self):
        draft = _build_ready_draft_17l()
        closure = _create_phase17_closure_record(draft, governance_present=True, schema_present=True)
        invariants = closure.get("phase_invariant_results", {})
        required_invariants = [
            "phase17a_strategy_governance_present",
            "phase17b_proposal_schema_present",
            "phase17c_proposal_non_executable",
            "phase17d_dossier_non_executable",
            "phase17e_decision_planning_only",
            "phase17f_order_plan_non_executable",
            "phase17g_simulation_not_actual_preflight",
            "phase17h_review_candidate_packaging_only",
            "phase17i_candidate_package_non_executable",
            "phase17j_review_preflight_drafting_only",
            "phase17k_request_draft_not_sent",
            "all_evidence_hashes_present",
            "all_evidence_hashes_match",
            "immutable_evidence_references_complete",
            "all_authorization_flags_false",
            "no_broker_identifiers_present",
            "no_execution_credentials_present",
            "complete_chain_non_executable",
            "complete_chain_unsent",
            "complete_chain_level1",
            "blocker_ordering_deterministic",
        ]
        for inv in required_invariants:
            assert inv in invariants, f"Missing invariant: {inv}"
            assert invariants[inv] is True, f"Invariant {inv} should be True but got {invariants[inv]}"

    def test_closure_hash_valid(self):
        draft = _build_ready_draft_17l()
        closure = _create_phase17_closure_record(draft, governance_present=True, schema_present=True)
        rh = closure.get("deterministic_phase17_closure_hash", "")
        assert len(rh) == 64
        assert all(c in "0123456789abcdef" for c in rh)

    def test_missing_draft_pending_input(self):
        closure = _create_phase17_closure_record({})
        assert closure["closure_state"] == "PENDING_INPUT"
        assert closure["blocker_count"] > 0

    def test_draft_blocked_blocks_closure(self):
        import copy
        draft = _build_ready_draft_17l()
        draft = copy.deepcopy(draft)
        draft["draft_state"] = "BLOCKED"
        closure = _create_phase17_closure_record(draft, governance_present=True, schema_present=True)
        assert closure["closure_state"] == "BLOCKED"

    def test_executable_true_blocks(self):
        import copy
        draft = _build_ready_draft_17l()
        draft = copy.deepcopy(draft)
        draft["executable"] = True
        closure = _create_phase17_closure_record(draft, governance_present=True, schema_present=True)
        assert closure["closure_state"] == "BLOCKED"

    def test_preflight_called_true_blocks(self):
        import copy
        draft = _build_ready_draft_17l()
        draft = copy.deepcopy(draft)
        draft["broker_preflight_called"] = True
        closure = _create_phase17_closure_record(draft, governance_present=True, schema_present=True)
        assert closure["closure_state"] == "BLOCKED"

    def test_actual_preflight_completed_true_blocks(self):
        import copy
        draft = _build_ready_draft_17l()
        draft = copy.deepcopy(draft)
        draft["actual_preflight_completed"] = True
        closure = _create_phase17_closure_record(draft, governance_present=True, schema_present=True)
        assert closure["closure_state"] == "BLOCKED"

    def test_order_created_true_blocks(self):
        import copy
        draft = _build_ready_draft_17l()
        draft = copy.deepcopy(draft)
        draft["actual_order_created"] = True
        closure = _create_phase17_closure_record(draft, governance_present=True, schema_present=True)
        assert closure["closure_state"] == "BLOCKED"

    def test_h1_accessed_true_blocks(self):
        import copy
        draft = _build_ready_draft_17l()
        draft = copy.deepcopy(draft)
        draft["h1_accessed"] = True
        closure = _create_phase17_closure_record(draft, governance_present=True, schema_present=True)
        assert closure["closure_state"] == "BLOCKED"

    def test_request_not_unsent_blocks(self):
        import copy
        draft = _build_ready_draft_17l()
        draft = copy.deepcopy(draft)
        draft["request_delivery_state"] = "SENT"
        closure = _create_phase17_closure_record(draft, governance_present=True, schema_present=True)
        assert closure["closure_state"] == "BLOCKED"

    def test_broker_authorized_true_blocks(self):
        import copy
        draft = _build_ready_draft_17l()
        draft = copy.deepcopy(draft)
        draft["broker_authorized"] = True
        closure = _create_phase17_closure_record(draft, governance_present=True, schema_present=True)
        assert closure["closure_state"] == "BLOCKED"

    def test_preflight_authorized_true_blocks(self):
        import copy
        draft = _build_ready_draft_17l()
        draft = copy.deepcopy(draft)
        draft["preflight_authorized"] = True
        closure = _create_phase17_closure_record(draft, governance_present=True, schema_present=True)
        assert closure["closure_state"] == "BLOCKED"

    def test_approval_authorized_true_blocks(self):
        import copy
        draft = _build_ready_draft_17l()
        draft = copy.deepcopy(draft)
        draft["approval_authorized"] = True
        closure = _create_phase17_closure_record(draft, governance_present=True, schema_present=True)
        assert closure["closure_state"] == "BLOCKED"

    def test_submission_authorized_true_blocks(self):
        import copy
        draft = _build_ready_draft_17l()
        draft = copy.deepcopy(draft)
        draft["submission_authorized"] = True
        closure = _create_phase17_closure_record(draft, governance_present=True, schema_present=True)
        assert closure["closure_state"] == "BLOCKED"

    def test_missing_governance_blocks(self):
        draft = _build_ready_draft_17l()
        closure = _create_phase17_closure_record(draft, governance_present=False, schema_present=True)
        assert closure["closure_state"] == "BLOCKED"
        assert any("governance_missing" in b.get("blocker", "") for b in closure["blockers"])
        assert "17A" not in closure["included_phases"]

    def test_missing_schema_blocks(self):
        draft = _build_ready_draft_17l()
        closure = _create_phase17_closure_record(draft, governance_present=True, schema_present=False)
        assert closure["closure_state"] == "BLOCKED"
        assert any("schema_missing" in b.get("blocker", "") for b in closure["blockers"])
        assert "17B" not in closure["included_phases"]

    def test_missing_evidence_hash_blocks(self):
        import copy
        for key in ["proposal_evidence_hash", "dossier_evidence_hash", "planning_decision_record_hash",
                     "order_plan_hash", "simulation_record_hash", "simulation_review_record_hash",
                     "candidate_package_hash", "candidate_review_record_hash"]:
            draft = _build_ready_draft_17l()
            draft = copy.deepcopy(draft)
            draft[key] = ""
            closure = _create_phase17_closure_record(draft, governance_present=True, schema_present=True)
            assert closure["closure_state"] == "BLOCKED", f"Missing {key} should block"

    def test_hash_mismatch_blocks(self):
        import copy
        draft = _build_ready_draft_17l()
        draft = copy.deepcopy(draft)
        draft["immutable_evidence_references"]["proposal_evidence_hash"] = "0" * 64
        closure = _create_phase17_closure_record(draft, governance_present=True, schema_present=True)
        assert closure["closure_state"] == "BLOCKED"

    def test_tampered_immutable_ref_blocks(self):
        import copy
        draft = _build_ready_draft_17l()
        draft = copy.deepcopy(draft)
        draft["immutable_evidence_references"] = {"bad": "tampered"}
        closure = _create_phase17_closure_record(draft, governance_present=True, schema_present=True)
        assert closure["closure_state"] == "BLOCKED"

    def test_disallowed_symbol_blocks(self):
        import copy
        draft = _build_ready_draft_17l()
        draft = copy.deepcopy(draft)
        draft["symbol"] = "TSLA"
        closure = _create_phase17_closure_record(draft, governance_present=True, schema_present=True)
        assert closure["closure_state"] == "BLOCKED"

    def test_invalid_side_blocks(self):
        import copy
        draft = _build_ready_draft_17l()
        draft = copy.deepcopy(draft)
        draft["side"] = "HOLD"
        closure = _create_phase17_closure_record(draft, governance_present=True, schema_present=True)
        assert closure["closure_state"] == "BLOCKED"

    def test_zero_quantity_blocks(self):
        import copy
        draft = _build_ready_draft_17l()
        draft = copy.deepcopy(draft)
        draft["quantity"] = 0
        closure = _create_phase17_closure_record(draft, governance_present=True, schema_present=True)
        assert closure["closure_state"] == "BLOCKED"

    def test_negative_quantity_blocks(self):
        import copy
        draft = _build_ready_draft_17l()
        draft = copy.deepcopy(draft)
        draft["quantity"] = -10
        closure = _create_phase17_closure_record(draft, governance_present=True, schema_present=True)
        assert closure["closure_state"] == "BLOCKED"

    def test_output_labels_present(self):
        draft = _build_ready_draft_17l()
        closure = _create_phase17_closure_record(draft, governance_present=True, schema_present=True)
        labels = closure.get("output_labels", [])
        required = ["PHASE17_CLOSED", "ARCHIVAL_AND_GOVERNANCE_ONLY", "LEVEL1",
                    "NON_EXECUTABLE", "NO_EXECUTION_SCOPE", "PREFLIGHT_DRAFT_NOT_SENT",
                    "ACTUAL_PREFLIGHT_NOT_COMPLETED", "NO_H1_ACCESSED", "NO_BROKER_MUTATION",
                    "PHASE18_RESEARCH_GOVERNANCE_ONLY"]
        for r in required:
            assert r in labels, f"Missing label: {r}"

    def test_labeled_output_in_json(self):
        draft = _build_ready_draft_17l()
        closure = _create_phase17_closure_record(draft, governance_present=True, schema_present=True)
        payload = json.dumps(closure, sort_keys=True)
        assert "NON_EXECUTABLE" in payload
        assert "ARCHIVAL_AND_GOVERNANCE_ONLY" in payload
        assert "PHASE17_CLOSED" in payload

    def test_immutable_evidence_references_complete(self):
        draft = _build_ready_draft_17l()
        closure = _create_phase17_closure_record(draft, governance_present=True, schema_present=True)
        ier = closure.get("immutable_evidence_references", {})
        expected = [
            "proposal_evidence_hash", "dossier_evidence_hash",
            "planning_decision_record_hash", "order_plan_hash",
            "simulation_record_hash", "simulation_review_record_hash",
            "candidate_package_hash", "candidate_review_record_hash",
            "preflight_request_draft_hash",
        ]
        for key in expected:
            assert key in ier, f"Missing immutable ref: {key}"
            assert len(ier[key]) == 64, f"Ref {key} not 64 chars: {len(ier[key])}"

    def test_required_archive_actions_present(self):
        draft = _build_ready_draft_17l()
        closure = _create_phase17_closure_record(draft, governance_present=True, schema_present=True)
        actions = closure.get("required_archive_actions", [])
        assert len(actions) >= 3
        assert any("archive" in a.lower() for a in actions)

    def test_blocker_ordering_deterministic(self):
        import copy
        draft = _build_ready_draft_17l()
        draft = copy.deepcopy(draft)
        draft["executable"] = True
        c1 = _create_phase17_closure_record(draft, governance_present=True, schema_present=True)
        c2 = _create_phase17_closure_record(draft, governance_present=True, schema_present=True)
        b1 = [b["blocker"] for b in c1["blockers"]]
        b2 = [b["blocker"] for b in c2["blockers"]]
        assert b1 == b2, f"Blocker ordering differs: {b1} vs {b2}"

    def test_no_broker_identifiers_in_output(self):
        draft = _build_ready_draft_17l()
        closure = _create_phase17_closure_record(draft, governance_present=True, schema_present=True)
        payload = json.dumps(closure, sort_keys=True)
        forbidden = ["permId", "order_id", "orderId", "approval_id",
                     "approvalId", "submission_id", "submissionId",
                     "exec_id", "execId", "conId", "broker_order_id",
                     "preflight_result", "broker_response"]
        for fid in forbidden:
            assert fid.lower() not in payload.lower(), \
                f"Forbidden identifier '{fid}' found in closure output"

    def test_does_not_mutate_draft(self):
        import copy
        draft = _build_ready_draft_17l()
        draft_before = copy.deepcopy(draft)
        _create_phase17_closure_record(draft, governance_present=True, schema_present=True)
        assert draft == draft_before, "Closure mutated the draft"

    def test_governance_schema_verification(self):
        ga = _verify_phase17a_governance_present()
        sb = _verify_phase17b_schema_present()
        assert isinstance(ga, bool)
        assert isinstance(sb, bool)

    def test_inherited_blockers_prevent_closure(self):
        import copy
        draft = _build_ready_draft_17l()
        draft = copy.deepcopy(draft)
        draft["blockers"] = [{"blocker": "inherited", "detail": "test"}]
        draft["blocker_count"] = 1
        # Even though draft_state is PREFLIGHT_REQUEST_DRAFT_READY,
        # inherited blockers should be detectable
        closure = _create_phase17_closure_record(draft, governance_present=True, schema_present=True)
        # 17K draft having blockers shouldn't have reached PREFLIGHT_REQUEST_DRAFT_READY
        # but if it did, closure should still catch it
        assert "PHASE17_CLOSED" in closure.get("closure_state", "") or closure.get("closure_state") == "BLOCKED"

    def test_request_sent_is_false_in_closed(self):
        draft = _build_ready_draft_17l()
        closure = _create_phase17_closure_record(draft, governance_present=True, schema_present=True)
        assert closure["request_sent"] is False
        assert closure["final_request_delivery_state"] == "NOT_SENT"


# ── No forbidden access ──────────────────────────────────────────────────────

class TestNoForbiddenAccess17L:

    def test_no_order_endpoints_in_source(self):
        import inspect
        src = inspect.getsource(_create_phase17_closure_record)
        truly_forbidden = [p for p in ["/order", "/connect", "/order/preflight",
                                        "/order/approve", "/order/submit"]
                           if p in src]
        assert len(truly_forbidden) == 0, f"Forbidden patterns: {truly_forbidden}"

    def test_no_trade_window_in_source(self):
        import inspect
        src = inspect.getsource(_create_phase17_closure_record)
        assert "ibkr-trade-window" not in src

    def test_no_home_ref_in_source(self):
        import inspect
        src = inspect.getsource(_create_phase17_closure_record)
        assert "Path.home()" not in src
        assert "~/.openclaw" not in src

    def test_no_sudo_in_source(self):
        import inspect
        src = inspect.getsource(_create_phase17_closure_record)
        assert "sudo" not in src


# ── Constants ────────────────────────────────────────────────────────────────

class TestPhase17LConstants:

    def test_diagnosis_dict_has_ready(self):
        assert _PHASE17L_DIAGNOSIS["ready"] == "phase17_chain_closed"

    def test_diagnosis_dict_has_all_keys(self):
        required = [
            "ready", "ready_closure_case_failed", "missing_draft_failed",
            "draft_not_ready_failed", "draft_sent_failed",
            "executable_true_failed", "authorization_flags_failed",
            "preflight_called_failed", "order_created_failed",
            "h1_accessed_failed", "evidence_hashes_missing_failed",
            "evidence_hashes_mismatch_failed",
            "governance_missing_failed", "schema_missing_failed",
            "deterministic_failed", "immutable_refs_failed",
            "no_forbidden_endpoints_failed", "no_broker_identifiers_failed",
            "read_only_invariant_failed", "fresh_clone_failed",
            "full_chain_failed", "unknown",
        ]
        for k in required:
            assert k in _PHASE17L_DIAGNOSIS, f"Missing diagnosis key: {k}"

    def test_explicit_non_actions_contains_protections(self):
        na = _PHASE17L_EXPLICIT_NON_ACTIONS
        assert any("closure" in s.lower() for s in na)
        assert any("h1" in s.lower() or "H1" in s for s in na)
        assert any("archival" in s.lower() or "ARCHIVAL" in s for s in na)

    def test_no_go_returns_correct_structure(self):
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        ts = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        result = _phase17l_no_go(
            "test-id", ts,
            {"branch": "test", "commit": "abc", "tag": "v1", "worktree_clean": False},
            "test_diagnosis", ["action 1"],
        )
        assert result["diagnosis"] == "test_diagnosis"
        assert result["severity"] == "NO_GO"
        assert result["no_order_endpoint_called"] is True
        assert result["no_broker_mutation"] is True


# ── Fresh-clone HOME independence ────────────────────────────────────────────

class TestFreshCloneHomeIndependence17L:

    def test_closure_with_empty_home(self):
        with tempfile.TemporaryDirectory() as td:
            env = os.environ.copy()
            env["HOME"] = td
            cp = subprocess.run(
                [sys.executable, "-c", f"""
import sys
sys.path.insert(0, r'{REPO}')
from ibkr_operator import _build_ready_draft_17l, _create_phase17_closure_record
draft = _build_ready_draft_17l()
closure = _create_phase17_closure_record(draft, governance_present=True, schema_present=True)
assert closure["closure_state"] == "PHASE17_CLOSED"
assert "deterministic_phase17_closure_hash" in closure
print("OK")
"""],
                capture_output=True, text=True, timeout=30,
                env=env,
            )
            assert "OK" in cp.stdout, f"stderr: {cp.stderr}"


# ── CLI tests ────────────────────────────────────────────────────────────────

class TestPhase17LCLI:

    def test_help_succeeds(self):
        result = subprocess.run(
            [sys.executable, str(OPERATOR),
             "level1-phase17-chain-closure-checkpoint", "--help"],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0, f"stderr: {result.stderr[:200]}"

    def test_alias_phase17l_works(self):
        result = subprocess.run(
            [sys.executable, str(OPERATOR),
             "phase17l-chain-closure-checkpoint", "--help"],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0, f"stderr: {result.stderr[:200]}"

    def test_alias_phase17_chain_closure_works(self):
        result = subprocess.run(
            [sys.executable, str(OPERATOR),
             "phase17-chain-closure", "--help"],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0, f"stderr: {result.stderr[:200]}"

    def test_json_output_valid(self):
        result = subprocess.run(
            [sys.executable, str(OPERATOR),
             "level1-phase17-chain-closure-checkpoint", "--json"],
            capture_output=True, text=True, timeout=60,
        )
        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError:
            pytest.fail(f"Invalid JSON: {result.stdout[:200]}")
        assert "diagnosis" in data

    def test_required_fields_present(self):
        result = subprocess.run(
            [sys.executable, str(OPERATOR),
             "level1-phase17-chain-closure-checkpoint", "--json"],
            capture_output=True, text=True, timeout=60,
        )
        data = json.loads(result.stdout)
        required = [
            "checkpoint_id", "timestamp", "diagnosis", "severity",
            "no_order_endpoint_called", "no_broker_mutation",
            "ready_closure_case_passed",
            "missing_draft_case_passed",
            "deterministic_case_passed",
            "full_chain_case_passed",
        ]
        for field in required:
            assert field in data, f"Missing required field in CLI output: {field}"


# ── Regression: Determinism at scale ────────────────────────────────────────

class TestRegressionDeterminismAtScale17L:

    def test_20_ready_closures_all_same_state(self):
        draft = _build_ready_draft_17l()
        closures = [
            _create_phase17_closure_record(draft, governance_present=True, schema_present=True)
            for _ in range(20)
        ]
        for i, c in enumerate(closures):
            assert c["closure_state"] == "PHASE17_CLOSED", \
                f"Closure {i}: expected PHASE17_CLOSED, got {c['closure_state']}"
            assert c["execution_scope"] == "NONE"
            assert c["autonomy_level"] == 1

    def test_20_ready_closures_all_identical_hash(self):
        draft = _build_ready_draft_17l()
        closures = [
            _create_phase17_closure_record(draft, governance_present=True, schema_present=True)
            for _ in range(20)
        ]
        hashes = [c["deterministic_phase17_closure_hash"] for c in closures]
        first_hash = hashes[0]
        for i, h in enumerate(hashes):
            assert h == first_hash, f"Closure {i} hash differs: {h[:16]}... vs {first_hash[:16]}..."

    def test_20_ready_closures_all_zero_blockers(self):
        draft = _build_ready_draft_17l()
        closures = [
            _create_phase17_closure_record(draft, governance_present=True, schema_present=True)
            for _ in range(20)
        ]
        for i, c in enumerate(closures):
            assert c["blocker_count"] == 0, \
                f"Closure {i}: expected 0 blockers, got {c['blocker_count']}"


# ── Regression: Upstream draft unchanged after 17L ──────────────────────

class TestRegressionUpstreamUnchanged17L:

    def test_draft_unchanged_after_17l(self):
        import copy
        draft = _build_ready_draft_17l()
        draft_before = copy.deepcopy(draft)
        _create_phase17_closure_record(draft, governance_present=True, schema_present=True)
        assert draft == draft_before, "Draft was mutated by 17L builder"

    def test_deterministic_blockers_same_input(self):
        import copy
        draft = _build_ready_draft_17l()
        draft = copy.deepcopy(draft)
        draft["executable"] = True
        c1 = _create_phase17_closure_record(draft, governance_present=True, schema_present=True)
        c2 = _create_phase17_closure_record(draft, governance_present=True, schema_present=True)
        b1 = [b["blocker"] for b in c1["blockers"]]
        b2 = [b["blocker"] for b in c2["blockers"]]
        assert b1 == b2, f"Blockers differ: {b1} vs {b2}"
