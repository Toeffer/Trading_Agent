"""Tests for Phase 16P — Level 1 Order-Window Canary Negative-Control Drill.

Expanded spec coverage:
  - order_window_canary section (status="closed_as_expected", full schema)
  - canary_negative_controls section (controls[], controls_count, etc.)
  - h1_boundary_probe section
  - order_window_matrix section
  - blocked_canary_attempts[] array (with helper_called, h1_token_used, order_window_opened)
  - order_window_checklist (21 entries)
  - workflow_summary (expanded)
  - All prerequisite NO_GO cases (18+ distinct scenarios)
  - Non-mutation guarantees (no /order*, no H1, no trade-window helper)
"""

import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from datetime import datetime, timezone, timedelta
_TODAY_STR = datetime.now(timezone.utc).strftime("%Y-%m-%d")
_YESTERDAY_STR = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")


BRIDGE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BRIDGE_DIR))

from ibkr_operator import (
    _run_level1_order_window_canary_negative_control_drill,
    _PHASE16P_DIAGNOSIS,
    _PHASE16P_REQUIRED_TAGS,
    _PHASE16P_EXPORT_DIR,
    _PHASE16P_EXPLICIT_NON_ACTIONS,
)


# ===========================================================================
# Fixtures
# ===========================================================================

@pytest.fixture
def clean_git_metadata():
    return {"branch": "master", "commit_short": "abc1234",
            "commit": "abc1234abc1234abc1234abc1234abc1234abc",
            "tag": "phase16o_level1_execution_gate_negative_control_drill"}


@pytest.fixture
def clean_worktree():
    return {"clean": True, "dirty_files": []}


@pytest.fixture
def dirty_worktree():
    return {"clean": False, "dirty_files": ["ibkr_operator.py"]}


@pytest.fixture
def origin_aligned():
    return {"aligned": True, "local_master_commit": "abc1234",
            "origin_master_commit": "abc1234"}


@pytest.fixture
def all_tags_present():
    return {"present_count": len(_PHASE16P_REQUIRED_TAGS),
            "present": list(_PHASE16P_REQUIRED_TAGS)}


@pytest.fixture
def one_tag_missing():
    missing = [_PHASE16P_REQUIRED_TAGS[0]]
    present = list(_PHASE16P_REQUIRED_TAGS[1:])
    return {"present_count": len(present), "present": present}


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
def positions_not_flat():
    return {"positions": [{"symbol": "SPY", "position": 100.0}]}


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
    return {"summary": {"kill_switches": {"system_locked": True},
                        "allow_orders": False}}


@pytest.fixture
def guard_state_clean():
    return json.dumps({"schema_version": 1, "trade_date": _TODAY_STR,
                       "daily_trade_count": 0, "daily_halt_active": False})


@pytest.fixture
def env_safety_locked():
    return {"IBKR_ALLOW_ORDERS": "false", "found": True}


@pytest.fixture
def rules_locked():
    return {"enforced": "false", "found": True}


@pytest.fixture
def autonomy_level_one():
    return "1"


@pytest.fixture
def doctor_pass():
    return {"pass": True, "passed": 14, "total": 15,
            "passed_count": 14, "check_count": 15,
            "checks": [{"check": "h1_token_canary", "ok": True, "status": "PASS"}]}


@pytest.fixture
def doctor_h1_manual():
    return {"pass": False, "passed": 14, "total": 15,
            "passed_count": 14, "check_count": 15,
            "checks": [{"check": "h1_token_canary", "ok": False, "status": "MANUAL_REQUIRED"}]}


@pytest.fixture
def kpi_hold_expected():
    return {"verdict": "HOLD",
            "blockers": [{"severity": "HOLD", "check": "system_locked"}],
            "autonomy": {"clean_cycles": 7}}


@pytest.fixture
def hermes_policy_ok():
    return {"hermes_policy_exists": True, "execution_path_ok": True, "advisory_boundary_ok": True}


@pytest.fixture
def hermes_policy_missing():
    return {"hermes_policy_exists": False, "execution_path_ok": False, "advisory_boundary_ok": False}


@pytest.fixture
def env_safety_unlocked():
    return {"IBKR_ALLOW_ORDERS": "true", "found": True}


@pytest.fixture
def rules_unlocked():
    return {"enforced": "true", "found": True}


@pytest.fixture
def readiness_unlocked():
    return {"summary": {"kill_switches": {"system_locked": False},
                        "allow_orders": True}}


@pytest.fixture
def autonomy_level_zero():
    return "0"


@pytest.fixture
def doctor_fail():
    return {"pass": False, "passed": 10, "total": 15,
            "passed_count": 10, "check_count": 15,
            "checks": [{"check": "h1_token_canary", "ok": False, "status": "FAIL"}]}


@pytest.fixture
def kpi_no_go():
    return {"verdict": "NO-GO",
            "blockers": [{"severity": "NO-GO", "check": "active_alerts"}],
            "autonomy": {"clean_cycles": 7}}


@pytest.fixture
def kpi_hold_clean_cycles_5():
    return {"verdict": "HOLD",
            "blockers": [{"severity": "HOLD", "check": "system_locked"}],
            "autonomy": {"clean_cycles": 5}}


@pytest.fixture
def guard_state_stale():
    return json.dumps({"schema_version": 1, "trade_date": _YESTERDAY_STR,
                       "daily_trade_count": 0, "daily_halt_active": False})


@pytest.fixture
def guard_state_with_trades():
    return json.dumps({"schema_version": 1, "trade_date": _TODAY_STR,
                       "daily_trade_count": 3, "daily_halt_active": False})


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
    patches.append(patch("ibkr_operator._PHASE16P_EXPORT_DIR", tmp_export))
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
        import subprocess
        r = subprocess.run([sys.executable, str(BRIDGE_DIR / "ibkr_operator.py"),
                           "level1-order-window-canary-negative-control-drill", "--help"],
                          capture_output=True, text=True, timeout=10)
        assert r.returncode == 0

    def test_alias_phase16p_works(self):
        import subprocess
        r = subprocess.run([sys.executable, str(BRIDGE_DIR / "ibkr_operator.py"),
                           "phase16p-order-window-canary-negative-control-drill", "--help"],
                          capture_output=True, text=True, timeout=10)
        assert r.returncode == 0

    def test_alias_level1_order_window_negative_control_works(self):
        import subprocess
        r = subprocess.run([sys.executable, str(BRIDGE_DIR / "ibkr_operator.py"),
                           "level1-order-window-negative-control-drill", "--help"],
                          capture_output=True, text=True, timeout=10)
        assert r.returncode == 0

    def test_alias_order_window_canary_negative_control_works(self):
        import subprocess
        r = subprocess.run([sys.executable, str(BRIDGE_DIR / "ibkr_operator.py"),
                           "order-window-canary-negative-control-drill", "--help"],
                          capture_output=True, text=True, timeout=10)
        assert r.returncode == 0


# ===========================================================================
# T2: Clean runtime => OK with full field verification
# ===========================================================================

class TestCleanRuntime:
    def test_clean_runtime_all_fields(self, clean_git_metadata, clean_worktree,
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
            result = _run_level1_order_window_canary_negative_control_drill(demo_candidates=3)
            assert result["diagnosis"] == _PHASE16P_DIAGNOSIS["ready"]
            assert result["severity"] == "OK"
            assert result["order_window_closed_as_expected"] is True
            assert result["all_canaries_blocked"] is True
            assert result["no_canary_executed"] is True

            # order_window_canary (expanded schema)
            owc = result["order_window_canary"]
            assert owc["status"] == "closed_as_expected"
            assert owc["canary_type"] == "ORDER_WINDOW_NEGATIVE_CONTROL"
            assert owc["negative_control_only"] is True
            assert owc["order_window_open"] is False
            assert owc["order_window_opened_by_drill"] is False
            assert owc["h1_token_available_to_drill"] is False
            assert owc["h1_token_read"] is False
            assert owc["h1_token_used"] is False
            assert owc["trade_window_helper_path"] == "/usr/local/sbin/ibkr-trade-window"
            assert owc["trade_window_helper_called"] is False
            assert owc["trade_window_helper_invoked"] is False
            assert owc["approval_endpoint_called"] is False
            assert owc["submit_endpoint_called"] is False
            assert owc["preflight_endpoint_called"] is False
            assert owc["order_endpoint_called"] is False
            assert owc["broker_order_created"] is False
            assert owc["broker_mutation"] is False
            assert owc["canary_expected_status"] == "MANUAL_REQUIRED"
            assert owc["canary_performed"] is False
            assert owc["canary_blocked"] is True
            assert owc["canary_block_reason"] == "order_window_closed_and_h1_not_available_to_drill"
            assert owc["future_order_window_required"] is True
            assert owc["future_h1_required"] is True
            assert owc["future_real_preflight_required"] is True
            assert owc["future_real_approval_required"] is True
            assert owc["future_real_submit_required"] is True
            assert "future_required_path" in owc
            assert owc["canaries_count"] == 3
            assert owc["canaries_blocked_count"] == 3
            assert owc["canaries_not_blocked_count"] == 0

            # canary_negative_controls
            cnc = result["canary_negative_controls"]
            assert cnc["controls_count"] == 3
            assert cnc["controls_passed_count"] == 3
            assert cnc["controls_failed_count"] == 0
            assert len(cnc["controls"]) == 3
            for ctrl in cnc["controls"]:
                assert ctrl["expected_block"] is True
                assert ctrl["actually_blocked"] is True
                assert ctrl["endpoint_called"] is False
                assert ctrl["helper_called"] is False
                assert ctrl["h1_token_used"] is False
                assert ctrl["order_window_opened"] is False
                assert ctrl["broker_mutation"] is False
                assert "blocker_reason" in ctrl
                assert "description" in ctrl
                assert "control" in ctrl

            # h1_boundary_probe
            h1bp = result["h1_boundary_probe"]
            assert h1bp["probe_only"] is True
            assert h1bp["raw_token_path_checked"] is False
            assert h1bp["raw_token_read"] is False
            assert h1bp["env_hash_only_expected"] is True
            assert h1bp["h1_header_constructed"] is False
            assert h1bp["h1_header_sent"] is False
            assert h1bp["approval_token_used"] is False
            assert h1bp["canary_command_recommended_only"] is True
            assert h1bp["canary_command_executed"] is False
            assert h1bp["manual_canary_required"] is True

            # order_window_matrix
            owm = result["order_window_matrix"]
            assert owm["level1_execution_allowed"] is False
            assert owm["order_window_open"] is False
            assert owm["orders_enabled"] is False
            assert owm["system_locked"] is True
            assert owm["bridge_allow_orders"] is False
            assert owm["rules_enforced"] is False
            assert owm["h1_available_to_drill"] is False
            assert owm["real_preflight_done"] is False
            assert owm["real_approval_done"] is False
            assert owm["real_submit_done"] is False
            assert owm["broker_submission_allowed"] is False

            # canary_intents
            canaries = result["canary_intents"]
            assert len(canaries) == 3
            for c in canaries:
                assert c["canary_type"] == "ORDER_WINDOW_CANARY"
                assert c["simulated_canary_only"] is True
                assert c["blocked"] is True
                assert c["executable"] is False
                assert c["expected_result"] == "blocked"
                assert c["order_window_opened_by_drill"] is False
                assert c["h1_token_used"] is False
                assert c["h1_token_read"] is False
                assert c["h1_token_available_to_drill"] is False
                assert c["trade_window_helper_called"] is False
                assert c["order_endpoint_called"] is False
                assert c["preflight_endpoint_called"] is False
                assert c["approval_endpoint_called"] is False
                assert c["submit_endpoint_called"] is False
                assert c["broker_mutation"] is False
                assert c["broker_order_created"] is False
                assert c["gate_status"] == "GATE_CLOSED"
                assert c["source_stage"] == "16P_order_window_canary_negative_control"
                assert c["performed"] is False
                assert "requires_h1" in c
                assert "requires_order_window" in c
                assert "requested_action" in c
                assert "canary_description" in c
                assert len(c.get("blocking_reasons", [])) > 0

            # blocked_canary_attempts
            attempts = result["blocked_canary_attempts"]
            assert len(attempts) == 3
            for a in attempts:
                assert a["local_negative_control_only"] is True
                assert a["blocked"] is True
                assert a["endpoint_called"] is False
                assert a["helper_called"] is False
                assert a["h1_token_used"] is False
                assert a["order_window_opened"] is False
                assert a["broker_mutation"] is False
                assert a["executable"] is False
                assert a["performed"] is False
                assert len(a.get("block_reason", "")) > 0

            # order_window_checklist
            ncl = result["order_window_checklist"]
            assert len(ncl) == 21
            ncl_checks = {c["check"]: c["status"] for c in ncl}
            assert ncl_checks.get("confirms_order_window_closed") == "PASS"
            assert ncl_checks.get("confirms_order_window_not_opened_by_drill") == "PASS"
            assert ncl_checks.get("confirms_h1_not_read") == "PASS"
            assert ncl_checks.get("confirms_h1_not_used") == "PASS"
            assert ncl_checks.get("confirms_trade_window_helper_not_called") == "PASS"
            assert ncl_checks.get("confirms_no_order_endpoint_called") == "PASS"
            assert ncl_checks.get("confirms_no_preflight_endpoint_called") == "PASS"
            assert ncl_checks.get("confirms_no_approval_endpoint_called") == "PASS"
            assert ncl_checks.get("confirms_no_submit_endpoint_called") == "PASS"
            assert ncl_checks.get("confirms_future_order_window_required") == "PASS"
            assert ncl_checks.get("confirms_future_h1_required") == "PASS"
            assert ncl_checks.get("confirms_future_real_preflight_required") == "PASS"
            assert ncl_checks.get("confirms_future_real_approval_required") == "PASS"
            assert ncl_checks.get("confirms_future_real_submit_required") == "PASS"

            # workflow_summary
            wf = result["workflow_summary"]
            assert wf["order_window_canary_negative_control_ready"] is True
            assert wf["order_window_closed_as_expected"] is True
            assert wf["canary_blocked_as_expected"] is True
            assert wf["all_controls_blocked"] is True
            assert wf["all_blocks_expected"] is True
            assert wf["h1_boundary_preserved"] is True
            assert wf["trade_window_helper_not_called"] is True
            assert wf["execution_authorized_now_false"] is True
            assert wf["no_order_endpoint_called"] is True
            assert wf["no_h1_seen"] is True
            assert wf["no_order_window_seen"] is True
            assert wf["checklist_complete"] is True

            # Non-mutation
            assert result["no_broker_mutation"] is True
            assert result["no_order_endpoint_called"] is True
            assert result["no_trade_window_helper_called"] is True
            assert result["no_trade_window_helper_called_by_drill"] is True
            assert result["no_h1_seen"] is True
            assert result["h1_token_not_used"] is True
            assert result["no_order_window_opened"] is True
            assert result["no_order_window_seen"] is True
            assert result["export_path"] is not None
        finally:
            stop_patches(mocks, patches)

    def test_h1_manual_doctor_acceptable(self, clean_git_metadata, clean_worktree,
                                          origin_aligned, all_tags_present, bridge_health_ok,
                                          positions_flat, alerts_clean, snapshot_ok,
                                          readiness_locked, guard_state_clean, env_safety_locked,
                                          rules_locked, autonomy_level_one, doctor_h1_manual,
                                          kpi_hold_expected, hermes_policy_ok):
        """Doctor with H1 MANUAL_REQUIRED should still be acceptable."""
        patches = _build_mocks(
            health=bridge_health_ok, positions=positions_flat,
            alerts=alerts_clean, snapshot=snapshot_ok, readiness=readiness_locked,
            git_metadata=clean_git_metadata, worktree=clean_worktree,
            origin=origin_aligned, tags=all_tags_present,
            guard_state_content=guard_state_clean, env_safety=env_safety_locked,
            rules=rules_locked, autonomy=autonomy_level_one,
            doctor=doctor_h1_manual, kpi=kpi_hold_expected, policy=hermes_policy_ok,
            clean_cycles_count=7, ledger_exists=True,
        )
        mocks, patches = apply_patches(patches)
        try:
            result = _run_level1_order_window_canary_negative_control_drill(demo_candidates=2)
            assert result["diagnosis"] == _PHASE16P_DIAGNOSIS["ready"]
            assert result["severity"] == "OK"
        finally:
            stop_patches(mocks, patches)


# ===========================================================================
# T3: Prerequisite NO_GO cases
# ===========================================================================

class TestPrerequisiteFailures:
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
            result = _run_level1_order_window_canary_negative_control_drill()
            assert result["diagnosis"] == _PHASE16P_DIAGNOSIS["missing_required_tags"]
            assert result["severity"] == "NO_GO"
            # no_go result should still have all sections
            assert "canary_negative_controls" in result
            assert "h1_boundary_probe" in result
            assert "order_window_matrix" in result
            assert "order_window_checklist" in result
        finally:
            stop_patches(mocks, patches)

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
            result = _run_level1_order_window_canary_negative_control_drill()
            assert result["diagnosis"] == _PHASE16P_DIAGNOSIS["dirty_worktree"]
            assert result["severity"] == "NO_GO"
        finally:
            stop_patches(mocks, patches)

    def test_bridge_disconnected_no_go(self, clean_git_metadata, clean_worktree,
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
            result = _run_level1_order_window_canary_negative_control_drill()
            assert result["diagnosis"] == _PHASE16P_DIAGNOSIS["runtime_not_ready"]
            assert result["severity"] == "NO_GO"
        finally:
            stop_patches(mocks, patches)

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
            result = _run_level1_order_window_canary_negative_control_drill()
            assert result["diagnosis"] == _PHASE16P_DIAGNOSIS["positions_not_flat"]
            assert result["severity"] == "NO_GO"
        finally:
            stop_patches(mocks, patches)


# ===========================================================================
# T3b: Additional prerequisite NO_GO cases (autonomy, safety, guard, KPI, etc.)
# ===========================================================================

class TestAdditionalPrerequisiteFailures:
    def test_autonomy_level_zero_no_go(self, clean_git_metadata, clean_worktree,
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
            result = _run_level1_order_window_canary_negative_control_drill()
            assert result["diagnosis"] == _PHASE16P_DIAGNOSIS["autonomy_not_level1"]
            assert result["severity"] == "NO_GO"
        finally:
            stop_patches(mocks, patches)

    def test_safety_unlocked_env_allow_orders_no_go(self, clean_git_metadata, clean_worktree,
                                                     origin_aligned, all_tags_present, bridge_health_ok,
                                                     positions_flat, alerts_clean, snapshot_ok,
                                                     readiness_locked, guard_state_clean, env_safety_unlocked,
                                                     rules_locked, autonomy_level_one, doctor_pass,
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
            result = _run_level1_order_window_canary_negative_control_drill()
            assert result["diagnosis"] == _PHASE16P_DIAGNOSIS["safety_not_locked"]
            assert result["severity"] == "NO_GO"
        finally:
            stop_patches(mocks, patches)

    def test_safety_unlocked_system_not_locked_no_go(self, clean_git_metadata, clean_worktree,
                                                       origin_aligned, all_tags_present, bridge_health_ok,
                                                       positions_flat, alerts_clean, snapshot_ok,
                                                       readiness_unlocked, guard_state_clean, env_safety_locked,
                                                       rules_locked, autonomy_level_one, doctor_pass,
                                                       kpi_hold_expected, hermes_policy_ok):
        patches = _build_mocks(
            health=bridge_health_ok, positions=positions_flat,
            alerts=alerts_clean, snapshot=snapshot_ok, readiness=readiness_unlocked,
            git_metadata=clean_git_metadata, worktree=clean_worktree,
            origin=origin_aligned, tags=all_tags_present,
            guard_state_content=guard_state_clean, env_safety=env_safety_locked,
            rules=rules_locked, autonomy=autonomy_level_one,
            doctor=doctor_pass, kpi=kpi_hold_expected, policy=hermes_policy_ok,
        )
        mocks, patches = apply_patches(patches)
        try:
            result = _run_level1_order_window_canary_negative_control_drill()
            assert result["diagnosis"] == _PHASE16P_DIAGNOSIS["safety_not_locked"]
            assert result["severity"] == "NO_GO"
        finally:
            stop_patches(mocks, patches)

    def test_rules_enforced_no_go(self, clean_git_metadata, clean_worktree,
                                   origin_aligned, all_tags_present, bridge_health_ok,
                                   positions_flat, alerts_clean, snapshot_ok,
                                   readiness_locked, guard_state_clean, env_safety_locked,
                                   rules_unlocked, autonomy_level_one, doctor_pass,
                                   kpi_hold_expected, hermes_policy_ok):
        patches = _build_mocks(
            health=bridge_health_ok, positions=positions_flat,
            alerts=alerts_clean, snapshot=snapshot_ok, readiness=readiness_locked,
            git_metadata=clean_git_metadata, worktree=clean_worktree,
            origin=origin_aligned, tags=all_tags_present,
            guard_state_content=guard_state_clean, env_safety=env_safety_locked,
            rules=rules_unlocked, autonomy=autonomy_level_one,
            doctor=doctor_pass, kpi=kpi_hold_expected, policy=hermes_policy_ok,
        )
        mocks, patches = apply_patches(patches)
        try:
            result = _run_level1_order_window_canary_negative_control_drill()
            assert result["diagnosis"] == _PHASE16P_DIAGNOSIS["safety_not_locked"]
            assert result["severity"] == "NO_GO"
        finally:
            stop_patches(mocks, patches)

    def test_active_alerts_no_go(self, clean_git_metadata, clean_worktree,
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
            result = _run_level1_order_window_canary_negative_control_drill()
            assert result["diagnosis"] == _PHASE16P_DIAGNOSIS["monitor_alerts_active"]
            assert result["severity"] == "NO_GO"
        finally:
            stop_patches(mocks, patches)

    def test_doctor_not_acceptable_no_go(self, clean_git_metadata, clean_worktree,
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
            result = _run_level1_order_window_canary_negative_control_drill()
            assert result["diagnosis"] == _PHASE16P_DIAGNOSIS["doctor_not_acceptable"]
            assert result["severity"] == "NO_GO"
        finally:
            stop_patches(mocks, patches)

    def test_kpi_no_go_blocker_no_go(self, clean_git_metadata, clean_worktree,
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
            result = _run_level1_order_window_canary_negative_control_drill()
            assert result["diagnosis"] == _PHASE16P_DIAGNOSIS["kpi_not_acceptable"]
            assert result["severity"] == "NO_GO"
        finally:
            stop_patches(mocks, patches)

    def test_hermes_policy_missing_no_go(self, clean_git_metadata, clean_worktree,
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
            result = _run_level1_order_window_canary_negative_control_drill()
            assert result["diagnosis"] == _PHASE16P_DIAGNOSIS["policy_boundary_missing"]
            assert result["severity"] == "NO_GO"
        finally:
            stop_patches(mocks, patches)

    def test_clean_cycles_mismatch_no_go(self, clean_git_metadata, clean_worktree,
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
            result = _run_level1_order_window_canary_negative_control_drill()
            assert result["diagnosis"] == _PHASE16P_DIAGNOSIS["clean_cycles_mismatch"]
            assert result["severity"] == "NO_GO"
        finally:
            stop_patches(mocks, patches)

    def test_stale_guard_trade_date_no_go(self, clean_git_metadata, clean_worktree,
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
            result = _run_level1_order_window_canary_negative_control_drill()
            assert result["diagnosis"] == _PHASE16P_DIAGNOSIS["guard_state_not_clean"]
            assert result["severity"] == "NO_GO"
        finally:
            stop_patches(mocks, patches)

    def test_guard_daily_trade_count_gt_0_no_go(self, clean_git_metadata, clean_worktree,
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
            result = _run_level1_order_window_canary_negative_control_drill()
            assert result["diagnosis"] == _PHASE16P_DIAGNOSIS["guard_state_not_clean"]
            assert result["severity"] == "NO_GO"
        finally:
            stop_patches(mocks, patches)


# ===========================================================================
# T4: Edge cases
# ===========================================================================

class TestEdgeCases:
    def test_demo_candidates_zero(self, clean_git_metadata, clean_worktree,
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
            result = _run_level1_order_window_canary_negative_control_drill(demo_candidates=0)
            assert result["diagnosis"] == _PHASE16P_DIAGNOSIS["ready"]
            assert result["order_window_canary"]["canaries_count"] == 0
            assert result["canary_intents"] == []
            assert result["blocked_canary_attempts"] == []
            assert result["canary_negative_controls"]["controls_count"] == 0
            assert result["order_window_closed_as_expected"] is True
        finally:
            stop_patches(mocks, patches)

    def test_export_and_evidence(self, clean_git_metadata, clean_worktree,
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
            result = _run_level1_order_window_canary_negative_control_drill()
            assert len(result.get("evidence_hash", "")) > 0
            assert result.get("export_path") is not None
            assert Path(result["export_path"]).exists()
            assert result["order_window_canary"].get("canary_artifact_path") is not None
            assert result["workflow_summary"]["order_window_canary_artifact_created"] is True
        finally:
            stop_patches(mocks, patches)

    def test_non_mutation_verified(self, clean_git_metadata, clean_worktree,
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
            result = _run_level1_order_window_canary_negative_control_drill()
            assert result["no_preflight_endpoint_called"] is True
            assert result["no_approval_endpoint_called"] is True
            assert result["no_submit_endpoint_called"] is True
            assert result["no_order_endpoint_called"] is True
            assert result["no_trade_window_helper_called"] is True
            assert result["no_trade_window_helper_called_by_drill"] is True
            assert result["no_h1_seen"] is True
            assert result["h1_token_not_used"] is True
            assert result["no_order_window_opened"] is True
            non_actions = result.get("explicit_non_actions", [])
            assert any("did not call /order" in a for a in non_actions)
            assert any("did not call /order/preflight" in a for a in non_actions)
            assert any("did not call /order/approve" in a for a in non_actions)
            assert any("did not call /order/submit" in a for a in non_actions)
            assert any("did not read H1 token" in a for a in non_actions)
            assert any("did not use H1 token" in a for a in non_actions)
            assert any("did not call trade-window helper" in a for a in non_actions)
            assert any("did not open an order window" in a for a in non_actions)
            assert any("negative-control" in a.lower() for a in non_actions)
        finally:
            stop_patches(mocks, patches)

    def test_demo_candidates_max(self, clean_git_metadata, clean_worktree,
                                  origin_aligned, all_tags_present, bridge_health_ok,
                                  positions_flat, alerts_clean, snapshot_ok,
                                  readiness_locked, guard_state_clean, env_safety_locked,
                                  rules_locked, autonomy_level_one, doctor_pass,
                                  kpi_hold_expected, hermes_policy_ok):
        """Max 5 canaries even with higher demo_candidates."""
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
            result = _run_level1_order_window_canary_negative_control_drill(demo_candidates=10)
            assert result["order_window_canary"]["canaries_count"] == 5  # capped
            assert len(result["canary_intents"]) == 5
            assert len(result["blocked_canary_attempts"]) == 5
            assert result["canary_negative_controls"]["controls_count"] == 5
        finally:
            stop_patches(mocks, patches)

    def test_git_section_present(self, clean_git_metadata, clean_worktree,
                                  origin_aligned, all_tags_present, bridge_health_ok,
                                  positions_flat, alerts_clean, snapshot_ok,
                                  readiness_locked, guard_state_clean, env_safety_locked,
                                  rules_locked, autonomy_level_one, doctor_pass,
                                  kpi_hold_expected, hermes_policy_ok):
        """Verify git, runtime, autonomy, safety, guard_state sections present."""
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
            result = _run_level1_order_window_canary_negative_control_drill()
            # git
            assert "branch" in result["git"]
            assert "commit" in result["git"]
            assert "worktree_clean" in result["git"]
            # runtime
            assert "bridge_reachable" in result["runtime"]
            assert "positions_count" in result["runtime"]
            assert "active_alerts_count" in result["runtime"]
            # safety
            assert "env_IBKR_ALLOW_ORDERS" in result["safety"]
            assert "system_locked" in result["safety"]
            # autonomy
            assert "current_level" in result["autonomy"]
            assert "clean_cycles" in result["autonomy"]
            # guard_state
            assert "daily_trade_count" in result.get("guard_state", {})
            # doctor / kpi / policy
            assert "h1_canary_status" in result.get("doctor_summary", {})
            assert "verdict" in result.get("kpi_summary", {})
            assert "hermes_policy_exists" in result.get("policy_summary", {})
        finally:
            stop_patches(mocks, patches)
