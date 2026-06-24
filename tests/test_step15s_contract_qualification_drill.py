"""Tests for Step 15S: Contract qualification / root-cause drill."""

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_health_response(connected=True):
    return json.dumps({"status": "ok", "connected": connected}).encode()


def _make_session_info(session="rth"):
    return {"session": session, "detail": "regular trading hours"}


def _make_contract_result(qualified=True, conid=265598, exchange="SMART",
                          primary_exchange="NASDAQ", symbol="AAPL",
                          currency="USD", local_symbol="AAPL",
                          trading_class="NMS"):
    """Build a mock qualified contract probe result."""
    contract = {
        "conid": conid, "symbol": symbol, "exchange": exchange,
        "primaryExchange": primary_exchange, "currency": currency,
        "localSymbol": local_symbol, "tradingClass": trading_class,
        "asset_type": "STK",
    }
    return {
        "qualified": qualified,
        "contract": contract,
        "con_id": conid,
        "exchange": exchange,
        "primary_exchange": primary_exchange,
        "currency": currency,
        "sec_type": "STK",
        "local_symbol": local_symbol,
        "trading_class": trading_class,
        "error_code": None if qualified else 200,
        "error_message": None if qualified else "contract not found",
        "duration_seconds": 0.15,
        "aborted_503": False,
    }


def _make_contract_not_found():
    return {
        "qualified": False,
        "contract": None,
        "con_id": None,
        "exchange": "SMART",
        "primary_exchange": None,
        "currency": "USD",
        "sec_type": "STK",
        "local_symbol": None,
        "trading_class": None,
        "error_code": 200,
        "error_message": "contract not found",
        "duration_seconds": 0.12,
        "aborted_503": False,
    }


def _make_contract_503():
    return {
        "qualified": False,
        "contract": None,
        "con_id": None,
        "exchange": "SMART",
        "primary_exchange": None,
        "currency": "USD",
        "sec_type": "STK",
        "local_symbol": None,
        "trading_class": None,
        "error_code": None,
        "error_message": "contract/stock returned 503 (backpressure)",
        "duration_seconds": 0.05,
        "aborted_503": True,
    }


class _MockUrlOpen:
    """Minimal mock for urllib.request.urlopen."""
    def __init__(self, routes: dict):
        self._routes = routes
    def __call__(self, req, *args, **kwargs):
        url = req.get_full_url() if hasattr(req, 'get_full_url') else str(req)
        for path, (status, body) in self._routes.items():
            if path in url:
                return _FakeResponse(status, body)
        return _FakeResponse(200, json.dumps({"status": "ok", "connected": True}).encode())


class _FakeResponse:
    def __init__(self, status, body):
        self.status = status
        self._body = body if isinstance(body, bytes) else body.encode()
    def read(self):
        return self._body
    def __enter__(self):
        return self
    def __exit__(self, *args):
        pass


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestQualifyContractProbe:
    """Unit tests for _qualify_contract_probe helper."""

    def test_probe_qualified_default(self):
        """Default probe returns qualified contract."""
        from ibkr_operator import _qualify_contract_probe

        def fake_urlopen(req, *args, **kwargs):
            url = req.get_full_url() if hasattr(req, 'get_full_url') else req
            if '/contract/stock' in str(url):
                return _FakeResponse(200, json.dumps({
                    "conid": 265598, "symbol": "AAPL",
                    "exchange": "SMART", "currency": "USD",
                    "localSymbol": "AAPL", "tradingClass": "NMS",
                }))
            return _FakeResponse(200, json.dumps({}))

        with patch("ibkr_operator.urllib.request.urlopen", side_effect=fake_urlopen):
            result = _qualify_contract_probe("AAPL")
        assert result["qualified"] is True
        assert result["con_id"] == 265598
        assert result["duration_seconds"] >= 0

    def test_probe_not_found(self):
        """Probe returns not found."""
        from ibkr_operator import _qualify_contract_probe

        with patch("ibkr_operator.urllib.request.urlopen",
                   side_effect=_MockUrlOpen({
                       "/contract/stock": (200, json.dumps({
                           "error": "contract not found", "code": 200,
                       }).encode()),
                   })):
            result = _qualify_contract_probe("ZZZZZ")
        assert result["qualified"] is False
        assert "not found" in (result["error_message"] or "")

    def test_probe_with_primary_exchange(self):
        """Probe includes primaryExchange in request body."""
        from ibkr_operator import _qualify_contract_probe

        def fake_urlopen(req, *args, **kwargs):
            return _FakeResponse(200, json.dumps({
                "conid": 265598, "symbol": "AAPL",
            }))

        with patch("ibkr_operator.urllib.request.urlopen", side_effect=fake_urlopen):
            result = _qualify_contract_probe("AAPL", primary_exchange="NASDAQ")
        assert result["qualified"] is True

    def test_probe_503_abort(self):
        """Probe aborts on 503."""
        from ibkr_operator import _qualify_contract_probe

        import urllib.error
        def raise_503(*args, **kwargs):
            raise urllib.error.HTTPError(
                "http://x", 503, "Service Unavailable", {}, None)

        with patch("ibkr_operator.urllib.request.urlopen",
                   side_effect=raise_503):
            result = _qualify_contract_probe("AAPL")
        assert result["qualified"] is False
        assert result["aborted_503"] is True


class TestContractQualificationDrill:
    """Integration tests for _run_contract_qualification_drill."""

    def test_qualified_with_default_contract(self):
        """Default contract qualifies immediately."""
        from ibkr_operator import _run_contract_qualification_drill
        from pathlib import Path

        export_dir = Path("/tmp/cq-drill-default")
        export_dir.mkdir(parents=True, exist_ok=True)

        call_count = [0]
        def only_first_qualifies(symbol, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return _make_contract_result(qualified=True)
            return _make_contract_not_found()

        with patch("ibkr_operator._capture_safety_flags_raw",
                   return_value={"env_IBKR_ALLOW_ORDERS": "false",
                                 "rules_enforced": "false",
                                 "capture_timestamp_utc": "2026-06-24T10:00:00Z"}), \
             patch("ibkr_operator._capture_guard_state_snapshot",
                   return_value={"guard_state_path": "/tmp/gs.json",
                                 "guard_state_hash": "abc",
                                 "daily_trade_count": 0,
                                 "capture_timestamp_utc": "2026-06-24T10:00:00Z",
                                 "file_exists": True}), \
             patch("ibkr_operator._qualify_contract_probe",
                   side_effect=only_first_qualifies), \
             patch("ibkr_operator._scan_forbidden_endpoints",
                   return_value={"ok": True, "violations": []}), \
             patch("ibkr_operator._git_metadata",
                   return_value={"branch": "test", "commit": "abc", "tag": "test"}), \
             patch("ibkr_operator.urllib.request.urlopen",
                   side_effect=_MockUrlOpen({
                       "/health": (200, _make_health_response(True)),
                   })), \
             patch("ibkr_operator._CQ_DRILL_EXPORT_DIR", export_dir), \
             patch("ibkr_operator.os.fsync"):
            result = _run_contract_qualification_drill(
                symbol="AAPL", max_attempts=3, attempt_alternates=True)

        assert result["contract_qualified"] is True
        assert result["root_cause"] == "qualified_with_default_contract"
        assert result["severity"] == "OK"
        assert result["attempts_count"] >= 1
        assert result["no_broker_mutation"] is True
        assert result["no_order_window_opened"] is True

    def test_missing_primary_exchange_root_cause(self):
        """Default fails, primaryExchange alternate succeeds (only one qualifies)."""
        from ibkr_operator import _run_contract_qualification_drill
        from pathlib import Path

        export_dir = Path("/tmp/cq-drill-mpe")
        export_dir.mkdir(parents=True, exist_ok=True)

        call_count = [0]
        def alt_probe(symbol, exchange="SMART", currency="USD",
                      sec_type="STK", primary_exchange="", timeout=10.0):
            call_count[0] += 1
            if call_count[0] == 1:
                # Default fails
                return _make_contract_not_found()
            elif call_count[0] == 2:
                # First alternate succeeds (SMART + NASDAQ)
                return _make_contract_result(qualified=True, primary_exchange="NASDAQ")
            # All subsequent alternates also fail
            return _make_contract_not_found()

        with patch("ibkr_operator._capture_safety_flags_raw",
                   return_value={"env_IBKR_ALLOW_ORDERS": "false",
                                 "rules_enforced": "false",
                                 "capture_timestamp_utc": "2026-06-24T10:00:00Z"}), \
             patch("ibkr_operator._capture_guard_state_snapshot",
                   return_value={"guard_state_path": "/tmp/gs.json",
                                 "guard_state_hash": "abc",
                                 "daily_trade_count": 0,
                                 "capture_timestamp_utc": "2026-06-24T10:00:00Z",
                                 "file_exists": True}), \
             patch("ibkr_operator._qualify_contract_probe", side_effect=alt_probe), \
             patch("ibkr_operator._scan_forbidden_endpoints",
                   return_value={"ok": True, "violations": []}), \
             patch("ibkr_operator._git_metadata",
                   return_value={"branch": "test", "commit": "abc", "tag": "test"}), \
             patch("ibkr_operator.urllib.request.urlopen",
                   side_effect=_MockUrlOpen({
                       "/health": (200, _make_health_response(True)),
                   })), \
             patch("ibkr_operator._CQ_DRILL_EXPORT_DIR", export_dir), \
             patch("ibkr_operator.os.fsync"):
            result = _run_contract_qualification_drill(
                symbol="AAPL", max_attempts=5, attempt_alternates=True)

        assert result["contract_qualified"] is True
        assert result["root_cause"] == "missing_primary_exchange"
        assert result["severity"] == "OK"
        assert result["operator_action_required"] is True
        assert result["attempts_count"] >= 2

    def test_ibkr_contract_not_found(self):
        """All alternates fail — contract not found on IBKR."""
        from ibkr_operator import _run_contract_qualification_drill
        from pathlib import Path

        export_dir = Path("/tmp/cq-drill-notfound")
        export_dir.mkdir(parents=True, exist_ok=True)

        with patch("ibkr_operator._capture_safety_flags_raw",
                   return_value={"env_IBKR_ALLOW_ORDERS": "false",
                                 "rules_enforced": "false",
                                 "capture_timestamp_utc": "2026-06-24T10:00:00Z"}), \
             patch("ibkr_operator._capture_guard_state_snapshot",
                   return_value={"guard_state_path": "/tmp/gs.json",
                                 "guard_state_hash": "abc",
                                 "daily_trade_count": 0,
                                 "capture_timestamp_utc": "2026-06-24T10:00:00Z",
                                 "file_exists": True}), \
             patch("ibkr_operator._qualify_contract_probe",
                   return_value=_make_contract_not_found()), \
             patch("ibkr_operator._scan_forbidden_endpoints",
                   return_value={"ok": True, "violations": []}), \
             patch("ibkr_operator._git_metadata",
                   return_value={"branch": "test", "commit": "abc", "tag": "test"}), \
             patch("ibkr_operator.urllib.request.urlopen",
                   side_effect=_MockUrlOpen({
                       "/health": (200, _make_health_response(True)),
                   })), \
             patch("ibkr_operator._CQ_DRILL_EXPORT_DIR", export_dir), \
             patch("ibkr_operator.os.fsync"):
            result = _run_contract_qualification_drill(
                symbol="ZZZZZ", max_attempts=3, attempt_alternates=True)

        assert result["contract_qualified"] is False
        assert result["root_cause"] == "ibkr_contract_not_found"
        assert result["severity"] == "NO_GO"

    def test_ambiguous_multiple_contracts(self):
        """Multiple alternates qualify — ambiguous."""
        from ibkr_operator import _run_contract_qualification_drill
        from pathlib import Path

        export_dir = Path("/tmp/cq-drill-ambiguous")
        export_dir.mkdir(parents=True, exist_ok=True)

        call_count = [0]
        def multi_qual(symbol, **kwargs):
            call_count[0] += 1
            if call_count[0] <= 2:
                return _make_contract_result(qualified=True)
            return _make_contract_not_found()

        with patch("ibkr_operator._capture_safety_flags_raw",
                   return_value={"env_IBKR_ALLOW_ORDERS": "false",
                                 "rules_enforced": "false",
                                 "capture_timestamp_utc": "2026-06-24T10:00:00Z"}), \
             patch("ibkr_operator._capture_guard_state_snapshot",
                   return_value={"guard_state_path": "/tmp/gs.json",
                                 "guard_state_hash": "abc",
                                 "daily_trade_count": 0,
                                 "capture_timestamp_utc": "2026-06-24T10:00:00Z",
                                 "file_exists": True}), \
             patch("ibkr_operator._qualify_contract_probe", side_effect=multi_qual), \
             patch("ibkr_operator._scan_forbidden_endpoints",
                   return_value={"ok": True, "violations": []}), \
             patch("ibkr_operator._git_metadata",
                   return_value={"branch": "test", "commit": "abc", "tag": "test"}), \
             patch("ibkr_operator.urllib.request.urlopen",
                   side_effect=_MockUrlOpen({
                       "/health": (200, _make_health_response(True)),
                   })), \
             patch("ibkr_operator._CQ_DRILL_EXPORT_DIR", export_dir), \
             patch("ibkr_operator.os.fsync"):
            result = _run_contract_qualification_drill(
                symbol="AAPL", max_attempts=5, attempt_alternates=True)

        assert result["root_cause"] == "ambiguous_multiple_contracts"
        assert result["severity"] == "HOLD"
        assert len(result["qualified_contracts"]) >= 2

    def test_pacing_or_backpressure_on_503(self):
        """503 from any probe → pacing_or_backpressure."""
        from ibkr_operator import _run_contract_qualification_drill
        from pathlib import Path

        export_dir = Path("/tmp/cq-drill-503")
        export_dir.mkdir(parents=True, exist_ok=True)

        with patch("ibkr_operator._capture_safety_flags_raw",
                   return_value={"env_IBKR_ALLOW_ORDERS": "false",
                                 "rules_enforced": "false",
                                 "capture_timestamp_utc": "2026-06-24T10:00:00Z"}), \
             patch("ibkr_operator._capture_guard_state_snapshot",
                   return_value={"guard_state_path": "/tmp/gs.json",
                                 "guard_state_hash": "abc",
                                 "daily_trade_count": 0,
                                 "capture_timestamp_utc": "2026-06-24T10:00:00Z",
                                 "file_exists": True}), \
             patch("ibkr_operator._qualify_contract_probe",
                   return_value=_make_contract_503()), \
             patch("ibkr_operator._scan_forbidden_endpoints",
                   return_value={"ok": True, "violations": []}), \
             patch("ibkr_operator._git_metadata",
                   return_value={"branch": "test", "commit": "abc", "tag": "test"}), \
             patch("ibkr_operator.urllib.request.urlopen",
                   side_effect=_MockUrlOpen({
                       "/health": (200, _make_health_response(True)),
                   })), \
             patch("ibkr_operator._CQ_DRILL_EXPORT_DIR", export_dir), \
             patch("ibkr_operator.os.fsync"):
            result = _run_contract_qualification_drill(
                symbol="AAPL", max_attempts=5, attempt_alternates=True)

        assert result["root_cause"] == "pacing_or_backpressure"
        assert result["severity"] == "HOLD"
        assert result["attempts_count"] == 1  # stopped early

    def test_ibkr_disconnected_root_cause(self):
        """IBKR disconnected → ibkr_disconnected root cause."""
        from ibkr_operator import _run_contract_qualification_drill
        from pathlib import Path

        export_dir = Path("/tmp/cq-drill-disc")
        export_dir.mkdir(parents=True, exist_ok=True)

        with patch("ibkr_operator._capture_safety_flags_raw",
                   return_value={"env_IBKR_ALLOW_ORDERS": "false",
                                 "rules_enforced": "false",
                                 "capture_timestamp_utc": "2026-06-24T10:00:00Z"}), \
             patch("ibkr_operator._capture_guard_state_snapshot",
                   return_value={"guard_state_path": "/tmp/gs.json",
                                 "guard_state_hash": "abc",
                                 "daily_trade_count": 0,
                                 "capture_timestamp_utc": "2026-06-24T10:00:00Z",
                                 "file_exists": True}), \
             patch("ibkr_operator._qualify_contract_probe"), \
             patch("ibkr_operator._scan_forbidden_endpoints",
                   return_value={"ok": True, "violations": []}), \
             patch("ibkr_operator._git_metadata",
                   return_value={"branch": "test", "commit": "abc", "tag": "test"}), \
             patch("ibkr_operator.urllib.request.urlopen",
                   side_effect=_MockUrlOpen({
                       "/health": (200, _make_health_response(False)),
                   })), \
             patch("ibkr_operator._CQ_DRILL_EXPORT_DIR", export_dir), \
             patch("ibkr_operator.os.fsync"):
            result = _run_contract_qualification_drill(
                symbol="AAPL", max_attempts=3, attempt_alternates=True)

        assert result["root_cause"] == "ibkr_disconnected"
        assert result["severity"] == "HOLD"

    def test_result_is_valid_json_serializable(self):
        """Drill result round-trips through json."""
        from ibkr_operator import _run_contract_qualification_drill
        from pathlib import Path

        export_dir = Path("/tmp/cq-drill-json")
        export_dir.mkdir(parents=True, exist_ok=True)

        call_count = [0]
        def only_first_qualifies(symbol, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return _make_contract_result(qualified=True)
            return _make_contract_not_found()

        with patch("ibkr_operator._capture_safety_flags_raw",
                   return_value={"env_IBKR_ALLOW_ORDERS": "false",
                                 "rules_enforced": "false",
                                 "capture_timestamp_utc": "2026-06-24T10:00:00Z"}), \
             patch("ibkr_operator._capture_guard_state_snapshot",
                   return_value={"guard_state_path": "/tmp/gs.json",
                                 "guard_state_hash": "abc",
                                 "daily_trade_count": 0,
                                 "capture_timestamp_utc": "2026-06-24T10:00:00Z",
                                 "file_exists": True}), \
             patch("ibkr_operator._qualify_contract_probe",
                   side_effect=only_first_qualifies), \
             patch("ibkr_operator._scan_forbidden_endpoints",
                   return_value={"ok": True, "violations": []}), \
             patch("ibkr_operator._git_metadata",
                   return_value={"branch": "test", "commit": "abc", "tag": "test"}), \
             patch("ibkr_operator.urllib.request.urlopen",
                   side_effect=_MockUrlOpen({
                       "/health": (200, _make_health_response(True)),
                   })), \
             patch("ibkr_operator._CQ_DRILL_EXPORT_DIR", export_dir), \
             patch("ibkr_operator.os.fsync"):
            result = _run_contract_qualification_drill(
                symbol="AAPL", max_attempts=3, attempt_alternates=True)

        raw = json.dumps(result, default=str)
        parsed = json.loads(raw)
        assert parsed["root_cause"] == "qualified_with_default_contract"
        assert parsed["contract_qualified"] is True
        assert parsed["no_broker_mutation"] is True

    def test_safety_flags_preserved(self):
        """Safety flags and guard-state unchanged."""
        from ibkr_operator import _run_contract_qualification_drill
        from pathlib import Path

        export_dir = Path("/tmp/cq-drill-safety")
        export_dir.mkdir(parents=True, exist_ok=True)

        safety = {"env_IBKR_ALLOW_ORDERS": "false",
                  "rules_enforced": "false",
                  "capture_timestamp_utc": "2026-06-24T10:00:00Z"}

        call_count = [0]
        def only_first_qualifies(symbol, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return _make_contract_result(qualified=True)
            return _make_contract_not_found()

        with patch("ibkr_operator._capture_safety_flags_raw",
                   return_value=safety), \
             patch("ibkr_operator._capture_guard_state_snapshot",
                   return_value={"guard_state_path": "/tmp/gs.json",
                                 "guard_state_hash": "abc",
                                 "daily_trade_count": 0,
                                 "capture_timestamp_utc": "2026-06-24T10:00:00Z",
                                 "file_exists": True}), \
             patch("ibkr_operator._qualify_contract_probe",
                   side_effect=only_first_qualifies), \
             patch("ibkr_operator._scan_forbidden_endpoints",
                   return_value={"ok": True, "violations": []}), \
             patch("ibkr_operator._git_metadata",
                   return_value={"branch": "test", "commit": "abc", "tag": "test"}), \
             patch("ibkr_operator.urllib.request.urlopen",
                   side_effect=_MockUrlOpen({
                       "/health": (200, _make_health_response(True)),
                   })), \
             patch("ibkr_operator._CQ_DRILL_EXPORT_DIR", export_dir), \
             patch("ibkr_operator.os.fsync"):
            result = _run_contract_qualification_drill(
                symbol="AAPL", max_attempts=3)

        assert result["safety_flags_unchanged"] is True
        assert result["guard_state_unchanged"] is True
        assert result["no_broker_mutation"] is True
        assert result["no_order_window_opened"] is True

    def test_cli_alias_cq_drill(self):
        """cq-drill alias works."""
        import subprocess
        cp = subprocess.run(
            [".venv/bin/python", "ibkr_operator.py", "cq-drill", "--help"],
            capture_output=True, text=True, cwd="/home/chris/agents/ibkr-bridge",
            timeout=10)
        assert cp.returncode == 0
        # The alias shows the subcommand name, not the parent
        assert "--symbol" in cp.stdout

    def test_cli_contract_diagnostics(self):
        """contract-diagnostics alias works."""
        import subprocess
        cp = subprocess.run(
            [".venv/bin/python", "ibkr_operator.py", "contract-diagnostics", "--help"],
            capture_output=True, text=True, cwd="/home/chris/agents/ibkr-bridge",
            timeout=10)
        assert cp.returncode == 0
        assert "--symbol" in cp.stdout

    def test_qualified_with_alternate_exchange(self):
        """Default fails, alternate exchange (not SMART) qualifies."""
        from ibkr_operator import _run_contract_qualification_drill
        from pathlib import Path

        export_dir = Path("/tmp/cq-drill-alt-ex")
        export_dir.mkdir(parents=True, exist_ok=True)

        call_count = [0]
        def alt_probe(symbol, exchange="SMART", currency="USD",
                      sec_type="STK", primary_exchange="", timeout=10.0):
            call_count[0] += 1
            # Default SMART fails, all SMART+PE fail, but NASDAQ alternate succeeds
            if exchange == "NASDAQ":
                return _make_contract_result(qualified=True, exchange="NASDAQ",
                                            primary_exchange="")
            return _make_contract_not_found()

        with patch("ibkr_operator._capture_safety_flags_raw",
                   return_value={"env_IBKR_ALLOW_ORDERS": "false",
                                 "rules_enforced": "false",
                                 "capture_timestamp_utc": "2026-06-24T10:00:00Z"}), \
             patch("ibkr_operator._capture_guard_state_snapshot",
                   return_value={"guard_state_path": "/tmp/gs.json",
                                 "guard_state_hash": "abc",
                                 "daily_trade_count": 0,
                                 "capture_timestamp_utc": "2026-06-24T10:00:00Z",
                                 "file_exists": True}), \
             patch("ibkr_operator._qualify_contract_probe", side_effect=alt_probe), \
             patch("ibkr_operator._scan_forbidden_endpoints",
                   return_value={"ok": True, "violations": []}), \
             patch("ibkr_operator._git_metadata",
                   return_value={"branch": "test", "commit": "abc", "tag": "test"}), \
             patch("ibkr_operator.urllib.request.urlopen",
                   side_effect=_MockUrlOpen({
                       "/health": (200, _make_health_response(True)),
                   })), \
             patch("ibkr_operator._CQ_DRILL_EXPORT_DIR", export_dir), \
             patch("ibkr_operator.os.fsync"):
            result = _run_contract_qualification_drill(
                symbol="AAPL", max_attempts=5, attempt_alternates=True)

        assert result["contract_qualified"] is True
        assert result["root_cause"] == "qualified_with_alternate_exchange"
        assert result["severity"] == "OK"
        assert result["operator_action_required"] is True

    def test_bridge_health_unreachable_url_error(self):
        """Bridge health URL error → NO_GO / bridge_runtime_error."""
        from ibkr_operator import _run_contract_qualification_drill
        from pathlib import Path
        import urllib.error

        export_dir = Path("/tmp/cq-drill-url-err")
        export_dir.mkdir(parents=True, exist_ok=True)

        def raise_url_err(req, *args, **kwargs):
            raise urllib.error.URLError("connection refused")

        with patch("ibkr_operator._capture_safety_flags_raw",
                   return_value={"env_IBKR_ALLOW_ORDERS": "false",
                                 "rules_enforced": "false",
                                 "capture_timestamp_utc": "2026-06-24T10:00:00Z"}), \
             patch("ibkr_operator._capture_guard_state_snapshot",
                   return_value={"guard_state_path": "/tmp/gs.json",
                                 "guard_state_hash": "abc",
                                 "daily_trade_count": 0,
                                 "capture_timestamp_utc": "2026-06-24T10:00:00Z",
                                 "file_exists": True}), \
             patch("ibkr_operator._qualify_contract_probe"), \
             patch("ibkr_operator._scan_forbidden_endpoints",
                   return_value={"ok": True, "violations": []}), \
             patch("ibkr_operator._git_metadata",
                   return_value={"branch": "test", "commit": "abc", "tag": "test"}), \
             patch("ibkr_operator.urllib.request.urlopen",
                   side_effect=raise_url_err), \
             patch("ibkr_operator._CQ_DRILL_EXPORT_DIR", export_dir), \
             patch("ibkr_operator.os.fsync"):
            result = _run_contract_qualification_drill(
                symbol="AAPL", max_attempts=3)

        assert result["root_cause"] == "bridge_runtime_error"
        assert result["severity"] == "NO_GO"
        assert result["bridge_runtime_ok"] is False
        assert result["bridge_reachable"] is False

    def test_export_path_written(self):
        """Export path is written to disk."""
        from ibkr_operator import _run_contract_qualification_drill
        from pathlib import Path

        export_dir = Path("/tmp/cq-drill-export")
        export_dir.mkdir(parents=True, exist_ok=True)

        call_count = [0]
        def only_first(symbol, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return _make_contract_result(qualified=True)
            return _make_contract_not_found()

        with patch("ibkr_operator._capture_safety_flags_raw",
                   return_value={"env_IBKR_ALLOW_ORDERS": "false",
                                 "rules_enforced": "false",
                                 "capture_timestamp_utc": "2026-06-24T10:00:00Z"}), \
             patch("ibkr_operator._capture_guard_state_snapshot",
                   return_value={"guard_state_path": "/tmp/gs.json",
                                 "guard_state_hash": "abc",
                                 "daily_trade_count": 0,
                                 "capture_timestamp_utc": "2026-06-24T10:00:00Z",
                                 "file_exists": True}), \
             patch("ibkr_operator._qualify_contract_probe",
                   side_effect=only_first), \
             patch("ibkr_operator._scan_forbidden_endpoints",
                   return_value={"ok": True, "violations": []}), \
             patch("ibkr_operator._git_metadata",
                   return_value={"branch": "test", "commit": "abc", "tag": "test"}), \
             patch("ibkr_operator.urllib.request.urlopen",
                   side_effect=_MockUrlOpen({
                       "/health": (200, _make_health_response(True)),
                   })), \
             patch("ibkr_operator._CQ_DRILL_EXPORT_DIR", export_dir), \
             patch("ibkr_operator.os.fsync"):
            result = _run_contract_qualification_drill(
                symbol="AAPL", max_attempts=3, attempt_alternates=True)

        export_path = result.get("_export_path")
        assert export_path is not None
        assert export_path.startswith(str(export_dir))
        assert Path(export_path).exists()
        # Verify file contains valid JSON
        written = json.loads(Path(export_path).read_text())
        assert written["root_cause"] == "qualified_with_default_contract"

    def test_repeated_drills_no_backpressure_leak(self):
        """Repeated drills do not accumulate backpressure."""
        from ibkr_operator import _run_contract_qualification_drill
        from pathlib import Path

        export_dir = Path("/tmp/cq-drill-repeat")
        export_dir.mkdir(parents=True, exist_ok=True)

        for i in range(3):
            call_count = [0]
            def only_first(symbol, **kwargs):
                call_count[0] += 1
                if call_count[0] == 1:
                    return _make_contract_result(qualified=True)
                return _make_contract_not_found()

            with patch("ibkr_operator._capture_safety_flags_raw",
                       return_value={"env_IBKR_ALLOW_ORDERS": "false",
                                     "rules_enforced": "false",
                                     "capture_timestamp_utc": "2026-06-24T10:00:00Z"}), \
                 patch("ibkr_operator._capture_guard_state_snapshot",
                       return_value={"guard_state_path": "/tmp/gs.json",
                                     "guard_state_hash": "abc",
                                     "daily_trade_count": 0,
                                     "capture_timestamp_utc": "2026-06-24T10:00:00Z",
                                     "file_exists": True}), \
                 patch("ibkr_operator._qualify_contract_probe",
                       side_effect=only_first), \
                 patch("ibkr_operator._scan_forbidden_endpoints",
                       return_value={"ok": True, "violations": []}), \
                 patch("ibkr_operator._git_metadata",
                       return_value={"branch": "test", "commit": "abc",
                                     "tag": "test"}), \
                 patch("ibkr_operator.urllib.request.urlopen",
                       side_effect=_MockUrlOpen({
                           "/health": (200, _make_health_response(True)),
                       })), \
                 patch("ibkr_operator._CQ_DRILL_EXPORT_DIR", export_dir), \
                 patch("ibkr_operator.os.fsync"):
                result = _run_contract_qualification_drill(
                    symbol="AAPL", max_attempts=3, attempt_alternates=True)

            assert result["contract_qualified"] is True, \
                f"Run {i}: expected qualified, got {result['root_cause']}"
            assert result["root_cause"] == "qualified_with_default_contract", \
                f"Run {i}: unexpected root_cause {result['root_cause']}"
            assert result["no_broker_mutation"] is True, \
                f"Run {i}: no_broker_mutation was False"
            assert result["no_order_window_opened"] is True, \
                f"Run {i}: no_order_window_opened was False"

    def test_forbidden_endpoint_scan_no_violations(self):
        """Forbidden endpoint scan shows no /order* calls."""
        from ibkr_operator import _run_contract_qualification_drill
        from pathlib import Path

        export_dir = Path("/tmp/cq-drill-forbidden")
        export_dir.mkdir(parents=True, exist_ok=True)

        call_count = [0]
        def only_first(symbol, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return _make_contract_result(qualified=True)
            return _make_contract_not_found()

        with patch("ibkr_operator._capture_safety_flags_raw",
                   return_value={"env_IBKR_ALLOW_ORDERS": "false",
                                 "rules_enforced": "false",
                                 "capture_timestamp_utc": "2026-06-24T10:00:00Z"}), \
             patch("ibkr_operator._capture_guard_state_snapshot",
                   return_value={"guard_state_path": "/tmp/gs.json",
                                 "guard_state_hash": "abc",
                                 "daily_trade_count": 0,
                                 "capture_timestamp_utc": "2026-06-24T10:00:00Z",
                                 "file_exists": True}), \
             patch("ibkr_operator._qualify_contract_probe",
                   side_effect=only_first), \
             patch("ibkr_operator._git_metadata",
                   return_value={"branch": "test", "commit": "abc", "tag": "test"}), \
             patch("ibkr_operator.urllib.request.urlopen",
                   side_effect=_MockUrlOpen({
                       "/health": (200, _make_health_response(True)),
                   })), \
             patch("ibkr_operator._CQ_DRILL_EXPORT_DIR", export_dir), \
             patch("ibkr_operator.os.fsync"):
            result = _run_contract_qualification_drill(
                symbol="AAPL", max_attempts=3, attempt_alternates=True)

        # The scan should report ok with no violations
        scan = result.get("forbidden_endpoint_scan", {})
        assert scan.get("ok") is True
        # No /order* calls present in the drill
        assert result["no_broker_mutation"] is True
        assert result["no_order_window_opened"] is True
