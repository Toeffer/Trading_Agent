"""Tests for Phase 19L — run_preflight()'s rollover write needs H1 scope (2026-08-17).

Live incident, run-start day: guard-state.json's trade_date (then, after a
manual repair, week_start_date) were stale. run_preflight() -> load_guard_state()
-> _rollover_guard_state() -> save_guard_state_atomic() writes guard-state.json,
a Phase H1.2 protected path -- but preflight never carries H1 authorization
(H1 is scoped to /order/approve and /order/submit only, invariant #17). The
call was unwrapped, and the except clause around it only caught
RuntimeError/ValueError/FileNotFoundError, not PermissionError, so the
unauthorized write raised straight through the request handler: preflight
500'd instead of returning its documented validation-only response.

Fix: the rollover call is deterministic, wall-clock-driven housekeeping with
no adversarial degrees of freedom -- not an order mutation -- so it gets its
own narrow `with h1_authorized_scope():`, exactly the pattern that context
manager exists for (see its own docstring). This does not widen H1
authorization for anything else in the request.

Mocking convention matches test_phase19g_weekly_loss_halt_rollover.py.
guard-state.json's real protection mechanism (PROTECTED_PATHS, a module-
level set) is exercised directly rather than mocked away, against a
tmp_path-redirected GUARD_STATE_PATH -- otherwise this test could pass for
the wrong reason (H1 enforcement silently not actually engaged).
"""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

BRIDGE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BRIDGE_DIR))

import guard  # noqa: E402
from guard import (  # noqa: E402
    _rollover_guard_state,
    _current_week_monday_utc_str,
    canonical_trade_date,
    h1_authorized_scope,
    _assert_h1_authorized_for_path,
    run_preflight,
)


def _stale_day_str(days_ago: int = 3) -> str:
    now = datetime.now(timezone.utc)
    return (now - timedelta(days=days_ago)).strftime("%Y-%m-%d")


def _stale_week_str(weeks_ago: int = 10) -> str:
    now = datetime.now(timezone.utc)
    current_monday = now - timedelta(days=now.weekday())
    return (current_monday - timedelta(weeks=weeks_ago)).strftime("%Y-%m-%d")


def _stale_state(**overrides) -> dict:
    state = {
        "schema_version": 1,
        "trade_date": _stale_day_str(),
        "daily_trade_count": 0,
        "day_start_nl_eur": 1_000_000.0,
        "week_start_date": _stale_week_str(),
        "week_start_nl_eur": None,
        "daily_halt_active": False,
        "weekly_halt_active": False,
        "halt_reason": None,
        "last_updated_utc": datetime.now(timezone.utc).isoformat(),
    }
    state.update(overrides)
    return state


@pytest.fixture
def h1_enforced(tmp_path):
    """Simulate real post-startup H1 enforcement (mirrors production, where
    h1_startup_done() has already run) against an isolated protected path
    -- never the real ~/.openclaw/guard-state.json. Restores all module
    globals afterward so this can't leak into other tests, the exact class
    of contamination that caused a real CI failure earlier this session."""
    tmp_guard_state = tmp_path / "guard-state.json"

    original_startup_complete = guard._h1_startup_complete
    original_protected_paths = set(guard.PROTECTED_PATHS)

    guard._h1_startup_complete = True
    guard.PROTECTED_PATHS.add(tmp_guard_state.resolve())
    # Ensure no stray authorization leaks in from a prior test/context.
    guard._h1_authorized.set(False)

    try:
        yield tmp_guard_state
    finally:
        guard._h1_startup_complete = original_startup_complete
        guard.PROTECTED_PATHS.clear()
        guard.PROTECTED_PATHS.update(original_protected_paths)
        guard._h1_authorized.set(False)


class TestBugReproduction:
    """Proves the original bug was real: an unscoped write to a protected
    path, under real enforcement, genuinely raises."""

    def test_unscoped_protected_write_raises_without_h1(self, h1_enforced):
        with pytest.raises(PermissionError, match="H1 approval token required"):
            _assert_h1_authorized_for_path(h1_enforced)

    def test_scoped_protected_write_does_not_raise(self, h1_enforced):
        with h1_authorized_scope():
            _assert_h1_authorized_for_path(h1_enforced)  # must not raise

    def test_scope_does_not_leak_past_its_block(self, h1_enforced):
        with h1_authorized_scope():
            _assert_h1_authorized_for_path(h1_enforced)
        with pytest.raises(PermissionError):
            _assert_h1_authorized_for_path(h1_enforced)


class TestRolloverUnderRealH1Enforcement:
    """_rollover_guard_state() itself, called the way run_preflight() now
    calls it -- inside h1_authorized_scope() -- against a real (tmp,
    isolated) protected path."""

    def test_unwrapped_rollover_raises_under_enforcement(self, h1_enforced):
        """Reproduces the exact live incident: a stale state, real
        enforcement active, no authorization -- the pre-fix call shape."""
        state = _stale_state()
        with patch("guard.GUARD_STATE_PATH", h1_enforced), \
             patch("guard.fetch_account", return_value={"net_liquidation_eur": 1_000_000.0}), \
             patch("guard._stream_count_confirmed_orders_for_date", return_value=0):
            with pytest.raises(PermissionError, match="H1 approval token required"):
                _rollover_guard_state(state)

    def test_scoped_rollover_succeeds_and_persists(self, h1_enforced):
        """The fix: identical setup, wrapped in h1_authorized_scope() --
        the exact shape run_preflight() now uses."""
        state = _stale_state()
        with patch("guard.GUARD_STATE_PATH", h1_enforced), \
             patch("guard.fetch_account", return_value={"net_liquidation_eur": 1_000_000.0}), \
             patch("guard._stream_count_confirmed_orders_for_date", return_value=0):
            with h1_authorized_scope():
                result = _rollover_guard_state(state)

        assert result is True
        assert state["trade_date"] == canonical_trade_date()
        assert state["week_start_date"] == _current_week_monday_utc_str()
        assert state["week_start_nl_eur"] == 1_000_000.0
        assert h1_enforced.exists()  # actually persisted to disk


class TestRunPreflightNoLongerCrashes:
    """End-to-end: run_preflight() itself, with a stale state and real H1
    enforcement active, must not 500 -- it must return its documented
    validation-only dict, same as any other preflight call."""

    def test_stale_state_no_longer_raises_permission_error(self, h1_enforced):
        state = _stale_state()
        with patch("guard.GUARD_STATE_PATH", h1_enforced), \
             patch("guard.load_guard_state", return_value=state), \
             patch("guard.fetch_account", return_value={
                 "net_liquidation_eur": 1_000_000.0, "exchange_rate": 1.08,
             }), \
             patch("guard._stream_count_confirmed_orders_for_date", return_value=0), \
             patch("guard.load_rules", return_value={
                 "symbol_allowlist": {"allow": ["AAPL"]},
                 "max_trades_per_day": {"value": 2},
             }):
            # Must not raise PermissionError (or anything else) -- whatever
            # gate it fails on next (missing quote/bars data, since those
            # aren't mocked here) is fine; only the rollover step is under
            # test. A clean dict response either way proves no crash.
            result = run_preflight({
                "symbol": "AAPL", "action": "BUY",
                "totalQuantity": 1, "orderType": "MKT", "mode": "paper",
            })

        assert isinstance(result, dict)
        assert "passed" in result
        # The rollover itself must have actually happened and persisted --
        # not silently skipped.
        assert state["trade_date"] == canonical_trade_date()
        assert state["week_start_date"] == _current_week_monday_utc_str()


class TestSourceGuardsAgainstRegression:
    def test_rollover_call_is_wrapped_in_h1_scope(self):
        src = Path(BRIDGE_DIR / "guard.py").read_text()
        idx = src.index("def run_preflight(")
        # Look within run_preflight()'s body for the specific call.
        snippet = src[idx: idx + 4000]
        call_idx = snippet.index("_rollover_guard_state(state)")
        preceding = snippet[:call_idx]
        # The nearest preceding non-blank line must be the scope's `with`.
        lines = [l for l in preceding.splitlines() if l.strip()]
        assert lines[-1].strip() == "with h1_authorized_scope():", (
            f"_rollover_guard_state(state) in run_preflight() is no longer "
            f"wrapped in h1_authorized_scope() -- found preceding line: {lines[-1]!r}"
        )
