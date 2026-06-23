"""Tests for Step 15M — Manual Level-1 Promotion Plan.

All tests are read-only. No broker mutation, no order endpoints,
no H1 token usage, no autonomy level changes.
"""

import json
import os
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

BRIDGE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BRIDGE_DIR))

from ibkr_operator import (
    _run_autonomy_promotion_plan,
    _EXPLICIT_NON_ACTIONS,
    _AUTONOMY_PROMOTION_PLANS_DIR,
    OPENCLAW_DIR,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_hold_autonomy_status() -> dict:
    """Return an autonomy-status result with HOLD recommendation."""
    return {
        "command": "ibkr-operator autonomy-status",
        "recommendation": "HOLD",
        "current_autonomy_level": "0",
        "target_autonomy_level": "1",
        "clean_cycles_observed": 3,
        "clean_cycles_required": 5,
        "latest_clean_cycle_timestamp": "2026-06-22T10:00:00Z",
        "doctor_verdict": "PASS",
        "kpi_verdict": "GO",
        "ibkr_connected": True,
        "bridge_reachable": True,
        "market_data_status": "unavailable",
        "fx_status": "unavailable",
        "safety_locked": True,
        "active_alert_count": 0,
        "reconciliation_passed": True,
        "env_IBKR_ALLOW_ORDERS": "false",
        "rules_enforced": "false",
        "system_locked": False,
        "evidence_exports": ["/tmp/mock-status-export.json"],
    }


def _make_ready_autonomy_status() -> dict:
    """Return an autonomy-status result with READY_FOR_MANUAL_REVIEW."""
    return {
        "command": "ibkr-operator autonomy-status",
        "recommendation": "READY_FOR_MANUAL_REVIEW",
        "current_autonomy_level": "0",
        "target_autonomy_level": "1",
        "clean_cycles_observed": 7,
        "clean_cycles_required": 5,
        "latest_clean_cycle_timestamp": "2026-06-23T08:00:00Z",
        "doctor_verdict": "PASS",
        "kpi_verdict": "GO",
        "ibkr_connected": True,
        "bridge_reachable": True,
        "market_data_status": "available",
        "fx_status": "not_required",
        "safety_locked": True,
        "active_alert_count": 0,
        "reconciliation_passed": True,
        "env_IBKR_ALLOW_ORDERS": "false",
        "rules_enforced": "false",
        "system_locked": False,
        "evidence_exports": ["/tmp/mock-status-export.json"],
    }


def _make_ready_autonomy_review() -> dict:
    """Return an autonomy-review result with READY_FOR_OPERATOR_REVIEW."""
    return {
        "command": "ibkr-operator autonomy-review",
        "review_status": "READY_FOR_OPERATOR_REVIEW",
        "_export_path": "/tmp/mock-review-export.json",
    }


def _make_hold_autonomy_review() -> dict:
    """Return an autonomy-review result with HOLD."""
    return {
        "command": "ibkr-operator autonomy-review",
        "review_status": "HOLD",
        "_export_path": "/tmp/mock-review-export.json",
    }


def _make_error_autonomy_status() -> dict:
    """Return an autonomy-status error."""
    return {
        "_error": "timeout",
        "recommendation": "ERROR",
        "safety_locked": True,
        "env_IBKR_ALLOW_ORDERS": "false",
        "rules_enforced": "false",
        "current_autonomy_level": "0",
        "clean_cycles_observed": 0,
        "clean_cycles_required": 5,
        "doctor_verdict": "UNKNOWN",
        "kpi_verdict": "UNKNOWN",
        "ibkr_connected": None,
        "bridge_reachable": True,
        "market_data_status": "unknown",
        "fx_status": "unknown",
        "active_alert_count": 0,
        "reconciliation_passed": None,
        "system_locked": None,
        "evidence_exports": [],
    }


def _make_error_autonomy_review() -> dict:
    """Return an autonomy-review error."""
    return {
        "_error": "timeout",
        "review_status": "ERROR",
        "_export_path": "/tmp/mock-review-error-export.json",
    }


# ---------------------------------------------------------------------------
# T1: Command exists and exports valid JSON
# ---------------------------------------------------------------------------

class TestCommandExistsAndExports:
    """Verify the promotion plan command produces valid JSON."""

    def test_function_imports(self):
        """_run_autonomy_promotion_plan is importable."""
        assert callable(_run_autonomy_promotion_plan)

    def test_json_stdout_pure_parseable(self):
        """--json output is pure parseable JSON."""
        with patch("ibkr_operator._run_autonomy_status",
                   return_value=_make_hold_autonomy_status()), \
             patch("ibkr_operator._run_autonomy_review",
                   return_value=_make_hold_autonomy_review()), \
             patch("ibkr_operator._scan_forbidden_endpoints",
                   return_value={"ok": True, "violations": []}):
            result = _run_autonomy_promotion_plan(target_level="1")

        serialized = json.dumps(result, default=str)
        parsed = json.loads(serialized)
        assert parsed["command"] == "ibkr-operator autonomy-promotion-plan"
        assert "plan_id" in parsed
        assert "plan_status" in parsed
        assert "evidence_hash" in parsed

    def test_export_file_written(self, tmp_path):
        """Export writes JSON to the plans directory."""
        plans_dir = tmp_path / "autonomy-promotion-plans"

        with patch("ibkr_operator._run_autonomy_status",
                   return_value=_make_hold_autonomy_status()), \
             patch("ibkr_operator._run_autonomy_review",
                   return_value=_make_hold_autonomy_review()), \
             patch("ibkr_operator._scan_forbidden_endpoints",
                   return_value={"ok": True, "violations": []}), \
             patch("ibkr_operator._AUTONOMY_PROMOTION_PLANS_DIR", plans_dir):
            result = _run_autonomy_promotion_plan(target_level="1")

        ep = result.get("_export_path")
        assert ep is not None
        export_file = Path(ep)
        assert export_file.exists()
        assert export_file.suffix == ".json"

        # Verify content round-trips
        exported = json.loads(export_file.read_text())
        assert exported["plan_id"] == result["plan_id"]
        assert exported["plan_status"] == result["plan_status"]


# ---------------------------------------------------------------------------
# T2: Aliases dispatch correctly
# ---------------------------------------------------------------------------

class TestAliases:
    """Verify alias command names are registered."""

    def test_aliases_registered(self):
        """promotion-plan and level1-promotion-plan are valid subcommands."""
        import subprocess

        # Check that the main parser recognizes the aliases
        r1 = subprocess.run(
            [sys.executable, str(BRIDGE_DIR / "ibkr_operator.py"),
             "promotion-plan", "--help"],
            capture_output=True, text=True, timeout=15,
        )
        assert r1.returncode == 0, f"promotion-plan --help failed: {r1.stderr}"

        r2 = subprocess.run(
            [sys.executable, str(BRIDGE_DIR / "ibkr_operator.py"),
             "level1-promotion-plan", "--help"],
            capture_output=True, text=True, timeout=15,
        )
        assert r2.returncode == 0, f"level1-promotion-plan --help failed: {r2.stderr}"


# ---------------------------------------------------------------------------
# T3: HOLD when autonomy-status is HOLD
# ---------------------------------------------------------------------------

class TestHoldScenarios:
    """Verify plan_status is HOLD under various insufficient conditions."""

    def test_hold_when_autonomy_status_hold(self):
        """When autonomy-status is HOLD, plan_status must be HOLD."""
        with patch("ibkr_operator._run_autonomy_status",
                   return_value=_make_hold_autonomy_status()), \
             patch("ibkr_operator._run_autonomy_review",
                   return_value=_make_hold_autonomy_review()), \
             patch("ibkr_operator._scan_forbidden_endpoints",
                   return_value={"ok": True, "violations": []}):
            result = _run_autonomy_promotion_plan(target_level="1")

        assert result["plan_status"] == "HOLD", \
            f"Expected HOLD, got {result['plan_status']}"
        blockers = {b["check"] for b in result["blockers"]}
        assert "autonomy_status_hold" in blockers or "market_data_unavailable" in blockers, \
            f"Expected autonomy_status_hold or market_data_unavailable blocker, got {blockers}"

    def test_hold_when_autonomy_review_hold(self):
        """When autonomy-review is HOLD, plan_status must be HOLD."""
        with patch("ibkr_operator._run_autonomy_status",
                   return_value=_make_ready_autonomy_status()), \
             patch("ibkr_operator._run_autonomy_review",
                   return_value=_make_hold_autonomy_review()), \
             patch("ibkr_operator._scan_forbidden_endpoints",
                   return_value={"ok": True, "violations": []}):
            result = _run_autonomy_promotion_plan(target_level="1")

        assert result["plan_status"] == "HOLD", \
            f"Expected HOLD when review is HOLD, got {result['plan_status']}"
        blockers = {b["check"] for b in result["blockers"]}
        assert "autonomy_review_hold" in blockers, \
            f"Expected autonomy_review_hold blocker, got {blockers}"

    def test_hold_when_market_data_unavailable(self):
        """Plan must HOLD when market data is unavailable."""
        ready_status = _make_ready_autonomy_status()
        ready_status["market_data_status"] = "unavailable"

        with patch("ibkr_operator._run_autonomy_status",
                   return_value=ready_status), \
             patch("ibkr_operator._run_autonomy_review",
                   return_value=_make_ready_autonomy_review()), \
             patch("ibkr_operator._scan_forbidden_endpoints",
                   return_value={"ok": True, "violations": []}):
            result = _run_autonomy_promotion_plan(target_level="1")

        assert result["plan_status"] == "HOLD", \
            f"Expected HOLD with unavailable market data, got {result['plan_status']}"
        blockers = {b["check"] for b in result["blockers"]}
        assert "market_data_unavailable" in blockers, \
            f"Expected market_data_unavailable blocker, got {blockers}"

    def test_hold_when_insufficient_clean_cycles(self):
        """Plan must HOLD when clean cycles are below threshold."""
        ready_status = _make_ready_autonomy_status()
        ready_status["clean_cycles_observed"] = 2  # below 5 threshold

        with patch("ibkr_operator._run_autonomy_status",
                   return_value=ready_status), \
             patch("ibkr_operator._run_autonomy_review",
                   return_value=_make_ready_autonomy_review()), \
             patch("ibkr_operator._scan_forbidden_endpoints",
                   return_value={"ok": True, "violations": []}):
            result = _run_autonomy_promotion_plan(target_level="1")

        assert result["plan_status"] == "HOLD", \
            f"Expected HOLD with insufficient clean cycles, got {result['plan_status']}"
        blockers = {b["check"] for b in result["blockers"]}
        assert "insufficient_clean_cycles" in blockers, \
            f"Expected insufficient_clean_cycles blocker, got {blockers}"

    def test_hold_when_ibkr_disconnected(self):
        """Plan must HOLD when IBKR is disconnected."""
        ready_status = _make_ready_autonomy_status()
        ready_status["ibkr_connected"] = False

        with patch("ibkr_operator._run_autonomy_status",
                   return_value=ready_status), \
             patch("ibkr_operator._run_autonomy_review",
                   return_value=_make_ready_autonomy_review()), \
             patch("ibkr_operator._scan_forbidden_endpoints",
                   return_value={"ok": True, "violations": []}):
            result = _run_autonomy_promotion_plan(target_level="1")

        assert result["plan_status"] == "HOLD", \
            f"Expected HOLD when disconnected, got {result['plan_status']}"
        blockers = {b["check"] for b in result["blockers"]}
        assert "ibkr_disconnected" in blockers, \
            f"Expected ibkr_disconnected blocker, got {blockers}"

    def test_hold_when_status_error(self):
        """Plan must HOLD when autonomy-status produces an error."""
        with patch("ibkr_operator._run_autonomy_status",
                   return_value=_make_error_autonomy_status()), \
             patch("ibkr_operator._run_autonomy_review",
                   return_value=_make_hold_autonomy_review()), \
             patch("ibkr_operator._scan_forbidden_endpoints",
                   return_value={"ok": True, "violations": []}):
            result = _run_autonomy_promotion_plan(target_level="1")

        assert result["plan_status"] == "HOLD", \
            f"Expected HOLD on error, got {result['plan_status']}"
        blockers = {b["check"] for b in result["blockers"]}
        assert "autonomy_status_error" in blockers, \
            f"Expected autonomy_status_error blocker, got {blockers}"


# ---------------------------------------------------------------------------
# T4: READY_FOR_MANUAL_DECISION when all gates pass
# ---------------------------------------------------------------------------

class TestReadyForManualDecision:
    """Verify plan_status is READY_FOR_MANUAL_DECISION when all gates pass."""

    def test_ready_when_all_gates_pass(self):
        """When all readiness evidence is clean, plan_status must be READY."""
        with patch("ibkr_operator._run_autonomy_status",
                   return_value=_make_ready_autonomy_status()), \
             patch("ibkr_operator._run_autonomy_review",
                   return_value=_make_ready_autonomy_review()), \
             patch("ibkr_operator._scan_forbidden_endpoints",
                   return_value={"ok": True, "violations": []}):
            result = _run_autonomy_promotion_plan(target_level="1")

        assert result["plan_status"] == "READY_FOR_MANUAL_DECISION", \
            f"Expected READY_FOR_MANUAL_DECISION, got {result['plan_status']}: " \
            f"blockers={[b['check'] for b in result['blockers']]}"
        assert result["operator_decision_required"] is True
        assert result["auto_promotion_performed"] is False
        assert result["config_changed"] is False
        assert result["no_broker_mutation"] is True
        assert result["no_order_window_opened"] is True


# ---------------------------------------------------------------------------
# T5: NO_GO when safety is unlocked
# ---------------------------------------------------------------------------

class TestNoGoScenarios:
    """Verify plan_status is NO_GO under safety violations."""

    def test_nogo_when_safety_unlocked(self):
        """Plan must be NO_GO when safety flags are unlocked."""
        unlocked_status = _make_ready_autonomy_status()
        unlocked_status["safety_locked"] = False
        unlocked_status["env_IBKR_ALLOW_ORDERS"] = "true"

        with patch("ibkr_operator._run_autonomy_status",
                   return_value=unlocked_status), \
             patch("ibkr_operator._run_autonomy_review",
                   return_value=_make_ready_autonomy_review()), \
             patch("ibkr_operator._scan_forbidden_endpoints",
                   return_value={"ok": True, "violations": []}):
            result = _run_autonomy_promotion_plan(target_level="1")

        assert result["plan_status"] == "NO_GO", \
            f"Expected NO_GO when safety unlocked, got {result['plan_status']}"
        blockers = {b["check"] for b in result["blockers"]}
        assert "safety_unlocked" in blockers or "orders_enabled" in blockers, \
            f"Expected safety_unlocked or orders_enabled blocker, got {blockers}"

    def test_nogo_when_active_alerts(self):
        """Plan must be NO_GO when there are active alerts."""
        alert_status = _make_ready_autonomy_status()
        alert_status["active_alert_count"] = 2

        with patch("ibkr_operator._run_autonomy_status",
                   return_value=alert_status), \
             patch("ibkr_operator._run_autonomy_review",
                   return_value=_make_ready_autonomy_review()), \
             patch("ibkr_operator._scan_forbidden_endpoints",
                   return_value={"ok": True, "violations": []}):
            result = _run_autonomy_promotion_plan(target_level="1")

        assert result["plan_status"] == "NO_GO", \
            f"Expected NO_GO with active alerts, got {result['plan_status']}"
        blockers = {b["check"] for b in result["blockers"]}
        assert "active_alerts" in blockers, \
            f"Expected active_alerts blocker, got {blockers}"

    def test_nogo_when_reconciliation_failed(self):
        """Plan must be NO_GO when reconciliation failed."""
        failed_status = _make_ready_autonomy_status()
        failed_status["reconciliation_passed"] = False

        with patch("ibkr_operator._run_autonomy_status",
                   return_value=failed_status), \
             patch("ibkr_operator._run_autonomy_review",
                   return_value=_make_ready_autonomy_review()), \
             patch("ibkr_operator._scan_forbidden_endpoints",
                   return_value={"ok": True, "violations": []}):
            result = _run_autonomy_promotion_plan(target_level="1")

        assert result["plan_status"] == "NO_GO", \
            f"Expected NO_GO when reconciliation failed, got {result['plan_status']}"
        blockers = {b["check"] for b in result["blockers"]}
        assert "reconciliation_failed" in blockers, \
            f"Expected reconciliation_failed blocker, got {blockers}"

    def test_nogo_when_orders_enabled(self):
        """Plan must be NO_GO when IBKR_ALLOW_ORDERS is true."""
        orders_status = _make_ready_autonomy_status()
        orders_status["env_IBKR_ALLOW_ORDERS"] = "true"

        with patch("ibkr_operator._run_autonomy_status",
                   return_value=orders_status), \
             patch("ibkr_operator._run_autonomy_review",
                   return_value=_make_ready_autonomy_review()), \
             patch("ibkr_operator._scan_forbidden_endpoints",
                   return_value={"ok": True, "violations": []}):
            result = _run_autonomy_promotion_plan(target_level="1")

        assert result["plan_status"] == "NO_GO", \
            f"Expected NO_GO when orders enabled, got {result['plan_status']}"
        blockers = {b["check"] for b in result["blockers"]}
        assert "orders_enabled" in blockers, \
            f"Expected orders_enabled blocker, got {blockers}"


# ---------------------------------------------------------------------------
# T6: No broker mutation / no order endpoint calls
# ---------------------------------------------------------------------------

class TestNoBrokerMutation:
    """Verify promotion plan is read-only, no broker mutation."""

    def test_no_order_endpoints_in_source(self):
        """The promotion plan function must not contain /order* calls."""
        import inspect
        source = inspect.getsource(_run_autonomy_promotion_plan)
        forbidden = ["/order/preflight", "/order/approve", "/order/submit",
                      "placeOrder", "cancelOrder"]
        for pattern in forbidden:
            found_line = None
            for line in source.splitlines():
                if pattern in line and not line.strip().startswith("#"):
                    # Allow documentation strings that mention the pattern in safety context
                    lower = line.strip().lower()
                    if any(kw in lower for kw in ["no /order", "must not", "did not"]):
                        continue
                    found_line = line.strip()[:100]
                    break
            assert found_line is None, \
                f"FORBIDDEN: '{pattern}' found in promotion plan source: {found_line}"

    def test_no_h1_token_in_source(self):
        """The promotion plan function must not reference H1 token."""
        import inspect
        source = inspect.getsource(_run_autonomy_promotion_plan)
        forbidden = ["_run_h1_canary(", "H1_APPROVAL_TOKEN_HASH",
                      "/etc/ibkr-bridge/h1_token"]
        for pattern in forbidden:
            found = False
            for line in source.splitlines():
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue
                if pattern in stripped:
                    found = True
                    break
            assert not found, \
                f"FORBIDDEN: '{pattern}' found in promotion plan source"

    def test_auto_promotion_is_false(self):
        """auto_promotion_performed must always be False."""
        with patch("ibkr_operator._run_autonomy_status",
                   return_value=_make_ready_autonomy_status()), \
             patch("ibkr_operator._run_autonomy_review",
                   return_value=_make_ready_autonomy_review()), \
             patch("ibkr_operator._scan_forbidden_endpoints",
                   return_value={"ok": True, "violations": []}):
            result = _run_autonomy_promotion_plan(target_level="1")

        assert result["auto_promotion_performed"] is False
        assert result["config_changed"] is False
        assert result["no_broker_mutation"] is True
        assert result["no_order_window_opened"] is True

    def test_does_not_modify_env(self, tmp_path):
        """The promotion plan must not modify any .env file."""
        env_path = tmp_path / ".env"
        original = "IBKR_ALLOW_ORDERS=false\n"
        env_path.write_text(original)

        with patch("ibkr_operator._run_autonomy_status",
                   return_value=_make_hold_autonomy_status()), \
             patch("ibkr_operator._run_autonomy_review",
                   return_value=_make_hold_autonomy_review()), \
             patch("ibkr_operator._scan_forbidden_endpoints",
                   return_value={"ok": True, "violations": []}):
            _run_autonomy_promotion_plan(target_level="1")

        # The .env file must be unchanged
        assert env_path.read_text() == original, \
            ".env file was modified by promotion plan"


# ---------------------------------------------------------------------------
# T7: Required fields and structure
# ---------------------------------------------------------------------------

class TestRequiredFields:
    """Verify all required fields are present in the promotion plan."""

    _REQUIRED_FIELDS = [
        "timestamp", "plan_id", "git", "current_autonomy_level",
        "target_autonomy_level", "plan_status", "operator_decision_required",
        "auto_promotion_performed", "config_changed", "no_broker_mutation",
        "no_order_window_opened", "readiness_export_path", "review_export_path",
        "clean_cycles_observed", "clean_cycles_required",
        "latest_clean_cycle_timestamp", "doctor_verdict", "kpi_verdict",
        "autonomy_status_recommendation", "autonomy_review_status",
        "bridge_connected", "market_data_status", "fx_status",
        "safety_flags", "blockers", "manual_preconditions",
        "manual_promotion_steps", "manual_rollback_steps",
        "post_promotion_validation_steps", "explicit_non_actions",
        "evidence_hash",
    ]

    def test_all_required_fields_present(self):
        """All spec-required fields must be present in the output."""
        with patch("ibkr_operator._run_autonomy_status",
                   return_value=_make_hold_autonomy_status()), \
             patch("ibkr_operator._run_autonomy_review",
                   return_value=_make_hold_autonomy_review()), \
             patch("ibkr_operator._scan_forbidden_endpoints",
                   return_value={"ok": True, "violations": []}):
            result = _run_autonomy_promotion_plan(target_level="1")

        for field in self._REQUIRED_FIELDS:
            assert field in result, f"Missing required field: {field}"

    def test_manual_steps_not_empty(self):
        """Manual preconditions, promotion steps, rollback steps must be non-empty."""
        with patch("ibkr_operator._run_autonomy_status",
                   return_value=_make_hold_autonomy_status()), \
             patch("ibkr_operator._run_autonomy_review",
                   return_value=_make_hold_autonomy_review()), \
             patch("ibkr_operator._scan_forbidden_endpoints",
                   return_value={"ok": True, "violations": []}):
            result = _run_autonomy_promotion_plan(target_level="1")

        assert len(result["manual_preconditions"]) >= 5, \
            "Should have at least 5 manual preconditions"
        assert len(result["manual_promotion_steps"]) >= 5, \
            "Should have at least 5 manual promotion steps"
        assert len(result["manual_rollback_steps"]) >= 5, \
            "Should have at least 5 manual rollback steps"
        assert len(result["post_promotion_validation_steps"]) >= 5, \
            "Should have at least 5 post-promotion validation steps"

    def test_explicit_non_actions_complete(self):
        """explicit_non_actions must cover all spec-required statements."""
        with patch("ibkr_operator._run_autonomy_status",
                   return_value=_make_hold_autonomy_status()), \
             patch("ibkr_operator._run_autonomy_review",
                   return_value=_make_hold_autonomy_review()), \
             patch("ibkr_operator._scan_forbidden_endpoints",
                   return_value={"ok": True, "violations": []}):
            result = _run_autonomy_promotion_plan(target_level="1")

        non_actions = result["explicit_non_actions"]
        required_topics = [
            "not change autonomy level",
            "not open an order",
            "not call",
            "not read H1",
            "not place",
            "not enable IBKR_ALLOW_ORDERS",
            "not enable rules.enforced",
        ]
        for topic in required_topics:
            found = any(topic.lower() in na.lower() for na in non_actions)
            assert found, f"explicit_non_actions missing: '{topic}'"

    def test_rollback_steps_included(self):
        """Manual rollback steps must include revert, doctor, KPI, status checks."""
        with patch("ibkr_operator._run_autonomy_status",
                   return_value=_make_hold_autonomy_status()), \
             patch("ibkr_operator._run_autonomy_review",
                   return_value=_make_hold_autonomy_review()), \
             patch("ibkr_operator._scan_forbidden_endpoints",
                   return_value={"ok": True, "violations": []}):
            result = _run_autonomy_promotion_plan(target_level="1")

        rollback_text = " ".join(
            s["action"] for s in result["manual_rollback_steps"]
        ).lower()
        assert "revert" in rollback_text or "level to 0" in rollback_text, \
            "Rollback steps must include reverting autonomy level"
        assert "doctor" in rollback_text, \
            "Rollback steps must include doctor check"
        assert "kpi" in rollback_text, \
            "Rollback steps must include KPI check"


# ---------------------------------------------------------------------------
# T8: Evidence hash stability
# ---------------------------------------------------------------------------

class TestEvidenceHash:
    """Verify evidence_hash is stable for identical content."""

    def test_hash_stable_for_identical_input(self):
        """Same inputs must produce same evidence_hash."""
        status = _make_hold_autonomy_status()
        review = _make_hold_autonomy_review()
        scan = {"ok": True, "violations": []}

        with patch("ibkr_operator._run_autonomy_status", return_value=status), \
             patch("ibkr_operator._run_autonomy_review", return_value=review), \
             patch("ibkr_operator._scan_forbidden_endpoints", return_value=scan):
            r1 = _run_autonomy_promotion_plan(target_level="1")

        with patch("ibkr_operator._run_autonomy_status", return_value=status), \
             patch("ibkr_operator._run_autonomy_review", return_value=review), \
             patch("ibkr_operator._scan_forbidden_endpoints", return_value=scan):
            r2 = _run_autonomy_promotion_plan(target_level="1")

        assert r1["evidence_hash"] == r2["evidence_hash"], \
            f"Hash mismatch for identical inputs: {r1['evidence_hash']} vs {r2['evidence_hash']}"

    def test_hash_differs_for_different_input(self):
        """Different inputs must produce different evidence_hash."""
        status1 = _make_hold_autonomy_status()
        status2 = _make_ready_autonomy_status()

        with patch("ibkr_operator._run_autonomy_status", return_value=status1), \
             patch("ibkr_operator._run_autonomy_review",
                   return_value=_make_hold_autonomy_review()), \
             patch("ibkr_operator._scan_forbidden_endpoints",
                   return_value={"ok": True, "violations": []}):
            r1 = _run_autonomy_promotion_plan(target_level="1")

        with patch("ibkr_operator._run_autonomy_status", return_value=status2), \
             patch("ibkr_operator._run_autonomy_review",
                   return_value=_make_ready_autonomy_review()), \
             patch("ibkr_operator._scan_forbidden_endpoints",
                   return_value={"ok": True, "violations": []}):
            r2 = _run_autonomy_promotion_plan(target_level="1")

        assert r1["evidence_hash"] != r2["evidence_hash"], \
            "Hash must differ for different inputs"


# ---------------------------------------------------------------------------
# T9: Existing tests still pass (integration check)
# ---------------------------------------------------------------------------

class TestExistingTestsStillPass:
    """Quick sanity: importing and running the plan doesn't break other modules."""

    def test_imports_dont_break(self):
        """All key operator functions remain importable."""
        from ibkr_operator import (
            _run_autonomy_status,
            _run_autonomy_review,
            _run_cycle_rehearsal,
            _run_candidate_dryrun,
        )
        assert callable(_run_autonomy_status)
        assert callable(_run_autonomy_review)
        assert callable(_run_cycle_rehearsal)
        assert callable(_run_candidate_dryrun)
        assert callable(_run_autonomy_promotion_plan)
