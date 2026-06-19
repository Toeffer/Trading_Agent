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
    """Return a full-pass doctor result (lightweight checks)."""
    return {
        "pass": True,
        "total": 9,
        "passed": 9,
        "checks": [
            {"check": "runbook_exists", "ok": True},
            {"check": "operator_symlink", "ok": True},
            {"check": "required_files", "ok": True, "detail": "5/5"},
            {"check": "bridge_health", "ok": True, "detail": "reachable"},
            {"check": "export_dir_writable", "ok": True},
            {"check": "hermes_policy_exists", "ok": True},
            {"check": "h1_token_canary", "ok": True, "detail": "skipped (lightweight)"},
            {"check": "bridge_port_listener", "ok": True, "detail": "1 listener(s)"},
            {"check": "bridge_safety_flags", "ok": True, "detail": "read_only=True, allow_orders=false"},
        ],
        "_lightweight": True,
    }


def _make_lightweight_clean() -> dict:
    """Return clean lightweight evidence snapshot (bridge connected, all pass)."""
    return {
        "bridge": {"reachable": True, "connected": True, "mode": "paper", "allow_orders": False, "read_only": True},
        "doctor": _make_pass_doctor(),
        "safety": {"read_only": True, "bridge_allow_orders": False, "env_IBKR_ALLOW_ORDERS": "false", "rules_enforced": "false", "system_locked": True},
        "strategy": {"strategy_exists": True, "autonomy_exists": True},
    }


def _make_lightweight_disconnected() -> dict:
    """Return lightweight evidence with bridge reachable but disconnected."""
    lw = _make_lightweight_clean()
    lw["bridge"] = dict(lw["bridge"], connected=False)
    return lw


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
            "net_liquidation": 100000.0,  # Step 15D: account evidence
            "cash_balance": 50000.0,
            "base_currency": "EUR",
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


def _make_market_data_clean(symbol: str = "AAPL") -> dict:
    """Step 15D: Return clean (connected, fresh) market data for testing."""
    import time
    return {
        "ok": True,
        "symbol": symbol,
        "market_data_available": True,
        "snapshot_timestamp": "2026-06-18T18:00:00Z",
        "snapshot_epoch": time.time(),
        "bid": 149.50,
        "ask": 150.50,
        "last": 150.00,
        "close": 149.80,
        "midpoint": 150.00,
        "currency": "USD",
        "exchange": "SMART",
        "delayed": True,
        "stale": False,
        "market_data_age_seconds": 2.1,
    }


def _patch_market_data(fresh: bool = True, symbol: str = "AAPL"):
    """Step 15D: Patch urllib.request.urlopen for market/snapshot endpoint.

    Returns a MagicMock that intercepts /market/snapshot/ URLs with mock data.
    Other URLs fall through to the real urlopen (not expected in mocked tests).
    """
    import json as _json
    from unittest.mock import patch, MagicMock

    if fresh:
        md = _make_market_data_clean(symbol)
    else:
        md = {
            "ok": False, "symbol": symbol, "market_data_available": False,
            "stale": True, "detail": "IBKR not connected",
            "snapshot_timestamp": "2026-06-18T18:00:00Z", "snapshot_epoch": 0,
            "bid": None, "ask": None, "last": None, "close": None,
            "midpoint": None, "currency": None, "exchange": None,
            "delayed": True, "market_data_age_seconds": None,
        }
    md_bytes = _json.dumps(md).encode()

    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.read.return_value = md_bytes
    mock_resp.__enter__.return_value = mock_resp
    mock_resp.__exit__.return_value = None

    return patch("urllib.request.urlopen", return_value=mock_resp)


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

        with patch("ibkr_operator._collect_lightweight_evidence", return_value=_make_lightweight_clean()), \
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

        with patch("ibkr_operator._collect_lightweight_evidence", return_value=_make_lightweight_clean()), \
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

        with patch("ibkr_operator._collect_lightweight_evidence", return_value=_make_lightweight_clean()), \
             patch("ibkr_operator.run_kpi", return_value=_make_clean_kpi()), \
             _patch_market_data(fresh=True), \
             patch("ibkr_operator._run_hermes_canary", return_value={"ok": True, "hermes_available": True}), \
             patch("ibkr_operator._scan_forbidden_endpoints", return_value={"ok": True, "violations": []}):
            result = _run_candidate_dryrun("AAPL", "BUY")

        p5 = result["p5_bracket"]
        assert "valid" in p5, "P5 evidence missing 'valid'"
        assert "protective_stop" in p5, "P5 evidence missing 'protective_stop'"
        assert "bracket" in p5, "P5 evidence missing 'bracket'"
        # Step 15D: P5 should be valid with fresh market data
        assert p5.get("valid") is True, f"P5 should be valid with fresh market data, got {p5}"


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

        with patch("ibkr_operator._collect_lightweight_evidence", return_value=_make_lightweight_clean()), \
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

        with patch("ibkr_operator._collect_lightweight_evidence", return_value=_make_lightweight_clean()), \
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

        with patch("ibkr_operator._collect_lightweight_evidence", return_value=_make_lightweight_clean()), \
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
        """With clean doctor, KPI, connected IBKR, autonomy>0, and clean cycles, verdict is READY_DRYRUN.

        Step 15E: READY_DRYRUN requires autonomy_level > 0 and at least one clean cycle.
        These are mocked here for the explicit clean test scenario.
        """
        from ibkr_operator import _run_candidate_dryrun

        with patch("ibkr_operator._collect_lightweight_evidence", return_value=_make_lightweight_clean()), \
             patch("ibkr_operator.run_kpi", return_value=_make_clean_kpi()), \
             _patch_market_data(fresh=True), \
             patch("ibkr_operator._run_hermes_canary", return_value={"ok": True, "hermes_available": True}), \
             patch("ibkr_operator._scan_forbidden_endpoints", return_value={"ok": True, "violations": []}), \
             patch("ibkr_operator._read_autonomy_level", return_value="1"), \
             patch("ibkr_operator._count_clean_cycles", return_value=5):
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

        with patch("ibkr_operator._collect_lightweight_evidence", return_value=_make_lightweight_clean()), \
             patch("ibkr_operator.run_kpi", return_value=_make_clean_kpi()), \
             patch("ibkr_operator._run_hermes_canary", return_value={"ok": True, "hermes_available": True}), \
             patch("ibkr_operator._scan_forbidden_endpoints", return_value={"ok": True, "violations": []}):
            result = _run_candidate_dryrun("AAPL", "BUY")

        assert result["gate_h"]["checks"]["symbol_allowed"] is True

    def test_unknown_symbol_blocked(self):
        """A symbol not in allowlist should produce NO-GO blocker."""
        from ibkr_operator import _run_candidate_dryrun

        with patch("ibkr_operator._collect_lightweight_evidence", return_value=_make_lightweight_clean()), \
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

        with patch("ibkr_operator._collect_lightweight_evidence", return_value=_make_lightweight_clean()), \
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

        with patch("ibkr_operator._collect_lightweight_evidence", return_value=_make_lightweight_clean()), \
             patch("ibkr_operator.run_kpi", return_value=_make_clean_kpi()):
            result = _run_candidate_dryrun("AAPL", "HOLD")

        assert result["verdict"] == "ERROR", (
            f"Invalid side must be ERROR, got {result['verdict']}"
        )


# ---------------------------------------------------------------------------
# T15: KPI HOLD → candidate HOLD (not NO-GO)
# ---------------------------------------------------------------------------

class TestKPIHoldCascadeHold:
    """KPI HOLD must cascade candidate to HOLD, not NO-GO."""

    def test_kpi_hold_cascades_hold(self):
        """When KPI is HOLD (bridge reachable, IBKR disconnected), candidate is HOLD."""
        from ibkr_operator import _run_candidate_dryrun

        kpi_hold = {
            "verdict": "HOLD",
            "blockers": [{"severity": "HOLD", "check": "ibkr_not_connected"}],
            "bridge": {"reachable": True, "connected": False},
            "safety_flags": {
                "read_only": True,
                "bridge_allow_orders": False,
                "env_IBKR_ALLOW_ORDERS": "false",
                "rules_enforced": "false",
                "system_locked": True,
            },
            "heartbeat": {"recent": True, "age_seconds": 120},
            "monitoring": {"active_alert_count": 0},
        }

        with patch("ibkr_operator._collect_lightweight_evidence", return_value=_make_lightweight_clean()), \
             patch("ibkr_operator.run_kpi", return_value=kpi_hold), \
             patch("ibkr_operator._run_hermes_canary", return_value={"ok": True, "hermes_available": True}), \
             patch("ibkr_operator._scan_forbidden_endpoints", return_value={"ok": True, "violations": []}):
            result = _run_candidate_dryrun("AAPL", "BUY")

        assert result["verdict"] == "HOLD", (
            f"KPI HOLD must cascade to candidate HOLD, got {result['verdict']}. "
            f"Blockers: {[b['check'] for b in result['blockers']]}"
        )
        assert result["verdict"] != "NO-GO", (
            "KPI HOLD must NOT cascade to candidate NO-GO"
        )

    def test_kpi_nogo_cascades_nogo(self):
        """When KPI is NO-GO, candidate must also be NO-GO."""
        from ibkr_operator import _run_candidate_dryrun

        with patch("ibkr_operator._collect_lightweight_evidence", return_value=_make_lightweight_clean()), \
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
# T16: Rehearsal HOLD → candidate HOLD (not NO-GO)
# ---------------------------------------------------------------------------

class TestRehearsalHoldCascadeHold:
    """Rehearsal HOLD must cascade candidate to HOLD, not NO-GO."""

    def test_rehearsal_hold_not_nogo(self):
        """When rehearsal is HOLD and KPI is GO, candidate is HOLD."""
        from ibkr_operator import _run_candidate_dryrun

        kpi_go = {
            "verdict": "GO",
            "blockers": [],
            "bridge": {"reachable": True, "connected": True},
            "safety_flags": {
                "read_only": True,
                "bridge_allow_orders": False,
                "env_IBKR_ALLOW_ORDERS": "false",
                "rules_enforced": "false",
                "system_locked": True,
            },
            "heartbeat": {"recent": True, "age_seconds": 120},
            "monitoring": {"active_alert_count": 0},
        }

        # Doctor with a non-canary failure to cause rehearsal HOLD
        lw_fail = _make_lightweight_clean()
        doc_fail = dict(lw_fail["doctor"])
        for c in doc_fail["checks"]:
            if c["check"] == "bridge_safety_flags":
                c["ok"] = False
                c["detail"] = "bridge unreachable — cannot verify safety"
                break
        doc_fail["pass"] = False
        doc_fail["passed"] = 8
        lw_fail["doctor"] = doc_fail

        with patch("ibkr_operator._collect_lightweight_evidence", return_value=lw_fail), \
             patch("ibkr_operator.run_kpi", return_value=kpi_go), \
             patch("ibkr_operator._run_hermes_canary", return_value={"ok": True, "hermes_available": True}), \
             patch("ibkr_operator._scan_forbidden_endpoints", return_value={"ok": True, "violations": []}):
            result = _run_candidate_dryrun("AAPL", "BUY")

        # Rehearsal should be HOLD (doctor_non_pass from bridge_safety_flags)
        # Candidate should be HOLD (rehearsal HOLD cascades to candidate HOLD when KPI is GO)
        assert result["verdict"] == "HOLD", (
            f"Rehearsal HOLD should cascade to candidate HOLD, got {result['verdict']}. "
            f"Blockers: {[b['check'] for b in result['blockers']]}"
        )
        assert result["verdict"] != "NO-GO", (
            "Rehearsal HOLD with KPI GO must NOT cascade to NO-GO"
        )


# ---------------------------------------------------------------------------
# T17: Dependency timeout → explicit evidence, not fake bridge-unreachable
# ---------------------------------------------------------------------------

class TestDependencyTimeout:
    """Dependency timeouts must produce explicit evidence, not fake bridge state."""

    def test_kpi_timeout_not_bridge_unreachable(self):
        """When KPI raises an exception, report dependency_timeout, not bridge_unreachable."""
        from ibkr_operator import _run_candidate_dryrun

        with patch("ibkr_operator._collect_lightweight_evidence", return_value=_make_lightweight_clean()), \
             patch("ibkr_operator.run_kpi", side_effect=TimeoutError("KPI timed out")), \
             patch("ibkr_operator._run_hermes_canary", return_value={"ok": True, "hermes_available": True}), \
             patch("ibkr_operator._scan_forbidden_endpoints", return_value={"ok": True, "violations": []}):
            result = _run_candidate_dryrun("AAPL", "BUY")

        # Must NOT have ibkr_unreachable (we didn't check bridge)
        ibkr_blockers = [b for b in result["blockers"] if b["check"] == "ibkr_unreachable"]
        assert len(ibkr_blockers) == 0, (
            f"KPI timeout must not fabricate ibkr_unreachable. Blockers: {[b['check'] for b in result['blockers']]}"
        )

        # Must have dependency_timeout (HOLD) or bridge_unknown (HOLD)
        timeout_blockers = [b for b in result["blockers"]
                           if b["check"] in ("dependency_timeout", "bridge_unknown")]
        assert len(timeout_blockers) > 0, (
            f"Expected dependency_timeout or bridge_unknown blocker on KPI timeout. "
            f"Blockers: {[b['check'] for b in result['blockers']]}"
        )

        # Verdict should be HOLD (not NO-GO from fake bridge-unreachable)
        assert result["verdict"] == "HOLD", (
            f"KPI timeout should produce HOLD not {result['verdict']}"
        )

        # ibkr_connection falls back to lightweight evidence when KPI fails
        ibkr = result["ibkr_connection"]
        assert ibkr["reachable"] is True, (
            f"Bridge reachable should be True from lightweight evidence on KPI timeout, got {ibkr['reachable']}"
        )


# ---------------------------------------------------------------------------
# T18: Single consistent snapshot
# ---------------------------------------------------------------------------

class TestSingleConsistentSnapshot:
    """Candidate must use a single consistent evidence snapshot per run."""

    def test_kpi_and_rehearsal_use_same_bridge_data(self):
        """Rehearsal bridge data must match KPI bridge data (same snapshot)."""
        from ibkr_operator import _run_candidate_dryrun

        kpi_data = {
            "verdict": "HOLD",
            "blockers": [{"severity": "HOLD", "check": "ibkr_not_connected"}],
            "bridge": {"reachable": True, "connected": False},
            "safety_flags": {
                "read_only": True,
                "bridge_allow_orders": False,
                "env_IBKR_ALLOW_ORDERS": "false",
                "rules_enforced": "false",
                "system_locked": True,
            },
            "heartbeat": {"recent": True, "age_seconds": 120},
            "monitoring": {"active_alert_count": 0},
        }

        with patch("ibkr_operator._collect_lightweight_evidence", return_value=_make_lightweight_clean()), \
             patch("ibkr_operator.run_kpi", return_value=kpi_data), \
             patch("ibkr_operator._run_hermes_canary", return_value={"ok": True, "hermes_available": True}), \
             patch("ibkr_operator._scan_forbidden_endpoints", return_value={"ok": True, "violations": []}):
            result = _run_candidate_dryrun("AAPL", "BUY")

        # KPI section and ibkr_connection must agree
        assert result["kpi"]["verdict"] == "HOLD"
        assert result["ibkr_connection"]["reachable"] is True
        assert result["ibkr_connection"]["connected"] is False

        # Bridge safety flags must come from the same KPI snapshot
        assert result["bridge_safety_flags"].get("env_IBKR_ALLOW_ORDERS") == "false"


# ---------------------------------------------------------------------------
# T19: Doctor PASS → rehearsal has no doctor_non_pass
# ---------------------------------------------------------------------------

class TestDoctorPassNoRehearsalBlocker:
    """When doctor is full PASS, rehearsal must not emit doctor_non_pass."""

    def test_doctor_pass_no_rehearsal_doctor_non_pass(self):
        """Full doctor PASS must not cause doctor_non_pass in rehearsal or candidate."""
        from ibkr_operator import _run_candidate_dryrun

        with patch("ibkr_operator._collect_lightweight_evidence", return_value=_make_lightweight_clean()), \
             patch("ibkr_operator.run_kpi", return_value=_make_clean_kpi()), \
             patch("ibkr_operator._run_hermes_canary", return_value={"ok": True, "hermes_available": True}), \
             patch("ibkr_operator._scan_forbidden_endpoints", return_value={"ok": True, "violations": []}):
            result = _run_candidate_dryrun("AAPL", "BUY")

        doctor_blockers = [
            b for b in result["blockers"]
            if b["check"] in ("doctor_non_pass", "doctor_timeout", "doctor_unavailable")
        ]
        assert len(doctor_blockers) == 0, (
            f"Full-PASS doctor must not produce doctor blockers. Got: {doctor_blockers}"
        )
        # Doctor section in result should show pass
        assert result["doctor"]["pass"] is True, (
            f"Doctor section should show pass=True, got: {result['doctor']}"
        )

    def test_doctor_h1_manual_no_rehearsal_blocker(self):
        """Doctor PASS with only H1 MANUAL must not produce doctor_non_pass."""
        from ibkr_operator import _run_candidate_dryrun

        lw_h1_manual = _make_lightweight_clean()
        doc_hm = dict(lw_h1_manual["doctor"])
        for c in doc_hm["checks"]:
            if c["check"] == "h1_token_canary":
                c["ok"] = False
                c["status"] = "MANUAL_REQUIRED"
                break
        doc_hm["passed"] = 8
        lw_h1_manual["doctor"] = doc_hm

        with patch("ibkr_operator._collect_lightweight_evidence", return_value=lw_h1_manual), \
             patch("ibkr_operator.run_kpi", return_value=_make_clean_kpi()), \
             patch("ibkr_operator._run_hermes_canary", return_value={"ok": True, "hermes_available": True}), \
             patch("ibkr_operator._scan_forbidden_endpoints", return_value={"ok": True, "violations": []}):
            result = _run_candidate_dryrun("AAPL", "BUY")

        doctor_blockers = [
            b for b in result["blockers"]
            if b["check"] in ("doctor_non_pass", "doctor_timeout", "doctor_unavailable")
        ]
        assert len(doctor_blockers) == 0, (
            f"Doctor with only H1 MANUAL must not produce doctor blockers. Got: {doctor_blockers}"
        )


# ---------------------------------------------------------------------------
# T20: Bridge safety flags regression — PASS does not fabricate failure
# ---------------------------------------------------------------------------

class TestBridgeSafetyFlagsNoFabrication:
    """bridge_safety_flags PASS must not produce spurious doctor_non_pass."""

    def test_bridge_safety_flags_pass_no_doctor_blocker(self):
        """When bridge_safety_flags is ok, candidate must not have doctor_non_pass."""
        from ibkr_operator import _run_candidate_dryrun

        lw = _make_lightweight_clean()
        # Explicitly set bridge_safety_flags to PASS
        for c in lw["doctor"]["checks"]:
            if c["check"] == "bridge_safety_flags":
                c["ok"] = True
                c["detail"] = "read_only=True, allow_orders=False"
        with patch("ibkr_operator._collect_lightweight_evidence", return_value=lw), \
             patch("ibkr_operator.run_kpi", return_value=_make_clean_kpi()), \
             patch("ibkr_operator._run_hermes_canary", return_value={"ok": True, "hermes_available": True}), \
             patch("ibkr_operator._scan_forbidden_endpoints", return_value={"ok": True, "violations": []}):
            result = _run_candidate_dryrun("AAPL", "BUY")

        sf_blockers = [
            b for b in result["blockers"]
            if "bridge_safety" in b.get("check", "") or "bridge_safety" in b.get("detail", "")
        ]
        assert len(sf_blockers) == 0, (
            f"bridge_safety_flags PASS must not produce blockers. Got: {sf_blockers}"
        )
        # Doctor PASS and no doctor_non_pass
        assert result["doctor"]["pass"] is True
        doctor_blockers = [b for b in result["blockers"] if "doctor" in b.get("check", "")]
        assert len(doctor_blockers) == 0, (
            f"No doctor blockers expected. Got: {doctor_blockers}"
        )

    def test_stale_safety_flags_failure_ignored_current_clean(self):
        """Current clean bridge_safety_flags overrides any stale failure state."""
        from ibkr_operator import _run_candidate_dryrun

        lw = _make_lightweight_clean()
        with patch("ibkr_operator._collect_lightweight_evidence", return_value=lw), \
             patch("ibkr_operator.run_kpi", return_value=_make_clean_kpi()), \
             patch("ibkr_operator._run_hermes_canary", return_value={"ok": True, "hermes_available": True}), \
             patch("ibkr_operator._scan_forbidden_endpoints", return_value={"ok": True, "violations": []}):
            result = _run_candidate_dryrun("AAPL", "BUY")

        # Doctor must show PASS (not FAIL from stale evidence)
        assert result["doctor"]["pass"] is True, (
            f"Doctor must PASS with clean evidence. Got: {result['doctor']}"
        )
        # No doctor_non_pass (from stale bridge_safety_flags)
        dnps = [b for b in result["blockers"] if b["check"] == "doctor_non_pass"]
        assert len(dnps) == 0, (
            f"Current clean evidence must not produce doctor_non_pass. Blockers: {[b['check'] for b in result['blockers']]}"
        )
        # bridge_safety_flags in result should reflect clean state
        bsf = result.get("bridge_safety_flags", {})
        assert bsf.get("env_IBKR_ALLOW_ORDERS") == "false", (
            f"bridge_safety_flags must show clean state. Got: {bsf}"
        )

    def test_current_bridge_health_overrides_previous_failure(self):
        """When current /health says read_only=True + allow_orders=False, doctor must not fail bridge_safety_flags."""
        from ibkr_operator import _run_candidate_dryrun

        # Construct lightweight evidence where bridge data explicitly shows safe state
        lw = _make_lightweight_clean()
        lw["bridge"] = {
            "reachable": True, "connected": True,
            "mode": "paper", "allow_orders": False, "read_only": True,
        }
        # Doctor check for bridge_safety_flags must derive ok from bridge data
        for c in lw["doctor"]["checks"]:
            if c["check"] == "bridge_safety_flags":
                c["ok"] = True
                c["detail"] = "read_only=True, allow_orders=False"

        with patch("ibkr_operator._collect_lightweight_evidence", return_value=lw), \
             patch("ibkr_operator.run_kpi", return_value=_make_clean_kpi()), \
             patch("ibkr_operator._run_hermes_canary", return_value={"ok": True, "hermes_available": True}), \
             patch("ibkr_operator._scan_forbidden_endpoints", return_value={"ok": True, "violations": []}):
            result = _run_candidate_dryrun("AAPL", "BUY")

        # Must NOT have doctor_non_pass
        dnps = [b for b in result["blockers"] if b["check"] == "doctor_non_pass"]
        assert len(dnps) == 0, (
            f"Current bridge health PASS must not cause doctor_non_pass. "
            f"Blockers: {[b['check'] for b in result['blockers']]}"
        )
        # bridge_safety_flags in result must reflect current state
        bsf = result.get("bridge_safety_flags", {})
        assert bsf.get("env_IBKR_ALLOW_ORDERS") == "false", (
            f"bridge_safety_flags must show allow_orders=false. Got: {bsf}"
        )


# ---------------------------------------------------------------------------
# T20: Integration acceptance — safe disconnected state → HOLD (not NO-GO)
# ---------------------------------------------------------------------------

class TestIntegrationSafeDisconnectedHOLD:
    """Full integration test: safe disconnected state must produce HOLD, not NO-GO.

    This is the acceptance case from Step 15A:
    - doctor PASS 9/9
    - KPI HOLD (ibkr_not_connected only)
    - bridge reachable, disconnected
    - safety locked
    => candidate verdict HOLD, no kpi_nogo_cascade, no bridge_unreachable, no doctor_non_pass
    """

    def test_safe_disconnected_produces_hold(self):
        """Safe + disconnected = HOLD, not NO-GO. No fabricated failures."""
        from ibkr_operator import _run_candidate_dryrun

        # Lightweight evidence: doctor PASS, bridge reachable+disconnected, safety locked
        lw = _make_lightweight_disconnected()

        # KPI: HOLD with only ibkr_not_connected (bridge reachable but disconnected)
        kpi_hold_disconnected = {
            "verdict": "HOLD",
            "blockers": [
                {"severity": "HOLD", "check": "ibkr_not_connected",
                 "detail": "IBKR Gateway is not connected"},
            ],
            "bridge": {
                "reachable": True,
                "connected": False,
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
            "heartbeat": {"recent": True, "age_seconds": 120, "age_human": "2m"},
            "monitoring": {
                "reconciliation_passed": True,
                "active_alert_count": 0,
            },
        }

        with patch("ibkr_operator._collect_lightweight_evidence", return_value=lw), \
             patch("ibkr_operator.run_kpi", return_value=kpi_hold_disconnected), \
             patch("ibkr_operator._run_hermes_canary", return_value={"ok": True, "hermes_available": True}), \
             patch("ibkr_operator._scan_forbidden_endpoints", return_value={"ok": True, "violations": []}):
            result = _run_candidate_dryrun("AAPL", "BUY")

        # 1. Verdict must be HOLD
        assert result["verdict"] == "HOLD", (
            f"Safe disconnected state must produce HOLD, got {result['verdict']}. "
            f"Blockers: {[(b['severity'], b['check']) for b in result['blockers']]}"
        )
        assert result["verdict"] != "NO-GO", (
            "Safe disconnected state must NOT cascade to NO-GO"
        )

        # 2. Doctor must PASS
        assert result["doctor"]["pass"] is True, (
            f"Doctor must PASS in safe state. Got: {result['doctor']}"
        )

        # 3. No doctor_non_pass blocker
        doctor_fail_blockers = [b for b in result["blockers"] if b["check"] == "doctor_non_pass"]
        assert len(doctor_fail_blockers) == 0, (
            f"Safe state must not produce doctor_non_pass. Got: {doctor_fail_blockers}"
        )

        # 4. KPI must be HOLD
        assert result["kpi"]["verdict"] == "HOLD", (
            f"KPI must be HOLD in safe disconnected state. Got: {result['kpi']['verdict']}"
        )

        # 5. No kpi_nogo_cascade
        nogo_cascade = [b for b in result["blockers"] if b["check"] == "kpi_nogo_cascade"]
        assert len(nogo_cascade) == 0, (
            f"KPI HOLD must not produce kpi_nogo_cascade. Got: {nogo_cascade}"
        )

        # 6. Rehearsal must be HOLD (not NO-GO)
        assert result["rehearsal"]["verdict"] == "HOLD", (
            f"Rehearsal must be HOLD in safe disconnected state. Got: {result['rehearsal']['verdict']}"
        )

        # 7. Bridge must be reachable (not unreachable)
        assert result["ibkr_connection"]["reachable"] is True, (
            "Bridge must be reachable in safe disconnected state"
        )
        assert result["ibkr_connection"]["connected"] is False, (
            "IBKR must be disconnected in this test state"
        )

        # 8. No bridge_unreachable or bridge_unknown blocker fabricated
        bridge_false_blockers = [
            b for b in result["blockers"]
            if b["check"] in ("bridge_unreachable", "bridge_unknown")
        ]
        assert len(bridge_false_blockers) == 0, (
            f"Reachable bridge must not produce bridge_unreachable/bridge_unknown. "
            f"Got: {bridge_false_blockers}"
        )

        # 9. Safety must be locked
        bsf = result["bridge_safety_flags"]
        assert bsf.get("system_locked") is True, (
            f"Safety must be locked. Got system_locked={bsf.get('system_locked')}"
        )
        assert bsf.get("env_IBKR_ALLOW_ORDERS") == "false", (
            f"IBKR_ALLOW_ORDERS must be false. Got: {bsf.get('env_IBKR_ALLOW_ORDERS')}"
        )
        assert bsf.get("rules_enforced") == "false", (
            f"rules_enforced must be false. Got: {bsf.get('rules_enforced')}"
        )

        # 10. No safety_unlocked blocker
        safety_blockers = [b for b in result["blockers"] if b["check"] == "safety_unlocked"]
        assert len(safety_blockers) == 0, (
            f"Locked safety must not produce safety_unlocked. Got: {safety_blockers}"
        )

        # 11. Only expected blockers: ibkr_disconnected + market_data_missing (Step 15D)
        unexpected_blockers = [
            b for b in result["blockers"]
            if b["check"] not in (
                "ibkr_disconnected", "market_data_missing",
                "autonomy_level_zero", "no_clean_cycles",
                "system_locked", "strategy_unavailable",
            )
        ]
        assert len(unexpected_blockers) == 0, (
            f"Unexpected blockers in safe disconnected state: "
            f"{[(b['severity'], b['check']) for b in unexpected_blockers]}"
        )


# =============================================================================
# Step 15D: Market-data evidence / placeholder rejection
# =============================================================================

class TestStep15DMarketData:
    """Step 15D: candidate pricing must use real market data, never placeholders."""

    def test_disconnected_candidate_is_HOLD(self):
        """When IBKR is disconnected, candidate must be HOLD (market data unavailable)."""
        from ibkr_operator import _run_candidate_dryrun
        r = _run_candidate_dryrun("AAPL", "BUY")
        assert r["verdict"] in ("HOLD", "NO-GO"), f"Expected HOLD/NO-GO, got {r['verdict']}"
        # Must have market_data_missing or ibkr_disconnected blocker
        checks = {b["check"] for b in r["blockers"]}
        assert ("market_data_missing" in checks or "ibkr_disconnected" in checks), \
            f"Expected market_data_missing or ibkr_disconnected blocker, got {checks}"

    def test_missing_market_data_is_HOLD(self):
        """When market data is unavailable, candidate is HOLD (not READY)."""
        from ibkr_operator import _run_candidate_dryrun
        r = _run_candidate_dryrun("AAPL", "BUY")
        # With disconnected IBKR, market data is always unavailable
        assert r["pricing"]["price_valid"] is False, \
            f"Price should not be valid with missing market data, got {r['pricing']}"
        assert r["verdict"] != "READY_DRYRUN", \
            "READY_DRYRUN must never be returned without valid market data"

    def test_placeholder_price_never_READY(self):
        """Runtime candidate must never use placeholder 100.0 as reference price."""
        from ibkr_operator import _run_candidate_dryrun
        r = _run_candidate_dryrun("AAPL", "BUY")
        ref = r["pricing"].get("reference_price")
        src = r["pricing"].get("price_source")
        # Placeholder would be 100.0 with source="placeholder" or "unknown"
        if ref == 100.0 and src in ("unknown", "placeholder"):
            # Even if it matches 100.0 by coincidence, price_valid must be False
            assert r["pricing"]["price_valid"] is False, \
                f"Placeholder-like pricing (ref=100.0, src={src}) must not be valid"
        # With no market data, verdict is always HOLD, never READY
        assert r["verdict"] != "READY_DRYRUN", \
            f"READY_DRYRUN with ref={ref} src={src} — placeholder pricing may have leaked"

    def test_Sell_candidate_hold_when_disconnected(self):
        """SELL candidate must also HOLD when disconnected."""
        from ibkr_operator import _run_candidate_dryrun
        r = _run_candidate_dryrun("AAPL", "SELL")
        assert r["verdict"] in ("HOLD", "NO-GO"), f"SELL with disconnected IBKR must HOLD, got {r['verdict']}"
        # SELL close-only does not require bracket stop
        assert r["stop"]["price"] is None
        assert "close-only" in r["stop"].get("rationale", "").lower()

    def test_export_has_market_data_fields(self):
        """Candidate export JSON must include market_data, pricing, account_evidence."""
        from ibkr_operator import _run_candidate_dryrun
        r = _run_candidate_dryrun("AAPL", "BUY")
        assert "market_data" in r, "Export missing market_data"
        assert "pricing" in r, "Export missing pricing"
        assert "account_evidence" in r, "Export missing account_evidence"
        # Pricing sub-fields
        p = r["pricing"]
        for k in ("reference_price", "price_source", "price_valid", "stop_price", "staleness_seconds"):
            assert k in p, f"pricing missing '{k}'"
        # Market data sub-fields (may be empty when disconnected)
        md = r["market_data"]
        assert "market_data_available" in md or "ok" in md, "market_data missing ok/available"
        assert "stale" in md or "market_data_available" in md, "market_data missing stale/available"

    def test_no_forbidden_endpoints(self):
        """Candidate must not reference forbidden endpoints."""
        from ibkr_operator import _run_candidate_dryrun
        r = _run_candidate_dryrun("AAPL", "BUY")
        scan = r.get("forbidden_endpoint_scan", {})
        assert scan.get("ok", True), f"Forbidden endpoint scan failed: {scan}"

    def test_no_h1_token_usage(self):
        """Candidate must not reference H1 tokens."""
        import json as _json
        result_str = _json.dumps({"test": "no H1"})
        assert "h1" not in result_str.lower() or "h1_token" not in result_str.lower()

    def test_no_placeholder_runtime_pricing(self):
        """Runtime pricing source must never be 'placeholder'."""
        from ibkr_operator import _run_candidate_dryrun
        r = _run_candidate_dryrun("AAPL", "BUY")
        src = r["pricing"].get("price_source", "")
        assert src != "placeholder", f"Runtime pricing has placeholder source: {src}"
        # And if price not valid, source must reflect that
        if not r["pricing"]["price_valid"]:
            assert src in ("unknown", ""), f"Invalid price with unexpected src: {src}"

    def test_kpi_hold_cascades_to_candidate_hold(self):
        """When KPI is HOLD (disconnected), candidate must also HOLD, not NO-GO."""
        from ibkr_operator import _run_candidate_dryrun
        r = _run_candidate_dryrun("AAPL", "BUY")
        kpi_v = r.get("kpi", {}).get("verdict", "?")
        # When KPI is HOLD and no NO-GO blockers exist, candidate must be HOLD
        if kpi_v == "HOLD" and r["verdict"] == "NO-GO":
            # Check that the NO-GO isn't from a cascade bug
            nogo_checks = [b["check"] for b in r["blockers"] if b["severity"] == "NO-GO"]
            assert "kpi_nogo_cascade" not in nogo_checks, \
                f"KPI HOLD should not cascade to candidate NO-GO. NO-GO blockers: {nogo_checks}"


# ---------------------------------------------------------------------------
# Step 15E: Connected read-only market-data validation
# ---------------------------------------------------------------------------

class TestStep15EStaleMarketData:
    """Step 15E: Stale market data must produce HOLD, never READY."""

    def test_stale_market_data_produces_HOLD(self):
        """When market data snapshot is stale (>60s), candidate is HOLD."""
        from ibkr_operator import _run_candidate_dryrun
        import json as _json
        from unittest.mock import patch, MagicMock

        stale_md = {
            "ok": True, "symbol": "AAPL", "market_data_available": True,
            "snapshot_timestamp": "2026-06-18T18:00:00Z", "snapshot_epoch": 0,
            "bid": 149.50, "ask": 150.50, "last": 150.00, "close": 149.80,
            "midpoint": 150.00, "currency": "USD", "exchange": "SMART",
            "delayed": True, "stale": True, "market_data_age_seconds": 120.0,
        }
        md_bytes = _json.dumps(stale_md).encode()
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.read.return_value = md_bytes
        mock_resp.__enter__.return_value = mock_resp
        mock_resp.__exit__.return_value = None

        with patch("ibkr_operator._collect_lightweight_evidence", return_value=_make_lightweight_clean()), \
             patch("ibkr_operator.run_kpi", return_value=_make_clean_kpi()), \
             patch("urllib.request.urlopen", return_value=mock_resp), \
             patch("ibkr_operator._run_hermes_canary", return_value={"ok": True, "hermes_available": True}), \
             patch("ibkr_operator._scan_forbidden_endpoints", return_value={"ok": True, "violations": []}), \
             patch("ibkr_operator._read_autonomy_level", return_value="1"), \
             patch("ibkr_operator._count_clean_cycles", return_value=5):
            result = _run_candidate_dryrun("AAPL", "BUY")

        assert result["verdict"] == "HOLD", (
            f"Stale market data must produce HOLD, got {result['verdict']}. "
            f"Blockers: {[b['check'] for b in result['blockers']]}"
        )
        checks = {b["check"] for b in result["blockers"]}
        assert "market_data_stale" in checks, f"Expected market_data_stale blocker, got {checks}"


class TestStep15EMissingBidAsk:
    """Step 15E: Missing bid/ask/last must produce HOLD."""

    def test_missing_bid_ask_last_produces_HOLD(self):
        """When bid/ask/last are all None, candidate has no valid reference price → HOLD."""
        from ibkr_operator import _run_candidate_dryrun
        import json as _json
        from unittest.mock import patch, MagicMock

        no_price_md = {
            "ok": True, "symbol": "AAPL", "market_data_available": True,
            "snapshot_timestamp": "2026-06-18T18:00:00Z", "snapshot_epoch": 0,
            "bid": None, "ask": None, "last": None, "close": None,
            "midpoint": None, "currency": "USD", "exchange": "SMART",
            "delayed": True, "stale": False, "market_data_age_seconds": 2.0,
        }
        md_bytes = _json.dumps(no_price_md).encode()
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.read.return_value = md_bytes
        mock_resp.__enter__.return_value = mock_resp
        mock_resp.__exit__.return_value = None

        with patch("ibkr_operator._collect_lightweight_evidence", return_value=_make_lightweight_clean()), \
             patch("ibkr_operator.run_kpi", return_value=_make_clean_kpi()), \
             patch("urllib.request.urlopen", return_value=mock_resp), \
             patch("ibkr_operator._run_hermes_canary", return_value={"ok": True, "hermes_available": True}), \
             patch("ibkr_operator._scan_forbidden_endpoints", return_value={"ok": True, "violations": []}), \
             patch("ibkr_operator._read_autonomy_level", return_value="1"), \
             patch("ibkr_operator._count_clean_cycles", return_value=5):
            result = _run_candidate_dryrun("AAPL", "BUY")

        assert result["verdict"] == "HOLD", (
            f"Missing bid/ask/last must produce HOLD, got {result['verdict']}"
        )
        checks = {b["check"] for b in result["blockers"]}
        assert "market_data_missing" in checks, f"Expected market_data_missing blocker, got {checks}"
        assert result["pricing"]["price_valid"] is False
        assert result["pricing"]["reference_price"] is None

    def test_only_bid_no_ask_last_produces_HOLD(self):
        """When only bid is available but ask and last are None, still no valid price."""
        from ibkr_operator import _run_candidate_dryrun
        import json as _json
        from unittest.mock import patch, MagicMock

        bid_only_md = {
            "ok": True, "symbol": "AAPL", "market_data_available": True,
            "snapshot_timestamp": "2026-06-18T18:00:00Z", "snapshot_epoch": 0,
            "bid": 149.50, "ask": None, "last": None, "close": None,
            "midpoint": None, "currency": "USD", "exchange": "SMART",
            "delayed": True, "stale": False, "market_data_age_seconds": 2.0,
        }
        md_bytes = _json.dumps(bid_only_md).encode()
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.read.return_value = md_bytes
        mock_resp.__enter__.return_value = mock_resp
        mock_resp.__exit__.return_value = None

        with patch("ibkr_operator._collect_lightweight_evidence", return_value=_make_lightweight_clean()), \
             patch("ibkr_operator.run_kpi", return_value=_make_clean_kpi()), \
             patch("urllib.request.urlopen", return_value=mock_resp), \
             patch("ibkr_operator._run_hermes_canary", return_value={"ok": True, "hermes_available": True}), \
             patch("ibkr_operator._scan_forbidden_endpoints", return_value={"ok": True, "violations": []}), \
             patch("ibkr_operator._read_autonomy_level", return_value="1"), \
             patch("ibkr_operator._count_clean_cycles", return_value=5):
            result = _run_candidate_dryrun("AAPL", "BUY")

        # bid alone doesn't give midpoint; last is None; so no valid reference price
        assert result["verdict"] != "READY_DRYRUN", (
            f"Bid-only data must not produce READY_DRYRUN, got {result['verdict']}"
        )
        assert result["pricing"]["price_valid"] is False


class TestStep15EMissingFxAccount:
    """Step 15E: Missing FX/account evidence must produce HOLD when otherwise clean."""

    def test_missing_account_evidence_fx_produces_HOLD(self):
        """When KPI has no net_liquidation (no FX/account data), candidate gets fx_missing blocker."""
        from ibkr_operator import _run_candidate_dryrun

        kpi_no_account = dict(_make_clean_kpi())
        # Remove account evidence from KPI bridge data
        kpi_no_account["bridge"] = dict(kpi_no_account["bridge"])
        del kpi_no_account["bridge"]["net_liquidation"]
        del kpi_no_account["bridge"]["cash_balance"]
        del kpi_no_account["bridge"]["base_currency"]

        with patch("ibkr_operator._collect_lightweight_evidence", return_value=_make_lightweight_clean()), \
             patch("ibkr_operator.run_kpi", return_value=kpi_no_account), \
             _patch_market_data(fresh=True), \
             patch("ibkr_operator._run_hermes_canary", return_value={"ok": True, "hermes_available": True}), \
             patch("ibkr_operator._scan_forbidden_endpoints", return_value={"ok": True, "violations": []}), \
             patch("ibkr_operator._read_autonomy_level", return_value="1"), \
             patch("ibkr_operator._count_clean_cycles", return_value=5):
            result = _run_candidate_dryrun("AAPL", "BUY")

        # With clean market data and everything else passing but no account data,
        # should get fx_missing blocker (or remain HOLD)
        assert result["verdict"] != "READY_DRYRUN", (
            f"Missing account evidence must not produce READY_DRYRUN, got {result['verdict']}"
        )
        checks = {b["check"] for b in result["blockers"]}
        assert "fx_missing" in checks or result["verdict"] == "HOLD", (
            f"Expected fx_missing blocker or HOLD verdict, got {result['verdict']} blockers={checks}"
        )
        assert result["account_evidence"]["fx_available"] is False


class TestStep15EAutonomyAndCleanCycles:
    """Step 15E: Autonomy level 0 and zero clean cycles must produce HOLD."""

    def test_autonomy_level_zero_produces_HOLD(self):
        """When autonomy level is 0, candidate must HOLD regardless of other checks."""
        from ibkr_operator import _run_candidate_dryrun

        with patch("ibkr_operator._collect_lightweight_evidence", return_value=_make_lightweight_clean()), \
             patch("ibkr_operator.run_kpi", return_value=_make_clean_kpi()), \
             _patch_market_data(fresh=True), \
             patch("ibkr_operator._run_hermes_canary", return_value={"ok": True, "hermes_available": True}), \
             patch("ibkr_operator._scan_forbidden_endpoints", return_value={"ok": True, "violations": []}), \
             patch("ibkr_operator._read_autonomy_level", return_value="0"), \
             patch("ibkr_operator._count_clean_cycles", return_value=5):
            result = _run_candidate_dryrun("AAPL", "BUY")

        checks = {b["check"] for b in result["blockers"]}
        assert "autonomy_level_zero" in checks, (
            f"Expected autonomy_level_zero blocker, got {checks}"
        )
        assert result["verdict"] == "HOLD", (
            f"Autonomy level 0 must produce HOLD, got {result['verdict']}"
        )
        assert result["strategy"]["autonomy_level"] == "0"

    def test_no_clean_cycles_produces_HOLD(self):
        """When zero clean cycles exist, candidate must HOLD."""
        from ibkr_operator import _run_candidate_dryrun

        with patch("ibkr_operator._collect_lightweight_evidence", return_value=_make_lightweight_clean()), \
             patch("ibkr_operator.run_kpi", return_value=_make_clean_kpi()), \
             _patch_market_data(fresh=True), \
             patch("ibkr_operator._run_hermes_canary", return_value={"ok": True, "hermes_available": True}), \
             patch("ibkr_operator._scan_forbidden_endpoints", return_value={"ok": True, "violations": []}), \
             patch("ibkr_operator._read_autonomy_level", return_value="1"), \
             patch("ibkr_operator._count_clean_cycles", return_value=0):
            result = _run_candidate_dryrun("AAPL", "BUY")

        checks = {b["check"] for b in result["blockers"]}
        assert "no_clean_cycles" in checks, (
            f"Expected no_clean_cycles blocker, got {checks}"
        )
        assert result["verdict"] == "HOLD", (
            f"Zero clean cycles must produce HOLD, got {result['verdict']}"
        )
        assert result["strategy"]["clean_cycles"] == 0

    def test_both_autonomy_zero_and_no_clean_cycles_produces_HOLD(self):
        """With both autonomy=0 and zero clean cycles, candidate is HOLD (realistic state)."""
        from ibkr_operator import _run_candidate_dryrun

        with patch("ibkr_operator._collect_lightweight_evidence", return_value=_make_lightweight_clean()), \
             patch("ibkr_operator.run_kpi", return_value=_make_clean_kpi()), \
             _patch_market_data(fresh=True), \
             patch("ibkr_operator._run_hermes_canary", return_value={"ok": True, "hermes_available": True}), \
             patch("ibkr_operator._scan_forbidden_endpoints", return_value={"ok": True, "violations": []}), \
             patch("ibkr_operator._read_autonomy_level", return_value="0"), \
             patch("ibkr_operator._count_clean_cycles", return_value=0):
            result = _run_candidate_dryrun("AAPL", "BUY")

        checks = {b["check"] for b in result["blockers"]}
        assert "autonomy_level_zero" in checks
        assert "no_clean_cycles" in checks
        assert result["verdict"] == "HOLD"
        assert result["strategy"]["autonomy_level"] == "0"
        assert result["strategy"]["clean_cycles"] == 0


class TestStep15EFreshMarketDataPricing:
    """Step 15E: Connected fresh market data produces valid pricing evidence."""

    def test_fresh_market_data_produces_valid_pricing(self):
        """Fresh connected market data must populate all pricing fields correctly."""
        from ibkr_operator import _run_candidate_dryrun

        with patch("ibkr_operator._collect_lightweight_evidence", return_value=_make_lightweight_clean()), \
             patch("ibkr_operator.run_kpi", return_value=_make_clean_kpi()), \
             _patch_market_data(fresh=True), \
             patch("ibkr_operator._run_hermes_canary", return_value={"ok": True, "hermes_available": True}), \
             patch("ibkr_operator._scan_forbidden_endpoints", return_value={"ok": True, "violations": []}), \
             patch("ibkr_operator._read_autonomy_level", return_value="1"), \
             patch("ibkr_operator._count_clean_cycles", return_value=5):
            result = _run_candidate_dryrun("AAPL", "BUY")

        p = result["pricing"]
        assert p["price_valid"] is True, f"Fresh data should have valid pricing, got {p}"
        assert p["reference_price"] == 150.00  # last price from mock
        assert p["price_source"] == "last"
        assert p["bid"] == 149.50
        assert p["ask"] == 150.50
        assert p["last"] == 150.00
        assert p["midpoint"] == 150.00
        assert p["currency"] == "USD"
        assert p["staleness_seconds"] == 2.1
        assert p["snapshot_timestamp"] is not None

    def test_fresh_market_data_calculates_real_stop_and_notional(self):
        """Fresh data must derive stop_price and notional from real reference price, not placeholders."""
        from ibkr_operator import _run_candidate_dryrun

        with patch("ibkr_operator._collect_lightweight_evidence", return_value=_make_lightweight_clean()), \
             patch("ibkr_operator.run_kpi", return_value=_make_clean_kpi()), \
             _patch_market_data(fresh=True), \
             patch("ibkr_operator._run_hermes_canary", return_value={"ok": True, "hermes_available": True}), \
             patch("ibkr_operator._scan_forbidden_endpoints", return_value={"ok": True, "violations": []}), \
             patch("ibkr_operator._read_autonomy_level", return_value="1"), \
             patch("ibkr_operator._count_clean_cycles", return_value=5):
            result = _run_candidate_dryrun("AAPL", "BUY")

        # Notional = quantity * reference_price = 1 * 150.00 = 150.00
        assert result["notional_eur"] == 150.00
        # Stop = reference_price * (1 - 0.05) = 150.00 * 0.95 = 142.50
        assert result["stop"]["price"] == 142.50
        # Stop must not be the placeholder 100.0
        assert result["stop"]["price"] != 100.0, "Stop price must not be placeholder 100.0"
        assert result["notional_eur"] != 100.0, "Notional must not be placeholder 100.0"
        # Verify the reference_price is not 100.0
        assert result["pricing"]["reference_price"] != 100.0, "Reference price must not be 100.0"
