"""Tests for Phase 17A — Level 1 Strategy v1 Governance Checkpoint."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ibkr_operator import (
    _PHASE17A_DIAGNOSIS,
    _PHASE17A_EXPLICIT_NON_ACTIONS,
    _synthetic_fixture_valid_strategy_doc,
    _synthetic_fixture_missing_risk_envelope,
    _synthetic_fixture_missing_no_trade_rules,
    _synthetic_fixture_missing_advisory_boundary,
    _synthetic_fixture_missing_anti_overfit,
    _synthetic_fixture_missing_bracket_requirement,
    _synthetic_fixture_read_only_invariant_17a,
    _phase17a_no_go,
    _verify_strategy_doc_present,
    _STRATEGY_V1_PATH,
)

REPO = Path(__file__).resolve().parent.parent
OPERATOR = REPO / "ibkr_operator.py"


# ===========================================================================
# Synthetic fixture tests — temp files only, never real artifacts
# ===========================================================================


class TestSyntheticFixtures17A:
    """All seven synthetic fixtures must pass without touching real artifacts."""

    def test_synthetic_valid_strategy_doc_passes(self):
        """Case 1: valid strategy_v1 document passes governance checks."""
        c = _synthetic_fixture_valid_strategy_doc()
        assert c["passed"], f"Valid strategy doc case failed: {c}"
        assert c["has_advisory_boundary"] is True
        assert c["has_risk_envelope"] is True
        assert c["has_no_trade_rules"] is True
        assert c["has_anti_overfit"] is True
        assert c["has_bracket_requirement"] is True

    def test_synthetic_missing_risk_envelope_fails(self):
        """Case 2: missing risk envelope should fail."""
        c = _synthetic_fixture_missing_risk_envelope()
        assert c["passed"], f"Missing risk envelope case failed: {c}"
        assert c["risk_envelope_missing"] is True

    def test_synthetic_missing_no_trade_rules_fails(self):
        """Case 3: missing no-trade rules should fail."""
        c = _synthetic_fixture_missing_no_trade_rules()
        assert c["passed"], f"Missing no-trade rules case failed: {c}"
        assert c["no_trade_rules_missing"] is True

    def test_synthetic_missing_advisory_boundary_fails(self):
        """Case 4: missing advisory-only boundary should fail."""
        c = _synthetic_fixture_missing_advisory_boundary()
        assert c["passed"], f"Missing advisory boundary case failed: {c}"
        assert c["advisory_boundary_missing"] is True

    def test_synthetic_missing_anti_overfit_fails(self):
        """Case 5: missing anti-overfit checklist should fail."""
        c = _synthetic_fixture_missing_anti_overfit()
        assert c["passed"], f"Missing anti-overfit case failed: {c}"
        assert c["anti_overfit_missing"] is True

    def test_synthetic_missing_bracket_requirement_fails(self):
        """Case 6: missing broker-side bracket requirement should fail."""
        c = _synthetic_fixture_missing_bracket_requirement()
        assert c["passed"], f"Missing bracket requirement case failed: {c}"
        assert c["bracket_requirement_missing"] is True

    def test_synthetic_read_only_invariant_passes(self):
        """Case 7: checkpoint never calls /order*, H1, trade-window, or mutation paths."""
        c = _synthetic_fixture_read_only_invariant_17a()
        assert c["passed"], f"Read-only invariant case failed: {c}"
        assert c["source_clean"] is True


# ===========================================================================
# Phase 17A specific constants tests
# ===========================================================================


class TestPhase17AConstants:

    def test_diagnosis_dict_has_ready(self):
        assert _PHASE17A_DIAGNOSIS["ready"] == "level1_strategy_v1_governance_ok"

    def test_diagnosis_dict_has_all_required_keys(self):
        required = [
            "ready", "git_worktree_dirty", "bridge_unreachable",
            "runtime_not_connected", "mode_not_paper", "read_only_not_true",
            "allow_orders_not_false", "endpoints_not_ok", "positions_not_flat",
            "guard_state_not_clean", "kpi_not_hold_system_locked",
            "strategy_doc_missing", "risk_envelope_missing",
            "no_trade_rules_missing", "advisory_boundary_missing",
            "anti_overfit_section_missing", "bracket_requirement_missing",
            "strategy_version_missing", "allowed_instruments_missing",
            "excluded_instruments_missing", "signal_inputs_missing",
            "data_quality_missing", "sizing_rule_missing",
            "daily_trade_limit_missing", "daily_loss_limit_missing",
            "stop_exit_policy_missing", "review_checklist_missing",
            "broker_execution_boundary_missing",
            "synthetic_valid_strategy_doc_failed",
            "synthetic_missing_risk_envelope_failed",
            "synthetic_missing_no_trade_rules_failed",
            "synthetic_missing_advisory_boundary_failed",
            "synthetic_missing_anti_overfit_failed",
            "synthetic_missing_bracket_requirement_failed",
            "synthetic_read_only_invariant_failed",
            "unknown",
        ]
        for k in required:
            assert k in _PHASE17A_DIAGNOSIS, f"Missing diagnosis key: {k}"

    def test_explicit_non_actions_contains_governance_protection(self):
        na = _PHASE17A_EXPLICIT_NON_ACTIONS
        assert any("~/.openclaw" in s for s in na)
        assert any("/etc/ibkr-bridge/h1_token" in s for s in na)
        assert any("strategy" in s.lower() for s in na)


# ===========================================================================
# Strategy doc verification tests
# ===========================================================================


class TestStrategyDocVerification:

    def test_strategy_doc_present_returns_structured(self):
        c = _verify_strategy_doc_present()
        assert "strategy_doc_present" in c
        assert "strategy_version_declared" in c

    def test_strategy_doc_exists(self):
        """The real docs/strategy_v1.md file exists."""
        assert _STRATEGY_V1_PATH.exists(), f"Missing strategy doc: {_STRATEGY_V1_PATH}"

    def test_strategy_doc_has_version(self):
        """Strategy doc declares version v1.0.0."""
        content = _STRATEGY_V1_PATH.read_text()
        assert "v1.0.0" in content or "strategy-v1-" in content, "Strategy doc missing version"

    def test_strategy_doc_has_advisory_boundary(self):
        """Strategy doc declares advisory-only boundary."""
        content = _STRATEGY_V1_PATH.read_text()
        assert "Advisory-Only" in content or "advisory-only" in content.lower(), "Missing advisory boundary"

    def test_strategy_doc_has_risk_envelope(self):
        """Strategy doc has risk envelope section."""
        content = _STRATEGY_V1_PATH.read_text()
        assert "Risk Envelope" in content or "risk envelope" in content.lower(), "Missing risk envelope"

    def test_strategy_doc_has_no_trade_rules(self):
        """Strategy doc has no-trade conditions."""
        content = _STRATEGY_V1_PATH.read_text()
        assert "No-Trade" in content or "no-trade" in content.lower(), "Missing no-trade rules"

    def test_strategy_doc_has_allowed_instruments(self):
        """Strategy doc has allowed instruments section."""
        content = _STRATEGY_V1_PATH.read_text()
        assert "Allowed Instruments" in content or "allowed instrument" in content.lower(), "Missing allowed instruments"

    def test_strategy_doc_has_excluded_instruments(self):
        """Strategy doc has excluded instruments section."""
        content = _STRATEGY_V1_PATH.read_text()
        assert "Excluded Instruments" in content or "excluded instrument" in content.lower(), "Missing excluded instruments"

    def test_strategy_doc_has_signal_inputs(self):
        """Strategy doc has signal inputs section."""
        content = _STRATEGY_V1_PATH.read_text()
        assert "Signal Inputs" in content or "signal" in content.lower(), "Missing signal inputs"

    def test_strategy_doc_has_data_quality(self):
        """Strategy doc has data quality requirements."""
        content = _STRATEGY_V1_PATH.read_text()
        assert "Data Quality" in content or "data quality" in content.lower(), "Missing data quality rules"

    def test_strategy_doc_has_sizing_rule(self):
        """Strategy doc has position sizing rule."""
        content = _STRATEGY_V1_PATH.read_text()
        assert "Sizing" in content and "Position" in content, "Missing sizing rule"

    def test_strategy_doc_has_daily_trade_limit(self):
        """Strategy doc has daily trade limit."""
        content = _STRATEGY_V1_PATH.read_text()
        assert "Daily" in content and ("trade" in content.lower() or "Trades" in content), "Missing daily trade limit"

    def test_strategy_doc_has_daily_loss_limit(self):
        """Strategy doc has daily loss limit."""
        content = _STRATEGY_V1_PATH.read_text()
        assert "loss halt" in content.lower() or "Daily Loss" in content or "daily loss" in content.lower(), "Missing daily loss limit"

    def test_strategy_doc_has_stop_exit_policy(self):
        """Strategy doc has stop/exit policy."""
        content = _STRATEGY_V1_PATH.read_text()
        assert "Stop" in content and ("Exit" in content or "exit" in content.lower()), "Missing stop/exit policy"

    def test_strategy_doc_has_bracket_requirement(self):
        """Strategy doc has broker-side bracket requirement."""
        content = _STRATEGY_V1_PATH.read_text()
        assert "Broker-Side Bracket" in content or "broker-side" in content.lower() or "bracket" in content.lower(), "Missing bracket requirement"

    def test_strategy_doc_has_review_checklist(self):
        """Strategy doc has review checklist."""
        content = _STRATEGY_V1_PATH.read_text()
        assert "Review Checklist" in content or "review checklist" in content.lower(), "Missing review checklist"

    def test_strategy_doc_has_anti_overfit(self):
        """Strategy doc has anti-overfit checklist."""
        content = _STRATEGY_V1_PATH.read_text()
        assert "Anti-Overfit" in content or "anti-overfit" in content.lower(), "Missing anti-overfit checklist"

    def test_strategy_doc_has_broker_execution_boundary(self):
        """Strategy doc declares broker execution boundary."""
        content = _STRATEGY_V1_PATH.read_text()
        assert "Broker Execution" in content or "broker execution" in content.lower() or "only path" in content.lower(), "Missing broker execution boundary"


# ===========================================================================
# CLI tests
# ===========================================================================


class TestPhase17ACLI:

    def test_help_succeeds(self):
        result = subprocess.run(
            [sys.executable, str(OPERATOR),
             "level1-strategy-v1-governance-checkpoint", "--help"],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0, f"stderr: {result.stderr[:200]}"
        assert "strategy" in result.stdout.lower() or "governance" in result.stdout.lower()

    def test_json_output_valid(self):
        """--json produces valid JSON with diagnosis field."""
        result = subprocess.run(
            [sys.executable, str(OPERATOR),
             "level1-strategy-v1-governance-checkpoint", "--json"],
            capture_output=True, text=True, timeout=60,
        )
        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError:
            pytest.fail(f"Invalid JSON output: {result.stdout[:200]}")
        assert "diagnosis" in data
        assert "command" in data

    def test_alias_phase17a_works(self):
        """Alias 'phase17a-strategy-v1-governance-checkpoint' works."""
        result = subprocess.run(
            [sys.executable, str(OPERATOR),
             "phase17a-strategy-v1-governance-checkpoint", "--json"],
            capture_output=True, text=True, timeout=60,
        )
        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError:
            pytest.fail(f"Invalid JSON: {result.stdout[:200]}")
        assert "diagnosis" in data

    def test_alias_strategy_v1_works(self):
        """Alias 'strategy-v1-governance-checkpoint' works."""
        result = subprocess.run(
            [sys.executable, str(OPERATOR),
             "strategy-v1-governance-checkpoint", "--json"],
            capture_output=True, text=True, timeout=60,
        )
        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError:
            pytest.fail(f"Invalid JSON: {result.stdout[:200]}")
        assert "diagnosis" in data

    def test_required_fields_present(self):
        """All required output fields are present."""
        result = subprocess.run(
            [sys.executable, str(OPERATOR),
             "level1-strategy-v1-governance-checkpoint", "--json"],
            capture_output=True, text=True, timeout=60,
        )
        data = json.loads(result.stdout)
        required_fields = [
            "diagnosis", "severity", "git",
            "runtime_connected", "mode", "read_only", "allow_orders",
            "endpoints_ok", "positions_flat", "guard_state_clean",
            "kpi_hold_only_system_locked",
            "strategy_doc_present",
            "strategy_version_declared",
            "allowed_instruments_declared",
            "excluded_instruments_declared",
            "signal_inputs_declared",
            "data_quality_rules_declared",
            "no_trade_rules_declared",
            "risk_envelope_declared",
            "sizing_rule_declared",
            "daily_trade_limit_declared",
            "daily_loss_limit_declared",
            "stop_exit_policy_declared",
            "broker_side_bracket_requirement_declared",
            "review_checklist_declared",
            "anti_overfit_checklist_declared",
            "advisory_only_boundary_declared",
            "broker_execution_boundary_declared",
            "synthetic_valid_strategy_doc_case_passed",
            "synthetic_missing_risk_envelope_case_passed",
            "synthetic_missing_no_trade_rules_case_passed",
            "synthetic_missing_advisory_boundary_case_passed",
            "synthetic_missing_anti_overfit_case_passed",
            "synthetic_missing_bracket_requirement_case_passed",
            "synthetic_read_only_invariant_case_passed",
            "no_order_endpoint_called", "no_preflight_endpoint_called",
            "no_approval_endpoint_called", "no_submit_endpoint_called",
            "no_h1_token_used", "no_trade_window_helper_called",
            "no_broker_mutation", "artifact_created",
        ]
        for field in required_fields:
            assert field in data, f"Missing field: {field}"


# ===========================================================================
# NO_GO helper tests
# ===========================================================================


class TestPhase17ANoGo:

    def test_no_go_returns_correct_structure(self):
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        ts = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        result = _phase17a_no_go(
            "test-id", ts,
            {"branch": "test", "commit": "abc", "tag": "v1", "worktree_clean": False},
            "test_diagnosis",
            ["action 1", "action 2"],
        )
        assert result["diagnosis"] == "test_diagnosis"
        assert result["severity"] == "NO_GO"
        assert result["operator_action_required"] is True
        assert len(result["suggested_operator_actions"]) == 2

    def test_no_go_defaults_all_mutation_flags_false(self):
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        ts = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        result = _phase17a_no_go(
            "test-id", ts,
            {"branch": "test", "commit": "abc", "tag": "v1", "worktree_clean": False},
            "test_diagnosis", [],
        )
        assert result["no_order_endpoint_called"] is True
        assert result["no_broker_mutation"] is True
        assert result["no_h1_token_used"] is True
        assert result["strategy_doc_present"] is False


# ===========================================================================
# Read-only invariant tests
# ===========================================================================


class TestPhase17AReadOnlyInvariants:

    def test_no_h1_token_in_checkpoint_source(self):
        """Phase 17A run function must not USE h1_token."""
        import inspect
        from ibkr_operator import _run_level1_strategy_v1_governance_checkpoint
        src = inspect.getsource(_run_level1_strategy_v1_governance_checkpoint)
        forbidden_patterns = [
            "X-H1-Token",
            "h1_token_file",
            'open("/etc/ibkr-bridge/h1_token"',
            "H1_TOKEN_PATH",
            "os.environ.get('H1'",
            'os.environ.get("H1"',
        ]
        for pat in forbidden_patterns:
            assert pat not in src, f"Forbidden H1 pattern found: {pat}"

    def test_no_order_endpoints_in_checkpoint_source(self):
        """Phase 17A run function must not reference /order endpoints."""
        import inspect
        from ibkr_operator import _run_level1_strategy_v1_governance_checkpoint
        src = inspect.getsource(_run_level1_strategy_v1_governance_checkpoint)
        assert "/order" not in src
        assert "/order/preflight" not in src
        assert "/order/approve" not in src
        assert "/order/submit" not in src

    def test_no_trade_window_in_checkpoint_source(self):
        """Phase 17A run function must not reference ibkr-trade-window."""
        import inspect
        from ibkr_operator import _run_level1_strategy_v1_governance_checkpoint
        src = inspect.getsource(_run_level1_strategy_v1_governance_checkpoint)
        assert "ibkr-trade-window" not in src
