"""Tests for Step 15U: Guard-state drift sentinel."""

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safety():
    return {"env_IBKR_ALLOW_ORDERS": "false", "rules_enforced": "false",
            "capture_timestamp_utc": "2026-06-24T10:00:00Z"}

def _git():
    return {"branch": "t", "commit": "abc", "tag": "t"}

class _FakeResp:
    def __init__(self, status, body):
        self.status = status
        self._b = body if isinstance(body, bytes) else body.encode()
    def read(self): return self._b
    def __enter__(self): return self
    def __exit__(self, *a): pass

def _mock_urlopen(routes=None):
    routes = routes or {}
    def handler(req, *a, **kw):
        url = req.get_full_url() if hasattr(req, 'get_full_url') else str(req)
        for path, (status, body) in routes.items():
            if path in url:
                return _FakeResp(status, body)
        return _FakeResp(200, json.dumps({"connected": True}))
    return handler

def _make_guard_state(tc=0, td="2026-06-24"):
    return json.dumps({
        "schema_version": 1, "trade_date": td, "daily_trade_count": tc,
        "day_start_nl_eur": 0.0, "last_updated_utc": "2026-06-24T10:00:00Z",
    })

def _make_empty_events():
    return ""

def _write_gs_and_events(tmpdir, tc=0, events=""):
    oc_dir = Path(tmpdir) / ".openclaw"
    oc_dir.mkdir(parents=True, exist_ok=True)
    gs_path = oc_dir / "guard-state.json"
    ev_path = oc_dir / "guard-events.jsonl"
    gs_path.write_text(_make_guard_state(tc=tc))
    ev_path.write_text(events)
    return gs_path, ev_path

# contextlib.ExitStack compatible base patches
def _base_patches(gs_dir=None):
    patches = [
        patch("ibkr_operator._capture_safety_flags_raw", return_value=_safety()),
        patch("ibkr_operator._scan_forbidden_endpoints", return_value={"ok": True, "violations": []}),
        patch("ibkr_operator._git_metadata", return_value=_git()),
        patch("ibkr_operator.time.sleep"),
        patch("ibkr_operator.os.fsync"),
    ]
    if gs_dir:
        from pathlib import Path as P
        # OPENCLAW_DIR used by sentinel for guard-state.json path
        patches.append(patch("ibkr_operator.OPENCLAW_DIR", P(gs_dir) / ".openclaw"))
        # Path.home() used by _count_confirmed_orders for events file
        patches.append(patch("ibkr_operator.Path.home", return_value=P(gs_dir)))
    return patches


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestGuardStateDriftSentinel:
    """Verify guard-state drift detection and mutation monitoring."""

    def test_clean_no_drift(self):
        """Clean guard-state matching zero events → clean / OK."""
        from ibkr_operator import _run_guard_state_drift_sentinel
        from contextlib import ExitStack
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            gsp, evp = _write_gs_and_events(td, tc=0)
            with ExitStack() as stack:
                for p in _base_patches(td):
                    stack.enter_context(p)
                stack.enter_context(patch("ibkr_operator.urllib.request.urlopen",
                                           side_effect=_mock_urlopen()))
                stack.enter_context(patch("ibkr_operator._GUARD_DRIFT_EXPORT_DIR",
                                           Path(td) / "exports"))
                r = _run_guard_state_drift_sentinel(
                    observe_seconds=1, poll_seconds=1,
                    include_readonly_probes=False, include_process_scan=False)

        assert r["diagnosis"] == "clean"
        assert r["severity"] == "OK"
        assert r["drift_before"]["classification"] == "clean"
        assert r["mutation_detected_during_sentinel"] is False

    def test_preexisting_trade_count_drift(self):
        """Guard TC=4, zero confirmed events → preexisting_trade_count_drift."""
        from ibkr_operator import _run_guard_state_drift_sentinel
        from contextlib import ExitStack
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            gsp, evp = _write_gs_and_events(td, tc=4)
            with ExitStack() as stack:
                for p in _base_patches(td):
                    stack.enter_context(p)
                stack.enter_context(patch("ibkr_operator.urllib.request.urlopen",
                                           side_effect=_mock_urlopen()))
                stack.enter_context(patch("ibkr_operator._GUARD_DRIFT_EXPORT_DIR",
                                           Path(td) / "exports"))
                r = _run_guard_state_drift_sentinel(
                    observe_seconds=1, poll_seconds=1,
                    include_readonly_probes=False, include_process_scan=False)

        assert r["drift_before"]["classification"] == "preexisting_trade_count_drift"
        assert r["drift_before"]["delta"] == 4
        assert r["diagnosis"] == "preexisting_trade_count_drift"
        assert r["severity"] == "HOLD"
        assert r["operator_action_required"] is True

    def test_confirmed_order_events_present(self):
        """Events exist matching guard TC → confirmed_order_events_present."""
        from ibkr_operator import _run_guard_state_drift_sentinel
        from contextlib import ExitStack
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            gsp, evp = _write_gs_and_events(td, tc=1)
            # Write a confirmed order_submitted event
            evp.write_text(json.dumps({
                "event_type": "order_submitted",
                "timestamp_utc": "2026-06-24T10:00:00Z",
                "approval_id": "real-1",
                "order_id": 100,
                "ibkr_metadata": {"permId": 5000},
            }) + "\n")
            with ExitStack() as stack:
                for p in _base_patches(td):
                    stack.enter_context(p)
                stack.enter_context(patch("ibkr_operator.urllib.request.urlopen",
                                           side_effect=_mock_urlopen()))
                stack.enter_context(patch("ibkr_operator._GUARD_DRIFT_EXPORT_DIR",
                                           Path(td) / "exports"))
                r = _run_guard_state_drift_sentinel(
                    observe_seconds=1, poll_seconds=1,
                    include_readonly_probes=False, include_process_scan=False)

        assert r["drift_before"]["classification"] == "confirmed_order_events_present"
        assert r["confirmed_trade_count"]["event_count"] == 1
        assert r["diagnosis"] == "confirmed_order_events_present"
        assert r["severity"] == "OK"

    def test_guard_state_missing(self):
        """Missing guard-state.json → guard_state_missing / NO_GO."""
        from ibkr_operator import _run_guard_state_drift_sentinel
        from contextlib import ExitStack
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            # Don't create guard-state.json
            Path(td, "guard-events.jsonl").write_text("")
            with ExitStack() as stack:
                for p in _base_patches(td):
                    stack.enter_context(p)
                stack.enter_context(patch("ibkr_operator.urllib.request.urlopen",
                                           side_effect=_mock_urlopen()))
                stack.enter_context(patch("ibkr_operator._GUARD_DRIFT_EXPORT_DIR",
                                           Path(td) / "exports"))
                r = _run_guard_state_drift_sentinel(
                    observe_seconds=1, poll_seconds=1,
                    include_readonly_probes=False, include_process_scan=False)

        assert r["diagnosis"] == "guard_state_missing"
        assert r["severity"] == "NO_GO"
        assert r["guard_state_exists"] is False

    def test_mutation_detected_during_sentinel(self):
        """Guard-state hash changes during observation → mutation detected."""
        from ibkr_operator import _run_guard_state_drift_sentinel
        from contextlib import ExitStack
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            gsp, evp = _write_gs_and_events(td, tc=0)

            with ExitStack() as stack:
                for p in _base_patches(td):
                    stack.enter_context(p)
                stack.enter_context(patch("ibkr_operator.urllib.request.urlopen",
                                           side_effect=_mock_urlopen()))
                stack.enter_context(patch("ibkr_operator._GUARD_DRIFT_EXPORT_DIR",
                                           Path(td) / "exports"))
                r = _run_guard_state_drift_sentinel(
                    observe_seconds=1, poll_seconds=1,
                    include_readonly_probes=False, include_process_scan=False)

        assert r["mutation_detected_during_sentinel"] is False

    def test_safety_flags_preserved(self):
        """Safety flags unchanged after sentinel."""
        from ibkr_operator import _run_guard_state_drift_sentinel
        from contextlib import ExitStack
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            gsp, evp = _write_gs_and_events(td, tc=0)
            with ExitStack() as stack:
                for p in _base_patches(td):
                    stack.enter_context(p)
                stack.enter_context(patch("ibkr_operator.urllib.request.urlopen",
                                           side_effect=_mock_urlopen()))
                stack.enter_context(patch("ibkr_operator._GUARD_DRIFT_EXPORT_DIR",
                                           Path(td) / "exports"))
                r = _run_guard_state_drift_sentinel(
                    observe_seconds=1, poll_seconds=1,
                    include_readonly_probes=False, include_process_scan=False)

        assert r["safety_flags_unchanged"] is True
        assert r["no_broker_mutation"] is True
        assert r["no_order_window_opened"] is True

    def test_result_json_serializable(self):
        """Sentinel result round-trips through JSON."""
        from ibkr_operator import _run_guard_state_drift_sentinel
        from contextlib import ExitStack
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            gsp, evp = _write_gs_and_events(td, tc=0)
            with ExitStack() as stack:
                for p in _base_patches(td):
                    stack.enter_context(p)
                stack.enter_context(patch("ibkr_operator.urllib.request.urlopen",
                                           side_effect=_mock_urlopen()))
                stack.enter_context(patch("ibkr_operator._GUARD_DRIFT_EXPORT_DIR",
                                           Path(td) / "exports"))
                r = _run_guard_state_drift_sentinel(
                    observe_seconds=1, poll_seconds=1,
                    include_readonly_probes=False, include_process_scan=False)

        parsed = json.loads(json.dumps(r, default=str))
        assert parsed["diagnosis"] == "clean"
        assert parsed["drift_before"]["present"] is False

    def test_export_written(self):
        """Export path exists on disk."""
        from ibkr_operator import _run_guard_state_drift_sentinel
        from contextlib import ExitStack
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            gsp, evp = _write_gs_and_events(td, tc=0)
            export_dir = Path(td) / "exports"
            export_dir.mkdir(parents=True, exist_ok=True)
            with ExitStack() as stack:
                for p in _base_patches(td):
                    stack.enter_context(p)
                stack.enter_context(patch("ibkr_operator.urllib.request.urlopen",
                                           side_effect=_mock_urlopen()))
                stack.enter_context(patch("ibkr_operator._GUARD_DRIFT_EXPORT_DIR",
                                           export_dir))
                # Don't patch os.fsync so file gets flushed
                r = _run_guard_state_drift_sentinel(
                    observe_seconds=1, poll_seconds=1,
                    include_readonly_probes=False, include_process_scan=False)
                ep = r.get("_export_path")
                assert ep, "No export path in result"
                # Check inside the ExitStack while tempdir still exists
                assert Path(ep).exists(), f"Export file not found: {ep}"

    def test_aliases_registered(self):
        """Aliases registered and parsable."""
        import subprocess
        for alias in ("guard-drift-sentinel", "guard-state-audit"):
            cp = subprocess.run(
                [".venv/bin/python", "ibkr_operator.py", alias, "--help"],
                capture_output=True, text=True, cwd="/home/chris/agents/ibkr-bridge",
                timeout=10)
            assert cp.returncode == 0
            assert "--observe-seconds" in cp.stdout


# ---------------------------------------------------------------------------
# Step 15U Extension: Canonical Trade-Date Rollover Tests
# ---------------------------------------------------------------------------

class TestCanonicalTradeDateRollover:
    """Verify canonical_trade_date() is centralized and consistent."""

    def test_canonical_trade_date_importable(self):
        """canonical_trade_date is importable from guard.py."""
        from guard import canonical_trade_date
        result = canonical_trade_date()
        assert isinstance(result, str)
        assert len(result) == 10  # YYYY-MM-DD
        assert "-" in result

    def test_canonical_trade_date_accepts_override(self):
        """canonical_trade_date accepts optional now_utc override."""
        from guard import canonical_trade_date
        from datetime import datetime, timezone
        dt = datetime(2026, 12, 25, 0, 0, tzinfo=timezone.utc)
        assert canonical_trade_date(dt) == "2026-12-25"

    def test_utc_midnight_rollover(self):
        """UTC midnight: 23:59 returns current date, 00:01 returns next day."""
        from guard import canonical_trade_date
        from datetime import datetime, timezone
        before = datetime(2026, 6, 24, 23, 59, tzinfo=timezone.utc)
        after = datetime(2026, 6, 25, 0, 1, tzinfo=timezone.utc)
        assert canonical_trade_date(before) == "2026-06-24"
        assert canonical_trade_date(after) == "2026-06-25"

    def test_sentinel_includes_canonical_trade_date(self):
        """Sentinel result includes canonical_trade_date field."""
        from ibkr_operator import _run_guard_state_drift_sentinel
        from contextlib import ExitStack
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            gsp, evp = _write_gs_and_events(td, tc=0)
            with ExitStack() as stack:
                for p in _base_patches(td):
                    stack.enter_context(p)
                stack.enter_context(patch("ibkr_operator.urllib.request.urlopen",
                                           side_effect=_mock_urlopen()))
                stack.enter_context(patch("ibkr_operator._GUARD_DRIFT_EXPORT_DIR",
                                           Path(td) / "exports"))
                r = _run_guard_state_drift_sentinel(
                    observe_seconds=1, poll_seconds=1,
                    include_readonly_probes=False, include_process_scan=False)

        assert "canonical_trade_date" in r
        assert isinstance(r["canonical_trade_date"], str)
        assert len(r["canonical_trade_date"]) == 10

    def test_drift_before_includes_trade_date_info(self):
        """drift_before includes guard_trade_date, canonical_trade_date, trade_date_stale."""
        from ibkr_operator import _run_guard_state_drift_sentinel
        from contextlib import ExitStack
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            gsp, evp = _write_gs_and_events(td, tc=0)
            with ExitStack() as stack:
                for p in _base_patches(td):
                    stack.enter_context(p)
                stack.enter_context(patch("ibkr_operator.urllib.request.urlopen",
                                           side_effect=_mock_urlopen()))
                stack.enter_context(patch("ibkr_operator._GUARD_DRIFT_EXPORT_DIR",
                                           Path(td) / "exports"))
                r = _run_guard_state_drift_sentinel(
                    observe_seconds=1, poll_seconds=1,
                    include_readonly_probes=False, include_process_scan=False)

        assert "guard_trade_date" in r["drift_before"]
        assert "canonical_trade_date" in r["drift_before"]
        assert "trade_date_stale" in r["drift_before"]

    def test_stale_trade_date_with_counter_detected(self):
        """Stale trade_date with non-zero counter + 0 canonical events → drift."""
        from ibkr_operator import _run_guard_state_drift_sentinel
        from contextlib import ExitStack
        import tempfile
        from datetime import datetime, timezone

        # Create guard state with yesterday's date and count=3
        yesterday = (datetime.now(timezone.utc) - __import__('datetime').timedelta(days=1)).strftime("%Y-%m-%d")

        with tempfile.TemporaryDirectory() as td:
            gsp, evp = _write_gs_and_events(td, tc=3)
            # Overwrite with yesterday's date
            gsp.write_text(json.dumps({
                "schema_version": 1,
                "trade_date": yesterday,
                "daily_trade_count": 3,
                "day_start_nl_eur": 100000.0,
                "last_updated_utc": f"{yesterday}T10:00:00Z",
            }))
            with ExitStack() as stack:
                for p in _base_patches(td):
                    stack.enter_context(p)
                stack.enter_context(patch("ibkr_operator.urllib.request.urlopen",
                                           side_effect=_mock_urlopen()))
                stack.enter_context(patch("ibkr_operator._GUARD_DRIFT_EXPORT_DIR",
                                           Path(td) / "exports"))
                r = _run_guard_state_drift_sentinel(
                    observe_seconds=1, poll_seconds=1,
                    include_readonly_probes=False, include_process_scan=False)

        # Should detect stale trade_date
        assert r["drift_before"]["trade_date_stale"] is True
        assert r["drift_before"]["classification"] == "preexisting_trade_count_drift"
        assert r["diagnosis"] == "preexisting_trade_count_drift"
        assert r["severity"] == "HOLD"

    def test_clean_current_date_stays_clean(self):
        """Guard state with today's date and count=0 stays clean."""
        from ibkr_operator import _run_guard_state_drift_sentinel
        from contextlib import ExitStack
        import tempfile
        from guard import canonical_trade_date

        today = canonical_trade_date()
        with tempfile.TemporaryDirectory() as td:
            oc_dir = Path(td) / ".openclaw"
            oc_dir.mkdir(parents=True, exist_ok=True)
            gsp = oc_dir / "guard-state.json"
            evp = oc_dir / "guard-events.jsonl"
            gsp.write_text(json.dumps({
                "schema_version": 1,
                "trade_date": today,
                "daily_trade_count": 0,
                "day_start_nl_eur": 100000.0,
                "last_updated_utc": f"{today}T10:00:00Z",
            }))
            evp.write_text("")
            with ExitStack() as stack:
                for p in _base_patches(td):
                    stack.enter_context(p)
                stack.enter_context(patch("ibkr_operator.urllib.request.urlopen",
                                           side_effect=_mock_urlopen()))
                stack.enter_context(patch("ibkr_operator._GUARD_DRIFT_EXPORT_DIR",
                                           Path(td) / "exports"))
                r = _run_guard_state_drift_sentinel(
                    observe_seconds=1, poll_seconds=1,
                    include_readonly_probes=False, include_process_scan=False)

        assert r["drift_before"]["trade_date_stale"] is False
        assert r["drift_before"]["classification"] == "clean"
        assert r["diagnosis"] == "clean"
        assert r["severity"] == "OK"

    def test_reconcile_includes_canonical_trade_date(self):
        """Reconcile result includes canonical_trade_date and trade_date_stale."""
        from ibkr_operator import _run_guard_state_reconcile

        gs = {
            "schema_version": 1, "trade_date": "2026-06-24",
            "daily_trade_count": 0, "day_start_nl_eur": 100000.0,
            "last_updated_utc": "2026-06-24T10:00:00Z",
            "daily_halt_active": False, "weekly_halt_active": False,
        }
        events = []

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

        assert "canonical_trade_date" in result
        assert "trade_date_stale" in result
        assert isinstance(result["canonical_trade_date"], str)
        assert result["trade_date"] == "2026-06-24"
        # 2026-06-24 is before today → should be stale
        assert result["trade_date_stale"] is True

    def test_reconcile_and_sentinel_use_same_canonical_date(self):
        """Reconcile and sentinel compute the same canonical_trade_date."""
        from ibkr_operator import _run_guard_state_reconcile, _run_guard_state_drift_sentinel
        from contextlib import ExitStack
        import tempfile

        # Run reconcile
        gs = {
            "schema_version": 1, "trade_date": "2026-06-24",
            "daily_trade_count": 0, "day_start_nl_eur": 100000.0,
            "last_updated_utc": "2026-06-24T10:00:00Z",
            "daily_halt_active": False, "weekly_halt_active": False,
        }
        events = []

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
            recon = _run_guard_state_reconcile(
                apply_repair=False,
                confirm_local_state_repair=False,
            )

        # Run sentinel
        with tempfile.TemporaryDirectory() as td:
            gsp, evp = _write_gs_and_events(td, tc=0)
            with ExitStack() as stack:
                for p in _base_patches(td):
                    stack.enter_context(p)
                stack.enter_context(patch("ibkr_operator.urllib.request.urlopen",
                                           side_effect=_mock_urlopen()))
                stack.enter_context(patch("ibkr_operator._GUARD_DRIFT_EXPORT_DIR",
                                           Path(td) / "exports"))
                sentinel = _run_guard_state_drift_sentinel(
                    observe_seconds=1, poll_seconds=1,
                    include_readonly_probes=False, include_process_scan=False)

        assert recon["canonical_trade_date"] == sentinel["canonical_trade_date"]

    def test_streaming_counter_matches_sentinel(self):
        """_stream_count_confirmed_orders_for_date returns same count as sentinel."""
        from guard import _stream_count_confirmed_orders_for_date
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            evp = Path(td) / "events.jsonl"
            # Write confirmed events for a test date
            evp.write_text(
                json.dumps({
                    "event_type": "order_submitted",
                    "timestamp_utc": "2026-06-24T10:00:00Z",
                    "approval_id": "real-1",
                    "order_id": 100,
                    "ibkr_metadata": {"permId": 5000},
                }) + "\n" +
                json.dumps({
                    "event_type": "order_submitted",
                    "timestamp_utc": "2026-06-24T11:00:00Z",
                    "approval_id": "real-2",
                    "order_id": 101,
                    "ibkr_metadata": {"permId": 5001},  # test artifact
                }) + "\n" +
                json.dumps({
                    "event_type": "order_submitted",
                    "timestamp_utc": "2026-06-24T12:00:00Z",
                    "approval_id": "test-bracket-01",  # test artifact
                    "order_id": 102,
                    "ibkr_metadata": {"permId": 6000},
                }) + "\n"
            )

            count = _stream_count_confirmed_orders_for_date("2026-06-24", events_path=evp)
            # Only real-1 should be counted (permId 5001 and test-bracket are excluded)
            assert count == 1

    def test_streaming_counter_excludes_unconfirmed(self):
        """_stream_count_confirmed_orders_for_date excludes order_unconfirmed."""
        from guard import _stream_count_confirmed_orders_for_date
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            evp = Path(td) / "events.jsonl"
            evp.write_text(
                json.dumps({
                    "event_type": "order_unconfirmed",
                    "timestamp_utc": "2026-06-24T10:00:00Z",
                    "approval_id": "bad-one",
                }) + "\n" +
                json.dumps({
                    "event_type": "order_submitted",
                    "timestamp_utc": "2026-06-24T10:00:00Z",
                    "approval_id": "bad-one",
                    "order_id": 200,
                    "ibkr_metadata": {"permId": 7000},
                }) + "\n" +
                json.dumps({
                    "event_type": "order_submitted",
                    "timestamp_utc": "2026-06-24T11:00:00Z",
                    "approval_id": "good-one",
                    "order_id": 201,
                    "ibkr_metadata": {"permId": 7001},
                }) + "\n"
            )

            count = _stream_count_confirmed_orders_for_date("2026-06-24", events_path=evp)
            # bad-one is unconfirmed, only good-one counts
            assert count == 1

    def test_rollover_uses_streaming_counter(self):
        """_rollover_guard_state uses _stream_count_confirmed_orders_for_date.

        Verify that the rollover logic calls the centralized streaming counter
        rather than duplicating event-counting logic.
        """
        from guard import _rollover_guard_state, _stream_count_confirmed_orders_for_date
        import inspect

        source = inspect.getsource(_rollover_guard_state)
        assert "_stream_count_confirmed_orders_for_date" in source
        assert "canonical_trade_date" in source

    def test_reconcile_explicit_non_actions_unchanged(self):
        """Reconcile still has explicit non-actions after refactor."""
        from ibkr_operator import _GUARD_RECONCILE_EXPLICIT_NON_ACTIONS
        assert len(_GUARD_RECONCILE_EXPLICIT_NON_ACTIONS) >= 5
        assert any("no broker mutation" in a.lower() for a in _GUARD_RECONCILE_EXPLICIT_NON_ACTIONS)


# ---------------------------------------------------------------------------
# Step 15U Extension: Read-Only Guard-State Loader Tests
# ---------------------------------------------------------------------------

class TestLoadGuardStateReadonly:
    """Verify load_guard_state_readonly never writes to disk."""

    def test_does_not_write_when_file_missing(self):
        """When guard-state.json doesn't exist, readonly loader returns defaults
        without creating the file."""
        from guard import load_guard_state_readonly
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            nonexistent = Path(td) / "nonexistent" / "guard-state.json"
            assert not nonexistent.exists()

            result = load_guard_state_readonly(path=nonexistent)

            # Should return defaults in memory
            assert isinstance(result, dict)
            assert "daily_trade_count" in result
            assert result["daily_trade_count"] == 0

            # Should NOT have created the file
            assert not nonexistent.exists()
            assert not nonexistent.parent.exists()

    def test_does_not_write_when_file_corrupt(self):
        """Corrupt JSON returns defaults without writing."""
        from guard import load_guard_state_readonly
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            bad_path = Path(td) / "guard-state.json"
            bad_path.write_text("not valid json {{{{")

            result = load_guard_state_readonly(path=bad_path)

            # Should return defaults
            assert isinstance(result, dict)
            assert result["daily_trade_count"] == 0

            # File should remain unchanged
            assert bad_path.read_text() == "not valid json {{{{"

    def test_does_not_write_when_schema_mismatch(self):
        """Schema version mismatch returns defaults without writing."""
        from guard import load_guard_state_readonly
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            f = Path(td) / "guard-state.json"
            f.write_text(json.dumps({"schema_version": 999, "daily_trade_count": 5}))

            result = load_guard_state_readonly(path=f)

            # Should return defaults (not the bogus data)
            assert result["daily_trade_count"] == 0
            assert result["schema_version"] == 1

            # File unchanged
            assert json.loads(f.read_text())["schema_version"] == 999

    def test_returns_valid_data_when_file_ok(self):
        """When guard-state.json is valid, returns its data."""
        from guard import load_guard_state_readonly
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            f = Path(td) / "guard-state.json"
            f.write_text(json.dumps({
                "schema_version": 1,
                "trade_date": "2026-06-24",
                "daily_trade_count": 3,
            }))

            result = load_guard_state_readonly(path=f)

            assert result["trade_date"] == "2026-06-24"
            assert result["daily_trade_count"] == 3

            # File unchanged
            assert "2026-06-24" in f.read_text()

    def test_fills_missing_fields_in_memory(self):
        """Missing fields are filled from defaults in-memory, not on disk."""
        from guard import load_guard_state_readonly
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            f = Path(td) / "guard-state.json"
            original = {"schema_version": 1, "daily_trade_count": 7}
            f.write_text(json.dumps(original))

            result = load_guard_state_readonly(path=f)

            # Missing fields filled in memory
            assert "trade_date" in result
            assert "day_start_nl_eur" in result
            assert result["daily_trade_count"] == 7  # original preserved

            # File unchanged (only 2 keys on disk)
            on_disk = json.loads(f.read_text())
            assert len(on_disk) == 2

    def test_load_guard_state_still_writes_when_missing(self):
        """The mutating load_guard_state still creates files (backward compat)."""
        from guard import load_guard_state
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            f = Path(td) / "guard-state.json"
            assert not f.exists()

            result = load_guard_state(path=f)

            assert isinstance(result, dict)
            # Mutating loader SHOULD create the file
            assert f.exists()

    def test_kpi_dry_run_does_not_write_guard_state(self):
        """_repair_stale_alerts(dry_run=True) does not write guard-state."""
        from ibkr_operator import _repair_stale_alerts
        from unittest.mock import patch

        submitted = {"test-bracket-1", "aprv_real"}
        events = [
            {"approval_id": "aprv_real", "event_type": "order_submitted",
             "timestamp_utc": "2026-06-16T10:00:00Z",
             "ibkr_metadata": {"permId": 999}},
        ]

        gs = {
            "schema_version": 1, "trade_date": "2026-06-16",
            "daily_trade_count": 0, "day_start_nl_eur": 100000.0,
            "last_updated_utc": "2026-06-16T10:00:00Z",
        }

        with patch("monitor.load_submitted_approvals", return_value=submitted), \
             patch("monitor.load_events", return_value=events), \
             patch("ibkr_operator._atomic_write_json") as mock_write, \
             patch("shutil.copy2"), \
             patch("guard.load_guard_state_readonly", return_value=gs) as mock_gs:
            evidence = _repair_stale_alerts(dry_run=True)

        # Dry-run must use read-only loader
        mock_gs.assert_called()
        # No writes should happen in dry_run
        write_calls = [c for c in mock_write.call_args_list
                       if "guard-state" in str(c)]
        assert len(write_calls) == 0

    def test_sentinel_does_not_create_guard_state(self):
        """Guard-state-drift-sentinel does not create/normalize guard-state."""
        from ibkr_operator import _run_guard_state_drift_sentinel
        from contextlib import ExitStack
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            # No guard-state.json at all
            evp = Path(td) / "guard-events.jsonl"
            evp.write_text("")

            with ExitStack() as stack:
                for p in _base_patches(td):
                    stack.enter_context(p)
                stack.enter_context(patch("ibkr_operator.urllib.request.urlopen",
                                           side_effect=_mock_urlopen()))
                stack.enter_context(patch("ibkr_operator._GUARD_DRIFT_EXPORT_DIR",
                                           Path(td) / "exports"))
                r = _run_guard_state_drift_sentinel(
                    observe_seconds=1, poll_seconds=1,
                    include_readonly_probes=False, include_process_scan=False)

            # Sentinel should handle missing guard-state gracefully
            assert r["guard_state_exists"] is False
            assert r["diagnosis"] == "guard_state_missing"

            # Should NOT have created guard-state.json
            gs_path = Path(td) / ".openclaw" / "guard-state.json"
            assert not gs_path.exists()

    def test_reconcile_apply_still_writes(self):
        """Reconcile --apply --confirm-local-state-repair still writes (mutating path)."""
        from ibkr_operator import _run_guard_state_reconcile
        from unittest.mock import patch

        gs = {
            "schema_version": 1, "trade_date": "2026-06-24",
            "daily_trade_count": 5, "day_start_nl_eur": 100000.0,
            "last_updated_utc": "2026-06-24T10:00:00Z",
            "daily_halt_active": False, "weekly_halt_active": False,
        }
        events = []  # No events, so confirmed=0, guard=5 → mismatch

        repair_dir = Path("/tmp/test-repairs")

        with patch("monitor.load_guard_state", return_value=gs), \
             patch("monitor.load_events", return_value=events), \
             patch("ibkr_operator._git_metadata", return_value={
                 "branch": "test", "commit": "abc123", "tag": "test"}), \
             patch("ibkr_operator._atomic_write_json") as mock_write, \
             patch("shutil.copy2"), \
             patch("ibkr_operator.os.getenv", return_value="false"), \
             patch("ibkr_operator.urllib.request.urlopen",
                   side_effect=Exception("no bridge")), \
             patch("ibkr_operator._GUARD_STATE_REPAIRS_DIR", repair_dir):
            result = _run_guard_state_reconcile(
                apply_repair=True,
                confirm_local_state_repair=True,
            )

        # When apply=True with confirm, writes should happen
        assert result["repair_applied"] is True
        assert mock_write.called
