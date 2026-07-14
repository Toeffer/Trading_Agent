"""Tests for Phase 17F — Level 1 Planning-Only Order Plan Draft Checkpoint."""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ibkr_operator import (
    _PHASE17F_DIAGNOSIS,
    _PHASE17F_EXPLICIT_NON_ACTIONS,
    _create_order_plan_draft,
    _build_accepted_decision_record,
    _build_rejected_decision_record,
    _build_pending_decision_record,
    _build_deferred_decision_record,
    _build_proposal_for_decision,
    _build_dossier_for_proposal,
    _synthetic_fixture_planning_draft_ready_17f,
    _synthetic_fixture_pending_review_blocked_17f,
    _synthetic_fixture_rejected_blocked_17f,
    _synthetic_fixture_deferred_blocked_17f,
    _synthetic_fixture_missing_reviewer_blocked_17f,
    _synthetic_fixture_missing_decision_hash_blocked_17f,
    _synthetic_fixture_hash_mismatch_blocked_17f,
    _synthetic_fixture_dossier_hash_mismatch_blocked_17f,
    _synthetic_fixture_disallowed_instrument_blocked_17f,
    _synthetic_fixture_invalid_side_blocked_17f,
    _synthetic_fixture_negative_quantity_blocked_17f,
    _synthetic_fixture_fractional_quantity_blocked_17f,
    _synthetic_fixture_missing_stop_blocked_17f,
    _synthetic_fixture_sizing_risk_mismatch_blocked_17f,
    _synthetic_fixture_no_broker_identifiers_17f,
    _synthetic_fixture_full_chain_non_executable_17f,
    _synthetic_fixture_executable_false_17f,
    _synthetic_fixture_broker_authorized_false_17f,
    _synthetic_fixture_preflight_authorized_false_17f,
    _synthetic_fixture_approval_authorized_false_17f,
    _synthetic_fixture_submission_authorized_false_17f,
    _synthetic_fixture_deterministic_plan_hash_17f,
    _synthetic_fixture_read_only_invariant_17f,
    _synthetic_fixture_fresh_clone_execution_17f,
    _phase17f_no_go,
    _generate_synthetic_ohlc_bars,
    _generate_proposal_packet,
    _review_proposal_dossier,
    _create_decision_record,
)

REPO = Path(__file__).resolve().parent.parent
OPERATOR = REPO / "ibkr_operator.py"


# ── helpers ──────────────────────────────────────────────────────────────────

def _make_ready_plan():
    """Build a valid PLANNING_DRAFT_READY plan for tests that need a baseline."""
    decision = _build_accepted_decision_record()
    bars = _generate_synthetic_ohlc_bars("AAPL", 30)
    proposal = _generate_proposal_packet("AAPL", bars)
    dossier = _review_proposal_dossier(proposal)
    decision["proposal_evidence_hash"] = proposal.get("evidence_hash", "")
    decision["dossier_evidence_hash"] = dossier.get("evidence_hash", "")
    return _create_order_plan_draft(decision, proposal, dossier)


# ── Synthetic fixtures (direct) ──────────────────────────────────────────────

class TestSyntheticFixtures17F:

    def test_planning_draft_ready_passes(self):
        c = _synthetic_fixture_planning_draft_ready_17f()
        assert c["passed"], f"Planning draft ready case failed: {c}"
        assert c["plan_state"] == "PLANNING_DRAFT_READY"
        assert c["executable"] is False
        assert c["broker_authorized"] is False
        assert c["planning_scope"] == "PLANNING_ONLY"

    def test_pending_review_blocked_passes(self):
        c = _synthetic_fixture_pending_review_blocked_17f()
        assert c["passed"], f"Pending review blocked case failed: {c}"
        assert c["plan_state"] == "BLOCKED"
        assert c["blocker_count"] >= 1

    def test_rejected_blocked_passes(self):
        c = _synthetic_fixture_rejected_blocked_17f()
        assert c["passed"], f"Rejected blocked case failed: {c}"
        assert c["plan_state"] == "BLOCKED"

    def test_deferred_blocked_passes(self):
        c = _synthetic_fixture_deferred_blocked_17f()
        assert c["passed"], f"Deferred blocked case failed: {c}"
        assert c["plan_state"] == "BLOCKED"

    def test_missing_reviewer_blocked_passes(self):
        c = _synthetic_fixture_missing_reviewer_blocked_17f()
        assert c["passed"], f"Missing reviewer blocked case failed: {c}"
        assert c["plan_state"] == "BLOCKED"

    def test_missing_decision_hash_blocked_passes(self):
        c = _synthetic_fixture_missing_decision_hash_blocked_17f()
        assert c["passed"], f"Missing decision hash blocked case failed: {c}"
        assert c["plan_state"] == "BLOCKED"

    def test_hash_mismatch_blocked_passes(self):
        c = _synthetic_fixture_hash_mismatch_blocked_17f()
        assert c["passed"], f"Hash mismatch blocked case failed: {c}"
        assert c["plan_state"] == "BLOCKED"

    def test_dossier_hash_mismatch_blocked_passes(self):
        c = _synthetic_fixture_dossier_hash_mismatch_blocked_17f()
        assert c["passed"], f"Dossier hash mismatch blocked case failed: {c}"
        assert c["plan_state"] == "BLOCKED"

    def test_disallowed_instrument_blocked_passes(self):
        c = _synthetic_fixture_disallowed_instrument_blocked_17f()
        assert c["passed"], f"Disallowed instrument blocked case failed: {c}"
        assert c["plan_state"] == "BLOCKED"

    def test_invalid_side_blocked_passes(self):
        c = _synthetic_fixture_invalid_side_blocked_17f()
        assert c["passed"], f"Invalid side blocked case failed: {c}"
        assert c["plan_state"] == "BLOCKED"

    def test_negative_quantity_blocked_passes(self):
        c = _synthetic_fixture_negative_quantity_blocked_17f()
        assert c["passed"], f"Negative quantity blocked case failed: {c}"
        assert c["plan_state"] == "BLOCKED"

    def test_fractional_quantity_blocked_passes(self):
        c = _synthetic_fixture_fractional_quantity_blocked_17f()
        assert c["passed"], f"Fractional quantity blocked case failed: {c}"
        assert c["plan_state"] == "BLOCKED"

    def test_missing_stop_blocked_passes(self):
        c = _synthetic_fixture_missing_stop_blocked_17f()
        assert c["passed"], f"Missing stop blocked case failed: {c}"
        assert c["plan_state"] == "BLOCKED"

    def test_sizing_risk_mismatch_blocked_passes(self):
        c = _synthetic_fixture_sizing_risk_mismatch_blocked_17f()
        assert c["passed"], f"Sizing/risk mismatch case failed: {c}"
        assert c["risk_notional_ok_carried"] is True

    def test_no_broker_identifiers_passes(self):
        c = _synthetic_fixture_no_broker_identifiers_17f()
        assert c["passed"], f"No broker identifiers case failed: {c}"

    def test_full_chain_non_executable_passes(self):
        c = _synthetic_fixture_full_chain_non_executable_17f()
        assert c["passed"], f"Full chain non-executable case failed: {c}"

    def test_executable_false_passes(self):
        c = _synthetic_fixture_executable_false_17f()
        assert c["passed"], f"Executable false case failed: {c}"
        assert c["executable"] is False

    def test_broker_authorized_false_passes(self):
        c = _synthetic_fixture_broker_authorized_false_17f()
        assert c["passed"], f"Broker authorized false case failed: {c}"
        assert c["broker_authorized"] is False

    def test_preflight_authorized_false_passes(self):
        c = _synthetic_fixture_preflight_authorized_false_17f()
        assert c["passed"], f"Preflight authorized false case failed: {c}"
        assert c["preflight_authorized"] is False

    def test_approval_authorized_false_passes(self):
        c = _synthetic_fixture_approval_authorized_false_17f()
        assert c["passed"], f"Approval authorized false case failed: {c}"
        assert c["approval_authorized"] is False

    def test_submission_authorized_false_passes(self):
        c = _synthetic_fixture_submission_authorized_false_17f()
        assert c["passed"], f"Submission authorized false case failed: {c}"
        assert c["submission_authorized"] is False

    def test_deterministic_passes(self):
        c = _synthetic_fixture_deterministic_plan_hash_17f()
        assert c["passed"], f"Deterministic case failed: {c}"
        assert c["same_plan_state"] is True
        assert c["same_plan_hash"] is True

    def test_read_only_invariant_passes(self):
        c = _synthetic_fixture_read_only_invariant_17f()
        assert c["passed"], f"Read-only invariant case failed: {c}"
        assert c["source_clean"] is True

    def test_fresh_clone_execution_passes(self):
        c = _synthetic_fixture_fresh_clone_execution_17f()
        assert c["passed"], f"Fresh-clone execution case failed: {c}"
        assert c["no_home_references"] is True
        assert c["runs_without_home"] is True


# ── Plan draft unit tests ────────────────────────────────────────────────────

class TestOrderPlanDraft:

    def test_plan_draft_has_all_required_fields(self):
        plan = _make_ready_plan()
        required = [
            "plan_record_version", "plan_state", "proposal_id",
            "proposal_evidence_hash", "dossier_evidence_hash",
            "decision_record_hash", "strategy_version", "symbol", "side",
            "quantity", "entry_plan", "stop_exit_plan", "bracket_simulation",
            "time_in_force_plan", "risk_summary", "sizing_calculation",
            "data_quality_reference", "no_trade_checklist_reference",
            "reviewer_identifier", "planning_scope", "executable",
            "broker_authorized", "preflight_authorized",
            "approval_authorized", "submission_authorized",
            "immutable_evidence_references", "deterministic_plan_hash",
            "blockers", "explicit_non_actions",
        ]
        for field in required:
            assert field in plan, f"Missing required field: {field}"

    def test_plan_record_version(self):
        plan = _make_ready_plan()
        assert plan["plan_record_version"] == "order-plan-draft-v1.0.0"

    def test_plan_hash_valid(self):
        plan = _make_ready_plan()
        ph = plan.get("deterministic_plan_hash", "")
        assert len(ph) == 64
        assert all(c in "0123456789abcdef" for c in ph)

    def test_plan_deterministic(self):
        plan1 = _make_ready_plan()
        plan2 = _make_ready_plan()
        assert plan1["plan_state"] == plan2["plan_state"]
        assert plan1["deterministic_plan_hash"] == plan2["deterministic_plan_hash"]

    def test_ready_plan_always_non_executable(self):
        plan = _make_ready_plan()
        assert plan["executable"] is False
        assert plan["broker_authorized"] is False
        assert plan["preflight_authorized"] is False
        assert plan["approval_authorized"] is False
        assert plan["submission_authorized"] is False
        assert plan["planning_scope"] == "PLANNING_ONLY"

    # ── Decision-state blocking ──────────────────────────────────────────

    def test_pending_review_decision_is_blocked(self):
        decision = _build_pending_decision_record()
        bars = _generate_synthetic_ohlc_bars("AAPL", 30)
        proposal = _generate_proposal_packet("AAPL", bars)
        decision["proposal_evidence_hash"] = proposal.get("evidence_hash", "")
        plan = _create_order_plan_draft(decision, proposal)
        assert plan["plan_state"] == "BLOCKED"
        assert any("decision_not_accepted_for_planning" in b.get("blocker", "")
                   for b in plan.get("blockers", []))

    def test_rejected_decision_is_blocked(self):
        decision = _build_rejected_decision_record()
        bars = _generate_synthetic_ohlc_bars("AAPL", 30)
        proposal = _generate_proposal_packet("AAPL", bars)
        dossier = _review_proposal_dossier(proposal)
        decision["proposal_evidence_hash"] = proposal.get("evidence_hash", "")
        decision["dossier_evidence_hash"] = dossier.get("evidence_hash", "")
        plan = _create_order_plan_draft(decision, proposal, dossier)
        assert plan["plan_state"] == "BLOCKED"
        assert any("decision_not_accepted_for_planning" in b.get("blocker", "")
                   for b in plan.get("blockers", []))

    def test_deferred_decision_is_blocked(self):
        decision = _build_deferred_decision_record()
        bars = _generate_synthetic_ohlc_bars("AAPL", 30)
        proposal = _generate_proposal_packet("AAPL", bars)
        dossier = _review_proposal_dossier(proposal)
        decision["proposal_evidence_hash"] = proposal.get("evidence_hash", "")
        decision["dossier_evidence_hash"] = dossier.get("evidence_hash", "")
        plan = _create_order_plan_draft(decision, proposal, dossier)
        assert plan["plan_state"] == "BLOCKED"
        assert any("decision_not_accepted_for_planning" in b.get("blocker", "")
                   for b in plan.get("blockers", []))

    def test_missing_reviewer_is_blocked(self):
        bars = _generate_synthetic_ohlc_bars("AAPL", 30)
        proposal = _generate_proposal_packet("AAPL", bars)
        dossier = _review_proposal_dossier(proposal)
        # No reviewer → falls to PENDING_REVIEW → BLOCKED
        decision = _create_decision_record(dossier, decision="ACCEPT", reviewer="",
                                           decision_reason="Missing reviewer.")
        decision["proposal_evidence_hash"] = proposal.get("evidence_hash", "")
        decision["dossier_evidence_hash"] = dossier.get("evidence_hash", "")
        plan = _create_order_plan_draft(decision, proposal, dossier)
        assert plan["plan_state"] == "BLOCKED"

    # ── Hash-mismatch blocking ───────────────────────────────────────────

    def test_missing_decision_hash_is_blocked(self):
        decision = _build_accepted_decision_record()
        bars = _generate_synthetic_ohlc_bars("AAPL", 30)
        proposal = _generate_proposal_packet("AAPL", bars)
        dossier = _review_proposal_dossier(proposal)
        decision["proposal_evidence_hash"] = proposal.get("evidence_hash", "")
        decision["dossier_evidence_hash"] = dossier.get("evidence_hash", "")
        decision["deterministic_record_hash"] = "bad"
        plan = _create_order_plan_draft(decision, proposal, dossier)
        assert plan["plan_state"] == "BLOCKED"
        assert any("invalid_decision_record_hash" in b.get("blocker", "")
                   for b in plan.get("blockers", []))

    def test_proposal_hash_mismatch_is_blocked(self):
        decision = _build_accepted_decision_record()
        bars = _generate_synthetic_ohlc_bars("AAPL", 30)
        proposal = _generate_proposal_packet("AAPL", bars)
        dossier = _review_proposal_dossier(proposal)
        decision["proposal_evidence_hash"] = "0" * 64  # mismatch
        decision["dossier_evidence_hash"] = dossier.get("evidence_hash", "")
        plan = _create_order_plan_draft(decision, proposal, dossier)
        assert plan["plan_state"] == "BLOCKED"
        assert any("hash_mismatch" in b.get("blocker", "")
                   for b in plan.get("blockers", []))

    def test_dossier_hash_mismatch_is_blocked(self):
        decision = _build_accepted_decision_record()
        bars = _generate_synthetic_ohlc_bars("AAPL", 30)
        proposal = _generate_proposal_packet("AAPL", bars)
        dossier = _review_proposal_dossier(proposal)
        decision["proposal_evidence_hash"] = proposal.get("evidence_hash", "")
        decision["dossier_evidence_hash"] = "a" * 64  # mismatch
        plan = _create_order_plan_draft(decision, proposal, dossier)
        assert plan["plan_state"] == "BLOCKED"
        assert any("dossier_evidence_hash_mismatch" in b.get("blocker", "")
                   for b in plan.get("blockers", []))

    # ── Instrument / side / quantity blocking ────────────────────────────

    def test_disallowed_symbol_is_blocked(self):
        decision = _build_accepted_decision_record()
        bars = _generate_synthetic_ohlc_bars("TSLA", 30)
        proposal = _generate_proposal_packet("TSLA", bars)
        decision["proposal_evidence_hash"] = proposal.get("evidence_hash", "")
        plan = _create_order_plan_draft(decision, proposal)
        assert plan["plan_state"] == "BLOCKED"
        assert any("disallowed_instrument" in b.get("blocker", "")
                   for b in plan.get("blockers", []))

    def test_invalid_side_is_blocked(self):
        decision = _build_accepted_decision_record()
        bars = _generate_synthetic_ohlc_bars("AAPL", 30)
        proposal = _generate_proposal_packet("AAPL", bars, side="SHORT")
        dossier = _review_proposal_dossier(proposal)
        decision["proposal_evidence_hash"] = proposal.get("evidence_hash", "")
        decision["dossier_evidence_hash"] = dossier.get("evidence_hash", "")
        plan = _create_order_plan_draft(decision, proposal, dossier)
        assert plan["plan_state"] == "BLOCKED"
        assert any("invalid_side" in b.get("blocker", "")
                   for b in plan.get("blockers", []))

    def test_zero_quantity_is_blocked(self):
        decision = _build_accepted_decision_record()
        bars = _generate_synthetic_ohlc_bars("AAPL", 30)
        proposal = _generate_proposal_packet("AAPL", bars)
        dossier = _review_proposal_dossier(proposal)
        decision["proposal_evidence_hash"] = proposal.get("evidence_hash", "")
        decision["dossier_evidence_hash"] = dossier.get("evidence_hash", "")
        proposal["quantity"] = 0
        plan = _create_order_plan_draft(decision, proposal, dossier)
        assert plan["plan_state"] == "BLOCKED"
        assert any("invalid_quantity" in b.get("blocker", "")
                   for b in plan.get("blockers", []))

    def test_negative_quantity_is_blocked(self):
        decision = _build_accepted_decision_record()
        bars = _generate_synthetic_ohlc_bars("AAPL", 30)
        proposal = _generate_proposal_packet("AAPL", bars)
        dossier = _review_proposal_dossier(proposal)
        decision["proposal_evidence_hash"] = proposal.get("evidence_hash", "")
        decision["dossier_evidence_hash"] = dossier.get("evidence_hash", "")
        proposal["quantity"] = -5
        plan = _create_order_plan_draft(decision, proposal, dossier)
        assert plan["plan_state"] == "BLOCKED"
        assert any("invalid_quantity" in b.get("blocker", "")
                   for b in plan.get("blockers", []))

    def test_fractional_quantity_is_blocked(self):
        decision = _build_accepted_decision_record()
        bars = _generate_synthetic_ohlc_bars("AAPL", 30)
        proposal = _generate_proposal_packet("AAPL", bars)
        dossier = _review_proposal_dossier(proposal)
        decision["proposal_evidence_hash"] = proposal.get("evidence_hash", "")
        decision["dossier_evidence_hash"] = dossier.get("evidence_hash", "")
        proposal["quantity"] = 3.5
        plan = _create_order_plan_draft(decision, proposal, dossier)
        assert plan["plan_state"] == "BLOCKED"
        assert any("invalid_quantity" in b.get("blocker", "")
                   for b in plan.get("blockers", []))

    # ── Stop protection blocking ─────────────────────────────────────────

    def test_stop_must_be_below_entry_for_buy(self):
        decision = _build_accepted_decision_record()
        bars = _generate_synthetic_ohlc_bars("AAPL", 30)
        proposal = _generate_proposal_packet("AAPL", bars)
        dossier = _review_proposal_dossier(proposal)
        decision["proposal_evidence_hash"] = proposal.get("evidence_hash", "")
        decision["dossier_evidence_hash"] = dossier.get("evidence_hash", "")
        proposal["stop_exit_plan"]["initial_stop_loss"] = proposal["entry_price"] + 10
        plan = _create_order_plan_draft(decision, proposal, dossier)
        assert plan["plan_state"] == "BLOCKED"
        assert any("stop_above_or_at_entry" in b.get("blocker", "")
                   for b in plan.get("blockers", []))

    def test_missing_protective_stop_is_blocked(self):
        decision = _build_accepted_decision_record()
        bars = _generate_synthetic_ohlc_bars("AAPL", 30)
        proposal = _generate_proposal_packet("AAPL", bars)
        dossier = _review_proposal_dossier(proposal)
        decision["proposal_evidence_hash"] = proposal.get("evidence_hash", "")
        decision["dossier_evidence_hash"] = dossier.get("evidence_hash", "")
        proposal["stop_exit_plan"]["initial_stop_loss"] = 0
        plan = _create_order_plan_draft(decision, proposal, dossier)
        assert plan["plan_state"] == "BLOCKED"
        assert any("missing_protective_stop" in b.get("blocker", "")
                   for b in plan.get("blockers", []))

    def test_stop_quantity_must_match_plan_quantity(self):
        decision = _build_accepted_decision_record()
        bars = _generate_synthetic_ohlc_bars("AAPL", 30)
        proposal = _generate_proposal_packet("AAPL", bars)
        dossier = _review_proposal_dossier(proposal)
        decision["proposal_evidence_hash"] = proposal.get("evidence_hash", "")
        decision["dossier_evidence_hash"] = dossier.get("evidence_hash", "")
        proposal["bracket_simulation"]["child_stop_quantity"] = proposal["quantity"] + 100
        plan = _create_order_plan_draft(decision, proposal, dossier)
        assert plan["plan_state"] == "BLOCKED"
        assert any("stop_quantity_mismatch" in b.get("blocker", "")
                   for b in plan.get("blockers", []))

    # ── Data-quality / no-trade gate blocking ────────────────────────────

    def test_data_quality_fail_is_blocked(self):
        decision = _build_accepted_decision_record()
        bars = _generate_synthetic_ohlc_bars("AAPL", 30)
        proposal = _generate_proposal_packet("AAPL", bars)
        dossier = _review_proposal_dossier(proposal)
        decision["proposal_evidence_hash"] = proposal.get("evidence_hash", "")
        decision["dossier_evidence_hash"] = dossier.get("evidence_hash", "")
        proposal["data_quality"]["overall"] = "FAIL"
        plan = _create_order_plan_draft(decision, proposal, dossier)
        assert plan["plan_state"] == "BLOCKED"
        assert any("data_quality_failed" in b.get("blocker", "")
                   for b in plan.get("blockers", []))

    def test_no_trade_fail_is_blocked(self):
        decision = _build_accepted_decision_record()
        bars = _generate_synthetic_ohlc_bars("AAPL", 30)
        proposal = _generate_proposal_packet("AAPL", bars)
        dossier = _review_proposal_dossier(proposal)
        decision["proposal_evidence_hash"] = proposal.get("evidence_hash", "")
        decision["dossier_evidence_hash"] = dossier.get("evidence_hash", "")
        proposal["no_trade_checklist"]["overall"] = "FAIL"
        plan = _create_order_plan_draft(decision, proposal, dossier)
        assert plan["plan_state"] == "BLOCKED"
        assert any("no_trade_checklist_failed" in b.get("blocker", "")
                   for b in plan.get("blockers", []))

    # ── Sizing / risk mismatch ───────────────────────────────────────────

    def test_sizing_risk_mismatch_is_blocked(self):
        decision = _build_accepted_decision_record()
        bars = _generate_synthetic_ohlc_bars("AAPL", 30)
        proposal = _generate_proposal_packet("AAPL", bars)
        dossier = _review_proposal_dossier(proposal)
        decision["proposal_evidence_hash"] = proposal.get("evidence_hash", "")
        decision["dossier_evidence_hash"] = dossier.get("evidence_hash", "")
        proposal["risk_envelope_check"]["notional_ok"] = False
        proposal["risk_envelope_check"]["overall"] = "FAIL"
        plan = _create_order_plan_draft(decision, proposal, dossier)
        rs = plan.get("risk_summary", {})
        assert rs.get("notional_ok") is False, "Risk summary must carry tampered notional_ok"

    # ── Determinism & blocker ordering ───────────────────────────────────

    def test_blocker_ordering_deterministic(self):
        decision = _build_accepted_decision_record()
        bars = _generate_synthetic_ohlc_bars("TSLA", 30)
        proposal = _generate_proposal_packet("TSLA", bars)
        decision["proposal_evidence_hash"] = ""
        plan1 = _create_order_plan_draft(decision, proposal)
        plan2 = _create_order_plan_draft(decision, proposal)
        blockers1 = [b.get("blocker") for b in plan1.get("blockers", [])]
        blockers2 = [b.get("blocker") for b in plan2.get("blockers", [])]
        assert blockers1 == blockers2, f"Blocker order changed: {blockers1} vs {blockers2}"

    # ── Evidence references ──────────────────────────────────────────────

    def test_explicit_non_actions_in_plan(self):
        plan = _make_ready_plan()
        non_actions = plan.get("explicit_non_actions", [])
        assert len(non_actions) > 0
        assert any("does not authorize" in s.lower() for s in non_actions)
        assert any("planning-only" in s.lower() or "PLANNING_DRAFT_READY" in s for s in non_actions)

    def test_immutable_evidence_references(self):
        plan = _make_ready_plan()
        ier = plan.get("immutable_evidence_references", {})
        assert "proposal_evidence_hash" in ier
        assert "dossier_evidence_hash" in ier
        assert "decision_record_hash" in ier
        assert "strategy_version_ref" in ier

    def test_reviewer_identifier_carried_through(self):
        plan = _make_ready_plan()
        assert plan["reviewer_identifier"] == "Chris"

    # ── No broker identifiers ────────────────────────────────────────────

    def test_no_order_approval_submission_ids(self):
        plan = _make_ready_plan()
        plan_json = json.dumps(plan, sort_keys=True)
        forbidden = ["permId", "order_id", "orderId", "approval_id",
                     "approvalId", "submission_id", "submissionId",
                     "exec_id", "execId", "broker_order_id", "brokerOrderId"]
        for fid in forbidden:
            assert fid.lower() not in plan_json.lower(), \
                f"Forbidden broker identifier '{fid}' found in plan"

    # ── Full chain non-executable ────────────────────────────────────────

    def test_full_chain_remains_non_executable(self):
        bars = _generate_synthetic_ohlc_bars("AAPL", 30)
        proposal = _generate_proposal_packet("AAPL", bars)
        dossier = _review_proposal_dossier(proposal)
        decision = _create_decision_record(dossier, decision="ACCEPT", reviewer="Chris",
                                           decision_reason="Chain test.")
        decision["proposal_evidence_hash"] = proposal.get("evidence_hash", "")
        decision["dossier_evidence_hash"] = dossier.get("evidence_hash", "")
        plan = _create_order_plan_draft(decision, proposal, dossier)

        assert decision["executable"] is False, "Decision must be non-executable"
        assert plan["executable"] is False, "Plan must be non-executable"
        assert plan["planning_scope"] == "PLANNING_ONLY"
        assert plan["broker_authorized"] is False
        assert plan["preflight_authorized"] is False
        assert plan["approval_authorized"] is False
        assert plan["submission_authorized"] is False


# ── No forbidden endpoint / H1 / trade-window / broker / guard / runtime ─────

class TestOrderPlanDraftNoForbiddenAccess:

    def test_create_order_plan_draft_has_no_order_endpoints(self):
        import inspect
        src = inspect.getsource(_create_order_plan_draft)
        for pat in ["/order", "/connect", "h1_token", "H1_TOKEN", "X-H1-Token"]:
            assert pat not in src, f"Forbidden pattern in _create_order_plan_draft: {pat}"

    def test_create_order_plan_draft_has_no_trade_window(self):
        import inspect
        src = inspect.getsource(_create_order_plan_draft)
        assert "ibkr-trade-window" not in src

    def test_create_order_plan_draft_has_no_sudo(self):
        import inspect
        src = inspect.getsource(_create_order_plan_draft)
        assert "sudo" not in src

    def test_create_order_plan_draft_has_no_home_ref(self):
        import inspect
        src = inspect.getsource(_create_order_plan_draft)
        assert "Path.home()" not in src
        assert "~/.openclaw" not in src
        assert "OPENCLAW_DIR" not in src

    def test_helper_builders_have_no_forbidden_refs(self):
        import inspect
        for func in [_build_accepted_decision_record, _build_rejected_decision_record,
                     _build_pending_decision_record, _build_deferred_decision_record]:
            src = inspect.getsource(func)
            for pat in ["/order", "/connect", "h1_token", "H1_TOKEN", "X-H1-Token",
                        "sudo", "ibkr-trade-window"]:
                assert pat not in src, f"Forbidden in {func.__name__}: {pat}"


# ── Constants ────────────────────────────────────────────────────────────────

class TestPhase17FConstants:

    def test_diagnosis_dict_has_ready(self):
        assert _PHASE17F_DIAGNOSIS["ready"] == "level1_planning_only_order_plan_draft_ok"

    def test_diagnosis_dict_has_all_required_keys(self):
        required = [
            "ready",
            "planning_draft_ready_case_failed",
            "pending_review_blocked_case_failed",
            "rejected_blocked_case_failed",
            "executable_false_case_failed",
            "broker_authorized_false_case_failed",
            "preflight_authorized_false_case_failed",
            "approval_authorized_false_case_failed",
            "submission_authorized_false_case_failed",
            "read_only_invariant_case_failed",
            "fresh_clone_case_failed",
            "deterministic_case_failed",
            "hash_mismatch_blocked_case_failed",
            "disallowed_instrument_blocked_case_failed",
            "unknown",
        ]
        for k in required:
            assert k in _PHASE17F_DIAGNOSIS, f"Missing diagnosis key: {k}"

    def test_explicit_non_actions_contains_protections(self):
        na = _PHASE17F_EXPLICIT_NON_ACTIONS
        assert any("/order" in s for s in na)
        assert any("h1_token" in s.lower() or "H1" in s for s in na)
        assert any("planning" in s.lower() for s in na)
        assert any("/connect" in s for s in na)
        assert any("PLANNING_DRAFT_READY" in s for s in na)

    def test_no_go_returns_correct_structure(self):
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        ts = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        result = _phase17f_no_go(
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


# ── Fresh-clone HOME independence ────────────────────────────────────────────

class TestFreshCloneHomeIndependence:

    def test_plan_draft_with_empty_home(self):
        """_create_order_plan_draft must work with HOME set to a temp dir."""
        with tempfile.TemporaryDirectory() as td:
            env = os.environ.copy()
            env["HOME"] = td
            cp = subprocess.run(
                [sys.executable, "-c", """
import sys
sys.path.insert(0, r'{repo}')
from ibkr_operator import _create_order_plan_draft, _build_accepted_decision_record
from ibkr_operator import _generate_synthetic_ohlc_bars, _generate_proposal_packet
from ibkr_operator import _review_proposal_dossier

decision = _build_accepted_decision_record()
bars = _generate_synthetic_ohlc_bars("AAPL", 30)
proposal = _generate_proposal_packet("AAPL", bars)
dossier = _review_proposal_dossier(proposal)
decision["proposal_evidence_hash"] = proposal.get("evidence_hash", "")
decision["dossier_evidence_hash"] = dossier.get("evidence_hash", "")
plan = _create_order_plan_draft(decision, proposal, dossier)
assert plan["plan_state"] == "PLANNING_DRAFT_READY"
assert "deterministic_plan_hash" in plan
print("OK")
""".replace("{repo}", str(REPO))],
                capture_output=True, text=True, timeout=30,
                env=env,
            )
            assert "OK" in cp.stdout, f"stderr: {cp.stderr}"

    def test_full_chain_with_empty_home(self):
        """Full 17C→17D→17E→17F chain must work with HOME set to temp dir."""
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
    _create_order_plan_draft,
)

bars = _generate_synthetic_ohlc_bars("AAPL", 30)
proposal = _generate_proposal_packet("AAPL", bars)
dossier = _review_proposal_dossier(proposal)
decision = _create_decision_record(dossier, decision="ACCEPT", reviewer="Chris",
                                   decision_reason="Full-chain.")
decision["proposal_evidence_hash"] = proposal.get("evidence_hash", "")
decision["dossier_evidence_hash"] = dossier.get("evidence_hash", "")
plan = _create_order_plan_draft(decision, proposal, dossier)

# Every stage must be non-executable
assert proposal.get("advisory_only_statement") != ""
assert decision["executable"] is False
assert plan["plan_state"] == "PLANNING_DRAFT_READY"
assert plan["executable"] is False
assert plan["broker_authorized"] is False
assert plan["preflight_authorized"] is False
assert plan["approval_authorized"] is False
assert plan["submission_authorized"] is False
print("OK")
""".replace("{repo}", str(REPO))],
                capture_output=True, text=True, timeout=30,
                env=env,
            )
            assert "OK" in cp.stdout, f"stderr: {cp.stderr}"


# ── CLI tests ────────────────────────────────────────────────────────────────

class TestPhase17FCLI:

    def test_help_succeeds(self):
        result = subprocess.run(
            [sys.executable, str(OPERATOR),
             "level1-planning-only-order-plan-draft-checkpoint", "--help"],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0, f"stderr: {result.stderr[:200]}"

    def test_alias_phase17f_works(self):
        result = subprocess.run(
            [sys.executable, str(OPERATOR),
             "phase17f-planning-only-order-plan-draft-checkpoint", "--help"],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0, f"stderr: {result.stderr[:200]}"

    def test_alias_planning_only_works(self):
        result = subprocess.run(
            [sys.executable, str(OPERATOR),
             "planning-only-order-plan-draft-checkpoint", "--help"],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0, f"stderr: {result.stderr[:200]}"

    def test_json_output_valid(self):
        result = subprocess.run(
            [sys.executable, str(OPERATOR),
             "level1-planning-only-order-plan-draft-checkpoint", "--json"],
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
             "level1-planning-only-order-plan-draft-checkpoint", "--json"],
            capture_output=True, text=True, timeout=60,
        )
        data = json.loads(result.stdout)
        required = [
            "checkpoint_id", "timestamp", "diagnosis", "severity",
            "no_order_endpoint_called", "no_preflight_endpoint_called",
            "no_approval_endpoint_called", "no_submit_endpoint_called",
            "no_h1_token_used", "no_connect_called", "no_broker_mutation",
            "no_trade_window_helper_called",
            "execution_authorized_now", "order_enablement_allowed_now",
            "order_enablement_performed", "execution_performed",
            "current_level", "explicit_non_actions",
            "planning_draft_ready_case_passed",
            "pending_review_blocked_case_passed",
            "rejected_blocked_case_passed",
            "deferred_blocked_case_passed",
            "missing_reviewer_blocked_case_passed",
            "missing_decision_hash_blocked_case_passed",
            "dossier_hash_mismatch_blocked_case_passed",
            "invalid_side_blocked_case_passed",
            "negative_quantity_blocked_case_passed",
            "fractional_quantity_blocked_case_passed",
            "missing_stop_blocked_case_passed",
            "sizing_risk_mismatch_blocked_case_passed",
            "no_broker_identifiers_case_passed",
            "full_chain_non_executable_case_passed",
            "executable_false_case_passed",
            "broker_authorized_false_case_passed",
        ]
        for field in required:
            assert field in data, f"Missing required field in CLI output: {field}"

    def test_canonical_plan_draft_present(self):
        result = subprocess.run(
            [sys.executable, str(OPERATOR),
             "level1-planning-only-order-plan-draft-checkpoint", "--json"],
            capture_output=True, text=True, timeout=60,
        )
        data = json.loads(result.stdout)
        if data.get("diagnosis") == _PHASE17F_DIAGNOSIS["ready"]:
            cp = data.get("canonical_order_plan_draft")
            assert cp is not None, "canonical_order_plan_draft must not be None when diagnosis is ready"
            assert "plan_state" in cp
            assert "deterministic_plan_hash" in cp

    def test_cli_returns_planning_draft_ready(self):
        result = subprocess.run(
            [sys.executable, str(OPERATOR),
             "level1-planning-only-order-plan-draft-checkpoint", "--json"],
            capture_output=True, text=True, timeout=60,
        )
        data = json.loads(result.stdout)
        if data.get("diagnosis") == _PHASE17F_DIAGNOSIS["ready"]:
            assert data.get("planning_draft_ready_case_passed") is True, \
                f"planning_draft_ready_case_passed should be True, got: {data.get('planning_draft_ready_case_passed')}"
