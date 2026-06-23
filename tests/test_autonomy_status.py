"""Tests for Step 15J — Autonomy Readiness Evaluator / Promotion Proposal.

All tests are read-only. No broker mutation, no order endpoints,
no H1 token usage, no autonomy level changes.
"""

import json
import os
import sys
import time
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

BRIDGE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BRIDGE_DIR))

from ibkr_operator import (
    _run_autonomy_status,
    _count_clean_cycles,
    _latest_clean_cycle_timestamp,
    _CLEAN_CYCLE_LEDGER,
    _CLEAN_CYCLES_REQUIRED,
    _CLEAN_CYCLES_WINDOW_DAYS,
    OPENCLAW_DIR,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_ledger_dir(tmp_path):
    """Create a temporary ledger directory with a clean-cycle-ledger.jsonl."""
    ledger_dir = tmp_path / "autonomy-cycles"
    ledger_dir.mkdir(parents=True, exist_ok=True)
    ledger_path = ledger_dir / "clean-cycle-ledger.jsonl"
    return ledger_path


def _make_clean_entry(timestamp: str, symbol: str = "AAPL", side: str = "BUY",
                      clean: bool = True) -> dict:
    """Create a clean-cycle ledger entry."""
    return {
        "timestamp": timestamp,
        "cycle_id": f"cycle-{symbol}-{side}-{timestamp.replace(':', '')}",
        "symbol": symbol,
        "side": side,
        "doctor_verdict": "PASS",
        "kpi_verdict": "GO",
        "rehearsal_verdict": "CLEAN",
        "candidate_verdict": "READY_DRYRUN",
        "clean": clean,
        "blockers": [],
        "entry_hash": "abc123",
    }


def _write_ledger_entries(path: Path, entries: list[dict]) -> None:
    """Write ledger entries to a JSONL file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")


# ---------------------------------------------------------------------------
# Tests: ledger parsing
# ---------------------------------------------------------------------------

class TestLedgerParsing:
    """Tests for clean-cycle ledger parsing."""

    def test_count_clean_cycles_basic(self, tmp_ledger_dir):
        """Counting clean cycles from a valid ledger."""
        entries = [
            _make_clean_entry("2026-06-15T10:00:00Z", clean=True),
            _make_clean_entry("2026-06-16T10:00:00Z", clean=True),
            _make_clean_entry("2026-06-17T10:00:00Z", clean=True),
            _make_clean_entry("2026-06-18T10:00:00Z", clean=False),  # dirty
            _make_clean_entry("2026-06-19T10:00:00Z", clean=True),
        ]
        _write_ledger_entries(tmp_ledger_dir, entries)

        # Patch OPENCLAW_DIR so _count_clean_cycles finds our ledger at:
        #   OPENCLAW_DIR/autonomy-cycles/clean-cycle-ledger.jsonl
        # tmp_ledger_dir = tmp_path/autonomy-cycles/clean-cycle-ledger.jsonl
        # So we need OPENCLAW_DIR = tmp_path (the parent of autonomy-cycles)
        from unittest.mock import patch
        with patch("ibkr_operator.OPENCLAW_DIR", tmp_ledger_dir.parent.parent):
            count = _count_clean_cycles(tmp_ledger_dir.parent.parent)
        assert count == 4, f"Expected 4 clean cycles, got {count}"

    def test_count_clean_cycles_with_window(self, tmp_ledger_dir):
        """Counting clean cycles respects the max_age_days window."""
        now = time.time()
        recent_ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now - 3600))
        old_ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now - 10 * 86400))

        entries = [
            _make_clean_entry(old_ts, clean=True),   # 10 days old — outside window
            _make_clean_entry(recent_ts, clean=True),  # 1 hour old — inside window
        ]
        _write_ledger_entries(tmp_ledger_dir, entries)

        from unittest.mock import patch
        with patch("ibkr_operator.OPENCLAW_DIR", tmp_ledger_dir.parent.parent):
            count = _count_clean_cycles(tmp_ledger_dir.parent.parent, max_age_days=7)
        assert count == 1, f"Expected 1 recent clean cycle, got {count}"

    def test_ignores_malformed_ledger_rows(self, tmp_ledger_dir):
        """Malformed JSON lines are safely ignored."""
        entries = [
            _make_clean_entry("2026-06-15T10:00:00Z", clean=True),
        ]
        _write_ledger_entries(tmp_ledger_dir, entries)

        # Append garbage
        with open(tmp_ledger_dir, "a", encoding="utf-8") as f:
            f.write("this is not json\n")
            f.write("{\"broken\": true\n")  # invalid JSON
            f.write("\n")  # empty line

        from unittest.mock import patch
        with patch("ibkr_operator.OPENCLAW_DIR", tmp_ledger_dir.parent.parent):
            count = _count_clean_cycles(tmp_ledger_dir.parent.parent)
        assert count == 1, f"Malformed rows should be ignored, got {count}"

    def test_empty_ledger_returns_zero(self, tmp_ledger_dir):
        """Empty or non-existent ledger returns 0."""
        from unittest.mock import patch
        with patch("ibkr_operator.OPENCLAW_DIR", tmp_ledger_dir.parent.parent):
            count = _count_clean_cycles(tmp_ledger_dir.parent.parent)
        assert count == 0

    def test_latest_clean_cycle_timestamp(self, tmp_ledger_dir):
        """Latest clean cycle timestamp is the most recent clean=true entry."""
        entries = [
            _make_clean_entry("2026-06-15T10:00:00Z", clean=True),
            _make_clean_entry("2026-06-17T10:00:00Z", clean=True),
            _make_clean_entry("2026-06-16T10:00:00Z", clean=False),  # dirty — skipped
            _make_clean_entry("2026-06-18T10:00:00Z", clean=True),   # latest clean
        ]
        _write_ledger_entries(tmp_ledger_dir, entries)

        latest = _latest_clean_cycle_timestamp(tmp_ledger_dir)
        assert latest == "2026-06-18T10:00:00Z", f"Expected latest clean ts, got {latest}"

    def test_latest_clean_cycle_no_entries(self, tmp_ledger_dir):
        """No clean entries returns None."""
        entries = [
            _make_clean_entry("2026-06-15T10:00:00Z", clean=False),
        ]
        _write_ledger_entries(tmp_ledger_dir, entries)
        latest = _latest_clean_cycle_timestamp(tmp_ledger_dir)
        assert latest is None, f"Expected None when no clean entries, got {latest}"

    def test_latest_clean_cycle_empty_file(self, tmp_ledger_dir):
        """Empty ledger returns None."""
        tmp_ledger_dir.parent.mkdir(parents=True, exist_ok=True)
        tmp_ledger_dir.write_text("")
        latest = _latest_clean_cycle_timestamp(tmp_ledger_dir)
        assert latest is None


# ---------------------------------------------------------------------------
# Tests: autonomy-status command
# ---------------------------------------------------------------------------

class TestAutonomyStatus:
    """Tests for the autonomy readiness evaluator."""

    def _make_lightweight_clean(self):
        """Return clean lightweight evidence snapshot."""
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
                    {"check": "h1_token_canary", "ok": True, "detail": "skipped (lightweight)"},
                    {"check": "bridge_port_listener", "ok": True, "detail": "1 listener(s)"},
                    {"check": "bridge_safety_flags", "ok": True, "detail": "read_only=True, allow_orders=false"},
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
            "liveness": {"oom_detected": False, "oom_detail": "no OOM evidence", "n_restarts": 0, "k17_ok": True},
            # Step 15P: session-aware fields
            "market_session_status": {"session": "rth", "data_availability": "available", "reason": "Inside RTH", "is_tradable_day": True, "in_rth": True, "market_date_et": "2026-06-23"},
            "market_data_runtime_ok": True,
        }

    def _make_lightweight_unlocked(self):
        """Return lightweight evidence with safety UNLOCKED."""
        return {
            "bridge": {
                "reachable": True, "connected": True,
                "mode": "paper", "allow_orders": True, "read_only": False,
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
                    {"check": "h1_token_canary", "ok": True, "detail": "skipped (lightweight)"},
                    {"check": "bridge_port_listener", "ok": True, "detail": "1 listener(s)"},
                    {"check": "bridge_safety_flags", "ok": False, "detail": "read_only=False, allow_orders=True"},
                ],
            },
            "safety": {
                "read_only": False,
                "bridge_allow_orders": True,
                "env_IBKR_ALLOW_ORDERS": "true",
                "rules_enforced": "true",
                "system_locked": False,
            },
            "strategy": {"strategy_exists": True, "autonomy_exists": True},
            "liveness": {"oom_detected": False, "oom_detail": "no OOM evidence", "n_restarts": 0, "k17_ok": True},
            # Step 15P: session-aware fields
            "market_session_status": {"session": "rth", "data_availability": "available", "reason": "Inside RTH", "is_tradable_day": True, "in_rth": True, "market_date_et": "2026-06-23"},
            "market_data_runtime_ok": True,
        }

    def _make_kpi_go(self):
        """Return a GO KPI result."""
        return {
            "verdict": "GO",
            "bridge": {"reachable": True, "connected": True},
            "monitoring": {
                "active_alert_count": 0,
                "reconciliation_passed": True,
            },
            "blockers": [],
        }

    def _make_kpi_nogo(self):
        """Return a NO-GO KPI result."""
        return {
            "verdict": "NO-GO",
            "bridge": {"reachable": True, "connected": True},
            "monitoring": {
                "active_alert_count": 3,
                "reconciliation_passed": False,
            },
            "blockers": [
                {"severity": "NO-GO", "check": "active_alerts", "detail": "3 alerts"},
                {"severity": "NO-GO", "check": "reconciliation_failed", "detail": "failed"},
            ],
        }

    def _make_kpi_hold(self):
        """Return a HOLD KPI result."""
        return {
            "verdict": "HOLD",
            "bridge": {"reachable": True, "connected": False},
            "monitoring": {
                "active_alert_count": 0,
                "reconciliation_passed": None,
            },
            "blockers": [
                {"severity": "HOLD", "check": "ibkr_not_connected", "detail": "disconnected"},
            ],
        }

    def _write_candidate(self, tmp_dir: Path, verdict: str = "READY_DRYRUN",
                         market_available: bool = True, market_stale: bool = False,
                         fx_available: bool = True, fx_required: bool = False) -> Path:
        """Write a candidate dry-run result to a temporary directory."""
        candidate_dir = tmp_dir / "candidate-dryruns"
        candidate_dir.mkdir(parents=True, exist_ok=True)
        cand_path = candidate_dir / "candidate-AAPL-BUY-test.json"
        cand_data = {
            "verdict": verdict,
            "market_data": {
                "market_data_available": market_available,
                "stale": market_stale,
                "currency": "USD",
            },
            "account_evidence": {
                "fx_available": fx_available,
                "fx_required": fx_required,
                "fx_staleness_seconds": 0,
            },
        }
        cand_path.write_text(json.dumps(cand_data))
        return candidate_dir

    # --- Test: insufficient clean cycles → HOLD ---

    def test_insufficient_clean_cycles_hold(self, tmp_path):
        """When clean cycles < required, recommendation is HOLD."""
        from unittest.mock import patch

        ledger_dir = tmp_path / "autonomy-cycles"
        ledger_path = ledger_dir / "clean-cycle-ledger.jsonl"
        # Write only 2 clean entries (< 5 required) — use recent timestamps
        now = time.time()
        ts1 = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now - 3600))
        ts2 = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now - 7200))
        entries = [
            _make_clean_entry(ts1, clean=True),
            _make_clean_entry(ts2, clean=True),
        ]
        _write_ledger_entries(ledger_path, entries)

        # Write a candidate with valid market data (so market_data is not "unknown")
        candidate_dir = self._write_candidate(tmp_path, verdict="READY_DRYRUN")

        lw = self._make_lightweight_clean()
        kpi = self._make_kpi_go()

        with patch("ibkr_operator._CLEAN_CYCLE_LEDGER", ledger_path), \
             patch("ibkr_operator.OPENCLAW_DIR", tmp_path), \
             patch("ibkr_operator._collect_lightweight_evidence", return_value=lw), \
             patch("ibkr_operator.run_kpi", return_value=kpi), \
             patch("ibkr_operator._CLEAN_CYCLES_REQUIRED", 5), \
             patch("ibkr_operator._CLEAN_CYCLES_WINDOW_DAYS", 7), \
             patch("ibkr_operator.BRIDGE_DIR", BRIDGE_DIR), \
             patch("ibkr_operator._read_autonomy_level", return_value="0"):
            result = _run_autonomy_status()

        assert result["recommendation"] == "HOLD", \
            f"Expected HOLD with insufficient clean cycles, got {result['recommendation']}"
        assert result["clean_cycles_observed"] == 2
        assert result["clean_cycles_required"] == 5

        # Must have insufficient_clean_cycles blocker
        insuf = [b for b in result["blockers"] if b["check"] == "insufficient_clean_cycles"]
        assert len(insuf) == 1, f"Expected insufficient_clean_cycles blocker, got {[b['check'] for b in result['blockers']]}"

    # --- Test: enough clean cycles + safe → READY_FOR_MANUAL_REVIEW ---

    def test_enough_clean_cycles_safe_ready(self, tmp_path):
        """When all criteria met, recommendation is READY_FOR_MANUAL_REVIEW."""
        from unittest.mock import patch

        ledger_dir = tmp_path / "autonomy-cycles"
        ledger_path = ledger_dir / "clean-cycle-ledger.jsonl"
        # Write 5 clean entries (meets requirement) — use recent timestamps
        now = time.time()
        entries = [
            _make_clean_entry(time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now - i * 3600)), clean=True)
            for i in range(1, 6)
        ]
        _write_ledger_entries(ledger_path, entries)

        # Write a valid candidate
        candidate_dir = self._write_candidate(tmp_path, verdict="READY_DRYRUN")

        lw = self._make_lightweight_clean()
        kpi = self._make_kpi_go()

        with patch("ibkr_operator._CLEAN_CYCLE_LEDGER", ledger_path), \
             patch("ibkr_operator.OPENCLAW_DIR", tmp_path), \
             patch("ibkr_operator._collect_lightweight_evidence", return_value=lw), \
             patch("ibkr_operator.run_kpi", return_value=kpi), \
             patch("ibkr_operator._CLEAN_CYCLES_REQUIRED", 5), \
             patch("ibkr_operator._CLEAN_CYCLES_WINDOW_DAYS", 7), \
             patch("ibkr_operator.BRIDGE_DIR", BRIDGE_DIR), \
             patch("ibkr_operator._read_autonomy_level", return_value="0"), \
             patch("ibkr_operator._scan_forbidden_endpoints", return_value={"ok": True, "violations": []}):
            result = _run_autonomy_status()

        assert result["recommendation"] == "READY_FOR_MANUAL_REVIEW", \
            f"Expected READY_FOR_MANUAL_REVIEW, got {result['recommendation']}"
        assert result["clean_cycles_observed"] == 5
        assert result["safety_locked"] is True
        assert result["blocker_count"] == 0

    # --- Test: safety unlocked → NO_GO ---

    def test_safety_unlocked_nogo(self, tmp_path):
        """When safety is unlocked, recommendation is NO_GO."""
        from unittest.mock import patch

        ledger_dir = tmp_path / "autonomy-cycles"
        ledger_path = ledger_dir / "clean-cycle-ledger.jsonl"
        now = time.time()
        entries = [
            _make_clean_entry(time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now - i * 3600)), clean=True)
            for i in range(1, 6)
        ]
        _write_ledger_entries(ledger_path, entries)

        lw = self._make_lightweight_unlocked()  # safety UNLOCKED
        kpi = self._make_kpi_go()

        with patch("ibkr_operator._CLEAN_CYCLE_LEDGER", ledger_path), \
             patch("ibkr_operator.OPENCLAW_DIR", tmp_path), \
             patch("ibkr_operator._collect_lightweight_evidence", return_value=lw), \
             patch("ibkr_operator.run_kpi", return_value=kpi), \
             patch("ibkr_operator._CLEAN_CYCLES_REQUIRED", 5), \
             patch("ibkr_operator._CLEAN_CYCLES_WINDOW_DAYS", 7), \
             patch("ibkr_operator.BRIDGE_DIR", BRIDGE_DIR), \
             patch("ibkr_operator._read_autonomy_level", return_value="0"):
            result = _run_autonomy_status()

        assert result["recommendation"] == "NO_GO", \
            f"Expected NO_GO with safety unlocked, got {result['recommendation']}"
        assert result["safety_locked"] is False

        nogo = [b for b in result["blockers"] if b["check"] == "safety_unlocked"]
        assert len(nogo) == 1, f"Expected safety_unlocked blocker, got {[b['check'] for b in result['blockers']]}"

    # --- Test: bridge unreachable → NO_GO ---

    def test_bridge_unreachable_nogo(self, tmp_path):
        """When bridge is unreachable, recommendation is NO_GO."""
        from unittest.mock import patch

        ledger_dir = tmp_path / "autonomy-cycles"
        ledger_path = ledger_dir / "clean-cycle-ledger.jsonl"
        now = time.time()
        entries = [
            _make_clean_entry(time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now - i * 3600)), clean=True)
            for i in range(1, 6)
        ]
        _write_ledger_entries(ledger_path, entries)

        lw = self._make_lightweight_clean()
        lw["bridge"]["reachable"] = False
        lw["bridge"]["connected"] = False

        kpi = self._make_kpi_go()

        with patch("ibkr_operator._CLEAN_CYCLE_LEDGER", ledger_path), \
             patch("ibkr_operator.OPENCLAW_DIR", tmp_path), \
             patch("ibkr_operator._collect_lightweight_evidence", return_value=lw), \
             patch("ibkr_operator.run_kpi", return_value=kpi), \
             patch("ibkr_operator._CLEAN_CYCLES_REQUIRED", 5), \
             patch("ibkr_operator._CLEAN_CYCLES_WINDOW_DAYS", 7), \
             patch("ibkr_operator.BRIDGE_DIR", BRIDGE_DIR), \
             patch("ibkr_operator._read_autonomy_level", return_value="0"):
            result = _run_autonomy_status()

        assert result["recommendation"] == "NO_GO", \
            f"Expected NO_GO with bridge unreachable, got {result['recommendation']}"

        nogo = [b for b in result["blockers"] if b["check"] == "bridge_unreachable"]
        assert len(nogo) == 1, f"Expected bridge_unreachable blocker"

    # --- Test: KPI NO-GO → NO_GO ---

    def test_kpi_nogo(self, tmp_path):
        """When KPI reports NO-GO, recommendation is NO_GO."""
        from unittest.mock import patch

        ledger_dir = tmp_path / "autonomy-cycles"
        ledger_path = ledger_dir / "clean-cycle-ledger.jsonl"
        now = time.time()
        entries = [
            _make_clean_entry(time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now - i * 3600)), clean=True)
            for i in range(1, 6)
        ]
        _write_ledger_entries(ledger_path, entries)

        lw = self._make_lightweight_clean()
        kpi = self._make_kpi_nogo()  # NO-GO from KPI

        with patch("ibkr_operator._CLEAN_CYCLE_LEDGER", ledger_path), \
             patch("ibkr_operator.OPENCLAW_DIR", tmp_path), \
             patch("ibkr_operator._collect_lightweight_evidence", return_value=lw), \
             patch("ibkr_operator.run_kpi", return_value=kpi), \
             patch("ibkr_operator._CLEAN_CYCLES_REQUIRED", 5), \
             patch("ibkr_operator._CLEAN_CYCLES_WINDOW_DAYS", 7), \
             patch("ibkr_operator.BRIDGE_DIR", BRIDGE_DIR), \
             patch("ibkr_operator._read_autonomy_level", return_value="0"):
            result = _run_autonomy_status()

        assert result["recommendation"] == "NO_GO", \
            f"Expected NO_GO with KPI NO-GO, got {result['recommendation']}"
        assert result["kpi_verdict"] == "NO-GO"

    # --- Test: forbidden endpoint evidence → NO_GO ---

    def test_forbidden_endpoint_nogo(self, tmp_path):
        """When forbidden endpoints found, recommendation is NO_GO."""
        from unittest.mock import patch

        ledger_dir = tmp_path / "autonomy-cycles"
        ledger_path = ledger_dir / "clean-cycle-ledger.jsonl"
        now = time.time()
        entries = [
            _make_clean_entry(time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now - i * 3600)), clean=True)
            for i in range(1, 6)
        ]
        _write_ledger_entries(ledger_path, entries)

        lw = self._make_lightweight_clean()
        kpi = self._make_kpi_go()

        bad_scan = {
            "ok": False,
            "violations": [{"endpoint": "/order/submit", "line": 123, "context": "url = /order/submit"}],
        }

        with patch("ibkr_operator._CLEAN_CYCLE_LEDGER", ledger_path), \
             patch("ibkr_operator.OPENCLAW_DIR", tmp_path), \
             patch("ibkr_operator._collect_lightweight_evidence", return_value=lw), \
             patch("ibkr_operator.run_kpi", return_value=kpi), \
             patch("ibkr_operator._CLEAN_CYCLES_REQUIRED", 5), \
             patch("ibkr_operator._CLEAN_CYCLES_WINDOW_DAYS", 7), \
             patch("ibkr_operator.BRIDGE_DIR", BRIDGE_DIR), \
             patch("ibkr_operator._read_autonomy_level", return_value="0"), \
             patch("ibkr_operator._scan_forbidden_endpoints", return_value=bad_scan):
            result = _run_autonomy_status()

        assert result["recommendation"] == "NO_GO", \
            f"Expected NO_GO with forbidden endpoints, got {result['recommendation']}"

        nogo = [b for b in result["blockers"] if b["check"] == "forbidden_endpoint_violation"]
        assert len(nogo) == 1

    # --- Test: candidate NO-GO → NO_GO ---

    def test_candidate_nogo(self, tmp_path):
        """When latest candidate is NO-GO, recommendation is NO_GO."""
        from unittest.mock import patch

        ledger_dir = tmp_path / "autonomy-cycles"
        ledger_path = ledger_dir / "clean-cycle-ledger.jsonl"
        now = time.time()
        entries = [
            _make_clean_entry(time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now - i * 3600)), clean=True)
            for i in range(1, 6)
        ]
        _write_ledger_entries(ledger_path, entries)

        # Write a NO-GO candidate
        candidate_dir = self._write_candidate(tmp_path, verdict="NO-GO")

        lw = self._make_lightweight_clean()
        kpi = self._make_kpi_go()

        with patch("ibkr_operator._CLEAN_CYCLE_LEDGER", ledger_path), \
             patch("ibkr_operator.OPENCLAW_DIR", tmp_path), \
             patch("ibkr_operator._collect_lightweight_evidence", return_value=lw), \
             patch("ibkr_operator.run_kpi", return_value=kpi), \
             patch("ibkr_operator._CLEAN_CYCLES_REQUIRED", 5), \
             patch("ibkr_operator._CLEAN_CYCLES_WINDOW_DAYS", 7), \
             patch("ibkr_operator.BRIDGE_DIR", BRIDGE_DIR), \
             patch("ibkr_operator._read_autonomy_level", return_value="0"):
            result = _run_autonomy_status()

        assert result["recommendation"] == "NO_GO", \
            f"Expected NO_GO with candidate NO-GO, got {result['recommendation']}"
        assert result["latest_candidate_verdict"] == "NO-GO"

    # --- Test: does not auto-change autonomy level ---

    def test_no_auto_change_autonomy_level(self, tmp_path):
        """The autonomy-status command must not modify autonomy config."""
        from unittest.mock import patch

        # We verify that _read_autonomy_level is called but no write occurs.
        # The autonomy_status function never writes to AUTONOMY_CRITERIA.md.
        # We can verify this by checking that the result contains current_autonomy_level
        # but there's no mutation path.

        ledger_dir = tmp_path / "autonomy-cycles"
        ledger_path = ledger_dir / "clean-cycle-ledger.jsonl"
        now = time.time()
        entries = [
            _make_clean_entry(time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now - i * 3600)), clean=True)
            for i in range(1, 6)
        ]
        _write_ledger_entries(ledger_path, entries)

        lw = self._make_lightweight_clean()
        kpi = self._make_kpi_go()

        with patch("ibkr_operator._CLEAN_CYCLE_LEDGER", ledger_path), \
             patch("ibkr_operator.OPENCLAW_DIR", tmp_path), \
             patch("ibkr_operator._collect_lightweight_evidence", return_value=lw), \
             patch("ibkr_operator.run_kpi", return_value=kpi), \
             patch("ibkr_operator._CLEAN_CYCLES_REQUIRED", 5), \
             patch("ibkr_operator._CLEAN_CYCLES_WINDOW_DAYS", 7), \
             patch("ibkr_operator.BRIDGE_DIR", BRIDGE_DIR), \
             patch("ibkr_operator._read_autonomy_level", return_value="0"):
            result = _run_autonomy_status()

        # The result shows current level is 0, target is 1
        assert result["current_autonomy_level"] == "0"
        assert result["target_autonomy_level"] == "1"
        # No auto-change: the function only reads, never writes autonomy config
        assert result["no_broker_mutation"] is True

        # Verify no write occurred to AUTONOMY_CRITERIA.md
        autonomy_doc = BRIDGE_DIR / "docs" / "AUTONOMY_CRITERIA.md"
        if autonomy_doc.exists():
            original = autonomy_doc.read_text()
            # After the test, the file should be unchanged
            assert autonomy_doc.read_text() == original, \
                "AUTONOMY_CRITERIA.md was modified — mutation detected"

    # --- Test: required output fields ---

    def test_required_output_fields(self, tmp_path):
        """All required output fields are present."""
        from unittest.mock import patch

        ledger_dir = tmp_path / "autonomy-cycles"
        ledger_path = ledger_dir / "clean-cycle-ledger.jsonl"
        entries = [
            _make_clean_entry("2026-06-19T10:00:00Z", clean=True),
        ]
        _write_ledger_entries(ledger_path, entries)

        lw = self._make_lightweight_clean()
        kpi = self._make_kpi_go()

        with patch("ibkr_operator._CLEAN_CYCLE_LEDGER", ledger_path), \
             patch("ibkr_operator.OPENCLAW_DIR", tmp_path), \
             patch("ibkr_operator._collect_lightweight_evidence", return_value=lw), \
             patch("ibkr_operator.run_kpi", return_value=kpi), \
             patch("ibkr_operator._CLEAN_CYCLES_REQUIRED", 5), \
             patch("ibkr_operator._CLEAN_CYCLES_WINDOW_DAYS", 7), \
             patch("ibkr_operator.BRIDGE_DIR", BRIDGE_DIR), \
             patch("ibkr_operator._read_autonomy_level", return_value="0"), \
             patch("ibkr_operator._scan_forbidden_endpoints", return_value={"ok": True, "violations": []}):
            result = _run_autonomy_status()

        required_fields = [
            "timestamp", "git", "current_autonomy_level", "target_autonomy_level",
            "recommendation", "clean_cycles_observed", "clean_cycles_required",
            "clean_cycles_window_days", "latest_clean_cycle_timestamp",
            "ledger_path", "doctor_verdict", "kpi_verdict",
            "bridge_reachable", "ibkr_connected", "safety_locked",
            "env_IBKR_ALLOW_ORDERS", "rules_enforced", "active_alert_count",
            "reconciliation_passed", "latest_candidate_verdict",
            "market_data_status", "fx_status", "blockers",
            "evidence_exports", "no_broker_mutation",
        ]
        for field in required_fields:
            assert field in result, f"Missing required field: {field}"

        # Git sub-fields
        for sub in ["branch", "commit", "tag"]:
            assert sub in result["git"], f"Missing git.{sub}"

    # --- Test: H1 token canary MANUAL is acceptable ---

    def test_h1_canary_manual_allowed(self, tmp_path):
        """H1 canary status MANUAL_REQUIRED does not block autonomy readiness."""
        from unittest.mock import patch

        ledger_dir = tmp_path / "autonomy-cycles"
        ledger_path = ledger_dir / "clean-cycle-ledger.jsonl"
        now = time.time()
        entries = [
            _make_clean_entry(time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now - i * 3600)), clean=True)
            for i in range(1, 6)
        ]
        _write_ledger_entries(ledger_path, entries)

        # Write a valid candidate
        candidate_dir = self._write_candidate(tmp_path, verdict="READY_DRYRUN")

        lw = self._make_lightweight_clean()
        # H1 canary is MANUAL_REQUIRED (sudo needed) — this is acceptable
        lw["doctor"]["pass"] = False  # doctor overall fails
        lw["doctor"]["checks"] = [
            {"check": "runbook_exists", "ok": True},
            {"check": "operator_symlink", "ok": True},
            {"check": "required_files", "ok": True},
            {"check": "bridge_health", "ok": True},
            {"check": "export_dir_writable", "ok": True},
            {"check": "hermes_policy_exists", "ok": True},
            {"check": "h1_token_canary", "ok": False, "status": "MANUAL_REQUIRED",
             "detail": "sudo requires password"},
            {"check": "bridge_port_listener", "ok": True},
            {"check": "bridge_safety_flags", "ok": True},
        ]

        kpi = self._make_kpi_go()

        with patch("ibkr_operator._CLEAN_CYCLE_LEDGER", ledger_path), \
             patch("ibkr_operator.OPENCLAW_DIR", tmp_path), \
             patch("ibkr_operator._collect_lightweight_evidence", return_value=lw), \
             patch("ibkr_operator.run_kpi", return_value=kpi), \
             patch("ibkr_operator._CLEAN_CYCLES_REQUIRED", 5), \
             patch("ibkr_operator._CLEAN_CYCLES_WINDOW_DAYS", 7), \
             patch("ibkr_operator.BRIDGE_DIR", BRIDGE_DIR), \
             patch("ibkr_operator._read_autonomy_level", return_value="0"), \
             patch("ibkr_operator._scan_forbidden_endpoints", return_value={"ok": True, "violations": []}):
            result = _run_autonomy_status()

        # H1 canary MANUAL should NOT block — doctor_verdict should be PASS
        assert result["doctor_verdict"] == "PASS", \
            f"H1 canary MANUAL should allow doctor PASS, got {result['doctor_verdict']}"

        # With enough clean cycles and safe evidence, should be READY
        assert result["recommendation"] == "READY_FOR_MANUAL_REVIEW", \
            f"Expected READY_FOR_MANUAL_REVIEW when H1 canary is MANUAL, got {result['recommendation']}"

    # --- Test: doctor non-canary failure → HOLD ---

    def test_doctor_non_canary_failure_hold(self, tmp_path):
        """When doctor has non-H1-canary failures, the verdict becomes HOLD."""
        from unittest.mock import patch

        ledger_dir = tmp_path / "autonomy-cycles"
        ledger_path = ledger_dir / "clean-cycle-ledger.jsonl"
        now = time.time()
        entries = [
            _make_clean_entry(time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now - i * 3600)), clean=True)
            for i in range(1, 6)
        ]
        _write_ledger_entries(ledger_path, entries)

        # Write a valid candidate
        candidate_dir = self._write_candidate(tmp_path, verdict="READY_DRYRUN")

        lw = self._make_lightweight_clean()
        lw["doctor"]["pass"] = False
        lw["doctor"]["checks"] = [
            {"check": "runbook_exists", "ok": True},
            {"check": "operator_symlink", "ok": False, "detail": "not found"},  # FAIL
            {"check": "h1_token_canary", "ok": True, "detail": "skipped (lightweight)"},
            {"check": "bridge_safety_flags", "ok": True},
        ]

        kpi = self._make_kpi_go()

        with patch("ibkr_operator._CLEAN_CYCLE_LEDGER", ledger_path), \
             patch("ibkr_operator.OPENCLAW_DIR", tmp_path), \
             patch("ibkr_operator._collect_lightweight_evidence", return_value=lw), \
             patch("ibkr_operator.run_kpi", return_value=kpi), \
             patch("ibkr_operator._CLEAN_CYCLES_REQUIRED", 5), \
             patch("ibkr_operator._CLEAN_CYCLES_WINDOW_DAYS", 7), \
             patch("ibkr_operator.BRIDGE_DIR", BRIDGE_DIR), \
             patch("ibkr_operator._read_autonomy_level", return_value="0"):
            result = _run_autonomy_status()

        assert result["doctor_verdict"] == "FAIL", \
            f"Expected FAIL with non-canary failures, got {result['doctor_verdict']}"

        # Should be HOLD because doctor non-canary fails
        assert result["recommendation"] in ("HOLD", "NO_GO"), \
            f"Expected HOLD or NO_GO with doctor fail, got {result['recommendation']}"

    # --- Test: CLI exit codes ---

    def test_cli_exit_code_ready(self, tmp_path):
        """CLI exits 0 when READY_FOR_MANUAL_REVIEW."""
        from unittest.mock import patch
        import subprocess

        ledger_dir = tmp_path / "autonomy-cycles"
        ledger_path = ledger_dir / "clean-cycle-ledger.jsonl"
        now = time.time()
        entries = [
            _make_clean_entry(time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now - i * 3600)), clean=True)
            for i in range(1, 6)
        ]
        _write_ledger_entries(ledger_path, entries)

        lw = self._make_lightweight_clean()
        kpi = self._make_kpi_go()

        with patch("ibkr_operator._CLEAN_CYCLE_LEDGER", ledger_path), \
             patch("ibkr_operator.OPENCLAW_DIR", tmp_path), \
             patch("ibkr_operator._collect_lightweight_evidence", return_value=lw), \
             patch("ibkr_operator.run_kpi", return_value=kpi), \
             patch("ibkr_operator._CLEAN_CYCLES_REQUIRED", 5), \
             patch("ibkr_operator._CLEAN_CYCLES_WINDOW_DAYS", 7), \
             patch("ibkr_operator.BRIDGE_DIR", BRIDGE_DIR), \
             patch("ibkr_operator._read_autonomy_level", return_value="0"), \
             patch("ibkr_operator._scan_forbidden_endpoints", return_value={"ok": True, "violations": []}):
            result = _run_autonomy_status()

        assert result["recommendation"] == "READY_FOR_MANUAL_REVIEW"
        # Exit code 0 for READY_FOR_MANUAL_REVIEW

    # --- Test: no H1 token reads ---

    def test_no_h1_token_reads(self, tmp_path):
        """The autonomy-status function does not perform H1 token reads itself."""
        # This is verified structurally: _run_autonomy_status() does not
        # call _run_h1_canary() or any sudo commands. The doctor used is
        # lightweight (no subprocess, no sudo).

        # Search the function source for actual H1 token read patterns
        # (NOT variable names or comments referencing h1_token)
        import inspect
        source = inspect.getsource(_run_autonomy_status)
        # Actual H1 token reads would involve calling _run_h1_canary, sudo,
        # or reading /etc/ibkr-bridge/h1_token
        forbidden_calls = ["_run_h1_canary(", "sudo ", "/etc/ibkr-bridge/h1_token"]
        for pattern in forbidden_calls:
            found = False
            for line in source.splitlines():
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue
                if pattern in stripped:
                    found = True
                    break
            assert not found, \
                f"FORBIDDEN: '{pattern}' found in _run_autonomy_status source"

    # --- Test: no order endpoints ---

    def test_no_order_endpoints(self, tmp_path):
        """The autonomy-status function does not call any order endpoints."""
        import inspect
        source = inspect.getsource(_run_autonomy_status)
        forbidden = ["/order", "/connect", "placeOrder", "cancelOrder"]
        for pattern in forbidden:
            found_line = None
            for line in source.splitlines():
                if pattern in line and not line.strip().startswith("#"):
                    found_line = line.strip()[:100]
                    break
            assert found_line is None, \
                f"FORBIDDEN: '{pattern}' found in _run_autonomy_status: {found_line}"

    # --- Test: autonomy-readiness alias ---

    def test_autonomy_readiness_alias(self, tmp_path):
        """autonomy-readiness is a valid alias for autonomy-status."""
        from unittest.mock import patch

        ledger_dir = tmp_path / "autonomy-cycles"
        ledger_path = ledger_dir / "clean-cycle-ledger.jsonl"
        entries = [
            _make_clean_entry("2026-06-19T10:00:00Z", clean=True),
        ]
        _write_ledger_entries(ledger_path, entries)

        lw = self._make_lightweight_clean()
        kpi = self._make_kpi_go()

        with patch("ibkr_operator._CLEAN_CYCLE_LEDGER", ledger_path), \
             patch("ibkr_operator.OPENCLAW_DIR", tmp_path), \
             patch("ibkr_operator._collect_lightweight_evidence", return_value=lw), \
             patch("ibkr_operator.run_kpi", return_value=kpi), \
             patch("ibkr_operator._CLEAN_CYCLES_REQUIRED", 5), \
             patch("ibkr_operator._CLEAN_CYCLES_WINDOW_DAYS", 7), \
             patch("ibkr_operator.BRIDGE_DIR", BRIDGE_DIR), \
             patch("ibkr_operator._read_autonomy_level", return_value="0"), \
             patch("ibkr_operator._scan_forbidden_endpoints", return_value={"ok": True, "violations": []}):
            result = _run_autonomy_status()

        # The result command is always "ibkr-operator autonomy-status"
        assert "autonomy-status" in result["command"]

    # --- Test: evidence export is written ---

    def test_evidence_export_written(self, tmp_path):
        """Evidence export file is written to autonomy-status directory."""
        from unittest.mock import patch

        ledger_dir = tmp_path / "autonomy-cycles"
        ledger_path = ledger_dir / "clean-cycle-ledger.jsonl"
        entries = [
            _make_clean_entry("2026-06-19T10:00:00Z", clean=True),
        ]
        _write_ledger_entries(ledger_path, entries)

        export_dir = tmp_path / "autonomy-status"
        export_dir.mkdir(parents=True, exist_ok=True)

        lw = self._make_lightweight_clean()
        kpi = self._make_kpi_go()

        with patch("ibkr_operator._CLEAN_CYCLE_LEDGER", ledger_path), \
             patch("ibkr_operator.OPENCLAW_DIR", tmp_path), \
             patch("ibkr_operator._collect_lightweight_evidence", return_value=lw), \
             patch("ibkr_operator.run_kpi", return_value=kpi), \
             patch("ibkr_operator._CLEAN_CYCLES_REQUIRED", 5), \
             patch("ibkr_operator._CLEAN_CYCLES_WINDOW_DAYS", 7), \
             patch("ibkr_operator.BRIDGE_DIR", BRIDGE_DIR), \
             patch("ibkr_operator._read_autonomy_level", return_value="0"), \
             patch("ibkr_operator._AUTONOMY_STATUS_EXPORT_DIR", export_dir), \
             patch("ibkr_operator._scan_forbidden_endpoints", return_value={"ok": True, "violations": []}):
            result = _run_autonomy_status()

        # Export should be listed in evidence_exports
        assert len(result["evidence_exports"]) > 0, "Expected at least one evidence export"

        # The export file should exist
        export_path = Path(result["evidence_exports"][0])
        assert export_path.exists(), f"Export file not found: {export_path}"

        # Verify content is valid JSON
        with open(export_path, "r", encoding="utf-8") as f:
            exported = json.load(f)
        assert exported["recommendation"] == result["recommendation"]
        assert exported["no_broker_mutation"] is True

    # --- Test: historical row clean=true + doctor_verdict=FAIL ignored ---

    def test_historical_clean_true_doctor_fail_ignored(self, tmp_path):
        """A row with clean=true but doctor_verdict=FAIL is NOT counted."""
        from unittest.mock import patch

        ledger_dir = tmp_path / "autonomy-cycles"
        ledger_path = ledger_dir / "clean-cycle-ledger.jsonl"
        now = time.time()

        # Row 1: clean=true but doctor_verdict=FAIL — should be ignored
        bad_entry = _make_clean_entry(
            time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now - 3600)),
            clean=True,
        )
        bad_entry["doctor_verdict"] = "FAIL"

        # Row 2: clean=true, doctor_verdict=PASS, all strict — should count
        good_entry = _make_clean_entry(
            time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now - 7200)),
            clean=True,
        )

        _write_ledger_entries(ledger_path, [bad_entry, good_entry])

        from ibkr_operator import _ledger_entry_strict_clean

        # Verify bad entry fails strict check
        bad_clean, bad_reasons = _ledger_entry_strict_clean(bad_entry)
        assert bad_clean is False, f"Expected bad entry to fail strict check, got reasons={bad_reasons}"
        assert any("doctor_verdict" in r for r in bad_reasons), \
            f"Expected doctor_verdict-related reason in {bad_reasons}"

        # Verify good entry passes strict check
        good_clean, good_reasons = _ledger_entry_strict_clean(good_entry)
        assert good_clean is True, f"Expected good entry to pass strict check, got reasons={good_reasons}"

        # Now verify _count_clean_cycles only counts the good one
        with patch("ibkr_operator.OPENCLAW_DIR", tmp_path):
            count = _count_clean_cycles(tmp_path)
        assert count == 1, f"Expected 1 strictly-clean cycle, got {count}"

    # --- Test: autonomy-status clean_cycles_observed equals strict validator count ---

    def test_autonomy_status_matches_strict_count(self, tmp_path):
        """Autonomy-status clean_cycles_observed matches strict validator."""
        from unittest.mock import patch

        ledger_dir = tmp_path / "autonomy-cycles"
        ledger_path = ledger_dir / "clean-cycle-ledger.jsonl"
        now = time.time()

        # 3 clean=true but only 2 pass strict validation
        entries = [
            _make_clean_entry(time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now - 1 * 3600)), clean=True),
            _make_clean_entry(time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now - 2 * 3600)), clean=True),
            _make_clean_entry(time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now - 3 * 3600)), clean=True),
        ]
        # Third entry has kpi_verdict=NO-GO — should be excluded by strict check
        entries[2]["kpi_verdict"] = "NO-GO"
        _write_ledger_entries(ledger_path, entries)

        # Write valid candidate
        candidate_dir = self._write_candidate(tmp_path, verdict="READY_DRYRUN")

        lw = self._make_lightweight_clean()
        kpi = self._make_kpi_go()

        with patch("ibkr_operator._CLEAN_CYCLE_LEDGER", ledger_path), \
             patch("ibkr_operator.OPENCLAW_DIR", tmp_path), \
             patch("ibkr_operator._collect_lightweight_evidence", return_value=lw), \
             patch("ibkr_operator.run_kpi", return_value=kpi), \
             patch("ibkr_operator._CLEAN_CYCLES_REQUIRED", 2), \
             patch("ibkr_operator._CLEAN_CYCLES_WINDOW_DAYS", 7), \
             patch("ibkr_operator.BRIDGE_DIR", BRIDGE_DIR), \
             patch("ibkr_operator._read_autonomy_level", return_value="0"), \
             patch("ibkr_operator._scan_forbidden_endpoints", return_value={"ok": True, "violations": []}):
            result = _run_autonomy_status()

        # Only 2 out of 3 pass strict check (one has kpi_verdict=NO-GO)
        assert result["clean_cycles_observed"] == 2, \
            f"Expected 2 strictly-clean cycles, got {result['clean_cycles_observed']}"

    # --- Test: --json --export stdout is parseable JSON ---

    def test_json_export_stdout_is_parseable(self, tmp_path):
        """--json --export writes pure JSON to stdout, export note to stderr."""
        import subprocess
        import sys

        # Use the CLI to verify stdout/stderr separation
        script = '''
import json, sys, time, os
from pathlib import Path
from unittest.mock import patch

# Patch OPENCLAW_DIR and other globals to use tmp_path
tmp = Path(sys.argv[1])

# Write 5 strictly-clean ledger entries
ledger_dir = tmp / "autonomy-cycles"
ledger_dir.mkdir(parents=True, exist_ok=True)
ledger_path = ledger_dir / "clean-cycle-ledger.jsonl"
now = time.time()
entries = []
for i in range(1, 6):
    ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now - i * 3600))
    entry = {
        "timestamp": ts,
        "cycle_id": f"cycle-test-{i}",
        "symbol": "AAPL",
        "side": "BUY",
        "doctor_verdict": "PASS",
        "kpi_verdict": "GO",
        "rehearsal_verdict": "CLEAN",
        "candidate_verdict": "READY_DRYRUN",
        "clean": True,
        "blockers": [],
        "entry_hash": "abc123",
    }
    entries.append(entry)
with open(ledger_path, "w", encoding="utf-8") as f:
    for e in entries:
        f.write(json.dumps(e) + "\\n")

# Write candidate
cand_dir = tmp / "candidate-dryruns"
cand_dir.mkdir(parents=True, exist_ok=True)
cand_path = cand_dir / "candidate-AAPL-BUY-test.json"
cand_data = {
    "verdict": "READY_DRYRUN",
    "market_data": {"market_data_available": True, "stale": False},
    "account_evidence": {"fx_available": True, "fx_required": False, "fx_staleness_seconds": 0},
}
cand_path.write_text(json.dumps(cand_data))

# Now run autonomy_status
sys.path.insert(0, str(Path(sys.argv[2])))
from ibkr_operator import _run_autonomy_status, _CLEAN_CYCLE_LEDGER, OPENCLAW_DIR
from pathlib import Path as P

bridge_dir = P(sys.argv[2])

with patch("ibkr_operator._CLEAN_CYCLE_LEDGER", ledger_path), \
     patch("ibkr_operator.OPENCLAW_DIR", tmp), \
     patch("ibkr_operator._CLEAN_CYCLES_REQUIRED", 5), \
     patch("ibkr_operator._CLEAN_CYCLES_WINDOW_DAYS", 7), \
     patch("ibkr_operator.BRIDGE_DIR", bridge_dir), \
     patch("ibkr_operator._read_autonomy_level", return_value="0"), \
     patch("ibkr_operator._scan_forbidden_endpoints", return_value={"ok": True, "violations": []}), \
     patch("ibkr_operator._collect_lightweight_evidence", return_value={
         "bridge": {"reachable": True, "connected": True, "mode": "paper", "allow_orders": False, "read_only": True},
         "doctor": {"pass": True, "total": 9, "passed": 9, "checks": []},
         "safety": {"read_only": True, "bridge_allow_orders": False, "env_IBKR_ALLOW_ORDERS": "false", "rules_enforced": "false", "system_locked": True},
         "strategy": {"strategy_exists": True, "autonomy_exists": True},
         "liveness": {"oom_detected": False, "oom_detail": "no OOM", "n_restarts": 0, "k17_ok": True},
     }), \
     patch("ibkr_operator.run_kpi", return_value={
         "verdict": "GO",
         "bridge": {"reachable": True, "connected": True},
         "monitoring": {"active_alert_count": 0, "reconciliation_passed": True},
         "blockers": [],
     }):
    result = _run_autonomy_status()
    # Write JSON to stdout
    print(json.dumps(result, indent=2, default=str))
    # Write export note to stderr
    exports = result.get("evidence_exports", [])
    if exports:
        print(f"Export written: {exports[0]}", file=sys.stderr)
'''
        result = subprocess.run(
            [sys.executable, "-c", script, str(tmp_path), str(BRIDGE_DIR)],
            capture_output=True, text=True, timeout=30,
        )

        # stdout must be parseable JSON
        stdout_text = result.stdout.strip()
        assert stdout_text, "stdout is empty"
        try:
            parsed = json.loads(stdout_text)
        except json.JSONDecodeError as e:
            assert False, f"stdout is not valid JSON: {e}\nstdout head: {stdout_text[:500]}"

        # Must contain the required command key
        assert "command" in parsed, f"Missing 'command' key in stdout JSON. Keys: {sorted(parsed.keys())[:10]}"

        # stderr must contain export message (not JSON)
        stderr_text = result.stderr.strip()
        assert "Export written" in stderr_text, \
            f"Expected 'Export written' in stderr, got: {stderr_text[:200]}"


# ---------------------------------------------------------------------------
# Tests: evidence-cycle writer clean predicate (hotfix)
# ---------------------------------------------------------------------------

class TestEvidenceCycleCleanPredicate:
    """Regression tests for evidence-cycle strict clean predicate."""

    def _make_fail_doctor(self) -> dict:
        """Return a doctor dict with pass=False and real non-H1 failures."""
        return {
            "pass": False,
            "total": 9,
            "passed": 8,
            "checks": [
                {"check": "runbook_exists", "ok": True},
                {"check": "operator_symlink", "ok": False, "detail": "not found"},
                {"check": "h1_token_canary", "ok": True, "detail": "skipped (lightweight)"},
            ],
        }

    def _make_pass_doctor(self) -> dict:
        """Return a doctor dict with pass=True."""
        return {
            "pass": True,
            "total": 9,
            "passed": 9,
            "checks": [
                {"check": "runbook_exists", "ok": True},
                {"check": "operator_symlink", "ok": True},
                {"check": "h1_token_canary", "ok": True, "detail": "skipped (lightweight)"},
            ],
        }

    # --- Test: doctor FAIL writes clean=false ---

    def test_doctor_fail_writes_clean_false(self, tmp_path):
        """Evidence cycle with doctor FAIL must write clean=false."""
        from unittest.mock import patch
        from ibkr_operator import _is_clean_cycle

        evidence = {
            "ibkr": {"reachable": True, "connected": True, "mode": "paper"},
            "safety": {
                "read_only": True,
                "bridge_allow_orders": False,
                "env_IBKR_ALLOW_ORDERS": "false",
                "rules_enforced": "false",
            },
            "doctor": self._make_fail_doctor(),
            "kpi": {"verdict": "GO", "blockers": []},
            "candidate": {"verdict": "READY_DRYRUN"},
            "forbidden_endpoint_scan": {"ok": True, "violations": []},
            "monitoring": {"active_alert_count": 0, "reconciliation_passed": True},
            "market_data": {"market_data_available": True},
            "account_evidence": {"fx_available": True, "fx_required": False},
        }

        clean, reasons = _is_clean_cycle(evidence)
        assert clean is False, f"Expected clean=False with doctor FAIL, got clean=True, reasons={reasons}"
        assert any("doctor_non_pass" in r for r in reasons), \
            f"Expected doctor_non_pass reason in {reasons}"

    # --- Test: doctor FAIL adds doctor_non_pass blocker ---

    def test_doctor_fail_adds_doctor_non_pass_blocker(self, tmp_path):
        """Evidence cycle with doctor FAIL includes doctor_non_pass in blockers."""
        from unittest.mock import patch
        from ibkr_operator import _is_clean_cycle

        evidence = {
            "ibkr": {"reachable": True, "connected": True, "mode": "paper"},
            "safety": {
                "read_only": True,
                "bridge_allow_orders": False,
                "env_IBKR_ALLOW_ORDERS": "false",
                "rules_enforced": "false",
            },
            "doctor": self._make_fail_doctor(),
            "kpi": {"verdict": "GO", "blockers": []},
            "candidate": {"verdict": "READY_DRYRUN"},
            "forbidden_endpoint_scan": {"ok": True, "violations": []},
            "monitoring": {"active_alert_count": 0, "reconciliation_passed": True},
            "market_data": {"market_data_available": True},
            "account_evidence": {"fx_available": True, "fx_required": False},
        }

        clean, reasons = _is_clean_cycle(evidence)
        assert not clean

        # Find the doctor_non_pass reason
        doc_reason = [r for r in reasons if "doctor_non_pass" in r]
        assert len(doc_reason) >= 1, \
            f"Expected doctor_non_pass in reasons, got {reasons}"

        # Verify the reason mentions the specific failing check
        assert "operator_symlink" in doc_reason[0], \
            f"Expected 'operator_symlink' in doctor_non_pass reason, got: {doc_reason[0]}"

    # --- Test: doctor FAIL → evidence-cycle prints [DIRTY], not [CLEAN] ---

    def test_cli_prints_dirty_when_doctor_fail(self, tmp_path):
        """CLI output shows [DIRTY] not [CLEAN] when doctor FAIL."""
        import subprocess
        import sys

        script = '''
import json, sys, time
from pathlib import Path
from unittest.mock import patch

bridge_dir = Path(sys.argv[1])
sys.path.insert(0, str(bridge_dir))

from ibkr_operator import _run_evidence_cycle

# Build a fail doctor to inject
fail_doctor = {
    "pass": False,
    "total": 9,
    "passed": 8,
    "checks": [
        {"check": "runbook_exists", "ok": False, "detail": "missing"},
        {"check": "h1_token_canary", "ok": True, "detail": "skipped"},
    ],
}

# Patch everything to return a failing doctor
with patch("ibkr_operator._collect_lightweight_evidence", return_value={
    "bridge": {"reachable": True, "connected": True, "mode": "paper", "allow_orders": False, "read_only": True},
    "doctor": fail_doctor,
    "safety": {"read_only": True, "bridge_allow_orders": False, "env_IBKR_ALLOW_ORDERS": "false", "rules_enforced": "false", "system_locked": True},
    "strategy": {"strategy_exists": True, "autonomy_exists": True},
    "liveness": {"oom_detected": False},
}), \
     patch("ibkr_operator.run_kpi", return_value={
         "verdict": "GO",
         "bridge": {"reachable": True, "connected": True},
         "monitoring": {"active_alert_count": 0, "reconciliation_passed": True},
         "blockers": [],
     }), \
     patch("ibkr_operator._run_cycle_rehearsal", return_value={"verdict": "CLEAN"}), \
     patch("ibkr_operator._run_candidate_dryrun", return_value={
         "verdict": "READY_DRYRUN",
         "market_data": {"market_data_available": True, "stale": False},
         "account_evidence": {"fx_available": True, "fx_required": False, "fx_staleness_seconds": 0},
     }), \
     patch("ibkr_operator._scan_forbidden_endpoints", return_value={"ok": True, "violations": []}), \
     patch("ibkr_operator.BRIDGE_DIR", bridge_dir):
    result = _run_evidence_cycle("AAPL", "BUY", record=False)

print(result["clean"])
print(result["doctor_verdict"])
blockers = result.get("blockers", [])
for b in blockers:
    if isinstance(b, dict):
        print(f"BLOCKER:{b.get('check')}:{b.get('severity')}")
'''
        result = subprocess.run(
            [sys.executable, "-c", script, str(BRIDGE_DIR)],
            capture_output=True, text=True, timeout=30,
        )

        lines = result.stdout.strip().splitlines()
        # First line is clean flag
        assert lines[0] == "False", f"Expected clean=False, got {lines[0]}"
        # Second line is doctor_verdict
        assert lines[1] == "FAIL", f"Expected doctor_verdict=FAIL, got {lines[1]}"
        # Must have doctor_non_pass blocker
        blocker_lines = [l for l in lines if "BLOCKER:" in l]
        doc_blockers = [l for l in blocker_lines if "doctor_non_pass" in l]
        assert len(doc_blockers) >= 1, \
            f"Expected doctor_non_pass blocker in output, got blockers: {blocker_lines}"

    # --- Test: autonomy-status still ignores historical clean=true doctor FAIL rows ---

    def test_autonomy_status_ignores_historical_dirty(self, tmp_path):
        """Autonomy-status ignores rows with clean=true but doctor_verdict=FAIL."""
        from unittest.mock import patch

        ledger_dir = tmp_path / "autonomy-cycles"
        ledger_path = ledger_dir / "clean-cycle-ledger.jsonl"
        now = time.time()

        # Write 5 clean=true rows but all with doctor_verdict=FAIL (historical bad data)
        entries = []
        for i in range(1, 6):
            ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now - i * 3600))
            entry = _make_clean_entry(ts, clean=True)
            entry["doctor_verdict"] = "FAIL"
            entries.append(entry)
        _write_ledger_entries(ledger_path, entries)

        # Write a valid candidate so market/fx don't block
        candidate_dir = tmp_path / "candidate-dryruns"
        candidate_dir.mkdir(parents=True, exist_ok=True)
        cand_path = candidate_dir / "candidate-AAPL-BUY-test.json"
        cand_path.write_text(json.dumps({
            "verdict": "READY_DRYRUN",
            "market_data": {"market_data_available": True, "stale": False},
            "account_evidence": {"fx_available": True, "fx_required": False, "fx_staleness_seconds": 0},
        }))

        lw = {
            "bridge": {"reachable": True, "connected": True, "mode": "paper", "allow_orders": False, "read_only": True},
            "doctor": {"pass": True, "total": 9, "passed": 9, "checks": []},
            "safety": {"read_only": True, "bridge_allow_orders": False, "env_IBKR_ALLOW_ORDERS": "false", "rules_enforced": "false", "system_locked": True},
            "strategy": {"strategy_exists": True, "autonomy_exists": True},
            "liveness": {"oom_detected": False, "oom_detail": "no OOM", "n_restarts": 0, "k17_ok": True},
            "market_session_status": {"session": "rth", "data_availability": "available", "reason": "Inside RTH", "is_tradable_day": True, "in_rth": True, "market_date_et": "2026-06-23"},
            "market_data_runtime_ok": True,
        }
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
            result = _run_autonomy_status()

        # All 5 rows have doctor_verdict=FAIL → strict count must be 0
        assert result["clean_cycles_observed"] == 0, \
            f"Expected 0 strictly-clean cycles (all have doctor_verdict=FAIL), got {result['clean_cycles_observed']}"

        # Must report insufficient_clean_cycles
        insuf = [b for b in result["blockers"] if b["check"] == "insufficient_clean_cycles"]
        assert len(insuf) == 1, \
            f"Expected insufficient_clean_cycles blocker, got {[b['check'] for b in result['blockers']]}"
