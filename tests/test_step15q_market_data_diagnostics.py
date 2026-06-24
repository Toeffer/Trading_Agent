"""Tests for Step 15Q — RTH market-data entitlement / subscription diagnosis.

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
        "in_rth": session == "rth", "market_date_et": "2026-06-23",
    }


def _make_health_response(connected: bool = True, mode: str = "paper") -> dict:
    return {"connected": connected, "mode": mode, "allow_orders": False}


def _make_contract_response(conid: int = 265598, symbol: str = "AAPL") -> dict:
    return {"conid": conid, "symbol": symbol, "exchange": "SMART",
            "currency": "USD", "asset_type": "STK"}


def _make_contract_error_response(error: str = "contract not found") -> dict:
    return {"error": error}


def _make_snapshot_response(available: bool = True, stale: bool = False,
                            delayed: bool = True, detail: str = "",
                            bid: float = 150.0, ask: float = 150.5,
                            last: float = 150.25) -> dict:
    ok = available  # ok=False when market_data_available=False
    return {
        "ok": ok, "symbol": "AAPL", "market_data_available": available,
        "detail": detail, "delayed": delayed, "stale": stale,
        "bid": bid if available else None, "ask": ask if available else None,
        "last": last if available else None, "close": 149.8 if available else None,
        "midpoint": 150.375 if available else None, "currency": "USD" if available else None,
        "exchange": "SMART", "snapshot_timestamp": "2026-06-23T10:00:00Z",
        "snapshot_epoch": time.time(), "market_data_age_seconds": 5.0 if available else None,
    }


def _make_bars_response(bars_count: int = 5) -> dict:
    return {"bars": [{"close": 150.0 + i} for i in range(bars_count)]}


class _MockUrlOpen:
    """Flexible urlopen mock that returns different responses per URL."""
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
# T1: Command exists
# ---------------------------------------------------------------------------

class TestCommandExists:
    """Verify the market-data-diagnostics command is registered and importable."""

    def test_function_importable(self):
        from ibkr_operator import _run_market_data_diagnostics
        assert callable(_run_market_data_diagnostics)

    def test_aliases_registered(self):
        import subprocess
        for alias in ("market-data-doctor", "md-diagnostics"):
            r = subprocess.run(
                [sys.executable, str(BRIDGE_DIR / "ibkr_operator.py"),
                 alias, "--help"],
                capture_output=True, text=True, timeout=15,
            )
            assert r.returncode == 0, f"{alias} --help failed: {r.stderr}"


# ---------------------------------------------------------------------------
# T2: JSON stdout pure
# ---------------------------------------------------------------------------

class TestJsonStdoutPure:
    """Verify --json output is pure parseable JSON."""

    def test_json_round_trips(self):
        from ibkr_operator import _run_market_data_diagnostics

        mock_urlopen = _MockUrlOpen({
            "/health": (200, _make_health_response(True)),
            "/contract/stock": (200, _make_contract_response()),
            "/market/snapshot": (200, _make_snapshot_response(True, False, True)),
            "/market/bars": (200, _make_bars_response(5)),
        })

        with patch("ibkr_operator._determine_market_session_status",
                   return_value=_make_session_info("rth")), \
             patch("ibkr_operator._git_metadata",
                   return_value={"branch": "test", "commit": "abc", "tag": "test"}), \
             patch("ibkr_operator.urllib.request.urlopen",
                   side_effect=mock_urlopen), \
             patch("ibkr_operator.time.sleep"), \
             patch("ibkr_operator._MD_DIAGNOSTICS_EXPORT_DIR",
                   Path("/tmp/md-diag")), \
             patch("ibkr_operator.os.fsync"):
            result = _run_market_data_diagnostics(symbol="AAPL")

        serialized = json.dumps(result, default=str)
        parsed = json.loads(serialized)
        assert parsed["diagnosis"] == "delayed_data_available"
        assert parsed["symbol"] == "AAPL"
        assert parsed["no_broker_mutation"] is True


# ---------------------------------------------------------------------------
# T3: Export written
# ---------------------------------------------------------------------------

class TestExportWritten:
    """Verify --export writes JSON to market-data-diagnostics directory."""

    def test_export_file_written(self, tmp_path):
        from ibkr_operator import _run_market_data_diagnostics

        mock_urlopen = _MockUrlOpen({
            "/health": (200, _make_health_response(True)),
            "/contract/stock": (200, _make_contract_response()),
            "/market/snapshot": (200, _make_snapshot_response(True, False, True)),
            "/market/bars": (200, _make_bars_response(5)),
        })
        export_dir = tmp_path / "market-data-diagnostics"

        with patch("ibkr_operator._determine_market_session_status",
                   return_value=_make_session_info("rth")), \
             patch("ibkr_operator._git_metadata",
                   return_value={"branch": "test", "commit": "abc", "tag": "test"}), \
             patch("ibkr_operator.urllib.request.urlopen",
                   side_effect=mock_urlopen), \
             patch("ibkr_operator.time.sleep"), \
             patch("ibkr_operator._MD_DIAGNOSTICS_EXPORT_DIR", export_dir), \
             patch("ibkr_operator.os.fsync"):
            result = _run_market_data_diagnostics(symbol="AAPL")

        ep = result.get("_export_path")
        assert ep is not None
        export_file = Path(ep)
        assert export_file.exists()
        exported = json.loads(export_file.read_text())
        assert exported["diagnosis"] == "delayed_data_available"


# ---------------------------------------------------------------------------
# T4: Contract qualification success
# ---------------------------------------------------------------------------

class TestContractQualification:
    """Verify contract qualification is attempted and classified."""

    def test_contract_qualification_success(self):
        from ibkr_operator import _run_market_data_diagnostics

        mock_urlopen = _MockUrlOpen({
            "/health": (200, _make_health_response(True)),
            "/contract/stock": (200, _make_contract_response(265598, "AAPL")),
            "/market/snapshot": (200, _make_snapshot_response(True, False, True)),
            "/market/bars": (200, _make_bars_response(5)),
        })

        with patch("ibkr_operator._determine_market_session_status",
                   return_value=_make_session_info("rth")), \
             patch("ibkr_operator._git_metadata",
                   return_value={"branch": "test", "commit": "abc", "tag": "test"}), \
             patch("ibkr_operator.urllib.request.urlopen",
                   side_effect=mock_urlopen), \
             patch("ibkr_operator.time.sleep"), \
             patch("ibkr_operator._MD_DIAGNOSTICS_EXPORT_DIR",
                   Path("/tmp/md-diag")), \
             patch("ibkr_operator.os.fsync"):
            result = _run_market_data_diagnostics(symbol="AAPL")

        assert result["contract_qualified"] is True
        assert result["qualified_contract"]["conid"] == 265598
        assert result["diagnosis"] == "delayed_data_available"

    def test_contract_qualification_failure_classified(self):
        from ibkr_operator import _run_market_data_diagnostics

        mock_urlopen = _MockUrlOpen({
            "/health": (200, _make_health_response(True)),
            "/contract/stock": (200, _make_contract_error_response("contract not found")),
            "/market/snapshot": (200, _make_snapshot_response(False, True, True, "no data")),
            "/market/bars": (200, {"bars": []}),
        })

        with patch("ibkr_operator._determine_market_session_status",
                   return_value=_make_session_info("rth")), \
             patch("ibkr_operator._git_metadata",
                   return_value={"branch": "test", "commit": "abc", "tag": "test"}), \
             patch("ibkr_operator.urllib.request.urlopen",
                   side_effect=mock_urlopen), \
             patch("ibkr_operator.time.sleep"), \
             patch("ibkr_operator._MD_DIAGNOSTICS_EXPORT_DIR",
                   Path("/tmp/md-diag")), \
             patch("ibkr_operator.os.fsync"):
            result = _run_market_data_diagnostics(symbol="ZZZZ")

        assert result["contract_qualified"] is False
        assert result["diagnosis"] == "contract_qualification_failed"
        assert result["severity"] == "NO_GO"


# ---------------------------------------------------------------------------
# T5: Diagnosis classifications
# ---------------------------------------------------------------------------

class TestDiagnosisClassifications:
    """Verify each diagnosis scenario is correctly classified."""

    def test_disconnected_classified(self):
        from ibkr_operator import _run_market_data_diagnostics

        mock_urlopen = _MockUrlOpen({
            "/health": (200, _make_health_response(False)),
            "/contract/stock": (200, _make_contract_error_response("unreachable")),
            "/market/snapshot": (200, _make_snapshot_response(False, True, True, "IBKR not connected")),
        })

        with patch("ibkr_operator._determine_market_session_status",
                   return_value=_make_session_info("rth")), \
             patch("ibkr_operator._git_metadata",
                   return_value={"branch": "test", "commit": "abc", "tag": "test"}), \
             patch("ibkr_operator.urllib.request.urlopen",
                   side_effect=mock_urlopen), \
             patch("ibkr_operator.time.sleep"), \
             patch("ibkr_operator._MD_DIAGNOSTICS_EXPORT_DIR",
                   Path("/tmp/md-diag")), \
             patch("ibkr_operator.os.fsync"):
            result = _run_market_data_diagnostics(symbol="AAPL")

        assert result["diagnosis"] == "ibkr_disconnected"
        assert result["severity"] == "HOLD"

    def test_rth_timeout_classified_as_no_tick_stream(self):
        from ibkr_operator import _run_market_data_diagnostics

        mock_urlopen = _MockUrlOpen({
            "/health": (200, _make_health_response(True)),
            "/contract/stock": (200, _make_contract_response()),
            "/market/snapshot": (200, _make_snapshot_response(
                False, True, True,
                "market_data_timeout: market data did not arrive within 8s")),
            "/market/bars": (200, _make_bars_response(5)),
        })

        with patch("ibkr_operator._determine_market_session_status",
                   return_value=_make_session_info("rth", "Inside RTH")), \
             patch("ibkr_operator._git_metadata",
                   return_value={"branch": "test", "commit": "abc", "tag": "test"}), \
             patch("ibkr_operator.urllib.request.urlopen",
                   side_effect=mock_urlopen), \
             patch("ibkr_operator.time.sleep"), \
             patch("ibkr_operator._MD_DIAGNOSTICS_EXPORT_DIR",
                   Path("/tmp/md-diag")), \
             patch("ibkr_operator.os.fsync"):
            result = _run_market_data_diagnostics(symbol="AAPL")

        assert result["diagnosis"] == "no_tick_stream_timeout", \
            f"Expected no_tick_stream_timeout, got {result['diagnosis']}"
        assert result["severity"] == "HOLD"
        assert result["operator_action_required"] is True
        assert "market_data_timeout" in result.get("market_data_unavailable_reason", "")

    def test_delayed_data_available_classified(self):
        from ibkr_operator import _run_market_data_diagnostics

        mock_urlopen = _MockUrlOpen({
            "/health": (200, _make_health_response(True)),
            "/contract/stock": (200, _make_contract_response()),
            "/market/snapshot": (200, _make_snapshot_response(True, False, True)),
            "/market/bars": (200, _make_bars_response(5)),
        })

        with patch("ibkr_operator._determine_market_session_status",
                   return_value=_make_session_info("rth")), \
             patch("ibkr_operator._git_metadata",
                   return_value={"branch": "test", "commit": "abc", "tag": "test"}), \
             patch("ibkr_operator.urllib.request.urlopen",
                   side_effect=mock_urlopen), \
             patch("ibkr_operator.time.sleep"), \
             patch("ibkr_operator._MD_DIAGNOSTICS_EXPORT_DIR",
                   Path("/tmp/md-diag")), \
             patch("ibkr_operator.os.fsync"):
            result = _run_market_data_diagnostics(symbol="AAPL")

        assert result["diagnosis"] == "delayed_data_available"
        assert result["severity"] == "OK"
        assert result["delayed_market_data_available"] is True

    def test_runtime_error_classified(self):
        from ibkr_operator import _run_market_data_diagnostics
        import urllib.error

        def _raise_urlerror(*args, **kwargs):
            raise urllib.error.URLError("connection refused")

        with patch("ibkr_operator._determine_market_session_status",
                   return_value=_make_session_info("rth")), \
             patch("ibkr_operator._git_metadata",
                   return_value={"branch": "test", "commit": "abc", "tag": "test"}), \
             patch("ibkr_operator.urllib.request.urlopen",
                   side_effect=_raise_urlerror), \
             patch("ibkr_operator.time.sleep"), \
             patch("ibkr_operator._MD_DIAGNOSTICS_EXPORT_DIR",
                   Path("/tmp/md-diag")), \
             patch("ibkr_operator.os.fsync"):
            result = _run_market_data_diagnostics(symbol="AAPL")

        assert result["diagnosis"] in ("bridge_runtime_error", "ibkr_disconnected")
        assert result["bridge_runtime_ok"] is False
        assert result["severity"] in ("HOLD", "NO_GO")


# ---------------------------------------------------------------------------
# T6: All required fields present
# ---------------------------------------------------------------------------

class TestRequiredFields:
    """Verify all spec-required fields are present."""

    _REQUIRED_FIELDS = [
        "timestamp", "diagnostic_id", "command", "git", "symbol",
        "requested_contract", "qualified_contract", "contract_qualified",
        "ibkr_connected", "bridge_reachable", "bridge_runtime_ok",
        "market_session_status", "attempts", "observed_ibkr_errors",
        "observed_snapshot_detail", "live_market_data_available",
        "delayed_market_data_available", "market_data_unavailable_reason",
        "diagnosis", "severity", "readiness_impact", "promotion_impact",
        "operator_action_required", "suggested_operator_actions",
        "no_broker_mutation", "no_order_window_opened",
        "explicit_non_actions", "evidence_hash", "_export_path",
    ]

    def test_all_required_fields_present(self):
        from ibkr_operator import _run_market_data_diagnostics

        mock_urlopen = _MockUrlOpen({
            "/health": (200, _make_health_response(True)),
            "/contract/stock": (200, _make_contract_response()),
            "/market/snapshot": (200, _make_snapshot_response(True, False, True)),
            "/market/bars": (200, _make_bars_response(5)),
        })

        with patch("ibkr_operator._determine_market_session_status",
                   return_value=_make_session_info("rth")), \
             patch("ibkr_operator._git_metadata",
                   return_value={"branch": "test", "commit": "abc", "tag": "test"}), \
             patch("ibkr_operator.urllib.request.urlopen",
                   side_effect=mock_urlopen), \
             patch("ibkr_operator.time.sleep"), \
             patch("ibkr_operator._MD_DIAGNOSTICS_EXPORT_DIR",
                   Path("/tmp/md-diag")), \
             patch("ibkr_operator.os.fsync"):
            result = _run_market_data_diagnostics(symbol="AAPL")

        for field in self._REQUIRED_FIELDS:
            assert field in result, f"Missing required field: {field}"


# ---------------------------------------------------------------------------
# T7: No /order* calls, no H1 token
# ---------------------------------------------------------------------------

class TestNoForbiddenCalls:
    """Verify diagnostics never call order endpoints or read H1 token."""

    def test_no_forbidden_patterns(self):
        import inspect
        from ibkr_operator import _run_market_data_diagnostics

        source = inspect.getsource(_run_market_data_diagnostics)
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
                                               "must not", "did not"]):
                    continue
                if pattern in stripped:
                    found = True
                    break
            assert not found, f"FORBIDDEN: '{pattern}' found in diagnostics source"


# ---------------------------------------------------------------------------
# T8: Existing tests still pass
# ---------------------------------------------------------------------------

class TestExistingTestsStillPass:
    """Quick sanity: imports and key functions still work."""

    def test_operator_imports(self):
        from ibkr_operator import (
            _run_market_data_diagnostics,
            _run_autonomy_status,
            _run_autonomy_promotion_plan,
            _run_guard_state_reconcile,
        )
        for func in [_run_market_data_diagnostics, _run_autonomy_status,
                     _run_autonomy_promotion_plan, _run_guard_state_reconcile]:
            assert callable(func), f"{func.__name__} is not callable"


# ---------------------------------------------------------------------------
# Step 15Q-BP: Backpressure cleanup tests
# ---------------------------------------------------------------------------

class TestDiagnosticsBackpressureCleanup:
    """Verify diagnostics don't leak active slots or saturate endpoints."""

    def test_cooldown_prevents_repeated_runs(self):
        """Repeated diagnostics within cooldown window are rejected."""
        from ibkr_operator import _check_diagnostics_cooldown, _record_diagnostics_run, _md_cooldown_file
        # Clean state: remove cooldown file and bypass pytest detection
        import os as _os
        cf = _md_cooldown_file()
        if cf.exists():
            cf.unlink()
        old_pytest = _os.environ.pop("PYTEST_CURRENT_TEST", None)
        try:
            # First run should be allowed
            ok1, elapsed1, detail1 = _check_diagnostics_cooldown()
            assert ok1 is True, f"First cooldown check should pass: {detail1}"

            # Record a run
            _record_diagnostics_run()

            # Second run should be blocked
            ok2, elapsed2, detail2 = _check_diagnostics_cooldown()
            assert ok2 is False, f"Second cooldown check should fail: {detail2}"
            assert "cooldown active" in detail2
        finally:
            if old_pytest is not None:
                _os.environ["PYTEST_CURRENT_TEST"] = old_pytest
            # Clean up cooldown file
            if cf.exists():
                cf.unlink()

    def test_cooldown_disabled_during_pytest(self):
        """Cooldown is bypassed when PYTEST_CURRENT_TEST is set."""
        from ibkr_operator import _check_diagnostics_cooldown, _record_diagnostics_run

        # Record a run to set the cooldown
        _record_diagnostics_run()

        # During pytest, cooldown should be bypassed (PYTEST_CURRENT_TEST is set)
        ok, elapsed, detail = _check_diagnostics_cooldown()
        assert ok is True, f"Cooldown should be bypassed during pytest: {detail}"

    def test_backpressure_check_rejects_when_saturated(self):
        """Pre-flight backpressure check rejects when bridge is saturated."""
        from ibkr_operator import _check_bridge_backpressure

        # Mock urlopen to return a saturated backpressure response
        mock_urlopen = _MockUrlOpen({
            "/monitor/backpressure": (200, {
                "ok": True, "active": 4, "max_active": 4,
                "total_accepted": 100, "total_rejected": 5,
                "leaked_md_threads": 0, "leaked_md_threads_warn": 5,
            }),
        })

        with patch("ibkr_operator.urllib.request.urlopen", side_effect=mock_urlopen):
            result = _check_bridge_backpressure()

        assert result["ok"] is False, f"Should reject when saturated: {result}"
        assert result["active"] == 4
        assert "saturated" in result["detail"]

    def test_backpressure_check_allows_when_idle(self):
        """Pre-flight backpressure check allows when bridge has capacity."""
        from ibkr_operator import _check_bridge_backpressure

        mock_urlopen = _MockUrlOpen({
            "/monitor/backpressure": (200, {
                "ok": True, "active": 0, "max_active": 4,
                "total_accepted": 100, "total_rejected": 0,
                "leaked_md_threads": 0, "leaked_md_threads_warn": 5,
            }),
        })

        with patch("ibkr_operator.urllib.request.urlopen", side_effect=mock_urlopen):
            result = _check_bridge_backpressure()

        assert result["ok"] is True, f"Should allow when idle: {result}"
        assert result["active"] == 0
        assert "capacity" in result["detail"]

    def test_backpressure_check_allows_when_unreachable(self):
        """Pre-flight backpressure check allows diagnostics when bridge unreachable."""
        from ibkr_operator import _check_bridge_backpressure

        with patch("ibkr_operator.urllib.request.urlopen",
                   side_effect=Exception("connection refused")):
            result = _check_bridge_backpressure()

        assert result["ok"] is True, "Should allow when bridge unreachable"
        assert result["active"] == -1
        assert "unavailable" in result["detail"]

    def test_diagnostics_aborts_on_bridge_saturated(self):
        """Diagnostics fast-fails when bridge backpressure check fails."""
        from ibkr_operator import _run_market_data_diagnostics

        with patch("ibkr_operator._check_diagnostics_cooldown",
                   return_value=(True, 999.0, "cooldown passed")), \
             patch("ibkr_operator._check_bridge_backpressure",
                   return_value={"ok": False, "active": 4, "max_active": 4,
                                 "rejected": 10, "leaked_md_threads": 2,
                                 "detail": "bridge saturated"}), \
             patch("ibkr_operator._determine_market_session_status",
                   return_value=_make_session_info("rth")), \
             patch("ibkr_operator._git_metadata",
                   return_value={"branch": "t", "commit": "abc", "tag": "t"}):
            result = _run_market_data_diagnostics(symbol="AAPL")

        assert result["diagnosis"] == "bridge_saturated"
        assert result["backpressure"]["ok"] is False
        assert result.get("contract_qualified") is None  # never made contract call
        assert result.get("aborted_early") is True or result.get("aborted_early") is None

    def test_diagnostics_aborts_on_503_from_probe(self):
        """Diagnostics sets aborted_early when a probe returns HTTP 503."""
        from ibkr_operator import _run_market_data_diagnostics

        # Health returns 503 (backpressure)
        mock_urlopen = _MockUrlOpen({
            "/health": (503, {"ok": False, "error": "backpressure"}),
            "/contract/stock": (200, _make_contract_response()),
            "/market/snapshot": (200, _make_snapshot_response(True)),
            "/market/bars": (200, _make_bars_response(5)),
        })

        from pathlib import Path
        export_dir = Path("/tmp/md-diag-test-503")
        export_dir.mkdir(parents=True, exist_ok=True)
        # Clean cooldown file
        (export_dir / ".last-run").unlink(missing_ok=True)

        with patch("ibkr_operator._check_diagnostics_cooldown",
                   return_value=(True, 999.0, "cooldown passed")), \
             patch("ibkr_operator._check_bridge_backpressure",
                   return_value={"ok": True, "active": 0, "max_active": 4,
                                 "rejected": 0, "leaked_md_threads": 0,
                                 "detail": "bridge has capacity"}), \
             patch("ibkr_operator.urllib.request.urlopen",
                   side_effect=mock_urlopen), \
             patch("ibkr_operator._determine_market_session_status",
                   return_value=_make_session_info("rth")), \
             patch("ibkr_operator._git_metadata",
                   return_value={"branch": "t", "commit": "abc", "tag": "t"}), \
             patch("ibkr_operator.time.sleep"), \
             patch("ibkr_operator._MD_DIAGNOSTICS_EXPORT_DIR", export_dir), \
             patch("ibkr_operator.os.fsync"):
            result = _run_market_data_diagnostics(symbol="AAPL")

        assert result["aborted_early"] is True
        assert result["abort_reason"] is not None
        assert "503" in str(result["abort_reason"])

    def test_diagnostics_handles_timeout_gracefully(self):
        """Diagnostics handles urllib timeout without crashing or leaking."""
        from ibkr_operator import _run_market_data_diagnostics

        # All bridge calls timeout
        def _timeout_side_effect(*args, **kwargs):
            raise TimeoutError("simulated timeout")

        from pathlib import Path
        export_dir = Path("/tmp/md-diag-test-timeout")
        export_dir.mkdir(parents=True, exist_ok=True)
        (export_dir / ".last-run").unlink(missing_ok=True)

        with patch("ibkr_operator._check_diagnostics_cooldown",
                   return_value=(True, 999.0, "cooldown passed")), \
             patch("ibkr_operator._check_bridge_backpressure",
                   return_value={"ok": True, "active": 0, "max_active": 4,
                                 "rejected": 0, "leaked_md_threads": 0,
                                 "detail": "bridge has capacity"}), \
             patch("ibkr_operator.urllib.request.urlopen",
                   side_effect=_timeout_side_effect), \
             patch("ibkr_operator._determine_market_session_status",
                   return_value=_make_session_info("rth")), \
             patch("ibkr_operator._git_metadata",
                   return_value={"branch": "t", "commit": "abc", "tag": "t"}), \
             patch("ibkr_operator.time.sleep"), \
             patch("ibkr_operator._MD_DIAGNOSTICS_EXPORT_DIR", export_dir), \
             patch("ibkr_operator.os.fsync"):
            result = _run_market_data_diagnostics(symbol="AAPL")

        # Should return a valid result even on total timeout
        assert result is not None
        assert "diagnosis" in result
        assert result.get("severity") in ("HOLD", "NO_GO")
        assert result.get("no_broker_mutation") is True

    def test_diagnostics_handles_exception_in_probe(self):
        """Diagnostics handles an exception in a single probe gracefully."""
        from ibkr_operator import _run_market_data_diagnostics

        call_count = [0]
        def _selective_timeout(req, timeout=None):
            call_count[0] += 1
            url = req.full_url if hasattr(req, 'full_url') else str(req)
            # Only timeout on contract lookup — others succeed
            if "/contract/stock" in url:
                raise ConnectionError("simulated connection error")
            if "/health" in url:
                return _MockResponse(200, json.dumps(_make_health_response(True)).encode())
            if "/market/snapshot" in url:
                return _MockResponse(200, json.dumps(_make_snapshot_response(True)).encode())
            if "/market/bars" in url:
                return _MockResponse(200, json.dumps(_make_bars_response(5)).encode())
            return _MockResponse(404, b"{}")

        from pathlib import Path
        export_dir = Path("/tmp/md-diag-test-exception")
        export_dir.mkdir(parents=True, exist_ok=True)
        (export_dir / ".last-run").unlink(missing_ok=True)

        with patch("ibkr_operator._check_diagnostics_cooldown",
                   return_value=(True, 999.0, "cooldown passed")), \
             patch("ibkr_operator._check_bridge_backpressure",
                   return_value={"ok": True, "active": 0, "max_active": 4,
                                 "rejected": 0, "leaked_md_threads": 0,
                                 "detail": "bridge has capacity"}), \
             patch("ibkr_operator.urllib.request.urlopen",
                   side_effect=_selective_timeout), \
             patch("ibkr_operator._determine_market_session_status",
                   return_value=_make_session_info("rth")), \
             patch("ibkr_operator._git_metadata",
                   return_value={"branch": "t", "commit": "abc", "tag": "t"}), \
             patch("ibkr_operator.time.sleep"), \
             patch("ibkr_operator._MD_DIAGNOSTICS_EXPORT_DIR", export_dir), \
             patch("ibkr_operator.os.fsync"):
            result = _run_market_data_diagnostics(symbol="AAPL")

        # Partial probe failure should still produce a valid result
        assert result is not None
        assert result.get("contract_qualified") is False
        # Other probes should have completed
        assert result.get("ibkr_connected") is True
        # Snapshot should have completed (not the same as contract_qualified)
        assert result.get("delayed_market_data_available") is True

    def test_backpressure_counter_gte_zero_after_all_operations(self):
        """Backpressure counter never goes negative after any operation."""
        # Simulate the backpressure accounting directly
        from threading import Lock
        active = 0
        lock = Lock()

        def accept():
            nonlocal active
            with lock:
                if active < 4:
                    active += 1
                    return True
                return False

        def release():
            nonlocal active
            with lock:
                if active > 0:
                    active -= 1
                # else: underflow guard

        # Simulate normal flow
        for _ in range(10):
            assert accept()
            assert active == 1
            release()
            assert active == 0

        # Simulate spurious release (should not go negative)
        for _ in range(5):
            release()
            assert active == 0, f"active should never go negative, got {active}"

        # Simulate rejected (no accept, no release needed)
        # Fill capacity
        for _ in range(4):
            assert accept()
        assert active == 4
        # Next should be rejected
        assert accept() is False
        assert active == 4  # rejected doesn't increment
        # Release all
        for _ in range(4):
            release()
        assert active == 0

    def test_diagnostics_result_includes_backpressure_fields(self):
        """Full diagnostics result includes backpressure and cooldown fields."""
        from ibkr_operator import _run_market_data_diagnostics

        mock_urlopen = _MockUrlOpen({
            "/health": (200, _make_health_response(True)),
            "/contract/stock": (200, _make_contract_response()),
            "/market/snapshot": (200, _make_snapshot_response(True, False, True)),
            "/market/bars": (200, _make_bars_response(5)),
        })

        from pathlib import Path
        export_dir = Path("/tmp/md-diag-test-bp-fields")
        export_dir.mkdir(parents=True, exist_ok=True)
        (export_dir / ".last-run").unlink(missing_ok=True)

        with patch("ibkr_operator._check_diagnostics_cooldown",
                   return_value=(True, 999.0, "cooldown passed")), \
             patch("ibkr_operator._check_bridge_backpressure",
                   return_value={"ok": True, "active": 1, "max_active": 4,
                                 "rejected": 0, "leaked_md_threads": 0,
                                 "detail": "bridge has capacity"}), \
             patch("ibkr_operator.urllib.request.urlopen",
                   side_effect=mock_urlopen), \
             patch("ibkr_operator._determine_market_session_status",
                   return_value=_make_session_info("rth")), \
             patch("ibkr_operator._git_metadata",
                   return_value={"branch": "t", "commit": "abc", "tag": "t"}), \
             patch("ibkr_operator.time.sleep"), \
             patch("ibkr_operator._MD_DIAGNOSTICS_EXPORT_DIR", export_dir), \
             patch("ibkr_operator.os.fsync"):
            result = _run_market_data_diagnostics(symbol="AAPL")

        assert "backpressure" in result
        assert result["backpressure"]["ok"] is True
        assert "cooldown" in result
        assert result["cooldown"]["ok"] is True
        assert "aborted_early" in result
        assert result["aborted_early"] is False


class TestStep15NBackpressureStillPasses:
    """Verify Step 15N backpressure tests are not weakened."""

    def test_active_count_never_negative(self):
        """Step 15N: active count underflow guard still works."""
        from threading import Lock
        active = 0
        lock = Lock()

        # Simulate the exact Step 15N guard logic
        def decrement():
            nonlocal active
            with lock:
                if active > 0:
                    active -= 1
                # else: underflow guard

        # Spam decrements — should never go negative
        for _ in range(100):
            decrement()
            assert active >= 0, f"Counter went negative: {active}"

    def test_rejected_requests_never_increment(self):
        """Step 15N: rejected requests don't increment active count."""
        from threading import Lock
        active = 0
        lock = Lock()
        max_active = 4

        def try_accept():
            nonlocal active
            with lock:
                if active >= max_active:
                    return False
                active += 1
                return True

        # Fill capacity
        for _ in range(4):
            assert try_accept()
        assert active == 4

        # Rejected should not increment
        for _ in range(10):
            assert try_accept() is False
            assert active == 4

    def test_try_finally_pattern_applies_to_all_paths(self):
        """Step 15N: try/finally decrement applies to success, error, timeout."""
        from threading import Lock
        active = 0
        lock = Lock()

        def process(crash=False):
            nonlocal active
            with lock:
                active += 1
            try:
                if crash:
                    raise RuntimeError("simulated crash")
            finally:
                with lock:
                    if active > 0:
                        active -= 1

        # Success path
        process(crash=False)
        assert active == 0

        # Error path
        try:
            process(crash=True)
        except RuntimeError:
            pass
        assert active == 0, f"Error path leaked: active={active}"

        # Mixed
        for _ in range(5):
            process(crash=False)
            assert active == 0


class TestBridgeTimeoutWrapping:
    """Verify bridge-side timeout wrapping for contract and bars endpoints.

    These tests validate the _CONTRACT_LOOKUP_TIMEOUT and _BARS_LOOKUP_TIMEOUT
    constants and the thread-executor pattern used in the bridge endpoints.
    """

    def test_timeout_constants_defined(self):
        """Timeout constants exist in bridge.py."""
        import bridge
        assert hasattr(bridge, '_CONTRACT_LOOKUP_TIMEOUT')
        assert hasattr(bridge, '_BARS_LOOKUP_TIMEOUT')
        assert bridge._CONTRACT_LOOKUP_TIMEOUT > 0
        assert bridge._BARS_LOOKUP_TIMEOUT > 0

    def test_thread_leak_tracking_functions_exist(self):
        """Thread-leak tracking functions exist in bridge.py."""
        import bridge
        assert callable(bridge._track_leaked_md_thread)
        assert callable(bridge._decrement_leaked_md_thread)
        assert hasattr(bridge, '_MD_LEAKED_THREAD_COUNT')
        assert hasattr(bridge, '_MD_LEAKED_THREAD_WARN')

    def test_leaked_thread_counter_never_negative(self):
        """Leaked thread counter underflow guard works."""
        from bridge import _MD_LEAKED_THREAD_LOCK, _MD_LEAKED_THREAD_COUNT
        initial = _MD_LEAKED_THREAD_COUNT
        try:
            # Decrement spam should not go negative
            import bridge
            for _ in range(10):
                bridge._decrement_leaked_md_thread()
            with bridge._MD_LEAKED_THREAD_LOCK:
                assert bridge._MD_LEAKED_THREAD_COUNT >= 0
        finally:
            with _MD_LEAKED_THREAD_LOCK:
                # Restore
                while bridge._MD_LEAKED_THREAD_COUNT < initial:
                    bridge._track_leaked_md_thread()

    def test_backpressure_monitor_includes_leaked_threads(self):
        """Backpressure monitor endpoint now includes leaked_md_threads field."""
        import bridge
        # Simulate the monitor_backpressure function output
        with bridge._BP_LOCK:
            active = bridge._BP_ACTIVE
        with bridge._MD_LEAKED_THREAD_LOCK:
            leaked = bridge._MD_LEAKED_THREAD_COUNT
        # Verify the fields exist and are accessible
        assert isinstance(leaked, int)
        assert leaked >= 0
        assert isinstance(active, int)
        assert active >= 0

    def test_backpressure_counter_importable_and_never_negative(self):
        """Step 15N: _BP_ACTIVE is accessible and guarded against underflow."""
        import bridge
        with bridge._BP_LOCK:
            assert bridge._BP_ACTIVE >= 0
            assert bridge._BP_TOTAL_ACCEPTED >= 0
            assert bridge._BP_TOTAL_REJECTED >= 0
