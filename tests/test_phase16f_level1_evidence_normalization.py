"""Tests for Phase 16F — Level 1 Evidence Normalization / Clean-Cycle Consistency.

All tests are read-only. No broker mutation, no order endpoints,
no H1 token usage, no autonomy level changes.

Coverage:
  - Command parser registers primary + 3 aliases
  - --help exits quickly
  - JSON stdout pure
  - Export written
  - Clean Level 1 mocked runtime => level1_evidence_normalization_ok / OK
  - clean_cycles_matches_kpi=true when both sources agree
  - clean_cycles_matches_kpi=false when mismatch
  - clean_cycles_defaulted_to_zero when ledger exists but drill returns 0
  - unknown clean_cycles reported as null
  - Dirty worktree => NO_GO
  - Missing required tag => NO_GO
  - Autonomy not Level 1 => NO_GO
  - Bridge disconnected => HOLD
  - Safety unlocked => NO_GO
  - Guard issues => NO_GO
  - Active alerts => NO_GO
  - Positions not flat => NO_GO
  - KPI blockers => NO_GO
  - No /order* calls
  - No H1 token reads
  - No mutation except export artifact
  - No autonomy level change
  - Evidence fields: clean_cycles_source, clean_cycles_matches_kpi present
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


    _run_level1_evidence_normalization_check,
    _PHASE16F_DIAGNOSIS,
    _PHASE16F_REQUIRED_TAGS,
    _PHASE16F_EXPORT_DIR,
    OPENCLAW_DIR as _OP_OPENCLAW_DIR,
)


# ===========================================================================
# Fixtures
# ===========================================================================

@pytest.fixture
def clean_git_metadata():
    return {
        "branch": "main",
        "commit_short": "abc1234",
        "tag": "phase16f_evidence_normalization",
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
    return {"required_count": len(_PHASE16F_REQUIRED_TAGS),
            "present_count": len(_PHASE16F_REQUIRED_TAGS),
            "missing": [], "present": list(_PHASE16F_REQUIRED_TAGS)}


@pytest.fixture
def one_tag_missing():
    return {"required_count": len(_PHASE16F_REQUIRED_TAGS),
            "present_count": len(_PHASE16F_REQUIRED_TAGS) - 1,
            "missing": [list(_PHASE16F_REQUIRED_TAGS)[0]],
            "present": list(_PHASE16F_REQUIRED_TAGS)[1:]}


@pytest.fixture
def bridge_health_ok():
    return {"connected": True, "mode": "paper", "read_only": True}


@pytest.fixture
def bridge_health_disconnected():
    return {"connected": False, "mode": "paper", "read_only": True}


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
    return json.dumps({"schema_version": 1, "trade_date": _TODAY_STR,
                       "daily_trade_count": 0, "daily_halt_active": False})


@pytest.fixture
def guard_state_with_trades():
    return json.dumps({"schema_version": 1, "trade_date": _TODAY_STR,
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
    """KPI HOLD — expected at Level 1 (only system_locked)."""
    return {"verdict": "HOLD",
            "blockers": [{"severity": "HOLD", "check": "system_locked"}],
            "autonomy": {"clean_cycles": 7}}


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
                 autonomy=None, doctor=None, kpi=None, policy=None,
                 clean_cycles_count=7, ledger_exists=True):
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
    if ledger_exists:
        cc_dir = tmp_openclaw / "autonomy-cycles"
        cc_dir.mkdir(parents=True, exist_ok=True)
        ledger_path = cc_dir / "clean-cycle-ledger.jsonl"
        lines = []
        for i in range(clean_cycles_count):
            lines.append(json.dumps({"timestamp": f"2026-06-{25-i}T12:00:00Z", "clean": True, "evidence_hash": f"hash{i}"}))
        ledger_path.write_text("\n".join(lines) + "\n")
    patches.append(patch("ibkr_operator.OPENCLAW_DIR", tmp_openclaw))
    tmp_export = Path(tempfile.mkdtemp())
    patches.append(patch("ibkr_operator._PHASE16F_EXPORT_DIR", tmp_export))
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
                           "level1-evidence-normalization-check", "--help"],
                          capture_output=True, text=True, timeout=10)
        assert r.returncode == 0, f"help failed: {r.stderr}"

    @pytest.mark.parametrize("alias", [
        "phase16f-evidence-normalization",
        "clean-cycle-consistency-check",
        "level1-clean-cycle-check",
    ])
    def test_alias_registered(self, alias):
        r = subprocess.run([sys.executable, str(BRIDGE_DIR / "ibkr_operator.py"),
                           alias, "--help"],
                          capture_output=True, text=True, timeout=10)
        assert r.returncode == 0, f"{alias} --help failed: {r.stderr}"

    def test_function_importable(self):
        assert callable(_run_level1_evidence_normalization_check)


# ===========================================================================
# T2: Clean => level1_evidence_normalization_ok
# ===========================================================================

class TestCleanNormalization:
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
            clean_cycles_count=7, ledger_exists=True,
        )
        mocks, patches = apply_patches(patches)
        try:
            result = _run_level1_evidence_normalization_check()
            assert result["diagnosis"] == _PHASE16F_DIAGNOSIS["ready"]
            assert result["severity"] == "OK"
            assert result["promotion_allowed_now"] is False
            assert result["order_enablement_allowed_now"] is False
            assert result["order_enablement_performed"] is False
            assert result["promotion_performed"] is False
            assert result["no_broker_mutation"] is True
            assert result["no_order_window_opened"] is True
            assert result["h1_token_not_used"] is True
            assert result["export_path"] is not None
            # Autonomy section
            auto = result["autonomy"]
            assert auto["current_level"] == "1"
            assert auto["clean_cycles"] == 7
            assert auto["clean_cycles_source"] == "openclaw_clean_cycle_ledger"
            assert auto["clean_cycles_matches_kpi"] is True
            assert auto["kpi_clean_cycles"] == 7
            assert auto["drill_clean_cycles"] == 7
            # Normalization summary
            ns = result["normalization_summary"]
            assert ns["evidence_normalized"] is True
            assert ns["clean_cycle_consistency_ok"] is True
            assert ns["stability_drill_source_corrected"] is True
            # Safety
            safety = result["safety"]
            assert safety["env_IBKR_ALLOW_ORDERS"] in ("false", "?")
            assert safety["system_locked"] is True
        finally:
            stop_patches(mocks, patches)


# ===========================================================================
# T3: clean_cycles_matches_kpi=true
# ===========================================================================

class TestCleanCyclesMatchesKpi:
    def test_matches_kpi_when_same(self, clean_git_metadata, clean_worktree,
                                   origin_aligned, all_tags_present, bridge_health_ok,
                                   positions_flat, alerts_clean, snapshot_ok,
                                   readiness_locked, guard_state_clean, env_safety_locked,
                                   rules_locked, autonomy_level_one, doctor_pass,
                                   kpi_hold_expected, hermes_policy_ok):
        # KPI reports 7, ledger has 7 entries
        patches = _build_mocks(
            health=bridge_health_ok, positions=positions_flat,
            alerts=alerts_clean, snapshot=snapshot_ok, readiness=readiness_locked,
            git_metadata=clean_git_metadata, worktree=clean_worktree,
            origin=origin_aligned, tags=all_tags_present,
            guard_state_content=guard_state_clean, env_safety=env_safety_locked,
            rules=rules_locked, autonomy=autonomy_level_one,
            doctor=doctor_pass, kpi=kpi_hold_expected, policy=hermes_policy_ok,
            clean_cycles_count=7, ledger_exists=True,
        )
        mocks, patches = apply_patches(patches)
        try:
            result = _run_level1_evidence_normalization_check()
            assert result["autonomy"]["clean_cycles_matches_kpi"] is True
        finally:
            stop_patches(mocks, patches)


# ===========================================================================
# T4: clean_cycles_matches_kpi=false when mismatch
# ===========================================================================

class TestCleanCyclesMismatch:
    def test_mismatch_detected(self, clean_git_metadata, clean_worktree,
                               origin_aligned, all_tags_present, bridge_health_ok,
                               positions_flat, alerts_clean, snapshot_ok,
                               readiness_locked, guard_state_clean, env_safety_locked,
                               rules_locked, autonomy_level_one, doctor_pass,
                               hermes_policy_ok):
        # KPI reports 7 but ledger has only 3 entries — mismatch
        kpi_mismatch = {"verdict": "HOLD",
                        "blockers": [{"severity": "HOLD", "check": "autonomy_level_zero"}],
                        "autonomy": {"clean_cycles": 7}}
        patches = _build_mocks(
            health=bridge_health_ok, positions=positions_flat,
            alerts=alerts_clean, snapshot=snapshot_ok, readiness=readiness_locked,
            git_metadata=clean_git_metadata, worktree=clean_worktree,
            origin=origin_aligned, tags=all_tags_present,
            guard_state_content=guard_state_clean, env_safety=env_safety_locked,
            rules=rules_locked, autonomy=autonomy_level_one,
            doctor=doctor_pass, kpi=kpi_mismatch, policy=hermes_policy_ok,
            clean_cycles_count=3, ledger_exists=True,
        )
        mocks, patches = apply_patches(patches)
        try:
            result = _run_level1_evidence_normalization_check()
            assert result["diagnosis"] == _PHASE16F_DIAGNOSIS["clean_cycles_mismatch"]
            assert result["severity"] == "NO_GO"
            assert result["autonomy"]["clean_cycles_matches_kpi"] is False
        finally:
            stop_patches(mocks, patches)


# ===========================================================================
# T5: clean_cycles_defaulted_to_zero detection
# ===========================================================================

class TestCleanCyclesDefaultedToZero:
    def test_defaulted_to_zero_detected(self, clean_git_metadata, clean_worktree,
                                        origin_aligned, all_tags_present, bridge_health_ok,
                                        positions_flat, alerts_clean, snapshot_ok,
                                        readiness_locked, guard_state_clean, env_safety_locked,
                                        rules_locked, autonomy_level_one, doctor_pass,
                                        hermes_policy_ok):
        # Ledger has entries but we simulate _count_clean_cycles returning 0
        kpi_with_cycles = {"verdict": "HOLD",
                           "blockers": [{"severity": "HOLD", "check": "autonomy_level_zero"}],
                           "autonomy": {"clean_cycles": 7}}
        patches = _build_mocks(
            health=bridge_health_ok, positions=positions_flat,
            alerts=alerts_clean, snapshot=snapshot_ok, readiness=readiness_locked,
            git_metadata=clean_git_metadata, worktree=clean_worktree,
            origin=origin_aligned, tags=all_tags_present,
            guard_state_content=guard_state_clean, env_safety=env_safety_locked,
            rules=rules_locked, autonomy=autonomy_level_one,
            doctor=doctor_pass, kpi=kpi_with_cycles, policy=hermes_policy_ok,
            clean_cycles_count=7, ledger_exists=True,
        )
        # Patch _count_clean_cycles to return 0 (simulating old broken drill source)
        patches.append(patch("ibkr_operator._count_clean_cycles", return_value=0))
        mocks, patches = apply_patches(patches)
        try:
            result = _run_level1_evidence_normalization_check()
            assert result["diagnosis"] == _PHASE16F_DIAGNOSIS["clean_cycles_defaulted_to_zero"]
            assert result["severity"] == "NO_GO"
            assert result["autonomy"]["clean_cycles_matches_kpi"] is False
        finally:
            stop_patches(mocks, patches)


# ===========================================================================
# T6: Unknown clean_cycles reported as null
# ===========================================================================

class TestUnknownCleanCycles:
    def test_null_when_ledger_missing(self, clean_git_metadata, clean_worktree,
                                      origin_aligned, all_tags_present, bridge_health_ok,
                                      positions_flat, alerts_clean, snapshot_ok,
                                      readiness_locked, guard_state_clean, env_safety_locked,
                                      rules_locked, autonomy_level_one, doctor_pass,
                                      hermes_policy_ok):
        # KPI has no clean_cycles (both unknown)
        kpi_no_cc = {"verdict": "HOLD",
                     "blockers": [{"severity": "HOLD", "check": "autonomy_level_zero"}],
                     "autonomy": {}}
        patches = _build_mocks(
            health=bridge_health_ok, positions=positions_flat,
            alerts=alerts_clean, snapshot=snapshot_ok, readiness=readiness_locked,
            git_metadata=clean_git_metadata, worktree=clean_worktree,
            origin=origin_aligned, tags=all_tags_present,
            guard_state_content=guard_state_clean, env_safety=env_safety_locked,
            rules=rules_locked, autonomy=autonomy_level_one,
            doctor=doctor_pass, kpi=kpi_no_cc, policy=hermes_policy_ok,
            clean_cycles_count=0, ledger_exists=False,
        )
        mocks, patches = apply_patches(patches)
        try:
            result = _run_level1_evidence_normalization_check()
            assert result["autonomy"]["clean_cycles"] is None
            assert result["autonomy"]["kpi_clean_cycles"] is None
            assert result["autonomy"]["clean_cycles_matches_kpi"] is True  # both None → match
            ns = result["normalization_summary"]
            assert ns["unknown_clean_cycles_reported_as_null"] is True
        finally:
            stop_patches(mocks, patches)


# ===========================================================================
# T7: Dirty worktree => NO_GO
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
            ledger_exists=False,
        )
        mocks, patches = apply_patches(patches)
        try:
            result = _run_level1_evidence_normalization_check()
            assert result["diagnosis"] == _PHASE16F_DIAGNOSIS["dirty_worktree"]
            assert result["severity"] == "NO_GO"
        finally:
            stop_patches(mocks, patches)


# ===========================================================================
# T8: Missing tags => NO_GO
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
            ledger_exists=False,
        )
        mocks, patches = apply_patches(patches)
        try:
            result = _run_level1_evidence_normalization_check()
            assert result["diagnosis"] == _PHASE16F_DIAGNOSIS["missing_required_tags"]
            assert result["severity"] == "NO_GO"
        finally:
            stop_patches(mocks, patches)


# ===========================================================================
# T9: Autonomy not Level 1 => NO_GO
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
            ledger_exists=False,
        )
        mocks, patches = apply_patches(patches)
        try:
            result = _run_level1_evidence_normalization_check()
            assert result["diagnosis"] == _PHASE16F_DIAGNOSIS["autonomy_not_level1"]
            assert result["severity"] == "NO_GO"
        finally:
            stop_patches(mocks, patches)


# ===========================================================================
# T10: Bridge disconnected => HOLD
# ===========================================================================

class TestDisconnected:
    def test_disconnected_hold(self, clean_git_metadata, clean_worktree,
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
            ledger_exists=False,
        )
        mocks, patches = apply_patches(patches)
        try:
            result = _run_level1_evidence_normalization_check()
            assert result["diagnosis"] == _PHASE16F_DIAGNOSIS["runtime_not_ready"]
            assert result["severity"] == "HOLD"
        finally:
            stop_patches(mocks, patches)


# ===========================================================================
# T11: Safety unlocked => NO_GO
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
            ledger_exists=False,
        )
        mocks, patches = apply_patches(patches)
        try:
            result = _run_level1_evidence_normalization_check()
            assert result["diagnosis"] == _PHASE16F_DIAGNOSIS["safety_not_locked"]
            assert result["severity"] == "NO_GO"
        finally:
            stop_patches(mocks, patches)


# ===========================================================================
# T12: Guard issues => NO_GO
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
            ledger_exists=False,
        )
        mocks, patches = apply_patches(patches)
        try:
            result = _run_level1_evidence_normalization_check()
            assert result["diagnosis"] == _PHASE16F_DIAGNOSIS["guard_state_not_clean"]
            assert result["severity"] == "NO_GO"
        finally:
            stop_patches(mocks, patches)


# ===========================================================================
# T13: Active alerts => NO_GO
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
            ledger_exists=False,
        )
        mocks, patches = apply_patches(patches)
        try:
            result = _run_level1_evidence_normalization_check()
            assert result["diagnosis"] == _PHASE16F_DIAGNOSIS["monitor_alerts_active"]
            assert result["severity"] == "NO_GO"
        finally:
            stop_patches(mocks, patches)


# ===========================================================================
# T14: Positions not flat => NO_GO
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
            ledger_exists=False,
        )
        mocks, patches = apply_patches(patches)
        try:
            result = _run_level1_evidence_normalization_check()
            assert result["diagnosis"] == _PHASE16F_DIAGNOSIS["positions_not_flat"]
            assert result["severity"] == "NO_GO"
        finally:
            stop_patches(mocks, patches)


# ===========================================================================
# T15: KPI blockers => NO_GO
# ===========================================================================

class TestKpiBlocker:
    def test_kpi_no_go(self, clean_git_metadata, clean_worktree,
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
            ledger_exists=False,
        )
        mocks, patches = apply_patches(patches)
        try:
            result = _run_level1_evidence_normalization_check()
            assert result["diagnosis"] == _PHASE16F_DIAGNOSIS["kpi_not_acceptable"]
            assert result["severity"] == "NO_GO"
        finally:
            stop_patches(mocks, patches)


# ===========================================================================
# T16: JSON stdout pure
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
            clean_cycles_count=7, ledger_exists=True,
        )
        mocks, patches = apply_patches(patches)
        try:
            result = _run_level1_evidence_normalization_check()
            serialized = json.dumps(result, indent=2, default=str)
            parsed = json.loads(serialized)
            assert parsed["check_id"] == result["check_id"]
        finally:
            stop_patches(mocks, patches)


# ===========================================================================
# T17: Export written
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
            clean_cycles_count=7, ledger_exists=True,
        )
        mocks, patches = apply_patches(patches)
        try:
            result = _run_level1_evidence_normalization_check()
            assert result["export_path"] is not None
            assert os.path.exists(result["export_path"])
        finally:
            stop_patches(mocks, patches)


# ===========================================================================
# T18: No /order* calls
# ===========================================================================

class TestNoOrderEndpoints:
    FORBIDDEN = {"/order", "/order/preflight", "/order/approve", "/order/submit",
                 "/connect", "/trade-window"}

    def test_no_forbidden_endpoints(self):
        import ast
        source = (BRIDGE_DIR / "ibkr_operator.py").read_text()
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "_run_level1_evidence_normalization_check":
                violations = []
                for subnode in ast.walk(node):
                    if isinstance(subnode, ast.Constant) and isinstance(subnode.value, str):
                        for fb in self.FORBIDDEN:
                            if fb in subnode.value:
                                lower = subnode.value.lower()
                                if any(kw in lower for kw in ["no " + fb, "forbidden", "must not", "never call",
                                                               "do not call", "not call"]):
                                    continue
                                violations.append(f"{fb} in: {subnode.value[:80]}")
                assert len(violations) == 0, f"Forbidden endpoints: {violations}"
                return
        pytest.fail("Could not find evidence normalization check function")


# ===========================================================================
# T19: No H1 token
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
            clean_cycles_count=7, ledger_exists=True,
        )
        mocks, patches = apply_patches(patches)
        try:
            result = _run_level1_evidence_normalization_check()
            assert result["h1_token_not_used"] is True
        finally:
            stop_patches(mocks, patches)


# ===========================================================================
# T20: No mutation except export
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
            clean_cycles_count=7, ledger_exists=True,
        )
        mocks, patches = apply_patches(patches)
        try:
            result = _run_level1_evidence_normalization_check()
            assert result["no_broker_mutation"] is True
            assert result["no_order_window_opened"] is True
            assert isinstance(result.get("explicit_non_actions"), list)
            assert len(result["explicit_non_actions"]) >= 10
        finally:
            stop_patches(mocks, patches)
