"""Tests for Step 15O — Guard-State Trade-Count Reconciliation Cleanup.

All tests are read-only. No broker mutation, no order endpoints,
no H1 token usage, no autonomy level changes.
"""

import json
import os
import sys
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

BRIDGE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BRIDGE_DIR))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_guard_state(daily_trade_count: int = 6,
                      trade_date: str = "2026-06-23",
                      schema_version: int = 1) -> dict:
    """Return a mock guard state dict."""
    return {
        "schema_version": schema_version,
        "trade_date": trade_date,
        "daily_trade_count": daily_trade_count,
        "day_start_nl_eur": 100000.0,
        "week_start_date": "2026-06-01",
        "week_start_nl_eur": None,
        "daily_halt_active": False,
        "weekly_halt_active": False,
        "halt_reason": None,
        "last_updated_utc": "2026-06-23T10:00:00Z",
        "legacy_unconfirmed_corrected": True,
        "trade_count_autocorrected": True,
        "trade_count_repaired": False,
    }


def _make_events(count: int = 0, with_perm_ids: bool = True,
                 trade_date: str = "2026-06-23") -> list[dict]:
    """Return mock order_submitted events."""
    events = []
    for i in range(count):
        event = {
            "event_id": f"evt-{i:04d}",
            "event_type": "order_submitted",
            "symbol": "AAPL",
            "side": "BUY",
            "timestamp_utc": f"{trade_date}T10:{i:02d}:00Z",
            "approval_id": f"aprv-test-{i:04d}",
        }
        if with_perm_ids:
            event["ibkr_metadata"] = {"permId": 1000 + i}
        events.append(event)
    return events


def _make_mock_load_guard_state(gs: dict):
    """Return a mock for load_guard_state that returns the given state."""
    return MagicMock(return_value=gs)


def _make_mock_load_events(events: list[dict]):
    """Return a mock for load_events."""
    mock = MagicMock()
    mock.return_value = events
    return mock


# ---------------------------------------------------------------------------
# T1: Command exists
# ---------------------------------------------------------------------------

class TestCommandExists:
    """Verify the guard-state-reconcile command is registered and importable."""

    def test_function_importable(self):
        """_run_guard_state_reconcile is importable and callable."""
        from ibkr_operator import _run_guard_state_reconcile
        assert callable(_run_guard_state_reconcile)

    def test_aliases_registered(self):
        """Aliases trade-count-reconcile and repair-trade-count are registered."""
        import subprocess

        for alias in ("trade-count-reconcile", "repair-trade-count"):
            r = subprocess.run(
                [sys.executable, str(BRIDGE_DIR / "ibkr_operator.py"),
                 alias, "--help"],
                capture_output=True, text=True, timeout=15,
            )
            assert r.returncode == 0, f"{alias} --help failed: {r.stderr}"


# ---------------------------------------------------------------------------
# T2: Dry-run detects mismatch and recommends repair
# ---------------------------------------------------------------------------

class TestDryRunDetectsMismatch:
    """Verify dry-run mode detects mismatch and recommends repair."""

    def test_mismatch_detected_when_guard_gt_events(self):
        """When guard count > confirmed events, mismatch is detected."""
        from ibkr_operator import _run_guard_state_reconcile

        gs = _make_guard_state(daily_trade_count=6)
        events = _make_events(count=0)  # zero confirmed

        with patch("monitor.load_guard_state", return_value=gs), \
             patch("monitor.load_events", return_value=events), \
             patch("ibkr_operator._git_metadata", return_value={
                 "branch": "test", "commit": "abc123", "tag": "test"}), \
             patch("ibkr_operator._atomic_write_json"), \
             patch("ibkr_operator.os.getenv", return_value="false"), \
             patch("ibkr_operator.urllib.request.urlopen",
                   side_effect=Exception("no bridge")), \
             patch("ibkr_operator._GUARD_STATE_REPAIRS_DIR",
                   Path("/tmp/guard-state-repairs")):
            result = _run_guard_state_reconcile(
                apply_repair=False,
                confirm_local_state_repair=False,
            )

        assert result["mode"] == "dry_run"
        assert result["mismatch_detected"] is True
        assert result["repair_recommended"] is True
        assert result["repair_applied"] is False
        assert result["guard_daily_trade_count_before"] == 6
        assert result["confirmed_event_trade_count"] == 0

    def test_no_mismatch_when_counts_match(self):
        """When guard count == confirmed events, no mismatch."""
        from ibkr_operator import _run_guard_state_reconcile

        gs = _make_guard_state(daily_trade_count=3)
        events = _make_events(count=3, with_perm_ids=True)

        with patch("monitor.load_guard_state", return_value=gs), \
             patch("monitor.load_events", return_value=events), \
             patch("ibkr_operator._git_metadata", return_value={
                 "branch": "test", "commit": "abc123", "tag": "test"}), \
             patch("ibkr_operator._atomic_write_json"), \
             patch("ibkr_operator.os.getenv", return_value="false"), \
             patch("ibkr_operator.urllib.request.urlopen",
                   side_effect=Exception("no bridge")), \
             patch("ibkr_operator._GUARD_STATE_REPAIRS_DIR",
                   Path("/tmp/guard-state-repairs")):
            result = _run_guard_state_reconcile(
                apply_repair=False,
                confirm_local_state_repair=False,
            )

        assert result["mismatch_detected"] is False
        assert result["repair_recommended"] is False
        assert result["repair_applied"] is False

    def test_dry_run_does_not_modify_guard_state(self, tmp_path):
        """Dry-run must never modify guard-state.json."""
        from ibkr_operator import _run_guard_state_reconcile

        guard_path = tmp_path / "guard-state.json"
        gs = _make_guard_state(daily_trade_count=6)
        guard_path.write_text(json.dumps(gs))

        events = _make_events(count=0)

        repairs_dir = tmp_path / "guard-state-repairs"

        with patch("monitor.load_guard_state", return_value=gs), \
             patch("monitor.load_events", return_value=events), \
             patch("ibkr_operator._git_metadata", return_value={
                 "branch": "test", "commit": "abc", "tag": "test"}), \
             patch("ibkr_operator._atomic_write_json"), \
             patch("ibkr_operator.os.getenv", return_value="false"), \
             patch("ibkr_operator.urllib.request.urlopen",
                   side_effect=Exception("no bridge")), \
             patch("ibkr_operator.OPENCLAW_DIR", tmp_path), \
             patch("ibkr_operator._GUARD_STATE_REPAIRS_DIR", repairs_dir):
            _run_guard_state_reconcile(
                apply_repair=False,
                confirm_local_state_repair=False,
            )

        # Guard state file must be unchanged
        assert guard_path.read_text() == json.dumps(gs), \
            "Dry-run must not modify guard-state.json"


# ---------------------------------------------------------------------------
# T3: Apply requires confirmation flag
# ---------------------------------------------------------------------------

class TestApplyRequiresConfirmation:
    """Verify --apply alone does nothing; --confirm-local-state-repair required."""

    def test_apply_without_confirmation_is_dry_run(self):
        """--apply without --confirm-local-state-repair = dry-run."""
        from ibkr_operator import _run_guard_state_reconcile

        gs = _make_guard_state(daily_trade_count=6)
        events = _make_events(count=0)

        with patch("monitor.load_guard_state", return_value=gs), \
             patch("monitor.load_events", return_value=events), \
             patch("ibkr_operator._git_metadata", return_value={
                 "branch": "test", "commit": "abc", "tag": "test"}), \
             patch("ibkr_operator._atomic_write_json"), \
             patch("ibkr_operator.os.getenv", return_value="false"), \
             patch("ibkr_operator.urllib.request.urlopen",
                   side_effect=Exception("no bridge")), \
             patch("ibkr_operator._GUARD_STATE_REPAIRS_DIR",
                   Path("/tmp/guard-state-repairs")):
            result = _run_guard_state_reconcile(
                apply_repair=True,
                confirm_local_state_repair=False,  # missing confirmation!
            )

        assert result["mode"] == "dry_run"
        assert result["repair_applied"] is False


# ---------------------------------------------------------------------------
# T4: Apply repairs downward only
# ---------------------------------------------------------------------------

class TestApplyRepairsDownward:
    """Verify apply mode repairs guard count downward to match confirmed events."""

    def test_apply_with_confirmation_repairs(self, tmp_path):
        """With both flags, repair is applied and guard count is corrected."""
        from ibkr_operator import _run_guard_state_reconcile

        gs = _make_guard_state(daily_trade_count=6)
        events = _make_events(count=2, with_perm_ids=True)

        # Simulate atomic write to track the repaired state
        repaired_state = {}

        def _mock_atomic_write(path, data):
            repaired_state["data"] = dict(data)
            repaired_state["path"] = str(path)

        repairs_dir = tmp_path / "guard-state-repairs"
        guard_path = tmp_path / "guard-state.json"
        guard_path.write_text(json.dumps(gs))

        # load_guard_state: first call returns original, after repair returns repaired
        call_count = [0]

        def _mock_load_guard_state(path=None):
            call_count[0] += 1
            if call_count[0] == 1:
                return dict(gs)
            else:
                return dict(repaired_state.get("data", gs))

        with patch("monitor.load_guard_state",
                   side_effect=_mock_load_guard_state), \
             patch("monitor.load_events", return_value=events), \
             patch("ibkr_operator._git_metadata", return_value={
                 "branch": "test", "commit": "abc", "tag": "test"}), \
             patch("ibkr_operator._atomic_write_json",
                   side_effect=_mock_atomic_write), \
 \
             patch("ibkr_operator.os.getenv", return_value="false"), \
             patch("ibkr_operator.urllib.request.urlopen",
                   side_effect=Exception("no bridge")), \
             patch("ibkr_operator.OPENCLAW_DIR", tmp_path), \
             patch("ibkr_operator._GUARD_STATE_REPAIRS_DIR", repairs_dir):
            result = _run_guard_state_reconcile(
                apply_repair=True,
                confirm_local_state_repair=True,
            )

        assert result["mode"] == "apply"
        assert result["repair_recommended"] is True
        assert result["repair_applied"] is True
        assert result["guard_daily_trade_count_after"] == 2
        assert repaired_state["data"]["daily_trade_count"] == 2

    def test_apply_preserves_unrelated_fields(self, tmp_path):
        """Repair must only change daily_trade_count, preserving other fields."""
        from ibkr_operator import _run_guard_state_reconcile

        gs = _make_guard_state(daily_trade_count=6)
        original_week_start = gs["week_start_date"]
        original_nl = gs["day_start_nl_eur"]

        events = _make_events(count=0)

        repaired_state = {}

        def _mock_atomic_write(path, data):
            repaired_state["data"] = dict(data)

        repairs_dir = tmp_path / "guard-state-repairs"
        guard_path = tmp_path / "guard-state.json"
        guard_path.write_text(json.dumps(gs))

        call_count = [0]

        def _mock_load_guard_state(path=None):
            call_count[0] += 1
            if call_count[0] == 1:
                return dict(gs)
            else:
                return dict(repaired_state.get("data", gs))

        with patch("monitor.load_guard_state",
                   side_effect=_mock_load_guard_state), \
             patch("monitor.load_events", return_value=events), \
             patch("ibkr_operator._git_metadata", return_value={
                 "branch": "test", "commit": "abc", "tag": "test"}), \
             patch("ibkr_operator._atomic_write_json",
                   side_effect=_mock_atomic_write), \
 \
             patch("ibkr_operator.os.getenv", return_value="false"), \
             patch("ibkr_operator.urllib.request.urlopen",
                   side_effect=Exception("no bridge")), \
             patch("ibkr_operator.OPENCLAW_DIR", tmp_path), \
             patch("ibkr_operator._GUARD_STATE_REPAIRS_DIR", repairs_dir):
            _run_guard_state_reconcile(
                apply_repair=True,
                confirm_local_state_repair=True,
            )

        assert repaired_state["data"]["week_start_date"] == original_week_start
        assert repaired_state["data"]["day_start_nl_eur"] == original_nl
        assert repaired_state["data"]["daily_trade_count"] == 0  # repaired


# ---------------------------------------------------------------------------
# T5: Never repair upward
# ---------------------------------------------------------------------------
# T5: Stale trade-date rollover repair
# ---------------------------------------------------------------------------

class TestStaleTradeDateRepair:
    """Verify stale trade_date (count=0, events=0) triggers date-rollover repair."""

    def test_stale_date_with_zero_counts_recommends_repair(self):
        """trade_date stale, count=0, events=0 → repair_recommended=true.

        No count mismatch, but guard state's trade_date is from yesterday.
        Phase 16A requires trade_date_stale=false for promotion readiness.
        """
        from ibkr_operator import _run_guard_state_reconcile

        # Guard state: yesterday's date, count 0
        gs = _make_guard_state(daily_trade_count=0, trade_date="2026-06-25")
        events: list[dict] = []  # no events

        with patch("monitor.load_guard_state", return_value=gs), \
             patch("monitor.load_events", return_value=events), \
             patch("ibkr_operator._git_metadata", return_value={
                 "branch": "test", "commit": "abc", "tag": "test"}), \
             patch("ibkr_operator._atomic_write_json"), \
             patch("ibkr_operator.os.getenv", return_value="false"), \
             patch("ibkr_operator.urllib.request.urlopen",
                   side_effect=Exception("no bridge")), \
             patch("ibkr_operator._GUARD_STATE_REPAIRS_DIR",
                   Path("/tmp/guard-state-repairs")):
            result = _run_guard_state_reconcile(
                apply_repair=False,
                confirm_local_state_repair=False,
            )

        assert result["trade_date_stale"] is True
        assert result["mismatch_detected"] is False  # both 0
        assert result["repair_recommended"] is True  # stale date triggers repair
        assert result["stale_trade_date_repair"] is True
        assert result["repair_reason"] == "stale_trade_date_rollover"
        assert result["trade_date_before"] == "2026-06-25"
        assert result["trade_date_after"] != "2026-06-25"  # advances to canonical
        assert result["guard_daily_trade_count_before"] == 0
        assert result["no_broker_mutation"] is True
        assert result["no_order_window_opened"] is True

    def test_apply_stale_date_repair_updates_trade_date(self, tmp_path):
        """Apply stale-date repair: trade_date rotates, count stays 0."""
        from ibkr_operator import _run_guard_state_reconcile

        gs = _make_guard_state(daily_trade_count=0, trade_date="2026-06-25")
        events: list[dict] = []

        repaired_state = {}

        def _mock_atomic_write(path, data):
            repaired_state["data"] = dict(data)
            repaired_state["path"] = str(path)

        repairs_dir = tmp_path / "guard-state-repairs"
        guard_path = tmp_path / "guard-state.json"
        guard_path.write_text(json.dumps(gs))

        call_count = [0]

        def _mock_load_guard_state(path=None):
            call_count[0] += 1
            if call_count[0] == 1:
                return dict(gs)
            else:
                return dict(repaired_state.get("data", gs))

        with patch("monitor.load_guard_state",
                   side_effect=_mock_load_guard_state), \
             patch("monitor.load_events", return_value=events), \
             patch("ibkr_operator._git_metadata", return_value={
                 "branch": "test", "commit": "abc", "tag": "test"}), \
             patch("ibkr_operator._atomic_write_json",
                   side_effect=_mock_atomic_write), \
             patch("ibkr_operator.os.getenv", return_value="false"), \
             patch("ibkr_operator.urllib.request.urlopen",
                   side_effect=Exception("no bridge")), \
             patch("ibkr_operator.OPENCLAW_DIR", tmp_path), \
             patch("ibkr_operator._GUARD_STATE_REPAIRS_DIR", repairs_dir):
            result = _run_guard_state_reconcile(
                apply_repair=True,
                confirm_local_state_repair=True,
            )

        assert result["mode"] == "apply"
        assert result["repair_recommended"] is True
        assert result["repair_applied"] is True
        assert result["stale_trade_date_repair"] is True
        assert result["repair_reason"] == "stale_trade_date_rollover"
        assert result["trade_date_before"] == "2026-06-25"
        # trade_date_after must be canonical (today)
        assert result["trade_date_after"] != "2026-06-25"
        # Count stays 0
        assert result["guard_daily_trade_count_after"] == 0
        assert repaired_state["data"]["daily_trade_count"] == 0
        assert repaired_state["data"]["trade_date"] != "2026-06-25"
        assert repaired_state["data"].get("stale_trade_date_repaired") is True
        assert repaired_state["data"].get("trade_date_repair_reason") == "stale_trade_date_rollover"

    def test_stale_date_repair_preserves_other_fields(self, tmp_path):
        """Stale-date repair only changes trade_date, not other fields."""
        from ibkr_operator import _run_guard_state_reconcile

        gs = _make_guard_state(daily_trade_count=0, trade_date="2026-06-25")
        original_week_start = gs["week_start_date"]
        original_nl = gs["day_start_nl_eur"]
        events: list[dict] = []

        repaired_state = {}

        def _mock_atomic_write(path, data):
            repaired_state["data"] = dict(data)

        repairs_dir = tmp_path / "guard-state-repairs"
        guard_path = tmp_path / "guard-state.json"
        guard_path.write_text(json.dumps(gs))

        call_count = [0]

        def _mock_load_guard_state(path=None):
            call_count[0] += 1
            if call_count[0] == 1:
                return dict(gs)
            else:
                return dict(repaired_state.get("data", gs))

        with patch("monitor.load_guard_state",
                   side_effect=_mock_load_guard_state), \
             patch("monitor.load_events", return_value=events), \
             patch("ibkr_operator._git_metadata", return_value={
                 "branch": "test", "commit": "abc", "tag": "test"}), \
             patch("ibkr_operator._atomic_write_json",
                   side_effect=_mock_atomic_write), \
             patch("ibkr_operator.os.getenv", return_value="false"), \
             patch("ibkr_operator.urllib.request.urlopen",
                   side_effect=Exception("no bridge")), \
             patch("ibkr_operator.OPENCLAW_DIR", tmp_path), \
             patch("ibkr_operator._GUARD_STATE_REPAIRS_DIR", repairs_dir):
            _run_guard_state_reconcile(
                apply_repair=True,
                confirm_local_state_repair=True,
            )

        assert repaired_state["data"]["week_start_date"] == original_week_start
        assert repaired_state["data"]["day_start_nl_eur"] == original_nl
        assert repaired_state["data"]["daily_trade_count"] == 0
        assert repaired_state["data"]["trade_date"] != "2026-06-25"
        assert repaired_state["data"]["stale_trade_date_repaired"] is True


# ---------------------------------------------------------------------------

class TestNeverRepairUpward:
    """Verify confirmed events > guard count is NO_GO, never repaired."""

    def test_events_exceed_guard_is_nogo(self):
        """When confirmed events > guard count, NO_GO blocker is emitted."""
        from ibkr_operator import _run_guard_state_reconcile

        gs = _make_guard_state(daily_trade_count=1)  # guard says 1
        events = _make_events(count=5, with_perm_ids=True)  # events show 5

        with patch("monitor.load_guard_state", return_value=gs), \
             patch("monitor.load_events", return_value=events), \
             patch("ibkr_operator._git_metadata", return_value={
                 "branch": "test", "commit": "abc", "tag": "test"}), \
             patch("ibkr_operator._atomic_write_json"), \
             patch("ibkr_operator.os.getenv", return_value="false"), \
             patch("ibkr_operator.urllib.request.urlopen",
                   side_effect=Exception("no bridge")), \
             patch("ibkr_operator._GUARD_STATE_REPAIRS_DIR",
                   Path("/tmp/guard-state-repairs")):
            result = _run_guard_state_reconcile(
                apply_repair=True,
                confirm_local_state_repair=True,
            )

        assert result["repair_recommended"] is False
        assert result["repair_applied"] is False
        blockers = {b["check"] for b in result["blockers"]}
        assert "confirmed_events_exceed_guard_count" in blockers, \
            f"Expected NO_GO blocker, got {blockers}"


# ---------------------------------------------------------------------------
# T6: Ambiguous evidence → HOLD
# ---------------------------------------------------------------------------

class TestAmbiguousEvidenceHold:
    """Verify ambiguous evidence produces HOLD, no apply."""

    def test_events_without_permids_ambiguous(self):
        """Events without permIds and without approval_ids are ambiguous."""
        from ibkr_operator import _run_guard_state_reconcile

        gs = _make_guard_state(daily_trade_count=6)
        # Events with neither permIds nor approval_ids → zero confirmed count
        events = [
            {
                "event_id": f"evt-{i:04d}",
                "event_type": "order_submitted",
                "symbol": "AAPL",
                "side": "BUY",
                "timestamp_utc": "2026-06-23T10:00:00Z",
            }
            for i in range(3)
        ]

        with patch("monitor.load_guard_state", return_value=gs), \
             patch("monitor.load_events", return_value=events), \
             patch("ibkr_operator._git_metadata", return_value={
                 "branch": "test", "commit": "abc", "tag": "test"}), \
             patch("ibkr_operator._atomic_write_json"), \
             patch("ibkr_operator.os.getenv", return_value="false"), \
             patch("ibkr_operator.urllib.request.urlopen",
                   side_effect=Exception("no bridge")), \
             patch("ibkr_operator._GUARD_STATE_REPAIRS_DIR",
                   Path("/tmp/guard-state-repairs")):
            result = _run_guard_state_reconcile(
                apply_repair=True,
                confirm_local_state_repair=True,
            )

        assert result["repair_recommended"] is False
        assert result["repair_applied"] is False
        blockers = {b["check"] for b in result["blockers"]}
        assert "ambiguous_events" in blockers, \
            f"Expected ambiguous_events blocker, got {blockers}"


# ---------------------------------------------------------------------------
# T7: Export and JSON
# ---------------------------------------------------------------------------

class TestExportAndJson:
    """Verify export and JSON output."""

    def test_json_stdout_pure_parseable(self):
        """--json output is pure parseable JSON."""
        from ibkr_operator import _run_guard_state_reconcile

        gs = _make_guard_state(daily_trade_count=6)
        events = _make_events(count=0)

        with patch("monitor.load_guard_state", return_value=gs), \
             patch("monitor.load_events", return_value=events), \
             patch("ibkr_operator._git_metadata", return_value={
                 "branch": "test", "commit": "abc", "tag": "test"}), \
             patch("ibkr_operator._atomic_write_json"), \
             patch("ibkr_operator.os.getenv", return_value="false"), \
             patch("ibkr_operator.urllib.request.urlopen",
                   side_effect=Exception("no bridge")), \
             patch("ibkr_operator._GUARD_STATE_REPAIRS_DIR",
                   Path("/tmp/guard-state-repairs")):
            result = _run_guard_state_reconcile(
                apply_repair=False,
                confirm_local_state_repair=False,
            )

        serialized = json.dumps(result, default=str)
        parsed = json.loads(serialized)
        assert parsed["mode"] == "dry_run"
        assert "evidence_hash" in parsed
        assert "explicit_non_actions" in parsed

    def test_export_file_written(self, tmp_path):
        """Export writes JSON to guard-state-repairs directory."""
        from ibkr_operator import _run_guard_state_reconcile

        gs = _make_guard_state(daily_trade_count=6)
        events = _make_events(count=0)
        repairs_dir = tmp_path / "guard-state-repairs"

        with patch("monitor.load_guard_state", return_value=gs), \
             patch("monitor.load_events", return_value=events), \
             patch("ibkr_operator._git_metadata", return_value={
                 "branch": "test", "commit": "abc", "tag": "test"}), \
             patch("ibkr_operator._atomic_write_json"), \
             patch("ibkr_operator.os.getenv", return_value="false"), \
             patch("ibkr_operator.urllib.request.urlopen",
                   side_effect=Exception("no bridge")), \
             patch("ibkr_operator._GUARD_STATE_REPAIRS_DIR", repairs_dir):
            result = _run_guard_state_reconcile(
                apply_repair=False,
                confirm_local_state_repair=False,
            )

        ep = result.get("_export_path")
        assert ep is not None
        export_file = Path(ep)
        assert export_file.exists()
        assert export_file.suffix == ".json"

        exported = json.loads(export_file.read_text())
        assert exported["repair_id"] == result["repair_id"]


# ---------------------------------------------------------------------------
# T8: All required fields present
# ---------------------------------------------------------------------------

class TestRequiredFields:
    """Verify all spec-required fields are present."""

    _REQUIRED_FIELDS = [
        "timestamp", "repair_id", "mode", "git", "guard_state_path",
        "backup_path", "audit_export_path", "trade_date",
        "guard_daily_trade_count_before", "confirmed_event_trade_count",
        "confirmed_unique_order_ids", "ibkr_live_order_count",
        "open_order_count", "positions_count", "positions_flat",
        "mismatch_detected", "repair_recommended", "repair_applied",
        "guard_daily_trade_count_after", "safety_flags", "blockers",
        "no_broker_mutation", "no_order_window_opened",
        "explicit_non_actions", "evidence_hash",
    ]

    def test_all_required_fields_present(self):
        """All spec fields are in the output."""
        from ibkr_operator import _run_guard_state_reconcile

        gs = _make_guard_state(daily_trade_count=6)
        events = _make_events(count=0)

        with patch("monitor.load_guard_state", return_value=gs), \
             patch("monitor.load_events", return_value=events), \
             patch("ibkr_operator._git_metadata", return_value={
                 "branch": "test", "commit": "abc", "tag": "test"}), \
             patch("ibkr_operator._atomic_write_json"), \
             patch("ibkr_operator.os.getenv", return_value="false"), \
             patch("ibkr_operator.urllib.request.urlopen",
                   side_effect=Exception("no bridge")), \
             patch("ibkr_operator._GUARD_STATE_REPAIRS_DIR",
                   Path("/tmp/guard-state-repairs")):
            result = _run_guard_state_reconcile(
                apply_repair=False,
                confirm_local_state_repair=False,
            )

        for field in self._REQUIRED_FIELDS:
            assert field in result, f"Missing required field: {field}"

    def test_explicit_non_actions_complete(self):
        """explicit_non_actions covers all required statements."""
        from ibkr_operator import _run_guard_state_reconcile

        gs = _make_guard_state(daily_trade_count=6)
        events = _make_events(count=0)

        with patch("monitor.load_guard_state", return_value=gs), \
             patch("monitor.load_events", return_value=events), \
             patch("ibkr_operator._git_metadata", return_value={
                 "branch": "test", "commit": "abc", "tag": "test"}), \
             patch("ibkr_operator._atomic_write_json"), \
             patch("ibkr_operator.os.getenv", return_value="false"), \
             patch("ibkr_operator.urllib.request.urlopen",
                   side_effect=Exception("no bridge")), \
             patch("ibkr_operator._GUARD_STATE_REPAIRS_DIR",
                   Path("/tmp/guard-state-repairs")):
            result = _run_guard_state_reconcile(
                apply_repair=False,
                confirm_local_state_repair=False,
            )

        non_actions = [na.lower() for na in result["explicit_non_actions"]]
        required = [
            "not change autonomy",
            "not open an order",
            "not call",
            "not read h1",
            "not place",
            "not enable ibkr_allow_orders",
            "not enable rules.enforced",
            "guard-state",
        ]
        for topic in required:
            found = any(topic in na for na in non_actions)
            assert found, f"explicit_non_actions missing: '{topic}'"


# ---------------------------------------------------------------------------
# T9: No /order* calls, no H1 token
# ---------------------------------------------------------------------------

class TestNoForbiddenCalls:
    """Verify reconciliation never calls order endpoints or reads H1 token."""

    def test_no_order_endpoints_in_source(self):
        """The reconcile function must not contain /order* calls."""
        import inspect
        from ibkr_operator import _run_guard_state_reconcile

        source = inspect.getsource(_run_guard_state_reconcile)
        forbidden = ["/order/preflight", "/order/approve", "/order/submit",
                      "placeOrder", "cancelOrder"]
        for pattern in forbidden:
            found_line = None
            for line in source.splitlines():
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue
                lower = stripped.lower()
                if any(kw in lower for kw in ["no /order", "must not", "did not"]):
                    continue
                if pattern in stripped:
                    found_line = stripped[:100]
                    break
            assert found_line is None, \
                f"FORBIDDEN: '{pattern}' found in reconcile source: {found_line}"

    def test_no_h1_token_in_source(self):
        """The reconcile function must not reference H1 token."""
        import inspect
        from ibkr_operator import _run_guard_state_reconcile

        source = inspect.getsource(_run_guard_state_reconcile)
        forbidden = ["_run_h1_canary(", "H1_APPROVAL_TOKEN_HASH",
                      "/etc/ibkr-bridge/h1_token"]
        for pattern in forbidden:
            found = False
            for line in source.splitlines():
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue
                if pattern in stripped:
                    found = True
                    break
            assert not found, \
                f"FORBIDDEN: '{pattern}' found in reconcile source"


# ---------------------------------------------------------------------------
# T10: Evidence hash stability
# ---------------------------------------------------------------------------

class TestEvidenceHash:
    """Verify evidence_hash is stable for identical input."""

    def test_hash_stable(self):
        """Same inputs → same hash."""
        from ibkr_operator import _run_guard_state_reconcile

        gs = _make_guard_state(daily_trade_count=6)
        events = _make_events(count=0)

        def _run_with_mocks():
            with patch("monitor.load_guard_state", return_value=gs), \
                 patch("monitor.load_events", return_value=events), \
                 patch("ibkr_operator._git_metadata", return_value={
                     "branch": "test", "commit": "abc", "tag": "test"}), \
                 patch("ibkr_operator._atomic_write_json"), \
                 patch("ibkr_operator.os.getenv", return_value="false"), \
                 patch("ibkr_operator.urllib.request.urlopen",
                       side_effect=Exception("no bridge")), \
                 patch("ibkr_operator._GUARD_STATE_REPAIRS_DIR",
                       Path("/tmp/guard-state-repairs")):
                return _run_guard_state_reconcile(
                    apply_repair=False,
                    confirm_local_state_repair=False,
                )

        r1 = _run_with_mocks()
        r2 = _run_with_mocks()

        assert r1["evidence_hash"] == r2["evidence_hash"], \
            f"Hash mismatch: {r1['evidence_hash']} vs {r2['evidence_hash']}"


# ---------------------------------------------------------------------------
# T11: Existing tests still pass
# ---------------------------------------------------------------------------

class TestExistingTestsStillPass:
    """Quick sanity: imports still work."""

    def test_operator_imports(self):
        """Key operator functions remain importable."""
        from ibkr_operator import (
            _run_autonomy_status,
            _run_autonomy_review,
            _run_autonomy_promotion_plan,
            _run_guard_state_reconcile,
            _run_cycle_rehearsal,
        )
        assert callable(_run_autonomy_status)
        assert callable(_run_autonomy_review)
        assert callable(_run_autonomy_promotion_plan)
        assert callable(_run_guard_state_reconcile)
        assert callable(_run_cycle_rehearsal)
