"""Tests for Phase 16B — Manual Level-1 Promotion Procedure Review.

All tests are read-only. No broker mutation, no order endpoints,
no H1 token usage, no autonomy level changes.

Coverage:
  - Command parser registers primary + 3 aliases
  - --help exits quickly
  - JSON stdout pure
  - Export written
  - Clean runtime => level1_promotion_review_ready / OK
  - Missing 16A tag => NO_GO
  - Dirty worktree => NO_GO
  - Bridge disconnected => HOLD or NO_GO
  - Safety unlocked => NO_GO
  - Autonomy not Level 0 => NO_GO
  - Guard count > 0 => NO_GO
  - Stale guard trade_date => NO_GO
  - Active alerts => NO_GO
  - Positions not flat => NO_GO
  - promotion_allowed_now=false always
  - order_enablement_allowed_now=false always
  - No /order* calls
  - No H1 token reads
  - No mutation except export artifact
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# Auto-generated: dynamic date helpers for guard-state fixtures
from datetime import datetime, timezone, timedelta
_TODAY_STR = datetime.now(timezone.utc).strftime("%Y-%m-%d")
_YESTERDAY_STR = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")


BRIDGE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BRIDGE_DIR))

from ibkr_operator import (


    _run_manual_level1_promotion_review,
    _PHASE16B_DIAGNOSIS,
    _PHASE16B_REQUIRED_TAGS,
    _PHASE16B_EXPORT_DIR,
    BRIDGE_DIR as _OP_BRIDGE_DIR,
    OPENCLAW_DIR,
)


# ===========================================================================
# Fixtures
# ===========================================================================

@pytest.fixture
def clean_git_metadata():
    return {
        "branch": "main",
        "commit_short": "abc1234",
        "tag": "phase16a_phase15_completion_checkpoint",
    }


@pytest.fixture
def clean_worktree():
    return {"clean": True, "dirty_files": []}


@pytest.fixture
def dirty_worktree():
    return {"clean": False, "dirty_files": ["M ibkr_operator.py"]}


@pytest.fixture
def origin_aligned():
    return {
        "aligned": True,
        "origin_master_commit": "abc1234",
        "local_master_commit": "abc1234",
        "detail": "local master == origin/master",
    }


@pytest.fixture
def all_tags_present():
    return {
        "required_count": len(_PHASE16B_REQUIRED_TAGS),
        "present_count": len(_PHASE16B_REQUIRED_TAGS),
        "missing": [],
        "present": list(_PHASE16B_REQUIRED_TAGS),
    }


@pytest.fixture
def one_tag_missing():
    return {
        "required_count": len(_PHASE16B_REQUIRED_TAGS),
        "present_count": len(_PHASE16B_REQUIRED_TAGS) - 1,
        "missing": [list(_PHASE16B_REQUIRED_TAGS)[0]],
        "present": list(_PHASE16B_REQUIRED_TAGS)[1:],
    }


@pytest.fixture
def bridge_health_ok():
    return {
        "ok": True, "service": "ibkr-openclaw-bridge",
        "mode": "paper", "host": "127.0.0.1", "port": 4002,
        "client_id": 777, "account": "DUQ542875",
        "read_only": True, "allow_orders": False,
        "connected": True,
        "startup_safety": {"pass": True, "check_count": 11, "passed_count": 11},
    }


@pytest.fixture
def bridge_health_disconnected():
    return {
        "ok": True, "service": "ibkr-openclaw-bridge",
        "mode": "paper", "host": "127.0.0.1", "port": 4002,
        "client_id": 777, "account": "DUQ542875",
        "read_only": True, "allow_orders": False,
        "connected": False,
    }


@pytest.fixture
def positions_flat():
    return {"ok": True, "positions": []}


@pytest.fixture
def positions_non_flat():
    return {"ok": True, "positions": [{"symbol": "AAPL", "position": 10}]}


@pytest.fixture
def alerts_clean():
    return {"alerts": []}


@pytest.fixture
def alerts_active():
    return {"alerts": [{"alert_type": "drift_detected", "severity": "CRITICAL",
                        "requires_action": True, "source": "live"}]}


@pytest.fixture
def readiness_locked():
    return {"summary": {"kill_switches": {"IBKR_ALLOW_ORDERS": False,
                                          "rules.enforced": False,
                                          "system_locked": True}}}


@pytest.fixture
def readiness_unlocked():
    return {"summary": {"kill_switches": {"IBKR_ALLOW_ORDERS": True,
                                          "rules.enforced": True,
                                          "system_locked": False}}}


@pytest.fixture
def snapshot_ok():
    return {"connected": True, "mode": "paper", "read_only": True,
            "allow_orders": False, "positions": [], "guard": {},
            "safety": {"IBKR_ALLOW_ORDERS": False, "rules_enforced": False,
                       "system_locked": True}}


@pytest.fixture
def guard_state_clean():
    return json.dumps({
        "schema_version": 1, "trade_date": _TODAY_STR,
        "daily_trade_count": 0, "daily_halt_active": False,
        "last_updated_utc": "2026-06-26T08:00:00Z",
    })


@pytest.fixture
def guard_state_stale():
    return json.dumps({
        "schema_version": 1, "trade_date": _YESTERDAY_STR,
        "daily_trade_count": 0, "daily_halt_active": False,
        "last_updated_utc": "2026-06-25T10:00:00Z",
    })


@pytest.fixture
def guard_state_with_trades():
    return json.dumps({
        "schema_version": 1, "trade_date": _TODAY_STR,
        "daily_trade_count": 3, "daily_halt_active": False,
    })


@pytest.fixture
def env_safety_locked():
    return {"IBKR_ALLOW_ORDERS": "false", "found": True}


@pytest.fixture
def env_safety_unlocked():
    return {"IBKR_ALLOW_ORDERS": "true", "found": True}


@pytest.fixture
def rules_locked():
    return {"enforced": "false", "found": True}


@pytest.fixture
def rules_unlocked():
    return {"enforced": "true", "found": True}


@pytest.fixture
def autonomy_level_zero():
    return "0"


@pytest.fixture
def autonomy_level_one():
    return "1"


@pytest.fixture
def doctor_pass():
    return {
        "pass": True, "passed": 14, "total": 15,
        "passed_count": 14, "check_count": 15,
        "_non_canary_ok": True, "_non_canary_failures": [],
        "checks": [{"check": "h1_token_canary", "ok": True, "status": "PASS"}],
    }


@pytest.fixture
def doctor_fail():
    return {
        "pass": False, "passed": 10, "total": 15,
        "passed_count": 10, "check_count": 15,
        "_non_canary_ok": False, "_non_canary_failures": ["hermes_policy_exists"],
        "checks": [{"check": "h1_token_canary", "ok": True, "status": "PASS"}],
    }


@pytest.fixture
def kpi_hold_expected():
    return {
        "verdict": "HOLD",
        "blockers": [
            {"severity": "HOLD", "check": "autonomy_level_zero"},
            {"severity": "HOLD", "check": "system_locked"},
        ],
    }


@pytest.fixture
def kpi_no_go():
    return {
        "verdict": "NO-GO",
        "blockers": [{"severity": "NO-GO", "check": "active_alerts"}],
    }


@pytest.fixture
def hermes_policy_ok():
    return {
        "hermes_policy_exists": True,
        "execution_path_ok": True,
        "advisory_boundary_ok": True,
    }


@pytest.fixture
def hermes_policy_missing():
    return {
        "hermes_policy_exists": False,
        "execution_path_ok": False,
        "advisory_boundary_ok": False,
    }


# ===========================================================================
# Mock helpers
# ===========================================================================

class _MockUrlOpen:
    def __init__(self, responses: dict):
        self._responses = responses
        self._calls: list[str] = []

    def __call__(self, req, timeout=None):
        url = req.full_url if hasattr(req, 'full_url') else str(req)
        self._calls.append(url)
        for pattern, (status, body) in self._responses.items():
            if pattern in url:
                return _MockResponse(status, json.dumps(body).encode())
        return _MockResponse(404, b'{}')


class _MockResponse:
    def __init__(self, status: int, body: bytes):
        self.status = status
        self._body = body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


def _make_bridge_responses(health=None, positions=None, alerts=None,
                           snapshot=None, readiness=None):
    responses = {}
    if health:
        responses["/health"] = (200, health)
    if positions:
        responses["/positions"] = (200, positions)
    if alerts:
        responses["/monitor/alerts"] = (200, alerts)
    if snapshot:
        responses["/snapshot"] = (200, snapshot)
    if readiness:
        responses["/readiness"] = (200, readiness)
    return _MockUrlOpen(responses)


def _mock_subprocess_output(outputs: dict):
    def _run(args, **kwargs):
        cmd_str = " ".join(args) if isinstance(args, list) else str(args)
        for pattern, (rc, out) in outputs.items():
            if pattern in cmd_str:
                result = MagicMock()
                result.returncode = rc
                result.stdout = out
                result.stderr = ""
                return result
        result = MagicMock()
        result.returncode = 0
        result.stdout = ""
        result.stderr = ""
        return result
    return _run


def _build_mocks(
    health=None, positions=None, alerts=None, snapshot=None, readiness=None,
    git_metadata=None, worktree=None, origin=None, tags=None,
    guard_state_content=None, env_safety=None, rules=None,
    autonomy=None, doctor=None, kpi=None, policy=None,
):
    patches = []
    # Bridge HTTP
    bridge_mock = _make_bridge_responses(
        health=health, positions=positions, alerts=alerts,
        snapshot=snapshot, readiness=readiness,
    )
    patches.append(patch("urllib.request.urlopen", bridge_mock))
    # Git metadata
    if git_metadata:
        patches.append(patch("ibkr_operator._git_metadata", return_value=git_metadata))
    # Subprocess
    sub_outputs = {}
    if worktree is not None:
        sub_outputs["status --porcelain"] = (0, "\n".join(worktree.get("dirty_files", [])))
    else:
        sub_outputs["status --porcelain"] = (0, "")
    if tags is not None:
        sub_outputs["tag"] = (0, "\n".join(tags.get("present", [])))
    if origin is not None:
        local = origin.get("local_master_commit", "abc1234")
        remote = origin.get("origin_master_commit", "abc1234")
        sub_outputs["rev-parse --short master"] = (0, local)
        sub_outputs["rev-parse --short origin/master"] = (0, remote)
        sub_outputs["merge-base --is-ancestor"] = (0, "")
    sub_outputs["systemctl is-active"] = (0, "active")
    sub_outputs["pgrep -c -f uvicorn"] = (0, "1")
    sub_outputs["rev-parse HEAD"] = (0, "abc1234abc1234abc1234abc1234abc1234abc")
    patches.append(patch("subprocess.run", side_effect=_mock_subprocess_output(sub_outputs)))
    # Guard state
    tmp_openclaw = Path(tempfile.mkdtemp())
    if guard_state_content is not None:
        (tmp_openclaw / "guard-state.json").write_text(guard_state_content)
    patches.append(patch("ibkr_operator.OPENCLAW_DIR", tmp_openclaw))
    tmp_export = Path(tempfile.mkdtemp())
    patches.append(patch("ibkr_operator._PHASE16B_EXPORT_DIR", tmp_export))
    # Safety
    if env_safety:
        patches.append(patch("ibkr_operator._read_env_safety", return_value=env_safety))
    if rules:
        patches.append(patch("ibkr_operator._read_rules_enforced", return_value=rules))
    if autonomy:
        patches.append(patch("ibkr_operator._read_autonomy_level", return_value=autonomy))
    if doctor:
        patches.append(patch("ibkr_operator.run_doctor", return_value=doctor))
    if kpi:
        patches.append(patch("ibkr_operator.run_kpi", return_value=kpi))
    if policy:
        patches.append(patch("ibkr_operator._check_hermes_policy", return_value=policy))
    return patches


def apply_patches(patches):
    mocks = [p.start() for p in patches]
    return mocks, patches


def stop_patches(mocks, patches):
    for p in patches:
        try:
            p.stop()
        except RuntimeError:
            pass


# ===========================================================================
# T1: Command exists
# ===========================================================================

class TestCommandExists:
    def test_primary_command_registered(self):
        r = subprocess.run(
            [sys.executable, str(BRIDGE_DIR / "ibkr_operator.py"),
             "manual-level1-promotion-review", "--help"],
            capture_output=True, text=True, timeout=10,
        )
        assert r.returncode == 0, f"help failed: {r.stderr}"

    @pytest.mark.parametrize("alias", [
        "level1-promotion-review",
        "promotion-procedure-review",
        "phase16b-promotion-review",
    ])
    def test_alias_registered(self, alias):
        r = subprocess.run(
            [sys.executable, str(BRIDGE_DIR / "ibkr_operator.py"),
             alias, "--help"],
            capture_output=True, text=True, timeout=10,
        )
        assert r.returncode == 0, f"{alias} --help failed: {r.stderr}"

    def test_function_importable(self):
        assert callable(_run_manual_level1_promotion_review)


# ===========================================================================
# T2: Clean runtime => level1_promotion_review_ready / OK
# ===========================================================================

class TestCleanRuntime:
    def test_clean_runtime_produces_ok(self,
                                       clean_git_metadata,
                                       clean_worktree, origin_aligned,
                                       all_tags_present, bridge_health_ok,
                                       positions_flat, alerts_clean,
                                       snapshot_ok, readiness_locked,
                                       guard_state_clean, env_safety_locked,
                                       rules_locked, autonomy_level_zero,
                                       doctor_pass, kpi_hold_expected,
                                       hermes_policy_ok):
        patches = _build_mocks(
            health=bridge_health_ok, positions=positions_flat,
            alerts=alerts_clean, snapshot=snapshot_ok,
            readiness=readiness_locked, git_metadata=clean_git_metadata,
            worktree=clean_worktree, origin=origin_aligned,
            tags=all_tags_present, guard_state_content=guard_state_clean,
            env_safety=env_safety_locked, rules=rules_locked,
            autonomy=autonomy_level_zero, doctor=doctor_pass,
            kpi=kpi_hold_expected, policy=hermes_policy_ok,
        )
        mocks, patches = apply_patches(patches)
        try:
            result = _run_manual_level1_promotion_review()
            assert result["diagnosis"] == _PHASE16B_DIAGNOSIS["ready"]
            assert result["severity"] == "OK"
            assert result["operator_action_required"] is False
            assert result["promotion_allowed_now"] is False
            assert result["order_enablement_allowed_now"] is False
            assert result["h1_token_not_used"] is True
            assert result["no_broker_mutation"] is True
            assert result["no_order_window_opened"] is True
            assert result["evidence_hash"] is not None
            assert result["export_path"] is not None
            # Promotion plan
            pp = result["promotion_plan"]
            assert pp["review_only"] is True
            assert pp["promotion_allowed_now"] is False
            assert "Phase 16C" in pp.get("proposed_next_step", "")
            # Dry-run procedure
            drp = result["dry_run_procedure"]
            assert drp["step_count"] == 6
            assert all(s.get("performed") is False for s in drp["steps"])
            # Prerequisites
            pr = result["promotion_prerequisites"]
            assert pr["all_required_tags_present"] is True
            assert pr["runtime_ready"] is True
            assert pr["guard_state_clean"] is True
        finally:
            stop_patches(mocks, patches)


# ===========================================================================
# T3: Missing required tag => NO_GO
# ===========================================================================

class TestMissingTags:
    def test_missing_16a_tag_produces_no_go(self,
                                            clean_git_metadata,
                                            clean_worktree, origin_aligned,
                                            one_tag_missing, bridge_health_ok,
                                            positions_flat, alerts_clean,
                                            snapshot_ok, readiness_locked,
                                            guard_state_clean, env_safety_locked,
                                            rules_locked, autonomy_level_zero,
                                            doctor_pass, kpi_hold_expected,
                                            hermes_policy_ok):
        patches = _build_mocks(
            health=bridge_health_ok, positions=positions_flat,
            alerts=alerts_clean, snapshot=snapshot_ok,
            readiness=readiness_locked, git_metadata=clean_git_metadata,
            worktree=clean_worktree, origin=origin_aligned,
            tags=one_tag_missing, guard_state_content=guard_state_clean,
            env_safety=env_safety_locked, rules=rules_locked,
            autonomy=autonomy_level_zero, doctor=doctor_pass,
            kpi=kpi_hold_expected, policy=hermes_policy_ok,
        )
        mocks, patches = apply_patches(patches)
        try:
            result = _run_manual_level1_promotion_review()
            assert result["diagnosis"] == _PHASE16B_DIAGNOSIS["missing_required_tags"]
            assert result["severity"] == "NO_GO"
            assert result["operator_action_required"] is True
        finally:
            stop_patches(mocks, patches)


# ===========================================================================
# T4: Dirty worktree => NO_GO
# ===========================================================================

class TestDirtyWorktree:
    def test_dirty_worktree_produces_no_go(self,
                                           clean_git_metadata,
                                           dirty_worktree, origin_aligned,
                                           all_tags_present, bridge_health_ok,
                                           positions_flat, alerts_clean,
                                           snapshot_ok, readiness_locked,
                                           guard_state_clean, env_safety_locked,
                                           rules_locked, autonomy_level_zero,
                                           doctor_pass, kpi_hold_expected,
                                           hermes_policy_ok):
        patches = _build_mocks(
            health=bridge_health_ok, positions=positions_flat,
            alerts=alerts_clean, snapshot=snapshot_ok,
            readiness=readiness_locked, git_metadata=clean_git_metadata,
            worktree=dirty_worktree, origin=origin_aligned,
            tags=all_tags_present, guard_state_content=guard_state_clean,
            env_safety=env_safety_locked, rules=rules_locked,
            autonomy=autonomy_level_zero, doctor=doctor_pass,
            kpi=kpi_hold_expected, policy=hermes_policy_ok,
        )
        mocks, patches = apply_patches(patches)
        try:
            result = _run_manual_level1_promotion_review()
            assert result["diagnosis"] == _PHASE16B_DIAGNOSIS["dirty_worktree"]
            assert result["severity"] == "NO_GO"
        finally:
            stop_patches(mocks, patches)


# ===========================================================================
# T5: Disconnected => HOLD
# ===========================================================================

class TestDisconnected:
    def test_disconnected_produces_hold(self,
                                        clean_git_metadata,
                                        clean_worktree, origin_aligned,
                                        all_tags_present,
                                        bridge_health_disconnected,
                                        positions_flat, alerts_clean,
                                        readiness_locked, guard_state_clean,
                                        env_safety_locked, rules_locked,
                                        autonomy_level_zero,
                                        doctor_pass, kpi_hold_expected,
                                        hermes_policy_ok):
        patches = _build_mocks(
            health=bridge_health_disconnected, positions=positions_flat,
            alerts=alerts_clean, snapshot=None,
            readiness=readiness_locked, git_metadata=clean_git_metadata,
            worktree=clean_worktree, origin=origin_aligned,
            tags=all_tags_present, guard_state_content=guard_state_clean,
            env_safety=env_safety_locked, rules=rules_locked,
            autonomy=autonomy_level_zero, doctor=doctor_pass,
            kpi=kpi_hold_expected, policy=hermes_policy_ok,
        )
        mocks, patches = apply_patches(patches)
        try:
            result = _run_manual_level1_promotion_review()
            assert result["diagnosis"] == _PHASE16B_DIAGNOSIS["runtime_not_ready"]
            assert result["severity"] == "HOLD"
        finally:
            stop_patches(mocks, patches)


# ===========================================================================
# T6: Safety unlocked => NO_GO
# ===========================================================================

class TestSafetyUnlocked:
    def test_env_allow_orders_true(self, clean_git_metadata,
                                   clean_worktree, origin_aligned,
                                   all_tags_present, bridge_health_ok,
                                   positions_flat, alerts_clean,
                                   snapshot_ok, readiness_locked,
                                   guard_state_clean,
                                   env_safety_unlocked, rules_locked,
                                   autonomy_level_zero, doctor_pass,
                                   kpi_hold_expected, hermes_policy_ok):
        patches = _build_mocks(
            health=bridge_health_ok, positions=positions_flat,
            alerts=alerts_clean, snapshot=snapshot_ok,
            readiness=readiness_locked, git_metadata=clean_git_metadata,
            worktree=clean_worktree, origin=origin_aligned,
            tags=all_tags_present, guard_state_content=guard_state_clean,
            env_safety=env_safety_unlocked, rules=rules_locked,
            autonomy=autonomy_level_zero, doctor=doctor_pass,
            kpi=kpi_hold_expected, policy=hermes_policy_ok,
        )
        mocks, patches = apply_patches(patches)
        try:
            result = _run_manual_level1_promotion_review()
            assert result["diagnosis"] == _PHASE16B_DIAGNOSIS["safety_not_locked"]
            assert result["severity"] == "NO_GO"
        finally:
            stop_patches(mocks, patches)

    def test_autonomy_not_zero(self, clean_git_metadata,
                               clean_worktree, origin_aligned,
                               all_tags_present, bridge_health_ok,
                               positions_flat, alerts_clean,
                               snapshot_ok, readiness_locked,
                               guard_state_clean, env_safety_locked,
                               rules_locked, autonomy_level_one,
                               doctor_pass, kpi_hold_expected,
                               hermes_policy_ok):
        patches = _build_mocks(
            health=bridge_health_ok, positions=positions_flat,
            alerts=alerts_clean, snapshot=snapshot_ok,
            readiness=readiness_locked, git_metadata=clean_git_metadata,
            worktree=clean_worktree, origin=origin_aligned,
            tags=all_tags_present, guard_state_content=guard_state_clean,
            env_safety=env_safety_locked, rules=rules_locked,
            autonomy=autonomy_level_one, doctor=doctor_pass,
            kpi=kpi_hold_expected, policy=hermes_policy_ok,
        )
        mocks, patches = apply_patches(patches)
        try:
            result = _run_manual_level1_promotion_review()
            assert result["diagnosis"] == _PHASE16B_DIAGNOSIS["safety_not_locked"]
            assert result["severity"] == "NO_GO"
        finally:
            stop_patches(mocks, patches)


# ===========================================================================
# T7: Guard state failures => NO_GO
# ===========================================================================

class TestGuardState:
    def test_nonzero_trade_count(self, clean_git_metadata,
                                 clean_worktree, origin_aligned,
                                 all_tags_present, bridge_health_ok,
                                 positions_flat, alerts_clean,
                                 snapshot_ok, readiness_locked,
                                 guard_state_with_trades,
                                 env_safety_locked, rules_locked,
                                 autonomy_level_zero, doctor_pass,
                                 kpi_hold_expected, hermes_policy_ok):
        patches = _build_mocks(
            health=bridge_health_ok, positions=positions_flat,
            alerts=alerts_clean, snapshot=snapshot_ok,
            readiness=readiness_locked, git_metadata=clean_git_metadata,
            worktree=clean_worktree, origin=origin_aligned,
            tags=all_tags_present,
            guard_state_content=guard_state_with_trades,
            env_safety=env_safety_locked, rules=rules_locked,
            autonomy=autonomy_level_zero, doctor=doctor_pass,
            kpi=kpi_hold_expected, policy=hermes_policy_ok,
        )
        mocks, patches = apply_patches(patches)
        try:
            result = _run_manual_level1_promotion_review()
            assert result["diagnosis"] == _PHASE16B_DIAGNOSIS["guard_state_not_clean"]
            assert result["severity"] == "NO_GO"
        finally:
            stop_patches(mocks, patches)

    def test_stale_trade_date(self, clean_git_metadata,
                              clean_worktree, origin_aligned,
                              all_tags_present, bridge_health_ok,
                              positions_flat, alerts_clean,
                              snapshot_ok, readiness_locked,
                              guard_state_stale,
                              env_safety_locked, rules_locked,
                              autonomy_level_zero, doctor_pass,
                              kpi_hold_expected, hermes_policy_ok):
        patches = _build_mocks(
            health=bridge_health_ok, positions=positions_flat,
            alerts=alerts_clean, snapshot=snapshot_ok,
            readiness=readiness_locked, git_metadata=clean_git_metadata,
            worktree=clean_worktree, origin=origin_aligned,
            tags=all_tags_present,
            guard_state_content=guard_state_stale,
            env_safety=env_safety_locked, rules=rules_locked,
            autonomy=autonomy_level_zero, doctor=doctor_pass,
            kpi=kpi_hold_expected, policy=hermes_policy_ok,
        )
        mocks, patches = apply_patches(patches)
        try:
            result = _run_manual_level1_promotion_review()
            assert result["diagnosis"] == _PHASE16B_DIAGNOSIS["guard_state_not_clean"]
            assert result["severity"] == "NO_GO"
            assert result["guard_state"]["trade_date_stale"] is True
        finally:
            stop_patches(mocks, patches)


# ===========================================================================
# T8: Active alerts => NO_GO
# ===========================================================================

class TestActiveAlerts:
    def test_active_alerts_no_go(self, clean_git_metadata,
                                 clean_worktree, origin_aligned,
                                 all_tags_present, bridge_health_ok,
                                 positions_flat, alerts_active,
                                 readiness_locked, guard_state_clean,
                                 env_safety_locked, rules_locked,
                                 autonomy_level_zero, doctor_pass,
                                 kpi_hold_expected, hermes_policy_ok):
        patches = _build_mocks(
            health=bridge_health_ok, positions=positions_flat,
            alerts=alerts_active, snapshot=None,
            readiness=readiness_locked, git_metadata=clean_git_metadata,
            worktree=clean_worktree, origin=origin_aligned,
            tags=all_tags_present, guard_state_content=guard_state_clean,
            env_safety=env_safety_locked, rules=rules_locked,
            autonomy=autonomy_level_zero, doctor=doctor_pass,
            kpi=kpi_hold_expected, policy=hermes_policy_ok,
        )
        mocks, patches = apply_patches(patches)
        try:
            result = _run_manual_level1_promotion_review()
            assert result["diagnosis"] == _PHASE16B_DIAGNOSIS["monitor_alerts_active"]
            assert result["severity"] == "NO_GO"
        finally:
            stop_patches(mocks, patches)


# ===========================================================================
# T9: Positions not flat => NO_GO
# ===========================================================================

class TestPositionsNotFlat:
    def test_non_flat_positions_no_go(self, clean_git_metadata,
                                      clean_worktree, origin_aligned,
                                      all_tags_present, bridge_health_ok,
                                      positions_non_flat, alerts_clean,
                                      snapshot_ok, readiness_locked,
                                      guard_state_clean, env_safety_locked,
                                      rules_locked, autonomy_level_zero,
                                      doctor_pass, kpi_hold_expected,
                                      hermes_policy_ok):
        patches = _build_mocks(
            health=bridge_health_ok, positions=positions_non_flat,
            alerts=alerts_clean, snapshot=snapshot_ok,
            readiness=readiness_locked, git_metadata=clean_git_metadata,
            worktree=clean_worktree, origin=origin_aligned,
            tags=all_tags_present, guard_state_content=guard_state_clean,
            env_safety=env_safety_locked, rules=rules_locked,
            autonomy=autonomy_level_zero, doctor=doctor_pass,
            kpi=kpi_hold_expected, policy=hermes_policy_ok,
        )
        mocks, patches = apply_patches(patches)
        try:
            result = _run_manual_level1_promotion_review()
            assert result["diagnosis"] == _PHASE16B_DIAGNOSIS["positions_not_flat"]
            assert result["severity"] == "NO_GO"
        finally:
            stop_patches(mocks, patches)


# ===========================================================================
# T10: Promotion flags always false
# ===========================================================================

class TestPromotionFlags:
    def test_flags_false_clean(self, clean_git_metadata,
                               clean_worktree, origin_aligned,
                               all_tags_present, bridge_health_ok,
                               positions_flat, alerts_clean,
                               snapshot_ok, readiness_locked,
                               guard_state_clean, env_safety_locked,
                               rules_locked, autonomy_level_zero,
                               doctor_pass, kpi_hold_expected,
                               hermes_policy_ok):
        patches = _build_mocks(
            health=bridge_health_ok, positions=positions_flat,
            alerts=alerts_clean, snapshot=snapshot_ok,
            readiness=readiness_locked, git_metadata=clean_git_metadata,
            worktree=clean_worktree, origin=origin_aligned,
            tags=all_tags_present, guard_state_content=guard_state_clean,
            env_safety=env_safety_locked, rules=rules_locked,
            autonomy=autonomy_level_zero, doctor=doctor_pass,
            kpi=kpi_hold_expected, policy=hermes_policy_ok,
        )
        mocks, patches = apply_patches(patches)
        try:
            result = _run_manual_level1_promotion_review()
            assert result["promotion_allowed_now"] is False
            assert result["order_enablement_allowed_now"] is False
        finally:
            stop_patches(mocks, patches)


# ===========================================================================
# T11: JSON stdout pure
# ===========================================================================

class TestJsonOutput:
    def test_json_parseable(self, clean_git_metadata,
                            clean_worktree, origin_aligned,
                            all_tags_present, bridge_health_ok,
                            positions_flat, alerts_clean,
                            snapshot_ok, readiness_locked,
                            guard_state_clean, env_safety_locked,
                            rules_locked, autonomy_level_zero,
                            doctor_pass, kpi_hold_expected,
                            hermes_policy_ok):
        patches = _build_mocks(
            health=bridge_health_ok, positions=positions_flat,
            alerts=alerts_clean, snapshot=snapshot_ok,
            readiness=readiness_locked, git_metadata=clean_git_metadata,
            worktree=clean_worktree, origin=origin_aligned,
            tags=all_tags_present, guard_state_content=guard_state_clean,
            env_safety=env_safety_locked, rules=rules_locked,
            autonomy=autonomy_level_zero, doctor=doctor_pass,
            kpi=kpi_hold_expected, policy=hermes_policy_ok,
        )
        mocks, patches = apply_patches(patches)
        try:
            result = _run_manual_level1_promotion_review()
            serialized = json.dumps(result, indent=2, default=str)
            parsed = json.loads(serialized)
            assert parsed["review_id"] == result["review_id"]
        finally:
            stop_patches(mocks, patches)


# ===========================================================================
# T12: Export written
# ===========================================================================

class TestExportWritten:
    def test_export_file_exists(self, clean_git_metadata,
                                clean_worktree, origin_aligned,
                                all_tags_present, bridge_health_ok,
                                positions_flat, alerts_clean,
                                snapshot_ok, readiness_locked,
                                guard_state_clean, env_safety_locked,
                                rules_locked, autonomy_level_zero,
                                doctor_pass, kpi_hold_expected,
                                hermes_policy_ok):
        patches = _build_mocks(
            health=bridge_health_ok, positions=positions_flat,
            alerts=alerts_clean, snapshot=snapshot_ok,
            readiness=readiness_locked, git_metadata=clean_git_metadata,
            worktree=clean_worktree, origin=origin_aligned,
            tags=all_tags_present, guard_state_content=guard_state_clean,
            env_safety=env_safety_locked, rules=rules_locked,
            autonomy=autonomy_level_zero, doctor=doctor_pass,
            kpi=kpi_hold_expected, policy=hermes_policy_ok,
        )
        mocks, patches = apply_patches(patches)
        try:
            result = _run_manual_level1_promotion_review()
            assert result["export_path"] is not None
            assert os.path.exists(result["export_path"])
        finally:
            stop_patches(mocks, patches)


# ===========================================================================
# T13: No /order* calls
# ===========================================================================

class TestNoOrderEndpoints:
    FORBIDDEN = {"/order", "/order/preflight", "/order/approve", "/order/submit", "/connect"}

    def test_no_forbidden_endpoints(self):
        import ast
        source = (BRIDGE_DIR / "ibkr_operator.py").read_text()
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "_run_manual_level1_promotion_review":
                violations = []
                for subnode in ast.walk(node):
                    if isinstance(subnode, ast.Constant) and isinstance(subnode.value, str):
                        for fb in self.FORBIDDEN:
                            if fb in subnode.value:
                                lower = subnode.value.lower()
                                if any(kw in lower for kw in ["no " + fb, "forbidden", "must not", "never call"]):
                                    continue
                                violations.append(f"{fb} in: {subnode.value[:80]}")
                assert len(violations) == 0, f"Forbidden endpoints: {violations}"
                return
        pytest.fail("Could not find review function")


# ===========================================================================
# T14: No H1 token
# ===========================================================================

class TestNoH1Token:
    def test_h1_not_used(self, clean_git_metadata,
                          clean_worktree, origin_aligned,
                          all_tags_present, bridge_health_ok,
                          positions_flat, alerts_clean,
                          snapshot_ok, readiness_locked,
                          guard_state_clean, env_safety_locked,
                          rules_locked, autonomy_level_zero,
                          doctor_pass, kpi_hold_expected,
                          hermes_policy_ok):
        patches = _build_mocks(
            health=bridge_health_ok, positions=positions_flat,
            alerts=alerts_clean, snapshot=snapshot_ok,
            readiness=readiness_locked, git_metadata=clean_git_metadata,
            worktree=clean_worktree, origin=origin_aligned,
            tags=all_tags_present, guard_state_content=guard_state_clean,
            env_safety=env_safety_locked, rules=rules_locked,
            autonomy=autonomy_level_zero, doctor=doctor_pass,
            kpi=kpi_hold_expected, policy=hermes_policy_ok,
        )
        mocks, patches = apply_patches(patches)
        try:
            result = _run_manual_level1_promotion_review()
            assert result["h1_token_not_used"] is True
        finally:
            stop_patches(mocks, patches)


# ===========================================================================
# T15: No mutation except export
# ===========================================================================

class TestNoMutation:
    def test_no_mutation(self, clean_git_metadata,
                         clean_worktree, origin_aligned,
                         all_tags_present, bridge_health_ok,
                         positions_flat, alerts_clean,
                         snapshot_ok, readiness_locked,
                         guard_state_clean, env_safety_locked,
                         rules_locked, autonomy_level_zero,
                         doctor_pass, kpi_hold_expected,
                         hermes_policy_ok):
        patches = _build_mocks(
            health=bridge_health_ok, positions=positions_flat,
            alerts=alerts_clean, snapshot=snapshot_ok,
            readiness=readiness_locked, git_metadata=clean_git_metadata,
            worktree=clean_worktree, origin=origin_aligned,
            tags=all_tags_present, guard_state_content=guard_state_clean,
            env_safety=env_safety_locked, rules=rules_locked,
            autonomy=autonomy_level_zero, doctor=doctor_pass,
            kpi=kpi_hold_expected, policy=hermes_policy_ok,
        )
        mocks, patches = apply_patches(patches)
        try:
            result = _run_manual_level1_promotion_review()
            assert result["no_broker_mutation"] is True
            assert result["no_order_window_opened"] is True
            assert isinstance(result.get("explicit_non_actions"), list)
            assert len(result["explicit_non_actions"]) >= 5
        finally:
            stop_patches(mocks, patches)
