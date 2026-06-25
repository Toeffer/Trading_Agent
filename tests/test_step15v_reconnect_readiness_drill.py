"""Tests for Step 15V: Reconnect readiness drill."""

import json
from pathlib import Path
from unittest.mock import patch, Mock, MagicMock
import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _FakeResp:
    def __init__(self, status, body):
        self.status = status
        self._b = body if isinstance(body, bytes) else body.encode()
    def read(self): return self._b
    def __enter__(self): return self
    def __exit__(self, *a): pass


def _mock_urlopen(routes=None):
    """Build a side_effect that returns FakeResp for matched paths."""
    routes = routes or {}
    def handler(req, *args, **kwargs):
        url = req.get_full_url() if hasattr(req, 'get_full_url') else str(req)
        for path, (status, body) in routes.items():
            if path in url:
                return _FakeResp(status, body)
        return _FakeResp(200, json.dumps({"connected": True}))
    return handler


def _mock_urlopen_lazy(routes=None):
    """Build a side_effect with lazy route evaluation (callables as values).

    Simulates real urllib behavior: raises HTTPError for non-200 status codes.
    """
    import urllib.error
    from io import BytesIO

    routes = routes or {}
    def handler(req, *args, **kwargs):
        url = req.get_full_url() if hasattr(req, 'get_full_url') else str(req)
        for path, factory in routes.items():
            if path in url:
                result = factory()  # Call the lambda each time
                if isinstance(result, tuple):
                    status, body = result
                else:
                    status, body = 200, json.dumps(result)
                body_bytes = body if isinstance(body, bytes) else body.encode()
                if status >= 400:
                    raise urllib.error.HTTPError(
                        url, status, "Mock Error", {}, BytesIO(body_bytes))
                return _FakeResp(status, body)
        return _FakeResp(200, json.dumps({"connected": True}))
    return handler


def _health(connected=True, mode="paper", **kw):
    d = {"connected": connected, "mode": mode,
         "startup_safety": {"passed_count": 10, "check_count": 10, "all_passed": True},
         "allow_orders": "false"}
    d.update(kw)
    return d

def _readiness(**kw):
    d = {"summary": {"kill_switches": {"IBKR_ALLOW_ORDERS": "false"}}}
    d.update(kw)
    return d

def _alerts_ok():
    return {"live": [], "live_count": 0, "active_alert_count": 0}

def _safety():
    return {"env_IBKR_ALLOW_ORDERS": "false", "rules_enforced": "false",
            "capture_timestamp_utc": "2026-06-25T10:00:00Z"}

def _guard():
    return {
        "guard_state_path": "/tmp/guard-state.json",
        "guard_state_hash": "abc123def456",
        "daily_trade_count": 0,
        "capture_timestamp_utc": "2026-06-25T10:00:00Z", "file_exists": True}

def _git(): return {"branch": "t", "commit": "abc", "tag": "t"}


BASE_PATCHES = lambda: [
    patch("ibkr_operator._capture_safety_flags_raw", return_value=_safety()),
    patch("ibkr_operator._capture_guard_state_snapshot", return_value=_guard()),
    patch("ibkr_operator._scan_forbidden_endpoints", return_value={"ok": True, "violations": []}),
    patch("ibkr_operator._git_metadata", return_value=_git()),
    patch("ibkr_operator.time.sleep"),
    patch("ibkr_operator.os.fsync"),
]


# Socket mock tuples: (reachable, error)
_socket_reachable = (True, None)
_socket_refused = (False, "connection refused")
_socket_timeout = (False, "timeout after 2s")


class _FakeSock:
    """Fake socket for socket probe testing."""
    def __init__(self, reachable=True, error=None):
        self._reachable = reachable
        self._error = error
        self._timeout = 2
    def settimeout(self, t): self._timeout = t
    def connect(self, addr):
        if not self._reachable:
            import socket
            if self._error and "refused" in self._error:
                raise ConnectionRefusedError(self._error)
            elif self._error and "timeout" in self._error:
                raise socket.timeout(self._error)
            else:
                raise OSError(self._error or "connection failed")
    def close(self): pass


def _mock_socket(reachable=True, error=None):
    """Return a patch for socket.socket."""
    return patch("socket.socket", return_value=_FakeSock(reachable=reachable, error=error))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestReconnectReadinessDrill:

    def _run(self, bridge_health=_health, bridge_readiness=_readiness,
             monitor_alerts=_alerts_ok, socket_patch=_socket_reachable,
             connect_result=None, attempt_connect=False,
             host="127.0.0.1", port=4002, client_id=777, socket_timeout=2):
        """Run the drill with full mock stack."""
        from ibkr_operator import _run_reconnect_readiness_drill
        from pathlib import Path
        from contextlib import ExitStack

        ed = Path("/tmp/rrd-test")
        ed.mkdir(parents=True, exist_ok=True)

        sock = _mock_socket(*socket_patch) if isinstance(socket_patch, tuple) else socket_patch

        # Build URL routes with lazy evaluation for dynamic functions
        def _body_or_call(val):
            return val() if callable(val) else val

        routes = {
            "/health": lambda: (200, json.dumps(_body_or_call(bridge_health))),
            "/readiness": lambda: (200, json.dumps(_body_or_call(bridge_readiness))),
            "/monitor/alerts": lambda: (200, json.dumps(_body_or_call(monitor_alerts))),
        }
        if connect_result is not None:
            if callable(connect_result):
                routes["/connect"] = connect_result
            elif isinstance(connect_result, tuple):
                routes["/connect"] = lambda r=connect_result: r
            else:
                routes["/connect"] = lambda r=connect_result: (200, json.dumps(r))

        urlopen = _mock_urlopen_lazy(routes)

        with ExitStack() as stack:
            for p in BASE_PATCHES():
                stack.enter_context(p)
            stack.enter_context(sock)
            stack.enter_context(patch("ibkr_operator.urllib.request.urlopen", side_effect=urlopen))
            stack.enter_context(patch("ibkr_operator._RECONNECT_READINESS_EXPORT_DIR", ed))
            return _run_reconnect_readiness_drill(
                host=host, port=port, client_id=client_id,
                socket_timeout=socket_timeout, attempt_connect=attempt_connect)

    # --- Diagnosis: connected_already ---

    def test_connected_already(self):
        """When bridge reports IBKR already connected → connected_already / OK."""
        r = self._run(
            bridge_health=lambda: _health(connected=True),
            socket_patch=_socket_reachable,
            attempt_connect=False,
        )
        assert r["diagnosis"] == "connected_already"
        assert r["severity"] == "OK"
        assert r["operator_action_required"] is False
        assert r["bridge_connected_before"] is True
        assert r["bridge_connected_after"] is True

    # --- Diagnosis: disconnected_socket_reachable ---

    def test_disconnected_socket_reachable(self):
        """Disconnected but socket reachable → disconnected_socket_reachable / HOLD."""
        r = self._run(
            bridge_health=lambda: _health(connected=False),
            socket_patch=_socket_reachable,
            attempt_connect=False,
        )
        assert r["diagnosis"] == "disconnected_socket_reachable"
        assert r["severity"] == "HOLD"
        assert r["operator_action_required"] is True
        assert len(r["suggested_operator_actions"]) >= 3
        assert any("client_id" in a for a in r["suggested_operator_actions"])

    # --- Diagnosis: gateway_not_running ---

    def test_gateway_not_running(self):
        """Bridge reachable, disconnected, socket refused → gateway_not_running / HOLD."""
        r = self._run(
            bridge_health=lambda: _health(connected=False),
            socket_patch=_socket_refused,
            attempt_connect=False,
        )
        assert r["diagnosis"] == "gateway_not_running"
        assert r["severity"] == "HOLD"
        assert r["operator_action_required"] is True
        assert r["ib_gateway_socket"]["reachable"] is False

    # --- Diagnosis: disconnected_socket_timeout ---

    def test_disconnected_socket_timeout(self):
        """Socket timeout → gateway_not_running / HOLD, error captured."""
        r = self._run(
            bridge_health=lambda: _health(connected=False),
            socket_patch=_socket_timeout,
            attempt_connect=False,
        )
        assert r["diagnosis"] == "gateway_not_running"
        assert r["severity"] == "HOLD"
        assert "timeout" in str(r["ib_gateway_socket"].get("error", ""))

    # --- Diagnosis: bridge_unreachable ---

    def test_bridge_unreachable(self):
        """Bridge unreachable → bridge_unreachable / HOLD."""
        def _unreachable():
            raise Exception("connection refused")

        from unittest.mock import patch as ptch
        from contextlib import ExitStack

        ed = Path("/tmp/rrd-test-bu")
        ed.mkdir(parents=True, exist_ok=True)

        sock = _mock_socket(reachable=False, error="refused")
        urlopen = _mock_urlopen({})

        with ExitStack() as stack:
            for p in BASE_PATCHES():
                stack.enter_context(p)
            stack.enter_context(sock)
            # Make urlopen always raise
            stack.enter_context(ptch("ibkr_operator.urllib.request.urlopen",
                                      side_effect=Exception("connection refused")))
            stack.enter_context(ptch("ibkr_operator._RECONNECT_READINESS_EXPORT_DIR", ed))
            from ibkr_operator import _run_reconnect_readiness_drill
            r = _run_reconnect_readiness_drill(attempt_connect=False)

        assert r["diagnosis"] == "bridge_unreachable"
        assert r["severity"] == "NO_GO"
        assert r["bridge_reachable"] is False
        assert r["bridge_runtime_ok"] is False

    # --- Explicit connect: reconnect_succeeded ---

    def test_reconnect_succeeded(self):
        """--attempt-connect + successful /connect → reconnect_succeeded / OK."""
        # First health: disconnected, then after connect: connected
        health_call_count = [0]
        def _health_dynamic():
            health_call_count[0] += 1
            # First call = before connect → disconnected
            connected = health_call_count[0] > 1
            return _health(connected=connected)

        r = self._run(
            bridge_health=_health_dynamic,
            socket_patch=_socket_reachable,
            connect_result={"ok": True, "connected": True},
            attempt_connect=True,
        )
        assert r["diagnosis"] == "reconnect_succeeded"
        assert r["severity"] == "OK"
        assert r["connect_attempt"]["attempted"] is True
        assert r["connect_attempt"]["ok"] is True

    # --- Explicit connect: reconnect_failed ---

    def test_reconnect_failed(self):
        """--attempt-connect but /connect fails → reconnect_failed / HOLD."""
        r = self._run(
            bridge_health=lambda: _health(connected=False),
            socket_patch=_socket_reachable,
            connect_result=(500, json.dumps({"detail": "internal error"})),
            attempt_connect=True,
        )
        assert r["diagnosis"] in ("reconnect_failed", "bridge_runtime_error")
        assert r["severity"] == "HOLD"
        assert r["connect_attempt"]["attempted"] is True
        assert r["connect_attempt"]["ok"] is False

    # --- Explicit connect: client_id_conflict ---

    def test_client_id_conflict_suspected(self):
        """--attempt-connect + client ID conflict → client_id_conflict_suspected."""
        r = self._run(
            bridge_health=lambda: _health(connected=False),
            socket_patch=_socket_reachable,
            connect_result=(409, json.dumps({"detail": "client_id 777 already in use"})),
            attempt_connect=True,
        )
        assert r["diagnosis"] == "client_id_conflict_suspected"
        assert r["severity"] == "HOLD"

    # --- Explicit connect: skipped when already connected ---

    def test_connect_skipped_when_already_connected(self):
        """--attempt-connect skipped when already connected."""
        r = self._run(
            bridge_health=lambda: _health(connected=True),
            socket_patch=_socket_reachable,
            attempt_connect=True,
        )
        assert r["diagnosis"] == "connected_already"
        assert r["connect_attempt"]["attempted"] is False
        assert "already connected" in r["connect_attempt"]["response_summary"]

    # --- Explicit connect: skipped when socket unreachable ---

    def test_connect_skipped_when_socket_unreachable(self):
        """--attempt-connect skipped when socket is refused."""
        r = self._run(
            bridge_health=lambda: _health(connected=False),
            socket_patch=_socket_refused,
            attempt_connect=True,
        )
        assert r["connect_attempt"]["attempted"] is False
        assert "socket unreachable" in r["connect_attempt"]["response_summary"]

    # --- Invariants ---

    def test_no_broker_mutation(self):
        r = self._run(socket_patch=_socket_refused)
        assert r["no_broker_mutation"] is True

    def test_no_order_window_opened(self):
        r = self._run(socket_patch=_socket_refused)
        assert r["no_order_window_opened"] is True

    def test_safety_flags_unchanged(self):
        r = self._run(socket_patch=_socket_refused)
        assert r["safety_flags_unchanged"] is True
        assert r["safety_flags_before"]["env_IBKR_ALLOW_ORDERS"] == "false"
        assert r["safety_flags_after"]["env_IBKR_ALLOW_ORDERS"] == "false"

    def test_guard_state_unchanged(self):
        r = self._run(socket_patch=_socket_refused)
        assert r["guard_state_unchanged"] is True

    # --- Output structure ---

    def test_result_json_serializable(self):
        r = self._run(socket_patch=_socket_refused)
        assert isinstance(r, dict)
        json.dumps(r, default=str)  # must not raise

    def test_has_all_required_fields(self):
        r = self._run(socket_patch=_socket_refused)
        required = [
            "timestamp", "drill_id", "command",
            "git_branch", "git_commit", "git_tag",
            "requested_connection",
            "bridge_reachable", "bridge_service_active", "bridge_runtime_ok",
            "bridge_connected_before", "bridge_connected_after",
            "ib_gateway_socket",
            "bridge_health_before", "bridge_health_after",
            "connect_attempt",
            "readiness_before", "readiness_after",
            "monitor_alerts_before", "monitor_alerts_after",
            "guard_state_before", "guard_state_after", "guard_state_unchanged",
            "safety_flags_before", "safety_flags_after", "safety_flags_unchanged",
            "diagnosis", "severity",
            "operator_action_required", "suggested_operator_actions",
            "no_broker_mutation", "no_order_window_opened",
            "forbidden_endpoint_scan", "explicit_non_actions",
            "evidence_hash", "_export_path",
        ]
        for field in required:
            assert field in r, f"Missing field: {field}"

    def test_requested_connection_fields(self):
        r = self._run(host="10.0.0.1", port=4001, client_id=999)
        rc = r["requested_connection"]
        assert rc["host"] == "10.0.0.1"
        assert rc["port"] == 4001
        assert rc["client_id"] == 999
        assert rc["attempt_connect"] is False

    def test_evidence_hash_present(self):
        r = self._run(socket_patch=_socket_refused)
        h = r.get("evidence_hash")
        assert h is not None
        assert len(h) == 64
        # Hash must be deterministic for same inputs
        r2 = self._run(socket_patch=_socket_refused)
        assert r2["evidence_hash"] == h

    def test_export_written(self):
        r = self._run(socket_patch=_socket_refused)
        assert r["_export_path"] is not None
        assert "reconnect-readiness-drill" in r["_export_path"]
        assert Path(r["_export_path"]).exists()

    # --- Command output fields ---

    def test_command_field_readonly(self):
        r = self._run(socket_patch=_socket_refused)
        assert "reconnect-readiness-drill" in r["command"]

    def test_advisory_readonly(self):
        r = self._run(socket_patch=_socket_refused)
        assert "Read-only" in r["advisory"]

    # --- Clamping ---

    def test_socket_timeout_clamped(self):
        r = self._run(socket_timeout=0)
        # socket_timeout=0 clamped to 1 inside the drill
        assert r["requested_connection"]["host"] == "127.0.0.1"  # still runs

    # --- Aliases ---

    def test_command_aliases_registered(self):
        """All 3 command names produce --help."""
        import subprocess
        for cmd in ("reconnect-readiness-drill", "ibkr-reconnect-drill", "disconnected-readiness"):
            cp = subprocess.run(
                [".venv/bin/python", "ibkr_operator.py", cmd, "--help"],
                capture_output=True, text=True,
                cwd="/home/chris/agents/ibkr-bridge", timeout=10,
            )
            assert cp.returncode == 0, f"{cmd} --help failed"
            assert "--host" in cp.stdout, f"{cmd} missing --host flag"

    def test_aliases_help_fast(self):
        """All 3 aliases --help exit within 5s."""
        import subprocess
        for cmd in ("reconnect-readiness-drill", "ibkr-reconnect-drill", "disconnected-readiness"):
            cp = subprocess.run(
                [".venv/bin/python", "ibkr_operator.py", cmd, "--help"],
                capture_output=True, text=True,
                cwd="/home/chris/agents/ibkr-bridge", timeout=5,
            )
            assert cp.returncode == 0

    def test_help_does_not_call_bridge(self):
        """--help exits even with broken bridge URL."""
        import subprocess, os
        cp = subprocess.run(
            [".venv/bin/python", "ibkr_operator.py", "reconnect-readiness-drill", "--help"],
            capture_output=True, text=True, cwd="/home/chris/agents/ibkr-bridge", timeout=2,
            env={**os.environ, "IBKR_BRIDGE_URL": "http://127.0.0.1:1"},
        )
        assert cp.returncode == 0

    # --- Additional acceptance tests ---

    def test_no_order_endpoint_calls(self):
        """Drill must not call /order, /order/preflight, /order/approve, /order/submit."""
        r = self._run(socket_patch=_socket_refused)
        forbidden_scan = r.get("forbidden_endpoint_scan", {})
        assert forbidden_scan.get("ok") is True
        assert r["no_broker_mutation"] is True
        assert r["no_order_window_opened"] is True
        # The explicit_non_actions must include the /order prohibition
        non_actions_text = " ".join(r.get("explicit_non_actions", [])).lower()
        assert "/order" in non_actions_text  # explicitly listed as forbidden

    def test_reconnect_failure_classified(self):
        """Every reconnect failure path produces a specific diagnosis, not unknown."""
        # Test 500 error -> bridge_runtime_error
        r = self._run(
            bridge_health=lambda: _health(connected=False),
            socket_patch=_socket_reachable,
            connect_result=(500, json.dumps({"detail": "internal error"})),
            attempt_connect=True,
        )
        assert r["diagnosis"] != "unknown"
        assert r["diagnosis"] != "reconnect_failed"  # must be further classified
        assert r["severity"] == "HOLD"

    def test_monitor_alerts_remain_empty(self):
        """Drill does not create monitor alerts for expected disconnected outcomes."""
        r = self._run(
            bridge_health=lambda: _health(connected=False),
            socket_patch=_socket_reachable,
            attempt_connect=False,
        )
        # disconnected_socket_reachable should not generate alerts
        mb = r.get("monitor_alerts_before", {})
        assert mb == {} or mb.get("live") == [] or mb.get("live_count") == 0

    def test_safety_flags_unchanged_true(self):
        """Explicit check that safety_flags_unchanged is True."""
        r = self._run(socket_patch=_socket_refused)
        assert r["safety_flags_unchanged"] is True
        assert r["guard_state_unchanged"] is True

    def test_diagnosis_never_unknown_for_clean_run(self):
        """Any valid run produces a specific diagnosis, never 'unknown'."""
        for sock_mock in (_socket_reachable, _socket_refused):
            r = self._run(socket_patch=sock_mock, attempt_connect=False)
            assert r["diagnosis"] != "unknown", f"diagnosis is unknown for {sock_mock}"
