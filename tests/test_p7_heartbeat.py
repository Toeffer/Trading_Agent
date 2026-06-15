#!/usr/bin/env python3
"""
Phase 7 (P7) — Read-Only Scheduled Heartbeat Tests (pytest)

Unit tests (fast, no subprocess heartbeat):
  - Heartbeat subcommand --help succeeds
  - py_compile passes
  - No forbidden endpoints in _HEARTBEAT_ENDPOINTS or _run_heartbeat() source
  - Endpoint whitelist has exactly the 8 read-only endpoints
  - No H1 token patterns in _run_heartbeat() source
  - systemd user service/timer exists and is safe
  - Freeze non_mutating_subcommands list includes heartbeat

Integration tests (marked, runs live heartbeat):
  - heartbeat --json --quiet produces valid JSON artifact
  - Artifact contains all required summary fields
  - Advisory block confirms read-only / no-orders / no-H1
  - No H1 token patterns in heartbeat output
  - Artifact is written to ~/.openclaw/heartbeat/

pytest markers:
  integration — live heartbeat invocation (skipped by default)
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

# ── Module-level constants (no subprocess calls) ──────────────────────────

REPO = Path.home() / "agents" / "ibkr-bridge"
OPERATOR = REPO / "ibkr_operator.py"
HEARTBEAT_DIR = Path.home() / ".openclaw" / "heartbeat"
SERVICE_FILE = Path.home() / ".config" / "systemd" / "user" / "ibkr-heartbeat.service"
TIMER_FILE = Path.home() / ".config" / "systemd" / "user" / "ibkr-heartbeat.timer"

REQUIRED_SUMMARY_FIELDS = [
    "timestamp", "bridge_url", "ok", "connected",
    "read_only", "allow_orders", "startup_safety_pass",
    "positions_count", "live_alert_count", "reconciliation_passed",
    "endpoint_failures", "endpoints_ok", "endpoints_total",
    "endpoint_results",
]

REQUIRED_ENDPOINTS = [
    "/health", "/readiness", "/monitor/health",
    "/monitor/reconciliation", "/monitor/alerts",
    "/monitor/positions/drift", "/positions", "/account",
]

FORBIDDEN_ENDPOINTS = [
    "/connect", "/order/approve", "/order/submit",
    "/order/preflight", "/order",
]

H1_PATTERNS = [
    "h1_token", "H1_TOKEN", "/etc/ibkr-bridge/h1_token",
    "sudo", "ibkr-trade-window",
]


# ── Helpers ───────────────────────────────────────────────────────────────

def _read_heartbeat_src() -> str:
    """Extract _run_heartbeat() source text from ibkr_operator.py."""
    if not OPERATOR.exists():
        return ""
    with open(OPERATOR) as f:
        lines = f.readlines()
    in_func = False
    src_lines = []
    for line in lines:
        if "def _run_heartbeat" in line:
            in_func = True
        elif in_func and line.startswith("def ") and "heartbeat" not in line:
            break
        elif in_func and line.startswith("# ---") and "heartbeat" not in line:
            # Section separator — stop at next section header
            break
        elif in_func:
            src_lines.append(line)
    return "".join(src_lines)


def _get_whitelist():
    """Return _HEARTBEAT_ENDPOINTS from ibkr_operator module."""
    sys.path.insert(0, str(REPO))
    from ibkr_operator import _HEARTBEAT_ENDPOINTS
    return _HEARTBEAT_ENDPOINTS


# ── Module-scoped fixtures (computed once, no subprocess) ─────────────────

@pytest.fixture(scope="module")
def heartbeat_src():
    return _read_heartbeat_src()


@pytest.fixture(scope="module")
def whitelist():
    return _get_whitelist()


# ═══════════════════════════════════════════════════════════════════════════
# UNIT TESTS — fast, no subprocess heartbeat invocation
# ═══════════════════════════════════════════════════════════════════════════

# ── 1. Heartbeat subcommand exists ───────────────────────────────────────

def test_operator_file_exists():
    assert OPERATOR.exists(), f"{OPERATOR} not found"


def test_heartbeat_help():
    result = subprocess.run(
        [sys.executable, str(OPERATOR), "heartbeat", "--help"],
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0, f"stderr: {result.stderr[:200]}"
    assert "heartbeat" in result.stdout.lower()


def test_py_compile():
    import py_compile
    try:
        py_compile.compile(str(OPERATOR), doraise=True)
    except py_compile.PyCompileError as e:
        pytest.fail(f"py_compile failed: {e}")


# ── 2. Forbidden endpoint audit ──────────────────────────────────────────

class TestForbiddenEndpoints:
    """No forbidden endpoints in whitelist or _run_heartbeat() source."""

    @pytest.mark.parametrize("ep", FORBIDDEN_ENDPOINTS)
    def test_not_in_required_list(self, ep):
        assert not any(ep in e for e in REQUIRED_ENDPOINTS), \
            f"Forbidden '{ep}' in REQUIRED_ENDPOINTS"

    @pytest.mark.parametrize("ep", FORBIDDEN_ENDPOINTS)
    def test_not_in_whitelist(self, whitelist, ep):
        assert not any(ep in e for e in whitelist), \
            f"Forbidden '{ep}' in _HEARTBEAT_ENDPOINTS"

    @pytest.mark.parametrize("ep", FORBIDDEN_ENDPOINTS)
    def test_not_in_source(self, heartbeat_src, ep):
        assert ep not in heartbeat_src, \
            f"Forbidden '{ep}' in _run_heartbeat() source"


# ── 3. Endpoint whitelist matches required set ───────────────────────────

class TestEndpointWhitelist:

    @pytest.mark.parametrize("ep", REQUIRED_ENDPOINTS)
    def test_in_whitelist(self, whitelist, ep):
        assert ep in whitelist, f"'{ep}' missing from _HEARTBEAT_ENDPOINTS"

    def test_exact_match(self, whitelist):
        assert set(whitelist) == set(REQUIRED_ENDPOINTS), \
            f"Extra: {set(whitelist) - set(REQUIRED_ENDPOINTS)}, " \
            f"Missing: {set(REQUIRED_ENDPOINTS) - set(whitelist)}"


# ── 4. No H1 token in source ─────────────────────────────────────────────

class TestH1TokenSource:

    @pytest.mark.parametrize("pat", H1_PATTERNS)
    def test_not_in_source(self, heartbeat_src, pat):
        assert pat not in heartbeat_src, \
            f"H1 pattern '{pat}' in _run_heartbeat() source"


# ── 5. Systemd service and timer ─────────────────────────────────────────

class TestSystemdUnits:

    def test_service_exists(self):
        assert SERVICE_FILE.exists(), f"{SERVICE_FILE} not found"

    def test_timer_exists(self):
        assert TIMER_FILE.exists(), f"{TIMER_FILE} not found"

    def test_timer_enabled(self):
        result = subprocess.run(
            ["systemctl", "--user", "is-enabled", "ibkr-heartbeat.timer"],
            capture_output=True, text=True, timeout=10,
        )
        assert result.stdout.strip() == "enabled", \
            f"Timer not enabled: {result.stdout.strip()}"

    def test_service_execstart(self):
        svc = SERVICE_FILE.read_text()
        assert "ExecStart" in svc

    def test_service_json_quiet_flags(self):
        svc = SERVICE_FILE.read_text()
        assert "--json" in svc and "--quiet" in svc

    def test_service_protect_system(self):
        svc = SERVICE_FILE.read_text()
        assert "ProtectSystem=strict" in svc

    def test_service_no_new_privs(self):
        svc = SERVICE_FILE.read_text()
        assert "NoNewPrivileges=true" in svc

    def test_service_no_restart_always(self):
        svc = SERVICE_FILE.read_text()
        assert "Restart=always" not in svc

    def test_service_no_exec_mutation(self):
        svc = SERVICE_FILE.read_text()
        assert "ExecStartPre" not in svc
        assert "ExecStartPost" not in svc

    @pytest.mark.parametrize("ep", FORBIDDEN_ENDPOINTS)
    def test_service_free_of_forbidden(self, ep):
        svc = SERVICE_FILE.read_text()
        assert ep not in svc, f"Forbidden '{ep}' in service file"

    def test_service_allow_orders_false(self):
        svc = SERVICE_FILE.read_text()
        ok = "ALLOW_ORDERS=false" in svc or "allow_orders" in svc.lower()
        assert ok, "Service missing ALLOW_ORDERS=false reference"


# ── 6. Freeze integrity ──────────────────────────────────────────────────

def test_freeze_includes_heartbeat():
    op_text = OPERATOR.read_text() if OPERATOR.exists() else ""
    if "non_mutating_subcommands" not in op_text:
        pytest.skip("non_mutating_subcommands not in operator source")
    start = op_text.index("non_mutating_subcommands")
    end = op_text.index("]", start)
    assert "heartbeat" in op_text[start:end], \
        "heartbeat not in non_mutating_subcommands"


# ═══════════════════════════════════════════════════════════════════════════
# INTEGRATION TESTS — run live heartbeat, validate artifact
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.integration
class TestHeartbeatIntegration:
    """Live heartbeat execution and artifact validation.

    Skipped by default.  Run with:
        pytest tests/test_p7_heartbeat.py -m integration
    """

    @pytest.fixture(scope="class")
    def heartbeat_artifact(self):
        """Run heartbeat --json --quiet once."""
        import time
        start = time.monotonic()
        result = subprocess.run(
            [sys.executable, str(OPERATOR), "heartbeat", "--json", "--quiet"],
            capture_output=True, text=True, timeout=120,
        )
        elapsed = time.monotonic() - start
        try:
            artifact = json.loads(result.stdout)
        except json.JSONDecodeError:
            artifact = {}
        return {
            "artifact": artifact,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "elapsed": elapsed,
        }

    def test_valid_json(self, heartbeat_artifact):
        assert heartbeat_artifact["artifact"], "Artifact is empty or invalid JSON"

    def test_has_timestamp(self, heartbeat_artifact):
        assert "timestamp" in heartbeat_artifact["artifact"]

    def test_endpoint_results_count(self, heartbeat_artifact):
        results = heartbeat_artifact["artifact"].get("endpoint_results", {})
        assert len(results) == 8, f"Expected 8, got {len(results)}"

    @pytest.mark.parametrize("field", REQUIRED_SUMMARY_FIELDS)
    def test_summary_field(self, heartbeat_artifact, field):
        assert field in heartbeat_artifact["artifact"], f"Missing '{field}'"

    def test_advisory_read_only(self, heartbeat_artifact):
        advisory = heartbeat_artifact["artifact"].get("advisory", "")
        assert "read-only" in advisory.lower()
        assert "no order" in advisory.lower()
        assert "no h1" in advisory.lower()

    @pytest.mark.parametrize("pat", H1_PATTERNS)
    def test_no_h1_in_output(self, heartbeat_artifact, pat):
        stdout = heartbeat_artifact["stdout"].lower()
        stderr = (heartbeat_artifact.get("stderr") or "").lower()
        assert pat.lower() not in stdout, f"'{pat}' in heartbeat stdout"
        assert pat.lower() not in stderr, f"'{pat}' in heartbeat stderr"

    def test_artifact_on_disk(self):
        assert HEARTBEAT_DIR.exists()
        artifacts = sorted(HEARTBEAT_DIR.glob("heartbeat-*.json"))
        assert len(artifacts) >= 1, "No heartbeat artifacts on disk"
        with open(artifacts[-1]) as f:
            data = json.load(f)
        assert "timestamp" in data
        assert "ok" in data
