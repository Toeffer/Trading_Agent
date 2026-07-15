"""Tests for Phase 17I — Level 1 Planning-Only Candidate Package Checkpoint."""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ibkr_operator import (
    _PHASE17I_DIAGNOSIS,
    _PHASE17I_EXPLICIT_NON_ACTIONS,
    _create_candidate_package,
    _build_ready_review_record,
    _build_ready_sim_dossier,
    _build_ready_plan_draft,
    _build_accepted_decision_record,
    _synthetic_fixture_ready_package_17i,
    _synthetic_fixture_missing_review_decision_17i,
    _synthetic_fixture_rejected_review_blocked_17i,
    _synthetic_fixture_deferred_review_blocked_17i,
    _synthetic_fixture_blocked_review_blocked_17i,
    _synthetic_fixture_scope_not_candidate_blocked_17i,
    _synthetic_fixture_executable_true_blocked_17i,
    _synthetic_fixture_broker_authorized_true_blocked_17i,
    _synthetic_fixture_broker_preflight_called_true_blocked_17i,
    _synthetic_fixture_review_has_blockers_blocked_17i,
    _synthetic_fixture_missing_proposal_hash_blocked_17i,
    _synthetic_fixture_proposal_hash_mismatch_blocked_17i,
    _synthetic_fixture_tampered_evidence_ref_blocked_17i,
    _synthetic_fixture_disallowed_instrument_blocked_17i,
    _synthetic_fixture_invalid_side_blocked_17i,
    _synthetic_fixture_invalid_quantity_blocked_17i,
    _synthetic_fixture_missing_stop_blocked_17i,
    _synthetic_fixture_stop_quantity_mismatch_blocked_17i,
    _synthetic_fixture_data_quality_fail_blocked_17i,
    _synthetic_fixture_no_trade_fail_blocked_17i,
    _synthetic_fixture_gate_fail_blocked_17i,
    _synthetic_fixture_deterministic_17i,
    _synthetic_fixture_no_forbidden_endpoints_17i,
    _synthetic_fixture_no_broker_identifiers_17i,
    _synthetic_fixture_read_only_invariant_17i,
    _synthetic_fixture_fresh_clone_17i,
    _synthetic_fixture_full_chain_17i,
    _phase17i_no_go,
    _generate_synthetic_ohlc_bars,
    _generate_proposal_packet,
    _review_proposal_dossier,
    _create_decision_record,
    _create_order_plan_draft,
    _create_simulated_preflight_dossier,
    _create_simulation_review_decision_record,
)

REPO = Path(__file__).resolve().parent.parent
OPERATOR = REPO / "ibkr_operator.py"


# ── helpers ──────────────────────────────────────────────────────────────────

def _make_ready_pkg():
    """Build a valid CANDIDATE_PACKAGE_READY package."""
    review = _build_ready_review_record()
    sim = _build_ready_sim_dossier()
    bars = _generate_synthetic_ohlc_bars("AAPL", 30)
    proposal = _generate_proposal_packet("AAPL", bars)
    dossier = _review_proposal_dossier(proposal)
    decision = _build_accepted_decision_record()
    decision["proposal_evidence_hash"] = proposal.get("evidence_hash", "")
    decision["dossier_evidence_hash"] = dossier.get("evidence_hash", "")
    plan = _build_ready_plan_draft()
    return _create_candidate_package(review, sim, proposal, dossier=dossier, decision_record=decision, order_plan=plan)


# ── Synthetic fixtures ───────────────────────────────────────────────────────

class TestSyntheticFixtures17I:

    def test_ready_package(self):
        c = _synthetic_fixture_ready_package_17i()
        assert c["passed"], f"Ready package case failed: {c}"
        assert c["package_state"] == "CANDIDATE_PACKAGE_READY"

    def test_missing_review_decision(self):
        c = _synthetic_fixture_missing_review_decision_17i()
        assert c["passed"], f"Missing review case failed: {c}"
        assert c["package_state"] in ("BLOCKED", "PENDING_INPUT")

    def test_rejected_review_blocked(self):
        c = _synthetic_fixture_rejected_review_blocked_17i()
        assert c["passed"], f"Rejected review case failed: {c}"

    def test_deferred_review_blocked(self):
        c = _synthetic_fixture_deferred_review_blocked_17i()
        assert c["passed"], f"Deferred review case failed: {c}"

    def test_blocked_review_blocked(self):
        c = _synthetic_fixture_blocked_review_blocked_17i()
        assert c["passed"], f"Blocked review case failed: {c}"

    def test_scope_not_candidate_blocked(self):
        c = _synthetic_fixture_scope_not_candidate_blocked_17i()
        assert c["passed"], f"Scope case failed: {c}"

    def test_executable_true_blocked(self):
        c = _synthetic_fixture_executable_true_blocked_17i()
        assert c["passed"], f"Executable true case failed: {c}"

    def test_broker_authorized_true_blocked(self):
        c = _synthetic_fixture_broker_authorized_true_blocked_17i()
        assert c["passed"], f"Broker authorized case failed: {c}"

    def test_broker_preflight_called_true_blocked(self):
        c = _synthetic_fixture_broker_preflight_called_true_blocked_17i()
        assert c["passed"], f"Preflight called case failed: {c}"

    def test_review_has_blockers_blocked(self):
        c = _synthetic_fixture_review_has_blockers_blocked_17i()
        assert c["passed"], f"Review blockers case failed: {c}"

    def test_missing_proposal_hash_blocked(self):
        c = _synthetic_fixture_missing_proposal_hash_blocked_17i()
        assert c["passed"], f"Missing proposal hash case failed: {c}"

    def test_proposal_hash_mismatch_blocked(self):
        c = _synthetic_fixture_proposal_hash_mismatch_blocked_17i()
        assert c["passed"], f"Proposal hash mismatch case failed: {c}"

    def test_tampered_evidence_ref_blocked(self):
        c = _synthetic_fixture_tampered_evidence_ref_blocked_17i()
        assert c["passed"], f"Tampered evidence ref case failed: {c}"

    def test_disallowed_instrument_blocked(self):
        c = _synthetic_fixture_disallowed_instrument_blocked_17i()
        assert c["passed"], f"Disallowed instrument case failed: {c}"

    def test_invalid_side_blocked(self):
        c = _synthetic_fixture_invalid_side_blocked_17i()
        assert c["passed"], f"Invalid side case failed: {c}"

    def test_invalid_quantity_blocked(self):
        c = _synthetic_fixture_invalid_quantity_blocked_17i()
        assert c["passed"], f"Invalid quantity case failed: {c}"

    def test_missing_stop_blocked(self):
        c = _synthetic_fixture_missing_stop_blocked_17i()
        assert c["passed"], f"Missing stop case failed: {c}"

    def test_stop_quantity_mismatch_blocked(self):
        c = _synthetic_fixture_stop_quantity_mismatch_blocked_17i()
        assert c["passed"], f"Stop quantity mismatch case failed: {c}"

    def test_data_quality_fail_blocked(self):
        c = _synthetic_fixture_data_quality_fail_blocked_17i()
        assert c["passed"], f"Data quality fail case failed: {c}"

    def test_no_trade_fail_blocked(self):
        c = _synthetic_fixture_no_trade_fail_blocked_17i()
        assert c["passed"], f"No-trade fail case failed: {c}"

    def test_gate_fail_blocked(self):
        c = _synthetic_fixture_gate_fail_blocked_17i()
        assert c["passed"], f"Gate fail case failed: {c}"

    def test_deterministic(self):
        c = _synthetic_fixture_deterministic_17i()
        assert c["passed"], f"Deterministic case failed: {c}"
        assert c["same_state"] is True
        assert c["same_hash"] is True

    def test_no_forbidden_endpoints(self):
        c = _synthetic_fixture_no_forbidden_endpoints_17i()
        assert c["passed"], f"Forbidden endpoints: {c.get('found', [])}"

    def test_no_broker_identifiers(self):
        c = _synthetic_fixture_no_broker_identifiers_17i()
        assert c["passed"], f"Broker identifiers: {c.get('found', [])}"

    def test_read_only_invariant(self):
        c = _synthetic_fixture_read_only_invariant_17i()
        assert c["passed"], f"Read-only invariant violated: {c.get('found', [])}"

    def test_fresh_clone(self):
        c = _synthetic_fixture_fresh_clone_17i()
        assert c["passed"], f"Fresh clone case failed: {c}"

    def test_full_chain(self):
        c = _synthetic_fixture_full_chain_17i()
        assert c["passed"], f"Full chain case failed: {c}"
        assert c["all_non_exec"] is True


# ── Unit tests ───────────────────────────────────────────────────────────────

class TestCandidatePackage:

    def test_package_has_all_required_fields(self):
        pkg = _make_ready_pkg()
        required = [
            "candidate_package_version", "package_state", "package_scope",
            "proposal_id", "proposal_evidence_hash", "dossier_evidence_hash",
            "planning_decision_record_hash", "order_plan_hash",
            "simulation_record_hash", "simulation_review_record_hash",
            "strategy_version", "symbol", "side", "quantity",
            "planned_entry", "planned_protective_stop",
            "planned_stop_quantity", "planned_time_in_force",
            "risk_summary", "sizing_summary",
            "data_quality_summary", "no_trade_summary",
            "simulated_gate_summary", "human_review_summary",
            "reviewer_identifier", "decision_reason",
            "evidence_chain_status", "candidate_packaging_permitted",
            "actual_preflight_completed", "executable",
            "broker_authorized", "preflight_authorized",
            "approval_authorized", "submission_authorized",
            "broker_preflight_called", "actual_order_created",
            "immutable_evidence_references",
            "deterministic_candidate_package_hash",
            "blockers", "explicit_non_actions",
            "required_future_human_actions",
        ]
        for field in required:
            assert field in pkg, f"Missing required field: {field}"

    def test_package_version(self):
        pkg = _make_ready_pkg()
        assert pkg["candidate_package_version"] == "candidate-package-v1.0.0"

    def test_ready_package_is_non_executable(self):
        pkg = _make_ready_pkg()
        assert pkg["package_state"] == "CANDIDATE_PACKAGE_READY"
        assert pkg["executable"] is False
        assert pkg["broker_authorized"] is False
        assert pkg["preflight_authorized"] is False
        assert pkg["approval_authorized"] is False
        assert pkg["submission_authorized"] is False
        assert pkg["broker_preflight_called"] is False
        assert pkg["actual_preflight_completed"] is False
        assert pkg["actual_order_created"] is False
        assert pkg["package_scope"] == "PLANNING_ONLY"

    def test_ready_package_cpp_true(self):
        pkg = _make_ready_pkg()
        assert pkg["candidate_packaging_permitted"] is True

    def test_package_hash_valid(self):
        pkg = _make_ready_pkg()
        ph = pkg.get("deterministic_candidate_package_hash", "")
        assert len(ph) == 64
        assert all(c in "0123456789abcdef" for c in ph)

    def test_package_deterministic(self):
        pkg1 = _make_ready_pkg()
        pkg2 = _make_ready_pkg()
        assert pkg1["package_state"] == pkg2["package_state"]
        assert pkg1["deterministic_candidate_package_hash"] == pkg2["deterministic_candidate_package_hash"]

    def test_required_future_human_actions_present(self):
        pkg = _make_ready_pkg()
        actions = pkg.get("required_future_human_actions", [])
        assert len(actions) >= 5
        assert any("inspect" in a.lower() for a in actions)
        assert any("preflight" in a.lower() for a in actions)
        assert any("h1" in a.lower() for a in actions)
        assert any("revalidate" in a.lower() for a in actions)
        assert any("reject" in a.lower() or "stale" in a.lower() for a in actions)

    def test_missing_review_decision_is_blocked(self):
        review = _build_ready_review_record()
        review["review_state"] = "PENDING_REVIEW"
        review["decision"] = "PENDING_REVIEW"
        review["acceptance_scope"] = "NONE"
        review["candidate_packaging_permitted"] = False
        sim = _build_ready_sim_dossier()
        bars = _generate_synthetic_ohlc_bars("AAPL", 30)
        proposal = _generate_proposal_packet("AAPL", bars)
        pkg = _create_candidate_package(review, sim, proposal)
        assert pkg["package_state"] in ("BLOCKED", "PENDING_INPUT")
        assert pkg["candidate_packaging_permitted"] is False

    def test_rejected_review_blocked(self):
        review = _build_ready_review_record()
        review["review_state"] = "REJECTED"
        review["decision"] = "REJECTED"
        review["acceptance_scope"] = "NONE"
        review["candidate_packaging_permitted"] = False
        sim = _build_ready_sim_dossier()
        bars = _generate_synthetic_ohlc_bars("AAPL", 30)
        proposal = _generate_proposal_packet("AAPL", bars)
        pkg = _create_candidate_package(review, sim, proposal)
        assert pkg["package_state"] == "BLOCKED"

    def test_executable_true_blocked(self):
        review = _build_ready_review_record()
        review["executable"] = True
        sim = _build_ready_sim_dossier()
        bars = _generate_synthetic_ohlc_bars("AAPL", 30)
        proposal = _generate_proposal_packet("AAPL", bars)
        pkg = _create_candidate_package(review, sim, proposal)
        assert pkg["package_state"] == "BLOCKED"
        assert any("executable_not_false" in b.get("blocker", "") for b in pkg.get("blockers", []))

    def test_review_blockers_propagate(self):
        review = _build_ready_review_record()
        review["blockers"] = [{"blocker": "test_b", "detail": "Test.", "severity": "HARD_BLOCK"}]
        sim = _build_ready_sim_dossier()
        bars = _generate_synthetic_ohlc_bars("AAPL", 30)
        proposal = _generate_proposal_packet("AAPL", bars)
        pkg = _create_candidate_package(review, sim, proposal)
        assert pkg["package_state"] == "BLOCKED"

    def test_hash_mismatch_blocked(self):
        review = _build_ready_review_record()
        review["proposal_evidence_hash"] = "0" * 64
        sim = _build_ready_sim_dossier()
        bars = _generate_synthetic_ohlc_bars("AAPL", 30)
        proposal = _generate_proposal_packet("AAPL", bars)
        pkg = _create_candidate_package(review, sim, proposal)
        assert pkg["package_state"] == "BLOCKED"

    def test_disallowed_instrument_blocked(self):
        review = _build_ready_review_record()
        review["symbol"] = "TSLA"
        sim = _build_ready_sim_dossier()
        sim["symbol"] = "TSLA"
        bars = _generate_synthetic_ohlc_bars("TSLA", 30)
        proposal = _generate_proposal_packet("TSLA", bars)
        pkg = _create_candidate_package(review, sim, proposal)
        assert pkg["package_state"] == "BLOCKED"

    def test_no_broker_identifiers(self):
        pkg = _make_ready_pkg()
        pkg_json = json.dumps(pkg, sort_keys=True)
        forbidden = ["permId", "order_id", "orderId", "approval_id",
                     "approvalId", "submission_id", "submissionId",
                     "exec_id", "execId", "conId", "broker_order_id"]
        for fid in forbidden:
            assert fid.lower() not in pkg_json.lower(), \
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
        assert plan["executable"] is False
        assert sim["executable"] is False
        assert review["executable"] is False
        assert pkg["executable"] is False
        assert pkg["actual_preflight_completed"] is False
        assert pkg["actual_order_created"] is False
        assert pkg["broker_preflight_called"] is False

    def test_explicit_non_actions_present(self):
        pkg = _make_ready_pkg()
        na = pkg.get("explicit_non_actions", [])
        assert len(na) > 0
        assert any("does not authorize" in s.lower() for s in na)

    def test_evidence_chain_status(self):
        pkg = _make_ready_pkg()
        ecs = pkg.get("evidence_chain_status", {})
        assert ecs.get("all_hashes_valid") is True
        assert ecs.get("chain_intact") is True

    def test_immutable_evidence_references(self):
        pkg = _make_ready_pkg()
        ier = pkg.get("immutable_evidence_references", {})
        ref_keys = [
            "proposal_evidence_hash", "dossier_evidence_hash",
            "decision_record_hash", "order_plan_hash",
            "simulation_record_hash", "simulation_review_record_hash",
        ]
        for key in ref_keys:
            assert key in ier, f"Missing immutable evidence reference: {key}"


# ── No forbidden access ──────────────────────────────────────────────────────

class TestCandidatePackageNoForbiddenAccess:

    def test_no_order_endpoints(self):
        import inspect
        src = inspect.getsource(_create_candidate_package)
        for pat in ["/order", "/connect", "h1_token", "H1_TOKEN", "X-H1-Token"]:
            assert pat not in src, f"Forbidden pattern: {pat}"

    def test_no_trade_window(self):
        import inspect
        src = inspect.getsource(_create_candidate_package)
        assert "ibkr-trade-window" not in src

    def test_no_sudo(self):
        import inspect
        src = inspect.getsource(_create_candidate_package)
        assert "sudo" not in src

    def test_no_home_ref(self):
        import inspect
        src = inspect.getsource(_create_candidate_package)
        assert "Path.home()" not in src
        assert "~/.openclaw" not in src


# ── Constants ────────────────────────────────────────────────────────────────

class TestPhase17IConstants:

    def test_diagnosis_dict_has_ready(self):
        assert _PHASE17I_DIAGNOSIS["ready"] == "level1_planning_only_candidate_package_ok"

    def test_diagnosis_dict_has_all_required_keys(self):
        required = [
            "ready", "ready_package_case_failed",
            "missing_review_decision_failed",
            "rejected_review_blocked_failed", "deferred_review_blocked_failed",
            "blocked_review_blocked_failed", "scope_not_candidate_failed",
            "executable_true_blocked_failed", "broker_authorized_true_blocked_failed",
            "broker_preflight_called_true_blocked_failed",
            "review_has_blockers_failed", "missing_proposal_hash_failed",
            "proposal_hash_mismatch_failed", "tampered_evidence_ref_failed",
            "disallowed_instrument_failed", "invalid_side_failed",
            "invalid_quantity_failed", "missing_stop_failed",
            "stop_quantity_mismatch_failed", "data_quality_fail_blocked_failed",
            "no_trade_fail_blocked_failed", "evidence_chain_fail_blocked_failed",
            "deterministic_failed", "no_forbidden_endpoints_failed",
            "no_broker_identifiers_failed", "read_only_invariant_failed",
            "fresh_clone_failed", "full_chain_failed", "unknown",
        ]
        for k in required:
            assert k in _PHASE17I_DIAGNOSIS, f"Missing diagnosis key: {k}"

    def test_explicit_non_actions_contains_protections(self):
        na = _PHASE17I_EXPLICIT_NON_ACTIONS
        assert any("/order" in s for s in na)
        assert any("h1_token" in s.lower() or "H1" in s for s in na)
        assert any("candidate" in s.lower() for s in na)
        assert any("/connect" in s for s in na)
        assert any("CANDIDATE_PACKAGE_READY" in s for s in na)
        assert any("PLANNING_ONLY" in s for s in na)

    def test_no_go_returns_correct_structure(self):
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        ts = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        result = _phase17i_no_go(
            "test-id", ts,
            {"branch": "test", "commit": "abc", "tag": "v1", "worktree_clean": False},
            "test_diagnosis", ["action 1"],
        )
        assert result["diagnosis"] == "test_diagnosis"
        assert result["severity"] == "NO_GO"
        assert result["no_order_endpoint_called"] is True
        assert result["no_broker_mutation"] is True


# ── Fresh-clone HOME independence ────────────────────────────────────────────

class TestFreshCloneHomeIndependence:

    def test_package_with_empty_home(self):
        with tempfile.TemporaryDirectory() as td:
            env = os.environ.copy()
            env["HOME"] = td
            cp = subprocess.run(
                [sys.executable, "-c", """
import sys
sys.path.insert(0, r'{repo}')
from ibkr_operator import (
    _create_candidate_package, _build_ready_review_record,
    _build_ready_sim_dossier,
    _generate_synthetic_ohlc_bars, _generate_proposal_packet,
    _review_proposal_dossier, _build_accepted_decision_record,
    _build_ready_plan_draft,
)
review = _build_ready_review_record()
sim = _build_ready_sim_dossier()
bars = _generate_synthetic_ohlc_bars("AAPL", 30)
proposal = _generate_proposal_packet("AAPL", bars)
dossier = _review_proposal_dossier(proposal)
decision = _build_accepted_decision_record()
decision["proposal_evidence_hash"] = proposal.get("evidence_hash", "")
decision["dossier_evidence_hash"] = dossier.get("evidence_hash", "")
plan = _build_ready_plan_draft()
pkg = _create_candidate_package(review, sim, proposal, dossier=dossier, decision_record=decision, order_plan=plan)
assert pkg["package_state"] == "CANDIDATE_PACKAGE_READY"
assert "deterministic_candidate_package_hash" in pkg
print("OK")
""".replace("{repo}", str(REPO))],
                capture_output=True, text=True, timeout=30,
                env=env,
            )
            assert "OK" in cp.stdout, f"stderr: {cp.stderr}"


# ── CLI tests ────────────────────────────────────────────────────────────────

class TestPhase17ICLI:

    def test_help_succeeds(self):
        result = subprocess.run(
            [sys.executable, str(OPERATOR),
             "level1-planning-only-candidate-package-checkpoint", "--help"],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0, f"stderr: {result.stderr[:200]}"

    def test_alias_phase17i_works(self):
        result = subprocess.run(
            [sys.executable, str(OPERATOR),
             "phase17i-planning-only-candidate-package-checkpoint", "--help"],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0, f"stderr: {result.stderr[:200]}"

    def test_alias_candidate_package_works(self):
        result = subprocess.run(
            [sys.executable, str(OPERATOR),
             "candidate-package-checkpoint", "--help"],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0, f"stderr: {result.stderr[:200]}"

    def test_json_output_valid(self):
        result = subprocess.run(
            [sys.executable, str(OPERATOR),
             "level1-planning-only-candidate-package-checkpoint", "--json"],
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
             "level1-planning-only-candidate-package-checkpoint", "--json"],
            capture_output=True, text=True, timeout=60,
        )
        data = json.loads(result.stdout)
        required = [
            "checkpoint_id", "timestamp", "diagnosis", "severity",
            "no_order_endpoint_called", "no_broker_mutation",
            "ready_package_case_passed",
            "rejected_review_blocked_case_passed",
            "deterministic_case_passed",
            "full_chain_case_passed",
        ]
        for field in required:
            assert field in data, f"Missing required field in CLI output: {field}"

    def test_canonical_package_present(self):
        result = subprocess.run(
            [sys.executable, str(OPERATOR),
             "level1-planning-only-candidate-package-checkpoint", "--json"],
            capture_output=True, text=True, timeout=60,
        )
        data = json.loads(result.stdout)
        if data.get("diagnosis") == _PHASE17I_DIAGNOSIS["ready"]:
            cp = data.get("canonical_candidate_package")
            assert cp is not None, "canonical_candidate_package must not be None when diagnosis is ready"
            assert "package_state" in cp
            assert "deterministic_candidate_package_hash" in cp


# ── Regression: Determinism at scale ────────────────────────────────────────

class TestRegressionDeterminismAtScale17I:

    def test_20_ready_packages_all_same_state(self):
        pkgs = [_make_ready_pkg() for _ in range(20)]
        for i, pkg in enumerate(pkgs):
            assert pkg["package_state"] == "CANDIDATE_PACKAGE_READY", \
                f"Pkg {i}: expected CANDIDATE_PACKAGE_READY, got {pkg['package_state']}"
            assert pkg["candidate_packaging_permitted"] is True

    def test_20_ready_packages_all_identical_hash(self):
        pkgs = [_make_ready_pkg() for _ in range(20)]
        hashes = [p["deterministic_candidate_package_hash"] for p in pkgs]
        first_hash = hashes[0]
        for i, h in enumerate(hashes):
            assert h == first_hash, f"Pkg {i} hash differs: {h[:16]}... vs {first_hash[:16]}..."

    def test_20_ready_packages_all_zero_blockers(self):
        pkgs = [_make_ready_pkg() for _ in range(20)]
        for i, pkg in enumerate(pkgs):
            assert pkg["blocker_count"] == 0, \
                f"Pkg {i}: expected 0 blockers, got {pkg['blocker_count']}"


# ── Regression: Upstream records unchanged after 17I build ────────────────

class TestRegressionUpstreamRecordsUnchanged17I:

    def test_review_unchanged_after_17i(self):
        import copy
        review = _build_ready_review_record()
        review_before = copy.deepcopy(review)
        sim = _build_ready_sim_dossier()
        bars = _generate_synthetic_ohlc_bars("AAPL", 30)
        proposal = _generate_proposal_packet("AAPL", bars)
        _create_candidate_package(review, sim, proposal)
        assert review == review_before, "Review was mutated"

    def test_sim_dossier_unchanged_after_17i(self):
        import copy
        review = _build_ready_review_record()
        sim = _build_ready_sim_dossier()
        sim_before = copy.deepcopy(sim)
        bars = _generate_synthetic_ohlc_bars("AAPL", 30)
        proposal = _generate_proposal_packet("AAPL", bars)
        _create_candidate_package(review, sim, proposal)
        assert sim == sim_before, "Sim dossier was mutated"

    def test_proposal_unchanged_after_17i(self):
        import copy
        review = _build_ready_review_record()
        sim = _build_ready_sim_dossier()
        bars = _generate_synthetic_ohlc_bars("AAPL", 30)
        proposal = _generate_proposal_packet("AAPL", bars)
        proposal_before = copy.deepcopy(proposal)
        _create_candidate_package(review, sim, proposal)
        assert proposal == proposal_before, "Proposal was mutated"
