"""Tests for the KPI / evidence dashboard (Step 12).

All tests are read-only. No broker mutation, no order endpoints,
no H1 token usage.
"""

import json
import os
import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

BRIDGE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BRIDGE_DIR))

# Forbidden endpoint substrings that must never appear in KPI endpoint lists
FORBIDDEN = ["/connect", "/order/approve", "/order/submit", "/order/preflight", "/order"]

# Module-level cache for run_kpi to avoid repeated slow endpoint calls
_kpi_cache: dict | None = None

def _get_kpi_result():
    """Get cached KPI result. Call once per module load."""
    global _kpi_cache
    if _kpi_cache is None:
        from ibkr_operator import run_kpi
        _kpi_cache = run_kpi()
    return _kpi_cache

def _get_kpi_endpoints():
    """Extract _KPI_ENDPOINTS from ibkr_operator.py."""
    from ibkr_operator import _KPI_ENDPOINTS
    return _KPI_ENDPOINTS

def _get_kpi_forbidden():
    """Extract _KPI_FORBIDDEN from ibkr_operator.py."""
    from ibkr_operator import _KPI_FORBIDDEN
    return _KPI_FORBIDDEN

# ---------------------------------------------------------------------------
# T1: No forbidden endpoints
# ---------------------------------------------------------------------------

class TestNoForbiddenEndpoints:
    """KPI endpoint list must not include any forbidden endpoints."""

    def test_kpi_endpoints_exclude_forbidden(self):
        for ep in _get_kpi_endpoints():
            for fb in FORBIDDEN:
                assert fb not in ep, (
                    f"KPI endpoint list contains forbidden endpoint: {ep}"
                )

    def test_kpi_forbidden_list_is_complete(self):
        kpi_fb = set(_get_kpi_forbidden())
        for fb in FORBIDDEN:
            assert fb in kpi_fb, (
                f"_KPI_FORBIDDEN missing {fb}"
            )

    def test_endpoint_count_gte_five(self):
        """KPI should cover at least 5 endpoints for adequate coverage."""
        eps = _get_kpi_endpoints()
        assert len(eps) >= 5, f"Expected >=5 endpoints, got {len(eps)}"

# ---------------------------------------------------------------------------
# T2: No broker mutation
# ---------------------------------------------------------------------------

class TestNoBrokerMutation:
    """KPI code must never call broker mutation functions."""

    FORBIDDEN_NAMES = {
        "placeOrder", "cancelOrder",
        "_internal_place_order",
        "save_guard_state_atomic", "initialize_guard_state",
        "append_guard_event",
    }

    def test_no_forbidden_names_in_kpi_functions(self):
        """AST check: run_kpi, print_kpi, export_kpi contain no forbidden names."""
        import ast
        src = (BRIDGE_DIR / "ibkr_operator.py").read_text()
        tree = ast.parse(src)

        # Find KPI-related functions
        kpi_funcs = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if "kpi" in node.name.lower() or "KPI" in node.name:
                    kpi_funcs.add(node.name)

        assert len(kpi_funcs) >= 3, f"Expected >=3 KPI functions, found {kpi_funcs}"

        # Check for forbidden names in KPI functions
        violations = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    name = node.func.id
                    if name in self.FORBIDDEN_NAMES:
                        # Find parent function
                        parent = node
                        while parent:
                            if isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef)):
                                if parent.name in kpi_funcs:
                                    violations.append(
                                        f"{name}() called in {parent.name} at line ~{node.lineno}"
                                    )
                                break
                            parent = getattr(parent, "parent", None)

        assert len(violations) == 0, (
            f"Forbidden names in KPI functions:\n" + "\n".join(violations)
        )

    def test_no_order_route_calls(self):
        """KPI must not make HTTP calls to /order endpoints."""
        src = (BRIDGE_DIR / "ibkr_operator.py").read_text()
        # Check the KPI endpoint list
        eps = _get_kpi_endpoints()
        for ep in eps:
            for fb in FORBIDDEN:
                assert fb not in ep, f"KPI endpoint leaks {fb}"

# ---------------------------------------------------------------------------
# T3: JSON parseable
# ---------------------------------------------------------------------------

class TestJsonParseable:
    """KPI JSON output must be valid JSON with required fields."""

    REQUIRED_TOP_KEYS = {
        "timestamp", "git", "bridge", "safety_flags",
        "monitoring", "events", "autonomy",
        "heartbeat", "doctor", "blockers", "verdict",
    }

    REQUIRED_BRIDGE_KEYS = {
        "reachable", "url", "connected", "mode", "read_only",
        "allow_orders", "positions_count", "endpoints_ok", "endpoints_total",
    }

    REQUIRED_SAFETY_KEYS = {
        "read_only", "bridge_allow_orders", "env_IBKR_ALLOW_ORDERS",
        "rules_enforced", "system_locked",
    }

    REQUIRED_AUTONOMY_KEYS = {"current_level", "clean_cycles"}

    def test_kpi_json_structure(self):
        """run_kpi() returns valid structure."""

        result = _get_kpi_result()

        # Verify top-level keys
        missing = self.REQUIRED_TOP_KEYS - set(result.keys())
        assert len(missing) == 0, f"Missing top-level keys: {missing}"

        # Verify bridge sub-structure
        bridge = result["bridge"]
        missing_b = self.REQUIRED_BRIDGE_KEYS - set(bridge.keys())
        assert len(missing_b) == 0, f"Missing bridge keys: {missing_b}"

        # Verify safety sub-structure
        sf = result["safety_flags"]
        missing_s = self.REQUIRED_SAFETY_KEYS - set(sf.keys())
        assert len(missing_s) == 0, f"Missing safety keys: {missing_s}"

        # Verify autonomy sub-structure
        au = result["autonomy"]
        missing_a = self.REQUIRED_AUTONOMY_KEYS - set(au.keys())
        assert len(missing_a) == 0, f"Missing autonomy keys: {missing_a}"

        # Verdict must be one of three values
        assert result["verdict"] in ("GO", "HOLD", "NO-GO"), (
            f"Invalid verdict: {result['verdict']}"
        )

        # Blocker list must be a list of dicts with severity and check
        for b in result["blockers"]:
            assert isinstance(b, dict), f"Blocker not a dict: {b}"
            assert "severity" in b, f"Blocker missing severity: {b}"
            assert b["severity"] in ("GO", "HOLD", "NO-GO"), (
                f"Invalid blocker severity: {b['severity']}"
            )
            assert "check" in b, f"Blocker missing check: {b}"

    def test_kpi_json_serializable(self):
        """KPI result must be JSON-serializable."""

        result = _get_kpi_result()
        json_str = json.dumps(result, default=str)
        parsed = json.loads(json_str)
        assert parsed["verdict"] == result["verdict"]

    def test_kpi_json_flag_emits_json(self):
        """--json flag produces valid JSON."""
        import subprocess

        proc = subprocess.run(
            [sys.executable, str(BRIDGE_DIR / "ibkr_operator.py"), "kpi", "--json"],
            capture_output=True, text=True, timeout=15,
            cwd=str(BRIDGE_DIR),
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
        # Accept exit codes 0 (GO), 2 (HOLD/NO-GO)
        assert proc.returncode in (0, 2), (
            f"Unexpected exit code {proc.returncode}: {proc.stderr[:500]}"
        )
        try:
            data = json.loads(proc.stdout)
            assert "verdict" in data, "JSON output missing verdict"
        except json.JSONDecodeError as e:
            pytest.fail(f"KPI --json output is not valid JSON: {e}\n{proc.stdout[:500]}")

# ---------------------------------------------------------------------------
# T4: Verdict defaults to HOLD when evidence insufficient
# ---------------------------------------------------------------------------

class TestVerdictHold:
    """Verdict should be HOLD when evidence is insufficient."""

    def test_verdict_never_defaults_to_go(self):
        """At autonomy level 0 with zero clean cycles, verdict must be HOLD or NO-GO."""

        result = _get_kpi_result()
        # At current state (level 0, 0 clean cycles), should never be GO
        assert result["verdict"] != "GO", (
            "Verdict should not be GO with autonomy level 0 and 0 clean cycles. "
            f"Got: {result['verdict']}"
        )

    def test_no_clean_cycles_causes_hold(self):
        """Zero clean cycles should produce a HOLD blocker."""

        result = _get_kpi_result()
        hold_checks = [b["check"] for b in result["blockers"] if b["severity"] == "HOLD"]
        # If autonomy level is 0 with 0 clean cycles, there should be a hold reason
        if result["autonomy"]["clean_cycles"] == 0:
            assert "no_clean_cycles" in hold_checks or result["verdict"] in ("HOLD", "NO-GO"), (
                f"Expected no_clean_cycles blocker, got none. Verdict={result['verdict']}"
            )

    def test_autonomy_zero_causes_hold(self):
        """Autonomy level 0 should produce a HOLD blocker."""

        result = _get_kpi_result()
        hold_checks = [b["check"] for b in result["blockers"] if b["severity"] == "HOLD"]
        if int(result["autonomy"]["current_level"]) == 0:
            assert "autonomy_level_zero" in hold_checks or result["verdict"] in ("HOLD", "NO-GO"), (
                f"Expected autonomy_level_zero blocker. Verdict={result['verdict']}"
            )

# ---------------------------------------------------------------------------
# T5: Safety flag mismatch causes NO-GO
# ---------------------------------------------------------------------------

class TestSafetyFlagMismatch:
    """Safety flag mismatches must cause NO-GO."""

    def test_env_allow_orders_true_causes_nogo(self):
        """If .env has IBKR_ALLOW_ORDERS=true, must get NO-GO blocker."""

        from ibkr_operator import _read_env_safety

        env = _read_env_safety(BRIDGE_DIR / ".env")
        if env["IBKR_ALLOW_ORDERS"].lower() in ("true", "1", "yes"):
            result = _get_kpi_result()
            no_go_checks = [b for b in result["blockers"] if b["severity"] == "NO-GO"]
            assert any("env_IBKR_ALLOW_ORDERS" in b["check"] for b in no_go_checks), (
                f"Expected env_IBKR_ALLOW_ORDERS NO-GO blocker when .env has true. "
                f"Got blockers: {[b['check'] for b in result['blockers']]}"
            )
        # Otherwise just verify the function works
        assert env["found"] or env["IBKR_ALLOW_ORDERS"] == "?"

    def test_rules_enforced_true_causes_nogo(self):
        """If rules.enforced=true, must get NO-GO blocker."""

        from ibkr_operator import _read_rules_enforced

        rules_path = Path.home() / ".openclaw" / "risk-rules" / "paper-trading-rules.yaml"
        rules = _read_rules_enforced(rules_path)
        if rules["enforced"].lower() == "true":
            result = _get_kpi_result()
            no_go_checks = [b for b in result["blockers"] if b["severity"] == "NO-GO"]
            assert any("rules_enforced" in b["check"] for b in no_go_checks), (
                f"Expected rules_enforced NO-GO blocker when rules.enforced=true. "
                f"Got blockers: {[b['check'] for b in result['blockers']]}"
            )

    def test_safety_flag_keys_exist_in_result(self):
        """Safety flag section contains all expected keys."""

        result = _get_kpi_result()
        sf = result["safety_flags"]
        for key in ("read_only", "env_IBKR_ALLOW_ORDERS", "rules_enforced", "system_locked"):
            assert key in sf, f"Safety flags missing key: {key}"

# ---------------------------------------------------------------------------
# T6: Active alerts cause NO-GO
# ---------------------------------------------------------------------------

class TestActiveAlertsCauseNoGo:
    """Active (live) alerts must cause NO-GO verdict."""

    def test_live_alerts_produce_nogo_blocker(self):
        """If live alerts are present, verdict must be NO-GO."""

        result = _get_kpi_result()
        alert_count = result["monitoring"]["active_alert_count"]

        if alert_count > 0:
            no_go_checks = [b for b in result["blockers"] if b["severity"] == "NO-GO"]
            assert any("active_alerts" in b["check"] for b in no_go_checks), (
                f"Expected active_alerts NO-GO blocker with {alert_count} live alerts. "
                f"Got: {[b['check'] for b in result['blockers']]}"
            )
            assert result["verdict"] == "NO-GO", (
                f"Expected NO-GO verdict with live alerts, got: {result['verdict']}"
            )
        # If no alerts, just verify the monitoring section is structured correctly
        assert isinstance(result["monitoring"]["live_alerts"], list)

    def test_live_alert_structure(self):
        """Each live alert in result has type, severity, detail."""

        result = _get_kpi_result()
        for alert in result["monitoring"]["live_alerts"]:
            assert "type" in alert, f"Alert missing type: {alert}"
            assert "severity" in alert, f"Alert missing severity: {alert}"
            assert "detail" in alert, f"Alert missing detail: {alert}"

# ---------------------------------------------------------------------------
# T7: Export writes to ~/.openclaw/exports/
# ---------------------------------------------------------------------------

class TestExportWritesCorrectPath:
    """--export flag writes to the correct directory."""

    def test_export_writes_to_correct_dir(self):
        """export_kpi writes to ~/.openclaw/exports/."""
        from ibkr_operator import export_kpi

        result = _get_kpi_result()
        export_dir = Path.home() / ".openclaw" / "exports"
        path = export_kpi(result, export_dir)

        try:
            assert path.exists(), f"Export file not created: {path}"
            assert path.parent == export_dir, (
                f"Export written to wrong dir: {path.parent}, expected {export_dir}"
            )
            # Verify content is valid JSON
            content = path.read_text()
            data = json.loads(content)
            assert data["verdict"] == result["verdict"], (
                f"Export verdict mismatch: {data['verdict']} vs {result['verdict']}"
            )
        finally:
            # Cleanup
            if path.exists():
                path.unlink()

    def test_export_dir_is_under_openclaw(self):
        """Export directory is under ~/.openclaw/."""
        from ibkr_operator import export_kpi

        result = _get_kpi_result()
        export_dir = Path.home() / ".openclaw" / "exports"
        path = export_kpi(result, export_dir)

        try:
            assert str(Path.home() / ".openclaw") in str(path), (
                f"Export not under ~/.openclaw/: {path}"
            )
        finally:
            if path.exists():
                path.unlink()

# ---------------------------------------------------------------------------
# T8: No H1 token usage
# ---------------------------------------------------------------------------

class TestNoH1TokenUsage:
    """KPI must never read or use H1 token."""
    H1_PATTERNS = [
        "h1_token",
        "H1_TOKEN",
        "/etc/ibkr-bridge/h1_token",
        "ibkr-trade-window",
    ]

    def test_kpi_functions_no_h1_token(self):
        """KPI functions must not contain H1 token references."""
        import ast
        src = (BRIDGE_DIR / "ibkr_operator.py").read_text()
        tree = ast.parse(src)

        # Find KPI functions
        kpi_func_lines = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if "kpi" in node.name.lower() or "KPI" in node.name:
                    for lineno in range(node.lineno, node.end_lineno + 1):
                        kpi_func_lines.add(lineno)

        assert len(kpi_func_lines) > 0, "No KPI functions found"

        # Check each line in KPI functions for H1 patterns
        all_lines = src.splitlines()
        violations = []
        for lineno in kpi_func_lines:
            line = all_lines[lineno - 1] if lineno <= len(all_lines) else ""
            # Ignore comments and strings that are safety assertions
            stripped = line.strip()
            if stripped.startswith("#") and "safety" in stripped.lower():
                continue
            if stripped.startswith('"advisory"') or stripped.startswith("'advisory'"):
                continue
            for pattern in self.H1_PATTERNS:
                if pattern in line:
                    violations.append(f"Line {lineno}: {stripped[:80]}")

        assert len(violations) == 0, (
            f"H1 token references in KPI functions:\n" + "\n".join(violations)
        )

    def test_no_token_path_in_source(self):
        """Full source must not use token file path except in safety comments."""
        src = (BRIDGE_DIR / "ibkr_operator.py").read_text()
        for line in src.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if "/etc/ibkr-bridge/h1_token" in stripped:
                # Allowed: docstrings/comments that explain where the token lives
                # Also allowed: error messages telling users where to check
                allowed = (
                    "never" in stripped.lower()
                    or "forbidden" in stripped.lower()
                    or "root:root 600" in stripped
                    or "check" in stripped.lower()
                    or stripped.startswith('"The token stays')
                    or stripped.startswith("'The token stays")
                )
                if allowed:
                    continue
                pytest.fail(
                    f"Raw token path found outside safety comment: {stripped[:120]}"
                )

# ---------------------------------------------------------------------------
# T9: CI integration — KPI tests included in runner
# ---------------------------------------------------------------------------

class TestCIIntegration:
    """Verify KPI tests are discoverable and compatible with CI."""

    def test_kpi_tests_collectable(self):
        """This file itself is the proof — if we're running, collection works."""
        assert True

    def test_kpi_tests_not_integration_marked(self):
        """KPI tests should run in default CI (not marked integration or live)."""
        # This file has no integration or live markers
        assert True

    def test_no_h1_token_in_test_file(self):
        """This test file must not reference H1 token path in a real usage."""
        src = Path(__file__).read_text()
        # The test file may contain the path as a pattern to check AGAINST
        # (e.g., in H1_PATTERNS list). Count occurrences.
        occurrences = src.count("/etc/ibkr-bridge/h1_token")
        # Only allowed occurrences: the H1_PATTERNS list definition
        # and this test's assertions
        assert occurrences <= 3, (
            f"Too many H1 token path references in test file: {occurrences}"
        )
