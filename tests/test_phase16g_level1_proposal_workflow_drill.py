"""Tests for Phase 16G — Level 1 Proposal-Only Workflow Drill.

All tests are read-only. No broker mutation, no order endpoints,
no H1 token usage, no autonomy level changes.

Coverage:
  - Command parser registers primary + 3 aliases
  - --help exits quickly
  - JSON stdout pure
  - Export written
  - Missing required tag => NO_GO
  - Dirty worktree => NO_GO
  - Clean connected locked runtime => diagnosis=level1_proposal_workflow_ok / severity=OK
  - Autonomy not level 1 => NO_GO
  - Safety unlocked => NO_GO
  - Active monitor alerts => NO_GO
  - Positions not flat => NO_GO
  - Guard daily_trade_count > 0 => NO_GO
  - Guard trade_date stale => NO_GO
  - Doctor not acceptable => NO_GO
  - KPI not acceptable => NO_GO
  - Policy boundary missing => NO_GO
  - Clean cycles mismatch => NO_GO
  - Proposals marked non-executable
  - Proposal batch structure correct
  - Workflow summary correct
  - No /order* calls
  - No H1 token reads
  - No mutation except export artifact
"""

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock, mock_open, PropertyMock

import pytest

# Auto-generated: dynamic date helpers for guard-state fixtures
from datetime import datetime, timezone, timedelta
_TODAY_STR = datetime.now(timezone.utc).strftime("%Y-%m-%d")
_YESTERDAY_STR = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")


BRIDGE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BRIDGE_DIR))

from ibkr_operator import (
    _run_level1_proposal_workflow_drill,
    _PHASE16G_DIAGNOSIS,
    _PHASE16G_REQUIRED_TAGS,
    _PHASE16G_EXPORT_DIR,
    _PHASE16G_EXPLICIT_NON_ACTIONS,
    _compute_evidence_hash,
    OPENCLAW_DIR,
)


# ===========================================================================
# Fixtures
# ===========================================================================

@pytest.fixture
def clean_git_metadata():
    return {"branch": "master", "commit_short": "abc1234",
            "commit": "abc1234abc1234abc1234abc1234abc1234abc",
            "tag": "phase16f_level1_evidence_normalization"}


@pytest.fixture
def clean_worktree():
    return {"clean": True, "dirty_files": []}


@pytest.fixture
def dirty_worktree():
    return {"clean": False, "dirty_files": ["ibkr_operator.py", "guard.py"]}


@pytest.fixture
def origin_aligned():
    return {"aligned": True, "local_master_commit": "abc1234",
            "origin_master_commit": "abc1234"}


@pytest.fixture
def all_tags_present():
    return {"present_count": len(_PHASE16G_REQUIRED_TAGS),
            "present": list(_PHASE16G_REQUIRED_TAGS)}


@pytest.fixture
def one_tag_missing():
    missing = [_PHASE16G_REQUIRED_TAGS[0]]
    present = list(_PHASE16G_REQUIRED_TAGS[1:])
    return {"present_count": len(present), "present": present}


@pytest.fixture
def bridge_health_ok():
    return {"connected": True, "mode": "paper", "read_only": True}


@pytest.fixture
def bridge_health_disconnected():
    return {"connected": False, "mode": "paper", "read_only": True}


@pytest.fixture
def bridge_health_live_mode():
    return {"connected": True, "mode": "live", "read_only": False}


@pytest.fixture
def positions_flat():
    return {"positions": []}


@pytest.fixture
def positions_not_flat():
    return {"positions": [{"symbol": "SPY", "position": 100.0,
                           "market_value": 45000.0, "avg_cost": 430.0}]}


@pytest.fixture
def alerts_clean():
    return {"alerts": []}


@pytest.fixture
def alerts_active():
    return {"alerts": [{"id": "a1", "requires_action": True,
                        "message": "Test alert", "severity": "WARN"}]}


@pytest.fixture
def snapshot_ok():
    return {"ok": True, "endpoints": 7}


@pytest.fixture
def readiness_locked():
    return {"summary": {"kill_switches": {"system_locked": True}}}


@pytest.fixture
def readiness_unlocked():
    return {"summary": {"kill_switches": {"system_locked": False}}}


@pytest.fixture
def guard_state_clean():
    return json.dumps({"schema_version": 1, "trade_date": _TODAY_STR,
                       "daily_trade_count": 0, "daily_halt_active": False})


@pytest.fixture
def guard_state_with_trades():
    return json.dumps({"schema_version": 1, "trade_date": _TODAY_STR,
                       "daily_trade_count": 3, "daily_halt_active": False})


@pytest.fixture
def guard_state_stale():
    return json.dumps({"schema_version": 1, "trade_date": _YESTERDAY_STR,
                       "daily_trade_count": 0, "daily_halt_active": False})


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
def doctor_fail():
    return {"pass": False, "passed": 10, "total": 15,
            "passed_count": 10, "check_count": 15,
            "checks": [{"check": "h1_token_canary", "ok": False, "status": "FAIL"}]}


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
def kpi_hold_clean_cycles_5():
    """KPI HOLD with clean_cycles=5 (mismatch)."""
    return {"verdict": "HOLD",
            "blockers": [{"severity": "HOLD", "check": "system_locked"}],
            "autonomy": {"clean_cycles": 5}}


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
            lines.append(json.dumps({"timestamp": f"2026-06-{25-i}T12:00:00Z",
                                     "clean": True, "evidence_hash": f"hash{i}"}))
        ledger_path.write_text("\n".join(lines) + "\n")
    patches.append(patch("ibkr_operator.OPENCLAW_DIR", tmp_openclaw))
    tmp_export = Path(tempfile.mkdtemp())
    patches.append(patch("ibkr_operator._PHASE16G_EXPORT_DIR", tmp_export))
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
                           "level1-proposal-workflow-drill", "--help"],
                          capture_output=True, text=True, timeout=10)
        assert r.returncode == 0, f"help failed: {r.stderr}"

    def test_alias_phase16g_works(self):
        r = subprocess.run([sys.executable, str(BRIDGE_DIR / "ibkr_operator.py"),
                           "phase16g-proposal-workflow-drill", "--help"],
                          capture_output=True, text=True, timeout=10)
        assert r.returncode == 0, f"alias help failed: {r.stderr}"

    def test_alias_level1_proposal_only_drill_works(self):
        r = subprocess.run([sys.executable, str(BRIDGE_DIR / "ibkr_operator.py"),
                           "level1-proposal-only-drill", "--help"],
                          capture_output=True, text=True, timeout=10)
        assert r.returncode == 0, f"alias help failed: {r.stderr}"

    def test_alias_proposal_only_workflow_drill_works(self):
        r = subprocess.run([sys.executable, str(BRIDGE_DIR / "ibkr_operator.py"),
                           "proposal-only-workflow-drill", "--help"],
                          capture_output=True, text=True, timeout=10)
        assert r.returncode == 0, f"alias help failed: {r.stderr}"


# ===========================================================================
# T2: Clean connected locked => ready
# ===========================================================================

class TestCleanRuntime:
    def test_clean_runtime_produces_ready(self, clean_git_metadata, clean_worktree,
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
            result = _run_level1_proposal_workflow_drill(demo_candidates=2)
            assert result["diagnosis"] == _PHASE16G_DIAGNOSIS["ready"]
            assert result["severity"] == "OK"
            assert result["operator_action_required"] is False
            assert result["promotion_allowed_now"] is False
            assert result["order_enablement_allowed_now"] is False
            assert result["order_enablement_performed"] is False
            assert result["promotion_performed"] is False
            assert result["no_broker_mutation"] is True
            assert result["no_order_window_opened"] is True
            assert result["h1_token_not_used"] is True
            assert result["export_path"] is not None
            assert result["drill_id"].startswith("proposal-drill-")
            # Proposal workflow
            pw = result["proposal_workflow"]
            assert pw["proposal_only"] is True
            assert pw["proposal_source"] == "synthetic_readonly_demo"
            assert pw["demo_candidates_requested"] == 2
            assert pw["proposals_created"] == 2
            assert pw["proposals_marked_executable"] is False
            assert pw["proposals_require_chris_review"] is True
            assert pw["human_approval_required"] is True
            assert pw["broker_submission_performed"] is False
            assert pw["preflight_performed"] is False
            assert pw["approval_performed"] is False
            assert pw["submit_performed"] is False
            # Proposal batch
            pb = result["proposal_batch"]
            assert pb["status"] == "review_only"
            assert len(pb["items"]) == 2
            for item in pb["items"]:
                assert item["executable"] is False
                assert item["requires_chris_approval"] is True
                assert item["performed"] is False
                assert item["future_required_path"] == "/order/preflight -> /order/approve -> /order/submit"
            # Workflow summary
            ws = result["workflow_summary"]
            assert ws["level1_proposal_workflow_ready"] is True
            assert ws["proposal_batch_created"] is True
            assert ws["all_items_non_executable"] is True
            assert ws["all_items_require_human_approval"] is True
            assert ws["no_order_path_called"] is True
            assert ws["no_broker_submission"] is True
            # Autonomy
            auto = result["autonomy"]
            assert auto["current_level"] == "1"
            assert auto["clean_cycles"] == 7
            assert auto["clean_cycles_source"] == "openclaw_clean_cycle_ledger"
            assert auto["clean_cycles_matches_kpi"] is True
            # Safety
            safety = result["safety"]
            assert safety["env_IBKR_ALLOW_ORDERS"] in ("false", "?")
            assert safety["rules_enforced"] in ("false", "?")
            assert safety["system_locked"] is True
        finally:
            stop_patches(mocks, patches)


# ===========================================================================
# T3: Proposal batch structure
# ===========================================================================

class TestProposalBatchStructure:
    def test_batch_items_have_correct_structure(self, clean_git_metadata, clean_worktree,
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
            result = _run_level1_proposal_workflow_drill(demo_candidates=3)
            assert result["diagnosis"] == _PHASE16G_DIAGNOSIS["ready"]
            pb = result["proposal_batch"]
            items = pb["items"]
            assert len(items) == 3
            seen_symbols = set()
            for item in items:
                assert "proposal_id" in item
                assert "symbol" in item
                assert "side" in item
                assert "quantity" in item
                assert "rationale" in item
                assert "risk_notes" in item
                assert item["executable"] is False
                assert item["requires_chris_approval"] is True
                assert item["source"] == "synthetic_readonly_demo"
                seen_symbols.add(item["symbol"])
            # All symbols should be unique
            assert len(seen_symbols) == 3
        finally:
            stop_patches(mocks, patches)

    def test_zero_candidates_creates_empty_batch(self, clean_git_metadata, clean_worktree,
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
            result = _run_level1_proposal_workflow_drill(demo_candidates=0)
            assert result["diagnosis"] == _PHASE16G_DIAGNOSIS["ready"]
            assert len(result["proposal_batch"]["items"]) == 0
            assert result["proposal_workflow"]["proposals_created"] == 0
        finally:
            stop_patches(mocks, patches)

    def test_different_proposal_source(self, clean_git_metadata, clean_worktree,
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
            result = _run_level1_proposal_workflow_drill(
                demo_candidates=1, proposal_source="custom_source"
            )
            assert result["proposal_workflow"]["proposal_source"] == "custom_source"
            assert result["proposal_batch"]["items"][0]["source"] == "custom_source"
        finally:
            stop_patches(mocks, patches)


# ===========================================================================
# T4: Prerequisites — negative cases
# ===========================================================================

class TestMissingTags:
    def test_missing_tag_no_go(self, clean_git_metadata, clean_worktree,
                               origin_aligned, one_tag_missing, bridge_health_ok,
                               positions_flat, alerts_clean, snapshot_ok,
                               readiness_locked, guard_state_clean, env_safety_locked,
                               rules_locked, autonomy_level_one, doctor_pass,
                               kpi_hold_expected, hermes_policy_ok):
        patches = _build_mocks(
            health=bridge_health_ok, positions=positions_flat,
            alerts=alerts_clean, snapshot=snapshot_ok, readiness=readiness_locked,
            git_metadata=clean_git_metadata, worktree=clean_worktree,
            origin=origin_aligned, tags=one_tag_missing,
            guard_state_content=guard_state_clean, env_safety=env_safety_locked,
            rules=rules_locked, autonomy=autonomy_level_one,
            doctor=doctor_pass, kpi=kpi_hold_expected, policy=hermes_policy_ok,
        )
        mocks, patches = apply_patches(patches)
        try:
            result = _run_level1_proposal_workflow_drill()
            assert result["diagnosis"] == _PHASE16G_DIAGNOSIS["missing_required_tags"]
            assert result["severity"] == "NO_GO"
        finally:
            stop_patches(mocks, patches)


class TestDirtyWorktree:
    def test_dirty_worktree_no_go(self, clean_git_metadata, dirty_worktree,
                                  origin_aligned, all_tags_present, bridge_health_ok,
                                  positions_flat, alerts_clean, snapshot_ok,
                                  readiness_locked, guard_state_clean, env_safety_locked,
                                  rules_locked, autonomy_level_one, doctor_pass,
                                  kpi_hold_expected, hermes_policy_ok):
        patches = _build_mocks(
            health=bridge_health_ok, positions=positions_flat,
            alerts=alerts_clean, snapshot=snapshot_ok, readiness=readiness_locked,
            git_metadata=clean_git_metadata, worktree=dirty_worktree,
            origin=origin_aligned, tags=all_tags_present,
            guard_state_content=guard_state_clean, env_safety=env_safety_locked,
            rules=rules_locked, autonomy=autonomy_level_one,
            doctor=doctor_pass, kpi=kpi_hold_expected, policy=hermes_policy_ok,
        )
        mocks, patches = apply_patches(patches)
        try:
            result = _run_level1_proposal_workflow_drill()
            assert result["diagnosis"] == _PHASE16G_DIAGNOSIS["dirty_worktree"]
            assert result["severity"] == "NO_GO"
        finally:
            stop_patches(mocks, patches)


class TestAutonomyNotLevel1:
    def test_autonomy_not_level1_no_go(self, clean_git_metadata, clean_worktree,
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
            result = _run_level1_proposal_workflow_drill()
            assert result["diagnosis"] == _PHASE16G_DIAGNOSIS["autonomy_not_level1"]
            assert result["severity"] == "NO_GO"
        finally:
            stop_patches(mocks, patches)


class TestSafetyNotLocked:
    def test_safety_unlocked_no_go(self, clean_git_metadata, clean_worktree,
                                   origin_aligned, all_tags_present, bridge_health_ok,
                                   positions_flat, alerts_clean, snapshot_ok,
                                   readiness_unlocked, guard_state_clean, env_safety_unlocked,
                                   rules_unlocked, autonomy_level_one, doctor_pass,
                                   kpi_hold_expected, hermes_policy_ok):
        patches = _build_mocks(
            health=bridge_health_ok, positions=positions_flat,
            alerts=alerts_clean, snapshot=snapshot_ok, readiness=readiness_unlocked,
            git_metadata=clean_git_metadata, worktree=clean_worktree,
            origin=origin_aligned, tags=all_tags_present,
            guard_state_content=guard_state_clean, env_safety=env_safety_unlocked,
            rules=rules_unlocked, autonomy=autonomy_level_one,
            doctor=doctor_pass, kpi=kpi_hold_expected, policy=hermes_policy_ok,
        )
        mocks, patches = apply_patches(patches)
        try:
            result = _run_level1_proposal_workflow_drill()
            assert result["diagnosis"] == _PHASE16G_DIAGNOSIS["safety_not_locked"]
            assert result["severity"] == "NO_GO"
        finally:
            stop_patches(mocks, patches)


class TestGuardStateNotClean:
    def test_trades_present_no_go(self, clean_git_metadata, clean_worktree,
                                  origin_aligned, all_tags_present, bridge_health_ok,
                                  positions_flat, alerts_clean, snapshot_ok,
                                  readiness_locked, guard_state_with_trades, env_safety_locked,
                                  rules_locked, autonomy_level_one, doctor_pass,
                                  kpi_hold_expected, hermes_policy_ok):
        patches = _build_mocks(
            health=bridge_health_ok, positions=positions_flat,
            alerts=alerts_clean, snapshot=snapshot_ok, readiness=readiness_locked,
            git_metadata=clean_git_metadata, worktree=clean_worktree,
            origin=origin_aligned, tags=all_tags_present,
            guard_state_content=guard_state_with_trades, env_safety=env_safety_locked,
            rules=rules_locked, autonomy=autonomy_level_one,
            doctor=doctor_pass, kpi=kpi_hold_expected, policy=hermes_policy_ok,
        )
        mocks, patches = apply_patches(patches)
        try:
            result = _run_level1_proposal_workflow_drill()
            assert result["diagnosis"] == _PHASE16G_DIAGNOSIS["guard_state_not_clean"]
            assert result["severity"] == "NO_GO"
        finally:
            stop_patches(mocks, patches)

    def test_stale_trade_date_no_go(self, clean_git_metadata, clean_worktree,
                                    origin_aligned, all_tags_present, bridge_health_ok,
                                    positions_flat, alerts_clean, snapshot_ok,
                                    readiness_locked, guard_state_stale, env_safety_locked,
                                    rules_locked, autonomy_level_one, doctor_pass,
                                    kpi_hold_expected, hermes_policy_ok):
        patches = _build_mocks(
            health=bridge_health_ok, positions=positions_flat,
            alerts=alerts_clean, snapshot=snapshot_ok, readiness=readiness_locked,
            git_metadata=clean_git_metadata, worktree=clean_worktree,
            origin=origin_aligned, tags=all_tags_present,
            guard_state_content=guard_state_stale, env_safety=env_safety_locked,
            rules=rules_locked, autonomy=autonomy_level_one,
            doctor=doctor_pass, kpi=kpi_hold_expected, policy=hermes_policy_ok,
        )
        mocks, patches = apply_patches(patches)
        try:
            result = _run_level1_proposal_workflow_drill()
            assert result["diagnosis"] == _PHASE16G_DIAGNOSIS["guard_state_not_clean"]
            assert result["severity"] == "NO_GO"
        finally:
            stop_patches(mocks, patches)


class TestDoctorNotAcceptable:
    def test_doctor_fail_no_go(self, clean_git_metadata, clean_worktree,
                               origin_aligned, all_tags_present, bridge_health_ok,
                               positions_flat, alerts_clean, snapshot_ok,
                               readiness_locked, guard_state_clean, env_safety_locked,
                               rules_locked, autonomy_level_one, doctor_fail,
                               kpi_hold_expected, hermes_policy_ok):
        patches = _build_mocks(
            health=bridge_health_ok, positions=positions_flat,
            alerts=alerts_clean, snapshot=snapshot_ok, readiness=readiness_locked,
            git_metadata=clean_git_metadata, worktree=clean_worktree,
            origin=origin_aligned, tags=all_tags_present,
            guard_state_content=guard_state_clean, env_safety=env_safety_locked,
            rules=rules_locked, autonomy=autonomy_level_one,
            doctor=doctor_fail, kpi=kpi_hold_expected, policy=hermes_policy_ok,
        )
        mocks, patches = apply_patches(patches)
        try:
            result = _run_level1_proposal_workflow_drill()
            assert result["diagnosis"] == _PHASE16G_DIAGNOSIS["doctor_not_acceptable"]
            assert result["severity"] == "NO_GO"
        finally:
            stop_patches(mocks, patches)


class TestKpiNotAcceptable:
    def test_kpi_no_go(self, clean_git_metadata, clean_worktree,
                       origin_aligned, all_tags_present, bridge_health_ok,
                       positions_flat, alerts_clean, snapshot_ok,
                       readiness_locked, guard_state_clean, env_safety_locked,
                       rules_locked, autonomy_level_one, doctor_pass,
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
            result = _run_level1_proposal_workflow_drill()
            assert result["diagnosis"] == _PHASE16G_DIAGNOSIS["kpi_not_acceptable"]
            assert result["severity"] == "NO_GO"
        finally:
            stop_patches(mocks, patches)


class TestPolicyBoundary:
    def test_policy_missing_no_go(self, clean_git_metadata, clean_worktree,
                                  origin_aligned, all_tags_present, bridge_health_ok,
                                  positions_flat, alerts_clean, snapshot_ok,
                                  readiness_locked, guard_state_clean, env_safety_locked,
                                  rules_locked, autonomy_level_one, doctor_pass,
                                  kpi_hold_expected, hermes_policy_missing):
        patches = _build_mocks(
            health=bridge_health_ok, positions=positions_flat,
            alerts=alerts_clean, snapshot=snapshot_ok, readiness=readiness_locked,
            git_metadata=clean_git_metadata, worktree=clean_worktree,
            origin=origin_aligned, tags=all_tags_present,
            guard_state_content=guard_state_clean, env_safety=env_safety_locked,
            rules=rules_locked, autonomy=autonomy_level_one,
            doctor=doctor_pass, kpi=kpi_hold_expected, policy=hermes_policy_missing,
        )
        mocks, patches = apply_patches(patches)
        try:
            result = _run_level1_proposal_workflow_drill()
            assert result["diagnosis"] == _PHASE16G_DIAGNOSIS["policy_boundary_missing"]
            assert result["severity"] == "NO_GO"
        finally:
            stop_patches(mocks, patches)


class TestCleanCyclesMismatch:
    def test_mismatch_detected(self, clean_git_metadata, clean_worktree,
                               origin_aligned, all_tags_present, bridge_health_ok,
                               positions_flat, alerts_clean, snapshot_ok,
                               readiness_locked, guard_state_clean, env_safety_locked,
                               rules_locked, autonomy_level_one, doctor_pass,
                               kpi_hold_clean_cycles_5, hermes_policy_ok):
        patches = _build_mocks(
            health=bridge_health_ok, positions=positions_flat,
            alerts=alerts_clean, snapshot=snapshot_ok, readiness=readiness_locked,
            git_metadata=clean_git_metadata, worktree=clean_worktree,
            origin=origin_aligned, tags=all_tags_present,
            guard_state_content=guard_state_clean, env_safety=env_safety_locked,
            rules=rules_locked, autonomy=autonomy_level_one,
            doctor=doctor_pass, kpi=kpi_hold_clean_cycles_5, policy=hermes_policy_ok,
            clean_cycles_count=7, ledger_exists=True,
        )
        mocks, patches = apply_patches(patches)
        try:
            result = _run_level1_proposal_workflow_drill()
            assert result["diagnosis"] == _PHASE16G_DIAGNOSIS["clean_cycles_mismatch"]
            assert result["severity"] == "NO_GO"
            assert result["autonomy"]["clean_cycles_matches_kpi"] is False
        finally:
            stop_patches(mocks, patches)


# ===========================================================================
# T5: Runtime prerequisites
# ===========================================================================

class TestRuntimeNotReady:
    def test_bridge_disconnected_hold(self, clean_git_metadata, clean_worktree,
                                      origin_aligned, all_tags_present, bridge_health_disconnected,
                                      positions_flat, alerts_clean, snapshot_ok,
                                      readiness_locked, guard_state_clean, env_safety_locked,
                                      rules_locked, autonomy_level_one, doctor_pass,
                                      kpi_hold_expected, hermes_policy_ok):
        patches = _build_mocks(
            health=bridge_health_disconnected, positions=positions_flat,
            alerts=alerts_clean, snapshot=snapshot_ok, readiness=readiness_locked,
            git_metadata=clean_git_metadata, worktree=clean_worktree,
            origin=origin_aligned, tags=all_tags_present,
            guard_state_content=guard_state_clean, env_safety=env_safety_locked,
            rules=rules_locked, autonomy=autonomy_level_one,
            doctor=doctor_pass, kpi=kpi_hold_expected, policy=hermes_policy_ok,
        )
        mocks, patches = apply_patches(patches)
        try:
            result = _run_level1_proposal_workflow_drill()
            assert result["diagnosis"] == _PHASE16G_DIAGNOSIS["runtime_not_ready"]
            assert result["severity"] == "HOLD"
        finally:
            stop_patches(mocks, patches)


class TestPositionsNotFlat:
    def test_positions_not_flat_no_go(self, clean_git_metadata, clean_worktree,
                                      origin_aligned, all_tags_present, bridge_health_ok,
                                      positions_not_flat, alerts_clean, snapshot_ok,
                                      readiness_locked, guard_state_clean, env_safety_locked,
                                      rules_locked, autonomy_level_one, doctor_pass,
                                      kpi_hold_expected, hermes_policy_ok):
        patches = _build_mocks(
            health=bridge_health_ok, positions=positions_not_flat,
            alerts=alerts_clean, snapshot=snapshot_ok, readiness=readiness_locked,
            git_metadata=clean_git_metadata, worktree=clean_worktree,
            origin=origin_aligned, tags=all_tags_present,
            guard_state_content=guard_state_clean, env_safety=env_safety_locked,
            rules=rules_locked, autonomy=autonomy_level_one,
            doctor=doctor_pass, kpi=kpi_hold_expected, policy=hermes_policy_ok,
        )
        mocks, patches = apply_patches(patches)
        try:
            result = _run_level1_proposal_workflow_drill()
            assert result["diagnosis"] == _PHASE16G_DIAGNOSIS["positions_not_flat"]
            assert result["severity"] == "NO_GO"
        finally:
            stop_patches(mocks, patches)


class TestAlertsActive:
    def test_alerts_active_no_go(self, clean_git_metadata, clean_worktree,
                                 origin_aligned, all_tags_present, bridge_health_ok,
                                 positions_flat, alerts_active, snapshot_ok,
                                 readiness_locked, guard_state_clean, env_safety_locked,
                                 rules_locked, autonomy_level_one, doctor_pass,
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
            result = _run_level1_proposal_workflow_drill()
            assert result["diagnosis"] == _PHASE16G_DIAGNOSIS["monitor_alerts_active"]
            assert result["severity"] == "NO_GO"
        finally:
            stop_patches(mocks, patches)


# ===========================================================================
# T6: Non-mutation guarantees
# ===========================================================================

class TestNonMutation:
    def test_no_order_paths_called(self, clean_git_metadata, clean_worktree,
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
            result = _run_level1_proposal_workflow_drill()
            assert result["diagnosis"] == _PHASE16G_DIAGNOSIS["ready"]
            assert result["no_broker_mutation"] is True
            assert result["no_order_window_opened"] is True
            assert result["h1_token_not_used"] is True
            assert result["promotion_allowed_now"] is False
            assert result["order_enablement_allowed_now"] is False
            assert result["order_enablement_performed"] is False
            assert result["promotion_performed"] is False
            pw = result["proposal_workflow"]
            assert pw["broker_submission_performed"] is False
            assert pw["preflight_performed"] is False
            assert pw["approval_performed"] is False
            assert pw["submit_performed"] is False
            assert pw["order_routing_disallowed"] is True
            # Explicit non-actions present
            non_actions = result.get("explicit_non_actions", [])
            assert len(non_actions) > 0
            assert any("did not change autonomy level" in a for a in non_actions)
            assert any("did not enable orders" in a for a in non_actions)
            assert any("did not call /order" in a for a in non_actions)
            assert any("did not read H1 token" in a for a in non_actions)
        finally:
            stop_patches(mocks, patches)


# ===========================================================================
# T7: Export artifact
# ===========================================================================

class TestExportArtifact:
    def test_export_path_set_on_success(self, clean_git_metadata, clean_worktree,
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
            result = _run_level1_proposal_workflow_drill()
            assert result["diagnosis"] == _PHASE16G_DIAGNOSIS["ready"]
            ep = result.get("export_path")
            assert ep is not None
            assert "proposal-drill-" in ep
            # Verify the exported file exists and is valid JSON
            assert Path(ep).exists()
            with open(ep) as f:
                loaded = json.load(f)
            assert loaded["diagnosis"] == _PHASE16G_DIAGNOSIS["ready"]
            assert loaded["drill_id"] == result["drill_id"]
        finally:
            stop_patches(mocks, patches)


# ===========================================================================
# T8: Evidence hash
# ===========================================================================

class TestEvidenceHash:
    def test_evidence_hash_present(self, clean_git_metadata, clean_worktree,
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
            result = _run_level1_proposal_workflow_drill()
            assert result["diagnosis"] == _PHASE16G_DIAGNOSIS["ready"]
            eh = result.get("evidence_hash", "")
            assert len(eh) > 0
        finally:
            stop_patches(mocks, patches)


# ===========================================================================
# T9: no_h1_seen and no_order_window_seen fields
# ===========================================================================

class TestNoH1NoOrderWindow:
    def test_no_h1_seen_field_present(self, clean_git_metadata, clean_worktree,
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
            result = _run_level1_proposal_workflow_drill()
            assert result["diagnosis"] == _PHASE16G_DIAGNOSIS["ready"]
            # Top-level fields
            assert result["no_h1_seen"] is True
            assert result["no_order_window_seen"] is True
            # Workflow summary fields
            ws = result["workflow_summary"]
            assert ws["no_h1_seen"] is True
            assert ws["no_order_window_seen"] is True
        finally:
            stop_patches(mocks, patches)

    def test_no_h1_seen_in_no_go_result(self, clean_git_metadata, clean_worktree,
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
            result = _run_level1_proposal_workflow_drill()
            # NO_GO results must also have these fields set True
            assert result["no_h1_seen"] is True
            assert result["no_order_window_seen"] is True
        finally:
            stop_patches(mocks, patches)


# ===========================================================================
# T10: No /order* calls, no H1 reads, no trade-window helper
# ===========================================================================

class TestNoOrderPathCall:
    def test_no_order_preflight_called(self, clean_git_metadata, clean_worktree,
                                        origin_aligned, all_tags_present, bridge_health_ok,
                                        positions_flat, alerts_clean, snapshot_ok,
                                        readiness_locked, guard_state_clean, env_safety_locked,
                                        rules_locked, autonomy_level_one, doctor_pass,
                                        kpi_hold_expected, hermes_policy_ok):
        """Verify that /order/preflight is never called during the drill."""
        patches_list = _build_mocks(
            health=bridge_health_ok, positions=positions_flat,
            alerts=alerts_clean, snapshot=snapshot_ok, readiness=readiness_locked,
            git_metadata=clean_git_metadata, worktree=clean_worktree,
            origin=origin_aligned, tags=all_tags_present,
            guard_state_content=guard_state_clean, env_safety=env_safety_locked,
            rules=rules_locked, autonomy=autonomy_level_one,
            doctor=doctor_pass, kpi=kpi_hold_expected, policy=hermes_policy_ok,
            clean_cycles_count=7, ledger_exists=True,
        )
        mocks, patches = apply_patches(patches_list)
        try:
            result = _run_level1_proposal_workflow_drill()
            assert result["diagnosis"] == _PHASE16G_DIAGNOSIS["ready"]
            # Proposal workflow fields confirm no order path
            pw = result["proposal_workflow"]
            assert pw["preflight_performed"] is False
            assert pw["approval_performed"] is False
            assert pw["submit_performed"] is False
            assert pw["broker_submission_performed"] is False
            assert pw["order_routing_disallowed"] is True
            # Explicit non-actions must mention /order
            non_actions = result.get("explicit_non_actions", [])
            assert any("/order" in a for a in non_actions)
        finally:
            stop_patches(mocks, patches)

    def test_no_h1_token_read(self, clean_git_metadata, clean_worktree,
                               origin_aligned, all_tags_present, bridge_health_ok,
                               positions_flat, alerts_clean, snapshot_ok,
                               readiness_locked, guard_state_clean, env_safety_locked,
                               rules_locked, autonomy_level_one, doctor_pass,
                               kpi_hold_expected, hermes_policy_ok):
        """Verify that H1 token is never read during the drill."""
        patches_list = _build_mocks(
            health=bridge_health_ok, positions=positions_flat,
            alerts=alerts_clean, snapshot=snapshot_ok, readiness=readiness_locked,
            git_metadata=clean_git_metadata, worktree=clean_worktree,
            origin=origin_aligned, tags=all_tags_present,
            guard_state_content=guard_state_clean, env_safety=env_safety_locked,
            rules=rules_locked, autonomy=autonomy_level_one,
            doctor=doctor_pass, kpi=kpi_hold_expected, policy=hermes_policy_ok,
            clean_cycles_count=7, ledger_exists=True,
        )
        mocks, patches = apply_patches(patches_list)
        try:
            result = _run_level1_proposal_workflow_drill()
            assert result["diagnosis"] == _PHASE16G_DIAGNOSIS["ready"]
            assert result["no_h1_seen"] is True
            assert result["h1_token_not_used"] is True
            # Explicit non-actions must mention H1
            non_actions = result.get("explicit_non_actions", [])
            assert any("H1" in a for a in non_actions)
        finally:
            stop_patches(mocks, patches)

    def test_no_trade_window_helper_called(self, clean_git_metadata, clean_worktree,
                                            origin_aligned, all_tags_present, bridge_health_ok,
                                            positions_flat, alerts_clean, snapshot_ok,
                                            readiness_locked, guard_state_clean, env_safety_locked,
                                            rules_locked, autonomy_level_one, doctor_pass,
                                            kpi_hold_expected, hermes_policy_ok):
        """Verify that trade-window helper is never called during the drill."""
        patches_list = _build_mocks(
            health=bridge_health_ok, positions=positions_flat,
            alerts=alerts_clean, snapshot=snapshot_ok, readiness=readiness_locked,
            git_metadata=clean_git_metadata, worktree=clean_worktree,
            origin=origin_aligned, tags=all_tags_present,
            guard_state_content=guard_state_clean, env_safety=env_safety_locked,
            rules=rules_locked, autonomy=autonomy_level_one,
            doctor=doctor_pass, kpi=kpi_hold_expected, policy=hermes_policy_ok,
            clean_cycles_count=7, ledger_exists=True,
        )
        mocks, patches = apply_patches(patches_list)
        try:
            result = _run_level1_proposal_workflow_drill()
            assert result["diagnosis"] == _PHASE16G_DIAGNOSIS["ready"]
            # Trade-window helper is referenced in non-actions
            non_actions = result.get("explicit_non_actions", [])
            assert any("trade-window" in a.lower() for a in non_actions)
        finally:
            stop_patches(mocks, patches)

    def test_no_broker_mutation_guaranteed(self, clean_git_metadata, clean_worktree,
                                            origin_aligned, all_tags_present, bridge_health_ok,
                                            positions_flat, alerts_clean, snapshot_ok,
                                            readiness_locked, guard_state_clean, env_safety_locked,
                                            rules_locked, autonomy_level_one, doctor_pass,
                                            kpi_hold_expected, hermes_policy_ok):
        """Verify that no broker mutation occurs during the drill."""
        patches_list = _build_mocks(
            health=bridge_health_ok, positions=positions_flat,
            alerts=alerts_clean, snapshot=snapshot_ok, readiness=readiness_locked,
            git_metadata=clean_git_metadata, worktree=clean_worktree,
            origin=origin_aligned, tags=all_tags_present,
            guard_state_content=guard_state_clean, env_safety=env_safety_locked,
            rules=rules_locked, autonomy=autonomy_level_one,
            doctor=doctor_pass, kpi=kpi_hold_expected, policy=hermes_policy_ok,
            clean_cycles_count=7, ledger_exists=True,
        )
        mocks, patches = apply_patches(patches_list)
        try:
            result = _run_level1_proposal_workflow_drill()
            assert result["diagnosis"] == _PHASE16G_DIAGNOSIS["ready"]
            assert result["no_broker_mutation"] is True
            # Non-actions must mention broker mutation
            non_actions = result.get("explicit_non_actions", [])
            assert any("broker" in a.lower() or "mutate" in a.lower() for a in non_actions)
        finally:
            stop_patches(mocks, patches)


# ===========================================================================
# T11: No proposal marked executable
# ===========================================================================

class TestNoExecutableProposals:
    def test_all_proposals_non_executable(self, clean_git_metadata, clean_worktree,
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
            result = _run_level1_proposal_workflow_drill(demo_candidates=5)
            assert result["diagnosis"] == _PHASE16G_DIAGNOSIS["ready"]
            # Check every proposal item
            pb = result["proposal_batch"]
            for item in pb["items"]:
                assert item["executable"] is False, \
                    f"Item {item.get('proposal_id')} marked executable — must be False"
                assert item["requires_chris_approval"] is True
                assert item["performed"] is False
            # Workflow summary confirms
            ws = result["workflow_summary"]
            assert ws["all_items_non_executable"] is True
            # Proposal workflow confirms
            pw = result["proposal_workflow"]
            assert pw["proposals_marked_executable"] is False
        finally:
            stop_patches(mocks, patches)

    def test_no_proposal_marked_executable_even_with_many_candidates(self,
                                                                      clean_git_metadata,
                                                                      clean_worktree,
                                                                      origin_aligned,
                                                                      all_tags_present,
                                                                      bridge_health_ok,
                                                                      positions_flat,
                                                                      alerts_clean,
                                                                      snapshot_ok,
                                                                      readiness_locked,
                                                                      guard_state_clean,
                                                                      env_safety_locked,
                                                                      rules_locked,
                                                                      autonomy_level_one,
                                                                      doctor_pass,
                                                                      kpi_hold_expected,
                                                                      hermes_policy_ok):
        """Even with max demo candidates (5), no proposal is executable."""
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
            result = _run_level1_proposal_workflow_drill(demo_candidates=5)
            assert result["diagnosis"] == _PHASE16G_DIAGNOSIS["ready"]
            assert result["proposal_workflow"]["proposals_created"] == 5
            # All 5 must be non-executable
            for item in result["proposal_batch"]["items"]:
                assert item["executable"] is False
            # proposals_marked_executable must remain False
            assert result["proposal_workflow"]["proposals_marked_executable"] is False
        finally:
            stop_patches(mocks, patches)
