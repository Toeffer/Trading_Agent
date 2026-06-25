"""Tests for Step 15W: Post-Gateway-start reconnect proof."""

import json
from pathlib import Path
from unittest.mock import patch
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


def _alerts_ok():
    return {"live": [], "live_count": 0, "active_alert_count": 0}


def _alerts_active():
    return {"live": [{"id": "a1", "severity": "WARN"}], "live_count": 1, "active_alert_count": 1}


def _safety():
    return {"env_IBKR_ALLOW_ORDERS": "false", "rules_enforced": "false",
            "capture_timestamp_utc": "2026-06-25T10:00:00Z"}


def _guard():
    return {
        "guard_state_path": "/tmp/guard-state.json",
        "guard_state_hash": "abc123def456",
        "daily_trade_count": 0,
        "capture_timestamp_utc": "2026-06-25T10:00:00Z", "file_exists": True}


def _git():
    return {"branch": "t", "commit": "abc", "tag": "t"}


BASE_PATCHES = lambda: [
    patch("ibkr_operator._capture_safety_flags_raw", return_value=_safety()),
    patch("ibkr_operator._capture_guard_state_snapshot", return_value=_guard()),
    patch("ibkr_operator._scan_forbidden_endpoints", return_value={"ok": True, "violations": []}),
    patch("ibkr_operator._git_metadata", return_value=_git()),
    patch("ibkr_operator.time.sleep"),
    patch("ibkr_operator.os.fsync"),
]


class _FakeSock:
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
    return patch("socket.socket", return_value=_FakeSock(reachable=reachable, error=error))


# Socket mock tuples
_socket_reachable = (True, None)
_socket_refused = (False, "connection refused")


# Evidence helpers
def _status_ok():
    return {"connected": True, "mode": "paper"}


def _readiness_ok():
    return {"summary": {"kill_switches": {"IBKR_ALLOW_ORDERS": "false"}}}


def _positions_ok():
    return [{"symbol": "AAPL", "position": 0}]


def _account_ok():
    return {"account": "DU12345", "account_id": "DU12345"}


def _reconciliation_ok():
    return {"passed": True, "check_count": 5, "passed_count": 5}


def _evidence_ok(ep: str):
    """Return default OK evidence for an endpoint."""
    return {
        "/status": _status_ok(),
        "/readiness": _readiness_ok(),
        "/positions": _positions_ok(),
        "/account": _account_ok(),
        "/monitor/alerts": _alerts_ok(),
        "/monitor/reconciliation": _reconciliation_ok(),
    }.get(ep, {"ok": True})


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestPostGatewayReconnectProof:

    def _run(self, bridge_health=None, monitor_alerts=None,
             socket_patch=_socket_refused,
             connect_result=None, attempt_connect=False,
             refresh_evidence=True, symbol="AAPL",
             host="127.0.0.1", port=4002, client_id=777, socket_timeout=2):
        """Run the proof with full mock stack."""
        from ibkr_operator import _run_post_gateway_reconnect_proof
        from pathlib import Path
        from contextlib import ExitStack

        ed = Path("/tmp/pgp-test")
        ed.mkdir(parents=True, exist_ok=True)

        sock = _mock_socket(*socket_patch) if isinstance(socket_patch, tuple) else socket_patch

        bh = bridge_health if bridge_health is not None else lambda: _health(connected=False)
        ma = monitor_alerts if monitor_alerts is not None else lambda: _alerts_ok()

        routes = {
            "/health": lambda: (200, json.dumps(bh() if callable(bh) else bh)),
            "/monitor/alerts": lambda: (200, json.dumps(ma() if callable(ma) else ma)),
            "/status": lambda: (200, json.dumps(_evidence_ok("/status"))),
            "/readiness": lambda: (200, json.dumps(_evidence_ok("/readiness"))),
            "/positions": lambda: (200, json.dumps(_evidence_ok("/positions"))),
            "/account": lambda: (200, json.dumps(_evidence_ok("/account"))),
            "/monitor/reconciliation": lambda: (200, json.dumps(_evidence_ok("/monitor/reconciliation"))),
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
            stack.enter_context(patch("ibkr_operator._POST_GATEWAY_PROOF_EXPORT_DIR", ed))
            return _run_post_gateway_reconnect_proof(
                host=host, port=port, client_id=client_id,
                socket_timeout=socket_timeout,
                attempt_connect=attempt_connect,
                refresh_evidence=refresh_evidence,
                symbol=symbol,
            )

    # --- connected_already ---

    def test_connected_already(self):
        r = self._run(
            bridge_health=lambda: _health(connected=True),
            socket_patch=_socket_reachable,
            refresh_evidence=True,
        )
        assert r["diagnosis"] == "post_connect_evidence_ok"
        assert r["severity"] == "OK"
        assert r["bridge_connected_before"] is True
        assert r["bridge_connected_after"] is True

    # --- gateway_socket_closed ---

    def test_gateway_socket_closed(self):
        r = self._run(
            bridge_health=lambda: _health(connected=False),
            socket_patch=_socket_refused,
        )
        assert r["diagnosis"] == "gateway_socket_closed"
        assert r["severity"] == "HOLD"
        assert r["operator_action_required"] is True
        assert r["connect_attempt"]["attempted"] is False

    # --- gateway_socket_reachable_no_connect_requested ---

    def test_socket_reachable_no_connect(self):
        r = self._run(
            bridge_health=lambda: _health(connected=False),
            socket_patch=_socket_reachable,
            attempt_connect=False,
        )
        assert r["diagnosis"] == "gateway_socket_reachable_no_connect_requested"
        assert r["severity"] == "HOLD"
        assert r["connect_attempt"]["attempted"] is False
        assert "connect" in r["suggested_operator_actions"][-1]

    # --- reconnect_succeeded ---

    def test_reconnect_succeeded(self):
        health_call_count = [0]

        def _health_dynamic():
            health_call_count[0] += 1
            connected = health_call_count[0] > 1
            return _health(connected=connected)

        r = self._run(
            bridge_health=_health_dynamic,
            socket_patch=_socket_reachable,
            connect_result={"ok": True, "connected": True},
            attempt_connect=True,
            refresh_evidence=True,
        )
        assert r["diagnosis"] == "post_connect_evidence_ok"
        assert r["severity"] == "OK"
        assert r["connect_attempt"]["attempted"] is True
        assert r["connect_attempt"]["ok"] is True
        assert len(r.get("readonly_evidence", {})) > 0

    # --- reconnect_failed ---

    def test_reconnect_failed(self):
        r = self._run(
            bridge_health=lambda: _health(connected=False),
            socket_patch=_socket_reachable,
            connect_result=(500, json.dumps({"detail": "internal error"})),
            attempt_connect=True,
        )
        assert r["diagnosis"] in ("reconnect_failed", "bridge_runtime_error")
        assert r["severity"] == "HOLD"
        assert r["connect_attempt"]["ok"] is False

    # --- client_id_conflict_suspected ---

    def test_client_id_conflict(self):
        r = self._run(
            bridge_health=lambda: _health(connected=False),
            socket_patch=_socket_reachable,
            connect_result=(409, json.dumps({"detail": "client_id 777 already in use"})),
            attempt_connect=True,
        )
        assert r["diagnosis"] == "client_id_conflict_suspected"
        assert r["severity"] == "HOLD"

    # --- gateway_login_required ---

    def test_gateway_login_required(self):
        r = self._run(
            bridge_health=lambda: _health(connected=False),
            socket_patch=_socket_reachable,
            connect_result=(401, json.dumps({"detail": "authentication required"})),
            attempt_connect=True,
        )
        assert r["diagnosis"] == "gateway_login_required"
        assert r["severity"] == "HOLD"

    # --- bridge_unreachable ---

    def test_bridge_unreachable(self):
        from contextlib import ExitStack

        ed = Path("/tmp/pgp-test-bu")
        ed.mkdir(parents=True, exist_ok=True)
        sock = _mock_socket(reachable=False, error="refused")

        with ExitStack() as stack:
            for p in BASE_PATCHES():
                stack.enter_context(p)
            stack.enter_context(sock)
            stack.enter_context(patch("ibkr_operator.urllib.request.urlopen",
                                      side_effect=Exception("connection refused")))
            stack.enter_context(patch("ibkr_operator._POST_GATEWAY_PROOF_EXPORT_DIR", ed))
            from ibkr_operator import _run_post_gateway_reconnect_proof
            r = _run_post_gateway_reconnect_proof(attempt_connect=False)

        assert r["diagnosis"] == "bridge_unreachable"
        assert r["severity"] == "NO_GO"

    # --- post_connect_evidence_degraded ---

    def test_post_connect_evidence_degraded(self):
        """Evidence fails on one endpoint → degraded."""
        def _status_fail():
            return (500, json.dumps({"error": "internal"}))

        custom_routes = {
            "/status": _status_fail,
        }
        def _health_connected():
            return _health(connected=True)

        from ibkr_operator import _run_post_gateway_reconnect_proof
        from pathlib import Path
        from contextlib import ExitStack

        ed = Path("/tmp/pgp-test-deg")
        ed.mkdir(parents=True, exist_ok=True)
        sock = _mock_socket(reachable=True)

        # Build routes that live outside _run's defaults
        routes = {
            "/health": lambda: (200, json.dumps(_health_connected())),
            "/monitor/alerts": lambda: (200, json.dumps(_alerts_ok())),
            "/status": lambda: (500, json.dumps({"error": "internal"})),
            "/readiness": lambda: (200, json.dumps(_evidence_ok("/readiness"))),
            "/positions": lambda: (200, json.dumps(_evidence_ok("/positions"))),
            "/account": lambda: (200, json.dumps(_evidence_ok("/account"))),
            "/monitor/reconciliation": lambda: (200, json.dumps(_evidence_ok("/monitor/reconciliation"))),
        }
        urlopen = _mock_urlopen_lazy(routes)

        with ExitStack() as stack:
            for p in BASE_PATCHES():
                stack.enter_context(p)
            stack.enter_context(sock)
            stack.enter_context(patch("ibkr_operator.urllib.request.urlopen", side_effect=urlopen))
            stack.enter_context(patch("ibkr_operator._POST_GATEWAY_PROOF_EXPORT_DIR", ed))
            r = _run_post_gateway_reconnect_proof(
                refresh_evidence=True, attempt_connect=False,
            )

        assert r["diagnosis"] == "post_connect_evidence_degraded"
        assert r["severity"] == "HOLD"

    # --- monitor_alerts_active ---

    def test_monitor_alerts_active(self):
        from ibkr_operator import _run_post_gateway_reconnect_proof
        from pathlib import Path
        from contextlib import ExitStack

        ed = Path("/tmp/pgp-test-malert")
        ed.mkdir(parents=True, exist_ok=True)
        sock = _mock_socket(reachable=True)

        routes = {
            "/health": lambda: (200, json.dumps(_health(connected=True))),
            "/monitor/alerts": lambda: (200, json.dumps(_alerts_active())),
            "/status": lambda: (200, json.dumps(_evidence_ok("/status"))),
            "/readiness": lambda: (200, json.dumps(_evidence_ok("/readiness"))),
            "/positions": lambda: (200, json.dumps(_evidence_ok("/positions"))),
            "/account": lambda: (200, json.dumps(_evidence_ok("/account"))),
            "/monitor/reconciliation": lambda: (200, json.dumps(_evidence_ok("/monitor/reconciliation"))),
        }
        urlopen = _mock_urlopen_lazy(routes)

        with ExitStack() as stack:
            for p in BASE_PATCHES():
                stack.enter_context(p)
            stack.enter_context(sock)
            stack.enter_context(patch("ibkr_operator.urllib.request.urlopen", side_effect=urlopen))
            stack.enter_context(patch("ibkr_operator._POST_GATEWAY_PROOF_EXPORT_DIR", ed))
            r = _run_post_gateway_reconnect_proof(
                refresh_evidence=True, attempt_connect=False,
            )

        assert r["diagnosis"] == "monitor_alerts_active"
        assert r["severity"] == "NO_GO"
        assert "active monitor alerts" in " ".join(r["suggested_operator_actions"])

    # --- connect skipped reason ---

    def test_connect_skipped_when_already_connected(self):
        r = self._run(
            bridge_health=lambda: _health(connected=True),
            socket_patch=_socket_reachable,
            attempt_connect=True,
        )
        assert r["connect_attempt"]["attempted"] is False
        assert r["connect_attempt"]["skipped_reason"] == "already_connected"

    def test_connect_skipped_when_socket_not_reachable(self):
        r = self._run(
            bridge_health=lambda: _health(connected=False),
            socket_patch=_socket_refused,
            attempt_connect=True,
        )
        assert r["connect_attempt"]["attempted"] is False
        assert r["connect_attempt"]["skipped_reason"] == "socket_not_reachable"

    # --- Invariants ---

    def test_no_broker_mutation(self):
        r = self._run(socket_patch=_socket_refused)
        assert r["no_broker_mutation"] is True

    def test_no_order_window_opened(self):
        r = self._run(socket_patch=_socket_refused)
        assert r["no_order_window_opened"] is True

    def test_guard_state_unchanged(self):
        r = self._run(socket_patch=_socket_refused)
        assert r["guard_state_unchanged"] is True

    def test_safety_flags_unchanged(self):
        r = self._run(socket_patch=_socket_refused)
        assert r["safety_flags_unchanged"] is True

    # --- Output structure ---

    def test_result_json_serializable(self):
        r = self._run(socket_patch=_socket_refused)
        json.dumps(r, default=str)

    def test_has_all_required_fields(self):
        r = self._run(socket_patch=_socket_refused)
        required = [
            "timestamp", "proof_id", "command",
            "git_branch", "git_commit", "git_tag",
            "requested_connection",
            "bridge_reachable", "bridge_service_active", "bridge_runtime_ok",
            "bridge_connected_before", "bridge_connected_after",
            "ib_gateway_socket",
            "connect_attempt",
            "health_before", "health_after",
            "readonly_evidence",
            "guard_state_before", "guard_state_after", "guard_state_unchanged",
            "safety_flags_before", "safety_flags_after", "safety_flags_unchanged",
            "monitor_alerts_before", "monitor_alerts_after",
            "diagnosis", "severity",
            "operator_action_required", "suggested_operator_actions",
            "no_broker_mutation", "no_order_window_opened",
            "forbidden_endpoint_scan", "explicit_non_actions",
            "evidence_hash", "_export_path",
        ]
        for field in required:
            assert field in r, f"Missing field: {field}"

    def test_requested_connection_fields(self):
        r = self._run(host="10.0.0.1", port=4001, client_id=999, symbol="META",
                      refresh_evidence=False)
        rc = r["requested_connection"]
        assert rc["host"] == "10.0.0.1"
        assert rc["port"] == 4001
        assert rc["client_id"] == 999
        assert rc["symbol"] == "META"
        assert rc["refresh_evidence"] is False

    def test_evidence_hash_present(self):
        r = self._run(socket_patch=_socket_refused)
        h = r.get("evidence_hash")
        assert h is not None
        assert len(h) == 64

    def test_export_written(self):
        r = self._run(socket_patch=_socket_refused)
        assert r["_export_path"] is not None
        assert "post-gateway-reconnect-proof" in r["_export_path"]
        assert Path(r["_export_path"]).exists()

    # --- Evidence gathering ---

    def test_evidence_endpoints_probed_when_connected(self):
        health_calls = [0]
        def _h():
            health_calls[0] += 1
            return _health(connected=health_calls[0] > 0)

        r = self._run(
            bridge_health=_h,
            socket_patch=_socket_reachable,
            refresh_evidence=True,
        )
        evidence = r.get("readonly_evidence", {})
        assert len(evidence) >= 5, f"Expected >=5 evidence endpoints, got {len(evidence)}: {list(evidence.keys())}"
        expected = ["status", "readiness", "positions", "account", "monitor_alerts", "monitor_reconciliation"]
        for ep in expected:
            assert ep in evidence, f"Missing evidence endpoint: {ep}"
            assert evidence[ep]["attempted"] is True
            assert evidence[ep]["ok"] is True, f"{ep} not ok: {evidence[ep].get('error')}"

    def test_no_evidence_when_not_connected(self):
        r = self._run(
            bridge_health=lambda: _health(connected=False),
            socket_patch=_socket_refused,
            refresh_evidence=True,
        )
        assert len(r.get("readonly_evidence", {})) == 0

    def test_no_evidence_when_refresh_disabled(self):
        health_calls = [0]
        def _h():
            health_calls[0] += 1
            return _health(connected=True)

        r = self._run(
            bridge_health=_h,
            socket_patch=_socket_reachable,
            refresh_evidence=False,
        )
        assert r["diagnosis"] == "connected_already"

    def test_evidence_summaries_present(self):
        health_calls = [0]
        def _h():
            health_calls[0] += 1
            return _health(connected=True)

        r = self._run(
            bridge_health=_h,
            socket_patch=_socket_reachable,
            refresh_evidence=True,
        )
        for ep_name, ep_data in r.get("readonly_evidence", {}).items():
            summary = ep_data.get("summary")
            assert summary is not None, f"Missing summary for {ep_name}"

    def test_diagnosis_never_unknown(self):
        for sock in (_socket_reachable, _socket_refused):
            r = self._run(socket_patch=sock)
            assert r["diagnosis"] != "unknown", f"unknown diagnosis for sock={sock}"

    # --- Aliases ---

    def test_command_aliases_registered(self):
        import subprocess
        for cmd in ("post-gateway-reconnect-proof", "reconnect-proof", "gateway-connect-proof"):
            cp = subprocess.run(
                [".venv/bin/python", "ibkr_operator.py", cmd, "--help"],
                capture_output=True, text=True,
                cwd="/home/chris/agents/ibkr-bridge", timeout=10,
            )
            assert cp.returncode == 0, f"{cmd} --help failed"
            assert "--host" in cp.stdout, f"{cmd} missing --host flag"

    def test_aliases_help_fast(self):
        import subprocess
        for cmd in ("post-gateway-reconnect-proof", "reconnect-proof", "gateway-connect-proof"):
            cp = subprocess.run(
                [".venv/bin/python", "ibkr_operator.py", cmd, "--help"],
                capture_output=True, text=True,
                cwd="/home/chris/agents/ibkr-bridge", timeout=5,
            )
            assert cp.returncode == 0

    # --- Additional acceptance tests ---

    def test_no_order_endpoint_calls(self):
        """Proof must not call /order* endpoints."""
        r = self._run(socket_patch=_socket_refused)
        forbidden_scan = r.get("forbidden_endpoint_scan", {})
        assert forbidden_scan.get("ok") is True
        assert r["no_broker_mutation"] is True
        assert r["no_order_window_opened"] is True
        non_actions_text = " ".join(r.get("explicit_non_actions", [])).lower()
        assert "/order" in non_actions_text

    def test_no_h1_token_reads(self):
        """Proof must not read or expose H1 tokens."""
        r = self._run(socket_patch=_socket_refused)
        result_json = json.dumps(r, default=str)
        assert "H1" not in result_json or "No H1" in result_json

    def test_no_unauthorized_endpoints_in_evidence(self):
        """Evidence refresh must only use allowed read-only endpoints."""
        from ibkr_operator import _POST_GATEWAY_PROOF_READONLY_ENDPOINTS
        allowed = set(_POST_GATEWAY_PROOF_READONLY_ENDPOINTS)
        forbidden_in_evidence = {"/order", "/order/preflight", "/order/approve",
                                 "/order/submit", "/connect",
                                 "/candidate-dryrun", "/market/snapshot",
                                 "/market-data-diagnostics"}
        assert allowed.isdisjoint(forbidden_in_evidence), \
            f"Forbidden endpoints in evidence set: {allowed & forbidden_in_evidence}"
