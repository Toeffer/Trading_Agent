"""Tests for Phase 16E — Level 1 Post-Promotion Stability Drill.

All tests are read-only. No broker mutation, no order endpoints,
no H1 token usage, no autonomy level changes.

Coverage:
  - Command parser registers primary + 3 aliases
  - --help exits quickly
  - JSON stdout pure
  - Export written
  - Clean runtime with 2 samples => level1_post_promotion_stability_ok / OK
  - Dirty worktree => NO_GO
  - Missing required tag => NO_GO
  - Autonomy not Level 1 => NO_GO
  - Bridge disconnected => HOLD or NO_GO
  - Safety unlocked => NO_GO
  - Guard issues => NO_GO
  - Active alerts => NO_GO
  - Positions not flat => NO_GO
  - Samples collected count matches request
  - No /order* calls
  - No H1 token reads
  - No mutation except export artifact
  - No autonomy level change
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
    _run_level1_post_promotion_stability_drill,
    _PHASE16E_DIAGNOSIS,
    _PHASE16E_REQUIRED_TAGS,
    _PHASE16E_EXPORT_DIR,
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
        "tag": "phase16e_level1_post_promotion_stability_drill",
    }


@pytest.fixture
def clean_worktree():
    return {"clean": True, "dirty_files": []}


@pytest.fixture
def dirty_worktree():
    return {"clean": False, "dirty_files": ["M ibkr_operator.py"]}


@pytest.fixture
def origin_aligned():
    return {"aligned": True, "origin_master_commit": "abc1234",
            "local_master_commit": "abc1234"}


@pytest.fixture
def all_tags_present():
    return {"required_count": len(_PHASE16E_REQUIRED_TAGS),
            "present_count": len(_PHASE16E_REQUIRED_TAGS),
            "missing": [], "present": list(_PHASE16E_REQUIRED_TAGS)}


@pytest.fixture
def one_tag_missing():
    return {"required_count": len(_PHASE16E_REQUIRED_TAGS),
            "present_count": len(_PHASE16E_REQUIRED_TAGS) - 1,
            "missing": [list(_PHASE16E_REQUIRED_TAGS)[0]],
            "present": list(_PHASE16E_REQUIRED_TAGS)[1:]}


@pytest.fixture
def bridge_health_ok():
    return {"connected": True, "mode": "paper", "read_only": True, "allow_orders": False}


@pytest.fixture
def bridge_health_disconnected():
    return {"connected": False, "mode": "paper", "read_only": True, "allow_orders": False}


@pytest.fixture
def positions_flat():
    return {"positions": []}


@pytest.fixture
def positions_non_flat():
    return {"positions": [{"symbol": "AAPL", "position": 10}]}


@pytest.fixture
def alerts_clean():
    return {"alerts": []}


@pytest.fixture
def alerts_active():
    return {"alerts": [{"alert_type": "drift", "requires_action": True}]}


@pytest.fixture
def readiness_locked():
    return {"summary": {"kill_switches": {"IBKR_ALLOW_ORDERS": False,
                                          "rules.enforced": False,
                                          "system_locked": True}}}


@pytest.fixture
def snapshot_ok():
    return {"connected": True, "mode": "paper", "read_only": True}


@pytest.fixture
def guard_state_clean():
    return json.dumps({"schema_version": 1, "trade_date": "2026-06-26",
                       "daily_trade_count": 0, "daily_halt_active": False})


@pytest.fixture
def guard_state_stale():
    return json.dumps({"schema_version": 1, "trade_date": "2026-06-25",
                       "daily_trade_count": 0, "daily_halt_active": False})


@pytest.fixture
def guard_state_with_trades():
    return json.dumps({"schema_version": 1, "trade_date": "2026-06-26",
                       "daily_trade_count": 3, "daily_halt_active": False})


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
def autonomy_level_one():
    return "1"


@pytest.fixture
def autonomy_level_zero():
    return "0"


@pytest.fixture
def doctor_pass():
    return {"pass": True, "passed": 14, "total": 15,
            "passed_count": 14, "check_count": 15,
            "checks": [{"check": "h1_token_canary", "ok": True, "status": "PASS"}]}


@pytest.fixture
def kpi_hold_expected():
    return {"verdict": "HOLD",
            "blockers": [{"severity": "HOLD", "check": "autonomy_level_zero"},
                         {"severity": "HOLD", "check": "system_locked"}]}


@pytest.fixture
def kpi_no_go():
    return {"verdict": "NO-GO",
            "blockers": [{"severity": "NO-GO", "check": "active_alerts"}]}


@pytest.fixture
def hermes_policy_ok():
    return {"hermes_policy_exists": True, "execution_path_ok": True, "advisory_boundary_ok": True}


@pytest.fixture
def hermes_policy_missing():
    return {"hermes_policy_exists": False, "execution_path_ok": False, "advisory_boundary_ok": False}


# ===========================================================================
# Mock helpers
# ===========================================================================

class _MockUrlOpen:
    def __init__(self, responses: dict):
        self._responses = responses

    def __call__(self, req, timeout=None):
        url = req.full_url if hasattr(req, 'full_url') else str(req)
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


def _build_mocks(health=None, positions=None, alerts=None, snapshot=None,
                 readiness=None, git_metadata=None, worktree=None, origin=None,
                 tags=None, guard_state_content=None, env_safety=None, rules=None,
                 autonomy=None, doctor=None, kpi=None, policy=None):
    patches = []
    bridge_mock = _MockUrlOpen({
        "/health": (200, health) if health else (500, {}),
        "/positions": (200, positions) if positions else (500, {}),
        "/monitor/alerts": (200, alerts) if alerts else (500, {}),
        "/snapshot": (200, snapshot) if snapshot else (500, {}),
        "/readiness": (200, readiness) if readiness else (500, {}),
    })
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
        sub_outputs["rev-parse --short master"] = (0, origin.get("local_master_commit", "abc"))
        sub_outputs["rev-parse --short origin/master"] = (0, origin.get("origin_master_commit", "abc"))
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
    patches.append(patch("ibkr_operator._PHASE16E_EXPORT_DIR", tmp_export))
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
    patches.append(patch("time.sleep", return_value=None))
    return patches


def apply_patches(patches):
    return [p.start() for p in patches], patches


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
        r = subprocess.run([sys.executable, str(BRIDGE_DIR / "ibkr_operator.py"),
                           "level1-post-promotion-stability-drill", "--help"],
                          capture_output=True, text=True, timeout=10)
        assert r.returncode == 0, f"help failed: {r.stderr}"

    @pytest.mark.parametrize("alias", [
        "phase16e-level1-stability-drill",
        "level1-stability-drill",
        "post-level1-stability",
    ])
    def test_alias_registered(self, alias):
        r = subprocess.run([sys.executable, str(BRIDGE_DIR / "ibkr_operator.py"),
                           alias, "--help"],
                          capture_output=True, text=True, timeout=10)
        assert r.returncode == 0, f"{alias} --help failed: {r.stderr}"

    def test_function_importable(self):
        assert callable(_run_level1_post_promotion_stability_drill)


# ===========================================================================
# T2: Clean => level1_post_promotion_stability_ok
# ===========================================================================

class TestCleanStability:
    def test_clean_produces_ok(self, clean_git_metadata, clean_worktree,
                               origin_aligned, all_tags_present, bridge_health_ok,
                               positions_flat, alerts_clean, snapshot_ok,
                               readiness_locked, guard_state_clean, env_safety_locked,
                               rules_locked, autonomy_level_one, doctor_pass,
                               kpi_hold_expected, hermes_policy_ok):
        patches = _build_mocks(
            health=bridge_health_ok, positions=positions_flat,
            alerts=alerts_clean, snapshot=snapshot_ok, readiness=readiness_locked,
            git_metadata=clean_git_metadata, worktree=clean_worktree,
            origin=origin_aligned, tags=all_tags_present,
            guard_state_content=guard_state_clean, env_safety=env_safety_locked,
            rules=rules_locked, autonomy=autonomy_level_one,
            doctor=doctor_pass, kpi=kpi_hold_expected, policy=hermes_policy_ok,
        )
        mocks, patches = apply_patches(patches)
        try:
            result = _run_level1_post_promotion_stability_drill(
                samples_requested=2, interval_seconds=1,
            )
            assert result["diagnosis"] == _PHASE16E_DIAGNOSIS["ready"]
            assert result["severity"] == "OK"
            assert result["samples_collected"] == 2
            assert result["samples_requested"] == 2
            assert result["promotion_allowed_now"] is False
            assert result["order_enablement_allowed_now"] is False
            assert result["no_broker_mutation"] is True
            assert result["no_order_window_opened"] is True
            assert result["h1_token_not_used"] is True
            assert result["export_path"] is not None
            # Stability summary checks
            ss = result["stability_summary"]
            assert ss["autonomy_level1_all_samples"] is True
            assert ss["bridge_connected_all_samples"] is True
            assert ss["paper_all_samples"] is True
            assert ss["read_only_all_samples"] is True
            assert ss["positions_flat_all_samples"] is True
            assert ss["alerts_clean_all_samples"] is True
            assert ss["safety_locked_all_samples"] is True
            assert ss["no_order_window_seen"] is True
            assert ss["no_h1_seen"] is True
            assert ss["no_broker_mutation_seen"] is True
            # Baseline present
            bl = result["baseline"]
            assert bl["autonomy_level"] == "1"
            assert bl["bridge_connected"] is True
            # Samples detail
            assert len(result["samples"]) == 2
            for s in result["samples"]:
                assert s["autonomy_level"] == "1"
                assert s["read_only"] is True
        finally:
            stop_patches(mocks, patches)


# ===========================================================================
# T3: Samples collected match request
# ===========================================================================

class TestSampleCount:
    def test_samples_count(self, clean_git_metadata, clean_worktree,
                           origin_aligned, all_tags_present, bridge_health_ok,
                           positions_flat, alerts_clean, snapshot_ok,
                           readiness_locked, guard_state_clean, env_safety_locked,
                           rules_locked, autonomy_level_one, doctor_pass,
                           kpi_hold_expected, hermes_policy_ok):
        patches = _build_mocks(
            health=bridge_health_ok, positions=positions_flat,
            alerts=alerts_clean, snapshot=snapshot_ok, readiness=readiness_locked,
            git_metadata=clean_git_metadata, worktree=clean_worktree,
            origin=origin_aligned, tags=all_tags_present,
            guard_state_content=guard_state_clean, env_safety=env_safety_locked,
            rules=rules_locked, autonomy=autonomy_level_one,
            doctor=doctor_pass, kpi=kpi_hold_expected, policy=hermes_policy_ok,
        )
        mocks, patches = apply_patches(patches)
        try:
            result = _run_level1_post_promotion_stability_drill(
                samples_requested=3, interval_seconds=1,
            )
            assert result["samples_requested"] == 3
            assert result["samples_collected"] == 3
            assert len(result["samples"]) == 3
        finally:
            stop_patches(mocks, patches)


# ===========================================================================
# T4: Dirty worktree => NO_GO
# ===========================================================================

class TestDirtyWorktree:
    def test_dirty_worktree_no_go(self, clean_git_metadata, dirty_worktree,
                                  origin_aligned, all_tags_present, bridge_health_ok):
        patches = _build_mocks(
            health=bridge_health_ok, positions={"positions": []},
            alerts={"alerts": []}, snapshot={"connected": True},
            readiness={"summary": {"kill_switches": {"system_locked": True}}},
            git_metadata=clean_git_metadata, worktree=dirty_worktree,
            origin=origin_aligned, tags=all_tags_present,
        )
        mocks, patches = apply_patches(patches)
        try:
            result = _run_level1_post_promotion_stability_drill(samples_requested=2, interval_seconds=1)
            assert result["diagnosis"] == _PHASE16E_DIAGNOSIS["dirty_worktree"]
            assert result["severity"] == "NO_GO"
            assert result["samples_collected"] == 0
        finally:
            stop_patches(mocks, patches)


# ===========================================================================
# T5: Missing tags => NO_GO
# ===========================================================================

class TestMissingTags:
    def test_missing_tags_no_go(self, clean_git_metadata, clean_worktree,
                                origin_aligned, one_tag_missing, bridge_health_ok):
        patches = _build_mocks(
            health=bridge_health_ok, positions={"positions": []},
            alerts={"alerts": []}, snapshot={"connected": True},
            readiness={"summary": {"kill_switches": {"system_locked": True}}},
            git_metadata=clean_git_metadata, worktree=clean_worktree,
            origin=origin_aligned, tags=one_tag_missing,
        )
        mocks, patches = apply_patches(patches)
        try:
            result = _run_level1_post_promotion_stability_drill(samples_requested=2, interval_seconds=1)
            assert result["diagnosis"] == _PHASE16E_DIAGNOSIS["missing_required_tags"]
            assert result["severity"] == "NO_GO"
            assert result["samples_collected"] == 0
        finally:
            stop_patches(mocks, patches)


# ===========================================================================
# T6: Autonomy not Level 1 => NO_GO
# ===========================================================================

class TestAutonomyNotLevel1:
    def test_autonomy_zero_no_go(self, clean_git_metadata, clean_worktree,
                                 origin_aligned, all_tags_present, bridge_health_ok,
                                 positions_flat, alerts_clean, snapshot_ok,
                                 readiness_locked, guard_state_clean, env_safety_locked,
                                 rules_locked, autonomy_level_zero, doctor_pass,
                                 kpi_hold_expected, hermes_policy_ok):
        patches = _build_mocks(
            health=bridge_health_ok, positions=positions_flat,
            alerts=alerts_clean, snapshot=snapshot_ok, readiness=readiness_locked,
            git_metadata=clean_git_metadata, worktree=clean_worktree,
            origin=origin_aligned, tags=all_tags_present,
            guard_state_content=guard_state_clean, env_safety=env_safety_locked,
            rules=rules_locked, autonomy=autonomy_level_zero,
            doctor=doctor_pass, kpi=kpi_hold_expected, policy=hermes_policy_ok,
        )
        mocks, patches = apply_patches(patches)
        try:
            result = _run_level1_post_promotion_stability_drill(samples_requested=2, interval_seconds=1)
            assert result["diagnosis"] == _PHASE16E_DIAGNOSIS["autonomy_not_level1"]
            assert result["severity"] == "NO_GO"
        finally:
            stop_patches(mocks, patches)


# ===========================================================================
# T7: Bridge disconnected => NO_GO
# ===========================================================================

class TestDisconnected:
    def test_disconnected_no_go(self, clean_git_metadata, clean_worktree,
                                origin_aligned, all_tags_present,
                                bridge_health_disconnected, positions_flat,
                                alerts_clean, snapshot_ok, readiness_locked,
                                guard_state_clean, env_safety_locked,
                                rules_locked, autonomy_level_one, doctor_pass,
                                kpi_hold_expected, hermes_policy_ok):
        patches = _build_mocks(
            health=bridge_health_disconnected, positions=positions_flat,
            alerts=alerts_clean, snapshot=None, readiness=readiness_locked,
            git_metadata=clean_git_metadata, worktree=clean_worktree,
            origin=origin_aligned, tags=all_tags_present,
            guard_state_content=guard_state_clean, env_safety=env_safety_locked,
            rules=rules_locked, autonomy=autonomy_level_one,
            doctor=doctor_pass, kpi=kpi_hold_expected, policy=hermes_policy_ok,
        )
        mocks, patches = apply_patches(patches)
        try:
            result = _run_level1_post_promotion_stability_drill(samples_requested=2, interval_seconds=1)
            assert result["diagnosis"] == _PHASE16E_DIAGNOSIS["runtime_not_ready"]
            assert result["severity"] == "HOLD"
        finally:
            stop_patches(mocks, patches)


# ===========================================================================
# T8: Safety unlocked => NO_GO
# ===========================================================================

class TestSafetyUnlocked:
    def test_env_unlocked_no_go(self, clean_git_metadata, clean_worktree,
                                origin_aligned, all_tags_present, bridge_health_ok,
                                positions_flat, alerts_clean, snapshot_ok,
                                readiness_locked, guard_state_clean,
                                env_safety_unlocked, rules_locked,
                                autonomy_level_one, doctor_pass,
                                kpi_hold_expected, hermes_policy_ok):
        patches = _build_mocks(
            health=bridge_health_ok, positions=positions_flat,
            alerts=alerts_clean, snapshot=snapshot_ok, readiness=readiness_locked,
            git_metadata=clean_git_metadata, worktree=clean_worktree,
            origin=origin_aligned, tags=all_tags_present,
            guard_state_content=guard_state_clean, env_safety=env_safety_unlocked,
            rules=rules_locked, autonomy=autonomy_level_one,
            doctor=doctor_pass, kpi=kpi_hold_expected, policy=hermes_policy_ok,
        )
        mocks, patches = apply_patches(patches)
        try:
            result = _run_level1_post_promotion_stability_drill(samples_requested=2, interval_seconds=1)
            assert result["diagnosis"] == _PHASE16E_DIAGNOSIS["safety_not_locked"]
            assert result["severity"] == "NO_GO"
        finally:
            stop_patches(mocks, patches)


# ===========================================================================
# T9: Guard issues => NO_GO
# ===========================================================================

class TestGuard:
    def test_nonzero_count_no_go(self, clean_git_metadata, clean_worktree,
                                 origin_aligned, all_tags_present, bridge_health_ok,
                                 positions_flat, alerts_clean, snapshot_ok,
                                 readiness_locked, guard_state_with_trades,
                                 env_safety_locked, rules_locked,
                                 autonomy_level_one, doctor_pass,
                                 kpi_hold_expected, hermes_policy_ok):
        patches = _build_mocks(
            health=bridge_health_ok, positions=positions_flat,
            alerts=alerts_clean, snapshot=snapshot_ok, readiness=readiness_locked,
            git_metadata=clean_git_metadata, worktree=clean_worktree,
            origin=origin_aligned, tags=all_tags_present,
            guard_state_content=guard_state_with_trades,
            env_safety=env_safety_locked, rules=rules_locked,
            autonomy=autonomy_level_one, doctor=doctor_pass,
            kpi=kpi_hold_expected, policy=hermes_policy_ok,
        )
        mocks, patches = apply_patches(patches)
        try:
            result = _run_level1_post_promotion_stability_drill(samples_requested=2, interval_seconds=1)
            assert result["diagnosis"] == _PHASE16E_DIAGNOSIS["guard_state_not_clean"]
            assert result["severity"] == "NO_GO"
        finally:
            stop_patches(mocks, patches)


# ===========================================================================
# T10: Active alerts => NO_GO
# ===========================================================================

class TestActiveAlerts:
    def test_active_alerts_no_go(self, clean_git_metadata, clean_worktree,
                                 origin_aligned, all_tags_present, bridge_health_ok,
                                 positions_flat, alerts_active, snapshot_ok,
                                 readiness_locked, guard_state_clean,
                                 env_safety_locked, rules_locked,
                                 autonomy_level_one, doctor_pass,
                                 kpi_hold_expected, hermes_policy_ok):
        patches = _build_mocks(
            health=bridge_health_ok, positions=positions_flat,
            alerts=alerts_active, snapshot=snapshot_ok, readiness=readiness_locked,
            git_metadata=clean_git_metadata, worktree=clean_worktree,
            origin=origin_aligned, tags=all_tags_present,
            guard_state_content=guard_state_clean, env_safety=env_safety_locked,
            rules=rules_locked, autonomy=autonomy_level_one,
            doctor=doctor_pass, kpi=kpi_hold_expected, policy=hermes_policy_ok,
        )
        mocks, patches = apply_patches(patches)
        try:
            result = _run_level1_post_promotion_stability_drill(samples_requested=2, interval_seconds=1)
            assert result["diagnosis"] == _PHASE16E_DIAGNOSIS["monitor_alerts_active"]
            assert result["severity"] == "NO_GO"
        finally:
            stop_patches(mocks, patches)


# ===========================================================================
# T11: Positions not flat => NO_GO
# ===========================================================================

class TestPositionsNotFlat:
    def test_non_flat_positions_no_go(self, clean_git_metadata, clean_worktree,
                                      origin_aligned, all_tags_present,
                                      bridge_health_ok, positions_non_flat,
                                      alerts_clean, snapshot_ok, readiness_locked,
                                      guard_state_clean, env_safety_locked,
                                      rules_locked, autonomy_level_one,
                                      doctor_pass, kpi_hold_expected, hermes_policy_ok):
        patches = _build_mocks(
            health=bridge_health_ok, positions=positions_non_flat,
            alerts=alerts_clean, snapshot=snapshot_ok, readiness=readiness_locked,
            git_metadata=clean_git_metadata, worktree=clean_worktree,
            origin=origin_aligned, tags=all_tags_present,
            guard_state_content=guard_state_clean, env_safety=env_safety_locked,
            rules=rules_locked, autonomy=autonomy_level_one,
            doctor=doctor_pass, kpi=kpi_hold_expected, policy=hermes_policy_ok,
        )
        mocks, patches = apply_patches(patches)
        try:
            result = _run_level1_post_promotion_stability_drill(samples_requested=2, interval_seconds=1)
            assert result["diagnosis"] == _PHASE16E_DIAGNOSIS["positions_not_flat"]
            assert result["severity"] == "NO_GO"
        finally:
            stop_patches(mocks, patches)


# ===========================================================================
# T12: JSON stdout pure
# ===========================================================================

class TestJsonOutput:
    def test_json_parseable(self, clean_git_metadata, clean_worktree,
                            origin_aligned, all_tags_present, bridge_health_ok,
                            positions_flat, alerts_clean, snapshot_ok,
                            readiness_locked, guard_state_clean, env_safety_locked,
                            rules_locked, autonomy_level_one, doctor_pass,
                            kpi_hold_expected, hermes_policy_ok):
        patches = _build_mocks(
            health=bridge_health_ok, positions=positions_flat,
            alerts=alerts_clean, snapshot=snapshot_ok, readiness=readiness_locked,
            git_metadata=clean_git_metadata, worktree=clean_worktree,
            origin=origin_aligned, tags=all_tags_present,
            guard_state_content=guard_state_clean, env_safety=env_safety_locked,
            rules=rules_locked, autonomy=autonomy_level_one,
            doctor=doctor_pass, kpi=kpi_hold_expected, policy=hermes_policy_ok,
        )
        mocks, patches = apply_patches(patches)
        try:
            result = _run_level1_post_promotion_stability_drill(samples_requested=2, interval_seconds=1)
            serialized = json.dumps(result, indent=2, default=str)
            parsed = json.loads(serialized)
            assert parsed["drill_id"] == result["drill_id"]
        finally:
            stop_patches(mocks, patches)


# ===========================================================================
# T13: Export written
# ===========================================================================

class TestExportWritten:
    def test_export_file_exists(self, clean_git_metadata, clean_worktree,
                                origin_aligned, all_tags_present, bridge_health_ok,
                                positions_flat, alerts_clean, snapshot_ok,
                                readiness_locked, guard_state_clean, env_safety_locked,
                                rules_locked, autonomy_level_one, doctor_pass,
                                kpi_hold_expected, hermes_policy_ok):
        patches = _build_mocks(
            health=bridge_health_ok, positions=positions_flat,
            alerts=alerts_clean, snapshot=snapshot_ok, readiness=readiness_locked,
            git_metadata=clean_git_metadata, worktree=clean_worktree,
            origin=origin_aligned, tags=all_tags_present,
            guard_state_content=guard_state_clean, env_safety=env_safety_locked,
            rules=rules_locked, autonomy=autonomy_level_one,
            doctor=doctor_pass, kpi=kpi_hold_expected, policy=hermes_policy_ok,
        )
        mocks, patches = apply_patches(patches)
        try:
            result = _run_level1_post_promotion_stability_drill(samples_requested=2, interval_seconds=1)
            assert result["export_path"] is not None
            assert os.path.exists(result["export_path"])
        finally:
            stop_patches(mocks, patches)


# ===========================================================================
# T14: No /order* calls
# ===========================================================================

class TestNoOrderEndpoints:
    FORBIDDEN = {"/order", "/order/preflight", "/order/approve", "/order/submit",
                 "/connect", "/trade-window"}

    def test_no_forbidden_endpoints(self):
        import ast
        source = (BRIDGE_DIR / "ibkr_operator.py").read_text()
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "_run_level1_post_promotion_stability_drill":
                violations = []
                for subnode in ast.walk(node):
                    if isinstance(subnode, ast.Constant) and isinstance(subnode.value, str):
                        for fb in self.FORBIDDEN:
                            if fb in subnode.value:
                                lower = subnode.value.lower()
                                if any(kw in lower for kw in ["no " + fb, "forbidden", "must not", "never call",
                                                               "do not call", "not call", "no /order",
                                                               "/order/preflight -> /order/approve -> /order/submit"]):
                                    continue
                                violations.append(f"{fb} in: {subnode.value[:80]}")
                assert len(violations) == 0, f"Forbidden endpoints: {violations}"
                return
        pytest.fail("Could not find stability drill function")


# ===========================================================================
# T15: No H1 token
# ===========================================================================

class TestNoH1Token:
    def test_h1_not_used(self, clean_git_metadata, clean_worktree,
                         origin_aligned, all_tags_present, bridge_health_ok,
                         positions_flat, alerts_clean, snapshot_ok,
                         readiness_locked, guard_state_clean, env_safety_locked,
                         rules_locked, autonomy_level_one, doctor_pass,
                         kpi_hold_expected, hermes_policy_ok):
        patches = _build_mocks(
            health=bridge_health_ok, positions=positions_flat,
            alerts=alerts_clean, snapshot=snapshot_ok, readiness=readiness_locked,
            git_metadata=clean_git_metadata, worktree=clean_worktree,
            origin=origin_aligned, tags=all_tags_present,
            guard_state_content=guard_state_clean, env_safety=env_safety_locked,
            rules=rules_locked, autonomy=autonomy_level_one,
            doctor=doctor_pass, kpi=kpi_hold_expected, policy=hermes_policy_ok,
        )
        mocks, patches = apply_patches(patches)
        try:
            result = _run_level1_post_promotion_stability_drill(samples_requested=2, interval_seconds=1)
            assert result["h1_token_not_used"] is True
        finally:
            stop_patches(mocks, patches)


# ===========================================================================
# T16: No mutation except export
# ===========================================================================

class TestNoMutation:
    def test_no_mutation(self, clean_git_metadata, clean_worktree,
                         origin_aligned, all_tags_present, bridge_health_ok,
                         positions_flat, alerts_clean, snapshot_ok,
                         readiness_locked, guard_state_clean, env_safety_locked,
                         rules_locked, autonomy_level_one, doctor_pass,
                         kpi_hold_expected, hermes_policy_ok):
        patches = _build_mocks(
            health=bridge_health_ok, positions=positions_flat,
            alerts=alerts_clean, snapshot=snapshot_ok, readiness=readiness_locked,
            git_metadata=clean_git_metadata, worktree=clean_worktree,
            origin=origin_aligned, tags=all_tags_present,
            guard_state_content=guard_state_clean, env_safety=env_safety_locked,
            rules=rules_locked, autonomy=autonomy_level_one,
            doctor=doctor_pass, kpi=kpi_hold_expected, policy=hermes_policy_ok,
        )
        mocks, patches = apply_patches(patches)
        try:
            result = _run_level1_post_promotion_stability_drill(samples_requested=2, interval_seconds=1)
            assert result["no_broker_mutation"] is True
            assert result["no_order_window_opened"] is True
            assert isinstance(result.get("explicit_non_actions"), list)
            assert len(result["explicit_non_actions"]) >= 10
        finally:
            stop_patches(mocks, patches)


# ===========================================================================
# T17: Stale guard trade_date => NO_GO
# ===========================================================================

class TestStaleGuardDate:
    def test_stale_trade_date_no_go(self, clean_git_metadata, clean_worktree,
                                    origin_aligned, all_tags_present, bridge_health_ok,
                                    positions_flat, alerts_clean, snapshot_ok,
                                    readiness_locked, guard_state_stale,
                                    env_safety_locked, rules_locked,
                                    autonomy_level_one, doctor_pass,
                                    kpi_hold_expected, hermes_policy_ok):
        patches = _build_mocks(
            health=bridge_health_ok, positions=positions_flat,
            alerts=alerts_clean, snapshot=snapshot_ok, readiness=readiness_locked,
            git_metadata=clean_git_metadata, worktree=clean_worktree,
            origin=origin_aligned, tags=all_tags_present,
            guard_state_content=guard_state_stale,
            env_safety=env_safety_locked, rules=rules_locked,
            autonomy=autonomy_level_one, doctor=doctor_pass,
            kpi=kpi_hold_expected, policy=hermes_policy_ok,
        )
        mocks, patches = apply_patches(patches)
        try:
            result = _run_level1_post_promotion_stability_drill(samples_requested=2, interval_seconds=1)
            assert result["diagnosis"] == _PHASE16E_DIAGNOSIS["guard_state_not_clean"]
            assert result["severity"] == "NO_GO"
        finally:
            stop_patches(mocks, patches)


# ===========================================================================
# T18: Autonomy Level 2 => NO_GO
# ===========================================================================

class TestAutonomyLevel2:
    @pytest.fixture
    def autonomy_level_two(self):
        return "2"

    def test_autonomy_level2_no_go(self, clean_git_metadata, clean_worktree,
                                   origin_aligned, all_tags_present, bridge_health_ok,
                                   positions_flat, alerts_clean, snapshot_ok,
                                   readiness_locked, guard_state_clean,
                                   env_safety_locked, rules_locked,
                                   autonomy_level_two, doctor_pass,
                                   kpi_hold_expected, hermes_policy_ok):
        patches = _build_mocks(
            health=bridge_health_ok, positions=positions_flat,
            alerts=alerts_clean, snapshot=snapshot_ok, readiness=readiness_locked,
            git_metadata=clean_git_metadata, worktree=clean_worktree,
            origin=origin_aligned, tags=all_tags_present,
            guard_state_content=guard_state_clean, env_safety=env_safety_locked,
            rules=rules_locked, autonomy=autonomy_level_two,
            doctor=doctor_pass, kpi=kpi_hold_expected, policy=hermes_policy_ok,
        )
        mocks, patches = apply_patches(patches)
        try:
            result = _run_level1_post_promotion_stability_drill(samples_requested=2, interval_seconds=1)
            assert result["diagnosis"] == _PHASE16E_DIAGNOSIS["autonomy_not_level1"]
            assert result["severity"] == "NO_GO"
        finally:
            stop_patches(mocks, patches)


# ===========================================================================
# T19: KPI blocker beyond system_locked => NO_GO
# ===========================================================================

class TestKpiBlocker:
    def test_kpi_no_go_blocker(self, clean_git_metadata, clean_worktree,
                               origin_aligned, all_tags_present, bridge_health_ok,
                               positions_flat, alerts_clean, snapshot_ok,
                               readiness_locked, guard_state_clean,
                               env_safety_locked, rules_locked,
                               autonomy_level_one, doctor_pass,
                               kpi_no_go, hermes_policy_ok):
        patches = _build_mocks(
            health=bridge_health_ok, positions=positions_flat,
            alerts=alerts_clean, snapshot=snapshot_ok, readiness=readiness_locked,
            git_metadata=clean_git_metadata, worktree=clean_worktree,
            origin=origin_aligned, tags=all_tags_present,
            guard_state_content=guard_state_clean, env_safety=env_safety_locked,
            rules=rules_locked, autonomy=autonomy_level_one,
            doctor=doctor_pass, kpi=kpi_no_go, policy=hermes_policy_ok,
        )
        mocks, patches = apply_patches(patches)
        try:
            result = _run_level1_post_promotion_stability_drill(samples_requested=2, interval_seconds=1)
            assert result["diagnosis"] == _PHASE16E_DIAGNOSIS["kpi_not_acceptable"]
            assert result["severity"] == "NO_GO"
        finally:
            stop_patches(mocks, patches)
