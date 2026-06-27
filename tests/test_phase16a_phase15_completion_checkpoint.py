"""Tests for Phase 16A — Phase-15 Completion Checkpoint / Promotion Readiness Dossier.

All tests are read-only. No broker mutation, no order endpoints,
no H1 token usage, no autonomy level changes.

Coverage:
  - Command parser registers primary + 3 aliases
  - --help exits quickly
  - JSON stdout pure
  - Export written
  - Missing Phase-15 tag => NO_GO
  - Dirty worktree => NO_GO
  - Clean connected locked runtime => diagnosis=phase15_complete_ready_for_review / severity=OK
  - Safety unlocked => NO_GO
  - Active monitor alerts => NO_GO
  - Guard daily_trade_count > 0 => NO_GO
  - promotion_allowed_now=false, order_enablement_allowed_now=false
  - No /order* calls in checkpoint path
  - No H1 token reads
  - No mutation except export artifact
"""

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock, mock_open, PropertyMock

import pytest

# Auto-generated: dynamic date helpers for guard-state fixtures
from datetime import datetime, timezone, timedelta
_TODAY_STR = datetime.now(timezone.utc).strftime("%Y-%m-%d")
_YESTERDAY_STR = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")


BRIDGE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BRIDGE_DIR))

# Import after path setup
from ibkr_operator import (


    _run_phase15_completion_checkpoint,
    _REQUIRED_PHASE15_TAGS,
    _PHASE16A_DIAGNOSIS,
    _PHASE16A_EXPORT_DIR,
    BRIDGE_DIR as _OP_BRIDGE_DIR,
    OPENCLAW_DIR,
)


# ===========================================================================
# Fixtures
# ===========================================================================

@pytest.fixture
def clean_git_metadata():
    """Return a clean git metadata dict."""
    return {
        "branch": "main",
        "commit_short": "abc1234",
        "tag": "phase0_2_step15z_locked_preflight_proof",
    }


@pytest.fixture
def clean_worktree():
    """Clean worktree — no dirty files."""
    return {"clean": True, "dirty_files": []}


@pytest.fixture
def dirty_worktree():
    """Dirty worktree — one modified file."""
    return {"clean": False, "dirty_files": ["M ibkr_operator.py"]}


@pytest.fixture
def origin_aligned():
    """Origin/master aligned."""
    return {
        "aligned": True,
        "origin_master_commit": "abc1234",
        "local_master_commit": "abc1234",
        "detail": "local master == origin/master",
    }


@pytest.fixture
def all_tags_present():
    """All 11 Phase-15 tags present."""
    return {
        "required_count": len(_REQUIRED_PHASE15_TAGS),
        "present_count": len(_REQUIRED_PHASE15_TAGS),
        "missing": [],
        "present": list(_REQUIRED_PHASE15_TAGS),
    }


@pytest.fixture
def one_tag_missing():
    """One tag missing from Phase-15."""
    return {
        "required_count": len(_REQUIRED_PHASE15_TAGS),
        "present_count": len(_REQUIRED_PHASE15_TAGS) - 1,
        "missing": [_REQUIRED_PHASE15_TAGS[0]],
        "present": list(_REQUIRED_PHASE15_TAGS[1:]),
    }


@pytest.fixture
def bridge_health_ok():
    """Healthy bridge response."""
    return {
        "ok": True, "service": "ibkr-openclaw-bridge",
        "mode": "paper", "host": "127.0.0.1", "port": 4002,
        "client_id": 777, "account": "DUQ542875",
        "read_only": True, "allow_orders": False,
        "connected": True,
        "startup_safety": {"pass": True, "check_count": 11, "passed_count": 11},
    }


@pytest.fixture
def bridge_health_disconnected():
    """Bridge running but IBKR disconnected."""
    return {
        "ok": True, "service": "ibkr-openclaw-bridge",
        "mode": "paper", "host": "127.0.0.1", "port": 4002,
        "client_id": 777, "account": "DUQ542875",
        "read_only": True, "allow_orders": False,
        "connected": False,
        "startup_safety": {"pass": True, "check_count": 11, "passed_count": 11},
    }


@pytest.fixture
def positions_flat():
    """No open positions."""
    return {"ok": True, "positions": []}


@pytest.fixture
def alerts_clean():
    """No active alerts."""
    return {"alerts": [], "reconciliation_timestamp_utc": "2026-06-26T08:00:00Z"}


@pytest.fixture
def alerts_active():
    """One active alert requiring action."""
    return {
        "alerts": [
            {
                "alert_type": "drift_detected",
                "severity": "CRITICAL",
                "requires_action": True,
                "source": "live",
                "detail": "Position drift detected for AAPL",
            }
        ],
        "reconciliation_timestamp_utc": "2026-06-26T08:00:00Z",
    }


@pytest.fixture
def readiness_locked():
    """Readiness with locked kill switches."""
    return {
        "summary": {
            "kill_switches": {
                "IBKR_ALLOW_ORDERS": False,
                "rules.enforced": False,
                "system_locked": True,
            }
        }
    }


@pytest.fixture
def readiness_unlocked():
    """Readiness with unlocked kill switches."""
    return {
        "summary": {
            "kill_switches": {
                "IBKR_ALLOW_ORDERS": True,
                "rules.enforced": True,
                "system_locked": False,
            }
        }
    }


@pytest.fixture
def snapshot_ok():
    """Snapshot endpoint response."""
    return {
        "connected": True, "mode": "paper", "read_only": True,
        "allow_orders": False, "positions": [], "guard": {},
        "safety": {"IBKR_ALLOW_ORDERS": False, "rules_enforced": False,
                    "system_locked": True},
    }


@pytest.fixture
def guard_state_clean():
    """Guard state with zero trades, no halt."""
    return json.dumps({
        "schema_version": 1,
        "trade_date": _TODAY_STR,
        "daily_trade_count": 0,
        "day_start_nl_eur": 100000.0,
        "daily_halt_active": False,
        "weekly_halt_active": False,
        "halt_reason": None,
        "last_updated_utc": "2026-06-26T08:00:00Z",
    })


@pytest.fixture
def guard_state_with_trades():
    """Guard state with non-zero daily trade count."""
    return json.dumps({
        "schema_version": 1,
        "trade_date": _TODAY_STR,
        "daily_trade_count": 3,
        "day_start_nl_eur": 100000.0,
        "daily_halt_active": False,
        "weekly_halt_active": False,
        "halt_reason": None,
        "last_updated_utc": "2026-06-26T08:00:00Z",
    })


@pytest.fixture
def env_safety_locked():
    """.env with IBKR_ALLOW_ORDERS=false."""
    return {"IBKR_ALLOW_ORDERS": "false", "found": True}


@pytest.fixture
def env_safety_unlocked():
    """.env with IBKR_ALLOW_ORDERS=true."""
    return {"IBKR_ALLOW_ORDERS": "true", "found": True}


@pytest.fixture
def rules_locked():
    """rules.enforced=false."""
    return {"enforced": "false", "found": True}


@pytest.fixture
def rules_unlocked():
    """rules.enforced=true."""
    return {"enforced": "true", "found": True}


@pytest.fixture
def autonomy_level_zero():
    """Autonomy level 0."""
    return "0"


@pytest.fixture
def autonomy_level_one():
    """Autonomy level 1."""
    return "1"


@pytest.fixture
def clean_cycles_recorded():
    """Some clean cycles recorded."""
    return 7


@pytest.fixture
def doctor_pass():
    """Doctor PASS result."""
    return {
        "pass": True,
        "passed": 14,
        "total": 15,
        "passed_count": 14,
        "check_count": 15,
        "_non_canary_ok": True,
        "_non_canary_failures": [],
        "checks": [
            {"check": "runbook_exists", "ok": True},
            {"check": "h1_token_canary", "ok": True, "status": "PASS"},
        ],
    }


@pytest.fixture
def doctor_h1_manual():
    """Doctor PASS but H1 canary requires manual."""
    return {
        "pass": True,
        "passed": 14,
        "total": 15,
        "passed_count": 14,
        "check_count": 15,
        "_non_canary_ok": True,
        "_non_canary_failures": [],
        "checks": [
            {"check": "runbook_exists", "ok": True},
            {"check": "h1_token_canary", "ok": False, "status": "MANUAL_REQUIRED"},
        ],
    }


@pytest.fixture
def doctor_fail():
    """Doctor FAIL result."""
    return {
        "pass": False,
        "passed": 10,
        "total": 15,
        "passed_count": 10,
        "check_count": 15,
        "_non_canary_ok": False,
        "_non_canary_failures": ["hermes_policy_exists"],
        "checks": [
            {"check": "runbook_exists", "ok": True},
            {"check": "hermes_policy_exists", "ok": False},
            {"check": "h1_token_canary", "ok": True, "status": "PASS"},
        ],
    }


@pytest.fixture
def kpi_hold_expected():
    """KPI HOLD — expected at Level 0."""
    return {
        "verdict": "HOLD",
        "blockers": [
            {"severity": "HOLD", "check": "autonomy_level_zero",
             "detail": "Autonomy level 0 — manual approval required"},
            {"severity": "HOLD", "check": "system_locked",
             "detail": "System locked"},
        ],
    }


@pytest.fixture
def kpi_no_go():
    """KPI NO-GO."""
    return {
        "verdict": "NO-GO",
        "blockers": [
            {"severity": "NO-GO", "check": "active_alerts",
             "detail": "1 live alert(s): drift_detected"},
            {"severity": "HOLD", "check": "autonomy_level_zero",
             "detail": "Autonomy level 0"},
        ],
    }


@pytest.fixture
def hermes_policy_ok():
    """Hermes policy exists and is clean."""
    return {
        "hermes_policy_exists": True,
        "policy_path": str(Path.home() / ".openclaw" / "memory" /
                          "hermes-advisory-guard-policy.md"),
        "execution_path_ok": True,
        "advisory_boundary_ok": True,
    }


@pytest.fixture
def hermes_policy_missing():
    """Hermes policy missing."""
    return {
        "hermes_policy_exists": False,
        "policy_path": str(Path.home() / ".openclaw" / "memory" /
                          "hermes-advisory-guard-policy.md"),
        "execution_path_ok": False,
        "advisory_boundary_ok": False,
    }


# ===========================================================================
# Mock assembly helpers
# ===========================================================================

class _MockUrlOpen:
    """Flexible urlopen mock returning per-URL responses."""

    def __init__(self, responses: dict):
        self._responses = responses  # {url_substring: (status, body_dict)}
        self._calls: list[str] = []

    def __call__(self, req, timeout=None):
        url = req.full_url if hasattr(req, 'full_url') else str(req)
        self._calls.append(url)
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


def _make_bridge_responses(health=None, positions=None, alerts=None,
                           snapshot=None, readiness=None):
    """Build a urlopen mock for bridge endpoints."""
    responses = {}
    if health:
        responses["/health"] = (200, health)
    if positions:
        responses["/positions"] = (200, positions)
    if alerts:
        responses["/monitor/alerts"] = (200, alerts)
    if snapshot:
        responses["/snapshot"] = (200, snapshot)
    if readiness:
        responses["/readiness"] = (200, readiness)
    return _MockUrlOpen(responses)


def _mock_subprocess_output(outputs: dict):
    """Mock subprocess.run to return per-command outputs.

    outputs maps command substring -> (returncode, stdout_string).
    """
    def _run(args, **kwargs):
        cmd_str = " ".join(args) if isinstance(args, list) else str(args)
        for pattern, (rc, out) in outputs.items():
            if pattern in cmd_str:
                result = MagicMock()
                result.returncode = rc
                result.stdout = out
                result.stderr = ""
                return result
        # Default: success with empty output
        result = MagicMock()
        result.returncode = 0
        result.stdout = ""
        result.stderr = ""
        return result
    return _run


def _build_clean_mocks(
    health=None, positions=None, alerts=None, snapshot=None, readiness=None,
    git_metadata=None, worktree=None, origin=None, tags=None,
    guard_state_content=None, env_safety=None, rules=None,
    autonomy=None, clean_cycles=None, doctor=None, kpi=None, policy=None,
):
    """Build a complete set of patches for clean checkpoint run."""
    patches = []

    # 1. Bridge HTTP
    bridge_mock = _make_bridge_responses(
        health=health, positions=positions, alerts=alerts,
        snapshot=snapshot, readiness=readiness,
    )
    patches.append(patch("urllib.request.urlopen", bridge_mock))

    # 2. Git metadata
    if git_metadata:
        patches.append(patch("ibkr_operator._git_metadata", return_value=git_metadata))

    # 3. Subprocess (git worktree, tags, origin, systemctl, pgrep)
    sub_outputs = {}
    if worktree is not None:
        sub_outputs["status --porcelain"] = (
            0, "\n".join(worktree.get("dirty_files", []))
        )
    else:
        sub_outputs["status --porcelain"] = (0, "")
    if tags is not None:
        sub_outputs["tag"] = (0, "\n".join(tags.get("present", [])))
    if origin is not None:
        local = origin.get("local_master_commit", "abc1234")
        remote = origin.get("origin_master_commit", "abc1234")
        sub_outputs["rev-parse --short master"] = (0, local)
        sub_outputs["rev-parse --short origin/master"] = (0, remote)
        # For alignment check
        sub_outputs["merge-base --is-ancestor"] = (0, "")
    # systemctl
    sub_outputs["systemctl is-active"] = (0, "active")
    # pgrep
    sub_outputs["pgrep -c -f uvicorn"] = (0, "1")
    # rev-parse HEAD
    sub_outputs["rev-parse HEAD"] = (0, "abc1234abc1234abc1234abc1234abc1234abc")
    patches.append(patch("subprocess.run", side_effect=_mock_subprocess_output(sub_outputs)))

    # 4. Guard state — create a temp openclaw dir with guard-state.json
    tmp_openclaw = Path(tempfile.mkdtemp())
    if guard_state_content is not None:
        (tmp_openclaw / "guard-state.json").write_text(guard_state_content)
    patches.append(patch("ibkr_operator.OPENCLAW_DIR", tmp_openclaw))
    # Also patch the _PHASE16A_EXPORT_DIR so export writes go to temp
    tmp_export = Path(tempfile.mkdtemp())
    patches.append(patch("ibkr_operator._PHASE16A_EXPORT_DIR", tmp_export))

    # 5. Env safety
    if env_safety:
        patches.append(patch("ibkr_operator._read_env_safety", return_value=env_safety))

    # 6. Rules
    if rules:
        patches.append(patch("ibkr_operator._read_rules_enforced", return_value=rules))

    # 7. Autonomy
    if autonomy:
        patches.append(patch("ibkr_operator._read_autonomy_level", return_value=autonomy))

    # 8. Clean cycles
    if clean_cycles is not None:
        patches.append(patch("ibkr_operator._count_clean_cycles", return_value=clean_cycles))

    # 9. Doctor
    if doctor:
        patches.append(patch("ibkr_operator.run_doctor", return_value=doctor))

    # 10. KPI
    if kpi:
        patches.append(patch("ibkr_operator.run_kpi", return_value=kpi))

    # 11. Policy
    if policy:
        patches.append(patch("ibkr_operator._check_hermes_policy", return_value=policy))

    return patches


def apply_patches(patches: list):
    """Start all patches and return a list of started mocks for cleanup."""
    mocks = [p.start() for p in patches]
    return mocks, patches


def stop_patches(mocks, patches):
    """Stop all patches."""
    for p in patches:
        try:
            p.stop()
        except RuntimeError:
            pass


# ===========================================================================
# T1: Command exists
# ===========================================================================

class TestCommandExists:
    """Verify primary command and aliases are registered."""

    def test_primary_command_registered(self):
        """phase15-completion-checkpoint --help exits 0 quickly."""
        r = subprocess.run(
            [sys.executable, str(BRIDGE_DIR / "ibkr_operator.py"),
             "phase15-completion-checkpoint", "--help"],
            capture_output=True, text=True, timeout=10,
        )
        assert r.returncode == 0, f"help failed: {r.stderr}"

    @pytest.mark.parametrize("alias", [
        "phase-readiness-dossier",
        "promotion-readiness-checkpoint",
        "level1-readiness-dossier",
    ])
    def test_alias_registered(self, alias):
        """Alias --help exits 0 quickly."""
        r = subprocess.run(
            [sys.executable, str(BRIDGE_DIR / "ibkr_operator.py"),
             alias, "--help"],
            capture_output=True, text=True, timeout=10,
        )
        assert r.returncode == 0, f"{alias} --help failed: {r.stderr}"

    def test_function_importable(self):
        """_run_phase15_completion_checkpoint is importable and callable."""
        from ibkr_operator import _run_phase15_completion_checkpoint
        assert callable(_run_phase15_completion_checkpoint)


# ===========================================================================
# T2: Missing Phase-15 tag => NO_GO
# ===========================================================================

class TestMissingTags:
    """When required Phase-15 tags are missing, diagnosis = missing_phase15_tags."""

    def test_missing_tag_produces_no_go(self,
                                        clean_git_metadata,
                                        clean_worktree,
                                        origin_aligned,
                                        one_tag_missing,
                                        bridge_health_ok,
                                        positions_flat,
                                        alerts_clean,
                                        snapshot_ok,
                                        readiness_locked,
                                        guard_state_clean,
                                        env_safety_locked,
                                        rules_locked,
                                        autonomy_level_zero,
                                        clean_cycles_recorded,
                                        doctor_pass,
                                        kpi_hold_expected,
                                        hermes_policy_ok):
        """One missing tag → NO_GO with correct diagnosis."""
        patches = _build_clean_mocks(
            health=bridge_health_ok,
            positions=positions_flat,
            alerts=alerts_clean,
            snapshot=snapshot_ok,
            readiness=readiness_locked,
            git_metadata=clean_git_metadata,
            worktree=clean_worktree,
            origin=origin_aligned,
            tags=one_tag_missing,
            guard_state_content=guard_state_clean,
            env_safety=env_safety_locked,
            rules=rules_locked,
            autonomy=autonomy_level_zero,
            clean_cycles=clean_cycles_recorded,
            doctor=doctor_pass,
            kpi=kpi_hold_expected,
            policy=hermes_policy_ok,
        )
        mocks, patches = apply_patches(patches)
        try:
            result = _run_phase15_completion_checkpoint()
            assert result["diagnosis"] == _PHASE16A_DIAGNOSIS["missing_tags"]
            assert result["severity"] == "NO_GO"
            assert result["phase15_complete"] is False
            assert result["operator_action_required"] is True
            assert len(result["suggested_operator_actions"]) > 0
            assert result["no_broker_mutation"] is True
            assert result["no_order_window_opened"] is True
            assert result["h1_token_not_used"] is True
            # Missing tag count correct
            assert result["phase15_tags"]["missing"] == one_tag_missing["missing"]
            assert result["phase15_tags"]["present_count"] == one_tag_missing["present_count"]
        finally:
            stop_patches(mocks, patches)


# ===========================================================================
# T3: Dirty worktree => NO_GO
# ===========================================================================

class TestDirtyWorktree:
    """When worktree is dirty, diagnosis = dirty_worktree."""

    def test_dirty_worktree_produces_no_go(self,
                                           clean_git_metadata,
                                           dirty_worktree,
                                           origin_aligned,
                                           all_tags_present,
                                           bridge_health_ok,
                                           positions_flat,
                                           alerts_clean,
                                           snapshot_ok,
                                           readiness_locked,
                                           guard_state_clean,
                                           env_safety_locked,
                                           rules_locked,
                                           autonomy_level_zero,
                                           clean_cycles_recorded,
                                           doctor_pass,
                                           kpi_hold_expected,
                                           hermes_policy_ok):
        """Dirty worktree → NO_GO with correct diagnosis."""
        patches = _build_clean_mocks(
            health=bridge_health_ok,
            positions=positions_flat,
            alerts=alerts_clean,
            snapshot=snapshot_ok,
            readiness=readiness_locked,
            git_metadata=clean_git_metadata,
            worktree=dirty_worktree,
            origin=origin_aligned,
            tags=all_tags_present,
            guard_state_content=guard_state_clean,
            env_safety=env_safety_locked,
            rules=rules_locked,
            autonomy=autonomy_level_zero,
            clean_cycles=clean_cycles_recorded,
            doctor=doctor_pass,
            kpi=kpi_hold_expected,
            policy=hermes_policy_ok,
        )
        mocks, patches = apply_patches(patches)
        try:
            result = _run_phase15_completion_checkpoint()
            assert result["diagnosis"] == _PHASE16A_DIAGNOSIS["dirty_worktree"]
            assert result["severity"] == "NO_GO"
            assert result["phase15_complete"] is False
            assert result["operator_action_required"] is True
            assert result["git"]["worktree_clean"] is False
            assert len(result["git"]["dirty_files"]) > 0
            # Suggested actions reference dirty files
            actions_text = " ".join(result["suggested_operator_actions"])
            assert "Commit or stash" in actions_text or "dirty" in actions_text.lower()
        finally:
            stop_patches(mocks, patches)


# ===========================================================================
# T4: Clean connected locked runtime => OK
# ===========================================================================

class TestCleanConnectedLocked:
    """All checks pass → diagnosis=phase15_complete_ready_for_review / severity=OK."""

    def test_clean_runtime_produces_ok(self,
                                       clean_git_metadata,
                                       clean_worktree,
                                       origin_aligned,
                                       all_tags_present,
                                       bridge_health_ok,
                                       positions_flat,
                                       alerts_clean,
                                       snapshot_ok,
                                       readiness_locked,
                                       guard_state_clean,
                                       env_safety_locked,
                                       rules_locked,
                                       autonomy_level_zero,
                                       clean_cycles_recorded,
                                       doctor_pass,
                                       kpi_hold_expected,
                                       hermes_policy_ok):
        """All checks pass → phase15_complete_ready_for_review / OK."""
        patches = _build_clean_mocks(
            health=bridge_health_ok,
            positions=positions_flat,
            alerts=alerts_clean,
            snapshot=snapshot_ok,
            readiness=readiness_locked,
            git_metadata=clean_git_metadata,
            worktree=clean_worktree,
            origin=origin_aligned,
            tags=all_tags_present,
            guard_state_content=guard_state_clean,
            env_safety=env_safety_locked,
            rules=rules_locked,
            autonomy=autonomy_level_zero,
            clean_cycles=clean_cycles_recorded,
            doctor=doctor_pass,
            kpi=kpi_hold_expected,
            policy=hermes_policy_ok,
        )
        mocks, patches = apply_patches(patches)
        try:
            result = _run_phase15_completion_checkpoint()
            assert result["diagnosis"] == _PHASE16A_DIAGNOSIS["ready"]
            assert result["severity"] == "OK"
            assert result["phase15_complete"] is True
            assert result["operator_action_required"] is False
            assert result["readiness_summary"]["promotion_review_ready"] is True
            assert result["readiness_summary"]["promotion_allowed_now"] is False
            assert result["readiness_summary"]["order_enablement_allowed_now"] is False
            assert "Phase 16B" in result["readiness_summary"]["required_next_step"]
            # Evidence hash present
            assert result["evidence_hash"] is not None
            assert len(result["evidence_hash"]) >= 64  # SHA-256 hex
            # Export path present
            assert result["export_path"] is not None
            # h1_token_not_used
            assert result["h1_token_not_used"] is True
        finally:
            stop_patches(mocks, patches)

    def test_clean_runtime_with_h1_manual_still_ok(self,
                                                   clean_git_metadata,
                                                   clean_worktree,
                                                   origin_aligned,
                                                   all_tags_present,
                                                   bridge_health_ok,
                                                   positions_flat,
                                                   alerts_clean,
                                                   snapshot_ok,
                                                   readiness_locked,
                                                   guard_state_clean,
                                                   env_safety_locked,
                                                   rules_locked,
                                                   autonomy_level_zero,
                                                   clean_cycles_recorded,
                                                   doctor_h1_manual,
                                                   kpi_hold_expected,
                                                   hermes_policy_ok):
        """Doctor PASS with H1 MANUAL_REQUIRED still acceptable → OK."""
        patches = _build_clean_mocks(
            health=bridge_health_ok,
            positions=positions_flat,
            alerts=alerts_clean,
            snapshot=snapshot_ok,
            readiness=readiness_locked,
            git_metadata=clean_git_metadata,
            worktree=clean_worktree,
            origin=origin_aligned,
            tags=all_tags_present,
            guard_state_content=guard_state_clean,
            env_safety=env_safety_locked,
            rules=rules_locked,
            autonomy=autonomy_level_zero,
            clean_cycles=clean_cycles_recorded,
            doctor=doctor_h1_manual,
            kpi=kpi_hold_expected,
            policy=hermes_policy_ok,
        )
        mocks, patches = apply_patches(patches)
        try:
            result = _run_phase15_completion_checkpoint()
            assert result["diagnosis"] == _PHASE16A_DIAGNOSIS["ready"]
            assert result["severity"] == "OK"
            assert result["doctor_summary"]["h1_canary_status"] == "MANUAL_REQUIRED"
            assert result["doctor_summary"]["acceptable"] is True
        finally:
            stop_patches(mocks, patches)


# ===========================================================================
# T5: Safety unlocked => NO_GO
# ===========================================================================

class TestSafetyUnlocked:
    """When safety flags are not locked, diagnosis = safety_not_locked."""

    def test_env_allow_orders_true(self,
                                   clean_git_metadata,
                                   clean_worktree,
                                   origin_aligned,
                                   all_tags_present,
                                   bridge_health_ok,
                                   positions_flat,
                                   alerts_clean,
                                   snapshot_ok,
                                   readiness_locked,
                                   guard_state_clean,
                                   env_safety_unlocked,
                                   rules_locked,
                                   autonomy_level_zero,
                                   clean_cycles_recorded,
                                   doctor_pass,
                                   kpi_hold_expected,
                                   hermes_policy_ok):
        """env IBKR_ALLOW_ORDERS=true → NO_GO."""
        patches = _build_clean_mocks(
            health=bridge_health_ok,
            positions=positions_flat,
            alerts=alerts_clean,
            snapshot=snapshot_ok,
            readiness=readiness_locked,
            git_metadata=clean_git_metadata,
            worktree=clean_worktree,
            origin=origin_aligned,
            tags=all_tags_present,
            guard_state_content=guard_state_clean,
            env_safety=env_safety_unlocked,
            rules=rules_locked,
            autonomy=autonomy_level_zero,
            clean_cycles=clean_cycles_recorded,
            doctor=doctor_pass,
            kpi=kpi_hold_expected,
            policy=hermes_policy_ok,
        )
        mocks, patches = apply_patches(patches)
        try:
            result = _run_phase15_completion_checkpoint()
            assert result["diagnosis"] == _PHASE16A_DIAGNOSIS["safety_not_locked"]
            assert result["severity"] == "NO_GO"
            assert result["phase15_complete"] is False
            assert result["safety"]["safety_locked_expected"] is False
        finally:
            stop_patches(mocks, patches)

    def test_rules_enforced_true(self,
                                 clean_git_metadata,
                                 clean_worktree,
                                 origin_aligned,
                                 all_tags_present,
                                 bridge_health_ok,
                                 positions_flat,
                                 alerts_clean,
                                 snapshot_ok,
                                 readiness_locked,
                                 guard_state_clean,
                                 env_safety_locked,
                                 rules_unlocked,
                                 autonomy_level_zero,
                                 clean_cycles_recorded,
                                 doctor_pass,
                                 kpi_hold_expected,
                                 hermes_policy_ok):
        """rules.enforced=true → NO_GO."""
        patches = _build_clean_mocks(
            health=bridge_health_ok,
            positions=positions_flat,
            alerts=alerts_clean,
            snapshot=snapshot_ok,
            readiness=readiness_locked,
            git_metadata=clean_git_metadata,
            worktree=clean_worktree,
            origin=origin_aligned,
            tags=all_tags_present,
            guard_state_content=guard_state_clean,
            env_safety=env_safety_locked,
            rules=rules_unlocked,
            autonomy=autonomy_level_zero,
            clean_cycles=clean_cycles_recorded,
            doctor=doctor_pass,
            kpi=kpi_hold_expected,
            policy=hermes_policy_ok,
        )
        mocks, patches = apply_patches(patches)
        try:
            result = _run_phase15_completion_checkpoint()
            assert result["diagnosis"] == _PHASE16A_DIAGNOSIS["safety_not_locked"]
            assert result["severity"] == "NO_GO"
        finally:
            stop_patches(mocks, patches)

    def test_autonomy_not_zero(self,
                               clean_git_metadata,
                               clean_worktree,
                               origin_aligned,
                               all_tags_present,
                               bridge_health_ok,
                               positions_flat,
                               alerts_clean,
                               snapshot_ok,
                               readiness_locked,
                               guard_state_clean,
                               env_safety_locked,
                               rules_locked,
                               autonomy_level_one,
                               clean_cycles_recorded,
                               doctor_pass,
                               kpi_hold_expected,
                               hermes_policy_ok):
        """Autonomy level != 0 → NO_GO."""
        patches = _build_clean_mocks(
            health=bridge_health_ok,
            positions=positions_flat,
            alerts=alerts_clean,
            snapshot=snapshot_ok,
            readiness=readiness_locked,
            git_metadata=clean_git_metadata,
            worktree=clean_worktree,
            origin=origin_aligned,
            tags=all_tags_present,
            guard_state_content=guard_state_clean,
            env_safety=env_safety_locked,
            rules=rules_locked,
            autonomy=autonomy_level_one,
            clean_cycles=clean_cycles_recorded,
            doctor=doctor_pass,
            kpi=kpi_hold_expected,
            policy=hermes_policy_ok,
        )
        mocks, patches = apply_patches(patches)
        try:
            result = _run_phase15_completion_checkpoint()
            assert result["diagnosis"] == _PHASE16A_DIAGNOSIS["safety_not_locked"]
            assert result["severity"] == "NO_GO"
        finally:
            stop_patches(mocks, patches)

    def test_system_locked_false_from_readiness(self,
                                                clean_git_metadata,
                                                clean_worktree,
                                                origin_aligned,
                                                all_tags_present,
                                                bridge_health_ok,
                                                positions_flat,
                                                alerts_clean,
                                                guard_state_clean,
                                                env_safety_locked,
                                                rules_locked,
                                                autonomy_level_zero,
                                                clean_cycles_recorded,
                                                doctor_pass,
                                                kpi_hold_expected,
                                                hermes_policy_ok):
        """system_locked=false from readiness endpoint → NO_GO.

        Note: no snapshot mock — forces fallback to individual /readiness endpoint.
        """
        # Build a readiness response with system_locked=false
        readiness_false = {
            "summary": {
                "kill_switches": {
                    "IBKR_ALLOW_ORDERS": False,
                    "rules.enforced": False,
                    "system_locked": False,
                }
            }
        }
        patches = _build_clean_mocks(
            health=bridge_health_ok,
            positions=positions_flat,
            alerts=alerts_clean,
            snapshot=None,  # no snapshot — force individual endpoint path
            readiness=readiness_false,
            git_metadata=clean_git_metadata,
            worktree=clean_worktree,
            origin=origin_aligned,
            tags=all_tags_present,
            guard_state_content=guard_state_clean,
            env_safety=env_safety_locked,
            rules=rules_locked,
            autonomy=autonomy_level_zero,
            clean_cycles=clean_cycles_recorded,
            doctor=doctor_pass,
            kpi=kpi_hold_expected,
            policy=hermes_policy_ok,
        )
        mocks, patches = apply_patches(patches)
        try:
            result = _run_phase15_completion_checkpoint()
            assert result["diagnosis"] == _PHASE16A_DIAGNOSIS["safety_not_locked"]
            assert result["severity"] == "NO_GO"
        finally:
            stop_patches(mocks, patches)


# ===========================================================================
# T6: Active monitor alerts => NO_GO
# ===========================================================================

class TestActiveAlerts:
    """When active alerts exist, diagnosis = runtime_not_ready."""

    def test_active_alerts_produces_no_go(self,
                                          clean_git_metadata,
                                          clean_worktree,
                                          origin_aligned,
                                          all_tags_present,
                                          bridge_health_ok,
                                          positions_flat,
                                          alerts_active,
                                          readiness_locked,
                                          guard_state_clean,
                                          env_safety_locked,
                                          rules_locked,
                                          autonomy_level_zero,
                                          clean_cycles_recorded,
                                          doctor_pass,
                                          kpi_hold_expected,
                                          hermes_policy_ok):
        """Active alerts → NO_GO (runtime_not_ready)."""
        patches = _build_clean_mocks(
            health=bridge_health_ok,
            positions=positions_flat,
            alerts=alerts_active,
            snapshot=None,  # no snapshot — fall back to individual endpoint
            readiness=readiness_locked,
            git_metadata=clean_git_metadata,
            worktree=clean_worktree,
            origin=origin_aligned,
            tags=all_tags_present,
            guard_state_content=guard_state_clean,
            env_safety=env_safety_locked,
            rules=rules_locked,
            autonomy=autonomy_level_zero,
            clean_cycles=clean_cycles_recorded,
            doctor=doctor_pass,
            kpi=kpi_hold_expected,
            policy=hermes_policy_ok,
        )
        mocks, patches = apply_patches(patches)
        try:
            result = _run_phase15_completion_checkpoint()
            assert result["diagnosis"] == _PHASE16A_DIAGNOSIS["runtime_not_ready"]
            assert result["severity"] == "NO_GO"
            assert result["runtime"]["active_alerts_count"] > 0
            assert result["runtime"]["active_alerts_count"] == 1
        finally:
            stop_patches(mocks, patches)


# ===========================================================================
# T7: Guard daily_trade_count > 0 => NO_GO
# ===========================================================================

class TestGuardTradeCount:
    """When guard daily_trade_count > 0, diagnosis = guard_state_not_clean."""

    def test_nonzero_trade_count_produces_no_go(self,
                                                clean_git_metadata,
                                                clean_worktree,
                                                origin_aligned,
                                                all_tags_present,
                                                bridge_health_ok,
                                                positions_flat,
                                                alerts_clean,
                                                snapshot_ok,
                                                readiness_locked,
                                                guard_state_with_trades,
                                                env_safety_locked,
                                                rules_locked,
                                                autonomy_level_zero,
                                                clean_cycles_recorded,
                                                doctor_pass,
                                                kpi_hold_expected,
                                                hermes_policy_ok):
        """daily_trade_count=3 → NO_GO."""
        patches = _build_clean_mocks(
            health=bridge_health_ok,
            positions=positions_flat,
            alerts=alerts_clean,
            snapshot=snapshot_ok,
            readiness=readiness_locked,
            git_metadata=clean_git_metadata,
            worktree=clean_worktree,
            origin=origin_aligned,
            tags=all_tags_present,
            guard_state_content=guard_state_with_trades,
            env_safety=env_safety_locked,
            rules=rules_locked,
            autonomy=autonomy_level_zero,
            clean_cycles=clean_cycles_recorded,
            doctor=doctor_pass,
            kpi=kpi_hold_expected,
            policy=hermes_policy_ok,
        )
        mocks, patches = apply_patches(patches)
        try:
            result = _run_phase15_completion_checkpoint()
            assert result["diagnosis"] == _PHASE16A_DIAGNOSIS["guard_state_not_clean"]
            assert result["severity"] == "NO_GO"
            assert result["guard_state"]["daily_trade_count"] == 3
        finally:
            stop_patches(mocks, patches)

    def test_stale_trade_date_produces_no_go(self,
                                             clean_git_metadata,
                                             clean_worktree,
                                             origin_aligned,
                                             all_tags_present,
                                             bridge_health_ok,
                                             positions_flat,
                                             alerts_clean,
                                             snapshot_ok,
                                             readiness_locked,
                                             env_safety_locked,
                                             rules_locked,
                                             autonomy_level_zero,
                                             clean_cycles_recorded,
                                             doctor_pass,
                                             kpi_hold_expected,
                                             hermes_policy_ok):
        """Stale trade_date (yesterday, count=0) → NO_GO.

        Guard state trade_date=2026-06-25 but canonical is 2026-06-26.
        Even with daily_trade_count=0, a stale date means the guard
        has not been rotated for today — block promotion.
        """
        stale_gs = json.dumps({
            "schema_version": 1,
            "trade_date": _YESTERDAY_STR,
            "daily_trade_count": 0,
            "day_start_nl_eur": 100000.0,
            "daily_halt_active": False,
            "weekly_halt_active": False,
            "halt_reason": None,
            "last_updated_utc": "2026-06-25T10:00:00Z",
        })
        patches = _build_clean_mocks(
            health=bridge_health_ok,
            positions=positions_flat,
            alerts=alerts_clean,
            snapshot=snapshot_ok,
            readiness=readiness_locked,
            git_metadata=clean_git_metadata,
            worktree=clean_worktree,
            origin=origin_aligned,
            tags=all_tags_present,
            guard_state_content=stale_gs,
            env_safety=env_safety_locked,
            rules=rules_locked,
            autonomy=autonomy_level_zero,
            clean_cycles=clean_cycles_recorded,
            doctor=doctor_pass,
            kpi=kpi_hold_expected,
            policy=hermes_policy_ok,
        )
        mocks, patches = apply_patches(patches)
        try:
            result = _run_phase15_completion_checkpoint()
            assert result["diagnosis"] == _PHASE16A_DIAGNOSIS["guard_state_not_clean"]
            assert result["severity"] == "NO_GO"
            assert result["phase15_complete"] is False
            assert result["guard_state"]["trade_date"] == _YESTERDAY_STR
            assert result["guard_state"]["trade_date_stale"] is True
            assert result["guard_state"]["daily_trade_count"] == 0
            # Suggested actions reference guard-state-reconcile
            actions_text = " ".join(result["suggested_operator_actions"])
            assert "guard-state-reconcile" in actions_text
        finally:
            stop_patches(mocks, patches)


# ===========================================================================
# T8: Promotion flags always false
# ===========================================================================

class TestPromotionFlags:
    """promotion_allowed_now and order_enablement_allowed_now are always false."""

    def test_flags_false_in_clean_state(self,
                                        clean_git_metadata,
                                        clean_worktree,
                                        origin_aligned,
                                        all_tags_present,
                                        bridge_health_ok,
                                        positions_flat,
                                        alerts_clean,
                                        snapshot_ok,
                                        readiness_locked,
                                        guard_state_clean,
                                        env_safety_locked,
                                        rules_locked,
                                        autonomy_level_zero,
                                        clean_cycles_recorded,
                                        doctor_pass,
                                        kpi_hold_expected,
                                        hermes_policy_ok):
        """Even when clean, promotion_allowed_now=false."""
        patches = _build_clean_mocks(
            health=bridge_health_ok,
            positions=positions_flat,
            alerts=alerts_clean,
            snapshot=snapshot_ok,
            readiness=readiness_locked,
            git_metadata=clean_git_metadata,
            worktree=clean_worktree,
            origin=origin_aligned,
            tags=all_tags_present,
            guard_state_content=guard_state_clean,
            env_safety=env_safety_locked,
            rules=rules_locked,
            autonomy=autonomy_level_zero,
            clean_cycles=clean_cycles_recorded,
            doctor=doctor_pass,
            kpi=kpi_hold_expected,
            policy=hermes_policy_ok,
        )
        mocks, patches = apply_patches(patches)
        try:
            result = _run_phase15_completion_checkpoint()
            assert result["readiness_summary"]["promotion_allowed_now"] is False
            assert result["readiness_summary"]["order_enablement_allowed_now"] is False
        finally:
            stop_patches(mocks, patches)

    def test_flags_false_in_no_go_state(self,
                                        clean_git_metadata,
                                        clean_worktree,
                                        origin_aligned,
                                        one_tag_missing,
                                        bridge_health_ok,
                                        positions_flat,
                                        alerts_clean,
                                        snapshot_ok,
                                        readiness_locked,
                                        guard_state_clean,
                                        env_safety_locked,
                                        rules_locked,
                                        autonomy_level_zero,
                                        clean_cycles_recorded,
                                        doctor_pass,
                                        kpi_hold_expected,
                                        hermes_policy_ok):
        """Even when NO_GO, promotion_allowed_now=false."""
        patches = _build_clean_mocks(
            health=bridge_health_ok,
            positions=positions_flat,
            alerts=alerts_clean,
            snapshot=snapshot_ok,
            readiness=readiness_locked,
            git_metadata=clean_git_metadata,
            worktree=clean_worktree,
            origin=origin_aligned,
            tags=one_tag_missing,
            guard_state_content=guard_state_clean,
            env_safety=env_safety_locked,
            rules=rules_locked,
            autonomy=autonomy_level_zero,
            clean_cycles=clean_cycles_recorded,
            doctor=doctor_pass,
            kpi=kpi_hold_expected,
            policy=hermes_policy_ok,
        )
        mocks, patches = apply_patches(patches)
        try:
            result = _run_phase15_completion_checkpoint()
            assert result["readiness_summary"]["promotion_allowed_now"] is False
            assert result["readiness_summary"]["order_enablement_allowed_now"] is False
        finally:
            stop_patches(mocks, patches)


# ===========================================================================
# T9: JSON stdout pure
# ===========================================================================

class TestJsonOutput:
    """JSON output is pure and parseable."""

    def test_json_output_parseable(self,
                                   clean_git_metadata,
                                   clean_worktree,
                                   origin_aligned,
                                   all_tags_present,
                                   bridge_health_ok,
                                   positions_flat,
                                   alerts_clean,
                                   snapshot_ok,
                                   readiness_locked,
                                   guard_state_clean,
                                   env_safety_locked,
                                   rules_locked,
                                   autonomy_level_zero,
                                   clean_cycles_recorded,
                                   doctor_pass,
                                   kpi_hold_expected,
                                   hermes_policy_ok):
        """Result is a valid JSON-serializable dict."""
        patches = _build_clean_mocks(
            health=bridge_health_ok,
            positions=positions_flat,
            alerts=alerts_clean,
            snapshot=snapshot_ok,
            readiness=readiness_locked,
            git_metadata=clean_git_metadata,
            worktree=clean_worktree,
            origin=origin_aligned,
            tags=all_tags_present,
            guard_state_content=guard_state_clean,
            env_safety=env_safety_locked,
            rules=rules_locked,
            autonomy=autonomy_level_zero,
            clean_cycles=clean_cycles_recorded,
            doctor=doctor_pass,
            kpi=kpi_hold_expected,
            policy=hermes_policy_ok,
        )
        mocks, patches = apply_patches(patches)
        try:
            result = _run_phase15_completion_checkpoint()
            # Must be json-serializable
            serialized = json.dumps(result, indent=2, default=str)
            parsed = json.loads(serialized)
            assert parsed["command"] == result["command"]
            assert parsed["diagnosis"] == result["diagnosis"]
            assert parsed["severity"] == result["severity"]
        finally:
            stop_patches(mocks, patches)


# ===========================================================================
# T10: Export written
# ===========================================================================

class TestExportWritten:
    """Export artifact is written to disk."""

    def test_export_path_present_and_writable(self,
                                              clean_git_metadata,
                                              clean_worktree,
                                              origin_aligned,
                                              all_tags_present,
                                              bridge_health_ok,
                                              positions_flat,
                                              alerts_clean,
                                              snapshot_ok,
                                              readiness_locked,
                                              guard_state_clean,
                                              env_safety_locked,
                                              rules_locked,
                                              autonomy_level_zero,
                                              clean_cycles_recorded,
                                              doctor_pass,
                                              kpi_hold_expected,
                                              hermes_policy_ok):
        """export_path points to a real file on disk."""
        patches = _build_clean_mocks(
            health=bridge_health_ok,
            positions=positions_flat,
            alerts=alerts_clean,
            snapshot=snapshot_ok,
            readiness=readiness_locked,
            git_metadata=clean_git_metadata,
            worktree=clean_worktree,
            origin=origin_aligned,
            tags=all_tags_present,
            guard_state_content=guard_state_clean,
            env_safety=env_safety_locked,
            rules=rules_locked,
            autonomy=autonomy_level_zero,
            clean_cycles=clean_cycles_recorded,
            doctor=doctor_pass,
            kpi=kpi_hold_expected,
            policy=hermes_policy_ok,
        )
        mocks, patches = apply_patches(patches)
        try:
            result = _run_phase15_completion_checkpoint()
            assert result["export_path"] is not None
            assert os.path.exists(result["export_path"])
            # File contains valid JSON matching the result
            with open(result["export_path"]) as f:
                on_disk = json.load(f)
            assert on_disk["checkpoint_id"] == result["checkpoint_id"]
            assert on_disk["diagnosis"] == result["diagnosis"]
        finally:
            stop_patches(mocks, patches)


# ===========================================================================
# T11: No /order* calls in checkpoint path
# ===========================================================================

class TestNoOrderEndpointCalls:
    """Source-level check: no forbidden endpoints in checkpoint code."""

    FORBIDDEN_ENDPOINTS = frozenset({
        "/order",
        "/order/preflight",
        "/order/approve",
        "/order/submit",
        "/connect",
    })

    def test_no_forbidden_endpoints_in_checkpoint_function(self):
        """AST scan: no forbidden endpoint strings in checkpoint function."""
        import ast
        source = (BRIDGE_DIR / "ibkr_operator.py").read_text()
        tree = ast.parse(source)

        # Find the checkpoint function
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "_run_phase15_completion_checkpoint":
                violations = []
                for subnode in ast.walk(node):
                    if isinstance(subnode, ast.Constant) and isinstance(subnode.value, str):
                        val = subnode.value
                        for fb in self.FORBIDDEN_ENDPOINTS:
                            if fb in val:
                                # Check if it's documentation (safety/comment)
                                lower = val.lower()
                                if "no " + fb in lower or "forbidden" in lower:
                                    continue
                                if "must not" in lower or "never call" in lower:
                                    continue
                                violations.append(f"{fb} in: {val[:80]}")
                assert len(violations) == 0, (
                    f"Found forbidden endpoint references in checkpoint function: {violations}"
                )
                return
        pytest.fail("Could not find _run_phase15_completion_checkpoint function")


# ===========================================================================
# T12: No H1 token reads
# ===========================================================================

class TestNoH1Token:
    """Verify h1_token_not_used is always true."""

    def test_h1_not_used_in_all_states(self,
                                       clean_git_metadata,
                                       clean_worktree,
                                       origin_aligned,
                                       all_tags_present,
                                       bridge_health_ok,
                                       positions_flat,
                                       alerts_clean,
                                       snapshot_ok,
                                       readiness_locked,
                                       guard_state_clean,
                                       env_safety_locked,
                                       rules_locked,
                                       autonomy_level_zero,
                                       clean_cycles_recorded,
                                       doctor_pass,
                                       kpi_hold_expected,
                                       hermes_policy_ok):
        """h1_token_not_used=true in clean state."""
        patches = _build_clean_mocks(
            health=bridge_health_ok,
            positions=positions_flat,
            alerts=alerts_clean,
            snapshot=snapshot_ok,
            readiness=readiness_locked,
            git_metadata=clean_git_metadata,
            worktree=clean_worktree,
            origin=origin_aligned,
            tags=all_tags_present,
            guard_state_content=guard_state_clean,
            env_safety=env_safety_locked,
            rules=rules_locked,
            autonomy=autonomy_level_zero,
            clean_cycles=clean_cycles_recorded,
            doctor=doctor_pass,
            kpi=kpi_hold_expected,
            policy=hermes_policy_ok,
        )
        mocks, patches = apply_patches(patches)
        try:
            result = _run_phase15_completion_checkpoint()
            assert result["h1_token_not_used"] is True
        finally:
            stop_patches(mocks, patches)

    def test_no_h1_references_in_source(self):
        """Source scan: no H1 token import or reference in checkpoint function.

        Excludes: h1_token_not_used (our own safety assertion field),
                  h1_canary_status (doctor result field),
                  and references in comments/docstrings.
        """
        import ast
        source = (BRIDGE_DIR / "ibkr_operator.py").read_text()
        tree = ast.parse(source)

        # Patterns that indicate an actual H1 token read/usage
        h1_patterns = ["H1_TOKEN", "h1-token", "H1Canary",
                       "ibkr-trade-window", "h1_canary"]
        # These are our own output field names — not H1 usage
        _allowed_includes = {"h1_token_not_used", "h1_canary_status",
                            "h1_token_canary", "h1_token"}
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "_run_phase15_completion_checkpoint":
                func_source = ast.get_source_segment(source, node)
                if func_source:
                    for pat in h1_patterns:
                        if pat not in func_source:
                            continue
                        lines = func_source.splitlines()
                        found_in_code = False
                        for line in lines:
                            stripped = line.strip()
                            if pat not in stripped:
                                continue
                            # Skip comments
                            if stripped.startswith("#"):
                                continue
                            # Skip allowed field names
                            if any(allowed in stripped for allowed in _allowed_includes):
                                continue
                            # Skip strings that are non-action assertions
                            if '"h1_' in stripped or "'h1_" in stripped:
                                # Check if it's in a value assignment or return dict
                                if "no H1" in stripped.lower() or "not_used" in stripped:
                                    continue
                            found_in_code = True
                            break
                        if found_in_code:
                            pytest.fail(
                                f"Found H1 token reference '{pat}' in checkpoint function "
                                f"at line: {line}"
                            )
                return
        # Function not found — test passes (doesn't exist to have H1 refs)


# ===========================================================================
# T13: No mutation except export artifact
# ===========================================================================

class TestNoMutation:
    """Verify no_broker_mutation is always true."""

    def test_no_mutation_in_all_states(self,
                                       clean_git_metadata,
                                       clean_worktree,
                                       origin_aligned,
                                       all_tags_present,
                                       bridge_health_ok,
                                       positions_flat,
                                       alerts_clean,
                                       snapshot_ok,
                                       readiness_locked,
                                       guard_state_clean,
                                       env_safety_locked,
                                       rules_locked,
                                       autonomy_level_zero,
                                       clean_cycles_recorded,
                                       doctor_pass,
                                       kpi_hold_expected,
                                       hermes_policy_ok):
        """no_broker_mutation=true in clean state."""
        patches = _build_clean_mocks(
            health=bridge_health_ok,
            positions=positions_flat,
            alerts=alerts_clean,
            snapshot=snapshot_ok,
            readiness=readiness_locked,
            git_metadata=clean_git_metadata,
            worktree=clean_worktree,
            origin=origin_aligned,
            tags=all_tags_present,
            guard_state_content=guard_state_clean,
            env_safety=env_safety_locked,
            rules=rules_locked,
            autonomy=autonomy_level_zero,
            clean_cycles=clean_cycles_recorded,
            doctor=doctor_pass,
            kpi=kpi_hold_expected,
            policy=hermes_policy_ok,
        )
        mocks, patches = apply_patches(patches)
        try:
            result = _run_phase15_completion_checkpoint()
            assert result["no_broker_mutation"] is True
            assert result["no_order_window_opened"] is True
            # explicit_non_actions exists
            assert isinstance(result.get("explicit_non_actions"), list)
            assert len(result["explicit_non_actions"]) >= 5
        finally:
            stop_patches(mocks, patches)


# ===========================================================================
# T14: Disconnected runtime => HOLD
# ===========================================================================

class TestDisconnectedRuntime:
    """When bridge is reachable but IBKR disconnected, diagnosis=runtime_not_ready / HOLD."""

    def test_disconnected_produces_hold(self,
                                        clean_git_metadata,
                                        clean_worktree,
                                        origin_aligned,
                                        all_tags_present,
                                        bridge_health_disconnected,
                                        positions_flat,
                                        alerts_clean,
                                        readiness_locked,
                                        guard_state_clean,
                                        env_safety_locked,
                                        rules_locked,
                                        autonomy_level_zero,
                                        clean_cycles_recorded,
                                        doctor_pass,
                                        kpi_hold_expected,
                                        hermes_policy_ok):
        """IBKR disconnected → HOLD (not NO_GO)."""
        patches = _build_clean_mocks(
            health=bridge_health_disconnected,
            positions=positions_flat,
            alerts=alerts_clean,
            snapshot=None,
            readiness=readiness_locked,
            git_metadata=clean_git_metadata,
            worktree=clean_worktree,
            origin=origin_aligned,
            tags=all_tags_present,
            guard_state_content=guard_state_clean,
            env_safety=env_safety_locked,
            rules=rules_locked,
            autonomy=autonomy_level_zero,
            clean_cycles=clean_cycles_recorded,
            doctor=doctor_pass,
            kpi=kpi_hold_expected,
            policy=hermes_policy_ok,
        )
        mocks, patches = apply_patches(patches)
        try:
            result = _run_phase15_completion_checkpoint()
            assert result["diagnosis"] == _PHASE16A_DIAGNOSIS["runtime_not_ready"]
            assert result["severity"] == "HOLD"
            assert result["runtime"]["bridge_connected"] is False
        finally:
            stop_patches(mocks, patches)


# ===========================================================================
# T15: Doctor not acceptable => NO_GO
# ===========================================================================

class TestDoctorNotAcceptable:
    """When doctor fails non-H1 checks, diagnosis = doctor_not_acceptable."""

    def test_doctor_failure_produces_no_go(self,
                                           clean_git_metadata,
                                           clean_worktree,
                                           origin_aligned,
                                           all_tags_present,
                                           bridge_health_ok,
                                           positions_flat,
                                           alerts_clean,
                                           snapshot_ok,
                                           readiness_locked,
                                           guard_state_clean,
                                           env_safety_locked,
                                           rules_locked,
                                           autonomy_level_zero,
                                           clean_cycles_recorded,
                                           doctor_fail,
                                           kpi_hold_expected,
                                           hermes_policy_ok):
        """Doctor non-canary failure → NO_GO."""
        patches = _build_clean_mocks(
            health=bridge_health_ok,
            positions=positions_flat,
            alerts=alerts_clean,
            snapshot=snapshot_ok,
            readiness=readiness_locked,
            git_metadata=clean_git_metadata,
            worktree=clean_worktree,
            origin=origin_aligned,
            tags=all_tags_present,
            guard_state_content=guard_state_clean,
            env_safety=env_safety_locked,
            rules=rules_locked,
            autonomy=autonomy_level_zero,
            clean_cycles=clean_cycles_recorded,
            doctor=doctor_fail,
            kpi=kpi_hold_expected,
            policy=hermes_policy_ok,
        )
        mocks, patches = apply_patches(patches)
        try:
            result = _run_phase15_completion_checkpoint()
            assert result["diagnosis"] == _PHASE16A_DIAGNOSIS["doctor_not_acceptable"]
            assert result["severity"] == "NO_GO"
        finally:
            stop_patches(mocks, patches)


# ===========================================================================
# T16: KPI not acceptable => NO_GO
# ===========================================================================

class TestKpiNotAcceptable:
    """When KPI returns NO-GO blockers, diagnosis = kpi_not_acceptable."""

    def test_kpi_no_go_produces_no_go(self,
                                      clean_git_metadata,
                                      clean_worktree,
                                      origin_aligned,
                                      all_tags_present,
                                      bridge_health_ok,
                                      positions_flat,
                                      alerts_clean,
                                      snapshot_ok,
                                      readiness_locked,
                                      guard_state_clean,
                                      env_safety_locked,
                                      rules_locked,
                                      autonomy_level_zero,
                                      clean_cycles_recorded,
                                      doctor_pass,
                                      kpi_no_go,
                                      hermes_policy_ok):
        """KPI NO-GO → NO_GO."""
        patches = _build_clean_mocks(
            health=bridge_health_ok,
            positions=positions_flat,
            alerts=alerts_clean,
            snapshot=snapshot_ok,
            readiness=readiness_locked,
            git_metadata=clean_git_metadata,
            worktree=clean_worktree,
            origin=origin_aligned,
            tags=all_tags_present,
            guard_state_content=guard_state_clean,
            env_safety=env_safety_locked,
            rules=rules_locked,
            autonomy=autonomy_level_zero,
            clean_cycles=clean_cycles_recorded,
            doctor=doctor_pass,
            kpi=kpi_no_go,
            policy=hermes_policy_ok,
        )
        mocks, patches = apply_patches(patches)
        try:
            result = _run_phase15_completion_checkpoint()
            assert result["diagnosis"] == _PHASE16A_DIAGNOSIS["kpi_not_acceptable"]
            assert result["severity"] == "NO_GO"
        finally:
            stop_patches(mocks, patches)


# ===========================================================================
# T17: Policy boundary missing => NO_GO
# ===========================================================================

class TestPolicyBoundary:
    """When Hermes policy is missing or compromised, diagnosis=policy_boundary_missing."""

    def test_policy_missing_produces_no_go(self,
                                           clean_git_metadata,
                                           clean_worktree,
                                           origin_aligned,
                                           all_tags_present,
                                           bridge_health_ok,
                                           positions_flat,
                                           alerts_clean,
                                           snapshot_ok,
                                           readiness_locked,
                                           guard_state_clean,
                                           env_safety_locked,
                                           rules_locked,
                                           autonomy_level_zero,
                                           clean_cycles_recorded,
                                           doctor_pass,
                                           kpi_hold_expected,
                                           hermes_policy_missing):
        """Hermes policy missing → NO_GO."""
        patches = _build_clean_mocks(
            health=bridge_health_ok,
            positions=positions_flat,
            alerts=alerts_clean,
            snapshot=snapshot_ok,
            readiness=readiness_locked,
            git_metadata=clean_git_metadata,
            worktree=clean_worktree,
            origin=origin_aligned,
            tags=all_tags_present,
            guard_state_content=guard_state_clean,
            env_safety=env_safety_locked,
            rules=rules_locked,
            autonomy=autonomy_level_zero,
            clean_cycles=clean_cycles_recorded,
            doctor=doctor_pass,
            kpi=kpi_hold_expected,
            policy=hermes_policy_missing,
        )
        mocks, patches = apply_patches(patches)
        try:
            result = _run_phase15_completion_checkpoint()
            assert result["diagnosis"] == _PHASE16A_DIAGNOSIS["policy_boundary_missing"]
            assert result["severity"] == "NO_GO"
        finally:
            stop_patches(mocks, patches)
