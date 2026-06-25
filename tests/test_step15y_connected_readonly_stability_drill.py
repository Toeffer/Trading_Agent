"""Tests for Step 15Y: Connected read-only stability drill."""

import json
from pathlib import Path
from unittest.mock import patch
import pytest


class _FakeResp:
    def __init__(self, status, body):
        self.status = status
        self._b = body if isinstance(body, bytes) else body.encode()
    def read(self): return self._b
    def __enter__(self): return self
    def __exit__(self, *a): pass


def _mock_urlopen_lazy(routes=None):
    import urllib.error
    from io import BytesIO
    routes = routes or {}
    def handler(req, *args, **kwargs):
        url = req.get_full_url() if hasattr(req, 'get_full_url') else str(req)
        for path, factory in routes.items():
            if path in url:
                result = factory()
                if isinstance(result, tuple):
                    status, body = result
                else:
                    status, body = 200, json.dumps(result)
                body_bytes = body if isinstance(body, bytes) else body.encode()
                if status >= 400:
                    raise urllib.error.HTTPError(url, status, "Mock", {}, BytesIO(body_bytes))
                return _FakeResp(status, body)
        return _FakeResp(200, json.dumps({}))
    return handler


def _health(connected=True):
    return {"connected": connected, "mode": "paper",
            "startup_safety": {"passed_count": 10, "check_count": 10, "all_passed": True}}

def _alerts_ok(): return {"live": [], "live_count": 0}
def _alerts_active(): return {"live": [{"id": "a1"}], "live_count": 1}

def _safety():
    return {"env_IBKR_ALLOW_ORDERS": "false", "rules_enforced": "false",
            "capture_timestamp_utc": "2026-06-25T10:00:00Z"}

def _guard():
    return {"guard_state_path": "/tmp/gs.json", "guard_state_hash": "abc123",
            "daily_trade_count": 0, "file_exists": True,
            "capture_timestamp_utc": "2026-06-25T10:00:00Z"}

def _git(): return {"branch": "t", "commit": "abc", "tag": "t"}

BASE_PATCHES = lambda: [
    patch("ibkr_operator._capture_safety_flags_raw", return_value=_safety()),
    patch("ibkr_operator._capture_guard_state_snapshot", return_value=_guard()),
    patch("ibkr_operator._scan_forbidden_endpoints", return_value={"ok": True, "violations": []}),
    patch("ibkr_operator._git_metadata", return_value=_git()),
    patch("ibkr_operator.time.sleep"),
    patch("ibkr_operator.os.fsync"),
]

def _evidence_ok(ep_path):
    return {
        "/health": _health(connected=True),
        "/readiness": {"summary": {"kill_switches": {"IBKR_ALLOW_ORDERS": "false"}}},
        "/positions": [],
        "/account": {"account": "DU12345", "account_id": "DU12345", "net_liquidation": 10000.0, "currency": "EUR"},
        "/monitor/alerts": _alerts_ok(),
        "/monitor/reconciliation": {"passed": True, "check_count": 5, "passed_count": 5},
    }.get(ep_path, {"ok": True})


class TestConnectedReadonlyStabilityDrill:

    def _run(self, connected=True, alerts=None, samples=2, interval=1, **kw):
        from ibkr_operator import _run_connected_readonly_stability_drill
        from pathlib import Path
        from contextlib import ExitStack

        ed = Path("/tmp/csd-test")
        ed.mkdir(parents=True, exist_ok=True)

        ma = _alerts_ok() if alerts is None else (alerts() if callable(alerts) else alerts)

        routes = {
            "/health": lambda: (200, json.dumps(_health(connected=connected))),
            "/monitor/alerts": lambda: (200, json.dumps(ma)),
        }
        from ibkr_operator import _CONNECTED_STABILITY_READONLY_ENDPOINTS
        for ep_path in _CONNECTED_STABILITY_READONLY_ENDPOINTS:
            if ep_path in routes:
                continue
            routes[ep_path] = lambda p=ep_path: (200, json.dumps(_evidence_ok(p)))

        urlopen = _mock_urlopen_lazy(routes)

        with ExitStack() as stack:
            for p in BASE_PATCHES():
                stack.enter_context(p)
            stack.enter_context(patch("ibkr_operator.urllib.request.urlopen", side_effect=urlopen))
            stack.enter_context(patch("ibkr_operator._CONNECTED_STABILITY_EXPORT_DIR", ed))
            return _run_connected_readonly_stability_drill(
                samples=samples, interval_seconds=interval, **kw
            )

    # --- Connected stability OK ---

    def test_connected_stability_ok(self):
        r = self._run(connected=True, samples=3, interval=1)
        assert r["diagnosis"] == "connected_readonly_stability_ok"
        assert r["severity"] == "OK"
        assert len(r["samples"]) == 3
        ss = r["stability_summary"]
        assert ss["positions_flat_all_samples"] is True
        assert ss["guard_state_hash_stable"] is True
        assert ss["monitor_alerts_clean_all_samples"] is True

    # --- Disconnected path ---

    def test_disconnected_ibkr_disconnected(self):
        r = self._run(connected=False, samples=2, interval=1)
        assert r["diagnosis"] == "ibkr_disconnected"
        assert r["severity"] == "HOLD"
        assert len(r["samples"]) == 0

    # --- Positions changed → NO_GO ---

    def test_positions_not_flat(self):
        from ibkr_operator import _run_connected_readonly_stability_drill
        from pathlib import Path
        from contextlib import ExitStack

        ed = Path("/tmp/csd-test-pos")
        ed.mkdir(parents=True, exist_ok=True)

        def _positions_with_holding():
            return [{"symbol": "AAPL", "position": 100}]

        routes = {
            "/health": lambda: (200, json.dumps(_health(connected=True))),
            "/monitor/alerts": lambda: (200, json.dumps(_alerts_ok())),
            "/readiness": lambda: (200, json.dumps(_evidence_ok("/readiness"))),
            "/positions": lambda: (200, json.dumps(_positions_with_holding())),
            "/account": lambda: (200, json.dumps(_evidence_ok("/account"))),
            "/monitor/reconciliation": lambda: (200, json.dumps(_evidence_ok("/monitor/reconciliation"))),
        }
        urlopen = _mock_urlopen_lazy(routes)

        with ExitStack() as stack:
            for p in BASE_PATCHES():
                stack.enter_context(p)
            stack.enter_context(patch("ibkr_operator.urllib.request.urlopen", side_effect=urlopen))
            stack.enter_context(patch("ibkr_operator._CONNECTED_STABILITY_EXPORT_DIR", ed))
            r = _run_connected_readonly_stability_drill(samples=2, interval_seconds=1)

        assert r["diagnosis"] == "positions_changed"
        assert r["severity"] == "NO_GO"

    # --- Monitor alerts active ---

    def test_monitor_alerts_active(self):
        r = self._run(connected=True, alerts=_alerts_active, samples=2, interval=1)
        assert r["diagnosis"] == "monitor_alerts_active"
        assert r["severity"] == "NO_GO"

    # --- Sample structure ---

    def test_each_sample_has_endpoint_results(self):
        r = self._run(connected=True, samples=2, interval=1)
        for s in r["samples"]:
            assert "endpoint_results" in s
            assert "positions_summary" in s
            assert "account_summary" in s
            assert "guard_state_hash" in s

    def test_sample_count_matches(self):
        for n in (2, 4):
            r = self._run(connected=True, samples=n, interval=1)
            assert len(r["samples"]) == n

    # --- Invariants ---

    def test_no_broker_mutation(self):
        r = self._run(connected=True, samples=2, interval=1)
        assert r["no_broker_mutation"] is True

    def test_no_order_window_opened(self):
        r = self._run(connected=True, samples=2, interval=1)
        assert r["no_order_window_opened"] is True

    def test_guard_state_unchanged(self):
        r = self._run(connected=True, samples=2, interval=1)
        assert r["guard_state_unchanged"] is True

    def test_safety_flags_unchanged(self):
        r = self._run(connected=True, samples=2, interval=1)
        assert r["safety_flags_unchanged"] is True

    # --- Output structure ---

    def test_result_json_serializable(self):
        r = self._run(connected=True, samples=2, interval=1)
        json.dumps(r, default=str)

    def test_has_required_fields(self):
        r = self._run(connected=True, samples=2, interval=1)
        required = [
            "timestamp", "drill_id", "command",
            "git_branch", "git_commit", "git_tag",
            "requested_sampling",
            "bridge_reachable", "bridge_connected_before", "bridge_connected_after",
            "bridge_runtime_ok",
            "safety_flags_before", "safety_flags_after", "safety_flags_unchanged",
            "guard_state_before", "guard_state_after", "guard_state_unchanged",
            "monitor_alerts_before", "monitor_alerts_after",
            "samples", "stability_summary",
            "diagnosis", "severity",
            "no_broker_mutation", "no_order_window_opened",
            "evidence_hash", "_export_path",
        ]
        for field in required:
            assert field in r, f"Missing field: {field}"

    def test_evidence_hash(self):
        r = self._run(connected=True, samples=2, interval=1)
        h = r.get("evidence_hash")
        assert h is not None and len(h) == 64

    def test_export_written(self):
        r = self._run(connected=True, samples=2, interval=1)
        assert r["_export_path"] is not None
        assert "connected-readonly-stability-drill" in r["_export_path"]
        assert Path(r["_export_path"]).exists()

    # --- Aliases ---

    def test_command_aliases_registered(self):
        import subprocess
        cmds = ("connected-readonly-stability-drill", "readonly-stability-drill",
                "account-position-stability-drill", "connected-evidence-stability-drill")
        for cmd in cmds:
            cp = subprocess.run(
                [".venv/bin/python", "ibkr_operator.py", cmd, "--help"],
                capture_output=True, text=True,
                cwd="/home/chris/agents/ibkr-bridge", timeout=10,
            )
            assert cp.returncode == 0, f"{cmd} --help failed"
            assert "--samples" in cp.stdout, f"{cmd} missing --samples"

    def test_aliases_help_fast(self):
        import subprocess
        cmds = ("connected-readonly-stability-drill", "readonly-stability-drill",
                "account-position-stability-drill", "connected-evidence-stability-drill")
        for cmd in cmds:
            cp = subprocess.run(
                [".venv/bin/python", "ibkr_operator.py", cmd, "--help"],
                capture_output=True, text=True,
                cwd="/home/chris/agents/ibkr-bridge", timeout=5,
            )
            assert cp.returncode == 0
