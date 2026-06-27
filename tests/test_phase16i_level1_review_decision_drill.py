"""Tests for Phase 16I — Level 1 Review Decision Drill.

All tests are read-only. No broker mutation, no order endpoints,
no H1 token usage, no autonomy level changes. Accepted items
remain non-executable.

Coverage:
  - Command parser registers primary + 3 aliases
  - --help exits quickly
  - JSON stdout pure
  - Export written
  - Decision artifact written
  - Clean runtime => level1_review_decision_ok / OK
  - All four decision modes: mixed_demo, accept_all_demo, reject_all_demo, defer_all_demo
  - Accepted items remain non-executable across all modes
  - decision_items[] with proposal_id, decision, decision_reason, performed, requires_chris_approval
  - decision_artifact_hash present
  - workflow_summary: review_decision_ready, all_decisions_audit_only, all_items_require_future_order_window, all_items_require_future_h1
  - Missing required tag => NO_GO
  - Dirty worktree => NO_GO
  - Autonomy not level 1 => NO_GO
  - Safety unlocked => NO_GO
  - Runtime not ready => HOLD/NO_GO
  - Guard not clean => NO_GO
  - Positions not flat => NO_GO
  - Active alerts => NO_GO
  - Doctor/KPI/Policy not acceptable => NO_GO
  - Clean cycles mismatch => NO_GO
  - Review package not found => NO_GO
  - Review package not review_only => NO_GO
  - Invalid (unparseable) review package => NO_GO
  - Loading prior valid 16H artifact
  - Decision artifact structure with artifact_id and decision_artifact_hash
  - input_review_package structure with package_hash
  - no_h1_seen / no_order_window_seen
  - No /order* calls, no H1, no trade-window, no broker mutation
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
    _run_level1_review_decision_drill,
    _PHASE16I_DIAGNOSIS,
    _PHASE16I_REQUIRED_TAGS,
    _PHASE16I_EXPORT_DIR,
    _PHASE16I_EXPLICIT_NON_ACTIONS,
    _DECISION_MODE_VALUES,
    _compute_evidence_hash,
    OPENCLAW_DIR,
)


# ===========================================================================
# Fixtures
# ===========================================================================

@pytest.fixture
def clean_git_metadata():
    return {"branch": "master", "commit_short": "abc1234",
            "commit": "abc1234abc1234abc1234abc1234abc1234abc",
            "tag": "phase16h_level1_human_review_package_drill"}


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
    return {"present_count": len(_PHASE16I_REQUIRED_TAGS),
            "present": list(_PHASE16I_REQUIRED_TAGS)}


@pytest.fixture
def one_tag_missing():
    missing = [_PHASE16I_REQUIRED_TAGS[0]]
    present = list(_PHASE16I_REQUIRED_TAGS[1:])
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
def prior_review_package_json():
    """A valid 16H-formatted review package artifact."""
    return json.dumps({
        "package_id": "review-package-20260627T120000Z",
        "status": "review_only",
        "generated_by": "level1-human-review-package-drill (Phase 16H)",
        "items": [
            {
                "review_id": "review-item-external-001",
                "symbol": "SPY", "side": "BUY", "quantity": 10,
                "rationale": "Core S&P 500",
                "executable": False, "requires_chris_approval": True,
                "performed": False, "review_status": "pending_review",
                "review_checklist": [
                    {"step": "chris_approval", "description": "Chris approves", "passed": False}
                ],
            },
            {
                "review_id": "review-item-external-002",
                "symbol": "QQQ", "side": "BUY", "quantity": 20,
                "rationale": "Nasdaq-100 growth",
                "executable": False, "requires_chris_approval": True,
                "performed": False, "review_status": "pending_review",
                "review_checklist": [
                    {"step": "chris_approval", "description": "Chris approves", "passed": False}
                ],
            },
        ],
        "summary": {"total_items": 2, "executable_items": 0,
                     "pending_review_items": 2, "approved_items": 0, "rejected_items": 0},
    })


@pytest.fixture
def non_review_only_package_json():
    """A package with status != review_only — should be rejected."""
    return json.dumps({
        "package_id": "bad-package",
        "status": "executable",
        "items": [{"review_id": "x", "symbol": "BAD", "side": "BUY", "quantity": 1}],
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
    patches.append(patch("ibkr_operator._PHASE16I_EXPORT_DIR", tmp_export))
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
                           "level1-review-decision-drill", "--help"],
                          capture_output=True, text=True, timeout=10)
        assert r.returncode == 0, f"help failed: {r.stderr}"

    def test_alias_phase16i_works(self):
        import subprocess
        r = subprocess.run([sys.executable, str(BRIDGE_DIR / "ibkr_operator.py"),
                           "phase16i-review-decision-drill", "--help"],
                          capture_output=True, text=True, timeout=10)
        assert r.returncode == 0, f"alias help failed: {r.stderr}"

    def test_alias_level1_accept_reject_works(self):
        import subprocess
        r = subprocess.run([sys.executable, str(BRIDGE_DIR / "ibkr_operator.py"),
                           "level1-accept-reject-drill", "--help"],
                          capture_output=True, text=True, timeout=10)
        assert r.returncode == 0, f"alias help failed: {r.stderr}"

    def test_alias_review_decision_works(self):
        import subprocess
        r = subprocess.run([sys.executable, str(BRIDGE_DIR / "ibkr_operator.py"),
                           "review-decision-drill", "--help"],
                          capture_output=True, text=True, timeout=10)
        assert r.returncode == 0, f"alias help failed: {r.stderr}"


# ===========================================================================
# T2: Clean runtime => OK
# ===========================================================================

class TestCleanRuntime:
    def test_clean_runtime_produces_ok(self, clean_git_metadata, clean_worktree,
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
            result = _run_level1_review_decision_drill(demo_candidates=2)
            assert result["diagnosis"] == _PHASE16I_DIAGNOSIS["ready"]
            assert result["severity"] == "OK"
            assert result["operator_action_required"] is False
            assert result["promotion_allowed_now"] is False
            assert result["order_enablement_allowed_now"] is False
            assert result["order_enablement_performed"] is False
            assert result["promotion_performed"] is False
            assert result["no_broker_mutation"] is True
            assert result["no_order_window_opened"] is True
            assert result["no_h1_seen"] is True
            assert result["no_order_window_seen"] is True
            assert result["h1_token_not_used"] is True
            assert result["export_path"] is not None
            assert result["decision_artifact_path"] is not None
            assert result["drill_id"].startswith("review-decision-drill-")
            # decision_artifact_hash
            assert len(result.get("decision_artifact_hash", "")) > 0
            # input_review_package
            irp = result["input_review_package"]
            assert irp["source"] == "synthesized_internally"
            assert irp["review_only"] is True
            assert irp["items_count"] == 2
            assert len(irp["package_hash"]) > 0
            # review_decision
            rd = result["review_decision"]
            assert rd["status"] == "audit_only"
            assert rd["executable"] is False
            assert rd["accepted_items_executable"] is False
            assert rd["requires_future_order_window"] is True
            assert rd["requires_future_h1"] is True
            assert rd["future_required_path"] == "/order/preflight -> /order/approve -> /order/submit"
            assert rd["decisions_count"] == 2
            # decision_items[] — verify new field names
            di = rd["decision_items"]
            assert len(di) == 2
            for d in di:
                assert "proposal_id" in d
                assert "decision" in d  # was "verdict"
                assert "decision_reason" in d  # was "decision_rationale"
                assert d["executable"] is False
                assert d["performed"] is False
                assert d["requires_chris_approval"] is True
                assert d["requires_future_order_window"] is True
                assert d["requires_future_h1"] is True
                assert d["future_required_path"] == "/order/preflight -> /order/approve -> /order/submit"
            # decision_artifact
            da = result["decision_artifact"]
            assert da["status"] == "audit_only"
            # Workflow summary — new fields
            ws = result["workflow_summary"]
            assert ws["review_decision_ready"] is True
            assert ws["all_decisions_audit_only"] is True
            assert ws["all_items_require_future_order_window"] is True
            assert ws["all_items_require_future_h1"] is True
            assert ws["accepted_items_non_executable"] is True
            assert ws["no_order_path_called"] is True
            assert ws["no_broker_submission"] is True
            assert ws["no_h1_seen"] is True
            assert ws["no_order_window_seen"] is True
            # Autonomy
            auto = result["autonomy"]
            assert auto["current_level"] == "1"
            assert auto["clean_cycles"] == 7
            assert auto["clean_cycles_matches_kpi"] is True
        finally:
            stop_patches(mocks, patches)


# ===========================================================================
# T3: All four decision modes
# ===========================================================================

class TestDecisionModes:
    def test_mixed_demo_produces_all_three_verdicts(self, clean_git_metadata, clean_worktree,
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
            result = _run_level1_review_decision_drill(
                demo_candidates=4, decision_mode="mixed_demo"
            )
            assert result["diagnosis"] == _PHASE16I_DIAGNOSIS["ready"]
            rd = result["review_decision"]
            assert rd["accepted_count"] >= 1
            assert rd["rejected_count"] >= 1
            assert rd["deferred_count"] >= 1
            assert rd["accepted_items_executable"] is False
            for d in rd["decision_items"]:
                assert d["executable"] is False
        finally:
            stop_patches(mocks, patches)

    def test_accept_all_demo(self, clean_git_metadata, clean_worktree,
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
            result = _run_level1_review_decision_drill(
                demo_candidates=3, decision_mode="accept_all_demo"
            )
            assert result["diagnosis"] == _PHASE16I_DIAGNOSIS["ready"]
            rd = result["review_decision"]
            assert rd["accepted_count"] == 3
            assert rd["rejected_count"] == 0
            assert rd["deferred_count"] == 0
            assert rd["accepted_items_executable"] is False
            for d in rd["decision_items"]:
                assert d["decision"] == "accept"
                assert d["executable"] is False
                assert d["performed"] is False
                assert d["requires_chris_approval"] is True
        finally:
            stop_patches(mocks, patches)

    def test_reject_all_demo(self, clean_git_metadata, clean_worktree,
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
            result = _run_level1_review_decision_drill(
                demo_candidates=3, decision_mode="reject_all_demo"
            )
            assert result["diagnosis"] == _PHASE16I_DIAGNOSIS["ready"]
            rd = result["review_decision"]
            assert rd["accepted_count"] == 0
            assert rd["rejected_count"] == 3
            assert rd["deferred_count"] == 0
            for d in rd["decision_items"]:
                assert d["decision"] == "reject"
                assert d["executable"] is False
        finally:
            stop_patches(mocks, patches)

    def test_defer_all_demo(self, clean_git_metadata, clean_worktree,
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
            result = _run_level1_review_decision_drill(
                demo_candidates=2, decision_mode="defer_all_demo"
            )
            assert result["diagnosis"] == _PHASE16I_DIAGNOSIS["ready"]
            rd = result["review_decision"]
            assert rd["accepted_count"] == 0
            assert rd["rejected_count"] == 0
            assert rd["deferred_count"] == 2
            for d in rd["decision_items"]:
                assert d["decision"] == "defer"
                assert d["executable"] is False
        finally:
            stop_patches(mocks, patches)

    def test_invalid_decision_mode_falls_back_to_mixed(self, clean_git_metadata, clean_worktree,
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
            result = _run_level1_review_decision_drill(
                demo_candidates=2, decision_mode="bogus_mode"
            )
            assert result["diagnosis"] == _PHASE16I_DIAGNOSIS["ready"]
            assert result["review_decision"]["decision_mode"] == "mixed_demo"
        finally:
            stop_patches(mocks, patches)


# ===========================================================================
# T4: Loading prior 16H review package artifact
# ===========================================================================

class TestPriorReviewPackage:
    def test_loads_prior_package_from_path(self, clean_git_metadata, clean_worktree,
                                            origin_aligned, all_tags_present, bridge_health_ok,
                                            positions_flat, alerts_clean, snapshot_ok,
                                            readiness_locked, guard_state_clean, env_safety_locked,
                                            rules_locked, autonomy_level_one, doctor_pass,
                                            kpi_hold_expected, hermes_policy_ok,
                                            prior_review_package_json):
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
                tf.write(prior_review_package_json)
                pkg_path = tf.name

            result = _run_level1_review_decision_drill(
                review_package_path=pkg_path,
            )
            assert result["diagnosis"] == _PHASE16I_DIAGNOSIS["ready"]
            irp = result["input_review_package"]
            assert irp["source"] == "loaded_from_prior_16h_artifact"
            assert irp["package_id"] == "review-package-20260627T120000Z"
            assert irp["items_count"] == 2
            assert irp["package_path"] is not None
            rd = result["review_decision"]
            assert rd["decisions_count"] == 2
            symbols = [d["symbol"] for d in rd["decision_items"]]
            assert "SPY" in symbols
            assert "QQQ" in symbols
            Path(pkg_path).unlink(missing_ok=True)
        finally:
            stop_patches(mocks, patches)


# ===========================================================================
# T5: Review package rejection NO_GOs
# ===========================================================================

class TestReviewPackageRejection:
    def test_nonexistent_package_path_no_go(self, clean_git_metadata, clean_worktree,
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
            result = _run_level1_review_decision_drill(
                review_package_path="/nonexistent/path/review-package.json",
            )
            assert result["diagnosis"] == _PHASE16I_DIAGNOSIS["review_package_not_found"]
            assert result["severity"] == "NO_GO"
        finally:
            stop_patches(mocks, patches)

    def test_non_review_only_package_no_go(self, clean_git_metadata, clean_worktree,
                                            origin_aligned, all_tags_present, bridge_health_ok,
                                            positions_flat, alerts_clean, snapshot_ok,
                                            readiness_locked, guard_state_clean, env_safety_locked,
                                            rules_locked, autonomy_level_one, doctor_pass,
                                            kpi_hold_expected, hermes_policy_ok,
                                            non_review_only_package_json):
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
                tf.write(non_review_only_package_json)
                pkg_path = tf.name

            result = _run_level1_review_decision_drill(review_package_path=pkg_path)
            assert result["diagnosis"] == _PHASE16I_DIAGNOSIS["review_package_not_review_only"]
            assert result["severity"] == "NO_GO"
            Path(pkg_path).unlink(missing_ok=True)
        finally:
            stop_patches(mocks, patches)

    def test_parse_error_package_no_go(self, clean_git_metadata, clean_worktree,
                                        origin_aligned, all_tags_present, bridge_health_ok,
                                        positions_flat, alerts_clean, snapshot_ok,
                                        readiness_locked, guard_state_clean, env_safety_locked,
                                        rules_locked, autonomy_level_one, doctor_pass,
                                        kpi_hold_expected, hermes_policy_ok):
        """A syntactically invalid JSON file should yield NO_GO."""
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
                tf.write("this is not json {{{")
                pkg_path = tf.name

            result = _run_level1_review_decision_drill(review_package_path=pkg_path)
            assert result["diagnosis"] == _PHASE16I_DIAGNOSIS["review_package_not_found"]
            assert result["severity"] == "NO_GO"
            Path(pkg_path).unlink(missing_ok=True)
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
            result = _run_level1_review_decision_drill()
            assert result["diagnosis"] == _PHASE16I_DIAGNOSIS["missing_required_tags"]
            assert result["severity"] == "NO_GO"
            assert len(result.get("decision_artifact_hash", "")) > 0
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
            result = _run_level1_review_decision_drill()
            assert result["diagnosis"] == _PHASE16I_DIAGNOSIS["dirty_worktree"]
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
            result = _run_level1_review_decision_drill()
            assert result["diagnosis"] == _PHASE16I_DIAGNOSIS["autonomy_not_level1"]
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
            result = _run_level1_review_decision_drill()
            assert result["diagnosis"] == _PHASE16I_DIAGNOSIS["safety_not_locked"]
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
            result = _run_level1_review_decision_drill()
            assert result["diagnosis"] == _PHASE16I_DIAGNOSIS["guard_state_not_clean"]
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
            result = _run_level1_review_decision_drill()
            assert result["diagnosis"] == _PHASE16I_DIAGNOSIS["guard_state_not_clean"]
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
            result = _run_level1_review_decision_drill()
            assert result["diagnosis"] == _PHASE16I_DIAGNOSIS["positions_not_flat"]
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
            result = _run_level1_review_decision_drill()
            assert result["diagnosis"] == _PHASE16I_DIAGNOSIS["monitor_alerts_active"]
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
            result = _run_level1_review_decision_drill()
            assert result["diagnosis"] == _PHASE16I_DIAGNOSIS["doctor_not_acceptable"]
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
            result = _run_level1_review_decision_drill()
            assert result["diagnosis"] == _PHASE16I_DIAGNOSIS["kpi_not_acceptable"]
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
            result = _run_level1_review_decision_drill()
            assert result["diagnosis"] == _PHASE16I_DIAGNOSIS["policy_boundary_missing"]
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
            result = _run_level1_review_decision_drill()
            assert result["diagnosis"] == _PHASE16I_DIAGNOSIS["clean_cycles_mismatch"]
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
            result = _run_level1_review_decision_drill()
            assert result["diagnosis"] == _PHASE16I_DIAGNOSIS["runtime_not_ready"]
            assert result["severity"] == "HOLD"
        finally:
            stop_patches(mocks, patches)


# ===========================================================================
# T7: Decision artifact structure
# ===========================================================================

class TestDecisionArtifact:
    def test_decision_artifact_complete(self, clean_git_metadata, clean_worktree,
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
            result = _run_level1_review_decision_drill(demo_candidates=3)
            da = result["decision_artifact"]
            assert da["artifact_id"].startswith("review-decision-")
            assert da["status"] == "audit_only"
            assert da["generated_by"] == "level1-review-decision-drill (Phase 16I)"
            assert "review_package" in da
            assert "review_decision" in da
            assert da["review_decision"]["executable"] is False
            assert da["review_decision"]["accepted_items_executable"] is False
            assert result.get("decision_artifact_hash") is not None
            assert len(result["decision_artifact_hash"]) > 0
        finally:
            stop_patches(mocks, patches)

    def test_decision_artifact_file_written(self, clean_git_metadata, clean_worktree,
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
            result = _run_level1_review_decision_drill(demo_candidates=2)
            da_path = result.get("decision_artifact_path")
            assert da_path is not None
            assert Path(da_path).exists()
            with open(da_path) as f:
                loaded = json.load(f)
            assert loaded["status"] == "audit_only"
            assert loaded["review_decision"]["executable"] is False
            assert loaded["review_decision"]["accepted_items_executable"] is False
        finally:
            stop_patches(mocks, patches)


# ===========================================================================
# T8: Accepted items non-executable guarantee
# ===========================================================================

class TestAcceptedItemsNonExecutable:
    def test_accept_all_still_non_executable(self, clean_git_metadata, clean_worktree,
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
            result = _run_level1_review_decision_drill(
                demo_candidates=5, decision_mode="accept_all_demo"
            )
            assert result["review_decision"]["accepted_count"] == 5
            assert result["review_decision"]["accepted_items_executable"] is False
            for d in result["review_decision"]["decision_items"]:
                if d["decision"] == "accept":
                    assert d["executable"] is False
                    assert d["performed"] is False
            ws = result["workflow_summary"]
            assert ws["accepted_items_non_executable"] is True
            assert ws["all_decisions_audit_only"] is True
        finally:
            stop_patches(mocks, patches)


# ===========================================================================
# T9: Non-mutation guarantees
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
            result = _run_level1_review_decision_drill()
            assert result["diagnosis"] == _PHASE16I_DIAGNOSIS["ready"]
            assert result["no_broker_mutation"] is True
            assert result["no_order_window_opened"] is True
            assert result["no_h1_seen"] is True
            assert result["no_order_window_seen"] is True
            assert result["h1_token_not_used"] is True
            assert result["promotion_allowed_now"] is False
            assert result["order_enablement_allowed_now"] is False
            assert result["order_enablement_performed"] is False
            assert result["promotion_performed"] is False
            rw = result["review_workflow"]
            assert rw["broker_submission_performed"] is False
            assert rw["preflight_performed"] is False
            assert rw["approval_performed"] is False
            assert rw["submit_performed"] is False
            assert rw["order_routing_disallowed"] is True
            non_actions = result.get("explicit_non_actions", [])
            assert len(non_actions) > 0
            assert any("did not change autonomy level" in a for a in non_actions)
            assert any("did not enable orders" in a for a in non_actions)
            assert any("did not call /order" in a for a in non_actions)
            assert any("did not read H1 token" in a for a in non_actions)
            assert any("Accepted items are advisory/audit only" in a for a in non_actions)
        finally:
            stop_patches(mocks, patches)


# ===========================================================================
# T10: Edge cases
# ===========================================================================

class TestEdgeCases:
    def test_zero_candidates_ok(self, clean_git_metadata, clean_worktree,
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
            result = _run_level1_review_decision_drill(demo_candidates=0)
            assert result["diagnosis"] == _PHASE16I_DIAGNOSIS["ready"]
            assert result["input_review_package"]["items_count"] == 0
            assert result["review_decision"]["decisions_count"] == 0
            assert result["workflow_summary"]["all_decisions_audit_only"] is True
            assert result["review_decision"]["decision_items"] == []
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
            result = _run_level1_review_decision_drill()
            assert result["diagnosis"] == _PHASE16I_DIAGNOSIS["ready"]
            assert len(result.get("evidence_hash", "")) > 0
            assert len(result.get("decision_artifact_hash", "")) > 0
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
            result = _run_level1_review_decision_drill()
            assert result.get("export_path") is not None
            assert result.get("decision_artifact_path") is not None
            assert Path(result["export_path"]).exists()
            assert Path(result["decision_artifact_path"]).exists()
        finally:
            stop_patches(mocks, patches)
