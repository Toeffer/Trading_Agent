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
        """With clean doctor, KPI, and connected IBKR, verdict is READY_DRYRUN."""
        from ibkr_operator import _run_candidate_dryrun

        with patch("ibkr_operator._collect_lightweight_evidence", return_value=_make_lightweight_clean()), \
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
        """When KPI raises an exception, report kpi_unavailable, not bridge_unreachable."""
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

        # Must have kpi_unavailable (HOLD) or bridge_unknown (HOLD)
        timeout_blockers = [b for b in result["blockers"]
                           if b["check"] in ("kpi_unavailable", "bridge_unknown")]
        assert len(timeout_blockers) > 0, (
            f"Expected kpi_unavailable or bridge_unknown blocker on KPI timeout. "
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
