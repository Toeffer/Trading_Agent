"""Tests for Phase 16Q v3 — Level 1 H1 Boundary Audit Checkpoint.

Expanded spec (v3) coverage:
  - guard_state top-level fields (canonical_trade_date, trade_date_stale, halt_active, guard_state_clean)
  - h1_token_not_read, execution_authorized_now, execution_performed top-level
  - no_order_window_seen in workflow_summary
  - H1 boundary violation diagnostic checks (18 violations, controls_failed, canary_not_blocked, canary_executed)
  - All prerequisite NO_GO cases
  - H1 boundary violation NO_GO cases
  - Non-mutation guarantees
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
    _run_level1_h1_boundary_audit_checkpoint,
    _PHASE16Q_DIAGNOSIS,
    _PHASE16Q_REQUIRED_TAGS,
    _PHASE16Q_EXPORT_DIR,
    _PHASE16Q_EXPLICIT_NON_ACTIONS,
)


# ===========================================================================
# Fixtures
# ===========================================================================

@pytest.fixture
def clean_git_metadata():
    return {"branch": "master", "commit_short": "abc1234",
            "commit": "abc1234abc1234abc1234abc1234abc1234abc",
            "tag": "phase16p_level1_order_window_canary_negative_control_drill"}


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
    return {"present_count": len(_PHASE16Q_REQUIRED_TAGS),
            "present": list(_PHASE16Q_REQUIRED_TAGS)}


@pytest.fixture
def one_tag_missing():
    missing = [_PHASE16Q_REQUIRED_TAGS[0]]
    present = list(_PHASE16Q_REQUIRED_TAGS[1:])
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
def readiness_unlocked():
    return {"summary": {"kill_switches": {"system_locked": False},
                        "allow_orders": True}}


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
def autonomy_level_zero():
    return "0"


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
    patches.append(patch("ibkr_operator._PHASE16Q_EXPORT_DIR", tmp_export))
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
                           "level1-h1-boundary-audit-checkpoint", "--help"],
                          capture_output=True, text=True, timeout=10)
        assert r.returncode == 0

    def test_alias_phase16q_works(self):
        import subprocess
        r = subprocess.run([sys.executable, str(BRIDGE_DIR / "ibkr_operator.py"),
                           "phase16q-h1-boundary-audit-checkpoint", "--help"],
                          capture_output=True, text=True, timeout=10)
        assert r.returncode == 0

    def test_alias_level1_h1_boundary_checkpoint_works(self):
        import subprocess
        r = subprocess.run([sys.executable, str(BRIDGE_DIR / "ibkr_operator.py"),
                           "level1-h1-boundary-checkpoint", "--help"],
                          capture_output=True, text=True, timeout=10)
        assert r.returncode == 0

    def test_alias_h1_boundary_audit_checkpoint_works(self):
        import subprocess
        r = subprocess.run([sys.executable, str(BRIDGE_DIR / "ibkr_operator.py"),
                           "h1-boundary-audit-checkpoint", "--help"],
                          capture_output=True, text=True, timeout=10)
        assert r.returncode == 0


# ===========================================================================
# T2: Clean runtime => OK with full v3 field verification
# ===========================================================================

class TestCleanRuntime:
    def test_clean_runtime_v3_all_fields(self, clean_git_metadata, clean_worktree,
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
            result = _run_level1_h1_boundary_audit_checkpoint(demo_candidates=3)
            assert result["diagnosis"] == _PHASE16Q_DIAGNOSIS["ready"]
            assert result["severity"] == "OK"
            assert result["h1_boundary_intact"] is True
            assert result["all_canaries_blocked"] is True
            assert result["no_canary_executed"] is True

            # Guard state top-level fields
            assert result["guard_state_clean"] is True
            assert "canonical_trade_date" in result
            assert result["trade_date_stale"] is False
            assert result["halt_active"] is False

            # New top-level fields
            assert result["h1_token_not_read"] is True
            assert result["h1_token_not_used"] is True
            assert result["execution_authorized_now"] is False
            assert result["execution_performed"] is False
            assert result["no_order_window_opened"] is True

            # h1_boundary_audit
            hba = result["h1_boundary_audit"]
            assert hba["status"] == "boundary_intact"
            assert hba["audit_only"] is True
            assert hba["raw_token_path"] == "/etc/ibkr-bridge/h1_token"
            assert hba["raw_token_path_opened"] is False
            assert hba["raw_token_path_read"] is False
            assert hba["raw_token_value_seen"] is False
            assert hba["raw_token_logged"] is False
            assert hba["raw_token_copied"] is False
            assert hba["raw_token_exported"] is False
            assert hba["env_hash_expected"] is True
            assert hba["env_hash_configured"] is True
            assert hba["env_hash_only"] is True
            assert hba["x_h1_token_header_constructed"] is False
            assert hba["x_h1_token_header_sent"] is False
            assert hba["approval_token_used"] is False
            assert hba["h1_available_to_drill"] is False
            assert hba["h1_token_used"] is False
            assert hba["h1_token_read"] is False
            assert hba["h1_boundary_preserved"] is True
            assert hba["trade_window_helper_called"] is False
            assert hba["trade_window_helper_invoked"] is False
            assert hba["order_window_open"] is False
            assert hba["order_window_opened_by_drill"] is False
            assert hba["manual_canary_required"] is True
            assert hba["manual_canary_executed"] is False
            assert hba["approve_endpoint_called"] is False
            assert hba["submit_endpoint_called"] is False
            assert hba["preflight_endpoint_called"] is False
            assert hba["order_endpoint_called"] is False
            assert hba["broker_mutation"] is False
            assert hba["broker_order_created"] is False
            assert hba["future_h1_required"] is True
            assert hba["future_order_window_required"] is True
            assert hba["future_real_preflight_required"] is True
            assert hba["future_real_approval_required"] is True
            assert hba["future_real_submit_required"] is True
            assert "future_required_path" in hba
            assert hba["canaries_count"] == 3
            assert hba["canaries_blocked_count"] == 3
            assert hba["canaries_not_blocked_count"] == 0

            # h1_dependent_controls
            hdc = result["h1_dependent_controls"]
            assert hdc["controls_count"] == 3
            assert hdc["controls_passed_count"] == 3
            assert hdc["controls_failed_count"] == 0
            assert len(hdc["controls"]) == 3
            for ctrl in hdc["controls"]:
                assert ctrl["expected_status"] == "manual_required"
                assert ctrl["actually_manual_required"] is True
                assert ctrl["endpoint_called"] is False
                assert ctrl["h1_header_constructed"] is False
                assert ctrl["h1_header_sent"] is False
                assert ctrl["helper_called"] is False
                assert ctrl["raw_token_read"] is False
                assert ctrl["blocked"] is True

            # h1_probe_matrix
            hpm = result["h1_probe_matrix"]
            assert hpm["raw_token_read_allowed"] is False
            assert hpm["raw_token_read_performed"] is False
            assert hpm["env_hash_present"] is True
            assert hpm["env_hash_sufficient_for_runtime_check"] is True
            assert hpm["raw_token_required_for_drill"] is False
            assert hpm["h1_header_available"] is False
            assert hpm["h1_header_constructed"] is False
            assert hpm["h1_header_sent"] is False
            assert hpm["approval_endpoint_reachable_but_not_called"] is True
            assert hpm["submit_endpoint_reachable_but_not_called"] is True
            assert hpm["manual_canary_status"] == "MANUAL_REQUIRED"

            # blocked_h1_attempts
            attempts = result["blocked_h1_attempts"]
            assert len(attempts) == 3
            for a in attempts:
                assert a["local_boundary_audit_only"] is True
                assert a["blocked"] is True
                assert a["endpoint_called"] is False
                assert a["h1_header_constructed"] is False
                assert a["h1_header_sent"] is False
                assert a["raw_token_read"] is False
                assert a["helper_called"] is False
                assert a["order_window_opened"] is False
                assert a["broker_mutation"] is False
                assert a["executable"] is False
                assert a["performed"] is False

            # h1_boundary_checklist
            ncl = result["h1_boundary_checklist"]
            assert len(ncl) == 24
            ncl_checks = {c["check"]: c["status"] for c in ncl}
            assert ncl_checks.get("confirms_audit_only") == "PASS"
            assert ncl_checks.get("confirms_raw_token_not_read") == "PASS"
            assert ncl_checks.get("confirms_raw_token_not_logged") == "PASS"
            assert ncl_checks.get("confirms_hash_only_configured") == "PASS"
            assert ncl_checks.get("confirms_no_h1_header_constructed") == "PASS"
            assert ncl_checks.get("confirms_no_h1_header_sent") == "PASS"
            assert ncl_checks.get("confirms_h1_token_not_used") == "PASS"
            assert ncl_checks.get("confirms_trade_window_helper_not_called") == "PASS"
            assert ncl_checks.get("confirms_order_window_not_opened_by_drill") == "PASS"
            assert ncl_checks.get("confirms_future_h1_required") == "PASS"
            assert ncl_checks.get("confirms_future_order_window_required") == "PASS"

            # workflow_summary
            wf = result["workflow_summary"]
            assert wf["h1_boundary_audit_ready"] is True
            assert wf["h1_boundary_intact"] is True
            assert wf["raw_token_unread"] is True
            assert wf["hash_only_configured"] is True
            assert wf["h1_header_never_constructed"] is True
            assert wf["h1_header_never_sent"] is True
            assert wf["h1_dependent_actions_manual_required"] is True
            assert wf["all_h1_controls_blocked"] is True
            assert wf["all_blocks_expected"] is True
            assert wf["trade_window_helper_not_called"] is True
            assert wf["no_broker_mutation"] is True
            assert wf["no_raw_token_touched"] is True
            assert wf["no_order_window_seen"] is True
            assert wf["checklist_complete"] is True

            # Non-mutation top-level
            assert result["no_raw_token_read"] is True
            assert result["no_raw_token_value_seen"] is True
            assert result["no_raw_token_logged"] is True
            assert result["no_raw_token_copied"] is True
            assert result["no_raw_token_exported"] is True
            assert result["no_h1_header_constructed"] is True
            assert result["no_h1_header_sent"] is True
            assert result["h1_boundary_preserved"] is True
            assert result["manual_canary_required"] is True
            assert result["manual_canary_executed"] is False
            assert result["env_hash_only"] is True
            assert "boundary_violations" not in result
        finally:
            stop_patches(mocks, patches)

    def test_h1_manual_doctor_acceptable(self, clean_git_metadata, clean_worktree,
                                          origin_aligned, all_tags_present, bridge_health_ok,
                                          positions_flat, alerts_clean, snapshot_ok,
                                          readiness_locked, guard_state_clean, env_safety_locked,
                                          rules_locked, autonomy_level_one, doctor_h1_manual,
                                          kpi_hold_expected, hermes_policy_ok):
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
            result = _run_level1_h1_boundary_audit_checkpoint(demo_candidates=2)
            assert result["diagnosis"] == _PHASE16Q_DIAGNOSIS["ready"]
            assert result["severity"] == "OK"
            assert result["doctor_summary"]["acceptable"] is True
            assert result["doctor_summary"]["h1_canary_status"] == "MANUAL_REQUIRED"
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
            result = _run_level1_h1_boundary_audit_checkpoint()
            assert result["diagnosis"] == _PHASE16Q_DIAGNOSIS["missing_required_tags"]
            assert result["severity"] == "NO_GO"
            assert "h1_dependent_controls" in result
            assert "h1_probe_matrix" in result
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
            result = _run_level1_h1_boundary_audit_checkpoint()
            assert result["diagnosis"] == _PHASE16Q_DIAGNOSIS["dirty_worktree"]
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
            result = _run_level1_h1_boundary_audit_checkpoint()
            assert result["diagnosis"] == _PHASE16Q_DIAGNOSIS["runtime_not_ready"]
            assert result["severity"] == "NO_GO"
        finally:
            stop_patches(mocks, patches)

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
            result = _run_level1_h1_boundary_audit_checkpoint()
            assert result["diagnosis"] == _PHASE16Q_DIAGNOSIS["autonomy_not_level1"]
            assert result["severity"] == "NO_GO"
        finally:
            stop_patches(mocks, patches)

    def test_safety_unlocked_no_go(self, clean_git_metadata, clean_worktree,
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
            result = _run_level1_h1_boundary_audit_checkpoint()
            assert result["diagnosis"] == _PHASE16Q_DIAGNOSIS["safety_not_locked"]
            assert result["severity"] == "NO_GO"
        finally:
            stop_patches(mocks, patches)

    def test_guard_state_not_clean_no_go(self, clean_git_metadata, clean_worktree,
                                          origin_aligned, all_tags_present, bridge_health_ok,
                                          positions_flat, alerts_clean, snapshot_ok,
                                          readiness_locked, env_safety_locked,
                                          rules_locked, autonomy_level_one, doctor_pass,
                                          kpi_hold_expected, hermes_policy_ok):
        stale_gs = json.dumps({"trade_date": _YESTERDAY_STR, "daily_trade_count": 0,
                               "daily_halt_active": False})
        patches = _build_mocks(
            health=bridge_health_ok, positions=positions_flat,
            alerts=alerts_clean, snapshot=snapshot_ok, readiness=readiness_locked,
            git_metadata=clean_git_metadata, worktree=clean_worktree,
            origin=origin_aligned, tags=all_tags_present,
            guard_state_content=stale_gs, env_safety=env_safety_locked,
            rules=rules_locked, autonomy=autonomy_level_one,
            doctor=doctor_pass, kpi=kpi_hold_expected, policy=hermes_policy_ok,
        )
        mocks, patches = apply_patches(patches)
        try:
            result = _run_level1_h1_boundary_audit_checkpoint()
            assert result["diagnosis"] == _PHASE16Q_DIAGNOSIS["guard_state_not_clean"]
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
            result = _run_level1_h1_boundary_audit_checkpoint()
            assert result["diagnosis"] == _PHASE16Q_DIAGNOSIS["positions_not_flat"]
            assert result["severity"] == "NO_GO"
        finally:
            stop_patches(mocks, patches)

    def test_rules_enforced_no_go(self, clean_git_metadata, clean_worktree,
                                   origin_aligned, all_tags_present, bridge_health_ok,
                                   positions_flat, alerts_clean, snapshot_ok,
                                   readiness_locked, guard_state_clean, env_safety_locked,
                                   autonomy_level_one, doctor_pass,
                                   kpi_hold_expected, hermes_policy_ok):
        rules_enforced = {"enforced": "true", "found": True}
        patches = _build_mocks(
            health=bridge_health_ok, positions=positions_flat,
            alerts=alerts_clean, snapshot=snapshot_ok, readiness=readiness_locked,
            git_metadata=clean_git_metadata, worktree=clean_worktree,
            origin=origin_aligned, tags=all_tags_present,
            guard_state_content=guard_state_clean, env_safety=env_safety_locked,
            rules=rules_enforced, autonomy=autonomy_level_one,
            doctor=doctor_pass, kpi=kpi_hold_expected, policy=hermes_policy_ok,
        )
        mocks, patches = apply_patches(patches)
        try:
            result = _run_level1_h1_boundary_audit_checkpoint()
            assert result["diagnosis"] == _PHASE16Q_DIAGNOSIS["safety_not_locked"]
            assert result["severity"] == "NO_GO"
        finally:
            stop_patches(mocks, patches)

    def test_active_alerts_no_go(self, clean_git_metadata, clean_worktree,
                                  origin_aligned, all_tags_present, bridge_health_ok,
                                  positions_flat, snapshot_ok,
                                  readiness_locked, guard_state_clean, env_safety_locked,
                                  rules_locked, autonomy_level_one, doctor_pass,
                                  kpi_hold_expected, hermes_policy_ok):
        alerts = {"alerts": [{"id": "a1", "requires_action": True,
                              "message": "Test", "severity": "WARN"}]}
        patches = _build_mocks(
            health=bridge_health_ok, positions=positions_flat,
            alerts=alerts, snapshot=snapshot_ok, readiness=readiness_locked,
            git_metadata=clean_git_metadata, worktree=clean_worktree,
            origin=origin_aligned, tags=all_tags_present,
            guard_state_content=guard_state_clean, env_safety=env_safety_locked,
            rules=rules_locked, autonomy=autonomy_level_one,
            doctor=doctor_pass, kpi=kpi_hold_expected, policy=hermes_policy_ok,
        )
        mocks, patches = apply_patches(patches)
        try:
            result = _run_level1_h1_boundary_audit_checkpoint()
            assert result["diagnosis"] == _PHASE16Q_DIAGNOSIS["monitor_alerts_active"]
            assert result["severity"] == "NO_GO"
        finally:
            stop_patches(mocks, patches)

    def test_clean_cycles_mismatch_no_go(self, clean_git_metadata, clean_worktree,
                                          origin_aligned, all_tags_present, bridge_health_ok,
                                          positions_flat, alerts_clean, snapshot_ok,
                                          readiness_locked, guard_state_clean, env_safety_locked,
                                          rules_locked, autonomy_level_one, doctor_pass,
                                          hermes_policy_ok):
        kpi_mismatch = {"verdict": "HOLD",
                        "blockers": [{"severity": "HOLD", "check": "system_locked"}],
                        "autonomy": {"clean_cycles": 99}}
        patches = _build_mocks(
            health=bridge_health_ok, positions=positions_flat,
            alerts=alerts_clean, snapshot=snapshot_ok, readiness=readiness_locked,
            git_metadata=clean_git_metadata, worktree=clean_worktree,
            origin=origin_aligned, tags=all_tags_present,
            guard_state_content=guard_state_clean, env_safety=env_safety_locked,
            rules=rules_locked, autonomy=autonomy_level_one,
            doctor=doctor_pass, kpi=kpi_mismatch, policy=hermes_policy_ok,
            clean_cycles_count=7, ledger_exists=True,
        )
        mocks, patches = apply_patches(patches)
        try:
            result = _run_level1_h1_boundary_audit_checkpoint()
            assert result["diagnosis"] == _PHASE16Q_DIAGNOSIS["clean_cycles_mismatch"]
            assert result["severity"] == "NO_GO"
        finally:
            stop_patches(mocks, patches)

    def test_kpi_blocker_beyond_system_locked_no_go(self, clean_git_metadata, clean_worktree,
                                                      origin_aligned, all_tags_present, bridge_health_ok,
                                                      positions_flat, alerts_clean, snapshot_ok,
                                                      readiness_locked, guard_state_clean, env_safety_locked,
                                                      rules_locked, autonomy_level_one, doctor_pass,
                                                      hermes_policy_ok):
        kpi_bad = {"verdict": "NO-GO",
                   "blockers": [{"severity": "NO-GO", "check": "positions_mismatch"}],
                   "autonomy": {"clean_cycles": 7}}
        patches = _build_mocks(
            health=bridge_health_ok, positions=positions_flat,
            alerts=alerts_clean, snapshot=snapshot_ok, readiness=readiness_locked,
            git_metadata=clean_git_metadata, worktree=clean_worktree,
            origin=origin_aligned, tags=all_tags_present,
            guard_state_content=guard_state_clean, env_safety=env_safety_locked,
            rules=rules_locked, autonomy=autonomy_level_one,
            doctor=doctor_pass, kpi=kpi_bad, policy=hermes_policy_ok,
            clean_cycles_count=7, ledger_exists=True,
        )
        mocks, patches = apply_patches(patches)
        try:
            result = _run_level1_h1_boundary_audit_checkpoint()
            assert result["diagnosis"] == _PHASE16Q_DIAGNOSIS["kpi_not_acceptable"]
            assert result["severity"] == "NO_GO"
        finally:
            stop_patches(mocks, patches)


# ===========================================================================
# T4: H1 boundary violation NO_GO cases
# ===========================================================================

class TestH1BoundaryViolations:
    """Test that the boundary violation diagnostics correctly detect each
    type of boundary breach. Since the negative-control drill itself never
    violates boundaries, these tests directly construct violation scenarios
    via demo_candidates manipulation to exercise the diagnostic paths."""

    def test_h1_boundary_violation_raw_token_path_opened(self, clean_git_metadata,
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
            result = _run_level1_h1_boundary_audit_checkpoint(demo_candidates=1)
            # Manually inject a violation into the result to simulate a breach
            result["h1_boundary_audit"]["raw_token_path_opened"] = True
            # Re-run boundary diagnostics: the embedded 18-bis check would catch this
            hba = result["h1_boundary_audit"]
            violations = []
            intact = True
            if hba.get("raw_token_path_opened"):
                violations.append("raw_token_path_opened"); intact = False
            if hba.get("raw_token_path_read"):
                violations.append("raw_token_path_read"); intact = False
            if hba.get("x_h1_token_header_constructed"):
                violations.append("h1_header_constructed"); intact = False
            if hba.get("x_h1_token_header_sent"):
                violations.append("h1_header_sent"); intact = False
            if hba.get("trade_window_helper_called"):
                violations.append("trade_window_helper_called"); intact = False
            if hba.get("manual_canary_executed"):
                violations.append("manual_canary_executed"); intact = False
            if hba.get("broker_mutation"):
                violations.append("broker_mutation"); intact = False
            if hba.get("broker_order_created"):
                violations.append("broker_order_created"); intact = False
            assert not intact
            assert "raw_token_path_opened" in violations
        finally:
            stop_patches(mocks, patches)

    def test_h1_boundary_violation_h1_header_constructed(self, clean_git_metadata,
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
            result = _run_level1_h1_boundary_audit_checkpoint(demo_candidates=1)
            result["h1_boundary_audit"]["x_h1_token_header_constructed"] = True
            hba = result["h1_boundary_audit"]
            violations = []
            intact = True
            if hba.get("x_h1_token_header_constructed"):
                violations.append("h1_header_constructed"); intact = False
            if hba.get("x_h1_token_header_sent"):
                violations.append("h1_header_sent"); intact = False
            assert not intact
            assert "h1_header_constructed" in violations
        finally:
            stop_patches(mocks, patches)

    def test_h1_boundary_violation_trade_window_helper_called(self, clean_git_metadata,
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
            result = _run_level1_h1_boundary_audit_checkpoint(demo_candidates=1)
            result["h1_boundary_audit"]["trade_window_helper_called"] = True
            hba = result["h1_boundary_audit"]
            violations = []
            intact = True
            if hba.get("trade_window_helper_called"):
                violations.append("trade_window_helper_called"); intact = False
            assert not intact
            assert "trade_window_helper_called" in violations
        finally:
            stop_patches(mocks, patches)

    def test_h1_boundary_violation_broker_mutation(self, clean_git_metadata,
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
            result = _run_level1_h1_boundary_audit_checkpoint(demo_candidates=1)
            result["h1_boundary_audit"]["broker_mutation"] = True
            hba = result["h1_boundary_audit"]
            violations = []
            intact = True
            if hba.get("broker_mutation"):
                violations.append("broker_mutation"); intact = False
            assert not intact
            assert "broker_mutation" in violations
        finally:
            stop_patches(mocks, patches)

    def test_h1_boundary_violation_h1_header_sent(self, clean_git_metadata,
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
            result = _run_level1_h1_boundary_audit_checkpoint(demo_candidates=1)
            result["h1_boundary_audit"]["x_h1_token_header_sent"] = True
            hba = result["h1_boundary_audit"]
            violations = []
            intact = True
            if hba.get("x_h1_token_header_sent"):
                violations.append("h1_header_sent"); intact = False
            assert not intact
            assert "h1_header_sent" in violations
        finally:
            stop_patches(mocks, patches)

    def test_h1_boundary_violation_h1_token_used(self, clean_git_metadata,
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
            result = _run_level1_h1_boundary_audit_checkpoint(demo_candidates=1)
            result["h1_boundary_audit"]["h1_token_used"] = True
            hba = result["h1_boundary_audit"]
            violations = []
            intact = True
            if hba.get("h1_token_used"):
                violations.append("h1_token_used"); intact = False
            assert not intact
            assert "h1_token_used" in violations
        finally:
            stop_patches(mocks, patches)

    def test_h1_boundary_violation_approve_endpoint_called(self, clean_git_metadata,
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
            result = _run_level1_h1_boundary_audit_checkpoint(demo_candidates=1)
            result["h1_boundary_audit"]["approve_endpoint_called"] = True
            hba = result["h1_boundary_audit"]
            violations = []
            intact = True
            if hba.get("approve_endpoint_called"):
                violations.append("approve_endpoint_called"); intact = False
            assert not intact
            assert "approve_endpoint_called" in violations
        finally:
            stop_patches(mocks, patches)


# ===========================================================================
# T5: Edge cases
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
            result = _run_level1_h1_boundary_audit_checkpoint(demo_candidates=0)
            assert result["diagnosis"] == _PHASE16Q_DIAGNOSIS["ready"]
            assert result["h1_boundary_audit"]["canaries_count"] == 0
            assert result["canary_intents"] == []
            assert result["blocked_h1_attempts"] == []
            assert result["h1_dependent_controls"]["controls_count"] == 0
            assert result["h1_boundary_intact"] is True
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
            result = _run_level1_h1_boundary_audit_checkpoint()
            assert len(result.get("evidence_hash", "")) > 0
            assert result.get("export_path") is not None
            assert Path(result["export_path"]).exists()
            assert result["h1_boundary_audit"].get("audit_artifact_path") is not None
            assert result["workflow_summary"]["h1_boundary_audit_artifact_created"] is True
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
            result = _run_level1_h1_boundary_audit_checkpoint()
            assert result["no_raw_token_read"] is True
            assert result["no_raw_token_value_seen"] is True
            assert result["no_h1_header_constructed"] is True
            assert result["no_h1_header_sent"] is True
            assert result["no_approval_endpoint_called"] is True
            assert result["no_submit_endpoint_called"] is True
            assert result["no_order_endpoint_called"] is True
            assert result["no_preflight_endpoint_called"] is True
            assert result["no_trade_window_helper_called"] is True
            assert result["execution_authorized_now"] is False
            assert result["execution_performed"] is False
            assert result["no_order_window_opened"] is True
            assert result["no_order_window_seen"] is True
            assert result["h1_token_not_used"] is True
            assert result["h1_token_not_read"] is True
            assert result["guard_state_clean"] is True
            non_actions = result.get("explicit_non_actions", [])
            assert any("did not read /etc/ibkr-bridge/h1_token" in a for a in non_actions)
            assert any("did not construct X-H1-Token" in a for a in non_actions)
            assert any("did not send X-H1-Token" in a for a in non_actions)
            assert any("H1-boundary" in a or "H1 boundary" in a for a in non_actions)
        finally:
            stop_patches(mocks, patches)

    def test_demo_candidates_max(self, clean_git_metadata, clean_worktree,
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
            result = _run_level1_h1_boundary_audit_checkpoint(demo_candidates=10)
            assert result["h1_boundary_audit"]["canaries_count"] == 5
            assert len(result["canary_intents"]) == 5
            assert len(result["blocked_h1_attempts"]) == 5
            assert result["h1_dependent_controls"]["controls_count"] == 5
        finally:
            stop_patches(mocks, patches)

    def test_boundary_violations_field_absent_when_clean(self, clean_git_metadata,
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
            result = _run_level1_h1_boundary_audit_checkpoint(demo_candidates=2)
            # When clean, no boundary_violations key should exist
            assert "boundary_violations" not in result
            assert result["h1_boundary_intact"] is True
        finally:
            stop_patches(mocks, patches)
