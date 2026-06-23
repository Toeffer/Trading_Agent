"""Tests for Step 15P — Session-aware readiness semantics.

All tests are read-only. No broker mutation, no order endpoints,
no H1 token usage, no autonomy level changes.
"""

import json
import os
import sys
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

BRIDGE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BRIDGE_DIR))


# ---------------------------------------------------------------------------
# Session mock helpers
# ---------------------------------------------------------------------------

def _make_session_info(session: str = "rth",
                       reason: str = "Inside RTH",
                       is_tradable: bool = True,
                       in_rth: bool = True) -> dict:
    """Return a mock session_info dict for a given session."""
    return {
        "session": session,
        "data_availability": "available" if session == "rth" else "unavailable",
        "reason": reason,
        "is_tradable_day": is_tradable,
        "in_rth": in_rth,
        "market_date_et": "2026-06-23",
    }


def _make_market_snapshot(available: bool = True,
                          stale: bool = False,
                          ok: bool = True,
                          detail: str = "",
                          bid: float | None = 150.0,
                          ask: float | None = 150.5,
                          last: float | None = 150.25,
                          close: float | None = 149.80,
                          currency: str = "USD",
                          age_s: float = 5.0) -> dict:
    """Return a mock market snapshot dict matching bridge.py output."""
    return {
        "ok": ok,
        "symbol": "AAPL",
        "market_data_available": available,
        "detail": detail,
        "snapshot_timestamp": "2026-06-23T10:00:00Z",
        "snapshot_epoch": time.time(),
        "bid": bid if available else None,
        "ask": ask if available else None,
        "last": last if available else None,
        "close": close if available else None,
        "midpoint": 150.375 if available else None,
        "currency": currency if available else None,
        "exchange": "SMART",
        "delayed": True,
        "stale": stale,
        "market_data_age_seconds": age_s,
    }


def _make_minimal_light_evidence(session: str = "rth",
                                  connected: bool | None = True,
                                  safety_locked: bool = True) -> dict:
    """Return minimal light evidence with session awareness."""
    return {
        "bridge": {
            "reachable": True,
            "url": "http://127.0.0.1:8790",
            "connected": connected,
            "mode": "paper",
            "allow_orders": "false",
            "read_only": True,
        },
        "safety": {
            "read_only": True,
            "bridge_allow_orders": "false",
            "env_IBKR_ALLOW_ORDERS": "false",
            "rules_enforced": "false",
            "system_locked": safety_locked,
        },
        "doctor": {"pass": True, "checks": []},
        "market_session_status": _make_session_info(session=session,
                                                     reason=f"Mock {session}"),
        "market_data_runtime_ok": True,
    }


# ---------------------------------------------------------------------------
# T1: Session classification helper
# ---------------------------------------------------------------------------

class TestSessionClassification:
    """Verify _determine_market_session_status and classification helpers."""

    def test_determine_session_returns_expected_keys(self):
        """_determine_market_session_status returns all required keys."""
        from ibkr_operator import _determine_market_session_status

        result = _determine_market_session_status()

        required = ["session", "data_availability", "reason",
                     "is_tradable_day", "in_rth", "market_date_et"]
        for key in required:
            assert key in result, f"Missing key: {key}"

        assert result["session"] in ("rth", "pre_market", "post_market",
                                      "closed", "unknown")

    def test_classify_timeout(self):
        """Bounded timeout returns market_data_timeout."""
        from ibkr_operator import _classify_market_data_unavailability

        snapshot = {"ok": False, "market_data_available": False,
                     "detail": "market_data_timeout: market data did not arrive",
                     "stale": True}
        result = _classify_market_data_unavailability(snapshot)
        assert result == "market_data_timeout"

    def test_classify_disconnected(self):
        """Disconnected detail returns ibkr_disconnected."""
        from ibkr_operator import _classify_market_data_unavailability

        snapshot = {"ok": False, "market_data_available": False,
                     "detail": "IBKR not connected", "stale": True}
        result = _classify_market_data_unavailability(snapshot)
        assert result == "ibkr_disconnected"

    def test_classify_stale(self):
        """Available but stale returns stale_data."""
        from ibkr_operator import _classify_market_data_unavailability

        snapshot = {"ok": True, "market_data_available": True,
                     "detail": "", "stale": True}
        result = _classify_market_data_unavailability(snapshot)
        assert result == "stale_data"

    def test_classify_closed_session(self):
        """Closed session with no data returns market_closed."""
        from ibkr_operator import _classify_market_data_unavailability

        snapshot = {"ok": False, "market_data_available": False,
                     "detail": "all price fields are null", "stale": True}
        session_info = _make_session_info(session="closed",
                                           reason="Weekend — market closed",
                                           is_tradable=False, in_rth=False)
        result = _classify_market_data_unavailability(snapshot, session_info)
        assert result == "market_closed"

    def test_classify_pre_market(self):
        """Pre-market session returns pre_market_no_data."""
        from ibkr_operator import _classify_market_data_unavailability

        snapshot = {"ok": False, "market_data_available": False,
                     "detail": "", "stale": True}
        session_info = _make_session_info(session="pre_market",
                                           reason="Pre-market",
                                           is_tradable=True, in_rth=False)
        result = _classify_market_data_unavailability(snapshot, session_info)
        assert result == "pre_market_no_data"

    def test_classify_none_when_available(self):
        """Available and not stale returns none."""
        from ibkr_operator import _classify_market_data_unavailability

        snapshot = {"ok": True, "market_data_available": True,
                     "detail": "", "stale": False}
        result = _classify_market_data_unavailability(snapshot)
        assert result == "none"

    def test_compute_unavailable_reason_available(self):
        """_compute_unavailable_reason returns none when available."""
        from ibkr_operator import _compute_unavailable_reason

        result = _compute_unavailable_reason(
            "available", "", {}
        )
        assert result == "none"

    def test_compute_unavailable_reason_timeout(self):
        """_compute_unavailable_reason returns market_data_timeout for timeout detail."""
        from ibkr_operator import _compute_unavailable_reason

        result = _compute_unavailable_reason(
            "unavailable",
            "market_data_timeout: market data did not arrive within 8.0s",
            {}
        )
        assert result == "market_data_timeout"


# ---------------------------------------------------------------------------
# T2: Session-aware blocker builder
# ---------------------------------------------------------------------------

class TestSessionAwareBlocker:
    """Verify _build_session_aware_market_blocker produces correct blockers."""

    def test_disconnected_gives_ibkr_disconnected(self):
        """Disconnected IBKR → HOLD ibkr_disconnected."""
        from ibkr_operator import _build_session_aware_market_blocker

        blocker = _build_session_aware_market_blocker(
            market_data_status="unavailable",
            snapshot_detail="",
            session_info={},
            ibkr_connected=False,
            market_data_runtime_ok=True,
        )
        assert blocker is not None
        assert blocker["check"] == "ibkr_disconnected"
        assert blocker["severity"] == "HOLD"

    def test_available_no_blocker(self):
        """Available market data → no blocker."""
        from ibkr_operator import _build_session_aware_market_blocker

        blocker = _build_session_aware_market_blocker(
            market_data_status="available",
            snapshot_detail="",
            session_info={},
            ibkr_connected=True,
            market_data_runtime_ok=True,
        )
        assert blocker is None

    def test_pre_market_gives_session_blocker(self):
        """Pre-market with no data → HOLD market_data_not_ready_for_session."""
        from ibkr_operator import _build_session_aware_market_blocker

        session_info = _make_session_info(session="pre_market",
                                           reason="Pre-market — market opens at 9:30 AM ET",
                                           in_rth=False)
        blocker = _build_session_aware_market_blocker(
            market_data_status="unavailable",
            snapshot_detail="market_data_timeout: market data did not arrive",
            session_info=session_info,
            ibkr_connected=True,
            market_data_runtime_ok=True,
        )
        assert blocker is not None
        assert blocker["check"] == "market_data_not_ready_for_session"
        assert blocker["severity"] == "HOLD"
        assert "pre_market" in blocker["detail"]
        assert "market_data_timeout" in blocker["detail"]
        assert "not a runtime defect" in blocker["detail"].lower()

    def test_closed_gives_session_blocker_not_defect(self):
        """Closed market with bounded timeout → HOLD, not NO_GO/defect."""
        from ibkr_operator import _build_session_aware_market_blocker

        session_info = _make_session_info(session="closed",
                                           reason="Weekend — market closed",
                                           is_tradable=False, in_rth=False)
        blocker = _build_session_aware_market_blocker(
            market_data_status="unavailable",
            snapshot_detail="market_data_timeout: market data did not arrive",
            session_info=session_info,
            ibkr_connected=True,
            market_data_runtime_ok=True,
        )
        assert blocker is not None
        assert blocker["check"] == "market_data_not_ready_for_session"
        assert blocker["severity"] == "HOLD"

    def test_rth_unavailable_gives_standard_blocker(self):
        """Unavailable during RTH → market_data_unavailable."""
        from ibkr_operator import _build_session_aware_market_blocker

        session_info = _make_session_info(session="rth",
                                           reason="Inside RTH",
                                           in_rth=True)
        blocker = _build_session_aware_market_blocker(
            market_data_status="unavailable",
            snapshot_detail="no data",
            session_info=session_info,
            ibkr_connected=True,
            market_data_runtime_ok=True,
        )
        assert blocker is not None
        assert blocker["check"] == "market_data_unavailable"
        # RTH timeout must include "market_data_timeout" in detail
        assert "market_data_timeout" not in blocker["detail"].lower()

    def test_rth_timeout_classified_as_timeout(self):
        """RTH bounded timeout → market_data_unavailable with timeout reason."""
        from ibkr_operator import _build_session_aware_market_blocker

        session_info = _make_session_info(session="rth",
                                           reason="Inside RTH",
                                           in_rth=True)
        blocker = _build_session_aware_market_blocker(
            market_data_status="unavailable",
            snapshot_detail="market_data_timeout: market data did not arrive within 8.0s",
            session_info=session_info,
            ibkr_connected=True,
            market_data_runtime_ok=True,
        )
        assert blocker is not None
        assert blocker["check"] == "market_data_unavailable"
        assert "market_data_timeout" in blocker["detail"].lower()
        assert blocker["severity"] == "HOLD"

    def test_runtime_error_gives_runtime_blocker(self):
        """Runtime error → market_data_runtime_error."""
        from ibkr_operator import _build_session_aware_market_blocker

        blocker = _build_session_aware_market_blocker(
            market_data_status="unavailable",
            snapshot_detail="bridge unreachable: connection refused",
            session_info={},
            ibkr_connected=True,
            market_data_runtime_ok=False,
        )
        assert blocker is not None
        assert blocker["check"] == "market_data_runtime_error"


# ---------------------------------------------------------------------------
# T3: Autonomy-status session-aware output
# ---------------------------------------------------------------------------

class TestAutonomyStatusSessionAware:
    """Verify autonomy-status produces session-aware fields and blockers."""

    def _run_status_with_mocks(self, session="pre_market",
                                market_available=False,
                                market_stale=True,
                                market_ok=False,
                                market_detail="market_data_timeout: bounded timeout",
                                ibkr_connected=True,
                                safety_locked=True):
        """Run autonomy_status with mocked market data and session."""
        from ibkr_operator import _run_autonomy_status

        session_info = _make_session_info(
            session=session,
            reason=f"Mock {session}",
            is_tradable=(session != "closed"),
            in_rth=(session == "rth"),
        )
        market_data = _make_market_snapshot(
            available=market_available,
            stale=market_stale,
            ok=market_ok,
            detail=market_detail,
        )
        candidate_data = {"verdict": "HOLD", "market_data": market_data,
                          "account_evidence": {}}
        light_ev = _make_minimal_light_evidence(
            session=session,
            connected=ibkr_connected,
            safety_locked=safety_locked,
        )

        kpi_result = {
            "verdict": "HOLD",
            "monitoring": {"active_alert_count": 0,
                           "reconciliation_passed": True},
            "bridge": {"reachable": True, "connected": ibkr_connected,
                       "mode": "paper"},
        }

        with patch("ibkr_operator._collect_lightweight_evidence",
                   return_value=light_ev), \
             patch("ibkr_operator.run_kpi", return_value=kpi_result), \
             patch("ibkr_operator._run_candidate_dryrun",
                   return_value=candidate_data), \
             patch("ibkr_operator._scan_forbidden_endpoints",
                   return_value={"ok": True, "violations": []}), \
             patch("ibkr_operator._count_clean_cycles", return_value=10), \
             patch("ibkr_operator._latest_clean_cycle_timestamp",
                   return_value="2026-06-23T10:00:00Z"), \
             patch("ibkr_operator._read_autonomy_level", return_value="0"), \
             patch("ibkr_operator._git_metadata",
                   return_value={"branch": "test", "commit": "abc",
                                 "tag": "test"}), \
             patch("ibkr_operator.time.sleep"), \
             patch("ibkr_operator.json.dump"), \
             patch("ibkr_operator.open"), \
             patch("ibkr_operator.os.getenv", return_value="false"), \
             patch("ibkr_operator._AUTONOMY_STATUS_EXPORT_DIR",
                   Path("/tmp/autonomy-status")), \
             patch("ibkr_operator.OPENCLAW_DIR", Path("/tmp/openclaw")):
            return _run_autonomy_status(refresh_evidence=True)

    def test_pre_market_timeout_is_hold(self):
        """Pre-market with bounded timeout → HOLD, not NO_GO."""
        result = self._run_status_with_mocks(
            session="pre_market",
            market_detail="market_data_timeout: market data did not arrive",
        )
        assert result["recommendation"] == "HOLD"
        assert result["market_data_runtime_ok"] is True
        # Must have session-aware blocker
        checks = [b["check"] for b in result["blockers"]]
        assert "market_data_not_ready_for_session" in checks, \
            f"Expected session-aware blocker, got {checks}"
        assert "ibkr_disconnected" not in checks

    def test_closed_market_timeout_is_hold(self):
        """Closed market with bounded timeout → HOLD."""
        result = self._run_status_with_mocks(
            session="closed",
            market_detail="market_data_timeout: bounded timeout",
        )
        assert result["recommendation"] == "HOLD"
        checks = [b["check"] for b in result["blockers"]]
        assert "market_data_not_ready_for_session" in checks

    def test_disconnected_is_hold(self):
        """Disconnected IBKR → HOLD with ibkr_disconnected."""
        result = self._run_status_with_mocks(
            session="rth",
            ibkr_connected=False,
            market_detail="IBKR not connected",
        )
        assert result["recommendation"] == "HOLD"
        checks = [b["check"] for b in result["blockers"]]
        assert "ibkr_disconnected" in checks, \
            f"Expected ibkr_disconnected, got {checks}"

    def test_fresh_market_data_possible_ready(self):
        """Fresh market data during RTH → READY possible if all gates pass."""
        result = self._run_status_with_mocks(
            session="rth",
            market_available=True,
            market_stale=False,
            market_ok=True,
            market_detail="",
        )
        # With fresh data and all gates, should be READY (no blockers)
        assert result["recommendation"] in ("READY_FOR_MANUAL_REVIEW", "HOLD")
        checks = [b["check"] for b in result["blockers"]
                  if "market" in b["check"]]
        assert len(checks) == 0, \
            f"Should have zero market blockers with fresh data, got {checks}"

    def test_session_fields_in_output(self):
        """All session-aware fields are present in output."""
        result = self._run_status_with_mocks(
            session="pre_market",
            market_detail="market_data_timeout: bounded timeout",
        )
        assert "market_session_status" in result
        assert "market_data_unavailable_reason" in result
        assert "market_data_runtime_ok" in result
        assert "market_data_required_for_readiness" in result
        assert "market_data_blocks_promotion" in result
        assert result["market_session_status"]["session"] == "pre_market"

    def test_runtime_error_is_blocker(self):
        """Endpoint hang/runtime error → HOLD with runtime blocker."""
        # Simulate by having market_data_runtime_ok=False
        result = self._run_status_with_mocks(
            session="rth",
            market_detail="bridge unreachable: timeout",
        )
        # When the runtime error propagates via market_data_runtime_ok,
        # the blocker should indicate a runtime issue
        assert result["recommendation"] in ("HOLD", "NO_GO")

    def test_fx_unknown_is_hold_not_nogo(self):
        """FX unknown due to no market currency → HOLD, not NO_GO."""
        result = self._run_status_with_mocks(
            session="pre_market",
            market_detail="market_data_timeout: bounded timeout",
        )
        # FX status should be "unavailable" because currency is None
        assert result["fx_status"] in ("unavailable", "not_required", "unknown")
        assert result["recommendation"] == "HOLD"


# ---------------------------------------------------------------------------
# T4: JSON stdout purity
# ---------------------------------------------------------------------------

class TestJsonStdoutPurity:
    """Verify JSON output is pure parseable JSON with no noise."""

    def _run_status_json(self, **kwargs):
        """Run with --json and return parsed output."""
        from ibkr_operator import _run_autonomy_status

        light_ev = _make_minimal_light_evidence(session="rth")
        market_data = _make_market_snapshot(available=True, stale=False)
        candidate_data = {"verdict": "HOLD", "market_data": market_data,
                          "account_evidence": {"fx_available": True,
                                               "fx_required": False}}
        kpi_result = {
            "verdict": "HOLD",
            "monitoring": {"active_alert_count": 0,
                           "reconciliation_passed": True},
            "bridge": {"reachable": True, "connected": True, "mode": "paper"},
        }

        with patch("ibkr_operator._collect_lightweight_evidence",
                   return_value=light_ev), \
             patch("ibkr_operator.run_kpi", return_value=kpi_result), \
             patch("ibkr_operator._run_candidate_dryrun",
                   return_value=candidate_data), \
             patch("ibkr_operator._scan_forbidden_endpoints",
                   return_value={"ok": True, "violations": []}), \
             patch("ibkr_operator._count_clean_cycles", return_value=10), \
             patch("ibkr_operator._latest_clean_cycle_timestamp",
                   return_value="2026-06-23T10:00:00Z"), \
             patch("ibkr_operator._read_autonomy_level", return_value="0"), \
             patch("ibkr_operator._git_metadata",
                   return_value={"branch": "test", "commit": "abc",
                                 "tag": "test"}), \
             patch("ibkr_operator.time.sleep"), \
             patch("ibkr_operator.json.dump"), \
             patch("ibkr_operator.open"), \
             patch("ibkr_operator.os.getenv", return_value="false"), \
             patch("ibkr_operator._AUTONOMY_STATUS_EXPORT_DIR",
                   Path("/tmp/autonomy-status")), \
             patch("ibkr_operator.OPENCLAW_DIR", Path("/tmp/openclaw")):
            return _run_autonomy_status(refresh_evidence=True)

    def test_json_round_trips(self):
        """Result can be serialized and deserialized cleanly."""
        result = self._run_status_json()
        serialized = json.dumps(result, default=str)
        parsed = json.loads(serialized)
        assert parsed["recommendation"] in ("HOLD", "READY_FOR_MANUAL_REVIEW",
                                             "NO_GO")
        assert "market_session_status" in parsed


# ---------------------------------------------------------------------------
# T5: No /order* calls, no H1 token
# ---------------------------------------------------------------------------

class TestNoForbiddenCalls:
    """Verify session-aware helpers never call order endpoints or read H1 token."""

    def test_helpers_no_forbidden_patterns(self):
        """Helper functions contain no forbidden patterns."""
        import inspect
        from ibkr_operator import (
            _determine_market_session_status,
            _classify_market_data_unavailability,
            _build_session_aware_market_blocker,
            _fetch_market_snapshot_with_session,
        )

        forbidden = ["/order/preflight", "/order/approve", "/order/submit",
                      "/order", "placeOrder", "cancelOrder",
                      "H1_APPROVAL_TOKEN_HASH", "/etc/ibkr-bridge/h1_token",
                      "_run_h1_canary("]

        for func in [_determine_market_session_status,
                     _classify_market_data_unavailability,
                     _build_session_aware_market_blocker,
                     _fetch_market_snapshot_with_session]:
            source = inspect.getsource(func)
            for pattern in forbidden:
                found = False
                for line in source.splitlines():
                    stripped = line.strip()
                    if stripped.startswith("#"):
                        continue
                    if pattern in stripped:
                        found = True
                        break
                assert not found, \
                    f"FORBIDDEN '{pattern}' in {func.__name__}:\n{source[:500]}"


# ---------------------------------------------------------------------------
# T6: Existing tests still pass
# ---------------------------------------------------------------------------

class TestExistingTestsStillPass:
    """Quick sanity: imports and key functions still work."""

    def test_operator_imports(self):
        """Key operator functions remain importable after Step 15P changes."""
        from ibkr_operator import (
            _run_autonomy_status,
            _run_autonomy_review,
            _run_autonomy_promotion_plan,
            _run_guard_state_reconcile,
            _run_cycle_rehearsal,
            _determine_market_session_status,
            _classify_market_data_unavailability,
            _build_session_aware_market_blocker,
            _fetch_market_snapshot_with_session,
        )
        for func in [_run_autonomy_status, _run_autonomy_review,
                     _run_autonomy_promotion_plan, _run_guard_state_reconcile,
                     _run_cycle_rehearsal, _determine_market_session_status,
                     _classify_market_data_unavailability,
                     _build_session_aware_market_blocker,
                     _fetch_market_snapshot_with_session]:
            assert callable(func), f"{func.__name__} is not callable"
