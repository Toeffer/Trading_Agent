"""Tests for Phase 17H — Level 1 Human Simulation Review Decision Record Checkpoint."""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ibkr_operator import (
    _PHASE17H_DIAGNOSIS,
    _PHASE17H_EXPLICIT_NON_ACTIONS,
    _create_simulation_review_decision_record,
    _build_ready_sim_dossier,
    _build_blocked_sim_dossier,
    _build_ready_plan_draft,
    _build_accepted_decision_record,
    _synthetic_fixture_missing_decision_pending_17h,
    _synthetic_fixture_accept_for_candidate_packaging_17h,
    _synthetic_fixture_explicit_reject_17h,
    _synthetic_fixture_explicit_defer_17h,
    _synthetic_fixture_missing_reason_fail_closed_17h,
    _synthetic_fixture_missing_reviewer_fail_closed_17h,
    _synthetic_fixture_blocked_sim_accept_blocked_17h,
    _synthetic_fixture_non_ready_sim_accept_blocked_17h,
    _synthetic_fixture_failed_gate_accept_blocked_17h,
    _synthetic_fixture_broker_preflight_called_accept_blocked_17h,
    _synthetic_fixture_executable_true_accept_blocked_17h,
    _synthetic_fixture_broker_authorized_true_accept_blocked_17h,
    _synthetic_fixture_missing_proposal_hash_blocked_17h,
    _synthetic_fixture_missing_dossier_hash_blocked_17h,
    _synthetic_fixture_missing_decision_hash_blocked_17h,
    _synthetic_fixture_missing_order_plan_hash_blocked_17h,
    _synthetic_fixture_missing_simulation_hash_blocked_17h,
    _synthetic_fixture_proposal_hash_mismatch_blocked_17h,
    _synthetic_fixture_dossier_hash_mismatch_blocked_17h,
    _synthetic_fixture_decision_hash_mismatch_blocked_17h,
    _synthetic_fixture_order_plan_hash_mismatch_blocked_17h,
    _synthetic_fixture_tampered_evidence_ref_blocked_17h,
    _synthetic_fixture_blocker_ordering_deterministic_17h,
    _synthetic_fixture_deterministic_review_hash_17h,
    _synthetic_fixture_no_forbidden_endpoints_17h,
    _synthetic_fixture_no_broker_identifiers_17h,
    _synthetic_fixture_read_only_invariant_17h,
    _synthetic_fixture_fresh_clone_17h,
    _synthetic_fixture_full_chain_17h,
    _phase17h_no_go,
    _generate_synthetic_ohlc_bars,
    _generate_proposal_packet,
    _review_proposal_dossier,
    _create_decision_record,
    _create_order_plan_draft,
    _create_simulated_preflight_dossier,
)

REPO = Path(__file__).resolve().parent.parent
OPERATOR = REPO / "ibkr_operator.py"


# ── helpers ──────────────────────────────────────────────────────────────────

def _make_ready_record():
    """Build a valid ACCEPTED_FOR_CANDIDATE_PACKAGING record for tests."""
    sim = _build_ready_sim_dossier()
    bars = _generate_synthetic_ohlc_bars("AAPL", 30)
    proposal = _generate_proposal_packet("AAPL", bars)
    dossier = _review_proposal_dossier(proposal)
    decision = _build_accepted_decision_record()
    decision["proposal_evidence_hash"] = proposal.get("evidence_hash", "")
    decision["dossier_evidence_hash"] = dossier.get("evidence_hash", "")
    plan = _build_ready_plan_draft()
    return _create_simulation_review_decision_record(
        sim, proposal, dossier=dossier, decision_record=decision, order_plan=plan,
        decision="ACCEPT", reviewer="Chris", decision_reason="Valid acceptance."
    )


# ── Synthetic fixtures ───────────────────────────────────────────────────────

class TestSyntheticFixtures17H:

    def test_missing_decision_produces_pending(self):
        c = _synthetic_fixture_missing_decision_pending_17h()
        assert c["passed"], f"Missing decision PENDING case failed: {c}"
        assert c["review_state"] == "PENDING_REVIEW"

    def test_explicit_accept_produces_accepted_for_candidate_packaging(self):
        c = _synthetic_fixture_accept_for_candidate_packaging_17h()
        assert c["passed"], f"Accept for candidate packaging case failed: {c}"
        assert c["review_state"] == "ACCEPTED_FOR_CANDIDATE_PACKAGING"
        assert c["acceptance_scope"] == "CANDIDATE_PACKAGING_ONLY"
        assert c["candidate_packaging_permitted"] is True

    def test_explicit_reject_succeeds(self):
        c = _synthetic_fixture_explicit_reject_17h()
        assert c["passed"], f"Explicit reject case failed: {c}"
        assert c["review_state"] == "REJECTED"

    def test_explicit_defer_succeeds(self):
        c = _synthetic_fixture_explicit_defer_17h()
        assert c["passed"], f"Explicit defer case failed: {c}"
        assert c["review_state"] == "DEFERRED"

    def test_missing_reason_fail_closed(self):
        c = _synthetic_fixture_missing_reason_fail_closed_17h()
        assert c["passed"], f"Missing reason fail-closed case failed: {c}"
        assert c["review_state"] == "BLOCKED"

    def test_missing_reviewer_fail_closed(self):
        c = _synthetic_fixture_missing_reviewer_fail_closed_17h()
        assert c["passed"], f"Missing reviewer fail-closed case failed: {c}"
        assert c["review_state"] == "BLOCKED"

    def test_blocked_sim_accept_blocked(self):
        c = _synthetic_fixture_blocked_sim_accept_blocked_17h()
        assert c["passed"], f"Blocked sim accept blocked case failed: {c}"
        assert c["review_state"] == "BLOCKED"

    def test_non_ready_sim_accept_blocked(self):
        c = _synthetic_fixture_non_ready_sim_accept_blocked_17h()
        assert c["passed"], f"Non-ready sim accept blocked case failed: {c}"
        assert c["review_state"] == "BLOCKED"

    def test_failed_gate_accept_blocked(self):
        c = _synthetic_fixture_failed_gate_accept_blocked_17h()
        assert c["passed"], f"Failed gate accept blocked case failed: {c}"
        assert c["review_state"] == "BLOCKED"

    def test_broker_preflight_called_accept_blocked(self):
        c = _synthetic_fixture_broker_preflight_called_accept_blocked_17h()
        assert c["passed"], f"Preflight called accept blocked case failed: {c}"
        assert c["review_state"] == "BLOCKED"

    def test_executable_true_accept_blocked(self):
        c = _synthetic_fixture_executable_true_accept_blocked_17h()
        assert c["passed"], f"Executable true accept blocked case failed: {c}"
        assert c["review_state"] == "BLOCKED"

    def test_broker_authorized_true_accept_blocked(self):
        c = _synthetic_fixture_broker_authorized_true_accept_blocked_17h()
        assert c["passed"], f"Broker authorized true accept blocked case failed: {c}"
        assert c["review_state"] == "BLOCKED"

    def test_missing_proposal_hash_blocked(self):
        c = _synthetic_fixture_missing_proposal_hash_blocked_17h()
        assert c["passed"], f"Missing proposal hash blocked case failed: {c}"
        assert c["review_state"] == "BLOCKED"

    def test_missing_dossier_hash_blocked(self):
        c = _synthetic_fixture_missing_dossier_hash_blocked_17h()
        assert c["passed"], f"Missing dossier hash blocked case failed: {c}"
        assert c["review_state"] == "BLOCKED"

    def test_missing_decision_hash_blocked(self):
        c = _synthetic_fixture_missing_decision_hash_blocked_17h()
        assert c["passed"], f"Missing decision hash blocked case failed: {c}"
        assert c["review_state"] == "BLOCKED"

    def test_missing_order_plan_hash_blocked(self):
        c = _synthetic_fixture_missing_order_plan_hash_blocked_17h()
        assert c["passed"], f"Missing order-plan hash blocked case failed: {c}"
        assert c["review_state"] == "BLOCKED"

    def test_missing_simulation_hash_blocked(self):
        c = _synthetic_fixture_missing_simulation_hash_blocked_17h()
        assert c["passed"], f"Missing simulation hash blocked case failed: {c}"
        assert c["review_state"] == "BLOCKED"

    def test_proposal_hash_mismatch_blocked(self):
        c = _synthetic_fixture_proposal_hash_mismatch_blocked_17h()
        assert c["passed"], f"Proposal hash mismatch blocked case failed: {c}"
        assert c["review_state"] == "BLOCKED"

    def test_dossier_hash_mismatch_blocked(self):
        c = _synthetic_fixture_dossier_hash_mismatch_blocked_17h()
        assert c["passed"], f"Dossier hash mismatch blocked case failed: {c}"
        assert c["review_state"] == "BLOCKED"

    def test_decision_hash_mismatch_blocked(self):
        c = _synthetic_fixture_decision_hash_mismatch_blocked_17h()
        assert c["passed"], f"Decision hash mismatch blocked case failed: {c}"
        assert c["review_state"] == "BLOCKED"

    def test_order_plan_hash_mismatch_blocked(self):
        c = _synthetic_fixture_order_plan_hash_mismatch_blocked_17h()
        assert c["passed"], f"Order-plan hash mismatch blocked case failed: {c}"
        assert c["review_state"] == "BLOCKED"

    def test_tampered_evidence_ref_blocked(self):
        c = _synthetic_fixture_tampered_evidence_ref_blocked_17h()
        assert c["passed"], f"Tampered evidence ref blocked case failed: {c}"
        assert c["review_state"] == "BLOCKED"

    def test_blocker_ordering_deterministic(self):
        c = _synthetic_fixture_blocker_ordering_deterministic_17h()
        assert c["passed"], f"Blocker ordering deterministic case failed: {c}"
        assert c["same_order"] is True

    def test_deterministic_review_hash(self):
        c = _synthetic_fixture_deterministic_review_hash_17h()
        assert c["passed"], f"Deterministic review hash case failed: {c}"
        assert c["same_state"] is True
        assert c["same_hash"] is True

    def test_no_forbidden_endpoints(self):
        c = _synthetic_fixture_no_forbidden_endpoints_17h()
        assert c["passed"], f"Forbidden endpoints found: {c.get('found', [])}"
        assert len(c.get("found", [])) == 0

    def test_no_broker_identifiers(self):
        c = _synthetic_fixture_no_broker_identifiers_17h()
        assert c["passed"], f"Broker identifiers found: {c.get('found', [])}"

    def test_read_only_invariant(self):
        c = _synthetic_fixture_read_only_invariant_17h()
        assert c["passed"], f"Read-only invariant violated: {c.get('found', [])}"

    def test_fresh_clone(self):
        c = _synthetic_fixture_fresh_clone_17h()
        assert c["passed"], f"Fresh clone case failed: {c}"
        assert c["runs"] is True
        assert c["no_home_refs"] is True

    def test_full_chain(self):
        c = _synthetic_fixture_full_chain_17h()
        assert c["passed"], f"Full chain case failed: {c}"
        assert c["all_non_exec"] is True


# ── Review decision record unit tests ────────────────────────────────────────

class TestSimulationReviewDecisionRecord:

    def test_record_has_all_required_fields(self):
        record = _make_ready_record()
        required = [
            "simulation_review_record_version", "review_state", "proposal_id",
            "proposal_evidence_hash", "dossier_evidence_hash",
            "decision_record_hash", "order_plan_hash", "simulation_record_hash",
            "strategy_version", "symbol", "side", "quantity",
            "reviewer_identifier", "decision", "decision_reason",
            "review_timestamp", "acceptance_scope",
            "candidate_packaging_permitted", "planning_scope",
            "executable", "broker_authorized", "preflight_authorized",
            "approval_authorized", "submission_authorized",
            "broker_preflight_called", "immutable_evidence_references",
            "blockers", "deterministic_review_hash", "explicit_non_actions",
        ]
        for field in required:
            assert field in record, f"Missing required field: {field}"

    def test_record_version(self):
        record = _make_ready_record()
        assert record["simulation_review_record_version"] == "simulation-review-decision-record-v1.0.0"

    def test_accepted_record_acceptance_scope(self):
        record = _make_ready_record()
        assert record["review_state"] == "ACCEPTED_FOR_CANDIDATE_PACKAGING"
        assert record["acceptance_scope"] == "CANDIDATE_PACKAGING_ONLY"
        assert record["candidate_packaging_permitted"] is True

    def test_accepted_record_non_executable(self):
        record = _make_ready_record()
        assert record["executable"] is False
        assert record["broker_authorized"] is False
        assert record["preflight_authorized"] is False
        assert record["approval_authorized"] is False
        assert record["submission_authorized"] is False
        assert record["broker_preflight_called"] is False
        assert record["planning_scope"] == "PLANNING_ONLY"

    def test_review_hash_valid(self):
        record = _make_ready_record()
        rh = record.get("deterministic_review_hash", "")
        assert len(rh) == 64
        assert all(c in "0123456789abcdef" for c in rh)

    def test_review_deterministic(self):
        r1 = _make_ready_record()
        r2 = _make_ready_record()
        assert r1["review_state"] == r2["review_state"]
        assert r1["deterministic_review_hash"] == r2["deterministic_review_hash"]

    # ── Missing decision → PENDING_REVIEW ────────────────────────────────

    def test_missing_decision_is_pending(self):
        sim = _build_ready_sim_dossier()
        bars = _generate_synthetic_ohlc_bars("AAPL", 30)
        proposal = _generate_proposal_packet("AAPL", bars)
        record = _create_simulation_review_decision_record(
            sim, proposal, decision="", reviewer="", decision_reason=""
        )
        assert record["review_state"] == "PENDING_REVIEW"

    # ── BLOCKED sim cannot be accepted ────────────────────────────────────

    def test_blocked_sim_is_blocked(self):
        sim = _build_blocked_sim_dossier()
        bars = _generate_synthetic_ohlc_bars("TSLA", 30)
        proposal = _generate_proposal_packet("TSLA", bars)
        record = _create_simulation_review_decision_record(
            sim, proposal, decision="ACCEPT", reviewer="Chris",
            decision_reason="Try to accept blocked sim."
        )
        assert record["review_state"] == "BLOCKED"
        assert any("simulation_not_ready" in b.get("blocker", "")
                   for b in record.get("blockers", []))

    # ── Non-SIMULATION_READY cannot be accepted ──────────────────────────

    def test_pending_input_sim_is_blocked(self):
        sim = _build_ready_sim_dossier()
        sim["simulation_state"] = "PENDING_INPUT"
        bars = _generate_synthetic_ohlc_bars("AAPL", 30)
        proposal = _generate_proposal_packet("AAPL", bars)
        record = _create_simulation_review_decision_record(
            sim, proposal, decision="ACCEPT", reviewer="Chris",
            decision_reason="Try non-ready."
        )
        assert record["review_state"] == "BLOCKED"
        assert any("simulation_not_ready" in b.get("blocker", "")
                   for b in record.get("blockers", []))

    # ── Hash validations ─────────────────────────────────────────────────

    def test_missing_proposal_hash_blocked(self):
        sim = _build_ready_sim_dossier()
        sim["proposal_evidence_hash"] = ""
        sim["immutable_evidence_references"]["proposal_evidence_hash"] = ""
        bars = _generate_synthetic_ohlc_bars("AAPL", 30)
        proposal = _generate_proposal_packet("AAPL", bars)
        record = _create_simulation_review_decision_record(
            sim, proposal, decision="ACCEPT", reviewer="Chris",
            decision_reason="Test."
        )
        assert record["review_state"] == "BLOCKED"
        assert any("missing_or_invalid_proposal_hash" in b.get("blocker", "")
                   for b in record.get("blockers", []))

    def test_proposal_hash_mismatch_blocked(self):
        sim = _build_ready_sim_dossier()
        sim["proposal_evidence_hash"] = "0" * 64
        bars = _generate_synthetic_ohlc_bars("AAPL", 30)
        proposal = _generate_proposal_packet("AAPL", bars)
        record = _create_simulation_review_decision_record(
            sim, proposal, decision="ACCEPT", reviewer="Chris",
            decision_reason="Test."
        )
        assert record["review_state"] == "BLOCKED"
        assert any("proposal_hash_mismatch" in b.get("blocker", "")
                   for b in record.get("blockers", []))

    def test_dossier_hash_mismatch_blocked(self):
        sim = _build_ready_sim_dossier()
        sim["dossier_evidence_hash"] = "0" * 64
        bars = _generate_synthetic_ohlc_bars("AAPL", 30)
        proposal = _generate_proposal_packet("AAPL", bars)
        dossier = _review_proposal_dossier(proposal)
        record = _create_simulation_review_decision_record(
            sim, proposal, dossier=dossier, decision="ACCEPT", reviewer="Chris",
            decision_reason="Test."
        )
        assert record["review_state"] == "BLOCKED"
        assert any("dossier_hash_mismatch" in b.get("blocker", "")
                   for b in record.get("blockers", []))

    # ── REJECT/DEFER require reason ──────────────────────────────────────

    def test_reject_without_reason_blocked(self):
        sim = _build_ready_sim_dossier()
        bars = _generate_synthetic_ohlc_bars("AAPL", 30)
        proposal = _generate_proposal_packet("AAPL", bars)
        record = _create_simulation_review_decision_record(
            sim, proposal, decision="REJECT", reviewer="Chris", decision_reason=""
        )
        assert record["review_state"] == "BLOCKED"
        assert any("missing_decision_reason" in b.get("blocker", "")
                   for b in record.get("blockers", []))

    def test_defer_without_reason_blocked(self):
        sim = _build_ready_sim_dossier()
        bars = _generate_synthetic_ohlc_bars("AAPL", 30)
        proposal = _generate_proposal_packet("AAPL", bars)
        record = _create_simulation_review_decision_record(
            sim, proposal, decision="DEFER", reviewer="Chris", decision_reason=""
        )
        assert record["review_state"] == "BLOCKED"
        assert any("missing_decision_reason" in b.get("blocker", "")
                   for b in record.get("blockers", []))

    # ── Missing reviewer ─────────────────────────────────────────────────

    def test_accept_without_reviewer_blocked(self):
        sim = _build_ready_sim_dossier()
        bars = _generate_synthetic_ohlc_bars("AAPL", 30)
        proposal = _generate_proposal_packet("AAPL", bars)
        record = _create_simulation_review_decision_record(
            sim, proposal, decision="ACCEPT", reviewer="", decision_reason="No reviewer."
        )
        assert record["review_state"] == "BLOCKED"
        assert any("missing_reviewer" in b.get("blocker", "")
                   for b in record.get("blockers", []))

    # ── Auth flags true → blocked ────────────────────────────────────────

    def test_executable_true_blocked(self):
        sim = _build_ready_sim_dossier()
        sim["executable"] = True
        bars = _generate_synthetic_ohlc_bars("AAPL", 30)
        proposal = _generate_proposal_packet("AAPL", bars)
        record = _create_simulation_review_decision_record(
            sim, proposal, decision="ACCEPT", reviewer="Chris",
            decision_reason="Try executable=true."
        )
        assert record["review_state"] == "BLOCKED"
        assert any("executable_not_false" in b.get("blocker", "")
                   for b in record.get("blockers", []))

    def test_broker_authorized_true_blocked(self):
        sim = _build_ready_sim_dossier()
        sim["broker_authorized"] = True
        bars = _generate_synthetic_ohlc_bars("AAPL", 30)
        proposal = _generate_proposal_packet("AAPL", bars)
        record = _create_simulation_review_decision_record(
            sim, proposal, decision="ACCEPT", reviewer="Chris",
            decision_reason="Try broker_authorized=true."
        )
        assert record["review_state"] == "BLOCKED"

    def test_broker_preflight_called_true_blocked(self):
        sim = _build_ready_sim_dossier()
        sim["broker_preflight_called"] = True
        bars = _generate_synthetic_ohlc_bars("AAPL", 30)
        proposal = _generate_proposal_packet("AAPL", bars)
        record = _create_simulation_review_decision_record(
            sim, proposal, decision="ACCEPT", reviewer="Chris",
            decision_reason="Try broker_preflight_called=true."
        )
        assert record["review_state"] == "BLOCKED"
        assert any("broker_preflight_called_not_false" in b.get("blocker", "")
                   for b in record.get("blockers", []))

    # ── Failed gates ─────────────────────────────────────────────────────

    def test_failed_gate_blocked(self):
        sim = _build_ready_sim_dossier()
        sim["simulated_gate_results"]["all_gates_passed"] = False
        bars = _generate_synthetic_ohlc_bars("AAPL", 30)
        proposal = _generate_proposal_packet("AAPL", bars)
        record = _create_simulation_review_decision_record(
            sim, proposal, decision="ACCEPT", reviewer="Chris",
            decision_reason="Try failed gate."
        )
        assert record["review_state"] == "BLOCKED"
        assert any("simulated_gate_failure" in b.get("blocker", "")
                   for b in record.get("blockers", []))

    # ── Evidence references ──────────────────────────────────────────────

    def test_immutable_evidence_references_present(self):
        record = _make_ready_record()
        ier = record.get("immutable_evidence_references", {})
        ref_keys = [
            "proposal_evidence_hash", "dossier_evidence_hash",
            "decision_record_hash", "order_plan_hash",
            "simulation_record_hash",
        ]
        for key in ref_keys:
            assert key in ier, f"Missing immutable evidence reference: {key}"

    def test_tampered_evidence_ref_blocked(self):
        sim = _build_ready_sim_dossier()
        sim["immutable_evidence_references"]["proposal_evidence_hash"] = "f" * 64
        bars = _generate_synthetic_ohlc_bars("AAPL", 30)
        proposal = _generate_proposal_packet("AAPL", bars)
        record = _create_simulation_review_decision_record(
            sim, proposal, decision="ACCEPT", reviewer="Chris",
            decision_reason="Tampered ref test."
        )
        assert record["review_state"] == "BLOCKED"
        assert any("tampered_evidence_reference" in b.get("blocker", "")
                   for b in record.get("blockers", []))

    # ── Blocker ordering ─────────────────────────────────────────────────

    def test_blocker_ordering_deterministic(self):
        sim = _build_ready_sim_dossier()
        sim["proposal_evidence_hash"] = ""
        sim["dossier_evidence_hash"] = ""
        sim["immutable_evidence_references"]["proposal_evidence_hash"] = ""
        sim["immutable_evidence_references"]["dossier_evidence_hash"] = ""
        bars = _generate_synthetic_ohlc_bars("AAPL", 30)
        proposal = _generate_proposal_packet("AAPL", bars)
        r1 = _create_simulation_review_decision_record(
            sim, proposal, decision="ACCEPT", reviewer="Chris",
            decision_reason="Order test 1."
        )
        r2 = _create_simulation_review_decision_record(
            sim, proposal, decision="ACCEPT", reviewer="Chris",
            decision_reason="Order test 2."
        )
        b1 = [b.get("blocker") for b in r1.get("blockers", [])]
        b2 = [b.get("blocker") for b in r2.get("blockers", [])]
        assert b1 == b2, f"Blocker order changed: {b1} vs {b2}"

    # ── Reject with reason succeeds ──────────────────────────────────────

    def test_explicit_reject_with_reason(self):
        sim = _build_ready_sim_dossier()
        bars = _generate_synthetic_ohlc_bars("AAPL", 30)
        proposal = _generate_proposal_packet("AAPL", bars)
        record = _create_simulation_review_decision_record(
            sim, proposal, decision="REJECT", reviewer="Chris",
            decision_reason="Risk threshold exceeded."
        )
        assert record["review_state"] == "REJECTED"

    def test_explicit_defer_with_reason(self):
        sim = _build_ready_sim_dossier()
        bars = _generate_synthetic_ohlc_bars("AAPL", 30)
        proposal = _generate_proposal_packet("AAPL", bars)
        record = _create_simulation_review_decision_record(
            sim, proposal, decision="DEFER", reviewer="Chris",
            decision_reason="Waiting for FOMC."
        )
        assert record["review_state"] == "DEFERRED"

    # ── Explicit non-actions ─────────────────────────────────────────────

    def test_explicit_non_actions_present(self):
        record = _make_ready_record()
        na = record.get("explicit_non_actions", [])
        assert len(na) > 0
        assert any("does not authorize" in s.lower() for s in na)
        assert any("candidate packaging" in s.lower() for s in na)

    # ── No broker identifiers ────────────────────────────────────────────

    def test_no_broker_identifiers(self):
        record = _make_ready_record()
        rec_json = json.dumps(record, sort_keys=True)
        forbidden = ["permId", "order_id", "orderId", "approval_id",
                     "approvalId", "submission_id", "submissionId",
                     "exec_id", "execId", "conId", "broker_order_id"]
        for fid in forbidden:
            assert fid.lower() not in rec_json.lower(), \
                f"Forbidden broker identifier '{fid}' found in review record"

    # ── Full chain ───────────────────────────────────────────────────────

    def test_full_chain_remains_non_executable(self):
        bars = _generate_synthetic_ohlc_bars("AAPL", 30)
        proposal = _generate_proposal_packet("AAPL", bars)
        dossier = _review_proposal_dossier(proposal)
        decision = _create_decision_record(dossier, decision="ACCEPT", reviewer="Chris",
                                           decision_reason="Chain test.")
        decision["proposal_evidence_hash"] = proposal.get("evidence_hash", "")
        decision["dossier_evidence_hash"] = dossier.get("evidence_hash", "")
        plan = _create_order_plan_draft(decision, proposal, dossier)
        sim = _create_simulated_preflight_dossier(plan, proposal, dossier, decision)
        record = _create_simulation_review_decision_record(
            sim, proposal, dossier=dossier, decision_record=decision, order_plan=plan,
            decision="ACCEPT", reviewer="Chris", decision_reason="Full chain."
        )
        assert plan["executable"] is False
        assert sim["executable"] is False
        assert record["executable"] is False
        assert record["broker_authorized"] is False
        assert record["preflight_authorized"] is False
        assert record["approval_authorized"] is False
        assert record["submission_authorized"] is False
        assert record["broker_preflight_called"] is False

    # ── Acceptance scope for non-ACCEPT decisions ────────────────────────

    def test_pending_review_scope_is_none(self):
        sim = _build_ready_sim_dossier()
        bars = _generate_synthetic_ohlc_bars("AAPL", 30)
        proposal = _generate_proposal_packet("AAPL", bars)
        record = _create_simulation_review_decision_record(
            sim, proposal, decision="", reviewer="", decision_reason=""
        )
        assert record["acceptance_scope"] == "NONE"
        assert record["candidate_packaging_permitted"] is False

    def test_rejected_scope_is_none(self):
        sim = _build_ready_sim_dossier()
        bars = _generate_synthetic_ohlc_bars("AAPL", 30)
        proposal = _generate_proposal_packet("AAPL", bars)
        record = _create_simulation_review_decision_record(
            sim, proposal, decision="REJECT", reviewer="Chris",
            decision_reason="Not this time."
        )
        assert record["acceptance_scope"] == "NONE"
        assert record["candidate_packaging_permitted"] is False

    def test_deferred_scope_is_none(self):
        sim = _build_ready_sim_dossier()
        bars = _generate_synthetic_ohlc_bars("AAPL", 30)
        proposal = _generate_proposal_packet("AAPL", bars)
        record = _create_simulation_review_decision_record(
            sim, proposal, decision="DEFER", reviewer="Chris",
            decision_reason="Later."
        )
        assert record["acceptance_scope"] == "NONE"
        assert record["candidate_packaging_permitted"] is False


# ── No forbidden access ──────────────────────────────────────────────────────

class TestSimulationReviewNoForbiddenAccess:

    def test_no_order_endpoints(self):
        import inspect
        src = inspect.getsource(_create_simulation_review_decision_record)
        for pat in ["/order", "/connect", "h1_token", "H1_TOKEN", "X-H1-Token"]:
            assert pat not in src, f"Forbidden pattern: {pat}"

    def test_no_trade_window(self):
        import inspect
        src = inspect.getsource(_create_simulation_review_decision_record)
        assert "ibkr-trade-window" not in src

    def test_no_sudo(self):
        import inspect
        src = inspect.getsource(_create_simulation_review_decision_record)
        assert "sudo" not in src

    def test_no_home_ref(self):
        import inspect
        src = inspect.getsource(_create_simulation_review_decision_record)
        assert "Path.home()" not in src
        assert "~/.openclaw" not in src
        assert "OPENCLAW_DIR" not in src


# ── Constants ────────────────────────────────────────────────────────────────

class TestPhase17HConstants:

    def test_diagnosis_dict_has_ready(self):
        assert _PHASE17H_DIAGNOSIS["ready"] == "level1_human_simulation_review_decision_record_ok"

    def test_diagnosis_dict_has_all_required_keys(self):
        required = [
            "ready", "accept_case_failed", "pending_missing_decision_failed",
            "reject_case_failed", "defer_case_failed",
            "missing_reason_fail_closed_failed", "missing_reviewer_fail_closed_failed",
            "blocked_sim_accept_blocked_failed", "pending_input_accept_blocked_failed",
            "non_ready_sim_accept_blocked_failed", "failed_gate_accept_blocked_failed",
            "broker_preflight_called_accept_blocked_failed",
            "executable_true_accept_blocked_failed",
            "broker_authorized_true_accept_blocked_failed",
            "missing_proposal_hash_failed", "missing_dossier_hash_failed",
            "missing_decision_hash_failed", "missing_order_plan_hash_failed",
            "missing_simulation_hash_failed",
            "proposal_hash_mismatch_failed", "dossier_hash_mismatch_failed",
            "decision_hash_mismatch_failed", "order_plan_hash_mismatch_failed",
            "tampered_evidence_ref_failed", "blocker_ordering_failed",
            "deterministic_failed", "timestamp_independent_failed",
            "immutable_evidence_failed", "no_forbidden_endpoints_failed",
            "no_broker_identifiers_failed", "read_only_invariant_failed",
            "fresh_clone_failed", "full_chain_non_executable_failed",
            "unknown",
        ]
        for k in required:
            assert k in _PHASE17H_DIAGNOSIS, f"Missing diagnosis key: {k}"

    def test_explicit_non_actions_contains_protections(self):
        na = _PHASE17H_EXPLICIT_NON_ACTIONS
        assert any("/order" in s for s in na)
        assert any("h1_token" in s.lower() or "H1" in s for s in na)
        assert any("candidate" in s.lower() for s in na)
        assert any("/connect" in s for s in na)
        assert any("CANDIDATE_PACKAGING_ONLY" in s for s in na)
        assert any("ACCEPTED_FOR_CANDIDATE_PACKAGING" in s for s in na)

    def test_no_go_returns_correct_structure(self):
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        ts = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        result = _phase17h_no_go(
            "test-id", ts,
            {"branch": "test", "commit": "abc", "tag": "v1", "worktree_clean": False},
            "test_diagnosis", ["action 1"],
        )
        assert result["diagnosis"] == "test_diagnosis"
        assert result["severity"] == "NO_GO"
        assert result["no_order_endpoint_called"] is True
        assert result["no_broker_mutation"] is True
        assert result["no_connect_called"] is True
        assert result["no_h1_token_used"] is True
        assert result["no_preflight_endpoint_called"] is True


# ── Fresh-clone HOME independence ────────────────────────────────────────────

class TestFreshCloneHomeIndependence:

    def test_review_record_with_empty_home(self):
        with tempfile.TemporaryDirectory() as td:
            env = os.environ.copy()
            env["HOME"] = td
            cp = subprocess.run(
                [sys.executable, "-c", """
import sys
sys.path.insert(0, r'{repo}')
from ibkr_operator import (
    _create_simulation_review_decision_record, _build_ready_sim_dossier,
    _generate_synthetic_ohlc_bars, _generate_proposal_packet,
    _review_proposal_dossier, _build_accepted_decision_record,
    _build_ready_plan_draft,
)
sim = _build_ready_sim_dossier()
bars = _generate_synthetic_ohlc_bars("AAPL", 30)
proposal = _generate_proposal_packet("AAPL", bars)
dossier = _review_proposal_dossier(proposal)
decision = _build_accepted_decision_record()
decision["proposal_evidence_hash"] = proposal.get("evidence_hash", "")
decision["dossier_evidence_hash"] = dossier.get("evidence_hash", "")
plan = _build_ready_plan_draft()
record = _create_simulation_review_decision_record(
    sim, proposal, dossier=dossier, decision_record=decision, order_plan=plan,
    decision="ACCEPT", reviewer="Chris", decision_reason="Fresh clone test."
)
assert record["review_state"] == "ACCEPTED_FOR_CANDIDATE_PACKAGING"
assert "deterministic_review_hash" in record
print("OK")
""".replace("{repo}", str(REPO))],
                capture_output=True, text=True, timeout=30,
                env=env,
            )
            assert "OK" in cp.stdout, f"stderr: {cp.stderr}"

    def test_full_chain_with_empty_home(self):
        with tempfile.TemporaryDirectory() as td:
            env = os.environ.copy()
            env["HOME"] = td
            cp = subprocess.run(
                [sys.executable, "-c", """
import sys
sys.path.insert(0, r'{repo}')
from ibkr_operator import (
    _generate_synthetic_ohlc_bars, _generate_proposal_packet,
    _review_proposal_dossier, _create_decision_record,
    _create_order_plan_draft, _create_simulated_preflight_dossier,
    _create_simulation_review_decision_record, _build_ready_plan_draft,
    _build_accepted_decision_record, _build_ready_sim_dossier,
)
sim = _build_ready_sim_dossier()
bars = _generate_synthetic_ohlc_bars("AAPL", 30)
proposal = _generate_proposal_packet("AAPL", bars)
dossier = _review_proposal_dossier(proposal)
decision = _create_decision_record(dossier, decision="ACCEPT", reviewer="Chris",
                                   decision_reason="Full-chain 17H.")
decision["proposal_evidence_hash"] = proposal.get("evidence_hash", "")
decision["dossier_evidence_hash"] = dossier.get("evidence_hash", "")
plan = _create_order_plan_draft(decision, proposal, dossier)
sim2 = _create_simulated_preflight_dossier(plan, proposal, dossier, decision)
record = _create_simulation_review_decision_record(
    sim2, proposal, dossier=dossier, decision_record=decision, order_plan=plan,
    decision="ACCEPT", reviewer="Chris", decision_reason="Full-chain test."
)
assert record["review_state"] == "ACCEPTED_FOR_CANDIDATE_PACKAGING"
assert record["executable"] is False
assert record["broker_preflight_called"] is False
print("OK")
""".replace("{repo}", str(REPO))],
                capture_output=True, text=True, timeout=30,
                env=env,
            )
            assert "OK" in cp.stdout, f"stderr: {cp.stderr}"


# ── CLI tests ────────────────────────────────────────────────────────────────

class TestPhase17HCLI:

    def test_help_succeeds(self):
        result = subprocess.run(
            [sys.executable, str(OPERATOR),
             "level1-human-simulation-review-decision-record-checkpoint", "--help"],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0, f"stderr: {result.stderr[:200]}"

    def test_alias_phase17h_works(self):
        result = subprocess.run(
            [sys.executable, str(OPERATOR),
             "phase17h-human-simulation-review-decision-record-checkpoint", "--help"],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0, f"stderr: {result.stderr[:200]}"

    def test_alias_human_simulation_review_works(self):
        result = subprocess.run(
            [sys.executable, str(OPERATOR),
             "human-simulation-review-decision-record-checkpoint", "--help"],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0, f"stderr: {result.stderr[:200]}"

    def test_json_output_valid(self):
        result = subprocess.run(
            [sys.executable, str(OPERATOR),
             "level1-human-simulation-review-decision-record-checkpoint", "--json"],
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
             "level1-human-simulation-review-decision-record-checkpoint", "--json"],
            capture_output=True, text=True, timeout=60,
        )
        data = json.loads(result.stdout)
        required = [
            "checkpoint_id", "timestamp", "diagnosis", "severity",
            "no_order_endpoint_called", "no_preflight_endpoint_called",
            "no_approval_endpoint_called", "no_submit_endpoint_called",
            "no_h1_token_used", "no_connect_called", "no_broker_mutation",
            "missing_decision_pending_case_passed",
            "accept_case_passed",
            "explicit_reject_case_passed",
            "explicit_defer_case_passed",
            "blocked_sim_accept_blocked_case_passed",
            "deterministic_case_passed",
            "full_chain_case_passed",
        ]
        for field in required:
            assert field in data, f"Missing required field in CLI output: {field}"

    def test_canonical_review_record_present(self):
        result = subprocess.run(
            [sys.executable, str(OPERATOR),
             "level1-human-simulation-review-decision-record-checkpoint", "--json"],
            capture_output=True, text=True, timeout=60,
        )
        data = json.loads(result.stdout)
        if data.get("diagnosis") == _PHASE17H_DIAGNOSIS["ready"]:
            cr = data.get("canonical_review_record")
            assert cr is not None, "canonical_review_record must not be None when diagnosis is ready"
            assert "review_state" in cr
            assert "deterministic_review_hash" in cr


# ── Regression: Determinism at scale ────────────────────────────────────────

class TestRegressionDeterminismAtScale17H:
    """Prove that 20+ identical calls produce identical results."""

    def test_20_ready_reviews_all_same_state(self):
        """20 identical review records → all ACCEPTED_FOR_CANDIDATE_PACKAGING."""
        records = [_make_ready_record() for _ in range(20)]
        for i, record in enumerate(records):
            assert record["review_state"] == "ACCEPTED_FOR_CANDIDATE_PACKAGING", \
                f"Record {i}: expected ACCEPTED_FOR_CANDIDATE_PACKAGING, got {record['review_state']}"
            assert record["executable"] is False
            assert record["candidate_packaging_permitted"] is True
            assert record["acceptance_scope"] == "CANDIDATE_PACKAGING_ONLY"

    def test_20_ready_reviews_all_identical_hash(self):
        """20 identical review records → all have the same deterministic hash."""
        records = [_make_ready_record() for _ in range(20)]
        hashes = [r["deterministic_review_hash"] for r in records]
        first_hash = hashes[0]
        for i, h in enumerate(hashes):
            assert h == first_hash, \
                f"Record {i} hash differs: {h[:16]}... vs {first_hash[:16]}..."

    def test_20_ready_reviews_all_zero_blockers(self):
        """20 identical review records → all have zero blockers."""
        records = [_make_ready_record() for _ in range(20)]
        for i, record in enumerate(records):
            assert record["blocker_count"] == 0, \
                f"Record {i}: expected 0 blockers, got {record['blocker_count']}"


# ── Regression: Upstream records unchanged after 17H build ────────────────

class TestRegressionUpstreamRecordsUnchanged17H:
    """Prove that Phase 17H builder does not mutate upstream evidence records."""

    def test_sim_dossier_unchanged_after_17h(self):
        import copy
        sim = _build_ready_sim_dossier()
        sim_before = copy.deepcopy(sim)
        bars = _generate_synthetic_ohlc_bars("AAPL", 30)
        proposal = _generate_proposal_packet("AAPL", bars)
        _create_simulation_review_decision_record(
            sim, proposal, decision="ACCEPT", reviewer="Chris",
            decision_reason="Upstream immutability test."
        )
        assert sim == sim_before, "Sim dossier was mutated by _create_simulation_review_decision_record"

    def test_proposal_unchanged_after_17h(self):
        import copy
        sim = _build_ready_sim_dossier()
        bars = _generate_synthetic_ohlc_bars("AAPL", 30)
        proposal = _generate_proposal_packet("AAPL", bars)
        proposal_before = copy.deepcopy(proposal)
        _create_simulation_review_decision_record(
            sim, proposal, decision="ACCEPT", reviewer="Chris",
            decision_reason="Upstream immutability test."
        )
        assert proposal == proposal_before, "Proposal was mutated by _create_simulation_review_decision_record"

    def test_dossier_unchanged_after_17h(self):
        import copy
        sim = _build_ready_sim_dossier()
        bars = _generate_synthetic_ohlc_bars("AAPL", 30)
        proposal = _generate_proposal_packet("AAPL", bars)
        dossier = _review_proposal_dossier(proposal)
        dossier_before = copy.deepcopy(dossier)
        _create_simulation_review_decision_record(
            sim, proposal, dossier=dossier, decision="ACCEPT", reviewer="Chris",
            decision_reason="Upstream immutability test."
        )
        assert dossier == dossier_before, "Dossier was mutated by _create_simulation_review_decision_record"

    def test_decision_unchanged_after_17h(self):
        import copy
        sim = _build_ready_sim_dossier()
        bars = _generate_synthetic_ohlc_bars("AAPL", 30)
        proposal = _generate_proposal_packet("AAPL", bars)
        dossier = _review_proposal_dossier(proposal)
        decision = _build_accepted_decision_record()
        decision["proposal_evidence_hash"] = proposal.get("evidence_hash", "")
        decision["dossier_evidence_hash"] = dossier.get("evidence_hash", "")
        decision_before = copy.deepcopy(decision)
        _create_simulation_review_decision_record(
            sim, proposal, dossier=dossier, decision_record=decision,
            decision="ACCEPT", reviewer="Chris",
            decision_reason="Upstream immutability test."
        )
        assert decision == decision_before, "Decision was mutated by _create_simulation_review_decision_record"

    def test_order_plan_unchanged_after_17h(self):
        import copy
        sim = _build_ready_sim_dossier()
        bars = _generate_synthetic_ohlc_bars("AAPL", 30)
        proposal = _generate_proposal_packet("AAPL", bars)
        plan = _build_ready_plan_draft()
        plan_before = copy.deepcopy(plan)
        _create_simulation_review_decision_record(
            sim, proposal, order_plan=plan, decision="ACCEPT", reviewer="Chris",
            decision_reason="Upstream immutability test."
        )
        assert plan == plan_before, "Order plan was mutated by _create_simulation_review_decision_record"
