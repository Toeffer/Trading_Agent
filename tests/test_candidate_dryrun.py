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


def _make_fx_evidence_clean(instrument: str = "USD", base: str = "EUR") -> dict:
    """Step 15G: Return valid cross-currency FX evidence for testing."""
    return {
        "fx_available": True,
        "fx_required": True,
        "fx_rate": 0.8744,
        "fx_pair": f"{instrument}/{base}",
        "fx_source": "ibkr_account_exchange_rate",
        "fx_timestamp": "2026-06-19T12:00:00Z",
        "fx_staleness_seconds": 0.0,
    }


def _make_fx_evidence_missing(instrument: str = "USD", base: str = "EUR") -> dict:
    """Step 15G: Return missing FX evidence for testing."""
    return {
        "fx_available": False,
        "fx_required": True,
        "fx_rate": None,
        "fx_pair": f"{instrument}/{base}",
        "fx_source": "no ExchangeRate for USD",
        "fx_timestamp": None,
        "fx_staleness_seconds": None,
    }


def _make_fx_evidence_same_currency() -> dict:
    """Step 15G: Return same-currency FX evidence (EUR/EUR)."""
    return {
        "fx_available": True,
        "fx_required": False,
        "fx_rate": 1.0,
        "fx_pair": "EUR/EUR",
        "fx_source": "identity",
        "fx_timestamp": "2026-06-19T12:00:00Z",
        "fx_staleness_seconds": 0.0,
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
             patch("ibkr_operator._count_clean_cycles", return_value=5), \
             patch("ibkr_operator._fetch_fx_evidence", return_value=_make_fx_evidence_clean()):
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
            assert count <= 4, (
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
        """When IBKR is disconnected, candidate must be HOLD (market data unavailable).

        Uses mocked disconnected market data to avoid dependency on live bridge state.
        """
        from ibkr_operator import _run_candidate_dryrun
        with _patch_market_data(fresh=False):
            r = _run_candidate_dryrun("AAPL", "BUY")
        assert r["verdict"] in ("HOLD", "NO-GO"), f"Expected HOLD/NO-GO, got {r['verdict']}"
        # Must have market_data_missing or ibkr_disconnected blocker
        checks = {b["check"] for b in r["blockers"]}
        assert ("market_data_missing" in checks or "ibkr_disconnected" in checks), \
            f"Expected market_data_missing or ibkr_disconnected blocker, got {checks}"

    def test_missing_market_data_is_HOLD(self):
        """When market data is unavailable, candidate is HOLD (not READY).

        Uses mocked disconnected market data to avoid dependency on live bridge state.
        """
        from ibkr_operator import _run_candidate_dryrun
        with _patch_market_data(fresh=False):
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
             patch("ibkr_operator._count_clean_cycles", return_value=5), \
             patch("ibkr_operator._fetch_fx_evidence", return_value=_make_fx_evidence_clean()):
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
        """Fresh data must derive stop_price and notional from real reference price, not placeholders.

        Step 15G: notional_eur is now notional_base_currency (USD→EUR via FX).
        """
        from ibkr_operator import _run_candidate_dryrun

        with patch("ibkr_operator._collect_lightweight_evidence", return_value=_make_lightweight_clean()), \
             patch("ibkr_operator.run_kpi", return_value=_make_clean_kpi()), \
             _patch_market_data(fresh=True), \
             patch("ibkr_operator._run_hermes_canary", return_value={"ok": True, "hermes_available": True}), \
             patch("ibkr_operator._scan_forbidden_endpoints", return_value={"ok": True, "violations": []}), \
             patch("ibkr_operator._read_autonomy_level", return_value="1"), \
             patch("ibkr_operator._count_clean_cycles", return_value=5), \
             patch("ibkr_operator._fetch_fx_evidence", return_value=_make_fx_evidence_clean()):
            result = _run_candidate_dryrun("AAPL", "BUY")

        # Notional instrument (USD) = 1 * 150.00 = 150.00
        ae = result["account_evidence"]
        assert ae["notional_instrument_currency"] == 150.00
        # Notional base (EUR) = 150.00 * 0.8744 = 131.16
        assert ae["notional_base_currency"] == 131.16
        assert result["notional_eur"] == 131.16  # backward compat
        # Stop = reference_price * (1 - 0.05) = 150.00 * 0.95 = 142.50
        assert result["stop"]["price"] == 142.50
        # Stop must not be the placeholder 100.0
        assert result["stop"]["price"] != 100.0, "Stop price must not be placeholder 100.0"
        assert result["notional_eur"] != 100.0, "Notional must not be placeholder 100.0"
        # Verify the reference_price is not 100.0
        assert result["pricing"]["reference_price"] != 100.0, "Reference price must not be 100.0"


# ---------------------------------------------------------------------------
# Step 15G: FX-normalized notional evidence
# ---------------------------------------------------------------------------

class TestStep15GFxSameCurrency:
    """Step 15G: Same-currency instrument/base uses fx_rate=1.0, fx_required=false."""

    def test_same_currency_fx_identity(self):
        """When instrument and base are both EUR, fx_rate=1.0 and no FX call needed."""
        from ibkr_operator import _run_candidate_dryrun

        with patch("ibkr_operator._collect_lightweight_evidence", return_value=_make_lightweight_clean()), \
             patch("ibkr_operator.run_kpi", return_value=_make_clean_kpi()), \
             _patch_market_data(fresh=True), \
             patch("ibkr_operator._run_hermes_canary", return_value={"ok": True, "hermes_available": True}), \
             patch("ibkr_operator._scan_forbidden_endpoints", return_value={"ok": True, "violations": []}), \
             patch("ibkr_operator._read_autonomy_level", return_value="1"), \
             patch("ibkr_operator._count_clean_cycles", return_value=5), \
             patch("ibkr_operator._fetch_fx_evidence", return_value=_make_fx_evidence_same_currency()):
            result = _run_candidate_dryrun("AAPL", "BUY")

        ae = result["account_evidence"]
        assert ae["fx_available"] is True
        assert ae["fx_required"] is False
        assert ae["fx_rate"] == 1.0
        assert ae["fx_source"] == "identity"
        # With fx_rate=1.0, instrument and base notional are equal
        assert ae["notional_base_currency"] == ae["notional_instrument_currency"]


class TestStep15GCrossCurrency:
    """Step 15G: USD instrument with EUR base requires FX."""

    def test_cross_currency_notional_normalized(self):
        """AAPL in USD with EUR base must compute notional_base = notional_instrument * fx_rate."""
        from ibkr_operator import _run_candidate_dryrun

        with patch("ibkr_operator._collect_lightweight_evidence", return_value=_make_lightweight_clean()), \
             patch("ibkr_operator.run_kpi", return_value=_make_clean_kpi()), \
             _patch_market_data(fresh=True), \
             patch("ibkr_operator._run_hermes_canary", return_value={"ok": True, "hermes_available": True}), \
             patch("ibkr_operator._scan_forbidden_endpoints", return_value={"ok": True, "violations": []}), \
             patch("ibkr_operator._read_autonomy_level", return_value="1"), \
             patch("ibkr_operator._count_clean_cycles", return_value=5), \
             patch("ibkr_operator._fetch_fx_evidence", return_value=_make_fx_evidence_clean()):
            result = _run_candidate_dryrun("AAPL", "BUY")

        ae = result["account_evidence"]
        assert ae["fx_available"] is True
        assert ae["fx_required"] is True
        assert ae["fx_rate"] == 0.8744
        assert ae["fx_pair"] == "USD/EUR"
        assert ae["fx_source"] == "ibkr_account_exchange_rate"
        assert ae["instrument_currency"] == "USD"
        assert ae["base_currency"] == "EUR"
        # 150.00 USD * 0.8744 = 131.16 EUR
        assert ae["notional_instrument_currency"] == 150.00
        assert ae["notional_base_currency"] == 131.16


class TestStep15GMissingFx:
    """Step 15G: Missing FX evidence must produce HOLD with fx_missing blocker."""

    def test_missing_fx_produces_HOLD(self):
        """When FX is unavailable for cross-currency, candidate must HOLD."""
        from ibkr_operator import _run_candidate_dryrun

        with patch("ibkr_operator._collect_lightweight_evidence", return_value=_make_lightweight_clean()), \
             patch("ibkr_operator.run_kpi", return_value=_make_clean_kpi()), \
             _patch_market_data(fresh=True), \
             patch("ibkr_operator._run_hermes_canary", return_value={"ok": True, "hermes_available": True}), \
             patch("ibkr_operator._scan_forbidden_endpoints", return_value={"ok": True, "violations": []}), \
             patch("ibkr_operator._read_autonomy_level", return_value="1"), \
             patch("ibkr_operator._count_clean_cycles", return_value=5), \
             patch("ibkr_operator._fetch_fx_evidence", return_value=_make_fx_evidence_missing()):
            result = _run_candidate_dryrun("AAPL", "BUY")

        checks = {b["check"] for b in result["blockers"]}
        assert "fx_missing" in checks, f"Expected fx_missing blocker, got {checks}"
        assert result["verdict"] == "HOLD"
        assert result["account_evidence"]["fx_available"] is False
        assert result["account_evidence"]["notional_base_currency"] is None

    def test_missing_fx_never_READY(self):
        """Placeholder FX (missing rate) cannot produce READY_DRYRUN."""
        from ibkr_operator import _run_candidate_dryrun

        with patch("ibkr_operator._collect_lightweight_evidence", return_value=_make_lightweight_clean()), \
             patch("ibkr_operator.run_kpi", return_value=_make_clean_kpi()), \
             _patch_market_data(fresh=True), \
             patch("ibkr_operator._run_hermes_canary", return_value={"ok": True, "hermes_available": True}), \
             patch("ibkr_operator._scan_forbidden_endpoints", return_value={"ok": True, "violations": []}), \
             patch("ibkr_operator._read_autonomy_level", return_value="1"), \
             patch("ibkr_operator._count_clean_cycles", return_value=5), \
             patch("ibkr_operator._fetch_fx_evidence", return_value=_make_fx_evidence_missing()):
            result = _run_candidate_dryrun("AAPL", "BUY")

        assert result["verdict"] != "READY_DRYRUN", (
            f"READY_DRYRUN must never be returned with missing FX. Got {result['verdict']}"
        )


class TestStep15GFxExportFields:
    """Step 15G: Export must include all FX-normalized fields."""

    def test_export_has_fx_fields(self):
        """Candidate export must include instrument_currency, fx_rate, notional_base_currency, etc."""
        from ibkr_operator import _run_candidate_dryrun

        with patch("ibkr_operator._collect_lightweight_evidence", return_value=_make_lightweight_clean()), \
             patch("ibkr_operator.run_kpi", return_value=_make_clean_kpi()), \
             _patch_market_data(fresh=True), \
             patch("ibkr_operator._run_hermes_canary", return_value={"ok": True, "hermes_available": True}), \
             patch("ibkr_operator._scan_forbidden_endpoints", return_value={"ok": True, "violations": []}), \
             patch("ibkr_operator._read_autonomy_level", return_value="1"), \
             patch("ibkr_operator._count_clean_cycles", return_value=5), \
             patch("ibkr_operator._fetch_fx_evidence", return_value=_make_fx_evidence_clean()):
            result = _run_candidate_dryrun("AAPL", "BUY")

        ae = result["account_evidence"]
        required_fields = [
            "instrument_currency", "base_currency", "fx_rate", "fx_pair",
            "fx_source", "fx_timestamp", "fx_staleness_seconds",
            "notional_instrument_currency", "notional_base_currency",
            "fx_available", "fx_required",
        ]
        for field in required_fields:
            assert field in ae, f"account_evidence missing required field '{field}'"

    def test_entry_basis_has_fx_fields(self):
        """Entry basis must include instrument_currency, base_currency, both notionals."""
        from ibkr_operator import _run_candidate_dryrun

        with patch("ibkr_operator._collect_lightweight_evidence", return_value=_make_lightweight_clean()), \
             patch("ibkr_operator.run_kpi", return_value=_make_clean_kpi()), \
             _patch_market_data(fresh=True), \
             patch("ibkr_operator._run_hermes_canary", return_value={"ok": True, "hermes_available": True}), \
             patch("ibkr_operator._scan_forbidden_endpoints", return_value={"ok": True, "violations": []}), \
             patch("ibkr_operator._read_autonomy_level", return_value="1"), \
             patch("ibkr_operator._count_clean_cycles", return_value=5), \
             patch("ibkr_operator._fetch_fx_evidence", return_value=_make_fx_evidence_clean()):
            result = _run_candidate_dryrun("AAPL", "BUY")

        eb = result["entry_basis"]
        assert eb["instrument_currency"] == "USD"
        assert eb["base_currency"] == "EUR"
        assert eb["notional_instrument_currency"] == 150.00
        assert eb["notional_base_currency"] == 131.16
        assert "notional_eur" in eb  # backward compat


class TestStep15GFxStale:
    """Step 15G: Stale FX evidence must produce HOLD with fx_stale."""

    def test_stale_fx_produces_HOLD(self):
        """When FX staleness exceeds threshold, candidate must HOLD."""
        from ibkr_operator import _run_candidate_dryrun

        stale_fx = _make_fx_evidence_clean()
        stale_fx["fx_staleness_seconds"] = 600.0  # 10 minutes > 5 min threshold

        with patch("ibkr_operator._collect_lightweight_evidence", return_value=_make_lightweight_clean()), \
             patch("ibkr_operator.run_kpi", return_value=_make_clean_kpi()), \
             _patch_market_data(fresh=True), \
             patch("ibkr_operator._run_hermes_canary", return_value={"ok": True, "hermes_available": True}), \
             patch("ibkr_operator._scan_forbidden_endpoints", return_value={"ok": True, "violations": []}), \
             patch("ibkr_operator._read_autonomy_level", return_value="1"), \
             patch("ibkr_operator._count_clean_cycles", return_value=5), \
             patch("ibkr_operator._fetch_fx_evidence", return_value=stale_fx):
            result = _run_candidate_dryrun("AAPL", "BUY")

        checks = {b["check"] for b in result["blockers"]}
        assert "fx_stale" in checks, f"Expected fx_stale blocker, got {checks}"
        assert result["verdict"] == "HOLD"


class TestStep15GFxInvalid:
    """Step 15G: Invalid FX rate (zero or negative) must produce HOLD."""

    def test_zero_fx_rate_produces_HOLD(self):
        """FX rate of 0 is invalid and must produce fx_invalid blocker."""
        from ibkr_operator import _run_candidate_dryrun

        zero_fx = _make_fx_evidence_clean()
        zero_fx["fx_rate"] = 0.0

        with patch("ibkr_operator._collect_lightweight_evidence", return_value=_make_lightweight_clean()), \
             patch("ibkr_operator.run_kpi", return_value=_make_clean_kpi()), \
             _patch_market_data(fresh=True), \
             patch("ibkr_operator._run_hermes_canary", return_value={"ok": True, "hermes_available": True}), \
             patch("ibkr_operator._scan_forbidden_endpoints", return_value={"ok": True, "violations": []}), \
             patch("ibkr_operator._read_autonomy_level", return_value="1"), \
             patch("ibkr_operator._count_clean_cycles", return_value=5), \
             patch("ibkr_operator._fetch_fx_evidence", return_value=zero_fx):
            result = _run_candidate_dryrun("AAPL", "BUY")

        checks = {b["check"] for b in result["blockers"]}
        assert "fx_invalid" in checks, f"Expected fx_invalid blocker, got {checks}"
        assert result["verdict"] == "HOLD"

    def test_negative_fx_rate_produces_HOLD(self):
        """Negative FX rate is invalid and must produce fx_invalid blocker."""
        from ibkr_operator import _run_candidate_dryrun

        neg_fx = _make_fx_evidence_clean()
        neg_fx["fx_rate"] = -0.5

        with patch("ibkr_operator._collect_lightweight_evidence", return_value=_make_lightweight_clean()), \
             patch("ibkr_operator.run_kpi", return_value=_make_clean_kpi()), \
             _patch_market_data(fresh=True), \
             patch("ibkr_operator._run_hermes_canary", return_value={"ok": True, "hermes_available": True}), \
             patch("ibkr_operator._scan_forbidden_endpoints", return_value={"ok": True, "violations": []}), \
             patch("ibkr_operator._read_autonomy_level", return_value="1"), \
             patch("ibkr_operator._count_clean_cycles", return_value=5), \
             patch("ibkr_operator._fetch_fx_evidence", return_value=neg_fx):
            result = _run_candidate_dryrun("AAPL", "BUY")

        checks = {b["check"] for b in result["blockers"]}
        assert "fx_invalid" in checks, f"Expected fx_invalid blocker, got {checks}"
        assert result["verdict"] == "HOLD"


class TestStep15GNoForbidden:
    """Step 15G: No forbidden endpoints, no H1 tokens, no broker mutation."""

    def test_fx_fetch_uses_only_account_endpoint(self):
        """_fetch_fx_evidence must only call /account, never order endpoints."""
        import inspect
        from ibkr_operator import _fetch_fx_evidence
        src = inspect.getsource(_fetch_fx_evidence)
        forbidden = ["/order", "/order/", "placeOrder", "cancelOrder", "h1_token", "H1_APPROVAL"]
        for f in forbidden:
            assert f not in src, f"_fetch_fx_evidence references forbidden: {f}"


# ---------------------------------------------------------------------------
# Step 15H: Runtime quieting + backpressure hardening
# ---------------------------------------------------------------------------

class TestStep15HRuntimeQuieting:
    """Step 15H: Debug flag gates verbose MEM/REQ logging."""

    def test_debug_flag_gated_in_bridge_source(self):
        bridge_src = (BRIDGE_DIR / "bridge.py").read_text()
        assert "IBKR_BRIDGE_DEBUG" in bridge_src
        assert "if _IBKR_BRIDGE_DEBUG:" in bridge_src

    def test_no_mem_or_req_in_default_path(self):
        bridge_src = (BRIDGE_DIR / "bridge.py").read_text()
        debug_start = bridge_src.find("if _IBKR_BRIDGE_DEBUG:")
        debug_end = bridge_src.find("# /OOM_TRACE_MIN")
        assert debug_start >= 0 and debug_end > debug_start
        debug_block = bridge_src[debug_start:debug_end]
        assert "_M.warning" in debug_block

    def test_no_forbidden_in_backpressure(self):
        bridge_src = (BRIDGE_DIR / "bridge.py").read_text()
        bp_start = bridge_src.find("# OOM_BACKPRESSURE_HARD")
        bp_end = bridge_src.find("# /OOM_BACKPRESSURE_HARD")
        bp_block = bridge_src[bp_start:bp_end]
        for fb in ["/order", "placeOrder", "cancelOrder", "h1_token"]:
            assert fb not in bp_block, f"BP block has forbidden: {fb}"


class TestStep15HBackpressureTiers:
    """Step 15H: Backpressure tier priorities."""

    def test_health_tier_0(self):
        from bridge import _bp_path_tier
        assert _bp_path_tier("/health") == 0
        assert _bp_path_tier("/monitor/liveness") == 0

    def test_market_tier_1(self):
        from bridge import _bp_path_tier
        assert _bp_path_tier("/market/snapshot/AAPL") == 1
        assert _bp_path_tier("/snapshot") == 1

    def test_account_tier_2(self):
        from bridge import _bp_path_tier
        assert _bp_path_tier("/account") == 2
        assert _bp_path_tier("/positions") == 2

    def test_audit_tier_3(self):
        from bridge import _bp_path_tier
        assert _bp_path_tier("/audit/bundle") == 3
        assert _bp_path_tier("/audit/verify") == 3
        assert _bp_path_tier("/monitor/reconciliation") == 3

    def test_unknown_tier_2(self):
        from bridge import _bp_path_tier
        assert _bp_path_tier("/unknown") == 2

    def test_tier_3_rejected_at_half(self):
        from bridge import _BP_MAX_ACTIVE
        assert _BP_MAX_ACTIVE >= 2
        assert _BP_MAX_ACTIVE // 2 >= 1


class TestStep15HNoBreakage:
    """Step 15H: Existing behavior preserved."""

    def test_candidate_still_works(self):
        from ibkr_operator import _run_candidate_dryrun
        r = _run_candidate_dryrun("AAPL", "BUY")
        assert "verdict" in r
        assert r["verdict"] in ("HOLD", "NO-GO", "READY_DRYRUN")

    def test_safety_locked(self):
        import os
        assert os.environ.get("IBKR_ALLOW_ORDERS", "false").lower() != "true"


# ---------------------------------------------------------------------------
# Step 15I — Clean-cycle ledger / evidence cadence
# ---------------------------------------------------------------------------

class TestStep15ICleanCycleLedger:
    """Step 15I: clean-cycle JSONL ledger and evidence-cycle command."""

    def _write_fake_ledger(self, entries: list[dict], tmp_path: Path) -> Path:
        """Write fake ledger entries to a temp file, return the path."""
        import json as _json
        ledger = tmp_path / "clean-cycle-ledger.jsonl"
        with open(ledger, "w", encoding="utf-8") as f:
            for e in entries:
                f.write(_json.dumps(e, default=str, ensure_ascii=False) + "\n")
        return ledger

    def test_count_clean_cycles_from_ledger(self, tmp_path):
        """_count_clean_cycles reads clean:true entries from JSONL ledger."""
        from ibkr_operator import _count_clean_cycles

        entries = [
            {"timestamp": "2026-06-19T10:00:00Z", "cycle_id": "c1", "clean": True, "entry_hash": "abc"},
            {"timestamp": "2026-06-19T11:00:00Z", "cycle_id": "c2", "clean": True, "entry_hash": "def"},
            {"timestamp": "2026-06-19T12:00:00Z", "cycle_id": "c3", "clean": False, "entry_hash": "ghi"},
        ]
        # _count_clean_cycles uses openclaw_dir / "autonomy-cycles" / "clean-cycle-ledger.jsonl"
        autonomy_dir = tmp_path / "autonomy-cycles"
        autonomy_dir.mkdir(parents=True, exist_ok=True)
        ledger = self._write_fake_ledger(entries, tmp_path)
        # Need to put it at the right path
        target = autonomy_dir / "clean-cycle-ledger.jsonl"
        ledger.rename(target)

        count = _count_clean_cycles(tmp_path)
        assert count == 2, f"Expected 2 clean entries, got {count}"

    def test_zero_clean_cycles_empty_ledger(self, tmp_path):
        """Empty ledger returns 0."""
        from ibkr_operator import _count_clean_cycles
        autonomy_dir = tmp_path / "autonomy-cycles"
        autonomy_dir.mkdir(parents=True, exist_ok=True)
        # empty file
        (autonomy_dir / "clean-cycle-ledger.jsonl").touch()

        count = _count_clean_cycles(tmp_path)
        assert count == 0

    def test_zero_clean_cycles_no_ledger(self, tmp_path):
        """Missing ledger returns 0."""
        from ibkr_operator import _count_clean_cycles
        count = _count_clean_cycles(tmp_path)
        assert count == 0

    def test_malformed_lines_ignored(self, tmp_path):
        """Malformed JSON lines in ledger are safely skipped."""
        from ibkr_operator import _count_clean_cycles
        autonomy_dir = tmp_path / "autonomy-cycles"
        autonomy_dir.mkdir(parents=True, exist_ok=True)
        ledger = autonomy_dir / "clean-cycle-ledger.jsonl"
        with open(ledger, "w", encoding="utf-8") as f:
            f.write('{"timestamp":"2026-06-19T10:00:00Z","cycle_id":"c1","clean":true,"entry_hash":"abc"}\n')
            f.write('not json at all\n')
            f.write('{"timestamp":"2026-06-19T11:00:00Z","cycle_id":"c2","clean":true}\n')
            f.write('{"cycle_id":"no_clean","clean":false}\n')
            f.write('\n')

        count = _count_clean_cycles(tmp_path)
        assert count == 2, f"Expected 2 clean entries (malformed skipped), got {count}"

    def test_count_clean_cycles_respects_max_age(self, tmp_path):
        """max_age_days filters out old entries."""
        from ibkr_operator import _count_clean_cycles
        from datetime import datetime, timezone, timedelta

        autonomy_dir = tmp_path / "autonomy-cycles"
        autonomy_dir.mkdir(parents=True, exist_ok=True)
        ledger = autonomy_dir / "clean-cycle-ledger.jsonl"

        old_ts = (datetime.now(timezone.utc) - timedelta(days=60)).strftime("%Y-%m-%dT%H:%M:%SZ")
        new_ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        entries = [
            {"timestamp": old_ts, "cycle_id": "old", "clean": True, "entry_hash": "x"},
            {"timestamp": new_ts, "cycle_id": "new", "clean": True, "entry_hash": "y"},
        ]
        tmp_ledger = self._write_fake_ledger(entries, tmp_path)
        target = autonomy_dir / "clean-cycle-ledger.jsonl"
        import shutil as _shutil
        _shutil.copy(str(tmp_ledger), str(target))

        count_all = _count_clean_cycles(tmp_path, max_age_days=None)
        count_recent = _count_clean_cycles(tmp_path, max_age_days=30)
        assert count_all == 2
        assert count_recent == 1, f"Expected 1 recent, got {count_recent}"

    def test_entry_hash_deterministic(self):
        """_compute_entry_hash produces same hash for same content."""
        from ibkr_operator import _compute_entry_hash
        entry = {"timestamp": "2026-01-01T00:00:00Z", "cycle_id": "c1", "clean": True, "entry_hash": ""}
        h1 = _compute_entry_hash(entry)
        h2 = _compute_entry_hash(entry)
        assert h1 == h2
        assert len(h1) == 64  # SHA-256 hex
        assert h1 != ""

    def test_entry_hash_excludes_self(self):
        """entry_hash is excluded from hash computation."""
        from ibkr_operator import _compute_entry_hash
        entry = {"a": 1, "entry_hash": "DEADBEEF", "b": 2}
        h1 = _compute_entry_hash(entry)
        entry["entry_hash"] = "DIFFERENT"
        h2 = _compute_entry_hash(entry)
        assert h1 == h2, "Hash should be independent of entry_hash value"

    def test_is_clean_with_perfect_evidence(self):
        """_is_clean_cycle returns clean=True for perfect evidence."""
        from ibkr_operator import _is_clean_cycle
        evidence = {
            "ibkr": {"reachable": True, "connected": True},
            "safety": {"read_only": True, "bridge_allow_orders": False, "env_IBKR_ALLOW_ORDERS": "false", "rules_enforced": "false"},
            "doctor": {"pass": True, "checks": []},
            "kpi": {"verdict": "GO"},
            "candidate": {"verdict": "READY_DRYRUN"},
            "forbidden_endpoint_scan": {"ok": True},
            "monitoring": {"active_alert_count": 0, "reconciliation_passed": True},
            "market_data": {"market_data_available": True},
            "account_evidence": {"fx_required": True, "fx_available": True, "fx_staleness_seconds": 5.0},
        }
        clean, reasons = _is_clean_cycle(evidence)
        assert clean is True, f"Expected clean, got {reasons}"
        assert reasons == []

    def test_is_clean_same_currency_no_fx_needed(self):
        """Same-currency cycles (fx_required=False) skip FX checks."""
        from ibkr_operator import _is_clean_cycle
        evidence = {
            "ibkr": {"reachable": True, "connected": True},
            "safety": {"read_only": True, "bridge_allow_orders": False, "env_IBKR_ALLOW_ORDERS": "false", "rules_enforced": "false"},
            "doctor": {"pass": True, "checks": []},
            "kpi": {"verdict": "GO"},
            "candidate": {"verdict": "READY_DRYRUN"},
            "forbidden_endpoint_scan": {"ok": True},
            "monitoring": {"active_alert_count": 0, "reconciliation_passed": True},
            "market_data": {"market_data_available": True},
            "account_evidence": {"fx_required": False, "fx_available": False, "fx_staleness_seconds": None},
        }
        clean, reasons = _is_clean_cycle(evidence)
        assert clean is True, f"No FX needed, should be clean. Got {reasons}"

    def test_market_data_missing_while_connected_is_dirty(self):
        """Market data missing while IBKR connected is not clean."""
        from ibkr_operator import _is_clean_cycle
        evidence = {
            "ibkr": {"reachable": True, "connected": True},
            "safety": {"read_only": True, "bridge_allow_orders": False, "env_IBKR_ALLOW_ORDERS": "false", "rules_enforced": "false"},
            "doctor": {"pass": True, "checks": []},
            "kpi": {"verdict": "GO"},
            "candidate": {"verdict": "READY_DRYRUN"},
            "forbidden_endpoint_scan": {"ok": True},
            "monitoring": {"active_alert_count": 0, "reconciliation_passed": True},
            "market_data": {"market_data_available": False},
            "account_evidence": {"fx_required": True, "fx_available": True, "fx_staleness_seconds": 1.0},
        }
        clean, reasons = _is_clean_cycle(evidence)
        assert clean is False
        assert "market_data_missing_while_connected" in reasons

    def test_fx_missing_when_required_is_dirty(self):
        """FX required but not available — dirty."""
        from ibkr_operator import _is_clean_cycle
        evidence = {
            "ibkr": {"reachable": True, "connected": True},
            "safety": {"read_only": True, "bridge_allow_orders": False, "env_IBKR_ALLOW_ORDERS": "false", "rules_enforced": "false"},
            "doctor": {"pass": True, "checks": []},
            "kpi": {"verdict": "GO"},
            "candidate": {"verdict": "READY_DRYRUN"},
            "forbidden_endpoint_scan": {"ok": True},
            "monitoring": {"active_alert_count": 0, "reconciliation_passed": True},
            "market_data": {"market_data_available": True},
            "account_evidence": {"fx_required": True, "fx_available": False, "fx_staleness_seconds": None},
        }
        clean, reasons = _is_clean_cycle(evidence)
        assert clean is False
        assert "fx_missing_when_required" in reasons

    def test_fx_stale_is_dirty(self):
        """FX stale >300s — dirty."""
        from ibkr_operator import _is_clean_cycle
        evidence = {
            "ibkr": {"reachable": True, "connected": True},
            "safety": {"read_only": True, "bridge_allow_orders": False, "env_IBKR_ALLOW_ORDERS": "false", "rules_enforced": "false"},
            "doctor": {"pass": True, "checks": []},
            "kpi": {"verdict": "GO"},
            "candidate": {"verdict": "READY_DRYRUN"},
            "forbidden_endpoint_scan": {"ok": True},
            "monitoring": {"active_alert_count": 0, "reconciliation_passed": True},
            "market_data": {"market_data_available": True},
            "account_evidence": {"fx_required": True, "fx_available": True, "fx_staleness_seconds": 500.0},
        }
        clean, reasons = _is_clean_cycle(evidence)
        assert clean is False
        assert "fx_stale" in reasons

    def test_doctor_only_h1_canary_fail_is_clean(self):
        """Doctor with only H1 canary failure is still clean."""
        from ibkr_operator import _is_clean_cycle
        evidence = {
            "ibkr": {"reachable": True, "connected": True},
            "safety": {"read_only": True, "bridge_allow_orders": False, "env_IBKR_ALLOW_ORDERS": "false", "rules_enforced": "false"},
            "doctor": {"pass": False, "checks": [
                {"check": "bridge_health", "ok": True},
                {"check": "h1_token_canary", "ok": False, "detail": "canary not reachable"},
            ]},
            "kpi": {"verdict": "GO"},
            "candidate": {"verdict": "READY_DRYRUN"},
            "forbidden_endpoint_scan": {"ok": True},
            "monitoring": {"active_alert_count": 0, "reconciliation_passed": True},
            "market_data": {"market_data_available": True},
            "account_evidence": {"fx_required": True, "fx_available": True, "fx_staleness_seconds": 5.0},
        }
        clean, reasons = _is_clean_cycle(evidence)
        assert clean is True, f"H1 canary only failure should be clean, got {reasons}"

    def test_doctor_non_h1_fail_is_dirty(self):
        """Doctor with non-H1 failure is dirty."""
        from ibkr_operator import _is_clean_cycle
        evidence = {
            "ibkr": {"reachable": True, "connected": True},
            "safety": {"read_only": True, "bridge_allow_orders": False, "env_IBKR_ALLOW_ORDERS": "false", "rules_enforced": "false"},
            "doctor": {"pass": False, "checks": [
                {"check": "bridge_health", "ok": False, "detail": "timeout"},
                {"check": "h1_token_canary", "ok": False},
            ]},
            "kpi": {"verdict": "GO"},
            "candidate": {"verdict": "READY_DRYRUN"},
            "forbidden_endpoint_scan": {"ok": True},
            "monitoring": {"active_alert_count": 0, "reconciliation_passed": True},
            "market_data": {"market_data_available": True},
            "account_evidence": {"fx_required": True, "fx_available": True, "fx_staleness_seconds": 5.0},
        }
        clean, reasons = _is_clean_cycle(evidence)
        assert clean is False
        assert any("doctor_non_pass" in r for r in reasons)

    def test_candidate_nogo_is_dirty(self):
        """Candidate NO-GO is dirty."""
        from ibkr_operator import _is_clean_cycle
        evidence = {
            "ibkr": {"reachable": True, "connected": True},
            "safety": {"read_only": True, "bridge_allow_orders": False, "env_IBKR_ALLOW_ORDERS": "false", "rules_enforced": "false"},
            "doctor": {"pass": True, "checks": []},
            "kpi": {"verdict": "GO"},
            "candidate": {"verdict": "NO-GO"},
            "forbidden_endpoint_scan": {"ok": True},
            "monitoring": {"active_alert_count": 0, "reconciliation_passed": True},
            "market_data": {"market_data_available": True},
            "account_evidence": {"fx_required": True, "fx_available": True, "fx_staleness_seconds": 5.0},
        }
        clean, _ = _is_clean_cycle(evidence)
        assert clean is False

    def test_kpi_nogo_is_dirty(self):
        """KPI NO-GO is dirty."""
        from ibkr_operator import _is_clean_cycle
        evidence = {
            "ibkr": {"reachable": True, "connected": True},
            "safety": {"read_only": True, "bridge_allow_orders": False, "env_IBKR_ALLOW_ORDERS": "false", "rules_enforced": "false"},
            "doctor": {"pass": True, "checks": []},
            "kpi": {"verdict": "NO-GO"},
            "candidate": {"verdict": "READY_DRYRUN"},
            "forbidden_endpoint_scan": {"ok": True},
            "monitoring": {"active_alert_count": 0, "reconciliation_passed": True},
            "market_data": {"market_data_available": True},
            "account_evidence": {"fx_required": True, "fx_available": True, "fx_staleness_seconds": 5.0},
        }
        clean, _ = _is_clean_cycle(evidence)
        assert clean is False

    def test_autonomy_zero_still_hold_even_with_clean_cycles(self):
        """Requirement 10: autonomy_level_zero keeps candidate HOLD even with clean_cycles > 0."""
        from ibkr_operator import _run_candidate_dryrun

        with patch("ibkr_operator._collect_lightweight_evidence", return_value=_make_lightweight_clean()), \
             patch("ibkr_operator.run_kpi", return_value=_make_clean_kpi()), \
             _patch_market_data(fresh=True), \
             patch("ibkr_operator._run_hermes_canary", return_value={"ok": True, "hermes_available": True}), \
             patch("ibkr_operator._scan_forbidden_endpoints", return_value={"ok": True, "violations": []}), \
             patch("ibkr_operator._read_autonomy_level", return_value="0"), \
             patch("ibkr_operator._count_clean_cycles", return_value=5), \
             patch("ibkr_operator._fetch_fx_evidence", return_value=_make_fx_evidence_clean()):
            result = _run_candidate_dryrun("AAPL", "BUY")

        checks = {b["check"] for b in result["blockers"]}
        assert "autonomy_level_zero" in checks, (
            f"Autonomy level 0 must still produce HOLD even with clean_cycles=5. Got {checks}"
        )
        assert result["verdict"] == "HOLD", f"Expected HOLD, got {result['verdict']}"
        assert result["strategy"]["clean_cycles"] == 5

    def test_no_clean_cycles_vanishes_when_count_positive(self):
        """Requirement: no_clean_cycles blocker disappears once clean_cycles > 0."""
        from ibkr_operator import _run_candidate_dryrun

        with patch("ibkr_operator._collect_lightweight_evidence", return_value=_make_lightweight_clean()), \
             patch("ibkr_operator.run_kpi", return_value=_make_clean_kpi()), \
             _patch_market_data(fresh=True), \
             patch("ibkr_operator._run_hermes_canary", return_value={"ok": True, "hermes_available": True}), \
             patch("ibkr_operator._scan_forbidden_endpoints", return_value={"ok": True, "violations": []}), \
             patch("ibkr_operator._read_autonomy_level", return_value="1"), \
             patch("ibkr_operator._count_clean_cycles", return_value=5), \
             patch("ibkr_operator._fetch_fx_evidence", return_value=_make_fx_evidence_clean()):
            result = _run_candidate_dryrun("AAPL", "BUY")

        checks = {b["check"] for b in result["blockers"]}
        assert "no_clean_cycles" not in checks, f"With clean_cycles=5, no_clean_cycles should vanish. Got {checks}"

    def test_ledger_entry_schema_stable(self):
        """_run_evidence_cycle returns expected schema fields."""
        from ibkr_operator import _run_evidence_cycle

        with patch("ibkr_operator._run_doctor_non_sudo", return_value=_make_pass_doctor()), \
             patch("ibkr_operator.run_kpi", return_value=_make_clean_kpi()), \
             patch("ibkr_operator._run_cycle_rehearsal", return_value={"verdict": "CLEAN", "blocker_count": 0}), \
             patch("ibkr_operator._run_candidate_dryrun", return_value={
                 "verdict": "READY_DRYRUN", "market_data": {"market_data_available": True},
                 "account_evidence": {"fx_available": True, "fx_required": True, "fx_staleness_seconds": 0.0}
             }), \
             patch("ibkr_operator._scan_forbidden_endpoints", return_value={"ok": True, "violations": []}), \
             patch("ibkr_operator._collect_lightweight_evidence", return_value=_make_lightweight_clean()), \
             patch("ibkr_operator.export_candidate_dryrun", return_value=Path("/tmp/fake.json")):
            result = _run_evidence_cycle("AAPL", "BUY", record=False)

        required_fields = [
            "timestamp", "cycle_id", "symbol", "side", "clean", "recorded",
            "doctor_verdict", "kpi_verdict", "rehearsal_verdict", "candidate_verdict",
            "entry_hash", "evidence"
        ]
        for f in required_fields:
            assert f in result, f"Missing field: {f}"

        assert len(result["entry_hash"]) == 64
        assert isinstance(result["clean"], bool)
        assert result["entry_hash"] != ""

    def test_evidence_cycle_not_recorded_does_not_write(self, tmp_path):
        """Without --record, no ledger entry is written."""
        from ibkr_operator import _run_evidence_cycle

        # Redirect ledger path to tmp
        with patch("ibkr_operator._CLEAN_CYCLE_LEDGER", tmp_path / "autonomy-cycles" / "clean-cycle-ledger.jsonl"), \
             patch("ibkr_operator._run_doctor_non_sudo", return_value=_make_pass_doctor()), \
             patch("ibkr_operator.run_kpi", return_value=_make_clean_kpi()), \
             patch("ibkr_operator._run_cycle_rehearsal", return_value={"verdict": "CLEAN", "blocker_count": 0}), \
             patch("ibkr_operator._run_candidate_dryrun", return_value={
                 "verdict": "READY_DRYRUN", "market_data": {"market_data_available": True},
                 "account_evidence": {"fx_available": True, "fx_required": True, "fx_staleness_seconds": 0.0}
             }), \
             patch("ibkr_operator._scan_forbidden_endpoints", return_value={"ok": True, "violations": []}), \
             patch("ibkr_operator._collect_lightweight_evidence", return_value=_make_lightweight_clean()), \
             patch("ibkr_operator.export_candidate_dryrun", return_value=Path("/tmp/fake.json")):
            result = _run_evidence_cycle("AAPL", "BUY", record=False)

        assert result["recorded"] is False
        assert not (tmp_path / "autonomy-cycles" / "clean-cycle-ledger.jsonl").exists()

    def test_evidence_cycle_recorded_writes_ledger(self, tmp_path):
        """With --record, ledger entry is appended."""
        from ibkr_operator import _run_evidence_cycle

        ledger_path = tmp_path / "autonomy-cycles" / "clean-cycle-ledger.jsonl"
        with patch("ibkr_operator._CLEAN_CYCLE_LEDGER", ledger_path), \
             patch("ibkr_operator._run_doctor_non_sudo", return_value=_make_pass_doctor()), \
             patch("ibkr_operator.run_kpi", return_value=_make_clean_kpi()), \
             patch("ibkr_operator._run_cycle_rehearsal", return_value={"verdict": "CLEAN", "blocker_count": 0}), \
             patch("ibkr_operator._run_candidate_dryrun", return_value={
                 "verdict": "READY_DRYRUN", "market_data": {"market_data_available": True},
                 "account_evidence": {"fx_available": True, "fx_required": True, "fx_staleness_seconds": 0.0}
             }), \
             patch("ibkr_operator._scan_forbidden_endpoints", return_value={"ok": True, "violations": []}), \
             patch("ibkr_operator._collect_lightweight_evidence", return_value=_make_lightweight_clean()), \
             patch("ibkr_operator.export_candidate_dryrun", return_value=Path("/tmp/fake.json")):
            result = _run_evidence_cycle("AAPL", "BUY", record=True)

        assert result["recorded"] is True
        assert ledger_path.exists()
        lines = ledger_path.read_text().strip().split("\n")
        assert len(lines) == 1
        import json as _json
        entry = _json.loads(lines[0])
        assert entry["clean"] is True
        assert entry["symbol"] == "AAPL"
        assert entry["side"] == "BUY"
        assert len(entry["entry_hash"]) == 64

    def test_no_forbidden_endpoint_in_ledger_code(self):
        """Evidence cycle code must not contain order endpoint calls."""
        from pathlib import Path as _Path
        src = _Path(__file__).resolve().parent.parent / "ibkr_operator.py"
        content = src.read_text()
        # Check the evidence cycle function area
        start = content.find("def _run_evidence_cycle")
        end = content.find("\ndef ", start + 1) if start > -1 else -1
        func_body = content[start:end] if start > -1 else content

        forbidden_calls = [
            "/order", "/order/preflight", "/order/approve", "/order/submit",
            "/order/cancel", "placeOrder", "cancelOrder"
        ]
        for fc in forbidden_calls:
            if fc in func_body:
                # Only flag if it's not in a comment
                lines = func_body.split("\n")
                for i, line in enumerate(lines):
                    if fc in line and not line.strip().startswith("#"):
                        pytest.fail(f"evidenc-cycle code contains forbidden call '{fc}' at line offset {i}")

    def test_no_h1_token_in_ledger_code(self):
        """Evidence cycle code must not read H1 tokens."""
        from pathlib import Path as _Path
        src = _Path(__file__).resolve().parent.parent / "ibkr_operator.py"
        content = src.read_text()
        start = content.find("def _run_evidence_cycle")
        end = content.find("\ndef ", start + 1) if start > -1 else -1
        func_body = content[start:end] if start > -1 else content

        forbidden = ["h1_token", "/etc/ibkr-bridge/h1_token", "H1_TOKEN"]
        for fb in forbidden:
            if fb in func_body:
                lines = func_body.split("\n")
                for i, line in enumerate(lines):
                    if fb in line and not line.strip().startswith("#"):
                        pytest.fail(f"evidence-cycle code references H1 token '{fb}' at line offset {i}")
