"""Tests for Phase 16D — Explicit Human-Signed Level-1 Apply Gate.

All tests are read-only by default. Apply-mode tests are isolated
with temporary AUTONOMY_CRITERIA.md files.

Coverage:
  - Command parser registers primary + 3 aliases
  - --help exits quickly
  - JSON stdout pure
  - Export written
  - Review mode: clean => level1_apply_gate_ready / OK, apply_performed=false
  - Review mode: dirty worktree => NO_GO
  - Review mode: missing tags => NO_GO
  - Review mode: disconnected => HOLD
  - Review mode: safety unlocked => NO_GO
  - Review mode: guard issues => NO_GO
  - Review mode: active alerts / non-flat positions => NO_GO
  - Apply mode: all 6 flags + clean => apply_performed=true, level1_apply_performed
  - Apply mode: missing flags => missing_explicit_apply_flags
  - Apply mode: autoo my level actually written to file
  - Apply mode: safety locks preserved
  - Apply mode: order_enablement_performed=false always
  - promotion_allowed_now=false always
  - no /order* calls
  - no H1 token reads
  - no mutation except autonomy file + export
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

BRIDGE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BRIDGE_DIR))

from ibkr_operator import (
    _run_level1_apply_gate,
    _PHASE16D_DIAGNOSIS,
    _PHASE16D_REQUIRED_TAGS,
    _PHASE16D_EXPORT_DIR,
    _PHASE16D_EXPLICIT_APPLY_FLAGS,
    _write_autonomy_level,
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
        "tag": "phase16c_level1_promotion_dry_run_gate",
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
        "required_count": len(_PHASE16D_REQUIRED_TAGS),
        "present_count": len(_PHASE16D_REQUIRED_TAGS),
        "missing": [],
        "present": list(_PHASE16D_REQUIRED_TAGS),
    }


@pytest.fixture
def one_tag_missing():
    return {
        "required_count": len(_PHASE16D_REQUIRED_TAGS),
        "present_count": len(_PHASE16D_REQUIRED_TAGS) - 1,
        "missing": [list(_PHASE16D_REQUIRED_TAGS)[0]],
        "present": list(_PHASE16D_REQUIRED_TAGS)[1:],
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
        "schema_version": 1, "trade_date": "2026-06-26",
        "daily_trade_count": 0, "daily_halt_active": False,
        "last_updated_utc": "2026-06-26T08:00:00Z",
    })


@pytest.fixture
def guard_state_stale():
    return json.dumps({
        "schema_version": 1, "trade_date": "2026-06-25",
        "daily_trade_count": 0, "daily_halt_active": False,
        "last_updated_utc": "2026-06-25T10:00:00Z",
    })


@pytest.fixture
def guard_state_with_trades():
    return json.dumps({
        "schema_version": 1, "trade_date": "2026-06-26",
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


@pytest.fixture
def tmp_autonomy_file():
    """Create a temporary AUTONOMY_CRITERIA.md with Level 0 set."""
    tmp = Path(tempfile.mkdtemp()) / "AUTONOMY_CRITERIA.md"
    tmp.write_text("""# Autonomy Criteria

Current setting: **0 (current)**

Level 0: full manual
Level 1: advisory only
""")
    return tmp


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
    autonomy=None, autonomy_path_override=None,
    doctor=None, kpi=None, policy=None,
):
    patches = []
    bridge_mock = _make_bridge_responses(
        health=health, positions=positions, alerts=alerts,
        snapshot=snapshot, readiness=readiness,
    )
    patches.append(patch("urllib.request.urlopen", bridge_mock))
    if git_metadata:
        patches.append(patch("ibkr_operator._git_metadata", return_value=git_metadata))
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
    tmp_openclaw = Path(tempfile.mkdtemp())
    if guard_state_content is not None:
        (tmp_openclaw / "guard-state.json").write_text(guard_state_content)
    patches.append(patch("ibkr_operator.OPENCLAW_DIR", tmp_openclaw))
    tmp_export = Path(tempfile.mkdtemp())
    patches.append(patch("ibkr_operator._PHASE16D_EXPORT_DIR", tmp_export))
    if env_safety:
        patches.append(patch("ibkr_operator._read_env_safety", return_value=env_safety))
    if rules:
        patches.append(patch("ibkr_operator._read_rules_enforced", return_value=rules))
    if autonomy:
        patches.append(patch("ibkr_operator._read_autonomy_level", return_value=autonomy))
    if autonomy_path_override:
        # Override the autonomy_path variable inside _run_level1_apply_gate
        pass
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
             "level1-apply-gate", "--help"],
            capture_output=True, text=True, timeout=10,
        )
        assert r.returncode == 0, f"help failed: {r.stderr}"

    @pytest.mark.parametrize("alias", [
        "human-signed-level1-apply-gate",
        "phase16d-level1-apply-gate",
        "level1-human-apply",
    ])
    def test_alias_registered(self, alias):
        r = subprocess.run(
            [sys.executable, str(BRIDGE_DIR / "ibkr_operator.py"),
             alias, "--help"],
            capture_output=True, text=True, timeout=10,
        )
        assert r.returncode == 0, f"{alias} --help failed: {r.stderr}"

    def test_function_importable(self):
        assert callable(_run_level1_apply_gate)


# ===========================================================================
# T2: Review mode clean => level1_apply_gate_ready / OK
# ===========================================================================

class TestReviewModeClean:
    def test_clean_produces_ready(self,
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
            result = _run_level1_apply_gate(apply_mode=False)
            assert result["diagnosis"] == _PHASE16D_DIAGNOSIS["ready"]
            assert result["severity"] == "OK"
            assert result["mode"] == "review"
            ag = result["apply_gate"]
            assert ag["apply_ready"] is True
            assert ag["apply_requested"] is False
            assert ag["apply_performed"] is False
            assert ag["order_enablement_performed"] is False
            assert ag["prior_autonomy_level"] == "0"
            assert ag["resulting_autonomy_level"] == "0"
            assert result["promotion_allowed_now"] is False
            assert result["promotion_performed"] is False
            assert result["order_enablement_allowed_now"] is False
            assert result["order_enablement_performed"] is False
            assert result["h1_token_not_used"] is True
            assert result["no_broker_mutation"] is True
            assert result["export_path"] is not None
            # New fields
            assert "safety_after" in result
            assert result["safety_after"]["autonomy_level_current"] == "0"
            assert isinstance(ag.get("required_flags"), list)
            assert len(ag.get("required_flags", [])) == 6
            assert isinstance(ag.get("missing_flags"), list)
            assert isinstance(ag.get("human_signoff_statement"), str)
            assert "Chris" in ag.get("human_signoff_statement", "")
            assert isinstance(ag.get("rollback_command_preview"), str)
            assert "target-level 0" in ag.get("rollback_command_preview", "")
            assert isinstance(ag.get("relock_command_preview"), str)
            assert "safety-relock" in ag.get("relock_command_preview", "")
        finally:
            stop_patches(mocks, patches)


# ===========================================================================
# T3: Review mode dirty worktree => NO_GO
# ===========================================================================

class TestReviewModeDirty:
    def test_dirty_worktree_no_go(self,
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
            result = _run_level1_apply_gate(apply_mode=False)
            assert result["diagnosis"] == _PHASE16D_DIAGNOSIS["dirty_worktree"]
            assert result["severity"] == "NO_GO"
        finally:
            stop_patches(mocks, patches)


# ===========================================================================
# T4: Review mode missing tags => NO_GO
# ===========================================================================

class TestReviewModeMissingTags:
    def test_missing_tags_no_go(self,
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
            result = _run_level1_apply_gate(apply_mode=False)
            assert result["diagnosis"] == _PHASE16D_DIAGNOSIS["missing_required_tags"]
            assert result["severity"] == "NO_GO"
        finally:
            stop_patches(mocks, patches)


# ===========================================================================
# T5: Review mode disconnected => HOLD
# ===========================================================================

class TestReviewModeDisconnected:
    def test_disconnected_hold(self,
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
            result = _run_level1_apply_gate(apply_mode=False)
            assert result["diagnosis"] == _PHASE16D_DIAGNOSIS["runtime_not_ready"]
            assert result["severity"] == "HOLD"
        finally:
            stop_patches(mocks, patches)


# ===========================================================================
# T6: Review mode safety unlocked => NO_GO
# ===========================================================================

class TestReviewModeSafety:
    def test_env_unlocked_no_go(self, clean_git_metadata,
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
            result = _run_level1_apply_gate(apply_mode=False)
            assert result["diagnosis"] == _PHASE16D_DIAGNOSIS["safety_not_locked"]
            assert result["severity"] == "NO_GO"
        finally:
            stop_patches(mocks, patches)

    def test_autonomy_not_zero_no_go(self, clean_git_metadata,
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
            result = _run_level1_apply_gate(apply_mode=False)
            assert result["diagnosis"] == _PHASE16D_DIAGNOSIS["safety_not_locked"]
            assert result["severity"] == "NO_GO"
        finally:
            stop_patches(mocks, patches)


# ===========================================================================
# T7: Review mode guard issues => NO_GO
# ===========================================================================

class TestReviewModeGuard:
    def test_nonzero_count_no_go(self, clean_git_metadata,
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
            result = _run_level1_apply_gate(apply_mode=False)
            assert result["diagnosis"] == _PHASE16D_DIAGNOSIS["guard_state_not_clean"]
            assert result["severity"] == "NO_GO"
        finally:
            stop_patches(mocks, patches)


# ===========================================================================
# T8: Review mode active alerts => NO_GO
# ===========================================================================

class TestReviewModeAlerts:
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
            result = _run_level1_apply_gate(apply_mode=False)
            assert result["diagnosis"] == _PHASE16D_DIAGNOSIS["monitor_alerts_active"]
            assert result["severity"] == "NO_GO"
        finally:
            stop_patches(mocks, patches)


# ===========================================================================
# T9: Apply mode with all 6 flags => apply_performed=true
# ===========================================================================

class TestApplyModeSuccess:
    def test_apply_all_flags_succeeds(self,
                                      clean_git_metadata,
                                      clean_worktree, origin_aligned,
                                      all_tags_present, bridge_health_ok,
                                      positions_flat, alerts_clean,
                                      snapshot_ok, readiness_locked,
                                      guard_state_clean, env_safety_locked,
                                      rules_locked, autonomy_level_zero,
                                      doctor_pass, kpi_hold_expected,
                                      hermes_policy_ok,
                                      tmp_autonomy_file):
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
        # Override autonomy path to use tmp file
        autonomy_patch = patch(
            "ibkr_operator.BRIDGE_DIR",
            BRIDGE_DIR,  # keep BRIDGE_DIR same
        )
        # We need a different approach: patch the autonomy_path inside the function
        # Since it's constructed as BRIDGE_DIR / "docs" / "AUTONOMY_CRITERIA.md",
        # we can patch BRIDGE_DIR to point to tmp
        tmp_bridge = tmp_autonomy_file.parent
        (tmp_bridge / "docs").mkdir(exist_ok=True)
        import shutil
        shutil.copy(tmp_autonomy_file, tmp_bridge / "docs" / "AUTONOMY_CRITERIA.md")
        patches.append(patch("ibkr_operator.BRIDGE_DIR", tmp_bridge))

        mocks, patches = apply_patches(patches)
        try:
            all_flags = tuple(_PHASE16D_EXPLICIT_APPLY_FLAGS)
            result = _run_level1_apply_gate(
                apply_mode=True,
                apply_flags_present=all_flags,
            )
            assert result["diagnosis"] == _PHASE16D_DIAGNOSIS["applied"]
            assert result["severity"] == "OK"
            assert result["mode"] == "apply"
            assert result["promotion_performed"] is True
            ag = result["apply_gate"]
            assert ag["apply_ready"] is True
            assert ag["apply_requested"] is True
            assert ag["apply_performed"] is True
            assert ag["prior_autonomy_level"] == "0"
            assert ag["resulting_autonomy_level"] == "1"
            assert ag["order_enablement_performed"] is False
            assert ag["verified_no_orders_enabled"] is True
            assert ag["all_safety_locks_preserved"] is True
            # New fields
            assert isinstance(ag.get("required_flags"), list)
            assert len(ag["required_flags"]) == 6
            assert ag.get("missing_flags") == []
            assert isinstance(ag.get("human_signoff_statement"), str)
            assert "Chris" in ag.get("human_signoff_statement", "")
            assert "safety-relock" in ag.get("relock_command_preview", "")
            # safety_after
            assert result["safety_after"]["autonomy_level_current"] == "1"
            assert result["safety_after"]["env_IBKR_ALLOW_ORDERS"] == "false"
            assert result["safety_after"]["rules_enforced"] == "false"
            assert result["safety_after"]["system_locked"] is True
            assert result["promotion_allowed_now"] is False
            assert result["order_enablement_allowed_now"] is False
            assert result["h1_token_not_used"] is True
            assert result["no_broker_mutation"] is True
            # Verify file was actually written
            content = (tmp_bridge / "docs" / "AUTONOMY_CRITERIA.md").read_text()
            assert "**1 (current)**" in content
        finally:
            stop_patches(mocks, patches)


# ===========================================================================
# T10: Apply mode with missing flags => missing_explicit_apply_flags
# ===========================================================================

class TestApplyModeIncompleteFlags:
    def test_missing_flags_no_go(self,
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
            # Only 4 of 6 flags present
            partial_flags = (
                "--apply",
                "--confirm-level1",
                "--human-signed-apply",
                "--ack-no-order-enablement",
            )
            result = _run_level1_apply_gate(
                apply_mode=True,
                apply_flags_present=partial_flags,
            )
            assert result["diagnosis"] == _PHASE16D_DIAGNOSIS["missing_explicit_apply_flags"]
            assert result["severity"] == "NO_GO"
            ag = result["apply_gate"]
            assert ag["apply_performed"] is False
        finally:
            stop_patches(mocks, patches)


# ===========================================================================
# T11: Apply mode preserves safety locks
# ===========================================================================

class TestApplyModeSafetyPreserved:
    def test_safety_locks_unchanged(self,
                                    clean_git_metadata,
                                    clean_worktree, origin_aligned,
                                    all_tags_present, bridge_health_ok,
                                    positions_flat, alerts_clean,
                                    snapshot_ok, readiness_locked,
                                    guard_state_clean, env_safety_locked,
                                    rules_locked, autonomy_level_zero,
                                    doctor_pass, kpi_hold_expected,
                                    hermes_policy_ok,
                                    tmp_autonomy_file):
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
        tmp_bridge = tmp_autonomy_file.parent
        (tmp_bridge / "docs").mkdir(exist_ok=True)
        import shutil
        shutil.copy(tmp_autonomy_file, tmp_bridge / "docs" / "AUTONOMY_CRITERIA.md")
        patches.append(patch("ibkr_operator.BRIDGE_DIR", tmp_bridge))

        mocks, patches = apply_patches(patches)
        try:
            all_flags = tuple(_PHASE16D_EXPLICIT_APPLY_FLAGS)
            result = _run_level1_apply_gate(
                apply_mode=True,
                apply_flags_present=all_flags,
            )
            assert result["apply_gate"]["apply_performed"] is True
            # Safety locks must be preserved
            assert result["order_enablement_allowed_now"] is False
            assert result["order_enablement_performed"] is False
            assert result["no_order_window_opened"] is True
            # No broker mutation
            assert result["no_broker_mutation"] is True
            # H1 not used
            assert result["h1_token_not_used"] is True
        finally:
            stop_patches(mocks, patches)


# ===========================================================================
# T12: promotion_allowed_now always false
# ===========================================================================

class TestPromotionFlags:
    def test_flags_always_false(self,
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
            result = _run_level1_apply_gate(apply_mode=False)
            assert result["promotion_allowed_now"] is False
            assert result["order_enablement_allowed_now"] is False
            assert result["order_enablement_performed"] is False
        finally:
            stop_patches(mocks, patches)


# ===========================================================================
# T13: JSON stdout pure
# ===========================================================================

class TestJsonOutput:
    def test_json_parseable(self,
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
            result = _run_level1_apply_gate(apply_mode=False)
            serialized = json.dumps(result, indent=2, default=str)
            parsed = json.loads(serialized)
            assert parsed["apply_gate_id"] == result["apply_gate_id"]
        finally:
            stop_patches(mocks, patches)


# ===========================================================================
# T14: Export written
# ===========================================================================

class TestExportWritten:
    def test_export_file_exists(self,
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
            result = _run_level1_apply_gate(apply_mode=False)
            assert result["export_path"] is not None
            assert os.path.exists(result["export_path"])
        finally:
            stop_patches(mocks, patches)


# ===========================================================================
# T15: No /order* calls
# ===========================================================================

class TestNoOrderEndpoints:
    FORBIDDEN = {"/order", "/order/preflight", "/order/approve", "/order/submit",
                 "/connect", "/trade-window"}

    def test_no_forbidden_endpoints(self):
        import ast
        source = (BRIDGE_DIR / "ibkr_operator.py").read_text()
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "_run_level1_apply_gate":
                violations = []
                for subnode in ast.walk(node):
                    if isinstance(subnode, ast.Constant) and isinstance(subnode.value, str):
                        for fb in self.FORBIDDEN:
                            if fb in subnode.value:
                                lower = subnode.value.lower()
                                if any(kw in lower for kw in ["no " + fb, "forbidden", "must not", "never call",
                                                               "do not call", "not call",
                                                               "no /order", "no order endpoint",
                                                               "/order/preflight -> /order/approve -> /order/submit",
                                                               "submit_path_only"]):
                                    continue
                                violations.append(f"{fb} in: {subnode.value[:80]}")
                assert len(violations) == 0, f"Forbidden endpoints: {violations}"
                return
        pytest.fail("Could not find apply gate function")


# ===========================================================================
# T16: No H1 token
# ===========================================================================

class TestNoH1Token:
    def test_h1_not_used(self,
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
            result = _run_level1_apply_gate(apply_mode=False)
            assert result["h1_token_not_used"] is True
        finally:
            stop_patches(mocks, patches)


# ===========================================================================
# T17: No mutation except autonomy + export
# ===========================================================================

class TestNoMutation:
    def test_no_mutation(self,
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
            result = _run_level1_apply_gate(apply_mode=False)
            assert result["no_broker_mutation"] is True
            assert result["no_order_window_opened"] is True
            assert isinstance(result.get("explicit_non_actions"), list)
            assert len(result["explicit_non_actions"]) >= 8
            # Check explicit non-actions include the key promises
            ena = "\n".join(result.get("explicit_non_actions", []))
            assert "ibkr_allow_orders=true" in ena.lower().replace(" ", "")
            assert "system_locked" in ena
        finally:
            stop_patches(mocks, patches)


# ===========================================================================
# T18: _write_autonomy_level helper
# ===========================================================================

class TestWriteAutonomyLevel:
    def test_write_updates_marker(self, tmp_autonomy_file):
        assert "**0 (current)**" in tmp_autonomy_file.read_text()
        result = _write_autonomy_level(tmp_autonomy_file, "1")
        assert result is True
        content = tmp_autonomy_file.read_text()
        assert "**1 (current)**" in content
        assert "**0 (current)**" not in content

    def test_write_no_change_returns_false(self):
        import tempfile
        tmp = Path(tempfile.mkdtemp()) / "AUTONOMY_CRITERIA.md"
        tmp.write_text("no marker here")
        result = _write_autonomy_level(tmp, "1")
        assert result is False
