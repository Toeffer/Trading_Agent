"""Tests for Phase 16T — Level 1 Restart-Persistence Safety Checkpoint.

Covers:
  - command registration + 3 aliases
  - clean runtime OK with full field verification
  - prerequisite NO_GO cases (tags, worktree, 16S pre-restart broken)
  - post-restart failure NO_GO cases
  - edge cases (export, evidence hash, non-mutation verification)
"""

import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from datetime import datetime, timezone, timedelta
_TODAY_STR = datetime.now(timezone.utc).strftime("%Y-%m-%d")


BRIDGE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BRIDGE_DIR))

from ibkr_operator import (
    _run_level1_restart_persistence_safety_checkpoint,
    _PHASE16T_DIAGNOSIS,
    _PHASE16T_REQUIRED_TAGS,
    _PHASE16T_EXPORT_DIR,
    _PHASE16T_EXPLICIT_NON_ACTIONS,
    _PHASE16T_BRIDGE_SERVICE,
    _restart_bridge_service,
    _poll_bridge_health,
    _snapshot_bridge_state,
)


# ===========================================================================
# Fixtures
# ===========================================================================

@pytest.fixture
def clean_git_metadata():
    return {"branch": "master", "commit_short": "abc1234",
            "commit": "abc1234abc1234abc1234abc1234abc1234abc",
            "tag": "phase16s_level1_end_to_end_safety_invariant_checkpoint"}

@pytest.fixture
def clean_worktree():
    return {"clean": True, "dirty_files": []}

@pytest.fixture
def all_tags_present():
    return {"present_count": len(_PHASE16T_REQUIRED_TAGS),
            "present": list(_PHASE16T_REQUIRED_TAGS)}

@pytest.fixture
def one_tag_missing():
    missing = [_PHASE16T_REQUIRED_TAGS[0]]
    present = []
    return {"present_count": len(present), "present": present}

@pytest.fixture
def before_bridge_ok():
    return {"connected": True, "mode": "paper", "read_only": True,
            "allow_orders": False, "endpoints_ok": True,
            "endpoints_ok_count": 8, "endpoints_total_count": 8,
            "positions_count": 0, "positions_flat": True,
            "system_locked": True}

@pytest.fixture
def after_bridge_ok():
    return {"connected": True, "mode": "paper", "read_only": True,
            "allow_orders": False, "endpoints_ok": True,
            "endpoints_ok_count": 8, "endpoints_total_count": 8,
            "positions_count": 0, "positions_flat": True,
            "system_locked": True}

@pytest.fixture
def sixteen_s_ok_result():
    from ibkr_operator import _PHASE16S_DIAGNOSIS
    return {
        "diagnosis": _PHASE16S_DIAGNOSIS["ready"],
        "severity": "OK",
        "end_to_end_safety_invariant": {"status": "invariant_intact"},
    }

@pytest.fixture
def sixteen_s_broken_result():
    from ibkr_operator import _PHASE16S_DIAGNOSIS
    return {
        "diagnosis": _PHASE16S_DIAGNOSIS["runtime_not_ready"],
        "severity": "NO_GO",
        "end_to_end_safety_invariant": {"status": "invariant_broken"},
    }

@pytest.fixture
def guard_state_clean_str():
    return json.dumps({"trade_date": _TODAY_STR, "daily_trade_count": 0, "daily_halt_active": False})

@pytest.fixture
def kpi_hold_expected():
    return {"verdict": "HOLD",
            "blockers": [{"severity": "HOLD", "check": "system_locked"}],
            "autonomy": {"clean_cycles": 7}}

@pytest.fixture
def doctor_pass():
    return {"pass": True, "passed": 14, "total": 15, "passed_count": 14, "check_count": 15}

@pytest.fixture
def hermes_policy_ok():
    return {"hermes_policy_exists": True, "execution_path_ok": True, "advisory_boundary_ok": True}

@pytest.fixture
def env_safety_locked():
    return {"IBKR_ALLOW_ORDERS": "false", "found": True}

@pytest.fixture
def rules_locked():
    return {"enforced": "false", "found": True}

@pytest.fixture
def autonomy_level_one():
    return "1"


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


def _build_mocks(before_health=None, after_health=None,
                 before_positions=None, after_positions=None,
                 before_snapshot=None, after_snapshot=None,
                 before_readiness=None, after_readiness=None,
                 git_metadata=None, worktree=None, tags=None,
                 sixteen_s_before_result=None, sixteen_s_after_result=None,
                 guard_state_content=None, restart_ok=True, restart_msg="ok",
                 env_safety=None, rules=None, autonomy=None,
                 doctor=None, kpi=None, policy=None,
                 clean_cycles_count=7, bridge_url="http://localhost:5000/v1/api"):
    """Build mock patches for Phase 16T checkpoint.

    The bridge mock is called multiple times (before + after restart),
    so we use side_effect with a sequence.
    """
    patches = []

    # Build a sequence of urllib.urlopen calls
    # Order: before health, before snapshot, before positions, before readiness,
    #        (restart happens here)
    #        after health x N (polling), after health, after snapshot, after positions, after readiness
    call_index = [0]

    def _mock_urlopen(req, timeout=None):
        url = req.full_url if hasattr(req, 'full_url') else str(req)
        idx = call_index[0]
        call_index[0] += 1

        if "/positions" in url:
            if idx < 4:
                body = before_positions if before_positions else {"positions": []}
                status = 200
            else:
                body = after_positions if after_positions else {"positions": []}
                status = 200
            return _MockResponse(status, json.dumps(body).encode())

        if "/snapshot" in url:
            if idx < 4:
                body = before_snapshot if before_snapshot else {"ok": True, "endpoints": 8}
                status = 200
            else:
                body = after_snapshot if after_snapshot else {"ok": True, "endpoints": 8}
                status = 200
            return _MockResponse(status, json.dumps(body).encode())

        if "/readiness" in url:
            if idx < 4:
                body = before_readiness if before_readiness else {"summary": {"kill_switches": {"system_locked": True}, "allow_orders": False}}
                status = 200
            else:
                body = after_readiness if after_readiness else {"summary": {"kill_switches": {"system_locked": True}, "allow_orders": False}}
                status = 200
            return _MockResponse(status, json.dumps(body).encode())

        if "/health" in url:
            if idx < 4:
                body = before_health if before_health else {"connected": True, "mode": "paper", "read_only": True}
                status = 200
            else:
                body = after_health if after_health else {"connected": True, "mode": "paper", "read_only": True}
                status = 200
            return _MockResponse(status, json.dumps(body).encode())

        return _MockResponse(404, b'{}')

    patches.append(patch("urllib.request.urlopen", side_effect=_mock_urlopen))

    if git_metadata:
        patches.append(patch("ibkr_operator._git_metadata", return_value=git_metadata))

    # Worktree
    if worktree is not None:
        patches.append(patch("ibkr_operator._get_worktree_state", return_value=worktree))
    else:
        patches.append(patch("ibkr_operator._get_worktree_state", return_value={"clean": True, "dirty_files": []}))

    # Subprocess: git tag
    def _mock_subprocess(args, **kwargs):
        result = MagicMock()
        result.returncode = 0
        cmd = " ".join(args) if isinstance(args, list) else str(args)
        if "tag" in cmd and "restart" not in cmd:
            if tags:
                result.stdout = "\n".join(tags.get("present", []))
            else:
                result.stdout = "\n".join(list(_PHASE16T_REQUIRED_TAGS))
        elif "systemctl" in cmd and "restart" in cmd:
            if restart_ok:
                result.returncode = 0
                result.stdout = restart_msg
                result.stderr = ""
            else:
                result.returncode = 1
                result.stdout = ""
                result.stderr = restart_msg
        else:
            result.stdout = ""
        result.stderr = result.stderr or ""
        return result
    patches.append(patch("subprocess.run", side_effect=_mock_subprocess))

    # Restart bridge service — now returns (ok, msg, timed_out)
    patches.append(patch("ibkr_operator._restart_bridge_service",
                         return_value=(restart_ok, restart_msg, False)))

    # Poll bridge health — return connected=True immediately
    def _mock_poll(url, timeout_secs=180, poll_interval=2.0):
        if after_health is None:
            return True, {"connected": True, "mode": "paper", "read_only": True}
        return after_health.get("connected", False), after_health or {}
    patches.append(patch("ibkr_operator._poll_bridge_health", side_effect=_mock_poll))

    # 16S checkpoint — return before/after results
    from ibkr_operator import _PHASE16S_DIAGNOSIS
    _DEFAULT_16S_OK = {
        "diagnosis": _PHASE16S_DIAGNOSIS["ready"],
        "severity": "OK",
        "end_to_end_safety_invariant": {"status": "invariant_intact"},
    }
    s16s_call_count = [0]
    def _mock_s16s(audit_source="synthetic_readonly_demo"):
        s16s_call_count[0] += 1
        if s16s_call_count[0] == 1:
            return sixteen_s_before_result or _DEFAULT_16S_OK
        else:
            return sixteen_s_after_result or _DEFAULT_16S_OK
    patches.append(patch("ibkr_operator._run_level1_end_to_end_safety_invariant_checkpoint",
                         side_effect=_mock_s16s))

    # Guard state
    tmp_openclaw = Path(tempfile.mkdtemp())
    if guard_state_content is not None:
        (tmp_openclaw / "guard-state.json").write_text(guard_state_content)
    else:
        (tmp_openclaw / "guard-state.json").write_text(
            json.dumps({"trade_date": _TODAY_STR, "daily_trade_count": 0, "daily_halt_active": False}))
    patches.append(patch("ibkr_operator.OPENCLAW_DIR", tmp_openclaw))

    # Clean cycles ledger
    cc_dir = tmp_openclaw / "autonomy-cycles"
    cc_dir.mkdir(parents=True, exist_ok=True)
    ledger_path = cc_dir / "clean-cycle-ledger.jsonl"
    lines = []
    for i in range(clean_cycles_count):
        lines.append(json.dumps({"timestamp": f"2026-06-{25-i}T12:00:00Z",
                                 "clean": True, "evidence_hash": f"hash{i}"}))
    ledger_path.write_text("\n".join(lines) + "\n")

    # Export dir
    tmp_export = Path(tempfile.mkdtemp())
    patches.append(patch("ibkr_operator._PHASE16T_EXPORT_DIR", tmp_export))

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
                           "level1-restart-persistence-safety-checkpoint", "--help"],
                          capture_output=True, text=True, timeout=10)
        assert r.returncode == 0

    def test_alias_phase16t_works(self):
        import subprocess
        r = subprocess.run([sys.executable, str(BRIDGE_DIR / "ibkr_operator.py"),
                           "phase16t-restart-persistence-safety-checkpoint", "--help"],
                          capture_output=True, text=True, timeout=10)
        assert r.returncode == 0

    def test_alias_level1_restart_safety_works(self):
        import subprocess
        r = subprocess.run([sys.executable, str(BRIDGE_DIR / "ibkr_operator.py"),
                           "level1-restart-safety-checkpoint", "--help"],
                          capture_output=True, text=True, timeout=10)
        assert r.returncode == 0

    def test_alias_restart_persistence_safety_works(self):
        import subprocess
        r = subprocess.run([sys.executable, str(BRIDGE_DIR / "ibkr_operator.py"),
                           "restart-persistence-safety-checkpoint", "--help"],
                          capture_output=True, text=True, timeout=10)
        assert r.returncode == 0


# ===========================================================================
# T2: Clean runtime => OK
# ===========================================================================

class TestCleanRuntime:
    def test_clean_runtime_ok(self, clean_git_metadata, clean_worktree,
                               all_tags_present, before_bridge_ok, after_bridge_ok,
                               sixteen_s_ok_result, guard_state_clean_str,
                               env_safety_locked, rules_locked, autonomy_level_one,
                               doctor_pass, kpi_hold_expected, hermes_policy_ok):
        patches = _build_mocks(
            before_health=before_bridge_ok, after_health=after_bridge_ok,
            before_snapshot={"ok": True, "endpoints_ok": 8, "endpoints_total": 8},
            after_snapshot={"ok": True, "endpoints_ok": 8, "endpoints_total": 8},
            before_readiness={"summary": {"kill_switches": {"system_locked": True}, "allow_orders": False}},
            after_readiness={"summary": {"kill_switches": {"system_locked": True}, "allow_orders": False}},
            before_positions={"positions": []},
            after_positions={"positions": []},
            git_metadata=clean_git_metadata,
            worktree=clean_worktree,
            tags=all_tags_present,
            sixteen_s_before_result=sixteen_s_ok_result,
            sixteen_s_after_result=sixteen_s_ok_result,
            guard_state_content=guard_state_clean_str,
            env_safety=env_safety_locked,
            rules=rules_locked,
            autonomy=autonomy_level_one,
            doctor=doctor_pass,
            kpi=kpi_hold_expected,
            policy=hermes_policy_ok,
            clean_cycles_count=7,
            restart_ok=True, restart_msg="restarted ok",
        )
        mocks, patches = apply_patches(patches)
        try:
            result = _run_level1_restart_persistence_safety_checkpoint()
            assert result["diagnosis"] == _PHASE16T_DIAGNOSIS["ready"]
            assert result["severity"] == "OK"
            assert result["current_level"] == 1

            # Core flags
            assert result["restart_attempted"] is True
            assert result["restart_performed"] is True
            assert result["restart_command_timed_out"] is False
            assert result["restart_target"] == _PHASE16T_BRIDGE_SERVICE

            # After state
            after = result["after"]
            assert after["connected"] is True
            assert after["mode"] == "paper"
            assert after["read_only"] is True
            assert after["allow_orders"] is False
            assert after["endpoints_ok"] is True
            assert after["positions_flat"] is True
            assert after["system_locked"] is True

            # Guard state
            assert result["guard_state_clean"] is True

            # 16S invariants
            assert result["sixteen_s_invariant_ok"] is True
            assert result["sixteen_s_before_summary"]["diagnosis"] == sixteen_s_ok_result["diagnosis"]
            assert result["sixteen_s_after_summary"]["diagnosis"] == sixteen_s_ok_result["diagnosis"]

            # Restart persistence audit
            audit = result["restart_persistence_audit"]
            assert audit["invariant_survived"] is True
            assert audit["restart_attempted"] is True
            assert audit["restart_performed"] is True
            assert audit["restart_command_timed_out"] is False
            assert audit["restart_target"] == _PHASE16T_BRIDGE_SERVICE
            assert audit["bridge_survived"] is True
            assert audit["mode_survived"] is True
            assert audit["read_only_survived"] is True
            assert audit["allow_orders_survived"] is True
            assert audit["endpoints_survived"] is True
            assert audit["positions_survived"] is True
            assert audit["guard_state_survived"] is True
            assert audit["safety_invariant_survived"] is True

            # Non-mutation guarantees
            assert result["no_broker_mutation"] is True
            assert result["no_order_endpoint_called"] is True
            assert result["no_preflight_endpoint_called"] is True
            assert result["no_approval_endpoint_called"] is True
            assert result["no_submit_endpoint_called"] is True
            assert result["no_mutation_endpoint_called"] is True
            assert result["h1_token_not_used"] is True
            assert result["no_h1_token_used"] is True
            assert result["no_order_window_opened"] is True
            assert result["execution_authorized_now"] is False
            assert result["order_enablement_allowed_now"] is False
            assert result["execution_performed"] is False

            # Evidence hash
            assert len(result.get("evidence_hash", "")) > 0

            # Export
            assert result.get("export_path") is not None
            assert Path(result["export_path"]).exists()
        finally:
            stop_patches(mocks, patches)


# ===========================================================================
# T3: Prerequisite NO_GO cases
# ===========================================================================

class TestPrerequisiteFailures:
    def test_missing_tag_no_go(self, clean_git_metadata, clean_worktree,
                                one_tag_missing, before_bridge_ok,
                                sixteen_s_ok_result, guard_state_clean_str,
                                env_safety_locked, rules_locked, autonomy_level_one,
                                doctor_pass, kpi_hold_expected, hermes_policy_ok):
        patches = _build_mocks(
            before_health=before_bridge_ok,
            git_metadata=clean_git_metadata,
            worktree=clean_worktree,
            tags=one_tag_missing,
            sixteen_s_before_result=sixteen_s_ok_result,
            guard_state_content=guard_state_clean_str,
            env_safety=env_safety_locked,
            rules=rules_locked,
            autonomy=autonomy_level_one,
            doctor=doctor_pass,
            kpi=kpi_hold_expected,
            policy=hermes_policy_ok,
            restart_ok=True,
        )
        mocks, patches = apply_patches(patches)
        try:
            result = _run_level1_restart_persistence_safety_checkpoint()
            assert result["diagnosis"] == _PHASE16T_DIAGNOSIS["missing_required_tags"]
            assert result["severity"] == "NO_GO"
            # Should NOT have restarted
            assert result["restart_attempted"] is False
            assert result["restart_performed"] is False
        finally:
            stop_patches(mocks, patches)

    def test_dirty_worktree_no_go(self, clean_git_metadata,
                                   all_tags_present, before_bridge_ok,
                                   sixteen_s_ok_result, guard_state_clean_str,
                                   env_safety_locked, rules_locked, autonomy_level_one,
                                   doctor_pass, kpi_hold_expected, hermes_policy_ok):
        dirty_wt = {"clean": False, "dirty_files": ["bridge.py"]}
        patches = _build_mocks(
            before_health=before_bridge_ok,
            git_metadata=clean_git_metadata,
            worktree=dirty_wt,
            tags=all_tags_present,
            sixteen_s_before_result=sixteen_s_ok_result,
            guard_state_content=guard_state_clean_str,
            env_safety=env_safety_locked,
            rules=rules_locked,
            autonomy=autonomy_level_one,
            doctor=doctor_pass,
            kpi=kpi_hold_expected,
            policy=hermes_policy_ok,
            restart_ok=True,
        )
        mocks, patches = apply_patches(patches)
        try:
            result = _run_level1_restart_persistence_safety_checkpoint()
            assert result["diagnosis"] == _PHASE16T_DIAGNOSIS["dirty_worktree"]
            assert result["severity"] == "NO_GO"
            assert result["restart_attempted"] is False
            assert result["restart_performed"] is False
        finally:
            stop_patches(mocks, patches)

    def test_sixteen_s_broken_before_no_go(self, clean_git_metadata, clean_worktree,
                                            all_tags_present, before_bridge_ok,
                                            sixteen_s_broken_result, guard_state_clean_str,
                                            env_safety_locked, rules_locked, autonomy_level_one,
                                            doctor_pass, kpi_hold_expected, hermes_policy_ok):
        patches = _build_mocks(
            before_health=before_bridge_ok,
            git_metadata=clean_git_metadata,
            worktree=clean_worktree,
            tags=all_tags_present,
            sixteen_s_before_result=sixteen_s_broken_result,
            guard_state_content=guard_state_clean_str,
            env_safety=env_safety_locked,
            rules=rules_locked,
            autonomy=autonomy_level_one,
            doctor=doctor_pass,
            kpi=kpi_hold_expected,
            policy=hermes_policy_ok,
            restart_ok=True,
        )
        mocks, patches = apply_patches(patches)
        try:
            result = _run_level1_restart_persistence_safety_checkpoint()
            assert result["diagnosis"] == _PHASE16T_DIAGNOSIS["sixteen_s_invariant_not_ok"]
            assert result["severity"] == "NO_GO"
            assert result["restart_attempted"] is False
            assert result["restart_performed"] is False
        finally:
            stop_patches(mocks, patches)


# ===========================================================================
# T4: Post-restart NO_GO cases
# ===========================================================================

class TestPostRestartFailures:
    def test_restart_fails_no_go(self, clean_git_metadata, clean_worktree,
                                  all_tags_present, before_bridge_ok,
                                  sixteen_s_ok_result, guard_state_clean_str,
                                  env_safety_locked, rules_locked, autonomy_level_one,
                                  doctor_pass, kpi_hold_expected, hermes_policy_ok):
        patches = _build_mocks(
            before_health=before_bridge_ok,
            git_metadata=clean_git_metadata,
            worktree=clean_worktree,
            tags=all_tags_present,
            sixteen_s_before_result=sixteen_s_ok_result,
            guard_state_content=guard_state_clean_str,
            env_safety=env_safety_locked,
            rules=rules_locked,
            autonomy=autonomy_level_one,
            doctor=doctor_pass,
            kpi=kpi_hold_expected,
            policy=hermes_policy_ok,
            restart_ok=False, restart_msg="Permission denied",
        )
        mocks, patches = apply_patches(patches)
        try:
            result = _run_level1_restart_persistence_safety_checkpoint()
            assert result["diagnosis"] == _PHASE16T_DIAGNOSIS["restart_failed"]
            assert result["severity"] == "NO_GO"
            assert result["restart_attempted"] is True
            assert result["restart_command_timed_out"] is False
        finally:
            stop_patches(mocks, patches)

    def test_bridge_not_reachable_after_restart_no_go(self, clean_git_metadata, clean_worktree,
                                                       all_tags_present, before_bridge_ok,
                                                       sixteen_s_ok_result, guard_state_clean_str,
                                                       env_safety_locked, rules_locked, autonomy_level_one,
                                                       doctor_pass, kpi_hold_expected, hermes_policy_ok):
        # After bridge is not connected
        after_health = {"connected": False, "mode": "live", "read_only": False}
        patches = _build_mocks(
            before_health=before_bridge_ok,
            after_health=after_health,
            git_metadata=clean_git_metadata,
            worktree=clean_worktree,
            tags=all_tags_present,
            sixteen_s_before_result=sixteen_s_ok_result,
            guard_state_content=guard_state_clean_str,
            env_safety=env_safety_locked,
            rules=rules_locked,
            autonomy=autonomy_level_one,
            doctor=doctor_pass,
            kpi=kpi_hold_expected,
            policy=hermes_policy_ok,
            restart_ok=True, restart_msg="restarted ok",
        )
        mocks, patches = apply_patches(patches)
        try:
            result = _run_level1_restart_persistence_safety_checkpoint()
            assert result["diagnosis"] == _PHASE16T_DIAGNOSIS["bridge_not_reachable_after_restart"]
            assert result["severity"] == "NO_GO"
            assert result["restart_attempted"] is True
            assert result["restart_performed"] is False
        finally:
            stop_patches(mocks, patches)

    def test_after_mode_not_paper_no_go(self, clean_git_metadata, clean_worktree,
                                         all_tags_present, before_bridge_ok,
                                         sixteen_s_ok_result, guard_state_clean_str,
                                         env_safety_locked, rules_locked, autonomy_level_one,
                                         doctor_pass, kpi_hold_expected, hermes_policy_ok):
        after_health = {"connected": True, "mode": "live", "read_only": True}
        patches = _build_mocks(
            before_health=before_bridge_ok,
            after_health=after_health,
            after_snapshot={"ok": True, "endpoints_ok": 8, "endpoints_total": 8},
            after_readiness={"summary": {"kill_switches": {"system_locked": True}, "allow_orders": False}},
            after_positions={"positions": []},
            git_metadata=clean_git_metadata,
            worktree=clean_worktree,
            tags=all_tags_present,
            sixteen_s_before_result=sixteen_s_ok_result,
            guard_state_content=guard_state_clean_str,
            env_safety=env_safety_locked,
            rules=rules_locked,
            autonomy=autonomy_level_one,
            doctor=doctor_pass,
            kpi=kpi_hold_expected,
            policy=hermes_policy_ok,
            restart_ok=True, restart_msg="restarted ok",
        )
        mocks, patches = apply_patches(patches)
        try:
            result = _run_level1_restart_persistence_safety_checkpoint()
            assert result["diagnosis"] == _PHASE16T_DIAGNOSIS["after_mode_not_paper"]
            assert result["severity"] == "NO_GO"
        finally:
            stop_patches(mocks, patches)

    def test_after_read_only_not_true_no_go(self, clean_git_metadata, clean_worktree,
                                             all_tags_present, before_bridge_ok,
                                             sixteen_s_ok_result, guard_state_clean_str,
                                             env_safety_locked, rules_locked, autonomy_level_one,
                                             doctor_pass, kpi_hold_expected, hermes_policy_ok):
        after_health = {"connected": True, "mode": "paper", "read_only": False}
        patches = _build_mocks(
            before_health=before_bridge_ok,
            after_health=after_health,
            after_snapshot={"ok": True, "endpoints_ok": 8, "endpoints_total": 8},
            after_readiness={"summary": {"kill_switches": {"system_locked": True}, "allow_orders": False}},
            after_positions={"positions": []},
            git_metadata=clean_git_metadata,
            worktree=clean_worktree,
            tags=all_tags_present,
            sixteen_s_before_result=sixteen_s_ok_result,
            guard_state_content=guard_state_clean_str,
            env_safety=env_safety_locked,
            rules=rules_locked,
            autonomy=autonomy_level_one,
            doctor=doctor_pass,
            kpi=kpi_hold_expected,
            policy=hermes_policy_ok,
            restart_ok=True, restart_msg="restarted ok",
        )
        mocks, patches = apply_patches(patches)
        try:
            result = _run_level1_restart_persistence_safety_checkpoint()
            assert result["diagnosis"] == _PHASE16T_DIAGNOSIS["after_read_only_not_true"]
            assert result["severity"] == "NO_GO"
        finally:
            stop_patches(mocks, patches)

    def test_after_allow_orders_true_no_go(self, clean_git_metadata, clean_worktree,
                                            all_tags_present, before_bridge_ok,
                                            sixteen_s_ok_result, guard_state_clean_str,
                                            env_safety_locked, rules_locked, autonomy_level_one,
                                            doctor_pass, kpi_hold_expected, hermes_policy_ok):
        after_health = {"connected": True, "mode": "paper", "read_only": True}
        patches = _build_mocks(
            before_health=before_bridge_ok,
            after_health=after_health,
            after_snapshot={"ok": True, "endpoints_ok": 8, "endpoints_total": 8},
            after_readiness={"summary": {"kill_switches": {"system_locked": True}, "allow_orders": True}},
            after_positions={"positions": []},
            git_metadata=clean_git_metadata,
            worktree=clean_worktree,
            tags=all_tags_present,
            sixteen_s_before_result=sixteen_s_ok_result,
            guard_state_content=guard_state_clean_str,
            env_safety=env_safety_locked,
            rules=rules_locked,
            autonomy=autonomy_level_one,
            doctor=doctor_pass,
            kpi=kpi_hold_expected,
            policy=hermes_policy_ok,
            restart_ok=True, restart_msg="restarted ok",
        )
        mocks, patches = apply_patches(patches)
        try:
            result = _run_level1_restart_persistence_safety_checkpoint()
            assert result["diagnosis"] == _PHASE16T_DIAGNOSIS["after_allow_orders_not_false"]
            assert result["severity"] == "NO_GO"
        finally:
            stop_patches(mocks, patches)

    def test_after_endpoints_not_ok_no_go(self, clean_git_metadata, clean_worktree,
                                           all_tags_present, before_bridge_ok,
                                           sixteen_s_ok_result, guard_state_clean_str,
                                           env_safety_locked, rules_locked, autonomy_level_one,
                                           doctor_pass, kpi_hold_expected, hermes_policy_ok):
        after_health = {"connected": True, "mode": "paper", "read_only": True}
        patches = _build_mocks(
            before_health=before_bridge_ok,
            after_health=after_health,
            after_snapshot={"ok": False, "endpoints_ok": 6, "endpoints_total": 8},
            after_readiness={"summary": {"kill_switches": {"system_locked": True}, "allow_orders": False}},
            after_positions={"positions": []},
            git_metadata=clean_git_metadata,
            worktree=clean_worktree,
            tags=all_tags_present,
            sixteen_s_before_result=sixteen_s_ok_result,
            guard_state_content=guard_state_clean_str,
            env_safety=env_safety_locked,
            rules=rules_locked,
            autonomy=autonomy_level_one,
            doctor=doctor_pass,
            kpi=kpi_hold_expected,
            policy=hermes_policy_ok,
            restart_ok=True, restart_msg="restarted ok",
        )
        mocks, patches = apply_patches(patches)
        try:
            result = _run_level1_restart_persistence_safety_checkpoint()
            assert result["diagnosis"] == _PHASE16T_DIAGNOSIS["after_endpoints_not_ok"]
            assert result["severity"] == "NO_GO"
        finally:
            stop_patches(mocks, patches)

    def test_after_16s_broken_no_go(self, clean_git_metadata, clean_worktree,
                                     all_tags_present, before_bridge_ok,
                                     sixteen_s_ok_result, sixteen_s_broken_result,
                                     guard_state_clean_str,
                                     env_safety_locked, rules_locked, autonomy_level_one,
                                     doctor_pass, kpi_hold_expected, hermes_policy_ok):
        after_health = {"connected": True, "mode": "paper", "read_only": True}
        patches = _build_mocks(
            before_health=before_bridge_ok,
            after_health=after_health,
            after_snapshot={"ok": True, "endpoints_ok": 8, "endpoints_total": 8},
            after_readiness={"summary": {"kill_switches": {"system_locked": True}, "allow_orders": False}},
            after_positions={"positions": []},
            git_metadata=clean_git_metadata,
            worktree=clean_worktree,
            tags=all_tags_present,
            sixteen_s_before_result=sixteen_s_ok_result,
            sixteen_s_after_result=sixteen_s_broken_result,
            guard_state_content=guard_state_clean_str,
            env_safety=env_safety_locked,
            rules=rules_locked,
            autonomy=autonomy_level_one,
            doctor=doctor_pass,
            kpi=kpi_hold_expected,
            policy=hermes_policy_ok,
            restart_ok=True, restart_msg="restarted ok",
        )
        mocks, patches = apply_patches(patches)
        try:
            result = _run_level1_restart_persistence_safety_checkpoint()
            assert result["diagnosis"] == _PHASE16T_DIAGNOSIS["sixteen_s_invariant_not_ok"]
            assert result["severity"] == "NO_GO"
            assert result["sixteen_s_invariant_ok"] is False
        finally:
            stop_patches(mocks, patches)


# ===========================================================================
# T5: Edge cases
# ===========================================================================

class TestEdgeCases:
    def test_export_and_evidence(self, clean_git_metadata, clean_worktree,
                                  all_tags_present, before_bridge_ok, after_bridge_ok,
                                  sixteen_s_ok_result, guard_state_clean_str,
                                  env_safety_locked, rules_locked, autonomy_level_one,
                                  doctor_pass, kpi_hold_expected, hermes_policy_ok):
        patches = _build_mocks(
            before_health=before_bridge_ok, after_health=after_bridge_ok,
            before_snapshot={"ok": True, "endpoints_ok": 8, "endpoints_total": 8},
            after_snapshot={"ok": True, "endpoints_ok": 8, "endpoints_total": 8},
            before_readiness={"summary": {"kill_switches": {"system_locked": True}, "allow_orders": False}},
            after_readiness={"summary": {"kill_switches": {"system_locked": True}, "allow_orders": False}},
            before_positions={"positions": []},
            after_positions={"positions": []},
            git_metadata=clean_git_metadata,
            worktree=clean_worktree,
            tags=all_tags_present,
            sixteen_s_before_result=sixteen_s_ok_result,
            sixteen_s_after_result=sixteen_s_ok_result,
            guard_state_content=guard_state_clean_str,
            env_safety=env_safety_locked,
            rules=rules_locked,
            autonomy=autonomy_level_one,
            doctor=doctor_pass,
            kpi=kpi_hold_expected,
            policy=hermes_policy_ok,
            clean_cycles_count=7,
            restart_ok=True, restart_msg="restarted ok",
        )
        mocks, patches = apply_patches(patches)
        try:
            result = _run_level1_restart_persistence_safety_checkpoint()
            assert len(result.get("evidence_hash", "")) > 0
            assert result.get("export_path") is not None
            assert Path(result["export_path"]).exists()
            assert result["workflow_summary"]["artifact_created"] is True
            assert result["workflow_summary"]["restart_persistence_artifact_created"] is True
        finally:
            stop_patches(mocks, patches)

    def test_non_mutation_verified(self, clean_git_metadata, clean_worktree,
                                    all_tags_present, before_bridge_ok, after_bridge_ok,
                                    sixteen_s_ok_result, guard_state_clean_str,
                                    env_safety_locked, rules_locked, autonomy_level_one,
                                    doctor_pass, kpi_hold_expected, hermes_policy_ok):
        patches = _build_mocks(
            before_health=before_bridge_ok, after_health=after_bridge_ok,
            before_snapshot={"ok": True, "endpoints_ok": 8, "endpoints_total": 8},
            after_snapshot={"ok": True, "endpoints_ok": 8, "endpoints_total": 8},
            before_readiness={"summary": {"kill_switches": {"system_locked": True}, "allow_orders": False}},
            after_readiness={"summary": {"kill_switches": {"system_locked": True}, "allow_orders": False}},
            before_positions={"positions": []},
            after_positions={"positions": []},
            git_metadata=clean_git_metadata,
            worktree=clean_worktree,
            tags=all_tags_present,
            sixteen_s_before_result=sixteen_s_ok_result,
            sixteen_s_after_result=sixteen_s_ok_result,
            guard_state_content=guard_state_clean_str,
            env_safety=env_safety_locked,
            rules=rules_locked,
            autonomy=autonomy_level_one,
            doctor=doctor_pass,
            kpi=kpi_hold_expected,
            policy=hermes_policy_ok,
            clean_cycles_count=7,
            restart_ok=True, restart_msg="restarted ok",
        )
        mocks, patches = apply_patches(patches)
        try:
            result = _run_level1_restart_persistence_safety_checkpoint()
            assert result["no_broker_mutation"] is True
            assert result["no_broker_order_created"] is True
            assert result["no_broker_submission"] is True
            assert result["no_account_mutation"] is True
            assert result["no_position_mutation"] is True
            assert result["no_order_mutation"] is True
            assert result["no_order_endpoint_called"] is True
            assert result["no_preflight_endpoint_called"] is True
            assert result["no_approval_endpoint_called"] is True
            assert result["no_submit_endpoint_called"] is True
            assert result["no_mutation_endpoint_called"] is True
            assert result["no_trade_window_helper_called"] is True
            assert result["h1_token_not_used"] is True
            assert result["execution_authorized_now"] is False
            assert result["execution_performed"] is False
            non_actions = result.get("explicit_non_actions", [])
            assert any("did not call /order" in a for a in non_actions)
            assert any("sudo systemctl restart" in a for a in non_actions)
        finally:
            stop_patches(mocks, patches)

    def test_after_field_completeness(self, clean_git_metadata, clean_worktree,
                                       all_tags_present, before_bridge_ok, after_bridge_ok,
                                       sixteen_s_ok_result, guard_state_clean_str,
                                       env_safety_locked, rules_locked, autonomy_level_one,
                                       doctor_pass, kpi_hold_expected, hermes_policy_ok):
        patches = _build_mocks(
            before_health=before_bridge_ok, after_health=after_bridge_ok,
            before_snapshot={"ok": True, "endpoints_ok": 8, "endpoints_total": 8},
            after_snapshot={"ok": True, "endpoints_ok": 8, "endpoints_total": 8},
            before_readiness={"summary": {"kill_switches": {"system_locked": True}, "allow_orders": False}},
            after_readiness={"summary": {"kill_switches": {"system_locked": True}, "allow_orders": False}},
            before_positions={"positions": []},
            after_positions={"positions": []},
            git_metadata=clean_git_metadata,
            worktree=clean_worktree,
            tags=all_tags_present,
            sixteen_s_before_result=sixteen_s_ok_result,
            sixteen_s_after_result=sixteen_s_ok_result,
            guard_state_content=guard_state_clean_str,
            env_safety=env_safety_locked,
            rules=rules_locked,
            autonomy=autonomy_level_one,
            doctor=doctor_pass,
            kpi=kpi_hold_expected,
            policy=hermes_policy_ok,
            clean_cycles_count=7,
            restart_ok=True, restart_msg="restarted ok",
        )
        mocks, patches = apply_patches(patches)
        try:
            result = _run_level1_restart_persistence_safety_checkpoint()
            after = result["after"]
            assert "connected" in after
            assert "mode" in after
            assert "read_only" in after
            assert "allow_orders" in after
            assert "endpoints_ok" in after
            assert "endpoints_ok_count" in after
            assert "endpoints_total_count" in after
            assert "positions_count" in after
            assert "positions_flat" in after
            assert "system_locked" in after
        finally:
            stop_patches(mocks, patches)

    def test_restart_persistence_audit_all_fields(self, clean_git_metadata, clean_worktree,
                                                   all_tags_present, before_bridge_ok, after_bridge_ok,
                                                   sixteen_s_ok_result, guard_state_clean_str,
                                                   env_safety_locked, rules_locked, autonomy_level_one,
                                                   doctor_pass, kpi_hold_expected, hermes_policy_ok):
        patches = _build_mocks(
            before_health=before_bridge_ok, after_health=after_bridge_ok,
            before_snapshot={"ok": True, "endpoints_ok": 8, "endpoints_total": 8},
            after_snapshot={"ok": True, "endpoints_ok": 8, "endpoints_total": 8},
            before_readiness={"summary": {"kill_switches": {"system_locked": True}, "allow_orders": False}},
            after_readiness={"summary": {"kill_switches": {"system_locked": True}, "allow_orders": False}},
            before_positions={"positions": []},
            after_positions={"positions": []},
            git_metadata=clean_git_metadata,
            worktree=clean_worktree,
            tags=all_tags_present,
            sixteen_s_before_result=sixteen_s_ok_result,
            sixteen_s_after_result=sixteen_s_ok_result,
            guard_state_content=guard_state_clean_str,
            env_safety=env_safety_locked,
            rules=rules_locked,
            autonomy=autonomy_level_one,
            doctor=doctor_pass,
            kpi=kpi_hold_expected,
            policy=hermes_policy_ok,
            clean_cycles_count=7,
            restart_ok=True, restart_msg="restarted ok",
        )
        mocks, patches = apply_patches(patches)
        try:
            result = _run_level1_restart_persistence_safety_checkpoint()
            audit = result["restart_persistence_audit"]
            required_audit_keys = [
                "invariant_survived", "before_16s_ok", "after_16s_ok",
                "restart_attempted", "restart_performed", "restart_command_timed_out",
                "restart_target",
                "bridge_reachable_after", "bridge_survived",
                "mode_survived", "read_only_survived", "allow_orders_survived",
                "endpoints_survived", "positions_survived",
                "guard_state_survived", "safety_invariant_survived",
                "h1_boundary_survived", "mutation_boundary_survived",
                "order_window_boundary_survived",
            ]
            for key in required_audit_keys:
                assert key in audit, f"Missing key in audit: {key}"
            # Verify survival keys are True (exclude restart_command_timed_out)
            survival_keys = [k for k in required_audit_keys
                           if k not in ("restart_attempted", "restart_command_timed_out")]
            for key in survival_keys:
                assert audit[key], f"Survival key {key} should be True"
        finally:
            stop_patches(mocks, patches)


# ===========================================================================
# T6: Helper function unit tests
# ===========================================================================

class TestHelpers:
    def test_restart_bridge_service_mocked_ok(self):
        with patch("subprocess.run") as mock_run:
            mock_result = MagicMock()
            mock_result.returncode = 0
            mock_result.stdout = "ok"
            mock_result.stderr = ""
            mock_run.return_value = mock_result

            ok, msg, timed_out = _restart_bridge_service()
            assert ok is True
            assert timed_out is False
            assert "restarted successfully" in msg

    def test_restart_bridge_service_mocked_fail(self):
        with patch("subprocess.run") as mock_run:
            mock_result = MagicMock()
            mock_result.returncode = 1
            mock_result.stdout = ""
            mock_result.stderr = "Access denied"
            mock_run.return_value = mock_result

            ok, msg, timed_out = _restart_bridge_service()
            assert ok is False
            assert timed_out is False
            assert "Access denied" in msg

    def test_restart_bridge_service_mocked_timeout(self):
        import subprocess as _sp
        with patch("subprocess.run", side_effect=_sp.TimeoutExpired(cmd=["sudo"], timeout=180)):
            ok, msg, timed_out = _restart_bridge_service()
            assert ok is False
            assert timed_out is True
            assert "recovery still pending" in msg

    def test_snapshot_bridge_state_ok(self):
        responses = {
            "/health": (200, {"connected": True, "mode": "paper", "read_only": True}),
            "/snapshot": (200, {"ok": True, "endpoints_ok": 8, "endpoints_total": 8}),
            "/positions": (200, {"positions": []}),
            "/readiness": (200, {"summary": {"kill_switches": {"system_locked": True}, "allow_orders": False}}),
        }
        mock_open = _MockUrlOpen(responses)
        with patch("urllib.request.urlopen", mock_open):
            state = _snapshot_bridge_state("http://localhost:5000/v1/api")
            assert state["connected"] is True
            assert state["mode"] == "paper"
            assert state["read_only"] is True
            assert state["allow_orders"] is False
            assert state["endpoints_ok"] is True
            assert state["endpoints_ok_count"] == 8
            assert state["endpoints_total_count"] == 8
            assert state["positions_count"] == 0
            assert state["positions_flat"] is True
            assert state["system_locked"] is True

    def test_snapshot_bridge_state_offline(self):
        with patch("urllib.request.urlopen", side_effect=Exception("offline")):
            state = _snapshot_bridge_state("http://localhost:5000/v1/api")
            assert state["connected"] is False
            assert state["endpoints_ok"] is False

    def test_poll_bridge_health_connected_immediately(self):
        responses = {"/health": (200, {"connected": True, "mode": "paper", "read_only": True})}
        mock_open = _MockUrlOpen(responses)
        with patch("urllib.request.urlopen", mock_open):
            ok, health = _poll_bridge_health("http://localhost:5000/v1/api", timeout_secs=5, poll_interval=0.1)
            assert ok is True
            assert health["connected"] is True

    def test_poll_bridge_health_timeout(self):
        with patch("urllib.request.urlopen", side_effect=Exception("offline")):
            ok, health = _poll_bridge_health("http://localhost:5000/v1/api", timeout_secs=1, poll_interval=0.1)
            assert ok is False
