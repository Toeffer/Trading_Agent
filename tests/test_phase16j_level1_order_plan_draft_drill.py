"""Tests for Phase 16J — Level 1 Approved-Item Order-Plan Draft Drill.

All tests are read-only. No broker mutation, no order endpoints,
no H1 token usage, no autonomy level changes. Draft items remain
non-executable. Only accepted items become plan items.

Coverage:
  - Command parser registers primary + 3 aliases
  - --help exits quickly
  - JSON stdout pure
  - Export written
  - Plan artifact written
  - Clean runtime => level1_order_plan_draft_ok / OK
  - Only accepted items become draft items; rejected/deferred skipped
  - skipped_items[] populated with skip_reason
  - All draft items: plan_item_id, source_decision_id, source_proposal_id, order_type, time_in_force, limit_price, rationale, risk_notes, broker_order_id=null
  - order_plan_path and order_plan_hash present
  - Mixed/accepted/rejected/deferred all 4 modes
  - Zero candidates => empty plan, OK
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
  - Decision artifact not found => NO_GO
  - Decision artifact not audit_only => NO_GO
  - Decision artifact unparseable => NO_GO
  - Loading prior 16I decision artifact
  - Plan artifact / workflow_summary structure
  - plan_artifact_hash present
  - Non-mutation guarantees
  - Rejected/deferred not in draft
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
    _run_level1_order_plan_draft_drill,
    _PHASE16J_DIAGNOSIS,
    _PHASE16J_REQUIRED_TAGS,
    _PHASE16J_EXPORT_DIR,
    _PHASE16J_EXPLICIT_NON_ACTIONS,
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
            "tag": "phase16i_level1_review_decision_drill"}


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
    return {"present_count": len(_PHASE16J_REQUIRED_TAGS),
            "present": list(_PHASE16J_REQUIRED_TAGS)}


@pytest.fixture
def one_tag_missing():
    missing = [_PHASE16J_REQUIRED_TAGS[0]]
    present = list(_PHASE16J_REQUIRED_TAGS[1:])
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
def prior_decision_artifact_json():
    """A valid 16I-formatted decision artifact with 2 accepted, 1 rejected, 1 deferred."""
    return json.dumps({
        "artifact_id": "review-decision-20260627T120000Z",
        "status": "audit_only",
        "generated_by": "level1-review-decision-drill (Phase 16I)",
        "review_decision": {
            "decision_id": "review-decision-20260627T120000Z",
            "reviewer": "Chris",
            "decision_mode": "mixed_demo",
            "status": "audit_only",
            "decisions_count": 4,
            "accepted_count": 2,
            "rejected_count": 1,
            "deferred_count": 1,
            "executable": False,
            "accepted_items_executable": False,
            "decision_items": [
                {"proposal_id": "d-001", "symbol": "SPY", "side": "BUY", "quantity": 10,
                 "decision": "accept", "decision_reason": "Core S&P 500 — advisory acceptance",
                 "executable": False, "performed": False, "requires_chris_approval": True},
                {"proposal_id": "d-002", "symbol": "QQQ", "side": "BUY", "quantity": 20,
                 "decision": "accept", "decision_reason": "Nasdaq-100 growth allocation",
                 "executable": False, "performed": False, "requires_chris_approval": True},
                {"proposal_id": "d-003", "symbol": "IWM", "side": "BUY", "quantity": 30,
                 "decision": "reject", "decision_reason": "Too volatile for current risk profile",
                 "executable": False, "performed": False, "requires_chris_approval": True},
                {"proposal_id": "d-004", "symbol": "TLT", "side": "BUY", "quantity": 40,
                 "decision": "defer", "decision_reason": "Deferred pending rate decision",
                 "executable": False, "performed": False, "requires_chris_approval": True},
            ],
        },
    })


@pytest.fixture
def non_audit_only_artifact_json():
    return json.dumps({
        "artifact_id": "bad-artifact",
        "status": "executed",
        "review_decision": {"decision_items": []},
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
    patches.append(patch("ibkr_operator._PHASE16J_EXPORT_DIR", tmp_export))
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
                           "level1-order-plan-draft-drill", "--help"],
                          capture_output=True, text=True, timeout=10)
        assert r.returncode == 0, f"help failed: {r.stderr}"

    def test_alias_phase16j_works(self):
        import subprocess
        r = subprocess.run([sys.executable, str(BRIDGE_DIR / "ibkr_operator.py"),
                           "phase16j-order-plan-draft-drill", "--help"],
                          capture_output=True, text=True, timeout=10)
        assert r.returncode == 0

    def test_alias_level1_approved_plan_drill_works(self):
        import subprocess
        r = subprocess.run([sys.executable, str(BRIDGE_DIR / "ibkr_operator.py"),
                           "level1-approved-plan-drill", "--help"],
                          capture_output=True, text=True, timeout=10)
        assert r.returncode == 0

    def test_alias_order_plan_draft_drill_works(self):
        import subprocess
        r = subprocess.run([sys.executable, str(BRIDGE_DIR / "ibkr_operator.py"),
                           "order-plan-draft-drill", "--help"],
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
            result = _run_level1_order_plan_draft_drill(demo_candidates=4, decision_mode="mixed_demo")
            assert result["diagnosis"] == _PHASE16J_DIAGNOSIS["ready"]
            assert result["severity"] == "OK"
            assert result["operator_action_required"] is False
            assert result["promotion_allowed_now"] is False
            assert result["order_enablement_allowed_now"] is False
            assert result["no_broker_mutation"] is True
            assert result["no_order_window_opened"] is True
            assert result["no_h1_seen"] is True
            assert result["no_order_window_seen"] is True
            assert result["h1_token_not_used"] is True
            assert result["export_path"] is not None
            assert result["plan_artifact_path"] is not None
            assert result["order_plan_path"] is not None
            assert len(result.get("order_plan_hash", "")) > 0
            assert len(result.get("plan_artifact_hash", "")) > 0
            assert result["drill_id"].startswith("order-plan-draft-drill-")
            # input_decision_artifact
            ida = result["input_decision_artifact"]
            assert ida["source"] == "synthesized_internally"
            assert ida["status"] == "audit_only"
            assert ida["audit_only"] is True
            assert len(ida["artifact_hash"]) > 0
            # order_plan_draft
            opd = result["order_plan_draft"]
            assert opd["plan_id"].startswith("order-plan-draft-")
            assert opd["status"] == "draft_only"
            assert opd["executable"] is False
            assert opd["broker_order_created"] is False
            assert opd["broker_submission_performed"] is False
            assert opd["preflight_performed"] is False
            assert opd["approval_performed"] is False
            assert opd["submit_performed"] is False
            assert opd["future_required_path"] == "/order/preflight -> /order/approve -> /order/submit"
            # Counted fields
            total = opd["draft_items_count"] + opd["skipped_rejected_count"] + opd["skipped_deferred_count"]
            assert total >= 1
            # draft_items[] — verify all new fields
            for d in opd["draft_items"]:
                assert "plan_item_id" in d
                assert "source_decision_id" in d
                assert "source_proposal_id" in d
                assert d["executable"] is False
                assert d["performed"] is False
                assert d["broker_order_created"] is False
                assert d["broker_order_id"] is None
                assert d["order_type"] == "LMT"
                assert d["time_in_force"] == "DAY"
                assert d["limit_price"] is None
                assert "rationale" in d
                assert "risk_notes" in d
                assert d["requires_chris_approval"] is True
                assert d["requires_future_order_window"] is True
                assert d["requires_future_h1"] is True
            # skipped_items[]
            si = opd["skipped_items"]
            assert isinstance(si, list)
            for s in si:
                assert "source_proposal_id" in s
                assert "decision" in s
                assert "skip_reason" in s
            # workflow_summary — all new fields
            ws = result["workflow_summary"]
            assert ws["order_plan_draft_ready"] is True
            assert ws["all_draft_items_non_executable"] is True
            assert ws["no_broker_order_created"] is True
            assert ws["no_order_path_called"] is True
            assert ws["no_preflight_performed"] is True
            assert ws["no_approval_performed"] is True
            assert ws["no_submit_performed"] is True
            assert ws["no_broker_submission"] is True
            assert ws["no_h1_seen"] is True
            assert ws["no_order_window_seen"] is True
            # Autonomy
            assert result["autonomy"]["current_level"] == "1"
        finally:
            stop_patches(mocks, patches)


# ===========================================================================
# T3: Accepted items only => draft; rejected/deferred => skipped
# ===========================================================================

class TestAcceptedItemsOnly:
    def test_mixed_demo_rejected_deferred_excluded(self, clean_git_metadata, clean_worktree,
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
            result = _run_level1_order_plan_draft_drill(demo_candidates=5, decision_mode="mixed_demo")
            opd = result["order_plan_draft"]
            rejected = opd["skipped_rejected_count"]
            deferred = opd["skipped_deferred_count"]
            # All draft items must be "accept"
            for d in opd["draft_items"]:
                assert d.get("original_decision") == "accept"
            # skipped_items must contain rejected and deferred
            si = opd["skipped_items"]
            assert len(si) == rejected + deferred
            # No draft item should come from a rejected/deferred source
            skipped_ids = {s["source_proposal_id"] for s in si}
            for d in opd["draft_items"]:
                src = d.get("source_proposal_id", d.get("source_decision_id", ""))
                assert src not in skipped_ids, f"Draft item {d['plan_item_id']} from skipped source {src}"
            # Plan workflow counts
            pw = result["plan_workflow"]
            assert pw["rejected_items_skipped"] == rejected
            assert pw["deferred_items_skipped"] == deferred
            assert pw["rejected_or_deferred_in_draft"] is False
        finally:
            stop_patches(mocks, patches)

    def test_accept_all_no_exclusions(self, clean_git_metadata, clean_worktree,
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
            result = _run_level1_order_plan_draft_drill(demo_candidates=3, decision_mode="accept_all_demo")
            assert result["diagnosis"] == _PHASE16J_DIAGNOSIS["ready"]
            opd = result["order_plan_draft"]
            assert opd["draft_items_count"] == 3
            assert opd["skipped_rejected_count"] == 0
            assert opd["skipped_deferred_count"] == 0
            assert opd["skipped_items"] == []
            ws = result["workflow_summary"]
            assert ws["accepted_items_converted_to_draft"] is True
        finally:
            stop_patches(mocks, patches)

    def test_reject_all_empty_draft_skipped_items_populated(self, clean_git_metadata, clean_worktree,
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
            result = _run_level1_order_plan_draft_drill(demo_candidates=3, decision_mode="reject_all_demo")
            assert result["diagnosis"] == _PHASE16J_DIAGNOSIS["ready"]
            opd = result["order_plan_draft"]
            assert opd["draft_items_count"] == 0
            assert opd["skipped_rejected_count"] == 3
            assert opd["skipped_deferred_count"] == 0
            assert len(opd["skipped_items"]) == 3
            for s in opd["skipped_items"]:
                assert s["decision"] == "reject"
                assert len(s["skip_reason"]) > 0
            ws = result["workflow_summary"]
            assert ws["rejected_items_skipped"] == (True)
        finally:
            stop_patches(mocks, patches)

    def test_defer_all_empty_draft_skipped_deferred(self, clean_git_metadata, clean_worktree,
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
            result = _run_level1_order_plan_draft_drill(demo_candidates=2, decision_mode="defer_all_demo")
            assert result["diagnosis"] == _PHASE16J_DIAGNOSIS["ready"]
            opd = result["order_plan_draft"]
            assert opd["draft_items_count"] == 0
            assert opd["skipped_deferred_count"] == 2
            assert len(opd["skipped_items"]) == 2
            for s in opd["skipped_items"]:
                assert s["decision"] == "defer"
        finally:
            stop_patches(mocks, patches)


# ===========================================================================
# T4: Loading prior 16I decision artifact
# ===========================================================================

class TestPriorDecisionArtifact:
    def test_loads_prior_artifact_from_path(self, clean_git_metadata, clean_worktree,
                                             origin_aligned, all_tags_present, bridge_health_ok,
                                             positions_flat, alerts_clean, snapshot_ok,
                                             readiness_locked, guard_state_clean, env_safety_locked,
                                             rules_locked, autonomy_level_one, doctor_pass,
                                             kpi_hold_expected, hermes_policy_ok,
                                             prior_decision_artifact_json):
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
            import tempfile
            with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as tf:
                tf.write(prior_decision_artifact_json)
                da_path = tf.name

            result = _run_level1_order_plan_draft_drill(decision_artifact_path=da_path)
            assert result["diagnosis"] == _PHASE16J_DIAGNOSIS["ready"]
            ida = result["input_decision_artifact"]
            assert ida["source"] == "loaded_from_prior_16i_artifact"
            assert ida["decision_id"] == "review-decision-20260627T120000Z"
            assert ida["accepted_count"] == 2
            assert ida["rejected_count"] == 1
            assert ida["deferred_count"] == 1
            opd = result["order_plan_draft"]
            assert opd["draft_items_count"] == 2  # 2 accepted
            assert opd["skipped_rejected_count"] == 1
            assert opd["skipped_deferred_count"] == 1
            assert len(opd["skipped_items"]) == 2
            symbols = [d["symbol"] for d in opd["draft_items"]]
            assert "SPY" in symbols
            assert "QQQ" in symbols
            assert "IWM" not in symbols
            assert "TLT" not in symbols
            # Verify draft items have source fields from the artifact
            for d in opd["draft_items"]:
                assert d["source_decision_id"] in ("d-001", "d-002")
            Path(da_path).unlink(missing_ok=True)
        finally:
            stop_patches(mocks, patches)


# ===========================================================================
# T5: Decision artifact rejection NO_GOs
# ===========================================================================

class TestDecisionArtifactRejection:
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
            result = _run_level1_order_plan_draft_drill(
                decision_artifact_path="/nonexistent/decision-artifact.json",
            )
            assert result["diagnosis"] == _PHASE16J_DIAGNOSIS["decision_artifact_not_found"]
            assert result["severity"] == "NO_GO"
            assert result["order_plan_draft"]["status"] == "blocked"
        finally:
            stop_patches(mocks, patches)

    def test_non_audit_only_artifact_no_go(self, clean_git_metadata, clean_worktree,
                                            origin_aligned, all_tags_present, bridge_health_ok,
                                            positions_flat, alerts_clean, snapshot_ok,
                                            readiness_locked, guard_state_clean, env_safety_locked,
                                            rules_locked, autonomy_level_one, doctor_pass,
                                            kpi_hold_expected, hermes_policy_ok,
                                            non_audit_only_artifact_json):
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
            import tempfile
            with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as tf:
                tf.write(non_audit_only_artifact_json)
                da_path = tf.name

            result = _run_level1_order_plan_draft_drill(decision_artifact_path=da_path)
            assert result["diagnosis"] == _PHASE16J_DIAGNOSIS["decision_artifact_not_audit_only"]
            Path(da_path).unlink(missing_ok=True)
        finally:
            stop_patches(mocks, patches)

    def test_parse_error_artifact_no_go(self, clean_git_metadata, clean_worktree,
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
            import tempfile
            with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as tf:
                tf.write("not valid {{{ json")
                da_path = tf.name

            result = _run_level1_order_plan_draft_drill(decision_artifact_path=da_path)
            assert result["diagnosis"] == _PHASE16J_DIAGNOSIS["decision_artifact_not_found"]
            Path(da_path).unlink(missing_ok=True)
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
            result = _run_level1_order_plan_draft_drill()
            assert result["diagnosis"] == _PHASE16J_DIAGNOSIS["missing_required_tags"]
            assert result["severity"] == "NO_GO"
            assert result["order_plan_draft"]["status"] == "blocked"
            assert result.get("order_plan_path") is None
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
            result = _run_level1_order_plan_draft_drill()
            assert result["diagnosis"] == _PHASE16J_DIAGNOSIS["dirty_worktree"]
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
            result = _run_level1_order_plan_draft_drill()
            assert result["diagnosis"] == _PHASE16J_DIAGNOSIS["autonomy_not_level1"]
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
            result = _run_level1_order_plan_draft_drill()
            assert result["diagnosis"] == _PHASE16J_DIAGNOSIS["safety_not_locked"]
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
            result = _run_level1_order_plan_draft_drill()
            assert result["diagnosis"] == _PHASE16J_DIAGNOSIS["guard_state_not_clean"]
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
            result = _run_level1_order_plan_draft_drill()
            assert result["diagnosis"] == _PHASE16J_DIAGNOSIS["positions_not_flat"]
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
            result = _run_level1_order_plan_draft_drill()
            assert result["diagnosis"] == _PHASE16J_DIAGNOSIS["monitor_alerts_active"]
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
            result = _run_level1_order_plan_draft_drill()
            assert result["diagnosis"] == _PHASE16J_DIAGNOSIS["doctor_not_acceptable"]
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
            result = _run_level1_order_plan_draft_drill()
            assert result["diagnosis"] == _PHASE16J_DIAGNOSIS["kpi_not_acceptable"]
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
            result = _run_level1_order_plan_draft_drill()
            assert result["diagnosis"] == _PHASE16J_DIAGNOSIS["policy_boundary_missing"]
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
            result = _run_level1_order_plan_draft_drill()
            assert result["diagnosis"] == _PHASE16J_DIAGNOSIS["clean_cycles_mismatch"]
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
            result = _run_level1_order_plan_draft_drill()
            assert result["diagnosis"] == _PHASE16J_DIAGNOSIS["runtime_not_ready"]
            assert result["severity"] == "HOLD"
        finally:
            stop_patches(mocks, patches)


# ===========================================================================
# T7: Plan artifact structure
# ===========================================================================

class TestPlanArtifact:
    def test_plan_artifact_complete(self, clean_git_metadata, clean_worktree,
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
            result = _run_level1_order_plan_draft_drill(demo_candidates=3)
            pa = result["plan_artifact"]
            assert pa["status"] == "draft_only"
            assert pa["generated_by"] == "level1-order-plan-draft-drill (Phase 16J)"
            assert "input_decision_artifact" in pa
            assert "order_plan_draft" in pa
            assert pa["order_plan_draft"]["executable"] is False
            assert pa["order_plan_draft"]["broker_order_created"] is False
            assert result.get("plan_artifact_hash") is not None
            assert result.get("order_plan_hash") is not None
            assert len(result["plan_artifact_hash"]) > 0
        finally:
            stop_patches(mocks, patches)

    def test_plan_artifact_file_written(self, clean_git_metadata, clean_worktree,
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
            result = _run_level1_order_plan_draft_drill(demo_candidates=2)
            pa_path = result.get("plan_artifact_path")
            assert pa_path is not None
            assert Path(pa_path).exists()
            with open(pa_path) as f:
                loaded = json.load(f)
            assert loaded["status"] == "draft_only"
            assert loaded["order_plan_draft"]["executable"] is False
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
            result = _run_level1_order_plan_draft_drill()
            assert result["diagnosis"] == _PHASE16J_DIAGNOSIS["ready"]
            assert result["no_broker_mutation"] is True
            assert result["no_order_window_opened"] is True
            assert result["no_h1_seen"] is True
            assert result["no_order_window_seen"] is True
            assert result["h1_token_not_used"] is True
            assert result["promotion_allowed_now"] is False
            assert result["order_enablement_allowed_now"] is False
            pw = result["plan_workflow"]
            assert pw["broker_submission_performed"] is False
            assert pw["preflight_performed"] is False
            assert pw["approval_performed"] is False
            assert pw["submit_performed"] is False
            assert pw["order_routing_disallowed"] is True
            ws = result["workflow_summary"]
            assert ws["no_preflight_performed"] is True
            assert ws["no_approval_performed"] is True
            assert ws["no_submit_performed"] is True
            non_actions = result.get("explicit_non_actions", [])
            assert any("did not preflight" in a for a in non_actions)
            assert any("did not approve" in a for a in non_actions)
            assert any("did not submit" in a for a in non_actions)
            assert any("did not create a broker order" in a for a in non_actions)
        finally:
            stop_patches(mocks, patches)


# ===========================================================================
# T9: Edge cases
# ===========================================================================

class TestEdgeCases:
    def test_zero_candidates_produces_empty_plan_ok(self, clean_git_metadata, clean_worktree,
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
            result = _run_level1_order_plan_draft_drill(demo_candidates=0)
            assert result["diagnosis"] == _PHASE16J_DIAGNOSIS["ready"]
            opd = result["order_plan_draft"]
            assert opd["draft_items_count"] == 0
            assert opd["draft_items"] == []
            assert opd["skipped_items"] == []
            assert opd["skipped_rejected_count"] == 0
            assert opd["skipped_deferred_count"] == 0
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
            result = _run_level1_order_plan_draft_drill()
            assert len(result.get("evidence_hash", "")) > 0
            assert len(result.get("plan_artifact_hash", "")) > 0
            assert len(result.get("order_plan_hash", "")) > 0
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
            result = _run_level1_order_plan_draft_drill()
            assert result.get("export_path") is not None
            assert result.get("plan_artifact_path") is not None
            assert result.get("order_plan_path") is not None
            assert Path(result["export_path"]).exists()
            assert Path(result["plan_artifact_path"]).exists()
        finally:
            stop_patches(mocks, patches)
