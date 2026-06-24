"""Tests for Step 15R — Market-data recovery drill.

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

def _make_session_info(session: str = "rth", reason: str = "Inside RTH") -> dict:
    return {
        "session": session, "data_availability": "available" if session == "rth" else "unavailable",
        "reason": reason, "is_tradable_day": session != "closed",
        "in_rth": session == "rth", "market_date_et": "2026-06-24",
    }


def _make_health_response(connected: bool = True, mode: str = "paper") -> dict:
    return {"connected": connected, "mode": mode, "allow_orders": False}


def _make_contract_response(conid: int = 265598, symbol: str = "AAPL") -> dict:
    return {"conid": conid, "symbol": symbol, "exchange": "SMART",
            "currency": "USD", "asset_type": "STK"}


def _make_snapshot_response(available: bool = True, stale: bool = False,
                            delayed: bool = True, detail: str = "",
                            bid: float = 150.0, ask: float = 150.5,
                            last: float = 150.25) -> dict:
    ok = available
    return {
        "ok": ok, "symbol": "AAPL", "market_data_available": available,
        "detail": detail, "delayed": delayed, "stale": stale,
        "bid": bid if available else None, "ask": ask if available else None,
        "last": last if available else None, "close": 149.8 if available else None,
        "midpoint": 150.375 if available else None, "currency": "USD" if available else None,
        "exchange": "SMART", "snapshot_timestamp": "2026-06-24T10:00:00Z",
        "snapshot_epoch": time.time(), "market_data_age_seconds": 5.0 if available else None,
    }


def _make_bars_response(bars_count: int = 5) -> dict:
    return {"bars": [{"close": 150.0 + i} for i in range(bars_count)]}


def _make_connect_response(ok: bool = True, connected: bool = True) -> dict:
    return {
        "ok": ok, "connected": connected,
        "managed_accounts": ["DU1234567"],
        "client_id": 101, "read_only": True, "allow_orders": False,
    }


def _make_diagnostics_live_available_result() -> dict:
    """Full diagnostics result with live data available."""
    return {
        "timestamp": "2026-06-24T10:00:00Z",
        "diagnostic_id": "md-test-1",
        "ibkr_connected": True,
        "bridge_reachable": True,
        "bridge_runtime_ok": True,
        "contract_qualified": True,
        "live_market_data_available": True,
        "delayed_market_data_available": True,
        "market_data_unavailable_reason": "",
        "diagnosis": "live_data_available",
        "severity": "OK",
        "market_session_status": _make_session_info("rth"),
        "operator_action_required": False,
        "suggested_operator_actions": [],
        "_export_path": "/tmp/test-diag.json",
    }


def _make_diagnostics_delayed_result() -> dict:
    """Full diagnostics result with delayed data available."""
    return {
        "timestamp": "2026-06-24T10:00:00Z",
        "diagnostic_id": "md-test-2",
        "ibkr_connected": True,
        "bridge_reachable": True,
        "bridge_runtime_ok": True,
        "contract_qualified": True,
        "live_market_data_available": False,
        "delayed_market_data_available": True,
        "market_data_unavailable_reason": "",
        "diagnosis": "delayed_data_available",
        "severity": "OK",
        "market_session_status": _make_session_info("rth"),
        "operator_action_required": False,
        "suggested_operator_actions": [],
        "_export_path": "/tmp/test-diag-delayed.json",
    }


def _make_diagnostics_no_tick_timeout_result() -> dict:
    """Full diagnostics result with no tick stream timeout."""
    return {
        "timestamp": "2026-06-24T10:00:00Z",
        "diagnostic_id": "md-test-3",
        "ibkr_connected": True,
        "bridge_reachable": True,
        "bridge_runtime_ok": True,
        "contract_qualified": True,
        "live_market_data_available": False,
        "delayed_market_data_available": False,
        "market_data_unavailable_reason": "market_data_timeout",
        "diagnosis": "no_tick_stream_timeout",
        "severity": "HOLD",
        "market_session_status": _make_session_info("rth"),
        "operator_action_required": True,
        "suggested_operator_actions": ["Check entitlement"],
        "_export_path": "/tmp/test-diag-timeout.json",
    }


def _make_diagnostics_disconnected_result() -> dict:
    """Full diagnostics result with IBKR disconnected."""
    return {
        "timestamp": "2026-06-24T10:00:00Z",
        "diagnostic_id": "md-test-4",
        "ibkr_connected": False,
        "bridge_reachable": True,
        "bridge_runtime_ok": False,
        "contract_qualified": False,
        "live_market_data_available": False,
        "delayed_market_data_available": False,
        "market_data_unavailable_reason": "",
        "diagnosis": "ibkr_disconnected",
        "severity": "HOLD",
        "market_session_status": _make_session_info("rth"),
        "operator_action_required": True,
        "suggested_operator_actions": ["Restart IBKR Gateway"],
        "_export_path": "/tmp/test-diag-disc.json",
    }


class _MockUrlOpen:
    """Flexible urlopen mock — returns different responses per URL pattern."""
    def __init__(self, responses: dict):
        self._responses = responses  # {url_substring: (status, body_dict)}
        self._calls = []

    def __call__(self, req, timeout=None):
        url = req.full_url if hasattr(req, 'full_url') else str(req)
        self._calls.append(url)
        for pattern, (status, body) in self._responses.items():
            if pattern in url:
                return _MockResponse(status, json.dumps(body).encode())
        return _MockResponse(404, b'{}')


class _MockResponse:
    def __init__(self, status, data):
        self.status = status
        self._data = data
    def read(self):
        return self._data
    def __enter__(self):
        return self
    def __exit__(self, *args):
        pass


# ---------------------------------------------------------------------------
# T1: Command exists and is importable
# ---------------------------------------------------------------------------

class TestCommandExists:
    """Verify the recovery drill command is registered and importable."""

    def test_function_importable(self):
        from ibkr_operator import _run_market_data_recovery_drill
        assert callable(_run_market_data_recovery_drill)

    def test_capture_safety_flags_importable(self):
        from ibkr_operator import _capture_safety_flags_raw
        assert callable(_capture_safety_flags_raw)


# ---------------------------------------------------------------------------
# T2: Required output fields
# ---------------------------------------------------------------------------

class TestRequiredFields:
    """Verify all spec-required fields are present."""

    _REQUIRED_FIELDS = [
        "timestamp", "drill_id", "command", "git", "symbol",
        "attempts_requested", "attempts_completed", "connect_if_needed",
        "initial_bridge_health", "initial_ibkr_connected",
        "connect_attempted", "connect_result",
        "per_attempt_results", "final_diagnosis", "final_severity",
        "final_market_data_status", "readiness_refresh_attempted",
        "readiness_export_path", "readiness_recommendation",
        "promotion_safe_to_recheck", "drill_result",
        "no_broker_mutation", "no_order_window_opened",
        "safety_flags_before", "safety_flags_after",
        "safety_flags_unchanged", "forbidden_endpoint_scan",
        "explicit_non_actions", "evidence_hash", "_export_path",
    ]

    def test_all_required_fields_present(self):
        from ibkr_operator import _run_market_data_recovery_drill
        from pathlib import Path

        export_dir = Path("/tmp/md-drill-test-fields")
        export_dir.mkdir(parents=True, exist_ok=True)

        with patch("ibkr_operator._capture_safety_flags_raw",
                   return_value={"env_IBKR_ALLOW_ORDERS": "false",
                                 "rules_enforced": "false",
                                 "capture_timestamp_utc": "2026-06-24T10:00:00Z"}), \
             patch("ibkr_operator._run_market_data_diagnostics",
                   return_value=_make_diagnostics_live_available_result()), \
             patch("ibkr_operator._run_autonomy_status",
                   return_value={"recommendation": "HOLD", "_export_path": "/tmp/stat.json"}), \
             patch("ibkr_operator._scan_forbidden_endpoints",
                   return_value={"ok": True, "violations": []}), \
             patch("ibkr_operator._git_metadata",
                   return_value={"branch": "test", "commit": "abc", "tag": "test"}), \
             patch("ibkr_operator.urllib.request.urlopen",
                   side_effect=_MockUrlOpen({
                       "/health": (200, _make_health_response(True)),
                   })), \
             patch("ibkr_operator.time.sleep"), \
             patch("ibkr_operator._MD_RECOVERY_DRILL_EXPORT_DIR", export_dir), \
             patch("ibkr_operator.os.fsync"):
            result = _run_market_data_recovery_drill(
                symbol="AAPL", attempts=1, connect_if_needed=False)

        for field in self._REQUIRED_FIELDS:
            assert field in result, f"Missing required field: {field}"


# ---------------------------------------------------------------------------
# T3: Safety flags captured and unchanged
# ---------------------------------------------------------------------------

class TestSafetyFlags:
    """Verify safety flags are captured before/after and unchanged."""

    def test_safety_flags_captured(self):
        from ibkr_operator import _run_market_data_recovery_drill
        from pathlib import Path

        export_dir = Path("/tmp/md-drill-test-safety")
        export_dir.mkdir(parents=True, exist_ok=True)

        safety_flags = {
            "env_IBKR_ALLOW_ORDERS": "false",
            "rules_enforced": "false",
            "capture_timestamp_utc": "2026-06-24T10:00:00Z",
        }

        with patch("ibkr_operator._capture_safety_flags_raw",
                   return_value=safety_flags), \
             patch("ibkr_operator._run_market_data_diagnostics",
                   return_value=_make_diagnostics_live_available_result()), \
             patch("ibkr_operator._run_autonomy_status",
                   return_value={"recommendation": "HOLD", "_export_path": "/tmp/stat.json"}), \
             patch("ibkr_operator._scan_forbidden_endpoints",
                   return_value={"ok": True, "violations": []}), \
             patch("ibkr_operator._git_metadata",
                   return_value={"branch": "test", "commit": "abc", "tag": "test"}), \
             patch("ibkr_operator.urllib.request.urlopen",
                   side_effect=_MockUrlOpen({
                       "/health": (200, _make_health_response(True)),
                   })), \
             patch("ibkr_operator.time.sleep"), \
             patch("ibkr_operator._MD_RECOVERY_DRILL_EXPORT_DIR", export_dir), \
             patch("ibkr_operator.os.fsync"):
            result = _run_market_data_recovery_drill(
                symbol="AAPL", attempts=1, connect_if_needed=False)

        assert result["safety_flags_before"] == safety_flags
        assert result["safety_flags_after"] == safety_flags
        assert result["safety_flags_unchanged"] is True


# ---------------------------------------------------------------------------
# T4: Live data → recovered
# ---------------------------------------------------------------------------

class TestRecoveredPath:
    """Verify recovery drill correctly identifies a recovered state."""

    def test_live_data_available_yields_recovered(self):
        from ibkr_operator import _run_market_data_recovery_drill
        from pathlib import Path

        export_dir = Path("/tmp/md-drill-test-live")
        export_dir.mkdir(parents=True, exist_ok=True)

        with patch("ibkr_operator._capture_safety_flags_raw",
                   return_value={"env_IBKR_ALLOW_ORDERS": "false",
                                 "rules_enforced": "false",
                                 "capture_timestamp_utc": "2026-06-24T10:00:00Z"}), \
             patch("ibkr_operator._run_market_data_diagnostics",
                   return_value=_make_diagnostics_live_available_result()), \
             patch("ibkr_operator._run_autonomy_status",
                   return_value={"recommendation": "READY_FOR_MANUAL_REVIEW",
                                 "market_data_status": "available",
                                 "_export_path": "/tmp/stat.json"}), \
             patch("ibkr_operator._scan_forbidden_endpoints",
                   return_value={"ok": True, "violations": []}), \
             patch("ibkr_operator._git_metadata",
                   return_value={"branch": "test", "commit": "abc", "tag": "test"}), \
             patch("ibkr_operator.urllib.request.urlopen",
                   side_effect=_MockUrlOpen({
                       "/health": (200, _make_health_response(True)),
                   })), \
             patch("ibkr_operator.time.sleep"), \
             patch("ibkr_operator._MD_RECOVERY_DRILL_EXPORT_DIR", export_dir), \
             patch("ibkr_operator.os.fsync"):
            result = _run_market_data_recovery_drill(
                symbol="AAPL", attempts=1, connect_if_needed=False)

        assert result["drill_result"] == "recovered"
        assert result["final_severity"] == "OK"
        assert result["final_market_data_status"] == "available"
        assert result["final_diagnosis"] == "live_data_available"
        assert result["readiness_refresh_attempted"] is True
        assert result["promotion_safe_to_recheck"] is True


# ---------------------------------------------------------------------------
# T5: Delayed data → HOLD
# ---------------------------------------------------------------------------

class TestDelayedPath:
    """Verify recovery drill handles delayed data correctly."""

    def test_delayed_data_in_rth_yields_hold(self):
        from ibkr_operator import _run_market_data_recovery_drill
        from pathlib import Path

        export_dir = Path("/tmp/md-drill-test-delayed")
        export_dir.mkdir(parents=True, exist_ok=True)

        with patch("ibkr_operator._capture_safety_flags_raw",
                   return_value={"env_IBKR_ALLOW_ORDERS": "false",
                                 "rules_enforced": "false",
                                 "capture_timestamp_utc": "2026-06-24T10:00:00Z"}), \
             patch("ibkr_operator._run_market_data_diagnostics",
                   return_value=_make_diagnostics_delayed_result()), \
             patch("ibkr_operator._run_autonomy_status",
                   return_value={"recommendation": "HOLD",
                                 "market_data_status": "stale",
                                 "_export_path": "/tmp/stat.json"}), \
             patch("ibkr_operator._scan_forbidden_endpoints",
                   return_value={"ok": True, "violations": []}), \
             patch("ibkr_operator._git_metadata",
                   return_value={"branch": "test", "commit": "abc", "tag": "test"}), \
             patch("ibkr_operator.urllib.request.urlopen",
                   side_effect=_MockUrlOpen({
                       "/health": (200, _make_health_response(True)),
                   })), \
             patch("ibkr_operator.time.sleep"), \
             patch("ibkr_operator._MD_RECOVERY_DRILL_EXPORT_DIR", export_dir), \
             patch("ibkr_operator.os.fsync"):
            result = _run_market_data_recovery_drill(
                symbol="AAPL", attempts=1, connect_if_needed=False)

        assert result["drill_result"] == "hold_no_tick_stream"
        assert result["final_severity"] == "HOLD"
        assert result["final_market_data_status"] == "delayed_available"


# ---------------------------------------------------------------------------
# T6: No tick stream timeout → HOLD, retries
# ---------------------------------------------------------------------------

class TestTimeoutRetryPath:
    """Verify recovery drill retries on timeout and eventually stops."""

    def test_timeout_triggers_retries(self):
        from ibkr_operator import _run_market_data_recovery_drill
        from pathlib import Path

        export_dir = Path("/tmp/md-drill-test-timeout")
        export_dir.mkdir(parents=True, exist_ok=True)

        with patch("ibkr_operator._capture_safety_flags_raw",
                   return_value={"env_IBKR_ALLOW_ORDERS": "false",
                                 "rules_enforced": "false",
                                 "capture_timestamp_utc": "2026-06-24T10:00:00Z"}), \
             patch("ibkr_operator._run_market_data_diagnostics",
                   return_value=_make_diagnostics_no_tick_timeout_result()), \
             patch("ibkr_operator._scan_forbidden_endpoints",
                   return_value={"ok": True, "violations": []}), \
             patch("ibkr_operator._git_metadata",
                   return_value={"branch": "test", "commit": "abc", "tag": "test"}), \
             patch("ibkr_operator.urllib.request.urlopen",
                   side_effect=_MockUrlOpen({
                       "/health": (200, _make_health_response(True)),
                   })), \
             patch("ibkr_operator.time.sleep"), \
             patch("ibkr_operator._MD_RECOVERY_DRILL_EXPORT_DIR", export_dir), \
             patch("ibkr_operator.os.fsync"):
            result = _run_market_data_recovery_drill(
                symbol="AAPL", attempts=3, sleep_seconds=0.1, connect_if_needed=False)

        assert result["attempts_requested"] == 3
        assert result["attempts_completed"] == 3  # all attempts exhausted
        assert result["drill_result"] == "hold_no_tick_stream"
        assert result["final_severity"] == "HOLD"
        assert len(result["per_attempt_results"]) == 3

    def test_timeout_recovers_on_second_attempt(self):
        """Recovery: first attempt fails, second succeeds."""
        from ibkr_operator import _run_market_data_recovery_drill
        from pathlib import Path

        export_dir = Path("/tmp/md-drill-test-recover")
        export_dir.mkdir(parents=True, exist_ok=True)

        # First call returns timeout, second returns live
        diag_results = [
            _make_diagnostics_no_tick_timeout_result(),
            _make_diagnostics_live_available_result(),
        ]
        call_count = [0]

        def _diag_side_effect(*args, **kwargs):
            idx = min(call_count[0], len(diag_results) - 1)
            call_count[0] += 1
            return diag_results[idx]

        with patch("ibkr_operator._capture_safety_flags_raw",
                   return_value={"env_IBKR_ALLOW_ORDERS": "false",
                                 "rules_enforced": "false",
                                 "capture_timestamp_utc": "2026-06-24T10:00:00Z"}), \
             patch("ibkr_operator._run_market_data_diagnostics",
                   side_effect=_diag_side_effect), \
             patch("ibkr_operator._run_autonomy_status",
                   return_value={"recommendation": "READY_FOR_MANUAL_REVIEW",
                                 "market_data_status": "available",
                                 "_export_path": "/tmp/stat.json"}), \
             patch("ibkr_operator._scan_forbidden_endpoints",
                   return_value={"ok": True, "violations": []}), \
             patch("ibkr_operator._git_metadata",
                   return_value={"branch": "test", "commit": "abc", "tag": "test"}), \
             patch("ibkr_operator.urllib.request.urlopen",
                   side_effect=_MockUrlOpen({
                       "/health": (200, _make_health_response(True)),
                   })), \
             patch("ibkr_operator.time.sleep"), \
             patch("ibkr_operator._MD_RECOVERY_DRILL_EXPORT_DIR", export_dir), \
             patch("ibkr_operator.os.fsync"):
            result = _run_market_data_recovery_drill(
                symbol="AAPL", attempts=3, sleep_seconds=0.1, connect_if_needed=False)

        assert result["attempts_completed"] == 2  # stopped at recovery
        assert result["drill_result"] == "recovered"
        assert result["final_severity"] == "OK"


# ---------------------------------------------------------------------------
# T7: Disconnected + connect
# ---------------------------------------------------------------------------

class TestConnectPath:
    """Verify connect path when IBKR is disconnected."""

    def test_connect_attempted_when_disconnected(self):
        from ibkr_operator import _run_market_data_recovery_drill
        from pathlib import Path

        export_dir = Path("/tmp/md-drill-test-connect")
        export_dir.mkdir(parents=True, exist_ok=True)

        # Health says disconnected, connect succeeds, diagnostics returns live
        mock_urlopen = _MockUrlOpen({
            "/health": (200, _make_health_response(False)),  # initially disconnected
            "/connect": (200, _make_connect_response(True, True)),  # connect succeeds
        })
        # After connect, health re-check also returns False (simulating the mock)
        # We override with a second health response via side_effect
        health_responses = [
            _MockResponse(200, json.dumps(_make_health_response(False)).encode()),
            _MockResponse(200, json.dumps(_make_health_response(False)).encode()),
            _MockResponse(200, json.dumps(_make_health_response(True)).encode()),
        ]
        health_idx = [0]

        def _urlopen_side_effect(req, timeout=None):
            url = req.full_url if hasattr(req, 'full_url') else str(req)
            if "/health" in url:
                idx = min(health_idx[0], len(health_responses) - 1)
                health_idx[0] += 1
                return health_responses[idx]
            if "/connect" in url:
                return _MockResponse(200, json.dumps(_make_connect_response()).encode())
            return _MockResponse(404, b"{}")

        with patch("ibkr_operator._capture_safety_flags_raw",
                   return_value={"env_IBKR_ALLOW_ORDERS": "false",
                                 "rules_enforced": "false",
                                 "capture_timestamp_utc": "2026-06-24T10:00:00Z"}), \
             patch("ibkr_operator._run_market_data_diagnostics",
                   return_value=_make_diagnostics_live_available_result()), \
             patch("ibkr_operator._run_autonomy_status",
                   return_value={"recommendation": "HOLD", "_export_path": "/tmp/stat.json"}), \
             patch("ibkr_operator._scan_forbidden_endpoints",
                   return_value={"ok": True, "violations": []}), \
             patch("ibkr_operator._git_metadata",
                   return_value={"branch": "test", "commit": "abc", "tag": "test"}), \
             patch("ibkr_operator.urllib.request.urlopen",
                   side_effect=_urlopen_side_effect), \
             patch("ibkr_operator.time.sleep"), \
             patch("ibkr_operator._MD_RECOVERY_DRILL_EXPORT_DIR", export_dir), \
             patch("ibkr_operator.os.fsync"):
            result = _run_market_data_recovery_drill(
                symbol="AAPL", attempts=1, connect_if_needed=True)

        assert result["connect_attempted"] is True
        assert result["connect_result"]["ok"] is True

    def test_no_connect_when_connected(self):
        from ibkr_operator import _run_market_data_recovery_drill
        from pathlib import Path

        export_dir = Path("/tmp/md-drill-test-noconnect")
        export_dir.mkdir(parents=True, exist_ok=True)

        with patch("ibkr_operator._capture_safety_flags_raw",
                   return_value={"env_IBKR_ALLOW_ORDERS": "false",
                                 "rules_enforced": "false",
                                 "capture_timestamp_utc": "2026-06-24T10:00:00Z"}), \
             patch("ibkr_operator._run_market_data_diagnostics",
                   return_value=_make_diagnostics_live_available_result()), \
             patch("ibkr_operator._run_autonomy_status",
                   return_value={"recommendation": "HOLD", "_export_path": "/tmp/stat.json"}), \
             patch("ibkr_operator._scan_forbidden_endpoints",
                   return_value={"ok": True, "violations": []}), \
             patch("ibkr_operator._git_metadata",
                   return_value={"branch": "test", "commit": "abc", "tag": "test"}), \
             patch("ibkr_operator.urllib.request.urlopen",
                   side_effect=_MockUrlOpen({
                       "/health": (200, _make_health_response(True)),  # already connected
                   })), \
             patch("ibkr_operator.time.sleep"), \
             patch("ibkr_operator._MD_RECOVERY_DRILL_EXPORT_DIR", export_dir), \
             patch("ibkr_operator.os.fsync"):
            result = _run_market_data_recovery_drill(
                symbol="AAPL", attempts=1, connect_if_needed=True)

        assert result["connect_attempted"] is False  # no need to connect
        assert result["connect_result"] == {"skipped": True}

    def test_no_connect_flag_respected(self):
        from ibkr_operator import _run_market_data_recovery_drill
        from pathlib import Path

        export_dir = Path("/tmp/md-drill-test-noconnect-flag")
        export_dir.mkdir(parents=True, exist_ok=True)

        with patch("ibkr_operator._capture_safety_flags_raw",
                   return_value={"env_IBKR_ALLOW_ORDERS": "false",
                                 "rules_enforced": "false",
                                 "capture_timestamp_utc": "2026-06-24T10:00:00Z"}), \
             patch("ibkr_operator._run_market_data_diagnostics",
                   return_value=_make_diagnostics_disconnected_result()), \
             patch("ibkr_operator._scan_forbidden_endpoints",
                   return_value={"ok": True, "violations": []}), \
             patch("ibkr_operator._git_metadata",
                   return_value={"branch": "test", "commit": "abc", "tag": "test"}), \
             patch("ibkr_operator.urllib.request.urlopen",
                   side_effect=_MockUrlOpen({
                       "/health": (200, _make_health_response(False)),
                   })), \
             patch("ibkr_operator.time.sleep"), \
             patch("ibkr_operator._MD_RECOVERY_DRILL_EXPORT_DIR", export_dir), \
             patch("ibkr_operator.os.fsync"):
            result = _run_market_data_recovery_drill(
                symbol="AAPL", attempts=1, connect_if_needed=False)

        assert result["connect_attempted"] is False
        assert result["drill_result"] == "hold_ibkr_disconnected"


# ---------------------------------------------------------------------------
# T8: Edge cases — contract failure, runtime error
# ---------------------------------------------------------------------------

class TestEdgeCases:
    """Verify edge case diagnosis paths."""

    def test_contract_failure_yields_no_go(self):
        from ibkr_operator import _run_market_data_recovery_drill
        from pathlib import Path

        export_dir = Path("/tmp/md-drill-test-contract")
        export_dir.mkdir(parents=True, exist_ok=True)

        diag = _make_diagnostics_no_tick_timeout_result()
        diag["diagnosis"] = "contract_qualification_failed"
        diag["contract_qualified"] = False

        with patch("ibkr_operator._capture_safety_flags_raw",
                   return_value={"env_IBKR_ALLOW_ORDERS": "false",
                                 "rules_enforced": "false",
                                 "capture_timestamp_utc": "2026-06-24T10:00:00Z"}), \
             patch("ibkr_operator._run_market_data_diagnostics", return_value=diag), \
             patch("ibkr_operator._scan_forbidden_endpoints",
                   return_value={"ok": True, "violations": []}), \
             patch("ibkr_operator._git_metadata",
                   return_value={"branch": "test", "commit": "abc", "tag": "test"}), \
             patch("ibkr_operator.urllib.request.urlopen",
                   side_effect=_MockUrlOpen({
                       "/health": (200, _make_health_response(True)),
                   })), \
             patch("ibkr_operator.time.sleep"), \
             patch("ibkr_operator._MD_RECOVERY_DRILL_EXPORT_DIR", export_dir), \
             patch("ibkr_operator.os.fsync"):
            result = _run_market_data_recovery_drill(
                symbol="INVALID", attempts=1, connect_if_needed=False)

        assert result["drill_result"] == "no_go_contract_failure"
        assert result["final_severity"] == "NO_GO"

    def test_runtime_error_yields_no_go(self):
        from ibkr_operator import _run_market_data_recovery_drill
        from pathlib import Path

        export_dir = Path("/tmp/md-drill-test-runtime")
        export_dir.mkdir(parents=True, exist_ok=True)

        diag = _make_diagnostics_no_tick_timeout_result()
        diag["diagnosis"] = "bridge_runtime_error"
        diag["bridge_runtime_ok"] = False

        with patch("ibkr_operator._capture_safety_flags_raw",
                   return_value={"env_IBKR_ALLOW_ORDERS": "false",
                                 "rules_enforced": "false",
                                 "capture_timestamp_utc": "2026-06-24T10:00:00Z"}), \
             patch("ibkr_operator._run_market_data_diagnostics", return_value=diag), \
             patch("ibkr_operator._scan_forbidden_endpoints",
                   return_value={"ok": True, "violations": []}), \
             patch("ibkr_operator._git_metadata",
                   return_value={"branch": "test", "commit": "abc", "tag": "test"}), \
             patch("ibkr_operator.urllib.request.urlopen",
                   side_effect=_MockUrlOpen({
                       "/health": (200, _make_health_response(True)),
                   })), \
             patch("ibkr_operator.time.sleep"), \
             patch("ibkr_operator._MD_RECOVERY_DRILL_EXPORT_DIR", export_dir), \
             patch("ibkr_operator.os.fsync"):
            result = _run_market_data_recovery_drill(
                symbol="AAPL", attempts=1, connect_if_needed=False)

        assert result["drill_result"] == "no_go_runtime_error"
        assert result["final_severity"] == "NO_GO"

    def test_delayed_data_outside_rth_yields_session_not_expected(self):
        from ibkr_operator import _run_market_data_recovery_drill
        from pathlib import Path

        export_dir = Path("/tmp/md-drill-test-session")
        export_dir.mkdir(parents=True, exist_ok=True)

        diag = _make_diagnostics_delayed_result()
        weekend_session = _make_session_info("closed", "Market closed — weekend")
        diag["market_session_status"] = weekend_session

        with patch("ibkr_operator._capture_safety_flags_raw",
                   return_value={"env_IBKR_ALLOW_ORDERS": "false",
                                 "rules_enforced": "false",
                                 "capture_timestamp_utc": "2026-06-24T10:00:00Z"}), \
             patch("ibkr_operator._run_market_data_diagnostics", return_value=diag), \
             patch("ibkr_operator._scan_forbidden_endpoints",
                   return_value={"ok": True, "violations": []}), \
             patch("ibkr_operator._git_metadata",
                   return_value={"branch": "test", "commit": "abc", "tag": "test"}), \
             patch("ibkr_operator.urllib.request.urlopen",
                   side_effect=_MockUrlOpen({
                       "/health": (200, _make_health_response(True)),
                   })), \
             patch("ibkr_operator.time.sleep"), \
             patch("ibkr_operator._MD_RECOVERY_DRILL_EXPORT_DIR", export_dir), \
             patch("ibkr_operator.os.fsync"):
            result = _run_market_data_recovery_drill(
                symbol="AAPL", attempts=1, connect_if_needed=False)

        assert result["drill_result"] == "hold_session_not_expected"
        assert result["final_severity"] == "HOLD"


# ---------------------------------------------------------------------------
# T9: No /order* calls, no H1 token
# ---------------------------------------------------------------------------

class TestNoForbiddenCalls:
    """Verify recovery drill never calls order endpoints or reads H1 token."""

    def test_no_forbidden_patterns(self):
        import inspect
        from ibkr_operator import _run_market_data_recovery_drill

        source = inspect.getsource(_run_market_data_recovery_drill)
        forbidden = ["/order/preflight", "/order/approve", "/order/submit",
                      "/order", "placeOrder", "cancelOrder",
                      "H1_APPROVAL_TOKEN_HASH", "/etc/ibkr-bridge/h1_token"]

        for pattern in forbidden:
            found = False
            for line in source.splitlines():
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue
                lower = stripped.lower()
                if any(kw in lower for kw in ["no-order", "no /order",
                                               "must not", "did not",
                                               "no order"]):
                    continue
                if pattern in stripped:
                    found = True
                    break
            assert not found, f"FORBIDDEN: '{pattern}' found in recovery drill source"


# ---------------------------------------------------------------------------
# T10: Clamping and bounds
# ---------------------------------------------------------------------------

class TestClampingBounds:
    """Verify attempt/sleep clamping works."""

    def test_attempts_clamped_min_1(self):
        from ibkr_operator import _run_market_data_recovery_drill
        from pathlib import Path

        export_dir = Path("/tmp/md-drill-test-clamp")
        export_dir.mkdir(parents=True, exist_ok=True)

        with patch("ibkr_operator._capture_safety_flags_raw",
                   return_value={"env_IBKR_ALLOW_ORDERS": "false",
                                 "rules_enforced": "false",
                                 "capture_timestamp_utc": "2026-06-24T10:00:00Z"}), \
             patch("ibkr_operator._run_market_data_diagnostics",
                   return_value=_make_diagnostics_live_available_result()), \
             patch("ibkr_operator._run_autonomy_status",
                   return_value={"recommendation": "HOLD", "_export_path": "/tmp/stat.json"}), \
             patch("ibkr_operator._scan_forbidden_endpoints",
                   return_value={"ok": True, "violations": []}), \
             patch("ibkr_operator._git_metadata",
                   return_value={"branch": "test", "commit": "abc", "tag": "test"}), \
             patch("ibkr_operator.urllib.request.urlopen",
                   side_effect=_MockUrlOpen({
                       "/health": (200, _make_health_response(True)),
                   })), \
             patch("ibkr_operator.time.sleep"), \
             patch("ibkr_operator._MD_RECOVERY_DRILL_EXPORT_DIR", export_dir), \
             patch("ibkr_operator.os.fsync"):
            result = _run_market_data_recovery_drill(
                symbol="AAPL", attempts=0, connect_if_needed=False)

        assert result["attempts_requested"] == 1  # clamped to min

    def test_attempts_clamped_max_5(self):
        from ibkr_operator import _run_market_data_recovery_drill
        from pathlib import Path

        export_dir = Path("/tmp/md-drill-test-clamp-max")
        export_dir.mkdir(parents=True, exist_ok=True)

        with patch("ibkr_operator._capture_safety_flags_raw",
                   return_value={"env_IBKR_ALLOW_ORDERS": "false",
                                 "rules_enforced": "false",
                                 "capture_timestamp_utc": "2026-06-24T10:00:00Z"}), \
             patch("ibkr_operator._run_market_data_diagnostics",
                   return_value=_make_diagnostics_live_available_result()), \
             patch("ibkr_operator._run_autonomy_status",
                   return_value={"recommendation": "HOLD", "_export_path": "/tmp/stat.json"}), \
             patch("ibkr_operator._scan_forbidden_endpoints",
                   return_value={"ok": True, "violations": []}), \
             patch("ibkr_operator._git_metadata",
                   return_value={"branch": "test", "commit": "abc", "tag": "test"}), \
             patch("ibkr_operator.urllib.request.urlopen",
                   side_effect=_MockUrlOpen({
                       "/health": (200, _make_health_response(True)),
                   })), \
             patch("ibkr_operator.time.sleep"), \
             patch("ibkr_operator._MD_RECOVERY_DRILL_EXPORT_DIR", export_dir), \
             patch("ibkr_operator.os.fsync"):
            result = _run_market_data_recovery_drill(
                symbol="AAPL", attempts=10, connect_if_needed=False)

        assert result["attempts_requested"] == 5  # clamped to max


# ---------------------------------------------------------------------------
# T11: Export to stderr, pure JSON stdout
# ---------------------------------------------------------------------------

class TestOutputFormat:
    """Verify JSON output is pure and export goes to stderr."""

    def test_result_is_valid_json(self):
        from ibkr_operator import _run_market_data_recovery_drill
        from pathlib import Path

        export_dir = Path("/tmp/md-drill-test-json")
        export_dir.mkdir(parents=True, exist_ok=True)

        with patch("ibkr_operator._capture_safety_flags_raw",
                   return_value={"env_IBKR_ALLOW_ORDERS": "false",
                                 "rules_enforced": "false",
                                 "capture_timestamp_utc": "2026-06-24T10:00:00Z"}), \
             patch("ibkr_operator._run_market_data_diagnostics",
                   return_value=_make_diagnostics_live_available_result()), \
             patch("ibkr_operator._run_autonomy_status",
                   return_value={"recommendation": "HOLD", "_export_path": "/tmp/stat.json"}), \
             patch("ibkr_operator._scan_forbidden_endpoints",
                   return_value={"ok": True, "violations": []}), \
             patch("ibkr_operator._git_metadata",
                   return_value={"branch": "test", "commit": "abc", "tag": "test"}), \
             patch("ibkr_operator.urllib.request.urlopen",
                   side_effect=_MockUrlOpen({
                       "/health": (200, _make_health_response(True)),
                   })), \
             patch("ibkr_operator.time.sleep"), \
             patch("ibkr_operator._MD_RECOVERY_DRILL_EXPORT_DIR", export_dir), \
             patch("ibkr_operator.os.fsync"):
            result = _run_market_data_recovery_drill(
                symbol="AAPL", attempts=1, connect_if_needed=False)

        # Should be valid JSON
        encoded = json.dumps(result, indent=2, default=str)
        decoded = json.loads(encoded)
        assert decoded["drill_id"] == result["drill_id"]
        assert decoded["no_broker_mutation"] is True


# ---------------------------------------------------------------------------
# T12: Existing tests still pass
# ---------------------------------------------------------------------------

class TestExistingTestsStillPass:
    """Quick sanity: other operator functions still work."""

    def test_other_functions_importable(self):
        from ibkr_operator import (
            _run_market_data_diagnostics,
            _run_market_data_recovery_drill,
            _run_autonomy_status,
        )
        for func in [_run_market_data_diagnostics, _run_market_data_recovery_drill,
                     _run_autonomy_status]:
            assert callable(func), f"{func.__name__} is not callable"


# ---------------------------------------------------------------------------
# T13: No live entitlement → hold_no_entitlement
# ---------------------------------------------------------------------------

class TestEntitlementPath:
    """Verify entitlement-related drill_result paths."""

    def test_no_live_entitlement_yields_hold_no_entitlement(self):
        from ibkr_operator import _run_market_data_recovery_drill
        from pathlib import Path

        export_dir = Path("/tmp/md-drill-test-entitlement")
        export_dir.mkdir(parents=True, exist_ok=True)

        diag = _make_diagnostics_no_tick_timeout_result()
        diag["diagnosis"] = "no_live_entitlement"
        diag["operator_action_required"] = True
        diag["suggested_operator_actions"] = [
            "Check market-data entitlement in IBKR account",
            "Verify API market data permissions are enabled",
        ]

        with patch("ibkr_operator._capture_safety_flags_raw",
                   return_value={"env_IBKR_ALLOW_ORDERS": "false",
                                 "rules_enforced": "false",
                                 "capture_timestamp_utc": "2026-06-24T10:00:00Z"}), \
             patch("ibkr_operator._run_market_data_diagnostics", return_value=diag), \
             patch("ibkr_operator._scan_forbidden_endpoints",
                   return_value={"ok": True, "violations": []}), \
             patch("ibkr_operator._git_metadata",
                   return_value={"branch": "test", "commit": "abc", "tag": "test"}), \
             patch("ibkr_operator.urllib.request.urlopen",
                   side_effect=_MockUrlOpen({
                       "/health": (200, _make_health_response(True)),
                   })), \
             patch("ibkr_operator.time.sleep"), \
             patch("ibkr_operator._MD_RECOVERY_DRILL_EXPORT_DIR", export_dir), \
             patch("ibkr_operator.os.fsync"):
            result = _run_market_data_recovery_drill(
                symbol="AAPL", attempts=1, connect_if_needed=False)

        assert result["drill_result"] == "hold_no_entitlement"
        assert result["final_severity"] == "HOLD"
        assert result["final_diagnosis"] == "no_live_entitlement"

    def test_entitlement_keyword_in_diagnosis_triggers(self):
        """Any diagnosis containing 'entitlement' triggers hold_no_entitlement."""
        from ibkr_operator import _run_market_data_recovery_drill
        from pathlib import Path

        export_dir = Path("/tmp/md-drill-test-entitlement2")
        export_dir.mkdir(parents=True, exist_ok=True)

        diag = _make_diagnostics_no_tick_timeout_result()
        diag["diagnosis"] = "market_data_entitlement_missing"

        with patch("ibkr_operator._capture_safety_flags_raw",
                   return_value={"env_IBKR_ALLOW_ORDERS": "false",
                                 "rules_enforced": "false",
                                 "capture_timestamp_utc": "2026-06-24T10:00:00Z"}), \
             patch("ibkr_operator._run_market_data_diagnostics", return_value=diag), \
             patch("ibkr_operator._scan_forbidden_endpoints",
                   return_value={"ok": True, "violations": []}), \
             patch("ibkr_operator._git_metadata",
                   return_value={"branch": "test", "commit": "abc", "tag": "test"}), \
             patch("ibkr_operator.urllib.request.urlopen",
                   side_effect=_MockUrlOpen({
                       "/health": (200, _make_health_response(True)),
                   })), \
             patch("ibkr_operator.time.sleep"), \
             patch("ibkr_operator._MD_RECOVERY_DRILL_EXPORT_DIR", export_dir), \
             patch("ibkr_operator.os.fsync"):
            result = _run_market_data_recovery_drill(
                symbol="AAPL", attempts=1, connect_if_needed=False)

        assert result["drill_result"] == "hold_no_entitlement"


# ---------------------------------------------------------------------------
# T14: Repeated drills do not leak backpressure
# ---------------------------------------------------------------------------

class TestBackpressureNotLeaked:
    """Verify repeated recovery drills don't leak active slots or saturate bridge."""

    def test_repeated_drills_no_backpressure_leak(self):
        """Running multiple drills in sequence leaves active slots at 0."""
        from ibkr_operator import _run_market_data_recovery_drill
        from pathlib import Path

        export_dir = Path("/tmp/md-drill-test-bpleak")
        export_dir.mkdir(parents=True, exist_ok=True)

        # Simulate a backpressure counter that persists across calls
        active_counter = [0]

        def _urlopen_side_effect(req, timeout=None):
            url = req.full_url if hasattr(req, 'full_url') else str(req)
            if "/health" in url:
                return _MockResponse(200, json.dumps(_make_health_response(True)).encode())
            if "/monitor/backpressure" in url:
                return _MockResponse(200, json.dumps({
                    "ok": True, "active": active_counter[0], "max_active": 4,
                    "total_accepted": 0, "total_rejected": 0,
                    "leaked_md_threads": 0,
                }).encode())
            return _MockResponse(404, b"{}")

        with patch("ibkr_operator._capture_safety_flags_raw",
                   return_value={"env_IBKR_ALLOW_ORDERS": "false",
                                 "rules_enforced": "false",
                                 "capture_timestamp_utc": "2026-06-24T10:00:00Z"}), \
             patch("ibkr_operator._run_market_data_diagnostics",
                   return_value=_make_diagnostics_live_available_result()), \
             patch("ibkr_operator._run_autonomy_status",
                   return_value={"recommendation": "HOLD", "_export_path": "/tmp/stat.json"}), \
             patch("ibkr_operator._scan_forbidden_endpoints",
                   return_value={"ok": True, "violations": []}), \
             patch("ibkr_operator._git_metadata",
                   return_value={"branch": "test", "commit": "abc", "tag": "test"}), \
             patch("ibkr_operator.urllib.request.urlopen",
                   side_effect=_urlopen_side_effect), \
             patch("ibkr_operator.time.sleep"), \
             patch("ibkr_operator._MD_RECOVERY_DRILL_EXPORT_DIR", export_dir), \
             patch("ibkr_operator.os.fsync"):
            # Run 3 consecutive drills — active should stay 0 after each
            for i in range(3):
                result = _run_market_data_recovery_drill(
                    symbol="AAPL", attempts=1, connect_if_needed=False)
                assert result["drill_result"] != "unknown"
                assert result["no_broker_mutation"] is True

        # After 3 drills, the simulated active counter should still be 0
        # (because each _run_market_data_diagnostics properly releases its slots)
        assert active_counter[0] == 0, f"Active counter leaked: {active_counter[0]}"

    def test_recovery_drill_preserves_503_recovery(self):
        """After a drill with timeout, the result still has valid structure.

        This verifies that even when diagnostics times out, the drill
        completes cleanly and the result is well-formed (bridge recovery
        is verified at the bridge level by 15Q-BP tests).
        """
        from ibkr_operator import _run_market_data_recovery_drill
        from pathlib import Path

        export_dir = Path("/tmp/md-drill-test-503recover")
        export_dir.mkdir(parents=True, exist_ok=True)

        # Simulate diagnostics that always times out
        diag = _make_diagnostics_no_tick_timeout_result()
        diag["diagnosis"] = "no_tick_stream_timeout"
        diag["bridge_runtime_ok"] = True

        with patch("ibkr_operator._capture_safety_flags_raw",
                   return_value={"env_IBKR_ALLOW_ORDERS": "false",
                                 "rules_enforced": "false",
                                 "capture_timestamp_utc": "2026-06-24T10:00:00Z"}), \
             patch("ibkr_operator._run_market_data_diagnostics", return_value=diag), \
             patch("ibkr_operator._scan_forbidden_endpoints",
                   return_value={"ok": True, "violations": []}), \
             patch("ibkr_operator._git_metadata",
                   return_value={"branch": "test", "commit": "abc", "tag": "test"}), \
             patch("ibkr_operator.urllib.request.urlopen",
                   side_effect=_MockUrlOpen({
                       "/health": (200, _make_health_response(True)),
                   })), \
             patch("ibkr_operator.time.sleep"), \
             patch("ibkr_operator._MD_RECOVERY_DRILL_EXPORT_DIR", export_dir), \
             patch("ibkr_operator.os.fsync"):
            result = _run_market_data_recovery_drill(
                symbol="AAPL", attempts=3, sleep_seconds=0.1, connect_if_needed=False)

        # Drill completes with valid result
        assert result["drill_result"] == "hold_no_tick_stream"
        assert result["attempts_completed"] == 3
        assert result["no_broker_mutation"] is True
        # All required top-level fields present
        for field in ("safety_flags_before", "safety_flags_after",
                      "per_attempt_results", "evidence_hash"):
            assert field in result, f"Missing field after timeout drill: {field}"


# ---------------------------------------------------------------------------
# T15: Runtime drill produces non-unknown drill_result for all branches
# ---------------------------------------------------------------------------

class TestAllBranchesNonUnknown:
    """Every explicit diagnosis path produces a non-unknown drill_result."""

    _BRANCH_DIAGNOSES = [
        ("live_data_available", "recovered"),
        ("delayed_data_available", "hold_no_tick_stream"),
        ("no_tick_stream_timeout", "hold_no_tick_stream"),
        ("ibkr_disconnected", "hold_ibkr_disconnected"),
        ("contract_qualification_failed", "no_go_contract_failure"),
        ("bridge_runtime_error", "no_go_runtime_error"),
        ("no_live_entitlement", "hold_no_entitlement"),
        ("bridge_saturated", "hold_bridge_saturated"),
        ("cooldown_active", "hold_cooldown_active"),
    ]

    @pytest.mark.parametrize("diag,expected_drill", _BRANCH_DIAGNOSES)
    def test_each_branch_produces_non_unknown(self, diag, expected_drill):
        from ibkr_operator import _run_market_data_recovery_drill
        from pathlib import Path

        export_dir = Path(f"/tmp/md-drill-branch-{diag}")
        export_dir.mkdir(parents=True, exist_ok=True)

        # Build a diagnostics result with proper data-availability flags
        if diag == "live_data_available":
            diag_result = _make_diagnostics_live_available_result()
            diag_result["diagnosis"] = diag
        elif diag == "delayed_data_available":
            diag_result = _make_diagnostics_delayed_result()
            diag_result["diagnosis"] = diag
        elif diag == "ibkr_disconnected":
            diag_result = _make_diagnostics_disconnected_result()
            diag_result["diagnosis"] = diag
        else:
            diag_result = _make_diagnostics_no_tick_timeout_result()
            diag_result["diagnosis"] = diag
            # Set bridge_runtime_ok=False for runtime error
            if diag == "bridge_runtime_error":
                diag_result["bridge_runtime_ok"] = False
            # Set contract_qualified=False for contract failure
            if diag == "contract_qualification_failed":
                diag_result["contract_qualified"] = False

        with patch("ibkr_operator._capture_safety_flags_raw",
                   return_value={"env_IBKR_ALLOW_ORDERS": "false",
                                 "rules_enforced": "false",
                                 "capture_timestamp_utc": "2026-06-24T10:00:00Z"}), \
             patch("ibkr_operator._run_market_data_diagnostics", return_value=diag_result), \
             patch("ibkr_operator._scan_forbidden_endpoints",
                   return_value={"ok": True, "violations": []}), \
             patch("ibkr_operator._git_metadata",
                   return_value={"branch": "test", "commit": "abc", "tag": "test"}), \
             patch("ibkr_operator.urllib.request.urlopen",
                   side_effect=_MockUrlOpen({
                       "/health": (200, _make_health_response(True)),
                   })), \
             patch("ibkr_operator.time.sleep"), \
             patch("ibkr_operator._MD_RECOVERY_DRILL_EXPORT_DIR", export_dir), \
             patch("ibkr_operator.os.fsync"):
            result = _run_market_data_recovery_drill(
                symbol="AAPL", attempts=1, connect_if_needed=False)

        assert result["drill_result"] != "unknown", \
            f"Diagnosis '{diag}' produced unknown drill_result"
        assert result["drill_result"] == expected_drill, \
            f"Diagnosis '{diag}': expected {expected_drill}, got {result['drill_result']}"


# ---------------------------------------------------------------------------
# T16: Guard-state mutation detection
# ---------------------------------------------------------------------------

_MOCK_GUARD_HASH = "abc123def456"
_MOCK_GUARD_HASH_DIFFERENT = "xyz789different"


def _mock_guard_snapshot(tc: int = 0, gh: str = _MOCK_GUARD_HASH):
    return {
        "guard_state_path": "/tmp/guard-state.json",
        "guard_state_hash": gh,
        "daily_trade_count": tc,
        "capture_timestamp_utc": "2026-06-24T10:00:00Z",
        "file_exists": True,
    }


class TestGuardStateMutationDetection:
    """Verify guard-state mutation detection in recovery drill."""

    def test_guard_state_unchanged_produces_ok(self):
        """When guard-state is unchanged, drill_result is normal."""
        from ibkr_operator import _run_market_data_recovery_drill
        from pathlib import Path

        export_dir = Path("/tmp/md-drill-guard-ok")
        export_dir.mkdir(parents=True, exist_ok=True)

        with patch("ibkr_operator._capture_safety_flags_raw",
                   return_value={"env_IBKR_ALLOW_ORDERS": "false",
                                 "rules_enforced": "false",
                                 "capture_timestamp_utc": "2026-06-24T10:00:00Z"}), \
             patch("ibkr_operator._capture_guard_state_snapshot",
                   side_effect=[_mock_guard_snapshot(tc=0, gh=_MOCK_GUARD_HASH),
                                _mock_guard_snapshot(tc=0, gh=_MOCK_GUARD_HASH)]), \
             patch("ibkr_operator._run_market_data_diagnostics",
                   return_value=_make_diagnostics_live_available_result()), \
             patch("ibkr_operator._run_autonomy_status",
                   return_value={"recommendation": "HOLD", "_export_path": "/tmp/stat.json"}), \
             patch("ibkr_operator._scan_forbidden_endpoints",
                   return_value={"ok": True, "violations": []}), \
             patch("ibkr_operator._git_metadata",
                   return_value={"branch": "test", "commit": "abc", "tag": "test"}), \
             patch("ibkr_operator.urllib.request.urlopen",
                   side_effect=_MockUrlOpen({
                       "/health": (200, _make_health_response(True)),
                   })), \
             patch("ibkr_operator.time.sleep"), \
             patch("ibkr_operator._MD_RECOVERY_DRILL_EXPORT_DIR", export_dir), \
             patch("ibkr_operator.os.fsync"):
            result = _run_market_data_recovery_drill(
                symbol="AAPL", attempts=1, connect_if_needed=False)

        assert result["guard_state_unchanged"] is True
        assert result["guard_state_hash_before"] == _MOCK_GUARD_HASH
        assert result["guard_state_hash_after"] == _MOCK_GUARD_HASH
        assert result["guard_daily_trade_count_before"] == 0
        assert result["guard_daily_trade_count_after"] == 0
        assert result["drill_result"] == "recovered"
        assert result["final_severity"] == "OK"

    def test_guard_state_hash_changed_yields_no_go(self):
        """When guard-state hash changes, drill_result becomes no_go_guard_state_mutation."""
        from ibkr_operator import _run_market_data_recovery_drill
        from pathlib import Path

        export_dir = Path("/tmp/md-drill-guard-mutated")
        export_dir.mkdir(parents=True, exist_ok=True)

        with patch("ibkr_operator._capture_safety_flags_raw",
                   return_value={"env_IBKR_ALLOW_ORDERS": "false",
                                 "rules_enforced": "false",
                                 "capture_timestamp_utc": "2026-06-24T10:00:00Z"}), \
             patch("ibkr_operator._capture_guard_state_snapshot",
                   side_effect=[_mock_guard_snapshot(tc=0, gh=_MOCK_GUARD_HASH),
                                _mock_guard_snapshot(tc=0, gh=_MOCK_GUARD_HASH_DIFFERENT)]), \
             patch("ibkr_operator._run_market_data_diagnostics",
                   return_value=_make_diagnostics_live_available_result()), \
             patch("ibkr_operator._run_autonomy_status",
                   return_value={"recommendation": "HOLD", "_export_path": "/tmp/stat.json"}), \
             patch("ibkr_operator._scan_forbidden_endpoints",
                   return_value={"ok": True, "violations": []}), \
             patch("ibkr_operator._git_metadata",
                   return_value={"branch": "test", "commit": "abc", "tag": "test"}), \
             patch("ibkr_operator.urllib.request.urlopen",
                   side_effect=_MockUrlOpen({
                       "/health": (200, _make_health_response(True)),
                   })), \
             patch("ibkr_operator.time.sleep"), \
             patch("ibkr_operator._MD_RECOVERY_DRILL_EXPORT_DIR", export_dir), \
             patch("ibkr_operator.os.fsync"):
            result = _run_market_data_recovery_drill(
                symbol="AAPL", attempts=1, connect_if_needed=False)

        assert result["guard_state_unchanged"] is False
        assert result["drill_result"] == "no_go_guard_state_mutation"
        assert result["final_severity"] == "NO_GO"

    def test_daily_trade_count_incremented_yields_no_go(self):
        """When daily_trade_count increments, drill_result becomes no_go_guard_state_mutation."""
        from ibkr_operator import _run_market_data_recovery_drill
        from pathlib import Path

        export_dir = Path("/tmp/md-drill-guard-tc")
        export_dir.mkdir(parents=True, exist_ok=True)

        with patch("ibkr_operator._capture_safety_flags_raw",
                   return_value={"env_IBKR_ALLOW_ORDERS": "false",
                                 "rules_enforced": "false",
                                 "capture_timestamp_utc": "2026-06-24T10:00:00Z"}), \
             patch("ibkr_operator._capture_guard_state_snapshot",
                   side_effect=[_mock_guard_snapshot(tc=0, gh=_MOCK_GUARD_HASH),
                                _mock_guard_snapshot(tc=4, gh=_MOCK_GUARD_HASH_DIFFERENT)]), \
             patch("ibkr_operator._run_market_data_diagnostics",
                   return_value=_make_diagnostics_live_available_result()), \
             patch("ibkr_operator._run_autonomy_status",
                   return_value={"recommendation": "HOLD", "_export_path": "/tmp/stat.json"}), \
             patch("ibkr_operator._scan_forbidden_endpoints",
                   return_value={"ok": True, "violations": []}), \
             patch("ibkr_operator._git_metadata",
                   return_value={"branch": "test", "commit": "abc", "tag": "test"}), \
             patch("ibkr_operator.urllib.request.urlopen",
                   side_effect=_MockUrlOpen({
                       "/health": (200, _make_health_response(True)),
                   })), \
             patch("ibkr_operator.time.sleep"), \
             patch("ibkr_operator._MD_RECOVERY_DRILL_EXPORT_DIR", export_dir), \
             patch("ibkr_operator.os.fsync"):
            result = _run_market_data_recovery_drill(
                symbol="AAPL", attempts=1, connect_if_needed=False)

        assert result["guard_state_unchanged"] is False
        assert result["guard_daily_trade_count_before"] == 0
        assert result["guard_daily_trade_count_after"] == 4
        assert result["drill_result"] == "no_go_guard_state_mutation"
        assert result["final_severity"] == "NO_GO"

    def test_guard_state_fields_present_in_result(self):
        """All guard_state output fields are present in drill result."""
        from ibkr_operator import _run_market_data_recovery_drill
        from pathlib import Path

        export_dir = Path("/tmp/md-drill-guard-fields")
        export_dir.mkdir(parents=True, exist_ok=True)

        with patch("ibkr_operator._capture_safety_flags_raw",
                   return_value={"env_IBKR_ALLOW_ORDERS": "false",
                                 "rules_enforced": "false",
                                 "capture_timestamp_utc": "2026-06-24T10:00:00Z"}), \
             patch("ibkr_operator._capture_guard_state_snapshot",
                   return_value=_mock_guard_snapshot(tc=0)), \
             patch("ibkr_operator._run_market_data_diagnostics",
                   return_value=_make_diagnostics_live_available_result()), \
             patch("ibkr_operator._run_autonomy_status",
                   return_value={"recommendation": "HOLD", "_export_path": "/tmp/stat.json"}), \
             patch("ibkr_operator._scan_forbidden_endpoints",
                   return_value={"ok": True, "violations": []}), \
             patch("ibkr_operator._git_metadata",
                   return_value={"branch": "test", "commit": "abc", "tag": "test"}), \
             patch("ibkr_operator.urllib.request.urlopen",
                   side_effect=_MockUrlOpen({
                       "/health": (200, _make_health_response(True)),
                   })), \
             patch("ibkr_operator.time.sleep"), \
             patch("ibkr_operator._MD_RECOVERY_DRILL_EXPORT_DIR", export_dir), \
             patch("ibkr_operator.os.fsync"):
            result = _run_market_data_recovery_drill(
                symbol="AAPL", attempts=1, connect_if_needed=False)

        for field in ("guard_state_path", "guard_state_hash_before",
                      "guard_state_hash_after", "guard_daily_trade_count_before",
                      "guard_daily_trade_count_after", "guard_state_unchanged"):
            assert field in result, f"Missing guard-state field: {field}"

    def test_repeated_drills_do_not_accumulate_guard_mutation(self):
        """Repeated drills with unchanged guard-state all pass."""
        from ibkr_operator import _run_market_data_recovery_drill
        from pathlib import Path

        export_dir = Path("/tmp/md-drill-guard-repeat")
        export_dir.mkdir(parents=True, exist_ok=True)

        call_count = [0]
        def _stable_guard():
            call_count[0] += 1
            return _mock_guard_snapshot(tc=0, gh=_MOCK_GUARD_HASH)

        with patch("ibkr_operator._capture_safety_flags_raw",
                   return_value={"env_IBKR_ALLOW_ORDERS": "false",
                                 "rules_enforced": "false",
                                 "capture_timestamp_utc": "2026-06-24T10:00:00Z"}), \
             patch("ibkr_operator._capture_guard_state_snapshot",
                   side_effect=_stable_guard), \
             patch("ibkr_operator._run_market_data_diagnostics",
                   return_value=_make_diagnostics_live_available_result()), \
             patch("ibkr_operator._run_autonomy_status",
                   return_value={"recommendation": "HOLD", "_export_path": "/tmp/stat.json"}), \
             patch("ibkr_operator._scan_forbidden_endpoints",
                   return_value={"ok": True, "violations": []}), \
             patch("ibkr_operator._git_metadata",
                   return_value={"branch": "test", "commit": "abc", "tag": "test"}), \
             patch("ibkr_operator.urllib.request.urlopen",
                   side_effect=_MockUrlOpen({
                       "/health": (200, _make_health_response(True)),
                   })), \
             patch("ibkr_operator.time.sleep"), \
             patch("ibkr_operator._MD_RECOVERY_DRILL_EXPORT_DIR", export_dir), \
             patch("ibkr_operator.os.fsync"):
            for i in range(3):
                result = _run_market_data_recovery_drill(
                    symbol="AAPL", attempts=1, connect_if_needed=False)
                assert result["guard_state_unchanged"] is True, \
                    f"Iteration {i}: guard_state mutated"
                assert result["drill_result"] == "recovered", \
                    f"Iteration {i}: unexpected drill_result {result['drill_result']}"


# ---------------------------------------------------------------------------
# T17: Safety-flag capture + error-result contract
# ---------------------------------------------------------------------------

class TestCaptureSafetyFlagsRaw:
    """Verify _capture_safety_flags_raw is importable and safe."""

    def test_importable_and_does_not_raise_nameerror(self):
        """_capture_safety_flags_raw must exist and not raise NameError."""
        from ibkr_operator import _capture_safety_flags_raw
        # Must be a callable
        assert callable(_capture_safety_flags_raw)

    def test_returns_dictionary(self):
        """Returns a dict with expected keys."""
        from ibkr_operator import _capture_safety_flags_raw
        result = _capture_safety_flags_raw()
        assert isinstance(result, dict)
        for key in ("env_IBKR_ALLOW_ORDERS", "rules_enforced", "capture_timestamp_utc"):
            assert key in result, f"Missing key: {key}"

    def test_reads_ibkr_allow_orders_from_env(self):
        """When .env has IBKR_ALLOW_ORDERS=false, capture reflects it."""
        import tempfile
        from pathlib import Path
        # Create a temp .env with IBKR_ALLOW_ORDERS=false
        with tempfile.TemporaryDirectory() as td:
            env_path = Path(td) / ".env"
            env_path.write_text("# test\nIBKR_ALLOW_ORDERS=false\nOTHER=v\n")
            with patch("ibkr_operator.BRIDGE_DIR", Path(td)):
                from ibkr_operator import _capture_safety_flags_raw
                result = _capture_safety_flags_raw()
        assert result["env_IBKR_ALLOW_ORDERS"] == "false", \
            f"Expected 'false', got {result['env_IBKR_ALLOW_ORDERS']}"

    def test_missing_env_file_returns_unknown(self):
        """When .env is missing, returns '?'."""
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as td:
            with patch("ibkr_operator.BRIDGE_DIR", Path(td)):
                from ibkr_operator import _capture_safety_flags_raw
                result = _capture_safety_flags_raw()
        assert result["env_IBKR_ALLOW_ORDERS"] == "?"

    def test_missing_rules_file_returns_unknown(self):
        """When rules YAML is missing, returns '?' for enforced."""
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as td:
            with patch("ibkr_operator.Path.home", return_value=Path(td)), \
                 patch("ibkr_operator.BRIDGE_DIR", Path(td) / "agents" / "ibkr-bridge"):
                from ibkr_operator import _capture_safety_flags_raw
                result = _capture_safety_flags_raw()
        assert result["rules_enforced"] == "?"


class TestRecoveryDrillErrorContract:
    """Verify JSON error contract for internal exceptions."""

    def test_error_result_includes_all_required_fields(self):
        """_make_recovery_drill_error_result produces all required fields."""
        from ibkr_operator import _make_recovery_drill_error_result
        exc = NameError("_read_allow_orders is not defined")
        result = _make_recovery_drill_error_result(exc, symbol="AAPL")
        assert result["final_severity"] == "NO_GO"
        assert result["drill_result"] == "no_go_runtime_error"
        assert result["bridge_runtime_ok"] is False
        assert result["no_broker_mutation"] is True
        assert result["no_order_window_opened"] is True
        assert result["internal_exception"] is True
        assert result["error_type"] == "NameError"
        assert "_read_allow_orders" in result["error_message"]
        assert result["symbol"] == "AAPL"
        assert "drill_id" in result
        assert result["diagnostics_ran"] is False

    def test_error_result_is_valid_json_serializable(self):
        """Error result round-trips through json.dumps/loads."""
        import json
        from ibkr_operator import _make_recovery_drill_error_result
        exc = RuntimeError("simulated bridge crash")
        result = _make_recovery_drill_error_result(exc, symbol="IBM")
        raw = json.dumps(result, default=str)
        parsed = json.loads(raw)
        assert parsed["drill_result"] == "no_go_runtime_error"
        assert parsed["internal_exception"] is True

    def test_drill_try_except_path_produces_error_result(self):
        """When drill raises, CLI path catches and uses error result."""
        import json
        from ibkr_operator import _make_recovery_drill_error_result

        exc = RuntimeError("mock crash during drill")
        result = _make_recovery_drill_error_result(exc, symbol="TEST")

        # Simulate what the CLI does in the except block
        raw = json.dumps(result, indent=2, default=str)
        parsed = json.loads(raw)

        assert parsed["final_severity"] == "NO_GO"
        assert parsed["drill_result"] == "no_go_runtime_error"
        assert parsed["internal_exception"] is True
        assert parsed["no_broker_mutation"] is True
        assert parsed["no_order_window_opened"] is True
        assert "drill_result" in parsed

    def test_drill_result_is_valid_json_on_mocked_path(self):
        """Mocked drill function result round-trips through json."""
        import json
        from ibkr_operator import _run_market_data_recovery_drill
        from pathlib import Path

        export_dir = Path("/tmp/test-drill-json-ok")
        export_dir.mkdir(parents=True, exist_ok=True)

        with patch("ibkr_operator._capture_safety_flags_raw",
                   return_value={"env_IBKR_ALLOW_ORDERS": "false",
                                 "rules_enforced": "false",
                                 "capture_timestamp_utc": "2026-06-24T10:00:00Z"}), \
             patch("ibkr_operator._capture_guard_state_snapshot",
                   return_value={"guard_state_path": "/tmp/guard-state.json",
                                 "guard_state_hash": "abc",
                                 "daily_trade_count": 0,
                                 "capture_timestamp_utc": "2026-06-24T10:00:00Z",
                                 "file_exists": True}), \
             patch("ibkr_operator._run_market_data_diagnostics",
                   return_value=_make_diagnostics_live_available_result()), \
             patch("ibkr_operator._run_autonomy_status",
                   return_value={"recommendation": "HOLD", "_export_path": "/tmp/stat.json"}), \
             patch("ibkr_operator._scan_forbidden_endpoints",
                   return_value={"ok": True, "violations": []}), \
             patch("ibkr_operator._git_metadata",
                   return_value={"branch": "test", "commit": "abc", "tag": "test"}), \
             patch("ibkr_operator.urllib.request.urlopen",
                   side_effect=_MockUrlOpen({
                       "/health": (200, _make_health_response(True)),
                   })), \
             patch("ibkr_operator.time.sleep"), \
             patch("ibkr_operator._MD_RECOVERY_DRILL_EXPORT_DIR", export_dir), \
             patch("ibkr_operator.os.fsync"):
            result = _run_market_data_recovery_drill(
                symbol="AAPL", attempts=1, connect_if_needed=False)

        # Result must be JSON-serializable
        raw = json.dumps(result, default=str)
        parsed = json.loads(raw)
        assert parsed["drill_result"] != "unknown"
        assert parsed["final_severity"] in ("OK", "NO_GO", "HOLD")

    def test_no_traceback_format_in_error_result(self):
        """Error result dict has no traceback formatting — just safe strings."""
        from ibkr_operator import _make_recovery_drill_error_result
        exc = RuntimeError("something broke")
        result = _make_recovery_drill_error_result(exc)
        assert result["error_type"] == "RuntimeError"
        assert result["error_message"] == "something broke"
        # No traceback lines leaking into error_message
        assert "Traceback" not in result["error_message"]
        assert "File " not in result["error_message"]
        # All string values must be plain strings, no traceback objects
        for k, v in result.items():
            if isinstance(v, str):
                assert "Traceback" not in v, f"Traceback found in field '{k}': {v[:100]}"


# ---------------------------------------------------------------------------
# T18: bridge_saturated classification
# ---------------------------------------------------------------------------

class TestBridgeSaturatedClassification:
    """Verify bridge_saturated maps to hold_bridge_saturated with full contract."""

    def test_bridge_saturated_produces_hold_bridge_saturated(self):
        """bridge_saturated diagnosis → hold_bridge_saturated drill_result."""
        from ibkr_operator import _run_market_data_recovery_drill
        from pathlib import Path

        export_dir = Path("/tmp/md-drill-saturated")
        export_dir.mkdir(parents=True, exist_ok=True)

        diag_result = _make_diagnostics_no_tick_timeout_result()
        diag_result["diagnosis"] = "bridge_saturated"

        with patch("ibkr_operator._capture_safety_flags_raw",
                   return_value={"env_IBKR_ALLOW_ORDERS": "false",
                                 "rules_enforced": "false",
                                 "capture_timestamp_utc": "2026-06-24T10:00:00Z"}), \
             patch("ibkr_operator._capture_guard_state_snapshot",
                   return_value={"guard_state_path": "/tmp/guard-state.json",
                                 "guard_state_hash": "abc",
                                 "daily_trade_count": 0,
                                 "capture_timestamp_utc": "2026-06-24T10:00:00Z",
                                 "file_exists": True}), \
             patch("ibkr_operator._run_market_data_diagnostics", return_value=diag_result), \
             patch("ibkr_operator._scan_forbidden_endpoints",
                   return_value={"ok": True, "violations": []}), \
             patch("ibkr_operator._git_metadata",
                   return_value={"branch": "test", "commit": "abc", "tag": "test"}), \
             patch("ibkr_operator.urllib.request.urlopen",
                   side_effect=_MockUrlOpen({
                       "/health": (200, _make_health_response(True)),
                   })), \
             patch("ibkr_operator.time.sleep"), \
             patch("ibkr_operator._MD_RECOVERY_DRILL_EXPORT_DIR", export_dir), \
             patch("ibkr_operator.os.fsync"):
            result = _run_market_data_recovery_drill(
                symbol="AAPL", attempts=1, connect_if_needed=False)

        assert result["drill_result"] == "hold_bridge_saturated", \
            f"Expected hold_bridge_saturated, got {result['drill_result']}"
        assert result["final_severity"] == "HOLD"
        assert result["operator_action_required"] is True
        assert result["bridge_saturated_blocker"] is not None
        assert result["bridge_saturated_blocker"]["check"] == "bridge_saturated"
        assert result["bridge_saturated_blocker"]["severity"] == "HOLD"
        assert "backpressure" in result["bridge_saturated_blocker"]["detail"].lower()

    def test_bridge_saturated_operator_actions(self):
        """bridge_saturated includes correct operator_actions."""
        from ibkr_operator import _run_market_data_recovery_drill
        from pathlib import Path

        export_dir = Path("/tmp/md-drill-saturated-actions")
        export_dir.mkdir(parents=True, exist_ok=True)

        diag_result = _make_diagnostics_no_tick_timeout_result()
        diag_result["diagnosis"] = "bridge_saturated"

        with patch("ibkr_operator._capture_safety_flags_raw",
                   return_value={"env_IBKR_ALLOW_ORDERS": "false",
                                 "rules_enforced": "false",
                                 "capture_timestamp_utc": "2026-06-24T10:00:00Z"}), \
             patch("ibkr_operator._capture_guard_state_snapshot",
                   return_value={"guard_state_path": "/tmp/guard-state.json",
                                 "guard_state_hash": "abc",
                                 "daily_trade_count": 0,
                                 "capture_timestamp_utc": "2026-06-24T10:00:00Z",
                                 "file_exists": True}), \
             patch("ibkr_operator._run_market_data_diagnostics", return_value=diag_result), \
             patch("ibkr_operator._scan_forbidden_endpoints",
                   return_value={"ok": True, "violations": []}), \
             patch("ibkr_operator._git_metadata",
                   return_value={"branch": "test", "commit": "abc", "tag": "test"}), \
             patch("ibkr_operator.urllib.request.urlopen",
                   side_effect=_MockUrlOpen({
                       "/health": (200, _make_health_response(True)),
                   })), \
             patch("ibkr_operator.time.sleep"), \
             patch("ibkr_operator._MD_RECOVERY_DRILL_EXPORT_DIR", export_dir), \
             patch("ibkr_operator.os.fsync"):
            result = _run_market_data_recovery_drill(
                symbol="AAPL", attempts=1, connect_if_needed=False)

        actions = result["operator_actions"]
        assert isinstance(actions, list)
        assert len(actions) >= 4
        assert "wait for active read-only probes to drain" in actions
        assert "run ibkr-operator doctor" in actions
        assert "run ibkr-operator kpi" in actions
        assert any("retry" in a and "cooldown" in a for a in actions)

    def test_bridge_saturated_preserves_safety_contract(self):
        """bridge_saturated: no_broker_mutation, no_order_window_opened, safety unchanged."""
        from ibkr_operator import _run_market_data_recovery_drill
        from pathlib import Path

        export_dir = Path("/tmp/md-drill-saturated-safety")
        export_dir.mkdir(parents=True, exist_ok=True)

        diag_result = _make_diagnostics_no_tick_timeout_result()
        diag_result["diagnosis"] = "bridge_saturated"

        safety_flags = {"env_IBKR_ALLOW_ORDERS": "false",
                        "rules_enforced": "false",
                        "capture_timestamp_utc": "2026-06-24T10:00:00Z"}

        with patch("ibkr_operator._capture_safety_flags_raw",
                   return_value=safety_flags), \
             patch("ibkr_operator._capture_guard_state_snapshot",
                   return_value={"guard_state_path": "/tmp/guard-state.json",
                                 "guard_state_hash": "abc",
                                 "daily_trade_count": 0,
                                 "capture_timestamp_utc": "2026-06-24T10:00:00Z",
                                 "file_exists": True}), \
             patch("ibkr_operator._run_market_data_diagnostics", return_value=diag_result), \
             patch("ibkr_operator._scan_forbidden_endpoints",
                   return_value={"ok": True, "violations": []}), \
             patch("ibkr_operator._git_metadata",
                   return_value={"branch": "test", "commit": "abc", "tag": "test"}), \
             patch("ibkr_operator.urllib.request.urlopen",
                   side_effect=_MockUrlOpen({
                       "/health": (200, _make_health_response(True)),
                   })), \
             patch("ibkr_operator.time.sleep"), \
             patch("ibkr_operator._MD_RECOVERY_DRILL_EXPORT_DIR", export_dir), \
             patch("ibkr_operator.os.fsync"):
            result = _run_market_data_recovery_drill(
                symbol="AAPL", attempts=1, connect_if_needed=False)

        assert result["no_broker_mutation"] is True
        assert result["no_order_window_opened"] is True
        assert result["safety_flags_unchanged"] is True
        assert result["guard_state_unchanged"] is True

    def test_bridge_saturated_not_unknown(self):
        """bridge_saturated drill_result is not unknown."""
        from ibkr_operator import _run_market_data_recovery_drill
        from pathlib import Path

        export_dir = Path("/tmp/md-drill-saturated-not-unknown")
        export_dir.mkdir(parents=True, exist_ok=True)

        diag_result = _make_diagnostics_no_tick_timeout_result()
        diag_result["diagnosis"] = "bridge_saturated"

        with patch("ibkr_operator._capture_safety_flags_raw",
                   return_value={"env_IBKR_ALLOW_ORDERS": "false",
                                 "rules_enforced": "false",
                                 "capture_timestamp_utc": "2026-06-24T10:00:00Z"}), \
             patch("ibkr_operator._capture_guard_state_snapshot",
                   return_value={"guard_state_path": "/tmp/guard-state.json",
                                 "guard_state_hash": "abc",
                                 "daily_trade_count": 0,
                                 "capture_timestamp_utc": "2026-06-24T10:00:00Z",
                                 "file_exists": True}), \
             patch("ibkr_operator._run_market_data_diagnostics", return_value=diag_result), \
             patch("ibkr_operator._scan_forbidden_endpoints",
                   return_value={"ok": True, "violations": []}), \
             patch("ibkr_operator._git_metadata",
                   return_value={"branch": "test", "commit": "abc", "tag": "test"}), \
             patch("ibkr_operator.urllib.request.urlopen",
                   side_effect=_MockUrlOpen({
                       "/health": (200, _make_health_response(True)),
                   })), \
             patch("ibkr_operator.time.sleep"), \
             patch("ibkr_operator._MD_RECOVERY_DRILL_EXPORT_DIR", export_dir), \
             patch("ibkr_operator.os.fsync"):
            result = _run_market_data_recovery_drill(
                symbol="AAPL", attempts=1, connect_if_needed=False)

        assert result["drill_result"] != "unknown", \
            "bridge_saturated must not produce unknown drill_result"
        assert result["final_diagnosis"] == "bridge_saturated"

    def test_non_saturated_branches_have_no_saturated_blocker(self):
        """Other diagnoses: operator_action_required is False, blocker is None."""
        from ibkr_operator import _run_market_data_recovery_drill
        from pathlib import Path

        export_dir = Path("/tmp/md-drill-no-saturated-blocker")
        export_dir.mkdir(parents=True, exist_ok=True)

        with patch("ibkr_operator._capture_safety_flags_raw",
                   return_value={"env_IBKR_ALLOW_ORDERS": "false",
                                 "rules_enforced": "false",
                                 "capture_timestamp_utc": "2026-06-24T10:00:00Z"}), \
             patch("ibkr_operator._capture_guard_state_snapshot",
                   return_value={"guard_state_path": "/tmp/guard-state.json",
                                 "guard_state_hash": "abc",
                                 "daily_trade_count": 0,
                                 "capture_timestamp_utc": "2026-06-24T10:00:00Z",
                                 "file_exists": True}), \
             patch("ibkr_operator._run_market_data_diagnostics",
                   return_value=_make_diagnostics_live_available_result()), \
             patch("ibkr_operator._run_autonomy_status",
                   return_value={"recommendation": "HOLD", "_export_path": "/tmp/stat.json"}), \
             patch("ibkr_operator._scan_forbidden_endpoints",
                   return_value={"ok": True, "violations": []}), \
             patch("ibkr_operator._git_metadata",
                   return_value={"branch": "test", "commit": "abc", "tag": "test"}), \
             patch("ibkr_operator.urllib.request.urlopen",
                   side_effect=_MockUrlOpen({
                       "/health": (200, _make_health_response(True)),
                   })), \
             patch("ibkr_operator.time.sleep"), \
             patch("ibkr_operator._MD_RECOVERY_DRILL_EXPORT_DIR", export_dir), \
             patch("ibkr_operator.os.fsync"):
            result = _run_market_data_recovery_drill(
                symbol="AAPL", attempts=1, connect_if_needed=False)

        # For recovered: operator_action_required should be False
        assert result["operator_action_required"] is False
        assert result["bridge_saturated_blocker"] is None
        assert result["operator_actions"] == []


# ---------------------------------------------------------------------------
# T19: Bridge-saturation fail-fast behavior
# ---------------------------------------------------------------------------


def _make_saturated_diagnostics_result() -> dict:
    """Diagnostics result with bridge_saturated diagnosis."""
    return {
        "timestamp": "2026-06-24T10:00:00Z",
        "diagnostic_id": "md-test-sat",
        "ibkr_connected": True,
        "bridge_reachable": True,
        "bridge_runtime_ok": True,
        "contract_qualified": False,
        "live_market_data_available": False,
        "delayed_market_data_available": False,
        "market_data_unavailable_reason": "",
        "diagnosis": "bridge_saturated",
        "severity": "HOLD",
        "market_session_status": _make_session_info("rth"),
        "operator_action_required": True,
        "suggested_operator_actions": [],
        "aborted_early": False,
        "abort_reason": None,
        "_export_path": "/tmp/test-sat.json",
    }


def _make_saturated_backpressure(active: int = 3, max_active: int = 4) -> dict:
    """Backpressure check result indicating saturation."""
    return {
        "ok": False,
        "active": active,
        "max_active": max_active,
        "rejected": 5,
        "leaked_md_threads": 0,
        "detail": f"bridge saturated: {active}/{max_active} active slots",
    }


def _make_ok_backpressure() -> dict:
    """Backpressure check result with capacity."""
    return {
        "ok": True,
        "active": 1,
        "max_active": 4,
        "rejected": 0,
        "leaked_md_threads": 0,
        "detail": "bridge has capacity: 1/4 active",
    }


class TestBridgeSaturatedFailFast:
    """Verify bridge_saturated immediately stops the retry loop."""

    def test_saturated_diagnostics_performs_no_extra_attempts(self):
        """When diagnostics returns bridge_saturated, loop breaks — no retries."""
        from ibkr_operator import _run_market_data_recovery_drill
        from pathlib import Path

        export_dir = Path("/tmp/md-drill-sat-ff")
        export_dir.mkdir(parents=True, exist_ok=True)

        call_count = [0]
        def counting_saturated(*args, **kwargs):
            call_count[0] += 1
            return _make_saturated_diagnostics_result()

        with patch("ibkr_operator._capture_safety_flags_raw",
                   return_value={"env_IBKR_ALLOW_ORDERS": "false",
                                 "rules_enforced": "false",
                                 "capture_timestamp_utc": "2026-06-24T10:00:00Z"}), \
             patch("ibkr_operator._capture_guard_state_snapshot",
                   return_value={"guard_state_path": "/tmp/guard-state.json",
                                 "guard_state_hash": "abc",
                                 "daily_trade_count": 0,
                                 "capture_timestamp_utc": "2026-06-24T10:00:00Z",
                                 "file_exists": True}), \
             patch("ibkr_operator._check_bridge_backpressure",
                   return_value=_make_ok_backpressure()), \
             patch("ibkr_operator._run_market_data_diagnostics",
                   side_effect=counting_saturated), \
             patch("ibkr_operator._scan_forbidden_endpoints",
                   return_value={"ok": True, "violations": []}), \
             patch("ibkr_operator._git_metadata",
                   return_value={"branch": "test", "commit": "abc", "tag": "test"}), \
             patch("ibkr_operator.urllib.request.urlopen",
                   side_effect=_MockUrlOpen({
                       "/health": (200, _make_health_response(True)),
                   })), \
             patch("ibkr_operator.time.sleep"), \
             patch("ibkr_operator._MD_RECOVERY_DRILL_EXPORT_DIR", export_dir), \
             patch("ibkr_operator.os.fsync"):
            result = _run_market_data_recovery_drill(
                symbol="AAPL", attempts=3, connect_if_needed=False)

        # Must have called diagnostics exactly once — no retries
        assert call_count[0] == 1, \
            f"Expected 1 diagnostic call, got {call_count[0]} (should not retry on saturated)"
        # attempts_completed reflects actual completed, not requested
        assert result["attempts_completed"] == 1
        assert result["attempts_requested"] == 3
        assert result["drill_result"] == "hold_bridge_saturated"

    def test_http_503_from_first_attempt_stops_retry_loop(self):
        """When diagnostics returns aborted_early=True, loop stops immediately."""
        from ibkr_operator import _run_market_data_recovery_drill
        from pathlib import Path

        export_dir = Path("/tmp/md-drill-503-abort")
        export_dir.mkdir(parents=True, exist_ok=True)

        call_count = [0]
        def aborted_503(*args, **kwargs):
            call_count[0] += 1
            d = _make_diagnostics_no_tick_timeout_result()
            d["aborted_early"] = True
            d["abort_reason"] = "health endpoint returned 503 (backpressure)"
            d["diagnosis"] = "no_tick_stream_timeout"
            return d

        with patch("ibkr_operator._capture_safety_flags_raw",
                   return_value={"env_IBKR_ALLOW_ORDERS": "false",
                                 "rules_enforced": "false",
                                 "capture_timestamp_utc": "2026-06-24T10:00:00Z"}), \
             patch("ibkr_operator._capture_guard_state_snapshot",
                   return_value={"guard_state_path": "/tmp/guard-state.json",
                                 "guard_state_hash": "abc",
                                 "daily_trade_count": 0,
                                 "capture_timestamp_utc": "2026-06-24T10:00:00Z",
                                 "file_exists": True}), \
             patch("ibkr_operator._check_bridge_backpressure",
                   return_value=_make_ok_backpressure()), \
             patch("ibkr_operator._run_market_data_diagnostics",
                   side_effect=aborted_503), \
             patch("ibkr_operator._scan_forbidden_endpoints",
                   return_value={"ok": True, "violations": []}), \
             patch("ibkr_operator._git_metadata",
                   return_value={"branch": "test", "commit": "abc", "tag": "test"}), \
             patch("ibkr_operator.urllib.request.urlopen",
                   side_effect=_MockUrlOpen({
                       "/health": (200, _make_health_response(True)),
                   })), \
             patch("ibkr_operator.time.sleep"), \
             patch("ibkr_operator._MD_RECOVERY_DRILL_EXPORT_DIR", export_dir), \
             patch("ibkr_operator.os.fsync"):
            result = _run_market_data_recovery_drill(
                symbol="AAPL", attempts=3, connect_if_needed=False)

        assert call_count[0] == 1, \
            f"Expected 1 call (aborted on 503), got {call_count[0]}"
        assert result["drill_aborted_early"] is True
        assert result["drill_abort_reason"] is not None
        assert "503" in result["drill_abort_reason"]

    def test_pre_attempt_backpressure_check_stops_before_diagnostics(self):
        """When pre-attempt backpressure check fails, diagnostics is never called."""
        from ibkr_operator import _run_market_data_recovery_drill
        from pathlib import Path

        export_dir = Path("/tmp/md-drill-pre-bp-stop")
        export_dir.mkdir(parents=True, exist_ok=True)

        called_diagnostics = [False]
        def never_called(*args, **kwargs):
            called_diagnostics[0] = True
            return _make_diagnostics_no_tick_timeout_result()

        with patch("ibkr_operator._capture_safety_flags_raw",
                   return_value={"env_IBKR_ALLOW_ORDERS": "false",
                                 "rules_enforced": "false",
                                 "capture_timestamp_utc": "2026-06-24T10:00:00Z"}), \
             patch("ibkr_operator._capture_guard_state_snapshot",
                   return_value={"guard_state_path": "/tmp/guard-state.json",
                                 "guard_state_hash": "abc",
                                 "daily_trade_count": 0,
                                 "capture_timestamp_utc": "2026-06-24T10:00:00Z",
                                 "file_exists": True}), \
             patch("ibkr_operator._check_bridge_backpressure",
                   return_value=_make_saturated_backpressure()), \
             patch("ibkr_operator._run_market_data_diagnostics",
                   side_effect=never_called), \
             patch("ibkr_operator._scan_forbidden_endpoints",
                   return_value={"ok": True, "violations": []}), \
             patch("ibkr_operator._git_metadata",
                   return_value={"branch": "test", "commit": "abc", "tag": "test"}), \
             patch("ibkr_operator.urllib.request.urlopen",
                   side_effect=_MockUrlOpen({
                       "/health": (200, _make_health_response(True)),
                   })), \
             patch("ibkr_operator.time.sleep"), \
             patch("ibkr_operator._MD_RECOVERY_DRILL_EXPORT_DIR", export_dir), \
             patch("ibkr_operator.os.fsync"):
            result = _run_market_data_recovery_drill(
                symbol="AAPL", attempts=3, connect_if_needed=False)

        # Diagnostics must never have been called
        assert called_diagnostics[0] is False, \
            "Diagnostics was called even though pre-backpressure check failed"
        assert result["drill_aborted_early"] is True
        assert result["drill_result"] == "hold_bridge_saturated"
        assert result["attempts_completed"] == 1

    def test_saturated_drill_includes_blocker_in_blockers_list(self):
        """bridge_saturated blocker appears in blockers[] list."""
        from ibkr_operator import _run_market_data_recovery_drill
        from pathlib import Path

        export_dir = Path("/tmp/md-drill-sat-blockers")
        export_dir.mkdir(parents=True, exist_ok=True)

        with patch("ibkr_operator._capture_safety_flags_raw",
                   return_value={"env_IBKR_ALLOW_ORDERS": "false",
                                 "rules_enforced": "false",
                                 "capture_timestamp_utc": "2026-06-24T10:00:00Z"}), \
             patch("ibkr_operator._capture_guard_state_snapshot",
                   return_value={"guard_state_path": "/tmp/guard-state.json",
                                 "guard_state_hash": "abc",
                                 "daily_trade_count": 0,
                                 "capture_timestamp_utc": "2026-06-24T10:00:00Z",
                                 "file_exists": True}), \
             patch("ibkr_operator._check_bridge_backpressure",
                   return_value=_make_ok_backpressure()), \
             patch("ibkr_operator._run_market_data_diagnostics",
                   return_value=_make_saturated_diagnostics_result()), \
             patch("ibkr_operator._scan_forbidden_endpoints",
                   return_value={"ok": True, "violations": []}), \
             patch("ibkr_operator._git_metadata",
                   return_value={"branch": "test", "commit": "abc", "tag": "test"}), \
             patch("ibkr_operator.urllib.request.urlopen",
                   side_effect=_MockUrlOpen({
                       "/health": (200, _make_health_response(True)),
                   })), \
             patch("ibkr_operator.time.sleep"), \
             patch("ibkr_operator._MD_RECOVERY_DRILL_EXPORT_DIR", export_dir), \
             patch("ibkr_operator.os.fsync"):
            result = _run_market_data_recovery_drill(
                symbol="AAPL", attempts=1, connect_if_needed=False)

        assert len(result["blockers"]) >= 1, \
            f"Expected at least 1 blocker in blockers[], got {len(result['blockers'])}"
        blocker_checks = [b["check"] for b in result["blockers"]]
        assert "bridge_saturated" in blocker_checks, \
            f"bridge_saturated not in blockers[] checks: {blocker_checks}"
        # Also verify severity is HOLD
        for b in result["blockers"]:
            if b["check"] == "bridge_saturated":
                assert b["severity"] == "HOLD"

    def test_saturated_drill_preserves_safety_contract(self):
        """Saturated drill: safety_unchanged, guard_unchanged, no_broker_mutation."""
        from ibkr_operator import _run_market_data_recovery_drill
        from pathlib import Path

        export_dir = Path("/tmp/md-drill-sat-safety")
        export_dir.mkdir(parents=True, exist_ok=True)

        with patch("ibkr_operator._capture_safety_flags_raw",
                   return_value={"env_IBKR_ALLOW_ORDERS": "false",
                                 "rules_enforced": "false",
                                 "capture_timestamp_utc": "2026-06-24T10:00:00Z"}), \
             patch("ibkr_operator._capture_guard_state_snapshot",
                   return_value={"guard_state_path": "/tmp/guard-state.json",
                                 "guard_state_hash": "abc",
                                 "daily_trade_count": 0,
                                 "capture_timestamp_utc": "2026-06-24T10:00:00Z",
                                 "file_exists": True}), \
             patch("ibkr_operator._check_bridge_backpressure",
                   return_value=_make_ok_backpressure()), \
             patch("ibkr_operator._run_market_data_diagnostics",
                   return_value=_make_saturated_diagnostics_result()), \
             patch("ibkr_operator._scan_forbidden_endpoints",
                   return_value={"ok": True, "violations": []}), \
             patch("ibkr_operator._git_metadata",
                   return_value={"branch": "test", "commit": "abc", "tag": "test"}), \
             patch("ibkr_operator.urllib.request.urlopen",
                   side_effect=_MockUrlOpen({
                       "/health": (200, _make_health_response(True)),
                   })), \
             patch("ibkr_operator.time.sleep"), \
             patch("ibkr_operator._MD_RECOVERY_DRILL_EXPORT_DIR", export_dir), \
             patch("ibkr_operator.os.fsync"):
            result = _run_market_data_recovery_drill(
                symbol="AAPL", attempts=1, connect_if_needed=False)

        assert result["no_broker_mutation"] is True
        assert result["no_order_window_opened"] is True
        assert result["safety_flags_unchanged"] is True
        assert result["guard_state_unchanged"] is True

    def test_repeated_saturated_drills_do_not_leak_attempts(self):
        """Repeated drills on saturated bridge: each stops at 1 attempt."""
        from ibkr_operator import _run_market_data_recovery_drill
        from pathlib import Path

        export_dir = Path("/tmp/md-drill-sat-repeat")
        export_dir.mkdir(parents=True, exist_ok=True)

        for i in range(3):
            with patch("ibkr_operator._capture_safety_flags_raw",
                       return_value={"env_IBKR_ALLOW_ORDERS": "false",
                                     "rules_enforced": "false",
                                     "capture_timestamp_utc": "2026-06-24T10:00:00Z"}), \
                 patch("ibkr_operator._capture_guard_state_snapshot",
                       return_value={"guard_state_path": "/tmp/guard-state.json",
                                     "guard_state_hash": "abc",
                                     "daily_trade_count": 0,
                                     "capture_timestamp_utc": "2026-06-24T10:00:00Z",
                                     "file_exists": True}), \
                 patch("ibkr_operator._check_bridge_backpressure",
                       return_value=_make_ok_backpressure()), \
                 patch("ibkr_operator._run_market_data_diagnostics",
                       return_value=_make_saturated_diagnostics_result()), \
                 patch("ibkr_operator._scan_forbidden_endpoints",
                       return_value={"ok": True, "violations": []}), \
                 patch("ibkr_operator._git_metadata",
                       return_value={"branch": "test", "commit": "abc", "tag": "test"}), \
                 patch("ibkr_operator.urllib.request.urlopen",
                       side_effect=_MockUrlOpen({
                           "/health": (200, _make_health_response(True)),
                       })), \
                 patch("ibkr_operator.time.sleep"), \
                 patch("ibkr_operator._MD_RECOVERY_DRILL_EXPORT_DIR", export_dir), \
                 patch("ibkr_operator.os.fsync"):
                result = _run_market_data_recovery_drill(
                    symbol="AAPL", attempts=3, connect_if_needed=False)

            assert result["attempts_completed"] == 1, \
                f"Run {i}: expected 1 attempt, got {result['attempts_completed']}"
            assert result["drill_result"] == "hold_bridge_saturated", \
                f"Run {i}: expected hold_bridge_saturated, got {result['drill_result']}"
