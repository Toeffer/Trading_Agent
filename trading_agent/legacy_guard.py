#!/usr/bin/env python3
"""
guard.py — Phase 2 Guarded Order Validation Layer
Step 1: YAML config loading and validation.

This module will eventually contain all preflight validation logic.
For now (Step 1), it only loads and validates
paper-trading-rules.yaml v1.3-draft.

Usage:
    python3 -c "from guard import load_rules; r = load_rules(); print('OK')"

    python3 -c "from guard import load_guard_state; s = load_guard_state(); print(s)"

    python3 -c "from guard import fetch_account; a = fetch_account(); print(a)"

    python3 -c "from guard import fetch_quote; q = fetch_quote('AAPL'); print(q)"

    python3 -c "from guard import fetch_bars; b = fetch_bars('AAPL'); print(len(b), 'bars')"

Direct test:
    python3 guard.py --test
"""

import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Any

if TYPE_CHECKING:
    from trading_agent.application import ExecutionService

_execution_service: "ExecutionService | None" = None
_proposal_loader: Callable[[str | None], dict[str, Any]] | None = None

# Phase 19B/B4: Gate I (sector concentration) — single source of truth for
# the counting/precedence logic lives in strategy_v1_1_core.py (B1, pure,
# 257 tests). guard.py's gate_sector_concentration() below is a thin adapter
# only — it must never reimplement this logic (H2 invariant).
from strategy_v1_1_core import gate_sector_concentration as _core_gate_sector_concentration

try:
    import yaml
except ImportError:
    yaml = None  # will be checked at load time

GUARD_STATE_PATH = Path(os.environ.get(
    "IBKR_GUARD_STATE_PATH",
    str(Path.home() / ".openclaw" / "guard-state.json")
))

# ---------------------------------------------------------------------------
# Phase H1 — Protected File Paths
# ---------------------------------------------------------------------------
# These files must never be modified by Werner/OpenClaw directly.
# All mutations require H1 token authorization through the bridge.

import contextvars
from contextlib import contextmanager

PROTECTED_PATHS: set[Path] = set()


def _init_protected_paths() -> None:
    """Initialize the set of protected file paths.

    Called once at module load. Protected files include:
    - .env (bridge configuration)
    - paper-trading-rules.yaml (risk rules)
    - guard-state.json (trading state)
    - approval-records.jsonl (approval history)
    - active-approvals.json (pending approvals snapshot)
    - submitted-approvals.json (submitted tracking)

    Note: guard-events.jsonl is NOT in the protected set — it is
    append-only and safety events (submit_blocked, etc.) must always
    be loggable without H1 token.
    """
    home = Path.home()
    PROTECTED_PATHS.update([
        Path(home / "agents" / "ibkr-bridge" / ".env").resolve(),
        Path(home / ".openclaw" / "risk-rules" / "paper-trading-rules.yaml").resolve(),
        Path(home / ".openclaw" / "guard-state.json").resolve(),
        Path(home / ".openclaw" / "approval-records.jsonl").resolve(),
        Path(home / ".openclaw" / "active-approvals.json").resolve(),
        Path(home / ".openclaw" / "submitted-approvals.json").resolve(),
    ])


_init_protected_paths()

# Phase H1: ContextVar-based H1 authorization — per-request, no global boolean.
# Replaces the old global _h1_authorized which could cause race conditions
# under concurrent requests (one request's deauthorize could unguard another).
_h1_authorized: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "h1_authorized", default=False
)

# Startup phase flag — H1 enforcement is suspended during module init
_h1_startup_complete: bool = False


def h1_startup_done() -> None:
    """Mark H1 startup phase as complete.

    Called by bridge after startup reconciliation finishes.
    After this, all protected file writes require H1 token authorization.
    """
    global _h1_startup_complete
    _h1_startup_complete = True


def h1_authorize() -> None:
    """Enable H1-authorized mode for the current request context.

    Uses ContextVar so authorization is scoped to the current
    request/thread — no global boolean that could race under
    concurrent requests.  Must be paired with h1_deauthorize().
    """
    _h1_authorized.set(True)


def h1_deauthorize() -> None:
    """Disable H1-authorized mode after request completes."""
    _h1_authorized.set(False)


@contextmanager
def h1_authorized_scope():
    """Context manager for H1-authorized critical section.

    Sets authorization only for the narrow critical section.
    Always resets in finally — no exception path can leak
    authorization across requests/tasks.

    Usage:
        with h1_authorized_scope():
            save_guard_state_atomic(data)

    Replaces the raw h1_authorize()/h1_deauthorize() pair
    which is error-prone (forgotten finally, misplaced
    deauthorize before critical section completes).

    Safety invariants:
    - Never stores authorization globally (ContextVar only)
    - Never uses mutable global bool for H1 authorization
    - Authorization is request/task-local
    - Reset guaranteed in finally (even on exception)
    """
    authorization_token = _h1_authorized.set(True)
    try:
        yield
    finally:
        _h1_authorized.reset(authorization_token)


def _is_protected_path(target: Path) -> bool:
    """Check if a path is in the protected set."""
    try:
        resolved = target.resolve()
    except OSError:
        resolved = target
    return resolved in PROTECTED_PATHS


def _assert_h1_authorized_for_path(target: Path) -> None:
    """Raise PermissionError if target is protected and H1 not authorized.

    Authorization is per-request via contextvars.ContextVar — no
    global boolean that could deadlock or race under concurrency.

    Startup reconciliation (before h1_startup_done()) is exempt.
    """
    # Skip enforcement during module startup reconciliation
    if not _h1_startup_complete:
        return
    if _is_protected_path(target) and not _h1_authorized.get():
        raise PermissionError(
            f"Protected file write blocked: {target}. "
            f"H1 approval token required for mutations to this file. "
            f"Werner/OpenClaw cannot modify protected configuration or guard-state directly."
        )

# --- Guards for Step 2 (will be wired from rules in orchestrator) ---

EXPECTED_SCHEMA_VERSION = 1


def _now_utc_iso() -> str:
    """Return current UTC time as ISO 8601 string."""
    return datetime.now(timezone.utc).isoformat()


def _today_utc_str() -> str:
    """Return YYYY-MM-DD for the current UTC day."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def canonical_trade_date(now_utc: datetime | None = None) -> str:
    """Return the canonical trading date as YYYY-MM-DD (UTC).

    This is the SINGLE SOURCE OF TRUTH for date comparison across ALL
    guard-state consumers:
      - guard-state-reconcile (Step 15O)
      - guard-state-drift-sentinel (Step 15U)
      - monitor/alerts trade_count_mismatch
      - KPI active-alert logic
      - _rollover_guard_state

    All consumers MUST use this function to determine "what trading date
    is it" so that trade_date comparisons are consistent.

    Args:
        now_utc: Optional override for testing. Defaults to datetime.now(UTC).

    Returns:
        str like "2026-06-25"
    """
    dt = now_utc if now_utc is not None else datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%d")


def _stream_count_confirmed_orders_for_date(
    trade_date: str,
    events_path: Path | None = None,
) -> int:
    """Count confirmed unique orders for a given trade_date using streaming.

    Uses the same canonical logic as monitor.reconcile_snapshot():
    - Composite identity: permId > approval_id > event_id
    - Excludes test artifacts (test-bracket-, test-double-, permId=5001, etc.)
    - Excludes unconfirmed orders (order_unconfirmed events)
    - Streams the events file (no full-memory load)

    Args:
        trade_date: YYYY-MM-DD date string to filter events by.
        events_path: Optional override for events file path.

    Returns:
        int: number of confirmed unique orders for the given date.
    """
    p = Path(events_path) if events_path else GUARD_EVENTS_PATH
    if not p.exists():
        return 0

    unconfirmed_aids: set[str] = set()
    submitted_events: list[dict] = []

    try:
        with open(p, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    evt = json.loads(line)
                except json.JSONDecodeError:
                    continue

                et = evt.get("event_type", "")

                # Track unconfirmed orders
                if et == "order_unconfirmed":
                    aid = evt.get("approval_id", "")
                    if aid:
                        unconfirmed_aids.add(aid)
                    continue

                # Collect only order_submitted for the target date
                if et != "order_submitted":
                    continue

                ts = evt.get("timestamp_utc", "")
                if not ts.startswith(trade_date):
                    continue

                # Exclude test artifacts inline
                aid = str(evt.get("approval_id", ""))
                if aid.startswith(("test-bracket-", "test-double-")):
                    continue

                submitted_events.append(evt)
    except Exception:
        return 0

    # Mark SELL events with no ibkr_metadata as unconfirmed
    for e in submitted_events:
        aid = e.get("approval_id", "")
        if aid and aid not in unconfirmed_aids:
            ibkr = e.get("ibkr_metadata")
            if ibkr is None and e.get("action") == "SELL":
                unconfirmed_aids.add(aid)

    # Filter to confirmed and use composite identity
    confirmed_identities: set[str] = set()
    for e in submitted_events:
        aid = e.get("approval_id", "")
        if aid in unconfirmed_aids:
            continue

        ibkr = e.get("ibkr_metadata")
        if ibkr and ibkr.get("permId") is not None:
            pid = ibkr["permId"]
            if pid == 5001:  # known test artifact
                continue
            identity = f"permId:{pid}"
        elif aid:
            identity = f"approval:{aid}"
        elif e.get("event_id"):
            identity = f"event:{e['event_id']}"
        else:
            oid = e.get("order_id")
            if oid is not None:
                oid_str = str(oid)
                if oid_str in {"12345", "99999", "1001"}:
                    continue
                identity = f"order_id:{oid_str}"
            else:
                continue

        confirmed_identities.add(identity)

    return len(confirmed_identities)


def _current_week_monday_utc_str() -> str:
    """Return YYYY-MM-DD for the Monday of the current UTC week.
    Monday = 0 in Python's weekday() convention (Mon=0, Sun=6).
    """
    today = datetime.now(timezone.utc)
    # weekday(): Monday=0, Sunday=6
    days_since_monday = today.weekday()
    monday = today.replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    monday -= timedelta(days=days_since_monday)
    return monday.strftime("%Y-%m-%d")


def _normalize_timestamp(ts: str) -> str:
    """Normalize a timestamp string for datetime.fromisoformat.

    Handles Z suffix, double timezone (e.g. +00:00Z), and missing timezone.
    Produces a string that Python's fromisoformat can parse.
    """
    if not ts:
        return ts
    # Strip trailing Z first
    ts_clean = ts.rstrip("Z")
    # Check if it already has timezone info
    if "T" in ts_clean:
        t_part = ts_clean.split("T", 1)[1]
        if "+" not in t_part and "-" not in t_part:
            ts_clean += "+00:00"
    return ts_clean


def default_guard_state() -> dict:
    """Return a fresh guard state dict with default values."""
    return {
        "schema_version": EXPECTED_SCHEMA_VERSION,
        "trade_date": _today_utc_str(),
        "daily_trade_count": 0,
        "day_start_nl_eur": None,
        "week_start_date": _current_week_monday_utc_str(),
        "week_start_nl_eur": None,
        "daily_halt_active": False,
        "weekly_halt_active": False,
        "halt_reason": None,
        "last_updated_utc": _now_utc_iso(),
    }


def load_guard_state_readonly(path: Path | None = None) -> dict:
    """Load guard state in pure read-only mode — NEVER writes to disk.

    For diagnostics, monitoring, sentinel, and dry-run audit paths
    that must not mutate the guard-state file or trigger H1 protection.

    - If the file doesn't exist: returns in-memory defaults WITHOUT creating it.
    - If the file is corrupt/unparseable: returns in-memory defaults.
    - If schema_version mismatches: returns in-memory defaults.
    - NEVER calls save_guard_state_atomic.
    - NEVER triggers _assert_h1_authorized_for_path.
    - NEVER creates directories or tmp files.

    Args:
        path: Optional override path. Defaults to GUARD_STATE_PATH.

    Returns:
        The parsed guard state dict, or in-memory defaults if unavailable.
    """
    p = Path(path) if path else GUARD_STATE_PATH

    if not p.exists():
        return default_guard_state()

    try:
        with open(p, "r", encoding="utf-8") as f:
            state = json.load(f)
    except (json.JSONDecodeError, OSError):
        return default_guard_state()

    if not isinstance(state, dict):
        return default_guard_state()

    schema_v = state.get("schema_version")
    if schema_v != EXPECTED_SCHEMA_VERSION:
        return default_guard_state()

    # Fill missing fields with defaults (in-memory only)
    defaults = default_guard_state()
    for key in defaults:
        if key not in state:
            state[key] = defaults[key]

    state["last_updated_utc"] = _now_utc_iso()

    return state


def load_guard_state(path: Path | None = None) -> dict:
    """Load guard state from JSON file.

    If the file doesn't exist, returns default state and
    automatically initialises the file via save_guard_state_atomic().

    If the file exists but has an invalid schema_version or is corrupt,
    raises ValueError.

    **Important**: This function performs file I/O (creates/normalizes).
    For read-only diagnostics/monitoring/sentinel paths, use
    load_guard_state_readonly() which never writes to disk.

    Args:
        path: Optional override path. Defaults to GUARD_STATE_PATH.

    Returns:
        The parsed guard state dict.
    """
    p = Path(path) if path else GUARD_STATE_PATH

    if not p.exists():
        state = default_guard_state()
        save_guard_state_atomic(state, path=p)
        return state

    try:
        with open(p, "r", encoding="utf-8") as f:
            state = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        raise ValueError(
            f"Guard state file corrupt or unreadable: {p} — {e}"
        )

    if not isinstance(state, dict):
        raise ValueError(
            f"Guard state file must contain a JSON object, got {type(state).__name__}"
        )

    schema_v = state.get("schema_version")
    if schema_v != EXPECTED_SCHEMA_VERSION:
        raise ValueError(
            f"Guard state schema_version mismatch: expected {EXPECTED_SCHEMA_VERSION}, "
            f"got {schema_v!r}. File may be from a different deployment."
        )

    # Ensure all required fields exist (fill missing with defaults)
    defaults = default_guard_state()
    for key in defaults:
        if key not in state:
            state[key] = defaults[key]

    # Update timestamp
    state["last_updated_utc"] = _now_utc_iso()

    return state


def _rollover_guard_state(state: dict) -> bool:
    """Roll over guard state counters — daily and weekly — if stale.

    Uses canonical_trade_date() for the daily comparison (single source of
    truth across reconcile, sentinel, monitor, KPI) and
    _current_week_monday_utc_str() for the weekly comparison.

    Daily: resets daily_trade_count to 0, clears daily_halt_active, updates
    trade_date, and captures day_start_nl_eur. Then restores count from
    confirmed events already on the new date using the same canonical
    counting logic as monitor.reconcile_snapshot() and the
    guard-state-drift-sentinel.

    Weekly (Phase 19G — previously missing entirely; week_start_date/
    week_start_nl_eur were only ever set once, in default_guard_state(),
    and never rolled forward. That left the -3% weekly loss halt in
    gate_loss_halts() structurally inert — week_start_nl_eur stayed None
    indefinitely, and gate_loss_halts() only evaluates the weekly check
    `if week_start and week_start > 0`, so it silently never fired):
    clears weekly_halt_active, updates week_start_date to the current
    UTC week's Monday, and captures week_start_nl_eur — mirroring the
    daily behavior exactly. A weekly halt clears on week rollover the
    same way a daily halt clears on day rollover; there is no count to
    restore (weekly has no trade-count rule, only the loss-halt).

    Both use a single shared fetch_account() call when either rolls over,
    to avoid a redundant live call on the (common) day-only-rollover case.

    Args:
        state: Guard state dict (loaded by load_guard_state), mutated in place
        and persisted if either rollover occurs.

    Returns:
        True if a daily or weekly rollover occurred, False if neither was needed.
    """
    now_utc = datetime.now(timezone.utc)
    today_str = canonical_trade_date(now_utc)
    current_trade_date = state.get("trade_date", "")
    day_rollover_needed = bool(current_trade_date) and current_trade_date < today_str

    monday_str = _current_week_monday_utc_str()
    current_week_start = state.get("week_start_date", "")
    week_rollover_needed = bool(current_week_start) and current_week_start < monday_str

    if not day_rollover_needed and not week_rollover_needed:
        return False

    # Fetch account once, shared by whichever rollover(s) need it, rather
    # than one live call per rollover type.
    acct: dict | None = None
    try:
        acct = fetch_account()
    except Exception:
        acct = None
    nl = acct.get("net_liquidation_eur") if acct else None
    nl_valid = bool(nl and nl > 0)

    if day_rollover_needed:
        state["trade_date"] = today_str
        state["daily_trade_count"] = 0
        state["daily_halt_active"] = False

        # Restore count from confirmed events already on today's date
        # using the SAME canonical counting logic as reconcile_snapshot()
        # and guard-state-drift-sentinel (composite identity, test-artifact
        # exclusion, unconfirmed exclusion).
        try:
            restored_count = _stream_count_confirmed_orders_for_date(today_str)
            if restored_count > 0:
                state["daily_trade_count"] = restored_count
        except Exception:
            pass

        if nl_valid:
            state["day_start_nl_eur"] = nl

    if week_rollover_needed:
        state["week_start_date"] = monday_str
        state["weekly_halt_active"] = False

        if nl_valid:
            state["week_start_nl_eur"] = nl

    state["last_updated_utc"] = now_utc.isoformat()
    save_guard_state_atomic(state)

    append_guard_event("guard_calendar_rollover", {
        "daily_rollover_occurred": day_rollover_needed,
        "from_trade_date": current_trade_date if day_rollover_needed else None,
        "to_trade_date": today_str if day_rollover_needed else None,
        "daily_trade_count_reset": day_rollover_needed,
        "daily_halt_cleared": day_rollover_needed,
        "weekly_rollover_occurred": week_rollover_needed,
        "from_week_start_date": current_week_start if week_rollover_needed else None,
        "to_week_start_date": monday_str if week_rollover_needed else None,
        "weekly_halt_cleared": week_rollover_needed,
        "nl_captured": nl_valid,
        "canonical_trade_date": today_str,
    })

    return True


def save_guard_state_atomic(state: dict, path: Path | None = None) -> None:
    """Write guard state to JSON file using atomic tmp-write + fsync + replace.

    Phase H1: Requires H1 authorization for protected paths.

    Writes to a .tmp file in the same directory, calls os.fsync() on the
    file descriptor to ensure data is flushed to disk, then uses os.replace()
    for atomic rename.

    Args:
        state: The guard state dict to persist.
        path: Optional override path. Defaults to GUARD_STATE_PATH.
    """
    p = Path(path) if path else GUARD_STATE_PATH

    # Phase H1: Block unauthorized writes to protected files
    _assert_h1_authorized_for_path(p)

    # Ensure parent directory exists
    p.parent.mkdir(parents=True, exist_ok=True)

    # Write to .tmp file in the same directory (same filesystem for atomic rename)
    tmp_path = p.with_suffix(".json.tmp")

    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())

    # Atomic rename (atomic on Linux for same-filesystem renames)
    os.replace(tmp_path, p)


def initialize_guard_state_if_missing(path: Path | None = None) -> bool:
    """Create default guard state file if it doesn't exist.

    Args:
        path: Optional override path. Defaults to GUARD_STATE_PATH.

    Returns:
        True if the file was created, False if it already existed.
    """
    p = Path(path) if path else GUARD_STATE_PATH

    if p.exists():
        return False

    state = default_guard_state()
    save_guard_state_atomic(state, path=p)
    return True


# --- Data Retrieval (Step 3) ---

BRIDGE_BASE = os.environ.get("IBKR_BRIDGE_URL", "http://127.0.0.1:8790")
HTTP_TIMEOUT = 10  # seconds for each bridge request


def _require_allowed_symbol(symbol: str, rules: dict | None = None) -> str:
    """Validate symbol is in the current YAML allowlist (Phase H2 — single source of truth).

    Raises ValueError if symbol is not in the allowlist defined in
    paper-trading-rules.yaml.
    Returns the uppercased symbol.
    """
    allowed = _get_allowed_symbols(rules=rules)
    sym = symbol.upper().strip()
    if sym not in allowed:
        raise ValueError(
            f"Symbol '{sym}' is not in the current allowlist "
            f"{allowed}. See paper-trading-rules.yaml symbol_allowlist.allow."
        )
    return sym


def _bridge_get(path: str) -> dict:
    """Perform a GET request to the bridge.

    Args:
        path: URL path like "/health" or "/account".

    Returns:
        Parsed JSON response dict.

    Raises:
        RuntimeError: bridge unreachable, timeout, or non-JSON response.
        ValueError: response JSON contains "ok": false.
    """
    url = f"{BRIDGE_BASE}{path}"
    try:
        resp = urllib.request.urlopen(url, timeout=HTTP_TIMEOUT)
        data = json.loads(resp.read().decode())
    except urllib.error.URLError as e:
        raise RuntimeError(f"Bridge GET {path} failed: {e}")
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Bridge GET {path} returned non-JSON: {e}")

    if isinstance(data, dict) and data.get("ok") is False:
        raise ValueError(f"Bridge GET {path} returned ok=false: {data.get('error', 'unknown')}")

    return data


def _bridge_post(path: str, body: dict) -> dict:
    """Perform a POST request to the bridge.

    Args:
        path: URL path like "/market/quote".
        body: JSON-serialisable request body.

    Returns:
        Parsed JSON response dict.

    Raises:
        RuntimeError: bridge unreachable, timeout, or non-JSON response.
        ValueError: response JSON contains "ok": false.
    """
    url = f"{BRIDGE_BASE}{path}"
    data_bytes = json.dumps(body).encode()
    req = urllib.request.Request(
        url,
        data=data_bytes,
        headers={"Content-Type": "application/json"},
    )
    try:
        resp = urllib.request.urlopen(req, timeout=HTTP_TIMEOUT)
        data = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        # Map 403 to a clear message
        if e.code == 403:
            body_text = e.read().decode(errors="replace")
            raise RuntimeError(
                f"Bridge POST {path} returned HTTP 403 (forbidden endpoint). "
                f"Body: {body_text}"
            )
        raise RuntimeError(f"Bridge POST {path} returned HTTP {e.code}: {e}")
    except urllib.error.URLError as e:
        raise RuntimeError(f"Bridge POST {path} failed: {e}")
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Bridge POST {path} returned non-JSON: {e}")

    if isinstance(data, dict) and data.get("ok") is False:
        raise ValueError(f"Bridge POST {path} returned ok=false: {data.get('error', 'unknown')}")

    return data


def fetch_account() -> dict:
    """Fetch account data from the bridge /account endpoint.

    Returns a normalised dict with:
        net_liquidation_eur: float
        total_cash_value_eur: float
        available_funds_eur: float
        buying_power_eur: float
        currency: str (e.g. "EUR")
        exchange_rate: float (EUR/USD, from tag ExchangeRate)
        account_code: str (e.g. "DUQ542875")

    Raises:
        RuntimeError: bridge unreachable or unexpected response.
        ValueError: missing required account fields.
    """
    data = _bridge_get("/account")

    values = data.get("values", [])
    if not values:
        raise ValueError("/account returned empty values array")

    # Build a lookup: tag -> (value, currency)
    tag_map: dict[str, tuple[str, str]] = {}
    for entry in values:
        tag = entry.get("tag", "")
        val = entry.get("value", "")
        cur = entry.get("currency", "")
        tag_map[tag] = (val, cur)

    def _get_tag(tag: str) -> str | None:
        t = tag_map.get(tag)
        if t is not None:
            return t[0]
        return None

    def _float(tag: str) -> float:
        raw = _get_tag(tag)
        if raw is None or raw == "":
            raise ValueError(f"Required account tag '{tag}' is missing or empty")
        try:
            return float(raw)
        except (ValueError, TypeError):
            raise ValueError(f"Account tag '{tag}' is not a valid number: {raw!r}")

    # Extract required fields
    account_code = _get_tag("AccountCode") or ""
    currency = _get_tag("Currency") or ""

    # Use EUR currency entries where available (EUR is the account base)
    # NetLiquidation: prefer EUR, fall back to first entry
    nl_raw, nl_cur = tag_map.get("NetLiquidation", (None, None))
    if nl_raw is None:
        raise ValueError("NetLiquidation tag missing from account values")
    net_liquidation_eur = float(nl_raw) if nl_raw else 0.0

    tcv_raw = _get_tag("TotalCashValue")
    total_cash_value_eur = float(tcv_raw) if tcv_raw else 0.0

    af_raw = _get_tag("AvailableFunds")
    available_funds_eur = float(af_raw) if af_raw else 0.0

    bp_raw = _get_tag("BuyingPower")
    buying_power_eur = float(bp_raw) if bp_raw else 0.0

    fx_raw = _get_tag("ExchangeRate")
    exchange_rate = float(fx_raw) if fx_raw else None  # H4.2: no silent 1.0 fallback

    return {
        "net_liquidation_eur": net_liquidation_eur,
        "total_cash_value_eur": total_cash_value_eur,
        "available_funds_eur": available_funds_eur,
        "buying_power_eur": buying_power_eur,
        "currency": currency or "EUR",
        "exchange_rate": exchange_rate,
        "account_code": account_code,
        "source": "/account",
    }


def fetch_quote(symbol: str) -> dict:
    """Fetch a delayed quote for an allowed symbol.

    Rejects symbols not in the YAML allowlist before any HTTP call.

    Args:
        symbol: Stock/ETF symbol (must be in YAML allowlist).

    Returns:
        Normalised dict with:
            symbol: str
            ask: float | None
            bid: float | None
            last: float | None
            close: float | None
            currency: str
            exchange: str
            delayed: bool

    Raises:
        ValueError: symbol not in allowlist.
        RuntimeError: bridge unreachable or unexpected response.
    """
    sym = _require_allowed_symbol(symbol)

    data = _bridge_post("/market/quote", {
        "symbol": sym,
        "exchange": "SMART",
        "currency": "USD",
        "delayed": True,
    })

    def _safe(v):
        if v is None:
            return None
        try:
            return float(v)
        except (ValueError, TypeError):
            return None

    return {
        "symbol": data.get("symbol", sym),
        "ask": _safe(data.get("ask")),
        "bid": _safe(data.get("bid")),
        "last": _safe(data.get("last")),
        "close": _safe(data.get("close")),
        "currency": data.get("currency", "USD"),
        "exchange": data.get("exchange", "SMART"),
        "delayed": data.get("delayed", True),
    }


def fetch_bars(symbol: str, duration: str = "30 D", bar_size: str = "1 day") -> list:
    """Fetch daily OHLC bars for an allowed symbol.

    Rejects symbols not in the YAML allowlist before any HTTP call.

    Args:
        symbol: Stock/ETF symbol (must be in YAML allowlist).
        duration: IBKR duration string (default "30 D").
        bar_size: IBKR bar size string (default "1 day").

    Returns:
        List of bar dicts, each with:
            date: str (YYYY-MM-DD)
            open: float
            high: float
            low: float
            close: float
            volume: int | None

    Raises:
        ValueError: symbol not in allowlist.
        RuntimeError: bridge unreachable or unexpected response.
    """
    sym = _require_allowed_symbol(symbol)

    data = _bridge_post("/market/bars", {
        "symbol": sym,
        "duration": duration,
        "bar_size": bar_size,
        "what_to_show": "TRADES",
        "use_rth": True,
    })

    bars = data.get("bars", [])
    if not bars:
        raise ValueError(f"No bars returned for {sym}")

    result = []
    for b in bars:
        result.append({
            "date": str(b.get("date", "")),
            "open": _safe_float(b.get("open")),
            "high": _safe_float(b.get("high")),
            "low": _safe_float(b.get("low")),
            "close": _safe_float(b.get("close")),
            "volume": int(b["volume"]) if b.get("volume") is not None else None,
        })

    return result


def _safe_float(x):
    """Safely convert a value to float, returning None on failure."""
    if x is None:
        return None
    try:
        return float(x)
    except (ValueError, TypeError):
        return None


# --- Stop Calculation (Step 4) ---

ATR_PERIOD = 14
ATR_MULTIPLIER = 2.0
SWING_LOOKBACK = 20
FLOOR_PERCENT = 0.95


def calc_true_range(high: float, low: float, prev_close: float) -> float:
    """Compute the True Range for one bar.

    TR = max(high - low, abs(high - prev_close), abs(low - prev_close))

    Args:
        high: Current bar high.
        low: Current bar low.
        prev_close: Previous bar close.

    Returns:
        True Range as a float.
    """
    return max(
        high - low,
        abs(high - prev_close),
        abs(low - prev_close),
    )


def calc_atr14(bars: list) -> float:
    """Compute ATR(14) from a list of normalized daily OHLC bars.

    Uses the Wilder's smoothed ATR method (simple moving average of
    True Ranges over the first 14 periods, then smoothed thereafter).

    Args:
        bars: List of OHLC dicts with 'high', 'low', 'close' keys.
              Must have at least 15 bars (14 TR values need 15 closes).

    Returns:
        ATR(14) value as float.

    Raises:
        ValueError: fewer than 15 bars provided.
    """
    if len(bars) < 15:
        raise ValueError(
            f"Need at least 15 bars to compute ATR(14), got {len(bars)}"
        )

    # Compute True Ranges
    tr_values = []
    for i in range(1, len(bars)):
        tr = calc_true_range(
            bars[i]["high"],
            bars[i]["low"],
            bars[i - 1]["close"],
        )
        tr_values.append(tr)

    # First ATR = SMA of first 14 TR values
    atr = sum(tr_values[:ATR_PERIOD]) / ATR_PERIOD

    # Wilder's smoothing for remaining values (not critical for daily use
    # since we always fetch 30 bars and recompute fresh, but included for
    # correctness)
    for i in range(ATR_PERIOD, len(tr_values)):
        atr = (atr * (ATR_PERIOD - 1) + tr_values[i]) / ATR_PERIOD

    return round(atr, 2)


def calc_20d_low(bars: list) -> float:
    """Find the lowest low in the most recent 20 trading days.

    Args:
        bars: List of OHLC dicts with 'low' key. Most recent bar last.

    Returns:
        Lowest low value.

    Raises:
        ValueError: fewer than 1 bar provided.
    """
    if not bars:
        raise ValueError("Need at least 1 bar to compute 20d low")

    # Take the last 20 bars (or all if fewer)
    recent = bars[-min(len(bars), SWING_LOOKBACK):]
    lows = [b["low"] for b in recent if b["low"] is not None]

    if not lows:
        raise ValueError("No valid low values in bars")

    return min(lows)


def calc_recent_swing_low(bars: list, lookback: int = 20) -> float:
    """Find the most recent swing low within the lookback window.

    A swing low is a bar where the low is lower than the bars immediately
    before and after it. Uses a 5-bar window (2 left, 1 center, 2 right).

    Args:
        bars: List of OHLC dicts with 'low' key. Most recent bar last.
        lookback: Number of recent bars to search (default 20).

    Returns:
        The lowest identified swing low, or falls back to 20d low.
    """
    recent = bars[-min(len(bars), lookback):]

    if len(recent) < 5:
        # Not enough bars for swing detection; fall back to min low
        lows = [b["low"] for b in recent if b["low"] is not None]
        return min(lows) if lows else 0.0

    swing_lows = []
    for i in range(1, len(recent) - 1):
        center_low = recent[i]["low"]
        if center_low is None:
            continue
        prev_low = recent[i - 1]["low"]
        next_low = recent[i + 1]["low"]
        if prev_low is not None and next_low is not None:
            if center_low < prev_low and center_low < next_low:
                swing_lows.append(center_low)

    if not swing_lows:
        # Fallback: return the lowest low in the window
        lows = [b["low"] for b in recent if b["low"] is not None]
        return min(lows) if lows else 0.0

    return min(swing_lows)


def calc_stop(entry_price: float, bars: list) -> dict:
    """Compute the final initial stop price using the Phase 1 formula.

    stop_price = max(
        entry_price - 2 * ATR(14),    # ATR-based distance
        recent_swing_low,              # nearest visible swing low
        20_day_low,                    # lowest close in 20 days
        entry_price * 0.95             # -5% hard cap
    )

    Args:
        entry_price: Proposed entry price (e.g. ask for a buy).
        bars: List of normalized OHLC bar dicts (most recent last).

    Returns:
        Dict with:
            entry_price: float
            atr14: float
            atr_stop: float
            swing_low: float
            twenty_day_low: float
            five_percent_floor: float
            stop_price: float
            stop_distance: float
            atr_distance_pct: float
            binding_candidate: str

    Raises:
        ValueError: entry_price <= 0, insufficient bars, stop_distance <= 0.
    """
    if entry_price is None or entry_price <= 0:
        raise ValueError(f"entry_price must be > 0, got {entry_price!r}")

    if not bars or len(bars) < 2:
        raise ValueError(
            f"Need at least 2 bars for stop calculation, got {len(bars)}"
        )

    # Compute components
    atr14 = calc_atr14(bars)
    twenty_day_low = calc_20d_low(bars)
    swing_low = calc_recent_swing_low(bars)
    five_percent_floor = round(entry_price * FLOOR_PERCENT, 2)
    atr_stop = round(entry_price - (ATR_MULTIPLIER * atr14), 2)

    # Final stop = max of all four candidates (tightest = closest to entry)
    candidates = {
        "atr_stop": atr_stop,
        "swing_low": swing_low,
        "twenty_day_low": twenty_day_low,
        "five_percent_floor": five_percent_floor,
    }
    stop_price = max(candidates.values())

    # Find which candidate was binding
    binding = [name for name, val in candidates.items() if val == stop_price]
    binding_candidate = binding[0] if binding else "unknown"

    stop_distance = round(entry_price - stop_price, 2)
    atr_distance_pct = round((entry_price - atr_stop) / entry_price * 100, 2)

    if stop_distance <= 0:
        raise ValueError(
            f"Stop distance must be > 0: entry={entry_price}, stop={stop_price}, "
            f"distance={stop_distance}. Check ATR and swing low values."
        )

    return {
        "entry_price": entry_price,
        "atr14": round(atr14, 2),
        "atr_stop": atr_stop,
        "swing_low": round(swing_low, 2),
        "twenty_day_low": round(twenty_day_low, 2),
        "five_percent_floor": five_percent_floor,
        "stop_price": stop_price,
        "stop_distance": stop_distance,
        "atr_distance_pct": atr_distance_pct,
        "binding_candidate": binding_candidate,
    }


# --- P5 Bracket-Stop Validation (Step 5P) ---


def validate_bracket_stop(
    stop_price: float | None,
    entry_price: float,
    quantity: int,
    action: str,
    stop_quantity: int | None = None,
) -> dict:
    """Validate bracket/protective stop for a proposed order.

    For BUY entries: requires a valid stop_price below entry_price,
    stop quantity matching entry quantity (unless explicitly rejected),
    and returns bracket construction evidence.

    For SELL close-only: no bracket required, returns valid=True with
    bracket=False. Never opens/increases a short.

    Args:
        stop_price: Stop price (None or 0 for SELL / auto-calc).
        entry_price: Entry/reference price.
        quantity: Entry order quantity.
        action: 'BUY' or 'SELL'.
        stop_quantity: Optional explicit stop quantity (defaults to quantity).

    Returns:
        Dict with keys:
        - valid: bool
        - bracket: bool (True for BUY, False for SELL)
        - protective_stop: bool
        - stop_price, stop_action, quantity, stop_distance
        - parent_transmit: bool (False for parent BUY)
        - stop_transmit: bool (True for child stop)
        - error: str (when not valid)
    """
    # SELL close-only: no bracket required
    if action.upper() == "SELL":
        return {
            "valid": True,
            "bracket": False,
            "protective_stop": False,
            "stop_price": None,
            "stop_action": None,
            "quantity": quantity,
            "stop_quantity": None,
            "stop_distance": None,
            "parent_transmit": False,
            "stop_transmit": False,
            "error": None,
        }

    # BUY entry: must have valid stop
    if stop_price is None or (isinstance(stop_price, (int, float)) and stop_price <= 0):
        return {
            "valid": False,
            "bracket": True,
            "protective_stop": True,
            "stop_price": stop_price,
            "stop_action": "SELL",
            "quantity": quantity,
            "stop_quantity": stop_quantity,
            "stop_distance": None,
            "parent_transmit": False,
            "stop_transmit": True,
            "error": "BUY entry requires a protective stop. stop_price is missing or invalid.",
        }

    # Stop must be strictly below entry price
    try:
        stop_price = float(stop_price)
        entry_price = float(entry_price)
    except (TypeError, ValueError):
        return {
            "valid": False,
            "bracket": True,
            "protective_stop": True,
            "stop_price": stop_price,
            "stop_action": "SELL",
            "quantity": quantity,
            "stop_quantity": stop_quantity,
            "stop_distance": None,
            "parent_transmit": False,
            "stop_transmit": True,
            "error": "stop_price and entry_price must be numeric.",
        }

    if stop_price >= entry_price:
        return {
            "valid": False,
            "bracket": True,
            "protective_stop": True,
            "stop_price": stop_price,
            "stop_action": "SELL",
            "quantity": quantity,
            "stop_quantity": stop_quantity,
            "stop_distance": round(entry_price - stop_price, 2),
            "parent_transmit": False,
            "stop_transmit": True,
            "error": f"stop_price ({stop_price}) must be below entry price ({entry_price}).",
        }

    # Validate stop quantity
    effective_stop_qty = stop_quantity if stop_quantity is not None else quantity
    if effective_stop_qty != quantity:
        return {
            "valid": False,
            "bracket": True,
            "protective_stop": True,
            "stop_price": stop_price,
            "stop_action": "SELL",
            "quantity": quantity,
            "stop_quantity": effective_stop_qty,
            "stop_distance": round(entry_price - stop_price, 2),
            "parent_transmit": False,
            "stop_transmit": True,
            "error": f"Stop quantity ({effective_stop_qty}) must match entry quantity ({quantity}).",
        }

    # Valid bracket construction
    stop_distance = round(entry_price - stop_price, 2)
    return {
        "valid": True,
        "bracket": True,
        "protective_stop": True,
        "stop_price": stop_price,
        "stop_action": "SELL",
        "quantity": quantity,
        "stop_quantity": effective_stop_qty,
        "stop_distance": stop_distance,
        "parent_transmit": False,
        "stop_transmit": True,
        "error": None,
    }


# --- Validation Gates (Step 5) ---


def _calc_shares_by_notional(
    max_notional_pct: float, net_liquidation_eur: float,
    exchange_rate: float, entry_price: float,
) -> int:
    """Compute max shares allowed by the notional cap.
    Formula: floor(max_notional_pct * net_liquidation_eur * exchange_rate / entry_price)
    """
    max_notional_usd = max_notional_pct * net_liquidation_eur * exchange_rate
    if entry_price <= 0:
        return 0
    return int(max_notional_usd // entry_price)


def _calc_shares_by_risk(
    max_risk_pct: float, net_liquidation_eur: float,
    exchange_rate: float, stop_distance: float,
) -> int:
    """Compute max shares allowed by the risk cap.
    Formula: floor(max_risk_pct * net_liquidation_eur * exchange_rate / stop_distance)
    """
    if stop_distance <= 0:
        return 0
    max_risk_usd = max_risk_pct * net_liquidation_eur * exchange_rate
    return int(max_risk_usd // stop_distance)


def compute_final_max_shares(
    rules: dict, net_liquidation_eur: float,
    exchange_rate: float, entry_price: float,
    stop_distance: float,
) -> dict:
    """Compute final max shares and identify binding cap."""
    max_notional_pct = rules["max_position_notional"]["value"] / 100.0
    max_risk_pct = rules["max_risk_per_trade"]["value"] / 100.0
    shares_by_notional = _calc_shares_by_notional(
        max_notional_pct, net_liquidation_eur, exchange_rate, entry_price,
    )
    shares_by_risk = _calc_shares_by_risk(
        max_risk_pct, net_liquidation_eur, exchange_rate, stop_distance,
    )
    final_max_shares = min(shares_by_notional, shares_by_risk)
    binding = "notional" if shares_by_notional <= shares_by_risk else "risk"
    max_notional_usd = max_notional_pct * net_liquidation_eur * exchange_rate
    max_risk_usd = max_risk_pct * net_liquidation_eur * exchange_rate
    return {
        "shares_by_notional": shares_by_notional,
        "shares_by_risk": shares_by_risk,
        "final_max_shares": final_max_shares,
        "binding_cap": binding,
        "max_notional_usd": round(max_notional_usd, 2),
        "max_risk_usd": round(max_risk_usd, 2),
    }


def _calculate_existing_exposure(positions: list, exchange_rate: float) -> float:
    """Total current portfolio exposure in USD from positions list."""
    total_usd = 0.0
    for pos in positions:
        shares = pos.get("position", 0)
        if shares <= 0:
            continue
        price = pos.get("marketPrice") or pos.get("market_price") or 0
        total_usd += shares * price
    return total_usd


# --- Individual Gate Functions ---


def gate_allowlist(symbol: str, rules: dict) -> tuple:
    """Gate A — Explicit symbol allowlist."""
    allowed = rules.get("symbol_allowlist", {}).get("allow", [])
    sym = symbol.upper().strip()
    if sym not in allowed:
        return (False, f"Symbol '{sym}' not in explicit allowlist {allowed}", {"symbol": sym, "allowed": allowed})
    return (True, "Symbol allowed", {"symbol": sym})


def gate_notional(
    symbol: str, proposed_shares: int, entry_price: float,
    rules: dict, net_liquidation_eur: float, exchange_rate: float,
    current_exposure_usd: float = 0.0,
) -> tuple:
    """Gate B — Max notional per symbol (5% of NL)."""
    max_notional_pct = rules["max_position_notional"]["value"] / 100.0
    max_notional_usd = max_notional_pct * net_liquidation_eur * exchange_rate
    proposed_notional_usd = proposed_shares * entry_price
    if proposed_notional_usd <= 0:
        return (False, f"Proposed notional must be > 0, got {proposed_notional_usd:.2f}", {"proposed_notional_usd": proposed_notional_usd, "max_notional_usd": max_notional_usd})
    if proposed_notional_usd > max_notional_usd:
        return (False, f"Proposed notional ${proposed_notional_usd:,.2f} exceeds cap of ${max_notional_usd:,.2f}", {"proposed_notional_usd": round(proposed_notional_usd,2), "max_notional_usd": round(max_notional_usd,2), "max_notional_pct": max_notional_pct*100, "exceeded_by": round(proposed_notional_usd - max_notional_usd,2)})
    combined_usd = current_exposure_usd + proposed_notional_usd
    if combined_usd > max_notional_usd:
        return (False, f"Existing ${current_exposure_usd:,.2f} + proposed ${proposed_notional_usd:,.2f} = ${combined_usd:,.2f} exceeds cap of ${max_notional_usd:,.2f}", {"proposed_notional_usd": round(proposed_notional_usd,2), "current_symbol_exposure_usd": round(current_exposure_usd,2), "combined_usd": round(combined_usd,2), "max_notional_usd": round(max_notional_usd,2)})
    return (True, f"Notional ${proposed_notional_usd:,.2f} within ${max_notional_usd:,.2f} cap", {"proposed_notional_usd": round(proposed_notional_usd,2), "max_notional_usd": round(max_notional_usd,2), "current_symbol_exposure_usd": round(current_exposure_usd,2)})


def gate_risk(
    proposed_shares: int, stop_distance: float,
    rules: dict, net_liquidation_eur: float, exchange_rate: float,
) -> tuple:
    """Gate C — Max risk per trade (2% of NL)."""
    max_risk_pct = rules["max_risk_per_trade"]["value"] / 100.0
    max_risk_usd = max_risk_pct * net_liquidation_eur * exchange_rate
    planned_risk_usd = proposed_shares * stop_distance
    if planned_risk_usd <= 0:
        return (False, f"Planned risk must be > 0, got {planned_risk_usd:.2f}", {"planned_risk_usd": planned_risk_usd, "max_risk_usd": max_risk_usd})
    if planned_risk_usd > max_risk_usd:
        return (False, f"Planned risk ${planned_risk_usd:,.2f} exceeds cap of ${max_risk_usd:,.2f}", {"planned_risk_usd": round(planned_risk_usd,2), "max_risk_usd": round(max_risk_usd,2), "exceeded_by": round(planned_risk_usd - max_risk_usd,2)})
    return (True, f"Risk ${planned_risk_usd:,.2f} within ${max_risk_usd:,.2f} cap", {"planned_risk_usd": round(planned_risk_usd,2), "max_risk_usd": round(max_risk_usd,2), "max_risk_pct": max_risk_pct*100})


def gate_trades_per_day(guard_state: dict, rules: dict) -> tuple:
    """Gate D — Max trades per day."""
    max_trades = rules["max_trades_per_day"]["value"]
    current = guard_state.get("daily_trade_count", 0)
    if current >= max_trades:
        return (False, f"Daily trade limit reached: {current}/{max_trades}", {"daily_trade_count": current, "max_trades_per_day": max_trades})
    return (True, f"Trades today: {current}/{max_trades}", {"daily_trade_count": current, "max_trades_per_day": max_trades})


def gate_loss_halts(
    guard_state: dict,
    current_nl_eur: float,
    rules: dict,
    *,
    action: str = "BUY",
    symbol: str | None = None,
    proposed_shares: int = 0,
    position_provider=None,
) -> tuple:
    """Gate E — Daily and weekly loss halts.

    P2b: Close-only SELL exits that reduce or flatten an existing long
    position are exempt from loss halts.  The exemption is narrow:
    - BUY / new exposure during a loss halt → blocked (no change).
    - SELL that would open or increase short exposure → blocked.
    - SELL quantity ≤ confirmed existing long position → may pass.
    - If position cannot be confirmed → fail closed.
    """
    # Determine whether a loss halt is active or would be triggered
    halt_active = guard_state.get("daily_halt_active", False) or guard_state.get("weekly_halt_active", False)
    day_start = guard_state.get("day_start_nl_eur")
    week_start = guard_state.get("week_start_nl_eur")
    details = {"daily_halt_triggered": False, "weekly_halt_triggered": False}
    reason_parts = []

    if day_start and day_start > 0:
        daily_loss_pct = (day_start - current_nl_eur) / day_start * 100
        daily_threshold = rules["loss_halts"]["daily"]["value"]
        if daily_loss_pct >= daily_threshold:
            details["daily_halt_triggered"] = True
            reason_parts.append(f"Portfolio down {daily_loss_pct:.2f}% from day-start (threshold {daily_threshold}%)")
            halt_active = True

    if week_start and week_start > 0:
        weekly_loss_pct = (week_start - current_nl_eur) / week_start * 100
        weekly_threshold = rules["loss_halts"]["weekly"]["value"]
        if weekly_loss_pct >= weekly_threshold:
            details["weekly_halt_triggered"] = True
            reason_parts.append(f"Portfolio down {weekly_loss_pct:.2f}% from week-start (threshold {weekly_threshold}%)")
            halt_active = True

    if not halt_active:
        return (True, "No loss halt triggered", details)

    # ── P2b: close-only SELL exemption ────────────────────────────────
    if action == "SELL":
        if not symbol or proposed_shares <= 0:
            # Cannot validate without symbol / positive quantity
            return (
                False,
                f"Loss halt active, SELL cannot be validated: "
                + ("; ".join(reason_parts) if reason_parts else "halt active"),
                {**details, "halt_active": halt_active, "p2b_note": "sell_no_symbol_or_qty"},
            )

        # Confirm existing position
        pos = _get_existing_position(symbol, position_provider)
        existing_qty = pos.get("qty", 0)
        pos_source = pos.get("source", "none")

        if pos_source == "none" or existing_qty <= 0:
            # Cannot confirm a long position → fail closed
            return (
                False,
                f"Loss halt active, existing position unconfirmed for {symbol}: "
                + ("; ".join(reason_parts) if reason_parts else "halt active"),
                {**details, "halt_active": halt_active,
                 "p2b_note": "position_unconfirmed",
                 "existing_position": existing_qty,
                 "position_source": pos_source},
            )

        if proposed_shares > existing_qty:
            # SELL exceeds existing long → could open short → blocked
            return (
                False,
                f"Loss halt active, SELL {proposed_shares} > existing {existing_qty} {symbol}: "
                + ("; ".join(reason_parts) if reason_parts else "halt active"),
                {**details, "halt_active": halt_active,
                 "p2b_note": "oversize_sell_blocked",
                 "existing_position": existing_qty,
                 "position_source": pos_source},
            )

        # Close-only SELL exemption: confirmed position, quantity ≤ existing
        return (
            True,
            f"Loss halt overridden for close-only SELL {proposed_shares} {symbol} "
            f"(existing: {existing_qty}, {pos_source}): "
            + ("; ".join(reason_parts) if reason_parts else "halt active"),
            {**details, "halt_active": halt_active,
             "p2b_exempt": True,
             "p2b_note": "close_only_sell_exempt",
             "existing_position": existing_qty,
             "position_source": pos_source},
        )

    # BUY (or unknown action): loss halt blocks entries
    if guard_state.get("daily_halt_active", False):
        return (False, "Daily loss halt active. Entries frozen for remainder of day.",
                {"halt_type": "daily", "halt_active": True})
    if guard_state.get("weekly_halt_active", False):
        return (False, "Weekly loss halt active. Entries frozen until manual review.",
                {"halt_type": "weekly", "halt_active": True})
    # Threshold-based halt (BUY side)
    return (False, "; ".join(reason_parts), {**details, "halt_active": True})


def gate_exposure(
    proposed_shares: int, entry_price: float,
    rules: dict, net_liquidation_eur: float,
    exchange_rate: float, positions: list,
) -> tuple:
    """Gate F — Max total portfolio exposure (30% of NL)."""
    max_exposure_pct = rules["max_total_exposure"]["value"] / 100.0
    max_exposure_usd = max_exposure_pct * net_liquidation_eur * exchange_rate
    current_exposure_usd = _calculate_existing_exposure(positions, exchange_rate)
    proposed_notional_usd = proposed_shares * entry_price
    total_exposure_usd = current_exposure_usd + proposed_notional_usd
    if total_exposure_usd > max_exposure_usd:
        return (False, f"Current ${current_exposure_usd:,.2f} + proposed ${proposed_notional_usd:,.2f} = ${total_exposure_usd:,.2f} exceeds cap of ${max_exposure_usd:,.2f}", {"current_exposure_usd": round(current_exposure_usd,2), "proposed_notional_usd": round(proposed_notional_usd,2), "total_exposure_usd": round(total_exposure_usd,2), "max_exposure_usd": round(max_exposure_usd,2), "max_exposure_pct": max_exposure_pct*100})
    return (True, f"Total exposure ${total_exposure_usd:,.2f} within ${max_exposure_usd:,.2f} cap", {"current_exposure_usd": round(current_exposure_usd,2), "proposed_notional_usd": round(proposed_notional_usd,2), "total_exposure_usd": round(total_exposure_usd,2), "max_exposure_usd": round(max_exposure_usd,2)})


def gate_sector_concentration(symbol: str, positions: list, rules: dict) -> tuple:
    """Gate I — reject BUY if the candidate's sector is already at capacity.

    Thin adapter over strategy_v1_1_core.gate_sector_concentration (B1) — all
    counting and failure-precedence logic lives there (H2 invariant: no
    hardcoded duplicates). This function only maps guard.py's rules dict onto
    that function's explicit sector_map/max_per_sector arguments, and filters
    positions to currently-held (qty > 0) entries, matching
    _get_existing_position's own convention for what counts as "held."

    Fails CLOSED on a symbol with no sector mapping (enforced inside the B1
    function; load_rules() also refuses to start if any allowlisted symbol
    lacks one, so this should be unreachable for a BUY that already passed
    Gate A). SELL is exempt by construction — this is only ever called from
    run_preflight's BUY branch.
    """
    sector_map = rules.get("symbol_sectors", {})
    max_per_sector = rules.get("max_positions_per_sector", {}).get("value", 1)
    held = [
        p for p in (positions or [])
        if isinstance(p, dict) and int(p.get("position", 0) or 0) > 0
    ]
    return _core_gate_sector_concentration(
        symbol=symbol,
        positions=held,
        sector_map=sector_map,
        max_per_sector=max_per_sector,
        side="BUY",
    )


# --- Phase 2G: Close-Only Position Gate (Gate G) ---

# Known test order IDs that should be excluded from position calculation
_KNOWN_TEST_ORDER_IDS_POSITION = frozenset({"12345", "99999"})

# Known test approval IDs to exclude
_KNOWN_TEST_APPROVALS_POSITION = frozenset({
    "aprv_noexec",
    "aprv_7",
})


def _get_existing_position(
    symbol: str,
    position_provider=None,
) -> dict:
    """Get the existing long position quantity for a symbol.

    Priority:
    1. IBKR live positions via position_provider (preferred)
    2. Guard event history (file-based fallback, degraded)

    Returns dict with:
        qty: int — existing long position (> 0 if held)
        source: str — "ibkr_live" | "event_history" | "none"
        note: str — human-readable context
    """
    # Priority 1: IBKR live positions
    if position_provider is not None:
        try:
            positions = position_provider()
            if isinstance(positions, list):
                for p in positions:
                    if p.get("symbol", "").upper() == symbol.upper():
                        qty = int(p.get("position", 0))
                        if qty > 0:
                            return {
                                "qty": qty,
                                "source": "ibkr_live",
                                "note": f"IBKR position: {qty} shares",
                            }
                        return {
                            "qty": 0,
                            "source": "ibkr_live",
                            "note": f"IBKR position is {qty} (not long)",
                        }
                return {
                    "qty": 0,
                    "source": "ibkr_live",
                    "note": "Symbol not found in IBKR positions",
                }
        except Exception:
            pass  # fall through to file-based

    # Priority 2: Guard event history (degraded)
    try:
        events = read_guard_events()
        submitted = [e for e in events
                     if e.get("event_type") == "order_submitted"
                     and e.get("symbol", "").upper() == symbol.upper()]

        net_qty = 0
        for e in submitted:
            # Skip known test artifacts
            oid = str(e.get("order_id", "")) if e.get("order_id") is not None else ""
            aid = e.get("approval_id", "")
            if oid in _KNOWN_TEST_ORDER_IDS_POSITION or aid in _KNOWN_TEST_APPROVALS_POSITION:
                continue
            action = e.get("action", "")
            qty = e.get("totalQuantity", 0) or 0
            if action == "BUY":
                net_qty += qty
            elif action == "SELL":
                net_qty -= qty

        if net_qty > 0:
            return {
                "qty": net_qty,
                "source": "event_history",
                "note": f"Net position from events: {net_qty} shares (degraded)",
            }
        return {
            "qty": 0,
            "source": "event_history",
            "note": f"Net position from events: {net_qty} (degraded, no position)",
        }
    except Exception:
        pass

    # No source available
    return {
        "qty": 0,
        "source": "none",
        "note": "No position data available (IBKR disconnected, no event history)",
    }


def gate_close_only(
    symbol: str,
    proposed_qty: int,
    position_provider=None,
) -> tuple:
    """Gate G — Close-only SELL validation.

    For SELL actions only. Verifies:
    - Existing long position exists
    - Proposed qty <= existing position
    - Resulting net position >= 0 (no short)

    Returns:
        (pass, reason, details_dict)
    """
    pos_info = _get_existing_position(symbol, position_provider)
    existing_qty = pos_info["qty"]
    position_source = pos_info["source"]

    if existing_qty <= 0:
        return (
            False,
            f"No existing long position in {symbol.upper()} to close (qty={existing_qty})",
            {
                "existing_qty": existing_qty,
                "proposed_qty": proposed_qty,
                "position_source": position_source,
                "position_note": pos_info["note"],
                "would_open_short": False,
            }
        )

    if proposed_qty <= 0:
        return (
            False,
            f"Close quantity must be > 0, got {proposed_qty}",
            {
                "existing_qty": existing_qty,
                "proposed_qty": proposed_qty,
                "position_source": position_source,
                "position_note": pos_info["note"],
                "would_open_short": False,
            }
        )

    if proposed_qty > existing_qty:
        return (
            False,
            f"Close qty {proposed_qty} exceeds existing position {existing_qty}",
            {
                "existing_qty": existing_qty,
                "proposed_qty": proposed_qty,
                "position_source": position_source,
                "position_note": pos_info["note"],
                "would_open_short": True if proposed_qty > existing_qty else False,
            }
        )

    net_after = existing_qty - proposed_qty
    return (
        True,
        f"Close {proposed_qty} of {existing_qty} {symbol.upper()} — net after: {net_after}",
        {
            "existing_qty": existing_qty,
            "proposed_qty": proposed_qty,
            "net_after": net_after,
            "position_source": position_source,
            "position_note": pos_info["note"],
            "would_open_short": False,
        }
    )


# --- Phase 3 (P3): Gate H — Proposal Discipline ---

PROPOSALS_PATH = Path(os.environ.get(
    "IBKR_PROPOSALS_PATH",
    str(Path.home() / ".openclaw" / "proposals")
))

# ── Common mandatory fields (both BUY and SELL) ────────────────────────

# String fields required for every proposal regardless of side
_MANDATORY_PROPOSAL_STRING_FIELDS_COMMON = frozenset({
    "symbol",
    "side",
    "reason_to_trade",
    "reason_not_to_trade",
    "daily_drawdown_status",
    "weekly_drawdown_status",
    "preflight_command",
})

# Numeric fields required for every proposal
_MANDATORY_PROPOSAL_NUMERIC_FIELDS_COMMON = frozenset({
    "quantity",
})

# Boolean fields required for every proposal
_MANDATORY_PROPOSAL_BOOL_FIELDS = frozenset({
    "awaiting_chris_approval",
    "advisory_only",
})

# ── BUY / new-entry mandatory fields ────────────────────────────────────

_MANDATORY_BUY_STRING_FIELDS = frozenset({
    "entry_reference",
    "stop_loss_invalidation",
})

_MANDATORY_BUY_NUMERIC_FIELDS = frozenset({
    "max_loss_eur",
    "max_loss_pct",
    "position_notional_eur",
    "position_notional_pct",
    "portfolio_exposure_after_pct",
})

# Minimum position_sizing sub-fields required for a valid BUY proposal
_MANDATORY_POSITION_SIZING_FIELDS = frozenset({
    "method",
    "stop_price",
    "final_shares",
})

# ── SELL / close-only EXIT mandatory fields ─────────────────────────────

_MANDATORY_SELL_STRING_FIELDS = frozenset({
    "entry_reference",  # serves as exit reference / exit rationale
})

_MANDATORY_SELL_NUMERIC_FIELDS: frozenset = frozenset()  # no extra numerics for EXIT

# ── Legacy alias (used by tests) ────────────────────────────────────────
_MANDATORY_PROPOSAL_STRING_FIELDS = (
    _MANDATORY_PROPOSAL_STRING_FIELDS_COMMON
    | _MANDATORY_BUY_STRING_FIELDS
    | _MANDATORY_SELL_STRING_FIELDS
)
_MANDATORY_PROPOSAL_NUMERIC_FIELDS = (
    _MANDATORY_PROPOSAL_NUMERIC_FIELDS_COMMON
    | _MANDATORY_BUY_NUMERIC_FIELDS
    | _MANDATORY_SELL_NUMERIC_FIELDS
)


def save_proposal_file(proposal: dict, proposal_id: str | None = None) -> Path:
    """Persist a proposal dict to ~/.openclaw/proposals/ as a JSON file.

    Creates the directory if it does not exist. The file is named
    ``{proposal_id}.json`` or, when proposal_id is None,
    ``{timestamp}_{symbol}.json``.

    Args:
        proposal: Proposal dict (must contain at least ``symbol``).
        proposal_id: Optional stable identifier; auto-generated when None.

    Returns:
        Path to the written file.

    Raises:
        ValueError: proposal is not a dict or missing ``symbol``.
        OSError: directory creation or file write fails.
    """
    if not isinstance(proposal, dict):
        raise ValueError(f"proposal must be a dict, got {type(proposal).__name__}")
    symbol = (proposal.get("symbol") or "unknown").upper()
    if proposal_id is None:
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        proposal_id = f"{ts}_{symbol}"

    PROPOSALS_PATH.mkdir(parents=True, exist_ok=True)
    filepath = PROPOSALS_PATH / f"{proposal_id}.json"

    payload = {
        "proposal_id": proposal_id,
        "saved_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        **proposal,
    }

    tmp = filepath.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, filepath)

    return filepath


def gate_proposal_discipline(
    proposal_path: str | Path | None = None,
    *, proposal_data: dict | None = None,
) -> tuple:
    """Gate H — Proposal discipline validation.

    Validates that a trade proposal file exists, is well-formed JSON,
    and contains all mandatory fields. Fails closed on missing,
    incomplete, or malformed proposals — no silent defaults, no
    phantom proposals.

    Args:
        proposal_path: Path to a proposal JSON file.
            If None, the gate fails closed (proposal required).

    Returns:
        (pass: bool, reason: str, details: dict)
    """
    if proposal_path is None:
        return (
            False,
            "No proposal file provided. Every trade requires a persisted "
            "proposal under ~/.openclaw/proposals/.",
            {"proposal_path": None, "error": "missing_proposal"},
        )

    path = Path(proposal_path)

    # Existence
    if not path.exists():
        return (
            False,
            f"Proposal file not found: {path}",
            {"proposal_path": str(path), "error": "file_not_found"},
        )

    # Parse
    try:
        if proposal_data is not None:
            proposal = proposal_data
        else:
            with open(path, "r", encoding="utf-8") as f:
                proposal = json.load(f)
    except json.JSONDecodeError as e:
        return (
            False,
            f"Malformed proposal JSON in {path.name}: {e}",
            {"proposal_path": str(path), "error": "malformed_json", "parse_error": str(e)},
        )
    except OSError as e:
        return (
            False,
            f"Cannot read proposal file {path}: {e}",
            {"proposal_path": str(path), "error": "read_error", "os_error": str(e)},
        )

    # Type
    if not isinstance(proposal, dict):
        return (
            False,
            f"Proposal must be a JSON object, got {type(proposal).__name__}",
            {"proposal_path": str(path), "error": "not_a_dict"},
        )

    # Determine side: BUY or SELL dictates which fields are mandatory.
    # Default to BUY for field-check purposes when side is missing —
    # the missing "side" will be caught by the common string-field check below.
    side_raw = proposal.get("side", "")
    side = side_raw.upper().strip() if isinstance(side_raw, str) else ""
    # Use BUY as the template for checking when side is indeterminate;
    # the side field itself will appear in missing_string_fields if absent.
    is_exit_hint = (side == "SELL")

    # Build the effective mandatory field sets
    effective_string_fields = (
        _MANDATORY_PROPOSAL_STRING_FIELDS_COMMON
        | (_MANDATORY_SELL_STRING_FIELDS if is_exit_hint else _MANDATORY_BUY_STRING_FIELDS)
    )
    effective_numeric_fields = (
        _MANDATORY_PROPOSAL_NUMERIC_FIELDS_COMMON
        | (_MANDATORY_SELL_NUMERIC_FIELDS if is_exit_hint else _MANDATORY_BUY_NUMERIC_FIELDS)
    )

    # ── Phase 1: common mandatory fields (apply to both BUY and SELL) ──
    missing_strings = []
    for field in sorted(_MANDATORY_PROPOSAL_STRING_FIELDS_COMMON):
        value = proposal.get(field)
        if not isinstance(value, str) or not value.strip():
            missing_strings.append(field)

    missing_numerics = []
    for field in sorted(_MANDATORY_PROPOSAL_NUMERIC_FIELDS_COMMON):
        value = proposal.get(field)
        if not isinstance(value, (int, float)):
            missing_numerics.append(field)

    missing_bools = []
    for field in sorted(_MANDATORY_PROPOSAL_BOOL_FIELDS):
        value = proposal.get(field)
        if not isinstance(value, bool):
            missing_bools.append(field)

    # If common fields are missing, fail early (don't evaluate side-specific)
    if missing_strings or missing_numerics or missing_bools:
        all_missing = missing_strings + missing_numerics + missing_bools
        return (
            False,
            f"Incomplete proposal: {len(all_missing)} missing/invalid field(s): "
            f"{', '.join(all_missing[:8])}"
            + (f" ... +{len(all_missing) - 8} more" if len(all_missing) > 8 else ""),
            {
                "proposal_path": str(path),
                "error": "incomplete_proposal",
                "side": side or None,
                "missing_string_fields": missing_strings,
                "missing_numeric_fields": missing_numerics,
                "missing_bool_fields": missing_bools,
                "total_missing": len(all_missing),
            },
        )

    # ── Phase 2: side validity ─────────────────────────────────────────
    if side not in ("BUY", "SELL"):
        return (
            False,
            f"Proposal side must be BUY or SELL, got {side!r}",
            {"proposal_path": str(path), "error": "invalid_side", "side": side},
        )

    is_exit = (side == "SELL")

    # ── Phase 3: side-specific mandatory fields ────────────────────────
    side_strings = []
    side_numerics = []
    side_sizing = []

    if is_exit:
        # SELL: require entry_reference as exit rationale
        for field in sorted(_MANDATORY_SELL_STRING_FIELDS):
            value = proposal.get(field)
            if not isinstance(value, str) or not value.strip():
                side_strings.append(field)
        # No extra numerics or position_sizing for EXIT
    else:
        # BUY: require entry_reference, stop_loss_invalidation, position_sizing, etc.
        for field in sorted(_MANDATORY_BUY_STRING_FIELDS):
            value = proposal.get(field)
            if not isinstance(value, str) or not value.strip():
                side_strings.append(field)
        for field in sorted(_MANDATORY_BUY_NUMERIC_FIELDS):
            value = proposal.get(field)
            if not isinstance(value, (int, float)):
                side_numerics.append(field)
        pos_sizing = proposal.get("position_sizing")
        if isinstance(pos_sizing, dict):
            for field in sorted(_MANDATORY_POSITION_SIZING_FIELDS):
                if field not in pos_sizing or pos_sizing[field] is None:
                    side_sizing.append(f"position_sizing.{field}")
        else:
            side_sizing.append("position_sizing (missing or not an object)")

    all_missing = side_strings + side_numerics + side_sizing
    if all_missing:
        return (
            False,
            f"Incomplete proposal ({side}): {len(all_missing)} missing/invalid field(s): "
            f"{', '.join(all_missing[:8])}"
            + (f" ... +{len(all_missing) - 8} more" if len(all_missing) > 8 else ""),
            {
                "proposal_path": str(path),
                "error": "incomplete_proposal",
                "side": side,
                "missing_string_fields": side_strings,
                "missing_numeric_fields": side_numerics,
                "missing_sizing_fields": side_sizing,
                "total_missing": len(all_missing),
            },
        )

    return (
        True,
        f"Proposal validated ({side}): {path.name}",
        {
            "proposal_path": str(path),
            "proposal_id": proposal.get("proposal_id"),
            "symbol": proposal.get("symbol"),
            "side": side,
            "quantity": proposal.get("quantity"),
        },
    )


def gate_open_orders(
    symbol: str,
    open_order_provider=None,
) -> tuple:
    """Open order conflict check.

    For SELL close-only preflight only. Rejects if any unresolved
    open/pending order exists for the same symbol.

    Unresolved statuses include:
        PreSubmitted, Submitted, PendingSubmit, ApiPending,
        PartiallyFilled (remaining > 0), Unknown (remaining > 0)

    Terminal/excluded statuses:
        Filled, Cancelled, ApiCancelled, Inactive

    Returns:
        (pass, reason, details_dict)
    """
    if open_order_provider is None:
        return (True, "No open-order provider — skipping gate H", {"gate_h_skipped": True})

    try:
        result = open_order_provider()
        open_orders = result.get("open_orders", [])
    except Exception:
        return (True, "Open-order provider error — skipping gate H", {"gate_h_skipped": True})

    # Filter to same-symbol unresolved orders
    conflicting = [
        o for o in open_orders
        if o.get("symbol", "").upper() == symbol.upper()
        and o.get("remaining", 0) > 0
    ]

    if not conflicting:
        return (
            True,
            f"No unresolved open orders for {symbol.upper()}",
            {"conflicting_count": 0},
        )

    conflict_details = [
        {
            "order_id": o.get("order_id"),
            "permId": o.get("permId"),
            "action": o.get("action"),
            "status": o.get("status"),
            "remaining": o.get("remaining"),
            "age_seconds": o.get("age_seconds"),
            "requires_manual_action": o.get("requires_manual_action", False),
        }
        for o in conflicting
    ]

    order_ids = [str(c["order_id"]) for c in conflict_details]
    statuses = [c["status"] for c in conflict_details]
    status_summary = ", ".join(f"order_id={oid} ({s})" for oid, s in zip(order_ids, statuses))
    return (
        False,
        f"Unresolved open order(s): {status_summary} for {symbol.upper()} — close blocked",
        {
            "conflicting_count": len(conflicting),
            "conflicting_orders": conflict_details,
        }
    )


# --- Paths ---

RULES_PATH = Path(os.environ.get(
    "IBKR_RULES_PATH",
    str(Path.home() / ".openclaw" / "risk-rules" / "paper-trading-rules.yaml")
))

GUARD_EVENTS_PATH = Path(os.environ.get(
    "IBKR_GUARD_EVENTS_PATH",
    str(Path.home() / ".openclaw" / "guard-events.jsonl")
))


# --- Event Logging (Step 6) ---

ALLOWED_EVENT_TYPES = frozenset({
    "preflight_pass",
    "preflight_fail",
    "approval_timeout",
    "approval_invalidated_restart",
    "user_approved",
    "user_denied",
    "halt_activated",
    "halt_cleared",
    "order_blocked",
    "safety_violation",
    "submit_blocked",
    "submit_revalidation_failed",
    "order_submitted",
    "order_failed",
    "startup_reconciliation",
    "order_unconfirmed",
    "guard_calendar_rollover",
    "monitor_alert",
    "monitor_reconciliation",
    "monitor_open_orders",
    "startup_safety",
    "dry_run_order",
})


# Fields that must never appear in a guard event log
_FORBIDDEN_LOG_FIELDS = frozenset({
    "api_key", "api_secret", "token", "password", "secret",
    "access_token", "refresh_token", "account_password",
    "env", "environment", "credentials",
})


def _strip_forbidden(payload: dict) -> dict:
    """Remove any forbidden fields from payload before logging."""
    clean = {}
    for k, v in payload.items():
        k_lower = k.lower()
        if k_lower in _FORBIDDEN_LOG_FIELDS:
            continue
        if isinstance(v, dict):
            clean[k] = _strip_forbidden(v)
        else:
            clean[k] = v
    return clean


def append_guard_event(
    event_type: str,
    payload: dict | None = None,
    path: str | Path | None = None,
) -> dict:
    """Append one JSON line to the guard events file.

    Args:
        event_type: One of ALLOWED_EVENT_TYPES.
        payload: Dict with safe computed values. Must not contain
            executable order payloads, secrets, tokens, or credentials.
        path: Override events file path (defaults to GUARD_EVENTS_PATH).

    Returns:
        The recorded event dict (for test assertions).

    Raises:
        ValueError: invalid event_type, or forbidden field detected.
    """
    if event_type not in ALLOWED_EVENT_TYPES:
        raise ValueError(
            f"Invalid event type '{event_type}'. "
            f"Allowed: {sorted(ALLOWED_EVENT_TYPES)}"
        )

    payload = payload or {}

    # Check for forbidden fields in the payload
    clean_payload = _strip_forbidden(payload)
    if clean_payload != payload:
        raise ValueError(
            "Forbidden field detected in log payload. "
            "Secrets, tokens, and credentials must not be logged."
        )

    event = {
        "event_id": str(uuid.uuid4()),
        "event_type": event_type,
        "timestamp_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "schema_version": EXPECTED_SCHEMA_VERSION,
        **clean_payload,
    }

    log_path = Path(path) if path else GUARD_EVENTS_PATH

    # Phase H1: Block unauthorized writes to protected files
    _assert_h1_authorized_for_path(log_path)

    log_path.parent.mkdir(parents=True, exist_ok=True)

    line = json.dumps(event, sort_keys=True) + "\n"

    # Atomic append: write, fsync, close
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(line)
        f.flush()
        os.fsync(f.fileno())

    return event


def read_guard_events(path: str | Path | None = None) -> list[dict]:
    """Read and parse all events from the JSONL file.

    Returns list of event dicts in file order.
    Returns empty list if file does not exist.
    """
    log_path = Path(path) if path else GUARD_EVENTS_PATH
    if not log_path.exists():
        return []
    events = []
    with open(log_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                events.append(json.loads(line))
    return events


# --- Preflight Orchestrator (Step 7A) ---

ALLOWED_REQUEST_FIELDS = frozenset({
    "symbol", "action", "totalQuantity", "orderType",
    "limitPrice", "stopPrice", "stopPercent", "mode",
})

ALLOWED_ACTIONS = frozenset({"BUY", "SELL"})
ALLOWED_ORDER_TYPES = frozenset({"MKT", "LMT"})


def _validate_preflight_request(request: dict) -> dict:
    """Validate and normalize a preflight request dict.

    Returns normalized request. Raises ValueError on invalid fields/values.
    """
    for key in request:
        if key not in ALLOWED_REQUEST_FIELDS:
            raise ValueError(
                f"Unknown request field '{key}'. "
                f"Allowed: {sorted(ALLOWED_REQUEST_FIELDS)}"
            )

    symbol = request.get("symbol", "").upper().strip()
    if not symbol:
        raise ValueError("Missing required field: symbol")

    action = request.get("action", "").upper().strip()
    if action not in ALLOWED_ACTIONS:
        raise ValueError(f"Invalid action '{action}'. Only BUY and SELL are allowed.")

    quantity = request.get("totalQuantity")
    if quantity is None:
        raise ValueError("Missing required field: totalQuantity")
    try:
        quantity = int(quantity)
    except (TypeError, ValueError):
        raise ValueError(f"totalQuantity must be an integer, got {quantity}")
    if quantity <= 0:
        raise ValueError(f"totalQuantity must be > 0, got {quantity}")

    order_type = request.get("orderType", "").upper().strip()
    if order_type not in ALLOWED_ORDER_TYPES:
        raise ValueError(
            f"Invalid orderType '{order_type}'. Only MKT and LMT are allowed."
        )

    if order_type == "LMT":
        limit_price = request.get("limitPrice")
        if limit_price is None or not isinstance(limit_price, (int, float)) or limit_price <= 0:
            raise ValueError("LMT orders require a valid limitPrice > 0")

    # P5: Normalize stopPercent if present
    stop_percent = request.get("stopPercent")
    if stop_percent is not None:
        try:
            stop_percent = float(stop_percent)
        except (TypeError, ValueError):
            raise ValueError(f"stopPercent must be numeric, got {stop_percent}")
        if not (-99.0 < stop_percent < 0):
            raise ValueError(
                f"stopPercent must be negative (e.g. -5.0 for 5% below entry), "
                f"got {stop_percent}"
            )

    return {
        "symbol": symbol,
        "action": action,
        "totalQuantity": quantity,
        "orderType": order_type,
        "limitPrice": request.get("limitPrice"),
        "stopPrice": request.get("stopPrice"),
        "stopPercent": stop_percent,
        "mode": request.get("mode"),
    }


def run_preflight(request: dict, account_provider=None, quote_provider=None,
                  bars_provider=None, position_provider=None, open_order_provider=None,
                  proposal_path=None) -> dict:
    """Compatibility entry point for the authoritative application preflight."""
    if _execution_service is None or _proposal_loader is None:
        return {"passed": False, "code": "EXECUTION_RUNTIME_NOT_READY"}
    if any(p is not None for p in (account_provider, quote_provider, bars_provider,
                                   position_provider, open_order_provider)):
        return {"passed": False, "code": "LEGACY_PROVIDERS_DISABLED"}
    payload = dict(request)
    path = proposal_path if proposal_path is not None else payload.pop("proposal_path", None)
    try:
        proposal = _proposal_loader(str(path) if path is not None else None)
    except (ValueError, OSError):
        return {"passed": False, "code": "PROPOSAL_INVALID", "error": "Valid persisted proposal required"}
    return _execution_service.preflight(payload, proposal=proposal)


# --- Approval Records (Phase 2C Step 1) ---

APPROVAL_RECORDS_PATH = Path(os.environ.get(
    "IBKR_APPROVAL_RECORDS_PATH",
    str(Path.home() / ".openclaw" / "approval-records.jsonl")
))

SUBMITTED_APPROVALS_PATH = Path(os.environ.get(
    "IBKR_SUBMITTED_APPROVALS_PATH",
    str(Path.home() / ".openclaw" / "submitted-approvals.json")
))

ACTIVE_APPROVALS_PATH = Path(os.environ.get(
    "IBKR_ACTIVE_APPROVALS_PATH",
    str(Path.home() / ".openclaw" / "active-approvals.json")
))

APPROVAL_TIMEOUT_SECONDS = 300

# In-memory active approvals dict: approval_id -> record
_active_approvals: dict[str, dict] = {}

# Fields that must never appear in an approval record
_FORBIDDEN_APPROVAL_FIELDS = frozenset({
    "order_id", "ibkr_order", "transmit", "account",
    "tif", "permId", "clientId", "submitted",
})

# Fields allowed in proposal subset of an approval record
_ALLOWED_PROPOSAL_FIELDS = frozenset({
    "symbol", "action", "totalQuantity", "orderType", "limitPrice",
})


def _generate_approval_id() -> str:
    return "aprv_" + str(uuid.uuid4())


def _generate_preflight_id() -> str:
    return "pf_" + str(uuid.uuid4())


def _strip_forbidden_approval(payload: dict) -> dict:
    """Remove any forbidden executable fields from payload."""
    return {k: v for k, v in payload.items() if k.lower() not in _FORBIDDEN_APPROVAL_FIELDS}


def _append_approval_record(record: dict) -> None:
    """Append one JSON line to approval-records.jsonl.

    Phase H1: Requires H1 authorization for protected paths.
    """
    path = APPROVAL_RECORDS_PATH

    # Phase H1: Block unauthorized writes to protected files
    _assert_h1_authorized_for_path(path)

    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, sort_keys=True) + "\n"
    with open(path, "a", encoding="utf-8") as f:
        f.write(line)
        f.flush()
        os.fsync(f.fileno())


def create_approval_record(preflight_result: dict) -> dict:
    if _execution_service is None:
        raise RuntimeError("EXECUTION_RUNTIME_NOT_READY")
    # Only a preflight-created, already committed immutable record can be returned.
    aid = preflight_result.get("approval_id")
    if not aid:
        raise ValueError("DURABLE_PREFLIGHT_REQUIRED")
    return _execution_service.store.approval(aid)


def _validate_ruling(approval_id: str) -> tuple[str, dict] | tuple[None, str]:
    """Validate that an approval_id exists and is pending.

    Returns (approval_id, record) on success, or (None, error_msg) on failure.
    """
    if not approval_id or not isinstance(approval_id, str):
        return None, "approval_id must be a non-empty string"

    record = _active_approvals.get(approval_id)
    if record is None:
        return None, f"No active approval found for id '{approval_id}'"

    if record["status"] != "pending":
        return None, f"Approval '{approval_id}' is already {record['status']}"

    # Check expiry
    expires = datetime.fromisoformat(_normalize_timestamp(record["expires_at_utc"]))
    if datetime.now(timezone.utc) > expires:
        # Auto-expire
        return None, f"Approval '{approval_id}' has expired"

    return approval_id, record


def approve_approval(approval_id: str, ruled_by: str = "Chris") -> dict:
    if _execution_service is None:
        raise RuntimeError("EXECUTION_RUNTIME_NOT_READY")
    return _execution_service.rule(approval_id, "approve", authorized=_h1_authorized.get())


def deny_approval(approval_id: str, ruled_by: str = "Chris") -> dict:
    if _execution_service is None:
        raise RuntimeError("EXECUTION_RUNTIME_NOT_READY")
    return _execution_service.rule(approval_id, "deny", authorized=_h1_authorized.get())


def expire_approval(approval_id: str) -> dict | None:
    """Transition approval from pending to expired.

    Returns updated record, or None if not found or already finalized.
    """
    record = _active_approvals.get(approval_id)
    if record is None or record["status"] != "pending":
        return None

    now = datetime.now(timezone.utc)
    record["status"] = "expired"
    record["ruling_at_utc"] = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    record["ruled_by"] = "system"
    _active_approvals[approval_id] = record
    _save_active_approvals()

    # Log event
    append_guard_event("approval_timeout", {
        "approval_id": approval_id,
        "symbol": record["proposal"].get("symbol"),
        "expires_at": record["expires_at_utc"],
    })

    return record


def expire_all_pending() -> list[dict]:
    """Expire all pending approvals whose expires_at_utc < now.

    Returns list of expired records.
    """
    now = datetime.now(timezone.utc)
    expired = []
    for aid in list(_active_approvals.keys()):
        record = _active_approvals[aid]
        if record["status"] != "pending":
            continue
        expires = datetime.fromisoformat(_normalize_timestamp(record["expires_at_utc"]))
        if now > expires:
            record["status"] = "expired"
            record["ruling_at_utc"] = now.strftime("%Y-%m-%dT%H:%M:%SZ")
            record["ruled_by"] = "system"
            _active_approvals[aid] = record
            append_guard_event("approval_timeout", {
                "approval_id": aid,
                "symbol": record["proposal"].get("symbol"),
                "expires_at": record["expires_at_utc"],
            })
            expired.append(record)
    if expired:
        _save_active_approvals()
    return expired


def get_active_approval(approval_id: str) -> dict | None:
    if _execution_service is None:
        return None
    from trading_agent.domain import timestamp, utcnow
    try:
        record = _execution_service.store.approval(approval_id)
    except ValueError:
        return None
    return record if record["status"] in ("pending", "approved") and timestamp(record["expires_at"]) > utcnow() else None


def get_all_active_approvals() -> list[dict]:
    return _execution_service.store.approvals() if _execution_service is not None else []


# --- Kill Switch Helpers (Phase 2D) ---


def _check_ibkr_allowed() -> bool:
    """Check if IBKR_ALLOW_ORDERS env var is true.

    Returns True only if the environment variable is set to 'true' (case-insensitive).
    This is one of two independent kill switches for /order/submit.
    """
    return os.getenv("IBKR_ALLOW_ORDERS", "false").lower() == "true"


def _check_enforced(rules: dict | None = None) -> bool:
    """Check if paper-trading-rules.yaml enforced flag is true.

    This is one of two independent kill switches for /order/submit.
    Accepts an optional pre-loaded rules dict to avoid re-reading the file.

    Returns True only when rules.enforced is exactly True.
    """
    if rules is None:
        try:
            rules = load_rules()
        except (FileNotFoundError, ValueError, ImportError):
            return False
    return rules.get("enforced", False) is True


# --- One-Use Approval Tracking (Phase 2D Step 2/3 — Phase 2E: Persistent) ---

# In-memory set of submitted approval IDs, seeded from persistent storage
# at module import time. Survives bridge restarts via submitted-approvals.json.
_submitted_approvals: set[str] = set()


def _submitted_approvals_path() -> Path:
    """Return the path to the submitted approvals file."""
    return SUBMITTED_APPROVALS_PATH


def _load_submitted_approvals() -> set[str]:
    """Load the persisted set of submitted approval IDs from disk.

    Returns an empty set if the file does not exist or is corrupt.
    """
    p = _submitted_approvals_path()
    if not p.exists():
        return set()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return set(data)
        return set()
    except (json.JSONDecodeError, OSError):
        return set()


def _save_submitted_approvals() -> None:
    """Atomically persist the submitted approvals set to disk.

    Phase H1: Requires H1 authorization for protected paths.
    """
    p = _submitted_approvals_path()

    # Phase H1: Block unauthorized writes to protected files
    _assert_h1_authorized_for_path(p)

    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(sorted(_submitted_approvals), indent=2), encoding="utf-8", newline="\n")
    tmp.replace(p)


def _active_approvals_path() -> Path:
    return ACTIVE_APPROVALS_PATH


def _load_active_approvals() -> dict[str, dict]:
    """Invalidate every pending/approved-but-unsubmitted approval left on disk.

    Safety invariant #12 (CLAUDE.md §3, RUNBOOK §L9): on bridge restart, all
    in-memory pending and approved-but-unsubmitted approvals are invalid.
    Fresh preflight -> fresh approval, always.

    This function used to *restore* those records from active-approvals.json
    (fallback: approval-records.jsonl) so they survived a restart. That
    contradicted the invariant: an approval ruled up to 300 s before a
    restart came back live in the new process and passed the submit
    validators; only the kill switches stood between it and IBKR.

    Now it does the opposite. Every pending/approved record that is not
    already submitted is
      - appended to approval-records.jsonl with status "expired",
        ruled_by "system", expiry_reason "bridge_restart"
      - logged as an approval_invalidated_restart guard event
    and the active-approvals.json snapshot is reset to {}.  _active_approvals
    always starts empty.  The function name is kept so the existing call
    site in reconcile_approvals_on_startup() and test patches still work.

    Runs inside h1_authorized_scope(): deterministic startup housekeeping
    with no operator degrees of freedom (same reasoning as the preflight
    calendar rollover, Phase 19L), not an order mutation.
    """
    global _active_approvals
    _active_approvals.clear()
    now_utc = datetime.now(timezone.utc)
    now_str = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")

    # Latest known record per approval_id. approval-records.jsonl is an
    # append-only log (later line supersedes earlier); the snapshot is
    # rewritten on every mutation, so it wins over the log.
    candidates: dict[str, dict] = {}

    records_path = APPROVAL_RECORDS_PATH
    if records_path.exists():
        try:
            for line in records_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(rec, dict):
                    continue
                aid = rec.get("approval_id", "")
                if aid:
                    candidates[aid] = rec
        except OSError:
            pass

    snapshot_path = ACTIVE_APPROVALS_PATH
    if snapshot_path.exists():
        try:
            snapshot_data = json.loads(snapshot_path.read_text(encoding="utf-8"))
            if isinstance(snapshot_data, dict):
                for aid, rec in snapshot_data.items():
                    if isinstance(rec, dict) and aid:
                        candidates[aid] = rec
        except (json.JSONDecodeError, OSError):
            pass

    invalidated: list[dict] = []
    for aid, rec in candidates.items():
        previous_status = rec.get("status", "")
        if previous_status not in ("pending", "approved"):
            continue
        if aid in _submitted_approvals:
            continue
        was_live = True
        expires_str = rec.get("expires_at_utc")
        if expires_str:
            try:
                expires = datetime.fromisoformat(_normalize_timestamp(expires_str))
                was_live = now_utc <= expires
            except (ValueError, TypeError):
                pass
        rec = dict(rec)
        rec["approval_id"] = aid
        rec["previous_status"] = previous_status
        rec["status"] = "expired"
        rec["ruling_at_utc"] = now_str
        rec["ruled_by"] = "system"
        rec["expiry_reason"] = "bridge_restart"
        rec["was_live_at_restart"] = was_live
        invalidated.append(rec)

    with h1_authorized_scope():
        for rec in invalidated:
            try:
                _append_approval_record(rec)
            except OSError:
                pass
            append_guard_event("approval_invalidated_restart", {
                "approval_id": rec["approval_id"],
                "symbol": (rec.get("proposal") or {}).get("symbol"),
                "previous_status": rec["previous_status"],
                "was_live_at_restart": rec["was_live_at_restart"],
                "expires_at": rec.get("expires_at_utc"),
            })
        # Reset the snapshot so nothing on disk still reads as active.
        if invalidated or snapshot_path.exists():
            try:
                _save_active_approvals()
            except OSError:
                pass

    return _active_approvals


def _save_active_approvals() -> None:
    """Atomically persist _active_approvals to disk.

    Phase H1: Requires H1 authorization for protected paths.
    """
    p = _active_approvals_path()

    # Phase H1: Block unauthorized writes to protected files
    _assert_h1_authorized_for_path(p)

    p.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = p.with_suffix(".json.tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(_active_approvals, f, indent=2, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_path, p)


def reconcile_approvals_on_startup() -> dict:
    """Reconcile submitted approvals from persistent storage + events on startup.

    Sources:
    1. submitted-approvals.json (if exists) — exact persisted set
    2. guard-events.jsonl — approve any order_submitted event not yet tracked
    3. approval-records.jsonl — mark any record with order_id as submitted

    This ensures that after a bridge restart, approvals that were already
    submitted cannot be reused, even if the in-memory set was lost.

    Returns a summary dict for logging."""
    global _submitted_approvals

    counts = {
        "from_file": 0,
        "from_events": 0,
        "from_records": 0,
        "total": 0,
    }

    # 1. Load from persisted file
    persisted = _load_submitted_approvals()
    _submitted_approvals = set(persisted)
    counts["from_file"] = len(persisted)

    # 2. Scan guard-events.jsonl for order_submitted events
    events_path = GUARD_EVENTS_PATH
    if events_path.exists():
        try:
            for line in events_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    evt = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if evt.get("event_type") == "order_submitted":
                    aid = evt.get("approval_id", "")
                    if aid and aid not in _submitted_approvals:
                        _submitted_approvals.add(aid)
                        counts["from_events"] += 1
        except OSError:
            pass

    # 3. Scan approval-records.jsonl for records with order_id set
    records_path = APPROVAL_RECORDS_PATH
    if records_path.exists():
        try:
            for line in records_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                aid = rec.get("approval_id", "")
                if aid and rec.get("order_id") is not None and aid not in _submitted_approvals:
                    _submitted_approvals.add(aid)
                    counts["from_records"] += 1
        except OSError:
            pass

    # 4. Mark stale pending approvals as expired
    stale_expired = 0
    if records_path.exists():
        now_utc = datetime.now(timezone.utc)
        try:
            for line in records_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if rec.get("status") == "pending" and rec.get("expires_at_utc"):
                    try:
                        expires = datetime.fromisoformat(_normalize_timestamp(rec["expires_at_utc"]))
                        if now_utc > expires:
                            stale_expired += 1
                    except (ValueError, TypeError):
                        pass
        except OSError:
            pass

    # 4.b. Invariant #12: invalidate (never restore) pending/approved-but-
    # unsubmitted approvals left on disk by the previous process. Records
    # them as expired (expiry_reason=bridge_restart), logs an event, resets
    # the snapshot. _active_approvals starts empty after every restart.
    _load_active_approvals()

    # 5. Scan guard-events.jsonl for order_unconfirmed events (stale/submitted-unacknowledged)
    unconfirmed_orders = []
    unconfirmed_approval_ids = set()
    if events_path.exists():
        try:
            for line in events_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    evt = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if evt.get("event_type") == "order_unconfirmed":
                    unconfirmed_orders.append({
                        "approval_id": evt.get("approval_id"),
                        "order_id": evt.get("order_id"),
                        "symbol": evt.get("symbol"),
                        "error": evt.get("error"),
                    })
                    aid = evt.get("approval_id", "")
                    if aid:
                        unconfirmed_approval_ids.add(aid)
        except OSError:
            pass

    # 6. Detect legacy order_submitted events that have no ibkr_metadata
    # (pre-fix submissions like order_id=24 that were never acknowledged by IBKR)
    #
    # Bug fix (2026-08-13): this previously re-flagged the same legacy event on
    # every single startup forever, even after a human had already manually
    # reconciled it via monitor.append_manual_reconciliation() (e.g. order_id=24
    # was confirmed NotFoundInIBKR/filled=0.0 on 2026-06-11, yet kept resurfacing
    # here on every restart for two more months because this scan never checked
    # the manual-reconciliation record). A (order_id, symbol) pair with an
    # existing manual_terminal record is excluded here — that question has
    # already been answered by a human and should not be re-asked.
    already_reconciled: set[tuple] = set()
    try:
        from monitor import load_manual_reconciliations
        for rec in load_manual_reconciliations():
            oid = rec.get("order_id")
            sym = rec.get("symbol")
            if oid is not None and sym:
                already_reconciled.add((oid, sym))
    except Exception:
        pass  # fail open — if manual reconciliations can't be read, fall back to old behavior

    legacy_unconfirmed = []
    if events_path.exists():
        try:
            for line in events_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    evt = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if evt.get("event_type") == "order_submitted":
                    ibkr = evt.get("ibkr_metadata")
                    if ibkr is None and evt.get("action") == "SELL":
                        # Legacy SELL close event without IBKR confirmation
                        aid_check = evt.get("approval_id", "")
                        evt_order_id = evt.get("order_id")
                        evt_symbol = evt.get("symbol")
                        if (evt_order_id, evt_symbol) in already_reconciled:
                            continue  # already manually resolved — stop re-flagging it
                        if aid_check and aid_check not in unconfirmed_approval_ids:
                            legacy_unconfirmed.append({
                                "approval_id": aid_check,
                                "order_id": evt_order_id,
                                "symbol": evt_symbol,
                            })
        except OSError:
            pass

    # Correct daily_trade_count exactly once for legacy unconfirmed events
    # Use guard_state flag to ensure idempotency across restarts
    if legacy_unconfirmed:
        guard_state = load_guard_state()
        already_corrected = guard_state.get("legacy_unconfirmed_corrected", False)
        if not already_corrected:
            corrected_down = 0
            for lu in legacy_unconfirmed:
                if guard_state.get("daily_trade_count", 0) > 0:
                    guard_state["daily_trade_count"] -= 1
                    corrected_down += 1
            if corrected_down > 0:
                guard_state["legacy_unconfirmed_corrected"] = True
                guard_state["last_updated_utc"] = _now_utc_iso()
                save_guard_state_atomic(guard_state)

    # 7. Persist the reconciled sets
    _save_submitted_approvals()
    _save_active_approvals()

    total = len(_submitted_approvals)
    counts["total"] = total
    counts["stale_expired"] = stale_expired
    counts["unconfirmed_orders"] = unconfirmed_orders
    counts["legacy_unconfirmed"] = legacy_unconfirmed

    # Log startup reconciliation event
    append_guard_event("startup_reconciliation", {
        "from_file": counts["from_file"],
        "from_events": counts["from_events"],
        "from_records": counts["from_records"],
        "total_submitted": total,
        "stale_expired": stale_expired,
        "unconfirmed_count": len(unconfirmed_orders),
        "unconfirmed_orders": unconfirmed_orders if unconfirmed_orders else None,
        "legacy_unconfirmed_count": len(legacy_unconfirmed),
        "legacy_unconfirmed": legacy_unconfirmed if legacy_unconfirmed else None,
    })

    return counts


def is_approval_submitted(approval_id: str) -> bool:
    return bool(_execution_service and _execution_service.store.execution_for_approval(approval_id))


def mark_approval_submitted(approval_id: str) -> str:
    raise RuntimeError("ONLY_ATOMIC_EXECUTION_RESERVATION_MAY_MARK_SUBMITTED")


# --- Submit Revalidation (Phase 2D Step 2) ---


def revalidate_before_submit(
    approval_record: dict,
    account_provider=None,
    quote_provider=None,
    bars_provider=None,
) -> dict:
    """Revalidate an approved approval immediately before submission.

    Checks:
    1. Approval status is "approved"
    2. Approval not expired (expires_at_utc still in future)
    3. Approval not already used/submitted
    4. Fresh account data (NL check, daily/weekly halts)
    5. Entry price drift <= 1% vs approved entry
    6. Stop price drift <= 2% vs recomputed stop
    7. Symbol still in allowlist

    Args:
        approval_record: The approval record dict.
        account_provider: Optional callable() -> dict for account data.
            If None, uses guard.fetch_account() (HTTP self-call).
        quote_provider: Optional callable(symbol) -> dict for quote data.
            If None, uses guard.fetch_quote() (HTTP self-call).
        bars_provider: Optional callable(symbol) -> list for bar data.
            If None, uses guard.fetch_bars() (HTTP self-call).

    Returns dict:
        On pass: {"passed": True, "details": {...}}
        On fail: {"passed": False, "error": "...", "code": "...", "details": {...}}

    Never calls IBKR order APIs. Never places orders.
    """
    errors: list[str] = []
    details: dict = {}

    aid = approval_record.get("approval_id", "")

    def _fail(code: str, error: str, extra: dict | None = None) -> dict:
        """Log submit_revalidation_failed and return the failure dict."""
        result = {"passed": False, "error": error, "code": code}
        if extra:
            result["details"] = {**details, **extra}
        append_guard_event("submit_revalidation_failed", {
            "code": code,
            "error": error,
            "approval_id": aid or None,
            "symbol": approval_record.get("proposal", {}).get("symbol"),
        })
        return result

    # 1. Status check
    status = approval_record.get("status")
    if status != "approved":
        return _fail("NOT_APPROVED", f"Approval status is '{status}', expected 'approved'")

    # 2. Expiry check
    expires_str = approval_record.get("expires_at_utc")
    if expires_str:
        try:
            expires = datetime.fromisoformat(_normalize_timestamp(expires_str))
            if datetime.now(timezone.utc) > expires:
                return _fail("EXPIRED", f"Approval expired at {expires_str}")
        except (ValueError, TypeError):
            pass  # malformed timestamp — proceed with other checks

    # 3. Already-used check
    aid = approval_record.get("approval_id", "")
    if aid and is_approval_submitted(aid):
        return _fail("ALREADY_SUBMITTED", f"Approval '{aid}' has already been submitted")

    # 4. Fresh account data — check NL loss halts
    try:
        guard_state = load_guard_state()
        account = account_provider() if account_provider else fetch_account()
    except (RuntimeError, ValueError) as e:
        return _fail("ACCOUNT_UNAVAILABLE", f"Cannot fetch account data: {e}")

    current_nl_eur = account.get("net_liquidation_eur", 0)
    details["current_nl_eur"] = current_nl_eur
    details["day_start_nl_eur"] = guard_state.get("day_start_nl_eur")
    details["week_start_nl_eur"] = guard_state.get("week_start_nl_eur")

    if guard_state.get("daily_halt_active", False):
        return _fail("DAILY_HALT_ACTIVE", "Daily loss halt active — entries frozen for remainder of day")
    if guard_state.get("weekly_halt_active", False):
        return _fail("WEEKLY_HALT_ACTIVE", "Weekly loss halt active — entries frozen until manual review")

    # Check if NL would trigger halt now
    try:
        rules = load_rules()
    except Exception:
        rules = {}

    day_start_nl = guard_state.get("day_start_nl_eur")
    week_start_nl = guard_state.get("week_start_nl_eur")

    if day_start_nl and day_start_nl > 0 and current_nl_eur > 0:
        daily_loss_pct = (day_start_nl - current_nl_eur) / day_start_nl * 100
        daily_threshold = rules.get("loss_halts", {}).get("daily", {}).get("value", 1)
        if daily_loss_pct >= daily_threshold:
            return _fail("DAILY_HALT_TRIGGERED", f"Portfolio down {daily_loss_pct:.2f}% from day-start (threshold {daily_threshold}%)")

    if week_start_nl and week_start_nl > 0 and current_nl_eur > 0:
        weekly_loss_pct = (week_start_nl - current_nl_eur) / week_start_nl * 100
        weekly_threshold = rules.get("loss_halts", {}).get("weekly", {}).get("value", 3)
        if weekly_loss_pct >= weekly_threshold:
            return _fail("WEEKLY_HALT_TRIGGERED", f"Portfolio down {weekly_loss_pct:.2f}% from week-start (threshold {weekly_threshold}%)")

    # 5. Entry price drift check
    proposal = approval_record.get("proposal", {})
    validation = approval_record.get("validation", {})
    symbol = proposal.get("symbol", "")
    action = proposal.get("action", "BUY")
    qty = proposal.get("totalQuantity", 0)
    approved_entry = validation.get("entry_price")

    if not symbol:
        return _fail("BAD_APPROVAL", "No symbol in approval proposal")

    # Close-only (SELL) has no entry_price — skip validation
    is_close = (action == "SELL")
    if not is_close and (not approved_entry or approved_entry <= 0):
        return _fail("BAD_APPROVAL", "No entry_price in approval validation")

    details["symbol"] = symbol
    details["action"] = action
    details["totalQuantity"] = qty
    details["approved_entry_price"] = approved_entry

    # Fetch fresh quote
    try:
        quote = quote_provider(symbol) if quote_provider else fetch_quote(symbol)
    except (RuntimeError, ValueError) as e:
        return _fail("QUOTE_UNAVAILABLE", f"Cannot fetch quote for {symbol}: {e}")

    current_ask = quote.get("ask")
    if current_ask is None or current_ask <= 0:
        current_ask = quote.get("last") or quote.get("close") or quote.get("marketPrice")
    if current_ask is None or current_ask <= 0:
        return _fail("QUOTE_NO_PRICE", f"No valid price in quote for {symbol}")

    details["current_ask"] = current_ask

    # Entry drift check: skip for close-only (SELL) — no entry price reference
    if not is_close:
        entry_drift_pct = abs(current_ask - approved_entry) / approved_entry * 100
        details["entry_drift_pct"] = round(entry_drift_pct, 3)

        MAX_ENTRY_DRIFT_PCT = 1.0
        if entry_drift_pct > MAX_ENTRY_DRIFT_PCT:
            return _fail("STALE_PRICE", f"Entry price drifted {entry_drift_pct:.2f}% from ${approved_entry:.2f} to ${current_ask:.2f} (threshold {MAX_ENTRY_DRIFT_PCT}%)", {"entry_drift_pct": round(entry_drift_pct,3), "approved_entry": approved_entry, "current_ask": current_ask})

    # 6. Stop price drift check — fetch bars and recompute
    try:
        bars = bars_provider(symbol) if bars_provider else fetch_bars(symbol)
    except (RuntimeError, ValueError) as e:
        return _fail("BARS_UNAVAILABLE", f"Cannot fetch bars for {symbol}: {e}")

    if len(bars) < 20:
        return _fail("INSUFFICIENT_BARS", f"Insufficient bars ({len(bars)}) for stop recomputation")

    try:
        stop_result = calc_stop(current_ask, bars)
    except ValueError as e:
        return _fail("STOP_COMPUTATION_ERROR", f"Stop recomputation failed: {e}")

    current_stop = stop_result["stop_price"]
    approved_stop = validation.get("stop_price")
    details["approved_stop_price"] = approved_stop
    details["current_stop_price"] = current_stop
    details["atr14"] = stop_result.get("atr14")

    if approved_stop and approved_stop > 0 and current_stop > 0:
        stop_drift_pct = abs(current_stop - approved_stop) / approved_stop * 100
        details["stop_drift_pct"] = round(stop_drift_pct, 3)

        MAX_STOP_DRIFT_PCT = 2.0
        if stop_drift_pct > MAX_STOP_DRIFT_PCT:
            return _fail("STALE_STOP", f"Stop price drifted {stop_drift_pct:.2f}% from ${approved_stop:.2f} to ${current_stop:.2f} (threshold {MAX_STOP_DRIFT_PCT}%)", {"stop_drift_pct": round(stop_drift_pct,3), "approved_stop": approved_stop, "current_stop": current_stop})
    else:
        details["stop_drift_pct"] = None

    # 7. Symbol allowlist check (Phase H2 — from YAML, single source of truth)
    allowed = _get_allowed_symbols()
    if symbol.upper() not in allowed:
        return _fail("SYMBOL_BLOCKED", f"Symbol '{symbol}' is not in the allowlist {allowed}")

    # All checks passed
    return {
        "passed": True,
        "details": details,
    }


# --- Order Status Polling (Phase 2D Step 4) ---

# Normalised status set — maps IBKR status strings to a canonical form.
# Terminal statuses are ones where no further polling is needed.
_TERMINAL_STATUSES = frozenset({"Filled", "Cancelled", "Inactive"})

def _normalize_status(raw_status: str | None) -> str:
    """Normalise an IBKR order status string to canonical form.

    Canonical statuses:
        PendingSubmit, PreSubmitted, Submitted, Filled,
        PartiallyFilled, Cancelled, Inactive, Unknown
    """
    if not raw_status:
        return "Unknown"
    s = raw_status.strip()
    # Handle common IBKR variants
    if s == "PendSubmit":
        return "PendingSubmit"
    if s == "PreSubmitted":
        return "PreSubmitted"
    if s in ("Submitted", "Filled", "Cancelled", "Inactive"):
        return s
    if s == "PartiallyFilled":
        return "PartiallyFilled"
    if s in ("ApiPending", "PendingCancel"):
        return "PendingSubmit"
    return "Unknown"


def poll_order_status(
    order_id: int | str,
    status_provider=None,
    max_polls: int = 5,
    interval_s: float = 2.0,
) -> dict:
    """Poll an IBKR order for its status.

    Polls every `interval_s` seconds up to `max_polls` times (default 5 polls
    over ~10 seconds) or until a terminal status (Filled, Cancelled, Inactive)
    is observed.

    Args:
        order_id: The IBKR order ID to poll.
        status_provider: Callable(order_id) -> str | None that returns the
            raw IBKR order status string. If None, uses a default that returns
            "Unknown" (for testing without a live order).
        max_polls: Maximum number of poll attempts.
        interval_s: Seconds between polls.

    Returns:
        Dict with:
            order_id: The requested order ID.
            status: The latest canonical status string.
            polls: Number of polls actually performed.
            terminal: True if a terminal status was reached.
            elapsed_seconds: Total polling time.

    Never places, cancels, or modifies orders.
    """
    import time as time_module

    if status_provider is None:
        status_provider = lambda _: None

    latest_raw = None
    polls_done = 0
    start = time_module.time()

    for i in range(max_polls):
        polls_done = i + 1
        try:
            latest_raw = status_provider(order_id)
        except Exception:
            latest_raw = None

        canonical = _normalize_status(latest_raw)

        if canonical in _TERMINAL_STATUSES:
            elapsed = time_module.time() - start
            return {
                "order_id": order_id,
                "status": canonical,
                "polls": polls_done,
                "terminal": True,
                "elapsed_seconds": round(elapsed, 2),
            }

        if i < max_polls - 1:
            time_module.sleep(interval_s)

    # Timeout — return whatever we have
    elapsed = time_module.time() - start
    final_canonical = _normalize_status(latest_raw)
    return {
        "order_id": order_id,
        "status": final_canonical,
        "polls": polls_done,
        "terminal": final_canonical in _TERMINAL_STATUSES,
        "elapsed_seconds": round(elapsed, 2),
    }


# --- Submit Orchestrator (Phase 2D Step 5) ---


def find_approval_record(approval_id: str) -> tuple[dict | None, str]:
    """Locate an approval record. Returns (record, source), source one of
    "memory" | "disk" | "none".

    This process's _active_approvals is authoritative. The disk fallback
    reads approval-records.jsonl — an append-only log where a later line for
    the same approval_id supersedes an earlier one — so the LAST match wins.
    (The two previous copies of this scan, in bridge.py and submit_order(),
    each stopped at the first match, i.e. the original "pending" creation
    line, even after a ruling or a restart invalidation had been appended.)
    Disk-only records exist for error reporting; they are never submittable
    (invariant #12 — see validate_approval_for_submit()).
    """
    rec = _active_approvals.get(approval_id)
    if rec is not None:
        return rec, "memory"
    found = None
    try:
        p = APPROVAL_RECORDS_PATH
        if p.exists():
            for line in p.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    cand = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(cand, dict) and cand.get("approval_id") == approval_id:
                    found = cand
    except OSError:
        pass
    return (found, "disk") if found is not None else (None, "none")


def validate_approval_for_submit(approval_id: str) -> tuple[dict | None, dict | None]:
    """Single source of truth for "may this approval be submitted right now?"

    Returns (record, None) when the approval is approved, unexpired,
    unsubmitted and live in this process; otherwise (None, error) where
    error is the {"submitted": False, "error": ..., "code": ...} dict the
    submit path returns verbatim.

    Runs BEFORE the kill switches so ALREADY_SUBMITTED / EXPIRED / NOT_FOUND
    report accurately even while orders are blocked. Used by
    bridge._validate_approval_for_submit() and guard.submit_order(); until
    2026-09-07 each carried its own copy of this ladder, which is how the two
    drifted apart on invariant #12.
    """
    def _err(code: str, msg: str) -> tuple[None, dict]:
        return None, {"submitted": False, "error": msg, "code": code}

    record, source = find_approval_record(approval_id)
    if record is None:
        return _err("NOT_FOUND", f"No active approval found for '{approval_id}'")
    status = record.get("status", "")
    if is_approval_submitted(approval_id):
        return _err("ALREADY_SUBMITTED", f"Approval '{approval_id}' has already been submitted")
    if status == "denied":
        return _err("NOT_FOUND", f"Approval '{approval_id}' was denied")
    if status == "expired":
        return _err("EXPIRED", f"Approval '{approval_id}' is expired")
    expires_str = record.get("expires_at_utc")
    if expires_str:
        try:
            expires = datetime.fromisoformat(_normalize_timestamp(expires_str))
            if datetime.now(timezone.utc) > expires:
                return _err("EXPIRED", f"Approval expired at {expires_str}")
        except (ValueError, TypeError):
            pass
    if source != "memory":
        # Invariant #12 (CLAUDE.md §3.12, RUNBOOK §L9): a record that is not in
        # this process's memory was created before a bridge restart. It is
        # invalid even if the on-disk copy still reads "approved" and is
        # inside its 300 s window. _load_active_approvals() expires such
        # records at startup; this is the matching check on the submit path.
        return _err(
            "NOT_FOUND",
            f"Approval '{approval_id}' is not active in this bridge process "
            f"(invalidated by bridge restart, safety invariant #12). "
            f"Run a fresh preflight and obtain a fresh approval.",
        )
    if status != "approved":
        return _err("NOT_APPROVED", f"Approval '{approval_id}' status is '{status}', expected 'approved'")
    return record, None


def submit_order(
    approval_id: str,
    order_provider=None,
    status_provider=None,
    account_provider=None,
    quote_provider=None,
    bars_provider=None,
) -> dict:
    if _execution_service is None:
        return {"submitted": False, "code": "EXECUTION_RUNTIME_NOT_READY", "retry_allowed": False}
    if any(p is not None for p in (order_provider, status_provider, account_provider, quote_provider, bars_provider)):
        return {"submitted": False, "code": "LEGACY_PROVIDERS_DISABLED", "retry_allowed": False}
    return _execution_service.submit(approval_id, authorized=_h1_authorized.get())


# --- Config Loading ---

EXPECTED_VERSION = "1.3-draft"


def _get_allowed_symbols(rules: dict | None = None) -> list[str]:
    """Return the current allowlist from paper-trading-rules.yaml.

    This is the SINGLE SOURCE OF TRUTH for symbol allowlisting (Phase H2).
    All gates, preflight, quote/bars restrictions, and submit-time checks
    route through this function — no hardcoded duplicate exists.

    Args:
        rules: Optional pre-loaded rules dict (avoids re-reading YAML).

    Returns:
        List of uppercase symbol strings that are currently tradeable.
    """
    if rules is None:
        rules = load_rules()
    allowlist = rules.get("symbol_allowlist", {})
    allowed = allowlist.get("allow", [])
    return [s.upper().strip() for s in allowed if isinstance(s, str)]


def load_rules(path: Path | None = None) -> dict:
    """Load and validate paper-trading-rules.yaml.

    Returns the full parsed rules dict.
    Raises:
        FileNotFoundError — rules file missing
        ValueError — invalid version, enforced=true, or missing required fields
    """

    if yaml is None:
        raise ImportError("PyYAML is required (pip install pyyaml)")

    p = Path(path) if path else RULES_PATH

    if not p.exists():
        raise FileNotFoundError(f"Rules file not found: {p}")

    with open(p, "r", encoding="utf-8") as f:
        rules = yaml.safe_load(f)

    if not isinstance(rules, dict):
        raise ValueError(f"Rules file did not parse as a dict: {p}")

    # --- Version check ---
    version = rules.get("rules_version")
    if version != EXPECTED_VERSION:
        raise ValueError(
            f"Expected rules_version={EXPECTED_VERSION!r}, got {version!r}. "
            f"File may be stale or from a different phase."
        )

    # --- Enforced safety check (disabled for Phase 2D first paper order) ---
    # This block was a Phase 1 safety measure. Phase 2D is complete and
    # Chris explicitly authorized the first paper order (2026-06-02).
    # enforced=true is now valid for controlled paper-order submission.

    # --- Required top-level fields ---
    required_keys = [
        "max_position_notional",
        "max_risk_per_trade",
        "max_total_exposure",
        "max_trades_per_day",
        "loss_halts",
        "initial_stop_loss",
        "symbol_allowlist",
        "manual_approval",
        "order_endpoint_gate",
        "guard_state",
        "preflight",
        "logging",
        # Phase 19B/B4 (Gate I) — safe to require now that the live YAML has
        # carried these sections since 2026-08-10; see CHANGELOG.
        "symbol_sectors",
        "max_positions_per_sector",
    ]
    missing = [k for k in required_keys if k not in rules]
    if missing:
        raise ValueError(f"Missing required rule sections: {missing}")

    # --- Allowlist validation ---
    allowlist = rules.get("symbol_allowlist", {})
    if allowlist.get("mode") != "explicit_list":
        raise ValueError(
            f"symbol_allowlist mode must be 'explicit_list', "
            f"got {allowlist.get('mode')!r}"
        )
    allowed = allowlist.get("allow", [])
    if not isinstance(allowed, list) or len(allowed) == 0:
        raise ValueError("symbol_allowlist.allow must be a non-empty list")
    # Phase H2: YAML is the single source of truth for allowlist.
    # No hardcoded comparison — the YAML defines what is allowed.

    # --- Sector concentration validation (Gate I, Phase 19B/B4) ---
    sector_map = rules.get("symbol_sectors", {})
    if not isinstance(sector_map, dict):
        raise ValueError("symbol_sectors must be a mapping of symbol -> sector")
    unmapped = [s for s in allowed if s not in sector_map]
    if unmapped:
        raise ValueError(
            f"symbol_sectors is missing a mapping for allowlisted symbol(s): "
            f"{unmapped} — every allowlisted symbol must have a sector "
            f"(H2: no hardcoded duplicates, so this is checked at load time, "
            f"not assumed)"
        )
    max_per_sector = rules.get("max_positions_per_sector", {}).get("value")
    if not isinstance(max_per_sector, int) or max_per_sector <= 0:
        raise ValueError(
            f"max_positions_per_sector.value must be a positive int, "
            f"got {max_per_sector!r}"
        )

    # --- Numeric cap validation (sanity checks) ---
    notional = rules.get("max_position_notional", {}).get("value")
    risk = rules.get("max_risk_per_trade", {}).get("value")
    exposure = rules.get("max_total_exposure", {}).get("value")
    trades = rules.get("max_trades_per_day", {}).get("value")

    if not isinstance(notional, (int, float)) or notional <= 0:
        raise ValueError(f"max_position_notional.value must be > 0, got {notional}")
    if not isinstance(risk, (int, float)) or risk <= 0:
        raise ValueError(f"max_risk_per_trade.value must be > 0, got {risk}")
    if not isinstance(exposure, (int, float)) or exposure <= 0:
        raise ValueError(f"max_total_exposure.value must be > 0, got {exposure}")
    if not isinstance(trades, int) or trades <= 0:
        raise ValueError(f"max_trades_per_day.value must be > 0, got {trades}")

    # --- Stop loss params ---
    stop = rules.get("initial_stop_loss", {})
    atr_mult = stop.get("atr_multiplier")
    atr_period = stop.get("atr_period")
    floor_pct = stop.get("absolute_floor_percent")

    if atr_mult != 2:
        raise ValueError(f"initial_stop_loss.atr_multiplier must be 2, got {atr_mult}")
    if atr_period != 14:
        raise ValueError(f"initial_stop_loss.atr_period must be 14, got {atr_period}")
    if floor_pct != 5:
        raise ValueError(
            f"initial_stop_loss.absolute_floor_percent must be 5, got {floor_pct}"
        )

    # --- Manual approval ---
    ma = rules.get("manual_approval", {})
    if ma.get("enabled") is not True:
        raise ValueError("manual_approval.enabled must be True")
    if ma.get("timeout_seconds") != 300:
        raise ValueError(
            f"manual_approval.timeout_seconds must be 300, "
            f"got {ma.get('timeout_seconds')}"
        )

    # --- Preflight ---
    pf = rules.get("preflight", {})
    if pf.get("strict_mode") is not True:
        raise ValueError("preflight.strict_mode must be True")
    if pf.get("response_type") != "validation_results_only":
        raise ValueError(
            f"preflight.response_type must be 'validation_results_only', "
            f"got {pf.get('response_type')!r}"
        )

    # --- Guard state ---
    gs = rules.get("guard_state", {})
    if not gs.get("file"):
        raise ValueError("guard_state.file must be set")

    # --- Logging ---
    lg = rules.get("logging", {})
    if not lg.get("file"):
        raise ValueError("logging.file must be set")

    return rules


def get_rules_path() -> Path:
    """Return the resolved rules file path."""
    return RULES_PATH.resolve()


# --- CLI Self-Test ---

def _run_step2_tests() -> None:
    from trading_agent.checkpoints import run
    run("_run_step2_tests")


def _run_step3_tests() -> None:
    from trading_agent.checkpoints import run
    run("_run_step3_tests")


def _run_step4_tests() -> None:
    from trading_agent.checkpoints import run
    run("_run_step4_tests")


def _run_step5_tests() -> None:
    from trading_agent.checkpoints import run
    run("_run_step5_tests")


def _run_step6_tests() -> None:
    from trading_agent.checkpoints import run
    run("_run_step6_tests")


def _run_step7a_tests() -> None:
    from trading_agent.checkpoints import run
    run("_run_step7a_tests")


def _run_step2c_tests() -> None:
    from trading_agent.checkpoints import run
    run("_run_step2c_tests")


def _run_self_test() -> None:
    from trading_agent.checkpoints import run
    run("_run_self_test")


# --- Phase 2E: Startup reconciliation — runs at module import time ---
# Reconcile submitted approvals from disk + events + records
# so submitted approvals survive bridge restarts.
_reconcile_summary = {}  # Populated by explicit application startup, never import.

# Phase H1: Mark startup as complete — from here on, protected file
# writes require H1 token authorization through the bridge.
h1_startup_done()


# ═══════════════════════════════════════════════════════════════════════════════
# Phase H4 — Guardian Alerts (read-only)
# ═══════════════════════════════════════════════════════════════════════════════

# ---------------------------------------------------------------------------
# H4.1 — US-domiciled ETF blocklist
#
# PRIIPs/KID is law, not policy. A US-domiciled ETF may not be distributed to
# an EU retail investor because US issuers do not produce a Key Information
# Document, and IBKR enforces this independently of this guard.
#
# The baseline below is therefore a REGULATORY FLOOR, not a tunable parameter.
# The rules YAML may EXTEND it (see `us_etf_blocklist.symbols`) but can never
# shrink it: the effective blocklist is `baseline | yaml`. This is deliberate.
# A pure YAML replacement would create a fail-open path where deleting one
# line silently legalizes an instrument the account is not permitted to hold.
#
# On H2 (single source of truth): the YAML is the sole source for blocklist
# *extensions*, which is the mutable part. The floor stays in code because it
# encodes a legal constraint rather than a risk preference.
# ---------------------------------------------------------------------------
_US_ETF_REGULATORY_BASELINE: frozenset = frozenset({
    "SPY", "QQQ", "IVV", "VOO", "VTI", "VEA", "VWO", "BND",
    "AGG", "GLD", "SLV", "IWM", "DIA", "EEM", "EFA", "XLF",
    "XLE", "XLK", "XLV", "XLY", "XLI", "XLP", "XLB", "XLU",
    "TLT", "LQD", "HYG", "VNQ", "ARKK", "SMH", "SOXX", "IBB",
    "TQQQ", "SQQQ", "UPRO", "SPXU", "SOXL", "FAS", "FAZ",
})

# Backward-compatible alias — existing callers and tests reference this name.
_US_ETF_BLOCKLIST: frozenset = _US_ETF_REGULATORY_BASELINE


def _load_us_etf_blocklist(rules: dict | None = None) -> frozenset:
    """Return the effective US ETF blocklist: regulatory baseline | YAML.

    The YAML section is optional. Its absence, emptiness, or malformation all
    resolve to the baseline alone — never to an empty set — so no
    configuration error can weaken the H4.1 block.

    Args:
        rules: Already-loaded rules dict. If None, rules are loaded lazily so
            that callers running before `load_rules()` keep their ordering.
    """
    if rules is None:
        try:
            rules = load_rules()
        except Exception:
            rules = None

    extra: set = set()
    if isinstance(rules, dict):
        section = rules.get("us_etf_blocklist")
        if isinstance(section, dict):
            symbols = section.get("symbols")
            if isinstance(symbols, list):
                extra = {
                    str(s).upper().strip() for s in symbols
                    if isinstance(s, str) and str(s).strip()
                }

    return _US_ETF_REGULATORY_BASELINE | frozenset(extra)


def _reject_us_domiciled_etf(
    symbol: str, contract_provider=None, rules: dict | None = None,
) -> None:
    """Reject US-domiciled ETFs structurally for this EU paper account.

    Dual check:
    1. Symbol-level: match against the effective blocklist (always active).
    2. Contract-level (if provider available): secType=="ETF" on US exchange.

    Raises ValueError if the symbol is a US-domiciled ETF.
    """
    sym = symbol.upper().strip()

    # Check 1: effective blocklist (regulatory baseline | YAML extensions)
    if sym in _load_us_etf_blocklist(rules):
        raise ValueError(
            f"Symbol '{sym}' is a US-domiciled ETF — blocked for EU paper "
            f"account DUQ542875 under KID/PRIIPs regulation."
        )

    # Check 2: structural via contract lookup (if provider available)
    if contract_provider is not None:
        try:
            contract = contract_provider(sym)
            if isinstance(contract, dict):
                sec_type = contract.get("secType", "").upper()
                exchange = contract.get("exchange", "").upper()
                us_exchanges = {"SMART", "NASDAQ", "NYSE", "ARCA", "BATS",
                                "IEX", "NMS", "AMEX", "BEX", "CBOE"}
                if sec_type == "ETF" and any(ex in exchange for ex in us_exchanges):
                    raise ValueError(
                        f"Symbol '{sym}' resolved as ETF on US exchange "
                        f"({exchange}) — blocked for EU paper account."
                    )
        except ValueError:
            raise  # re-raise our own ValueError
        except Exception:
            pass  # contract lookup failed — fall through, rely on blocklist


def _fetch_exchange_rate(account_provider=None) -> float:
    """Fetch EUR/USD exchange rate with plausibility guard (H4.2).

    Returns float EUR/USD rate.

    Raises:
        ValueError: rate fetch failed or outside [0.8, 1.4] plausibility range.
    """
    if account_provider is not None:
        try:
            account = account_provider()
        except Exception as e:
            raise ValueError(
                f"EUR/USD fetch failed: account provider error: {e}"
            )
    else:
        try:
            account = fetch_account()
        except (RuntimeError, ValueError) as e:
            raise ValueError(
                f"EUR/USD fetch failed: bridge account endpoint error: {e}"
            )

    fx_raw = account.get("exchange_rate") if isinstance(account, dict) else None

    if fx_raw is None:
        raise ValueError(
            "EUR/USD rate unavailable: ExchangeRate tag missing from "
            "IBKR account data. Cannot compute USD sizing."
        )

    try:
        fx_rate = float(fx_raw)
    except (TypeError, ValueError):
        raise ValueError(
            f"EUR/USD rate unparseable: {fx_raw!r}. Cannot compute USD sizing."
        )

    if fx_rate < 0.8 or fx_rate > 1.4:
        raise ValueError(
            f"EUR/USD rate {fx_rate:.4f} outside plausibility range [0.80, 1.40]. "
            f"Refusing to compute USD sizing with implausible FX."
        )

    return fx_rate


def check_stop_breach(
    quote_provider=None,
    position_provider=None,
) -> list[dict]:
    """Check all active positions for stop-loss breaches (H4.3).

    Read-only: generates alerts, does NOT submit orders or auto-exit.

    For each active position:
    1. Find the associated stop from approval records / order_submitted events.
    2. Get live quote (bid for SELL stops, ask/close for BUY stops).
    3. Compare: if BUY and close <= stop → alert.

    Args:
        quote_provider: Callable(symbol) -> dict with close/bid/ask.
        position_provider: Callable() -> list of position dicts.

    Returns:
        List of breach alert dicts (empty if no breaches).
    """
    alerts: list[dict] = []

    # Get active positions from event ledger
    positions = _compute_positions_from_events()
    if not positions:
        return alerts

    for symbol, net_qty in positions.items():
        if net_qty <= 0:
            continue  # no long position

        # Find the most recent BUY order_submitted event for this symbol
        # that has a stop_price in its approval record
        stop_price = _find_active_stop(symbol)
        if stop_price is None:
            continue  # no stop recorded

        # Get live quote
        try:
            if quote_provider:
                quote = quote_provider(symbol)
            else:
                quote = fetch_quote(symbol)
        except Exception:
            continue  # can't get quote — skip, don't false-alert

        if not isinstance(quote, dict):
            continue

        close = quote.get("close") or quote.get("last") or 0.0
        if close <= 0:
            continue

        # Breach check: for a BUY position, stop is breached if close <= stop
        if close <= stop_price:
            alerts.append({
                "alert_type": "stop_breach",
                "symbol": symbol,
                "position_qty": net_qty,
                "stop_price": stop_price,
                "current_price": close,
                "breach_pct": round((stop_price - close) / stop_price * 100, 2),
                "severity": "high",
                "action_required": "Chris review — NO auto-exit",
            })

    return alerts


def _compute_positions_from_events() -> dict[str, int]:
    """Compute net positions from order_submitted events in guard-events.jsonl.

    Returns dict of symbol → net_qty (BUY +qty, SELL -qty).
    Ignores test artifacts and unconfirmed orders.
    """
    events = read_guard_events()
    submitted = [e for e in events
                 if e.get("event_type") == "order_submitted"]

    # Exclude unconfirmed orders
    unconfirmed_oids = {e.get("order_id") for e in events
                        if e.get("event_type") == "order_unconfirmed"}

    net: dict[str, int] = {}
    for e in submitted:
        oid = str(e.get("order_id", "")) if e.get("order_id") is not None else ""
        aid = e.get("approval_id", "")

        # Skip test artifacts
        if oid in _KNOWN_TEST_ORDER_IDS_POSITION or aid in _KNOWN_TEST_APPROVALS_POSITION:
            continue
        if oid in unconfirmed_oids:
            continue

        symbol = e.get("symbol", "").upper()
        if not symbol:
            continue
        action = (e.get("action") or "").upper()
        qty = int(e.get("totalQuantity", 0) or 0)
        if qty <= 0:
            continue  # qty=0 events are test placeholders
        if action == "BUY":
            net[symbol] = net.get(symbol, 0) + qty
        elif action == "SELL":
            net[symbol] = net.get(symbol, 0) - qty
        # Unknown action (None/empty) — skip, these are test artifacts

    return {s: q for s, q in net.items() if q > 0}


def read_approval_records(path: str | Path | None = None) -> list[dict]:
    """Read and parse all records from approval-records.jsonl.

    Mirrors read_guard_events()'s pattern exactly. Malformed lines are
    skipped rather than raising, matching every other reader of this file
    in guard.py (see reconcile_approvals_on_startup(), the submitted-approval
    scan below).

    Returns list of record dicts in file order. Returns empty list if the
    file does not exist.

    Bug fix (2026-08-27, Fable code review): this function did not exist at
    all -- _find_active_stop() called it anyway, immediately caught by its
    own bare `except Exception: pass`, so the stop-breach detector's primary
    lookup (approval records) silently always fell through to its secondary
    lookup (order_submitted events) instead of ever actually running. No
    open positions were affected while this went unnoticed (nothing to
    breach-check), but it would have silently degraded stop-breach alerting
    the first time it mattered.
    """
    log_path = Path(path) if path else APPROVAL_RECORDS_PATH
    if not log_path.exists():
        return []
    records = []
    for line in log_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return records


def _find_active_stop(symbol: str) -> float | None:
    """Find the most recent stop_price for an active BUY position.

    Searches:
    1. approval-records.jsonl for approved BUY proposals with stop_price.
    2. order_submitted events with stop_price in metadata.

    Returns stop_price float or None if not found.
    """
    sym = symbol.upper()

    # Check approval records
    try:
        records = read_approval_records()
        for rec in reversed(records):
            if rec.get("status") != "approved":
                continue
            proposal = rec.get("proposal", {})
            if proposal.get("symbol", "").upper() == sym:
                if proposal.get("action", "").upper() == "BUY":
                    # Bug fix (2026-08-27): stop_price lives under the
                    # record's "validation" subset, not "proposal" --
                    # create_approval_record()'s _ALLOWED_PROPOSAL_FIELDS
                    # never includes stop_price, so proposal.get("stop_price")
                    # was unconditionally None even once read_approval_records()
                    # itself was fixed to exist.
                    validation = rec.get("validation", {})
                    sp = validation.get("stop_price")
                    if sp is not None:
                        return float(sp)
    except Exception:
        pass

    # Check order_submitted events for stop_price in metadata
    events = read_guard_events()
    for e in reversed(events):
        if e.get("event_type") != "order_submitted":
            continue
        if e.get("symbol", "").upper() != sym:
            continue
        if e.get("action", "").upper() != "BUY":
            continue
        sp = e.get("stop_price")
        if sp is not None:
            return float(sp)

    return None


def check_kill_switch_watchdog(
    max_minutes: int = 10,
    rules: dict | None = None,
) -> list[dict]:
    """Check if kill switches have been true too long without an active trade cycle (H4.4).

    Read-only: generates alerts, does NOT disable switches or submit orders.

    Alert condition:
    - IBKR_ALLOW_ORDERS=true AND rules.enforced=true
    - AND no active approval cycle within the last max_minutes

    Args:
        max_minutes: Max allowed minutes before alert (default 10).
        rules: Pre-loaded rules dict.

    Returns:
        List of watchdog alert dicts (empty if no alert).
    """
    from datetime import datetime as dt, timezone as tz

    alerts: list[dict] = []

    if not _check_ibkr_allowed():
        return alerts

    if not _check_enforced(rules=rules):
        return alerts

    # Both kill switches are true — check for active trade cycle
    now_utc = dt.now(tz.utc)

    # Look for active/pending approvals within max_minutes
    has_active_cycle = False
    try:
        for aid, record in _active_approvals.items():
            status = record.get("status", "")
            if status in ("pending", "approved"):
                created_str = record.get("created_at", "")
                if created_str:
                    try:
                        created = dt.fromisoformat(created_str)
                        if created.tzinfo is None:
                            created = created.replace(tzinfo=tz.utc)
                        age_minutes = (now_utc - created).total_seconds() / 60.0
                        if age_minutes <= max_minutes + 5:
                            has_active_cycle = True
                            break
                    except (ValueError, TypeError):
                        pass
    except Exception:
        pass

    if not has_active_cycle:
        # Check guard state for last trade timestamp
        try:
            gs = load_guard_state()
            last_trade_str = gs.get("last_trade_utc", "")
            if last_trade_str:
                last_trade = dt.fromisoformat(last_trade_str)
                if last_trade.tzinfo is None:
                    last_trade = last_trade.replace(tzinfo=tz.utc)
                age_minutes = (now_utc - last_trade).total_seconds() / 60.0
                if age_minutes <= max_minutes + 5:
                    has_active_cycle = True
        except Exception:
            pass

    if not has_active_cycle:
        alerts.append({
            "alert_type": "kill_switch_watchdog",
            "severity": "medium",
            "detail": (
                f"Both kill switches (IBKR_ALLOW_ORDERS=true, "
                f"rules.enforced=true) have been active for >{max_minutes} "
                f"minutes with no active trade cycle detected. "
                f"Chris: consider rolling back if no trade is planned."
            ),
            "action_required": "Chris review — no auto-disable",
        })

    return alerts


# H4 helpers: grant monitor.py access to H4 check functions
# These are imported by monitor.py for the /monitor/alerts endpoint.
def _run_h4_stop_breach_check(quote_provider=None, position_provider=None) -> list[dict]:
    """Public entry point for H4 stop-breach check."""
    try:
        return check_stop_breach(quote_provider=quote_provider,
                                 position_provider=position_provider)
    except Exception:
        return []


def _run_h4_watchdog_check(max_minutes: int = 10, rules=None) -> list[dict]:
    """Public entry point for H4 kill-switch watchdog check."""
    try:
        return check_kill_switch_watchdog(max_minutes=max_minutes, rules=rules)
    except Exception:
        return []
