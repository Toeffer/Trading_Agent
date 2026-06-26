"""Tests for Step 15Z: Locked connected preflight-only proof."""

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
    return {"connected": connected, "mode": "paper"}


def _alerts_ok(): return {"live": [], "live_count": 0}
def _alerts_active(): return {"live": [{"id": "a1"}], "live_count": 1}


def _safety(locked=True):
    return {
        "env_IBKR_ALLOW_ORDERS": "false" if locked else "true",
        "rules_enforced": "false" if locked else "true",
        "system_locked": locked,
        "capture_timestamp_utc": "2026-06-25T10:00:00Z",
    }


def _safety_unlocked():
    return _safety(locked=False)


def _guard():
    return {
        "guard_state_path": "/tmp/gs.json", "guard_state_hash": "abc123",
        "daily_trade_count": 0, "file_exists": True,
    }


def _positions():
    return {"ok": True, "count": 0, "flat": True}


def _account():
    return {"ok": True, "account_id": "DUQ542875", "currency": "EUR", "net_liquidation": 10000.0}


def _events():
    return {"events": [], "submitted_count": 0}


def _git():
    return {"branch": "t", "commit": "abc", "tag": "t"}


def _preflight_blocked():
    return {"blocked": True, "blockers": ["IBKR_ALLOW_ORDERS=false", "rules_enforced=false"]}


def _preflight_allowed():
    return {"blocked": False, "blockers": [], "approval_id": "ap-123", "submit_token": "st-456"}


def _preflight_approval():
    return {"blocked": True, "blockers": ["IBKR_ALLOW_ORDERS=false"], "approval_id": "ap-789"}


def _readiness():
    return {"summary": {"kill_switches": {"IBKR_ALLOW_ORDERS": "false"}}}


BASE_PATCHES = lambda: [
    patch("ibkr_operator._capture_safety_flags_raw", return_value=_safety()),
    patch("ibkr_operator._capture_guard_state_snapshot", return_value=_guard()),
    patch("ibkr_operator._scan_forbidden_endpoints",
          return_value={"ok": True, "violations": []}),
    patch("ibkr_operator._git_metadata", return_value=_git()),
    patch("ibkr_operator.time.sleep"),
    patch("ibkr_operator.os.fsync"),
]


class TestLockedPreflightProof:

    def _run(self, connected=True, safety=None, preflight=None, alerts=None,
             with_preflight_route=True, **kw):
        from ibkr_operator import _run_locked_preflight_proof
        from contextlib import ExitStack

        ed = Path("/tmp/lpp-test")
        ed.mkdir(parents=True, exist_ok=True)

        s = safety if safety is not None else _safety()
        pf = preflight if preflight is not None else _preflight_blocked()
        ma = alerts if alerts is not None else _alerts_ok()

        routes = {
            "/health": lambda: (200, json.dumps(_health(connected=connected))),
            "/monitor/alerts": lambda: (200, json.dumps(ma)),
            "/monitor/events": lambda: (200, json.dumps(_events())),
            "/readiness": lambda: (200, json.dumps(_readiness())),
            "/positions": lambda: (200, json.dumps([])),
            "/account": lambda: (200, json.dumps(_account())),
        }
        if with_preflight_route:
            if callable(pf):
                routes["/order/preflight"] = pf
            else:
                routes["/order/preflight"] = lambda p=pf: (200, json.dumps(p))

        urlopen = _mock_urlopen_lazy(routes)

        with ExitStack() as stack:
            for p in BASE_PATCHES():
                stack.enter_context(p)
            stack.enter_context(patch("ibkr_operator.urllib.request.urlopen",
                                       side_effect=urlopen))
            stack.enter_context(patch("ibkr_operator._LOCKED_PREFLIGHT_EXPORT_DIR", ed))
            return _run_locked_preflight_proof(**kw)

    # --- Blocked when locked ---

    def test_locked_preflight_blocked_ok(self):
        r = self._run(connected=True, safety=_safety(locked=True),
                      preflight=_preflight_blocked())
        assert r["diagnosis"] == "locked_preflight_blocked"
        assert r["severity"] == "OK"
        ps = r["preflight_summary"]
        assert ps["blocked_count"] == 1
        assert ps["allowed_count"] == 0
        assert ps["approval_artifacts_present"] == 0
        assert ps["submit_tokens_present"] == 0
        assert ps["order_ids_present"] == 0

    def test_locked_preflight_blocked_with_expected_blockers(self):
        r = self._run(connected=True, safety=_safety(locked=True),
                      preflight=_preflight_blocked())
        assert r["preflight_summary"]["expected_lock_blockers_present"] is True

    # --- Disconnected path ---

    def test_disconnected(self):
        r = self._run(connected=False, safety=_safety(locked=True))
        assert r["diagnosis"] == "ibkr_disconnected"
        assert r["severity"] == "HOLD"
        assert len(r["preflight_samples"]) == 0

    # --- Preflight allowed while locked = NO_GO ---

    def test_preflight_allowed_while_locked(self):
        r = self._run(connected=True, safety=_safety(locked=True),
                      preflight=_preflight_allowed())
        assert r["diagnosis"] == "preflight_allowed_while_locked"
        assert r["severity"] == "NO_GO"

    # --- Approval artifact created = NO_GO ---

    def test_approval_artifact_while_locked(self):
        r = self._run(connected=True, safety=_safety(locked=True),
                      preflight=_preflight_approval())
        assert r["diagnosis"] == "approval_artifact_created"
        assert r["severity"] == "NO_GO"

    # --- Preflight HTTP 403 expected when locked ---

    def test_http_403_while_locked(self):
        def _pf_403():
            import urllib.error
            raise urllib.error.HTTPError("/order/preflight", 403, "Forbidden", {}, None)
        r = self._run(connected=True, safety=_safety(locked=True),
                      preflight=_pf_403)
        ps = r["preflight_summary"]
        assert ps["blocked_count"] >= 1
        assert ps["allowed_count"] == 0
        assert r["severity"] == "OK"

    # --- Safety flags unchanged ---

    def test_safety_flags_unchanged(self):
        r = self._run(connected=True, safety=_safety(locked=True),
                      preflight=_preflight_blocked())
        assert r["safety_flags_unchanged"] is True

    # --- Guard state unchanged ---

    def test_guard_state_unchanged(self):
        r = self._run(connected=True, safety=_safety(locked=True),
                      preflight=_preflight_blocked())
        assert r["guard_state_unchanged"] is True

    # --- Positions unchanged ---

    def test_positions_unchanged(self):
        r = self._run(connected=True, safety=_safety(locked=True),
                      preflight=_preflight_blocked())
        assert r["positions_unchanged"] is True

    # --- Invariants ---

    def test_no_broker_mutation(self):
        r = self._run(connected=True, safety=_safety(locked=True),
                      preflight=_preflight_blocked())
        assert r["no_broker_mutation"] is True

    def test_no_order_window_opened(self):
        r = self._run(connected=True, safety=_safety(locked=True),
                      preflight=_preflight_blocked())
        assert r["no_order_window_opened"] is True

    def test_h1_token_not_used(self):
        r = self._run(connected=True, safety=_safety(locked=True),
                      preflight=_preflight_blocked())
        assert r.get("h1_token_not_used") is True

    # --- Output structure ---

    def test_result_json_serializable(self):
        r = self._run(connected=True, safety=_safety(locked=True),
                      preflight=_preflight_blocked())
        json.dumps(r, default=str)

    def test_has_required_fields(self):
        r = self._run(connected=True, safety=_safety(locked=True),
                      preflight=_preflight_blocked())
        required = [
            "timestamp", "proof_id", "command",
            "git_branch", "git_commit", "git_tag",
            "requested_preflight",
            "lock_status",
            "bridge_reachable", "bridge_connected_before", "bridge_connected_after",
            "bridge_runtime_ok",
            "safety_flags_before", "safety_flags_after", "safety_flags_unchanged",
            "guard_state_before", "guard_state_after", "guard_state_unchanged",
            "monitor_alerts_before", "monitor_alerts_after",
            "positions_before", "positions_after", "positions_unchanged",
            "account_snapshot_available",
            "preflight_samples", "preflight_summary", "mutation_summary",
            "diagnosis", "severity",
            "no_broker_mutation", "no_order_window_opened",
            "evidence_hash", "_export_path",
        ]
        for field in required:
            assert field in r, f"Missing field: {field}"

    def test_evidence_hash(self):
        r = self._run(connected=True, safety=_safety(locked=True),
                      preflight=_preflight_blocked())
        h = r.get("evidence_hash")
        assert h is not None and len(h) == 64

    def test_export_written(self):
        r = self._run(connected=True, safety=_safety(locked=True),
                      preflight=_preflight_blocked())
        assert r["_export_path"] is not None
        assert "locked-preflight-proof" in r["_export_path"]
        assert Path(r["_export_path"]).exists()

    # --- Aliases ---

    def test_command_aliases_registered(self):
        import subprocess
        cmds = ("locked-preflight-proof", "preflight-lock-proof",
                "level0-preflight-proof", "safe-preflight-proof")
        for cmd in cmds:
            cp = subprocess.run(
                [".venv/bin/python", "ibkr_operator.py", cmd, "--help"],
                capture_output=True, text=True,
                cwd="/home/chris/agents/ibkr-bridge", timeout=10,
            )
            assert cp.returncode == 0, f"{cmd} --help failed"
            assert "--symbol" in cp.stdout, f"{cmd} missing --symbol"

    def test_aliases_help_fast(self):
        import subprocess
        cmds = ("locked-preflight-proof", "preflight-lock-proof",
                "level0-preflight-proof", "safe-preflight-proof")
        for cmd in cmds:
            cp = subprocess.run(
                [".venv/bin/python", "ibkr_operator.py", cmd, "--help"],
                capture_output=True, text=True,
                cwd="/home/chris/agents/ibkr-bridge", timeout=5,
            )
            assert cp.returncode == 0

    # --- Monitor alerts active ---

    def test_monitor_alerts_active(self):
        r = self._run(connected=True, safety=_safety(locked=True),
                      preflight=_preflight_blocked(), alerts=_alerts_active())
        assert r["diagnosis"] == "monitor_alerts_active"
        assert r["severity"] == "NO_GO"

    # --- Multiple samples ---

    def test_two_samples_blocked(self):
        r = self._run(connected=True, safety=_safety(locked=True),
                      preflight=_preflight_blocked(), samples=2)
        assert r["diagnosis"] == "locked_preflight_blocked"
        assert r["preflight_summary"]["samples_count"] == 2
        assert r["preflight_summary"]["attempted_count"] == 2
        assert r["preflight_summary"]["blocked_count"] == 2

    # --- Lock status ---

    def test_lock_status_all_locked(self):
        r = self._run(connected=True, safety=_safety(locked=True),
                      preflight=_preflight_blocked())
        ls = r["lock_status"]
        assert ls["all_locked"] is True

    # --- Requested preflight params ---

    def test_requested_preflight_params(self):
        r = self._run(connected=True, safety=_safety(locked=True),
                      preflight=_preflight_blocked(), symbol="MSFT",
                      action="SELL", quantity=100, order_type="LMT")
        rp = r["requested_preflight"]
        assert rp["symbol"] == "MSFT"
        assert rp["action"] == "SELL"
        assert rp["quantity"] == 100
        assert rp["order_type"] == "LMT"
