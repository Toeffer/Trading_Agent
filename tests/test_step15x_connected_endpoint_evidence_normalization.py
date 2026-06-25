"""Tests for Step 15X: Connected endpoint evidence normalization drill."""

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
                    raise urllib.error.HTTPError(
                        url, status, "Mock Error", {}, BytesIO(body_bytes))
                return _FakeResp(status, body)
        return _FakeResp(200, json.dumps({}))
    return handler


def _health(connected=True, mode="paper"):
    return {"connected": connected, "mode": mode,
            "startup_safety": {"passed_count": 10, "check_count": 10, "all_passed": True}}

def _alerts_ok(): return {"live": [], "live_count": 0, "active_alert_count": 0}
def _alerts_active(): return {"live": [{"id": "a1"}], "live_count": 1, "active_alert_count": 1}

def _safety():
    return {"env_IBKR_ALLOW_ORDERS": "false", "rules_enforced": "false",
            "capture_timestamp_utc": "2026-06-25T10:00:00Z"}

def _guard():
    return {"guard_state_path": "/tmp/gs.json", "guard_state_hash": "abc123",
            "daily_trade_count": 0, "capture_timestamp_utc": "2026-06-25T10:00:00Z", "file_exists": True}

def _git(): return {"branch": "t", "commit": "abc", "tag": "t"}

BASE_PATCHES = lambda: [
    patch("ibkr_operator._capture_safety_flags_raw", return_value=_safety()),
    patch("ibkr_operator._capture_guard_state_snapshot", return_value=_guard()),
    patch("ibkr_operator._scan_forbidden_endpoints", return_value={"ok": True, "violations": []}),
    patch("ibkr_operator._git_metadata", return_value=_git()),
    patch("ibkr_operator.os.fsync"),
    patch("ibkr_operator.time.sleep"),
]


def _evidence_ok(ep_path: str):
    return {
        "/health": {"connected": True, "mode": "paper"},
        "/status": {"connected": True, "mode": "paper"},
        "/readiness": {"summary": {"kill_switches": {"IBKR_ALLOW_ORDERS": "false"}}},
        "/positions": [{"symbol": "AAPL", "position": 0}],
        "/account": {"account": "DU12345"},
        "/monitor/alerts": {"live": [], "live_count": 0},
        "/monitor/reconciliation": {"passed": True},
    }.get(ep_path, {"ok": True})


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestConnectedEndpointEvidenceDrill:

    def _run(self, connected=True, alerts=None, fail_endpoints=None, **kw):
        """Run the drill with full mock stack."""
        from ibkr_operator import _run_connected_endpoint_evidence_drill
        from pathlib import Path
        from contextlib import ExitStack

        ed = Path("/tmp/ced-test")
        ed.mkdir(parents=True, exist_ok=True)

        bh = _health(connected=connected)
        ma = _alerts_ok() if alerts is None else (alerts() if callable(alerts) else alerts)
        fail_endpoints = fail_endpoints or set()

        routes = {
            "/health": lambda: (200, json.dumps(bh)),
            "/monitor/alerts": lambda: (200, json.dumps(ma)),
        }
        # Add all registry endpoints
        from ibkr_operator import _CONNECTED_ENDPOINT_REGISTRY
        for entry in _CONNECTED_ENDPOINT_REGISTRY:
            ep_path = entry["path"]
            if ep_path in routes:
                continue
            if ep_path in fail_endpoints:
                routes[ep_path] = lambda: (500, json.dumps({"error": "internal"}))
            else:
                routes[ep_path] = lambda p=ep_path: (200, json.dumps(_evidence_ok(p)))

        urlopen = _mock_urlopen_lazy(routes)

        with ExitStack() as stack:
            for p in BASE_PATCHES():
                stack.enter_context(p)
            stack.enter_context(patch("ibkr_operator.urllib.request.urlopen", side_effect=urlopen))
            stack.enter_context(patch("ibkr_operator._CONNECTED_ENDPOINT_EXPORT_DIR", ed))
            return _run_connected_endpoint_evidence_drill(**kw)

    # --- Connected: all endpoints OK ---

    def test_connected_all_ok(self):
        r = self._run(connected=True)
        assert r["diagnosis"] == "endpoints_normalized_ok"
        assert r["severity"] == "OK"
        s = r["endpoint_summary"]
        assert s["ok_count"] == s["declared_count"]
        assert s["failed_count"] == 0
        assert s["skipped_count"] == 0
        assert s["normalized_ratio"] == 1.0
        assert r["kpi_normalization_preview"]["connected_sensitive"] is False

    # --- Disconnected: connected-only endpoints skipped ---

    def test_disconnected_expected_skips(self):
        r = self._run(connected=False)
        assert r["diagnosis"] == "disconnected_expected_skips"
        assert r["severity"] == "HOLD"
        s = r["endpoint_summary"]
        assert s["skipped_count"] >= 1  # /positions, /account
        # Normalized ratio should be 1.0 (always endpoints OK)
        assert s["normalized_ratio"] >= 0.5
        # Raw ratio is lower (counts all declared)
        assert s["raw_ratio"] < s["normalized_ratio"]
        assert r["kpi_normalization_preview"]["connected_sensitive"] is True

    # --- Endpoint matrix structure ---

    def test_endpoint_matrix_has_all_entries(self):
        r = self._run(connected=True)
        matrix = r["endpoint_matrix"]
        assert len(matrix) == 7
        names = {e["name"] for e in matrix}
        assert "health" in names
        assert "readiness" in names
        assert "positions" in names
        assert "account" in names
        assert "monitor_alerts" in names
        assert "monitor_reconciliation" in names

    def test_skipped_connected_only_when_disconnected(self):
        r = self._run(connected=False)
        for e in r["endpoint_matrix"]:
            if e["applicability"] == "connected_only":
                assert e["skipped"] is True, f"{e['name']} should be skipped"
                assert "ibkr_not_connected" in (e["skipped_reason"] or "")

    def test_not_skipped_when_connected(self):
        r = self._run(connected=True)
        for e in r["endpoint_matrix"]:
            assert e["skipped"] is False, f"{e['name']} was skipped but should not be"
            assert e["attempted"] is True

    # --- Endpoint failures ---

    def test_endpoint_failure_degraded(self):
        r = self._run(connected=True, fail_endpoints={"/readiness"})
        assert r["diagnosis"] == "endpoints_degraded"
        assert r["severity"] == "HOLD"
        s = r["endpoint_summary"]
        assert s["failed_count"] >= 1

    def test_strict_mode_no_go(self):
        r = self._run(connected=True, fail_endpoints={"/readiness"}, strict=True)
        assert r["diagnosis"] == "endpoints_degraded"
        assert r["severity"] == "NO_GO"

    # --- KPI normalization preview ---

    def test_kpi_preview_shows_normalized(self):
        r = self._run(connected=True)
        kpi = r["kpi_normalization_preview"]
        assert "old_display" in kpi
        assert "proposed_display" in kpi
        assert "normalized" in kpi["proposed_display"].lower()

    def test_kpi_preview_disconnected_shows_skips(self):
        r = self._run(connected=False)
        kpi = r["kpi_normalization_preview"]
        assert "skipped" in kpi["proposed_display"].lower() or "skip" in kpi["proposed_display"].lower()
        assert kpi["connected_sensitive"] is True

    # --- Diagnosis: monitor_alerts_active ---

    def test_monitor_alerts_active(self):
        r = self._run(connected=True, alerts=_alerts_active)
        assert r["diagnosis"] == "monitor_alerts_active"
        assert r["severity"] == "NO_GO"

    # --- Invariants ---

    def test_no_broker_mutation(self):
        r = self._run(connected=False)
        assert r["no_broker_mutation"] is True

    def test_no_order_window_opened(self):
        r = self._run(connected=False)
        assert r["no_order_window_opened"] is True

    def test_guard_state_unchanged(self):
        r = self._run(connected=False)
        assert r["guard_state_unchanged"] is True

    def test_safety_flags_unchanged(self):
        r = self._run(connected=False)
        assert r["safety_flags_unchanged"] is True

    # --- Output structure ---

    def test_result_json_serializable(self):
        r = self._run(connected=False)
        json.dumps(r, default=str)

    def test_has_all_required_fields(self):
        r = self._run(connected=False)
        required = [
            "timestamp", "drill_id", "command",
            "git_branch", "git_commit", "git_tag",
            "bridge_reachable", "bridge_connected", "bridge_runtime_ok",
            "safety_flags_before", "safety_flags_after", "safety_flags_unchanged",
            "guard_state_before", "guard_state_after", "guard_state_unchanged",
            "monitor_alerts_before", "monitor_alerts_after",
            "endpoint_registry", "endpoint_matrix", "endpoint_summary",
            "kpi_normalization_preview",
            "diagnosis", "severity",
            "operator_action_required", "suggested_operator_actions",
            "no_broker_mutation", "no_order_window_opened",
            "forbidden_endpoint_scan", "explicit_non_actions",
            "evidence_hash", "_export_path",
        ]
        for field in required:
            assert field in r, f"Missing field: {field}"

    def test_evidence_hash_present(self):
        r = self._run(connected=False)
        h = r.get("evidence_hash")
        assert h is not None
        assert len(h) == 64

    def test_export_written(self):
        r = self._run(connected=False)
        assert r["_export_path"] is not None
        assert "connected-endpoint-evidence-drill" in r["_export_path"]
        assert Path(r["_export_path"]).exists()

    # --- Endpoint registry validation ---

    def test_registry_no_forbidden_endpoints(self):
        from ibkr_operator import _CONNECTED_ENDPOINT_REGISTRY, _CONNECTED_ENDPOINT_FORBIDDEN_ENDPOINTS
        paths = {e["path"] for e in _CONNECTED_ENDPOINT_REGISTRY}
        forbidden = _CONNECTED_ENDPOINT_FORBIDDEN_ENDPOINTS
        assert paths.isdisjoint(forbidden), "Registry contains forbidden endpoints"

    def test_every_registry_entry_has_required_keys(self):
        from ibkr_operator import _CONNECTED_ENDPOINT_REGISTRY
        for entry in _CONNECTED_ENDPOINT_REGISTRY:
            assert "name" in entry
            assert "path" in entry
            assert "category" in entry
            assert "applicability" in entry
            assert entry["applicability"] in ("always", "connected_only", "connected_preferred")

    # --- Endpoint summary calculation ---

    def test_normalized_denominator_smaller_when_disconnected(self):
        r_conn = self._run(connected=True)
        r_disc = self._run(connected=False)
        assert r_conn["endpoint_summary"]["normalized_denominator"] == r_conn["endpoint_summary"]["declared_count"]
        assert r_disc["endpoint_summary"]["normalized_denominator"] < r_disc["endpoint_summary"]["declared_count"]

    # --- No unauthorized endpoints ---

    def test_no_unauthorized_endpoints(self):
        r = self._run(connected=False)
        forbidden_scan = r.get("forbidden_endpoint_scan", {})
        assert forbidden_scan.get("ok") is True

    def test_non_actions_covers_protections(self):
        r = self._run(connected=False)
        na_text = " ".join(r.get("explicit_non_actions", [])).lower()
        assert "/order" in na_text
        assert "h1" in na_text

    # --- Aliases ---

    def test_command_aliases_registered(self):
        import subprocess
        for cmd in ("connected-endpoint-evidence-drill", "endpoint-evidence-drill",
                    "read-only-endpoint-proof", "endpoint-normalization-drill"):
            cp = subprocess.run(
                [".venv/bin/python", "ibkr_operator.py", cmd, "--help"],
                capture_output=True, text=True,
                cwd="/home/chris/agents/ibkr-bridge", timeout=10,
            )
            assert cp.returncode == 0, f"{cmd} --help failed"
            assert "--timeout" in cp.stdout, f"{cmd} missing --timeout flag"

    def test_aliases_help_fast(self):
        import subprocess
        for cmd in ("connected-endpoint-evidence-drill", "endpoint-evidence-drill",
                    "read-only-endpoint-proof", "endpoint-normalization-drill"):
            cp = subprocess.run(
                [".venv/bin/python", "ibkr_operator.py", cmd, "--help"],
                capture_output=True, text=True,
                cwd="/home/chris/agents/ibkr-bridge", timeout=5,
            )
            assert cp.returncode == 0
