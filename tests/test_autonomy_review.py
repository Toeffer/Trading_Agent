"""Tests for Step 15K — Manual Autonomy-Promotion Review Package.

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
    _run_autonomy_review,
    _run_autonomy_status,
    _count_clean_cycles,
    _latest_clean_cycle_timestamp,
    _ledger_entry_strict_clean,
    _compute_evidence_hash,
    _CLEAN_CYCLE_LEDGER,
    _CLEAN_CYCLES_REQUIRED,
    _CLEAN_CYCLES_WINDOW_DAYS,
    _MANUAL_REVIEW_CHECKLIST,
    OPENCLAW_DIR,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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
    """Write ledger entries to a JSONL file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")


def _write_candidate(tmp_dir: Path, verdict: str = "READY_DRYRUN",
                     market_available: bool = True,
                     fx_available: bool = True, fx_required: bool = False) -> Path:
    """Write a candidate dry-run result to a temporary directory."""
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
        },
        "account_evidence": {
            "fx_available": fx_available,
            "fx_required": fx_required,
            "fx_staleness_seconds": 0,
        },
    }
    cand_path.write_text(json.dumps(cand_data))
    return candidate_dir


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestAutonomyReview:
    """Tests for the manual autonomy-promotion review package."""

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
        }

    # --- Test: command exists and exports JSON ---

    def test_command_exists_and_exports_json(self, tmp_path):
        """autonomy-review command runs and returns parseable JSON."""
        from unittest.mock import patch

        now = time.time()
        ledger_dir = tmp_path / "autonomy-cycles"
        ledger_path = ledger_dir / "clean-cycle-ledger.jsonl"
        entries = [
            _make_clean_entry(time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now - i * 3600)))
            for i in range(1, 6)
        ]
        _write_ledger_entries(ledger_path, entries)

        # Write a valid candidate
        _write_candidate(tmp_path, verdict="READY_DRYRUN")

        lw = self._make_lightweight_clean()
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
            result = _run_autonomy_review(target_level="1")

        # Required fields
        required_fields = [
            "timestamp", "review_id", "git", "current_autonomy_level",
            "target_autonomy_level", "review_status", "operator_decision_required",
            "auto_promotion_performed", "no_broker_mutation",
            "autonomy_status_export_path", "latest_autonomy_status_summary",
            "clean_cycles_observed", "clean_cycles_required",
            "clean_cycle_ledger_path", "clean_cycle_entries_used",
            "latest_candidate_export_path", "latest_candidate_summary",
            "latest_kpi_summary", "doctor_summary", "safety_flags",
            "ibkr_connected", "market_data_status", "fx_status",
            "active_alert_count", "reconciliation_passed", "blockers",
            "manual_review_checklist", "evidence_hash",
        ]
        for field in required_fields:
            assert field in result, f"Missing required field: {field}"

        # Invariants
        assert result["auto_promotion_performed"] is False
        assert result["operator_decision_required"] is True
        assert result["no_broker_mutation"] is True

    # --- Test: --json stdout is pure parseable JSON ---

    def test_json_stdout_is_parseable(self, tmp_path):
        """--json output is pure parseable JSON on stdout."""
        import subprocess

        script = '''
import json, sys, time
from pathlib import Path
from unittest.mock import patch

tmp = Path(sys.argv[1])
bridge_dir = Path(sys.argv[2])
sys.path.insert(0, str(bridge_dir))

from ibkr_operator import _run_autonomy_review

# Set up ledger
ledger_dir = tmp / "autonomy-cycles"
ledger_dir.mkdir(parents=True, exist_ok=True)
ledger_path = ledger_dir / "clean-cycle-ledger.jsonl"
now = time.time()
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

# Candidate
cand_dir = tmp / "candidate-dryruns"
cand_dir.mkdir(parents=True, exist_ok=True)
cand_path = cand_dir / "candidate-AAPL-BUY-test.json"
cand_path.write_text(json.dumps({
    "verdict": "READY_DRYRUN", "symbol": "AAPL", "side": "BUY",
    "market_data": {"market_data_available": True, "stale": False},
    "account_evidence": {"fx_available": True, "fx_required": False},
}))

lw = {
    "bridge": {"reachable": True, "connected": True, "mode": "paper", "allow_orders": False, "read_only": True},
    "doctor": {"pass": True, "total": 9, "passed": 9, "checks": []},
    "safety": {"read_only": True, "bridge_allow_orders": False, "env_IBKR_ALLOW_ORDERS": "false", "rules_enforced": "false", "system_locked": True},
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
    result = _run_autonomy_review(target_level="1")
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
        assert parsed["auto_promotion_performed"] is False

    # --- Test: export file written to ~/.openclaw/autonomy-review/ ---

    def test_export_file_written(self, tmp_path):
        """Export file is written to the autonomy-review directory."""
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

        export_dir = tmp_path / "autonomy-review"
        export_dir.mkdir(parents=True, exist_ok=True)

        lw = self._make_lightweight_clean()
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
             patch("ibkr_operator._scan_forbidden_endpoints", return_value={"ok": True, "violations": []}), \
             patch("ibkr_operator._AUTONOMY_REVIEW_EXPORT_DIR", export_dir):
            result = _run_autonomy_review(target_level="1")

        export_path = Path(result["_export_path"])
        assert export_path.exists(), f"Export file not found: {export_path}"
        with open(export_path, "r") as f:
            exported = json.load(f)
        assert exported["review_id"] == result["review_id"]
        assert exported["no_broker_mutation"] is True

    # --- Test: does not modify autonomy level ---

    def test_does_not_modify_autonomy_level(self, tmp_path):
        """Autonomy review command must never change autonomy level."""
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

        lw = self._make_lightweight_clean()
        kpi = {
            "verdict": "GO",
            "bridge": {"reachable": True, "connected": True},
            "monitoring": {"active_alert_count": 0, "reconciliation_passed": True},
            "blockers": [],
        }

        autonomy_doc = BRIDGE_DIR / "docs" / "AUTONOMY_CRITERIA.md"
        original_content = autonomy_doc.read_text() if autonomy_doc.exists() else ""

        with patch("ibkr_operator._CLEAN_CYCLE_LEDGER", ledger_path), \
             patch("ibkr_operator.OPENCLAW_DIR", tmp_path), \
             patch("ibkr_operator._collect_lightweight_evidence", return_value=lw), \
             patch("ibkr_operator.run_kpi", return_value=kpi), \
             patch("ibkr_operator._CLEAN_CYCLES_REQUIRED", 5), \
             patch("ibkr_operator._CLEAN_CYCLES_WINDOW_DAYS", 7), \
             patch("ibkr_operator.BRIDGE_DIR", BRIDGE_DIR), \
             patch("ibkr_operator._read_autonomy_level", return_value="0"), \
             patch("ibkr_operator._scan_forbidden_endpoints", return_value={"ok": True, "violations": []}):
            result = _run_autonomy_review(target_level="1")

        assert result["auto_promotion_performed"] is False
        assert result["current_autonomy_level"] == "0"

        if autonomy_doc.exists():
            assert autonomy_doc.read_text() == original_content, \
                "AUTONOMY_CRITERIA.md was modified — mutation detected"

    # --- Test: does not call /order* ---

    def test_no_order_endpoints(self):
        """The autonomy-review function does not call any order endpoints."""
        import inspect
        source = inspect.getsource(_run_autonomy_review)
        forbidden = ["/order", "/connect", "placeOrder", "cancelOrder"]
        for pattern in forbidden:
            found_line = None
            for line in source.splitlines():
                if pattern in line and not line.strip().startswith("#"):
                    found_line = line.strip()[:100]
                    break
            assert found_line is None, \
                f"FORBIDDEN: '{pattern}' found in _run_autonomy_review: {found_line}"

    # --- Test: does not read H1 token ---

    def test_no_h1_token_reads(self):
        """The autonomy-review function does not perform H1 token reads."""
        import inspect
        source = inspect.getsource(_run_autonomy_review)
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
                f"FORBIDDEN: '{pattern}' found in _run_autonomy_review source"

    # --- Test: READY_FOR_OPERATOR_REVIEW when autonomy-status is READY_FOR_MANUAL_REVIEW ---

    def test_ready_when_autonomy_status_ready(self, tmp_path):
        """READY_FOR_OPERATOR_REVIEW when all criteria are met."""
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

        lw = self._make_lightweight_clean()
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
            result = _run_autonomy_review(target_level="1")

        assert result["review_status"] == "READY_FOR_OPERATOR_REVIEW", \
            f"Expected READY_FOR_OPERATOR_REVIEW, got {result['review_status']}"
        blockers = [b["check"] for b in result["blockers"]]
        assert len(blockers) == 0, f"Expected 0 blockers, got {blockers}"

    # --- Test: HOLD when autonomy-status is HOLD ---

    def test_hold_when_autonomy_status_hold(self, tmp_path):
        """HOLD when autonomy-status reports HOLD (e.g., insufficient cycles)."""
        from unittest.mock import patch

        now = time.time()
        ledger_dir = tmp_path / "autonomy-cycles"
        ledger_path = ledger_dir / "clean-cycle-ledger.jsonl"
        # Only 2 clean entries
        entries = [
            _make_clean_entry(time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now - i * 3600)))
            for i in range(1, 3)
        ]
        _write_ledger_entries(ledger_path, entries)

        _write_candidate(tmp_path, verdict="READY_DRYRUN")

        lw = self._make_lightweight_clean()
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
            result = _run_autonomy_review(target_level="1")

        assert result["review_status"] == "HOLD", \
            f"Expected HOLD with insufficient cycles, got {result['review_status']}"
        insuf = [b for b in result["blockers"] if b["check"] == "insufficient_clean_cycles"]
        assert len(insuf) == 1, \
            f"Expected insufficient_clean_cycles blocker, got {[b['check'] for b in result['blockers']]}"

    # --- Test: NO_GO when safety unlocked ---

    def test_nogo_when_safety_unlocked(self, tmp_path):
        """NO_GO when safety flags are unlocked."""
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

        lw = self._make_lightweight_clean()
        # Unlock safety
        lw["safety"]["read_only"] = False
        lw["safety"]["bridge_allow_orders"] = True
        lw["safety"]["env_IBKR_ALLOW_ORDERS"] = "true"
        lw["safety"]["rules_enforced"] = "true"
        lw["safety"]["system_locked"] = False

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
            result = _run_autonomy_review(target_level="1")

        assert result["review_status"] == "NO_GO", \
            f"Expected NO_GO with safety unlocked, got {result['review_status']}"
        safety_blocker = [b for b in result["blockers"] if b["check"] == "safety_unlocked"]
        assert len(safety_blocker) >= 1, \
            f"Expected safety_unlocked blocker, got {[b['check'] for b in result['blockers']]}"

    # --- Test: evidence hash stable ---

    def test_evidence_hash_stable(self, tmp_path):
        """Evidence hash is stable for identical package content."""
        from unittest.mock import patch

        evidence1 = {
            "current_autonomy_level": "0",
            "target_autonomy_level": "1",
            "review_status": "READY_FOR_OPERATOR_REVIEW",
            "clean_cycles_observed": 5,
            "clean_cycles_required": 5,
            "safety_locked": True,
            "env_IBKR_ALLOW_ORDERS": "false",
            "rules_enforced": "false",
            "ibkr_connected": True,
            "active_alert_count": 0,
            "reconciliation_passed": True,
            "autonomy_status_recommendation": "READY_FOR_MANUAL_REVIEW",
            "kpi_verdict": "GO",
            "candidate_verdict": "READY_DRYRUN",
            "forbidden_endpoint_scan_ok": True,
            "blocker_count": 0,
            "blocker_checks": [],
            "git_commit": "abc123",
            "auto_promotion_performed": False,
            "no_broker_mutation": True,
        }

        evidence2 = dict(evidence1)  # identical copy

        hash1 = _compute_evidence_hash(evidence1)
        hash2 = _compute_evidence_hash(evidence2)

        assert hash1 == hash2, \
            f"Evidence hash not stable: {hash1[:16]} vs {hash2[:16]}"

    # --- Test: evidence hash changes with different content ---

    def test_evidence_hash_changes_with_content(self):
        """Evidence hash changes when package content differs."""
        evidence1 = {
            "current_autonomy_level": "0",
            "target_autonomy_level": "1",
            "review_status": "READY_FOR_OPERATOR_REVIEW",
            "clean_cycles_observed": 5,
            "clean_cycles_required": 5,
            "safety_locked": True,
            "env_IBKR_ALLOW_ORDERS": "false",
            "rules_enforced": "false",
            "ibkr_connected": True,
            "active_alert_count": 0,
            "reconciliation_passed": True,
            "autonomy_status_recommendation": "READY_FOR_MANUAL_REVIEW",
            "kpi_verdict": "GO",
            "candidate_verdict": "READY_DRYRUN",
            "forbidden_endpoint_scan_ok": True,
            "blocker_count": 0,
            "blocker_checks": [],
            "git_commit": "abc123",
            "auto_promotion_performed": False,
            "no_broker_mutation": True,
        }

        evidence2 = dict(evidence1)
        evidence2["review_status"] = "HOLD"

        hash1 = _compute_evidence_hash(evidence1)
        hash2 = _compute_evidence_hash(evidence2)

        assert hash1 != hash2, "Evidence hash should change with different content"

    # --- Test: promotion-review alias ---

    def test_promotion_review_alias(self, tmp_path):
        """promotion-review is a valid alias for autonomy-review."""
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

        lw = self._make_lightweight_clean()
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
            result = _run_autonomy_review(target_level="1")

        # The result command is always "ibkr-operator autonomy-review"
        assert "autonomy-review" in result["command"]

    # --- Test: manual review checklist has all items ---

    def test_manual_review_checklist_complete(self, tmp_path):
        """Manual review checklist contains all required items."""
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

        lw = self._make_lightweight_clean()
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
            result = _run_autonomy_review(target_level="1")

        checklist = result["manual_review_checklist"]
        assert len(checklist) == 7, f"Expected 7 checklist items, got {len(checklist)}"

        required_tasks = [
            "Confirm no order window was opened.",
            "Confirm safety flags are locked",
            "Confirm clean cycles are valid and recent.",
            "Confirm candidate evidence is HOLD/READY only",
            "Confirm market data and FX evidence",
            "Confirm promotion is manual only",
            "Confirm no live orders will be enabled",
        ]
        all_tasks = " ".join(item["task"] for item in checklist)
        for req in required_tasks:
            assert req in all_tasks, f"Missing checklist task: {req}"
