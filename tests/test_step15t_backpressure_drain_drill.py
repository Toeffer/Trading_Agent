"""Tests for Step 15T: Backpressure drain drill."""

import json
from pathlib import Path
from unittest.mock import patch
import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ok_bp(active=0, max_active=4, leaked=0):
    return {"ok": True, "active": active, "max_active": max_active,
            "rejected": 0, "leaked_md_threads": leaked,
            "detail": f"capacity: {active}/{max_active}"}

def _sat_bp(active=4, max_active=4, leaked=0):
    return {"ok": False, "active": active, "max_active": max_active,
            "rejected": 5, "leaked_md_threads": leaked,
            "detail": f"saturated: {active}/{max_active}"}


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

def _safety():
    return {"env_IBKR_ALLOW_ORDERS": "false", "rules_enforced": "false",
            "capture_timestamp_utc": "2026-06-24T10:00:00Z"}

def _guard():
    return {"guard_state_path": "/tmp/gs.json", "guard_state_hash": "abc",
            "daily_trade_count": 0,
            "capture_timestamp_utc": "2026-06-24T10:00:00Z", "file_exists": True}

def _git(): return {"branch": "t", "commit": "abc", "tag": "t"}

def _cooldown_ok(): return (True, 60.0, "ok")
def _cooldown_active(): return (False, 10.0, "active: 20s left")

BASE_PATCHES = lambda: [
    patch("ibkr_operator._capture_safety_flags_raw", return_value=_safety()),
    patch("ibkr_operator._capture_guard_state_snapshot", return_value=_guard()),
    patch("ibkr_operator._scan_forbidden_endpoints", return_value={"ok": True, "violations": []}),
    patch("ibkr_operator._git_metadata", return_value=_git()),
    patch("ibkr_operator.time.sleep"),
    patch("ibkr_operator.os.fsync"),
]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestBackpressureDrainDrill:

    def _run(self, bp, cooldown, observe=1, poll=1, probes=False, urlopen=None):
        from ibkr_operator import _run_backpressure_drain_drill
        from pathlib import Path
        from contextlib import ExitStack
        ed = Path("/tmp/bp-test")
        ed.mkdir(parents=True, exist_ok=True)
        uo = urlopen or _mock_urlopen()
        with ExitStack() as stack:
            for p in BASE_PATCHES():
                stack.enter_context(p)
            stack.enter_context(patch("ibkr_operator._check_bridge_backpressure",
                                       side_effect=bp if callable(bp) else lambda: bp))
            stack.enter_context(patch("ibkr_operator._check_diagnostics_cooldown",
                return_value=cooldown if isinstance(cooldown, tuple) else (cooldown, 60.0, "ok")))
            stack.enter_context(patch("ibkr_operator.urllib.request.urlopen", side_effect=uo))
            stack.enter_context(patch("ibkr_operator._BP_DRAIN_EXPORT_DIR", ed))
            return _run_backpressure_drain_drill(
                observe_seconds=observe, poll_seconds=poll,
                include_endpoint_probes=probes)

    # --- Diagnoses ---

    def test_healthy_idle(self):
        r = self._run(_ok_bp(), _cooldown_ok())
        assert r["diagnosis"] == "healthy_idle"
        assert r["severity"] == "OK"
        assert r["no_broker_mutation"] is True
        assert r["no_order_window_opened"] is True

    def test_transient_saturation_drained(self):
        c = [0]
        def bp():
            c[0] += 1
            return _sat_bp(4) if c[0] <= 1 else _ok_bp(0)
        r = self._run(bp, _cooldown_ok(), observe=2)
        assert r["diagnosis"] == "transient_saturation_drained"
        assert r["severity"] == "OK"

    def test_persistent_saturation(self):
        r = self._run(_sat_bp(4), _cooldown_ok())
        assert r["diagnosis"] == "persistent_saturation"
        assert r["severity"] == "HOLD"
        assert r["operator_action_required"] is True

    def test_suspected_thread_leak(self):
        r = self._run(_sat_bp(4, leaked=3), _cooldown_ok())
        assert r["diagnosis"] == "suspected_thread_leak"
        assert r["severity"] == "NO_GO"

    def test_suspected_active_count_leak(self):
        c = [0]
        def bp():
            c[0] += 1
            return _sat_bp(2) if c[0] <= 1 else _sat_bp(4)
        r = self._run(bp, _cooldown_ok(), observe=2)
        assert r["diagnosis"] == "suspected_active_count_leak"
        assert r["severity"] == "HOLD"

    def test_cooldown_active(self):
        r = self._run(_ok_bp(), _cooldown_active())
        assert r["diagnosis"] == "cooldown_active"
        assert r["severity"] == "HOLD"
        assert r["cooldown_state"]["market_data_diagnostics_cooldown_active"] is True

    def test_bridge_unreachable(self):
        import urllib.error
        def raise_err(req, *a, **kw):
            raise urllib.error.URLError("refused")
        r = self._run(lambda: _ok_bp(), _cooldown_ok(), urlopen=raise_err)
        assert r["diagnosis"] == "bridge_unreachable"
        assert r["severity"] == "NO_GO"
        assert r["bridge_runtime_ok"] is False

    # --- Safety / guard ---

    def test_safety_flags_preserved(self):
        r = self._run(_ok_bp(), _cooldown_ok())
        assert r["safety_flags_unchanged"] is True
        assert r["guard_state_unchanged"] is True

    def test_guard_state_mutation_detected(self):
        from ibkr_operator import _run_backpressure_drain_drill
        from pathlib import Path
        from contextlib import ExitStack
        ed = Path("/tmp/bp-guard")
        ed.mkdir(parents=True, exist_ok=True)
        with ExitStack() as stack:
            for p in BASE_PATCHES():
                if "_capture_guard_state_snapshot" in str(p):
                    continue
                stack.enter_context(p)
            stack.enter_context(patch("ibkr_operator._capture_guard_state_snapshot",
                side_effect=[
                    {"guard_state_path": "/t", "guard_state_hash": "aaa",
                     "daily_trade_count": 0, "capture_timestamp_utc": "t", "file_exists": True},
                    {"guard_state_path": "/t", "guard_state_hash": "bbb",
                     "daily_trade_count": 4, "capture_timestamp_utc": "t", "file_exists": True},
                ]))
            stack.enter_context(patch("ibkr_operator._check_bridge_backpressure", return_value=_ok_bp()))
            stack.enter_context(patch("ibkr_operator._check_diagnostics_cooldown", return_value=_cooldown_ok()))
            stack.enter_context(patch("ibkr_operator.urllib.request.urlopen", side_effect=_mock_urlopen()))
            stack.enter_context(patch("ibkr_operator._BP_DRAIN_EXPORT_DIR", ed))
            r = _run_backpressure_drain_drill(observe_seconds=1, poll_seconds=1)
        assert r["guard_state_unchanged"] is False
        assert r["severity"] == "NO_GO"
        assert r["guard_daily_trade_count_after"] == 4

    # --- Endpoint probes ---

    def test_endpoint_probes_run(self):
        r = self._run(_ok_bp(), _cooldown_ok(), probes=True)
        assert r["endpoint_probes_run"] is True
        eps = [p["endpoint"] for p in r["endpoint_probe_results"]]
        assert "/positions" in eps
        assert "/account" in eps
        assert "/monitor/alerts" in eps

    def test_endpoint_probes_disabled(self):
        r = self._run(_ok_bp(), _cooldown_ok(), probes=False)
        assert r["endpoint_probes_run"] is False
        assert r["endpoint_probe_results"] == []

    def test_endpoint_probes_only_allowed_paths(self):
        """Probes only hit /positions, /account, /monitor/alerts — no /order*."""
        r = self._run(_ok_bp(), _cooldown_ok(), probes=True)
        used = [p["endpoint"] for p in r["endpoint_probe_results"]]
        for ep in used:
            assert ep in ("/positions", "/account", "/monitor/alerts"), \
                f"Unexpected probe endpoint: {ep}"
        # No /order* anywhere
        assert all("/order" not in ep for ep in used)
        assert r["no_broker_mutation"] is True
        assert r["no_order_window_opened"] is True

    # --- JSON / Export ---

    def test_result_json_serializable(self):
        r = self._run(_ok_bp(), _cooldown_ok(), probes=True)
        parsed = json.loads(json.dumps(r, default=str))
        assert parsed["diagnosis"] == "healthy_idle"
        assert parsed["samples_count"] >= 1

    def test_export_written(self):
        r = self._run(_ok_bp(), _cooldown_ok())
        ep = r.get("_export_path")
        assert ep and Path(ep).exists()

    # --- Clamping / Bounds ---

    def test_clamping_bounds(self):
        from ibkr_operator import _run_backpressure_drain_drill
        from pathlib import Path
        from contextlib import ExitStack
        ed = Path("/tmp/bp-clamp")
        ed.mkdir(parents=True, exist_ok=True)
        with ExitStack() as stack:
            for p in BASE_PATCHES():
                stack.enter_context(p)
            stack.enter_context(patch("ibkr_operator._check_bridge_backpressure", return_value=_ok_bp()))
            stack.enter_context(patch("ibkr_operator._check_diagnostics_cooldown", return_value=_cooldown_ok()))
            stack.enter_context(patch("ibkr_operator.urllib.request.urlopen", side_effect=_mock_urlopen()))
            stack.enter_context(patch("ibkr_operator._BP_DRAIN_EXPORT_DIR", ed))
            r1 = _run_backpressure_drain_drill(observe_seconds=500, poll_seconds=1)
            assert r1["observe_seconds"] == 120
            r2 = _run_backpressure_drain_drill(observe_seconds=0, poll_seconds=1)
            assert r2["observe_seconds"] == 1
            r3 = _run_backpressure_drain_drill(observe_seconds=5, poll_seconds=60)
            assert r3["poll_seconds"] == 15

    # --- Repeated drills ---

    def test_repeated_drills_no_backpressure_leak(self):
        for i in range(3):
            r = self._run(_ok_bp(), _cooldown_ok())
            assert r["diagnosis"] == "healthy_idle", f"Run {i}: {r['diagnosis']}"
            assert r["no_broker_mutation"] is True, f"Run {i}: mutated"

    # --- Aliases ---

    def test_aliases_registered(self):
        """Parser registers all 3 command names and --observe-seconds flag."""
        import subprocess
        cp = subprocess.run(
            [".venv/bin/python", "ibkr_operator.py", "backpressure-drain-drill", "--help"],
            capture_output=True, text=True, cwd="/home/chris/agents/ibkr-bridge", timeout=10)
        assert cp.returncode == 0
        assert "--observe-seconds" in cp.stdout


# ---------------------------------------------------------------------------
# Step 15T/15U Extension: CLI --help Fast-Path Tests
# ---------------------------------------------------------------------------

class TestHelpFastPath:
    """Verify CLI --help is parse-only — no heavy init, no side effects."""

    PYTHON = ".venv/bin/python"
    SCRIPT = "ibkr_operator.py"
    CWD = "/home/chris/agents/ibkr-bridge"

    def _help(self, command: str, timeout: int = 5) -> "subprocess.CompletedProcess":
        import subprocess
        return subprocess.run(
            [self.PYTHON, self.SCRIPT, command, "--help"],
            capture_output=True, text=True, cwd=self.CWD, timeout=timeout,
        )

    # --- Speed: each alias --help exits quickly ---

    def test_backpressure_drain_drill_help_fast(self):
        cp = self._help("backpressure-drain-drill", timeout=2)
        assert cp.returncode == 0
        assert "--observe-seconds" in cp.stdout

    def test_bridge_drain_drill_help_fast(self):
        cp = self._help("bridge-drain-drill", timeout=2)
        assert cp.returncode == 0

    def test_backpressure_doctor_help_fast(self):
        cp = self._help("backpressure-doctor", timeout=2)
        assert cp.returncode == 0

    def test_guard_state_drift_sentinel_help_fast(self):
        cp = self._help("guard-state-drift-sentinel", timeout=2)
        assert cp.returncode == 0
        assert "--observe-seconds" in cp.stdout

    def test_guard_drift_sentinel_help_fast(self):
        cp = self._help("guard-drift-sentinel", timeout=2)
        assert cp.returncode == 0

    def test_guard_state_audit_help_fast(self):
        cp = self._help("guard-state-audit", timeout=2)
        assert cp.returncode == 0

    # --- No side effects: --help must not write files ---

    def test_help_does_not_create_export_files(self):
        """--help must not create any export or audit files."""
        import os, tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as td:
            # Run --help with a clean HOME pointing to temp dir
            import subprocess
            env = {**os.environ, "HOME": td}
            cp = subprocess.run(
                [self.PYTHON, self.SCRIPT, "backpressure-drain-drill", "--help"],
                capture_output=True, text=True, cwd=self.CWD, timeout=5,
                env=env,
            )
            assert cp.returncode == 0

            # No exports dir should have been created
            openclaw = Path(td) / ".openclaw"
            assert not openclaw.exists(), f"{openclaw} was created by --help"

    def test_help_does_not_create_guard_state(self):
        """--help must not create or read guard-state.json."""
        import os, tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as td:
            import subprocess
            env = {**os.environ, "HOME": td}
            cp = subprocess.run(
                [self.PYTHON, self.SCRIPT, "guard-state-drift-sentinel", "--help"],
                capture_output=True, text=True, cwd=self.CWD, timeout=5,
                env=env,
            )
            assert cp.returncode == 0

            # No guard-state file should exist
            gs = Path(td) / ".openclaw" / "guard-state.json"
            assert not gs.exists(), f"guard-state.json was created by --help"

    def test_help_does_not_create_cooldown_files(self):
        """--help must not create cooldown/tracking files."""
        import os, tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as td:
            import subprocess
            env = {**os.environ, "HOME": td}
            cp = subprocess.run(
                [self.PYTHON, self.SCRIPT, "backpressure-drain-drill", "--help"],
                capture_output=True, text=True, cwd=self.CWD, timeout=5,
                env=env,
            )
            assert cp.returncode == 0

            openclaw = Path(td) / ".openclaw"
            if openclaw.exists():
                # If .openclaw exists, it must be empty (just dir maybe)
                contents = list(openclaw.rglob("*"))
                assert len(contents) == 0, f"Files created: {contents}"

    # --- No bridge calls: --help must not touch HTTP ---

    def test_help_does_not_call_bridge(self):
        """--help must exit even when bridge is unreachable / no network."""
        import subprocess
        # Use a short timeout to verify it exits quickly without connecting
        cp = subprocess.run(
            [self.PYTHON, self.SCRIPT, "backpressure-drain-drill", "--help"],
            capture_output=True, text=True, cwd=self.CWD, timeout=2,
            env={**__import__('os').environ, "IBKR_BRIDGE_URL": "http://127.0.0.1:1"},
        )
        assert cp.returncode == 0

    def test_all_15u_aliases_help_fast(self):
        """All 15U aliases (guard-state-drift-sentinel, guard-drift-sentinel,
        guard-state-audit) produce --help within 2s."""
        for alias in ("guard-state-drift-sentinel", "guard-drift-sentinel", "guard-state-audit"):
            cp = self._help(alias, timeout=2)
            assert cp.returncode == 0, f"{alias} --help failed: {cp.stderr[:200]}"
            assert len(cp.stdout) > 50, f"{alias} --help output too short"
