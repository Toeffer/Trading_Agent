"""Tests for Phase 16M — Level 1 Execution-Readiness Packet Drill (refined spec v2).

All tests are read-only. No broker mutation, no order endpoints,
no /order/preflight, /order/approve, /order/submit, no H1 token usage,
no order window opened, no autonomy level changes.
Every readiness item must declare:
  readiness_packet_only=true
  execution_authorized_now=false
  executable=false
  order_enablement_required=true
  future_order_window_required=true
  future_h1_required=true
  future_real_preflight_required=true
  future_real_approval_required=true
  future_real_submit_required=true
  readiness_status="NOT_READY"
  required_future_steps[] present
  blocking_conditions[] present

Coverage:
  - Command parser registers primary + 3 aliases
  - --help exits quickly
  - JSON stdout pure
  - Export + readiness artifact written
  - Clean runtime => level1_execution_readiness_packet_ok / OK
  - status="readiness_only", all readiness_items[] tagged correctly
  - readiness_checklist present with all 17 confirms
  - execution_readiness_packet key (not execution_readiness)
  - blocked_or_skipped_items[] key (not skipped_items)
  - Mixed/accepted/rejected/deferred all 4 modes
  - Zero candidates => empty packet, OK
  - Missing required tag => NO_GO
  - Dirty worktree => NO_GO
  - Autonomy not level 1 => NO_GO
  - Safety unlocked => NO_GO
  - Bridge disconnected => HOLD
  - Guard not clean => NO_GO
  - Positions not flat => NO_GO
  - Active alerts => NO_GO
  - Doctor/KPI/Policy => NO_GO
  - Clean cycles mismatch => NO_GO
  - Approval packet artifact not found => NO_GO
  - Approval packet not packet_only => NO_GO
  - Approval packet with broker_approval_performed=true => NO_GO
  - Approval packet with executable items => NO_GO
  - Loading prior 16L approval packet artifact
  - Readiness artifact / workflow_summary structure
  - readiness_artifact_hash present
  - Non-mutation guarantees
  - All no_x flags verified
  - Per-item new fields: simulated_preflight_status, readiness_status,
    readiness_notes, required_future_steps[], blocking_conditions[]
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
    _run_level1_execution_readiness_packet_drill,
    _PHASE16M_DIAGNOSIS,
    _PHASE16M_REQUIRED_TAGS,
    _PHASE16M_EXPORT_DIR,
    _PHASE16M_EXPLICIT_NON_ACTIONS,
    _compute_evidence_hash,
    _DECISION_MODE_VALUES,
    OPENCLAW_DIR,
)


# ===========================================================================
# Fixtures
# ===========================================================================

@pytest.fixture
def clean_git_metadata():
    return {"branch": "master", "commit_short": "abc1234",
            "commit": "abc1234abc1234abc1234abc1234abc1234abc",
            "tag": "phase16l_level1_human_approval_packet_drill"}


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
    return {"present_count": len(_PHASE16M_REQUIRED_TAGS),
            "present": list(_PHASE16M_REQUIRED_TAGS)}


@pytest.fixture
def one_tag_missing():
    missing = [_PHASE16M_REQUIRED_TAGS[0]]
    present = list(_PHASE16M_REQUIRED_TAGS[1:])
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


@pytest.fixture
def prior_approval_packet_json():
    """A valid 16L-formatted human approval packet with 2 packet items."""
    return json.dumps({
        "artifact_id": "approval-packet-20260629T120000Z",
        "status": "packet_only",
        "generated_by": "level1-human-approval-packet-drill (Phase 16L)",
        "human_approval_packet": {
            "packet_id": "approval-packet-20260629T120000Z",
            "status": "packet_only",
            "human_packet_only": True,
            "broker_approval_performed": False,
            "approval_endpoint_called": False,
            "h1_token_used": False,
            "executable": False,
            "packet_items_count": 2,
            "packet_items": [
                {"packet_item_id": "packet-001", "source_simulation_item_id": "sim-item-001",
                 "source_plan_item_id": "draft-item-001",
                 "source_proposal_id": "d-001",
                 "symbol": "SPY", "side": "BUY", "quantity": 10,
                 "order_type": "LMT", "time_in_force": "DAY",
                 "simulated_preflight_status": "PASS (simulated)",
                 "human_packet_only": True, "broker_approval_performed": False,
                 "approval_endpoint_called": False, "h1_token_used": False,
                 "executable": False,
                 "rationale": "Core S&P 500", "risk_notes": "Packet item"},
                {"packet_item_id": "packet-002", "source_simulation_item_id": "sim-item-002",
                 "source_plan_item_id": "draft-item-002",
                 "source_proposal_id": "d-002",
                 "symbol": "QQQ", "side": "BUY", "quantity": 20,
                 "order_type": "LMT", "time_in_force": "DAY",
                 "simulated_preflight_status": "PASS (simulated)",
                 "human_packet_only": True, "broker_approval_performed": False,
                 "approval_endpoint_called": False, "h1_token_used": False,
                 "executable": False,
                 "rationale": "Nasdaq-100 growth", "risk_notes": "Packet item"},
            ],
        },
    })


@pytest.fixture
def approval_packet_with_broker_activity_json():
    return json.dumps({
        "artifact_id": "bad-ap",
        "status": "packet_only",
        "human_approval_packet": {
            "packet_id": "bad-ap", "status": "packet_only",
            "human_packet_only": True,
            "broker_approval_performed": True,
            "approval_endpoint_called": False,
            "executable": False,
            "packet_items_count": 1,
            "packet_items": [
                {"packet_item_id": "bad-001", "symbol": "SPY", "side": "BUY",
                 "quantity": 10, "executable": False}
            ],
        },
    })


@pytest.fixture
def approval_packet_executable_item_json():
    return json.dumps({
        "artifact_id": "bad-ap2",
        "status": "packet_only",
        "human_approval_packet": {
            "packet_id": "bad-ap2", "status": "packet_only",
            "human_packet_only": True,
            "broker_approval_performed": False,
            "approval_endpoint_called": False,
            "executable": False,
            "packet_items_count": 1,
            "packet_items": [
                {"packet_item_id": "bad-002", "symbol": "AAPL", "side": "SELL",
                 "quantity": 5, "executable": True,
                 "human_packet_only": True, "broker_approval_performed": False,
                 "approval_endpoint_called": False, "h1_token_used": False}
            ],
        },
    })


@pytest.fixture
def non_packet_only_approval_json():
    return json.dumps({
        "artifact_id": "executed-ap",
        "status": "executed",
        "human_approval_packet": {
            "packet_id": "executed-ap", "status": "executed",
            "packet_items": [],
        },
    })


@pytest.fixture
def approval_packet_with_h1_token_json():
    return json.dumps({
        "artifact_id": "bad-ap-h1",
        "status": "packet_only",
        "human_approval_packet": {
            "packet_id": "bad-ap-h1", "status": "packet_only",
            "human_packet_only": True,
            "broker_approval_performed": False,
            "approval_endpoint_called": False,
            "h1_token_used": True,
            "executable": False,
            "packet_items_count": 1,
            "packet_items": [
                {"packet_item_id": "bad-003", "symbol": "TSLA", "side": "BUY",
                 "quantity": 15, "executable": False}
            ],
        },
    })


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
    patches.append(patch("ibkr_operator._PHASE16M_EXPORT_DIR", tmp_export))
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
                           "level1-execution-readiness-packet-drill", "--help"],
                          capture_output=True, text=True, timeout=10)
        assert r.returncode == 0, f"help failed: {r.stderr}"

    def test_alias_phase16m_works(self):
        import subprocess
        r = subprocess.run([sys.executable, str(BRIDGE_DIR / "ibkr_operator.py"),
                           "phase16m-execution-readiness-packet-drill", "--help"],
                          capture_output=True, text=True, timeout=10)
        assert r.returncode == 0

    def test_alias_level1_execution_readiness_drill_works(self):
        import subprocess
        r = subprocess.run([sys.executable, str(BRIDGE_DIR / "ibkr_operator.py"),
                           "level1-execution-readiness-drill", "--help"],
                          capture_output=True, text=True, timeout=10)
        assert r.returncode == 0

    def test_alias_execution_readiness_packet_drill_works(self):
        import subprocess
        r = subprocess.run([sys.executable, str(BRIDGE_DIR / "ibkr_operator.py"),
                           "execution-readiness-packet-drill", "--help"],
                          capture_output=True, text=True, timeout=10)
        assert r.returncode == 0


# ===========================================================================
# T2: Clean runtime => OK with full field verification
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
            result = _run_level1_execution_readiness_packet_drill(demo_candidates=4, decision_mode="mixed_demo")
            assert result["diagnosis"] == _PHASE16M_DIAGNOSIS["ready"]
            assert result["severity"] == "OK"
            assert result["operator_action_required"] is False
            assert result["promotion_allowed_now"] is False
            assert result["order_enablement_allowed_now"] is False
            assert result["no_broker_mutation"] is True
            assert result["no_order_window_opened"] is True
            assert result["no_h1_seen"] is True
            assert result["no_order_window_seen"] is True
            assert result["h1_token_not_used"] is True
            assert result["no_preflight_endpoint_called"] is True
            assert result["no_approval_endpoint_called"] is True
            assert result["no_submit_endpoint_called"] is True
            assert result["export_path"] is not None
            assert result["readiness_artifact_path"] is not None
            assert len(result.get("readiness_artifact_hash", "")) > 0
            assert result["packet_id"].startswith("execution-readiness-")
            # input_approval_packet
            iap = result["input_approval_packet"]
            assert iap["source"] == "synthesized_internally"
            assert iap["status"] == "packet_only"
            assert iap["human_packet_only"] is True
            assert iap["broker_approval_performed"] is False
            assert len(iap["artifact_hash"]) > 0
            # execution_readiness_packet (NEW KEY NAME)
            assert "execution_readiness_packet" in result
            assert "execution_readiness" not in result  # old name should be gone
            er = result["execution_readiness_packet"]
            assert er["packet_id"].startswith("readiness-packet-")
            assert er["status"] == "readiness_only"
            assert er["readiness_packet_only"] is True
            assert er["execution_authorized_now"] is False
            assert er["executable"] is False
            assert er["broker_order_created"] is False
            assert er["broker_submission_performed"] is False
            assert er["preflight_performed"] is False
            assert er["approval_performed"] is False
            assert er["submit_performed"] is False
            assert er["order_window_opened"] is False
            assert er["h1_token_used"] is False
            assert er["order_enablement_required"] is True
            assert er["future_order_window_required"] is True
            assert er["future_h1_required"] is True
            assert er["future_real_preflight_required"] is True
            assert er["future_real_approval_required"] is True
            assert er["future_real_submit_required"] is True
            assert er["readiness_items_count"] >= 1
            assert er["blocked_items_count"] == 0
            assert er["future_required_path"] == (
                "/order/preflight -> /order/approve -> /order/submit"
            )
            # readiness_checklist
            rc = er.get("readiness_checklist", {})
            assert rc["confirms_level1_only"] is True
            assert rc["confirms_readiness_packet_only"] is True
            assert rc["confirms_not_execution_authorization"] is True
            assert rc["confirms_orders_disabled"] is True
            assert rc["confirms_system_locked"] is True
            assert rc["confirms_no_h1_used"] is True
            assert rc["confirms_no_order_window_opened"] is True
            assert rc["confirms_no_preflight_endpoint_called"] is True
            assert rc["confirms_no_approval_endpoint_called"] is True
            assert rc["confirms_no_submit_endpoint_called"] is True
            assert rc["confirms_no_broker_order_created"] is True
            assert rc["confirms_order_enablement_still_required"] is True
            assert rc["confirms_future_real_preflight_required"] is True
            assert rc["confirms_future_real_approval_required"] is True
            assert rc["confirms_future_real_submit_required"] is True
            assert rc["confirms_future_h1_required"] is True
            assert rc["confirms_future_order_window_required"] is True
            # blocked_or_skipped_items (NEW KEY NAME)
            assert isinstance(er.get("blocked_or_skipped_items"), list)
            assert "skipped_items" not in er  # old name should be gone
            # Every readiness item must have all required flags
            for r in er["readiness_items"]:
                assert "readiness_item_id" in r
                assert "source_packet_item_id" in r
                assert "source_simulation_item_id" in r
                assert "source_plan_item_id" in r
                assert "source_proposal_id" in r
                assert "simulated_preflight_status" in r
                assert "readiness_status" in r
                assert r["readiness_status"] == "NOT_READY"
                assert "readiness_notes" in r
                assert "required_future_steps" in r
                assert isinstance(r["required_future_steps"], list)
                assert len(r["required_future_steps"]) >= 5
                assert "blocking_conditions" in r
                assert isinstance(r["blocking_conditions"], list)
                assert len(r["blocking_conditions"]) >= 5
                assert r["readiness_packet_only"] is True
                assert r["execution_authorized_now"] is False
                assert r["executable"] is False
                assert r["performed"] is False
                assert r["broker_order_id"] is None
                assert r["order_enablement_required"] is True
                assert r["h1_token_used"] is False
                assert r["future_order_window_required"] is True
                assert r["future_h1_required"] is True
                assert r["future_real_preflight_required"] is True
                assert r["future_real_approval_required"] is True
                assert r["future_real_submit_required"] is True
                assert r["future_required_path"] == (
                    "/order/preflight -> /order/approve -> /order/submit"
                )
            # workflow_summary
            ws = result["workflow_summary"]
            assert ws["execution_readiness_packet_ready"] is True
            assert ws["execution_readiness_packet_created"] is True
            assert ws["execution_authorized_now_false"] is True
            assert ws["all_items_readiness_only"] is True
            assert ws["all_items_non_executable"] is True
            assert ws["order_enablement_still_required"] is True
            assert ws["no_real_preflight_performed"] is True
            assert ws["no_approval_endpoint_called"] is True
            assert ws["no_submit_endpoint_called"] is True
            assert ws["no_order_path_called"] is True
            assert ws["no_broker_order_created"] is True
            assert ws["no_broker_submission"] is True
            assert ws["no_h1_seen"] is True
            assert ws["no_order_window_seen"] is True
            assert ws["checklist_complete"] is True
            # packet_path / packet_hash on result
            assert isinstance(result.get("packet_path"), (str, type(None)))
            assert isinstance(result.get("packet_hash"), (str, type(None)))
            # packet_path / packet_hash on execution_readiness_packet
            assert isinstance(er.get("packet_path"), (str, type(None)))
            assert isinstance(er.get("packet_hash"), (str, type(None)))
            # Autonomy
            assert result["autonomy"]["current_level"] == "1"
        finally:
            stop_patches(mocks, patches)


# ===========================================================================
# T3: All 4 decision modes produce correct packets
# ===========================================================================

class TestDecisionModes:
    def test_accept_all_no_empty_packet(self, clean_git_metadata, clean_worktree,
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
            result = _run_level1_execution_readiness_packet_drill(demo_candidates=3, decision_mode="accept_all_demo")
            assert result["diagnosis"] == _PHASE16M_DIAGNOSIS["ready"]
            er = result["execution_readiness_packet"]
            assert er["status"] == "readiness_only"
            assert er["execution_authorized_now"] is False
            assert er["readiness_items_count"] == 3
            assert len(er["readiness_items"]) == 3
            for r in er["readiness_items"]:
                assert r["readiness_packet_only"] is True
                assert r["execution_authorized_now"] is False
                assert r["future_real_submit_required"] is True
                assert r["readiness_status"] == "NOT_READY"
                assert len(r["required_future_steps"]) >= 5
        finally:
            stop_patches(mocks, patches)

    def test_reject_all_empty_packet_ok(self, clean_git_metadata, clean_worktree,
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
            result = _run_level1_execution_readiness_packet_drill(demo_candidates=3, decision_mode="reject_all_demo")
            assert result["diagnosis"] == _PHASE16M_DIAGNOSIS["no_items_to_assess"]
            assert result["severity"] == "OK"
            er = result["execution_readiness_packet"]
            assert er["readiness_items_count"] == 0
            assert er["readiness_items"] == []
            assert er["execution_authorized_now"] is False
        finally:
            stop_patches(mocks, patches)

    def test_defer_all_empty_packet_ok(self, clean_git_metadata, clean_worktree,
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
            result = _run_level1_execution_readiness_packet_drill(demo_candidates=2, decision_mode="defer_all_demo")
            assert result["severity"] == "OK"
            er = result["execution_readiness_packet"]
            assert er["readiness_items_count"] == 0
            assert er["execution_authorized_now"] is False
        finally:
            stop_patches(mocks, patches)


# ===========================================================================
# T4: Loading prior 16L approval packet artifact
# ===========================================================================

class TestPriorApprovalPacketArtifact:
    def test_loads_prior_artifact_from_path(self, clean_git_metadata, clean_worktree,
                                             origin_aligned, all_tags_present, bridge_health_ok,
                                             positions_flat, alerts_clean, snapshot_ok,
                                             readiness_locked, guard_state_clean, env_safety_locked,
                                             rules_locked, autonomy_level_one, doctor_pass,
                                             kpi_hold_expected, hermes_policy_ok,
                                             prior_approval_packet_json):
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
            with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as tf:
                tf.write(prior_approval_packet_json)
                ap_path = tf.name

            result = _run_level1_execution_readiness_packet_drill(approval_packet_path=ap_path)
            assert result["diagnosis"] == _PHASE16M_DIAGNOSIS["ready"]
            iap = result["input_approval_packet"]
            assert iap["source"] == "loaded_from_prior_16l_artifact"
            assert iap["approval_packet_id"] == "approval-packet-20260629T120000Z"
            assert iap["packet_items_count"] == 2
            er = result["execution_readiness_packet"]
            assert er["readiness_items_count"] == 2
            assert er["execution_authorized_now"] is False
            symbols = [r["symbol"] for r in er["readiness_items"]]
            assert "SPY" in symbols
            assert "QQQ" in symbols
            for r in er["readiness_items"]:
                assert r["source_packet_item_id"] in ("packet-001", "packet-002")
                assert r["readiness_packet_only"] is True
                assert r["execution_authorized_now"] is False
                assert r["future_real_submit_required"] is True
                assert r["readiness_status"] == "NOT_READY"
            Path(ap_path).unlink(missing_ok=True)
        finally:
            stop_patches(mocks, patches)


# ===========================================================================
# T5: Approval packet artifact rejection NO_GOs
# ===========================================================================

class TestApprovalPacketRejection:
    def test_nonexistent_artifact_path_no_go(self, clean_git_metadata, clean_worktree,
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
            result = _run_level1_execution_readiness_packet_drill(
                approval_packet_path="/nonexistent/ap.json",
            )
            assert result["diagnosis"] == _PHASE16M_DIAGNOSIS["approval_packet_not_found"]
            assert result["severity"] == "NO_GO"
            assert result["execution_readiness_packet"]["status"] == "blocked"
        finally:
            stop_patches(mocks, patches)

    def test_non_packet_only_approval_no_go(self, clean_git_metadata, clean_worktree,
                                             origin_aligned, all_tags_present, bridge_health_ok,
                                             positions_flat, alerts_clean, snapshot_ok,
                                             readiness_locked, guard_state_clean, env_safety_locked,
                                             rules_locked, autonomy_level_one, doctor_pass,
                                             kpi_hold_expected, hermes_policy_ok,
                                             non_packet_only_approval_json):
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
            with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as tf:
                tf.write(non_packet_only_approval_json)
                ap_path = tf.name

            result = _run_level1_execution_readiness_packet_drill(approval_packet_path=ap_path)
            assert result["diagnosis"] == _PHASE16M_DIAGNOSIS["approval_packet_not_packet_only"]
            Path(ap_path).unlink(missing_ok=True)
        finally:
            stop_patches(mocks, patches)

    def test_parse_error_approval_no_go(self, clean_git_metadata, clean_worktree,
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
            with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as tf:
                tf.write("not valid {{{ json")
                ap_path = tf.name

            result = _run_level1_execution_readiness_packet_drill(approval_packet_path=ap_path)
            assert result["diagnosis"] == _PHASE16M_DIAGNOSIS["approval_packet_not_found"]
            Path(ap_path).unlink(missing_ok=True)
        finally:
            stop_patches(mocks, patches)

    def test_broker_activity_no_go(self, clean_git_metadata, clean_worktree,
                                    origin_aligned, all_tags_present, bridge_health_ok,
                                    positions_flat, alerts_clean, snapshot_ok,
                                    readiness_locked, guard_state_clean, env_safety_locked,
                                    rules_locked, autonomy_level_one, doctor_pass,
                                    kpi_hold_expected, hermes_policy_ok,
                                    approval_packet_with_broker_activity_json):
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
            with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as tf:
                tf.write(approval_packet_with_broker_activity_json)
                ap_path = tf.name

            result = _run_level1_execution_readiness_packet_drill(approval_packet_path=ap_path)
            assert result["diagnosis"] == _PHASE16M_DIAGNOSIS["approval_packet_has_broker_activity"]
            Path(ap_path).unlink(missing_ok=True)
        finally:
            stop_patches(mocks, patches)

    def test_executable_items_no_go(self, clean_git_metadata, clean_worktree,
                                     origin_aligned, all_tags_present, bridge_health_ok,
                                     positions_flat, alerts_clean, snapshot_ok,
                                     readiness_locked, guard_state_clean, env_safety_locked,
                                     rules_locked, autonomy_level_one, doctor_pass,
                                     kpi_hold_expected, hermes_policy_ok,
                                     approval_packet_executable_item_json):
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
            with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as tf:
                tf.write(approval_packet_executable_item_json)
                ap_path = tf.name

            result = _run_level1_execution_readiness_packet_drill(approval_packet_path=ap_path)
            assert result["diagnosis"] == _PHASE16M_DIAGNOSIS["approval_packet_has_executable_items"]
            Path(ap_path).unlink(missing_ok=True)
        finally:
            stop_patches(mocks, patches)

    def test_h1_token_used_no_go(self, clean_git_metadata, clean_worktree,
                                  origin_aligned, all_tags_present, bridge_health_ok,
                                  positions_flat, alerts_clean, snapshot_ok,
                                  readiness_locked, guard_state_clean, env_safety_locked,
                                  rules_locked, autonomy_level_one, doctor_pass,
                                  kpi_hold_expected, hermes_policy_ok,
                                  approval_packet_with_h1_token_json):
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
            with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as tf:
                tf.write(approval_packet_with_h1_token_json)
                ap_path = tf.name

            result = _run_level1_execution_readiness_packet_drill(approval_packet_path=ap_path)
            assert result["diagnosis"] == _PHASE16M_DIAGNOSIS["approval_packet_has_broker_activity"]
            Path(ap_path).unlink(missing_ok=True)
        finally:
            stop_patches(mocks, patches)


# ===========================================================================
# T6: Prerequisite negatives
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
            result = _run_level1_execution_readiness_packet_drill()
            assert result["diagnosis"] == _PHASE16M_DIAGNOSIS["missing_required_tags"]
            assert result["severity"] == "NO_GO"
            assert result["execution_readiness_packet"]["status"] == "blocked"
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
            result = _run_level1_execution_readiness_packet_drill()
            assert result["diagnosis"] == _PHASE16M_DIAGNOSIS["dirty_worktree"]
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
            result = _run_level1_execution_readiness_packet_drill()
            assert result["diagnosis"] == _PHASE16M_DIAGNOSIS["autonomy_not_level1"]
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
            result = _run_level1_execution_readiness_packet_drill()
            assert result["diagnosis"] == _PHASE16M_DIAGNOSIS["safety_not_locked"]
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
            result = _run_level1_execution_readiness_packet_drill()
            assert result["diagnosis"] == _PHASE16M_DIAGNOSIS["guard_state_not_clean"]
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
            result = _run_level1_execution_readiness_packet_drill()
            assert result["diagnosis"] == _PHASE16M_DIAGNOSIS["guard_state_not_clean"]
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
            result = _run_level1_execution_readiness_packet_drill()
            assert result["diagnosis"] == _PHASE16M_DIAGNOSIS["positions_not_flat"]
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
            result = _run_level1_execution_readiness_packet_drill()
            assert result["diagnosis"] == _PHASE16M_DIAGNOSIS["monitor_alerts_active"]
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
            result = _run_level1_execution_readiness_packet_drill()
            assert result["diagnosis"] == _PHASE16M_DIAGNOSIS["doctor_not_acceptable"]
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
            result = _run_level1_execution_readiness_packet_drill()
            assert result["diagnosis"] == _PHASE16M_DIAGNOSIS["kpi_not_acceptable"]
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
            result = _run_level1_execution_readiness_packet_drill()
            assert result["diagnosis"] == _PHASE16M_DIAGNOSIS["policy_boundary_missing"]
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
            result = _run_level1_execution_readiness_packet_drill()
            assert result["diagnosis"] == _PHASE16M_DIAGNOSIS["clean_cycles_mismatch"]
        finally:
            stop_patches(mocks, patches)

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
            result = _run_level1_execution_readiness_packet_drill()
            assert result["diagnosis"] == _PHASE16M_DIAGNOSIS["runtime_not_ready"]
            assert result["severity"] == "HOLD"
        finally:
            stop_patches(mocks, patches)


# ===========================================================================
# T7: Readiness artifact structure
# ===========================================================================

class TestReadinessArtifact:
    def test_readiness_artifact_complete(self, clean_git_metadata, clean_worktree,
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
            result = _run_level1_execution_readiness_packet_drill(demo_candidates=3)
            ra = result["readiness_artifact"]
            assert ra["status"] == "readiness_only"
            assert ra["generated_by"] == "level1-execution-readiness-packet-drill (Phase 16M)"
            assert "input_approval_packet" in ra
            assert "execution_readiness_packet" in ra
            er = ra["execution_readiness_packet"]
            assert er["readiness_packet_only"] is True
            assert er["execution_authorized_now"] is False
            assert er["preflight_performed"] is False
            assert er["approval_performed"] is False
            assert er["submit_performed"] is False
            assert result.get("readiness_artifact_hash") is not None
            assert len(result["readiness_artifact_hash"]) > 0
        finally:
            stop_patches(mocks, patches)

    def test_readiness_artifact_file_written(self, clean_git_metadata, clean_worktree,
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
            result = _run_level1_execution_readiness_packet_drill(demo_candidates=2)
            ra_path = result.get("readiness_artifact_path")
            assert ra_path is not None
            assert Path(ra_path).exists()
            with open(ra_path) as f:
                loaded = json.load(f)
            assert loaded["status"] == "readiness_only"
            assert loaded["execution_readiness_packet"]["execution_authorized_now"] is False
            assert loaded["execution_readiness_packet"]["readiness_packet_only"] is True
        finally:
            stop_patches(mocks, patches)


# ===========================================================================
# T8: Non-mutation guarantees
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
            result = _run_level1_execution_readiness_packet_drill()
            assert result["diagnosis"] == _PHASE16M_DIAGNOSIS["ready"]
            assert result["no_broker_mutation"] is True
            assert result["no_order_window_opened"] is True
            assert result["no_h1_seen"] is True
            assert result["no_order_window_seen"] is True
            assert result["h1_token_not_used"] is True
            assert result["no_preflight_endpoint_called"] is True
            assert result["no_approval_endpoint_called"] is True
            assert result["no_submit_endpoint_called"] is True
            assert result["promotion_allowed_now"] is False
            assert result["order_enablement_allowed_now"] is False
            rw = result["readiness_workflow"]
            assert rw["preflight_performed"] is False
            assert rw["approval_performed"] is False
            assert rw["submit_performed"] is False
            assert rw["h1_token_used"] is False
            assert rw["any_real_broker_activity"] is False
            ws = result["workflow_summary"]
            assert ws["no_real_preflight_performed"] is True
            assert ws["no_approval_endpoint_called"] is True
            assert ws["no_submit_endpoint_called"] is True
            assert ws["no_broker_order_created"] is True
            assert ws["no_broker_submission"] is True
            assert ws["execution_authorized_now_false"] is True
            assert ws["checklist_complete"] is True
            non_actions = result.get("explicit_non_actions", [])
            assert any("did not call /order/preflight" in a for a in non_actions)
            assert any("did not call /order/approve" in a for a in non_actions)
            assert any("did not call /order/submit" in a for a in non_actions)
            assert any("execution_authorized_now=false" in a for a in non_actions)
            assert any("not execution authorization" in a.lower() for a in non_actions)
            assert any("Chris must manually" in a for a in non_actions)
        finally:
            stop_patches(mocks, patches)


# ===========================================================================
# T9: Edge cases
# ===========================================================================

class TestEdgeCases:
    def test_zero_candidates_produces_empty_packet_ok(self, clean_git_metadata, clean_worktree,
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
            result = _run_level1_execution_readiness_packet_drill(demo_candidates=0)
            assert result["severity"] == "OK"
            assert result["diagnosis"] == _PHASE16M_DIAGNOSIS["no_items_to_assess"]
            er = result["execution_readiness_packet"]
            assert er["readiness_items_count"] == 0
            assert er["readiness_items"] == []
            assert er["readiness_packet_only"] is True
            assert er["execution_authorized_now"] is False
            assert er["preflight_performed"] is False
            assert er["approval_performed"] is False
            assert er["submit_performed"] is False
            assert er["h1_token_used"] is False
            assert er["status"] == "readiness_only"
            assert er["executable"] is False
        finally:
            stop_patches(mocks, patches)

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
            result = _run_level1_execution_readiness_packet_drill()
            assert len(result.get("evidence_hash", "")) > 0
            assert len(result.get("readiness_artifact_hash", "")) > 0
        finally:
            stop_patches(mocks, patches)

    def test_export_and_artifact_paths_set(self, clean_git_metadata, clean_worktree,
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
            result = _run_level1_execution_readiness_packet_drill()
            assert result.get("export_path") is not None
            assert result.get("readiness_artifact_path") is not None
            assert Path(result["export_path"]).exists()
            assert Path(result["readiness_artifact_path"]).exists()
        finally:
            stop_patches(mocks, patches)

    def test_reviewer_customizable(self, clean_git_metadata, clean_worktree,
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
            result = _run_level1_execution_readiness_packet_drill(
                demo_candidates=3, reviewer="CustomReviewer"
            )
            assert result["diagnosis"] == _PHASE16M_DIAGNOSIS["ready"]
            er = result["execution_readiness_packet"]
            assert er["reviewer"] == "CustomReviewer"
        finally:
            stop_patches(mocks, patches)

    def test_packet_source_customizable(self, clean_git_metadata, clean_worktree,
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
            result = _run_level1_execution_readiness_packet_drill(
                demo_candidates=3, packet_source="custom_source"
            )
            assert result["diagnosis"] == _PHASE16M_DIAGNOSIS["ready"]
            er = result["execution_readiness_packet"]
            assert er["packet_source"] == "custom_source"
        finally:
            stop_patches(mocks, patches)

    def test_readiness_checklist_all_confirms(self, clean_git_metadata, clean_worktree,
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
            result = _run_level1_execution_readiness_packet_drill(demo_candidates=2)
            er = result["execution_readiness_packet"]
            rc = er.get("readiness_checklist", {})
            required_confirms = [
                "confirms_level1_only", "confirms_readiness_packet_only",
                "confirms_not_execution_authorization",
                "confirms_orders_disabled", "confirms_system_locked",
                "confirms_no_h1_used", "confirms_no_order_window_opened",
                "confirms_no_preflight_endpoint_called",
                "confirms_no_approval_endpoint_called",
                "confirms_no_submit_endpoint_called",
                "confirms_no_broker_order_created",
                "confirms_order_enablement_still_required",
                "confirms_future_real_preflight_required",
                "confirms_future_real_approval_required",
                "confirms_future_real_submit_required",
                "confirms_future_h1_required",
                "confirms_future_order_window_required",
            ]
            for cf in required_confirms:
                assert rc.get(cf) is True, f"Missing checklist item: {cf}"
            # Verify count matches spec (17 items)
            assert len(rc) == 17, f"Expected 17 checklist items, got {len(rc)}"
        finally:
            stop_patches(mocks, patches)
