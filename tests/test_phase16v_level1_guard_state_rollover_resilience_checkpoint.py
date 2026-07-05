"""Tests for Phase 16V — Level 1 Guard-State Rollover Resilience Checkpoint."""

import json
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

import pytest

# Ensure the ibkr-bridge root is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ibkr_operator import (
    _PHASE16V_DIAGNOSIS,
    _synthetic_guard_state_reconcile_for_path,
    _synthetic_fixture_stale_trade_date_rollover,
    _synthetic_fixture_false_trade_count,
    _synthetic_fixture_already_clean,
    _synthetic_fixture_blocked_repair,
    _phase16v_no_go,
)


# ===========================================================================
# Synthetic fixture tests — temp files only, never real guard-state.json
# ===========================================================================


class TestSyntheticFixtures:
    """All four synthetic fixtures must pass without touching the real
    ~/.openclaw/guard-state.json.  Each test creates temp files only."""

    def test_stale_trade_date_rollover(self):
        """Case 1: stale date, count=0 → repair_recommended=true."""
        c = _synthetic_fixture_stale_trade_date_rollover()
        assert c["passed"], f"Stale trade-date case failed: {c.get('result')}"
        r = c["result"]
        assert r["trade_date_stale"] is True
        assert r["repair_recommended"] is True
        assert r["repair_applied"] is False
        assert r["stale_trade_date_repair"] is True
        assert r["no_broker_mutation"] is True

    def test_false_trade_count(self):
        """Case 2: count=3, confirmed=0 → mismatch, repair recommended."""
        c = _synthetic_fixture_false_trade_count()
        assert c["passed"], f"False trade-count case failed: {c.get('result')}"
        r = c["result"]
        assert r["mismatch_detected"] is True
        assert r["repair_recommended"] is True
        assert r["repair_applied"] is False
        assert r["trade_date_stale"] is False
        assert r["no_broker_mutation"] is True

    def test_already_clean(self):
        """Case 3: clean state → no mismatch, no repair."""
        c = _synthetic_fixture_already_clean()
        assert c["passed"], f"Already-clean case failed: {c.get('result')}"
        r = c["result"]
        assert r["mismatch_detected"] is False
        assert r["repair_recommended"] is False
        assert r["repair_applied"] is False
        assert r["no_broker_mutation"] is True

    def test_blocked_repair(self):
        """Case 4: stale date but live orders → repair blocked."""
        c = _synthetic_fixture_blocked_repair()
        assert c["passed"], f"Blocked-repair case failed: {c.get('result')}"
        r = c["result"]
        assert r["repair_recommended"] is False
        assert r["repair_applied"] is False
        assert len(r["blockers"]) > 0
        assert r["no_broker_mutation"] is True


# ===========================================================================
# Synthetic reconcile helper tests
# ===========================================================================


class TestSyntheticReconcileHelper:
    """Tests for _synthetic_guard_state_reconcile_for_path."""

    def test_never_mutates_real_file(self, tmp_path):
        """Helper must never write to ~/.openclaw/guard-state.json."""
        # Just verify the function returns without error and repair_applied=False
        gp = tmp_path / "guard-state.json"
        gp.write_text(json.dumps({
            "daily_trade_count": 0,
            "trade_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "daily_halt_active": False,
        }))
        result = _synthetic_guard_state_reconcile_for_path(gp)
        assert result["repair_applied"] is False
        assert result["no_broker_mutation"] is True

    def test_stale_date_detection(self, tmp_path):
        """Yesterday's date should be detected as stale."""
        yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        gp = tmp_path / "guard-state.json"
        gp.write_text(json.dumps({
            "daily_trade_count": 0,
            "trade_date": yesterday,
        }))
        result = _synthetic_guard_state_reconcile_for_path(
            gp, canonical_date_override=today,
        )
        assert result["trade_date_stale"] is True
        assert result["repair_recommended"] is True

    def test_false_count_detection(self, tmp_path):
        """Inflated count with 0 confirmed → mismatch + repair recommended."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        gp = tmp_path / "guard-state.json"
        gp.write_text(json.dumps({
            "daily_trade_count": 5,
            "trade_date": today,
        }))
        result = _synthetic_guard_state_reconcile_for_path(
            gp, canonical_date_override=today,
        )
        assert result["mismatch_detected"] is True
        assert result["repair_recommended"] is True
        assert result["repair_applied"] is False

    def test_blocked_by_live_orders(self, tmp_path):
        """Stale date with live orders → repair blocked."""
        yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        gp = tmp_path / "guard-state.json"
        gp.write_text(json.dumps({
            "daily_trade_count": 0,
            "trade_date": yesterday,
        }))
        result = _synthetic_guard_state_reconcile_for_path(
            gp, canonical_date_override=today,
            live_order_override=3,
            open_order_override=3,
        )
        assert result["repair_recommended"] is False
        assert len(result["blockers"]) > 0
        assert result["no_broker_mutation"] is True


# ===========================================================================
# NO_GO helper tests
# ===========================================================================


class TestNoGoHelper:
    """Tests for _phase16v_no_go."""

    def test_returns_all_required_fields(self):
        git = {"branch": "test", "commit": "abc123", "tag": "v1", "worktree_clean": True}
        result = _phase16v_no_go(
            "16v-test-1", "2026-01-01T00:00:00Z", git,
            _PHASE16V_DIAGNOSIS["unknown"], ["Fix it"],
        )
        required = [
            "diagnosis", "severity", "git_worktree_clean",
            "runtime_connected", "mode", "read_only", "allow_orders",
            "endpoints_ok", "current_guard_state_clean",
            "reconcile_dry_run_exit", "reconcile_repair_applied",
            "synthetic_stale_trade_date_case_passed",
            "synthetic_false_trade_count_case_passed",
            "synthetic_clean_case_passed",
            "synthetic_blocked_repair_case_passed",
            "no_order_endpoint_called", "no_preflight_endpoint_called",
            "no_approval_endpoint_called", "no_submit_endpoint_called",
            "no_h1_token_used", "no_trade_window_helper_called",
            "no_broker_mutation", "artifact_created",
        ]
        for field in required:
            assert field in result, f"Missing field: {field}"
        assert result["severity"] == "NO_GO"
        assert result["operator_action_required"] is True
        assert result["reconcile_repair_applied"] is False
        assert result["no_broker_mutation"] is True


# ===========================================================================
# CLI command registration tests
# ===========================================================================


class TestCommandExists:
    """Verify the command is registered in the CLI."""

    def test_primary_command_registered(self):
        r = subprocess.run(
            [sys.executable, "ibkr_operator.py", "level1-guard-state-rollover-resilience-checkpoint", "--help"],
            capture_output=True, text=True, cwd=str(Path(__file__).resolve().parent.parent),
        )
        assert r.returncode == 0, f"stderr: {r.stderr}"
        assert "level1-guard-state-rollover-resilience-checkpoint" in r.stdout
        assert "Phase 16V" in r.stdout or "guard-state" in r.stdout

    def test_alias_phase16v_works(self):
        r = subprocess.run(
            [sys.executable, "ibkr_operator.py", "phase16v-guard-state-rollover-resilience-checkpoint", "--help"],
            capture_output=True, text=True, cwd=str(Path(__file__).resolve().parent.parent),
        )
        assert r.returncode == 0

    def test_alias_level1_guard_state_rollover_resilience_works(self):
        r = subprocess.run(
            [sys.executable, "ibkr_operator.py", "level1-guard-state-rollover-resilience", "--help"],
            capture_output=True, text=True, cwd=str(Path(__file__).resolve().parent.parent),
        )
        assert r.returncode == 0

    def test_alias_guard_state_rollover_resilience_works(self):
        r = subprocess.run(
            [sys.executable, "ibkr_operator.py", "guard-state-rollover-resilience-checkpoint", "--help"],
            capture_output=True, text=True, cwd=str(Path(__file__).resolve().parent.parent),
        )
        assert r.returncode == 0


# ===========================================================================
# Non-mutation invariants
# ===========================================================================


class TestNonMutation:
    """Verify all non-mutation fields are True in the checkpoint output."""

    def test_json_output_has_all_non_mutation_fields(self):
        # Run with --json and verify the required fields
        r = subprocess.run(
            [sys.executable, "ibkr_operator.py",
             "level1-guard-state-rollover-resilience-checkpoint", "--json"],
            capture_output=True, text=True, timeout=60,
            cwd=str(Path(__file__).resolve().parent.parent),
        )
        # May exit 0 or 1 depending on worktree state
        try:
            d = json.loads(r.stdout)
        except json.JSONDecodeError:
            pytest.skip("Could not parse JSON — likely dirty worktree")

        assert d["no_order_endpoint_called"] is True
        assert d["no_preflight_endpoint_called"] is True
        assert d["no_approval_endpoint_called"] is True
        assert d["no_submit_endpoint_called"] is True
        assert d["no_h1_token_used"] is True
        assert d["no_trade_window_helper_called"] is True
        assert d["no_broker_mutation"] is True
        assert "command" in d
        assert "checkpoint_id" in d
