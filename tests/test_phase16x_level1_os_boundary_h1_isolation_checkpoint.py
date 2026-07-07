"""Tests for Phase 16X — Level 1 OS Boundary & H1 Isolation Checkpoint."""

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ibkr_operator import (
    _PHASE16X_DIAGNOSIS,
    _PHASE16X_EXPLICIT_NON_ACTIONS,
    _synthetic_fixture_env_write_denied,
    _synthetic_fixture_rules_write_denied,
    _synthetic_fixture_guard_state_write_denied,
    _synthetic_fixture_h1_file_mode,
    _synthetic_fixture_raw_h1_leak_scan,
    _synthetic_fixture_concurrent_h1_isolation,
    _synthetic_fixture_read_only_invariant_16x,
    _phase16x_no_go,
    _verify_env_file_protection,
    _verify_rules_file_protection,
    _verify_guard_state_file_protection,
    _verify_h1_raw_token_protection,
    _verify_h1_hash_only_in_env,
    _verify_non_owner_write_denied,
    _verify_bridge_service_user,
)

REPO = Path(__file__).resolve().parent.parent
OPERATOR = REPO / "ibkr_operator.py"


# ===========================================================================
# Synthetic fixture tests — temp files only
# ===========================================================================


class TestSyntheticFixtures:
    """All seven synthetic fixtures must pass without touching real artifacts."""

    def test_synthetic_env_write_denied(self):
        c = _synthetic_fixture_env_write_denied()
        assert c["passed"], f"Env write denied failed: {c}"
        assert c["owner_only"] is True
        assert c["world_writable"] is False
        assert c["group_writable"] is False

    def test_synthetic_rules_write_denied(self):
        c = _synthetic_fixture_rules_write_denied()
        assert c["passed"], f"Rules write denied failed: {c}"
        assert c["owner_only"] is True
        assert c["world_writable"] is False

    def test_synthetic_guard_state_write_denied(self):
        c = _synthetic_fixture_guard_state_write_denied()
        assert c["passed"], f"Guard-state write denied failed: {c}"
        assert c["owner_only"] is True
        assert c["world_writable"] is False

    def test_synthetic_h1_file_mode(self):
        c = _synthetic_fixture_h1_file_mode()
        assert c["passed"], f"H1 file mode failed: {c}"
        assert c["is_600"] is True
        assert c["is_owner_only"] is True
        assert c["is_world_readable"] is False

    def test_synthetic_raw_h1_leak_scan_detects_leaks(self):
        """Case 5: synthetic leak scan detects planted leaks (pass = leaks found)."""
        c = _synthetic_fixture_raw_h1_leak_scan()
        assert c["passed"], f"Raw H1 leak scan failed: {c}"
        assert c["findings_count"] >= 2
        assert c["detection_works"] is True

    def test_synthetic_concurrent_h1_isolation(self):
        c = _synthetic_fixture_concurrent_h1_isolation()
        assert c["passed"], f"Concurrent H1 isolation failed: {c}"
        assert c["all_isolated"] is True
        assert c["no_h1_constructed"] is True
        assert c["no_authorization_bleed"] is True

    def test_synthetic_read_only_invariant(self):
        c = _synthetic_fixture_read_only_invariant_16x()
        assert c["passed"], f"Read-only invariant failed: {c}"
        assert c["source_clean"] is True


# ===========================================================================
# Phase 16X constants tests
# ===========================================================================


class TestPhase16XConstants:

    def test_diagnosis_dict_has_ready(self):
        assert _PHASE16X_DIAGNOSIS["ready"] == "level1_os_boundary_h1_isolation_ok"

    def test_diagnosis_dict_has_all_required_keys(self):
        required = [
            "ready", "git_worktree_dirty", "bridge_unreachable",
            "runtime_not_connected", "mode_not_paper", "read_only_not_true",
            "allow_orders_not_false", "endpoints_not_ok", "positions_not_flat",
            "guard_state_not_clean", "kpi_not_hold_system_locked",
            "env_file_not_protected", "h1_raw_token_not_protected",
            "h1_hash_not_only_in_env", "raw_h1_leak_detected",
            "non_owner_write_not_denied", "bridge_service_user_not_verified",
            "synthetic_env_write_denied_failed", "synthetic_rules_write_denied_failed",
            "synthetic_guard_state_write_denied_failed", "synthetic_h1_file_mode_failed",
            "synthetic_raw_h1_leak_scan_failed", "synthetic_concurrent_h1_isolation_failed",
            "synthetic_read_only_invariant_failed", "unknown",
        ]
        for k in required:
            assert k in _PHASE16X_DIAGNOSIS, f"Missing diagnosis key: {k}"

    def test_explicit_non_actions_contains_h1_protection(self):
        na = _PHASE16X_EXPLICIT_NON_ACTIONS
        assert any("raw H1 token" in s.lower() or "h1 token contents" in s.lower() for s in na)
        assert any("x-h1-token" in s.lower() for s in na)
        assert any("env" in s.lower() for s in na)
        assert any("guard-state" in s.lower() for s in na)


# ===========================================================================
# OS boundary helper tests
# ===========================================================================


class TestOSBoundaryHelpers:

    def test_env_file_protection_returns_structured(self):
        c = _verify_env_file_protection()
        assert "found" in c
        assert "protected" in c

    def test_rules_file_protection_returns_structured(self):
        c = _verify_rules_file_protection()
        assert "found" in c
        assert "protected" in c

    def test_guard_state_file_protection_returns_structured(self):
        c = _verify_guard_state_file_protection()
        assert "found" in c
        assert "protected" in c

    def test_h1_raw_token_protection_returns_structured(self):
        c = _verify_h1_raw_token_protection()
        assert "found" in c
        assert "protected" in c
        assert "contents_not_read" in c
        assert c["contents_not_read"] is True

    def test_h1_hash_only_in_env_returns_structured(self):
        c = _verify_h1_hash_only_in_env()
        assert "h1_hash_in_env" in c
        assert "raw_h1_in_env" in c

    def test_non_owner_write_denied(self):
        c = _verify_non_owner_write_denied()
        assert c["non_owner_write_denied"] is True
        assert c["method"] == "synthetic"

    def test_bridge_service_user_returns_structured(self):
        c = _verify_bridge_service_user()
        assert "service_user_verified" in c
        assert "service_user" in c


# ===========================================================================
# CLI tests
# ===========================================================================


class TestPhase16XCLI:

    def test_help_succeeds(self):
        result = subprocess.run(
            [sys.executable, str(OPERATOR),
             "level1-os-boundary-h1-isolation-checkpoint", "--help"],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0, f"stderr: {result.stderr[:200]}"
        assert "os-boundary" in result.stdout.lower() or "isolation" in result.stdout.lower()

    def test_json_output_valid(self):
        result = subprocess.run(
            [sys.executable, str(OPERATOR),
             "level1-os-boundary-h1-isolation-checkpoint", "--json"],
            capture_output=True, text=True, timeout=30,
        )
        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError:
            pytest.fail(f"Invalid JSON output: {result.stdout[:200]}")
        assert "diagnosis" in data
        assert "command" in data

    def test_alias_phase16x_works(self):
        result = subprocess.run(
            [sys.executable, str(OPERATOR),
             "phase16x-os-boundary-h1-isolation-checkpoint", "--json"],
            capture_output=True, text=True, timeout=30,
        )
        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError:
            pytest.fail(f"Invalid JSON: {result.stdout[:200]}")
        assert "diagnosis" in data

    def test_alias_level1_os_boundary_works(self):
        result = subprocess.run(
            [sys.executable, str(OPERATOR),
             "level1-os-boundary-h1-isolation", "--json"],
            capture_output=True, text=True, timeout=30,
        )
        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError:
            pytest.fail(f"Invalid JSON: {result.stdout[:200]}")
        assert "diagnosis" in data

    def test_alias_os_boundary_works(self):
        result = subprocess.run(
            [sys.executable, str(OPERATOR),
             "os-boundary-h1-isolation-checkpoint", "--json"],
            capture_output=True, text=True, timeout=30,
        )
        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError:
            pytest.fail(f"Invalid JSON: {result.stdout[:200]}")
        assert "diagnosis" in data

    def test_required_fields_present(self):
        result = subprocess.run(
            [sys.executable, str(OPERATOR),
             "level1-os-boundary-h1-isolation-checkpoint", "--json"],
            capture_output=True, text=True, timeout=30,
        )
        data = json.loads(result.stdout)
        required_fields = [
            "diagnosis", "severity", "git",
            "runtime_connected", "mode", "read_only", "allow_orders",
            "endpoints_ok", "positions_flat", "guard_state_clean",
            "kpi_hold_only_system_locked",
            "bridge_service_user_verified",
            "env_file_protected", "rules_file_protected",
            "guard_state_file_protected", "h1_raw_token_file_protected",
            "h1_hash_only_in_env", "raw_h1_not_leaked",
            "non_owner_write_denied", "h1_request_scope_isolated",
            "synthetic_env_write_denied_case_passed",
            "synthetic_rules_write_denied_case_passed",
            "synthetic_guard_state_write_denied_case_passed",
            "synthetic_h1_file_mode_case_passed",
            "synthetic_raw_h1_leak_scan_case_passed",
            "concurrent_h1_isolation_case_passed",
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


class TestPhase16XNoGo:

    def test_no_go_returns_correct_structure(self):
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        ts = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        result = _phase16x_no_go(
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
        result = _phase16x_no_go(
            "test-id", ts,
            {"branch": "test", "commit": "abc", "tag": "v1", "worktree_clean": False},
            "test_diagnosis", [],
        )
        assert result["no_order_endpoint_called"] is True
        assert result["no_broker_mutation"] is True
        assert result["no_h1_token_used"] is True
        assert result["h1_raw_token_file_protected"] is False


# ===========================================================================
# H1 Isolation tests
# ===========================================================================


class TestH1Isolation:

    def test_h1_token_file_not_read(self):
        """verify_h1_raw_token_protection must not read contents."""
        c = _verify_h1_raw_token_protection()
        assert c["contents_not_read"] is True
        assert "token_value" not in c

    def test_h1_hash_in_env_no_raw(self):
        """verify_h1_hash_only_in_env should find hash key, no raw token key."""
        c = _verify_h1_hash_only_in_env()
        if c.get("env_scanned"):
            assert c["h1_hash_in_env"] is True
            assert c["raw_h1_in_env"] is False
            assert "HASH" in c.get("h1_hash_key", "").upper()

    def test_h1_request_scope_isolated(self):
        """Concurrent H1 isolation synthetic test proves no cross-request bleed."""
        c = _synthetic_fixture_concurrent_h1_isolation()
        assert c["no_authorization_bleed"] is True
        assert c["dry_run"] is True
