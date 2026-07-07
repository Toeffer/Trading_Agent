"""Tests for Phase 16W — Level 1 Scheduled Heartbeat & Alerting Resilience Checkpoint."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

# Ensure the ibkr-bridge root is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ibkr_operator import (
    _PHASE16W_DIAGNOSIS,
    _synthetic_fixture_fresh_heartbeat,
    _synthetic_fixture_stale_heartbeat,
    _synthetic_fixture_missing_timer,
    _synthetic_fixture_dry_run_alert,
    _synthetic_fixture_read_only_invariant,
    _phase16w_no_go,
    _HEARTBEAT_ENDPOINTS,
    _FORBIDDEN_HEARTBEAT_SUBSTRINGS,
)

REPO = Path(__file__).resolve().parent.parent
OPERATOR = REPO / "ibkr_operator.py"


# ===========================================================================
# Synthetic fixture tests — temp files only, never real heartbeat artifacts
# ===========================================================================


class TestSyntheticFixtures:
    """All five synthetic fixtures must pass without touching real artifacts."""

    def test_synthetic_fresh_heartbeat_passes(self):
        """Case 1: fresh heartbeat artifact (age < 86400s) passes."""
        c = _synthetic_fixture_fresh_heartbeat()
        assert c["passed"], f"Fresh heartbeat case failed: {c}"
        assert c["heartbeat_present"] is True
        assert c["heartbeat_fresh"] is True
        assert c["heartbeat_age_seconds"] is not None
        assert c["heartbeat_age_seconds"] < c["threshold_seconds"]

    def test_synthetic_stale_heartbeat_fails(self):
        """Case 2: stale heartbeat artifact (age > 86400s) fails."""
        c = _synthetic_fixture_stale_heartbeat()
        assert c["passed"], f"Stale heartbeat case failed: {c}"
        assert c["heartbeat_present"] is True
        assert c["heartbeat_fresh"] is False
        assert c["heartbeat_stale"] is True
        assert c["heartbeat_age_seconds"] is not None
        assert c["heartbeat_age_seconds"] > c["threshold_seconds"]

    def test_synthetic_missing_timer_fails(self):
        """Case 3: missing systemd timer unit correctly identified."""
        c = _synthetic_fixture_missing_timer()
        assert c["passed"], f"Missing timer case failed: {c}"
        assert c["timer_found"] is False
        assert c["timer_not_found"] is True

    def test_synthetic_dry_run_alert(self):
        """Case 4: simulated stop_breach alert produces dry-run event."""
        c = _synthetic_fixture_dry_run_alert()
        assert c["passed"], f"Dry-run alert case failed: {c}"
        assert c["all_required_fields_present"] is True
        assert c["is_dry_run"] is True
        assert c["no_broker_mutation"] is True
        alert = c["simulated_alert"]
        assert alert["dry_run"] is True
        assert alert["alert_type"] == "stop_breach"
        assert "alert_channel_config" in alert

    def test_synthetic_read_only_invariant(self):
        """Case 5: heartbeat never calls /order*, H1, trade-window, mutation."""
        c = _synthetic_fixture_read_only_invariant()
        assert c["passed"], f"Read-only invariant case failed: {c}"
        assert c["heartbeat_endpoints_read_only"] is True
        assert c["forbidden_substrings_complete"] is True
        assert c["no_h1_in_heartbeat_source"] is True
        # Service may not be checked if not found, but that's ok
        if c.get("service_checked"):
            assert c["service_read_only_flags"] is True


# ===========================================================================
# Phase 16W specific constants tests
# ===========================================================================


class TestPhase16WConstants:

    def test_diagnosis_dict_has_ready(self):
        assert _PHASE16W_DIAGNOSIS["ready"] == "level1_scheduled_heartbeat_alerting_resilience_ok"

    def test_diagnosis_dict_has_all_required_keys(self):
        required = [
            "ready", "git_worktree_dirty", "bridge_unreachable",
            "runtime_not_connected", "mode_not_paper", "read_only_not_true",
            "allow_orders_not_false", "endpoints_not_ok", "positions_not_flat",
            "guard_state_not_clean", "kpi_not_hold_system_locked",
            "heartbeat_missing", "heartbeat_stale",
            "scheduled_timer_missing", "scheduled_timer_not_enabled",
            "synthetic_fresh_heartbeat_failed", "synthetic_stale_heartbeat_failed",
            "synthetic_missing_timer_failed", "synthetic_dry_run_alert_failed",
            "synthetic_read_only_invariant_failed", "unknown",
        ]
        for k in required:
            assert k in _PHASE16W_DIAGNOSIS, f"Missing diagnosis key: {k}"

    def test_heartbeat_endpoints_are_read_only(self):
        """All heartbeat endpoints must be read-only (no /order, /connect)."""
        forbidden = ["/connect", "/order/approve", "/order/submit",
                     "/order/preflight", "/order"]
        for ep in _HEARTBEAT_ENDPOINTS:
            for fs in forbidden:
                assert fs not in ep, f"Forbidden '{fs}' in endpoint '{ep}'"

    def test_forbidden_heartbeat_substrings_complete(self):
        """_FORBIDDEN_HEARTBEAT_SUBSTRINGS must include all mutation paths."""
        required = ["/connect", "/order/approve", "/order/submit",
                    "/order/preflight", "/order"]
        for fs in required:
            assert fs in _FORBIDDEN_HEARTBEAT_SUBSTRINGS, \
                f"Missing '{fs}' from forbidden heartbeat substrings"


# ===========================================================================
# CLI tests
# ===========================================================================


class TestPhase16WCLI:

    def test_help_succeeds(self):
        result = subprocess.run(
            [sys.executable, str(OPERATOR),
             "level1-scheduled-heartbeat-alerting-resilience-checkpoint", "--help"],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0, f"stderr: {result.stderr[:200]}"
        assert "heartbeat" in result.stdout.lower()

    def test_json_output_valid(self):
        """--json produces valid JSON with diagnosis field."""
        result = subprocess.run(
            [sys.executable, str(OPERATOR),
             "level1-scheduled-heartbeat-alerting-resilience-checkpoint", "--json"],
            capture_output=True, text=True, timeout=30,
        )
        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError:
            pytest.fail(f"Invalid JSON output: {result.stdout[:200]}")
        assert "diagnosis" in data
        assert "command" in data

    def test_alias_level1_heartbeat_alerting_resilience_works(self):
        """Alias 'level1-heartbeat-alerting-resilience' works."""
        result = subprocess.run(
            [sys.executable, str(OPERATOR),
             "level1-heartbeat-alerting-resilience", "--json"],
            capture_output=True, text=True, timeout=30,
        )
        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError:
            pytest.fail(f"Invalid JSON: {result.stdout[:200]}")
        assert "diagnosis" in data

    def test_alias_scheduled_heartbeat_alerting_works(self):
        """Alias 'scheduled-heartbeat-alerting-resilience-checkpoint' works."""
        result = subprocess.run(
            [sys.executable, str(OPERATOR),
             "scheduled-heartbeat-alerting-resilience-checkpoint", "--json"],
            capture_output=True, text=True, timeout=30,
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
             "level1-scheduled-heartbeat-alerting-resilience-checkpoint", "--json"],
            capture_output=True, text=True, timeout=30,
        )
        data = json.loads(result.stdout)
        required_fields = [
            "diagnosis", "severity", "git",
            "runtime_connected", "mode", "read_only", "allow_orders",
            "endpoints_ok", "positions_flat", "guard_state_clean",
            "kpi_hold_only_system_locked",
            "heartbeat_present", "heartbeat_fresh", "heartbeat_age_seconds",
            "scheduled_timer_found", "scheduled_timer_enabled",
            "timer_install_plan_present",
            "heartbeat_command_read_only", "monitor_alert_check_read_only",
            "alert_channel_configured", "alert_channel_dry_run_verified",
            "synthetic_fresh_heartbeat_case_passed",
            "synthetic_stale_heartbeat_case_passed",
            "synthetic_missing_timer_case_passed",
            "synthetic_dry_run_alert_case_passed",
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


class TestPhase16WNoGo:

    def test_no_go_returns_correct_structure(self):
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        ts = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        result = _phase16w_no_go(
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
        result = _phase16w_no_go(
            "test-id", ts,
            {"branch": "test", "commit": "abc", "tag": "v1", "worktree_clean": False},
            "test_diagnosis", [],
        )
        assert result["no_order_endpoint_called"] is True
        assert result["no_broker_mutation"] is True
        assert result["no_h1_token_used"] is True
        assert result["heartbeat_present"] is False


# ===========================================================================
# Read-only invariant tests
# ===========================================================================


class TestHeartbeatReadOnlyInvariants:

    def test_heartbeat_endpoints_exclude_forbidden(self):
        """All _HEARTBEAT_ENDPOINTS are GET only."""
        import inspect
        from ibkr_operator import _run_heartbeat
        hb_src = inspect.getsource(_run_heartbeat)
        # Must not contain mutation patterns
        assert "urllib.request.Request" in hb_src
        assert "method=\"GET\"" in hb_src or "method='GET'" in hb_src
        assert "POST" not in hb_src
        assert "PUT" not in hb_src
        assert "DELETE" not in hb_src

    def test_no_h1_in_endpoints(self):
        """No endpoint touching H1 token."""
        for ep in _HEARTBEAT_ENDPOINTS:
            assert "h1" not in ep.lower()
            assert "token" not in ep.lower()
