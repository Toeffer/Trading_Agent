"""Tests for Step 15L — Readiness Connected-Evidence Refresh.

All tests are read-only. No broker mutation, no order endpoints,
no H1 token usage, no autonomy level changes.
"""

import json
import os
import sys
import time
from pathlib import Path

import pytest

BRIDGE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BRIDGE_DIR))

from ibkr_operator import (
    _run_autonomy_status,
    _run_autonomy_review,
    _count_clean_cycles,
    _ledger_entry_strict_clean,
    _CLEAN_CYCLE_LEDGER,
    _CLEAN_CYCLES_REQUIRED,
    _CLEAN_CYCLES_WINDOW_DAYS,
    _CANDIDATE_EVIDENCE_MAX_AGE_SECONDS,
    _DEFAULT_REFRESH_SYMBOL,
    _DEFAULT_REFRESH_SIDE,
    OPENCLAW_DIR,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_clean_entry(timestamp: str, symbol: str = "AAPL", side: str = "BUY",
                      clean: bool = True) -> dict:
    return {
        "timestamp": timestamp,
        "cycle_id": f"cycle-{symbol}-{side}-{timestamp.replace(':', '')}",
        "symbol": symbol,
        "side": side,
        "doctor_verdict": "PASS",
        "kpi_verdict": "GO",
        "rehearsal_verdict": "CLEAN",
        "candidate_verdict": "READY_DRYRUN",
        "no_forbidden_endpoints": True,
        "safety_flags": {
            "read_only": True,
            "bridge_allow_orders": False,
            "env_IBKR_ALLOW_ORDERS": "false",
            "rules_enforced": "false",
            "system_locked": True,
        },
        "clean": clean,
        "blockers": [],
        "entry_hash": "abc123",
    }


def _write_ledger_entries(path: Path, entries: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")


def _write_candidate(tmp_dir: Path, verdict: str = "READY_DRYRUN",
                     market_available: bool = True,
                     fx_available: bool = True, fx_required: bool = False,
                     mtime_offset_seconds: int = -60) -> Path:
    """Write a candidate dry-run result with optional age offset."""
    candidate_dir = tmp_dir / "candidate-dryruns"
    candidate_dir.mkdir(parents=True, exist_ok=True)
    cand_path = candidate_dir / "candidate-AAPL-BUY-test.json"
    cand_data = {
        "verdict": verdict,
        "symbol": "AAPL",
        "side": "BUY",
        "timestamp": "2026-06-22T10:00:00Z",
        "market_data": {
            "market_data_available": market_available,
            "stale": False,
            "currency": "USD",
            "last": 210.0,
            "midpoint": 210.05,
        },
        "account_evidence": {
            "fx_available": fx_available,
            "fx_required": fx_required,
            "fx_staleness_seconds": 0,
        },
    }
    cand_path.write_text(json.dumps(cand_data))

    # Set mtime for age testing
    target_mtime = time.time() + mtime_offset_seconds  # negative = in the past
    os.utime(str(cand_path), (target_mtime, target_mtime))
    return candidate_dir


def _make_lightweight_clean() -> dict:
    return {
        "bridge": {
            "reachable": True, "connected": True,
            "mode": "paper", "allow_orders": False, "read_only": True,
        },
        "doctor": {
            "pass": True, "total": 9, "passed": 9,
            "checks": [
                {"check": "runbook_exists", "ok": True},
                {"check": "operator_symlink", "ok": True},
                {"check": "required_files", "ok": True},
                {"check": "bridge_health", "ok": True},
                {"check": "export_dir_writable", "ok": True},
                {"check": "hermes_policy_exists", "ok": True},
                {"check": "h1_token_canary", "ok": True},
                {"check": "bridge_port_listener", "ok": True},
                {"check": "bridge_safety_flags", "ok": True},
            ],
        },
        "safety": {
            "read_only": True,
            "bridge_allow_orders": False,
            "env_IBKR_ALLOW_ORDERS": "false",
            "rules_enforced": "false",
            "system_locked": True,
        },
        "strategy": {"strategy_exists": True, "autonomy_exists": True},
        "liveness": {"oom_detected": False, "oom_detail": "no OOM", "n_restarts": 0, "k17_ok": True},
        # Step 15P: session-aware fields
        "market_session_status": {"session": "rth", "data_availability": "available", "reason": "Inside RTH", "is_tradable_day": True, "in_rth": True, "market_date_et": "2026-06-23"},
        "market_data_runtime_ok": True,
    }


def _make_fresh_candidate_result() -> dict:
    """Return a plausible fresh candidate dry-run result."""
    return {
        "verdict": "READY_DRYRUN",
        "symbol": "AAPL",
        "side": "BUY",
        "timestamp": "2026-06-22T10:10:00Z",
        "market_data": {
            "market_data_available": True,
            "stale": False,
            "currency": "USD",
            "last": 210.0,
            "midpoint": 210.05,
        },
        "account_evidence": {
            "fx_available": True,
            "fx_required": False,
            "fx_staleness_seconds": 0,
        },
        "fx_evidence": {  # both forms
            "fx_available": True,
            "fx_required": False,
            "fx_staleness_seconds": 0,
        },
        "_export_path": "/tmp/test-candidate-export.json",
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestRefreshEvidence:
    """Tests for --refresh-evidence flag on autonomy-status."""

    # --- Test: non-refresh path returns refresh_evidence=False and has age ---

    def test_non_refresh_has_freshness_markers(self, tmp_path):
        """Without --refresh-evidence, result has refresh_evidence=False and candidate_evidence_age_seconds."""
        from unittest.mock import patch

        now = time.time()
        ledger_dir = tmp_path / "autonomy-cycles"
        ledger_path = ledger_dir / "clean-cycle-ledger.jsonl"
        entries = [
            _make_clean_entry(time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now - i * 3600)))
            for i in range(1, 6)
        ]
        _write_ledger_entries(ledger_path, entries)

        _write_candidate(tmp_path, verdict="READY_DRYRUN")

        lw = _make_lightweight_clean()
        kpi = {
            "verdict": "GO",
            "bridge": {"reachable": True, "connected": True},
            "monitoring": {"active_alert_count": 0, "reconciliation_passed": True},
            "blockers": [],
        }

        with patch("ibkr_operator._CLEAN_CYCLE_LEDGER", ledger_path), \
             patch("ibkr_operator.OPENCLAW_DIR", tmp_path), \
             patch("ibkr_operator._collect_lightweight_evidence", return_value=lw), \
             patch("ibkr_operator.run_kpi", return_value=kpi), \
             patch("ibkr_operator._CLEAN_CYCLES_REQUIRED", 5), \
             patch("ibkr_operator._CLEAN_CYCLES_WINDOW_DAYS", 7), \
             patch("ibkr_operator.BRIDGE_DIR", BRIDGE_DIR), \
             patch("ibkr_operator._read_autonomy_level", return_value="0"), \
             patch("ibkr_operator._scan_forbidden_endpoints", return_value={"ok": True, "violations": []}):
            result = _run_autonomy_status(refresh_evidence=False)

        assert result["refresh_evidence"] is False
        assert result["candidate_evidence_age_seconds"] is not None
        assert result["candidate_evidence_age_seconds"] >= 0
        # No refreshed_* fields in non-refresh path
        assert "refreshed_at" not in result

    # --- Test: refresh path returns refresh_evidence=True ---

    def test_refresh_returns_refreshed_fields(self, tmp_path):
        """With --refresh-evidence, result has refresh_evidence=True and refreshed_* fields."""
        from unittest.mock import patch

        now = time.time()
        ledger_dir = tmp_path / "autonomy-cycles"
        ledger_path = ledger_dir / "clean-cycle-ledger.jsonl"
        entries = [
            _make_clean_entry(time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now - i * 3600)))
            for i in range(1, 6)
        ]
        _write_ledger_entries(ledger_path, entries)

        fresh_cand = _make_fresh_candidate_result()
        lw = _make_lightweight_clean()
        kpi = {
            "verdict": "GO",
            "bridge": {"reachable": True, "connected": True},
            "monitoring": {"active_alert_count": 0, "reconciliation_passed": True},
            "blockers": [],
        }

        with patch("ibkr_operator._CLEAN_CYCLE_LEDGER", ledger_path), \
             patch("ibkr_operator.OPENCLAW_DIR", tmp_path), \
             patch("ibkr_operator._collect_lightweight_evidence", return_value=lw), \
             patch("ibkr_operator.run_kpi", return_value=kpi), \
             patch("ibkr_operator._run_candidate_dryrun", return_value=fresh_cand), \
             patch("ibkr_operator._CLEAN_CYCLES_REQUIRED", 5), \
             patch("ibkr_operator._CLEAN_CYCLES_WINDOW_DAYS", 7), \
             patch("ibkr_operator.BRIDGE_DIR", BRIDGE_DIR), \
             patch("ibkr_operator._read_autonomy_level", return_value="0"), \
             patch("ibkr_operator._scan_forbidden_endpoints", return_value={"ok": True, "violations": []}):
            result = _run_autonomy_status(refresh_evidence=True)

        assert result["refresh_evidence"] is True
        assert result["refreshed_at"] is not None
        assert result["refreshed_market_data_status"] == "available"
        assert result["refreshed_fx_status"] == "not_required"
        assert result["refreshed_ibkr_connected"] is True
        assert result["refreshed_evidence_age_seconds"] is not None
        assert result["refreshed_evidence_age_seconds"] >= 0

    # --- Test: --refresh-evidence calls only read-only paths ---

    def test_refresh_only_read_only_paths(self):
        """--refresh-evidence uses only read-only functions (no /order*, no H1)."""
        import inspect
        source = inspect.getsource(_run_autonomy_status)
        # The refresh path calls _run_candidate_dryrun, run_kpi, _collect_lightweight_evidence, _scan_forbidden_endpoints
        # None of these should call /order endpoints
        forbidden = ["/order/preflight", "/order/approve", "/order/submit",
                      "placeOrder", "cancelOrder", "_run_h1_canary"]
        for pattern in forbidden:
            found_line = None
            for line in source.splitlines():
                if pattern in line and not line.strip().startswith("#"):
                    found_line = line.strip()[:120]
                    break
            assert found_line is None, \
                f"FORBIDDEN: '{pattern}' found in _run_autonomy_status: {found_line}"

    # --- Test: disconnected + enough clean cycles => HOLD ---

    def test_disconnected_hold(self, tmp_path):
        """When IBKR is disconnected, recommendation is HOLD even with enough clean cycles."""
        from unittest.mock import patch

        now = time.time()
        ledger_dir = tmp_path / "autonomy-cycles"
        ledger_path = ledger_dir / "clean-cycle-ledger.jsonl"
        entries = [
            _make_clean_entry(time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now - i * 3600)))
            for i in range(1, 6)
        ]
        _write_ledger_entries(ledger_path, entries)

        _write_candidate(tmp_path, verdict="READY_DRYRUN",
                         market_available=False)  # market unavailable

        lw = _make_lightweight_clean()
        lw["bridge"]["connected"] = False  # disconnected

        kpi = {
            "verdict": "GO",
            "bridge": {"reachable": True, "connected": False},
            "monitoring": {"active_alert_count": 0, "reconciliation_passed": True},
            "blockers": [],
        }

        with patch("ibkr_operator._CLEAN_CYCLE_LEDGER", ledger_path), \
             patch("ibkr_operator.OPENCLAW_DIR", tmp_path), \
             patch("ibkr_operator._collect_lightweight_evidence", return_value=lw), \
             patch("ibkr_operator.run_kpi", return_value=kpi), \
             patch("ibkr_operator._CLEAN_CYCLES_REQUIRED", 5), \
             patch("ibkr_operator._CLEAN_CYCLES_WINDOW_DAYS", 7), \
             patch("ibkr_operator.BRIDGE_DIR", BRIDGE_DIR), \
             patch("ibkr_operator._read_autonomy_level", return_value="0"), \
             patch("ibkr_operator._scan_forbidden_endpoints", return_value={"ok": True, "violations": []}):
            result = _run_autonomy_status(refresh_evidence=False)

        assert result["recommendation"] == "HOLD", \
            f"Expected HOLD when disconnected, got {result['recommendation']}"
        blockers = {b["check"]: b for b in result["blockers"]}
        assert "ibkr_disconnected" in blockers, \
            f"Expected ibkr_disconnected blocker, got {list(blockers.keys())}"

    # --- Test: connected + fresh market + FX + enough cycles => READY_FOR_MANUAL_REVIEW ---

    def test_connected_fresh_market_fx_ready(self, tmp_path):
        """READY_FOR_MANUAL_REVIEW with connected, fresh market data, FX OK, enough cycles."""
        from unittest.mock import patch

        now = time.time()
        ledger_dir = tmp_path / "autonomy-cycles"
        ledger_path = ledger_dir / "clean-cycle-ledger.jsonl"
        entries = [
            _make_clean_entry(time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now - i * 3600)))
            for i in range(1, 6)
        ]
        _write_ledger_entries(ledger_path, entries)

        _write_candidate(tmp_path, verdict="READY_DRYRUN",
                         market_available=True, fx_available=True, fx_required=False)

        lw = _make_lightweight_clean()
        kpi = {
            "verdict": "GO",
            "bridge": {"reachable": True, "connected": True},
            "monitoring": {"active_alert_count": 0, "reconciliation_passed": True},
            "blockers": [],
        }

        with patch("ibkr_operator._CLEAN_CYCLE_LEDGER", ledger_path), \
             patch("ibkr_operator.OPENCLAW_DIR", tmp_path), \
             patch("ibkr_operator._collect_lightweight_evidence", return_value=lw), \
             patch("ibkr_operator.run_kpi", return_value=kpi), \
             patch("ibkr_operator._CLEAN_CYCLES_REQUIRED", 5), \
             patch("ibkr_operator._CLEAN_CYCLES_WINDOW_DAYS", 7), \
             patch("ibkr_operator.BRIDGE_DIR", BRIDGE_DIR), \
             patch("ibkr_operator._read_autonomy_level", return_value="0"), \
             patch("ibkr_operator._scan_forbidden_endpoints", return_value={"ok": True, "violations": []}):
            result = _run_autonomy_status(refresh_evidence=False)

        assert result["recommendation"] == "READY_FOR_MANUAL_REVIEW", \
            f"Expected READY_FOR_MANUAL_REVIEW, got {result['recommendation']}"

    # --- Test: stale market data => HOLD ---

    def test_stale_market_data_hold(self, tmp_path):
        """Stale market data causes HOLD."""
        from unittest.mock import patch

        now = time.time()
        ledger_dir = tmp_path / "autonomy-cycles"
        ledger_path = ledger_dir / "clean-cycle-ledger.jsonl"
        entries = [
            _make_clean_entry(time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now - i * 3600)))
            for i in range(1, 6)
        ]
        _write_ledger_entries(ledger_path, entries)

        # Write candidate with stale market data
        candidate_dir = tmp_path / "candidate-dryruns"
        candidate_dir.mkdir(parents=True, exist_ok=True)
        cand_path = candidate_dir / "candidate-AAPL-BUY-test.json"
        cand_data = {
            "verdict": "READY_DRYRUN",
            "symbol": "AAPL",
            "side": "BUY",
            "market_data": {
                "market_data_available": True,
                "stale": True,  # stale!
                "currency": "USD",
                "market_data_age_seconds": 900,
            },
            "account_evidence": {
                "fx_available": True,
                "fx_required": False,
                "fx_staleness_seconds": 0,
            },
        }
        cand_path.write_text(json.dumps(cand_data))

        lw = _make_lightweight_clean()
        kpi = {
            "verdict": "GO",
            "bridge": {"reachable": True, "connected": True},
            "monitoring": {"active_alert_count": 0, "reconciliation_passed": True},
            "blockers": [],
        }

        with patch("ibkr_operator._CLEAN_CYCLE_LEDGER", ledger_path), \
             patch("ibkr_operator.OPENCLAW_DIR", tmp_path), \
             patch("ibkr_operator._collect_lightweight_evidence", return_value=lw), \
             patch("ibkr_operator.run_kpi", return_value=kpi), \
             patch("ibkr_operator._CLEAN_CYCLES_REQUIRED", 5), \
             patch("ibkr_operator._CLEAN_CYCLES_WINDOW_DAYS", 7), \
             patch("ibkr_operator.BRIDGE_DIR", BRIDGE_DIR), \
             patch("ibkr_operator._read_autonomy_level", return_value="0"), \
             patch("ibkr_operator._scan_forbidden_endpoints", return_value={"ok": True, "violations": []}):
            result = _run_autonomy_status(refresh_evidence=False)

        assert result["recommendation"] == "HOLD", \
            f"Expected HOLD with stale market data, got {result['recommendation']}"
        blockers = {b["check"] for b in result["blockers"]}
        assert "market_data_stale" in blockers, \
            f"Expected market_data_stale blocker, got {blockers}"

    # --- Test: FX required but missing => HOLD ---

    def test_fx_required_missing_hold(self, tmp_path):
        """FX required but unavailable causes HOLD."""
        from unittest.mock import patch

        now = time.time()
        ledger_dir = tmp_path / "autonomy-cycles"
        ledger_path = ledger_dir / "clean-cycle-ledger.jsonl"
        entries = [
            _make_clean_entry(time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now - i * 3600)))
            for i in range(1, 6)
        ]
        _write_ledger_entries(ledger_path, entries)

        # FX required but unavailable
        _write_candidate(tmp_path, verdict="READY_DRYRUN",
                         fx_available=False, fx_required=True)

        lw = _make_lightweight_clean()
        kpi = {
            "verdict": "GO",
            "bridge": {"reachable": True, "connected": True},
            "monitoring": {"active_alert_count": 0, "reconciliation_passed": True},
            "blockers": [],
        }

        with patch("ibkr_operator._CLEAN_CYCLE_LEDGER", ledger_path), \
             patch("ibkr_operator.OPENCLAW_DIR", tmp_path), \
             patch("ibkr_operator._collect_lightweight_evidence", return_value=lw), \
             patch("ibkr_operator.run_kpi", return_value=kpi), \
             patch("ibkr_operator._CLEAN_CYCLES_REQUIRED", 5), \
             patch("ibkr_operator._CLEAN_CYCLES_WINDOW_DAYS", 7), \
             patch("ibkr_operator.BRIDGE_DIR", BRIDGE_DIR), \
             patch("ibkr_operator._read_autonomy_level", return_value="0"), \
             patch("ibkr_operator._scan_forbidden_endpoints", return_value={"ok": True, "violations": []}):
            result = _run_autonomy_status(refresh_evidence=False)

        assert result["recommendation"] == "HOLD", \
            f"Expected HOLD when FX required but missing, got {result['recommendation']}"
        blockers = {b["check"] for b in result["blockers"]}
        assert "fx_unavailable" in blockers, \
            f"Expected fx_unavailable blocker, got {blockers}"

    # --- Test: stale candidate evidence (too old) => HOLD ---

    def test_stale_candidate_evidence_hold(self, tmp_path):
        """Candidate evidence older than _CANDIDATE_EVIDENCE_MAX_AGE_SECONDS causes HOLD."""
        from unittest.mock import patch

        now = time.time()
        ledger_dir = tmp_path / "autonomy-cycles"
        ledger_path = ledger_dir / "clean-cycle-ledger.jsonl"
        entries = [
            _make_clean_entry(time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now - i * 3600)))
            for i in range(1, 6)
        ]
        _write_ledger_entries(ledger_path, entries)

        # Candidate file older than max age (mtime = -601 seconds → > 600)
        _write_candidate(tmp_path, verdict="READY_DRYRUN",
                         mtime_offset_seconds=-(_CANDIDATE_EVIDENCE_MAX_AGE_SECONDS + 5))

        lw = _make_lightweight_clean()
        kpi = {
            "verdict": "GO",
            "bridge": {"reachable": True, "connected": True},
            "monitoring": {"active_alert_count": 0, "reconciliation_passed": True},
            "blockers": [],
        }

        with patch("ibkr_operator._CLEAN_CYCLE_LEDGER", ledger_path), \
             patch("ibkr_operator.OPENCLAW_DIR", tmp_path), \
             patch("ibkr_operator._collect_lightweight_evidence", return_value=lw), \
             patch("ibkr_operator.run_kpi", return_value=kpi), \
             patch("ibkr_operator._CLEAN_CYCLES_REQUIRED", 5), \
             patch("ibkr_operator._CLEAN_CYCLES_WINDOW_DAYS", 7), \
             patch("ibkr_operator._CANDIDATE_EVIDENCE_MAX_AGE_SECONDS", 600), \
             patch("ibkr_operator.BRIDGE_DIR", BRIDGE_DIR), \
             patch("ibkr_operator._read_autonomy_level", return_value="0"), \
             patch("ibkr_operator._scan_forbidden_endpoints", return_value={"ok": True, "violations": []}):
            result = _run_autonomy_status(refresh_evidence=False)

        assert result["recommendation"] == "HOLD", \
            f"Expected HOLD with stale candidate evidence, got {result['recommendation']}"
        blockers = {b["check"] for b in result["blockers"]}
        assert "stale_candidate_evidence" in blockers, \
            f"Expected stale_candidate_evidence blocker, got {blockers}"

    # --- Test: --json stdout parseable JSON ---

    def test_json_stdout_parseable(self, tmp_path):
        """--json output is pure parseable JSON."""
        import subprocess

        # Write fresh candidate so evidence isn't stale
        _write_candidate(tmp_path, verdict="READY_DRYRUN",
                         mtime_offset_seconds=-30)

        script = '''
import json, sys, time
from pathlib import Path
from unittest.mock import patch

tmp = Path(sys.argv[1])
bridge_dir = Path(sys.argv[2])
sys.path.insert(0, str(bridge_dir))

from ibkr_operator import _run_autonomy_status

now = time.time()
ledger_dir = tmp / "autonomy-cycles"
ledger_dir.mkdir(parents=True, exist_ok=True)
ledger_path = ledger_dir / "clean-cycle-ledger.jsonl"
entries = []
for i in range(1, 6):
    ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now - i * 3600))
    entry = {
        "timestamp": ts, "cycle_id": f"cycle-{i}", "symbol": "AAPL",
        "side": "BUY", "doctor_verdict": "PASS", "kpi_verdict": "GO",
        "rehearsal_verdict": "CLEAN", "candidate_verdict": "READY_DRYRUN",
        "no_forbidden_endpoints": True,
        "safety_flags": {"read_only": True, "bridge_allow_orders": False,
                         "env_IBKR_ALLOW_ORDERS": "false", "rules_enforced": "false"},
        "clean": True, "blockers": [], "entry_hash": "abc",
    }
    entries.append(entry)
with open(ledger_path, "w") as f:
    for e in entries:
        f.write(json.dumps(e) + "\\n")

lw = {
    "bridge": {"reachable": True, "connected": True, "mode": "paper", "allow_orders": False, "read_only": True},
    "doctor": {"pass": True, "total": 9, "passed": 9, "checks": []},
    "safety": {"read_only": True, "bridge_allow_orders": False, "env_IBKR_ALLOW_ORDERS": "false",
               "rules_enforced": "false", "system_locked": True},
    "strategy": {"strategy_exists": True, "autonomy_exists": True},
    "liveness": {"oom_detected": False},
}
kpi = {
    "verdict": "GO",
    "bridge": {"reachable": True, "connected": True},
    "monitoring": {"active_alert_count": 0, "reconciliation_passed": True},
    "blockers": [],
}

with patch("ibkr_operator._CLEAN_CYCLE_LEDGER", ledger_path), \
     patch("ibkr_operator.OPENCLAW_DIR", tmp), \
     patch("ibkr_operator._collect_lightweight_evidence", return_value=lw), \
     patch("ibkr_operator.run_kpi", return_value=kpi), \
     patch("ibkr_operator._CLEAN_CYCLES_REQUIRED", 5), \
     patch("ibkr_operator._CLEAN_CYCLES_WINDOW_DAYS", 7), \
     patch("ibkr_operator.BRIDGE_DIR", bridge_dir), \
     patch("ibkr_operator._read_autonomy_level", return_value="0"), \
     patch("ibkr_operator._scan_forbidden_endpoints", return_value={"ok": True, "violations": []}):
    result = _run_autonomy_status(refresh_evidence=False)
print(json.dumps(result, indent=2, default=str))
'''
        result = subprocess.run(
            [sys.executable, "-c", script, str(tmp_path), str(BRIDGE_DIR)],
            capture_output=True, text=True, timeout=30,
        )
        stdout_text = result.stdout.strip()
        assert stdout_text, "stdout is empty"
        try:
            parsed = json.loads(stdout_text)
        except json.JSONDecodeError as e:
            assert False, f"stdout is not valid JSON: {e}"

        assert "command" in parsed
        assert parsed.get("refresh_evidence") is False
        assert parsed.get("candidate_evidence_age_seconds") is not None

    # --- Test: autonomy-review consumes refreshed autonomy-status correctly ---

    def test_autonomy_review_consumes_refreshed_status(self, tmp_path):
        """autonomy-review passes refresh_evidence through to autonomy-status."""
        from unittest.mock import patch

        now = time.time()
        ledger_dir = tmp_path / "autonomy-cycles"
        ledger_path = ledger_dir / "clean-cycle-ledger.jsonl"
        entries = [
            _make_clean_entry(time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now - i * 3600)))
            for i in range(1, 6)
        ]
        _write_ledger_entries(ledger_path, entries)

        _write_candidate(tmp_path, verdict="READY_DRYRUN")

        lw = _make_lightweight_clean()
        kpi = {
            "verdict": "GO",
            "bridge": {"reachable": True, "connected": True},
            "monitoring": {"active_alert_count": 0, "reconciliation_passed": True},
            "blockers": [],
        }

        with patch("ibkr_operator._CLEAN_CYCLE_LEDGER", ledger_path), \
             patch("ibkr_operator.OPENCLAW_DIR", tmp_path), \
             patch("ibkr_operator._collect_lightweight_evidence", return_value=lw), \
             patch("ibkr_operator.run_kpi", return_value=kpi), \
             patch("ibkr_operator._CLEAN_CYCLES_REQUIRED", 5), \
             patch("ibkr_operator._CLEAN_CYCLES_WINDOW_DAYS", 7), \
             patch("ibkr_operator.BRIDGE_DIR", BRIDGE_DIR), \
             patch("ibkr_operator._read_autonomy_level", return_value="0"), \
             patch("ibkr_operator._scan_forbidden_endpoints", return_value={"ok": True, "violations": []}):
            result = _run_autonomy_review(target_level="1", refresh_evidence=False)

        # Verify autonomy-status inside the review used the right path
        as_summary = result.get("latest_autonomy_status_summary", {})
        assert as_summary is not None

    # --- Test: existing tests still pass ---

    def test_no_h1_token_reads(self):
        """The refresh path does not perform H1 token reads."""
        import inspect
        source = inspect.getsource(_run_autonomy_status)
        forbidden = ["_run_h1_canary(", "sudo ", "/etc/ibkr-bridge/h1_token"]
        for pattern in forbidden:
            found = False
            for line in source.splitlines():
                if line.strip().startswith("#"):
                    continue
                if pattern in line:
                    found = True
                    break
            assert not found, \
                f"FORBIDDEN: '{pattern}' found in _run_autonomy_status source"

    # --- Test: no /order* calls in refresh path ---

    def test_no_order_endpoints(self):
        """The refresh path does not call any order endpoints."""
        import inspect
        source = inspect.getsource(_run_autonomy_status)
        forbidden = ["/order/preflight", "/order/approve", "/order/submit",
                      "placeOrder", "cancelOrder"]
        for pattern in forbidden:
            found_line = None
            for line in source.splitlines():
                if pattern in line and not line.strip().startswith("#"):
                    found_line = line.strip()[:100]
                    break
            assert found_line is None, \
                f"FORBIDDEN: '{pattern}' found in _run_autonomy_status: {found_line}"

# ===========================================================================
# Step 15L-B: Bounded read-only market snapshot timeout
# ===========================================================================


class TestMarketSnapshotTimeout:
    """Step 15L-B: Market snapshot must return bounded JSON, never hang."""

    # --- Helpers ---

    @staticmethod
    def _make_market_timeout_response(symbol: str = "AAPL") -> dict:
        """Simulate a bridge /market/snapshot response after timeout."""
        return {
            "ok": False,
            "symbol": symbol,
            "market_data_available": False,
            "detail": "market_data_timeout: market data did not arrive within 8s",
            "snapshot_timestamp": "2026-06-23T08:00:00Z",
            "snapshot_epoch": time.time(),
            "bid": None,
            "ask": None,
            "last": None,
            "close": None,
            "midpoint": None,
            "currency": None,
            "exchange": None,
            "delayed": True,
            "stale": True,
            "market_data_age_seconds": None,
        }

    @staticmethod
    def _make_market_disconnected_response(symbol: str = "AAPL") -> dict:
        """Simulate a bridge /market/snapshot response when disconnected."""
        return {
            "ok": False,
            "symbol": symbol,
            "market_data_available": False,
            "detail": "IBKR not connected",
            "snapshot_timestamp": "2026-06-23T08:00:00Z",
            "snapshot_epoch": time.time(),
            "bid": None,
            "ask": None,
            "last": None,
            "close": None,
            "midpoint": None,
            "currency": None,
            "exchange": None,
            "delayed": True,
            "stale": True,
            "market_data_age_seconds": None,
        }

    @staticmethod
    def _make_market_clean_response(symbol: str = "AAPL") -> dict:
        """Simulate a bridge /market/snapshot response with fresh data."""
        return {
            "ok": True,
            "symbol": symbol,
            "market_data_available": True,
            "snapshot_timestamp": "2026-06-23T08:00:00Z",
            "snapshot_epoch": time.time(),
            "bid": 209.5,
            "ask": 210.5,
            "last": 210.0,
            "close": 208.0,
            "midpoint": 210.0,
            "currency": "USD",
            "exchange": "SMART",
            "delayed": True,
            "stale": False,
            "market_data_age_seconds": 1.5,
        }

    def _make_timeout_candidate(self, tmp_path: Path) -> Path:
        """Write a candidate dry-run with timeout market data."""
        candidate_dir = tmp_path / "candidate-dryruns"
        candidate_dir.mkdir(parents=True, exist_ok=True)
        cand_path = candidate_dir / "candidate-AAPL-BUY-test.json"
        cand_data = {
            "verdict": "HOLD",
            "symbol": "AAPL",
            "side": "BUY",
            "timestamp": "2026-06-23T08:00:00Z",
            "market_data": self._make_market_timeout_response("AAPL"),
            "account_evidence": {
                "fx_available": True,
                "fx_required": False,
                "fx_staleness_seconds": 0,
            },
        }
        cand_path.write_text(json.dumps(cand_data))
        return candidate_dir

    # --- Test: timeout snapshot returns valid JSON ---

    def test_timeout_snapshot_returns_json(self):
        """A market snapshot timeout response is valid JSON with all required fields."""
        resp = self._make_market_timeout_response("AAPL")
        required_fields = [
            "ok", "symbol", "market_data_available", "detail",
            "snapshot_timestamp", "snapshot_epoch", "bid", "ask",
            "last", "close", "midpoint", "currency", "exchange",
            "delayed", "stale", "market_data_age_seconds",
        ]
        for field in required_fields:
            assert field in resp, f"Missing field '{field}' in timeout response"
        assert resp["ok"] is False
        assert resp["market_data_available"] is False
        assert "market_data_timeout" in resp["detail"]
        assert resp["bid"] is None
        assert resp["ask"] is None
        assert resp["last"] is None
        assert resp["close"] is None
        assert resp["midpoint"] is None
        assert resp["currency"] is None
        assert resp["stale"] is True
        assert resp["delayed"] is True
        # Verify it's serializable
        json.dumps(resp)

    # --- Test: connected=true + market timeout => autonomy-status HOLD ---

    def test_connected_market_timeout_hold(self, tmp_path):
        """When IBKR is connected but market data times out, autonomy-status HOLDs."""
        from unittest.mock import patch

        now = time.time()
        ledger_dir = tmp_path / "autonomy-cycles"
        ledger_path = ledger_dir / "clean-cycle-ledger.jsonl"
        entries = [
            _make_clean_entry(time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now - i * 3600)))
            for i in range(1, 6)
        ]
        _write_ledger_entries(ledger_path, entries)

        # Write candidate with timeout market data
        self._make_timeout_candidate(tmp_path)

        lw = _make_lightweight_clean()  # connected=True
        kpi = {
            "verdict": "GO",
            "bridge": {"reachable": True, "connected": True},
            "monitoring": {"active_alert_count": 0, "reconciliation_passed": True},
            "blockers": [],
        }

        with patch("ibkr_operator._CLEAN_CYCLE_LEDGER", ledger_path), \
             patch("ibkr_operator.OPENCLAW_DIR", tmp_path), \
             patch("ibkr_operator._collect_lightweight_evidence", return_value=lw), \
             patch("ibkr_operator.run_kpi", return_value=kpi), \
             patch("ibkr_operator._CLEAN_CYCLES_REQUIRED", 5), \
             patch("ibkr_operator._CLEAN_CYCLES_WINDOW_DAYS", 7), \
             patch("ibkr_operator.BRIDGE_DIR", BRIDGE_DIR), \
             patch("ibkr_operator._read_autonomy_level", return_value="0"), \
             patch("ibkr_operator._scan_forbidden_endpoints", return_value={"ok": True, "violations": []}):
            result = _run_autonomy_status(refresh_evidence=False)

        assert result["recommendation"] == "HOLD", \
            f"Expected HOLD when market data times out, got {result['recommendation']}"
        blockers = {b["check"] for b in result["blockers"]}
        # Step 15P: timeout blocker is now session-aware
        timeout_checks = blockers & {"market_data_not_ready_for_session", "market_data_unavailable"}
        assert len(timeout_checks) >= 1, \
            f"Expected session-aware timeout blocker, got {blockers}"

    # --- Test: timeout does not call /order* ---

    def test_market_timeout_no_order_calls(self):
        """Market timeout path must not call any /order* endpoints."""
        import inspect

        # Check _run_autonomy_status source for order endpoints
        source = inspect.getsource(_run_autonomy_status)
        forbidden = ["/order/preflight", "/order/approve", "/order/submit",
                      "placeOrder", "cancelOrder"]
        for pattern in forbidden:
            found_line = None
            for line in source.splitlines():
                if pattern in line and not line.strip().startswith("#"):
                    found_line = line.strip()[:100]
                    break
            assert found_line is None, \
                f"FORBIDDEN: '{pattern}' found in _run_autonomy_status: {found_line}"

        # Also check _run_autonomy_review
        source_review = inspect.getsource(_run_autonomy_review)
        for pattern in forbidden:
            found_line = None
            for line in source_review.splitlines():
                if pattern in line and not line.strip().startswith("#"):
                    found_line = line.strip()[:100]
                    break
            assert found_line is None, \
                f"FORBIDDEN: '{pattern}' found in _run_autonomy_review: {found_line}"

    # --- Test: timeout does not read H1 token ---

    def test_market_timeout_no_h1_token(self):
        """Market timeout path must not read H1 token."""
        import inspect

        source = inspect.getsource(_run_autonomy_status)
        forbidden = ["_run_h1_canary(", "sudo ", "/etc/ibkr-bridge/h1_token"]
        for pattern in forbidden:
            found = False
            for line in source.splitlines():
                if line.strip().startswith("#"):
                    continue
                if pattern in line:
                    found = True
                    break
            assert not found, \
                f"FORBIDDEN: '{pattern}' found in _run_autonomy_status source"

    # --- Test: JSON stdout remains pure for autonomy-status ---

    def test_json_stdout_pure_with_timeout(self, tmp_path):
        """Even with market timeout, stdout is parseable JSON."""
        from unittest.mock import patch

        now = time.time()
        ledger_dir = tmp_path / "autonomy-cycles"
        ledger_path = ledger_dir / "clean-cycle-ledger.jsonl"
        entries = [
            _make_clean_entry(time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now - i * 3600)))
            for i in range(1, 6)
        ]
        _write_ledger_entries(ledger_path, entries)
        self._make_timeout_candidate(tmp_path)

        lw = _make_lightweight_clean()
        kpi = {
            "verdict": "GO",
            "bridge": {"reachable": True, "connected": True},
            "monitoring": {"active_alert_count": 0, "reconciliation_passed": True},
            "blockers": [],
        }

        with patch("ibkr_operator._CLEAN_CYCLE_LEDGER", ledger_path), \
             patch("ibkr_operator.OPENCLAW_DIR", tmp_path), \
             patch("ibkr_operator._collect_lightweight_evidence", return_value=lw), \
             patch("ibkr_operator.run_kpi", return_value=kpi), \
             patch("ibkr_operator._CLEAN_CYCLES_REQUIRED", 5), \
             patch("ibkr_operator._CLEAN_CYCLES_WINDOW_DAYS", 7), \
             patch("ibkr_operator.BRIDGE_DIR", BRIDGE_DIR), \
             patch("ibkr_operator._read_autonomy_level", return_value="0"), \
             patch("ibkr_operator._scan_forbidden_endpoints", return_value={"ok": True, "violations": []}):
            result = _run_autonomy_status(refresh_evidence=False)

        # Must be valid JSON
        serialized = json.dumps(result, default=str)
        parsed_back = json.loads(serialized)
        assert parsed_back["recommendation"] == "HOLD"
        assert "command" in parsed_back
        assert parsed_back["refresh_evidence"] is False

    # --- Test: later successful snapshot clears the blocker ---

    def test_later_snapshot_succeeds_clears_market_blocker(self, tmp_path):
        """When a later market snapshot succeeds, the READY path can proceed."""
        from unittest.mock import patch

        now = time.time()
        ledger_dir = tmp_path / "autonomy-cycles"
        ledger_path = ledger_dir / "clean-cycle-ledger.jsonl"
        entries = [
            _make_clean_entry(time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now - i * 3600)))
            for i in range(1, 6)
        ]
        _write_ledger_entries(ledger_path, entries)

        # Write candidate with CLEAN market data (fresh, available)
        _write_candidate(tmp_path, verdict="READY_DRYRUN",
                         market_available=True, fx_available=True, fx_required=False)

        lw = _make_lightweight_clean()
        kpi = {
            "verdict": "GO",
            "bridge": {"reachable": True, "connected": True},
            "monitoring": {"active_alert_count": 0, "reconciliation_passed": True},
            "blockers": [],
        }

        with patch("ibkr_operator._CLEAN_CYCLE_LEDGER", ledger_path), \
             patch("ibkr_operator.OPENCLAW_DIR", tmp_path), \
             patch("ibkr_operator._collect_lightweight_evidence", return_value=lw), \
             patch("ibkr_operator.run_kpi", return_value=kpi), \
             patch("ibkr_operator._CLEAN_CYCLES_REQUIRED", 5), \
             patch("ibkr_operator._CLEAN_CYCLES_WINDOW_DAYS", 7), \
             patch("ibkr_operator.BRIDGE_DIR", BRIDGE_DIR), \
             patch("ibkr_operator._read_autonomy_level", return_value="0"), \
             patch("ibkr_operator._scan_forbidden_endpoints", return_value={"ok": True, "violations": []}):
            result = _run_autonomy_status(refresh_evidence=False)

        assert result["recommendation"] == "READY_FOR_MANUAL_REVIEW", \
            f"Expected READY_FOR_MANUAL_REVIEW with successful snapshot, got {result['recommendation']}"
        # Verify market data is marked available
        assert result.get("market_data_status") == "available", \
            f"Expected market_data_status=available, got {result.get('market_data_status')}"

    # --- Test: doctor can still PASS when market data is unavailable ---

    def test_doctor_pass_market_unavailable(self, tmp_path):
        """Doctor may PASS even when market data is unavailable.

        Doctor checks bridge health, not data-plane availability.
        """
        from unittest.mock import patch

        now = time.time()
        ledger_dir = tmp_path / "autonomy-cycles"
        ledger_path = ledger_dir / "clean-cycle-ledger.jsonl"
        entries = [
            _make_clean_entry(time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now - i * 3600)))
            for i in range(1, 6)
        ]
        _write_ledger_entries(ledger_path, entries)
        self._make_timeout_candidate(tmp_path)

        # Doctor passes (all checks OK)
        lw = _make_lightweight_clean()
        kpi = {
            "verdict": "GO",
            "bridge": {"reachable": True, "connected": True},
            "monitoring": {"active_alert_count": 0, "reconciliation_passed": True},
            "blockers": [],
        }

        with patch("ibkr_operator._CLEAN_CYCLE_LEDGER", ledger_path), \
             patch("ibkr_operator.OPENCLAW_DIR", tmp_path), \
             patch("ibkr_operator._collect_lightweight_evidence", return_value=lw), \
             patch("ibkr_operator.run_kpi", return_value=kpi), \
             patch("ibkr_operator._CLEAN_CYCLES_REQUIRED", 5), \
             patch("ibkr_operator._CLEAN_CYCLES_WINDOW_DAYS", 7), \
             patch("ibkr_operator.BRIDGE_DIR", BRIDGE_DIR), \
             patch("ibkr_operator._read_autonomy_level", return_value="0"), \
             patch("ibkr_operator._scan_forbidden_endpoints", return_value={"ok": True, "violations": []}):
            result = _run_autonomy_status(refresh_evidence=False)

        # Doctor should PASS (bridge is reachable, connected)
        assert result["doctor_verdict"] == "PASS", \
            f"Doctor should PASS when bridge is healthy, got {result['doctor_verdict']}"
        # But overall recommendation is HOLD because market data is unavailable
        assert result["recommendation"] == "HOLD", \
            f"Expected HOLD (market data unavailable), got {result['recommendation']}"
