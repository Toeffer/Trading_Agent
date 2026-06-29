"""Tests for Phase 16L — Level 1 Human Approval Packet Drill (expanded spec).

All tests are read-only. No broker mutation, no order endpoints,
no /order/approve call, no H1 token usage, no autonomy level changes.
Every packet item must declare human_packet_only=true,
broker_approval_performed=false, h1_token_used=false,
future_real_approval_required=true, future_order_window_required=true.

Coverage:
  - Command parser registers primary + 3 aliases
  - --help exits quickly
  - JSON stdout pure
  - Export written
  - Packet artifact written
  - Clean runtime => level1_human_approval_packet_ok / OK
  - status="packet_only", all packet_items[] tagged correctly
  - approval_checklist present with all confirms
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
  - Dossier artifact not found => NO_GO
  - Dossier not simulation_only => NO_GO
  - Dossier artifact unparseable => NO_GO
  - real_preflight_performed=true => NO_GO
  - preflight_endpoint_called=true => NO_GO
  - Loading prior 16K dossier artifact
  - Packet artifact / workflow_summary structure
  - packet_artifact_hash present
  - Non-mutation guarantees
  - All no_x flags verified
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
    _run_level1_human_approval_packet_drill,
    _PHASE16L_DIAGNOSIS,
    _PHASE16L_REQUIRED_TAGS,
    _PHASE16L_EXPORT_DIR,
    _PHASE16L_EXPLICIT_NON_ACTIONS,
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
            "tag": "phase16k_level1_preflight_simulation_dossier"}


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
    return {"present_count": len(_PHASE16L_REQUIRED_TAGS),
            "present": list(_PHASE16L_REQUIRED_TAGS)}


@pytest.fixture
def one_tag_missing():
    missing = [_PHASE16L_REQUIRED_TAGS[0]]
    present = list(_PHASE16L_REQUIRED_TAGS[1:])
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
def prior_dossier_artifact_json():
    """A valid 16K-formatted simulation dossier with 2 simulated items."""
    return json.dumps({
        "artifact_id": "preflight-sim-20260627T120000Z",
        "status": "simulation_only",
        "generated_by": "level1-preflight-simulation-dossier (Phase 16K)",
        "preflight_simulation": {
            "simulation_id": "preflight-sim-20260627T120000Z",
            "status": "simulation_only",
            "simulated_preflight_only": True,
            "real_preflight_performed": False,
            "preflight_endpoint_called": False,
            "simulated_items_count": 2,
            "simulated_items": [
                {"simulation_item_id": "sim-item-001", "source_proposal_id": "d-001",
                 "source_plan_item_id": "draft-item-001",
                 "symbol": "SPY", "side": "BUY", "quantity": 10,
                 "order_type": "LMT", "time_in_force": "DAY", "limit_price": None,
                 "rationale": "Core S&P 500", "risk_notes": "Simulated item",
                 "simulated_preflight_only": True,
                 "real_preflight_performed": False,
                 "simulated_preflight_status": "PASS (simulated)",
                 "simulated_checks": [
                     {"check": "margin", "status": "PASS", "detail": "Deterministic local simulation"},
                     {"check": "contract", "status": "PASS", "detail": "Deterministic local simulation"},
                     {"check": "risk", "status": "PASS", "detail": "Deterministic local simulation"},
                     {"check": "compliance", "status": "PASS", "detail": "Deterministic local simulation"},
                 ],
                 "executable": False},
                {"simulation_item_id": "sim-item-002", "source_proposal_id": "d-002",
                 "source_plan_item_id": "draft-item-002",
                 "symbol": "QQQ", "side": "BUY", "quantity": 20,
                 "order_type": "LMT", "time_in_force": "DAY", "limit_price": None,
                 "rationale": "Nasdaq-100 growth", "risk_notes": "Simulated item",
                 "simulated_preflight_only": True,
                 "real_preflight_performed": False,
                 "simulated_preflight_status": "PASS (simulated)",
                 "simulated_checks": [
                     {"check": "margin", "status": "PASS", "detail": "Deterministic local simulation"},
                     {"check": "contract", "status": "PASS", "detail": "Deterministic local simulation"},
                     {"check": "risk", "status": "PASS", "detail": "Deterministic local simulation"},
                     {"check": "compliance", "status": "PASS", "detail": "Deterministic local simulation"},
                 ],
                 "executable": False},
            ],
        },
    })


@pytest.fixture
def non_sim_only_dossier_json():
    return json.dumps({
        "artifact_id": "bad-dossier",
        "status": "executed",
        "preflight_simulation": {"simulated_items": []},
    })


@pytest.fixture
def dossier_with_real_preflight_json():
    return json.dumps({
        "artifact_id": "bad-dossier",
        "status": "simulation_only",
        "preflight_simulation": {
            "status": "simulation_only",
            "real_preflight_performed": True,
            "preflight_endpoint_called": True,
            "simulated_items": [
                {"simulation_item_id": "sim-bad-001", "symbol": "SPY", "side": "BUY",
                 "quantity": 10, "executable": False}
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
    patches.append(patch("ibkr_operator._PHASE16L_EXPORT_DIR", tmp_export))
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
                           "level1-human-approval-packet-drill", "--help"],
                          capture_output=True, text=True, timeout=10)
        assert r.returncode == 0, f"help failed: {r.stderr}"

    def test_alias_phase16l_works(self):
        import subprocess
        r = subprocess.run([sys.executable, str(BRIDGE_DIR / "ibkr_operator.py"),
                           "phase16l-human-approval-packet-drill", "--help"],
                          capture_output=True, text=True, timeout=10)
        assert r.returncode == 0

    def test_alias_level1_approval_packet_drill_works(self):
        import subprocess
        r = subprocess.run([sys.executable, str(BRIDGE_DIR / "ibkr_operator.py"),
                           "level1-approval-packet-drill", "--help"],
                          capture_output=True, text=True, timeout=10)
        assert r.returncode == 0

    def test_alias_human_approval_packet_drill_works(self):
        import subprocess
        r = subprocess.run([sys.executable, str(BRIDGE_DIR / "ibkr_operator.py"),
                           "human-approval-packet-drill", "--help"],
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
            result = _run_level1_human_approval_packet_drill(demo_candidates=4, decision_mode="mixed_demo")
            assert result["diagnosis"] == _PHASE16L_DIAGNOSIS["ready"]
            assert result["severity"] == "OK"
            assert result["operator_action_required"] is False
            assert result["promotion_allowed_now"] is False
            assert result["order_enablement_allowed_now"] is False
            assert result["no_broker_mutation"] is True
            assert result["no_order_window_opened"] is True
            assert result["no_h1_seen"] is True
            assert result["no_order_window_seen"] is True
            assert result["h1_token_not_used"] is True
            assert result["no_approval_endpoint_called"] is True
            assert result["export_path"] is not None
            assert result["packet_artifact_path"] is not None
            assert len(result.get("packet_artifact_hash", "")) > 0
            assert result["packet_id"].startswith("human-approval-packet-")
            # input_preflight_dossier
            ipd = result["input_preflight_dossier"]
            assert ipd["source"] == "synthesized_internally"
            assert ipd["status"] == "simulation_only"
            assert ipd["simulation_only"] is True
            assert ipd["real_preflight_performed"] is False
            assert ipd["preflight_endpoint_called"] is False
            assert len(ipd["artifact_hash"]) > 0
            # human_approval_packet
            hap = result["human_approval_packet"]
            assert hap["packet_id"].startswith("approval-packet-")
            assert hap["status"] == "packet_only"
            assert hap["human_packet_only"] is True
            assert hap["broker_approval_performed"] is False
            assert hap["h1_token_used"] is False
            assert hap["approval_endpoint_called"] is False
            assert hap["executable"] is False
            assert hap["future_real_approval_required"] is True
            assert hap["future_real_preflight_required"] is True
            assert hap["requires_future_order_window"] is True
            assert hap["requires_future_h1"] is True
            assert hap["requires_future_chris_approval"] is True
            assert hap["future_required_path"] == "/order/preflight -> /order/approve -> /order/submit"
            assert hap["reviewer"] == "Chris"
            assert hap["signature_required"] is True
            assert hap["packet_items_count"] >= 1
            assert hap["blocked_items_count"] == 0
            # approval_checklist
            ac = hap.get("approval_checklist", {})
            assert ac["confirms_level1_only"] is True
            assert ac["confirms_packet_only"] is True
            assert ac["confirms_not_broker_approval"] is True
            assert ac["confirms_orders_disabled"] is True
            assert ac["confirms_system_locked"] is True
            assert ac["confirms_no_h1_used"] is True
            assert ac["confirms_no_order_window_opened"] is True
            assert ac["confirms_no_approval_endpoint_called"] is True
            assert ac["confirms_no_submit_endpoint_called"] is True
            assert ac["confirms_no_broker_order_created"] is True
            assert ac["confirms_future_real_preflight_required"] is True
            assert ac["confirms_future_h1_required"] is True
            assert ac["confirms_future_order_window_required"] is True
            assert ac["requires_chris_accept_or_reject"] is True
            # skipped_items in hap
            assert isinstance(hap.get("skipped_items"), list)
            # Every packet item must have all required flags
            for p in hap["packet_items"]:
                assert "packet_item_id" in p
                assert "source_simulation_item_id" in p
                assert "source_plan_item_id" in p
                assert "source_proposal_id" in p
                assert "source_dossier_id" in p
                assert "approval_question" in p
                assert "operator_notes" in p
                assert "simulated_preflight_status" in p
                assert p["human_packet_only"] is True
                assert p["broker_approval_performed"] is False
                assert p["h1_token_used"] is False
                assert p["approval_endpoint_called"] is False
                assert p["future_real_approval_required"] is True
                assert p["future_real_preflight_required"] is True
                assert p["requires_future_order_window"] is True
                assert p["requires_future_h1"] is True
                assert p["requires_future_chris_approval"] is True
                assert p["executable"] is False
                assert p["performed"] is False
                assert p["broker_order_id"] is None
                assert "risk_notes" in p
                assert p["future_required_path"] == "/order/preflight -> /order/approve -> /order/submit"
            # workflow_summary
            ws = result["workflow_summary"]
            assert ws["human_approval_packet_ready"] is True
            assert ws["all_items_packet_only"] is True
            assert ws["all_items_non_executable"] is True
            assert ws["no_real_preflight_performed"] is True
            assert ws["no_approval_endpoint_called"] is True
            assert ws["no_order_path_called"] is True
            assert ws["no_broker_approval"] is True
            assert ws["no_broker_order_created"] is True
            assert ws["no_broker_submission"] is True
            assert ws["no_h1_seen"] is True
            assert ws["no_order_window_seen"] is True
            assert ws["checklist_complete"] is True
            # packet_path and packet_hash on result
            assert isinstance(result.get("packet_path"), (str, type(None)))
            assert isinstance(result.get("packet_hash"), (str, type(None)))
            # approval_packet_path / approval_packet_hash on hap
            assert isinstance(hap.get("approval_packet_path"), (str, type(None)))
            assert isinstance(hap.get("approval_packet_hash"), (str, type(None)))
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
            result = _run_level1_human_approval_packet_drill(demo_candidates=3, decision_mode="accept_all_demo")
            assert result["diagnosis"] == _PHASE16L_DIAGNOSIS["ready"]
            hap = result["human_approval_packet"]
            assert hap["status"] == "packet_only"
            assert hap["packet_items_count"] == 3
            assert len(hap["packet_items"]) == 3
            for p in hap["packet_items"]:
                assert p["human_packet_only"] is True
                assert p["broker_approval_performed"] is False
                assert p["future_real_approval_required"] is True
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
            result = _run_level1_human_approval_packet_drill(demo_candidates=3, decision_mode="reject_all_demo")
            assert result["diagnosis"] == _PHASE16L_DIAGNOSIS["no_items_to_approve"]
            assert result["severity"] == "OK"
            hap = result["human_approval_packet"]
            assert hap["packet_items_count"] == 0
            assert hap["packet_items"] == []
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
            result = _run_level1_human_approval_packet_drill(demo_candidates=2, decision_mode="defer_all_demo")
            assert result["severity"] == "OK"
            hap = result["human_approval_packet"]
            assert hap["packet_items_count"] == 0
        finally:
            stop_patches(mocks, patches)


# ===========================================================================
# T4: Loading prior 16K dossier artifact
# ===========================================================================

class TestPriorDossierArtifact:
    def test_loads_prior_artifact_from_path(self, clean_git_metadata, clean_worktree,
                                             origin_aligned, all_tags_present, bridge_health_ok,
                                             positions_flat, alerts_clean, snapshot_ok,
                                             readiness_locked, guard_state_clean, env_safety_locked,
                                             rules_locked, autonomy_level_one, doctor_pass,
                                             kpi_hold_expected, hermes_policy_ok,
                                             prior_dossier_artifact_json):
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
                tf.write(prior_dossier_artifact_json)
                ds_path = tf.name

            result = _run_level1_human_approval_packet_drill(preflight_dossier_path=ds_path)
            assert result["diagnosis"] == _PHASE16L_DIAGNOSIS["ready"]
            ipd = result["input_preflight_dossier"]
            assert ipd["source"] == "loaded_from_prior_16k_artifact"
            assert ipd["dossier_id"] == "preflight-sim-20260627T120000Z"
            assert ipd["simulated_items_count"] == 2
            hap = result["human_approval_packet"]
            assert hap["packet_items_count"] == 2
            symbols = [p["symbol"] for p in hap["packet_items"]]
            assert "SPY" in symbols
            assert "QQQ" in symbols
            for p in hap["packet_items"]:
                assert p["source_simulation_item_id"] in ("sim-item-001", "sim-item-002")
                assert p["human_packet_only"] is True
                assert p["broker_approval_performed"] is False
            Path(ds_path).unlink(missing_ok=True)
        finally:
            stop_patches(mocks, patches)


# ===========================================================================
# T5: Dossier artifact rejection NO_GOs
# ===========================================================================

class TestDossierArtifactRejection:
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
            result = _run_level1_human_approval_packet_drill(
                preflight_dossier_path="/nonexistent/dossier.json",
            )
            assert result["diagnosis"] == _PHASE16L_DIAGNOSIS["dossier_not_found"]
            assert result["severity"] == "NO_GO"
            assert result["human_approval_packet"]["status"] == "blocked"
        finally:
            stop_patches(mocks, patches)

    def test_non_sim_only_dossier_no_go(self, clean_git_metadata, clean_worktree,
                                         origin_aligned, all_tags_present, bridge_health_ok,
                                         positions_flat, alerts_clean, snapshot_ok,
                                         readiness_locked, guard_state_clean, env_safety_locked,
                                         rules_locked, autonomy_level_one, doctor_pass,
                                         kpi_hold_expected, hermes_policy_ok,
                                         non_sim_only_dossier_json):
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
                tf.write(non_sim_only_dossier_json)
                ds_path = tf.name

            result = _run_level1_human_approval_packet_drill(preflight_dossier_path=ds_path)
            assert result["diagnosis"] == _PHASE16L_DIAGNOSIS["dossier_not_simulation_only"]
            Path(ds_path).unlink(missing_ok=True)
        finally:
            stop_patches(mocks, patches)

    def test_parse_error_dossier_no_go(self, clean_git_metadata, clean_worktree,
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
                ds_path = tf.name

            result = _run_level1_human_approval_packet_drill(preflight_dossier_path=ds_path)
            assert result["diagnosis"] == _PHASE16L_DIAGNOSIS["dossier_not_found"]
            Path(ds_path).unlink(missing_ok=True)
        finally:
            stop_patches(mocks, patches)

    def test_real_preflight_performed_no_go(self, clean_git_metadata, clean_worktree,
                                             origin_aligned, all_tags_present, bridge_health_ok,
                                             positions_flat, alerts_clean, snapshot_ok,
                                             readiness_locked, guard_state_clean, env_safety_locked,
                                             rules_locked, autonomy_level_one, doctor_pass,
                                             kpi_hold_expected, hermes_policy_ok,
                                             dossier_with_real_preflight_json):
        """Dossier with real_preflight_performed=true must be rejected."""
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
                tf.write(dossier_with_real_preflight_json)
                ds_path = tf.name

            result = _run_level1_human_approval_packet_drill(preflight_dossier_path=ds_path)
            assert result["diagnosis"] == _PHASE16L_DIAGNOSIS["dossier_has_real_preflight"]
            Path(ds_path).unlink(missing_ok=True)
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
            result = _run_level1_human_approval_packet_drill()
            assert result["diagnosis"] == _PHASE16L_DIAGNOSIS["missing_required_tags"]
            assert result["severity"] == "NO_GO"
            assert result["human_approval_packet"]["status"] == "blocked"
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
            result = _run_level1_human_approval_packet_drill()
            assert result["diagnosis"] == _PHASE16L_DIAGNOSIS["dirty_worktree"]
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
            result = _run_level1_human_approval_packet_drill()
            assert result["diagnosis"] == _PHASE16L_DIAGNOSIS["autonomy_not_level1"]
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
            result = _run_level1_human_approval_packet_drill()
            assert result["diagnosis"] == _PHASE16L_DIAGNOSIS["safety_not_locked"]
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
            result = _run_level1_human_approval_packet_drill()
            assert result["diagnosis"] == _PHASE16L_DIAGNOSIS["guard_state_not_clean"]
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
            result = _run_level1_human_approval_packet_drill()
            assert result["diagnosis"] == _PHASE16L_DIAGNOSIS["positions_not_flat"]
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
            result = _run_level1_human_approval_packet_drill()
            assert result["diagnosis"] == _PHASE16L_DIAGNOSIS["monitor_alerts_active"]
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
            result = _run_level1_human_approval_packet_drill()
            assert result["diagnosis"] == _PHASE16L_DIAGNOSIS["doctor_not_acceptable"]
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
            result = _run_level1_human_approval_packet_drill()
            assert result["diagnosis"] == _PHASE16L_DIAGNOSIS["kpi_not_acceptable"]
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
            result = _run_level1_human_approval_packet_drill()
            assert result["diagnosis"] == _PHASE16L_DIAGNOSIS["policy_boundary_missing"]
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
            result = _run_level1_human_approval_packet_drill()
            assert result["diagnosis"] == _PHASE16L_DIAGNOSIS["clean_cycles_mismatch"]
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
            result = _run_level1_human_approval_packet_drill()
            assert result["diagnosis"] == _PHASE16L_DIAGNOSIS["runtime_not_ready"]
            assert result["severity"] == "HOLD"
        finally:
            stop_patches(mocks, patches)


# ===========================================================================
# T7: Packet artifact structure
# ===========================================================================

class TestPacketArtifact:
    def test_packet_artifact_complete(self, clean_git_metadata, clean_worktree,
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
            result = _run_level1_human_approval_packet_drill(demo_candidates=3)
            pa = result["packet_artifact"]
            assert pa["status"] == "packet_only"
            assert pa["generated_by"] == "level1-human-approval-packet-drill (Phase 16L)"
            assert "input_preflight_dossier" in pa
            assert "human_approval_packet" in pa
            assert pa["human_approval_packet"]["human_packet_only"] is True
            assert pa["human_approval_packet"]["broker_approval_performed"] is False
            assert result.get("packet_artifact_hash") is not None
            assert len(result["packet_artifact_hash"]) > 0
        finally:
            stop_patches(mocks, patches)

    def test_packet_artifact_file_written(self, clean_git_metadata, clean_worktree,
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
            result = _run_level1_human_approval_packet_drill(demo_candidates=2)
            pa_path = result.get("packet_artifact_path")
            assert pa_path is not None
            assert Path(pa_path).exists()
            with open(pa_path) as f:
                loaded = json.load(f)
            assert loaded["status"] == "packet_only"
            assert loaded["human_approval_packet"]["human_packet_only"] is True
            assert loaded["human_approval_packet"]["broker_approval_performed"] is False
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
            result = _run_level1_human_approval_packet_drill()
            assert result["diagnosis"] == _PHASE16L_DIAGNOSIS["ready"]
            assert result["no_broker_mutation"] is True
            assert result["no_order_window_opened"] is True
            assert result["no_h1_seen"] is True
            assert result["no_order_window_seen"] is True
            assert result["h1_token_not_used"] is True
            assert result["no_approval_endpoint_called"] is True
            assert result["promotion_allowed_now"] is False
            assert result["order_enablement_allowed_now"] is False
            aw = result["approval_workflow"]
            assert aw["broker_approval_performed"] is False
            assert aw["approval_endpoint_called"] is False
            assert aw["h1_token_used"] is False
            assert aw["any_real_broker_activity"] is False
            ws = result["workflow_summary"]
            assert ws["no_broker_approval"] is True
            assert ws["no_approval_endpoint_called"] is True
            assert ws["no_broker_order_created"] is True
            assert ws["no_broker_submission"] is True
            assert ws["no_real_preflight_performed"] is True
            assert ws["checklist_complete"] is True
            non_actions = result.get("explicit_non_actions", [])
            assert any("did not call /order/approve" in a for a in non_actions)
            assert any("did not approve with broker" in a for a in non_actions)
            assert any("did not submit" in a for a in non_actions)
            assert any("did not create a broker order" in a for a in non_actions)
            assert any("Chris must manually sign" in a for a in non_actions)
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
            result = _run_level1_human_approval_packet_drill(demo_candidates=0)
            assert result["severity"] == "OK"
            assert result["diagnosis"] == _PHASE16L_DIAGNOSIS["no_items_to_approve"]
            hap = result["human_approval_packet"]
            assert hap["packet_items_count"] == 0
            assert hap["packet_items"] == []
            assert hap["human_packet_only"] is True
            assert hap["broker_approval_performed"] is False
            assert hap["h1_token_used"] is False
            assert hap["status"] == "packet_only"
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
            result = _run_level1_human_approval_packet_drill()
            assert len(result.get("evidence_hash", "")) > 0
            assert len(result.get("packet_artifact_hash", "")) > 0
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
            result = _run_level1_human_approval_packet_drill()
            assert result.get("export_path") is not None
            assert result.get("packet_artifact_path") is not None
            assert Path(result["export_path"]).exists()
            assert Path(result["packet_artifact_path"]).exists()
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
            result = _run_level1_human_approval_packet_drill(
                demo_candidates=3, reviewer="CustomReviewer"
            )
            assert result["diagnosis"] == _PHASE16L_DIAGNOSIS["ready"]
            hap = result["human_approval_packet"]
            assert hap["reviewer"] == "CustomReviewer"
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
            result = _run_level1_human_approval_packet_drill(
                demo_candidates=3, packet_source="custom_source"
            )
            assert result["diagnosis"] == _PHASE16L_DIAGNOSIS["ready"]
            hap = result["human_approval_packet"]
            assert hap["packet_source"] == "custom_source"
        finally:
            stop_patches(mocks, patches)

    def test_approval_checklist_all_confirms(self, clean_git_metadata, clean_worktree,
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
            result = _run_level1_human_approval_packet_drill(demo_candidates=2)
            hap = result["human_approval_packet"]
            ac = hap.get("approval_checklist", {})
            required_confirms = [
                "confirms_level1_only", "confirms_packet_only",
                "confirms_not_broker_approval", "confirms_orders_disabled",
                "confirms_system_locked", "confirms_no_h1_used",
                "confirms_no_order_window_opened", "confirms_no_approval_endpoint_called",
                "confirms_no_submit_endpoint_called", "confirms_no_broker_order_created",
                "confirms_future_real_preflight_required", "confirms_future_h1_required",
                "confirms_future_order_window_required", "requires_chris_accept_or_reject",
            ]
            for cf in required_confirms:
                assert ac.get(cf) is True, f"Missing checklist item: {cf}"
        finally:
            stop_patches(mocks, patches)
