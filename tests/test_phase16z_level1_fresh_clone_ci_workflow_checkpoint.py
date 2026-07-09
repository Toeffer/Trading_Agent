"""Tests for Phase 16Z — Level 1 Fresh-Clone CI Workflow Checkpoint."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ibkr_operator import (
    _PHASE16Z_DIAGNOSIS,
    _PHASE16Z_EXPLICIT_NON_ACTIONS,
    _synthetic_fixture_ci_workflow_16z,
    _synthetic_fixture_marker_exclusion,
    _synthetic_fixture_temp_home_ci,
    _synthetic_fixture_fresh_clone,
    _synthetic_fixture_no_real_openclaw_16z,
    _synthetic_fixture_no_h1_file_access_16z,
    _synthetic_fixture_read_only_invariant_16z,
    _phase16z_no_go,
    _verify_github_actions_workflow_16z,
    _verify_ci_excludes_acceptance_16z,
    _verify_ci_command_exits_zero_16z,
    _verify_fresh_clone_command_16z,
    _verify_pure_tests_home_isolated_16z,
    _verify_pure_tests_no_h1_access_16z,
    _verify_pure_tests_no_ibkr_gateway_16z,
    _verify_pure_tests_no_systemd_16z,
)

REPO = Path(__file__).resolve().parent.parent
OPERATOR = REPO / "ibkr_operator.py"


# ===========================================================================
# Synthetic fixture tests — temp files only, never real artifacts
# ===========================================================================


class TestSyntheticFixtures16Z:
    """All seven synthetic fixtures must pass without touching real artifacts."""

    def test_synthetic_ci_workflow_parse_passes(self):
        """Case 1: .github/workflows/ci.yml exists and is parseable."""
        c = _synthetic_fixture_ci_workflow_16z()
        assert c["passed"], f"CI workflow parse case failed: {c}"
        assert c["workflow_file_present"] is True
        assert c["workflow_parseable"] is True

    def test_synthetic_marker_exclusion_passes(self):
        """Case 2: CI workflow excludes integration/live/acceptance markers."""
        c = _synthetic_fixture_marker_exclusion()
        assert c["passed"], f"Marker exclusion case failed: {c}"
        assert c["excludes_integration"] is True
        assert c["excludes_live"] is True
        assert c["excludes_acceptance"] is True

    def test_synthetic_temp_home_ci_passes(self):
        """Case 3: CI command succeeds with HOME set to temp dir."""
        c = _synthetic_fixture_temp_home_ci()
        assert c["passed"], f"Temp HOME CI case failed: {c}"
        assert c["home_isolated"] is True
        assert c["no_real_openclaw_in_temp_home"] is True

    def test_synthetic_fresh_clone_passes(self):
        """Case 4: fresh-clone / temp-copy command is documented."""
        c = _synthetic_fixture_fresh_clone()
        assert c["passed"], f"Fresh clone case failed: {c}"
        assert c["ci_script_present"] is True
        assert c["requirements_present"] is True

    def test_synthetic_no_real_openclaw_passes(self):
        """Case 5: CI/pure tests fail if they attempt to read real ~/.openclaw."""
        c = _synthetic_fixture_no_real_openclaw_16z()
        assert c["passed"], f"No real openclaw case failed: {c}"
        assert c["real_openclaw_isolated"] is True
        assert c["temp_home_used"] is True

    def test_synthetic_no_h1_file_access_passes(self):
        """Case 6: CI/pure tests fail if they attempt to read /etc/ibkr-bridge/h1_token."""
        c = _synthetic_fixture_no_h1_file_access_16z()
        assert c["passed"], f"No H1 file access case failed: {c}"
        assert c["h1_blocked"] is True
        assert c["contents_not_read"] is True
        assert c["synthetic_guard_active"] is True

    def test_synthetic_read_only_invariant_passes(self):
        """Case 7: checkpoint never calls /order*, H1, trade-window, or mutation paths."""
        c = _synthetic_fixture_read_only_invariant_16z()
        assert c["passed"], f"Read-only invariant case failed: {c}"
        assert c["source_clean"] is True


# ===========================================================================
# Phase 16Z specific constants tests
# ===========================================================================


class TestPhase16ZConstants:

    def test_diagnosis_dict_has_ready(self):
        assert _PHASE16Z_DIAGNOSIS["ready"] == "level1_fresh_clone_ci_workflow_ok"

    def test_diagnosis_dict_has_all_required_keys(self):
        required = [
            "ready", "git_worktree_dirty", "bridge_unreachable",
            "runtime_not_connected", "mode_not_paper", "read_only_not_true",
            "allow_orders_not_false", "endpoints_not_ok", "positions_not_flat",
            "guard_state_not_clean", "kpi_not_hold_system_locked",
            "no_github_actions_workflow", "github_actions_workflow_invalid",
            "ci_command_not_exits_zero", "fresh_clone_command_not_exits_zero",
            "ci_acceptance_tests_not_excluded",
            "pure_tests_home_not_isolated", "pure_tests_real_openclaw_access",
            "pure_tests_h1_file_access", "pure_tests_ibkr_gateway_required",
            "pure_tests_systemd_required", "host_acceptance_tests_in_ci",
            "synthetic_workflow_parse_failed",
            "synthetic_marker_exclusion_failed",
            "synthetic_temp_home_ci_failed",
            "synthetic_fresh_clone_failed",
            "synthetic_no_real_openclaw_failed",
            "synthetic_no_h1_file_access_failed",
            "synthetic_read_only_invariant_failed",
            "unknown",
        ]
        for k in required:
            assert k in _PHASE16Z_DIAGNOSIS, f"Missing diagnosis key: {k}"

    def test_explicit_non_actions_contains_ci_protection(self):
        na = _PHASE16Z_EXPLICIT_NON_ACTIONS
        assert any("~/.openclaw" in s for s in na)
        assert any("/etc/ibkr-bridge/h1_token" in s for s in na)
        assert any("fresh-clone" in s.lower() for s in na)


# ===========================================================================
# CI / Fresh-Clone verification helper tests
# ===========================================================================


class TestCIWorkflowHelpers16Z:

    def test_github_actions_workflow_check_returns_structured(self):
        c = _verify_github_actions_workflow_16z()
        assert "github_actions_workflow_present" in c
        assert "github_actions_workflow_valid" in c

    def test_ci_excludes_acceptance_returns_structured(self):
        c = _verify_ci_excludes_acceptance_16z()
        assert "host_acceptance_tests_excluded_from_ci" in c
        assert "ci_file_found" in c

    def test_ci_command_exits_zero_returns_structured(self):
        c = _verify_ci_command_exits_zero_16z()
        assert "ci_command_documented" in c
        assert "ci_command_exits_zero" in c

    def test_fresh_clone_command_returns_structured(self):
        c = _verify_fresh_clone_command_16z()
        assert "fresh_clone_unit_command_documented" in c

    def test_pure_tests_home_isolated_returns_structured(self):
        c = _verify_pure_tests_home_isolated_16z()
        assert "pure_tests_home_isolated" in c
        assert "pure_tests_no_real_openclaw_access" in c

    def test_pure_tests_no_h1_access_returns_structured(self):
        c = _verify_pure_tests_no_h1_access_16z()
        assert "pure_tests_no_h1_file_access" in c

    def test_pure_tests_no_ibkr_gateway_returns_structured(self):
        c = _verify_pure_tests_no_ibkr_gateway_16z()
        assert "pure_tests_no_ibkr_gateway_required" in c

    def test_pure_tests_no_systemd_returns_structured(self):
        c = _verify_pure_tests_no_systemd_16z()
        assert "pure_tests_no_systemd_required" in c


# ===========================================================================
# CLI tests
# ===========================================================================


class TestPhase16ZCLI:

    def test_help_succeeds(self):
        result = subprocess.run(
            [sys.executable, str(OPERATOR),
             "level1-fresh-clone-ci-workflow-checkpoint", "--help"],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0, f"stderr: {result.stderr[:200]}"
        assert "fresh" in result.stdout.lower() or "ci" in result.stdout.lower()

    def test_json_output_valid(self):
        """--json produces valid JSON with diagnosis field."""
        result = subprocess.run(
            [sys.executable, str(OPERATOR),
             "level1-fresh-clone-ci-workflow-checkpoint", "--json"],
            capture_output=True, text=True, timeout=60,
        )
        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError:
            pytest.fail(f"Invalid JSON output: {result.stdout[:200]}")
        assert "diagnosis" in data
        assert "command" in data

    def test_alias_phase16z_works(self):
        """Alias 'phase16z-fresh-clone-ci-workflow-checkpoint' works."""
        result = subprocess.run(
            [sys.executable, str(OPERATOR),
             "phase16z-fresh-clone-ci-workflow-checkpoint", "--json"],
            capture_output=True, text=True, timeout=60,
        )
        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError:
            pytest.fail(f"Invalid JSON: {result.stdout[:200]}")
        assert "diagnosis" in data

    def test_alias_fresh_clone_works(self):
        """Alias 'fresh-clone-ci-workflow-checkpoint' works."""
        result = subprocess.run(
            [sys.executable, str(OPERATOR),
             "fresh-clone-ci-workflow-checkpoint", "--json"],
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
             "level1-fresh-clone-ci-workflow-checkpoint", "--json"],
            capture_output=True, text=True, timeout=60,
        )
        data = json.loads(result.stdout)
        required_fields = [
            "diagnosis", "severity", "git",
            "runtime_connected", "mode", "read_only", "allow_orders",
            "endpoints_ok", "positions_flat", "guard_state_clean",
            "kpi_hold_only_system_locked",
            "github_actions_workflow_present",
            "github_actions_workflow_valid",
            "ci_command_documented",
            "ci_command_exits_zero",
            "fresh_clone_unit_command_documented",
            "fresh_clone_unit_command_exits_zero",
            "pure_tests_home_isolated",
            "pure_tests_no_real_openclaw_access",
            "pure_tests_no_h1_file_access",
            "pure_tests_no_ibkr_gateway_required",
            "pure_tests_no_systemd_required",
            "host_acceptance_tests_excluded_from_ci",
            "synthetic_workflow_parse_case_passed",
            "synthetic_marker_exclusion_case_passed",
            "synthetic_temp_home_ci_case_passed",
            "synthetic_fresh_clone_case_passed",
            "synthetic_no_real_openclaw_case_passed",
            "synthetic_no_h1_file_access_case_passed",
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


class TestPhase16ZNoGo:

    def test_no_go_returns_correct_structure(self):
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        ts = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        result = _phase16z_no_go(
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
        result = _phase16z_no_go(
            "test-id", ts,
            {"branch": "test", "commit": "abc", "tag": "v1", "worktree_clean": False},
            "test_diagnosis", [],
        )
        assert result["no_order_endpoint_called"] is True
        assert result["no_broker_mutation"] is True
        assert result["no_h1_token_used"] is True
        assert result["github_actions_workflow_present"] is False


# ===========================================================================
# Read-only invariant tests
# ===========================================================================


class TestPhase16ZReadOnlyInvariants:

    def test_no_h1_token_in_checkpoint_source(self):
        """Phase 16Z run function must not USE h1_token."""
        import inspect
        from ibkr_operator import _run_level1_fresh_clone_ci_workflow_checkpoint
        src = inspect.getsource(_run_level1_fresh_clone_ci_workflow_checkpoint)
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
        """Phase 16Z run function must not reference /order endpoints."""
        import inspect
        from ibkr_operator import _run_level1_fresh_clone_ci_workflow_checkpoint
        src = inspect.getsource(_run_level1_fresh_clone_ci_workflow_checkpoint)
        assert "/order" not in src
        assert "/order/preflight" not in src
        assert "/order/approve" not in src
        assert "/order/submit" not in src

    def test_no_trade_window_in_checkpoint_source(self):
        """Phase 16Z run function must not reference ibkr-trade-window."""
        import inspect
        from ibkr_operator import _run_level1_fresh_clone_ci_workflow_checkpoint
        src = inspect.getsource(_run_level1_fresh_clone_ci_workflow_checkpoint)
        assert "ibkr-trade-window" not in src
        # Allow "no_trade_window_helper_called" as a field name but not actual calls
        assert "trade_window_helper(" not in src
        assert "ibkr_trade_window" not in src.lower().replace("no_trade_window_helper_called", "").replace("no_trade_window", "")


# ===========================================================================
# Real workflow file tests (verifies actual .github/workflows/ci.yml)
# ===========================================================================


class TestRealWorkflowFile:

    def test_ci_yml_exists(self):
        """The real .github/workflows/ci.yml file exists."""
        ci_path = REPO / ".github" / "workflows" / "ci.yml"
        assert ci_path.exists(), f"Missing CI workflow: {ci_path}"

    def test_ci_yml_has_runs_on(self):
        """CI workflow specifies runs-on."""
        ci_path = REPO / ".github" / "workflows" / "ci.yml"
        content = ci_path.read_text()
        assert "runs-on" in content, "CI workflow missing runs-on"

    def test_ci_yml_has_pytest(self):
        """CI workflow runs pytest."""
        ci_path = REPO / ".github" / "workflows" / "ci.yml"
        content = ci_path.read_text()
        assert "pytest" in content, "CI workflow missing pytest"

    def test_ci_yml_has_checkout(self):
        """CI workflow uses actions/checkout."""
        ci_path = REPO / ".github" / "workflows" / "ci.yml"
        content = ci_path.read_text()
        assert "actions/checkout" in content, "CI workflow missing checkout"

    def test_ci_yml_has_setup_python(self):
        """CI workflow sets up Python."""
        ci_path = REPO / ".github" / "workflows" / "ci.yml"
        content = ci_path.read_text()
        assert "setup-python" in content or "python" in content.lower(), "CI workflow missing Python setup"

    def test_ci_yml_excludes_integration(self):
        """CI workflow excludes integration tests."""
        ci_path = REPO / ".github" / "workflows" / "ci.yml"
        content = ci_path.read_text()
        assert "not integration" in content, "CI workflow does not exclude integration tests"

    def test_ci_yml_excludes_live(self):
        """CI workflow excludes live tests."""
        ci_path = REPO / ".github" / "workflows" / "ci.yml"
        content = ci_path.read_text()
        assert "not live" in content, "CI workflow does not exclude live tests"

    def test_ci_yml_excludes_acceptance(self):
        """CI workflow excludes acceptance tests."""
        ci_path = REPO / ".github" / "workflows" / "ci.yml"
        content = ci_path.read_text()
        assert "not acceptance" in content, "CI workflow does not exclude acceptance tests"

    def test_ci_yml_has_python_version(self):
        """CI workflow specifies Python version."""
        ci_path = REPO / ".github" / "workflows" / "ci.yml"
        content = ci_path.read_text()
        assert "3.12" in content, "CI workflow missing Python 3.12 version"

    def test_ci_yml_installs_requirements(self):
        """CI workflow installs from requirements.txt."""
        ci_path = REPO / ".github" / "workflows" / "ci.yml"
        content = ci_path.read_text()
        assert "requirements.txt" in content, "CI workflow missing requirements install"

    def test_ci_yml_has_compile_check(self):
        """CI workflow has compile check step."""
        ci_path = REPO / ".github" / "workflows" / "ci.yml"
        content = ci_path.read_text()
        assert "py_compile" in content, "CI workflow missing compile check"
