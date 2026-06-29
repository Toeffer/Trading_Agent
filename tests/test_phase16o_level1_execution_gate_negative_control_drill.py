"""Tests for Phase 16O v2 — Level 1 Execution Gate Negative-Control Drill.

Expanded spec coverage (v2):
  - execution_gate_negative_controls section (status="blocked_as_expected", controls[])
  - blocked_execution_attempts[] array
  - gate_matrix section
  - workflow_summary (renamed from negative_control_summary)
  - Expanded per-intent fields (source_stage, side, time_in_force, simulated_intent_only, etc.)
  - Updated checklist (19 entries, spec-aligned)
  - All prerequisite NO_GO cases
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
    _run_level1_execution_gate_negative_control_drill,
    _PHASE16O_DIAGNOSIS,
    _PHASE16O_REQUIRED_TAGS,
    _PHASE16O_EXPORT_DIR,
    _PHASE16O_EXPLICIT_NON_ACTIONS,
)


# ===========================================================================
# Fixtures
# ===========================================================================

@pytest.fixture
def clean_git_metadata():
    return {"branch": "master", "commit_short": "abc1234",
            "commit": "abc1234abc1234abc1234abc1234abc1234abc",
            "tag": "phase16n_level1_readiness_chain_integrity_checkpoint"}


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
    return {"present_count": len(_PHASE16O_REQUIRED_TAGS),
            "present": list(_PHASE16O_REQUIRED_TAGS)}


@pytest.fixture
def one_tag_missing():
    missing = [_PHASE16O_REQUIRED_TAGS[0]]
    present = list(_PHASE16O_REQUIRED_TAGS[1:])
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
    return {"verdict": "HOLD",
            "blockers": [{"severity": "HOLD", "check": "system_locked"}],
            "autonomy": {"clean_cycles": 7}}


@pytest.fixture
def kpi_no_go():
    return {"verdict": "NO-GO",
            "blockers": [{"severity": "NO-GO", "check": "active_alerts"}]}


@pytest.fixture
def kpi_hold_clean_cycles_5():
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
    patches.append(patch("ibkr_operator._PHASE16O_EXPORT_DIR", tmp_export))
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
                           "level1-execution-gate-negative-control-drill", "--help"],
                          capture_output=True, text=True, timeout=10)
        assert r.returncode == 0

    def test_alias_phase16o_works(self):
        import subprocess
        r = subprocess.run([sys.executable, str(BRIDGE_DIR / "ibkr_operator.py"),
                           "phase16o-execution-gate-negative-control-drill", "--help"],
                          capture_output=True, text=True, timeout=10)
        assert r.returncode == 0

    def test_alias_level1_execution_negative_control_works(self):
        import subprocess
        r = subprocess.run([sys.executable, str(BRIDGE_DIR / "ibkr_operator.py"),
                           "level1-execution-negative-control-drill", "--help"],
                          capture_output=True, text=True, timeout=10)
        assert r.returncode == 0

    def test_alias_execution_gate_negative_control_works(self):
        import subprocess
        r = subprocess.run([sys.executable, str(BRIDGE_DIR / "ibkr_operator.py"),
                           "execution-gate-negative-control-drill", "--help"],
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
            result = _run_level1_execution_gate_negative_control_drill(demo_candidates=3)
            assert result["diagnosis"] == _PHASE16O_DIAGNOSIS["ready"]
            assert result["severity"] == "OK"
            assert result["execution_blocked_as_expected"] is True
            assert result["all_intents_blocked"] is True
            assert result["no_intent_executed"] is True

            # execution_gate_negative_controls (v2 — replaces old execution_gate)
            egnc = result["execution_gate_negative_controls"]
            assert egnc["status"] == "blocked_as_expected"
            assert egnc["negative_control_only"] is True
            assert egnc["execution_authorized_now"] is False
            assert egnc["order_enablement_required"] is True
            assert egnc["order_window_required"] is True
            assert egnc["h1_required"] is True
            assert egnc["real_preflight_required"] is True
            assert egnc["real_approval_required"] is True
            assert egnc["real_submit_required"] is True
            assert egnc["controls_count"] == 3
            assert egnc["controls_passed_count"] == 3
            assert egnc["controls_failed_count"] == 0
            assert len(egnc["controls"]) == 3
            for ctrl in egnc["controls"]:
                assert ctrl["attempted"] is True
                assert ctrl["endpoint_called"] is False
                assert ctrl["expected_block"] is True
                assert ctrl["actually_blocked"] is True
                assert ctrl["mutation_performed"] is False
                assert ctrl["h1_token_used"] is False
                assert ctrl["order_window_opened"] is False
                assert ctrl["broker_order_created"] is False

            # blocked_execution_attempts (v2 — new section)
            attempts = result["blocked_execution_attempts"]
            assert len(attempts) == 3
            for a in attempts:
                assert a["local_negative_control_only"] is True
                assert a["blocked"] is True
                assert a["endpoint_called"] is False
                assert a["broker_mutation"] is False
                assert a["executable"] is False
                assert a["performed"] is False
                assert len(a.get("block_reason", "")) > 0

            # gate_matrix (v2 — new section)
            gm = result["gate_matrix"]
            assert gm["level1_execution_allowed"] is False
            assert gm["readiness_chain_complete"] is True
            assert gm["readiness_chain_sufficient_for_execution"] is False
            assert gm["orders_enabled"] is False
            assert gm["system_locked"] is True
            assert gm["rules_enforced"] is False
            assert gm["order_window_open"] is False
            assert gm["h1_available_to_drill"] is False
            assert gm["real_preflight_done"] is False
            assert gm["real_approval_done"] is False
            assert gm["real_submit_done"] is False
            assert gm["broker_submission_allowed"] is False

            # Expanded per-intent fields
            intents = result["negative_control_plan"]["execution_intents"]
            for intent in intents:
                assert intent["simulated_intent_only"] is True
                assert intent["expected_result"] == "blocked"
                assert intent["executable"] is False
                assert intent["gate_status"] == "GATE_CLOSED"
                assert intent["source_stage"] == "16O_execution_gate_negative_control"
                assert intent["time_in_force"] == "DAY"
                assert intent["side"] == "BUY"
                assert intent["performed"] is False
                assert "requested_action" in intent

            # Checklist v2 entries
            ncl = result["negative_control_checklist"]
            assert len(ncl) == 19
            ncl_checks = {c["check"]: c["status"] for c in ncl}
            assert ncl_checks.get("confirms_readiness_chain_not_execution_authorization") == "PASS"
            assert ncl_checks.get("confirms_execution_authorized_now_false") == "PASS"
            assert ncl_checks.get("confirms_rules_not_enforced") == "PASS"
            assert ncl_checks.get("confirms_no_h1_used") == "PASS"

            # workflow_summary (v2 — renamed from negative_control_summary)
            wf = result["workflow_summary"]
            assert wf["execution_gate_negative_control_ready"] is True
            assert wf["all_execution_intents_blocked"] is True
            assert wf["all_blocks_expected"] is True
            assert wf["readiness_chain_not_sufficient_for_execution"] is True
            assert wf["execution_authorized_now_false"] is True
            assert wf["checklist_complete"] is True
            assert wf["no_broker_mutation"] is True
            assert wf["no_h1_seen"] is True

            # Non-mutation
            assert result["no_broker_mutation"] is True
            assert result["no_order_endpoint_called"] is True
            assert result["execution_authorized_now"] is False
            assert result["export_path"] is not None
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
            result = _run_level1_execution_gate_negative_control_drill()
            assert result["diagnosis"] == _PHASE16O_DIAGNOSIS["missing_required_tags"]
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
            result = _run_level1_execution_gate_negative_control_drill()
            assert result["diagnosis"] == _PHASE16O_DIAGNOSIS["dirty_worktree"]
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
            result = _run_level1_execution_gate_negative_control_drill()
            assert result["diagnosis"] == _PHASE16O_DIAGNOSIS["runtime_not_ready"]
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
            result = _run_level1_execution_gate_negative_control_drill(demo_candidates=0)
            assert result["diagnosis"] == _PHASE16O_DIAGNOSIS["ready"]
            assert result["negative_control_plan"]["execution_intents_count"] == 0
            assert result["execution_gate_negative_controls"]["controls_count"] == 0
            assert result["blocked_execution_attempts"] == []
            assert result["execution_blocked_as_expected"] is True
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
            result = _run_level1_execution_gate_negative_control_drill()
            assert len(result.get("evidence_hash", "")) > 0
            assert result.get("export_path") is not None
            assert Path(result["export_path"]).exists()
            assert result["execution_gate_negative_controls"]["gate_artifact_path"] is not None
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
            result = _run_level1_execution_gate_negative_control_drill()
            assert result["no_preflight_endpoint_called"] is True
            assert result["no_approval_endpoint_called"] is True
            assert result["no_submit_endpoint_called"] is True
            assert result["no_order_endpoint_called"] is True
            assert result["no_trade_window_helper_called"] is True
            non_actions = result.get("explicit_non_actions", [])
            assert any("did not call /order" in a for a in non_actions)
            assert any("did not call /order/preflight" in a for a in non_actions)
            assert any("did not call /order/approve" in a for a in non_actions)
            assert any("did not call /order/submit" in a for a in non_actions)
            assert any("negative-control" in a.lower() for a in non_actions)
        finally:
            stop_patches(mocks, patches)
