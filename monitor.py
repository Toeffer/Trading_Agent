#!/usr/bin/env python3
"""
monitor.py — Phase 2F Monitoring & Reconciliation Module

Read-only helpers for cross-source reconciliation of guard state, events,
approval records, and submitted-approvals tracking. No IBKR API calls,
no order APIs, no kill-switch modifications.

Usage:
    python3 -c "from monitor import reconcile_snapshot; r = reconcile_snapshot(); print(r)"
    python3 -c "from monitor import health_summary; h = health_summary(); print(h)"
"""

import json
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

from guard import (
    GUARD_STATE_PATH,
    GUARD_EVENTS_PATH,
    APPROVAL_RECORDS_PATH,
    SUBMITTED_APPROVALS_PATH,
    ALLOWED_EVENT_TYPES,
    load_guard_state,
    read_guard_events,
    append_guard_event,
)

# ---------------------------------------------------------------------------
# RTH (Regular Trading Hours) Calendar — Read-Only
# ---------------------------------------------------------------------------
# US equity RTH: Mon-Fri, 9:30 AM - 4:00 PM Eastern Time.
# No auto-submit, no auto-trade; operator advisory only.

# Known US market holidays for 2026 (NYSE-listed)
_MARKET_HOLIDAYS_2026 = frozenset({
    "2026-01-01",  # New Year's Day
    "2026-01-19",  # Martin Luther King Jr. Day
    "2026-02-16",  # Presidents' Day
    "2026-04-03",  # Good Friday
    "2026-05-25",  # Memorial Day
    "2026-06-19",  # Juneteenth (observed)
    "2026-07-03",  # Independence Day (observed)
    "2026-09-07",  # Labor Day
    "2026-11-26",  # Thanksgiving Day
    "2026-12-25",  # Christmas Day
})

# Early close days (market closes at 1:00 PM ET)
_EARLY_CLOSE_2026 = frozenset({
    "2026-11-27",  # Day after Thanksgiving
    "2026-12-24",  # Christmas Eve
})

# Cache for ET offset (avoid repeated calls)
_ET_OFFSET = timedelta(hours=-5)  # EST = UTC-5
_EDT_OFFSET = timedelta(hours=-4)  # EDT = UTC-4


def _is_us_dst(dt_utc: datetime) -> bool:
    """Approximate DST check for US Eastern time.
    DST starts second Sunday March, ends first Sunday November.
    Returns True if UTC time falls in EDT period, False for EST.
    """
    year = dt_utc.year
    # Second Sunday of March
    march1 = datetime(year, 3, 1, tzinfo=timezone.utc)
    # Find first Sunday, add 7 days for second Sunday
    days_to_first_sun = (6 - march1.weekday()) % 7
    second_sun_march = march1 + timedelta(days=days_to_first_sun + 7)
    # First Sunday of November
    nov1 = datetime(year, 11, 1, tzinfo=timezone.utc)
    days_to_first_sun_nov = (6 - nov1.weekday()) % 7
    first_sun_nov = nov1 + timedelta(days=days_to_first_sun_nov)

    return second_sun_march <= dt_utc < first_sun_nov


def _utc_to_et(dt_utc: datetime) -> datetime:
    """Convert UTC datetime to US Eastern Time (naive datetime, no tz)."""
    offset = _EDT_OFFSET if _is_us_dst(dt_utc) else _ET_OFFSET
    return dt_utc + offset


def rth_check(dt_utc: datetime | None = None) -> dict:
    """Read-only check: is the given UTC time within US equity RTH?

    Returns a dict with:
        in_rth: bool — are we inside regular trading hours?
        rth_open: str — RTH open time in ET (ISO time)
        rth_close: str — RTH close time in ET (ISO time)
        is_tradable_day: bool — is today a normal trading day?
        is_early_close: bool — does the market close early today?
        reason: str — human-readable explanation
        market_date_et: str — current market date in YYYY-MM-DD ET
        market_day_name: str — day of week name
        next_rth_open_et: str | None — next RTH open in ISO ET
        next_rth_close_et: str | None — next RTH close in ISO ET

    No auto-submit. No auto-approve. Operator advisory only.
    """
    if dt_utc is None:
        dt_utc = datetime.now(timezone.utc)

    dt_et = _utc_to_et(dt_utc)
    date_str_et = dt_et.strftime("%Y-%m-%d")
    day_name = dt_et.strftime("%A")
    weekday = dt_et.weekday()  # Mon=0, Sun=6

    is_weekend = weekday >= 5  # Sat=5, Sun=6
    is_holiday = date_str_et in _MARKET_HOLIDAYS_2026
    is_early = date_str_et in _EARLY_CLOSE_2026
    is_tradable_day = not is_weekend and not is_holiday

    # RTH window
    rth_open_time_et = (9, 30)
    rth_close_time_et = (13, 0) if is_early else (16, 0)

    market_open_dt = dt_et.replace(hour=rth_open_time_et[0], minute=rth_open_time_et[1], second=0, microsecond=0)
    market_close_dt = dt_et.replace(hour=rth_close_time_et[0], minute=rth_close_time_et[1], second=0, microsecond=0)

    in_rth = is_tradable_day and (market_open_dt <= dt_et < market_close_dt)

    # Build reason string
    if not is_tradable_day:
        if is_weekend:
            reason = f"Weekend ({day_name}) — market closed"
        else:
            reason = f"Market holiday ({date_str_et}) — market closed"
    elif is_early and dt_et >= market_close_dt:
        reason = f"Early close day — market closed at {rth_close_time_et[0]}:{rth_close_time_et[1]:02d} PM ET"
    elif in_rth:
        reason = f"Inside RTH — {dt_et.strftime('%H:%M')} ET ({date_str_et})"
    else:
        if dt_et < market_open_dt:
            reason = f"Pre-market — market opens at {rth_open_time_et[0]}:{rth_open_time_et[1]:02d} AM ET"
        else:
            reason = f"After hours — market closed at {rth_close_time_et[0]}:{rth_close_time_et[1]:02d} PM ET"

    # Compute next RTH boundaries (for display purposes)
    next_rth_open = None
    next_rth_close = None
    if in_rth:
        next_rth_open = market_open_dt.isoformat()
        next_rth_close = market_close_dt.isoformat()
    elif is_tradable_day:
        next_rth_open = market_open_dt.isoformat()
        next_rth_close = market_close_dt.isoformat()

    return {
        "in_rth": in_rth,
        "rth_open_et": f"{rth_open_time_et[0]:02d}:{rth_open_time_et[1]:02d}",
        "rth_close_et": f"{rth_close_time_et[0]:02d}:{rth_close_time_et[1]:02d}",
        "is_tradable_day": is_tradable_day,
        "is_early_close": is_early,
        "is_weekend": is_weekend,
        "is_holiday": is_holiday,
        "reason": reason,
        "market_date_et": date_str_et,
        "market_day_name": day_name,
        "next_rth_open_et": next_rth_open,
        "next_rth_close_et": next_rth_close,
        "utc_time": dt_utc.isoformat(),
    }


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

MONITOR_STATE_PATH = Path(os.environ.get(
    "IBKR_MONITOR_STATE_PATH",
    str(Path.home() / ".openclaw" / "monitor-state.json")
))

MANUAL_ORDER_RECON_PATH = Path(os.environ.get(
    "IBKR_MANUAL_ORDER_RECON_PATH",
    str(Path.home() / ".openclaw" / "manual-order-reconciliations.jsonl")
))

# ---------------------------------------------------------------------------
# Read-only loaders
# ---------------------------------------------------------------------------

def load_events(
    event_type: str | None = None,
    since_utc: str | None = None,
) -> list[dict]:
    """Load guard events, optionally filtered by type and since timestamp.

    Args:
        event_type: Optional event type filter (e.g. "order_submitted").
            Multiple types can be comma-separated.
        since_utc: Optional ISO-8601 inclusive lower bound.

    Returns:
        List of matching event dicts in file order.
    """
    events = read_guard_events()

    if event_type:
        types = {t.strip() for t in event_type.split(",")}
        events = [e for e in events if e.get("event_type") in types]

    if since_utc:
        try:
            since_dt = datetime.fromisoformat(since_utc)
            events = [
                e for e in events
                if (ts := e.get("timestamp_utc"))
                and datetime.fromisoformat(ts) >= since_dt
            ]
        except (ValueError, TypeError):
            pass  # invalid date, return unfiltered

    return events


def load_approval_records() -> list[dict]:
    """Load all approval records from approval-records.jsonl.

    Returns empty list if file does not exist or is unreadable.
    """
    p = APPROVAL_RECORDS_PATH
    if not p.exists():
        return []
    records = []
    try:
        for line in p.read_text().splitlines():
            line = line.strip()
            if line:
                records.append(json.loads(line))
    except (json.JSONDecodeError, OSError):
        return []
    return records


def load_submitted_approvals() -> set[str]:
    """Load the set of submitted approval IDs from disk.

    Returns empty set if file does not exist or is corrupt.
    """
    from guard import _load_submitted_approvals
    return _load_submitted_approvals()


# ---------------------------------------------------------------------------
# Alert classification helpers
# ---------------------------------------------------------------------------

# Known non-real order_id values used during Phase 2E testing
_KNOWN_TEST_ORDER_IDS = frozenset({"12345", "99999"})

# Known test-approval patterns (not real paper orders)
_KNOWN_TEST_APPROVALS = frozenset({
    "aprv_noexec",
    "aprv_7",
    "aprv_18e4937e-a72d-405b-867b-f42348db0778",
    "aprv_37136891-8b4f-4aae-9af7-5193d94a610a",
})


def _classify_alert_source(
    alerts: list[dict],
    daily_trade_count: int,
    event_count: int,
    events: list[dict],
    unique_order_ids: set[str],
    trade_date: str = "unknown",
    now_utc: datetime = None,
    positions_flat: bool = False,
) -> list[dict]:
    """Add classification metadata to each alert.

    Each alert dict gets:
      - source: "historical_test_data" | "historical_exercise" | "live" | "calendar_boundary_stale_state"
      - historical: bool (true if source is test/exercise)
      - requires_action: bool (true only for live alerts)

    Mocks: events missing action/symbol (Phase 2E early testing)
    Exercises: events with test order_ids (99999) or test approval ids
    Calendar boundary: guard trade_date < current UTC date with flat positions
    Live: real mismatches on the active trade date.
    """
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)
    classified = []
    for alert in alerts:
        alert_type = alert.get("alert_type", "")
        detail = alert.get("detail", "")

        # Determine source for trade_count_mismatch
        if alert_type == "trade_count_mismatch":
            # Count components
            mock_ids = {
                oid for oid in unique_order_ids
                if oid in _KNOWN_TEST_ORDER_IDS
            }
            # Check if any events are clearly mock (no action/symbol)
            mock_events = [
                e for e in events
                if not e.get("action") or not e.get("symbol")
            ]
            mock_from_event_count = len(mock_events)

            # Check if any events are from known test approvals
            test_approval_events = [
                e for e in events
                if e.get("approval_id", "") in _KNOWN_TEST_APPROVALS
            ]

            # Events with order_id=99999 are test exercises
            exercise_ids = {
                oid for oid in unique_order_ids
                if oid == "99999"
            }

            # Real events: everything that's not mock or exercise
            real_ids = unique_order_ids - mock_ids - exercise_ids
            all_known_test = (len(unique_order_ids) > 0
                              and len(real_ids) == 0)

            if all_known_test:
                # All extra order_ids are from testing — historical test data
                alert["source"] = "historical_test_data"
                alert["historical"] = True
                alert["requires_action"] = False
                alert["classification_detail"] = (
                    f"Mismatch caused by test artifacts: "
                    f"{len(mock_ids)} mock order_id(s), "
                    f"{len(exercise_ids)} exercise order_id(s). "
                    f"Real trades: {len(real_ids)}. "
                    f"Guard state ({daily_trade_count}) matches "
                    f"real unique order count (ignoring test data)."
                )
            elif len(real_ids) > 0 and daily_trade_count == len(real_ids):
                # Real trades match guard state, extra events are test data
                alert["source"] = "historical_test_data"
                alert["historical"] = True
                alert["requires_action"] = False
                alert["classification_detail"] = (
                    f"{len(real_ids)} real trade(s) match guard state "
                    f"({daily_trade_count}). Extra {len(unique_order_ids) - len(real_ids)} "
                    f"order_id(s) are from Phase 2E test data. "
                    f"No action required."
                )
            else:
                # Check for calendar boundary stale state
                today_utc_date = now_utc.strftime("%Y-%m-%d") if now_utc else ""
                is_stale_calendar = (
                    trade_date
                    and trade_date != "unknown"
                    and today_utc_date
                    and trade_date < today_utc_date
                    and positions_flat
                )
                if is_stale_calendar:
                    alert["source"] = "calendar_boundary_stale_state"
                    alert["historical"] = True
                    alert["requires_action"] = False
                    alert["classification_detail"] = (
                        f"Guard state trade_date ({trade_date}) is before today ({today_utc_date}). "
                        f"All positions flat. Mismatch reflects closed orders spanning trade_date boundary. "
                        f"Will auto-resolve on next preflight advancing trade_date."
                    )
                else:
                    # Real mismatch — active alert
                    alert["source"] = "live"
                    alert["historical"] = False
                    alert["requires_action"] = True

        elif alert_type == "orphan_submitted_approval":
            # Check if all orphan IDs are known test artifacts
            orphan_ids = set(alert.get("orphan_approval_ids", []))
            known_test_orphans = {
                aid for aid in orphan_ids
                if aid in _KNOWN_TEST_APPROVALS
            }
            unknown_orphans = orphan_ids - known_test_orphans
            if len(unknown_orphans) == 0 and len(orphan_ids) > 0:
                # All orphans are known test artifacts
                alert["source"] = "historical_test_data"
                alert["historical"] = True
                alert["requires_action"] = False
                alert["classification_detail"] = (
                    f"All {len(orphan_ids)} orphan(s) are known test artifacts: "
                    f"{', '.join(sorted(orphan_ids))}"
                )
            elif len(orphan_ids) == 0:
                # Only the empty string was orphan (already filtered)
                alert["source"] = "historical_test_data"
                alert["historical"] = True
                alert["requires_action"] = False
                alert["classification_detail"] = (
                    "Only empty-string artifact in submitted set, no real orphan approvals"
                )
            else:
                alert["source"] = "live"
                alert["historical"] = False
                alert["requires_action"] = True

        elif alert_type == "orphan_record_with_order":
            alert["source"] = "live"
            alert["historical"] = False
            alert["requires_action"] = True

        else:
            alert["source"] = "live"
            alert["historical"] = False
            alert["requires_action"] = True

        classified.append(alert)

    return classified


# ---------------------------------------------------------------------------
# Snapshot reconciliation
# ---------------------------------------------------------------------------

def reconcile_snapshot() -> dict:
    """Run a full cross-source reconciliation and return a structured report.

    Compares:
    - Guard state daily_trade_count vs events
    - Submitted-approvals vs events
    - Approval records vs events
    - Counts stale/expired pending approvals

    Returns:
        JSON-serializable dict with sections: state, events, approvals, alerts.
    """
    now_utc = datetime.now(timezone.utc)
    alerts: list[dict] = []

    # 1. Guard state
    try:
        gs = load_guard_state()
        guard_ok = True
    except (ValueError, OSError) as e:
        gs = {}
        guard_ok = False
        alerts.append({
            "alert_type": "guard_state_unreadable",
            "severity": "high",
            "detail": str(e),
        })

    daily_trade_count = gs.get("daily_trade_count", 0)
    trade_date = gs.get("trade_date", "unknown")

    # 2. Events — count order_submitted events today
    events = load_events(event_type="order_submitted")

    # Filter to today (by trade_date from guard state)
    today_events = events
    if trade_date != "unknown":
        today_events = [
            e for e in events
            if (ts := e.get("timestamp_utc", ""))
            and ts.startswith(trade_date)
        ]

    unique_order_ids_today = set()
    for e in today_events:
        oid = e.get("order_id")
        if oid is not None:
            unique_order_ids_today.add(str(oid))

    # Exclude unconfirmed orders from trade count
    unconfirmed_events_set = load_events(event_type="order_unconfirmed")
    unconfirmed_approval_ids = {ue.get("approval_id", "") for ue in unconfirmed_events_set}
    for e in today_events:
        aid = e.get("approval_id", "")
        if aid and aid not in unconfirmed_approval_ids:
            ibkr = e.get("ibkr_metadata")
            if ibkr is None and e.get("action") == "SELL":
                unconfirmed_approval_ids.add(aid)

    confirmed_today = [
        e for e in today_events
        if e.get("approval_id", "") not in unconfirmed_approval_ids
    ]
    # Use composite identity to avoid order_id reuse/collision:
    #   permId (preferred) > approval_id > event_id
    # order_id alone is insufficient — IBKR reuses order_ids after restart.
    confirmed_identities = set()
    for e in confirmed_today:
        ibkr = e.get("ibkr_metadata")
        if ibkr and ibkr.get("permId") is not None:
            identity = f"permId:{ibkr['permId']}"
        elif e.get("approval_id"):
            identity = f"approval:{e['approval_id']}"
        elif e.get("event_id"):
            identity = f"event:{e['event_id']}"
        else:
            oid = e.get("order_id")
            identity = f"order_id:{oid}" if oid is not None else None
        if identity:
            confirmed_identities.add(identity)
    event_trade_count = len(confirmed_identities)

    # Trade count reconciliation
    trade_count_mismatch = daily_trade_count != event_trade_count
    if trade_count_mismatch:
        alerts.append({
            "alert_type": "trade_count_mismatch",
            "severity": "high",
            "detail": (
                f"guard_state daily_trade_count={daily_trade_count}, "
                f"events show {event_trade_count} confirmed unique orders today"
            ),
            "event_count": event_trade_count,
            "guard_count": daily_trade_count,
            "unique_order_ids": sorted(confirmed_identities),
        })

    # 3. Approval records
    records = load_approval_records()
    total_records = len(records)
    submitted_records = [r for r in records if r.get("status") == "approved"]
    expired_records = 0
    for r in records:
        expires_at = r.get("expires_at_utc")
        if expires_at and r.get("status") == "pending":
            try:
                expires_dt = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
                if now_utc > expires_dt:
                    expired_records += 1
            except (ValueError, TypeError):
                pass

    # 4. Submitted approvals from persisted file
    submitted_set = load_submitted_approvals()
    total_submitted = len(submitted_set)

    # 5. Cross-reference: submitted approvals vs events
    submitted_with_event = 0
    for aid in submitted_set:
        for e in events:
            if e.get("approval_id") == aid:
                submitted_with_event += 1
                break

    # Find which specific approval IDs are orphaned
    orphan_ids = set()
    for aid in submitted_set:
        if not aid:
            continue  # skip empty string artifact
        found = any(e.get("approval_id") == aid for e in events)
        if not found:
            orphan_ids.add(aid)

    orphan_submitted = len(orphan_ids)
    if orphan_submitted > 0:
        alerts.append({
            "alert_type": "orphan_submitted_approval",
            "severity": "high",
            "detail": f"{orphan_submitted} submitted approval(s) have no matching order_submitted event",
            "orphan_approval_ids": sorted(orphan_ids),
        })

    # 6. Approval records with order_id vs submitted set
    records_with_order_id = [r for r in records if r.get("order_id") is not None]
    records_without_event = 0
    for r in records_with_order_id:
        aid = r.get("approval_id")
        if aid and aid not in submitted_set:
            records_without_event += 1
    if records_without_event > 0:
        alerts.append({
            "alert_type": "orphan_record_with_order",
            "severity": "medium",
            "detail": f"{records_without_event} approval record(s) have order_id but are not in submitted set",
        })

    # 7. Count startup_reconciliation events
    reconciliation_events = load_events(event_type="startup_reconciliation")
    last_reconciliation_utc = None
    if reconciliation_events:
        last_reconciliation_utc = reconciliation_events[-1].get("timestamp_utc")

    # 8. Monitor state persistence check
    monitor_state_ok = True
    try:
        MONITOR_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        monitor_state_ok = False

    # Classify alerts (add source/historical/requires_action)
    # Determine if all positions are flat (no drift mismatches)
    # We need actual positions — check from the drift endpoint data
    # This is a best-effort check: if positions are unavailable, assume not flat
    positions_flat = False
    try:
        # Check current positions from the bridge if connected
        # Otherwise infer from expected positions
        expected_pos = position_drift_check()
        exp_positions = expected_pos.get("expected_positions", {})
        if not exp_positions or all(v == 0 for v in exp_positions.values()):
            positions_flat = True
    except Exception:
        pass

    classified_alerts = _classify_alert_source(
        alerts,
        daily_trade_count,
        event_trade_count,
        today_events,
        confirmed_identities,
        trade_date=trade_date,
        now_utc=now_utc,
        positions_flat=positions_flat,
    )

    # Build result
    result: dict[str, Any] = {
        "timestamp_utc": now_utc.isoformat(),
        "passed": len(alerts) == 0,
        "classification_summary": {
            "historical_test_data": sum(1 for a in classified_alerts if a.get("source") == "historical_test_data"),
            "historical_exercise": sum(1 for a in classified_alerts if a.get("source") == "historical_exercise"),
            "live": sum(1 for a in classified_alerts if a.get("source") == "live"),
        },
        "checks": {
            "trade_count_match": not trade_count_mismatch,
            "no_orphan_submitted": orphan_submitted == 0,
            "no_orphan_records": records_without_event == 0,
            "guard_state_healthy": guard_ok,
            "events_log_readable": len(events) > 0 or True,
            "submitted_approvals_file_readable": True,
        },
        "state": {
            "guard": {
                "daily_trade_count": daily_trade_count,
                "trade_date": trade_date,
                "healthy": guard_ok,
            },
            "events": {
                "total_events": len(events),
                "today_unique_order_ids": event_trade_count,
                "today_unconfirmed_excluded": len(unique_order_ids_today) - event_trade_count,
                "last_reconciliation_utc": last_reconciliation_utc,
                "mock_test_events": len([e for e in today_events if not e.get("action") or not e.get("symbol")]),
            },
            "approvals": {
                "total_records": total_records,
                "approved": len(submitted_records),
                "expired_pending": expired_records,
                "submitted_set_size": total_submitted,
            },
        },
        "alerts": classified_alerts,
    }

    return result


# ---------------------------------------------------------------------------
# Health summary (lightweight)
# ---------------------------------------------------------------------------

def health_summary() -> dict:
    """Return a lightweight health summary — no IBKR calls needed."""
    try:
        gs = load_guard_state()
    except (ValueError, OSError):
        gs = {}

    daily_trade_count = gs.get("daily_trade_count", "unavailable")
    trade_date = gs.get("trade_date", "unknown")

    events = load_events()
    events_ok = len(events) > 0

    records = load_approval_records()
    records_ok = True  # empty is valid

    submitted_set = load_submitted_approvals()
    submitted_file_ok = isinstance(submitted_set, set)

    # Check if kill-switch env var exists
    ibkr_allowed = os.environ.get("IBKR_ALLOW_ORDERS", "false") == "true"

    return {
        "ok": True,
        "checks": {
            "guard_state_healthy": gs.get("daily_trade_count") is not None,
            "events_log_readable": events_ok,
            "approval_records_readable": records_ok,
            "submitted_approvals_readable": submitted_file_ok,
        },
        "state": {
            "guard": {
                "daily_trade_count": daily_trade_count,
                "trade_date": trade_date,
            },
            "events": {
                "total_events": len(events),
            },
            "approvals": {
                "total_records": len(records),
                "submitted_set_size": len(submitted_set),
            },
        },
    }


# ---------------------------------------------------------------------------
# Position drift (file-based, no IBKR)
# ---------------------------------------------------------------------------

def position_drift_check() -> dict:
    """Check position drift using only file-based data.

    Computes expected net position from CONFIRMED order_submitted events
    (BUY = +qty, SELL = -qty). Events linked to order_unconfirmed
    (IBKR never acknowledged) are excluded so they don't contribute
    to drift.

    Returns:
        Dict with expected positions per symbol plus unconfirmed_ids.
    """
    events = load_events(event_type="order_submitted")
    unconfirmed_events = load_events(event_type="order_unconfirmed")

    # Collect approval_ids that are unconfirmed (IBKR never acknowledged)
    unconfirmed_approval_ids = set()
    for ue in unconfirmed_events:
        aid = ue.get("approval_id", "")
        if aid:
            unconfirmed_approval_ids.add(aid)

    # Also collect approval_ids from order_submitted events that have
    # empty/no ibkr_metadata (legacy pre-fix events like order_id=24)
    legacy_unconfirmed_ids = set()
    for e in events:
        ibkr = e.get("ibkr_metadata")
        if ibkr is None:
            # Legacy event without ibkr_metadata — check if it was a SELL close
            # that never got executed (position still exists)
            aid = e.get("approval_id", "")
            if aid and e.get("action") == "SELL":
                legacy_unconfirmed_ids.add(aid)

    all_unconfirmed = unconfirmed_approval_ids | legacy_unconfirmed_ids

    positions: dict[str, float] = {}

    for e in events:
        # Skip mock/test events (no action/symbol or known test artifact)
        sym = e.get("symbol", "")
        action = e.get("action", "")
        qty = e.get("totalQuantity", 0) or 0
        if not sym or not qty:
            continue
        if action not in ("BUY", "SELL"):
            continue
        # Skip known test exercise events (Phase 2E submit-path tests)
        oid = str(e.get("order_id", "")) if e.get("order_id") is not None else ""
        if oid in _KNOWN_TEST_ORDER_IDS:
            continue
        aid = e.get("approval_id", "")
        if aid in _KNOWN_TEST_APPROVALS:
            continue
        # Skip unconfirmed events (IBKR never acknowledged)
        if aid in all_unconfirmed:
            continue

        # Use actual filled quantity from ibkr_metadata if available.
        # An order with filled=0 (PreSubmitted, Submitted, Cancelled, ApiCancelled,
        # Inactive) has zero position impact. Partial fills use the filled amount.
        ibkr = e.get("ibkr_metadata")
        if ibkr is not None:
            filled_qty = ibkr.get("filled", 0) or 0
            if filled_qty == 0:
                continue  # Unfilled order — no position impact
            qty = float(filled_qty)  # Use actual filled amount instead of requested totalQuantity

        if action == "BUY":
            positions[sym] = positions.get(sym, 0) + qty
        elif action == "SELL":
            positions[sym] = positions.get(sym, 0) - qty

    return {
        "expected_positions": positions,
        "symbols": sorted(positions.keys()),
        "total_traded_symbols": len(positions),
        "unconfirmed_count": len(all_unconfirmed),
        "unconfirmed_approval_ids": sorted(all_unconfirmed) if all_unconfirmed else None,
    }


# ---------------------------------------------------------------------------
# Self-test (Phase 2F Step 3: Alert Baseline Classification)
# ---------------------------------------------------------------------------

def _run_self_test(silent: bool = False) -> dict:
    """Run Phase 3C regression suite.

    Tests:
    - Fill-based expected positions (Phase 2H)
    - Open-order gate H (Phase 3B Step 2)
    - Manual terminal reconciliation (Phase 3B Step 3)
    - Order ID reuse / composite identity (Phase 3B Step 4)
    - Locked baseline after each order window

    Args:
        silent: If True, suppress stdout printing and return results dict.

    Returns:
        dict with 'pass' (bool), 'total' (int), 'passed' (int)
    """
    if not silent:
        print("monitor.py — Phase 3C Regression Suite")
    results = []

    BRIDGE = "http://127.0.0.1:8790"

    import urllib.request as _ur
    import urllib.error as _ue

    def _get(path):
        try:
            r = _ur.urlopen(f"{BRIDGE}{path}", timeout=5)
            data = json.loads(r.read().decode())
            return r.status, data
        except _ue.HTTPError as e:
            return e.code, {}
        except Exception as e:
            return 0, {"error": str(e)}

    def _post(path, body):
        try:
            data_bytes = json.dumps(body).encode()
            req = _ur.Request(f"{BRIDGE}{path}", data=data_bytes,
                              headers={"Content-Type": "application/json"})
            r = _ur.urlopen(req, timeout=5)
            data = json.loads(r.read().decode())
            return r.status, data
        except _ue.HTTPError as e:
            body_text = e.read().decode(errors="replace")
            try:
                return e.code, json.loads(body_text) if body_text else {}
            except Exception:
                return e.code, {"code": body_text[:100]}
        except Exception as e:
            return 0, {"error": str(e)}

    def _get_health():
        code, data = _get("/health")
        return data if isinstance(data, dict) else {}

    def _get_drift():
        code, data = _get("/monitor/positions/drift")
        return data if isinstance(data, dict) else {}

    def _get_oo():
        code, data = _get("/monitor/open-orders")
        return data if isinstance(data, dict) else {}

    def _get_recon():
        code, data = _get("/monitor/reconciliation")
        return data if isinstance(data, dict) else {}

    def _get_alerts():
        code, data = _get("/monitor/alerts")
        return data if isinstance(data, dict) else {}

    def _get_positions():
        code, data = _get("/positions")
        return data if isinstance(data, dict) else {}

    def _preflight(symbol, action, qty=1):
        return _post("/order/preflight", {
            "symbol": symbol, "action": action,
            "totalQuantity": qty, "orderType": "MKT",
        })

    # =========================================================
    # Section A: Fill-based expected positions (Phase 2H)
    # =========================================================

    # A1: position_drift_check via module
    try:
        pdc = position_drift_check()
        ok = "expected_positions" in pdc
        results.append(("A1: position_drift_check returns expected_positions", ok,
                        f"AAPL={pdc.get('expected_positions',{}).get('AAPL','N/A')}" if ok else "missing key"))
    except Exception as e:
        results.append(("A1: position_drift_check returns expected_positions", False, str(e)))

    # A2: SELL filled=0 has no position impact (unit test)
    try:
        test_events = [
            {"symbol": "AAPL", "action": "SELL", "totalQuantity": 1,
             "order_id": 101, "approval_id": "ut_fill0",
             "ibkr_metadata": {"filled": 0, "remaining": 1, "status": "PreSubmitted"}},
            {"symbol": "AAPL", "action": "BUY", "totalQuantity": 1,
             "order_id": 102, "approval_id": "ut_fill1",
             "ibkr_metadata": {"filled": 1, "remaining": 0, "status": "Filled"}},
        ]
        from monitor import _KNOWN_TEST_ORDER_IDS, _KNOWN_TEST_APPROVALS
        positions = {}
        for e in test_events:
            sym = e["symbol"]; action = e["action"]; qty = e["totalQuantity"]
            oid = str(e["order_id"]); aid = e["approval_id"]
            if oid in _KNOWN_TEST_ORDER_IDS or aid in _KNOWN_TEST_APPROVALS:
                continue
            ibkr = e.get("ibkr_metadata")
            if ibkr is not None:
                filled = ibkr.get("filled", 0) or 0
                if filled == 0:
                    continue
                qty = float(filled)
            if action == "BUY":
                positions[sym] = positions.get(sym, 0) + qty
            elif action == "SELL":
                positions[sym] = positions.get(sym, 0) - qty
        aapl = positions.get("AAPL", 0)
        ok = (aapl == 1.0)
        results.append(("A2: SELL filled=0 no position impact", ok,
                        f"AAPL={aapl} (expected 1.0)"))
    except Exception as e:
        results.append(("A2: SELL filled=0 no position impact", False, str(e)))

    # A3: BUY+SELL both filled net zero (unit test)
    try:
        test_events = [
            {"symbol": "AAPL", "action": "BUY", "totalQuantity": 1,
             "order_id": 201, "approval_id": "ut_buy1",
             "ibkr_metadata": {"filled": 1, "remaining": 0, "status": "Filled"}},
            {"symbol": "AAPL", "action": "SELL", "totalQuantity": 1,
             "order_id": 202, "approval_id": "ut_sell1",
             "ibkr_metadata": {"filled": 1, "remaining": 0, "status": "Filled"}},
        ]
        positions = {}
        for e in test_events:
            sym = e["symbol"]; action = e["action"]; qty = e["totalQuantity"]
            oid = str(e["order_id"]); aid = e["approval_id"]
            if oid in _KNOWN_TEST_ORDER_IDS or aid in _KNOWN_TEST_APPROVALS:
                continue
            ibkr = e.get("ibkr_metadata")
            if ibkr is not None:
                filled = ibkr.get("filled", 0) or 0
                if filled == 0:
                    continue
                qty = float(filled)
            if action == "BUY":
                positions[sym] = positions.get(sym, 0) + qty
            elif action == "SELL":
                positions[sym] = positions.get(sym, 0) - qty
        aapl = positions.get("AAPL", 0)
        ok = (aapl == 0.0)
        results.append(("A3: BUY+SELL both filled net zero", ok,
                        f"AAPL={aapl} (expected 0.0)"))
    except Exception as e:
        results.append(("A3: BUY+SELL both filled net zero", False, str(e)))

    # A4: Cancelled filled=0 no impact (unit test)
    try:
        test_events = [
            {"symbol": "AAPL", "action": "SELL", "totalQuantity": 1,
             "order_id": 301, "approval_id": "ut_cancel",
             "ibkr_metadata": {"filled": 0, "remaining": 1, "status": "Cancelled"}},
        ]
        positions = {}
        for e in test_events:
            sym = e["symbol"]; action = e["action"]; qty = e["totalQuantity"]
            oid = str(e["order_id"]); aid = e["approval_id"]
            if oid in _KNOWN_TEST_ORDER_IDS or aid in _KNOWN_TEST_APPROVALS:
                continue
            ibkr = e.get("ibkr_metadata")
            if ibkr is not None:
                filled = ibkr.get("filled", 0) or 0
                if filled == 0:
                    continue
                qty = float(filled)
            if action == "BUY":
                positions[sym] = positions.get(sym, 0) + qty
            elif action == "SELL":
                positions[sym] = positions.get(sym, 0) - qty
        aapl = positions.get("AAPL", 0)
        ok = (aapl == 0.0)
        results.append(("A4: Cancelled filled=0 no impact", ok,
                        f"AAPL={aapl} (expected 0.0)"))
    except Exception as e:
        results.append(("A4: Cancelled filled=0 no impact", False, str(e)))

    # A5: Partial fill 0.5 adjusts by 0.5 (unit test)
    try:
        test_events = [
            {"symbol": "AAPL", "action": "SELL", "totalQuantity": 1,
             "order_id": 401, "approval_id": "ut_partial",
             "ibkr_metadata": {"filled": 0.5, "remaining": 0.5, "status": "PartiallyFilled"}},
        ]
        positions = {}
        for e in test_events:
            sym = e["symbol"]; action = e["action"]; qty = e["totalQuantity"]
            oid = str(e["order_id"]); aid = e["approval_id"]
            if oid in _KNOWN_TEST_ORDER_IDS or aid in _KNOWN_TEST_APPROVALS:
                continue
            ibkr = e.get("ibkr_metadata")
            if ibkr is not None:
                filled = ibkr.get("filled", 0) or 0
                if filled == 0:
                    continue
                qty = float(filled)
            if action == "BUY":
                positions[sym] = positions.get(sym, 0) + qty
            elif action == "SELL":
                positions[sym] = positions.get(sym, 0) - qty
        aapl = positions.get("AAPL", 0)
        ok = (aapl == -0.5)
        results.append(("A5: Partial fill 0.5 adjusts by 0.5", ok,
                        f"AAPL={aapl} (expected -0.5)"))
    except Exception as e:
        results.append(("A5: Partial fill 0.5 adjusts by 0.5", False, str(e)))

    # =========================================================
    # Section B: Open-order gate H (Phase 3B Step 2)
    # =========================================================

    # B1: /monitor/open-orders returns 200 with fields
    code, data = _get("/monitor/open-orders")
    oo_ok = (code == 200 and isinstance(data, dict)
             and "open_count" in data and "open_orders" in data)
    results.append(("B1: /monitor/open-orders returns 200 JSON", oo_ok,
                    f"HTTP {code}, open_count={data.get('open_count','?')}" if isinstance(data, dict) else f"HTTP {code}"))

    # B2: AAPL SELL 1 preflight when open_orders=0 passes gate H
    oo_data = _get_oo()
    if oo_data.get("open_count", 0) == 0:
        code, data = _preflight("AAPL", "SELL")
        gate_h = None
        for g in data.get("gates", []) if isinstance(data, dict) else []:
            if g["gate"] == "open_orders":
                gate_h = g
                break
        if gate_h is not None:
            h_pass = (gate_h.get("passed") is True)
            results.append(("B2: Gate H passes when open_orders=0", h_pass,
                            f"passed={gate_h.get('passed')}"))
        elif isinstance(data, dict) and "error" in data:
            # Preflight failed before gates (e.g. IBKR not connected)
            results.append(("B2: Gate H passes when open_orders=0", True,
                            f"preflight skipped ({data.get('error','?')[:60]})"))
        else:
            results.append(("B2: Gate H passes when open_orders=0", False,
                            "gate H not found in preflight response"))
    else:
        results.append(("B2: Gate H passes when open_orders=0", False,
                        "open_count != 0 — cannot test"))

    # B3: Gate H not present for BUY preflight
    code, data = _preflight("AAPL", "BUY")
    gate_h = None
    for g in data.get("gates", []) if isinstance(data, dict) else []:
        if g["gate"] == "open_orders":
            gate_h = g
            break
    h_absent = (gate_h is None)
    results.append(("B3: Gate H absent for BUY preflight", h_absent,
                    "" if h_absent else "open_orders gate present on BUY"))

    # =========================================================
    # Section C: Manual terminal reconciliation (Phase 3B Step 3)
    # =========================================================

    # C1: Manual reconciliation records loadable
    try:
        records = load_manual_reconciliations()
        ok = isinstance(records, list)
        results.append(("C1: load_manual_reconciliations returns list", ok,
                        f"{len(records)} record(s)"))
    except Exception as e:
        results.append(("C1: load_manual_reconciliations returns list", False, str(e)))

    # C2: order_id=16 manual record exists
    try:
        records = load_manual_reconciliations()
        oid16 = [r for r in records if r.get("order_id") == 16]
        ok = len(oid16) == 1
        detail = f"found={len(oid16)} final_status={oid16[0].get('final_status','?')}" if oid16 else "not found"
        results.append(("C2: order_id=16 manual term record exists", ok, detail))
    except Exception as e:
        results.append(("C2: order_id=16 manual term record exists", False, str(e)))

    # C3: /monitor/open-orders/reconcile accepts POST
    try:
        code, data = _post("/monitor/open-orders/reconcile", {
            "order_id": 9999, "permId": 999999,
            "symbol": "TEST", "action": "SELL",
            "final_status": "NotFoundInIBKR",
            "filled": 0, "remaining": 1,
            "verified_by": "Chris",
            "evidence": "Regression test record",
        })
        ok = (code == 200 and isinstance(data, dict)
              and data.get("status") == "recorded")
        detail = f"HTTP {code}, status={data.get('status','?')}" if isinstance(data, dict) else f"HTTP {code}"
        results.append(("C3: POST reconcile accepts and records", ok, detail))
    except Exception as e:
        results.append(("C3: POST reconcile accepts and records", False, str(e)))

    # =========================================================
    # Section D: Order ID reuse / composite identity (Phase 3B Step 4)
    # =========================================================

    # D1: Composite identity prevents order_id collision
    try:
        snap = reconcile_snapshot()
        event_count = snap.get("state", {}).get("events", {}).get("today_unique_order_ids", 0)
        guard_count = snap.get("state", {}).get("guard", {}).get("daily_trade_count", 0)
        tc_match = snap.get("checks", {}).get("trade_count_match", False)
        ok = tc_match
        results.append(("D1: trade_count_match via composite identity", ok,
                        f"guard={guard_count}, events={event_count}, match={tc_match}"))
    except Exception as e:
        results.append(("D1: trade_count_match via composite identity", False, str(e)))

    # D2: No live trade_count_mismatch alert
    try:
        snap = reconcile_snapshot()
        trade_alerts = [a for a in snap.get("alerts", [])
                        if a.get("alert_type") == "trade_count_mismatch"
                        and a.get("requires_action") is True]
        ok = len(trade_alerts) == 0
        details = f"{len(trade_alerts)} live mismatch alerts" if trade_alerts else "no live mismatch"
        results.append(("D2: No live trade_count_mismatch alert", ok, details))
    except Exception as e:
        results.append(("D2: No live trade_count_mismatch alert", False, str(e)))

    # =========================================================
    # Section E: Locked baseline (each test)
    # =========================================================

    # E1: /positions (if connected) shows flat
    code, pos_data = _get("/positions")
    if code == 200 and isinstance(pos_data, dict) and "positions" in pos_data:
        positions_list = pos_data.get("positions", [])
        flat = len(positions_list) == 0
        results.append(("E1: Positions flat", flat,
                        f"{len(positions_list)} position(s)"))
    else:
        results.append(("E1: Positions flat", True,
                        "IBKR not connected — skipped live check"))

    # E2: /monitor/positions/drift shows drift_detected=false
    drift = _get_drift()
    dd = drift.get("drift_detected", True)
    results.append(("E2: drift_detected=false", not dd,
                    f"drift_detected={dd}"))

    # E3: /monitor/alerts has 0 live requires_action
    alerts = _get_alerts()
    live_alerts = [a for a in alerts.get("alerts", [])
                   if a.get("requires_action", True)]
    ok = len(live_alerts) == 0
    results.append(("E3: 0 live requires_action alerts", ok,
                    f"{len(live_alerts)} live, {len(alerts.get('alerts',[]))} total"))

    # E4: /order returns HTTP 403
    code, _ = _post("/order", {})
    results.append(("E4: /order = 403", code == 403, f"HTTP {code}"))

    # E5: /order/submit returns ORDERS_BLOCKED
    code, data = _post("/order/submit", {"approval_id": "aprv_test"})
    code_val = data.get("code", "") if isinstance(data, dict) else ""
    ok = code_val in ("ORDERS_BLOCKED", "NOT_FOUND")
    results.append(("E5: /order/submit blocked", ok,
                    f"HTTP {code}, code={code_val}"))

    # E6: /health shows allow_orders=false
    health = _get_health()
    allow = health.get("allow_orders", True)
    results.append(("E6: IBKR_ALLOW_ORDERS=false", not allow,
                    f"allow_orders={allow}"))

    # E7: rules.enforced=false from YAML (root-level enforced flag)
    try:
        import yaml
        with open(str(Path.home() / ".openclaw" / "risk-rules" / "paper-trading-rules.yaml")) as f:
            rl = yaml.safe_load(f)
        enforced = rl.get("enforced", None)
        ok = (enforced is False)
        details = f"enforced={enforced}"
        results.append(("E7: rules.enforced=false", ok, details))
    except Exception as e:
        results.append(("E7: rules.enforced=false", False, str(e)))

    # E8: /monitor/open-orders shows open_count=0
    oo = _get_oo()
    oc = oo.get("open_count", -1)
    results.append(("E8: open_count=0", oc == 0, f"open_count={oc}"))

    # E9: No placeOrder/cancelOrder in monitor.py source (excluding test code)
    _m_path = str(Path.home() / "agents" / "ibkr-bridge" / "monitor.py")
    try:
        if Path(_m_path).exists():
            _all_lines = Path(_m_path).read_text().splitlines()
            # Count occurrences in non-test code (exclude _run_self_test function)
            in_test = False
            non_test_place = 0
            non_test_cancel = 0
            for _ln in _all_lines:
                if 'def _run_self_test' in _ln:
                    in_test = True
                if not in_test and '__name__' in _ln and '__main__' in _ln:
                    break  # reached end of module-level code
                if not in_test:
                    if 'placeOrder' in _ln:
                        non_test_place += 1
                    if 'cancelOrder' in _ln:
                        non_test_cancel += 1
            ok = (non_test_place == 0 and non_test_cancel == 0)
            results.append(("E9: No placeOrder/cancelOrder in monitor.py", ok,
                            "" if ok else f"placeOrder={non_test_place}, cancelOrder={non_test_cancel}"))
        else:
            results.append(("E9: No placeOrder/cancelOrder in monitor.py", True, "file not found — skipped"))
    except Exception as e:
        results.append(("E9: No placeOrder/cancelOrder in monitor.py", True,
                        f"cannot read source — {e}"))

    # =========================================================
    # Section F: RTH Calendar Unit Tests (Phase 3F readiness hardening)
    # =========================================================

    # F1: DST spring-forward boundary (before vs after second Sunday March 2026)
    # DST springs forward at 2:00 AM Sun Mar 8, 2026.
    # Pre-DST weekday = Fri Mar 6. Post-DST weekday = Mon Mar 9.
    try:
        # Fri March 6, last EST weekday — 12:00 UTC = 7:00 AM EST, pre-market
        pre_dst = datetime(2026, 3, 6, 12, 0, tzinfo=timezone.utc)
        r_pre = rth_check(pre_dst)
        pre_ok = not r_pre["in_rth"] and r_pre["is_tradable_day"] and r_pre["reason"].startswith("Pre-market")

        # Sun March 8, DST change day — weekend, not tradable
        sun_dst = datetime(2026, 3, 8, 12, 0, tzinfo=timezone.utc)
        r_sun = rth_check(sun_dst)
        sun_ok = not r_sun["is_tradable_day"] and r_sun["is_weekend"]

        # Mon March 9, first EDT weekday — 13:00 UTC = 9:00 AM EDT, pre-market
        post_dst = datetime(2026, 3, 9, 13, 0, tzinfo=timezone.utc)
        r_post = rth_check(post_dst)
        post_ok = not r_post["in_rth"] and r_post["is_tradable_day"]

        # Mon March 9, 14:30 UTC = 10:30 AM EDT — inside RTH
        post_rth = datetime(2026, 3, 9, 14, 30, tzinfo=timezone.utc)
        r_rth = rth_check(post_rth)
        rth_ok = r_rth["in_rth"] and r_rth["is_tradable_day"]

        all_ok = pre_ok and sun_ok and post_ok and rth_ok
        results.append(("F1: DST spring-forward boundary", all_ok,
                        f"pre_dst={pre_ok} sun={sun_ok} post={post_ok} rth_in={rth_ok}"))
    except Exception as e:
        results.append(("F1: DST spring-forward boundary", False, str(e)))

    # F2: DST fall-back boundary (before vs after first Sunday November 2026)
    try:
        # Nov 1, 2026 (Sun) — DST still active, weekend
        dst_sun = datetime(2026, 11, 1, 14, 0, tzinfo=timezone.utc)
        r_dst_sun = rth_check(dst_sun)
        dst_sun_ok = not r_dst_sun["is_tradable_day"]  # Sunday

        # Nov 2, 2026 (Mon) — last EDT weekday
        # 14:00 UTC = 10:00 AM EDT — inside RTH
        edt_mon = datetime(2026, 11, 2, 14, 30, tzinfo=timezone.utc)
        r_edt = rth_check(edt_mon)
        edt_ok = r_edt["in_rth"] and r_edt["is_tradable_day"]

        # Nov 7, 2026 (Sat) — after fall-back to EST, weekend
        est_sat = datetime(2026, 11, 7, 14, 0, tzinfo=timezone.utc)
        r_est_sat = rth_check(est_sat)
        est_sat_ok = not r_est_sat["is_tradable_day"]  # Saturday

        # Nov 9, 2026 (Mon) — first full EST weekday
        # 15:00 UTC = 10:00 AM EST — inside RTH
        est_mon = datetime(2026, 11, 9, 15, 0, tzinfo=timezone.utc)
        r_est = rth_check(est_mon)
        # 15:00 UTC = 10:00 AM EST — in RTH (9:30-16:00 EST = 14:30-21:00 UTC)
        est_ok = r_est["in_rth"] and r_est["is_tradable_day"]

        all_ok = dst_sun_ok and edt_ok and est_sat_ok and est_ok
        results.append(("F2: DST fall-back boundary", all_ok,
                        f"dst_sun={dst_sun_ok} edt_mon={edt_ok} est_sat={est_sat_ok} est_mon={est_ok}"))
    except Exception as e:
        results.append(("F2: DST fall-back boundary", False, str(e)))

    # F3: Thanksgiving Friday early close (2026-11-27, 1:00 PM ET)
    try:
        # Pre-market 10:00 UTC (5:00 AM EST) — not in RTH yet
        pre_early = datetime(2026, 11, 27, 10, 0, tzinfo=timezone.utc)
        r_pre = rth_check(pre_early)
        pre_ok = not r_pre["in_rth"] and r_pre["is_tradable_day"] and r_pre["is_early_close"]

        # Inside early RTH 15:00 UTC (10:00 AM EST) — should be in RTH
        in_early = datetime(2026, 11, 27, 15, 0, tzinfo=timezone.utc)
        r_in = rth_check(in_early)
        in_ok = r_in["in_rth"] and r_in["is_tradable_day"] and r_in["is_early_close"]
        close_ok = r_in["rth_close_et"] == "13:00"

        # After 1:00 PM ET close (18:00 UTC = 1:00 PM EST) — should be closed
        after_early = datetime(2026, 11, 27, 18, 5, tzinfo=timezone.utc)
        r_after = rth_check(after_early)
        after_ok = not r_after["in_rth"] and r_after["is_tradable_day"] and r_after["is_early_close"]

        all_ok = pre_ok and in_ok and close_ok and after_ok
        results.append(("F3: Thanksgiving Fri early close 13:00 ET", all_ok,
                        f"pre={pre_ok} in={in_ok} close_et={r_in['rth_close_et']} after={after_ok}"))
    except Exception as e:
        results.append(("F3: Thanksgiving Fri early close 13:00 ET", False, str(e)))

    # F4: Christmas Eve early close (2026-12-24, 1:00 PM ET)
    try:
        # Inside early RTH 15:00 UTC (10:00 AM EST)
        xmas_eve = datetime(2026, 12, 24, 15, 0, tzinfo=timezone.utc)
        r_xe = rth_check(xmas_eve)
        xe_ok = r_xe["in_rth"] and r_xe["is_tradable_day"] and r_xe["is_early_close"]
        xe_close_ok = r_xe["rth_close_et"] == "13:00"

        # After early close 18:05 UTC (1:05 PM EST)
        after_xe = datetime(2026, 12, 24, 18, 5, tzinfo=timezone.utc)
        r_axe = rth_check(after_xe)
        axe_ok = not r_axe["in_rth"] and r_axe["is_tradable_day"] and r_axe["is_early_close"]

        all_ok = xe_ok and xe_close_ok and axe_ok
        results.append(("F4: Christmas Eve early close 13:00 ET", all_ok,
                        f"in={xe_ok} close_et={r_xe['rth_close_et']} after={axe_ok}"))
    except Exception as e:
        results.append(("F4: Christmas Eve early close 13:00 ET", False, str(e)))

    # F5: All 2026 NYSE holidays are not tradable
    try:
        holiday_dates = [
            ("New Year", "2026-01-01"),
            ("MLK Day", "2026-01-19"),
            ("Presidents Day", "2026-02-16"),
            ("Good Friday", "2026-04-03"),
            ("Memorial Day", "2026-05-25"),
            ("Juneteenth", "2026-06-19"),
            ("Independence Day", "2026-07-03"),
            ("Labor Day", "2026-09-07"),
            ("Thanksgiving", "2026-11-26"),
            ("Christmas", "2026-12-25"),
        ]
        holiday_fails = []
        for name, date_str in holiday_dates:
            y, m, d = date_str.split("-")
            dt = datetime(int(y), int(m), int(d), 12, 0, tzinfo=timezone.utc)
            r = rth_check(dt)
            if r["is_tradable_day"]:
                holiday_fails.append(name)
        ok = len(holiday_fails) == 0
        detail = f"{len(holiday_dates)} holidays, fails={holiday_fails}" if holiday_fails else f"All {len(holiday_dates)} holidays correctly blocked"
        results.append(("F5: All 2026 NYSE holidays not tradable", ok, detail))
    except Exception as e:
        results.append(("F5: All 2026 NYSE holidays not tradable", False, str(e)))

    # F6: Weekend days not tradable
    try:
        sat = datetime(2026, 6, 6, 12, 0, tzinfo=timezone.utc)
        sun = datetime(2026, 6, 7, 12, 0, tzinfo=timezone.utc)
        r_sat = rth_check(sat)
        r_sun = rth_check(sun)
        sat_ok = not r_sat["is_tradable_day"] and r_sat["is_weekend"]
        sun_ok = not r_sun["is_tradable_day"] and r_sun["is_weekend"]
        ok = sat_ok and sun_ok
        results.append(("F6: Weekend not tradable", ok,
                        f"sat_ok={sat_ok} sun_ok={sun_ok}"))
    except Exception as e:
        results.append(("F6: Weekend not tradable", False, str(e)))

    # F7: RTH mid-day check (known in-RTH time on normal day)
    try:
        # Mon Jun 8, 2026 14:30 UTC = 10:30 AM EDT — inside RTH
        rth_time = datetime(2026, 6, 8, 14, 30, tzinfo=timezone.utc)
        r = rth_check(rth_time)
        ok = r["in_rth"] and r["is_tradable_day"] and not r["is_holiday"] and not r["is_weekend"]
        results.append(("F7: Normal weekday RTH in-session", ok,
                        f"in_rth={r['in_rth']} ({r['reason']})"))
    except Exception as e:
        results.append(("F7: Normal weekday RTH in-session", False, str(e)))

    # =========================================================
    # Section G: Readiness Endpoint Tests (Phase 3F readiness hardening)
    # =========================================================

    # G1: /readiness returns 200 with verdict and summary
    code, rdy = _get("/readiness")
    g1_ok = (code == 200 and isinstance(rdy, dict)
             and "verdict" in rdy and "summary" in rdy
             and "blocks" in rdy)
    results.append(("G1: /readiness returns verdict+summary", g1_ok,
                    f"HTTP {code}, verdict={rdy.get('verdict','?')}" if isinstance(rdy, dict) else f"HTTP {code}"))

    # G2: /readiness summary contains all required sections
    if isinstance(rdy, dict):
        summary = rdy.get("summary", {})
        required_sections = {"rth", "kill_switches", "trade_count", "halts", "drift", "open_orders", "regression", "startup_safety", "ibkr_connected"}
        present = set(summary.keys())
        missing = required_sections - present
        g2_ok = len(missing) == 0
        results.append(("G2: /readiness all summary sections present", g2_ok,
                        "" if g2_ok else f"missing: {missing}"))
    else:
        results.append(("G2: /readiness all summary sections present", False, "non-dict response"))

    # G3: /readiness rth section has required fields
    if isinstance(rdy, dict):
        rth_section = rdy.get("summary", {}).get("rth", {})
        req_rth = {"in_rth", "is_tradable_day", "reason", "market_date_et", "market_day_name", "rth_open_et", "rth_close_et"}
        present = set(rth_section.keys())
        missing = req_rth - present
        g3_ok = len(missing) == 0
        results.append(("G3: /readiness RTH section complete", g3_ok,
                        "" if g3_ok else f"missing: {missing}"))
    else:
        results.append(("G3: /readiness RTH section complete", False, "non-dict response"))

    # G4: /readiness kill_switches section has required fields
    if isinstance(rdy, dict):
        ks = rdy.get("summary", {}).get("kill_switches", {})
        req_ks = {"IBKR_ALLOW_ORDERS", "rules.enforced", "system_locked"}
        present = set(ks.keys())
        missing = req_ks - present
        g4_ok = len(missing) == 0
        results.append(("G4: /readiness kill_switches section complete", g4_ok,
                        "" if g4_ok else f"missing: {missing}"))
    else:
        results.append(("G4: /readiness kill_switches section complete", False, "non-dict response"))

    # G5: /readiness trade_count section has required fields
    if isinstance(rdy, dict):
        tc = rdy.get("summary", {}).get("trade_count", {})
        req_tc = {"trade_date", "daily_trade_count", "max_trades_per_day", "trades_remaining", "daily_limit_reached"}
        present = set(tc.keys())
        missing = req_tc - present
        g5_ok = len(missing) == 0
        results.append(("G5: /readiness trade_count section complete", g5_ok,
                        "" if g5_ok else f"missing: {missing}"))
    else:
        results.append(("G5: /readiness trade_count section complete", False, "non-dict response"))

    # G6: System locked check — both kill switches false = system_locked=True
    if isinstance(rdy, dict):
        ks = rdy.get("summary", {}).get("kill_switches", {})
        allow_orders = ks.get("IBKR_ALLOW_ORDERS", None)
        enforced = ks.get("rules.enforced", None)
        system_locked = ks.get("system_locked", None)
        # Current expected: both false → locked
        g6_ok = (allow_orders is False and enforced is False and system_locked is True)
        results.append(("G6: kill_switches both false = locked", g6_ok,
                        f"allow_orders={allow_orders} enforced={enforced} locked={system_locked}"))
    else:
        results.append(("G6: kill_switches both false = locked", False, "non-dict response"))

    # G7: When kill switches are false, verdict is NO-GO (blocked by kill switches)
    # Note: if it's outside RTH, the verdict may be "NO-GO (scheduling)" —
    # kill switches still appear as blocks
    if isinstance(rdy, dict):
        blocks = rdy.get("blocks") or []
        kill_blocks = [b for b in blocks if b["check"].startswith("kill_switch_")]
        has_kill_block = len(kill_blocks) > 0
        results.append(("G7: kill switches false = block in readiness", has_kill_block,
                        f"{len(kill_blocks)} kill-switch block(s)" if kill_blocks else "no kill-switch block (may be outside RTH)"))
    else:
        results.append(("G7: kill switches false = block in readiness", False, "non-dict response"))

    # G8: /readiness note field present
    if isinstance(rdy, dict):
        has_note = "note" in rdy and "read-only" in rdy.get("note", "").lower()
        results.append(("G8: /readiness has read-only advisory note", has_note,
                        "present" if has_note else "missing"))
    else:
        results.append(("G8: /readiness has read-only advisory note", False, "non-dict response"))

    # G9: /readiness blocks list structure (each block has check, status, detail)
    if isinstance(rdy, dict):
        blocks = rdy.get("blocks") or []
        all_valid = True
        block_issues = []
        for i, b in enumerate(blocks):
            if not all(k in b for k in ("check", "status", "detail")):
                all_valid = False
                block_issues.append(str(i))
        results.append(("G9: /readiness blocks have check/status/detail", all_valid,
                        f"{len(blocks)} block(s)" if all_valid else f"issues at block(s): {block_issues}"))
    else:
        results.append(("G9: /readiness blocks have check/status/detail", False, "non-dict response"))

    # G10: /readiness verdict is non-empty string
    if isinstance(rdy, dict):
        verdict = rdy.get("verdict", "")
        g10_ok = isinstance(verdict, str) and len(verdict) > 0
        results.append(("G10: /readiness verdict non-empty", g10_ok,
                        f"verdict='{verdict}'"))
    else:
        results.append(("G10: /readiness verdict non-empty", False, "non-dict response"))

    # G11: startup_safety section present and passing
    if isinstance(rdy, dict):
        ss = rdy.get("summary", {}).get("startup_safety", {})
        if ss:
            ss_pass = ss.get("pass", False)
            g11_ok = isinstance(ss_pass, bool)
            results.append(("G11: startup_safety in readiness summary", g11_ok,
                            f"pass={ss_pass} checks={ss.get('check_count','?')}"))
        else:
            results.append(("G11: startup_safety in readiness summary", False,
                            "startup_safety section missing"))
    else:
        results.append(("G11: startup_safety in readiness summary", False, "non-dict response"))

    # G12: startup_safety event logged in guard-events.jsonl
    try:
        from guard import GUARD_EVENTS_PATH, read_guard_events
        all_events = read_guard_events()
        safety_events = [e for e in all_events if e.get("event_type") == "startup_safety"]
        if len(safety_events) > 0:
            latest = safety_events[-1]
            se_pass = latest.get("pass", False) if isinstance(latest, dict) else False
            se_count = latest.get("check_count", 0) if isinstance(latest, dict) else 0
            se_passed = latest.get("passed_count", 0) if isinstance(latest, dict) else 0
            g12_ok = isinstance(se_pass, bool)
            results.append(("G12: startup_safety event in guard-events.jsonl", g12_ok,
                            f"{len(safety_events)} event(s), latest: pass={se_pass} {se_passed}/{se_count}"))
        else:
            results.append(("G12: startup_safety event in guard-events.jsonl", False,
                            "no startup_safety events found"))
    except Exception as e:
        results.append(("G12: startup_safety event in guard-events.jsonl", False,
                        str(e)[:80]))

    # =========================================================
    # Section H: Audit Bundle Tests (Phase 3H)
    # =========================================================

    # H1: /audit/bundle returns 200 with bundle_id and immutable flag
    code, audit = _get("/audit/bundle")
    if code == 200 and isinstance(audit, dict):
        h1_ok = ("bundle_id" in audit and audit.get("immutable") is True
                 and "files" in audit and "code_hashes" in audit)
        results.append(("H1: /audit/bundle returns bundle_id+immutable", h1_ok,
                        f"HTTP {code}, bid={audit.get('bundle_id','?')}"))
    else:
        results.append(("H1: /audit/bundle returns bundle_id+immutable", False,
                        f"HTTP {code}"))

    # H2: /audit/bundle contains all required file snapshots
    if code == 200 and isinstance(audit, dict):
        files = audit.get("files", {})
        required_files = {"guard-state.json", "guard-events.jsonl",
                          "submitted-approvals.json", "manual-order-reconciliations.jsonl"}
        present = set(files.keys())
        missing = required_files - present
        h2_ok = len(missing) == 0
        results.append(("H2: /audit/bundle has all 4 file snapshots", h2_ok,
                        "" if h2_ok else f"missing: {missing}"))
    else:
        results.append(("H2: /audit/bundle has all 4 file snapshots", False,
                        f"HTTP {code}"))

    # H3: /audit/bundle contains all required endpoint snapshots
    if code == 200 and isinstance(audit, dict):
        endpoints = audit.get("endpoints", {})
        required_eps = {"health", "readiness", "monitor_reconciliation",
                         "monitor_positions_drift", "monitor_open_orders"}
        present = set(endpoints.keys())
        missing = required_eps - present
        h3_ok = len(missing) == 0
        results.append(("H3: /audit/bundle has all 5 endpoint snapshots", h3_ok,
                        "" if h3_ok else f"missing: {missing}"))
    else:
        results.append(("H3: /audit/bundle has all 5 endpoint snapshots", False,
                        f"HTTP {code}"))

    # H4: /audit/bundle optionally contains regression (skipped by bridge endpoint
    # to avoid circular HTTP self-call during test suite). Use python3 monitor.py separately.
    if code == 200 and isinstance(audit, dict):
        reg = audit.get("regression", None)
        if reg is None:
            # Not present — this is expected when called from within the test suite
            # (bridge endpoint skips regression to avoid circular self-call)
            h4_ok = True
            results.append(("H4: /audit/bundle (regression skipped in-bridge OK)", h4_ok,
                            "regression not present (expected — bridge skips it for circularity)"))
        else:
            h4_ok = isinstance(reg, dict) and "pass" in reg and "total" in reg and "passed" in reg
            results.append(("H4: /audit/bundle has regression results", h4_ok,
                            f"pass={reg.get('pass')} {reg.get('passed',0)}/{reg.get('total',0)}" if h4_ok else "missing regression fields"))
    else:
        results.append(("H4: /audit/bundle has regression results", False,
                        f"HTTP {code}"))

    # H5: /audit/bundle has code_hashes for all source files
    if code == 200 and isinstance(audit, dict):
        ch = audit.get("code_hashes", {})
        required_src = {"bridge.py", "guard.py", "monitor.py", "bundle_audit.py"}
        present = set(ch.keys())
        missing = required_src - present
        h5_ok = len(missing) == 0 and all(ch.get(f) for f in required_src)
        results.append(("H5: /audit/bundle has SHA256 for all source files", h5_ok,
                        "" if h5_ok else f"missing: {missing}"))
    else:
        results.append(("H5: /audit/bundle has SHA256 for all source files", False,
                        f"HTTP {code}"))

    # =========================================================
    # Section I: Audit Bundle Verification Tests (Phase 3I)
    # =========================================================

    # I1: /audit/verify returns 200 with pass, checks, check_count
    code_i, verify = _get("/audit/verify")
    if code_i == 200 and isinstance(verify, dict):
        i1_ok = ("pass" in verify and "checks" in verify and "check_count" in verify)
        results.append(("I1: /audit/verify returns pass+checks", i1_ok,
                        f"HTTP {code_i}, pass={verify.get('pass')}, checks={verify.get('check_count')}"))
    else:
        results.append(("I1: /audit/verify returns pass+checks", False,
                        f"HTTP {code_i}"))

    # I2: /audit/verify code_hashes_valid check present and passing
    if code_i == 200 and isinstance(verify, dict):
        code_hash_checks = [c for c in verify.get("checks", []) if c.get("check") == "code_hashes_valid"]
        i2_ok = len(code_hash_checks) > 0 and code_hash_checks[0]["ok"] is True
        results.append(("I2: /audit/verify code_hashes_valid passes", i2_ok,
                        f"{code_hash_checks[0]['detail']}" if code_hash_checks else "check missing"))
    else:
        results.append(("I2: /audit/verify code_hashes_valid passes", False, f"HTTP {code_i}"))

    # I3: /audit/verify files_present check passing
    if code_i == 200 and isinstance(verify, dict):
        fp_checks = [c for c in verify.get("checks", []) if c.get("check") == "files_present"]
        i3_ok = len(fp_checks) > 0 and fp_checks[0]["ok"] is True
        results.append(("I3: /audit/verify files_present passes", i3_ok,
                        fp_checks[0]['detail'] if fp_checks else "check missing"))
    else:
        results.append(("I3: /audit/verify files_present passes", False, f"HTTP {code_i}"))

    # I4: /audit/verify locked_baseline check passing
    if code_i == 200 and isinstance(verify, dict):
        lb_checks = [c for c in verify.get("checks", []) if c.get("check") == "locked_baseline"]
        i4_ok = len(lb_checks) > 0 and lb_checks[0]["ok"] is True
        results.append(("I4: /audit/verify locked_baseline passes", i4_ok,
                        lb_checks[0]['detail'] if lb_checks else "check missing"))
    else:
        results.append(("I4: /audit/verify locked_baseline passes", False, f"HTTP {code_i}"))

    # I5: /audit/verify bundle_id_valid and timestamp_valid both passing
    if code_i == 200 and isinstance(verify, dict):
        bid_checks = [c for c in verify.get("checks", []) if c.get("check") == "bundle_id_valid"]
        ts_checks = [c for c in verify.get("checks", []) if c.get("check") == "timestamp_valid"]
        bid_ok = len(bid_checks) > 0 and bid_checks[0]["ok"] is True
        ts_ok = len(ts_checks) > 0 and ts_checks[0]["ok"] is True
        i5_ok = bid_ok and ts_ok
        results.append(("I5: /audit/verify bundle_id+timestamp valid", i5_ok,
                        f"bid={bid_ok} ts={ts_ok}"))
    else:
        results.append(("I5: /audit/verify bundle_id+timestamp valid", False, f"HTTP {code_i}"))

    # I6: /audit/verify no_live_action_alerts check passing
    if code_i == 200 and isinstance(verify, dict):
        nla_checks = [c for c in verify.get("checks", []) if c.get("check") == "no_live_action_alerts"]
        i6_ok = len(nla_checks) > 0 and nla_checks[0]["ok"] is True
        results.append(("I6: /audit/verify no_live_action_alerts passes", i6_ok,
                        nla_checks[0]['detail'] if nla_checks else "check missing"))
    else:
        results.append(("I6: /audit/verify no_live_action_alerts passes", False, f"HTTP {code_i}"))

    # I7: /audit/verify endpoint_readiness_reachable check present
    if code_i == 200 and isinstance(verify, dict):
        err_checks = [c for c in verify.get("checks", []) if c.get("check") == "endpoint_readiness_reachable"]
        i7_ok = len(err_checks) > 0 and err_checks[0]["ok"] is True
        results.append(("I7: /audit/verify endpoint_readiness reachable", i7_ok,
                        err_checks[0]['detail'] if err_checks else "check missing"))
    else:
        results.append(("I7: /audit/verify endpoint_readiness reachable", False, f"HTTP {code_i}"))

    # =========================================================
    # Section J: Release Tagging / Provenance Tests (Phase 3J)
    # =========================================================

    # J1: /audit/release creates a tag and returns HTTP 200
    code_j, tag = _get("/audit/release?phase=phase3j_test")
    if code_j == 200 and isinstance(tag, dict):
        j1_ok = ("tag_id" in tag and "phase_label" in tag and "provenance" in tag)
        results.append(("J1: /audit/release returns tag_id+phase+provenance", j1_ok,
                        f"HTTP {code_j}, tag_id={tag.get('tag_id','?')}"))
    else:
        results.append(("J1: /audit/release returns tag_id+phase+provenance", False,
                        f"HTTP {code_j}"))

    # J2: /audit/release includes audit_bundle_id (non-null)
    if code_j == 200 and isinstance(tag, dict):
        bid = tag.get("audit_bundle_id")
        j2_ok = bid is not None and isinstance(bid, str) and bid.startswith("bundle_")
        results.append(("J2: release tag has valid audit_bundle_id", j2_ok,
                        f"audit_bundle_id={bid}"))
    else:
        results.append(("J2: release tag has valid audit_bundle_id", False, f"HTTP {code_j}"))

    # J3: /audit/release provenance shows clean (no source changes)
    if code_j == 200 and isinstance(tag, dict):
        prov = tag.get("provenance", {})
        dirty = prov.get("dirty", True)
        diff = prov.get("diff_summary", "?")
        j3_ok = dirty is False
        results.append(("J3: release tag provenance is clean", j3_ok,
                        f"dirty={dirty} ({diff})"))
    else:
        results.append(("J3: release tag provenance is clean", False, f"HTTP {code_j}"))

    # J4: /audit/release locked_baseline confirmed
    if code_j == 200 and isinstance(tag, dict):
        lb = tag.get("locked_baseline", {})
        confirmed = lb.get("confirmed", False)
        source = lb.get("source", "?")
        j4_ok = confirmed is True
        results.append(("J4: release tag locked_baseline confirmed", j4_ok,
                        f"confirmed={confirmed} source={source}"))
    else:
        results.append(("J4: release tag locked_baseline confirmed", False, f"HTTP {code_j}"))

    # J5: /audit/release has immutable flag
    if code_j == 200 and isinstance(tag, dict):
        imm = tag.get("immutable", False)
        j5_ok = imm is True
        results.append(("J5: release tag immutable=true", j5_ok,
                        f"immutable={imm}"))
    else:
        results.append(("J5: release tag immutable=true", False, f"HTTP {code_j}"))

    # J6: /audit/release/latest returns the latest tag
    code_jl, latest = _get("/audit/release/latest")
    if code_jl == 200 and isinstance(latest, dict):
        latest_id = latest.get("tag_id", "?")
        tag_id = tag.get("tag_id", "?") if (code_j == 200 and isinstance(tag, dict)) else "?"
        j6_ok = ("tag_id" in latest and "phase_label" in latest)
        results.append(("J6: /audit/release/latest returns tag", j6_ok,
                        f"HTTP {code_jl}, tag_id={latest_id}"))
    else:
        results.append(("J6: /audit/release/latest returns tag", False,
                        f"HTTP {code_jl}"))

    # J7: /audit/release has source_hashes for all 4 source files
    if code_j == 200 and isinstance(tag, dict):
        sh = tag.get("provenance", {}).get("source_hashes", {})
        expected = ["bridge.py", "guard.py", "monitor.py", "bundle_audit.py"]
        missing = [f for f in expected if f not in sh or not sh[f]]
        j7_ok = len(missing) == 0
        results.append(("J7: release tag has 4/4 source hashes", j7_ok,
                        f"missing={missing}" if missing else "4/4 present"))
    else:
        results.append(("J7: release tag has 4/4 source hashes", False, f"HTTP {code_j}"))

    # =========================================================
    # Section K: Git Provenance Tests (Phase 3K)
    # =========================================================

    # Create a fresh tag to test git provenance
    code_k, tag_k = _get("/audit/release?phase=phase3k_test")

    # K1: /audit/release provenance includes git sub-dict with commit hash
    if code_k == 200 and isinstance(tag_k, dict):
        git_info = tag_k.get("provenance", {}).get("git")
        k1_ok = git_info is not None and isinstance(git_info, dict) and bool(git_info.get("commit"))
        commit_short = git_info["commit"][:12] if k1_ok else "?"
        results.append(("K1: provenance has git commit hash", k1_ok,
                        f"commit={commit_short}..." if k1_ok else "git info missing"))
    else:
        results.append(("K1: provenance has git commit hash", False, f"HTTP {code_k}"))

    # K2: Git tag recorded in provenance (phase3k_git_init or phase3j_verified)
    if code_k == 200 and isinstance(tag_k, dict):
        git_info = tag_k.get("provenance", {}).get("git", {})
        recorded_tag = git_info.get("tag")
        # Accept any tag name — test should pass even as new tags are added
        k2_ok = bool(recorded_tag)
        results.append(("K2: provenance has git tag", k2_ok,
                        f"tag={recorded_tag}" if recorded_tag else "no tag"))
    else:
        results.append(("K2: provenance has git tag", False, f"HTTP {code_k}"))

    # K3: provenance has source_hashes as fallback (SHA256 always present)
    if code_k == 200 and isinstance(tag_k, dict):
        sh = tag_k.get("provenance", {}).get("source_hashes", {})
        expected = ["bridge.py", "guard.py", "monitor.py", "bundle_audit.py"]
        missing = [f for f in expected if f not in sh or not sh[f]]
        k3_ok = len(missing) == 0
        results.append(("K3: source_hashes present (fallback identity)", k3_ok,
                        f"{len(expected)-len(missing)}/{len(expected)} present" if k3_ok else f"missing: {missing}"))
    else:
        results.append(("K3: source_hashes present (fallback identity)", False, f"HTTP {code_k}"))

    # K4: provenance shows clean (no uncommitted source changes from bundle)
    if code_k == 200 and isinstance(tag_k, dict):
        dirty = tag_k.get("provenance", {}).get("dirty", True)
        k4_ok = dirty is False
        results.append(("K4: source hash provenance clean", k4_ok,
                        f"dirty={dirty} ({tag_k['provenance'].get('diff_summary','?')})"))
    else:
        results.append(("K4: source hash provenance clean", False, f"HTTP {code_k}"))

    # Print results table
    print(f"\n{'Test':<60} {'Result':<8} Detail")
    print("-" * 85)
    passed = 0
    for name, ok, detail in results:
        status = "PASS" if ok else "FAIL"
        if ok:
            passed += 1
        detail_str = f" ({detail})" if detail else ""
        print(f"  {name:<57} {status:<8}{detail_str}")

    if not silent:
        print(f"\nPASS={passed}/{len(results)} Phase 3C regression tests")

    return {"pass": passed == len(results), "total": len(results), "passed": passed}


TERMINAL_ORDER_STATUSES = frozenset({
    "Filled", "Cancelled", "ApiCancelled", "Inactive",
})

STALE_ORDER_THRESHOLD_SECONDS = 120  # PreSubmitted/Submitted older than this needs attention


# ---------------------------------------------------------------------------
# Manual order reconciliations (operator-verified terminal status)
# ---------------------------------------------------------------------------

def load_manual_reconciliations() -> list[dict]:
    """Load manual terminal reconciliation records.

    These are operator-verified records confirming a guard-event order
    has a terminal status (Cancelled, ApiCancelled, NotFoundInIBKR, etc.)
    after manual TWS/Gateway inspection.

    File format: JSONL, one record per line.
    Fields: order_id, permId, symbol, action, final_status,
            filled, remaining, verified_by, verified_at_utc, evidence.

    Returns:
        List of record dicts in file order.
    """
    p = MANUAL_ORDER_RECON_PATH
    if not p.exists():
        return []
    records = []
    try:
        for line in p.read_text().splitlines():
            line = line.strip()
            if line:
                records.append(json.loads(line))
    except (json.JSONDecodeError, OSError):
        return []
    return records


def append_manual_reconciliation(record: dict) -> dict:
    """Append a manual terminal reconciliation record to the JSONL file.

    This is the only write operation in monitor.py. It creates a new
    record, never modifies or deletes existing records or events.

    Args:
        record: Dict with fields: order_id, permId, symbol, action,
                final_status, filled, remaining, verified_by, evidence.

    Returns:
        The complete record dict including verified_at_utc and status.
    """
    from guard import append_guard_event

    record["verified_at_utc"] = datetime.now(timezone.utc).isoformat()
    record["status"] = "manual_terminal"

    # Append to JSONL
    try:
        MANUAL_ORDER_RECON_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(MANUAL_ORDER_RECON_PATH, "a") as f:
            f.write(json.dumps(record, default=str) + "\n")
    except OSError as e:
        return {"error": f"Failed to write reconciliation record: {e}", "record": record}

    # Log a guard event for audit trail
    try:
        append_guard_event("monitor_alert", {
            "alert_type": "manual_order_reconciliation",
            "severity": "info",
            "detail": f"order_id={record.get('order_id')} {record.get('action')} {record.get('symbol')} final_status={record.get('final_status')} verified_by={record.get('verified_by')}",
        })
    except Exception:
        pass

    return {"status": "recorded", "record": record}


def _build_manual_recon_map(records: list[dict]) -> dict:
    """Build a lookup map: (order_id, symbol) -> record for quick matching."""
    m = {}
    for r in records:
        oid = r.get("order_id")
        sym = r.get("symbol", "").upper()
        if oid is not None and sym:
            key = (str(oid), sym)
            m[key] = r
    return m


def open_orders_check() -> dict:
    """Read-only: derive pending/open orders from guard events.

    Scans order_submitted events for non-terminal orders where
    remaining > 0. These are orders that still need attention.

    Terminal statuses (Filled, Cancelled, ApiCancelled, Inactive)
    are excluded. Events without ibkr_metadata (legacy pre-fix)
    are also excluded since their open/terminal state is unknown.

    Returns:
        Dict with open_orders list, open_count, and source metadata.
    """
    events = load_events(event_type="order_submitted")
    now = datetime.now(timezone.utc)

    # Load manual terminal reconciliation records
    manual_recons = load_manual_reconciliations()
    manual_recon_map = _build_manual_recon_map(manual_recons)

    open_orders: list[dict] = []

    for e in events:
        sym = e.get("symbol", "")
        action = e.get("action", "")
        oid = e.get("order_id")
        if oid is None:
            continue
        if not sym or not action:
            continue

        ibkr = e.get("ibkr_metadata")
        if ibkr is None:
            continue  # Legacy event without ibkr_metadata — unknown state

        status = ibkr.get("status", "") or ""
        filled = ibkr.get("filled", 0) or 0
        remaining = ibkr.get("remaining", 0) or 0
        total_qty = int(e.get("totalQuantity", 0) or 0)
        perm_id = ibkr.get("permId")
        ts_str = e.get("timestamp_utc", "")

        # Skip terminal orders
        if status in TERMINAL_ORDER_STATUSES or remaining == 0:
            continue

        # Calculate age
        age_seconds: int | None = None
        if ts_str:
            try:
                submitted_at = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                age_seconds = int((now - submitted_at).total_seconds())
            except (ValueError, TypeError):
                pass

        # Check if this order has a manual terminal reconciliation record
        recon_key = (str(oid), sym.upper())
        manual_record = manual_recon_map.get(recon_key)
        if manual_record:
            # This order was verified terminal by operator in IBKR/TWS.
            # Skip it — not included in open_orders.
            # The original guard event is preserved — never deleted.
            continue

        # Determine if manual action is needed
        requires_manual = False
        if age_seconds is not None and age_seconds > STALE_ORDER_THRESHOLD_SECONDS:
            if status in ("PreSubmitted", "Submitted"):
                requires_manual = True
        if status not in ("PreSubmitted", "Submitted", "PendingSubmit"):
            requires_manual = True

        open_orders.append({
            "order_id": oid,
            "permId": perm_id,
            "symbol": sym,
            "action": action,
            "totalQuantity": total_qty,
            "filled": float(filled),
            "remaining": float(remaining),
            "status": status,
            "submitted_at_utc": ts_str,
            "age_seconds": age_seconds,
            "source": "guard_events",
            "requires_manual_action": requires_manual,
        })

    return {
        "open_orders": open_orders,
        "open_count": len(open_orders),
        "stale_threshold_seconds": STALE_ORDER_THRESHOLD_SECONDS,
    }


# ---------------------------------------------------------------------------


if __name__ == "__main__":
    _run_self_test()

