"""Tests for Phase 17E — Level 1 Human Review Decision Record Checkpoint."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ibkr_operator import (
    _PHASE17E_DIAGNOSIS,
    _PHASE17E_EXPLICIT_NON_ACTIONS,
    _create_decision_record,
    _build_reviewable_dossier,
    _build_rejected_dossier,
    _synthetic_fixture_accept_for_planning_17e,
    _synthetic_fixture_rejected_dossier_accept_blocked_17e,
    _synthetic_fixture_missing_decision_pending_17e,
    _synthetic_fixture_explicit_reject_17e,
    _synthetic_fixture_explicit_defer_17e,
    _synthetic_fixture_missing_reviewer_fail_closed_17e,
    _synthetic_fixture_missing_reason_fail_closed_17e,
    _synthetic_fixture_proposal_hash_mismatch_17e,
    _synthetic_fixture_dossier_hash_mismatch_17e,
    _synthetic_fixture_accepted_non_executable_17e,
    _synthetic_fixture_deterministic_17e,
    _synthetic_fixture_read_only_invariant_17e,
    _synthetic_fixture_fresh_clone_execution_17e,
    _phase17e_no_go,
)

REPO = Path(__file__).resolve().parent.parent
OPERATOR = REPO / "ibkr_operator.py"


class TestSyntheticFixtures17E:

    def test_accept_for_planning_passes(self):
        c = _synthetic_fixture_accept_for_planning_17e()
        assert c["passed"], f"Accept for planning case failed: {c}"
        assert c["decision"] == "ACCEPTED_FOR_PLANNING"
        assert c["executable"] is False
        assert c["broker_authorized"] is False
        assert c["acceptance_scope"] == "PLANNING_ONLY"

    def test_rejected_dossier_accept_blocked_passes(self):
        c = _synthetic_fixture_rejected_dossier_accept_blocked_17e()
        assert c["passed"], f"Rejected dossier accept blocked case failed: {c}"
        assert c["has_validation_errors"] is True

    def test_missing_decision_pending_passes(self):
        c = _synthetic_fixture_missing_decision_pending_17e()
        assert c["passed"], f"Missing decision PENDING case failed: {c}"
        assert c["decision"] == "PENDING_REVIEW"

    def test_explicit_reject_passes(self):
        c = _synthetic_fixture_explicit_reject_17e()
        assert c["passed"], f"Explicit reject case failed: {c}"
        assert c["decision"] == "REJECTED"
        assert c["has_reason"] is True

    def test_explicit_defer_passes(self):
        c = _synthetic_fixture_explicit_defer_17e()
        assert c["passed"], f"Explicit defer case failed: {c}"
        assert c["decision"] == "DEFERRED"
        assert c["has_reason"] is True

    def test_missing_reviewer_fail_closed_passes(self):
        c = _synthetic_fixture_missing_reviewer_fail_closed_17e()
        assert c["passed"], f"Missing reviewer fail closed case failed: {c}"
        assert c["decision"] == "PENDING_REVIEW"
        assert c["has_validation_errors"] is True

    def test_missing_reason_fail_closed_passes(self):
        c = _synthetic_fixture_missing_reason_fail_closed_17e()
        assert c["passed"], f"Missing reason fail closed case failed: {c}"
        assert c["decision"] == "PENDING_REVIEW"
        assert c["has_validation_errors"] is True

    def test_proposal_hash_mismatch_passes(self):
        c = _synthetic_fixture_proposal_hash_mismatch_17e()
        assert c["passed"], f"Proposal hash mismatch case failed: {c}"
        assert c["has_validation_errors"] is True

    def test_dossier_hash_mismatch_passes(self):
        c = _synthetic_fixture_dossier_hash_mismatch_17e()
        assert c["passed"], f"Dossier hash mismatch case failed: {c}"
        assert c["has_validation_errors"] is True

    def test_accepted_non_executable_passes(self):
        c = _synthetic_fixture_accepted_non_executable_17e()
        assert c["passed"], f"Accepted non-executable case failed: {c}"
        assert c["executable"] is False
        assert c["broker_authorized"] is False
        assert c["acceptance_scope"] == "PLANNING_ONLY"

    def test_deterministic_passes(self):
        c = _synthetic_fixture_deterministic_17e()
        assert c["passed"], f"Deterministic case failed: {c}"
        assert c["same_decision"] is True
        assert c["same_record_hash"] is True

    def test_read_only_invariant_passes(self):
        c = _synthetic_fixture_read_only_invariant_17e()
        assert c["passed"], f"Read-only invariant case failed: {c}"
        assert c["source_clean"] is True

    def test_fresh_clone_execution_passes(self):
        c = _synthetic_fixture_fresh_clone_execution_17e()
        assert c["passed"], f"Fresh-clone execution case failed: {c}"
        assert c["no_home_references"] is True
        assert c["runs_without_home"] is True


class TestDecisionRecord:

    def test_decision_record_has_all_required_fields(self):
        """Decision record must contain all required fields."""
        dossier = _build_reviewable_dossier()
        record = _create_decision_record(dossier, decision="ACCEPT", reviewer="Chris", decision_reason="Test.")
        required = [
            "decision_record_version", "proposal_id", "proposal_evidence_hash",
            "dossier_evidence_hash", "dossier_id", "strategy_version",
            "reviewer_identifier", "decision", "decision_reason",
            "decision_timestamp", "acceptance_scope", "executable",
            "broker_authorized", "immutable_evidence_references",
            "deterministic_record_hash", "explicit_non_actions",
            "validation_errors", "has_validation_errors",
        ]
        for field in required:
            assert field in record, f"Missing required field: {field}"

    def test_decision_record_version(self):
        dossier = _build_reviewable_dossier()
        record = _create_decision_record(dossier, decision="ACCEPT", reviewer="Chris", decision_reason="Test.")
        assert record["decision_record_version"] == "decision-record-v1.0.0"

    def test_decision_record_hash_valid(self):
        """Deterministic record hash must be valid SHA-256."""
        dossier = _build_reviewable_dossier()
        record = _create_decision_record(dossier, decision="ACCEPT", reviewer="Chris", decision_reason="Test.")
        rh = record.get("deterministic_record_hash", "")
        assert len(rh) == 64
        assert all(c in "0123456789abcdef" for c in rh)

    def test_decision_record_deterministic(self):
        """Identical inputs must produce identical record hashes."""
        dossier = _build_reviewable_dossier()
        rec1 = _create_decision_record(dossier, decision="ACCEPT", reviewer="Chris", decision_reason="Determinism test.")
        rec2 = _create_decision_record(dossier, decision="ACCEPT", reviewer="Chris", decision_reason="Determinism test.")
        assert rec1["decision"] == rec2["decision"]
        assert rec1["deterministic_record_hash"] == rec2["deterministic_record_hash"]

    def test_accept_result_always_non_executable(self):
        """ACCEPTED_FOR_PLANNING must always have executable=false."""
        dossier = _build_reviewable_dossier()
        record = _create_decision_record(dossier, decision="ACCEPT", reviewer="Chris", decision_reason="Test.")
        assert record["executable"] is False
        assert record["broker_authorized"] is False
        assert record["acceptance_scope"] == "PLANNING_ONLY"

    def test_reject_and_defer_always_non_executable(self):
        """REJECTED and DEFERRED must always have executable=false."""
        for dec, reason in [("REJECT", "Risk too high."), ("DEFER", "Wait for earnings.")]:
            dossier = _build_reviewable_dossier()
            record = _create_decision_record(dossier, decision=dec, reviewer="Chris", decision_reason=reason)
            assert record["executable"] is False, f"{dec} should have executable=false"
            assert record["broker_authorized"] is False, f"{dec} should have broker_authorized=false"

    def test_decision_aliases(self):
        """Decision aliases must map correctly."""
        dossier = _build_reviewable_dossier()
        tests = [
            ("ACCEPT", "ACCEPTED_FOR_PLANNING"),
            ("APPROVE", "ACCEPTED_FOR_PLANNING"),
            ("REJECT", "REJECTED"),
            ("DECLINE", "REJECTED"),
            ("DEFER", "DEFERRED"),
            ("PENDING", "PENDING_REVIEW"),
            ("", "PENDING_REVIEW"),
        ]
        for alias, expected in tests:
            record = _create_decision_record(dossier, decision=alias, reviewer="Chris", decision_reason="Test.")
            assert record["decision"] == expected, f"Alias '{alias}' should map to '{expected}' but got '{record['decision']}'"

    def test_invalid_decision_falls_to_pending(self):
        """Invalid decision string must produce PENDING_REVIEW with error."""
        dossier = _build_reviewable_dossier()
        record = _create_decision_record(dossier, decision="EXECUTE_NOW", reviewer="Chris", decision_reason="Invalid.")
        assert record["decision"] == "PENDING_REVIEW"
        assert record["has_validation_errors"] is True

    def test_accept_rejected_dossier_blocked(self):
        """Cannot ACCEPT a REJECTED dossier."""
        dossier = _build_rejected_dossier()
        record = _create_decision_record(dossier, decision="ACCEPT", reviewer="Chris", decision_reason="Should be blocked.")
        assert record["decision"] == "PENDING_REVIEW"
        assert record["has_validation_errors"] is True
        assert any("Cannot ACCEPT a REJECTED dossier" in e.get("error", "")
                   for e in record.get("validation_errors", []))

    def test_missing_reviewer_fail_closed(self):
        """Missing reviewer for non-pending decisions must fail closed."""
        dossier = _build_reviewable_dossier()
        for dec in ["ACCEPT", "REJECT", "DEFER"]:
            record = _create_decision_record(dossier, decision=dec, reviewer="", decision_reason="Test.")
            assert record["decision"] == "PENDING_REVIEW", f"Missing reviewer for {dec} should force PENDING_REVIEW"
            assert record["has_validation_errors"] is True

    def test_missing_decision_reason_for_reject_defer(self):
        """Missing reason for REJECT/DEFER must fail closed."""
        dossier = _build_reviewable_dossier()
        for dec in ["REJECT", "DEFER"]:
            record = _create_decision_record(dossier, decision=dec, reviewer="Chris", decision_reason="")
            assert record["decision"] == "PENDING_REVIEW", f"Missing reason for {dec} should force PENDING_REVIEW"
            assert record["has_validation_errors"] is True

    def test_missing_evidence_hashes_fail_closed(self):
        """Tampered evidence hashes in dossier must fail closed."""
        dossier = _build_reviewable_dossier()
        # Clear proposal evidence hash
        dossier["immutable_evidence"]["proposal_evidence_hash"] = ""
        record = _create_decision_record(dossier, decision="ACCEPT", reviewer="Chris", decision_reason="Test.")
        assert record["has_validation_errors"] is True

    def test_accept_reason_can_be_empty(self):
        """Accept decision does NOT require a reason (unlike reject/defer)."""
        dossier = _build_reviewable_dossier()
        record = _create_decision_record(dossier, decision="ACCEPT", reviewer="Chris", decision_reason="")
        # Accept should still work even without reason
        assert record["decision"] == "ACCEPTED_FOR_PLANNING"

    def test_reject_reason_preserved(self):
        """Rejection reason must be preserved in the record."""
        reason = "Volatility too high under current VIX levels."
        dossier = _build_reviewable_dossier()
        record = _create_decision_record(dossier, decision="REJECT", reviewer="Chris", decision_reason=reason)
        assert record["decision_reason"] == reason

    def test_defer_reason_preserved(self):
        """Deferral reason must be preserved in the record."""
        reason = "Deferring until after FOMC meeting."
        dossier = _build_reviewable_dossier()
        record = _create_decision_record(dossier, decision="DEFER", reviewer="Chris", decision_reason=reason)
        assert record["decision_reason"] == reason

    def test_reviewer_preserved(self):
        """Reviewer identifier must be preserved in the record."""
        dossier = _build_reviewable_dossier()
        record = _create_decision_record(dossier, decision="ACCEPT", reviewer="Chris (H1 Token)", decision_reason="OK.")
        assert record["reviewer_identifier"] == "Chris (H1 Token)"

    def test_proposal_id_carried_through(self):
        """Proposal ID from dossier must be carried into the record."""
        dossier = _build_reviewable_dossier()
        record = _create_decision_record(dossier, decision="ACCEPT", reviewer="Chris", decision_reason="Test.")
        assert record["proposal_id"] == dossier["proposal_identity"]["proposal_id"]

    def test_explicit_non_actions_in_record(self):
        """Every decision record must contain explicit non-actions."""
        dossier = _build_reviewable_dossier()
        record = _create_decision_record(dossier, decision="ACCEPT", reviewer="Chris", decision_reason="Test.")
        non_actions = record.get("explicit_non_actions", [])
        assert len(non_actions) > 0
        assert any("does not authorize" in s.lower() for s in non_actions)
        assert any("planning-only" in s.lower() or "PLANNING_ONLY" in s for s in non_actions)

    def test_immutable_evidence_references(self):
        """Immutable evidence references must link back to proposal and dossier."""
        dossier = _build_reviewable_dossier()
        record = _create_decision_record(dossier, decision="ACCEPT", reviewer="Chris", decision_reason="Test.")
        ier = record.get("immutable_evidence_references", {})
        assert "proposal_evidence_hash" in ier
        assert "dossier_evidence_hash" in ier
        assert "strategy_version_ref" in ier


class TestDecisionRecordNoForbiddenAccess:

    def test_create_decision_record_has_no_order_endpoints(self):
        """_create_decision_record must not contain /order references."""
        import inspect
        src = inspect.getsource(_create_decision_record)
        for pat in ["/order", "/connect", "h1_token", "H1_TOKEN", "X-H1-Token"]:
            assert pat not in src, f"Forbidden pattern in _create_decision_record: {pat}"

    def test_create_decision_record_has_no_trade_window(self):
        import inspect
        src = inspect.getsource(_create_decision_record)
        assert "ibkr-trade-window" not in src

    def test_create_decision_record_has_no_sudo(self):
        import inspect
        src = inspect.getsource(_create_decision_record)
        assert "sudo" not in src

    def test_create_decision_record_has_no_home_ref(self):
        import inspect
        src = inspect.getsource(_create_decision_record)
        assert "Path.home()" not in src
        assert "~/.openclaw" not in src
        assert "OPENCLAW_DIR" not in src

    def test_helper_builders_have_no_forbidden_refs(self):
        """Helper builders must also be clean."""
        import inspect
        for func in [_build_reviewable_dossier, _build_rejected_dossier]:
            src = inspect.getsource(func)
            for pat in ["/order", "/connect", "h1_token", "H1_TOKEN", "X-H1-Token", "sudo", "ibkr-trade-window"]:
                assert pat not in src, f"Forbidden in {func.__name__}: {pat}"


class TestPhase17EConstants:

    def test_diagnosis_dict_has_ready(self):
        assert _PHASE17E_DIAGNOSIS["ready"] == "level1_human_review_decision_record_ok"

    def test_diagnosis_dict_has_all_required_keys(self):
        required = [
            "ready", "git_worktree_dirty", "bridge_unreachable",
            "runtime_not_connected", "mode_not_paper", "read_only_not_true",
            "allow_orders_not_false", "endpoints_not_ok", "positions_not_flat",
            "guard_state_not_clean", "kpi_not_hold_system_locked",
            "governance_docs_missing",
            "accept_for_planning_case_failed",
            "rejected_dossier_accept_blocked_case_failed",
            "missing_decision_pending_case_failed",
            "explicit_reject_case_failed",
            "explicit_defer_case_failed",
            "missing_reviewer_fail_closed_case_failed",
            "missing_reason_fail_closed_case_failed",
            "proposal_hash_mismatch_case_failed",
            "dossier_hash_mismatch_case_failed",
            "accepted_non_executable_case_failed",
            "deterministic_case_failed",
            "read_only_invariant_case_failed",
            "fresh_clone_case_failed",
            "unknown",
        ]
        for k in required:
            assert k in _PHASE17E_DIAGNOSIS, f"Missing diagnosis key: {k}"

    def test_explicit_non_actions_contains_protections(self):
        na = _PHASE17E_EXPLICIT_NON_ACTIONS
        assert any("/order" in s for s in na)
        assert any("h1_token" in s.lower() or "H1" in s for s in na)
        assert any("advisory" in s.lower() for s in na)
        assert any("/connect" in s for s in na)
        assert any("ACCEPTED_FOR_PLANNING" in s for s in na)

    def test_no_go_returns_correct_structure(self):
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        ts = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        result = _phase17e_no_go(
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


class TestPhase17ECLI:

    def test_help_succeeds(self):
        result = subprocess.run(
            [sys.executable, str(OPERATOR),
             "level1-human-review-decision-record-checkpoint", "--help"],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0, f"stderr: {result.stderr[:200]}"

    def test_json_output_valid(self):
        result = subprocess.run(
            [sys.executable, str(OPERATOR),
             "level1-human-review-decision-record-checkpoint", "--json"],
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
             "level1-human-review-decision-record-checkpoint", "--json"],
            capture_output=True, text=True, timeout=60,
        )
        data = json.loads(result.stdout)
        required = [
            "diagnosis", "severity", "git",
            "runtime_connected", "mode", "read_only", "allow_orders",
            "endpoints_ok", "positions_flat", "guard_state_clean",
            "kpi_hold_only_system_locked",
            "governance_docs_present",
            "accept_for_planning_case_passed",
            "rejected_dossier_accept_blocked_case_passed",
            "missing_decision_pending_case_passed",
            "explicit_reject_case_passed",
            "explicit_defer_case_passed",
            "missing_reviewer_fail_closed_case_passed",
            "missing_reason_fail_closed_case_passed",
            "proposal_hash_mismatch_case_passed",
            "dossier_hash_mismatch_case_passed",
            "accepted_non_executable_case_passed",
            "deterministic_case_passed",
            "read_only_invariant_case_passed",
            "fresh_clone_case_passed",
            "no_order_endpoint_called", "no_broker_mutation",
            "no_connect_called", "artifact_created",
        ]
        for field in required:
            assert field in data, f"Missing field: {field}"
        if data.get("diagnosis") == _PHASE17E_DIAGNOSIS["ready"]:
            assert "canonical_decision_record" in data
            assert data["canonical_decision_record"] is not None

    def test_cli_alias_phase17e_works(self):
        result = subprocess.run(
            [sys.executable, str(OPERATOR),
             "phase17e-human-review-decision-record-checkpoint", "--help"],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0

    def test_cli_alias_short_works(self):
        result = subprocess.run(
            [sys.executable, str(OPERATOR),
             "human-review-decision-record-checkpoint", "--help"],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0

    def test_deterministic_diagnosis_on_repeat_run(self):
        result1 = subprocess.run(
            [sys.executable, str(OPERATOR),
             "level1-human-review-decision-record-checkpoint", "--json"],
            capture_output=True, text=True, timeout=60,
        )
        data1 = json.loads(result1.stdout)
        result2 = subprocess.run(
            [sys.executable, str(OPERATOR),
             "level1-human-review-decision-record-checkpoint", "--json"],
            capture_output=True, text=True, timeout=60,
        )
        data2 = json.loads(result2.stdout)
        assert data1["diagnosis"] == data2["diagnosis"], \
            f"Non-deterministic: {data1['diagnosis']} vs {data2['diagnosis']}"

    def test_canonical_decision_record_populated(self):
        result = subprocess.run(
            [sys.executable, str(OPERATOR),
             "level1-human-review-decision-record-checkpoint", "--json"],
            capture_output=True, text=True, timeout=60,
        )
        data = json.loads(result.stdout)
        if data.get("diagnosis") == _PHASE17E_DIAGNOSIS["ready"]:
            cr = data.get("canonical_decision_record")
            assert cr is not None, "canonical_decision_record should be populated when OK"
            assert "deterministic_record_hash" in cr
            assert "decision" in cr


class TestPhase17EReadOnlyInvariants:

    def test_no_h1_token_in_checkpoint_source(self):
        import inspect
        from ibkr_operator import _run_level1_human_review_decision_record_checkpoint
        src = inspect.getsource(_run_level1_human_review_decision_record_checkpoint)
        for pat in ["X-H1-Token", "H1_TOKEN_PATH", "/etc/ibkr-bridge/h1_token"]:
            assert pat not in src, f"Forbidden pattern: {pat}"

    def test_no_order_endpoints_in_checkpoint_source(self):
        import inspect
        from ibkr_operator import _run_level1_human_review_decision_record_checkpoint
        src = inspect.getsource(_run_level1_human_review_decision_record_checkpoint)
        assert "/order" not in src

    def test_no_connect_in_checkpoint_source(self):
        import inspect
        from ibkr_operator import _run_level1_human_review_decision_record_checkpoint
        src = inspect.getsource(_run_level1_human_review_decision_record_checkpoint)
        assert "/connect" not in src

    def test_no_trade_window_in_checkpoint_source(self):
        import inspect
        from ibkr_operator import _run_level1_human_review_decision_record_checkpoint
        src = inspect.getsource(_run_level1_human_review_decision_record_checkpoint)
        assert "ibkr-trade-window" not in src

    def test_no_sudo_in_checkpoint_source(self):
        import inspect
        from ibkr_operator import _run_level1_human_review_decision_record_checkpoint
        src = inspect.getsource(_run_level1_human_review_decision_record_checkpoint)
        assert "sudo" not in src


class TestFreshCloneHomeIndependence:

    def test_decision_record_with_empty_home(self):
        """Decision record creation must work with HOME set to empty temp dir."""
        import os
        import tempfile
        import shutil
        orig_home = os.environ.get("HOME", "")
        tmpdir = tempfile.mkdtemp()
        try:
            os.environ["HOME"] = tmpdir
            from ibkr_operator import _build_reviewable_dossier, _create_decision_record
            dossier = _build_reviewable_dossier()
            record = _create_decision_record(dossier, decision="ACCEPT", reviewer="Chris", decision_reason="Test.")
            assert record is not None
            assert "deterministic_record_hash" in record
            assert record["decision"] == "ACCEPTED_FOR_PLANNING"
            assert record["executable"] is False
        finally:
            os.environ["HOME"] = orig_home
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_rejected_dossier_home_independent(self):
        """Rejected dossier decision must work with empty HOME."""
        import os
        import tempfile
        import shutil
        orig_home = os.environ.get("HOME", "")
        tmpdir = tempfile.mkdtemp()
        try:
            os.environ["HOME"] = tmpdir
            from ibkr_operator import _build_rejected_dossier, _create_decision_record
            dossier = _build_rejected_dossier()
            record = _create_decision_record(dossier, decision="REJECT", reviewer="Chris", decision_reason="Blocked.")
            assert record is not None
            assert record["decision"] == "REJECTED"
        finally:
            os.environ["HOME"] = orig_home
            shutil.rmtree(tmpdir, ignore_errors=True)


class Test17CTo17EIntegration:

    def test_full_chain_proposal_to_decision(self):
        """Test the full chain: proposal → dossier → decision record."""
        from ibkr_operator import (
            _generate_synthetic_ohlc_bars,
            _generate_proposal_packet,
            _review_proposal_dossier,
            _create_decision_record,
        )
        bars = _generate_synthetic_ohlc_bars("AAPL", 30)
        proposal = _generate_proposal_packet("AAPL", bars)
        dossier = _review_proposal_dossier(proposal)
        assert dossier["human_decision_state"] == "REVIEWABLE"
        record = _create_decision_record(dossier, decision="ACCEPT", reviewer="Chris", decision_reason="Full chain test.")
        assert record["decision"] == "ACCEPTED_FOR_PLANNING"
        assert record["executable"] is False
        assert record["broker_authorized"] is False
        assert len(record["deterministic_record_hash"]) == 64

    def test_full_chain_rejected_symbol(self):
        """Test full chain for rejected symbol."""
        from ibkr_operator import (
            _generate_synthetic_ohlc_bars,
            _generate_proposal_packet,
            _review_proposal_dossier,
            _create_decision_record,
        )
        bars = _generate_synthetic_ohlc_bars("TSLA", 30)
        proposal = _generate_proposal_packet("TSLA", bars)
        dossier = _review_proposal_dossier(proposal)
        assert dossier["human_decision_state"] == "REJECTED"
        # Try to accept — must be blocked
        record = _create_decision_record(dossier, decision="ACCEPT", reviewer="Chris", decision_reason="Should fail.")
        assert record["decision"] == "PENDING_REVIEW"
        assert record["has_validation_errors"] is True
        # Reject must work
        record2 = _create_decision_record(dossier, decision="REJECT", reviewer="Chris", decision_reason="Invalid symbol.")
        assert record2["decision"] == "REJECTED"

    def test_decision_records_never_executable_across_all_states(self):
        """Every decision state must preserve executable=false."""
        from ibkr_operator import (
            _generate_synthetic_ohlc_bars,
            _generate_proposal_packet,
            _review_proposal_dossier,
            _create_decision_record,
        )
        bars = _generate_synthetic_ohlc_bars("AAPL", 30)
        proposal = _generate_proposal_packet("AAPL", bars)
        dossier = _review_proposal_dossier(proposal)
        scenarios = [
            ("", "", ""),                                    # No decision → PENDING
            ("ACCEPT", "Chris", "Proceed to planning."),     # ACCEPTED_FOR_PLANNING
            ("REJECT", "Chris", "Risk exceeds limits."),     # REJECTED
            ("DEFER", "Chris", "After earnings."),           # DEFERRED
        ]
        for dec, rev, reason in scenarios:
            record = _create_decision_record(dossier, decision=dec, reviewer=rev, decision_reason=reason)
            assert record["executable"] is False, f"State {record['decision']} has executable={record['executable']}"
            assert record["broker_authorized"] is False, f"State {record['decision']} has broker_authorized={record['broker_authorized']}"
