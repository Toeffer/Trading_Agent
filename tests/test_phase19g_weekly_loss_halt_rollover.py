"""Tests for Phase 19G — Weekly Loss-Halt Rollover.

guard._rollover_guard_state() previously handled ONLY the daily
trade_date/day_start_nl_eur rollover. week_start_date/week_start_nl_eur
were set exactly once, in default_guard_state(), and never rolled
forward — leaving the -3% weekly loss halt in gate_loss_halts()
structurally inert (it only evaluates `if week_start and week_start > 0`,
and week_start_nl_eur stayed None indefinitely).

This test file covers both: the pre-existing daily behavior (which had
zero direct test coverage before this change — only exercised indirectly
via run_preflight() integration) and the new weekly behavior, mirroring
it field-for-field.

All tests mock fetch_account(), _stream_count_confirmed_orders_for_date(),
save_guard_state_atomic(), and append_guard_event() — no real file I/O,
no H1 path, no live IBKR calls.
"""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

BRIDGE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BRIDGE_DIR))

from guard import _rollover_guard_state, _current_week_monday_utc_str, canonical_trade_date  # noqa: E402


def _base_state(**overrides) -> dict:
    """A guard-state dict with today's trade_date and this week's Monday —
    i.e. nothing stale, nothing should roll over unless overridden."""
    now = datetime.now(timezone.utc)
    state = {
        "schema_version": 1,
        "trade_date": canonical_trade_date(now),
        "daily_trade_count": 0,
        "day_start_nl_eur": 1_000_000.0,
        "week_start_date": _current_week_monday_utc_str(),
        "week_start_nl_eur": 1_000_000.0,
        "daily_halt_active": False,
        "weekly_halt_active": False,
        "halt_reason": None,
        "last_updated_utc": now.isoformat(),
    }
    state.update(overrides)
    return state


def _stale_week_str(weeks_ago: int = 1) -> str:
    """A YYYY-MM-DD Monday from `weeks_ago` weeks before the current UTC week."""
    now = datetime.now(timezone.utc)
    current_monday = now - timedelta(days=now.weekday())
    stale_monday = current_monday - timedelta(weeks=weeks_ago)
    return stale_monday.strftime("%Y-%m-%d")


def _stale_day_str(days_ago: int = 1) -> str:
    now = datetime.now(timezone.utc)
    return (now - timedelta(days=days_ago)).strftime("%Y-%m-%d")


_PATCHES = dict(
    fetch_account=lambda nl=2_000_000.0: patch("guard.fetch_account", return_value={"net_liquidation_eur": nl}),
    stream_count=lambda n=0: patch("guard._stream_count_confirmed_orders_for_date", return_value=n),
    save=lambda: patch("guard.save_guard_state_atomic"),
    event=lambda: patch("guard.append_guard_event"),
)


class TestNoRolloverNeeded:
    def test_current_day_and_week_is_a_noop(self):
        state = _base_state()
        original = dict(state)
        with _PATCHES["fetch_account"](), _PATCHES["stream_count"](), \
             _PATCHES["save"]() as mock_save, _PATCHES["event"]() as mock_event:
            result = _rollover_guard_state(state)

        assert result is False
        assert state == original
        mock_save.assert_not_called()
        mock_event.assert_not_called()

    def test_fetch_account_not_called_when_nothing_stale(self):
        """No live account call at all on the common no-op path."""
        state = _base_state()
        with _PATCHES["fetch_account"]() as mock_fetch, _PATCHES["stream_count"](), \
             _PATCHES["save"](), _PATCHES["event"]():
            _rollover_guard_state(state)
        mock_fetch.assert_not_called()


class TestDailyRolloverOnly:
    """Pre-existing behavior — locking it in, since it had no direct test before."""

    def test_stale_trade_date_rolls_over(self):
        state = _base_state(trade_date=_stale_day_str(1), daily_trade_count=2, daily_halt_active=True)
        with _PATCHES["fetch_account"](nl=1_500_000.0), _PATCHES["stream_count"](n=0), \
             _PATCHES["save"](), _PATCHES["event"]():
            result = _rollover_guard_state(state)

        assert result is True
        assert state["trade_date"] == canonical_trade_date()
        assert state["daily_trade_count"] == 0
        assert state["daily_halt_active"] is False
        assert state["day_start_nl_eur"] == 1_500_000.0
        # Week fields untouched — still this week
        assert state["week_start_date"] == _current_week_monday_utc_str()
        assert state["weekly_halt_active"] is False
        assert state["week_start_nl_eur"] == 1_000_000.0

    def test_restores_count_from_confirmed_events(self):
        state = _base_state(trade_date=_stale_day_str(1), daily_trade_count=99)
        with _PATCHES["fetch_account"](), _PATCHES["stream_count"](n=1), \
             _PATCHES["save"](), _PATCHES["event"]():
            _rollover_guard_state(state)
        assert state["daily_trade_count"] == 1

    def test_account_fetch_failure_does_not_crash_or_block_rollover(self):
        state = _base_state(trade_date=_stale_day_str(1))
        with patch("guard.fetch_account", side_effect=RuntimeError("no bridge")), \
             _PATCHES["stream_count"](), _PATCHES["save"](), _PATCHES["event"]():
            result = _rollover_guard_state(state)
        assert result is True
        assert state["trade_date"] == canonical_trade_date()
        # day_start_nl_eur left as-is when the account fetch fails
        assert state["day_start_nl_eur"] == 1_000_000.0


class TestWeeklyRolloverOnly:
    """New behavior — the actual fix."""

    def test_stale_week_start_date_rolls_over(self):
        state = _base_state(
            week_start_date=_stale_week_str(1),
            week_start_nl_eur=None,
            weekly_halt_active=True,
        )
        with _PATCHES["fetch_account"](nl=1_200_000.0), _PATCHES["stream_count"](), \
             _PATCHES["save"](), _PATCHES["event"]():
            result = _rollover_guard_state(state)

        assert result is True
        assert state["week_start_date"] == _current_week_monday_utc_str()
        assert state["weekly_halt_active"] is False
        assert state["week_start_nl_eur"] == 1_200_000.0
        # Day fields untouched — still today
        assert state["trade_date"] == canonical_trade_date()
        assert state["daily_halt_active"] is False

    def test_null_week_start_nl_eur_gets_populated_on_next_stale_rollover(self):
        """The exact bug this fixes: week_start_nl_eur stuck at None forever
        because nothing ever rolled week_start_date forward to trigger a
        fresh capture."""
        state = _base_state(week_start_date=_stale_week_str(2), week_start_nl_eur=None)
        with _PATCHES["fetch_account"](nl=987_654.0), _PATCHES["stream_count"](), \
             _PATCHES["save"](), _PATCHES["event"]():
            _rollover_guard_state(state)
        assert state["week_start_nl_eur"] == 987_654.0

    def test_account_fetch_failure_does_not_crash_or_block_weekly_rollover(self):
        state = _base_state(week_start_date=_stale_week_str(1), week_start_nl_eur=None)
        with patch("guard.fetch_account", side_effect=RuntimeError("no bridge")), \
             _PATCHES["stream_count"](), _PATCHES["save"](), _PATCHES["event"]():
            result = _rollover_guard_state(state)
        assert result is True
        assert state["week_start_date"] == _current_week_monday_utc_str()
        # Never captured — stays None rather than a fabricated value
        assert state["week_start_nl_eur"] is None


class TestBothRolloverTogether:
    def test_day_and_week_stale_simultaneously_share_one_account_fetch(self):
        state = _base_state(
            trade_date=_stale_day_str(3),
            week_start_date=_stale_week_str(1),
            week_start_nl_eur=None,
            daily_halt_active=True,
            weekly_halt_active=True,
        )
        with _PATCHES["fetch_account"](nl=1_100_000.0) as mock_fetch, \
             _PATCHES["stream_count"](), _PATCHES["save"](), _PATCHES["event"]():
            result = _rollover_guard_state(state)

        assert result is True
        assert mock_fetch.call_count == 1  # shared, not fetched twice
        assert state["trade_date"] == canonical_trade_date()
        assert state["daily_halt_active"] is False
        assert state["day_start_nl_eur"] == 1_100_000.0
        assert state["week_start_date"] == _current_week_monday_utc_str()
        assert state["weekly_halt_active"] is False
        assert state["week_start_nl_eur"] == 1_100_000.0

    def test_event_payload_reflects_both_rollovers(self):
        state = _base_state(trade_date=_stale_day_str(1), week_start_date=_stale_week_str(1))
        with _PATCHES["fetch_account"](), _PATCHES["stream_count"](), \
             _PATCHES["save"](), _PATCHES["event"]() as mock_event:
            _rollover_guard_state(state)

        mock_event.assert_called_once()
        event_type, payload = mock_event.call_args[0]
        assert event_type == "guard_calendar_rollover"
        assert payload["daily_rollover_occurred"] is True
        assert payload["weekly_rollover_occurred"] is True
        assert payload["daily_halt_cleared"] is True
        assert payload["weekly_halt_cleared"] is True

    def test_event_payload_reflects_week_only_rollover(self):
        """Day fields in the event must be None, not stale/incorrect
        values, when only the week rolled over."""
        state = _base_state(week_start_date=_stale_week_str(1))
        with _PATCHES["fetch_account"](), _PATCHES["stream_count"](), \
             _PATCHES["save"](), _PATCHES["event"]() as mock_event:
            _rollover_guard_state(state)

        _, payload = mock_event.call_args[0]
        assert payload["daily_rollover_occurred"] is False
        assert payload["from_trade_date"] is None
        assert payload["to_trade_date"] is None
        assert payload["weekly_rollover_occurred"] is True
        assert payload["from_week_start_date"] is not None
        assert payload["to_week_start_date"] == _current_week_monday_utc_str()


class TestGateLossHaltsHonoursTheCapturedValue:
    """End-to-end: once week_start_nl_eur is captured, the weekly loss
    halt actually evaluates instead of silently no-op'ing."""

    def test_weekly_halt_triggers_after_rollover_captures_a_start_value(self):
        from guard import gate_loss_halts

        state = _base_state(week_start_date=_stale_week_str(1), week_start_nl_eur=None)
        with _PATCHES["fetch_account"](nl=1_000_000.0), _PATCHES["stream_count"](), \
             _PATCHES["save"](), _PATCHES["event"]():
            _rollover_guard_state(state)
        assert state["week_start_nl_eur"] == 1_000_000.0

        rules = {"loss_halts": {"daily": {"value": 1}, "weekly": {"value": 3}}}
        # Down 4% from the just-captured week start — should now trigger,
        # where before the fix this branch was unreachable (week_start
        # was always None).
        ok, reason, details = gate_loss_halts(state, 960_000.0, rules)
        assert ok is False
        assert details["weekly_halt_triggered"] is True
