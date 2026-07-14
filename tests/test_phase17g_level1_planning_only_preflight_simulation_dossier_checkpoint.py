"""Tests for Phase 17G — Level 1 Planning-Only Preflight Simulation Dossier Checkpoint."""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ibkr_operator import (
    _PHASE17G_DIAGNOSIS,
    _PHASE17G_EXPLICIT_NON_ACTIONS,
    _create_simulated_preflight_dossier,
    _build_ready_plan_draft,
    _build_blocked_plan_draft,
    _build_accepted_decision_record,
    _synthetic_fixture_simulation_ready_17g,
    _synthetic_fixture_blocked_plan_blocked_17g,
    _synthetic_fixture_executable_false_17g,
    _synthetic_fixture_broker_authorized_false_17g,
    _synthetic_fixture_preflight_authorized_false_17g,
    _synthetic_fixture_approval_authorized_false_17g,
    _synthetic_fixture_submission_authorized_false_17g,
    _synthetic_fixture_broker_preflight_called_false_17g,
    _synthetic_fixture_hash_mismatch_blocked_17g,
    _synthetic_fixture_disallowed_instrument_blocked_17g,
    _synthetic_fixture_invalid_side_blocked_17g,
    _synthetic_fixture_invalid_quantity_blocked_17g,
    _synthetic_fixture_stop_below_entry_blocked_17g,
    _synthetic_fixture_stop_quantity_mismatch_blocked_17g,
    _synthetic_fixture_data_quality_fail_blocked_17g,
    _synthetic_fixture_no_trade_fail_blocked_17g,
    _synthetic_fixture_deterministic_17g,
    _synthetic_fixture_read_only_invariant_17g,
    _synthetic_fixture_fresh_clone_17g,
    _synthetic_fixture_full_chain_17g,
    _phase17g_no_go,
    _generate_synthetic_ohlc_bars,
    _generate_proposal_packet,
    _review_proposal_dossier,
    _create_decision_record,
    _create_order_plan_draft,
)

REPO = Path(__file__).resolve().parent.parent
OPERATOR = REPO / "ibkr_operator.py"


# ── helpers ──────────────────────────────────────────────────────────────────

def _make_ready_sim():
    """Build a valid SIMULATION_READY dossier for tests."""
    plan = _build_ready_plan_draft()
    bars = _generate_synthetic_ohlc_bars("AAPL", 30)
    proposal = _generate_proposal_packet("AAPL", bars)
    dossier = _review_proposal_dossier(proposal)
    decision = _build_accepted_decision_record()
    decision["proposal_evidence_hash"] = proposal.get("evidence_hash", "")
    decision["dossier_evidence_hash"] = dossier.get("evidence_hash", "")
    return _create_simulated_preflight_dossier(plan, proposal, dossier, decision)


# ── Synthetic fixtures ───────────────────────────────────────────────────────

class TestSyntheticFixtures17G:

    def test_simulation_ready_passes(self):
        c = _synthetic_fixture_simulation_ready_17g()
        assert c["passed"], f"Simulation ready case failed: {c}"
        assert c["simulation_state"] == "SIMULATION_READY"
        assert c["executable"] is False
        assert c["broker_authorized"] is False
        assert c["broker_preflight_called"] is False

    def test_blocked_plan_blocked_passes(self):
        c = _synthetic_fixture_blocked_plan_blocked_17g()
        assert c["passed"], f"Blocked plan blocked case failed: {c}"
        assert c["simulation_state"] == "BLOCKED"

    def test_executable_false_passes(self):
        c = _synthetic_fixture_executable_false_17g()
        assert c["passed"], f"Executable false case failed: {c}"
        assert c["executable"] is False

    def test_broker_authorized_false_passes(self):
        c = _synthetic_fixture_broker_authorized_false_17g()
        assert c["passed"]
        assert c["broker_authorized"] is False

    def test_preflight_authorized_false_passes(self):
        c = _synthetic_fixture_preflight_authorized_false_17g()
        assert c["passed"]
        assert c["preflight_authorized"] is False

    def test_approval_authorized_false_passes(self):
        c = _synthetic_fixture_approval_authorized_false_17g()
        assert c["passed"]
        assert c["approval_authorized"] is False

    def test_submission_authorized_false_passes(self):
        c = _synthetic_fixture_submission_authorized_false_17g()
        assert c["passed"]
        assert c["submission_authorized"] is False

    def test_broker_preflight_called_false_passes(self):
        c = _synthetic_fixture_broker_preflight_called_false_17g()
        assert c["passed"]
        assert c["broker_preflight_called"] is False

    def test_hash_mismatch_blocked_passes(self):
        c = _synthetic_fixture_hash_mismatch_blocked_17g()
        assert c["passed"], f"Hash mismatch blocked case failed: {c}"
        assert c["simulation_state"] == "BLOCKED"

    def test_disallowed_instrument_blocked_passes(self):
        c = _synthetic_fixture_disallowed_instrument_blocked_17g()
        assert c["passed"]
        assert c["simulation_state"] == "BLOCKED"

    def test_invalid_side_blocked_passes(self):
        c = _synthetic_fixture_invalid_side_blocked_17g()
        assert c["passed"]
        assert c["simulation_state"] == "BLOCKED"

    def test_invalid_quantity_blocked_passes(self):
        c = _synthetic_fixture_invalid_quantity_blocked_17g()
        assert c["passed"]
        assert c["simulation_state"] == "BLOCKED"

    def test_stop_below_entry_blocked_passes(self):
        c = _synthetic_fixture_stop_below_entry_blocked_17g()
        assert c["passed"]
        assert c["simulation_state"] == "BLOCKED"

    def test_stop_quantity_mismatch_blocked_passes(self):
        c = _synthetic_fixture_stop_quantity_mismatch_blocked_17g()
        assert c["passed"]
        assert c["simulation_state"] == "BLOCKED"

    def test_data_quality_fail_blocked_passes(self):
        c = _synthetic_fixture_data_quality_fail_blocked_17g()
        assert c["passed"]
        assert c["simulation_state"] == "BLOCKED"

    def test_no_trade_fail_blocked_passes(self):
        c = _synthetic_fixture_no_trade_fail_blocked_17g()
        assert c["passed"]
        assert c["simulation_state"] == "BLOCKED"

    def test_deterministic_passes(self):
        c = _synthetic_fixture_deterministic_17g()
        assert c["passed"], f"Deterministic case failed: {c}"
        assert c["same_state"] is True
        assert c["same_hash"] is True

    def test_read_only_invariant_passes(self):
        c = _synthetic_fixture_read_only_invariant_17g()
        assert c["passed"]
        assert c["source_clean"] is True

    def test_fresh_clone_passes(self):
        c = _synthetic_fixture_fresh_clone_17g()
        assert c["passed"], f"Fresh clone case failed: {c}"
        assert c["no_home_refs"] is True
        assert c["runs"] is True

    def test_full_chain_passes(self):
        c = _synthetic_fixture_full_chain_17g()
        assert c["passed"], f"Full chain case failed: {c}"
        assert c["all_non_exec"] is True


# ── Simulation dossier unit tests ────────────────────────────────────────────

class TestSimulatedPreflightDossier:

    def test_dossier_has_all_required_fields(self):
        sim = _make_ready_sim()
        required = [
            "simulation_record_version", "simulation_state", "proposal_id",
            "proposal_evidence_hash", "dossier_evidence_hash",
            "decision_record_hash", "order_plan_hash", "strategy_version",
            "symbol", "side", "quantity",
            "simulated_entry", "simulated_stop", "simulated_stop_quantity",
            "simulated_time_in_force", "contract_assumptions",
            "market_data_assumptions", "data_quality_check",
            "instrument_check", "quantity_check", "protective_stop_check",
            "stop_quantity_check", "risk_envelope_check",
            "sizing_consistency_check", "no_trade_check",
            "evidence_chain_check", "simulated_gate_results",
            "blockers", "planning_scope", "executable",
            "broker_authorized", "preflight_authorized",
            "approval_authorized", "submission_authorized",
            "broker_preflight_called", "immutable_evidence_references",
            "deterministic_simulation_hash", "explicit_non_actions",
        ]
        for field in required:
            assert field in sim, f"Missing required field: {field}"

    def test_dossier_version(self):
        sim = _make_ready_sim()
        assert sim["simulation_record_version"] == "simulated-preflight-dossier-v1.0.0"

    def test_simulation_hash_valid(self):
        sim = _make_ready_sim()
        sh = sim.get("deterministic_simulation_hash", "")
        assert len(sh) == 64
        assert all(c in "0123456789abcdef" for c in sh)

    def test_simulation_deterministic(self):
        sim1 = _make_ready_sim()
        sim2 = _make_ready_sim()
        assert sim1["simulation_state"] == sim2["simulation_state"]
        assert sim1["deterministic_simulation_hash"] == sim2["deterministic_simulation_hash"]

    def test_ready_sim_always_non_executable(self):
        sim = _make_ready_sim()
        assert sim["executable"] is False
        assert sim["broker_authorized"] is False
        assert sim["preflight_authorized"] is False
        assert sim["approval_authorized"] is False
        assert sim["submission_authorized"] is False
        assert sim["broker_preflight_called"] is False
        assert sim["planning_scope"] == "PLANNING_ONLY"

    # ── Blocked plan → BLOCKED ───────────────────────────────────────────

    def test_blocked_plan_is_blocked(self):
        plan = _build_blocked_plan_draft()
        bars = _generate_synthetic_ohlc_bars("TSLA", 30)
        proposal = _generate_proposal_packet("TSLA", bars)
        sim = _create_simulated_preflight_dossier(plan, proposal)
        assert sim["simulation_state"] == "BLOCKED"
        assert any("plan_not_ready" in b.get("blocker", "")
                   for b in sim.get("blockers", []))

    # ── Hash mismatch → BLOCKED ──────────────────────────────────────────

    def test_proposal_hash_mismatch_is_blocked(self):
        plan = _build_ready_plan_draft()
        plan["proposal_evidence_hash"] = "0" * 64
        bars = _generate_synthetic_ohlc_bars("AAPL", 30)
        proposal = _generate_proposal_packet("AAPL", bars)
        sim = _create_simulated_preflight_dossier(plan, proposal)
        assert sim["simulation_state"] == "BLOCKED"
        assert any("hash_mismatch" in b.get("blocker", "")
                   for b in sim.get("blockers", []))

    # ── Disallowed instrument → BLOCKED ──────────────────────────────────

    def test_disallowed_symbol_is_blocked(self):
        plan = _build_ready_plan_draft()
        plan["symbol"] = "TSLA"
        bars = _generate_synthetic_ohlc_bars("TSLA", 30)
        proposal = _generate_proposal_packet("TSLA", bars)
        sim = _create_simulated_preflight_dossier(plan, proposal)
        assert sim["simulation_state"] == "BLOCKED"
        assert any("disallowed_instrument" in b.get("blocker", "")
                   for b in sim.get("blockers", []))

    # ── Invalid side / quantity ──────────────────────────────────────────

    def test_invalid_side_is_blocked(self):
        plan = _build_ready_plan_draft()
        plan["side"] = "SHORT"
        bars = _generate_synthetic_ohlc_bars("AAPL", 30)
        proposal = _generate_proposal_packet("AAPL", bars)
        sim = _create_simulated_preflight_dossier(plan, proposal)
        assert sim["simulation_state"] == "BLOCKED"
        assert any("invalid_side" in b.get("blocker", "")
                   for b in sim.get("blockers", []))

    def test_invalid_quantity_is_blocked(self):
        plan = _build_ready_plan_draft()
        plan["quantity"] = 0
        bars = _generate_synthetic_ohlc_bars("AAPL", 30)
        proposal = _generate_proposal_packet("AAPL", bars)
        sim = _create_simulated_preflight_dossier(plan, proposal)
        assert sim["simulation_state"] == "BLOCKED"
        assert any("invalid_quantity" in b.get("blocker", "")
                   for b in sim.get("blockers", []))

    # ── Stop protection ──────────────────────────────────────────────────

    def test_stop_above_entry_is_blocked(self):
        plan = _build_ready_plan_draft()
        plan["stop_exit_plan"]["initial_stop_loss"] = plan["entry_plan"]["entry_price"] + 10
        bars = _generate_synthetic_ohlc_bars("AAPL", 30)
        proposal = _generate_proposal_packet("AAPL", bars)
        sim = _create_simulated_preflight_dossier(plan, proposal)
        assert sim["simulation_state"] == "BLOCKED"
        assert any("protective_stop_failed" in b.get("blocker", "")
                   for b in sim.get("blockers", []))

    def test_stop_quantity_mismatch_is_blocked(self):
        plan = _build_ready_plan_draft()
        plan["bracket_simulation"]["child_stop_quantity"] = plan["quantity"] + 100
        bars = _generate_synthetic_ohlc_bars("AAPL", 30)
        proposal = _generate_proposal_packet("AAPL", bars)
        sim = _create_simulated_preflight_dossier(plan, proposal)
        assert sim["simulation_state"] == "BLOCKED"
        assert any("stop_quantity_mismatch" in b.get("blocker", "")
                   for b in sim.get("blockers", []))

    # ── Data quality / no-trade ──────────────────────────────────────────

    def test_data_quality_fail_is_blocked(self):
        plan = _build_ready_plan_draft()
        plan["data_quality_reference"]["overall"] = "FAIL"
        bars = _generate_synthetic_ohlc_bars("AAPL", 30)
        proposal = _generate_proposal_packet("AAPL", bars)
        sim = _create_simulated_preflight_dossier(plan, proposal)
        assert sim["simulation_state"] == "BLOCKED"
        assert any("data_quality_failed" in b.get("blocker", "")
                   for b in sim.get("blockers", []))

    def test_no_trade_fail_is_blocked(self):
        plan = _build_ready_plan_draft()
        plan["no_trade_checklist_reference"]["overall"] = "FAIL"
        bars = _generate_synthetic_ohlc_bars("AAPL", 30)
        proposal = _generate_proposal_packet("AAPL", bars)
        sim = _create_simulated_preflight_dossier(plan, proposal)
        assert sim["simulation_state"] == "BLOCKED"
        assert any("no_trade_checklist_failed" in b.get("blocker", "")
                   for b in sim.get("blockers", []))

    # ── Risk / sizing ────────────────────────────────────────────────────

    def test_risk_envelope_check_present(self):
        sim = _make_ready_sim()
        rc = sim.get("risk_envelope_check", {})
        assert "notional_ok" in rc
        assert "risk_ok" in rc
        assert "total_exposure_ok" in rc

    def test_sizing_consistency_check_present(self):
        sim = _make_ready_sim()
        sc = sim.get("sizing_consistency_check", {})
        assert sc.get("passed") is True
        assert sc.get("consistent") is True

    def test_evidence_chain_check_present(self):
        sim = _make_ready_sim()
        ec = sim.get("evidence_chain_check", {})
        assert ec.get("chain_intact") is True
        assert ec.get("passed") is True

    # ── Gates deterministic ──────────────────────────────────────────────

    def test_blocker_ordering_deterministic(self):
        plan = _build_ready_plan_draft()
        plan["symbol"] = "TSLA"
        plan["quantity"] = 0
        bars = _generate_synthetic_ohlc_bars("TSLA", 30)
        proposal = _generate_proposal_packet("TSLA", bars)
        sim1 = _create_simulated_preflight_dossier(plan, proposal)
        sim2 = _create_simulated_preflight_dossier(plan, proposal)
        b1 = [b.get("blocker") for b in sim1.get("blockers", [])]
        b2 = [b.get("blocker") for b in sim2.get("blockers", [])]
        assert b1 == b2, f"Blocker order changed: {b1} vs {b2}"

    # ── Explicit non-actions ─────────────────────────────────────────────

    def test_explicit_non_actions_present(self):
        sim = _make_ready_sim()
        na = sim.get("explicit_non_actions", [])
        assert len(na) > 0
        assert any("does not authorize" in s.lower() for s in na)
        assert any("simulation" in s.lower() for s in na)

    def test_immutable_evidence_references(self):
        sim = _make_ready_sim()
        ier = sim.get("immutable_evidence_references", {})
        assert "proposal_evidence_hash" in ier
        assert "dossier_evidence_hash" in ier
        assert "decision_record_hash" in ier
        assert "order_plan_hash" in ier

    # ── No broker identifiers ────────────────────────────────────────────

    def test_no_broker_identifiers(self):
        sim = _make_ready_sim()
        sim_json = json.dumps(sim, sort_keys=True)
        forbidden = ["permId", "order_id", "orderId", "approval_id",
                     "approvalId", "submission_id", "submissionId",
                     "exec_id", "execId", "conId", "broker_order_id"]
        for fid in forbidden:
            assert fid.lower() not in sim_json.lower(), \
                f"Forbidden broker identifier '{fid}' found in simulation dossier"

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

        assert plan["executable"] is False
        assert sim["executable"] is False
        assert sim["broker_authorized"] is False
        assert sim["preflight_authorized"] is False
        assert sim["approval_authorized"] is False
        assert sim["submission_authorized"] is False
        assert sim["broker_preflight_called"] is False
        assert sim["simulation_state"] == "SIMULATION_READY"

    # ── Simulated gates ──────────────────────────────────────────────────

    def test_simulated_gate_results_structured(self):
        sim = _make_ready_sim()
        gates = sim.get("simulated_gate_results", {})
        required_gates = [
            "contract_assumptions", "market_data_assumptions",
            "data_quality_check", "instrument_check", "quantity_check",
            "protective_stop_check", "stop_quantity_check",
            "risk_envelope_check", "sizing_consistency_check",
            "no_trade_check", "evidence_chain_check",
        ]
        for gate in required_gates:
            assert gate in gates, f"Missing gate: {gate}"
        assert gates.get("all_gates_passed") is True

    def test_contract_assumptions_labeled_simulated(self):
        sim = _make_ready_sim()
        ca = sim.get("contract_assumptions", {})
        assert "simulated" in ca.get("note", "").lower() or "not verified" in ca.get("note", "").lower()

    def test_market_data_labeled_simulated(self):
        sim = _make_ready_sim()
        mda = sim.get("market_data_assumptions", {})
        assert "no live" in mda.get("note", "").lower() or "simulated" in mda.get("note", "").lower()


# ── No forbidden access ──────────────────────────────────────────────────────

class TestSimulatedPreflightNoForbiddenAccess:

    def test_no_order_endpoints(self):
        import inspect
        src = inspect.getsource(_create_simulated_preflight_dossier)
        for pat in ["/order", "/connect", "h1_token", "H1_TOKEN", "X-H1-Token"]:
            assert pat not in src, f"Forbidden pattern: {pat}"

    def test_no_trade_window(self):
        import inspect
        src = inspect.getsource(_create_simulated_preflight_dossier)
        assert "ibkr-trade-window" not in src

    def test_no_sudo(self):
        import inspect
        src = inspect.getsource(_create_simulated_preflight_dossier)
        assert "sudo" not in src

    def test_no_home_ref(self):
        import inspect
        src = inspect.getsource(_create_simulated_preflight_dossier)
        assert "Path.home()" not in src
        assert "~/.openclaw" not in src
        assert "OPENCLAW_DIR" not in src


# ── Constants ────────────────────────────────────────────────────────────────

class TestPhase17GConstants:

    def test_diagnosis_dict_has_ready(self):
        assert _PHASE17G_DIAGNOSIS["ready"] == "level1_planning_only_preflight_simulation_dossier_ok"

    def test_diagnosis_dict_has_all_required_keys(self):
        required = [
            "ready", "simulation_ready_case_failed",
            "blocked_plan_blocked_case_failed",
            "executable_false_case_failed", "broker_authorized_false_case_failed",
            "preflight_authorized_false_case_failed", "approval_authorized_false_case_failed",
            "submission_authorized_false_case_failed", "broker_preflight_called_false_case_failed",
            "hash_mismatch_blocked_case_failed", "disallowed_instrument_blocked_case_failed",
            "invalid_side_blocked_case_failed", "invalid_quantity_blocked_case_failed",
            "stop_below_entry_case_failed", "stop_quantity_match_case_failed",
            "data_quality_fail_blocked_case_failed", "no_trade_fail_blocked_case_failed",
            "deterministic_case_failed", "read_only_invariant_case_failed",
            "fresh_clone_case_failed", "full_chain_case_failed", "unknown",
        ]
        for k in required:
            assert k in _PHASE17G_DIAGNOSIS, f"Missing diagnosis key: {k}"

    def test_explicit_non_actions_contains_protections(self):
        na = _PHASE17G_EXPLICIT_NON_ACTIONS
        assert any("/order" in s for s in na)
        assert any("h1_token" in s.lower() or "H1" in s for s in na)
        assert any("simulation" in s.lower() for s in na)
        assert any("/connect" in s for s in na)
        assert any("SIMULATION_READY" in s for s in na)

    def test_no_go_returns_correct_structure(self):
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        ts = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        result = _phase17g_no_go(
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

    def test_simulation_dossier_with_empty_home(self):
        with tempfile.TemporaryDirectory() as td:
            env = os.environ.copy()
            env["HOME"] = td
            cp = subprocess.run(
                [sys.executable, "-c", """
import sys
sys.path.insert(0, r'{repo}')
from ibkr_operator import (
    _create_simulated_preflight_dossier, _build_ready_plan_draft,
    _generate_synthetic_ohlc_bars, _generate_proposal_packet,
    _review_proposal_dossier, _build_accepted_decision_record,
)
plan = _build_ready_plan_draft()
bars = _generate_synthetic_ohlc_bars("AAPL", 30)
proposal = _generate_proposal_packet("AAPL", bars)
dossier = _review_proposal_dossier(proposal)
decision = _build_accepted_decision_record()
decision["proposal_evidence_hash"] = proposal.get("evidence_hash", "")
decision["dossier_evidence_hash"] = dossier.get("evidence_hash", "")
sim = _create_simulated_preflight_dossier(plan, proposal, dossier, decision)
assert sim["simulation_state"] == "SIMULATION_READY"
assert "deterministic_simulation_hash" in sim
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
)
bars = _generate_synthetic_ohlc_bars("AAPL", 30)
proposal = _generate_proposal_packet("AAPL", bars)
dossier = _review_proposal_dossier(proposal)
decision = _create_decision_record(dossier, decision="ACCEPT", reviewer="Chris",
                                   decision_reason="Full-chain 17G.")
decision["proposal_evidence_hash"] = proposal.get("evidence_hash", "")
decision["dossier_evidence_hash"] = dossier.get("evidence_hash", "")
plan = _create_order_plan_draft(decision, proposal, dossier)
sim = _create_simulated_preflight_dossier(plan, proposal, dossier, decision)
assert sim["simulation_state"] == "SIMULATION_READY"
assert sim["executable"] is False
assert sim["broker_preflight_called"] is False
print("OK")
""".replace("{repo}", str(REPO))],
                capture_output=True, text=True, timeout=30,
                env=env,
            )
            assert "OK" in cp.stdout, f"stderr: {cp.stderr}"


# ── CLI tests ────────────────────────────────────────────────────────────────

class TestPhase17GCLI:

    def test_help_succeeds(self):
        result = subprocess.run(
            [sys.executable, str(OPERATOR),
             "level1-planning-only-preflight-simulation-dossier-checkpoint", "--help"],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0, f"stderr: {result.stderr[:200]}"

    def test_alias_phase17g_works(self):
        result = subprocess.run(
            [sys.executable, str(OPERATOR),
             "phase17g-planning-only-preflight-simulation-dossier-checkpoint", "--help"],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0, f"stderr: {result.stderr[:200]}"

    def test_alias_preflight_simulation_works(self):
        result = subprocess.run(
            [sys.executable, str(OPERATOR),
             "preflight-simulation-dossier-checkpoint", "--help"],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0, f"stderr: {result.stderr[:200]}"

    def test_json_output_valid(self):
        result = subprocess.run(
            [sys.executable, str(OPERATOR),
             "level1-planning-only-preflight-simulation-dossier-checkpoint", "--json"],
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
             "level1-planning-only-preflight-simulation-dossier-checkpoint", "--json"],
            capture_output=True, text=True, timeout=60,
        )
        data = json.loads(result.stdout)
        required = [
            "checkpoint_id", "timestamp", "diagnosis", "severity",
            "no_order_endpoint_called", "no_preflight_endpoint_called",
            "no_approval_endpoint_called", "no_submit_endpoint_called",
            "no_h1_token_used", "no_connect_called", "no_broker_mutation",
            "simulation_ready_case_passed",
            "blocked_plan_blocked_case_passed",
            "executable_false_case_passed",
            "broker_preflight_called_false_case_passed",
            "hash_mismatch_blocked_case_passed",
            "data_quality_fail_blocked_case_passed",
            "no_trade_fail_blocked_case_passed",
            "deterministic_case_passed",
            "full_chain_case_passed",
        ]
        for field in required:
            assert field in data, f"Missing required field in CLI output: {field}"

    def test_canonical_simulation_dossier_present(self):
        result = subprocess.run(
            [sys.executable, str(OPERATOR),
             "level1-planning-only-preflight-simulation-dossier-checkpoint", "--json"],
            capture_output=True, text=True, timeout=60,
        )
        data = json.loads(result.stdout)
        if data.get("diagnosis") == _PHASE17G_DIAGNOSIS["ready"]:
            cs = data.get("canonical_simulation_dossier")
            assert cs is not None, "canonical_simulation_dossier must not be None when diagnosis is ready"
            assert "simulation_state" in cs
            assert "deterministic_simulation_hash" in cs
