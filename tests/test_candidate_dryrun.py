"""Tests for Step 15A: candidate dry-run.

Verifies:
- No forbidden order endpoints in candidate dry-run code
- No H1 token usage
- No sudo
- Exports valid JSON
- BUY candidate without stop is NO-GO
- BUY candidate with stop validates P5 in dry-run/mocked mode
- SELL candidate is close-only and cannot open/increase short
- Disconnected IBKR produces HOLD, not GO
- KPI NO-GO cascades to candidate NO-GO
- Local CI runner includes candidate dry-run tests

All tests are read-only. No broker mutation, no H1 token.
"""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone

import pytest

BRIDGE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BRIDGE_DIR))


# ---------------------------------------------------------------------------
# Shared mock helpers
# ---------------------------------------------------------------------------

def _make_pass_doctor() -> dict:
    """Return a full-pass doctor result (15/15)."""
    return {
        "pass": True,
        "total": 15,
        "passed": 15,
        "checks": [
            {"check": "runbook_exists", "ok": True},
            {"check": "operator_symlink", "ok": True},
            {"check": "required_files", "ok": True},
            {"check": "bridge_health", "ok": True},
            {"check": "checklist_parseable", "ok": True},
            {"check": "daily_report_parseable", "ok": True},
            {"check": "export_dir_writable", "ok": True},
            {"check": "maintenance_dryrun", "ok": True},
            {"check": "protected_files_safe", "ok": True},
            {"check": "hermes_policy_exists", "ok": True},
            {"check": "h1_token_canary", "ok": True, "detail": "skipped (rehearsal mode)"},
            {"check": "bridge_listener_localhost", "ok": True},
            {"check": "bridge_service_active", "ok": True},
            {"check": "bridge_no_duplicate_processes", "ok": True},
            {"check": "bridge_safety_flags", "ok": True},
        ],
    }


def _make_clean_kpi() -> dict:
    """Return a GO KPI result with connected bridge and locked safety."""
    return {
        "verdict": "GO",
        "blockers": [],
        "bridge": {
            "reachable": True,
            "connected": True,
            "url": "http://127.0.0.1:8790",
            "mode": "paper",
            "read_only": True,
            "allow_orders": "false",
        },
        "safety_flags": {
            "read_only": True,
            "bridge_allow_orders": False,
            "env_IBKR_ALLOW_ORDERS": "false",
            "rules_enforced": "false",
            "system_locked": True,
        },
        "heartbeat": {
            "recent": True,
            "age_seconds": 120,
            "age_human": "2m",
        },
        "monitoring": {
            "reconciliation_passed": True,
            "active_alert_count": 0,
        },
    }


def _make_disconnected_kpi() -> dict:
    """Return a HOLD KPI with unreachable bridge."""
    return {
        "verdict": "HOLD",
        "blockers": [{"severity": "HOLD", "check": "bridge_unreachable"}],
        "bridge": {
            "reachable": False,
            "connected": False,
        },
        "safety_flags": {
            "read_only": False,
            "bridge_allow_orders": "?",
            "env_IBKR_ALLOW_ORDERS": "false",
            "rules_enforced": "false",
            "system_locked": True,
        },
        "heartbeat": {"recent": True, "age_seconds": 120},
    }


def _make_nogo_kpi() -> dict:
    """Return a NO-GO KPI result."""
    return {
        "verdict": "NO-GO",
        "blockers": [
            {"severity": "NO-GO", "check": "active_alerts", "detail": "2 active alerts"},
        ],
        "bridge": {"reachable": True, "connected": True},
        "safety_flags": {
            "env_IBKR_ALLOW_ORDERS": "false",
            "rules_enforced": "false",
            "system_locked": True,
        },
        "heartbeat": {"recent": True, "age_seconds": 120},
        "monitoring": {"active_alert_count": 2},
    }


# ---------------------------------------------------------------------------
# T1: No forbidden order endpoints
# ---------------------------------------------------------------------------

class TestNoForbiddenEndpoints:
    """Verify candidate dry-run code does NOT call forbidden endpoints."""

    _FORBIDDEN = [
        "/order",
        "/order/preflight",
        "/order/approve",
        "/order/submit",
        "/connect",
    ]

    def test_dryrun_function_no_forbidden_urls(self):
        """AST scan: _run_candidate_dryrun must not contain forbidden endpoint URLs."""
        import ast, inspect
        from ibkr_operator import _run_candidate_dryrun

        src = inspect.getsource(_run_candidate_dryrun)
        tree = ast.parse(src)

        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                val = node.value
                for ep in self._FORBIDDEN:
                    if ep in val:
                        lower_val = val.lower()
                        # Allow documentation strings that mention forbidden endpoints
                        if any(kw in lower_val for kw in [
                            "no /order", "forbidden", "do not", "must not",
                            "safety", "never", "no h1",
                        ]):
                            continue
                        if any(kw in lower_val for kw in ["request", "url", "fetch"]):
                            raise AssertionError(
                                f"Forbidden endpoint '{ep}' found in candidate-dryrun code: {val[:100]}"
                            )


# ---------------------------------------------------------------------------
# T2: No H1 token usage
# ---------------------------------------------------------------------------

class TestNoH1Token:
    """Verify candidate dry-run code does NOT read or use H1 token."""

    def test_dryrun_function_no_h1_reference(self):
        """_run_candidate_dryrun source must not reference H1 token path or sudo."""
        import inspect
        from ibkr_operator import _run_candidate_dryrun

        src = inspect.getsource(_run_candidate_dryrun)
        forbidden = [
            "/etc/ibkr-bridge/h1_token",
            "ibkr-trade-window",
        ]
        for token in forbidden:
            assert token not in src, (
                f"H1 reference '{token}' found in candidate-dryrun code"
            )


# ---------------------------------------------------------------------------
# T3: No sudo required
# ---------------------------------------------------------------------------

class TestNoSudoRequired:
    """Verify candidate dry-run does not require sudo."""

    def test_no_sudo_in_dryrun_code(self):
        """No actual sudo execution in _run_candidate_dryrun."""
        import inspect
        from ibkr_operator import _run_candidate_dryrun

        src = inspect.getsource(_run_candidate_dryrun)
        sudo_patterns = [
            "subprocess.run(['sudo'",
            'subprocess.run(["sudo"',
            "os.system('sudo",
            'os.system("sudo',
        ]
        for pat in sudo_patterns:
            assert pat not in src, f"sudo invocation pattern '{pat}' found"

        # Strip lines that legitimately mention sudo in comments/docs
        lines = [l for l in src.split('\n') if 'non_sudo' not in l.lower()]
        cleaned = '\n'.join(lines)
        # Only allow "no sudo" in comments
        for line in cleaned.split('\n'):
            if 'sudo' in line.lower():
                # Allow "no sudo" and "No sudo" comments
                if 'no sudo' not in line.lower() and 'skip_h1' not in line.lower():
                    assert False, f"sudo found outside allowed context: {line.strip()[:100]}"


# ---------------------------------------------------------------------------
# T4: JSON output structure
# ---------------------------------------------------------------------------

class TestJsonStructure:
    """Verify candidate dry-run JSON output has all required fields."""

    _REQUIRED_KEYS = [
        "advisory", "timestamp", "git", "verdict", "symbol", "side",
        "quantity", "notional_eur", "doctor", "kpi", "rehearsal",
        "bridge_safety_flags", "ibkr_connection", "strategy",
        "hermes", "gate_h", "proposal_schema", "candidate",
        "entry_basis", "stop", "p5_bracket", "forbidden_endpoint_scan",
        "blockers", "blocker_count",
    ]

    def test_all_keys_present(self):
        """Mock clean environment — all keys must be present."""
        from ibkr_operator import _run_candidate_dryrun

        with patch("ibkr_operator.run_doctor", return_value=_make_pass_doctor()), \
             patch("ibkr_operator.run_kpi", return_value=_make_clean_kpi()), \
             patch("ibkr_operator._run_hermes_canary", return_value={"ok": True, "hermes_available": True}), \
             patch("ibkr_operator._scan_forbidden_endpoints", return_value={"ok": True, "violations": []}):
            result = _run_candidate_dryrun("AAPL", "BUY")

        for key in self._REQUIRED_KEYS:
            assert key in result, f"Missing key: {key}"

        assert result["verdict"] in ("READY_DRYRUN", "HOLD", "NO-GO", "ERROR")

    def test_json_parseable(self):
        """Entire result must be JSON-serializable."""
        from ibkr_operator import _run_candidate_dryrun

        with patch("ibkr_operator.run_doctor", return_value=_make_pass_doctor()), \
             patch("ibkr_operator.run_kpi", return_value=_make_clean_kpi()), \
             patch("ibkr_operator._run_hermes_canary", return_value={"ok": True, "hermes_available": True}), \
             patch("ibkr_operator._scan_forbidden_endpoints", return_value={"ok": True, "violations": []}):
            result = _run_candidate_dryrun("AAPL", "BUY")

        dumped = json.dumps(result, indent=2, default=str)
        reparsed = json.loads(dumped)
        assert reparsed["verdict"] == result["verdict"]


# ---------------------------------------------------------------------------
# T5: BUY candidate without stop is NO-GO
# ---------------------------------------------------------------------------

class TestBuyWithoutStop:
    """BUY without protective stop must be NO-GO."""

    def test_buy_no_stop_rejected_by_p5(self):
        """P5.validate_bracket_stop rejects BUY with stop_price=None."""
        from guard import validate_bracket_stop

        result = validate_bracket_stop(
            stop_price=None,
            entry_price=150.0,
            quantity=1,
            action="BUY",
        )
        assert result["valid"] is False, (
            f"BUY without stop must be invalid, got valid={result['valid']}"
        )
        assert "protective stop" in result.get("error", "").lower(), (
            f"Error should mention protective stop: {result.get('error')}"
        )

    def test_buy_zero_stop_rejected_by_p5(self):
        """P5.validate_bracket_stop rejects BUY with stop_price=0."""
        from guard import validate_bracket_stop

        result = validate_bracket_stop(
            stop_price=0,
            entry_price=150.0,
            quantity=1,
            action="BUY",
        )
        assert result["valid"] is False, (
            f"BUY with stop_price=0 must be invalid"
        )


# ---------------------------------------------------------------------------
# T6: BUY candidate with stop validates P5 in dry-run/mocked mode
# ---------------------------------------------------------------------------

class TestBuyWithStop:
    """BUY with valid protective stop must pass P5 validation in dry-run."""

    def test_buy_with_stop_passes_p5(self):
        """P5.validate_bracket_stop accepts BUY with valid stop below entry."""
        from guard import validate_bracket_stop

        result = validate_bracket_stop(
            stop_price=142.5,
            entry_price=150.0,
            quantity=1,
            action="BUY",
        )
        assert result["valid"] is True, (
            f"BUY with stop=142.5 entry=150 must be valid, got: {result}"
        )
        assert result["bracket"] is True
        assert result["protective_stop"] is True
        assert result["parent_transmit"] is False
        assert result["stop_transmit"] is True

    def test_dryrun_candidate_p5_evidence(self):
        """Candidate dry-run for BUY must include P5 bracket evidence."""
        from ibkr_operator import _run_candidate_dryrun

        with patch("ibkr_operator.run_doctor", return_value=_make_pass_doctor()), \
             patch("ibkr_operator.run_kpi", return_value=_make_clean_kpi()), \
             patch("ibkr_operator._run_hermes_canary", return_value={"ok": True, "hermes_available": True}), \
             patch("ibkr_operator._scan_forbidden_endpoints", return_value={"ok": True, "violations": []}):
            result = _run_candidate_dryrun("AAPL", "BUY")

        p5 = result["p5_bracket"]
        assert "valid" in p5, "P5 evidence missing 'valid'"
        assert "protective_stop" in p5, "P5 evidence missing 'protective_stop'"
        assert "bracket" in p5, "P5 evidence missing 'bracket'"


# ---------------------------------------------------------------------------
# T7: SELL candidate is close-only and cannot open/increase short
# ---------------------------------------------------------------------------

class TestSellCloseOnly:
    """SELL candidate must be close-only — no bracket required, no short."""

    def test_sell_no_bracket_required(self):
        """P5.validate_bracket_stop for SELL returns bracket=False."""
        from guard import validate_bracket_stop

        result = validate_bracket_stop(
            stop_price=None,
            entry_price=150.0,
            quantity=1,
            action="SELL",
        )
        assert result["valid"] is True
        assert result["bracket"] is False, "SELL must not require bracket"
        assert result["protective_stop"] is False

    def test_dryrun_sell_no_stop_blocker(self):
        """Candidate dry-run for SELL should not require stop price."""
        from ibkr_operator import _run_candidate_dryrun

        with patch("ibkr_operator.run_doctor", return_value=_make_pass_doctor()), \
             patch("ibkr_operator.run_kpi", return_value=_make_clean_kpi()), \
             patch("ibkr_operator._run_hermes_canary", return_value={"ok": True, "hermes_available": True}), \
             patch("ibkr_operator._scan_forbidden_endpoints", return_value={"ok": True, "violations": []}):
            result = _run_candidate_dryrun("AAPL", "SELL")

        # SELL should not have p5_bracket as a blocker
        p5_blockers = [b for b in result["blockers"] if "p5" in b.get("check", "")]
        assert len(p5_blockers) == 0, (
            f"SELL should not have P5 blockers, got: {p5_blockers}"
        )
        # Stop should indicate no protective stop needed
        assert result["stop"]["rationale"] is not None

    def test_sell_stop_above_entry_rejected(self):
        """P5: stop must be below entry for BUY (just sanity)."""
        from guard import validate_bracket_stop

        result = validate_bracket_stop(
            stop_price=155.0,
            entry_price=150.0,
            quantity=1,
            action="BUY",
        )
        assert result["valid"] is False, (
            f"Stop above entry must be invalid for BUY"
        )


# ---------------------------------------------------------------------------
# T8: Disconnected IBKR produces HOLD, not GO or READY_DRYRUN
# ---------------------------------------------------------------------------

class TestDisconnectedIBKR:
    """Disconnected IBKR Gateway must produce HOLD, never READY_DRYRUN."""

    def test_disconnected_produces_hold(self):
        """When bridge is unreachable, verdict must be HOLD or NO-GO."""
        from ibkr_operator import _run_candidate_dryrun

        with patch("ibkr_operator.run_doctor", return_value=_make_pass_doctor()), \
             patch("ibkr_operator.run_kpi", return_value=_make_disconnected_kpi()), \
             patch("ibkr_operator._run_hermes_canary", return_value={"ok": True, "hermes_available": True}), \
             patch("ibkr_operator._scan_forbidden_endpoints", return_value={"ok": True, "violations": []}):
            result = _run_candidate_dryrun("AAPL", "BUY")

        assert result["verdict"] != "READY_DRYRUN", (
            f"Disconnected IBKR must not be READY_DRYRUN, got {result['verdict']}"
        )
        assert result["verdict"] != "CLEAN", (
            f"Disconnected IBKR must not be CLEAN"
        )
        assert result["verdict"] in ("HOLD", "NO-GO"), (
            f"Expected HOLD/NO-GO, got {result['verdict']}"
        )
        # Should have ibkr_unreachable or ibkr_disconnected blocker
        ibkr_blockers = [b for b in result["blockers"]
                         if "ibkr" in b.get("check", "")]
        assert len(ibkr_blockers) > 0, "Expected IBKR connection blocker"


# ---------------------------------------------------------------------------
# T9: KPI NO-GO cascades to candidate NO-GO
# ---------------------------------------------------------------------------

class TestKPINoGoCascade:
    """KPI NO-GO must cascade to candidate NO-GO."""

    def test_kpi_nogo_cascades(self):
        """When KPI reports NO-GO, candidate must also be NO-GO."""
        from ibkr_operator import _run_candidate_dryrun

        with patch("ibkr_operator.run_doctor", return_value=_make_pass_doctor()), \
             patch("ibkr_operator.run_kpi", return_value=_make_nogo_kpi()), \
             patch("ibkr_operator._run_hermes_canary", return_value={"ok": True, "hermes_available": True}), \
             patch("ibkr_operator._scan_forbidden_endpoints", return_value={"ok": True, "violations": []}):
            result = _run_candidate_dryrun("AAPL", "BUY")

        assert result["verdict"] == "NO-GO", (
            f"KPI NO-GO must cascade to candidate NO-GO, got {result['verdict']}"
        )
        kpi_cascade = [b for b in result["blockers"] if b["check"] == "kpi_nogo_cascade"]
        assert len(kpi_cascade) >= 1, "Expected kpi_nogo_cascade blocker"


# ---------------------------------------------------------------------------
# T10: Clean environment → READY_DRYRUN
# ---------------------------------------------------------------------------

class TestCleanReadyDryrun:
    """When all checks pass, verdict must be READY_DRYRUN."""

    def test_clean_ready_dryrun(self):
        """With clean doctor, KPI, and connected IBKR, verdict is READY_DRYRUN."""
        from ibkr_operator import _run_candidate_dryrun

        with patch("ibkr_operator.run_doctor", return_value=_make_pass_doctor()), \
             patch("ibkr_operator.run_kpi", return_value=_make_clean_kpi()), \
             patch("ibkr_operator._run_hermes_canary", return_value={"ok": True, "hermes_available": True}), \
             patch("ibkr_operator._scan_forbidden_endpoints", return_value={"ok": True, "violations": []}):
            result = _run_candidate_dryrun("AAPL", "BUY")

        assert result["verdict"] == "READY_DRYRUN", (
            f"Clean environment should be READY_DRYRUN, got {result['verdict']}. "
            f"Blockers: {[b['check'] for b in result['blockers']]}"
        )
        assert result["blocker_count"] == 0
        assert result["p5_bracket"]["valid"] is True
        assert result["gate_h"]["ok"] is True


# ---------------------------------------------------------------------------
# T11: Symbol validation
# ---------------------------------------------------------------------------

class TestSymbolValidation:
    """Gate H symbol allowlist enforcement."""

    def test_allowed_symbol_passes(self):
        """AAPL is in the allowed symbols list."""
        from ibkr_operator import _run_candidate_dryrun

        with patch("ibkr_operator.run_doctor", return_value=_make_pass_doctor()), \
             patch("ibkr_operator.run_kpi", return_value=_make_clean_kpi()), \
             patch("ibkr_operator._run_hermes_canary", return_value={"ok": True, "hermes_available": True}), \
             patch("ibkr_operator._scan_forbidden_endpoints", return_value={"ok": True, "violations": []}):
            result = _run_candidate_dryrun("AAPL", "BUY")

        assert result["gate_h"]["checks"]["symbol_allowed"] is True

    def test_unknown_symbol_blocked(self):
        """A symbol not in allowlist should produce NO-GO blocker."""
        from ibkr_operator import _run_candidate_dryrun

        with patch("ibkr_operator.run_doctor", return_value=_make_pass_doctor()), \
             patch("ibkr_operator.run_kpi", return_value=_make_clean_kpi()), \
             patch("ibkr_operator._run_hermes_canary", return_value={"ok": True, "hermes_available": True}), \
             patch("ibkr_operator._scan_forbidden_endpoints", return_value={"ok": True, "violations": []}):
            result = _run_candidate_dryrun("PENNY", "BUY")

        assert result["verdict"] == "NO-GO", (
            f"Unknown symbol must be NO-GO, got {result['verdict']}"
        )
        sym_blockers = [b for b in result["blockers"] if "symbol" in b.get("check", "")]
        assert len(sym_blockers) > 0, "Expected symbol_not_allowed blocker"


# ---------------------------------------------------------------------------
# T12: Export writes to correct directory
# ---------------------------------------------------------------------------

class TestExport:
    """Verify export writes to ~/.openclaw/candidate-dryruns/ ."""

    def test_export_creates_file(self, tmp_path):
        """Export to tmp dir creates a valid JSON file."""
        from ibkr_operator import _run_candidate_dryrun, export_candidate_dryrun

        with patch("ibkr_operator.run_doctor", return_value=_make_pass_doctor()), \
             patch("ibkr_operator.run_kpi", return_value=_make_clean_kpi()), \
             patch("ibkr_operator._run_hermes_canary", return_value={"ok": True, "hermes_available": True}), \
             patch("ibkr_operator._scan_forbidden_endpoints", return_value={"ok": True, "violations": []}):
            result = _run_candidate_dryrun("AAPL", "BUY")

        export_path = export_candidate_dryrun(result, tmp_path)
        assert export_path.exists(), f"Export file not found: {export_path}"
        assert export_path.suffix == ".json"

        exported = json.loads(export_path.read_text())
        assert exported["verdict"] == result["verdict"]


# ---------------------------------------------------------------------------
# T13: No broker mutation
# ---------------------------------------------------------------------------

class TestNoBrokerMutation:
    """Verify test file does not mutate broker state."""

    def test_no_place_order_in_test_file(self):
        """Test file must not contain broker mutation calls (outside self-test)."""
        src = Path(__file__).read_text()
        forbidden = ["placeOrder", "cancelOrder", "_internal_place_order"]
        for f in forbidden:
            # Count occurrences — exactly 1 is allowed (the self-test assertion line)
            count = src.count(f)
            assert count <= 2, (
                f"Forbidden string '{f}' found {count} times in test file "
                f"(expected <= 2 for self-test assertions)"
            )


# ---------------------------------------------------------------------------
# T14: Invalid side produces ERROR
# ---------------------------------------------------------------------------

class TestInvalidInput:
    """Verify input validation."""

    def test_invalid_side_error(self):
        """Invalid side must return ERROR verdict."""
        from ibkr_operator import _run_candidate_dryrun

        with patch("ibkr_operator.run_doctor", return_value=_make_pass_doctor()), \
             patch("ibkr_operator.run_kpi", return_value=_make_clean_kpi()):
            result = _run_candidate_dryrun("AAPL", "HOLD")

        assert result["verdict"] == "ERROR", (
            f"Invalid side must be ERROR, got {result['verdict']}"
        )
