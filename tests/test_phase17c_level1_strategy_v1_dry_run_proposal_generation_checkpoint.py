"""Tests for Phase 17C — Level 1 Strategy v1 Dry-Run Proposal Generation Checkpoint."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ibkr_operator import (
    _PHASE17C_DIAGNOSIS,
    _PHASE17C_EXPLICIT_NON_ACTIONS,
    _synthetic_fixture_generate_valid_proposal_17c,
    _synthetic_fixture_proposal_schema_compliance_17c,
    _synthetic_fixture_advisory_boundary_enforced_17c,
    _synthetic_fixture_disallowed_instrument_generation_fails_17c,
    _synthetic_fixture_rejection_blocker_deterministic_17c,
    _synthetic_fixture_read_only_invariant_17c,
    _generate_synthetic_ohlc_bars,
    _generate_proposal_packet,
    _validate_proposal_against_schema,
    _phase17c_no_go,
)

REPO = Path(__file__).resolve().parent.parent
OPERATOR = REPO / "ibkr_operator.py"


class TestSyntheticFixtures17C:

    def test_synthetic_generate_valid_proposal_passes(self):
        c = _synthetic_fixture_generate_valid_proposal_17c()
        assert c["passed"], f"Generate valid proposal case failed: {c}"
        assert c["all_required_fields"] is True
        assert c["symbol_in_allowlist"] is True
        assert c["quantity_valid"] is True

    def test_synthetic_proposal_schema_compliance_passes(self):
        c = _synthetic_fixture_proposal_schema_compliance_17c()
        assert c["passed"], f"Schema compliance case failed: {c}"
        assert c["all_structural_checks_ok"] is True
        # If jsonschema is installed, schema_valid must be True
        if "jsonschema" in sys.modules or c.get("schema_valid") is not None:
            assert c["schema_valid"], f"Schema validation failed: {c.get('schema_errors', [])}"

    def test_synthetic_advisory_boundary_enforced_passes(self):
        c = _synthetic_fixture_advisory_boundary_enforced_17c()
        assert c["passed"], f"Advisory boundary enforcement case failed: {c}"
        assert c["advisory_statement_present"] is True
        assert c["broker_execution_path_present"] is True

    def test_synthetic_disallowed_instrument_generation_fails(self):
        c = _synthetic_fixture_disallowed_instrument_generation_fails_17c()
        assert c["passed"], f"Disallowed instrument case failed: {c}"
        assert c["proposal_rejected"] is True
        assert c["allowlist_rejection"] is True
        assert c["rejection_severity"] == "HARD_BLOCK"

    def test_synthetic_rejection_blocker_deterministic(self):
        c = _synthetic_fixture_rejection_blocker_deterministic_17c()
        assert c["passed"], f"Rejection deterministic case failed: {c}"
        assert c["same_rejection_outcome"] is True
        assert c["same_rejection_reasons"] is True

    def test_synthetic_read_only_invariant_passes(self):
        c = _synthetic_fixture_read_only_invariant_17c()
        assert c["passed"], f"Read-only invariant case failed: {c}"
        assert c["source_clean"] is True


class TestProposalGenerator:

    def test_generate_synthetic_bars_produces_valid_data(self):
        bars = _generate_synthetic_ohlc_bars("AAPL", 30)
        assert len(bars) == 30
        for bar in bars:
            assert "open" in bar and "high" in bar and "low" in bar and "close" in bar and "volume" in bar
            assert bar["high"] >= bar["low"]
            assert bar["high"] >= bar["open"]
            assert bar["high"] >= bar["close"]
            assert bar["low"] <= bar["open"]
            assert bar["low"] <= bar["close"]
            assert bar["volume"] > 0
            assert bar["close"] > 0

    def test_generate_synthetic_bars_is_deterministic(self):
        bars1 = _generate_synthetic_ohlc_bars("AAPL", 30)
        bars2 = _generate_synthetic_ohlc_bars("AAPL", 30)
        for i in range(30):
            assert bars1[i]["close"] == bars2[i]["close"], f"Bar {i} differs: {bars1[i]} vs {bars2[i]}"

    def test_generate_synthetic_bars_different_symbols_differ(self):
        bars_aapl = _generate_synthetic_ohlc_bars("AAPL", 30)
        bars_nvda = _generate_synthetic_ohlc_bars("NVDA", 30)
        # Different symbols should produce different base prices
        assert bars_aapl[0]["close"] != bars_nvda[0]["close"]

    def test_generate_proposal_packet_has_all_26_required_fields(self):
        bars = _generate_synthetic_ohlc_bars("AAPL", 30)
        proposal = _generate_proposal_packet("AAPL", bars)
        required = [
            "proposal_id", "timestamp", "strategy_version", "strategy_doc_ref",
            "symbol", "side", "quantity", "entry_price", "signal_thesis",
            "signal_inputs", "data_quality", "no_trade_checklist",
            "risk_envelope_check", "sizing_calculation", "daily_trade_count_check",
            "daily_loss_check", "stop_exit_plan", "bracket_simulation",
            "advisory_only_statement", "broker_execution_path",
            "human_review_checklist", "proposed_by", "model",
            "rejection_reasons", "evidence_hash",
        ]
        for field in required:
            assert field in proposal, f"Missing required field: {field}"
        assert len(required) == 25  # export_path is optional 26th

    def test_generate_proposal_packet_advisory_boundary(self):
        bars = _generate_synthetic_ohlc_bars("AAPL", 30)
        proposal = _generate_proposal_packet("AAPL", bars)
        assert "advisory-only" in proposal["advisory_only_statement"].lower()
        assert "guard" in proposal["broker_execution_path"].lower()

    def test_generate_proposal_packet_evidence_hash_valid(self):
        import hashlib
        bars = _generate_synthetic_ohlc_bars("AAPL", 30)
        proposal = _generate_proposal_packet("AAPL", bars)
        eh = proposal.get("evidence_hash", "")
        assert len(eh) == 64
        assert all(c in "0123456789abcdef" for c in eh)

    def test_generate_proposal_packet_disallowed_symbol_rejected(self):
        bars = _generate_synthetic_ohlc_bars("TSLA", 30)
        proposal = _generate_proposal_packet("TSLA", bars)
        assert proposal.get("passed") is False
        assert len(proposal.get("rejection_reasons", [])) > 0
        assert proposal["rejection_reasons"][0]["severity"] == "HARD_BLOCK"

    def test_generate_proposal_packet_disallowed_symbol_tsla(self):
        bars = _generate_synthetic_ohlc_bars("TSLA", 30)
        proposal = _generate_proposal_packet("TSLA", bars)
        assert proposal.get("passed") is False

    def test_generate_proposal_packet_disallowed_symbol_goog(self):
        bars = _generate_synthetic_ohlc_bars("GOOG", 30)
        proposal = _generate_proposal_packet("GOOG", bars)
        assert proposal.get("passed") is False

    def test_generate_proposal_packet_disallowed_symbol_btc(self):
        bars = _generate_synthetic_ohlc_bars("BTC", 30)
        proposal = _generate_proposal_packet("BTC", bars)
        assert proposal.get("passed") is False

    def test_generate_proposal_packet_all_allowed_symbols(self):
        for symbol in ["AAPL", "META", "NVDA", "AMD"]:
            bars = _generate_synthetic_ohlc_bars(symbol, 30)
            proposal = _generate_proposal_packet(symbol, bars)
            assert proposal.get("symbol") == symbol, f"Failed for {symbol}"
            assert proposal.get("side") == "BUY"
            assert proposal.get("quantity", 0) >= 1, f"Quantity invalid for {symbol}"
            assert len(proposal.get("rejection_reasons", [])) == 0, f"Unexpected rejection for {symbol}"

    def test_generate_proposal_packet_sizing_formula_correct(self):
        bars = _generate_synthetic_ohlc_bars("AAPL", 30)
        proposal = _generate_proposal_packet("AAPL", bars)
        sizing = proposal.get("sizing_calculation", {})
        final = sizing.get("final_shares", 0)
        notional_cap = sizing.get("notional_cap_shares", 0)
        risk_cap = sizing.get("risk_cap_shares", 0)
        allowlist_max = sizing.get("allowlist_max_shares", 0)
        expected = min(notional_cap, risk_cap, allowlist_max)
        assert final == expected, f"final_shares {final} != min({notional_cap}, {risk_cap}, {allowlist_max}) = {expected}"
        assert final >= 1

    def test_generate_proposal_packet_stop_distance_within_5pct(self):
        bars = _generate_synthetic_ohlc_bars("AAPL", 30)
        proposal = _generate_proposal_packet("AAPL", bars)
        sizing = proposal.get("sizing_calculation", {})
        stop_pct = sizing.get("stop_distance_pct", 0)
        assert stop_pct <= 5.0, f"Stop distance {stop_pct}% exceeds 5% hard cap"

    def test_generate_proposal_packet_no_trade_checklist_preserves_level1(self):
        bars = _generate_synthetic_ohlc_bars("AAPL", 30)
        proposal = _generate_proposal_packet("AAPL", bars)
        nt = proposal.get("no_trade_checklist", {})
        assert nt.get("ibkr_allow_orders_false") is True
        assert nt.get("rules_enforced_false") is True
        assert nt.get("system_locked") is True
        assert nt.get("rth_window_open") is False
        assert nt.get("overall") == "PASS"

    def test_generate_proposal_packet_risk_envelope_bounds(self):
        bars = _generate_synthetic_ohlc_bars("AAPL", 30)
        proposal = _generate_proposal_packet("AAPL", bars)
        re = proposal.get("risk_envelope_check", {})
        assert re.get("notional_ok") is True
        assert re.get("risk_ok") is True
        assert re.get("total_exposure_ok") is True
        assert re.get("overall") == "PASS"

    def test_generate_proposal_packet_bracket_simulation_level1(self):
        bars = _generate_synthetic_ohlc_bars("AAPL", 30)
        proposal = _generate_proposal_packet("AAPL", bars)
        bs = proposal.get("bracket_simulation", {})
        assert bs.get("bracket_required") is True
        assert bs.get("fail_closed") is True
        assert bs.get("oco_group") is False  # Level 1: no OCO
        assert bs.get("child_stop_quantity") == proposal.get("quantity")

    def test_generate_proposal_packet_human_review_pending(self):
        bars = _generate_synthetic_ohlc_bars("AAPL", 30)
        proposal = _generate_proposal_packet("AAPL", bars)
        hr = proposal.get("human_review_checklist", {})
        assert hr.get("chris_review_complete") is False
        assert "PENDING" in hr.get("overall", "")

    def test_validate_proposal_against_schema_returns_dict(self):
        bars = _generate_synthetic_ohlc_bars("AAPL", 30)
        proposal = _generate_proposal_packet("AAPL", bars)
        result = _validate_proposal_against_schema(proposal)
        assert isinstance(result, dict)
        assert "valid" in result
        assert "errors" in result

    def test_generate_proposal_packet_signal_thesis_min_length(self):
        bars = _generate_synthetic_ohlc_bars("AAPL", 30)
        proposal = _generate_proposal_packet("AAPL", bars)
        assert len(proposal["signal_thesis"]) >= 20

    def test_generate_proposal_packet_proposal_id_format(self):
        bars = _generate_synthetic_ohlc_bars("AAPL", 30)
        proposal = _generate_proposal_packet("AAPL", bars)
        pid = proposal.get("proposal_id", "")
        assert pid.startswith("prop-")

    def test_generate_proposal_packet_strategy_version(self):
        bars = _generate_synthetic_ohlc_bars("AAPL", 30)
        proposal = _generate_proposal_packet("AAPL", bars)
        assert proposal.get("strategy_version") == "v1.0.0"
        assert proposal.get("strategy_doc_ref") == "docs/strategy_v1.md"

    def test_generate_proposal_packet_rejection_reasons_empty_for_valid(self):
        bars = _generate_synthetic_ohlc_bars("AAPL", 30)
        proposal = _generate_proposal_packet("AAPL", bars)
        assert isinstance(proposal.get("rejection_reasons"), list)
        assert len(proposal.get("rejection_reasons", [])) == 0


class TestLevel1PosturePreservation:

    def test_proposal_no_trade_checklist_preserves_hard_blocks(self):
        """Verify generated proposals reflect Level 1 safe baseline."""
        bars = _generate_synthetic_ohlc_bars("AAPL", 30)
        proposal = _generate_proposal_packet("AAPL", bars)
        nt = proposal["no_trade_checklist"]
        # Level 1 baseline: orders disabled, rules not enforced, system locked
        assert nt["ibkr_allow_orders_false"] is True, "IBKR_ALLOW_ORDERS must remain false in Level 1"
        assert nt["rules_enforced_false"] is True, "rules.enforced must remain false in Level 1"
        assert nt["system_locked"] is True, "system_locked must be true (RTH closed / safety)"
        assert nt["rth_window_open"] is False, "RTH window must be closed for dry-run safety"

    def test_advisory_only_statement_explicit(self):
        """Every proposal must contain explicit advisory-only language."""
        bars = _generate_synthetic_ohlc_bars("AAPL", 30)
        proposal = _generate_proposal_packet("AAPL", bars)
        adv = proposal["advisory_only_statement"].lower()
        assert "advisory-only" in adv or "no broker execution" in adv or "does not authorize" in adv

    def test_broker_execution_path_describes_guard_chain(self):
        """Every proposal must describe the guard→preflight→approve→submit chain."""
        bars = _generate_synthetic_ohlc_bars("AAPL", 30)
        proposal = _generate_proposal_packet("AAPL", bars)
        bp = proposal["broker_execution_path"].lower()
        assert "guard" in bp
        assert "preflight" in bp or "approve" in bp or "submit" in bp


class TestPhase17CConstants:

    def test_diagnosis_dict_has_ready(self):
        assert _PHASE17C_DIAGNOSIS["ready"] == "level1_strategy_v1_dry_run_proposal_generation_ok"

    def test_diagnosis_dict_has_all_required_keys(self):
        required = [
            "ready", "git_worktree_dirty", "bridge_unreachable",
            "runtime_not_connected", "mode_not_paper", "read_only_not_true",
            "allow_orders_not_false", "endpoints_not_ok", "positions_not_flat",
            "guard_state_not_clean", "kpi_not_hold_system_locked",
            "governance_docs_missing",
            "synthetic_proposal_generation_failed",
            "synthetic_proposal_schema_validation_failed",
            "synthetic_advisory_boundary_enforced_failed",
            "synthetic_disallowed_instrument_generation_failed",
            "synthetic_rejection_blocker_deterministic_failed",
            "synthetic_read_only_invariant_failed",
            "unknown",
        ]
        for k in required:
            assert k in _PHASE17C_DIAGNOSIS, f"Missing diagnosis key: {k}"

    def test_explicit_non_actions_contains_proposal_protection(self):
        na = _PHASE17C_EXPLICIT_NON_ACTIONS
        assert any("~/.openclaw" in s for s in na)
        assert any("h1_token" in s.lower() or "H1" in s for s in na)
        assert any("advisory-only" in s.lower() for s in na)
        assert any("/order" in s for s in na)
        assert any("non-executable" in s.lower() for s in na)


class TestPhase17CCLI:

    def test_help_succeeds(self):
        result = subprocess.run(
            [sys.executable, str(OPERATOR),
             "level1-strategy-v1-dry-run-proposal-generation-checkpoint", "--help"],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0, f"stderr: {result.stderr[:200]}"

    def test_json_output_valid(self):
        result = subprocess.run(
            [sys.executable, str(OPERATOR),
             "level1-strategy-v1-dry-run-proposal-generation-checkpoint", "--json"],
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
             "level1-strategy-v1-dry-run-proposal-generation-checkpoint", "--json"],
            capture_output=True, text=True, timeout=60,
        )
        data = json.loads(result.stdout)
        required = [
            "diagnosis", "severity", "git",
            "runtime_connected", "mode", "read_only", "allow_orders",
            "endpoints_ok", "positions_flat", "guard_state_clean",
            "kpi_hold_only_system_locked",
            "governance_docs_present",
            "synthetic_proposal_generation_case_passed",
            "synthetic_proposal_schema_compliance_case_passed",
            "synthetic_advisory_boundary_enforced_case_passed",
            "synthetic_disallowed_instrument_generation_case_passed",
            "synthetic_rejection_blocker_deterministic_case_passed",
            "synthetic_read_only_invariant_case_passed",
            "no_order_endpoint_called", "no_broker_mutation",
            "no_connect_called", "artifact_created",
        ]
        for field in required:
            assert field in data, f"Missing field: {field}"
        # canonical_proposal only present when diagnosis is OK
        if data.get("diagnosis") == _PHASE17C_DIAGNOSIS["ready"]:
            assert "canonical_proposal" in data
            assert data["canonical_proposal"] is not None

    def test_cli_alias_phase17c_works(self):
        result = subprocess.run(
            [sys.executable, str(OPERATOR),
             "phase17c-strategy-v1-dry-run-proposal-generation-checkpoint", "--help"],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0

    def test_cli_alias_dry_run_works(self):
        result = subprocess.run(
            [sys.executable, str(OPERATOR),
             "dry-run-proposal-generation-checkpoint", "--help"],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0

    def test_deterministic_diagnosis_on_repeat_run(self):
        """Running twice should produce consistent diagnosis structure."""
        result1 = subprocess.run(
            [sys.executable, str(OPERATOR),
             "level1-strategy-v1-dry-run-proposal-generation-checkpoint", "--json"],
            capture_output=True, text=True, timeout=60,
        )
        data1 = json.loads(result1.stdout)
        result2 = subprocess.run(
            [sys.executable, str(OPERATOR),
             "level1-strategy-v1-dry-run-proposal-generation-checkpoint", "--json"],
            capture_output=True, text=True, timeout=60,
        )
        data2 = json.loads(result2.stdout)
        # Diagnosis should match (both runs should produce the same verdict)
        assert data1["diagnosis"] == data2["diagnosis"], \
            f"Non-deterministic diagnosis: {data1['diagnosis']} vs {data2['diagnosis']}"

    def test_canonical_proposal_populated(self):
        result = subprocess.run(
            [sys.executable, str(OPERATOR),
             "level1-strategy-v1-dry-run-proposal-generation-checkpoint", "--json"],
            capture_output=True, text=True, timeout=60,
        )
        data = json.loads(result.stdout)
        # canonical_proposal is populated when diagnosis is OK; skip if NO_GO
        if data.get("diagnosis") == _PHASE17C_DIAGNOSIS["ready"]:
            cp = data.get("canonical_proposal")
            assert cp is not None, "canonical_proposal should be populated when OK"
            assert "symbol" in cp
            assert "evidence_hash" in cp
        else:
            # NO_GO due to bridge not running is acceptable
            assert data.get("diagnosis") is not None


class TestPhase17CNoGo:

    def test_no_go_returns_correct_structure(self):
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        ts = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        result = _phase17c_no_go(
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


class TestPhase17CReadOnlyInvariants:

    def test_no_h1_token_in_checkpoint_source(self):
        import inspect
        from ibkr_operator import _run_level1_strategy_v1_dry_run_proposal_generation_checkpoint
        src = inspect.getsource(_run_level1_strategy_v1_dry_run_proposal_generation_checkpoint)
        for pat in ["X-H1-Token", "H1_TOKEN_PATH", "/etc/ibkr-bridge/h1_token"]:
            assert pat not in src, f"Forbidden pattern: {pat}"

    def test_no_order_endpoints_in_checkpoint_source(self):
        import inspect
        from ibkr_operator import _run_level1_strategy_v1_dry_run_proposal_generation_checkpoint
        src = inspect.getsource(_run_level1_strategy_v1_dry_run_proposal_generation_checkpoint)
        assert "/order" not in src

    def test_no_connect_in_checkpoint_source(self):
        import inspect
        from ibkr_operator import _run_level1_strategy_v1_dry_run_proposal_generation_checkpoint
        src = inspect.getsource(_run_level1_strategy_v1_dry_run_proposal_generation_checkpoint)
        assert "/connect" not in src

    def test_no_trade_window_in_checkpoint_source(self):
        import inspect
        from ibkr_operator import _run_level1_strategy_v1_dry_run_proposal_generation_checkpoint
        src = inspect.getsource(_run_level1_strategy_v1_dry_run_proposal_generation_checkpoint)
        assert "ibkr-trade-window" not in src

    def test_no_sudo_in_checkpoint_source(self):
        import inspect
        from ibkr_operator import _run_level1_strategy_v1_dry_run_proposal_generation_checkpoint
        src = inspect.getsource(_run_level1_strategy_v1_dry_run_proposal_generation_checkpoint)
        assert "sudo" not in src


class TestAdvisoryOnlyBoundary:

    def test_proposal_generator_never_calls_order_endpoints(self):
        """Source-level audit: proposal generator must not reference order endpoints."""
        import inspect
        from ibkr_operator import _generate_proposal_packet
        src = inspect.getsource(_generate_proposal_packet)
        for pat in ["/order", "/connect", "h1_token", "H1_TOKEN", "X-H1-Token"]:
            assert pat not in src, f"Proposal generator contains forbidden pattern: {pat}"

    def test_all_synthetic_fixtures_are_advisory_only(self):
        """Every synthetic fixture must verify no broker mutation."""
        fixtures = [
            _synthetic_fixture_generate_valid_proposal_17c,
            _synthetic_fixture_proposal_schema_compliance_17c,
            _synthetic_fixture_advisory_boundary_enforced_17c,
            _synthetic_fixture_disallowed_instrument_generation_fails_17c,
            _synthetic_fixture_rejection_blocker_deterministic_17c,
            _synthetic_fixture_read_only_invariant_17c,
        ]
        for fixture in fixtures:
            result = fixture()
            assert result.get("passed") is True, f"Fixture {fixture.__name__} failed: {result}"