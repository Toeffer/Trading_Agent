"""Tests for Phase 16N v2 — Level 1 Readiness-Chain Integrity Checkpoint.

Expanded spec coverage:
  - readiness_chain_checkpoint section (status="checkpoint_only", future_* flags)
  - integrity_checklist (19 confirms)
  - workflow_summary (18 entries)
  - Top-level booleans (chain_complete, no_stage_*, final_stage_*, all_items_non_executable)
  - Per-stage expanded fields (order_window_opened, broker_mutation, futures, chain_complete, chain_order_valid)
  - All stages non_executable=true, advisory_or_readiness_only=true
  - Verdict CHAIN_INTACT/CHAIN_BROKEN
  - NO_GO prerequisites (missing tags, dirty worktree, autonomy, safety, guard, etc.)
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
    _run_level1_readiness_chain_integrity_checkpoint,
    _PHASE16N_DIAGNOSIS,
    _PHASE16N_REQUIRED_TAGS,
    _PHASE16N_EXPORT_DIR,
    _PHASE16N_EXPLICIT_NON_ACTIONS,
    _compute_evidence_hash,
)


# ===========================================================================
# Fixtures
# ===========================================================================

@pytest.fixture
def clean_git_metadata():
    return {"branch": "master", "commit_short": "abc1234",
            "commit": "abc1234abc1234abc1234abc1234abc1234abc",
            "tag": "phase16m_level1_execution_readiness_packet_drill"}


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
    return {"present_count": len(_PHASE16N_REQUIRED_TAGS),
            "present": list(_PHASE16N_REQUIRED_TAGS)}


@pytest.fixture
def one_tag_missing():
    missing = [_PHASE16N_REQUIRED_TAGS[0]]
    present = list(_PHASE16N_REQUIRED_TAGS[1:])
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
    patches.append(patch("ibkr_operator._PHASE16N_EXPORT_DIR", tmp_export))
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
                           "level1-readiness-chain-integrity-checkpoint", "--help"],
                          capture_output=True, text=True, timeout=10)
        assert r.returncode == 0

    def test_alias_phase16n_works(self):
        import subprocess
        r = subprocess.run([sys.executable, str(BRIDGE_DIR / "ibkr_operator.py"),
                           "phase16n-readiness-chain-integrity-checkpoint", "--help"],
                          capture_output=True, text=True, timeout=10)
        assert r.returncode == 0

    def test_alias_level1_readiness_chain_checkpoint_works(self):
        import subprocess
        r = subprocess.run([sys.executable, str(BRIDGE_DIR / "ibkr_operator.py"),
                           "level1-readiness-chain-checkpoint", "--help"],
                          capture_output=True, text=True, timeout=10)
        assert r.returncode == 0

    def test_alias_readiness_chain_integrity_checkpoint_works(self):
        import subprocess
        r = subprocess.run([sys.executable, str(BRIDGE_DIR / "ibkr_operator.py"),
                           "readiness-chain-integrity-checkpoint", "--help"],
                          capture_output=True, text=True, timeout=10)
        assert r.returncode == 0


# ===========================================================================
# T2: Clean runtime => OK with full field verification (v2 expanded spec)
# ===========================================================================

class TestCleanRuntime:
    def test_clean_runtime_produces_ok_all_fields(self, clean_git_metadata, clean_worktree,
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
            result = _run_level1_readiness_chain_integrity_checkpoint(demo_candidates=3)
            assert result["diagnosis"] == _PHASE16N_DIAGNOSIS["ready"]
            assert result["severity"] == "OK"
            assert result["operator_action_required"] is False

            # Top-level booleans
            assert result["chain_complete"] is True
            assert result["chain_order_valid"] is True
            assert result["all_stages_non_executable"] is True
            assert result["all_stages_advisory_or_readiness_only"] is True
            assert result["all_items_non_executable"] is True
            assert result["no_stage_authorizes_execution"] is True
            assert result["no_stage_calls_order_path"] is True
            assert result["no_stage_uses_h1"] is True
            assert result["no_stage_opens_order_window"] is True
            assert result["no_stage_creates_broker_order"] is True
            assert result["no_stage_mutates_broker"] is True
            assert result["no_stage_calls_trade_window_helper"] is True
            assert result["final_stage_readiness_only"] is True
            assert result["final_stage_execution_authorized_now"] is False
            assert result["final_stage_order_enablement_required"] is True

            # Non-mutation flags
            assert result["no_broker_mutation"] is True
            assert result["no_order_window_opened"] is True
            assert result["no_h1_seen"] is True
            assert result["no_preflight_endpoint_called"] is True
            assert result["no_approval_endpoint_called"] is True
            assert result["no_submit_endpoint_called"] is True
            assert result["no_order_path_called"] is True
            assert result["no_broker_order_created"] is True
            assert result["no_broker_submission"] is True

            # Export
            assert result["export_path"] is not None
            assert result["checkpoint_id"].startswith("chain-integrity-")

            # chain_integrity section
            ci = result["chain_integrity"]
            assert ci["chain_source"] == "synthetic_readonly_demo"
            assert ci["stages_expected_count"] == 7
            assert ci["stages_verified_count"] == 7
            assert ci["stages_missing"] == []
            assert ci["chain_intact"] is True
            assert ci["chain_complete"] is True
            assert ci["chain_order_valid"] is True
            assert ci["all_stages_non_executable"] is True
            assert ci["all_stages_advisory_or_readiness_only"] is True
            assert ci["any_broker_activity_detected"] is False
            assert ci["verdict"] == "CHAIN_INTACT"

            # 7 stages present with expanded per-stage fields
            stages = ci["stages"]
            assert len(stages) == 7
            expected_stages = [
                "16G proposal workflow", "16H human review package",
                "16I review decision audit", "16J order-plan draft",
                "16K simulated preflight dossier", "16L human approval packet",
                "16M execution-readiness packet",
            ]
            expected_types = [
                "proposal_drill", "review_package_drill",
                "decision_audit_drill", "order_plan_draft",
                "preflight_simulation_dossier", "human_approval_packet",
                "execution_readiness_packet",
            ]
            for i, s in enumerate(stages):
                assert s["stage"] == expected_stages[i]
                assert s["status"] == "verified_non_executable"
                assert s["artifact_type"] == expected_types[i]
                # Core invariants
                assert s["non_executable"] is True
                assert s["advisory_or_readiness_only"] is True
                assert s["broker_preflight_performed"] is False
                assert s["broker_approval_performed"] is False
                assert s["broker_submit_performed"] is False
                assert s["broker_order_created"] is False
                assert s["executable"] is False
                assert s["h1_token_used"] is False
                assert s["execution_authorized_now"] is False
                assert s["trade_window_helper_called"] is False
                # Expanded per-stage fields
                assert s["order_window_opened"] is False
                assert s["broker_mutation"] is False
                assert s["no_order_endpoint_called"] is True
                assert s["future_order_window_required"] is True
                assert s["future_h1_required"] is True
                assert isinstance(s["future_required_path"], str)
                assert s["chain_complete"] is True
                assert s["chain_order_valid"] is True
                # Final stage (16M) specific
                if i == 6:
                    assert s["final_stage_readiness_only"] is True
                    assert s["final_stage_execution_authorized_now"] is False
                    assert s["final_stage_order_enablement_required"] is True
                else:
                    assert s["final_stage_readiness_only"] is False
                    assert s["final_stage_execution_authorized_now"] is None
                    assert s["final_stage_order_enablement_required"] is None

            # readiness_chain_checkpoint section
            rcc = result["readiness_chain_checkpoint"]
            assert rcc["status"] == "checkpoint_only"
            assert rcc["executable"] is False
            assert rcc["execution_authorized_now"] is False
            assert rcc["order_enablement_required"] is True
            assert rcc["future_order_window_required"] is True
            assert rcc["future_h1_required"] is True
            assert rcc["future_real_preflight_required"] is True
            assert rcc["future_real_approval_required"] is True
            assert rcc["future_real_submit_required"] is True
            assert rcc["future_required_path"] == "/order/preflight -> /order/approve -> /order/submit"
            assert rcc.get("checkpoint_path") is not None
            assert len(rcc.get("checkpoint_hash", "")) > 0

            # integrity_checklist — 19 entries
            cl = result["integrity_checklist"]
            assert len(cl) == 19
            cl_checks = {c["check"]: c["status"] for c in cl}
            assert cl_checks["confirms_level1_only"] == "PASS"
            assert cl_checks["confirms_checkpoint_only"] == "PASS"
            assert cl_checks["confirms_full_chain_present"] == "PASS"
            assert cl_checks["confirms_chain_order_valid"] == "PASS"
            assert cl_checks["confirms_all_stages_non_executable"] == "PASS"
            assert cl_checks["confirms_no_execution_authorization"] == "PASS"
            assert cl_checks["confirms_orders_disabled"] == "PASS"
            assert cl_checks["confirms_system_locked"] == "PASS"
            assert cl_checks["confirms_no_h1_used"] == "PASS"
            assert cl_checks["confirms_no_order_window_opened"] == "PASS"
            assert cl_checks["confirms_no_preflight_endpoint_called"] == "PASS"
            assert cl_checks["confirms_no_approval_endpoint_called"] == "PASS"
            assert cl_checks["confirms_no_submit_endpoint_called"] == "PASS"
            assert cl_checks["confirms_no_broker_order_created"] == "PASS"
            assert cl_checks["confirms_no_broker_mutation"] == "PASS"
            assert cl_checks["confirms_order_enablement_still_required"] == "PASS"
            assert cl_checks["confirms_future_real_preflight_required"] == "PASS"
            assert cl_checks["confirms_future_real_approval_required"] == "PASS"
            assert cl_checks["confirms_future_real_submit_required"] == "PASS"

            # workflow_summary
            wf = result["workflow_summary"]
            assert wf["readiness_chain_integrity_ready"] is True
            assert wf["readiness_chain_checkpoint_created"] is True
            assert wf["full_chain_verified"] is True
            assert wf["chain_order_valid"] is True
            assert wf["all_stages_non_executable"] is True
            assert wf["all_stages_advisory_or_readiness_only"] is True
            assert wf["execution_authorized_now_false"] is True
            assert wf["order_enablement_still_required"] is True
            assert wf["no_real_preflight_performed"] is True
            assert wf["no_approval_endpoint_called"] is True
            assert wf["no_submit_endpoint_called"] is True
            assert wf["no_order_path_called"] is True
            assert wf["no_broker_order_created"] is True
            assert wf["no_broker_submission"] is True
            assert wf["no_broker_mutation"] is True
            assert wf["no_h1_seen"] is True
            assert wf["no_order_window_seen"] is True
            assert wf["checklist_complete"] is True

            # Evidence hash
            assert len(result.get("evidence_hash", "")) > 0

            # Guard state
            assert result["guard_state"]["guard_state_clean"] is True
        finally:
            stop_patches(mocks, patches)


# ===========================================================================
# T3: Chain broken when tags missing
# ===========================================================================

class TestChainBroken:
    def test_one_tag_missing_broken_chain(self, clean_git_metadata, clean_worktree,
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
            result = _run_level1_readiness_chain_integrity_checkpoint()
            assert result["diagnosis"] == _PHASE16N_DIAGNOSIS["missing_required_tags"]
            assert result["severity"] == "NO_GO"
            assert result["chain_complete"] is False
            assert result["chain_order_valid"] is False
            ci = result["chain_integrity"]
            assert ci["verdict"] == "CHAIN_BROKEN"
            assert ci["chain_intact"] is False
        finally:
            stop_patches(mocks, patches)

    def test_missing_16g_tag_no_go(self, clean_git_metadata, clean_worktree,
                                    origin_aligned, bridge_health_ok,
                                    positions_flat, alerts_clean, snapshot_ok,
                                    readiness_locked, guard_state_clean, env_safety_locked,
                                    rules_locked, autonomy_level_one, doctor_pass,
                                    kpi_hold_expected, hermes_policy_ok):
        """Missing only the 16G tag while others are present => NO_GO."""
        # All tags except 16G
        tags_16g_missing = {
            "present_count": len(_PHASE16N_REQUIRED_TAGS) - 1,
            "present": [t for t in _PHASE16N_REQUIRED_TAGS
                        if t != "phase16g_level1_proposal_workflow_drill"],
        }
        patches = _build_mocks(
            health=bridge_health_ok, positions=positions_flat,
            alerts=alerts_clean, snapshot=snapshot_ok, readiness=readiness_locked,
            git_metadata=clean_git_metadata, worktree=clean_worktree,
            origin=origin_aligned, tags=tags_16g_missing,
            guard_state_content=guard_state_clean, env_safety=env_safety_locked,
            rules=rules_locked, autonomy=autonomy_level_one,
            doctor=doctor_pass, kpi=kpi_hold_expected, policy=hermes_policy_ok,
        )
        mocks, patches = apply_patches(patches)
        try:
            result = _run_level1_readiness_chain_integrity_checkpoint()
            assert result["diagnosis"] == _PHASE16N_DIAGNOSIS["missing_required_tags"]
            assert result["severity"] == "NO_GO"
        finally:
            stop_patches(mocks, patches)

    def test_missing_16m_tag_no_go(self, clean_git_metadata, clean_worktree,
                                    origin_aligned, bridge_health_ok,
                                    positions_flat, alerts_clean, snapshot_ok,
                                    readiness_locked, guard_state_clean, env_safety_locked,
                                    rules_locked, autonomy_level_one, doctor_pass,
                                    kpi_hold_expected, hermes_policy_ok):
        """Missing only the 16M tag while others are present => NO_GO."""
        tags_16m_missing = {
            "present_count": len(_PHASE16N_REQUIRED_TAGS) - 1,
            "present": [t for t in _PHASE16N_REQUIRED_TAGS
                        if t != "phase16m_level1_execution_readiness_packet_drill"],
        }
        patches = _build_mocks(
            health=bridge_health_ok, positions=positions_flat,
            alerts=alerts_clean, snapshot=snapshot_ok, readiness=readiness_locked,
            git_metadata=clean_git_metadata, worktree=clean_worktree,
            origin=origin_aligned, tags=tags_16m_missing,
            guard_state_content=guard_state_clean, env_safety=env_safety_locked,
            rules=rules_locked, autonomy=autonomy_level_one,
            doctor=doctor_pass, kpi=kpi_hold_expected, policy=hermes_policy_ok,
        )
        mocks, patches = apply_patches(patches)
        try:
            result = _run_level1_readiness_chain_integrity_checkpoint()
            assert result["diagnosis"] == _PHASE16N_DIAGNOSIS["missing_required_tags"]
            assert result["severity"] == "NO_GO"
        finally:
            stop_patches(mocks, patches)


# ===========================================================================
# T4: Prerequisite negatives
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
            result = _run_level1_readiness_chain_integrity_checkpoint()
            assert result["diagnosis"] == _PHASE16N_DIAGNOSIS["missing_required_tags"]
            assert result.get("export_path") is None
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
            result = _run_level1_readiness_chain_integrity_checkpoint()
            assert result["diagnosis"] == _PHASE16N_DIAGNOSIS["dirty_worktree"]
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
            result = _run_level1_readiness_chain_integrity_checkpoint()
            assert result["diagnosis"] == _PHASE16N_DIAGNOSIS["autonomy_not_level1"]
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
            result = _run_level1_readiness_chain_integrity_checkpoint()
            assert result["diagnosis"] == _PHASE16N_DIAGNOSIS["safety_not_locked"]
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
            result = _run_level1_readiness_chain_integrity_checkpoint()
            assert result["diagnosis"] == _PHASE16N_DIAGNOSIS["guard_state_not_clean"]
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
            result = _run_level1_readiness_chain_integrity_checkpoint()
            assert result["diagnosis"] == _PHASE16N_DIAGNOSIS["guard_state_not_clean"]
        finally:
            stop_patches(mocks, patches)


class TestOtherPrerequisites:
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
            result = _run_level1_readiness_chain_integrity_checkpoint()
            assert result["diagnosis"] == _PHASE16N_DIAGNOSIS["positions_not_flat"]
        finally:
            stop_patches(mocks, patches)

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
            result = _run_level1_readiness_chain_integrity_checkpoint()
            assert result["diagnosis"] == _PHASE16N_DIAGNOSIS["monitor_alerts_active"]
        finally:
            stop_patches(mocks, patches)

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
            result = _run_level1_readiness_chain_integrity_checkpoint()
            assert result["diagnosis"] == _PHASE16N_DIAGNOSIS["doctor_not_acceptable"]
        finally:
            stop_patches(mocks, patches)

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
            result = _run_level1_readiness_chain_integrity_checkpoint()
            assert result["diagnosis"] == _PHASE16N_DIAGNOSIS["kpi_not_acceptable"]
        finally:
            stop_patches(mocks, patches)

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
            result = _run_level1_readiness_chain_integrity_checkpoint()
            assert result["diagnosis"] == _PHASE16N_DIAGNOSIS["policy_boundary_missing"]
        finally:
            stop_patches(mocks, patches)

    def test_clean_cycles_mismatch(self, clean_git_metadata, clean_worktree,
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
            result = _run_level1_readiness_chain_integrity_checkpoint()
            assert result["diagnosis"] == _PHASE16N_DIAGNOSIS["clean_cycles_mismatch"]
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
            result = _run_level1_readiness_chain_integrity_checkpoint()
            assert result["diagnosis"] == _PHASE16N_DIAGNOSIS["runtime_not_ready"]
            assert result["severity"] == "NO_GO"
        finally:
            stop_patches(mocks, patches)


# ===========================================================================
# T5: Non-mutation guarantees
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
            result = _run_level1_readiness_chain_integrity_checkpoint()
            assert result["diagnosis"] == _PHASE16N_DIAGNOSIS["ready"]
            assert result["no_broker_mutation"] is True
            assert result["no_order_window_opened"] is True
            assert result["no_h1_seen"] is True
            assert result["no_order_window_seen"] is True
            assert result["h1_token_not_used"] is True
            assert result["no_preflight_endpoint_called"] is True
            assert result["no_approval_endpoint_called"] is True
            assert result["no_submit_endpoint_called"] is True
            assert result["no_order_path_called"] is True
            assert result["promotion_allowed_now"] is False
            assert result["order_enablement_allowed_now"] is False
            # Validate non-actions text
            non_actions = result.get("explicit_non_actions", [])
            assert any("did not call /order/preflight" in a for a in non_actions)
            assert any("did not call /order/approve" in a for a in non_actions)
            assert any("did not call /order/submit" in a for a in non_actions)
            assert any("non-executable" in a.lower() for a in non_actions)
            assert any("advisory" in a.lower() for a in non_actions)
        finally:
            stop_patches(mocks, patches)


# ===========================================================================
# T6: Edge cases
# ===========================================================================

class TestEdgeCases:
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
            result = _run_level1_readiness_chain_integrity_checkpoint()
            assert len(result.get("evidence_hash", "")) > 0
            assert len(result["readiness_chain_checkpoint"].get("checkpoint_hash", "")) > 0
        finally:
            stop_patches(mocks, patches)

    def test_export_path_set(self, clean_git_metadata, clean_worktree,
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
            result = _run_level1_readiness_chain_integrity_checkpoint()
            assert result.get("export_path") is not None
            assert Path(result["export_path"]).exists()
            assert result["readiness_chain_checkpoint"].get("checkpoint_path") is not None
        finally:
            stop_patches(mocks, patches)

    def test_chain_source_customizable(self, clean_git_metadata, clean_worktree,
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
            result = _run_level1_readiness_chain_integrity_checkpoint(
                chain_source="custom_chain"
            )
            assert result["diagnosis"] == _PHASE16N_DIAGNOSIS["ready"]
            assert result["chain_integrity"]["chain_source"] == "custom_chain"
            assert result["readiness_chain_checkpoint"]["checkpoint_source"] == "custom_chain"
        finally:
            stop_patches(mocks, patches)

    def test_workflow_summary_in_no_go(self, clean_git_metadata, clean_worktree,
                                        origin_aligned, one_tag_missing, bridge_health_ok,
                                        positions_flat, alerts_clean, snapshot_ok,
                                        readiness_locked, guard_state_clean, env_safety_locked,
                                        rules_locked, autonomy_level_one, doctor_pass,
                                        kpi_hold_expected, hermes_policy_ok):
        """Workflow summary in NO_GO confirms no real activity happened."""
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
            result = _run_level1_readiness_chain_integrity_checkpoint()
            wf = result["workflow_summary"]
            assert wf["readiness_chain_integrity_ready"] is False
            assert wf["readiness_chain_checkpoint_created"] is False
            assert wf["full_chain_verified"] is False
            assert wf["no_broker_mutation"] is True
            assert wf["no_h1_seen"] is True
            assert wf["no_order_window_seen"] is True
            assert wf["checklist_complete"] is False
        finally:
            stop_patches(mocks, patches)

    def test_integrity_checklist_in_no_go(self, clean_git_metadata, clean_worktree,
                                           origin_aligned, one_tag_missing, bridge_health_ok,
                                           positions_flat, alerts_clean, snapshot_ok,
                                           readiness_locked, guard_state_clean, env_safety_locked,
                                           rules_locked, autonomy_level_one, doctor_pass,
                                           kpi_hold_expected, hermes_policy_ok):
        """Integrity checklist in NO_GO has 19 entries, mostly SKIP/FAIL."""
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
            result = _run_level1_readiness_chain_integrity_checkpoint()
            cl = result["integrity_checklist"]
            assert len(cl) == 19
            statuses = {c["status"] for c in cl}
            assert "FAIL" in statuses  # at least chain present should fail
        finally:
            stop_patches(mocks, patches)
