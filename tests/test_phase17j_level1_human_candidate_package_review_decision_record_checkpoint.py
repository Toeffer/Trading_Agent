"""Tests for Phase 17J — Level 1 Human Candidate Package Review Decision Record."""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ibkr_operator import (
    _PHASE17J_DIAGNOSIS,
    _PHASE17J_EXPLICIT_NON_ACTIONS,
    _create_candidate_package_review_decision_record,
    _build_ready_package_17j,
    _synthetic_fixture_ready_accept_17j,
    _synthetic_fixture_missing_decision_17j,
    _synthetic_fixture_rejected_decision_17j,
    _synthetic_fixture_deferred_decision_17j,
    _synthetic_fixture_invalid_decision_17j,
    _synthetic_fixture_missing_reviewer_accept_17j,
    _synthetic_fixture_missing_reviewer_reject_17j,
    _synthetic_fixture_reject_missing_reason_17j,
    _synthetic_fixture_defer_missing_reason_17j,
    _synthetic_fixture_package_not_ready_17j,
    _synthetic_fixture_package_blocked_17j,
    _synthetic_fixture_scope_not_planning_only_17j,
    _synthetic_fixture_executable_true_17j,
    _synthetic_fixture_broker_authorized_true_17j,
    _synthetic_fixture_preflight_authorized_true_17j,
    _synthetic_fixture_approval_authorized_true_17j,
    _synthetic_fixture_submission_authorized_true_17j,
    _synthetic_fixture_broker_preflight_called_true_17j,
    _synthetic_fixture_actual_preflight_completed_true_17j,
    _synthetic_fixture_actual_order_created_true_17j,
    _synthetic_fixture_package_has_blockers_17j,
    _synthetic_fixture_disallowed_symbol_17j,
    _synthetic_fixture_invalid_side_17j,
    _synthetic_fixture_invalid_quantity_17j,
    _synthetic_fixture_negative_quantity_17j,
    _synthetic_fixture_stop_above_entry_17j,
    _synthetic_fixture_stop_quantity_mismatch_17j,
    _synthetic_fixture_data_quality_fail_17j,
    _synthetic_fixture_no_trade_fail_17j,
    _synthetic_fixture_risk_fail_17j,
    _synthetic_fixture_sizing_fail_17j,
    _synthetic_fixture_evidence_chain_fail_17j,
    _synthetic_fixture_simulated_gate_fail_17j,
    _synthetic_fixture_hash_mismatch_17j,
    _synthetic_fixture_tampered_evidence_ref_17j,
    _synthetic_fixture_deterministic_17j,
    _synthetic_fixture_no_forbidden_endpoints_17j,
    _synthetic_fixture_no_broker_identifiers_17j,
    _synthetic_fixture_read_only_invariant_17j,
    _synthetic_fixture_fresh_clone_17j,
    _synthetic_fixture_full_chain_17j,
    _phase17j_no_go,
    _generate_synthetic_ohlc_bars,
    _generate_proposal_packet,
    _review_proposal_dossier,
    _create_decision_record,
    _create_order_plan_draft,
    _create_simulated_preflight_dossier,
    _create_simulation_review_decision_record,
    _create_candidate_package,
)

REPO = Path(__file__).resolve().parent.parent
OPERATOR = REPO / "ibkr_operator.py"


# ── Synthetic fixtures ───────────────────────────────────────────────────────

class TestSyntheticFixtures17J:

    def test_ready_accept(self):
        c = _synthetic_fixture_ready_accept_17j()
        assert c["passed"], f"Ready accept case failed: {c}"
        assert c["review_state"] == "ACCEPTED_FOR_PREFLIGHT_REQUEST_DRAFTING"
        assert c["preflight_drafting_permitted"] is True

    def test_missing_decision(self):
        c = _synthetic_fixture_missing_decision_17j()
        assert c["passed"], f"Missing decision case failed: {c}"
        assert c["review_state"] == "PENDING_REVIEW"

    def test_rejected_decision(self):
        c = _synthetic_fixture_rejected_decision_17j()
        assert c["passed"], f"Rejected case failed: {c}"
        assert c["review_state"] == "REJECTED"

    def test_deferred_decision(self):
        c = _synthetic_fixture_deferred_decision_17j()
        assert c["passed"], f"Deferred case failed: {c}"
        assert c["review_state"] == "DEFERRED"

    def test_invalid_decision(self):
        c = _synthetic_fixture_invalid_decision_17j()
        assert c["passed"], f"Invalid decision case failed: {c}"

    def test_missing_reviewer_accept(self):
        c = _synthetic_fixture_missing_reviewer_accept_17j()
        assert c["passed"], f"Missing reviewer accept case failed: {c}"

    def test_missing_reviewer_reject(self):
        c = _synthetic_fixture_missing_reviewer_reject_17j()
        assert c["passed"], f"Missing reviewer reject case failed: {c}"

    def test_reject_missing_reason(self):
        c = _synthetic_fixture_reject_missing_reason_17j()
        assert c["passed"], f"Reject missing reason case failed: {c}"

    def test_defer_missing_reason(self):
        c = _synthetic_fixture_defer_missing_reason_17j()
        assert c["passed"], f"Defer missing reason case failed: {c}"

    def test_package_not_ready(self):
        c = _synthetic_fixture_package_not_ready_17j()
        assert c["passed"], f"Package not ready case failed: {c}"

    def test_package_blocked(self):
        c = _synthetic_fixture_package_blocked_17j()
        assert c["passed"], f"Package blocked case failed: {c}"

    def test_scope_not_planning_only(self):
        c = _synthetic_fixture_scope_not_planning_only_17j()
        assert c["passed"], f"Scope case failed: {c}"

    def test_executable_true(self):
        c = _synthetic_fixture_executable_true_17j()
        assert c["passed"], f"Executable true case failed: {c}"

    def test_broker_authorized_true(self):
        c = _synthetic_fixture_broker_authorized_true_17j()
        assert c["passed"], f"Broker authorized case failed: {c}"

    def test_preflight_authorized_true(self):
        c = _synthetic_fixture_preflight_authorized_true_17j()
        assert c["passed"], f"Preflight authorized case failed: {c}"

    def test_approval_authorized_true(self):
        c = _synthetic_fixture_approval_authorized_true_17j()
        assert c["passed"], f"Approval authorized case failed: {c}"

    def test_submission_authorized_true(self):
        c = _synthetic_fixture_submission_authorized_true_17j()
        assert c["passed"], f"Submission authorized case failed: {c}"

    def test_broker_preflight_called_true(self):
        c = _synthetic_fixture_broker_preflight_called_true_17j()
        assert c["passed"], f"Broker preflight called case failed: {c}"

    def test_actual_preflight_completed_true(self):
        c = _synthetic_fixture_actual_preflight_completed_true_17j()
        assert c["passed"], f"Actual preflight completed case failed: {c}"

    def test_actual_order_created_true(self):
        c = _synthetic_fixture_actual_order_created_true_17j()
        assert c["passed"], f"Actual order created case failed: {c}"

    def test_package_has_blockers(self):
        c = _synthetic_fixture_package_has_blockers_17j()
        assert c["passed"], f"Package blockers case failed: {c}"

    def test_disallowed_symbol(self):
        c = _synthetic_fixture_disallowed_symbol_17j()
        assert c["passed"], f"Disallowed symbol case failed: {c}"

    def test_invalid_side(self):
        c = _synthetic_fixture_invalid_side_17j()
        assert c["passed"], f"Invalid side case failed: {c}"

    def test_invalid_quantity(self):
        c = _synthetic_fixture_invalid_quantity_17j()
        assert c["passed"], f"Invalid quantity case failed: {c}"

    def test_negative_quantity(self):
        c = _synthetic_fixture_negative_quantity_17j()
        assert c["passed"], f"Negative quantity case failed: {c}"

    def test_stop_above_entry(self):
        c = _synthetic_fixture_stop_above_entry_17j()
        assert c["passed"], f"Stop above entry case failed: {c}"

    def test_stop_quantity_mismatch(self):
        c = _synthetic_fixture_stop_quantity_mismatch_17j()
        assert c["passed"], f"Stop-qty mismatch case failed: {c}"

    def test_data_quality_fail(self):
        c = _synthetic_fixture_data_quality_fail_17j()
        assert c["passed"], f"Data-quality fail case failed: {c}"

    def test_no_trade_fail(self):
        c = _synthetic_fixture_no_trade_fail_17j()
        assert c["passed"], f"No-trade fail case failed: {c}"

    def test_risk_fail(self):
        c = _synthetic_fixture_risk_fail_17j()
        assert c["passed"], f"Risk fail case failed: {c}"

    def test_sizing_fail(self):
        c = _synthetic_fixture_sizing_fail_17j()
        assert c["passed"], f"Sizing fail case failed: {c}"

    def test_evidence_chain_fail(self):
        c = _synthetic_fixture_evidence_chain_fail_17j()
        assert c["passed"], f"Evidence-chain fail case failed: {c}"

    def test_simulated_gate_fail(self):
        c = _synthetic_fixture_simulated_gate_fail_17j()
        assert c["passed"], f"Simulated-gate fail case failed: {c}"

    def test_hash_mismatch(self):
        c = _synthetic_fixture_hash_mismatch_17j()
        assert c["passed"], f"Hash mismatch case failed: {c}"

    def test_tampered_evidence_ref(self):
        c = _synthetic_fixture_tampered_evidence_ref_17j()
        assert c["passed"], f"Tampered evidence ref case failed: {c}"

    def test_deterministic(self):
        c = _synthetic_fixture_deterministic_17j()
        assert c["passed"], f"Deterministic case failed: {c}"
        assert c["same_state"] is True
        assert c["same_hash"] is True

    def test_no_forbidden_endpoints(self):
        c = _synthetic_fixture_no_forbidden_endpoints_17j()
        assert c["passed"], f"Forbidden endpoints found: {c.get('found', [])}"

    def test_no_broker_identifiers(self):
        c = _synthetic_fixture_no_broker_identifiers_17j()
        assert c["passed"], f"Broker identifiers found: {c.get('found', [])}"

    def test_read_only_invariant(self):
        c = _synthetic_fixture_read_only_invariant_17j()
        assert c["passed"], f"Read-only invariant violated"

    def test_fresh_clone(self):
        c = _synthetic_fixture_fresh_clone_17j()
        assert c["passed"], f"Fresh clone case failed: {c}"

    def test_full_chain(self):
        c = _synthetic_fixture_full_chain_17j()
        assert c["passed"], f"Full chain case failed: {c}"
        assert c["all_non_exec"] is True


# ── Unit tests ───────────────────────────────────────────────────────────────

class TestCandidatePackageReviewDecisionRecord:

    def test_record_has_all_required_fields(self):
        pkg = _build_ready_package_17j()
        record = _create_candidate_package_review_decision_record(
            pkg, decision="ACCEPT", reviewer="Chris", decision_reason="Test."
        )
        required = [
            "candidate_review_record_version", "review_state", "proposal_id",
            "proposal_evidence_hash", "dossier_evidence_hash",
            "planning_decision_record_hash", "order_plan_hash",
            "simulation_record_hash", "simulation_review_record_hash",
            "candidate_package_hash", "strategy_version", "symbol",
            "side", "quantity", "reviewer_identifier", "decision",
            "decision_reason", "acceptance_scope",
            "preflight_request_drafting_permitted",
            "package_scope", "executable", "broker_authorized",
            "preflight_authorized", "approval_authorized",
            "submission_authorized", "broker_preflight_called",
            "actual_preflight_completed", "actual_order_created",
            "immutable_evidence_references",
            "deterministic_candidate_review_hash",
            "blockers", "blocker_count",
            "explicit_non_actions", "required_future_human_actions",
        ]
        for field in required:
            assert field in record, f"Missing required field: {field}"

    def test_record_version(self):
        pkg = _build_ready_package_17j()
        record = _create_candidate_package_review_decision_record(
            pkg, decision="ACCEPT", reviewer="Chris", decision_reason="Test."
        )
        assert record["candidate_review_record_version"] == "candidate-review-record-v1.0.0"

    def test_accepted_is_non_executable(self):
        pkg = _build_ready_package_17j()
        record = _create_candidate_package_review_decision_record(
            pkg, decision="ACCEPT", reviewer="Chris", decision_reason="Test."
        )
        assert record["executable"] is False
        assert record["broker_authorized"] is False
        assert record["preflight_authorized"] is False
        assert record["approval_authorized"] is False
        assert record["submission_authorized"] is False
        assert record["broker_preflight_called"] is False
        assert record["actual_preflight_completed"] is False
        assert record["actual_order_created"] is False
        assert record["package_scope"] == "PLANNING_ONLY"

    def test_accepted_preflight_drafting_permitted(self):
        pkg = _build_ready_package_17j()
        record = _create_candidate_package_review_decision_record(
            pkg, decision="ACCEPT", reviewer="Chris", decision_reason="Test."
        )
        assert record["review_state"] == "ACCEPTED_FOR_PREFLIGHT_REQUEST_DRAFTING"
        assert record["preflight_request_drafting_permitted"] is True
        assert record["acceptance_scope"] == "PREFLIGHT_REQUEST_DRAFTING_ONLY"

    def test_review_hash_valid(self):
        pkg = _build_ready_package_17j()
        record = _create_candidate_package_review_decision_record(
            pkg, decision="ACCEPT", reviewer="Chris", decision_reason="Test."
        )
        rh = record.get("deterministic_candidate_review_hash", "")
        assert len(rh) == 64
        assert all(c in "0123456789abcdef" for c in rh)

    def test_missing_decision_pending(self):
        pkg = _build_ready_package_17j()
        record = _create_candidate_package_review_decision_record(pkg)
        assert record["review_state"] == "PENDING_REVIEW"
        assert record["decision"] == "PENDING_REVIEW"
        assert record["preflight_request_drafting_permitted"] is False
        assert record["blocker_count"] > 0

    def test_rejected_is_not_permitted(self):
        pkg = _build_ready_package_17j()
        record = _create_candidate_package_review_decision_record(
            pkg, decision="REJECT", reviewer="Chris", decision_reason="Not needed."
        )
        assert record["review_state"] == "REJECTED"
        assert record["preflight_request_drafting_permitted"] is False
        assert record["acceptance_scope"] == "NONE"

    def test_deferred_is_not_permitted(self):
        pkg = _build_ready_package_17j()
        record = _create_candidate_package_review_decision_record(
            pkg, decision="DEFER", reviewer="Chris", decision_reason="Need more data."
        )
        assert record["review_state"] == "DEFERRED"
        assert record["preflight_request_drafting_permitted"] is False

    def test_invalid_decision_blocked(self):
        pkg = _build_ready_package_17j()
        record = _create_candidate_package_review_decision_record(
            pkg, decision="APPROVE", reviewer="Chris", decision_reason="Bad."
        )
        assert record["review_state"] == "BLOCKED"

    def test_missing_reviewer_blocked(self):
        pkg = _build_ready_package_17j()
        record = _create_candidate_package_review_decision_record(
            pkg, decision="ACCEPT", reviewer="", decision_reason="No reviewer."
        )
        assert record["review_state"] == "BLOCKED"

    def test_reject_missing_reason_blocked(self):
        pkg = _build_ready_package_17j()
        record = _create_candidate_package_review_decision_record(
            pkg, decision="REJECT", reviewer="Chris", decision_reason=""
        )
        assert record["review_state"] == "BLOCKED"

    def test_package_not_ready_blocked(self):
        pkg = _build_ready_package_17j()
        pkg["package_state"] = "PENDING_INPUT"
        pkg["candidate_packaging_permitted"] = False
        record = _create_candidate_package_review_decision_record(
            pkg, decision="ACCEPT", reviewer="Chris", decision_reason="Should block."
        )
        assert record["review_state"] == "BLOCKED"

    def test_disallowed_symbol_blocked(self):
        pkg = _build_ready_package_17j()
        pkg["symbol"] = "TSLA"
        record = _create_candidate_package_review_decision_record(
            pkg, decision="ACCEPT", reviewer="Chris", decision_reason="Should block."
        )
        assert record["review_state"] == "BLOCKED"
        assert any("disallowed" in b["blocker"] for b in record["blockers"])

    def test_invalid_side_blocked(self):
        pkg = _build_ready_package_17j()
        pkg["side"] = "HOLD"
        record = _create_candidate_package_review_decision_record(
            pkg, decision="ACCEPT", reviewer="Chris", decision_reason="Should block."
        )
        assert record["review_state"] == "BLOCKED"

    def test_zero_quantity_blocked(self):
        pkg = _build_ready_package_17j()
        pkg["quantity"] = 0
        record = _create_candidate_package_review_decision_record(
            pkg, decision="ACCEPT", reviewer="Chris", decision_reason="Should block."
        )
        assert record["review_state"] == "BLOCKED"

    def test_negative_quantity_blocked(self):
        pkg = _build_ready_package_17j()
        pkg["quantity"] = -10
        record = _create_candidate_package_review_decision_record(
            pkg, decision="ACCEPT", reviewer="Chris", decision_reason="Should block."
        )
        assert record["review_state"] == "BLOCKED"

    def test_stop_above_entry_blocked(self):
        pkg = _build_ready_package_17j()
        pkg["side"] = "BUY"
        pkg["planned_entry"]["entry_price"] = 100.0
        pkg["planned_protective_stop"]["initial_stop_loss"] = 105.0
        record = _create_candidate_package_review_decision_record(
            pkg, decision="ACCEPT", reviewer="Chris", decision_reason="Should block."
        )
        assert record["review_state"] == "BLOCKED"

    def test_stop_quantity_mismatch_blocked(self):
        pkg = _build_ready_package_17j()
        pkg["quantity"] = 100
        pkg["planned_stop_quantity"] = 50
        record = _create_candidate_package_review_decision_record(
            pkg, decision="ACCEPT", reviewer="Chris", decision_reason="Should block."
        )
        assert record["review_state"] == "BLOCKED"

    def test_data_quality_fail_blocked(self):
        pkg = _build_ready_package_17j()
        pkg["data_quality_summary"]["overall_passed"] = False
        record = _create_candidate_package_review_decision_record(
            pkg, decision="ACCEPT", reviewer="Chris", decision_reason="Should block."
        )
        assert record["review_state"] == "BLOCKED"

    def test_no_trade_fail_blocked(self):
        pkg = _build_ready_package_17j()
        pkg["no_trade_summary"]["overall_passed"] = False
        record = _create_candidate_package_review_decision_record(
            pkg, decision="ACCEPT", reviewer="Chris", decision_reason="Should block."
        )
        assert record["review_state"] == "BLOCKED"

    def test_risk_fail_blocked(self):
        pkg = _build_ready_package_17j()
        pkg["risk_summary"]["overall_passed"] = False
        record = _create_candidate_package_review_decision_record(
            pkg, decision="ACCEPT", reviewer="Chris", decision_reason="Should block."
        )
        assert record["review_state"] == "BLOCKED"

    def test_sizing_fail_blocked(self):
        pkg = _build_ready_package_17j()
        pkg["sizing_summary"]["overall_passed"] = False
        record = _create_candidate_package_review_decision_record(
            pkg, decision="ACCEPT", reviewer="Chris", decision_reason="Should block."
        )
        assert record["review_state"] == "BLOCKED"

    def test_evidence_chain_fail_blocked(self):
        pkg = _build_ready_package_17j()
        pkg["evidence_chain_status"]["chain_intact"] = False
        record = _create_candidate_package_review_decision_record(
            pkg, decision="ACCEPT", reviewer="Chris", decision_reason="Should block."
        )
        assert record["review_state"] == "BLOCKED"

    def test_simulated_gate_fail_blocked(self):
        pkg = _build_ready_package_17j()
        pkg["simulated_gate_summary"]["all_gates_passed"] = False
        record = _create_candidate_package_review_decision_record(
            pkg, decision="ACCEPT", reviewer="Chris", decision_reason="Should block."
        )
        assert record["review_state"] == "BLOCKED"

    def test_output_labels_present(self):
        pkg = _build_ready_package_17j()
        record = _create_candidate_package_review_decision_record(
            pkg, decision="ACCEPT", reviewer="Chris", decision_reason="Test."
        )
        labels = record.get("output_labels", [])
        assert "PREFLIGHT_REQUEST_DRAFTING_ONLY" in labels
        assert "PLANNING_ONLY" in labels
        assert "NON_EXECUTABLE" in labels
        assert "ACTUAL_PREFLIGHT_NOT_COMPLETED" in labels
        assert "PREFLIGHT_NOT_AUTHORIZED" in labels
        assert "SEPARATE_H1_APPROVAL_REQUIRED" in labels

    def test_output_labels_also_on_blocked(self):
        pkg = _build_ready_package_17j()
        pkg["package_state"] = "BLOCKED"
        record = _create_candidate_package_review_decision_record(
            pkg, decision="ACCEPT", reviewer="Chris", decision_reason="Test."
        )
        labels = record.get("output_labels", [])
        assert "NON_EXECUTABLE" in labels
        assert "PLANNING_ONLY" in labels

    def test_labeled_output_in_json(self):
        pkg = _build_ready_package_17j()
        record = _create_candidate_package_review_decision_record(
            pkg, decision="ACCEPT", reviewer="Chris", decision_reason="Test."
        )
        payload = json.dumps(record, sort_keys=True)
        assert "NON_EXECUTABLE" in payload
        assert "PLANNING_ONLY" in payload
        assert "ACTUAL_PREFLIGHT_NOT_COMPLETED" in payload

    def test_immutable_evidence_references_complete(self):
        pkg = _build_ready_package_17j()
        record = _create_candidate_package_review_decision_record(
            pkg, decision="ACCEPT", reviewer="Chris", decision_reason="Test."
        )
        ier = record.get("immutable_evidence_references", {})
        for key in ("proposal_evidence_hash", "dossier_evidence_hash",
                     "planning_decision_record_hash", "order_plan_hash",
                     "simulation_record_hash", "simulation_review_record_hash",
                     "candidate_package_hash"):
            assert key in ier, f"Missing immutable ref: {key}"
            assert len(ier[key]) == 64, f"Ref {key} not 64 chars: {len(ier[key])}"

    def test_required_future_human_actions_accepted(self):
        pkg = _build_ready_package_17j()
        record = _create_candidate_package_review_decision_record(
            pkg, decision="ACCEPT", reviewer="Chris", decision_reason="Test."
        )
        actions = record.get("required_future_human_actions", [])
        assert len(actions) >= 5
        assert any("inspect" in a.lower() for a in actions)
        assert any("preflight" in a.lower() for a in actions)
        assert any("h1" in a.lower() for a in actions)
        assert any("stale" in a.lower() for a in actions)

    def test_blocker_ordering_deterministic(self):
        pkg = _build_ready_package_17j()
        r1 = _create_candidate_package_review_decision_record(
            pkg, decision="ACCEPT", reviewer="", decision_reason=""
        )
        r2 = _create_candidate_package_review_decision_record(
            pkg, decision="ACCEPT", reviewer="", decision_reason=""
        )
        b1 = [b["blocker"] for b in r1["blockers"]]
        b2 = [b["blocker"] for b in r2["blockers"]]
        assert b1 == b2, f"Blocker ordering differs: {b1} vs {b2}"

    def test_no_broker_identifiers_in_output(self):
        pkg = _build_ready_package_17j()
        record = _create_candidate_package_review_decision_record(
            pkg, decision="ACCEPT", reviewer="Chris", decision_reason="Test."
        )
        payload = json.dumps(record, sort_keys=True)
        forbidden = ["permId", "order_id", "orderId", "approval_id",
                     "approvalId", "submission_id", "submissionId",
                     "exec_id", "execId", "conId", "broker_order_id"]
        for fid in forbidden:
            assert fid.lower() not in payload.lower(), \
                f"Forbidden broker identifier '{fid}' found"

    def test_full_chain_non_executable(self):
        bars = _generate_synthetic_ohlc_bars("AAPL", 30)
        proposal = _generate_proposal_packet("AAPL", bars)
        dossier = _review_proposal_dossier(proposal)
        decision = _create_decision_record(dossier, decision="ACCEPT", reviewer="Chris",
                                           decision_reason="Chain test.")
        decision["proposal_evidence_hash"] = proposal.get("evidence_hash", "")
        decision["dossier_evidence_hash"] = dossier.get("evidence_hash", "")
        plan = _create_order_plan_draft(decision, proposal, dossier)
        sim = _create_simulated_preflight_dossier(plan, proposal, dossier, decision)
        review = _create_simulation_review_decision_record(
            sim, proposal, dossier=dossier, decision_record=decision, order_plan=plan,
            decision="ACCEPT", reviewer="Chris", decision_reason="Full chain."
        )
        pkg = _create_candidate_package(review, sim, proposal, dossier=dossier, decision_record=decision, order_plan=plan)
        record_17j = _create_candidate_package_review_decision_record(
            pkg, decision="ACCEPT", reviewer="Chris", decision_reason="Full chain."
        )
        assert pkg["executable"] is False
        assert record_17j["executable"] is False
        assert record_17j["actual_preflight_completed"] is False
        assert record_17j["actual_order_created"] is False


# ── No forbidden access ──────────────────────────────────────────────────────

class TestNoForbiddenAccess17J:

    def test_no_order_endpoints_in_source(self):
        import inspect
        src = inspect.getsource(_create_candidate_package_review_decision_record)
        for pat in ["/order", "/connect", "h1_token", "H1_TOKEN", "X-H1-Token"]:
            assert pat not in src, f"Forbidden pattern: {pat}"

    def test_no_trade_window_in_source(self):
        import inspect
        src = inspect.getsource(_create_candidate_package_review_decision_record)
        assert "ibkr-trade-window" not in src

    def test_no_home_ref_in_source(self):
        import inspect
        src = inspect.getsource(_create_candidate_package_review_decision_record)
        assert "Path.home()" not in src
        assert "~/.openclaw" not in src

    def test_no_sudo_in_source(self):
        import inspect
        src = inspect.getsource(_create_candidate_package_review_decision_record)
        assert "sudo" not in src


# ── Constants ────────────────────────────────────────────────────────────────

class TestPhase17JConstants:

    def test_diagnosis_dict_has_ready(self):
        assert _PHASE17J_DIAGNOSIS["ready"] == "level1_human_candidate_package_review_decision_ok"

    def test_diagnosis_dict_has_all_keys(self):
        required = [
            "ready", "ready_accept_case_failed", "missing_decision_failed",
            "rejected_decision_failed", "deferred_decision_failed",
            "invalid_decision_failed", "missing_reviewer_failed",
            "rejected_missing_reason_failed", "deferred_missing_reason_failed",
            "package_not_ready_failed", "package_not_planning_only_failed",
            "cpp_not_true_failed", "executable_true_failed",
            "broker_authorized_true_failed",
            "preflight_authorized_true_failed",
            "approval_authorized_true_failed",
            "submission_authorized_true_failed",
            "broker_preflight_called_true_failed",
            "actual_preflight_completed_true_failed",
            "actual_order_created_true_failed",
            "package_has_blockers_failed",
            "proposal_hash_mismatch_failed",
            "tampered_evidence_ref_failed",
            "deterministic_failed",
            "no_forbidden_endpoints_failed",
            "no_broker_identifiers_failed",
            "read_only_invariant_failed",
            "fresh_clone_failed", "full_chain_failed",
            "unknown",
        ]
        for k in required:
            assert k in _PHASE17J_DIAGNOSIS, f"Missing diagnosis key: {k}"

    def test_explicit_non_actions_contains_protections(self):
        na = _PHASE17J_EXPLICIT_NON_ACTIONS
        assert any("/order" in s for s in na)
        assert any("h1_token" in s.lower() or "H1" in s for s in na)
        assert any("PREFLIGHT_REQUEST_DRAFTING_ONLY" in s for s in na)
        assert any("candidate" in s.lower() for s in na)

    def test_no_go_returns_correct_structure(self):
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        ts = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        result = _phase17j_no_go(
            "test-id", ts,
            {"branch": "test", "commit": "abc", "tag": "v1", "worktree_clean": False},
            "test_diagnosis", ["action 1"],
        )
        assert result["diagnosis"] == "test_diagnosis"
        assert result["severity"] == "NO_GO"
        assert result["no_order_endpoint_called"] is True
        assert result["no_broker_mutation"] is True


# ── Fresh-clone HOME independence ────────────────────────────────────────────

class TestFreshCloneHomeIndependence17J:

    def test_review_with_empty_home(self):
        with tempfile.TemporaryDirectory() as td:
            env = os.environ.copy()
            env["HOME"] = td
            cp = subprocess.run(
                [sys.executable, "-c", f"""
import sys
sys.path.insert(0, r'{REPO}')
from ibkr_operator import (
    _build_ready_package_17j,
    _create_candidate_package_review_decision_record,
)
pkg = _build_ready_package_17j()
record = _create_candidate_package_review_decision_record(
    pkg, decision="ACCEPT", reviewer="Chris", decision_reason="Fresh clone test."
)
assert record["review_state"] == "ACCEPTED_FOR_PREFLIGHT_REQUEST_DRAFTING"
assert "deterministic_candidate_review_hash" in record
print("OK")
"""],
                capture_output=True, text=True, timeout=30,
                env=env,
            )
            assert "OK" in cp.stdout, f"stderr: {cp.stderr}"


# ── CLI tests ────────────────────────────────────────────────────────────────

class TestPhase17JCLI:

    def test_help_succeeds(self):
        result = subprocess.run(
            [sys.executable, str(OPERATOR),
             "level1-human-candidate-package-review-decision-record-checkpoint", "--help"],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0, f"stderr: {result.stderr[:200]}"

    def test_alias_phase17j_works(self):
        result = subprocess.run(
            [sys.executable, str(OPERATOR),
             "phase17j-human-candidate-package-review-decision-record-checkpoint", "--help"],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0, f"stderr: {result.stderr[:200]}"

    def test_alias_candidate_package_review_works(self):
        result = subprocess.run(
            [sys.executable, str(OPERATOR),
             "candidate-package-review-checkpoint", "--help"],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0, f"stderr: {result.stderr[:200]}"

    def test_json_output_valid(self):
        result = subprocess.run(
            [sys.executable, str(OPERATOR),
             "level1-human-candidate-package-review-decision-record-checkpoint", "--json"],
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
             "level1-human-candidate-package-review-decision-record-checkpoint", "--json"],
            capture_output=True, text=True, timeout=60,
        )
        data = json.loads(result.stdout)
        required = [
            "checkpoint_id", "timestamp", "diagnosis", "severity",
            "no_order_endpoint_called", "no_broker_mutation",
            "ready_accept_case_passed",
            "missing_decision_case_passed",
            "deterministic_case_passed",
            "full_chain_case_passed",
        ]
        for field in required:
            assert field in data, f"Missing required field in CLI output: {field}"


# ── Regression: Determinism at scale ────────────────────────────────────────

class TestRegressionDeterminismAtScale17J:

    def test_20_ready_reviews_all_same_state(self):
        pkg = _build_ready_package_17j()
        records = [
            _create_candidate_package_review_decision_record(
                pkg, decision="ACCEPT", reviewer="Chris", decision_reason="Same."
            )
            for _ in range(20)
        ]
        for i, r in enumerate(records):
            assert r["review_state"] == "ACCEPTED_FOR_PREFLIGHT_REQUEST_DRAFTING", \
                f"Record {i}: expected ACCEPTED_FOR_PREFLIGHT_REQUEST_DRAFTING, got {r['review_state']}"
            assert r["preflight_request_drafting_permitted"] is True

    def test_20_ready_reviews_all_identical_hash(self):
        pkg = _build_ready_package_17j()
        records = [
            _create_candidate_package_review_decision_record(
                pkg, decision="ACCEPT", reviewer="Chris", decision_reason="Same."
            )
            for _ in range(20)
        ]
        hashes = [r["deterministic_candidate_review_hash"] for r in records]
        first_hash = hashes[0]
        for i, h in enumerate(hashes):
            assert h == first_hash, f"Record {i} hash differs: {h[:16]}... vs {first_hash[:16]}..."

    def test_20_ready_reviews_all_zero_blockers(self):
        pkg = _build_ready_package_17j()
        records = [
            _create_candidate_package_review_decision_record(
                pkg, decision="ACCEPT", reviewer="Chris", decision_reason="Same."
            )
            for _ in range(20)
        ]
        for i, r in enumerate(records):
            assert r["blocker_count"] == 0, \
                f"Record {i}: expected 0 blockers, got {r['blocker_count']}"


# ── Regression: Upstream package unchanged after 17J ──────────────────────

class TestRegressionUpstreamUnchanged17J:

    def test_package_unchanged_after_17j(self):
        import copy
        pkg = _build_ready_package_17j()
        pkg_before = copy.deepcopy(pkg)
        _create_candidate_package_review_decision_record(
            pkg, decision="ACCEPT", reviewer="Chris", decision_reason="Should not mutate."
        )
        assert pkg == pkg_before, "Package was mutated by 17J builder"

    def test_deterministic_blockers_same_input(self):
        pkg = _build_ready_package_17j()
        pkg["executable"] = True  # triggers a blocker
        r1 = _create_candidate_package_review_decision_record(
            pkg, decision="ACCEPT", reviewer="Chris", decision_reason="Should block."
        )
        r2 = _create_candidate_package_review_decision_record(
            pkg, decision="ACCEPT", reviewer="Chris", decision_reason="Should block."
        )
        b1 = [b["blocker"] for b in r1["blockers"]]
        b2 = [b["blocker"] for b in r2["blockers"]]
        assert b1 == b2, f"Blockers differ: {b1} vs {b2}"
