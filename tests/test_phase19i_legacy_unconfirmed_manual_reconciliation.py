"""Tests for Phase 19I — legacy_unconfirmed respects manual reconciliations (2026-08-13).

guard.reconcile_approvals_on_startup() re-flagged the same legacy
order_submitted event (no ibkr_metadata, SELL) as "legacy_unconfirmed" on
every single bridge startup, forever -- even after a human had already
manually reconciled that exact (order_id, symbol) via
monitor.append_manual_reconciliation(). Discovered live: order_id=24/AAPL
(approval aprv_d39f1f84) was confirmed NotFoundInIBKR/filled=0.0 by
Werner-H4.1 on 2026-06-11, yet still appeared identically in
startup_reconciliation's legacy_unconfirmed list on every restart through
2026-08-13 -- ~32,000 repeated log lines because the two never talked to
each other.

Mocking convention matches test_phase19g_weekly_loss_halt_rollover.py /
test_phase19f_position_drift_reconcile.py: patch guard's module-level path
constants to tmp_path, patch out the unrelated persistence side effects
(_load_submitted_approvals etc.) so only legacy_unconfirmed detection is
under test.
"""

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

BRIDGE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BRIDGE_DIR))

import guard  # noqa: E402


def _write_events(path, events):
    path.write_text("\n".join(json.dumps(e) for e in events) + "\n")


def _write_manual_reconciliations(path, records):
    path.write_text("\n".join(json.dumps(r) for r in records) + ("\n" if records else ""))


_LEGACY_AAPL_SELL_EVENT = {
    "event_id": "evt-0024", "event_type": "order_submitted",
    "symbol": "AAPL", "action": "SELL", "order_id": 24,
    "approval_id": "aprv_d39f1f84-b8fd-4d6a-9a99-0485b677dd4f",
    "ibkr_metadata": None,
    "timestamp_utc": "2026-06-09T10:00:00Z",
}

_MANUAL_RECONCILIATION_FOR_ORDER_24 = {
    "order_id": 24, "permId": 1529342545, "symbol": "AAPL", "action": "SELL",
    "final_status": "NotFoundInIBKR", "filled": 0.0, "remaining": 0.0,
    "verified_by": "Werner-H4.1",
    "evidence": "Phase H4.1 stale reconciliation: no AAPL position, event age >48h",
    "verified_at_utc": "2026-06-11T15:02:40.994932+00:00",
    "status": "manual_terminal",
}


def _run_reconcile(tmp_path, events, manual_records):
    events_path = tmp_path / "guard-events.jsonl"
    _write_events(events_path, events)
    manual_path = tmp_path / "order-reconciliations.jsonl"
    _write_manual_reconciliations(manual_path, manual_records)

    # load_guard_state()/save_guard_state_atomic() are mocked directly rather
    # than redirecting GUARD_STATE_PATH -- guard-state.json is an H1-protected
    # path (Phase H1.2), and whether an unmocked write there is exempt
    # depends on module-global H1 startup state left over from whatever else
    # ran earlier in the same pytest process. That's exactly what broke this
    # test in CI while passing locally: order-dependent, not deterministic.
    # This suite only cares about legacy_unconfirmed detection, not guard
    # state, so mock both calls out entirely.
    with patch("guard.GUARD_EVENTS_PATH", events_path), \
         patch("guard._load_submitted_approvals", return_value=set()), \
         patch("guard._save_submitted_approvals"), \
         patch("guard._load_active_approvals"), \
         patch("guard._save_active_approvals"), \
         patch("guard.append_guard_event"), \
         patch("guard.load_guard_state", return_value={"daily_trade_count": 0}), \
         patch("guard.save_guard_state_atomic"), \
         patch("guard.APPROVAL_RECORDS_PATH", tmp_path / "approval-records.jsonl"), \
         patch("monitor.MANUAL_ORDER_RECON_PATH", manual_path):
        return guard.reconcile_approvals_on_startup()


class TestLegacyUnconfirmedWithoutManualReconciliation:
    def test_unreconciled_legacy_sell_is_still_flagged(self, tmp_path):
        """Baseline: with no manual reconciliation on file, the legacy event
        is (correctly) still flagged -- this is the pre-fix behavior,
        preserved for the genuinely-unresolved case."""
        result = _run_reconcile(tmp_path, [_LEGACY_AAPL_SELL_EVENT], manual_records=[])

        assert len(result["legacy_unconfirmed"]) == 1
        assert result["legacy_unconfirmed"][0]["order_id"] == 24
        assert result["legacy_unconfirmed"][0]["symbol"] == "AAPL"


class TestLegacyUnconfirmedRespectsManualReconciliation:
    def test_manually_reconciled_order_stops_being_flagged(self, tmp_path):
        """The actual fix: once a human has manually reconciled this exact
        (order_id, symbol), it must not keep resurfacing on every startup."""
        result = _run_reconcile(
            tmp_path, [_LEGACY_AAPL_SELL_EVENT],
            manual_records=[_MANUAL_RECONCILIATION_FOR_ORDER_24],
        )

        assert result["legacy_unconfirmed"] == []

    def test_reconciliation_for_different_order_id_does_not_suppress(self, tmp_path):
        """A manual reconciliation for a different order must not
        accidentally suppress an unrelated, still-open legacy event."""
        other_reconciliation = dict(_MANUAL_RECONCILIATION_FOR_ORDER_24, order_id=99)
        result = _run_reconcile(
            tmp_path, [_LEGACY_AAPL_SELL_EVENT],
            manual_records=[other_reconciliation],
        )

        assert len(result["legacy_unconfirmed"]) == 1

    def test_reconciliation_for_same_order_id_different_symbol_does_not_suppress(self, tmp_path):
        """order_id alone isn't the key -- (order_id, symbol) must both match."""
        other_symbol_reconciliation = dict(_MANUAL_RECONCILIATION_FOR_ORDER_24, symbol="MSFT")
        result = _run_reconcile(
            tmp_path, [_LEGACY_AAPL_SELL_EVENT],
            manual_records=[other_symbol_reconciliation],
        )

        assert len(result["legacy_unconfirmed"]) == 1

    def test_manual_reconciliations_unreadable_fails_open_to_old_behavior(self, tmp_path):
        """If load_manual_reconciliations() can't be read for any reason,
        fail open to the pre-fix behavior (still flag it) rather than
        crashing startup reconciliation."""
        events_path = tmp_path / "guard-events.jsonl"
        _write_events(events_path, [_LEGACY_AAPL_SELL_EVENT])

        with patch("guard.GUARD_EVENTS_PATH", events_path), \
             patch("guard._load_submitted_approvals", return_value=set()), \
             patch("guard._save_submitted_approvals"), \
             patch("guard._load_active_approvals"), \
             patch("guard._save_active_approvals"), \
             patch("guard.append_guard_event"), \
             patch("guard.load_guard_state", return_value={"daily_trade_count": 0}), \
             patch("guard.save_guard_state_atomic"), \
             patch("guard.APPROVAL_RECORDS_PATH", tmp_path / "approval-records.jsonl"), \
             patch("monitor.load_manual_reconciliations", side_effect=RuntimeError("disk error")):
            result = guard.reconcile_approvals_on_startup()

        assert len(result["legacy_unconfirmed"]) == 1
