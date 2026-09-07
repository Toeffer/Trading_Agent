"""Tests for Phase 19O — two undefined-name bugs found by an external code
review (Fable), independently re-verified against this exact checkout
before any fix was written (2026-08-27).

Both bugs share a shape: a call to a name that does not exist anywhere in
the codebase, immediately swallowed by a bare `except Exception`, so the
NameError never surfaced -- the caller just silently got the except
clause's fallback value forever.

1. guard.py's _find_active_stop() (feeds live stop-breach detection) called
   read_approval_records(), which did not exist. Its primary lookup source
   (approval-records.jsonl) silently always fell through to its secondary
   source (order_submitted events) -- not dead, but silently degraded.
   A second, compounding bug in the same function: even with
   read_approval_records() defined, the stop_price lookup looked in
   proposal.get("stop_price") -- but create_approval_record()'s
   _ALLOWED_PROPOSAL_FIELDS never includes stop_price; it's stored under
   the record's "validation" subset instead. Both are fixed together.

2. ibkr_operator.py's _assess_kpi_hold_only_system_locked() was called at
   all 7 of the Phase 17F-17L planning-only-checkpoint call sites and
   defined nowhere. Fails safe (every call site already defaults to
   kpi_ok=False on exception -- never a false GO) but for the wrong
   reason, permanently, regardless of actual system state.
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

BRIDGE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BRIDGE_DIR))

import guard  # noqa: E402
from guard import read_approval_records, _find_active_stop  # noqa: E402

import ibkr_operator  # noqa: E402
from ibkr_operator import _assess_kpi_hold_only_system_locked  # noqa: E402


GUARD_SOURCE = (BRIDGE_DIR / "guard.py").read_text()
OPERATOR_SOURCE = (BRIDGE_DIR / "ibkr_operator.py").read_text()


def _approval_record(symbol="AAPL", action="BUY", status="approved", stop_price=180.0):
    return {
        "approval_id": "aprv_test",
        "status": status,
        "proposal": {"symbol": symbol, "action": action, "totalQuantity": 1,
                     "orderType": "MKT"},
        "validation": {"stop_price": stop_price, "entry_price": 200.0},
    }


# ---------------------------------------------------------------------------
# T1: read_approval_records() -- the function that did not exist
# ---------------------------------------------------------------------------

class TestReadApprovalRecords:
    def test_missing_file_returns_empty_list(self, tmp_path):
        missing = tmp_path / "approval-records.jsonl"
        assert read_approval_records(missing) == []

    def test_reads_jsonl_records_in_order(self, tmp_path):
        p = tmp_path / "approval-records.jsonl"
        rec1 = _approval_record(symbol="AAPL")
        rec2 = _approval_record(symbol="MSFT")
        p.write_text(json.dumps(rec1) + "\n" + json.dumps(rec2) + "\n")

        records = read_approval_records(p)

        assert len(records) == 2
        assert records[0]["proposal"]["symbol"] == "AAPL"
        assert records[1]["proposal"]["symbol"] == "MSFT"

    def test_malformed_line_skipped_not_raised(self, tmp_path):
        p = tmp_path / "approval-records.jsonl"
        good = _approval_record()
        p.write_text("{not valid json\n" + json.dumps(good) + "\n")

        records = read_approval_records(p)

        assert len(records) == 1
        assert records[0]["proposal"]["symbol"] == "AAPL"

    def test_blank_lines_skipped(self, tmp_path):
        p = tmp_path / "approval-records.jsonl"
        p.write_text("\n" + json.dumps(_approval_record()) + "\n\n")

        assert len(read_approval_records(p)) == 1

    def test_default_path_is_module_constant(self):
        # Mirrors read_guard_events()'s own default-path pattern exactly.
        assert read_approval_records.__defaults__ == (None,)


# ---------------------------------------------------------------------------
# T2: _find_active_stop() -- both bugs together, against a real (tmp,
# redirected) approval-records.jsonl.
# ---------------------------------------------------------------------------

class TestFindActiveStopReadsApprovalRecords:
    def test_finds_stop_from_validation_subset(self, tmp_path):
        p = tmp_path / "approval-records.jsonl"
        p.write_text(json.dumps(_approval_record(
            symbol="AAPL", action="BUY", status="approved", stop_price=185.5,
        )) + "\n")

        with patch.object(guard, "APPROVAL_RECORDS_PATH", p):
            stop = _find_active_stop("AAPL")

        assert stop == 185.5

    def test_no_longer_raises_or_silently_no_ops(self, tmp_path):
        """Before the fix, read_approval_records() didn't exist -- the call
        raised NameError, caught by _find_active_stop()'s own bare except,
        so this always silently returned None regardless of what was on
        disk. Prove that no longer happens: a real, well-formed record on
        disk is now actually found."""
        p = tmp_path / "approval-records.jsonl"
        p.write_text(json.dumps(_approval_record(stop_price=199.99)) + "\n")

        with patch.object(guard, "APPROVAL_RECORDS_PATH", p):
            stop = _find_active_stop("AAPL")

        assert stop is not None, (
            "_find_active_stop() still isn't reading approval records -- "
            "the NameError bug (or an equivalent silent failure) survived"
        )
        assert stop == 199.99

    def test_only_approved_status_considered(self, tmp_path):
        p = tmp_path / "approval-records.jsonl"
        p.write_text(json.dumps(_approval_record(status="pending", stop_price=150.0)) + "\n")

        with patch.object(guard, "APPROVAL_RECORDS_PATH", p):
            stop = _find_active_stop("AAPL")

        assert stop is None

    def test_only_buy_action_considered(self, tmp_path):
        p = tmp_path / "approval-records.jsonl"
        p.write_text(json.dumps(_approval_record(action="SELL", stop_price=150.0)) + "\n")

        with patch.object(guard, "APPROVAL_RECORDS_PATH", p):
            stop = _find_active_stop("AAPL")

        assert stop is None

    def test_most_recent_matching_record_wins(self, tmp_path):
        p = tmp_path / "approval-records.jsonl"
        older = _approval_record(stop_price=100.0)
        newer = _approval_record(stop_price=222.0)
        p.write_text(json.dumps(older) + "\n" + json.dumps(newer) + "\n")

        with patch.object(guard, "APPROVAL_RECORDS_PATH", p):
            stop = _find_active_stop("AAPL")

        assert stop == 222.0

    def test_falls_back_to_events_when_no_approval_record_matches(self, tmp_path):
        """Pre-existing fallback behavior (source 2 in the docstring) must
        still work when the approval-records lookup finds nothing."""
        p = tmp_path / "approval-records.jsonl"
        p.write_text("")  # empty -- no records

        fake_events = [{
            "event_type": "order_submitted", "symbol": "AAPL", "action": "BUY",
            "stop_price": 175.25,
        }]

        with patch.object(guard, "APPROVAL_RECORDS_PATH", p), \
             patch("guard.read_guard_events", return_value=fake_events):
            stop = _find_active_stop("AAPL")

        assert stop == 175.25


class TestGuardSourceRegression:
    def test_read_approval_records_defined(self):
        assert "def read_approval_records(" in GUARD_SOURCE

    def test_find_active_stop_reads_validation_not_proposal_for_stop_price(self):
        idx = GUARD_SOURCE.index("def _find_active_stop(")
        snippet = GUARD_SOURCE[idx: idx + 2200]
        assert 'validation.get("stop_price")' in snippet, (
            "_find_active_stop() must read stop_price from the record's "
            "validation subset -- create_approval_record() never puts it "
            "under proposal"
        )
        assert 'sp = proposal.get("stop_price")' not in snippet, (
            "the old, always-None field lookup survived the fix"
        )


# ---------------------------------------------------------------------------
# T3: _assess_kpi_hold_only_system_locked() -- the function that did not
# exist, called at all 7 Phase 17F-17L call sites.
# ---------------------------------------------------------------------------

def _kpi_result(verdict="HOLD", checks=("autonomy_level_zero", "system_locked")):
    return {
        "verdict": verdict,
        "blockers": [{"severity": "HOLD", "check": c} for c in checks],
        "blocker_count": len(checks),
    }


class TestAssessKpiHoldOnlySystemLocked:
    def test_true_when_hold_with_only_expected_blockers(self):
        with patch("ibkr_operator.run_kpi", return_value=_kpi_result(
                verdict="HOLD", checks=("autonomy_level_zero", "system_locked"))):
            result = _assess_kpi_hold_only_system_locked(datetime.now(timezone.utc))

        assert result["kpi_hold_only_system_locked"] is True
        assert result["kpi_verdict"] == "HOLD"
        assert result["kpi_unexpected_blockers"] == []

    def test_true_when_hold_with_only_system_locked(self):
        with patch("ibkr_operator.run_kpi", return_value=_kpi_result(
                verdict="HOLD", checks=("system_locked",))):
            result = _assess_kpi_hold_only_system_locked(datetime.now(timezone.utc))

        assert result["kpi_hold_only_system_locked"] is True

    def test_false_when_system_locked_not_present(self):
        """A HOLD blocked only by autonomy_level_zero, with system_locked
        absent, is not the condition this helper confirms."""
        with patch("ibkr_operator.run_kpi", return_value=_kpi_result(
                verdict="HOLD", checks=("autonomy_level_zero",))):
            result = _assess_kpi_hold_only_system_locked(datetime.now(timezone.utc))

        assert result["kpi_hold_only_system_locked"] is False

    def test_false_when_unexpected_blocker_present(self):
        with patch("ibkr_operator.run_kpi", return_value=_kpi_result(
                verdict="HOLD",
                checks=("system_locked", "ibkr_not_connected"))):
            result = _assess_kpi_hold_only_system_locked(datetime.now(timezone.utc))

        assert result["kpi_hold_only_system_locked"] is False
        assert "ibkr_not_connected" in result["kpi_unexpected_blockers"]

    def test_false_when_verdict_is_go(self):
        with patch("ibkr_operator.run_kpi", return_value=_kpi_result(
                verdict="GO", checks=())):
            result = _assess_kpi_hold_only_system_locked(datetime.now(timezone.utc))

        assert result["kpi_hold_only_system_locked"] is False

    def test_false_when_verdict_is_no_go(self):
        with patch("ibkr_operator.run_kpi", return_value=_kpi_result(
                verdict="NO-GO", checks=("system_locked",))):
            result = _assess_kpi_hold_only_system_locked(datetime.now(timezone.utc))

        assert result["kpi_hold_only_system_locked"] is False

    def test_fails_safe_when_run_kpi_raises(self):
        """No longer a NameError -- but the function must still fail safe
        (never a false True) if the live KPI dashboard itself errors."""
        with patch("ibkr_operator.run_kpi", side_effect=RuntimeError("bridge unreachable")):
            result = _assess_kpi_hold_only_system_locked(datetime.now(timezone.utc))

        assert result["kpi_hold_only_system_locked"] is False
        assert result["kpi_section"]["error"] is not None

    def test_does_not_raise_nameerror(self):
        """The literal original bug: calling this must not raise at all."""
        with patch("ibkr_operator.run_kpi", return_value=_kpi_result()):
            try:
                _assess_kpi_hold_only_system_locked(datetime.now(timezone.utc))
            except NameError:
                pytest.fail("_assess_kpi_hold_only_system_locked is still undefined")


class TestOperatorSourceRegression:
    def test_function_defined(self):
        assert "def _assess_kpi_hold_only_system_locked(" in OPERATOR_SOURCE

    def test_all_seven_call_sites_still_present(self):
        """Sanity: confirm the call sites this was written for are still
        there and still call it the same way (now_utc) -- this fix adds
        the missing function, it does not touch any of the 7 callers."""
        count = OPERATOR_SOURCE.count("_assess_kpi_hold_only_system_locked(now_utc)")
        assert count == 7, (
            f"Expected 7 call sites (Phase 17F-17L), found {count} -- "
            f"either a caller changed or this count needs updating"
        )
