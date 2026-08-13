"""Tests for Phase 19H — checklist reconciliation_pass key-name bug (2026-08-13).

ibkr_operator._build_summary() read recon.get("pass", recon.get("ok", False))
to populate summary["monitoring"]["reconciliation_pass"]. But /monitor/
reconciliation (monitor.reconcile_snapshot(), returned verbatim by bridge.py's
/monitor/reconciliation endpoint) has only ever returned its verdict under the
key "passed". Neither "pass" nor "ok" has ever existed in the real response,
so reconciliation_pass silently defaulted to False on every checklist run,
regardless of the actual reconciliation state -- discovered live when a real
/monitor/reconciliation response showed "passed": true with all six
sub-checks true, while the same-moment checklist run reported
reconciliation_pass: false.

_build_summary() is a pure function over a plain dict (no HTTP involved), so
these tests call it directly with minimal fixtures.
"""

import sys
from pathlib import Path

BRIDGE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BRIDGE_DIR))

from ibkr_operator import _build_summary  # noqa: E402


def _minimal_data(**overrides) -> dict:
    """The minimal `data` dict _build_summary() needs, with everything empty
    except whatever the test overrides."""
    base = {
        "health": {},
        "readiness": {},
        "rth": {},
        "drift": {},
        "open_orders": {},
        "reconciliation": {},
        "alerts": {},
        "status": {},
        "audit_bundle": {},
        "audit_verify": {},
        "release_latest": {},
        "positions": {},
        "account": {},
    }
    base.update(overrides)
    return base


class TestReconciliationPassReadsRealKey:
    def test_passed_true_is_honoured(self):
        """The exact real-world shape: reconcile_snapshot() returns "passed"."""
        data = _minimal_data(reconciliation={
            "passed": True,
            "checks": {
                "trade_count_match": True,
                "no_orphan_submitted": True,
                "no_orphan_records": True,
                "guard_state_healthy": True,
                "events_log_readable": True,
                "submitted_approvals_file_readable": True,
            },
        })
        summary = _build_summary(data)
        assert summary["monitoring"]["reconciliation_pass"] is True

    def test_passed_false_is_honoured(self):
        data = _minimal_data(reconciliation={"passed": False, "checks": {}})
        summary = _build_summary(data)
        assert summary["monitoring"]["reconciliation_pass"] is False

    def test_missing_reconciliation_response_defaults_false(self):
        """No response at all (bridge unreachable) — fail closed, not a crash."""
        data = _minimal_data(reconciliation={})
        summary = _build_summary(data)
        assert summary["monitoring"]["reconciliation_pass"] is False

    def test_legacy_pass_key_still_honoured(self):
        """Defensive fallback — if some other endpoint ever used "pass"."""
        data = _minimal_data(reconciliation={"pass": True})
        summary = _build_summary(data)
        assert summary["monitoring"]["reconciliation_pass"] is True

    def test_legacy_ok_key_still_honoured(self):
        data = _minimal_data(reconciliation={"ok": True})
        summary = _build_summary(data)
        assert summary["monitoring"]["reconciliation_pass"] is True

    def test_passed_takes_priority_over_stale_pass_key(self):
        """If both were ever present, the real key wins."""
        data = _minimal_data(reconciliation={"passed": True, "pass": False})
        summary = _build_summary(data)
        assert summary["monitoring"]["reconciliation_pass"] is True
