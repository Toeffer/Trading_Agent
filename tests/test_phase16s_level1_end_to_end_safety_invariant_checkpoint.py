"""Tests for Phase 16S — Level 1 End-to-End Safety Invariant Checkpoint.

Covers:
  - command registration + 3 aliases
  - clean runtime OK with full field verification
  - prerequisite NO_GO cases (tags, worktree, runtime, orders, bridge AO,
    rules, system unlocked, autonomy, guard, doctor, KPI, policy, clean_cycles,
    positions, alerts, endpoints)
  - safety invariant broken NO_GO
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
_YESTERDAY_STR = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")


BRIDGE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BRIDGE_DIR))

from ibkr_operator import (
    _run_level1_end_to_end_safety_invariant_checkpoint,
    _PHASE16S_DIAGNOSIS,
    _PHASE16S_REQUIRED_TAGS,
    _PHASE16S_EXPORT_DIR,
    _PHASE16S_EXPLICIT_NON_ACTIONS,
)


# ===========================================================================
# Fixtures
# ===========================================================================

@pytest.fixture
def clean_git_metadata():
    return {"branch": "master", "commit_short": "abc1234",
            "commit": "abc1234abc1234abc1234abc1234abc1234abc",
            "tag": "phase16r_level1_broker_mutation_firewall_audit_checkpoint"}

@pytest.fixture
def clean_worktree():
    return {"clean": True, "dirty_files": []}

@pytest.fixture
def origin_aligned():
    return {"aligned": True, "local_master_commit": "abc1234",
            "origin_master_commit": "abc1234"}

@pytest.fixture
def all_tags_present():
    return {"present_count": len(_PHASE16S_REQUIRED_TAGS),
            "present": list(_PHASE16S_REQUIRED_TAGS)}

@pytest.fixture
def one_tag_missing():
    missing = [_PHASE16S_REQUIRED_TAGS[0]]
    present = list(_PHASE16S_REQUIRED_TAGS[1:])
    return {"present_count": len(present), "present": present}

@pytest.fixture
def bridge_health_ok():
    return {"connected": True, "mode": "paper", "read_only": True}

@pytest.fixture
def positions_flat():
    return {"positions": []}

@pytest.fixture
def alerts_clean():
    return {"alerts": []}

@pytest.fixture
def snapshot_ok():
    return {"ok": True, "endpoints": 8}

@pytest.fixture
def readiness_locked():
    return {"summary": {"kill_switches": {"system_locked": True}, "allow_orders": False}}

@pytest.fixture
def guard_state_clean():
    return json.dumps({"trade_date": _TODAY_STR, "daily_trade_count": 0, "daily_halt_active": False})

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
    return {"pass": True, "passed": 14, "total": 15, "passed_count": 14, "check_count": 15,
            "checks": [{"check": "h1_token_canary", "ok": True, "status": "PASS"}]}

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
                 clean_cycles_count=7, ledger_exists=True, bridge_url="http://localhost:5000/v1/api"):
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
    patches.append(patch("ibkr_operator._PHASE16S_EXPORT_DIR", tmp_export))
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
                           "level1-end-to-end-safety-invariant-checkpoint", "--help"],
                          capture_output=True, text=True, timeout=10)
        assert r.returncode == 0

    def test_alias_phase16s_works(self):
        import subprocess
        r = subprocess.run([sys.executable, str(BRIDGE_DIR / "ibkr_operator.py"),
                           "phase16s-end-to-end-safety-invariant-checkpoint", "--help"],
                          capture_output=True, text=True, timeout=10)
        assert r.returncode == 0

    def test_alias_level1_safety_invariant_works(self):
        import subprocess
        r = subprocess.run([sys.executable, str(BRIDGE_DIR / "ibkr_operator.py"),
                           "level1-safety-invariant-checkpoint", "--help"],
                          capture_output=True, text=True, timeout=10)
        assert r.returncode == 0

    def test_alias_end_to_end_safety_invariant_works(self):
        import subprocess
        r = subprocess.run([sys.executable, str(BRIDGE_DIR / "ibkr_operator.py"),
                           "end-to-end-safety-invariant-checkpoint", "--help"],
                          capture_output=True, text=True, timeout=10)
        assert r.returncode == 0


# ===========================================================================
# T2: Clean runtime => OK
# ===========================================================================

class TestCleanRuntime:
    def test_clean_runtime_ok(self, clean_git_metadata, clean_worktree,
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
            result = _run_level1_end_to_end_safety_invariant_checkpoint()
            assert result["diagnosis"] == _PHASE16S_DIAGNOSIS["ready"]
            assert result["severity"] == "OK"
            assert result["current_level"] == 1

            # End-to-end safety invariant
            inv = result["end_to_end_safety_invariant"]
            assert inv["status"] == "invariant_intact"
            assert inv["invariant_only"] is True
            assert inv["readiness_chain_intact"] is True
            assert inv["execution_gate_closed"] is True
            assert inv["order_window_closed"] is True
            assert inv["h1_boundary_intact"] is True
            assert inv["broker_mutation_firewall_intact"] is True
            assert inv["level1_advisory_only"] is True
            assert inv["read_only_mode"] is True
            assert inv["paper_mode"] is True
            assert inv["orders_disabled"] is True
            assert inv["rules_not_enforced"] is True
            assert inv["system_locked"] is True
            assert inv["positions_flat"] is True
            assert inv["no_order_endpoint_called"] is True
            assert inv["no_preflight_endpoint_called"] is True
            assert inv["no_approval_endpoint_called"] is True
            assert inv["no_submit_endpoint_called"] is True
            assert inv["no_mutation_endpoint_called"] is True
            assert inv["no_broker_order_created"] is True
            assert inv["no_broker_submission"] is True
            assert inv["no_account_mutation"] is True
            assert inv["no_position_mutation"] is True
            assert inv["no_order_mutation"] is True
            assert inv["no_broker_mutation"] is True
            assert inv["no_order_window_opened"] is True
            assert inv["h1_token_not_read"] is True
            assert inv["h1_token_not_used"] is True
            assert inv["no_h1_header_constructed"] is True
            assert inv["no_h1_header_sent"] is True
            assert inv["no_trade_window_helper_called"] is True
            assert inv["execution_authorized_now"] is False
            assert inv["order_enablement_allowed_now"] is False
            assert "future_required_path" in inv
            assert inv["all_boundaries_intact"] is True
            assert inv["kpi_boundary_ok"] is True
            assert inv["doctor_boundary_ok"] is True
            assert inv["policy_boundary_ok"] is True
            assert inv["mutation_boundary_ok"] is True
            assert inv["h1_boundary_ok"] is True
            assert inv["order_window_boundary_ok"] is True
            assert inv["execution_gate_boundary_ok"] is True

            # Invariant checklist
            ncl = result.get("invariant_checklist", [])
            assert len(ncl) == 23
            ncl_checks = {c["check"]: c["status"] for c in ncl}
            assert ncl_checks["confirms_level1_only"] == "PASS"
            assert ncl_checks["confirms_all_boundaries_intact"] == "PASS"
            assert ncl_checks["confirms_kpi_boundary_ok"] == "PASS"

            # Top-level boundary flags
            assert result["kpi_acceptable"] is True
            assert result["doctor_acceptable"] is True
            assert result["policy_boundary_ok"] is True
            assert result["mutation_boundary_ok"] is True

            # Invariant matrix
            matrix = result["invariant_matrix"]
            assert matrix["all_required_tags_present"] is True
            assert matrix["runtime_safe"] is True
            assert matrix["autonomy_safe"] is True
            assert matrix["guard_state_clean"] is True
            assert matrix["safety_flags_locked"] is True
            assert matrix["positions_flat"] is True

            # Top-level no-mutation guarantees
            assert result["no_broker_mutation"] is True
            assert result["no_order_endpoint_called"] is True
            assert result["no_h1_token_used"] is True
            assert result["no_order_window_opened"] is True
            assert result["execution_authorized_now"] is False
            assert result["execution_performed"] is False
            assert result["h1_token_not_used"] is True
            assert result["no_mutation_endpoint_called"] is True
            assert result["no_order_mutation"] is True
            assert result["all_mutation_surfaces_blocked"] is True
            assert result["all_blocks_expected"] is True
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
            result = _run_level1_end_to_end_safety_invariant_checkpoint()
            assert result["diagnosis"] == _PHASE16S_DIAGNOSIS["missing_required_tags"]
            assert result["severity"] == "NO_GO"
        finally:
            stop_patches(mocks, patches)

    def test_bridge_disconnected_no_go(self, clean_git_metadata, clean_worktree,
                                       origin_aligned, all_tags_present,
                                       positions_flat, alerts_clean, snapshot_ok,
                                       readiness_locked, guard_state_clean, env_safety_locked,
                                       rules_locked, autonomy_level_one, doctor_pass,
                                       kpi_hold_expected, hermes_policy_ok):
        patches = _build_mocks(
            health={"connected": False, "mode": "paper"}, positions=positions_flat,
            alerts=alerts_clean, snapshot=snapshot_ok, readiness=readiness_locked,
            git_metadata=clean_git_metadata, worktree=clean_worktree,
            origin=origin_aligned, tags=all_tags_present,
            guard_state_content=guard_state_clean, env_safety=env_safety_locked,
            rules=rules_locked, autonomy=autonomy_level_one,
            doctor=doctor_pass, kpi=kpi_hold_expected, policy=hermes_policy_ok,
        )
        mocks, patches = apply_patches(patches)
        try:
            result = _run_level1_end_to_end_safety_invariant_checkpoint()
            assert result["diagnosis"] == _PHASE16S_DIAGNOSIS["runtime_not_ready"]
            assert result["severity"] == "NO_GO"
        finally:
            stop_patches(mocks, patches)

    def test_orders_enabled_no_go(self, clean_git_metadata, clean_worktree,
                                   origin_aligned, all_tags_present, bridge_health_ok,
                                   positions_flat, alerts_clean, snapshot_ok,
                                   readiness_locked, guard_state_clean,
                                   rules_locked, autonomy_level_one, doctor_pass,
                                   kpi_hold_expected, hermes_policy_ok):
        patches = _build_mocks(
            health=bridge_health_ok, positions=positions_flat,
            alerts=alerts_clean, snapshot=snapshot_ok, readiness=readiness_locked,
            git_metadata=clean_git_metadata, worktree=clean_worktree,
            origin=origin_aligned, tags=all_tags_present,
            guard_state_content=guard_state_clean,
            env_safety={"IBKR_ALLOW_ORDERS": "true", "found": True},
            rules=rules_locked, autonomy=autonomy_level_one,
            doctor=doctor_pass, kpi=kpi_hold_expected, policy=hermes_policy_ok,
        )
        mocks, patches = apply_patches(patches)
        try:
            result = _run_level1_end_to_end_safety_invariant_checkpoint()
            assert result["diagnosis"] == _PHASE16S_DIAGNOSIS["orders_enabled"]
            assert result["severity"] == "NO_GO"
        finally:
            stop_patches(mocks, patches)

    def test_system_unlocked_no_go(self, clean_git_metadata, clean_worktree,
                                    origin_aligned, all_tags_present, bridge_health_ok,
                                    positions_flat, alerts_clean, snapshot_ok,
                                    guard_state_clean, env_safety_locked,
                                    rules_locked, autonomy_level_one, doctor_pass,
                                    kpi_hold_expected, hermes_policy_ok):
        readiness = {"summary": {"kill_switches": {"system_locked": False}, "allow_orders": False}}
        patches = _build_mocks(
            health=bridge_health_ok, positions=positions_flat,
            alerts=alerts_clean, snapshot=snapshot_ok, readiness=readiness,
            git_metadata=clean_git_metadata, worktree=clean_worktree,
            origin=origin_aligned, tags=all_tags_present,
            guard_state_content=guard_state_clean, env_safety=env_safety_locked,
            rules=rules_locked, autonomy=autonomy_level_one,
            doctor=doctor_pass, kpi=kpi_hold_expected, policy=hermes_policy_ok,
        )
        mocks, patches = apply_patches(patches)
        try:
            result = _run_level1_end_to_end_safety_invariant_checkpoint()
            assert result["diagnosis"] == _PHASE16S_DIAGNOSIS["system_unlocked"]
            assert result["severity"] == "NO_GO"
        finally:
            stop_patches(mocks, patches)

    def test_autonomy_level_zero_no_go(self, clean_git_metadata, clean_worktree,
                                        origin_aligned, all_tags_present, bridge_health_ok,
                                        positions_flat, alerts_clean, snapshot_ok,
                                        readiness_locked, guard_state_clean, env_safety_locked,
                                        rules_locked, doctor_pass,
                                        kpi_hold_expected, hermes_policy_ok):
        patches = _build_mocks(
            health=bridge_health_ok, positions=positions_flat,
            alerts=alerts_clean, snapshot=snapshot_ok, readiness=readiness_locked,
            git_metadata=clean_git_metadata, worktree=clean_worktree,
            origin=origin_aligned, tags=all_tags_present,
            guard_state_content=guard_state_clean, env_safety=env_safety_locked,
            rules=rules_locked, autonomy="0",
            doctor=doctor_pass, kpi=kpi_hold_expected, policy=hermes_policy_ok,
        )
        mocks, patches = apply_patches(patches)
        try:
            result = _run_level1_end_to_end_safety_invariant_checkpoint()
            assert result["diagnosis"] == _PHASE16S_DIAGNOSIS["autonomy_not_level1"]
            assert result["severity"] == "NO_GO"
        finally:
            stop_patches(mocks, patches)


# ===========================================================================
# T4: Edge cases
# ===========================================================================

class TestEdgeCases:
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
            result = _run_level1_end_to_end_safety_invariant_checkpoint()
            assert len(result.get("evidence_hash", "")) > 0
            assert result.get("export_path") is not None
            assert Path(result["export_path"]).exists()
            assert result["end_to_end_safety_invariant"].get("artifact_path") is not None
            assert result["workflow_summary"]["artifact_created"] is True
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
            result = _run_level1_end_to_end_safety_invariant_checkpoint()
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
            assert any("did not call /usr/local/sbin/ibkr-trade-window" in a for a in non_actions)
            assert any("end-to-end safety invariant" in a.lower() for a in non_actions)
        finally:
            stop_patches(mocks, patches)

    def test_invariant_matrix_all_fields(self, clean_git_metadata, clean_worktree,
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
            result = _run_level1_end_to_end_safety_invariant_checkpoint()
            matrix = result["invariant_matrix"]
            assert "all_required_tags_present" in matrix
            assert "runtime_safe" in matrix
            assert "autonomy_safe" in matrix
            assert "guard_state_clean" in matrix
            assert "safety_flags_locked" in matrix
            assert "positions_flat" in matrix
            # All true for clean runtime
            assert all(matrix.values())
        finally:
            stop_patches(mocks, patches)
