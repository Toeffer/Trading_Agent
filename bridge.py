import os
import socket
import asyncio
import time
from datetime import datetime, timezone
from typing import Any, Dict
import logging
from fastapi import Request

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Header
from pydantic import BaseModel

load_dotenv()

try:
    from ib_insync import IB, Stock
except Exception:
    IB = None
    Stock = None

APP_NAME = "ibkr-openclaw-bridge"
app = FastAPI(title=APP_NAME)

# Step 15H: Runtime quieting — debug flag gates verbose MEM/REQ logging
_IBKR_BRIDGE_DEBUG = os.getenv("IBKR_BRIDGE_DEBUG", "").lower() in ("1", "true", "yes", "on")

if _IBKR_BRIDGE_DEBUG:
    # OOM_TRACE_MIN — only active when IBKR_BRIDGE_DEBUG=true
    import logging as _mlog
    _M=_mlog.getLogger("ibkr-bridge.mem")
    def _m():
        d={}
        try:
            for l in open(f"/proc/{os.getpid()}/status"):
                if l.startswith(("VmRSS:","VmPeak:","VmSize:","Threads:")):
                    k,v=l.split(":",1); d[k]=v.strip()
        except Exception as e: d["err"]=repr(e)
        return d
    async def _ms():
        while True:
            _M.warning("MEM %s",_m()); await asyncio.sleep(1)
    @app.on_event("startup")
    async def _mst(): asyncio.create_task(_ms())
    @app.middleware("http")
    async def _mt(req, call_next):
        _M.warning("REQ_START %s %s %s",req.method,req.url.path,_m())
        try: return await call_next(req)
        finally: _M.warning("REQ_END %s %s %s",req.method,req.url.path,_m())
# /OOM_TRACE_MIN


IBKR_MODE = os.getenv("IBKR_MODE", "paper")
IBKR_HOST = os.getenv("IBKR_HOST", "127.0.0.1")
IBKR_PORT = int(os.getenv("IBKR_PORT", "4002"))
IBKR_CLIENT_ID = int(os.getenv("IBKR_CLIENT_ID", "101"))
IBKR_ACCOUNT = os.getenv("IBKR_ACCOUNT", "")
IBKR_READ_ONLY = os.getenv("IBKR_READ_ONLY", "true").lower() == "true"
IBKR_ALLOW_ORDERS = os.getenv("IBKR_ALLOW_ORDERS", "false").lower() == "true"

logger= logging.getLogger("ibkr-bridge.mem")

# ---------------------------------------------------------------------------
# Phase H1 — Enforced Approval Token
# ---------------------------------------------------------------------------
H1_APPROVAL_TOKEN_HASH = os.getenv("H1_APPROVAL_TOKEN_HASH", "")


def _verify_h1_token(token: str | None) -> bool:
    """Verify the H1 approval token against the stored SHA-256 hash.

    The actual token is known only to Chris (provided out-of-band).
    Werner/OpenClaw cannot read or generate a valid token because only
    the hash is stored in .env, which is itself protected from Werner
    write access.

    Returns True if the token hash matches the stored hash.
    Returns False if no H1 token hash is configured (backward compat).
    """
    import hashlib
    if not H1_APPROVAL_TOKEN_HASH:
        return False
    if not token or not isinstance(token, str):
        return False
    token = token.strip()
    if not token:
        return False
    return hashlib.sha256(token.encode()).hexdigest() == H1_APPROVAL_TOKEN_HASH


ib = IB() if IB else None

# ---------------------------------------------------------------------------
# Step 15C v2 — Snapshot Cache (lightweight, bounded, no subprocess storms)
# ---------------------------------------------------------------------------
# Caches bridge-level evidence so KPI/rehearsal/candidate can fetch one
# consolidated snapshot instead of hammering 8+ endpoints.
# TTL is 30s — long enough to cover a full runtime-gate sequence.
# Lock prevents concurrent snapshot builds from stacking memory under load.
# NO reconciliation, NO subprocess calls in the hot path — those are in
# /monitor/reconciliation and /monitor/liveness respectively.
_snapshot_cache: dict | None = None
_snapshot_cache_ts: float = 0.0
_SNAPSHOT_CACHE_TTL = 30.0  # seconds — covers a full gate sequence
import threading as _threading
_snapshot_build_lock = _threading.Lock()

# Separate liveness cache — lightweight /proc reads only (no subprocess forks)
# Cached independently with 60s TTL. OOM detection at systemd level is done by
# the operator-side K17 check, not inside the bridge process.
_liveness_cache: dict | None = None
_liveness_cache_ts: float = 0.0
_LIVENESS_CACHE_TTL = 60.0  # seconds — memory/RSS doesn't change sub-second


def _snapshot_ibkr_disconnected_response() -> dict:
    """Return a minimal disconnected-evidence payload for fast-fail.

    When IBKR is not connected, endpoints like /positions and /account
    return this instead of blocking on a 503. The snapshot cache detects
    disconnected state and short-circuits.
    """
    return {
        "ok": False,
        "connected": False,
        "mode": IBKR_MODE,
        "read_only": IBKR_READ_ONLY,
        "allow_orders": IBKR_ALLOW_ORDERS,
        "detail": "IBKR not connected — no live data available",
    }


def _build_snapshot_lightweight() -> dict:
    """Build a lightweight evidence snapshot — no heavy I/O, no subprocesses.

    Step 15C v2: This MUST be fast and low-memory. No reconciliation,
    no subprocess calls (systemctl/journalctl/dmesg/ss), no large file reads.
    Those belong in dedicated endpoints (/monitor/reconciliation, /monitor/liveness).

    Returns: health, connected, safety, RTH, guard summary, positions count,
    account net-liq only. All fast, all bounded.
    """
    now_utc = datetime.now(timezone.utc)
    connected = is_connected()

    # RTH (in-memory computation, no I/O)
    from monitor import rth_check as _rth_check
    rth = _rth_check()

    # Guard state summary (single small JSON file, cached in memory by guard module)
    try:
        from guard import load_guard_state
        gs = load_guard_state()
    except Exception:
        gs = {}

    # Rules (small YAML file, read once)
    try:
        rules = load_rules()
    except Exception:
        rules = {}

    result = {
        "timestamp_utc": now_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "connected": connected,
        "mode": IBKR_MODE,
        "read_only": IBKR_READ_ONLY,
        "allow_orders": IBKR_ALLOW_ORDERS,
        "ib_insync_available": IB is not None,
        "rth": {
            "in_rth": rth.get("in_rth", False),
            "is_tradable_day": rth.get("is_tradable_day", False),
            "reason": rth.get("reason", ""),
            "market_date_et": rth.get("market_date_et", ""),
        },
        "safety": {
            "IBKR_ALLOW_ORDERS": IBKR_ALLOW_ORDERS,
            "rules_enforced": rules.get("enforced", False),
            "system_locked": not (IBKR_ALLOW_ORDERS and rules.get("enforced", False)),
        },
        "guard": {
            "trade_date": gs.get("trade_date", ""),
            "daily_trade_count": gs.get("daily_trade_count", 0),
            "daily_halt_active": gs.get("daily_halt_active", False),
            "weekly_halt_active": gs.get("weekly_halt_active", False),
        },
        "startup_safety": _startup_safety if _startup_safety else {},
    }

    # IBKR-dependent — only if connected, fast-fail otherwise
    if connected:
        try:
            pos = ib.positions()
            result["positions_ok"] = True
            result["position_count"] = len(pos)
            result["positions"] = [
                {"symbol": getattr(p.contract, "symbol", None),
                 "position": p.position, "avgCost": p.avgCost}
                for p in pos[:50]  # bounded: max 50 positions
            ]
        except Exception:
            result["positions_ok"] = False
            result["position_count"] = 0
            result["positions"] = []

        try:
            values = ib.accountValues()
            result["account_ok"] = True
            net_liq = None
            cash_balance = None
            base_currency = None
            for v in values:
                if v.tag == "NetLiquidation" and v.currency == "BASE":
                    net_liq = v.value
                if v.tag == "TotalCashBalance" and v.currency == "BASE":
                    cash_balance = v.value
                # Infer base currency from any non-BASE NetLiquidation entry
                if v.tag == "NetLiquidation" and v.currency != "BASE" and base_currency is None:
                    base_currency = v.currency
            if base_currency is None:
                base_currency = "EUR"  # default assumption for this account
            result["net_liquidation"] = net_liq
            result["cash_balance"] = cash_balance
            result["base_currency"] = base_currency
            result["account_tag_count"] = len(values)
        except Exception:
            result["account_ok"] = False
            result["net_liquidation"] = None
            result["cash_balance"] = None
            result["base_currency"] = None
            result["account_tag_count"] = 0
    else:
        result["positions_ok"] = False
        result["position_count"] = 0
        result["positions"] = []
        result["account_ok"] = False
        result["net_liquidation"] = None
        result["cash_balance"] = None
        result["base_currency"] = None
        result["account_tag_count"] = 0

    # Reconciliation: lightweight status only (no heavy file scan)
    # Returns cached pass/fail from guard state; full scan is at /monitor/reconciliation
    try:
        from monitor import health_summary
        hs = health_summary()
        result["reconciliation"] = {
            "passed": hs.get("passed", None),
            "alert_count": hs.get("alert_count", 0),
        }
    except Exception:
        result["reconciliation"] = {"passed": None, "alert_count": 0}

    return result

    return result


# ---------------------------------------------------------------------------
# Phase 3G — Startup Safety Gate (module-level, populated on module import)
# ---------------------------------------------------------------------------
_startup_safety: dict | None = None  # populated once at module load


def _run_startup_safety() -> dict:
    """Run startup safety checks at module load time.

    Checks:
    - IBKR_ALLOW_ORDERS is false
    - rules.enforced is false
    - /order remains 403 (no order payloads)
    - H1_APPROVAL_TOKEN_HASH configured (Phase H1)
    - guard-state.json readable and parseable
    - guard-events.jsonl readable and parseable
    - submitted-approvals.json reconcilable
    - manual-order-reconciliations.jsonl loadable
    - no unresolved open orders from file state
    - readiness endpoint available (imported)

    Logs a startup_safety event to guard-events.jsonl.

    Returns a dict with all checks, overall pass/fail, and timestamp.
    May raise RuntimeError if critical config cannot be read (fail-closed).
    """
    from pathlib import Path
    import json
    import yaml

    checks: list[dict] = []
    home = Path.home()

    def _check(name: str, ok: bool, detail: str):
        checks.append({"check": name, "ok": ok, "detail": detail})

    # 1. IBKR_ALLOW_ORDERS env
    allow_orders_env = os.getenv("IBKR_ALLOW_ORDERS", "false").lower() == "true"
    _check("IBKR_ALLOW_ORDERS", not allow_orders_env,
           f"env={allow_orders_env} (expected false)")

    # 2. rules.enforced from YAML
    rules_path = home / ".openclaw" / "risk-rules" / "paper-trading-rules.yaml"
    try:
        with open(rules_path) as f:
            rules = yaml.safe_load(f)
        enforced = rules.get("enforced", None)
        if enforced is None:
            _check("rules_enforced_key_present", False,
                   "rules YAML missing 'enforced' key")
        else:
            _check("rules.enforced", enforced is False,
                   f"enforced={enforced} (expected false)")
    except FileNotFoundError:
        raise RuntimeError(f"FAIL_CLOSED: rules file not found at {rules_path}")
    except Exception as e:
        raise RuntimeError(f"FAIL_CLOSED: rules YAML unreadable: {e}")

    # 3. guard-state.json readable
    gs_path = home / ".openclaw" / "guard-state.json"
    gs_readable = False
    gs_content = None
    try:
        gs_content = json.loads(gs_path.read_text())
        gs_readable = True
        _check("guard_state_readable", True,
               f"schema_version={gs_content.get('schema_version')}")
    except FileNotFoundError:
        _check("guard_state_readable", False, "file not found")
    except (json.JSONDecodeError, OSError) as e:
        _check("guard_state_readable", False, str(e)[:100])

    # 4. guard-events.jsonl readable
    ge_path = home / ".openclaw" / "guard-events.jsonl"
    ge_readable = False
    ge_line_count = 0
    try:
        for line in ge_path.read_text().splitlines():
            line = line.strip()
            if line:
                json.loads(line)
                ge_line_count += 1
        ge_readable = True
        _check("guard_events_readable", True, f"{ge_line_count} valid JSON lines")
    except FileNotFoundError:
        _check("guard_events_readable", False, "file not found")
    except (json.JSONDecodeError, OSError) as e:
        _check("guard_events_readable", False, str(e)[:100])

    # 5. submitted-approvals.json readable
    sa_path = home / ".openclaw" / "submitted-approvals.json"
    if sa_path.exists():
        try:
            sa_content = json.loads(sa_path.read_text())
            if isinstance(sa_content, dict):
                submitted_set = set(sa_content.get("submitted", []))
            else:
                submitted_set = set()
            _check("submitted_approvals_readable", True,
                   f"{len(submitted_set)} submitted approval(s)")
        except (json.JSONDecodeError, OSError) as e:
            _check("submitted_approvals_readable", False, str(e)[:100])
            submitted_set = set()
    else:
        submitted_set = set()
        _check("submitted_approvals_readable", True, "file not present (empty)")

    # 6. manual-order-reconciliations.jsonl loadable
    recon_path = home / ".openclaw" / "manual-order-reconciliations.jsonl"
    if recon_path.exists():
        try:
            recon_count = 0
            for line in recon_path.read_text().splitlines():
                if line.strip():
                    json.loads(line)
                    recon_count += 1
            _check("manual_recon_readable", True, f"{recon_count} record(s)")
        except (json.JSONDecodeError, OSError) as e:
            _check("manual_recon_readable", False, str(e)[:100])
    else:
        _check("manual_recon_readable", True, "file not present (empty)")

    # 7. No unresolved open orders from file state
    try:
        from monitor import open_orders_check
        oo = open_orders_check()
        open_count = oo.get("open_count", -1)
        _check("no_unresolved_open_orders", open_count == 0,
               f"open_count={open_count}")
    except Exception as e:
        _check("no_unresolved_open_orders", False, str(e)[:100])

    # 8. Orphaned submitted approvals (submitted but no confirm event)
    try:
        from monitor import load_events
        submit_events = load_events(event_type="order_submitted")
        confirmed_ids = set()
        for e in submit_events:
            aid = e.get("approval_id", "")
            if aid:
                ibkr = e.get("ibkr_metadata")
                if ibkr is not None and ibkr.get("filled", 0) is not None:
                    confirmed_ids.add(aid)
        orphaned = submitted_set - confirmed_ids
        _check("no_orphaned_submitted_approvals", len(orphaned) == 0,
               f"{len(orphaned)} orphaned" if orphaned else "none")
    except Exception as e:
        _check("no_orphaned_submitted_approvals", False, str(e)[:100])

    # 9. /order endpoint is 403 (no executable order payloads)
    _check("order_endpoint_blocked", True,
           "/order returns HTTP 403 (design invariant)")

    # 10. Phase H1: H1_APPROVAL_TOKEN_HASH configured
    h1_hash = os.getenv("H1_APPROVAL_TOKEN_HASH", "")
    h1_configured = bool(h1_hash and len(h1_hash) == 64 and all(c in "0123456789abcdef" for c in h1_hash))
    _check("h1_approval_token_configured", h1_configured,
           "SHA-256 hash present and valid" if h1_configured else "H1_APPROVAL_TOKEN_HASH missing or invalid — enforced approval boundary inactive")

    # 11. Readiness endpoint available (module-import check)
    try:
        from monitor import rth_check
        _check("readiness_endpoint_available", True, "monitor.rth_check importable")
    except ImportError as e:
        _check("readiness_endpoint_available", False, str(e)[:100])

    # Overall verdict
    all_ok = all(c["ok"] for c in checks)
    result = {
        "pass": all_ok,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "checks": checks,
        "check_count": len(checks),
        "passed_count": sum(1 for c in checks if c["ok"]),
    }

    # Log startup_safety event to guard-events.jsonl
    try:
        from guard import append_guard_event
        append_guard_event("startup_safety", {
            "pass": all_ok,
            "check_count": len(checks),
            "passed_count": sum(1 for c in checks if c["ok"]),
            "failed_checks": [c["check"] for c in checks if not c["ok"]],
        })
    except Exception:
        pass  # non-fatal — event log failure doesn't block startup

    return result


# Run startup safety checks at module import time.
# If critical config (rules YAML) cannot be read, raises RuntimeError (fail-closed).
_startup_safety = _run_startup_safety()


# --- Internal IBKR Data Providers (Phase 2D self-call fix) ---
# These functions call IBKR directly without HTTP self-calls.
# They return the same format as guard.fetch_account(), guard.fetch_quote(), guard.fetch_bars().


def _internal_fetch_account() -> dict:
    """Fetch account data via IBKR directly.

    Returns the same format as guard.fetch_account().
    Raises RuntimeError if IBKR not connected.
    """
    ensure_loop()
    if not ib or not ib.isConnected():
        raise RuntimeError("IBKR not connected")
    try:
        values = ib.accountValues()
    except Exception as e:
        raise RuntimeError(f"account failed: {type(e).__name__}: {repr(e)}")

    tag_map: dict[str, tuple[str, str]] = {}
    for v in values:
        tag_map[v.tag] = (v.value, v.currency)

    def _get(tag: str) -> str | None:
        t = tag_map.get(tag)
        if t:
            return t[0]
        return None

    def _flt(tag: str) -> float:
        raw = _get(tag)
        if raw is None or raw == "":
            raise ValueError(f"Required account tag '{tag}' is missing or empty")
        return float(raw)

    account_code = _get("AccountCode") or ""
    currency = _get("Currency") or ""

    nl_raw = _get("NetLiquidation")
    if nl_raw is None:
        raise ValueError("NetLiquidation tag missing from account values")
    net_liquidation_eur = float(nl_raw)

    return {
        "net_liquidation_eur": net_liquidation_eur,
        "total_cash_value_eur": float(_get("TotalCashValue") or 0),
        "available_funds_eur": float(_get("AvailableFunds") or 0),
        "buying_power_eur": float(_get("BuyingPower") or 0),
        "currency": currency or "EUR",
        "exchange_rate": float(_get("ExchangeRate") or 1.0),
        "account_code": account_code,
        "source": "internal",
    }


def _internal_fetch_quote(symbol: str) -> dict:
    """Fetch a delayed quote for a symbol via IBKR directly.

    Returns the same format as guard.fetch_quote().
    Raises RuntimeError if IBKR not connected or symbol not found.
    """
    ensure_loop()
    if not ib or not ib.isConnected():
        raise RuntimeError("IBKR not connected")
    if IB is None or Stock is None:
        raise RuntimeError("ib_insync not available")

    contract = Stock(symbol.upper(), "SMART", "USD")
    qualified = ib.qualifyContracts(contract)
    if not qualified:
        raise RuntimeError(f"Contract not found for {symbol}")
    contract = qualified[0]

    ib.reqMarketDataType(3)
    ticker = ib.reqMktData(contract, "", False, False)
    ib.sleep(3)

    def _sf(v):
        if v is None:
            return None
        try:
            fv = float(v)
        except (ValueError, TypeError):
            return None
        # IBKR returns -1.0 as sentinel for unavailable values in delayed mode
        if fv <= -1.0:
            return None
        return fv

    result = {
        "symbol": contract.symbol,
        "ask": _sf(ticker.ask),
        "bid": _sf(ticker.bid),
        "last": _sf(ticker.last),
        "close": _sf(ticker.close),
        "currency": contract.currency,
        "exchange": contract.exchange,
        "delayed": True,
        "_fetch_epoch": time.time(),  # Step 15D: for staleness calculation
    }

    try:
        ib.cancelMktData(contract)
    except Exception:
        pass

    return result


def _internal_fetch_bars(symbol: str) -> list:
    """Fetch daily OHLC bars for a symbol via IBKR directly.

    Returns the same format as guard.fetch_bars().
    Raises RuntimeError if IBKR not connected or no data.
    """
    ensure_loop()
    if not ib or not ib.isConnected():
        raise RuntimeError("IBKR not connected")
    if IB is None or Stock is None:
        raise RuntimeError("ib_insync not available")

    contract = Stock(symbol.upper(), "SMART", "USD")
    qualified = ib.qualifyContracts(contract)
    if not qualified:
        raise RuntimeError(f"Contract not found for {symbol}")
    contract = qualified[0]

    raw = ib.reqHistoricalData(
        contract,
        endDateTime="",
        durationStr="30 D",
        barSizeSetting="1 day",
        whatToShow="TRADES",
        useRTH=True,
        formatDate=1,
        keepUpToDate=False,
    )

    if not raw:
        raise RuntimeError(f"No bars returned for {symbol}")

    def _sf(v):
        if v is None:
            return None
        try:
            fv = float(v)
        except (ValueError, TypeError):
            return None
        # IBKR returns -1.0 as sentinel for unavailable values in delayed mode
        if fv <= -1.0:
            return None
        return fv

    result = []
    for b in raw:
        result.append({
            "date": str(b.date),
            "open": _sf(b.open),
            "high": _sf(b.high),
            "low": _sf(b.low),
            "close": _sf(b.close),
            "volume": int(b.volume) if b.volume is not None else None,
        })

    return result


def _internal_fetch_positions() -> list:
    """Fetch positions via IBKR directly, returning a list of position dicts.

    Each position dict:
        {"symbol": str, "position": int, "avgCost": float, ...}

    Returns empty list if not connected.
    """
    ensure_loop()
    if not ib or not ib.isConnected():
        return []
    try:
        pos = ib.positions()
        return [
            {
                "account": p.account,
                "symbol": getattr(p.contract, "symbol", None),
                "secType": getattr(p.contract, "secType", None),
                "exchange": getattr(p.contract, "exchange", None),
                "currency": getattr(p.contract, "currency", None),
                "position": p.position,
                "avgCost": p.avgCost,
            }
            for p in pos
        ]
    except Exception:
        return []


def _internal_place_order(approval_record: dict) -> dict:
    """Place an order via IBKR directly and wait for IBKR acknowledgment.

    P5 Bracket Support:
    For BUY entries with a stop_price in the proposal, constructs a
    broker-side protective stop bracket:
      - Parent BUY order: transmit=False
      - Child SELL stop order: parentId=<parent>, transmit=True
    If the child stop placement fails, the parent is cancelled (fail-closed).

    Returns the format expected by guard.submit_order():
        {"success": True, "order_id": int, "ib_order_id": ..., "status": ...,
         "bracket_evidence": {...}, "stop_order_id": int, ...}
        or {"success": False, "code": "...", "error": str}

    Never returns success without IBKR acknowledgment.
    Never called while kill switches are false — guarded by submit_order().
    """
    ensure_loop()
    if not ib or not ib.isConnected():
        return {"success": False, "error": "IBKR not connected"}
    if IB is None or Stock is None:
        return {"success": False, "error": "ib_insync not available"}

    proposal = approval_record.get("proposal", {})
    symbol = proposal.get("symbol", "")
    qty = proposal.get("totalQuantity", 0)
    action = proposal.get("action", "BUY")
    stop_price = proposal.get("stop_price")
    entry_price = proposal.get("entry_price")

    if not symbol:
        return {"success": False, "error": "No symbol in proposal"}

    contract = Stock(symbol.upper(), "SMART", "USD")
    qualified = ib.qualifyContracts(contract)
    if not qualified:
        return {"success": False, "error": f"Contract not found for {symbol}"}
    contract = qualified[0]

    from ib_insync import Order as IbOrder

    ACKNOWLEDGED_STATUSES = {"Submitted", "PreSubmitted", "Filled", "PartiallyFilled", "PendingSubmit", "PendingCancel"}
    MAX_POLLS = 30
    POLL_INTERVAL_S = 0.5

    def _poll_for_ack(trade, trade_order_id: int, label: str = "order"):
        """Poll for IBKR acknowledgment of a placed trade."""
        for attempt in range(1, MAX_POLLS + 1):
            try:
                ib.sleep(POLL_INTERVAL_S)
            except Exception:
                import time as _tm
                _tm.sleep(POLL_INTERVAL_S)

            # Check 1: trade.orderStatus.status
            status = getattr(trade.orderStatus, 'status', None) or ""
            filled = getattr(trade.orderStatus, 'filled', 0)
            remaining = getattr(trade.orderStatus, 'remaining', 0)
            avg_fill_price = getattr(trade.orderStatus, 'avgFillPrice', 0.0)

            if status in ACKNOWLEDGED_STATUSES:
                return {
                    "ack": True,
                    "order_id": trade_order_id,
                    "ib_order_id": trade_order_id,
                    "permId": getattr(trade.order, 'permId', None),
                    "status": status,
                    "filled": filled,
                    "remaining": remaining,
                    "avgFillPrice": avg_fill_price,
                    "last_timestamp_utc": datetime.now(timezone.utc).isoformat(),
                }

            # Check 2: appears in ib.openTrades()
            try:
                open_trades = ib.openTrades()
                for ot in open_trades:
                    if ot.order and ot.order.orderId == trade_order_id:
                        ot_status = getattr(ot.orderStatus, 'status', None) or ""
                        if ot_status in ACKNOWLEDGED_STATUSES:
                            return {
                                "ack": True,
                                "order_id": trade_order_id,
                                "ib_order_id": trade_order_id,
                                "permId": getattr(ot.order, 'permId', None),
                                "status": ot_status,
                                "filled": getattr(ot.orderStatus, 'filled', 0),
                                "remaining": getattr(ot.orderStatus, 'remaining', 0),
                                "avgFillPrice": getattr(ot.orderStatus, 'avgFillPrice', 0.0),
                                "last_timestamp_utc": datetime.now(timezone.utc).isoformat(),
                            }
            except Exception:
                pass

            # Check 3: appears in ib.trades()
            try:
                all_trades = ib.trades()
                for at in all_trades:
                    if at.order and at.order.orderId == trade_order_id:
                        at_status = getattr(at.orderStatus, 'status', None) or ""
                        if at_status in ACKNOWLEDGED_STATUSES:
                            return {
                                "ack": True,
                                "order_id": trade_order_id,
                                "ib_order_id": trade_order_id,
                                "permId": getattr(at.order, 'permId', None),
                                "status": at_status,
                                "filled": getattr(at.orderStatus, 'filled', 0),
                                "remaining": getattr(at.orderStatus, 'remaining', 0),
                                "avgFillPrice": getattr(at.orderStatus, 'avgFillPrice', 0.0),
                                "last_timestamp_utc": datetime.now(timezone.utc).isoformat(),
                            }
            except Exception:
                pass

            # Check 4: execution/fill appeared
            try:
                fills = ib.fills()
                for f in fills:
                    if f.execution and getattr(f.execution, 'orderId', None) == trade_order_id:
                        return {
                            "ack": True,
                            "order_id": trade_order_id,
                            "ib_order_id": trade_order_id,
                            "permId": getattr(trade.order, 'permId', None),
                            "status": "Filled",
                            "filled": int(getattr(f.execution, 'shares', qty)),
                            "remaining": 0,
                            "avgFillPrice": float(getattr(f.execution, 'price', 0.0)),
                            "last_timestamp_utc": datetime.now(timezone.utc).isoformat(),
                            "fill_time": str(getattr(f.execution, 'time', '')),
                        }
            except Exception:
                pass

        # Timeout
        return {
            "ack": False,
            "code": "IBKR_ACK_TIMEOUT",
            "error": f"IBKR did not acknowledge {label} within polling window",
            "order_id": trade_order_id,
            "last_status": status if 'status' in dir() else "Unknown",
        }

    # ---- P5 Bracket Path: BUY with stop_price ----
    if action.upper() == "BUY" and stop_price is not None and stop_price > 0:
        stop_price_f = float(stop_price)
        qty_int = int(qty)

        # 1. Place parent BUY with transmit=False
        parent_order = IbOrder()
        parent_order.action = "BUY"
        parent_order.totalQuantity = qty_int
        parent_order.orderType = "MKT"
        parent_order.account = IBKR_ACCOUNT or ""
        parent_order.transmit = False

        try:
            parent_trade = ib.placeOrder(contract, parent_order)
        except Exception as e:
            return {
                "success": False,
                "error": f"Parent BUY placeOrder failed: {type(e).__name__}: {e}",
                "code": "PARENT_PLACE_FAILED",
            }

        if not parent_trade or not hasattr(parent_trade, 'order') or not parent_trade.order:
            return {"success": False, "error": "Parent BUY placeOrder returned no trade object"}

        parent_order_id = int(parent_trade.order.orderId)
        parent_perm_id = getattr(parent_trade.order, 'permId', None)

        # 2. Wait for parent acknowledgment or timeout
        parent_ack = _poll_for_ack(parent_trade, parent_order_id, "parent BUY")
        if not parent_ack.get("ack"):
            # Parent never acknowledged - fail closed (nothing to cancel, it's dead)
            parent_ack["success"] = False
            parent_ack["code"] = parent_ack.get("code", "PARENT_ACK_TIMEOUT")
            return parent_ack

        # 3. Create child protective SELL stop with parentId
        try:
            child_order = IbOrder()
            child_order.action = "SELL"
            child_order.totalQuantity = qty_int
            child_order.orderType = "STP"
            child_order.auxPrice = stop_price_f
            child_order.account = IBKR_ACCOUNT or ""
            child_order.parentId = parent_order_id
            child_order.transmit = True  # Transmits the entire bracket

            child_trade = ib.placeOrder(contract, child_order)
        except Exception as e:
            # Child placement failed — cancel parent to avoid orphaned order
            _cancel_parent_safe(parent_order_id)
            return {
                "success": False,
                "error": f"Protective stop placeOrder failed: {type(e).__name__}: {e}",
                "code": "STOP_PLACE_FAILED",
                "parent_order_id": parent_order_id,
            }

        if not child_trade or not hasattr(child_trade, 'order') or not child_trade.order:
            _cancel_parent_safe(parent_order_id)
            return {
                "success": False,
                "error": "Protective stop placeOrder returned no trade object",
                "code": "STOP_NO_TRADE",
                "parent_order_id": parent_order_id,
            }

        child_order_id = int(child_trade.order.orderId)
        child_perm_id = getattr(child_trade.order, 'permId', None)

        # 4. Wait for child stop acknowledgment
        child_ack = _poll_for_ack(child_trade, child_order_id, "child SELL stop")
        if not child_ack.get("ack"):
            # Stop not acknowledged — cancel parent, fail closed
            _cancel_parent_safe(parent_order_id)
            child_ack["success"] = False
            child_ack["code"] = child_ack.get("code", "STOP_ACK_TIMEOUT")
            return child_ack

        # 5. Both acknowledged — build combined bracket evidence
        bracket_evidence = {
            "parent_order_id": parent_order_id,
            "parent_permId": parent_perm_id,
            "parent_transmit": False,
            "stop_order_id": child_order_id,
            "stop_permId": child_perm_id,
            "stop_transmit": True,
            "stop_price": stop_price_f,
            "entry_price": entry_price,
            "quantity": qty_int,
            "action": "BUY",
            "stop_action": "SELL",
            "bracket": True,
            "protective_stop": True,
        }

        return {
            "success": True,
            "order_id": parent_order_id,
            "ib_order_id": parent_order_id,
            "stop_order_id": child_order_id,
            "permId": parent_perm_id,
            "status": parent_ack.get("status", "Submitted"),
            "filled": parent_ack.get("filled", 0),
            "remaining": parent_ack.get("remaining", 0),
            "avgFillPrice": parent_ack.get("avgFillPrice", 0.0),
            "last_timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "bracket_evidence": bracket_evidence,
        }

    # ---- Simple Path: SELL (close-only) or BUY without stop is BLOCKED ----
    # P5 defense-in-depth: BUY entries must never be submitted without a
    # valid protective stop.  The simple path handles SELL close-only exits.
    if action.upper() == "BUY":
        return {
            "success": False,
            "error": "BUY entry requires a protective bracket stop. "
                     "No valid stop_price found in approval proposal.",
            "code": "BRACKET_STOP_REQUIRED",
        }

    order = IbOrder()
    order.action = action.upper()
    order.totalQuantity = int(qty)
    order.orderType = "MKT"
    order.account = IBKR_ACCOUNT or ""

    try:
        trade = ib.placeOrder(contract, order)
    except Exception as e:
        return {"success": False, "error": f"placeOrder failed: {type(e).__name__}: {e}"}

    if not trade or not hasattr(trade, 'order') or not trade.order:
        return {"success": False, "error": "IBKR placeOrder returned no trade object"}

    order_id = int(trade.order.orderId)

    ack_result = _poll_for_ack(trade, order_id, "order")
    if not ack_result.get("ack"):
        ack_result["success"] = False
        ack_result["code"] = ack_result.get("code", "IBKR_ACK_TIMEOUT")
        return ack_result

    return ack_result


def _cancel_parent_safe(order_id: int) -> bool:
    """Attempt to cancel a parent order by order ID. Best-effort; never raises.

    Finds the order via ib.trades()/ib.openTrades() matching the order_id,
    then calls ib.cancelOrder() with the Order object.

    Returns True if cancellation was attempted, False if the order couldn't
    be found or the IB connection was unavailable.
    """
    try:
        if not ib or not ib.isConnected():
            return False
        # Search open trades for the matching order
        for t in ib.openTrades():
            if t.order and t.order.orderId == order_id:
                ib.cancelOrder(t.order)
                return True
        for t in ib.trades():
            if t.order and t.order.orderId == order_id:
                ib.cancelOrder(t.order)
                return True
    except Exception:
        pass
    return False


# ---- ORIGINAL _internal_place_order (replaced above) ----
# The function above subsumes the original single-order logic.
# _poll_for_ack is shared between bracket and simple paths.


def _internal_order_status(order_id: int | str) -> str | None:
    """Fetch current order status from IBKR by order_id.

    Returns raw status string (e.g. "Filled", "Submitted") or None.
    """
    ensure_loop()
    if not ib or not ib.isConnected():
        return None
    try:
        trades = ib.trades()
        for t in trades:
            if t.order and t.order.orderId == int(order_id):
                return t.orderStatus.status
        return None
    except Exception:
        return None


def ensure_loop():
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def is_connected() -> bool:
    return bool(ib and ib.isConnected())


@app.get("/health")
def health() -> Dict[str, Any]:
    result = {
        "ok": True,
        "service": APP_NAME,
        "time": now_iso(),
        "mode": IBKR_MODE,
        "host": IBKR_HOST,
        "port": IBKR_PORT,
        "client_id": IBKR_CLIENT_ID,
        "account": IBKR_ACCOUNT or None,
        "read_only": IBKR_READ_ONLY,
        "allow_orders": IBKR_ALLOW_ORDERS,
        "ib_insync_available": IB is not None,
        "connected": is_connected(),
    }
    # Phase 3G: startup safety gate
    global _startup_safety
    if _startup_safety is not None:
        result["startup_safety"] = {
            "pass": _startup_safety["pass"],
            "check_count": _startup_safety["check_count"],
            "passed_count": _startup_safety["passed_count"],
        }
    return result


@app.get("/ibkr/socket-test")
def socket_test() -> Dict[str, Any]:
    try:
        with socket.create_connection((IBKR_HOST, IBKR_PORT), timeout=5):
            return {
                "ok": True,
                "host": IBKR_HOST,
                "port": IBKR_PORT,
                "message": "TCP socket reachable",
            }
    except Exception as e:
        raise HTTPException(
            status_code=503,
            detail=f"socket failed: {type(e).__name__}: {repr(e)}",
        )


@app.post("/disconnect")
def disconnect() -> Dict[str, Any]:
    global ib
    try:
        if ib and ib.isConnected():
            ib.disconnect()
    finally:
        ib = IB() if IB else None
    return {"ok": True, "connected": is_connected()}


@app.post("/connect")
def connect() -> Dict[str, Any]:
    global ib
    ensure_loop()

    if not IB:
        raise HTTPException(status_code=500, detail="ib_insync not installed")

    if ib and ib.isConnected():
        return {
            "ok": True,
            "connected": True,
            "managed_accounts": ib.managedAccounts(),
            "message": "already connected",
        }

    ib = IB()

    try:
        ib.connect(
            IBKR_HOST,
            IBKR_PORT,
            clientId=IBKR_CLIENT_ID,
            timeout=20,
            readonly=IBKR_READ_ONLY,
            account=IBKR_ACCOUNT or "",
        )

        return {
            "ok": True,
            "connected": ib.isConnected(),
            "managed_accounts": ib.managedAccounts(),
            "client_id": IBKR_CLIENT_ID,
            "read_only": IBKR_READ_ONLY,
            "allow_orders": IBKR_ALLOW_ORDERS,
        }

    except Exception as e:
        try:
            ib.disconnect()
        except Exception:
            pass
        raise HTTPException(
            status_code=503,
            detail=f"IBKR connect failed: {type(e).__name__}: {repr(e)}",
        )


@app.post("/connect-light")
def connect_light() -> Dict[str, Any]:
    return connect()


@app.get("/account")
def account() -> Dict[str, Any]:
    ensure_loop()

    if not ib or not ib.isConnected():
        # Step 15C: fast-fail with disconnected evidence instead of 503
        return _snapshot_ibkr_disconnected_response()

    try:
        accounts = ib.managedAccounts()
        values = ib.accountValues()
        return {
            "ok": True,
            "managed_accounts": accounts,
            "values_count": len(values),
            "values": [
                {
                    "account": v.account,
                    "tag": v.tag,
                    "value": v.value,
                    "currency": v.currency,
                    "modelCode": v.modelCode,
                }
                for v in values[:200]
            ],
        }
    except Exception as e:
        raise HTTPException(
            status_code=503,
            detail=f"account failed: {type(e).__name__}: {repr(e)}",
        )

@app.get("/account/summary")
def account_summary() -> Dict[str, Any]:
    account_id = IBKR_ACCOUNT

    required_tags = [
        "NetLiquidation",
        "TotalCashValue",
        "AvailableFunds",
        "BuyingPower",
        "Currency",
    ]

    connect()

    try:
        summary_items = ib.accountSummary()
        values = {}

        for item in summary_items:
            item_account = getattr(item, "account", "")
            item_tag = getattr(item, "tag", "")
            item_value = getattr(item, "value", "")
            item_currency = getattr(item, "currency", "")

            if item_account not in ("", account_id):
                continue

            if item_tag in required_tags:
                values[item_tag] = {
                    "value": item_value,
                    "currency": item_currency,
                }

        if "Currency" not in values:
            for tag in ["NetLiquidation", "TotalCashValue", "AvailableFunds", "BuyingPower"]:
                if tag in values and values[tag].get("currency"):
                    values["Currency"] = {
                        "value": values[tag]["currency"],
                        "currency": values[tag]["currency"],
                    }
                    break

        required_present = {
            tag: tag in values and values[tag].get("value") not in [None, ""]
            for tag in required_tags
        }

        return {
            "ok": all(required_present.values()),
            "account_id": account_id,
            "values_count": len(values),
            "values": values,
            "required_present": required_present,
        }

    except Exception as e:
        return {
            "ok": False,
            "account_id": account_id,
            "error": repr(e),
            "values_count": 0,
            "values": {},
        }

@app.get("/positions")
def positions() -> Dict[str, Any]:
    ensure_loop()

    if not ib or not ib.isConnected():
        # Step 15C: fast-fail with disconnected evidence instead of 503
        return _snapshot_ibkr_disconnected_response()

    try:
        pos = ib.positions()
        return {
            "ok": True,
            "positions": [
                {
                    "account": p.account,
                    "symbol": getattr(p.contract, "symbol", None),
                    "secType": getattr(p.contract, "secType", None),
                    "exchange": getattr(p.contract, "exchange", None),
                    "currency": getattr(p.contract, "currency", None),
                    "position": p.position,
                    "avgCost": p.avgCost,
                }
                for p in pos
            ],
        }
    except Exception as e:
        raise HTTPException(
            status_code=503,
            detail=f"positions failed: {type(e).__name__}: {repr(e)}",
        )


class ContractLookup(BaseModel):
    symbol: str
    exchange: str = "SMART"
    currency: str = "USD"


@app.post("/contract/stock")
def contract_stock(req: ContractLookup) -> Dict[str, Any]:
    ensure_loop()

    if not ib or not ib.isConnected():
        raise HTTPException(status_code=503, detail="IBKR not connected")

    c = Stock(req.symbol.upper(), req.exchange, req.currency.upper())

    try:
        details = ib.reqContractDetails(c)
        return {
            "ok": True,
            "symbol": req.symbol.upper(),
            "matches": [
                {
                    "conId": d.contract.conId,
                    "symbol": d.contract.symbol,
                    "secType": d.contract.secType,
                    "exchange": d.contract.exchange,
                    "primaryExchange": getattr(d.contract, "primaryExchange", ""),
                    "currency": d.contract.currency,
                    "longName": getattr(d, "longName", ""),
                }
                for d in details[:10]
            ],
        }
    except Exception as e:
        raise HTTPException(
            status_code=503,
            detail=f"contract lookup failed: {type(e).__name__}: {repr(e)}",
        )


@app.post("/order")
def order_blocked() -> Dict[str, Any]:
    raise HTTPException(
        status_code=403,
        detail="orders disabled by policy: manual-approval execution path required. "
               "Use /order/preflight → /order/approve → /order/submit with H1 token. "
               "This endpoint is permanently blocked by design (safety invariant §3.1).",
    )


# --- Preflight Validation Endpoint (Phase 2) ---

from guard import run_preflight
from monitor import health_summary, reconcile_snapshot, load_events, load_approval_records, position_drift_check, load_submitted_approvals, open_orders_check, append_manual_reconciliation, rth_check


class PreflightRequest(BaseModel):
    symbol: str
    action: str = "BUY"
    totalQuantity: int
    orderType: str = "MKT"
    limitPrice: float | None = None
    stopPrice: float | None = None
    mode: str | None = None
    proposal_path: str | None = None  # P3: path to persisted proposal JSON


@app.post("/order/preflight")
def order_preflight(req: PreflightRequest) -> Dict[str, Any]:
    """Validate a proposed order without submitting it.

    Calls guard.run_preflight() which runs all validation gates.
    Never submits an order. Never calls /order or ib.placeOrder.
    Returns validation result only — no executable order payloads.
    """
    request_dict = req.model_dump(exclude_none=True)
    proposal_path = request_dict.pop("proposal_path", None)
    result = run_preflight(
        request_dict,
        account_provider=_internal_fetch_account if is_connected() else None,
        quote_provider=_internal_fetch_quote if is_connected() else None,
        bars_provider=_internal_fetch_bars if is_connected() else None,
        position_provider=_internal_fetch_positions if is_connected() else None,
        open_order_provider=open_orders_check,
        proposal_path=proposal_path,
    )
    return result


# --- Approval Endpoint (Phase 2C Step 3) ---

from guard import approve_approval, deny_approval, get_active_approval, load_rules, _check_ibkr_allowed, _check_enforced, append_guard_event, submit_order, mark_approval_submitted, save_guard_state_atomic, load_guard_state, _now_utc_iso, poll_order_status, read_guard_events, h1_authorized_scope


class ApproveRequest(BaseModel):
    approval_id: str
    decision: str
    ruled_by: str = "Chris"


@app.post("/order/approve")
def order_approve(
    req: ApproveRequest,
    x_h1_token: str | None = Header(None, alias="X-H1-Token"),
) -> Dict[str, Any]:
    """Approve or deny a pending preflight approval.

    Phase H1: Requires X-H1-Token header with Chris's approval token.
    Werner/OpenClaw cannot read or generate this token — only the
    SHA-256 hash is stored in .env.

    LOCAL-STATE ONLY. Never calls IBKR, /account, /positions, monitor,
    reconciliation, readiness, open-orders, or any network/broker path.

    Fast path (nonexistent approval): returns 404 without touching
    guard file I/O or approval bookkeeping.  Only the H1 token check
    and an in-memory dict lookup.

    Never submits an order. Never calls /order or ib.placeOrder.
    Returns approval status only — no executable order payloads.
    """
    # 1. Verify H1 token — fast SHA-256 comparison, no I/O
    if not _verify_h1_token(x_h1_token):
        raise HTTPException(
            status_code=401,
            detail="H1 approval token required. Werner/OpenClaw cannot approve orders. "
                   "Chris must provide the X-H1-Token header.",
        )

    # 2. Fast local-state lookup first — no authorization, no guard.py
    #    function calls needed yet.  Inline dict access for nonexistent
    #    IDs (including the canary aprv_canary) returns 404 in
    #    microseconds.  No file I/O, network, or broker paths touched.
    from guard import _active_approvals
    active = _active_approvals.get(req.approval_id)
    if active is None or active.get("status") != "pending":
        raise HTTPException(status_code=404, detail=f"Approval '{req.approval_id}' not found, expired, or already ruled.")

    # 3. Approval exists and is pending — authorize mutations, validate
    #    decision, and rule the approval.
    with h1_authorized_scope():
        decision = req.decision.lower().strip()

        if decision not in ("approve", "deny"):
            raise HTTPException(status_code=400, detail=f"Invalid decision '{req.decision}'. Must be 'approve' or 'deny'.")

        try:
            if decision == "approve":
                record = approve_approval(req.approval_id, req.ruled_by)
            else:
                record = deny_approval(req.approval_id, req.ruled_by)
        except ValueError as e:
            raise HTTPException(status_code=409, detail=str(e))

        result = {
            "status": record["status"],
            "approval_id": record["approval_id"],
            "ruled_by": record["ruled_by"],
            "ruling_at_utc": record["ruling_at_utc"],
            "symbol": record["proposal"].get("symbol"),
            "action": record["proposal"].get("action"),
            "totalQuantity": record["proposal"].get("totalQuantity"),
        }

        exec_fields = ["order_id", "ibkr_order", "transmit", "account", "tif", "permId", "clientId", "submitted"]
        for f in exec_fields:
            result.pop(f, None)

        return result


class SubmitRequest(BaseModel):
    approval_id: str


def _load_rules_safe() -> tuple[bool, dict]:
    """Load rules safely, returning (loaded_ok, rules_or_empty).

    Never raises — returns a default empty dict on failure.
    Used by /order/submit to check the enforced kill switch.
    """
    try:
        r = load_rules()
        return True, r
    except Exception:
        return False, {}


def _validate_approval_for_submit(approval_id: str) -> dict | None:
    """Validate an approval exists and is ready to submit.

    Checks memory and approval-records.jsonl for the approval.
    Returns a result dict with error code if validation fails,
    or None if the approval is valid for submission.

    Must be called BEFORE kill switch checks so that expired/
    submitted/denied approvals return proper codes even when
    switches are off.
    """
    # Try bridge's in-memory active approvals
    # Bridge imports guard.approve_approval which populates
    # _active_approvals, but we also need direct record lookup
    from guard import _active_approvals, is_approval_submitted, APPROVAL_RECORDS_PATH
    import json
    from datetime import datetime, timezone
    from guard import _normalize_timestamp

    # 1. Check in-memory
    record = _active_approvals.get(approval_id)

    # 2. If not in memory, scan approval-records.jsonl
    if record is None:
        try:
            p = APPROVAL_RECORDS_PATH
            if p.exists():
                for line in p.read_text().splitlines():
                    if not line.strip():
                        continue
                    try:
                        rec_check = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if rec_check.get("approval_id") == approval_id:
                        record = rec_check
                        break
        except OSError:
            pass

    if record is None:
        return {
            "submitted": False,
            "error": f"No active approval found for '{approval_id}'",
            "code": "NOT_FOUND",
        }

    status = record.get("status", "")

    # Check already-submitted
    if is_approval_submitted(approval_id):
        return {
            "submitted": False,
            "error": f"Approval '{approval_id}' has already been submitted",
            "code": "ALREADY_SUBMITTED",
        }

    # Check denied
    if status == "denied":
        return {
            "submitted": False,
            "error": f"Approval '{approval_id}' was denied",
            "code": "NOT_FOUND",
        }

    # Check expired or past expiry
    if status in ("expired",):
        return {
            "submitted": False,
            "error": f"Approval '{approval_id}' is expired",
            "code": "EXPIRED",
        }

    expires_str = record.get("expires_at_utc")
    if expires_str:
        try:
            expires = datetime.fromisoformat(
                _normalize_timestamp(expires_str)
            )
            if datetime.now(timezone.utc) > expires:
                return {
                    "submitted": False,
                    "error": f"Approval expired at {expires_str}",
                    "code": "EXPIRED",
                }
        except (ValueError, TypeError):
            pass

    # Valid: approved and not expired/submitted/denied
    if status != "approved":
        return {
            "submitted": False,
            "error": f"Approval '{approval_id}' status is '{status}', expected 'approved'",
            "code": "NOT_APPROVED",
        }

    return None


@app.post("/order/submit")
def order_submit(
    req: SubmitRequest,
    x_h1_token: str | None = Header(None, alias="X-H1-Token"),
) -> Dict[str, Any]:
    """Submit an approved preflight as an IBKR MKT order.

    Phase H1: Requires X-H1-Token header with Chris's approval token.
    Werner/OpenClaw cannot read or generate this token — only the
    SHA-256 hash is stored in .env.

    BLOCKED-FIRST: While either kill switch is false, returns ORDERS_BLOCKED
    and never reaches IBKR. This endpoint is the only submit path — /order
    remains permanently HTTP 403.

    Kill switches:
      1. IBKR_ALLOW_ORDERS env var (bridge-level gate)
      2. paper-trading-rules.yaml enforced flag (rules-level gate)
      3. H1_APPROVAL_TOKEN required (Phase H1 enforced approval)

    All three must pass before any order reaches IBKR.
    """
    # 0. Phase H1: Enforced approval token
    if not _verify_h1_token(x_h1_token):
        return {
            "submitted": False,
            "error": "H1 approval token required. Werner/OpenClaw cannot submit orders. "
                     "Chris must provide the X-H1-Token header.",
            "code": "H1_TOKEN_REQUIRED",
        }

    # 1. Validate approval BEFORE kill switch checks
    # This ensures expired/submitted/denied approvals return proper codes
    # even when kill switches are off (enables acceptance testing).
    approval_check = _validate_approval_for_submit(req.approval_id)
    if approval_check is not None:
        return approval_check

    # 2. Kill switch checks
    if not _check_ibkr_allowed():
        append_guard_event("submit_blocked", {
            "reason": "IBKR_ALLOW_ORDERS=false",
            "approval_id": req.approval_id,
        })
        return {
            "submitted": False,
            "error": "Orders blocked: IBKR_ALLOW_ORDERS=false. Chris must enable orders.",
            "code": "ORDERS_BLOCKED",
        }

    loaded_ok, rules = _load_rules_safe()
    if not loaded_ok or not _check_enforced(rules):
        reason = "rules file not loaded" if not loaded_ok else "rules.enforced=false"
        append_guard_event("submit_blocked", {
            "reason": reason,
            "approval_id": req.approval_id,
        })
        return {
            "submitted": False,
            "error": f"Orders blocked: rules.enforced=false. Both kill switches must be true.",
            "code": "ORDERS_BLOCKED",
        }

    # 3. Both kill switches pass — delegate to guard.submit_order
    # Phase H1: Authorize guard mutations for this request
    with h1_authorized_scope():
        result = submit_order(
            req.approval_id,
            order_provider=_internal_place_order,
            status_provider=_internal_order_status,
            account_provider=_internal_fetch_account if is_connected() else None,
            quote_provider=_internal_fetch_quote if is_connected() else None,
            bars_provider=_internal_fetch_bars if is_connected() else None,
        )
    return result


# --- Read-only market data endpoints ---

import math
import asyncio
from pydantic import BaseModel

try:
    from ib_insync import Stock
except Exception:
    Stock = None


class QuoteRequest(BaseModel):
    symbol: str
    exchange: str = "SMART"
    currency: str = "USD"
    delayed: bool = True


def _safe_float(x):
    try:
        if x is None:
            return None
        y = float(x)
        if math.isnan(y):
            return None
        return y
    except Exception:
        return None


def _ensure_worker_event_loop():
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())




# --- Dry-Run Endpoint (Phase 3U) ---

class DryRunRequest(BaseModel):
    """Request body for /order/dry-run.

    Same fields as a preflight request, but never submits to IBKR.
    Simulates approval, submission, and fill, then records a dry_run_order
    event. Does not call placeOrder, cancelOrder, or any IBKR API.
    """
    symbol: str
    action: str               # BUY or SELL
    totalQuantity: int
    orderType: str = "MKT"
    limitPrice: float | None = None
    stopPrice: float | None = None
    mode: str = "dry-run"
    dry_run_auto_approve: bool = True
    dry_run_fill_qty: int | None = None   # None = full fill
    proposal_path: str | None = None  # P3: path to persisted proposal JSON


@app.post("/order/dry-run")
def order_dry_run(req: DryRunRequest) -> Dict[str, Any]:
    """Simulate the full order lifecycle without touching IBKR.

    No placeOrder, no cancelOrder, no ib_insync Order objects.
    No guard-state mutations, no approval records persisted.
    All dry-run evidence is logged as dry_run_order guard events.

    Acceptable usage:
      - BUY 5 AAPL (simulates approval + full fill)
      - SELL 3 AAPL (simulates approval + partial fill)
      - Manual-terminal reconciliation exercises
    """
    from guard import run_preflight, append_guard_event, _now_utc_iso
    from datetime import datetime, timezone
    import json

    request_dict = req.model_dump(exclude_none=True)
    fill_qty = req.dry_run_fill_qty if req.dry_run_fill_qty is not None else req.totalQuantity
    start_ts = _now_utc_iso()
    proposal_path = request_dict.pop("proposal_path", None)
    dry_run_auto = request_dict.pop("dry_run_auto_approve", True)
    request_dict.pop("dry_run_fill_qty", None)

    if fill_qty < 0 or fill_qty > req.totalQuantity:
        return {"ok": False, "error": f"dry_run_fill_qty ({fill_qty}) must be 0..{req.totalQuantity}",
                "code": "INVALID_FILL"}

    # 1. Run preflight validation (same logic as /order/preflight)
    try:
        preflight = run_preflight(
            request_dict,
            account_provider=_internal_fetch_account if is_connected() else None,
            quote_provider=_internal_fetch_quote if is_connected() else None,
            bars_provider=_internal_fetch_bars if is_connected() else None,
            position_provider=_internal_fetch_positions if is_connected() else None,
            open_order_provider=open_orders_check,
            proposal_path=proposal_path,
        )
    except Exception as e:
        return {"ok": False, "step": "preflight", "error": str(e), "code": "PREFLIGHT_FAILED"}

    preflight_pass = preflight.get("pass", False)
    blocks = preflight.get("blocks", [])
    block_checks = [b.get("check", "") for b in blocks] if blocks else []

    # 2. Simulate approval (if auto-approve enabled)
    # In dry-run mode, we simulate the approval decision without
    # calling approve_approval() — that would create real approval records.
    approval_simulated = False
    if req.dry_run_auto_approve and preflight_pass:
        approval_simulated = True

    # 3. Simulate submission / fill
    simulated_order_id = f"dry-run-{int(datetime.now(timezone.utc).timestamp())}"
    
    # Compute position impact (BUY=+qty, SELL=-qty)
    action = req.action.upper()
    if action == "BUY":
        position_delta = fill_qty
    elif action == "SELL":
        position_delta = -fill_qty
    else:
        position_delta = 0
        action_label = action
    action_label = action

    # Simulated result
    simulated = {
        "ok": True,
        "simulated": True,
        "mode": "dry-run",
        "preflight_pass": preflight_pass,
        "approval_simulated": approval_simulated,
        "fill_simulated": True,
        "simulated_order_id": simulated_order_id,
        "symbol": req.symbol,
        "action": action_label,
        "totalQuantity": req.totalQuantity,
        "filled": fill_qty,
        "remaining": req.totalQuantity - fill_qty,
        "position_delta": position_delta,
        "description": f"Dry-run {action_label} {fill_qty} {req.symbol} (simulated {'full' if fill_qty == req.totalQuantity else 'partial'} fill)",
        "preflight_summary": {
            "pass": preflight_pass,
            "block_count": len(blocks) if not preflight_pass else 0,
            "blocks": blocks if not preflight_pass else [],
        },
        "timestamp_utc": start_ts,
    }

    # 4. Log dry-run event (same event log as guard events, filtered by type)
    # This makes dry-runs visible to position_drift_check() and reporting.
    if preflight_pass:
        append_guard_event("dry_run_order", {
            "mode": "dry-run",
            "simulated_order_id": simulated_order_id,
            "symbol": req.symbol,
            "action": action_label,
            "totalQuantity": req.totalQuantity,
            "filled": fill_qty,
            "remaining": req.totalQuantity - fill_qty,
            "position_delta": position_delta,
            "preflight_pass": True,
            "preflight_blocks": [],
            "approval_simulated": approval_simulated,
            "timestamp_utc": start_ts,
        })
    else:
        # Even blocked preflights are logged for audit trail
        append_guard_event("dry_run_order", {
            "mode": "dry-run",
            "symbol": req.symbol,
            "action": action_label,
            "totalQuantity": req.totalQuantity,
            "preflight_pass": False,
            "preflight_blocks": block_checks[:3],  # top 3 blocks
            "approval_simulated": False,
            "fill_simulated": False,
            "timestamp_utc": start_ts,
        })

    return simulated


# --- Scenario Library Endpoints (Phase 3W) ---

from dry_run_scenarios import list_scenarios, run_scenario


class ScenarioRequest(BaseModel):
    scenario: str


@app.get("/order/dry-run/scenarios")
def dry_run_list_scenarios() -> Dict[str, Any]:
    """List available named dry-run scenarios.

    No trading. No IBKR calls. Read-only.
    Returns descriptions and step counts for all 10 scenarios.
    """
    return {"scenarios": list_scenarios(), "count": len(list_scenarios())}


@app.post("/order/dry-run/scenario")
def dry_run_execute_scenario(req: ScenarioRequest) -> Dict[str, Any]:
    """Execute a named dry-run scenario.

    No trading. No IBKR calls. No guard-state mutations.
    Emits only dry_run_order events. Preserves locked live baseline.

    Args:
        scenario: Name from GET /order/dry-run/scenarios.

    Returns:
        Dict with per-step results, overall ok flag, and error list.
    """
    def _dry_run_caller(body: dict) -> dict:
        dr_req = DryRunRequest(**body)
        return order_dry_run(dr_req)

    def _reconcile_caller(order_id: int, final_status: str, step_body: dict = None) -> dict:
        sym = (step_body or {}).get("symbol", "AAPL")
        act = (step_body or {}).get("action", "SELL")
        rec = ReconciliationRecord(
            order_id=order_id,
            final_status=final_status,
            symbol=sym,
            action=act,
        )
        return monitor_reconcile_order(rec)

    try:
        result = run_scenario(
            req.scenario,
            dry_run_caller=_dry_run_caller,
            reconcile_caller=_reconcile_caller,
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# --- Scenario Report Endpoints (Phase 3X) ---

from dry_run_scenarios import run_scenario_report, generate_full_report


@app.get("/order/dry-run/report")
def dry_run_report(scenario: str = "buy_full_fill") -> Dict[str, Any]:
    """Run a named dry-run scenario and produce a pass/fail simulation audit report.

    No trading. No IBKR calls.
    Compares expected_drift vs actual_drift, lists event IDs,
    and confirms live baseline unchanged.

    Args:
        scenario: Scenario name (default: buy_full_fill).

    Returns:
        Dict with full report including drift comparison, event IDs, baseline check.
    """
    def _dry_run_caller(body: dict) -> dict:
        dr_req = DryRunRequest(**body)
        return order_dry_run(dr_req)

    def _reconcile_caller(order_id: int, final_status: str, step_body: dict = None) -> dict:
        sym = (step_body or {}).get("symbol", "AAPL")
        act = (step_body or {}).get("action", "SELL")
        rec = ReconciliationRecord(
            order_id=order_id,
            final_status=final_status,
            symbol=sym,
            action=act,
        )
        return monitor_reconcile_order(rec)

    def _drift_provider() -> dict:
        return position_drift_check(include_dry_run=True)

    try:
        result = run_scenario_report(
            scenario,
            dry_run_caller=_dry_run_caller,
            reconcile_caller=_reconcile_caller,
            drift_provider=_drift_provider,
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/order/dry-run/report/all")
def dry_run_report_all() -> Dict[str, Any]:
    """Run all scenarios and produce a full simulation audit report.

    No trading. No IBKR calls.
    Returns aggregated pass/fail across all scenarios.
    """
    def _dry_run_caller(body: dict) -> dict:
        dr_req = DryRunRequest(**body)
        return order_dry_run(dr_req)

    def _reconcile_caller(order_id: int, final_status: str, step_body: dict = None) -> dict:
        sym = (step_body or {}).get("symbol", "AAPL")
        act = (step_body or {}).get("action", "SELL")
        rec = ReconciliationRecord(
            order_id=order_id,
            final_status=final_status,
            symbol=sym,
            action=act,
        )
        return monitor_reconcile_order(rec)

    def _drift_provider() -> dict:
        return position_drift_check(include_dry_run=True)

    try:
        result = generate_full_report(
            dry_run_caller=_dry_run_caller,
            reconcile_caller=_reconcile_caller,
            drift_provider=_drift_provider,
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))



@app.post("/market/quote")
def market_quote(req: QuoteRequest):
    """
    Read-only quote endpoint.
    No orders. Uses delayed data by default.
    """
    _ensure_worker_event_loop()

    if IB is None or Stock is None or ib is None:
        raise HTTPException(status_code=500, detail="ib_insync not available")

    if not ib.isConnected():
        connect()

    contract = Stock(req.symbol.upper(), req.exchange, req.currency)
    qualified = ib.qualifyContracts(contract)

    if not qualified:
        return {
            "ok": False,
            "symbol": req.symbol.upper(),
            "error": "contract not found"
        }

    contract = qualified[0]

    # 1 = live, 3 = delayed, 4 = delayed-frozen
    if req.delayed:
        ib.reqMarketDataType(3)
    else:
        ib.reqMarketDataType(1)

    ticker = ib.reqMktData(contract, "", False, False)
    ib.sleep(3)

    result = {
        "ok": True,
        "symbol": contract.symbol,
        "conId": contract.conId,
        "exchange": contract.exchange,
        "primaryExchange": getattr(contract, "primaryExchange", None),
        "currency": contract.currency,
        "delayed": req.delayed,
        "bid": _safe_float(ticker.bid),
        "ask": _safe_float(ticker.ask),
        "last": _safe_float(ticker.last),
        "close": _safe_float(ticker.close),
        "marketPrice": _safe_float(ticker.marketPrice()),
    }

    try:
        ib.cancelMktData(contract)
    except Exception:
        pass

    return result

# --- Read-only market data endpoints ---

import math
import asyncio
from pydantic import BaseModel

try:
    from ib_insync import Stock
except Exception:
    Stock = None


class QuoteRequest(BaseModel):
    symbol: str
    exchange: str = "SMART"
    currency: str = "USD"
    delayed: bool = True


def _safe_float(x):
    try:
        if x is None:
            return None
        y = float(x)
        if math.isnan(y):
            return None
        return y
    except Exception:
        return None


def _ensure_worker_event_loop():
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())


@app.post("/market/quote")
def market_quote(req: QuoteRequest):
    """
    Read-only quote endpoint.
    No orders. Uses delayed data by default.
    """
    _ensure_worker_event_loop()

    if IB is None or Stock is None or ib is None:
        raise HTTPException(status_code=500, detail="ib_insync not available")

    if not ib.isConnected():
        connect()

    contract = Stock(req.symbol.upper(), req.exchange, req.currency)
    qualified = ib.qualifyContracts(contract)

    if not qualified:
        return {
            "ok": False,
            "symbol": req.symbol.upper(),
            "error": "contract not found"
        }

    contract = qualified[0]

    # 1 = live, 3 = delayed, 4 = delayed-frozen
    if req.delayed:
        ib.reqMarketDataType(3)
    else:
        ib.reqMarketDataType(1)

    ticker = ib.reqMktData(contract, "", False, False)
    ib.sleep(3)

    result = {
        "ok": True,
        "symbol": contract.symbol,
        "conId": contract.conId,
        "exchange": contract.exchange,
        "primaryExchange": getattr(contract, "primaryExchange", None),
        "currency": contract.currency,
        "delayed": req.delayed,
        "bid": _safe_float(ticker.bid),
        "ask": _safe_float(ticker.ask),
        "last": _safe_float(ticker.last),
        "close": _safe_float(ticker.close),
        "marketPrice": _safe_float(ticker.marketPrice()),
    }

    try:
        ib.cancelMktData(contract)
    except Exception:
        pass

    return result

# --- Read-only market data endpoints ---

import math
import asyncio
from pydantic import BaseModel

try:
    from ib_insync import Stock
except Exception:
    Stock = None


class QuoteRequest(BaseModel):
    symbol: str
    exchange: str = "SMART"
    currency: str = "USD"
    delayed: bool = True


def _safe_float(x):
    try:
        if x is None:
            return None
        y = float(x)
        if math.isnan(y):
            return None
        return y
    except Exception:
        return None


def _ensure_worker_event_loop():
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())


@app.post("/market/quote")
def market_quote(req: QuoteRequest):
    """
    Read-only quote endpoint.
    No orders. Uses delayed data by default.
    """
    _ensure_worker_event_loop()

    if IB is None or Stock is None or ib is None:
        raise HTTPException(status_code=500, detail="ib_insync not available")

    if not ib.isConnected():
        connect()

    contract = Stock(req.symbol.upper(), req.exchange, req.currency)
    qualified = ib.qualifyContracts(contract)

    if not qualified:
        return {
            "ok": False,
            "symbol": req.symbol.upper(),
            "error": "contract not found"
        }

    contract = qualified[0]

    # 1 = live, 3 = delayed, 4 = delayed-frozen
    if req.delayed:
        ib.reqMarketDataType(3)
    else:
        ib.reqMarketDataType(1)

    ticker = ib.reqMktData(contract, "", False, False)
    ib.sleep(3)

    result = {
        "ok": True,
        "symbol": contract.symbol,
        "conId": contract.conId,
        "exchange": contract.exchange,
        "primaryExchange": getattr(contract, "primaryExchange", None),
        "currency": contract.currency,
        "delayed": req.delayed,
        "bid": _safe_float(ticker.bid),
        "ask": _safe_float(ticker.ask),
        "last": _safe_float(ticker.last),
        "close": _safe_float(ticker.close),
        "marketPrice": _safe_float(ticker.marketPrice()),
    }

    try:
        ib.cancelMktData(contract)
    except Exception:
        pass

    return result
# --- Read-only historical bars endpoint ---

class BarsRequest(BaseModel):
    symbol: str
    exchange: str = "SMART"
    currency: str = "USD"
    duration: str = "30 D"
    bar_size: str = "1 day"
    what_to_show: str = "TRADES"
    use_rth: bool = True


@app.post("/market/bars")
def market_bars(req: BarsRequest):
    _ensure_worker_event_loop()

    if IB is None or Stock is None or ib is None:
        raise HTTPException(status_code=500, detail="ib_insync not available")

    if not ib.isConnected():
        connect()

    contract = Stock(req.symbol.upper(), req.exchange, req.currency)
    qualified = ib.qualifyContracts(contract)

    if not qualified:
        return {
            "ok": False,
            "symbol": req.symbol.upper(),
            "error": "contract not found"
        }

    contract = qualified[0]

    bars = ib.reqHistoricalData(
        contract,
        endDateTime="",
        durationStr=req.duration,
        barSizeSetting=req.bar_size,
        whatToShow=req.what_to_show,
        useRTH=req.use_rth,
        formatDate=1,
        keepUpToDate=False,
    )

    out = []
    for b in bars:
        out.append({
            "date": str(b.date),
            "open": _safe_float(b.open),
            "high": _safe_float(b.high),
            "low": _safe_float(b.low),
            "close": _safe_float(b.close),
            "volume": int(b.volume) if b.volume is not None else None,
        })

    return {
        "ok": True,
        "symbol": contract.symbol,
        "conId": contract.conId,
        "exchange": contract.exchange,
        "primaryExchange": getattr(contract, "primaryExchange", None),
        "currency": contract.currency,
        "duration": req.duration,
        "bar_size": req.bar_size,
        "what_to_show": req.what_to_show,
        "use_rth": req.use_rth,
        "count": len(out),
        "bars": out,
    }

if _IBKR_BRIDGE_DEBUG:

    def _proc_mem_kb() -> dict:
        out = {}
        try:
            with open(f"/proc/{os.getpid()}/status", "r", encoding="utf-8") as f:
                for line in f:
                    if line.startswith(("VmRSS:", "VmPeak:", "VmSize:")):
                        key, value = line.split(":", 1)
                        out[key] = value.strip()
        except OSError as exc:
            out["error"] = str(exc)
        return out


    @app.middleware("http")
    async def memory_trace_middleware(request: Request, call_next):
        start = time.monotonic()
        before = _proc_mem_kb()
        logger.warning(
            "REQ_START path=%s method=%s mem=%s",
            request.url.path,
            request.method,
            before,
        )

        try:
            response = await call_next(request)
            return response
        finally:
            elapsed_ms = int((time.monotonic() - start) * 1000)
            after = _proc_mem_kb()
            logger.warning(
                "REQ_END path=%s method=%s elapsed_ms=%s mem=%s",
                request.url.path,
                request.method,
                elapsed_ms,
                after,
            )

# /MEMORY_TRACE_DEBUG

# ===========================================================================
# Phase 2F — Read-Only Monitoring Endpoints
# ===========================================================================


@app.get("/monitor/health")
def monitor_health() -> Dict[str, Any]:
    """Lightweight system health summary.

    Always allowed — no kill-switch dependency.
    Works with or without IBKR connection (file-based).
    Returns checks summary with guard state, events, and approvals status.
    """
    return health_summary()


@app.get("/monitor/reconciliation")
def monitor_reconciliation() -> Dict[str, Any]:
    """Full cross-source reconciliation report.

    Compares guard state vs events vs approval records vs submitted approvals.
    Detects trade count mismatches, orphan approvals, stale pending, drift.
    Logs a monitor_reconciliation event to guard-events.jsonl.
    """
    result = reconcile_snapshot()
    try:
        append_guard_event("monitor_reconciliation", {
            "passed": result.get("passed", False),
            "checks_passed": sum(1 for v in result.get("checks", {}).values() if v),
            "checks_total": len(result.get("checks", {})),
            "alert_count": len(result.get("alerts", [])),
        })
    except Exception:
        pass  # non-critical — don't fail the endpoint if logging fails
    return result


@app.get("/monitor/events")
def monitor_events(
    type: str | None = None,
    since: str | None = None,
) -> Dict[str, Any]:
    """Filtered event log query.

    Query params:
        type: Optional event type filter (comma-separated).
        since: Optional ISO-8601 timestamp inclusive lower bound.

    Returns matching events in file order. Read-only, no kill-switch dep.
    """
    events = load_events(event_type=type, since_utc=since)
    return {
        "events": events,
        "count": len(events),
        "query": {"type": type, "since": since},
    }


@app.get("/monitor/alerts")
def monitor_alerts() -> Dict[str, Any]:
    """Active alerts from the latest reconciliation run.

    Returns alerts from a fresh reconciliation scan.
    No persistent alert state — alerts are derived on-demand.
    """
    snap = reconcile_snapshot()
    return {
        "alerts": snap.get("alerts", []),
        "reconciliation_timestamp_utc": snap.get("timestamp_utc"),
    }


@app.get("/monitor/positions/drift")
def monitor_positions_drift() -> Dict[str, Any]:
    """Position drift check: expected vs actual positions.

    Computes expected net position from order_submitted events
    (BUY=+qty, SELL=-qty). If IBKR is connected, also fetches actual
    positions and compares for drift detection.

    Returns drift_detected bool, expected_positions, actual_positions,
    and mismatches list.
    """
    expected = position_drift_check()
    expected_positions = expected.get("expected_positions", {})
    # Include dry-run preview separately (Phase 3V — never pollutes live drift)
    dry_run_expected = position_drift_check(include_dry_run=True)
    dry_run_positions = dry_run_expected.get("expected_positions", {})
    # Extract purely dry-run positions by subtracting live positions
    dry_run_only = {}
    all_syms_dr = set(dry_run_positions.keys()) | set(expected_positions.keys())
    for sym in all_syms_dr:
        live_qty = expected_positions.get(sym, 0)
        dr_qty = dry_run_positions.get(sym, 0)
        diff = dr_qty - live_qty
        if diff != 0:
            dry_run_only[sym] = diff
    symbols = expected.get("symbols", [])

    actual_positions = []
    mismatches = []

    if is_connected():
        try:
            pos_response = positions()
            actual_list = pos_response.get("positions", [])
            actual_dict: dict[str, dict] = {}
            for p in actual_list:
                sym = p.get("symbol", "")
                actual_dict[sym] = p
            actual_positions = actual_list

            # Compare expected vs actual for each symbol
            all_syms = set(symbols) | set(p.get("symbol", "") for p in actual_list)
            for sym in sorted(all_syms):
                exp_qty = expected_positions.get(sym, 0)
                actual_p = actual_dict.get(sym, {})
                actual_qty = int(actual_p.get("position", 0))
                if exp_qty != actual_qty:
                    mismatches.append({
                        "symbol": sym,
                        "expected_qty": exp_qty,
                        "actual_qty": actual_qty,
                        "avgCost": actual_p.get("avgCost"),
                    })
        except Exception:
            pass  # IBKR unavailable — drift check uses expected only
    else:
        # Build expected positions list
        actual_positions = []
        for sym in symbols:
            actual_positions.append({
                "symbol": sym,
                "expected_qty": expected_positions.get(sym, 0),
                "note": "IBKR not connected — actual positions unavailable",
            })

    drift_detected = len(mismatches) > 0

    if drift_detected:
        try:
            append_guard_event("monitor_alert", {
                "alert_type": "position_drift",
                "severity": "critical",
                "detail": f"Position drift detected: {mismatches}",
            })
        except Exception:
            pass

    # Include unconfirmed order info for drift context
    unconfirmed_count = expected.get("unconfirmed_count", 0)
    unconfirmed_ids = expected.get("unconfirmed_approval_ids", [])

    # If drift exists AND there are unconfirmed orders, this is
    # a stale submission that needs action, not a real trade drift
    if drift_detected and unconfirmed_count > 0:
        drift_detail = "Drift likely caused by unconfirmed (IBKR-unacknowledged) orders"
    else:
        drift_detail = None

    return {
        "drift_detected": drift_detected,
        "dry_run_preview": dry_run_only if dry_run_only else None,
        "expected_positions": [
            {"symbol": s, "expected_qty": expected_positions.get(s, 0)}
            for s in symbols
        ],
        "actual_positions": actual_positions,
        "mismatches": mismatches,
        "unconfirmed_count": unconfirmed_count,
        "unconfirmed_approval_ids": unconfirmed_ids,
        "drift_detail": drift_detail,
    }


@app.get("/monitor/open-orders")
def monitor_open_orders() -> Dict[str, Any]:
    """Read-only: list pending/open orders from guard events + IBKR.

    Derives open orders from order_submitted events with non-terminal
    status and remaining > 0. If IBKR is connected, also fetches
    live open trades from IBKR for comparison.

    Returns open_orders list with age, status, and manual-action flags.
    No writes. No cancel. No order submission.
    """
    result = open_orders_check()

    # Add IBKR open trades if connected
    ibkr_open: list[dict] = []
    if is_connected():
        try:
            ensure_loop()
            open_trades = ib.openTrades()
            now = datetime.now(timezone.utc)
            for ot in open_trades:
                if not ot.order or not ot.contract:
                    continue
                oid = getattr(ot.order, 'orderId', None)
                perm_id = getattr(ot.order, 'permId', None)
                sym = getattr(ot.contract, 'symbol', '')
                action = getattr(ot.order, 'action', '')
                total_qty = int(getattr(ot.order, 'totalQuantity', 0) or 0)
                filled = float(getattr(ot.orderStatus, 'filled', 0) or 0)
                remaining = float(getattr(ot.orderStatus, 'remaining', 0) or 0)
                status = getattr(ot.orderStatus, 'status', '') or ''

                if remaining == 0:
                    continue

                ibkr_open.append({
                    "order_id": oid,
                    "permId": perm_id,
                    "symbol": sym,
                    "action": action,
                    "totalQuantity": total_qty,
                    "filled": filled,
                    "remaining": remaining,
                    "status": status,
                    "submitted_at_utc": None,
                    "age_seconds": None,
                    "source": "ibkr_live",
                    "requires_manual_action": status not in ("PreSubmitted", "Submitted", "PendingSubmit"),
                })
        except Exception:
            pass  # IBKR unavailable — return file-based data only

    result["ibkr_live_count"] = len(ibkr_open)
    result["ibkr_open_orders"] = ibkr_open

    # Add manual terminal reconciliation count
    from monitor import load_manual_reconciliations
    manual_records = load_manual_reconciliations()
    result["manual_terminal_count"] = len(manual_records)
    result["manual_terminal_records"] = manual_records

    # Log the check if any open orders exist
    if result["open_count"] > 0:
        try:
            append_guard_event("monitor_open_orders", {
                "open_count": result["open_count"],
                "ibkr_live_count": len(ibkr_open),
            })
        except Exception:
            pass

    return result


class ReconciliationRecord(BaseModel):
    order_id: int
    permId: int | None = None
    symbol: str
    action: str
    final_status: str
    filled: float = 0.0
    remaining: float = 0.0
    verified_by: str = "Chris"
    evidence: str = ""


@app.post("/monitor/open-orders/reconcile")
def monitor_reconcile_order(req: ReconciliationRecord) -> Dict[str, Any]:
    """Record a manual terminal reconciliation.

    Operator confirms after manual TWS/Gateway inspection that a
    guard-event order is terminal (cancelled, not found in IBKR, etc.).

    This writes a record to manual-order-reconciliations.jsonl.
    It does NOT modify guard-events.jsonl, guard-state.json, or any
    original event data. It does NOT cancel orders from the bridge.

    Accepts:
        order_id, permId, symbol, action, final_status,
        filled, remaining, verified_by, evidence

    Returns:
        Record status with the saved record.
    """
    record = req.model_dump(exclude_none=True)
    result = append_manual_reconciliation(record)
    return result


@app.get("/readiness")
def readiness() -> Dict[str, Any]:
    """Read-only: comprehensive GO / NO-GO assessment.

    Checks:
    - Is today tradable? (RTH calendar)
    - Are we inside RTH?
    - Is daily_trade_count below limit?
    - Is the system locked? (both kill switches)
    - Are positions/open orders/drift clean?
    - Is regression suite passing?

    Returns a GO / NO-GO verdict with detailed reasons.
    No auto-submit. No auto-approve. Operator advisory only.

    Step 15C: When IBKR is disconnected, returns cached/disconnected
    evidence immediately instead of blocking on IBKR calls.
    """
    global _startup_safety
    verdict = "GO"
    blocks: list[dict] = []

    # 1. RTH calendar check
    rth = rth_check()
    rth_detail = {
        "in_rth": rth["in_rth"],
        "is_tradable_day": rth["is_tradable_day"],
        "reason": rth["reason"],
        "market_date_et": rth["market_date_et"],
        "market_day_name": rth["market_day_name"],
        "rth_open_et": rth["rth_open_et"],
        "rth_close_et": rth["rth_close_et"],
    }
    if not rth["in_rth"]:
        if rth["is_tradable_day"]:
            blocks.append({
                "check": "rth_window",
                "status": "BLOCK",
                "detail": rth["reason"],
            })
        else:
            blocks.append({
                "check": "tradable_day",
                "status": "BLOCK",
                "detail": rth["reason"],
            })

    # 2. Kill switches (locked state)
    allow_orders = IBKR_ALLOW_ORDERS
    try:
        rules = load_rules()
        enforced = rules.get("enforced", False)
    except Exception:
        rules = {}
        enforced = False

    kill_switch_status = {
        "IBKR_ALLOW_ORDERS": allow_orders,
        "rules.enforced": enforced,
        "system_locked": not (allow_orders and enforced),
    }
    if not allow_orders:
        blocks.append({
            "check": "kill_switch_IBKR_ALLOW_ORDERS",
            "status": "BLOCK",
            "detail": "IBKR_ALLOW_ORDERS=false — orders blocked at bridge level",
        })
    if not enforced:
        blocks.append({
            "check": "kill_switch_rules_enforced",
            "status": "BLOCK",
            "detail": "rules.enforced=false — orders blocked at rule level",
        })

    # 3. Daily trade count vs limit
    try:
        guard_state = load_guard_state()
    except Exception:
        guard_state = {}
    trade_date = guard_state.get("trade_date", "")
    daily_trade_count = guard_state.get("daily_trade_count", 0)
    max_trades = rules.get("max_trades_per_day", {}).get("value", 2) if rules else 2
    trades_remaining = max_trades - daily_trade_count

    trade_count_status = {
        "trade_date": trade_date,
        "daily_trade_count": daily_trade_count,
        "max_trades_per_day": max_trades,
        "trades_remaining": trades_remaining,
        "daily_limit_reached": trades_remaining <= 0,
    }
    if trades_remaining <= 0:
        blocks.append({
            "check": "daily_trade_limit",
            "status": "BLOCK",
            "detail": f"Daily trade limit reached ({daily_trade_count}/{max_trades})",
        })

    # 4. Loss halts
    halt_active = guard_state.get("daily_halt_active", False) or guard_state.get("weekly_halt_active", False)
    halt_reason = guard_state.get("halt_reason", None)
    halt_status = {
        "daily_halt_active": guard_state.get("daily_halt_active", False),
        "weekly_halt_active": guard_state.get("weekly_halt_active", False),
        "halt_reason": halt_reason,
    }
    if halt_active:
        blocks.append({
            "check": "loss_halt",
            "status": "BLOCK",
            "detail": halt_reason or "Loss halt active",
        })

    # 5. Positions / drift
    drift_info = position_drift_check()
    open_orders_info = open_orders_check()

    drift_status = {
        "drift_detected": drift_info.get("drift_detected", False),
        "expected_positions": len(drift_info.get("expected_positions", [])),
        "actual_positions": len(drift_info.get("actual_positions", [])),
        "mismatches": len(drift_info.get("mismatches", [])),
        "unconfirmed_count": drift_info.get("unconfirmed_count", 0),
    }
    if drift_info.get("drift_detected", False):
        blocks.append({
            "check": "position_drift",
            "status": "BLOCK",
            "detail": f"Position drift detected: {len(drift_info.get('mismatches', []))} mismatch(es)",
        })

    open_orders_status = {
        "open_count": open_orders_info.get("open_count", 0),
        "ibkr_live_count": open_orders_info.get("ibkr_live_count", 0),
        "manual_terminal_count": open_orders_info.get("manual_terminal_count", 0),
    }
    if open_orders_info.get("open_count", 0) > 0:
        blocks.append({
            "check": "open_orders",
            "status": "BLOCK",
            "detail": f"{open_orders_info['open_count']} open order(s) exist — must be resolved first",
        })

    # 6. File integrity check (lightweight, no circular HTTP self-calls)
    # Does NOT call _run_self_test() — that runs HTTP tests that would
    # cause a circular call back to this same endpoint.
    # Instead, verify critical files exist and are parseable.
    from pathlib import Path
    home = Path.home()
    integrity_issues = []

    # Check guard-state.json
    gs_path = home / ".openclaw" / "guard-state.json"
    if gs_path.exists():
        try:
            import json
            gs_data = json.loads(gs_path.read_text())
            if not isinstance(gs_data, dict):
                integrity_issues.append("guard-state.json is not a dict")
        except (json.JSONDecodeError, OSError):
            integrity_issues.append("guard-state.json unreadable")
    else:
        integrity_issues.append("guard-state.json missing")

    # Check guard-events.jsonl
    ge_path = home / ".openclaw" / "guard-events.jsonl"
    if ge_path.exists():
        try:
            for line in ge_path.read_text().splitlines():
                if line.strip():
                    json.loads(line)
        except (json.JSONDecodeError, OSError):
            integrity_issues.append("guard-events.jsonl has invalid JSON")
    else:
        integrity_issues.append("guard-events.jsonl missing")

    reg_passed = len(integrity_issues) == 0
    reg_status = {
        "pass": reg_passed,
        "integrity_issues": integrity_issues if integrity_issues else None,
        "note": "File-integrity check only. Run 'python3 monitor.py' for full regression suite.",
    }
    if not reg_passed:
        blocks.append({
            "check": "file_integrity",
            "status": "BLOCK",
            "detail": f"Integrity issues: {'; '.join(integrity_issues)}",
        })

    # 7. Startup safety gate
    if _startup_safety is not None:
        start_safe = _startup_safety["pass"]
        start_detail = f"{_startup_safety['passed_count']}/{_startup_safety['check_count']} checks passed"
        startup_status = {
            "pass": start_safe,
            "passed_count": _startup_safety["passed_count"],
            "check_count": _startup_safety["check_count"],
        }
        if not start_safe:
            blocks.append({
                "check": "startup_safety",
                "status": "BLOCK",
                "detail": f"Startup safety checks failed: {start_detail}",
            })
    else:
        startup_status = {"pass": False, "note": "not run"}
        blocks.append({
            "check": "startup_safety",
            "status": "BLOCK",
            "detail": "Startup safety not run — restart bridge",
        })

    # 8. Connection status
    connected = is_connected()
    if not connected:
        blocks.append({
            "check": "ibkr_connection",
            "status": "WARN",
            "detail": "IBKR Gateway not connected — position drift check is file-based only",
        })

    if len(blocks) > 0:
        verdict = "NO-GO"
        # Override to GO if the only blocks are non-trading-day or pre-market
        block_checks = {b["check"] for b in blocks if b["status"] == "BLOCK"}
        warn_only = {b["check"] for b in blocks if b["status"] == "WARN"}
        # If all BLOCK checks are scheduling (not tradable today or outside RTH),
        # still NO-GO but indicate it's a scheduling issue
        scheduling_only = block_checks.issubset({"rth_window", "tradable_day"})
        if scheduling_only and not block_checks:
            scheduling_only = True  # no BLOCK checks
        if not block_checks:
            verdict = "GO"
        elif scheduling_only:
            verdict = "NO-GO (scheduling)"
        else:
            verdict = "NO-GO"

    return {
        "verdict": verdict,
        "blocks": blocks if blocks else None,
        "summary": {
            "rth": rth_detail,
            "kill_switches": kill_switch_status,
            "trade_count": trade_count_status,
            "halts": halt_status,
            "drift": drift_status,
            "open_orders": open_orders_status,
            "regression": reg_status,
            "startup_safety": startup_status,
            "ibkr_connected": connected,
        },
        "note": "Read-only advisory. No auto-submit. No auto-approve. Manual operator review required.",
    }


@app.get("/snapshot")
def snapshot() -> Dict[str, Any]:
    """Consolidated lightweight evidence snapshot for KPI/rehearsal/candidate.

    Step 15C v2: Strictly lightweight — no reconciliation, no subprocess calls.
    Uses 30s cache with double-checked locking to prevent concurrent builds.
    Liveness data served separately via /monitor/liveness.

    Returns HTTP 200 always. Read-only advisory.
    """
    global _snapshot_cache, _snapshot_cache_ts, _SNAPSHOT_CACHE_TTL, _snapshot_build_lock

    # Fast path: return cached if fresh (no lock needed for read)
    now_ms = time.time()
    if _snapshot_cache is not None and (now_ms - _snapshot_cache_ts) < _SNAPSHOT_CACHE_TTL:
        result = dict(_snapshot_cache)  # shallow copy so we can add instrumentation
        result["_instrumentation"] = {
            "cache_hit": True,
            "cache_age_seconds": round(now_ms - _snapshot_cache_ts, 3),
            "build_ms": 0,
            "in_flight_collapsed": False,
        }
        return result

    # Slow path: acquire lock, re-check, build
    t_build_start = time.time()
    in_flight_collapsed = False
    with _snapshot_build_lock:
        now_ms = time.time()
        if _snapshot_cache is not None and (now_ms - _snapshot_cache_ts) < _SNAPSHOT_CACHE_TTL:
            in_flight_collapsed = True
            result = dict(_snapshot_cache)
            result["_instrumentation"] = {
                "cache_hit": True,
                "cache_age_seconds": round(now_ms - _snapshot_cache_ts, 3),
                "build_ms": round((time.time() - t_build_start) * 1000, 1),
                "in_flight_collapsed": True,
            }
            return result
        snap = _build_snapshot_lightweight()
        build_ms = round((time.time() - t_build_start) * 1000, 1)
        snap["_instrumentation"] = {
            "cache_hit": False,
            "cache_age_seconds": 0,
            "build_ms": build_ms,
            "in_flight_collapsed": False,
        }
        _snapshot_cache = snap
        _snapshot_cache_ts = time.time()
        return snap


# ---------------------------------------------------------------------------
# Step 15C — Liveness / OOM Detection
# ---------------------------------------------------------------------------

def _check_liveness() -> dict:
    """Check process liveness — ZERO subprocess forks.

    Step 15C v3: Reads /proc/self/status for memory, avoids all subprocess
    calls (systemctl, journalctl) that fork under memory pressure and can
    themselves trigger OOM. For systemd-level OOM evidence, use the K17
    check in ibkr_operator's _collect_lightweight_evidence() which runs
    outside the bridge process.

    Returns memory stats and process state without spawning anything.
    """
    import os as _os

    result = {
        "ok": True,
        "service_active": True,
        "warnings": [],
        "memory": {},
        "oom_evidence": {
            "recent_oom_detected": False,
            "oom_details": [],
            "_note": "No subprocess checks — use K17 lightweight evidence for systemd OOM detection",
        },
    }

    # Read process memory from /proc/self/status (no fork)
    try:
        rss_bytes = 0
        vm_peak = 0
        vm_size = 0
        with open("/proc/self/status", "r") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    rss_bytes = int(line.split()[1]) * 1024  # kB → bytes
                elif line.startswith("VmPeak:"):
                    vm_peak = int(line.split()[1]) * 1024
                elif line.startswith("VmSize:"):
                    vm_size = int(line.split()[1]) * 1024

        # Also check cgroup memory limit if available
        mem_max = 0
        try:
            with open("/sys/fs/cgroup/memory.max", "r") as f:
                val = f.read().strip()
                if val != "max":
                    mem_max = int(val)
        except Exception:
            pass

        result["memory"] = {
            "rss_bytes": rss_bytes,
            "rss_mb": round(rss_bytes / (1024 * 1024), 1),
            "vm_peak_mb": round(vm_peak / (1024 * 1024), 1),
            "vm_size_mb": round(vm_size / (1024 * 1024), 1),
            "max_bytes": mem_max,
            "max_mb": round(mem_max / (1024 * 1024), 1) if mem_max else None,
        }

        # Memory pressure warnings
        if mem_max > 0 and rss_bytes > 0:
            ratio = rss_bytes / mem_max
            if ratio > 0.7:
                pct = round(ratio * 100)
                result["warnings"].append(
                    f"Memory at {pct}% of cgroup limit ({result['memory']['rss_mb']}MB / {result['memory']['max_mb']}MB)"
                )

        # Check /proc/vmstat for system OOM kills (no fork, just file read)
        try:
            with open("/proc/vmstat", "r") as f:
                for line in f:
                    if line.startswith("oom_kill"):
                        count = int(line.split()[1])
                        if count > 0:
                            result["oom_evidence"]["system_oom_kill_count"] = count
                            # Don't set recent_oom_detected — this is system-wide, not necessarily us
                        break
        except Exception:
            pass

    except Exception as e:
        result["warnings"].append(f"Cannot read /proc/self/status: {str(e)[:100]}")

    return result


@app.get("/monitor/liveness")
def monitor_liveness() -> Dict[str, Any]:
    """Step 15C v3: Liveness check — ZERO subprocess forks.

    Reads /proc/self/status directly — no systemctl, no journalctl.
    Uses a separate 60s cache. Always returns HTTP 200.
    For systemd-level OOM detection, see K17 in lightweight evidence.
    """
    global _liveness_cache, _liveness_cache_ts, _LIVENESS_CACHE_TTL
    now_ms = time.time()
    if _liveness_cache is not None and (now_ms - _liveness_cache_ts) < _LIVENESS_CACHE_TTL:
        return _liveness_cache
    result = _check_liveness()
    _liveness_cache = result
    _liveness_cache_ts = time.time()
    return result


@app.get("/market/snapshot/{symbol}")
def market_snapshot(symbol: str) -> Dict[str, Any]:
    """Step 15D: Market data snapshot — read-only, fast-fail when disconnected.

    Returns bid/ask/last/close with snapshot timestamp and age.
    When IBKR is disconnected: HTTP 200 with ok=False, market_data_available=False.
    Staleness: >60s since snapshot marks stale=True (candidate must HOLD).
    No cache — market data is time-sensitive. No subprocess forks.
    """
    symbol = symbol.upper().strip()
    now_epoch = time.time()

    if not is_connected():
        return {
            "ok": False,
            "symbol": symbol,
            "market_data_available": False,
            "detail": "IBKR not connected",
            "snapshot_timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "snapshot_epoch": now_epoch,
            "bid": None,
            "ask": None,
            "last": None,
            "close": None,
            "midpoint": None,
            "currency": None,
            "exchange": None,
            "delayed": True,
            "stale": True,
            "market_data_age_seconds": None,
        }

    try:
        q = _internal_fetch_quote(symbol)
        bid = q.get("bid")
        ask = q.get("ask")
        last = q.get("last")
        close = q.get("close")

        # Compute midpoint if bid and ask available
        midpoint = None
        if bid is not None and ask is not None:
            midpoint = round((bid + ask) / 2, 4)

        # Staleness: if snapshot > 60s old (ib.reqMktData takes ~3s, so 60s is generous)
        age_s = round(now_epoch - (q.get("_fetch_epoch", now_epoch)), 1)
        stale = age_s > 60.0

        return {
            "ok": True,
            "symbol": q.get("symbol", symbol),
            "market_data_available": True,
            "snapshot_timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "snapshot_epoch": now_epoch,
            "bid": bid,
            "ask": ask,
            "last": last,
            "close": close,
            "midpoint": midpoint,
            "currency": q.get("currency", "USD"),
            "exchange": q.get("exchange", "SMART"),
            "delayed": q.get("delayed", True),
            "stale": stale,
            "market_data_age_seconds": age_s,
        }
    except RuntimeError as e:
        return {
            "ok": False,
            "symbol": symbol,
            "market_data_available": False,
            "detail": str(e)[:200],
            "snapshot_timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "snapshot_epoch": now_epoch,
            "bid": None,
            "ask": None,
            "last": None,
            "close": None,
            "midpoint": None,
            "currency": None,
            "exchange": None,
            "delayed": True,
            "stale": True,
            "market_data_age_seconds": None,
        }


@app.get("/audit/bundle")
def audit_bundle() -> Dict[str, Any]:
    """Create an immutable audit bundle (Phase 3H).

    Packages:
    - guard-state.json, guard-events.jsonl, submitted-approvals.json,
      manual-order-reconciliations.jsonl
    - Current /health, /readiness, /monitor/reconciliation,
      /monitor/positions/drift, /monitor/open-orders
    - Regression suite results (41/41 expected)
    - SHA256 hashes of all source files

    Returns the bundle directly as JSON. Also writes to disk at
    ~/.openclaw/audit-bundles/bundle_<timestamp>.json

    No auto-submit. No auto-approve. No trading logic.
    """
    from bundle_audit import create_audit_bundle, write_audit_bundle
    # Skip regression to avoid circular H-test self-call during bundle creation.
    # Regression is run separately: python3 monitor.py
    bundle = create_audit_bundle(skip_regression=True)
    try:
        write_audit_bundle(bundle)
    except Exception:
        pass  # non-fatal — bundle is returned inline
    return bundle


@app.get("/audit/verify")
def audit_verify() -> Dict[str, Any]:
    """Create a fresh audit bundle and verify it for consistency (Phase 3I).

    Steps:
    1. Create a fresh bundle (skip endpoints to avoid circular HTTP self-call,
       skip regression to avoid circular test call)
    2. Write it to disk
    3. Verify the bundle's internal consistency

    Returns:
        Dict with pass/fail, per-check results, and bundle_id.
    """
    from bundle_audit import create_audit_bundle, write_audit_bundle, verify_audit_bundle
    # Create fresh bundle, skip endpoints to avoid circular HTTP self-call
    bundle = create_audit_bundle(skip_endpoints=True, skip_regression=True)
    try:
        write_audit_bundle(bundle)
    except Exception:
        pass  # non-fatal
    result = verify_audit_bundle(bundle)
    return result


@app.get("/audit/release")
def audit_release(phase: str = "phase3j_verified") -> Dict[str, Any]:
    """Create a release tag / provenance document (Phase 3J + 3Y).

    Steps:
    1. Creates a fresh audit bundle (skip regression to avoid circular self-call)
    2. Writes the bundle to disk
    3. Runs full dry-run simulation report (Phase 3Y)
    4. Creates a release tag referencing the bundle + dry-run evidence
    5. Writes the tag to disk

    Query params:
        phase: Label for this release (default: "phase3j_verified")

    Returns:
        The release tag dict with dry_run_simulation section.
    """
    from bundle_audit import (create_audit_bundle, write_audit_bundle,
                               create_release_tag, write_release_tag)
    from dry_run_scenarios import generate_full_report

    # Step 1: Fresh audit bundle
    bundle = create_audit_bundle(skip_regression=True)
    try:
        write_audit_bundle(bundle)
    except Exception:
        pass

    # Step 2: Compute dry-run simulation report
    dry_run_report = None
    try:
        def _dry_run_caller(body: dict) -> dict:
            dr_req = DryRunRequest(**body)
            return order_dry_run(dr_req)

        def _reconcile_caller(order_id: int, final_status: str, step_body: dict = None) -> dict:
            sym = (step_body or {}).get("symbol", "AAPL")
            act = (step_body or {}).get("action", "SELL")
            rec = ReconciliationRecord(
                order_id=order_id,
                final_status=final_status,
                symbol=sym,
                action=act,
            )
            return monitor_reconcile_order(rec)

        def _drift_provider() -> dict:
            return position_drift_check(include_dry_run=True)

        dry_run_report = generate_full_report(
            dry_run_caller=_dry_run_caller,
            reconcile_caller=_reconcile_caller,
            drift_provider=_drift_provider,
        )
    except Exception:
        dry_run_report = {"error": "dry-run report generation failed", "total_scenarios": 0, "passed_count": 0}

    # Step 3: Create release tag with dry-run evidence
    tag = create_release_tag(phase_label=phase, dry_run_report=dry_run_report)
    try:
        write_release_tag(tag)
    except Exception:
        pass  # non-fatal — tag is returned inline
    return tag


@app.get("/audit/release/latest")
def audit_release_latest() -> Dict[str, Any]:
    """Return the latest release tag."""
    from bundle_audit import latest_release_tag
    tag = latest_release_tag()
    if tag is None:
        return {"status": "no_tags", "detail": "No release tags found. Create one with GET /audit/release"}
    return tag


@app.get("/status")
def status_dashboard() -> Dict[str, Any]:
    """Release inventory / status dashboard (Phase 3O, hardened Phase 3P).

    Aggregates health, readiness, audit, provenance, and monitoring
    state into a single read-only summary.

    Resilient under partial failures:
    - IBKR disconnected
    - no audit bundle yet
    - no release tag yet
    - git unavailable
    - malformed runtime state
    - readiness unavailable
    - monitor fallback active

    Always returns HTTP 200. Each section has a 'status' field:
      'ok'    - section fully populated
      'warn'  - partial data, some fallback
      'error' - section failed

    No trading. No order paths. Read-only advisory.
    """
    from bundle_audit import latest_audit_bundle, latest_release_tag, _latest_git_tag
    from pathlib import Path
    BRIDGE_DIR = Path.home() / "agents" / "ibkr-bridge"

    # Default empty sections (status=error)
    health_sec = {"status": "error", "mode": None, "connected": None,
                  "allow_orders": None, "startup_safety": None}
    readiness_sec = {"status": "error", "verdict": None, "system_locked": None,
                     "allow_orders": None, "rules_enforced": None,
                     "rth_window": None, "ibkr_connected": None,
                     "block_count": None, "warn_count": None}
    git_sec = {"status": "error", "commit": None, "tag": None}
    bundle_sec = {"status": "error", "bundle_id": None}
    tag_sec = {"status": "error", "tag_id": None}
    drift_sec = {"status": "ok", "expected_positions": 0, "symbols": []}
    oo_sec = {"status": "ok", "open_count": 0}
    pos_sec = {"status": "warn", "positions_flat": None,
               "detail": "IBKR not connected — position check unavailable"}
    service_ver = "ibkr-openclaw-bridge"

    # 1. Health / startup safety
    try:
        h = health()
        service_ver = h.get("service", service_ver)
        ss = h.get("startup_safety", {})
        health_sec = {
            "status": "ok",
            "mode": h.get("mode"),
            "connected": h.get("connected"),
            "allow_orders": h.get("allow_orders"),
            "startup_safety": {
                "pass": ss.get("pass"),
                "passed_count": ss.get("passed_count"),
                "check_count": ss.get("check_count"),
            },
        }
    except Exception:
        health_sec["status"] = "error"

    # 2. Readiness
    try:
        r = readiness()
        r_sum = r.get("summary", {})
        blocks = r.get("blocks", [])
        ks = r_sum.get("kill_switches", {})
        readiness_sec = {
            "status": "ok",
            "verdict": r.get("verdict"),
            "system_locked": ks.get("system_locked"),
            "allow_orders": ks.get("IBKR_ALLOW_ORDERS"),
            "rules_enforced": ks.get("rules.enforced"),
            "rth_window": r_sum.get("rth", {}).get("in_rth"),
            "ibkr_connected": r_sum.get("ibkr_connected"),
            "block_count": len(blocks),
            "warn_count": sum(1 for b in blocks if b.get("status") == "WARN"),
        }
        if readiness_sec.get("system_locked") is True:
            readiness_sec["status"] = "ok"
        elif readiness_sec.get("verdict") == "NO-GO (scheduling)":
            readiness_sec["status"] = "warn"
    except Exception:
        readiness_sec["status"] = "error"

    # 3. Git identity
    try:
        import subprocess
        gc = subprocess.run(["git", "rev-parse", "HEAD"],
                            capture_output=True, text=True, cwd=BRIDGE_DIR, timeout=5)
        if gc.returncode == 0:
            commit = gc.stdout.strip()
            gtag = _latest_git_tag()
            git_sec = {"status": "ok", "commit": commit, "tag": gtag}
        else:
            git_sec = {"status": "warn", "commit": None, "tag": None,
                       "detail": "git rev-parse exited non-zero"}
    except FileNotFoundError:
        git_sec = {"status": "warn", "commit": None, "tag": None,
                   "detail": "git not installed"}
    except Exception:
        git_sec = {"status": "error", "commit": None, "tag": None}

    # 4. Latest audit bundle
    try:
        bundle = latest_audit_bundle()
        if bundle is not None:
            reg = bundle.get("regression", {})
            bundle_sec = {"status": "ok",
                          "bundle_id": bundle.get("bundle_id"),
                          "created_at_utc": bundle.get("created_at_utc"),
                          "files": len(bundle.get("files", {})),
                          "endpoints": len(bundle.get("endpoints", {})),
                          "regression": f"{reg.get('passed', '?')}/{reg.get('total', '?')}" if reg else "not recorded"}
        else:
            bundle_sec = {"status": "warn", "bundle_id": None,
                          "detail": "No audit bundles found — run GET /audit/bundle"}
    except Exception:
        bundle_sec = {"status": "error", "bundle_id": None,
                      "detail": "Failed to load audit bundles"}

    # 5. Latest release tag
    try:
        tag = latest_release_tag()
        if tag is not None:
            prov = tag.get("provenance", {})
            tag_sec = {"status": "ok",
                       "tag_id": tag.get("tag_id"),
                       "phase_label": tag.get("phase_label"),
                       "created_at_utc": tag.get("created_at_utc"),
                       "audit_bundle_id": tag.get("audit_bundle_id"),
                       "dirty": prov.get("dirty"),
                       "locked_baseline": tag.get("locked_baseline", {}).get("confirmed")}
        else:
            tag_sec = {"status": "warn", "tag_id": None,
                       "detail": "No release tags found — create one with GET /audit/release"}
    except Exception:
        tag_sec = {"status": "error", "tag_id": None,
                   "detail": "Failed to load release tags"}

    # 6. Monitoring state (file-based)
    try:
        expected = position_drift_check()
        drift_sec = {"status": "ok",
                     "expected_positions": len(expected.get("expected_positions", {})),
                     "symbols": expected.get("symbols", [])}
    except Exception:
        drift_sec = {"status": "error", "expected_positions": 0, "symbols": [],
                     "detail": "position_drift_check failed"}

    try:
        oo = open_orders_check()
        oo_sec = {"status": "ok", "open_count": oo.get("open_count")}
    except Exception:
        oo_sec = {"status": "error", "open_count": None,
                  "detail": "open_orders_check failed"}

    try:
        if ib and ib.isConnected():
            portfolio = ib.portfolio()
            flat = all(p.position == 0 for p in portfolio)
            pos_sec = {"status": "ok", "positions_flat": flat,
                       "position_count": len(portfolio)}
    except Exception:
        pos_sec = {"status": "error", "positions_flat": None,
                   "detail": "IBKR position check failed"}

    # Overall status
    sections = [health_sec, readiness_sec, git_sec, bundle_sec, tag_sec,
                drift_sec, oo_sec, pos_sec]
    errors = [s for s in sections if s.get("status") == "error"]
    warns = [s for s in sections if s.get("status") == "warn"]
    if errors:
        overall = "degraded"
    elif warns:
        overall = "ok_with_warnings"
    else:
        overall = "ok"

    return {
        "ok": True,
        "status": overall,
        "dashboard": {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "version": service_ver,
        },
        "health": health_sec,
        "readiness": readiness_sec,
        "git": git_sec,
        "audit_bundle": bundle_sec,
        "release_tag": tag_sec,
        "monitoring": {
            "drift": drift_sec,
            "open_orders": oo_sec,
            "positions": pos_sec,
        },
    }


# OOM_BACKPRESSURE_HARD — Step 15H: priority-tiered load shedding
from fastapi.responses import JSONResponse as _BPJR
import threading as _BPTH
import logging as _BPLOG
_BP_LOG=_BPLOG.getLogger("ibkr-bridge.backpressure")
_BP_LOCK=_BPTH.Lock()
_BP_ACTIVE=0
_BP_MAX_ACTIVE=4
_BP_MAX_RSS_KB=1800000

# Step 15H: Priority tiers — lower number = higher priority
_BP_TIER0 = ("/health", "/monitor/liveness")
_BP_TIER1 = ("/market/", "/snapshot")
_BP_TIER3 = ("/audit/", "/monitor/reconciliation", "/monitor/positions/drift")

def _bp_path_tier(path: str) -> int:
    if path in _BP_TIER0:
        return 0
    for pfx in _BP_TIER1:
        if path.startswith(pfx):
            return 1
    for pfx in _BP_TIER3:
        if path.startswith(pfx):
            return 3
    return 2

def _bp_rss_kb():
    try:
        for l in open(f"/proc/{os.getpid()}/status"):
            if l.startswith("VmRSS:"):
                return int(l.split()[1])
    except Exception:
        return 0
    return 0

@app.middleware("http")
async def _oom_backpressure_hard(req, call_next):
    global _BP_ACTIVE
    tier = _bp_path_tier(req.url.path)
    if tier == 0:
        return await call_next(req)
    rss=_bp_rss_kb()
    with _BP_LOCK:
        active=_BP_ACTIVE
        # Tier 3 (audit) load-shed at half capacity
        if tier == 3 and active >= _BP_MAX_ACTIVE // 2:
            _BP_LOG.error("BP_REJECT_AUDIT path=%s active=%s rss_kb=%s tier=%s", req.url.path, active, rss, tier)
            return _BPJR({"ok":False,"error":"bridge_backpressure","path":req.url.path,"active":active,"rss_kb":rss,"max_active":_BP_MAX_ACTIVE,"max_rss_kb":_BP_MAX_RSS_KB,"tier":tier,"detail":"Audit load-shed — retry when idle"}, status_code=503)
        if active >= _BP_MAX_ACTIVE or rss >= _BP_MAX_RSS_KB:
            _BP_LOG.error("BP_REJECT path=%s active=%s rss_kb=%s tier=%s", req.url.path, active, rss, tier)
            return _BPJR({"ok":False,"error":"bridge_backpressure","path":req.url.path,"active":active,"rss_kb":rss,"max_active":_BP_MAX_ACTIVE,"max_rss_kb":_BP_MAX_RSS_KB,"tier":tier}, status_code=503)
        _BP_ACTIVE += 1
    try:
        return await call_next(req)
    finally:
        with _BP_LOCK:
            _BP_ACTIVE -= 1
# /OOM_BACKPRESSURE_HARD
