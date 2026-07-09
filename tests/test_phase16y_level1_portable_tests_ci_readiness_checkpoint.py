"""Tests for Phase 16Y — Level 1 Portable Tests & CI Readiness Checkpoint."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ibkr_operator import (
    _PHASE16Y_DIAGNOSIS,
    _PHASE16Y_EXPLICIT_NON_ACTIONS,
    _synthetic_fixture_home_isolation,
    _synthetic_fixture_no_h1_file_access,
    _synthetic_fixture_acceptance_marker,
    _synthetic_fixture_ci_workflow,
    _synthetic_fixture_ci_install_plan,
    _synthetic_fixture_read_only_invariant_16y,
    _phase16y_no_go,
    _verify_ci_workflow,
    _verify_ci_command_documented,
    _verify_fresh_clone_command,
    _verify_pure_tests_discovery,
    _verify_acceptance_tests_separated,
    _verify_pure_tests_home_isolated,
    _verify_pure_tests_no_h1_access,
    _verify_pure_tests_no_ibkr_gateway,
    _verify_pure_tests_no_systemd,
)

REPO = Path(__file__).resolve().parent.parent
OPERATOR = REPO / "ibkr_operator.py"


# ===========================================================================
# Synthetic fixture tests — temp files only, never real artifacts
# ===========================================================================


class TestSyntheticFixtures:
    """All six synthetic fixtures must pass without touching real artifacts."""

    def test_synthetic_home_isolation_passes(self):
        """Case 1: pure tests run with HOME set to temp dir."""
        c = _synthetic_fixture_home_isolation()
        assert c["passed"], f"Home isolation case failed: {c}"
        assert c["temp_home_used"] is True
        assert c["no_real_openclaw_access"] is True

    def test_synthetic_no_h1_file_access_passes(self):
        """Case 2: pure tests must not read /etc/ibkr-bridge/h1_token."""
        c = _synthetic_fixture_no_h1_file_access()
        assert c["passed"], f"No H1 file access case failed: {c}"
        assert c["h1_blocked"] is True
        assert c["contents_not_read"] is True
        assert c["synthetic_guard_active"] is True

    def test_synthetic_acceptance_marker_passes(self):
        """Case 3: acceptance tests discoverable via marker, not required in CI."""
        c = _synthetic_fixture_acceptance_marker()
        assert c["passed"], f"Acceptance marker case failed: {c}"
        assert c["acceptance_tests_discoverable"] is True
        assert c["pure_tests_found"] is True
        assert c["marker_separation_confirmed"] is True

    def test_synthetic_ci_workflow_passes(self):
        """Case 4: CI workflow file is syntactically valid."""
        c = _synthetic_fixture_ci_workflow()
        assert c["passed"], f"CI workflow case failed: {c}"
        assert c["workflow_file_present"] is True
        assert c["workflow_syntax_valid"] is True

    def test_synthetic_ci_install_plan_passes(self):
        """Case 4b: CI install plan can be generated."""
        c = _synthetic_fixture_ci_install_plan()
        assert c["passed"], f"CI install plan case failed: {c}"
        assert c["install_plan_present"] is True
        plan = c.get("plan", {})
        assert len(plan.get("steps", [])) >= 3

    def test_synthetic_read_only_invariant(self):
        """Case 5: checkpoint never calls /order*, H1, trade-window, mutation."""
        c = _synthetic_fixture_read_only_invariant_16y()
        assert c["passed"], f"Read-only invariant case failed: {c}"
        assert c["source_clean"] is True


# ===========================================================================
# Phase 16Y specific constants tests
# ===========================================================================


class TestPhase16YConstants:

    def test_diagnosis_dict_has_ready(self):
        assert _PHASE16Y_DIAGNOSIS["ready"] == "level1_portable_tests_ci_readiness_ok"

    def test_diagnosis_dict_has_all_required_keys(self):
        required = [
            "ready", "git_worktree_dirty", "bridge_unreachable",
            "runtime_not_connected", "mode_not_paper", "read_only_not_true",
            "allow_orders_not_false", "endpoints_not_ok", "positions_not_flat",
            "guard_state_not_clean", "kpi_not_hold_system_locked",
            "pure_tests_not_discovered", "host_acceptance_not_separated",
            "pure_tests_home_not_isolated", "pure_tests_real_openclaw_access",
            "pure_tests_h1_file_access", "pure_tests_ibkr_gateway_required",
            "pure_tests_systemd_required", "no_ci_workflow_or_install_plan",
            "ci_command_not_documented", "fresh_clone_command_not_documented",
            "synthetic_home_isolation_case_failed",
            "synthetic_no_h1_file_access_case_failed",
            "synthetic_acceptance_marker_case_failed",
            "synthetic_ci_workflow_case_failed",
            "synthetic_read_only_invariant_case_failed",
            "unknown",
        ]
        for k in required:
            assert k in _PHASE16Y_DIAGNOSIS, f"Missing diagnosis key: {k}"

    def test_explicit_non_actions_contains_ci_protection(self):
        na = _PHASE16Y_EXPLICIT_NON_ACTIONS
        assert any("~/.openclaw" in s for s in na)
        assert any("/etc/ibkr-bridge/h1_token" in s for s in na)
        assert any("portable" in s.lower() for s in na)


# ===========================================================================
# CI Readiness helper tests
# ===========================================================================


class TestCIReadinessHelpers:

    def test_ci_workflow_check_returns_structured(self):
        c = _verify_ci_workflow()
        assert "found" in c
        # Either workflow found or install plan present
        assert c["found"] or c.get("install_plan_present", False)

    def test_ci_command_documented_returns_structured(self):
        c = _verify_ci_command_documented()
        assert "ci_command_found" in c

    def test_fresh_clone_command_returns_structured(self):
        c = _verify_fresh_clone_command()
        assert "fresh_clone_command_found" in c

    def test_pure_tests_discovery_returns_structured(self):
        c = _verify_pure_tests_discovery()
        assert "pure_tests_discovered" in c
        assert "test_count" in c

    def test_acceptance_tests_separated_returns_structured(self):
        c = _verify_acceptance_tests_separated()
        assert "host_acceptance_separated" in c

    def test_pure_tests_home_isolated_returns_structured(self):
        c = _verify_pure_tests_home_isolated()
        assert "pure_tests_home_isolated" in c

    def test_pure_tests_no_h1_access_returns_structured(self):
        c = _verify_pure_tests_no_h1_access()
        assert "pure_tests_no_h1_access" in c

    def test_pure_tests_no_ibkr_gateway_returns_structured(self):
        c = _verify_pure_tests_no_ibkr_gateway()
        assert "pure_tests_no_ibkr_gateway" in c

    def test_pure_tests_no_systemd_returns_structured(self):
        c = _verify_pure_tests_no_systemd()
        assert "pure_tests_no_systemd" in c


# ===========================================================================
# CLI tests
# ===========================================================================


class TestPhase16YCLI:

    def test_help_succeeds(self):
        result = subprocess.run(
            [sys.executable, str(OPERATOR),
             "level1-portable-tests-ci-readiness-checkpoint", "--help"],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0, f"stderr: {result.stderr[:200]}"
        assert "portable" in result.stdout.lower() or "ci" in result.stdout.lower()

    def test_json_output_valid(self):
        """--json produces valid JSON with diagnosis field."""
        result = subprocess.run(
            [sys.executable, str(OPERATOR),
             "level1-portable-tests-ci-readiness-checkpoint", "--json"],
            capture_output=True, text=True, timeout=30,
        )
        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError:
            pytest.fail(f"Invalid JSON output: {result.stdout[:200]}")
        assert "diagnosis" in data
        assert "command" in data

    def test_alias_phase16y_works(self):
        """Alias 'phase16y-portable-tests-ci-readiness-checkpoint' works."""
        result = subprocess.run(
            [sys.executable, str(OPERATOR),
             "phase16y-portable-tests-ci-readiness-checkpoint", "--json"],
            capture_output=True, text=True, timeout=30,
        )
        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError:
            pytest.fail(f"Invalid JSON: {result.stdout[:200]}")
        assert "diagnosis" in data

    def test_alias_level1_portable_tests_works(self):
        """Alias 'level1-portable-tests-ci-readiness' works."""
        result = subprocess.run(
            [sys.executable, str(OPERATOR),
             "level1-portable-tests-ci-readiness", "--json"],
            capture_output=True, text=True, timeout=30,
        )
        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError:
            pytest.fail(f"Invalid JSON: {result.stdout[:200]}")
        assert "diagnosis" in data

    def test_alias_portable_tests_works(self):
        """Alias 'portable-tests-ci-readiness-checkpoint' works."""
        result = subprocess.run(
            [sys.executable, str(OPERATOR),
             "portable-tests-ci-readiness-checkpoint", "--json"],
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
             "level1-portable-tests-ci-readiness-checkpoint", "--json"],
            capture_output=True, text=True, timeout=30,
        )
        data = json.loads(result.stdout)
        required_fields = [
            "diagnosis", "severity", "git",
            "runtime_connected", "mode", "read_only", "allow_orders",
            "endpoints_ok", "positions_flat", "guard_state_clean",
            "kpi_hold_only_system_locked",
            "pure_tests_discovered",
            "host_acceptance_tests_separated",
            "pure_tests_home_isolated",
            "pure_tests_no_real_openclaw_access",
            "pure_tests_no_h1_file_access",
            "pure_tests_no_ibkr_gateway_required",
            "pure_tests_no_systemd_required",
            "github_actions_workflow_present",
            "ci_install_plan_present",
            "ci_command_documented",
            "fresh_clone_unit_command_documented",
            "synthetic_home_isolation_case_passed",
            "synthetic_no_h1_file_access_case_passed",
            "synthetic_acceptance_marker_case_passed",
            "synthetic_ci_workflow_case_passed",
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


class TestPhase16YNoGo:

    def test_no_go_returns_correct_structure(self):
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        ts = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        result = _phase16y_no_go(
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
        result = _phase16y_no_go(
            "test-id", ts,
            {"branch": "test", "commit": "abc", "tag": "v1", "worktree_clean": False},
            "test_diagnosis", [],
        )
        assert result["no_order_endpoint_called"] is True
        assert result["no_broker_mutation"] is True
        assert result["no_h1_token_used"] is True
        assert result["pure_tests_discovered"] is False


# ===========================================================================
# Read-only invariant tests
# ===========================================================================


class TestPortableTestsReadOnlyInvariants:

    def test_no_h1_token_in_checkpoint_source(self):
        """Phase 16Y run function must not USE h1_token (boundary checks are OK)."""
        import inspect
        from ibkr_operator import _run_level1_portable_tests_ci_readiness_checkpoint
        src = inspect.getsource(_run_level1_portable_tests_ci_readiness_checkpoint)
        # Allow references in function names and field names (boundary checking)
        # but forbid actual H1 token construction or reading
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
        """Phase 16Y run function must not reference /order endpoints."""
        import inspect
        from ibkr_operator import _run_level1_portable_tests_ci_readiness_checkpoint
        src = inspect.getsource(_run_level1_portable_tests_ci_readiness_checkpoint)
        assert "/order" not in src
        assert "/order/preflight" not in src
        assert "/order/approve" not in src
        assert "/order/submit" not in src
