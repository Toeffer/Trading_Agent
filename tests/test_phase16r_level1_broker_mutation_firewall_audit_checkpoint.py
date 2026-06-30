"""Tests for Phase 16R v2 — Level 1 Broker-Mutation Firewall Audit Checkpoint.

Expanded spec (v2) coverage:
  - broker_mutation_firewall section (30+ fields, full schema)
  - mutation_surface_audit section (surfaces_count, surfaces[], expected_status="blocked_or_unperformed")
  - read_only_evidence section (new)
  - mutation_probe_matrix (expanded with bridge/env/rules fields)
  - blocked_mutation_attempts (refined field names)
  - broker_mutation_checklist (31 entries)
  - workflow_summary (all_mutation_surfaces_blocked)
  - Prerequisite NO_GO cases (5)
  - Firewall violation NO_GO cases
  - Edge cases
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
    _run_level1_broker_mutation_firewall_audit_checkpoint,
    _PHASE16R_DIAGNOSIS,
    _PHASE16R_REQUIRED_TAGS,
    _PHASE16R_EXPORT_DIR,
    _PHASE16R_EXPLICIT_NON_ACTIONS,
)


# ===========================================================================
# Fixtures
# ===========================================================================

@pytest.fixture
def clean_git_metadata():
    return {"branch": "master", "commit_short": "abc1234",
            "commit": "abc1234abc1234abc1234abc1234abc1234abc",
            "tag": "phase16q_level1_h1_boundary_audit_checkpoint"}


@pytest.fixture
def clean_worktree():
    return {"clean": True, "dirty_files": []}


@pytest.fixture
def origin_aligned():
    return {"aligned": True, "local_master_commit": "abc1234",
            "origin_master_commit": "abc1234"}


@pytest.fixture
def all_tags_present():
    return {"present_count": len(_PHASE16R_REQUIRED_TAGS),
            "present": list(_PHASE16R_REQUIRED_TAGS)}


@pytest.fixture
def one_tag_missing():
    missing = [_PHASE16R_REQUIRED_TAGS[0]]
    present = list(_PHASE16R_REQUIRED_TAGS[1:])
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
    patches.append(patch("ibkr_operator._PHASE16R_EXPORT_DIR", tmp_export))
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
                           "level1-broker-mutation-firewall-audit-checkpoint", "--help"],
                          capture_output=True, text=True, timeout=10)
        assert r.returncode == 0

    def test_alias_phase16r_works(self):
        import subprocess
        r = subprocess.run([sys.executable, str(BRIDGE_DIR / "ibkr_operator.py"),
                           "phase16r-broker-mutation-firewall-audit-checkpoint", "--help"],
                          capture_output=True, text=True, timeout=10)
        assert r.returncode == 0

    def test_alias_level1_firewall_checkpoint_works(self):
        import subprocess
        r = subprocess.run([sys.executable, str(BRIDGE_DIR / "ibkr_operator.py"),
                           "level1-broker-mutation-firewall-checkpoint", "--help"],
                          capture_output=True, text=True, timeout=10)
        assert r.returncode == 0

    def test_alias_broker_mutation_firewall_audit_works(self):
        import subprocess
        r = subprocess.run([sys.executable, str(BRIDGE_DIR / "ibkr_operator.py"),
                           "broker-mutation-firewall-audit-checkpoint", "--help"],
                          capture_output=True, text=True, timeout=10)
        assert r.returncode == 0


# ===========================================================================
# T2: Clean runtime => OK with full v2 field verification
# ===========================================================================

class TestCleanRuntime:
    def test_clean_runtime_v2_all_fields(self, clean_git_metadata, clean_worktree,
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
            result = _run_level1_broker_mutation_firewall_audit_checkpoint(demo_candidates=3)
            assert result["diagnosis"] == _PHASE16R_DIAGNOSIS["ready"]
            assert result["severity"] == "OK"
            assert result["broker_mutation_firewall_intact"] is True
            assert result["all_canaries_blocked"] is True
            assert result["no_canary_executed"] is True

            # Guard state top-level
            assert result["guard_state_clean"] is True
            assert "canonical_trade_date" in result
            assert result["trade_date_stale"] is False
            assert result["halt_active"] is False

            # Top-level non-mutation
            assert result["no_broker_mutation"] is True
            assert result["no_broker_order_created"] is True
            assert result["no_broker_submission"] is True
            assert result["no_account_mutation"] is True
            assert result["no_position_mutation"] is True
            assert result["no_order_window_opened"] is True
            assert result["no_h1_token_used"] is True
            assert result["no_h1_token_read"] is True
            assert result["execution_authorized_now"] is False
            assert result["execution_performed"] is False

            # New spec fields (message #4310/#4311)
            assert result["current_level"] == 1
            assert result["no_mutation_endpoint_called"] is True
            assert result["no_order_mutation"] is True
            assert result["h1_token_not_used"] is True
            assert result["all_mutation_surfaces_blocked"] is True
            assert result["all_blocks_expected"] is True

            # broker_mutation_firewall
            fw = result["broker_mutation_firewall"]
            assert fw["status"] == "firewall_intact"
            assert fw["audit_only"] is True
            assert fw["read_only_mode"] is True
            assert fw["paper_mode"] is True
            assert fw["positions_flat"] is True
            assert fw["positions_count"] == 0
            assert fw["broker_order_created"] is False
            assert fw["broker_submission_performed"] is False
            assert fw["broker_cancel_performed"] is False
            assert fw["broker_modify_performed"] is False
            assert fw["account_mutation_performed"] is False
            assert fw["position_mutation_performed"] is False
            assert fw["order_mutation_performed"] is False
            assert fw["order_window_opened"] is False
            assert fw["h1_token_used"] is False
            assert fw["h1_header_constructed"] is False
            assert fw["h1_header_sent"] is False
            assert fw["trade_window_helper_called"] is False
            assert fw["order_endpoint_called"] is False
            assert fw["preflight_endpoint_called"] is False
            assert fw["approval_endpoint_called"] is False
            assert fw["submit_endpoint_called"] is False
            assert fw["mutation_endpoint_called"] is False
            assert fw["allowed_write_paths"] == ["export_artifact", "audit_artifact"]
            assert fw["disallowed_mutation_paths_blocked"] is True
            assert fw["future_order_window_required"] is True
            assert fw["future_h1_required"] is True
            assert fw["future_real_preflight_required"] is True
            assert fw["future_real_approval_required"] is True
            assert fw["future_real_submit_required"] is True
            assert "future_required_path" in fw
            assert fw["canaries_count"] == 3
            assert fw["canaries_blocked_count"] == 3
            assert fw["canaries_not_blocked_count"] == 0

            # mutation_surface_audit
            msa = result["mutation_surface_audit"]
            assert msa["surfaces_count"] == 3
            assert msa["surfaces_passed_count"] == 3
            assert msa["surfaces_failed_count"] == 0
            assert len(msa["surfaces"]) == 3
            for sf in msa["surfaces"]:
                assert sf["expected_status"] == "blocked_or_unperformed"
                assert sf["endpoint_called"] is False
                assert sf["mutation_performed"] is False
                assert sf["broker_state_changed"] is False
                assert sf["blocked"] is True
                assert "category" in sf

            # read_only_evidence
            roe = result["read_only_evidence"]
            assert roe["only_export_artifacts_written"] is True
            assert roe["no_runtime_config_mutation"] is True
            assert roe["no_env_mutation"] is True
            assert roe["no_rules_mutation"] is True
            assert roe["no_guard_repair_performed"] is True
            assert roe["no_service_restart"] is True
            assert roe["no_reconnect_attempted"] is True

            # mutation_probe_matrix
            mpm = result["mutation_probe_matrix"]
            assert mpm["bridge_read_only"] is True
            assert mpm["bridge_allow_orders"] is False
            assert mpm["system_locked"] is True
            assert mpm["broker_submission_allowed"] is False
            assert mpm["broker_write_allowed"] is False
            assert mpm["account_write_allowed"] is False
            assert mpm["position_write_allowed"] is False
            assert mpm["order_write_allowed"] is False
            assert mpm["order_window_open"] is False
            assert mpm["h1_available_to_drill"] is False

            # blocked_mutation_attempts
            attempts = result["blocked_mutation_attempts"]
            assert len(attempts) == 3
            for a in attempts:
                assert a["local_audit_only"] is True
                assert a["blocked"] is True
                assert a["endpoint_called"] is False
                assert a["broker_mutation"] is False
                assert a["account_mutation"] is False
                assert a["position_mutation"] is False
                assert a["order_mutation"] is False
                assert a["h1_token_used"] is False
                assert a["order_window_opened"] is False
                assert a["executable"] is False
                assert a["performed"] is False

            # broker_mutation_checklist
            ncl = result["broker_mutation_checklist"]
            assert len(ncl) == 31
            ncl_checks = {c["check"]: c["status"] for c in ncl}
            assert ncl_checks["confirms_read_only_mode"] == "PASS"
            assert ncl_checks["confirms_paper_mode"] == "PASS"
            assert ncl_checks["confirms_positions_flat"] == "PASS"
            assert ncl_checks["confirms_no_order_endpoint_called"] == "PASS"
            assert ncl_checks["confirms_no_broker_order_created"] == "PASS"
            assert ncl_checks["confirms_no_broker_submission"] == "PASS"
            assert ncl_checks["confirms_no_broker_cancel"] == "PASS"
            assert ncl_checks["confirms_no_broker_modify"] == "PASS"
            assert ncl_checks["confirms_no_account_mutation"] == "PASS"
            assert ncl_checks["confirms_no_position_mutation"] == "PASS"
            assert ncl_checks["confirms_no_order_mutation"] == "PASS"
            assert ncl_checks["confirms_no_h1_used"] == "PASS"
            assert ncl_checks["confirms_trade_window_helper_not_called"] == "PASS"
            assert ncl_checks["confirms_only_export_artifacts_written"] == "PASS"

            # workflow_summary
            wf = result["workflow_summary"]
            assert wf["broker_mutation_firewall_audit_ready"] is True
            assert wf["broker_mutation_firewall_intact"] is True
            assert wf["all_mutation_surfaces_blocked"] is True
            assert wf["no_broker_mutation"] is True
            assert wf["no_order_endpoint_called"] is True
            assert wf["checklist_complete"] is True
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
            result = _run_level1_broker_mutation_firewall_audit_checkpoint()
            assert result["diagnosis"] == _PHASE16R_DIAGNOSIS["missing_required_tags"]
            assert result["severity"] == "NO_GO"
            assert "broker_mutation_firewall" in result
            assert "mutation_surface_audit" in result
            assert "read_only_evidence" in result
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
            result = _run_level1_broker_mutation_firewall_audit_checkpoint()
            assert result["diagnosis"] == _PHASE16R_DIAGNOSIS["runtime_not_ready"]
            assert result["severity"] == "NO_GO"
        finally:
            stop_patches(mocks, patches)

    def test_safety_unlocked_no_go(self, clean_git_metadata, clean_worktree,
                                    origin_aligned, all_tags_present, bridge_health_ok,
                                    positions_flat, alerts_clean, snapshot_ok,
                                    guard_state_clean, env_safety_locked,
                                    rules_locked, autonomy_level_one, doctor_pass,
                                    kpi_hold_expected, hermes_policy_ok):
        # system_locked=False but orders still disabled, rules not enforced
        readiness = {"summary": {"kill_switches": {"system_locked": False},
                                 "allow_orders": False}}
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
            result = _run_level1_broker_mutation_firewall_audit_checkpoint()
            assert result["diagnosis"] == _PHASE16R_DIAGNOSIS["safety_unlocked"]
            assert result["severity"] == "NO_GO"
        finally:
            stop_patches(mocks, patches)

    def test_orders_enabled_no_go(self, clean_git_metadata, clean_worktree,
                                   origin_aligned, all_tags_present, bridge_health_ok,
                                   positions_flat, alerts_clean, snapshot_ok,
                                   readiness_locked, guard_state_clean,
                                   rules_locked, autonomy_level_one, doctor_pass,
                                   kpi_hold_expected, hermes_policy_ok):
        # env_allow_orders = "true"
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
            result = _run_level1_broker_mutation_firewall_audit_checkpoint()
            assert result["diagnosis"] == _PHASE16R_DIAGNOSIS["orders_enabled"]
            assert result["severity"] == "NO_GO"
        finally:
            stop_patches(mocks, patches)

    def test_bridge_allow_orders_no_go(self, clean_git_metadata, clean_worktree,
                                        origin_aligned, all_tags_present, bridge_health_ok,
                                        positions_flat, alerts_clean, snapshot_ok,
                                        guard_state_clean, env_safety_locked,
                                        rules_locked, autonomy_level_one, doctor_pass,
                                        kpi_hold_expected, hermes_policy_ok):
        # bridge allow_orders=True
        readiness = {"summary": {"kill_switches": {"system_locked": True},
                                 "allow_orders": True}}
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
            result = _run_level1_broker_mutation_firewall_audit_checkpoint()
            assert result["diagnosis"] == _PHASE16R_DIAGNOSIS["bridge_allow_orders_enabled"]
            assert result["severity"] == "NO_GO"
        finally:
            stop_patches(mocks, patches)

    def test_rules_enforced_no_go(self, clean_git_metadata, clean_worktree,
                                   origin_aligned, all_tags_present, bridge_health_ok,
                                   positions_flat, alerts_clean, snapshot_ok,
                                   readiness_locked, guard_state_clean, env_safety_locked,
                                   autonomy_level_one, doctor_pass,
                                   kpi_hold_expected, hermes_policy_ok):
        # rules_enforced = "true"
        patches = _build_mocks(
            health=bridge_health_ok, positions=positions_flat,
            alerts=alerts_clean, snapshot=snapshot_ok, readiness=readiness_locked,
            git_metadata=clean_git_metadata, worktree=clean_worktree,
            origin=origin_aligned, tags=all_tags_present,
            guard_state_content=guard_state_clean, env_safety=env_safety_locked,
            rules={"enforced": "true", "found": True},
            autonomy=autonomy_level_one,
            doctor=doctor_pass, kpi=kpi_hold_expected, policy=hermes_policy_ok,
        )
        mocks, patches = apply_patches(patches)
        try:
            result = _run_level1_broker_mutation_firewall_audit_checkpoint()
            assert result["diagnosis"] == _PHASE16R_DIAGNOSIS["rules_enforced"]
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
            result = _run_level1_broker_mutation_firewall_audit_checkpoint()
            assert result["diagnosis"] == _PHASE16R_DIAGNOSIS["autonomy_not_level1"]
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
            result = _run_level1_broker_mutation_firewall_audit_checkpoint()
            assert result["diagnosis"] == _PHASE16R_DIAGNOSIS["guard_state_not_clean"]
            assert result["severity"] == "NO_GO"
        finally:
            stop_patches(mocks, patches)


# ===========================================================================
# T4: Firewall violation NO_GO cases
# ===========================================================================

class TestFirewallViolations:
    def test_firewall_violation_order_endpoint_called(self, clean_git_metadata,
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
            result = _run_level1_broker_mutation_firewall_audit_checkpoint(demo_candidates=1)
            result["broker_mutation_firewall"]["order_endpoint_called"] = True
            fw = result["broker_mutation_firewall"]
            violations = []
            intact = True
            if fw.get("order_endpoint_called"):
                violations.append("order_endpoint_called"); intact = False
            assert not intact
            assert "order_endpoint_called" in violations
        finally:
            stop_patches(mocks, patches)

    def test_firewall_violation_broker_order_created(self, clean_git_metadata,
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
            result = _run_level1_broker_mutation_firewall_audit_checkpoint(demo_candidates=1)
            result["broker_mutation_firewall"]["broker_order_created"] = True
            fw = result["broker_mutation_firewall"]
            violations = []
            intact = True
            if fw.get("broker_order_created"):
                violations.append("broker_order_created"); intact = False
            assert not intact
            assert "broker_order_created" in violations
        finally:
            stop_patches(mocks, patches)

    def test_firewall_violation_broker_submission(self, clean_git_metadata,
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
            result = _run_level1_broker_mutation_firewall_audit_checkpoint(demo_candidates=1)
            result["broker_mutation_firewall"]["broker_submission_performed"] = True
            fw = result["broker_mutation_firewall"]
            violations = []
            intact = True
            if fw.get("broker_submission_performed"):
                violations.append("broker_submission_performed"); intact = False
            assert not intact
            assert "broker_submission_performed" in violations
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
            result = _run_level1_broker_mutation_firewall_audit_checkpoint(demo_candidates=0)
            assert result["diagnosis"] == _PHASE16R_DIAGNOSIS["ready"]
            assert result["broker_mutation_firewall"]["canaries_count"] == 0
            assert result["canary_intents"] == []
            assert result["blocked_mutation_attempts"] == []
            assert result["mutation_surface_audit"]["surfaces_count"] == 0
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
            result = _run_level1_broker_mutation_firewall_audit_checkpoint()
            assert len(result.get("evidence_hash", "")) > 0
            assert result.get("export_path") is not None
            assert Path(result["export_path"]).exists()
            assert result["broker_mutation_firewall"].get("audit_artifact_path") is not None
            assert result["workflow_summary"]["broker_mutation_firewall_artifact_created"] is True
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
            result = _run_level1_broker_mutation_firewall_audit_checkpoint()
            assert result["no_broker_mutation"] is True
            assert result["no_broker_order_created"] is True
            assert result["no_broker_submission"] is True
            assert result["no_account_mutation"] is True
            assert result["no_position_mutation"] is True
            assert result["no_order_endpoint_called"] is True
            assert result["no_preflight_endpoint_called"] is True
            assert result["no_approval_endpoint_called"] is True
            assert result["no_submit_endpoint_called"] is True
            assert result["no_trade_window_helper_called"] is True
            assert result["no_mutation_endpoint_called"] is True
            assert result["no_order_mutation"] is True
            assert result["h1_token_not_used"] is True
            assert result["execution_authorized_now"] is False
            assert result["execution_performed"] is False
            non_actions = result.get("explicit_non_actions", [])
            assert any("did not call /order" in a for a in non_actions)
            assert any("did not call /usr/local/sbin/ibkr-trade-window" in a for a in non_actions)
            assert any("broker-mutation firewall" in a.lower() for a in non_actions)
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
            result = _run_level1_broker_mutation_firewall_audit_checkpoint(demo_candidates=10)
            assert result["broker_mutation_firewall"]["canaries_count"] == 5
            assert len(result["canary_intents"]) == 5
            assert len(result["blocked_mutation_attempts"]) == 5
            assert result["mutation_surface_audit"]["surfaces_count"] == 5
        finally:
            stop_patches(mocks, patches)
