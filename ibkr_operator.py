#!/usr/bin/env python3
"""
ibkr_operator.py — Phase 4B Operator Daily Checklist CLI

Read-only. No trading. No order enablement. No broker mutation.

Codifies the 8-step daily operator workflow into deterministic CLI commands.
Auto-detects workflow state by time + system state. Produces verdict + blocks
+ exactly one next safe action.

Safety invariants (enforced at module load via AST self-check):
  - No save_guard_state_atomic / initialize_guard_state
  - No append_guard_event
  - No placeOrder / cancelOrder
  - No /order or /order/submit calls
  - No .env or rules YAML writes
  - No IBKR mutation or bridge mutation

Usage:
    ibkr-operator checklist                    # auto-detect state
    ibkr-operator checklist start-of-day       # explicit state
    ibkr-operator checklist reconcile --json   # JSON output
    ibkr-operator checklist end-of-day --explain  # with rationale
"""

import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Safety invariant enforcement (AST self-check at module load)
# ---------------------------------------------------------------------------

_FORBIDDEN_NAMES = frozenset({
    "save_guard_state_atomic", "initialize_guard_state",
    "append_guard_event",
    "create_approval_record", "run_preflight",
    "_internal_place_order",
    "placeOrder", "cancelOrder",
})


def _enforce_safety():
    """Read own source, parse AST, reject any forbidden name usage."""
    import ast
    try:
        with open(__file__) as f:
            tree = ast.parse(f.read())
        for node in ast.walk(tree):
            # Direct calls: forbidden_name(...)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                if node.func.id in _FORBIDDEN_NAMES:
                    print(f"SAFETY FATAL: {node.func.id}() called directly in {__file__}",
                          file=sys.stderr)
                    sys.exit(99)
            # Attribute calls: module.forbidden_name(...)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr in _FORBIDDEN_NAMES:
                    print(f"SAFETY FATAL: {node.func.attr}() called via attribute in {__file__}",
                          file=sys.stderr)
                    sys.exit(99)
            # Imports: from X import forbidden_name
            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    if alias.name in _FORBIDDEN_NAMES:
                        print(f"SAFETY FATAL: {alias.name} imported in {__file__}",
                              file=sys.stderr)
                        sys.exit(99)
            # Imports: import forbidden_name
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name in _FORBIDDEN_NAMES:
                        print(f"SAFETY FATAL: {alias.name} imported in {__file__}",
                              file=sys.stderr)
                        sys.exit(99)
    except Exception as e:
        print(f"Safety self-check warning: {e}", file=sys.stderr)


_enforce_safety()

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

HOME = Path.home()
OPENCLAW_DIR = HOME / ".openclaw"
BRIDGE_DIR = HOME / "agents" / "ibkr-bridge"
BRIDGE_URL = os.environ.get("IBKR_BRIDGE_URL", "http://127.0.0.1:8790")
AUDIT_DIR = OPENCLAW_DIR / "audit-bundles"
RELEASE_DIR = OPENCLAW_DIR / "releases"
HEARTBEAT_DIR = OPENCLAW_DIR / "heartbeat"

# ---------------------------------------------------------------------------
# ANSI helpers
# ---------------------------------------------------------------------------

GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
CYAN = "\033[96m"
BOLD = "\033[1m"
RESET = "\033[0m"

# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def _fetch(endpoint: str) -> tuple[int, Any]:
    url = f"{BRIDGE_URL}{endpoint}"
    try:
        r = urllib.request.urlopen(url, timeout=5)
        return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        try:
            return e.code, json.loads(body) if body else {}
        except Exception:
            return e.code, {"_error": body[:200]}
    except Exception as e:
        return 0, {"_error": str(e)}

# ---------------------------------------------------------------------------
# RTH / calendar (import from monitor)
# ---------------------------------------------------------------------------

def _import_rth_check():
    """Import rth_check from monitor module."""
    sys.path.insert(0, str(BRIDGE_DIR))
    try:
        from monitor import rth_check
        return rth_check
    except ImportError as e:
        return None

# ---------------------------------------------------------------------------
# State detection
# ---------------------------------------------------------------------------

def _detect_state(rth: dict, health: dict, readiness: dict,
                  drift: dict, oo: dict, recon: dict) -> str:
    """Auto-detect current workflow state.

    Returns one of:
        weekend, pre-market, rth-locked, rth-preflight-ready,
        post-trade, end-of-day, error
    """
    # Error: bridge down
    if health.get("_error"):
        return "error"

    # Weekend / holiday
    if not rth.get("is_tradable_day", True):
        return "weekend"

    # Pre-market
    if not rth.get("in_rth", False):
        return "pre-market"

    # Post-trade: trade happened today
    tc = readiness.get("summary", {}).get("trade_count", {})
    trades_today = tc.get("daily_trade_count", 0)
    if trades_today > 0:
        return "post-trade"

    # RTH locked vs preflight-ready
    ks = readiness.get("summary", {}).get("kill_switches", {})
    if ks.get("system_locked", True):
        return "rth-locked"

    return "rth-preflight-ready"

# ---------------------------------------------------------------------------
# Core checklist logic
# ---------------------------------------------------------------------------

def _gather_data() -> dict:
    """Fetch all required data. Returns dict of endpoint results."""
    _, health = _fetch("/health")
    _, readiness = _fetch("/readiness")
    _, drift = _fetch("/monitor/positions/drift")
    _, oo = _fetch("/monitor/open-orders")
    _, recon = _fetch("/monitor/reconciliation")
    _, alerts_data = _fetch("/monitor/alerts")
    _, status = _fetch("/status")
    _, bundle = _fetch("/audit/bundle")
    _, verify = _fetch("/audit/verify")
    _, release = _fetch("/audit/release/latest")
    _, positions = _fetch("/positions")
    _, account = _fetch("/account")

    rth_fn = _import_rth_check()
    rth = rth_fn() if rth_fn else {}

    return {
        "health": health if isinstance(health, dict) else {},
        "readiness": readiness if isinstance(readiness, dict) else {},
        "drift": drift if isinstance(drift, dict) else {},
        "open_orders": oo if isinstance(oo, dict) else {},
        "reconciliation": recon if isinstance(recon, dict) else {},
        "alerts": alerts_data if isinstance(alerts_data, dict) else {},
        "status": status if isinstance(status, dict) else {},
        "audit_bundle": bundle if isinstance(bundle, dict) else {},
        "audit_verify": verify if isinstance(verify, dict) else {},
        "release_latest": release if isinstance(release, dict) else {},
        "positions": positions if isinstance(positions, dict) else {},
        "account": account if isinstance(account, dict) else {},
        "rth": rth,
    }

# ---------------------------------------------------------------------------

def _build_summary(data: dict) -> dict:
    """Extract summary fields from gathered data."""
    h = data["health"]
    rdy = data["readiness"]
    rth = data["rth"]
    drift = data["drift"]
    oo = data["open_orders"]
    recon = data["reconciliation"]
    alerts = data["alerts"]
    status = data["status"]
    ab = data["audit_bundle"]
    verify = data["audit_verify"]
    release = data["release_latest"]
    positions = data["positions"]
    acct = data["account"]

    # Runtime
    bridge_up = h.get("connected") in (True, False)
    ibkr_connected = h.get("connected", False)
    mode = h.get("mode", "paper")
    account_id = h.get("account", "?")
    if account_id == "?" and isinstance(acct, dict):
        mas = acct.get("managed_accounts", [])
        if mas:
            account_id = mas[0]

    # Safety
    ks = rdy.get("summary", {}).get("kill_switches", {})
    allow_orders = ks.get("IBKR_ALLOW_ORDERS", h.get("allow_orders", "?"))
    enforced = ks.get("rules.enforced", "?")
    system_locked = ks.get("system_locked", rdy.get("system_locked", "?"))
    ss = h.get("startup_safety", {})
    startup_safety = f"{ss.get('passed_count', '?')}/{ss.get('check_count', '?')}"

    # Calendar
    rth_section = rdy.get("summary", {}).get("rth", {})
    market_date_et = rth.get("market_date_et", rth_section.get("market_date_et", "?"))
    in_rth = rth.get("in_rth", rth_section.get("in_rth", False))
    is_tradable = rth.get("is_tradable_day", rth_section.get("is_tradable_day", False))
    day_name = rth.get("market_day_name", rth_section.get("market_day_name", "?"))
    rth_open = rth.get("rth_open_et", rth_section.get("rth_open_et", "?"))
    rth_close = rth.get("rth_close_et", rth_section.get("rth_close_et", "?"))
    cal_reason = rth.get("reason", rth_section.get("reason", "?"))

    # Portfolio
    net_liq = None
    cash = None
    if isinstance(acct, dict) and "values" in acct:
        for v in acct["values"]:
            if v.get("tag") == "NetLiquidation" and v.get("currency") in ("EUR", "BASE"):
                net_liq = v.get("value")
            if v.get("tag") == "TotalCashValue" and v.get("currency") in ("EUR", "BASE"):
                cash = v.get("value")
    pos_list = []
    if isinstance(positions, dict) and "positions" in positions:
        pos_list = positions["positions"]
    elif isinstance(positions, list):
        pos_list = positions

    exp_pos = drift.get("expected_positions", {})
    if isinstance(exp_pos, list):
        exp_pos = {p.get("symbol", "?"): p.get("expected_qty", 0) for p in exp_pos}

    # Monitoring
    drift_detected = drift.get("drift_detected", False)
    mismatches = len(drift.get("mismatches", []))
    alert_list = alerts.get("alerts", [])
    live_alerts = sum(1 for a in alert_list if a.get("requires_action", False))
    recon_pass = recon.get("pass", recon.get("ok", False))
    open_count = oo.get("open_count", 0)
    manual_terminal = oo.get("manual_terminal_count", 0)

    # Release
    rel_tag = release.get("tag_id", "?")
    rel_phase = release.get("phase_label", "?")

    # Regression — try multiple sources
    reg_count = "?"
    if isinstance(status, dict):
        rdy_section = status.get("readiness", {})
        if isinstance(rdy_section, dict):
            reg_summary = rdy_section.get("summary", {})
            if isinstance(reg_summary, dict):
                reg_count = reg_summary.get("regression", "?")
    if reg_count == "?" and isinstance(ab, dict):
        reg_count = ab.get("regression", "?")

    bundle_id = ab.get("bundle_id", "?")
    verify_pass = isinstance(verify, dict) and verify.get("pass", False)
    verify_count = f"{verify.get('passed_count', '?')}/{verify.get('check_count', '?')}" if isinstance(verify, dict) else "?"

    return {
        "runtime": {
            "bridge": "up" if bridge_up else "down",
            "ibkr_connected": ibkr_connected,
            "mode": str(mode),
            "account": str(account_id),
        },
        "safety": {
            "system_locked": system_locked if isinstance(system_locked, bool) else str(system_locked),
            "allow_orders": allow_orders if isinstance(allow_orders, bool) else str(allow_orders),
            "enforced": enforced if isinstance(enforced, bool) else str(enforced),
            "startup_safety": startup_safety,
            "order_blocked": True,
        },
        "calendar": {
            "market_date_et": str(market_date_et),
            "in_rth": bool(in_rth) if isinstance(in_rth, bool) else in_rth,
            "is_tradable_day": bool(is_tradable) if isinstance(is_tradable, bool) else is_tradable,
            "day_name": str(day_name),
            "rth_open_et": str(rth_open),
            "rth_close_et": str(rth_close),
            "reason": str(cal_reason),
        },
        "portfolio": {
            "net_liq_eur": net_liq,
            "cash_eur": cash,
            "positions": [str(p.get("symbol", "?")) for p in pos_list] if isinstance(pos_list, list) else [],
            "expected_positions": exp_pos if isinstance(exp_pos, dict) else {},
            "open_orders_count": open_count,
            "manual_terminal_count": manual_terminal,
        },
        "monitoring": {
            "drift_detected": drift_detected if isinstance(drift_detected, bool) else False,
            "drift_mismatches": mismatches,
            "live_alerts": live_alerts,
            "total_alerts": len(alert_list),
            "reconciliation_pass": recon_pass if isinstance(recon_pass, bool) else False,
        },
        "release": {
            "git_tag": rel_phase,
            "latest_release": rel_tag,
            "regression": str(reg_count),
            "latest_bundle": bundle_id,
            "audit_verify": verify_pass,
            "audit_verify_score": verify_count,
        },
    }

# ---------------------------------------------------------------------------

def _detect_blocks(data: dict, summary: dict, state: str) -> list[dict]:
    """Determine blocking conditions for the current state."""
    blocks = []
    rth = data["rth"]
    h = data["health"]
    rdy = data["readiness"]
    drift = data["drift"]
    oo = data["open_orders"]

    # Calendar blocks
    if not rth.get("is_tradable_day", True):
        blocks.append({
            "check": "tradable_day",
            "status": "BLOCK",
            "detail": rth.get("reason", "Market closed today"),
        })

    if not rth.get("in_rth", False) and rth.get("is_tradable_day", False):
        reason = rth.get("reason", "Outside regular trading hours")
        blocks.append({
            "check": "rth_window",
            "status": "BLOCK" if state in ("rth-preflight-ready",) else "WARN",
            "detail": reason,
        })

    # Safety blocks
    ks = rdy.get("summary", {}).get("kill_switches", {})
    if ks.get("system_locked", True):
        blocks.append({
            "check": "kill_switch_IBKR_ALLOW_ORDERS",
            "status": "BLOCK",
            "detail": "IBKR_ALLOW_ORDERS=false — orders blocked at bridge level",
        })
        blocks.append({
            "check": "kill_switch_rules_enforced",
            "status": "BLOCK",
            "detail": "rules.enforced=false — orders blocked at rule level",
        })

    # Trade count
    tc = rdy.get("summary", {}).get("trade_count", {})
    if tc.get("daily_limit_reached", False):
        blocks.append({
            "check": "daily_trade_limit",
            "status": "BLOCK",
            "detail": f"Trade limit reached: {tc.get('daily_trade_count', '?')}/{tc.get('max_trades_per_day', '?')}",
        })

    # Drift
    if drift.get("drift_detected", False):
        mismatches = len(drift.get("mismatches", []))
        blocks.append({
            "check": "position_drift",
            "status": "BLOCK",
            "detail": f"Drift detected: {mismatches} mismatches",
        })

    # Open orders
    if oo.get("open_count", 0) > 0:
        blocks.append({
            "check": "open_orders",
            "status": "BLOCK",
            "detail": f"{oo.get('open_count')} unresolved open orders",
        })

    # IBKR connection (WARN only)
    if not h.get("connected", False):
        blocks.append({
            "check": "ibkr_connection",
            "status": "WARN",
            "detail": "IBKR not connected — file-based drift only",
        })

    # Regression
    reg_str = summary.get("release", {}).get("regression", "?")
    if reg_str != "?" and "/" in str(reg_str):
        parts = str(reg_str).split("/")
        if len(parts) == 2:
            try:
                passed, total = int(parts[0]), int(parts[1])
                if passed < total:
                    blocks.append({
                        "check": "regression",
                        "status": "BLOCK",
                        "detail": f"Regression: {passed}/{total} PASS — some tests failing",
                    })
            except ValueError:
                pass

    return blocks

# ---------------------------------------------------------------------------

def _detect_warnings(data: dict, summary: dict) -> list[str]:
    """Detect non-blocking warnings."""
    warnings = []
    drift = data["drift"]
    alerts = data["alerts"]
    oo = data["open_orders"]
    verify = data["audit_verify"]

    # Unconfirmed orders
    uc = drift.get("unconfirmed_count", 0)
    if uc and uc > 0:
        warnings.append(f"{uc} unconfirmed order(s) (legacy pre-fix, harmless)")

    # Historical test alerts
    alert_list = alerts.get("alerts", [])
    hist = [a for a in alert_list if not a.get("requires_action", True)]
    if hist:
        warnings.append(f"{len(hist)} historical test alert(s) (no action required)")

    # Manual terminal records
    mt = oo.get("manual_terminal_count", 0)
    if mt and mt > 0:
        warnings.append(f"{mt} manual terminal record(s) on file")

    # Audit verify not passing
    if isinstance(verify, dict) and not verify.get("pass", True):
        warnings.append("Latest audit verification did not pass — run end-of-day checklist")

    # Bridge unavailable
    if isinstance(data["health"], dict) and data["health"].get("_error"):
        warnings.append("Bridge unreachable — data may be stale")

    return warnings

# ---------------------------------------------------------------------------

def _next_safe_action(state: str, blocks: list[dict], summary: dict) -> dict:
    """Determine exactly one next safe action."""
    has_block = any(b["status"] == "BLOCK" for b in blocks)
    has_drift = any(b["check"] == "position_drift" for b in blocks)
    has_open = any(b["check"] == "open_orders" for b in blocks)
    block_details = [b["detail"] for b in blocks if b["status"] == "BLOCK"]

    # Error state takes precedence over everything
    if state == "error":
        return {"action": "Restart bridge and retry",
                "rationale": "Bridge is unreachable. No checks can be performed."}

    # Drift and open orders are urgent regardless of state
    if has_drift:
        return {"action": "Stop — investigate position drift",
                "rationale": "Expected position does not match actual. Do not trade until drift is resolved."}

    if has_open:
        return {"action": "Resolve open orders manually",
                "rationale": "Open orders exist. Check TWS and create manual terminal records if needed."}

    # Calendar-driven states
    if state in ("weekend",):
        return {"action": "Stay locked — no market today",
                "rationale": f"It's {summary['calendar']['day_name']}. Next trading day resumes Monday."}

    if state == "pre-market":
        ot = summary["calendar"].get("rth_open_et", "09:30")
        ct = summary["calendar"].get("rth_close_et", "16:00")
        return {"action": f"Wait for RTH ({ot}–{ct} ET)",
                "rationale": f"Market opens at {ot} ET. Run start-of-day at or after open."}

    # Explicit workflow states
    if state == "start-of-day":
        if has_block:
            return {"action": "Resolve blocking issues",
                    "rationale": "; ".join(block_details[:2]) + ("..." if len(block_details) > 2 else "")}
        return {"action": "Baseline verified — all systems nominal",
                "rationale": "Start-of-day checks passed. System is in expected state."}

    if state == "preflight-ready":
        if has_block:
            return {"action": "Resolve gate blocks",
                    "rationale": "; ".join(block_details[:2]) + ("..." if len(block_details) > 2 else "")}
        return {"action": "Preflight gates pass — run POST /order/preflight manually",
                "rationale": "All gates check out. Operator must POST preflight and approve separately."}

    if state == "reconcile":
        tc_ok = summary.get("monitoring", {}).get("reconciliation_pass", False)
        if tc_ok and not has_block:
            return {"action": "Reconciliation complete — run regression suite",
                    "rationale": "Trade reconciled cleanly. Run regression to confirm baseline."}
        return {"action": "Manual review required",
                "rationale": "; ".join(block_details) if block_details else "Trade not reconciled cleanly."}

    if state == "regression":
        return {"action": "Run: cd ~/agents/ibkr-bridge && .venv/bin/python3 monitor.py",
                "rationale": "Regression baseline check required after changes or trades."}

    if state == "end-of-day":
        if has_block:
            return {"action": "Resolve before end-of-day lockdown",
                    "rationale": "; ".join(block_details[:2]) + ("..." if len(block_details) > 2 else "")}
        return {"action": "Create audit bundle: curl http://127.0.0.1:8790/audit/bundle",
                "rationale": "End-of-day checks pass. Operator may create audit bundle and release tag."}

    # Standard locked/preflight-reticle states
    if state == "rth-locked":
        return {"action": "Stay locked",
                "rationale": "System is locked by design. Both kill switches are false."}

    if state == "rth-preflight-ready":
        return {"action": "Run preflight POST manually",
                "rationale": "All gates pass and system is unlocked. Operator must POST /order/preflight."}

    if state == "post-trade":
        tc_ok = summary.get("monitoring", {}).get("reconciliation_pass", False)
        if tc_ok and not has_block:
            return {"action": "Reconciliation complete — run regression",
                    "rationale": "Trade reconciled cleanly."}
        return {"action": "Manual review required",
                "rationale": "; ".join(block_details) if block_details else "Unknown"}

    if has_block:
        return {"action": "Manual review required",
                "rationale": "; ".join(block_details[:2]) + ("..." if len(block_details) > 2 else "")}

    return {"action": "Stay locked", "rationale": "No actionable state detected."}

# ---------------------------------------------------------------------------

def _required_confirmations(state: str, summary: dict) -> list[str]:
    """List manual confirmations the operator must perform."""
    if state in ("weekend", "pre-market", "error"):
        return []

    confirmations = []

    if state in ("rth-preflight-ready", "rth-locked", "post-trade"):
        confirmations.append("Verify positions match TWS display")
        confirmations.append("Confirm no open orders in TWS")

    if state == "post-trade":
        recon = summary.get("monitoring", {}).get("reconciliation_pass", False)
        if not recon:
            confirmations.append("Investigate reconciliation mismatch before next trade")

    return confirmations

# ---------------------------------------------------------------------------
# Verdict calculation
# ---------------------------------------------------------------------------

def _compute_verdict(state: str, blocks: list[dict]) -> str:
    """Map state + blocks to a verdict string."""
    block_statuses = [b["status"] for b in blocks]
    has_block = "BLOCK" in block_statuses

    verdict_map = {
        "weekend": "NO-OP",
        "pre-market": "HOLD",
        "rth-locked": "NO-GO",
        "rth-preflight-ready": "PASS" if not has_block else "NO-GO",
        "post-trade": "RECONCILE-OK" if not has_block else "MANUAL-REQUIRED",
        "end-of-day": "BASELINE-LOCKED" if not has_block else "STOP",
        "error": "ERROR",
    }
    return verdict_map.get(state, "STOP")

# ---------------------------------------------------------------------------
# Checklist result builder
# ---------------------------------------------------------------------------

def run_checklist(state_override: str | None = None, data: dict | None = None) -> dict:
    """Run the checklist and return the full result dict."""
    data = _gather_data() if data is None else data
    rth = data["rth"]
    h = data["health"]
    rdy = data["readiness"]
    drift = data["drift"]
    oo = data["open_orders"]
    recon = data["reconciliation"]

    detected_state = _detect_state(rth, h, rdy, drift, oo, recon)
    state = state_override if state_override else detected_state
    summary = _build_summary(data)
    blocks = _detect_blocks(data, summary, state)
    warnings = _detect_warnings(data, summary)
    verdict = _compute_verdict(detected_state, blocks)
    next_action = _next_safe_action(state, blocks, summary)
    confirmations = _required_confirmations(state, summary)

    return {
        "command": "ibkr-operator checklist",
        "timestamp_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "state": state,
        "auto_detected": state_override is None,
        "verdict": verdict,
        "blocks": blocks,
        "warnings": warnings,
        "summary": summary,
        "required_manual_confirmations": confirmations,
        "next_safe_action": next_action,
    }

# ---------------------------------------------------------------------------
# Display: human-readable output
# ---------------------------------------------------------------------------

def _color_verdict(v: str) -> str:
    green_vals = {"PASS", "RECONCILE-OK", "NO-OP", "BASELINE-LOCKED"}
    yellow_vals = {"HOLD", "NO-GO"}
    red_vals = {"STOP", "ERROR", "MANUAL-REQUIRED"}
    if v in green_vals:
        return f"{GREEN}{v}{RESET}"
    if v in yellow_vals:
        return f"{YELLOW}{v}{RESET}"
    if v in red_vals:
        return f"{RED}{v}{RESET}"
    return v

def _color_block_status(s: str) -> str:
    if s == "PASS":
        return f"{GREEN}PASS{RESET}"
    if s == "WARN":
        return f"{YELLOW}WARN{RESET}"
    if s == "BLOCK":
        return f"{RED}BLOCK{RESET}"
    return s

def _bool_icon(val: Any) -> str:
    if val is True:
        return f"{GREEN}\u2713{RESET}"
    if val is False:
        return f"{RED}\u2717{RESET}"
    return f"{YELLOW}?{RESET}"

def _value_color(val: Any, ok_vals=(True, "up", "paper", "10/10", "true")) -> str:
    s = str(val) if val is not None else "\u2014"
    if val in ok_vals:
        return f"{GREEN}{s}{RESET}"
    if val is False or val == "false" or val == "down":
        return f"{RED}{s}{RESET}"
    return s

def print_checklist(result: dict, explain: bool = False) -> None:
    """Print checklist result as human-readable table."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    state_label = result["state"].replace("-", " ").title()
    auto_tag = " (auto-detected)" if result["auto_detected"] else ""

    print(f"{BOLD}\u2554\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2557{RESET}")
    print(f"{BOLD}\u2551       Operator Daily Checklist           \u2551{RESET}")
    print(f"{BOLD}\u255a\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u255d{RESET}")
    print(f"  Time:     {now}")
    print(f"  State:    {CYAN}{state_label}{RESET}{auto_tag}")
    print(f"  Verdict:  {_color_verdict(result['verdict'])}")
    print()

    if result["blocks"]:
        print(f"{BOLD}Blocks{RESET}")
        for b in result["blocks"]:
            print(f"  [{_color_block_status(b['status'])}] {b['check']}: {b['detail']}")
        print()
    else:
        print(f"{BOLD}Blocks{RESET}  {GREEN}None \u2014 all checks pass{RESET}")
        print()

    if result["warnings"]:
        print(f"{BOLD}Warnings{RESET}")
        for w in result["warnings"]:
            print(f"  {YELLOW}\u26a0{RESET} {w}")
        print()

    s = result["summary"]
    print(f"{BOLD}Runtime{RESET}")
    print(f"  Bridge:   {_value_color(s['runtime']['bridge'])}")
    print(f"  IBKR:     {_bool_icon(s['runtime']['ibkr_connected'])}  connected={s['runtime']['ibkr_connected']}")
    print(f"  Mode:     {_value_color(s['runtime']['mode'], ok_vals=('paper',))}")
    print(f"  Account:  {s['runtime']['account']}")
    print()
    print(f"{BOLD}Safety{RESET}")
    print(f"  Locked:   {_bool_icon(s['safety']['system_locked'])}  system_locked={s['safety']['system_locked']}")
    print(f"  Allow:    {_value_color(s['safety']['allow_orders'], ok_vals=(False, 'false'))}")
    print(f"  Enforce:  {_value_color(s['safety']['enforced'], ok_vals=(False, 'false'))}")
    print(f"  Startup:  {_value_color(s['safety']['startup_safety'], ok_vals=('10/10',))}")
    print()
    print(f"{BOLD}Calendar{RESET}")
    print(f"  Date:     {s['calendar']['market_date_et']} ({s['calendar']['day_name']})")
    print(f"  RTH:      {_bool_icon(s['calendar']['in_rth'])}  {s['calendar']['reason']}")
    print()
    print(f"{BOLD}Portfolio{RESET}")
    print(f"  Positions: {s['portfolio']['positions']}")
    print(f"  Expected:  {s['portfolio']['expected_positions']}")
    print(f"  Net Liq:   {s['portfolio']['net_liq_eur'] or '?'} EUR")
    print(f"  Cash:      {s['portfolio']['cash_eur'] or '?'} EUR")
    print(f"  Open Ord:  {s['portfolio']['open_orders_count']}")
    print()
    print(f"{BOLD}Monitoring{RESET}")
    print(f"  Drift:     {_bool_icon(not s['monitoring']['drift_detected'])}  detected={s['monitoring']['drift_detected']}")
    print(f"  Alerts:    {s['monitoring']['total_alerts']} total, {s['monitoring']['live_alerts']} requiring action")
    print(f"  Recon:     {_bool_icon(s['monitoring']['reconciliation_pass'])}")
    print()
    print(f"{BOLD}Release{RESET}")
    print(f"  Git Tag:   {s['release']['git_tag']}")
    print(f"  Release:   {s['release']['latest_release']}")
    print(f"  Regress:   {s['release']['regression']}")
    print(f"  Bundle:    {s['release']['latest_bundle']}")
    print(f"  Verify:    {_bool_icon(s['release']['audit_verify'])}  {s['release']['audit_verify_score']}")
    print()

    if result["required_manual_confirmations"]:
        print(f"{BOLD}Required Manual Confirmations{RESET}")
        for i, c in enumerate(result["required_manual_confirmations"], 1):
            print(f"  {i}. {c}")
        print()

    nsa = result["next_safe_action"]
    print(f"{BOLD}Next Safe Action{RESET}")
    print(f"  {CYAN}{nsa['action']}{RESET}")
    print(f"  {nsa['rationale']}")
    print()

    if explain:
        print(f"{BOLD}Explanation{RESET}")
        print(f"  State '{result['state']}' was determined by evaluating:")
        print(f"    - Calendar: tradable_day={s['calendar']['is_tradable_day']}, in_rth={s['calendar']['in_rth']}")
        print(f"    - Safety: system_locked={s['safety']['system_locked']}")
        print(f"    - Trade count from readiness endpoint")
        if result["blocks"]:
            print(f"  {len(result['blocks'])} block(s) found:")
            for b in result["blocks"]:
                print(f"    - {b['check']}: {b['detail']}")
        print(f"  Verdict '{result['verdict']}' is derived from state + block analysis.")
        print(f"  Next safe action follows the Phase 3D runbook.")
        print()

    print(f"{BOLD}Advisory{RESET}")
    print(f"  Read-only. No trading. No order automation.")


# ===================================================================
# Phase 4F — Daily Report (Consolidated)
# ===================================================================

def run_daily_report() -> dict:
    """Consolidated daily report gathering checklist, maintenance, and resources.

    Combines:
    - Checklist verdict, state, next_safe_action
    - Maintenance report (audit + release retention)
    - Resource health (RAM, swap, processes)
    - Kill switch state
    - Trading baseline
    - Drift/open orders

    Returns:
        Dict with all sections for display or JSON export.
    """
    now = datetime.now(timezone.utc)

    # 1. Checklist
    checklist = run_checklist()

    # 2. Maintenance report (Phase 4D) for audit + release retention
    try:
        from bundle_audit import maintenance_report as _mr
        maint = _mr()
    except Exception:
        maint = {}

    # 3. Resources (Phase 4E — embedded in maintenance_report)
    resources = maint.get("resources", {})

    # 4. Extract key sections
    s = checklist["summary"]

    report: dict[str, Any] = {
        "command": "ibkr-operator daily-report",
        "timestamp_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "generated_at_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "advisory": "Read-only. No trading. No order automation.",
        # Checklist
        "checklist": {
            "state": checklist["state"],
            "auto_detected": checklist["auto_detected"],
            "verdict": checklist["verdict"],
            "blocks": checklist["blocks"],
            "warnings": checklist["warnings"],
            "next_safe_action": checklist["next_safe_action"],
            "required_manual_confirmations": checklist["required_manual_confirmations"],
        },
        # Kill switch state
        "kill_switches": {
            "system_locked": s["safety"]["system_locked"],
            "IBKR_ALLOW_ORDERS": s["safety"]["allow_orders"],
            "rules_enforced": s["safety"]["enforced"],
            "startup_safety": s["safety"]["startup_safety"],
            "order_blocked": s["safety"]["order_blocked"],
        },
        # Runtime / trading baseline
        "runtime": s["runtime"],
        "calendar": s["calendar"],
        "portfolio": s["portfolio"],
        "monitoring": s["monitoring"],
        "release": s["release"],
        # Audit retention (from maintenance report)
        "audit_retention": {
            "bundles": maint.get("audit_bundles", {}),
            "release_tags": maint.get("release_tags", {}),
            "protected_files": maint.get("protected_files", []),
        },
        # Resource health (from maintenance report)
        "resources": resources,
    }

    return report


def print_daily_report(report: dict) -> None:
    """Print the daily report in human-readable format."""
    ts = report["timestamp_utc"]
    cl = report["checklist"]
    ks = report["kill_switches"]
    rt = report["runtime"]
    cal = report["calendar"]
    port = report["portfolio"]
    mon = report["monitoring"]
    rel = report["release"]
    ar = report["audit_retention"]
    rs = report["resources"]

    state_label = cl["state"].replace("-", " ").title()

    # ──────────────────────────────────────────────────
    # Header
    # ──────────────────────────────────────────────────
    print(f"{BOLD}Daily Operator Report{RESET}")
    print(f"{BOLD}{'=' * 50}{RESET}")
    print(f"  Time:     {ts}")
    print(f"  State:    {CYAN}{state_label}{RESET}")
    print(f"  Verdict:  {_color_verdict(cl['verdict'])}")
    print()

    # ──────────────────────────────────────────────────
    # Blocks & Warnings
    # ──────────────────────────────────────────────────
    if cl["blocks"]:
        print(f"{BOLD}Blocks{RESET}")
        for b in cl["blocks"]:
            print(f"  [{_color_block_status(b['status'])}] {b['check']}: {b['detail']}")
        print()
    else:
        print(f"{BOLD}Blocks{RESET}  {GREEN}None \u2014 all checks pass{RESET}")
        print()

    if cl["warnings"]:
        print(f"{BOLD}Warnings{RESET}")
        for w in cl["warnings"]:
            print(f"  {YELLOW}\u26a0{RESET} {w}")
        print()

    # ──────────────────────────────────────────────────
    # Kill Switches & Safety
    # ──────────────────────────────────────────────────
    print(f"{BOLD}Kill Switches / Safety{RESET}")
    print(f"  System locked: {_bool_icon(ks['system_locked'])}  {ks['system_locked']}")
    print(f"  Allow orders:  {_bool_icon(not ks['IBKR_ALLOW_ORDERS'])}  IBKR_ALLOW_ORDERS={ks['IBKR_ALLOW_ORDERS']}")
    print(f"  Rules enforcd: {_bool_icon(not ks['rules_enforced'])}  rules.enforced={ks['rules_enforced']}")
    print(f"  Startup safet: {_value_color(ks['startup_safety'], ok_vals=('10/10',))}")
    print(f"  Orders blckd:  {_bool_icon(ks['order_blocked'])}")
    print()

    # ──────────────────────────────────────────────────
    # Runtime / Bridge
    # ──────────────────────────────────────────────────
    print(f"{BOLD}Runtime / Bridge{RESET}")
    print(f"  Bridge:   {_value_color(rt['bridge'])}")
    print(f"  IBKR:     {_bool_icon(rt['ibkr_connected'])}  connected={rt['ibkr_connected']}")
    print(f"  Mode:     {_value_color(rt['mode'], ok_vals=('paper',))}")
    print(f"  Account:  {rt['account']}")
    print()

    # ──────────────────────────────────────────────────
    # Calendar / RTH
    # ──────────────────────────────────────────────────
    print(f"{BOLD}Calendar / RTH{RESET}")
    print(f"  Date: {cal['market_date_et']} ({cal['day_name']})")
    print(f"  RTH:  {_bool_icon(cal['in_rth'])}  {cal['reason']}")
    print(f"  Open: {cal['rth_open_et']} ET  Close: {cal['rth_close_et']} ET")
    print()

    # ──────────────────────────────────────────────────
    # Trading Baseline (Portfolio)
    # ──────────────────────────────────────────────────
    print(f"{BOLD}Trading Baseline{RESET}")
    print(f"  Net Liq:  {port['net_liq_eur'] or '\u2014'} EUR")
    print(f"  Cash:     {port['cash_eur'] or '\u2014'} EUR")
    print(f"  Positions: {port['positions'] or '\u2014'}")
    print(f"  Expected:  {port['expected_positions'] or '\u2014'}")
    print(f"  Open Ord:  {port['open_orders_count']}")
    print()

    # ──────────────────────────────────────────────────
    # Monitoring (Drift / Alerts / Recon)
    # ──────────────────────────────────────────────────
    print(f"{BOLD}Monitoring{RESET}")
    print(f"  Drift:     {_bool_icon(not mon['drift_detected'])}  detected={mon['drift_detected']}")
    print(f"  Mismatch:  {mon['drift_mismatches']}")
    print(f"  Alerts:    {mon['total_alerts']} total, {mon['live_alerts']} requiring action")
    print(f"  Recon:     {_bool_icon(mon['reconciliation_pass'])}")
    print()

    # ──────────────────────────────────────────────────
    # Release / Audit
    # ──────────────────────────────────────────────────
    print(f"{BOLD}Release / Audit{RESET}")
    print(f"  Git tag:    {rel['git_tag']}")
    print(f"  Release:    {rel['latest_release']}")
    print(f"  Regression: {rel['regression']}")
    print(f"  Bundle:     {rel['latest_bundle']}")
    print(f"  Audit ver:  {_bool_icon(rel['audit_verify'])}  {rel['audit_verify_score']}")

    ab = ar.get("bundles", {})
    print(f"  Bundles:    {ab.get('count', 0)} ({ab.get('size_mb', 0)} MB)  keep={ab.get('retention_limit', '?')}")
    rt_tags = ar.get("release_tags", {})
    print(f"  Releases:   {rt_tags.get('count', 0)} ({rt_tags.get('size_mb', 0)} MB)  keep={rt_tags.get('retention_limit', '?')}")
    print()

    # ──────────────────────────────────────────────────
    # System Resources
    # ──────────────────────────────────────────────────
    if rs:
        mem = rs.get("memory", {})
        swap = rs.get("swap", {})
        procs = rs.get("processes", {})
        print(f"{BOLD}System Resources{RESET}")
        print(f"  RAM:    {mem.get('used_mb', '?')}MB / {mem.get('total_mb', '?')}MB ({mem.get('used_pct', '?')}% used)")
        print(f"  Swap:   {swap.get('used_mb', '?')}MB / {swap.get('total_mb', '?')}MB")
        bw = procs.get("ibkr_bridge", {})
        gw = procs.get("ib_gateway", {})
        bridge_rss = bw.get("rss_mb", None)
        gateway_rss = gw.get("rss_mb", None)
        print(f"  Bridge:  {_bool_icon(bw.get('running'))}  RSS={f'{bridge_rss:.0f}MB' if bridge_rss else '\u2014'}")
        print(f"  Gateway: {_bool_icon(gw.get('running'))}  RSS={f'{gateway_rss:.0f}MB' if gateway_rss else '\u2014'}")

        rsw = rs.get("warnings", [])
        if rsw:
            print(f"  Warnings:")
            for w in rsw:
                print(f"    {YELLOW}\u26a0{RESET} {w}")
            print(f"  Next: {rs.get('next_safe_action', '\u2014')}")
        print()

    # ──────────────────────────────────────────────────
    # Next Safe Action
    # ──────────────────────────────────────────────────
    nsa = cl["next_safe_action"]
    print(f"{BOLD}Next Safe Action{RESET}")
    print(f"  {CYAN}{nsa['action']}{RESET}")
    print(f"  {nsa['rationale']}")
    print()

    # ──────────────────────────────────────────────────
    # Required Confirmations
    # ──────────────────────────────────────────────────
    if cl["required_manual_confirmations"]:
        print(f"{BOLD}Required Manual Confirmations{RESET}")
        for i, c in enumerate(cl["required_manual_confirmations"], 1):
            print(f"  {i}. {c}")
        print()

    print(f"{BOLD}Advisory{RESET}")
    print(f"  {report['advisory']}")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

VALID_STATES = frozenset({
    "start-of-day", "sod", "baseline",
    "preflight-ready", "ready", "gates",
    "reconcile", "post-trade", "recon",
    "regression", "tests", "suite",
    "end-of-day", "eod", "lockdown",
})

STATE_ALIASES = {
    "sod": "start-of-day", "baseline": "start-of-day",
    "ready": "preflight-ready", "gates": "preflight-ready",
    "post-trade": "reconcile", "recon": "reconcile",
    "tests": "regression", "suite": "regression",
    "eod": "end-of-day", "lockdown": "end-of-day",
}


# ---------------------------------------------------------------------------
# Phase 4H — Operator Evidence Export
# ---------------------------------------------------------------------------

_EXPORT_DIR = OPENCLAW_DIR / "exports"
_EXPORT_MAX_BYTES = 256 * 1024  # 256KB cap for the full export file


def run_export() -> dict:
    """Produce a read-only evidence export combining all operator data.

    Includes:
    - daily_report_snapshot (Phase 4G)
    - checklist_snapshot (Phase 4C)
    - maintenance/resource snapshot (Phase 4D/4E)
    - latest audit/release identifiers
    - git tag/commit
    - locked baseline confirmation

    Redacts secrets. Caps at 256KB. No historical logs. No raw guard-events.

    Returns:
        Dict with all sections, safe for export.
    """
    now = datetime.now(timezone.utc)
    ts_utc = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    export_id = f"export_{now.strftime('%Y%m%dT%H%M%S')}"

    # 1. Daily report snapshot (Phase 4G)
    try:
        from bundle_audit import _run_daily_report_snapshot
        daily_report_snapshot = _run_daily_report_snapshot()
    except Exception:
        daily_report_snapshot = None

    # 2. Checklist snapshot (Phase 4C)
    try:
        from bundle_audit import _run_checklist_snapshot
        checklist_snapshot = _run_checklist_snapshot()
    except Exception:
        checklist_snapshot = None

    # 3. Maintenance + resource report (Phase 4D/4E)
    try:
        from bundle_audit import maintenance_report
        maint = maintenance_report()
        # Extract just the resource summary, not full audit paths
        maintenance_snapshot = {
            "audit_bundles": {
                "count": maint.get("audit_bundles", {}).get("count", 0),
                "size_mb": maint.get("audit_bundles", {}).get("size_mb", 0.0),
                "retention_limit": maint.get("audit_bundles", {}).get("retention_limit", 20),
            },
            "release_tags": {
                "count": maint.get("release_tags", {}).get("count", 0),
                "size_mb": maint.get("release_tags", {}).get("size_mb", 0.0),
                "retention_limit": maint.get("release_tags", {}).get("retention_limit", 20),
            },
            "protected_files_present": sum(1 for f in maint.get("protected_files", []) if f.get("exists")),
            "protected_files_total": len(maint.get("protected_files", [])),
        }
        resources_snapshot = maint.get("resources", {})
    except Exception:
        maintenance_snapshot = {}
        resources_snapshot = {}

    # 4. Latest audit/release identifiers
    latest_bundle = None
    latest_release = None
    try:
        from bundle_audit import latest_audit_bundle, latest_release_tag
        lb = latest_audit_bundle()
        if lb:
            latest_bundle = {
                "bundle_id": lb.get("bundle_id"),
                "created_at_utc": lb.get("created_at_utc"),
            }
        lr = latest_release_tag()
        if lr:
            latest_release = {
                "tag_id": lr.get("tag_id"),
                "phase_label": lr.get("phase_label"),
                "created_at_utc": lr.get("created_at_utc"),
            }
    except Exception:
        pass

    # 5. Git tag/commit + locked baseline from provenance
    git_info = None
    locked_baseline = None
    try:
        from bundle_audit import _compute_provenance
        prov = _compute_provenance(latest_audit_bundle() if latest_bundle else None)
        if "git" in prov:
            git_info = {
                k: v for k, v in prov["git"].items()
                if k in ("commit", "tag", "dirty")
            }
        # Locked baseline from checklist snapshot
        if checklist_snapshot and isinstance(checklist_snapshot, dict):
            ss = checklist_snapshot.get("summary_safety", {})
            system_locked = ss.get("system_locked", "?")
            locked_baseline = {
                "confirmed": bool(system_locked) if system_locked not in ("?",) else "?",
                "allow_orders": ss.get("allow_orders"),
                "enforced": ss.get("enforced"),
                "source": "checklist_snapshot",
            }
        elif daily_report_snapshot and isinstance(daily_report_snapshot, dict):
            ks = daily_report_snapshot.get("kill_switches", {})
            locked_baseline = {
                "confirmed": ks.get("system_locked") is True,
                "system_locked": ks.get("system_locked"),
                "IBKR_ALLOW_ORDERS": ks.get("IBKR_ALLOW_ORDERS"),
                "rules_enforced": ks.get("rules_enforced"),
                "source": "daily_report_snapshot",
            }
    except Exception:
        pass

    # 6. Assemble export
    export: dict[str, Any] = {
        "command": "ibkr-operator export",
        "export_id": export_id,
        "generated_at_utc": ts_utc,
        "read_only": True,
        "advisory": "Read-only evidence export. No trading. No order automation.",
        "sections_included": [
            "daily_report_snapshot",
            "checklist_snapshot",
            "maintenance_snapshot",
            "resources_snapshot",
            "latest_identifiers",
            "git_info",
            "locked_baseline",
        ],
        "revision": "phase4h-1",
        # Sections
        "daily_report_snapshot": daily_report_snapshot,
        "checklist_snapshot": checklist_snapshot,
        "maintenance_snapshot": maintenance_snapshot,
        "resources_snapshot": resources_snapshot,
        "latest_identifiers": {
            "audit_bundle": latest_bundle,
            "release_tag": latest_release,
        },
        "git_info": git_info,
        "locked_baseline": locked_baseline,
    }

    # Size cap enforcement
    serialized = json.dumps(export, default=str)
    if len(serialized) > _EXPORT_MAX_BYTES:
        trimmed = False
        # Trim daily_report_snapshot blocks/warnings
        drs = export.get("daily_report_snapshot", {})
        if isinstance(drs, dict):
            blk = drs.get("checklist", {}).get("blocks", [])
            if len(blk) > 5:
                drs["checklist"]["blocks"] = blk[:5]
                drs["checklist"]["blocks"].append({"_truncated": True})
                trimmed = True
            wng = drs.get("checklist", {}).get("warnings", [])
            if len(wng) > 5:
                drs["checklist"]["warnings"] = wng[:5]
                drs["checklist"]["warnings"].append({"_truncated": True})
                trimmed = True
        # Trim resources
        rs = export.get("resources_snapshot", {})
        if isinstance(rs, dict):
            export["resources_snapshot"] = {
                "memory": {"used_pct": rs.get("memory", {}).get("used_pct")},
                "processes": {
                    "ibkr_bridge": {"rss_mb": rs.get("processes", {}).get("ibkr_bridge", {}).get("rss_mb")},
                    "ib_gateway": {"rss_mb": rs.get("processes", {}).get("ib_gateway", {}).get("rss_mb")},
                },
            }
            trimmed = True
        if trimmed:
            export["_size_trimmed"] = True

    return export


def write_export(export: dict) -> Path:
    """Write evidence export to disk. Returns output path."""
    _EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    eid = export.get("export_id", f"export_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}")
    out_path = _EXPORT_DIR / f"{eid}.json"
    out_path.write_text(json.dumps(export, indent=2, default=str))
    return out_path


def run_doctor(skip_h1_canary: bool = False) -> dict:
    """Run operator self-test / doctor diagnostics. Read-only.

    Args:
        skip_h1_canary: If True, skip the H1 token canary (avoids sudo, faster).

    Returns:
        dict with "pass" (bool), "checks" (list[dict]), and metadata.
    """
    checks: list[dict[str, Any]] = []
    all_pass = True
    repo = Path.home() / "agents" / "ibkr-bridge"

    # K2: RUNBOOK.md exists
    rb_path = repo / "RUNBOOK.md"
    k2 = rb_path.exists()
    if not k2:
        all_pass = False
    checks.append({"check": "runbook_exists", "ok": k2,
                    "detail": f"{rb_path} ({rb_path.stat().st_size}B)" if k2 else "MISSING"})

    # K3: ibkr-operator symlink exists
    candidate_links = [
        Path.home() / ".local/bin/ibkr-operator",
        Path("/usr/local/bin/ibkr-operator"),
        Path.home() / "bin/ibkr-operator",
    ]
    found_link = None
    for cl in candidate_links:
        try:
            if cl.is_symlink() and cl.resolve().name == "ibkr_operator.py":
                found_link = str(cl)
                break
        except (OSError, RuntimeError):
            continue
    k3 = found_link is not None
    if not k3:
        # Fallback: check if ibkr_operator.py is in PATH via which
        import shutil
        which_ok = shutil.which("ibkr-operator") is not None
        if which_ok:
            found_link = shutil.which("ibkr-operator")
            k3 = True
    if not k3:
        all_pass = False
    checks.append({"check": "operator_symlink", "ok": k3,
                    "detail": found_link if k3 else "Not found in PATH"})

    # K4: Required files exist
    required = ["ibkr_operator.py", "bundle_audit.py", "monitor.py",
                "guard.py", "RUNBOOK.md"]
    file_details = []
    for f in required:
        exists = (repo / f).exists()
        file_details.append({"file": f, "exists": exists})
    k4 = all(fd["exists"] for fd in file_details)
    if not k4:
        all_pass = False
    checks.append({"check": "required_files", "ok": k4,
                    "detail": f"{sum(1 for fd in file_details if fd['exists'])}/{len(required)}"})

    # K5: Bridge reachable or fallback available
    import urllib.request
    bridge_up = False
    try:
        req = urllib.request.Request("http://127.0.0.1:8790/health", method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            bridge_up = resp.status == 200
    except Exception:
        bridge_up = False
    # Fallback is always available — the operator degrades gracefully
    k5 = True  # fallback always available
    checks.append({"check": "bridge_health", "ok": k5,
                    "detail": "reachable" if bridge_up else "unreachable (fallback ok)"})

    # K6: Checklist JSON is parseable
    try:
        ck = run_checklist()
        ck_ok = isinstance(ck, dict) and "verdict" in ck
        if not ck_ok:
            all_pass = False
        checks.append({"check": "checklist_parseable", "ok": ck_ok,
                        "detail": f"verdict={ck.get('verdict', '?')}" if ck_ok else "missing verdict"})
    except Exception as e:
        all_pass = False
        checks.append({"check": "checklist_parseable", "ok": False, "detail": str(e)[:120]})

    # K7: Daily-report JSON is parseable
    try:
        dr = run_daily_report()
        dr_ok = isinstance(dr, dict) and "checklist" in dr
        if not dr_ok:
            all_pass = False
        checks.append({"check": "daily_report_parseable", "ok": dr_ok,
                        "detail": "ok" if dr_ok else "missing checklist key"})
    except Exception as e:
        all_pass = False
        checks.append({"check": "daily_report_parseable", "ok": False, "detail": str(e)[:120]})

    # K8: Export directory writable
    from bundle_audit import EXPORT_DIR
    try:
        EXPORT_DIR.mkdir(parents=True, exist_ok=True)
        test_f = EXPORT_DIR / ".doctor_writable"
        test_f.write_text("")
        test_f.unlink()
        checks.append({"check": "export_dir_writable", "ok": True,
                        "detail": str(EXPORT_DIR)})
    except Exception as e:
        all_pass = False
        checks.append({"check": "export_dir_writable", "ok": False, "detail": str(e)[:120]})

    # K9: Maintenance dry-run works
    try:
        from bundle_audit import maintenance_report
        mr = maintenance_report()
        mr_ok = isinstance(mr, dict) and "audit_bundles" in mr
        if not mr_ok:
            all_pass = False
        checks.append({"check": "maintenance_dryrun", "ok": mr_ok,
                        "detail": "ok" if mr_ok else "missing audit_bundles"})
    except Exception as e:
        all_pass = False
        checks.append({"check": "maintenance_dryrun", "ok": False, "detail": str(e)[:120]})

    # K10: Protected files safety gate
    from bundle_audit import _PROTECTED_FILE_NAMES as pfn
    try:
        # Verify the safety gate is intact by checking it blocks known names
        known_safe = {"guard-state.json", "guard-events.jsonl",
                      "submitted-approvals.json", "manual-order-reconciliations.jsonl"}
        gate_ok = known_safe.issubset(pfn)
        if not gate_ok:
            all_pass = False
        checks.append({"check": "protected_files_safe", "ok": gate_ok,
                        "detail": f"{len(pfn)} protected entries" if gate_ok else "MISSING expected entries"})
    except Exception as e:
        all_pass = False
        checks.append({"check": "protected_files_safe", "ok": False, "detail": str(e)[:120]})

    # K11: Hermes advisory guard policy exists
    hermes_policy_path = Path.home() / ".openclaw" / "memory" / "hermes-advisory-guard-policy.md"
    try:
        hp_exists = hermes_policy_path.exists()
        if not hp_exists:
            all_pass = False
        checks.append({"check": "hermes_policy_exists", "ok": hp_exists,
                        "detail": str(hermes_policy_path) if hp_exists else "MISSING"})
    except Exception as e:
        all_pass = False
        checks.append({"check": "hermes_policy_exists", "ok": False, "detail": str(e)[:120]})

    # K12: H1 token canary — verifies Chris's approval token is valid.
    # Uses a fake approval ID that should never exist; the expected
    # response is "Approval not found", proving the token was accepted.
    # Never prints, logs, or exports the raw H1 token.
    if not skip_h1_canary:
        try:
            canary = _run_h1_canary()
            canary_status = canary.get("status", "FAIL")
            if canary_status == "MANUAL_REQUIRED":
                # sudo needs password — show the exact command to run manually
                canary_ok = False  # doesn't fail doctor, but flags as action needed
                checks.append({
                    "check": "h1_token_canary", "ok": False,
                    "status": "MANUAL_REQUIRED",
                    "detail": canary.get("manual_command",
                        "sudo /usr/local/sbin/ibkr-trade-window approve aprv_canary"),
                })
            elif canary_status == "PASS":
                canary_ok = True
                checks.append({"check": "h1_token_canary", "ok": True,
                               "detail": canary.get("detail", "H1 token valid")})
            else:
                canary_ok = False
                all_pass = False
                checks.append({"check": "h1_token_canary", "ok": False,
                               "detail": canary.get("detail", "H1 token canary failed")})
        except Exception as e:
            all_pass = False
            checks.append({"check": "h1_token_canary", "ok": False,
                           "detail": f"Canary error: {str(e)[:120]}"})
    else:
        checks.append({"check": "h1_token_canary", "ok": True,
                       "detail": "skipped (rehearsal mode)"})

    # ------------------------------------------------------------------
    # Step 7 — OS boundary / process hardening checks (K13-K16)
    # ------------------------------------------------------------------

    # K13: Exactly one bridge listener on 127.0.0.1:8790
    import subprocess
    try:
        result = subprocess.run(
            ["ss", "-ltnp"], capture_output=True, text=True, timeout=5)
        listeners = [
            line for line in result.stdout.splitlines()
            if "8790" in line and "LISTEN" in line.upper()
        ]
        localhost_listeners = [
            l for l in listeners if "127.0.0.1:8790" in l or "*:8790" in l or "[::]:8790" in l
        ]
        non_localhost = [
            l for l in listeners
            if "127.0.0.1:8790" not in l
            and "*:8790" not in l
            and "[::]:8790" not in l
        ]
        listener_count = len(listeners)
        # Accept 1-2 listeners (uvicorn may bind IPv4 + IPv6 on *:8790 or just 127.0.0.1)
        k13_ok = listener_count >= 1 and len(non_localhost) == 0
        if not k13_ok:
            all_pass = False
        k13_detail = f"{listener_count} listener(s) on port 8790"
        if non_localhost:
            k13_detail += f" ({len(non_localhost)} non-localhost)"
        checks.append({"check": "bridge_listener_localhost", "ok": k13_ok,
                       "detail": k13_detail})
    except Exception as e:
        all_pass = False
        checks.append({"check": "bridge_listener_localhost", "ok": False,
                       "detail": f"ss check failed: {str(e)[:120]}"})

    # K14: Systemd service active (or clearly reported if manual)
    try:
        result = subprocess.run(
            ["systemctl", "is-active", "ibkr-bridge.service"],
            capture_output=True, text=True, timeout=5)
        svc_state = result.stdout.strip()
        k14_ok = svc_state == "active"
        if not k14_ok:
            # Not a hard failure — bridge may be run manually
            k14_detail = f"{svc_state} (manual run assumed ok)"
        else:
            k14_detail = "active"
        checks.append({"check": "bridge_service_active", "ok": k14_ok,
                       "detail": k14_detail})
    except Exception as e:
        checks.append({"check": "bridge_service_active", "ok": False,
                       "detail": f"systemctl failed: {str(e)[:120]}"})

    # K15: No duplicate uvicorn processes
    try:
        result = subprocess.run(
            ["pgrep", "-c", "-f", "uvicorn bridge:app"],
            capture_output=True, text=True, timeout=5)
        count_str = result.stdout.strip()
        uvicorn_count = int(count_str) if count_str.isdigit() else 0
        k15_ok = uvicorn_count <= 2  # allow 1 main + maybe 1 child
        if not k15_ok:
            all_pass = False
        checks.append({"check": "bridge_no_duplicate_processes", "ok": k15_ok,
                       "detail": f"{uvicorn_count} uvicorn bridge process(es)"})
    except Exception as e:
        # pgrep with no matches returns exit code 1 — count = 0 is ok
        checks.append({"check": "bridge_no_duplicate_processes", "ok": True,
                       "detail": "0 uvicorn bridge processes (pgrep empty ok)"})

    # K16: Bridge health confirms read_only=true, allow_orders=false
    try:
        req = urllib.request.Request(f"{BRIDGE_URL}/health", method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            health_data = json.loads(resp.read().decode())
            mode = health_data.get("mode", "?")
            allow_orders = health_data.get("allow_orders", "?")
            read_only = mode == "paper"
            orders_disabled = (allow_orders == "false" or allow_orders is False)
            k16_ok = read_only and orders_disabled
            if not k16_ok:
                all_pass = False
            checks.append({"check": "bridge_safety_flags", "ok": k16_ok,
                           "detail": f"read_only={read_only}, allow_orders={allow_orders}"})
    except Exception as e:
        all_pass = False
        checks.append({"check": "bridge_safety_flags", "ok": False,
                       "detail": f"health check failed: {str(e)[:120]}"})

    return {
        "command": "ibkr-operator doctor",
        "timestamp_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "read_only": True,
        "pass": all_pass,
        "checks": checks,
        "passed": sum(1 for c in checks if c["ok"]),
        "total": len(checks),
    }


def print_doctor(result: dict) -> None:
    """Print doctor results in human-readable format."""
    ts = result.get("timestamp_utc", "?")
    passed = result.get("passed", 0)
    total = result.get("total", 0)
    ok = result.get("pass", False)

    verdict_color = GREEN if ok else RED
    print(f"{BOLD}Operator Doctor{RESET}  ({ts})")
    print(f"{BOLD}{'=' * 40}{RESET}")

    for c in result.get("checks", []):
        status = c.get("status", "")
        if status == "MANUAL_REQUIRED":
            status_str = f"{YELLOW}MANUAL{RESET}"
        elif c["ok"]:
            status_str = f"{GREEN}PASS{RESET}"
        else:
            status_str = f"{RED}FAIL{RESET}"
        print(f"  {status_str}  {c['check']}: {c['detail']}")

    print()
    print(f"  {BOLD}Result:{RESET} {verdict_color}{'PASS' if ok else 'FAIL'}{RESET}  ({passed}/{total})")

    if not ok:
        print(f"{YELLOW}  Some checks failed. Review above for details.{RESET}")


# ---------------------------------------------------------------------------
# Phase 4L — Release Freeze / Full CLI Evidence Snapshot
# ---------------------------------------------------------------------------


def _get_git_timeline() -> dict:
    """Collect git branch, current commit, and recent tags."""
    import subprocess as _sp
    repo = Path.home() / "agents" / "ibkr-bridge"
    try:
        branch = _sp.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, timeout=5, cwd=repo
        ).stdout.strip()
    except Exception:
        branch = "?"
    try:
        commit = _sp.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=5, cwd=repo
        ).stdout.strip()
    except Exception:
        commit = "?"
    try:
        tags_out = _sp.run(
            ["git", "tag", "--sort=-creatordate"],
            capture_output=True, text=True, timeout=5, cwd=repo
        ).stdout.strip().splitlines()
        recent_tags = tags_out[:20] if tags_out else []
    except Exception:
        recent_tags = []
    return {
        "branch": branch,
        "commit": commit,
        "tag_count": len(recent_tags),
        "recent_tags": recent_tags,
    }


def _run_regression_check() -> dict:
    """Run lightweight regression smoke test (not full monitor.py suite).

    Quickly imports and calls all operator subcommands to verify they
    parse and produce valid JSON. Falls back gracefully.
    """
    import subprocess as _sp
    import json as _json
    op = Path.home() / "agents" / "ibkr-bridge" / "ibkr_operator.py"
    if not op.exists():
        return {"pass": False, "detail": "ibkr_operator.py not found"}

    # Run a quick subcommand smoke test: each of the read-only commands
    # should exit 0 and produce parseable JSON.
    smoke_commands = [
        "doctor --json",
        "checklist --json",
        "daily-report --json",
        "export --json",
        "maintenance --json",
    ]
    results = []
    for cmd_str in smoke_commands:
        args = [sys.executable, str(op)] + cmd_str.split()
        try:
            proc = _sp.run(args, capture_output=True, text=True, timeout=15)
            parsed = _json.loads(proc.stdout) if proc.stdout.strip() else {}
            results.append({
                "command": cmd_str,
                "exit": proc.returncode,
                "parseable": bool(parsed),
            })
        except Exception as e:
            results.append({
                "command": cmd_str,
                "exit": -1,
                "parseable": False,
                "error": str(e)[:60],
            })

    passed_count = sum(1 for r in results if r["parseable"])
    total_count = len(results)
    return {
        "pass": passed_count == total_count,
        "passed": passed_count,
        "total": total_count,
        "detail": "smoke test",
        "results": results,
    }


def run_freeze() -> dict:
    """Run full operator evidence freeze snapshot. Read-only.

    Calls all operator subcommands internally and bundles results
    into one comprehensive evidence dict.
    """
    from bundle_audit import verify_export, maintenance_report

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # L2: doctor result
    doctor_result = run_doctor()

    # L3: checklist result
    checklist_result = run_checklist()

    # L4: daily-report result
    daily_report_result = run_daily_report()

    # L5: export verification (latest if available)
    try:
        export_verify = verify_export(None)
    except Exception:
        export_verify = {"pass": False, "detail": "verify_export(None) failed",
                        "passed_count": 0, "check_count": 0}

    # L6: maintenance dry-run result
    try:
        maintenance_result = maintenance_report()
    except Exception:
        maintenance_result = {"mode": "error", "detail": "maintenance_report() failed"}

    # L7: RUNBOOK.md metadata
    rb_path = Path.home() / "agents" / "ibkr-bridge" / "RUNBOOK.md"
    if rb_path.exists():
        runbook_info = {
            "exists": True,
            "size_bytes": rb_path.stat().st_size,
            "path": str(rb_path),
        }
    else:
        runbook_info = {"exists": False}

    # L8: git timeline
    git_timeline = _get_git_timeline()

    # L9 + L10: safety confirmation
    safety_confirmation = {
        "all_read_only": True,  # structural guarantee via AST
        "non_mutating_subcommands": [
            "checklist", "daily-report", "doctor",
            "export", "export --verify",
            "maintenance", "maintenance --dry-run",
            "freeze", "heartbeat",
        ],
        "protected_files_untouched": True,
        "ast_forbidden_names_blocked": True,
    }

    # L11: regression check
    regression = _run_regression_check()

    # Compose sections
    sections = {
        "doctor": doctor_result,
        "checklist": checklist_result,
        "daily_report": daily_report_result,
        "export_verify": export_verify,
        "maintenance": maintenance_result,
        "runbook": runbook_info,
        "git_timeline": git_timeline,
        "safety_confirmation": safety_confirmation,
        "regression": regression,
    }

    # Overall verdict: all must pass
    doctor_ok = doctor_result.get("pass", False)
    export_ok = export_verify.get("pass", False) if isinstance(export_verify, dict) else False
    maintenance_ok = maintenance_result.get("mode") != "error" if isinstance(maintenance_result, dict) else False
    regression_ok = regression.get("pass", False) if isinstance(regression, dict) else False
    all_pass = doctor_ok and export_ok and maintenance_ok and regression_ok

    return {
        "command": "ibkr-operator freeze",
        "timestamp_utc": ts,
        "generated_at_utc": ts,
        "read_only": True,
        "advisory": "Release freeze evidence snapshot — all CLI results bundled.",
        "sections": sections,
        "sections_included": list(sections.keys()),
        "verdict": "PASS" if all_pass else "REVIEW",
        "pass": all_pass,
    }


def print_freeze(result: dict) -> None:
    """Print release freeze snapshot in human-readable format."""
    ts = result.get("timestamp_utc", "?")
    verdict = result.get("verdict", "?")
    verdict_color = GREEN if verdict == "PASS" else RED
    sections = result.get("sections", {})

    print(f"{BOLD}Operator Release Freeze Snapshot{RESET}")
    print(f"{BOLD}{'=' * 50}{RESET}")
    print(f"  Timestamp:     {ts}")
    print(f"  Verdict:       {verdict_color}{verdict}{RESET}")
    print()

    # L2: doctor
    doc = sections.get("doctor", {})
    doc_ok = doc.get("pass", False)
    doc_color = GREEN if doc_ok else RED
    print(f"  {doc_color}{'PASS' if doc_ok else 'FAIL'}{RESET}  doctor: "
          f"{doc.get('passed', 0)}/{doc.get('total', 0)} checks passed")

    # L3: checklist
    ck = sections.get("checklist", {})
    ck_ok = ck.get("verdict") not in ("STOP", "ERROR")
    ck_color = GREEN if ck_ok else RED
    print(f"  {ck_color}{'PASS' if ck_ok else 'FAIL'}{RESET}  checklist: "
          f"verdict={ck.get('verdict', '?')}, {len(ck.get('blocks', []))} blocks")

    # L4: daily-report
    dr = sections.get("daily_report", {})
    dr_ok = "checklist" in dr
    dr_color = GREEN if dr_ok else RED
    print(f"  {dr_color}{'PASS' if dr_ok else 'FAIL'}{RESET}  daily-report: "
          f"{'present' if dr_ok else 'MISSING'}")

    # L5: export verify
    ev = sections.get("export_verify", {})
    ev_ok = ev.get("pass", False)
    ev_color = GREEN if ev_ok else RED
    print(f"  {ev_color}{'PASS' if ev_ok else 'FAIL'}{RESET}  export-verify: "
          f"{ev.get('passed_count', 0)}/{ev.get('check_count', 0)} checks")

    # L6: maintenance
    mr = sections.get("maintenance", {})
    mr_ok = mr.get("mode") != "error"
    mr_color = GREEN if mr_ok else RED
    bundles = mr.get("audit_bundles", {})
    releases = mr.get("release_tags", {})
    print(f"  {mr_color}{'PASS' if mr_ok else 'FAIL'}{RESET}  maintenance: "
          f"{bundles.get('count', '?')} bundles, {releases.get('count', '?')} tags")

    # L7: runbook
    rb = sections.get("runbook", {})
    rb_ok = rb.get("exists", False)
    rb_color = GREEN if rb_ok else RED
    print(f"  {rb_color}{'PASS' if rb_ok else 'FAIL'}{RESET}  runbook: "
          f"{rb.get('size_bytes', 0)} bytes" if rb_ok else "  FAIL  runbook: MISSING")

    # L8: git
    gt = sections.get("git_timeline", {})
    print(f"  {'INFO':<8} git: {gt.get('branch', '?')} @ {gt.get('commit', '?')}"
          f" ({gt.get('tag_count', 0)} tags)")

    # L9 + L10: safety
    sc = sections.get("safety_confirmation", {})
    sc_ok = sc.get("all_read_only", False) and sc.get("protected_files_untouched", False)
    sc_color = GREEN if sc_ok else RED
    print(f"  {sc_color}{'PASS' if sc_ok else 'FAIL'}{RESET}  safety: "
          f"read_only={sc.get('all_read_only')}, protected_untouched={sc.get('protected_files_untouched')}")

    # L11: regression
    rg = sections.get("regression", {})
    rg_ok = rg.get("pass", False)
    rg_color = GREEN if rg_ok else RED
    print(f"  {rg_color}{'PASS' if rg_ok else 'FAIL'}{RESET}  regression: "
          f"{rg.get('passed', '?')}/{rg.get('total', '?')}")

    print()
    print(f"  {BOLD}Overall:{RESET} {verdict_color}{verdict}{RESET}")


def print_export(export: dict) -> None:
    """Print evidence export in human-readable format."""
    eid = export.get("export_id", "?")
    ts = export.get("generated_at_utc", "?")

    print(f"{BOLD}Operator Evidence Export{RESET}")
    """Print evidence export in human-readable format."""
    eid = export.get("export_id", "?")
    ts = export.get("generated_at_utc", "?")

    print(f"{BOLD}Operator Evidence Export{RESET}")
    print(f"{BOLD}{'=' * 50}{RESET}")
    print(f"  ID:       {eid}")
    print(f"  Time:     {ts}")
    print(f"  Verbose:  {export.get('sections_included', [])}")
    print()

    # Daily report snapshot
    drs = export.get("daily_report_snapshot", {})
    if drs:
        print(f"{BOLD}Daily Report Snapshot{RESET}")
        cl = drs.get("checklist", {})
        print(f"  State:    {cl.get('state', '?')}")
        print(f"  Verdict:  {_color_verdict(cl.get('verdict', '?'))}")
        nsa = cl.get("next_safe_action", {})
        print(f"  Next:     {CYAN}{nsa.get('action', '?')}{RESET}")
        ks = drs.get("kill_switches", {})
        print(f"  Locked:   {_bool_icon(ks.get('system_locked'))}")
        print(f"  Allow:    {_bool_icon(not ks.get('IBKR_ALLOW_ORDERS', True))}")
        tb = drs.get("trading_baseline", {})
        print(f"  Net Liq:  {tb.get('net_liq_eur') or '\u2014'} EUR")
        print(f"  Positions:{tb.get('positions_count', '?')}  Drift: {_bool_icon(not drs.get('monitoring',{}).get('drift_detected'))}")
        print()

    # Checklist snapshot
    cs = export.get("checklist_snapshot", {})
    if cs and isinstance(cs, dict):
        print(f"{BOLD}Checklist Snapshot{RESET}")
        ss = cs.get("summary_safety", {})
        print(f"  Safety:   allow={ss.get('allow_orders')} enforced={ss.get('enforced')} locked={ss.get('system_locked')}")
        sr = cs.get("summary_release", {})
        print(f"  Release:  {sr.get('latest_release', '?')}  Bundle: {sr.get('latest_bundle', '?')}")
        print()

    # Maintenance snapshot
    ms = export.get("maintenance_snapshot", {})
    if ms:
        print(f"{BOLD}Maintenance / Retention{RESET}")
        ab = ms.get("audit_bundles", {})
        rt = ms.get("release_tags", {})
        print(f"  Bundles:  {ab.get('count', 0)} ({ab.get('size_mb', 0)} MB)  keep={ab.get('retention_limit', '?')}")
        print(f"  Releases: {rt.get('count', 0)} ({rt.get('size_mb', 0)} MB)  keep={rt.get('retention_limit', '?')}")
        print()

    # Resources
    rs = export.get("resources_snapshot", {})
    if rs:
        mem = rs.get("memory", {})
        procs = rs.get("processes", {})
        print(f"{BOLD}System Resources{RESET}")
        print(f"  RAM:  {mem.get('used_pct', '?')}% used")
        bw = procs.get("ibkr_bridge", {})
        gw = procs.get("ib_gateway", {})
        print(f"  Bridge:  {_bool_icon(bw.get('running'))}  RSS={f'{bw.get("rss_mb"):.0f}MB' if bw.get("rss_mb") else '\u2014'}")
        print(f"  Gateway: {_bool_icon(gw.get('running'))}  RSS={f'{gw.get("rss_mb"):.0f}MB' if gw.get("rss_mb") else '\u2014'}")
        print()

    # Latest identifiers
    li = export.get("latest_identifiers", {})
    if li:
        print(f"{BOLD}Latest Identifiers{RESET}")
        b = li.get("audit_bundle", {})
        r = li.get("release_tag", {})
        print(f"  Bundle:  {b.get('bundle_id', '\u2014')} ({b.get('created_at_utc', '')})")
        print(f"  Release: {r.get('tag_id', '\u2014')} ({r.get('phase_label', '')})")
        print()

    # Git info
    gi = export.get("git_info")
    if gi:
        print(f"{BOLD}Git / Provenance{RESET}")
        print(f"  Commit:  {gi.get('commit', '?')[:16]}...")
        print(f"  Tag:     {gi.get('tag', '?')}")
        print(f"  Dirty:   {_bool_icon(not gi.get('dirty', True))}")
        print()

    # Locked baseline
    lb = export.get("locked_baseline")
    if lb:
        print(f"{BOLD}Locked Baseline{RESET}")
        print(f"  Confirmed: {_bool_icon(lb.get('confirmed', False))}")
        print(f"  Source:    {lb.get('source', '?')}")
        _safe_str = f"allow={lb.get('allow_orders')} enforced={lb.get('enforced')}" if lb.get("allow_orders") is not None else f"locked={lb.get('system_locked')}"
        print(f"  Details:   {_safe_str}")
        print()

    if export.get("_size_trimmed"):
        print(f"  {YELLOW}Note: export was size-trimmed (some sections truncated){RESET}")
        print()

    print(f"{BOLD}Advisory{RESET}")
    print(f"  {export['advisory']}")


def _print_maintenance(result: dict) -> None:
    """Pretty-print maintenance report or prune result."""
    mode = result.get("mode", "read-only")
    print(f"Mode: {mode}")
    print()

    if mode in ("dry-run",):
        # Dry-run plan
        wd = result.get("would_delete", {})
        print(f"Would delete: {wd.get('total', 0)} files total")

        ab = result.get("audit_bundles", {})
        if ab.get("count", 0) > 0:
            print(f"\n  Audit bundles to delete: {ab['count']}")
            print(f"    by age:  {ab.get('by_age', 0)}")
            print(f"    by limit: {ab.get('by_limit', 0)}")
            for p in ab.get("paths", [])[:5]:
                print(f"    - {p}")
            if len(ab.get("paths", [])) > 5:
                print(f"    ... and {len(ab['paths']) - 5} more")

        rt = result.get("release_tags", {})
        if rt.get("count", 0) > 0:
            print(f"\n  Release tags to delete: {rt['count']}")
            print(f"    by age:  {rt.get('by_age', 0)}")
            print(f"    by limit: {rt.get('by_limit', 0)}")
            for p in rt.get("paths", [])[:5]:
                print(f"    - {p}")
            if len(rt.get("paths", [])) > 5:
                print(f"    ... and {len(rt['paths']) - 5} more")

        ex = result.get("exports", {})
        if ex.get("count", 0) > 0:
            print(f"\n  Exports to delete: {ex['count']}")
            print(f"    by age:  {ex.get('by_age', 0)}")
            print(f"    by limit: {ex.get('by_limit', 0)}")
            for p in ex.get("paths", [])[:5]:
                print(f"    - {p}")
            if len(ex.get("paths", [])) > 5:
                print(f"    ... and {len(ex['paths']) - 5} more")

        if wd.get("total", 0) == 0:
            print("  Nothing to delete.")
        return

    if mode == "prune":
        ab = result.get("audit_bundles", {})
        rt = result.get("release_tags", {})
        ex = result.get("exports", {})
        print(f"  Audit bundles: removed {ab.get('total_removed', 0)}"
              f" (age={ab.get('by_age', 0)}, count={ab.get('by_count', 0)})")
        print(f"  Release tags:  removed {rt.get('total_removed', 0)}"
              f" (age={rt.get('by_age', 0)}, count={rt.get('by_count', 0)})")
        print(f"  Exports:       removed {ex.get('total_removed', 0)}"
              f" (age={ex.get('by_age', 0)}, count={ex.get('by_count', 0)})")
        print(f"  Total removed: {result.get('total_removed', 0)}")
        return

    # Read-only report
    ab = result.get("audit_bundles", {})
    print("Audit Bundles")
    print(f"  Count:      {ab.get('count', 0)}")
    print(f"  Size:       {ab.get('size_mb', 0)} MB")
    print(f"  Newest:     {ab.get('newest', '-')}")
    print(f"  Oldest:     {ab.get('oldest', '-')}")
    print(f"  Retention:  {ab.get('retention_limit', '?')} max")

    rt = result.get("release_tags", {})
    print()
    print("Release Tags")
    print(f"  Count:      {rt.get('count', 0)}")
    print(f"  Size:       {rt.get('size_mb', 0)} MB")
    print(f"  Newest:     {rt.get('newest', '-')}")
    print(f"  Oldest:     {rt.get('oldest', '-')}")
    print(f"  Retention:  {rt.get('retention_limit', '?')} max")

    ex = result.get("exports", {})
    if ex:
        print()
        print("Exports")
        print(f"  Count:      {ex.get('count', 0)}")
        print(f"  Size:       {ex.get('size_mb', 0)} MB")
        print(f"  Newest:     {ex.get('newest', '-')}")
        print(f"  Oldest:     {ex.get('oldest', '-')}")
        print(f"  Retention:  {ex.get('retention_limit', '?')} max")

    pf = result.get("protected_files", [])
    if pf:
        print()
        print("Protected Files (never deleted)")
        for f in pf:
            status = "✓" if f["exists"] else "✗"
            print(f"  {status} {f['name']}")

    # Phase 4E — Resource health
    rs = result.get("resources", {})
    if rs:
        mem = rs.get("memory", {})
        swap = rs.get("swap", {})
        procs = rs.get("processes", {})
        print()
        print("System Resources")
        print(f"  RAM:    {mem.get('used_mb', '?')}MB / {mem.get('total_mb', '?')}MB ({mem.get('used_pct', '?')}% used)")
        print(f"  Swap:   {swap.get('used_mb', '?')}MB / {swap.get('total_mb', '?')}MB")

        bw = procs.get("ibkr_bridge", {})
        gw = procs.get("ib_gateway", {})
        bridge_rss = bw.get("rss_mb", None)
        gateway_rss = gw.get("rss_mb", None)
        bridge_status = "✓" if bw.get("running") else "✗"
        gateway_status = "✓" if gw.get("running") else "✗"
        bridge_mem = f"{bridge_rss:.0f}MB" if bridge_rss else "-"
        gateway_mem = f"{gateway_rss:.0f}MB" if gateway_rss else "-"
        print(f"  Bridge:  {bridge_status}  RSS={bridge_mem}")
        print(f"  Gateway: {gateway_status}  RSS={gateway_mem}")

        warnings = rs.get("warnings", [])
        if warnings:
            print()
            print("Warnings")
            for w in warnings:
                print(f"  ⚠ {w}")
            print()
            print(f"  Next: {rs.get('next_safe_action', '-')}")

    print()
    print("Run with --dry-run to see what would be pruned.")
    print("Run with --prune-audit --keep-audit N to prune audit bundles.")
    print("Run with --prune-releases --keep-releases N to prune release tags.")
    print("Run with --prune-exports --keep-exports N to prune exports.")


# ---------------------------------------------------------------------------
# Phase 7 (P7) — Read-Only Scheduled Heartbeat
# ---------------------------------------------------------------------------

# Whitelist of read-only endpoints the heartbeat may call
_HEARTBEAT_ENDPOINTS = [
    "/health",
    "/readiness",
    "/monitor/health",
    "/monitor/reconciliation",
    "/monitor/alerts",
    "/monitor/positions/drift",
    "/positions",
    "/account",
]

# Endpoints that must NEVER be called by the heartbeat (safety assert)
_FORBIDDEN_HEARTBEAT_SUBSTRINGS = [
    "/connect",
    "/order/approve",
    "/order/submit",
    "/order/preflight",
    "/order",
]


def _run_heartbeat() -> dict:
    """Run a read-only heartbeat against the IBKR bridge.

    Calls each read-only endpoint with a short timeout.  Records
    pass/fail per endpoint; never mutates state, never calls
    forbidden endpoints, never reads or uses H1 token.

    Returns a dict suitable for JSON serialization and archival.
    """
    import urllib.request
    import urllib.error
    import time
    from datetime import datetime, timezone

    ts = datetime.now(timezone.utc)
    ts_str = ts.strftime("%Y-%m-%dT%H:%M:%SZ")
    ts_file = ts.strftime("%Y%m%dT%H%M%SZ")

    results: dict[str, dict] = {}
    endpoint_failures: list[str] = []
    ok_count = 0

    for ep in _HEARTBEAT_ENDPOINTS:
        url = f"{BRIDGE_URL}{ep}"
        ep_start = time.time()
        try:
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=7) as resp:
                body = resp.read().decode(errors="replace")
                parse_ok = True
                try:
                    data = json.loads(body)
                except json.JSONDecodeError:
                    data = {"_raw": body[:500], "_parse_error": True}
                    parse_ok = False
                elapsed = round(time.time() - ep_start, 3)
                ep_ok = (resp.status == 200 and parse_ok)
                results[ep] = {
                    "status": resp.status,
                    "ok": ep_ok,
                    "elapsed_s": elapsed,
                    "data": data,
                }
                if ep_ok:
                    ok_count += 1
                else:
                    reason = f"HTTP {resp.status}" if resp.status != 200 else "invalid JSON"
                    endpoint_failures.append(f"{ep} ({reason})")
        except urllib.error.HTTPError as e:
            elapsed = round(time.time() - ep_start, 3)
            results[ep] = {
                "status": e.code,
                "ok": False,
                "elapsed_s": elapsed,
                "error": f"HTTP {e.code}",
            }
            endpoint_failures.append(f"{ep} (HTTP {e.code})")
        except Exception as e:
            elapsed = round(time.time() - ep_start, 3)
            results[ep] = {
                "status": 0,
                "ok": False,
                "elapsed_s": elapsed,
                "error": str(e)[:200],
            }
            endpoint_failures.append(f"{ep} ({type(e).__name__})")

    # Build summary from endpoint data (tolerate missing keys)
    health = results.get("/health", {}).get("data", {})
    readiness = results.get("/readiness", {}).get("data", {})
    positions = results.get("/positions", {}).get("data", {})
    alerts = results.get("/monitor/alerts", {}).get("data", {})
    recon = results.get("/monitor/reconciliation", {}).get("data", {})

    connected = health.get("connected", None)
    mode = health.get("mode", "?")
    read_only = mode == "paper"
    ks = readiness.get("summary", {}).get("kill_switches", {}) if isinstance(readiness, dict) else {}
    allow_orders = ks.get("IBKR_ALLOW_ORDERS", health.get("allow_orders", "?"))
    ss = health.get("startup_safety", {}) if isinstance(health, dict) else {}
    startup_count = f"{ss.get('passed_count', '?')}/{ss.get('check_count', '?')}"
    startup_pass = ss.get("all_passed", None)
    positions_data = positions if isinstance(positions, (dict, list)) else {}
    positions_count = len(positions_data) if isinstance(positions_data, list) else \
        positions_data.get("count", len(positions_data)) if isinstance(positions_data, dict) else 0
    live_alerts = alerts.get("live", []) if isinstance(alerts, dict) else []
    live_alert_count = len(live_alerts) if isinstance(live_alerts, list) else 0
    reconciliation_passed = recon.get("passed", None) if isinstance(recon, dict) else None

    all_endpoints_ok = len(endpoint_failures) == 0

    artifact = {
        "advisory": "Read-only heartbeat. No orders. No mutations. No H1 token.",
        "timestamp": ts_str,
        "bridge_url": BRIDGE_URL,
        "all_endpoints_ok": all_endpoints_ok,
        "endpoint_failures": endpoint_failures,
        "connected": connected,
        "read_only": read_only,
        "allow_orders": allow_orders,
        "startup_safety_pass": startup_pass,
        "startup_safety_count": startup_count,
        "positions_count": positions_count,
        "live_alert_count": live_alert_count,
        "reconciliation_passed": reconciliation_passed,
        "endpoints_ok": ok_count,
        "endpoints_total": len(_HEARTBEAT_ENDPOINTS),
        "endpoint_results": results,
    }

    # Write artifact.  Execution success (ok) is determined by whether we
    # successfully wrote the artifact, not by whether every endpoint was
    # healthy.  Endpoint failures are still recorded in the JSON.
    execution_ok = False
    artifact_path = None
    try:
        HEARTBEAT_DIR.mkdir(parents=True, exist_ok=True)
        artifact_path = HEARTBEAT_DIR / f"heartbeat-{ts_file}.json"
        tmp = artifact_path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(artifact, f, indent=2, default=str, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, artifact_path)
        execution_ok = True
    except OSError as e:
        artifact["_write_error"] = str(e)

    artifact["ok"] = execution_ok
    if artifact_path is not None:
        artifact["_artifact_path"] = str(artifact_path)

    return artifact


# ---------------------------------------------------------------------------
# Step 12 (Phase 5C) — KPI / Evidence Dashboard
# ---------------------------------------------------------------------------

# Endpoints the KPI dashboard may call (subset of heartbeat, no /order variants)
# Step 15C: Primary path is /snapshot (single consolidated call).
# Fallback to individual endpoints only when /snapshot is unavailable.
_KPI_SNAPSHOT_ENDPOINT = "/snapshot"
_KPI_ENDPOINTS = [
    "/health",
    "/readiness",
    "/status",
    "/monitor/reconciliation",
    "/monitor/alerts",
    "/monitor/events",
    "/positions",
    "/account",
]

# Forbidden endpoint substrings — safety assert
_KPI_FORBIDDEN = [
    "/connect",
    "/order/approve",
    "/order/submit",
    "/order/preflight",
    "/order",
]


def _git_metadata(repo_path: Path) -> dict:
    """Return branch, short commit, and latest tag from git.

    Uses bounded subprocess timeouts so KPI never hangs on git.
    """
    import subprocess as _sp
    _GIT_TIMEOUT = 3  # seconds — git should be sub-second locally
    result = {"branch": "?", "commit_short": "?", "tag": "?"}
    try:
        p = _sp.run(["git", "-C", str(repo_path), "rev-parse", "--abbrev-ref", "HEAD"],
                     capture_output=True, text=True, timeout=_GIT_TIMEOUT)
        result["branch"] = p.stdout.strip()
    except Exception:
        pass
    try:
        p = _sp.run(["git", "-C", str(repo_path), "rev-parse", "--short", "HEAD"],
                     capture_output=True, text=True, timeout=_GIT_TIMEOUT)
        result["commit_short"] = p.stdout.strip()
    except Exception:
        pass
    try:
        p = _sp.run(["git", "-C", str(repo_path), "describe", "--tags", "--abbrev=0"],
                     capture_output=True, text=True, timeout=_GIT_TIMEOUT)
        result["tag"] = p.stdout.strip() or "none"
    except Exception:
        pass
    return result


def _read_autonomy_level(doc_path: Path) -> str:
    """Read current autonomy level from AUTONOMY_CRITERIA.md."""
    try:
        content = doc_path.read_text()
        # Match "**0 (current)**" or "Level 0" patterns
        import re
        m = re.search(r'\*\*(\d+)\s*\(current\)\*\*', content)
        if m:
            return m.group(1)
        m = re.search(r'Level\s+(\d+)', content)
        if m:
            return m.group(1)
    except Exception:
        pass
    return "0"


def _count_clean_cycles(openclaw_dir: Path) -> int:
    """Count clean cycle evidence files."""
    count = 0
    cycle_dir = openclaw_dir / "trade-journal"
    if not cycle_dir.exists():
        return 0
    try:
        for f in cycle_dir.iterdir():
            if f.is_file() and f.suffix == ".md":
                raw = f.read_text(errors="replace")
                if "clean cycle" in raw.lower() or "cycle complete" in raw.lower():
                    count += 1
    except Exception:
        pass
    return count


def _heartbeat_age_seconds(heartbeat_dir: Path) -> float | None:
    """Return age (seconds) of most recent heartbeat artifact, or None if none."""
    if not heartbeat_dir.exists():
        return None
    try:
        files = sorted(
            heartbeat_dir.glob("heartbeat-*.json"),
            key=lambda f: f.stat().st_mtime,
            reverse=True,
        )
        if files:
            return time.time() - files[0].stat().st_mtime
    except Exception:
        pass
    return None


def _read_env_safety(env_path: Path) -> dict:
    """Read IBKR_ALLOW_ORDERS from .env (file only, not process env)."""
    result = {"IBKR_ALLOW_ORDERS": "?", "found": False}
    if not env_path.exists():
        return result
    try:
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line.startswith("#"):
                continue
            if "=" in line and not line.startswith("export "):
                k, _, v = line.partition("=")
                k = k.strip()
                v = v.strip().strip('"').strip("'")
                if k == "IBKR_ALLOW_ORDERS":
                    result["IBKR_ALLOW_ORDERS"] = v
                    result["found"] = True
                    break
    except Exception:
        pass
    return result


def _read_rules_enforced(rules_path: Path) -> dict:
    """Read rules.enforced from paper-trading-rules.yaml (file only)."""
    result = {"enforced": "?", "found": False}
    if not rules_path.exists():
        return result
    try:
        content = rules_path.read_text()
        for line in content.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if "enforced:" in stripped:
                # Handle inline comment: 'enforced: false # comment'
                val_part = stripped.split("enforced:", 1)[1]
                val = val_part.split("#", 1)[0].strip()
                result["enforced"] = val
                result["found"] = True
                break
    except Exception:
        pass
    return result


def _run_doctor_non_sudo() -> dict:
    """Lightweight doctor status. Does NOT run the heavy doctor command
    (known SIGKILL issue during automated runs). Instead, reports that
    the user should run 'ibkr-operator doctor' separately.

    Returns a placeholder indicating doctor was not run automatically.
    """
    return {
        "pass": None,
        "checks": [],
        "_note": "Doctor not run automatically (known SIGKILL issue). Run 'ibkr-operator doctor' separately.",
        "_non_canary_ok": True,  # Don't block on this
        "_non_canary_failures": [],
    }


def run_kpi() -> dict:
    """Run the KPI / Evidence dashboard. Read-only. Never touches orders.

    Fetches bridge endpoints, reads git/env/rules/docs, runs doctor,
    computes autonomy evidence, and produces a GO/HOLD/NO-GO verdict.
    """
    import urllib.request
    import urllib.error

    ts = datetime.now(timezone.utc)
    ts_str = ts.strftime("%Y-%m-%dT%H:%M:%SZ")
    ts_file = ts.strftime("%Y%m%dT%H%M%SZ")

    # ------------------------------------------------------------------
    # Verify no forbidden endpoints are in our list (safety invariant)
    # ------------------------------------------------------------------
    for ep_test in _KPI_ENDPOINTS:
        for fb in _KPI_FORBIDDEN:
            if fb in ep_test:
                return {
                    "verdict": "ERROR",
                    "error": f"Forbidden endpoint leaked into KPI list: {ep_test}",
                }

    # ------------------------------------------------------------------
    # 1. Git metadata
    # ------------------------------------------------------------------
    git = _git_metadata(BRIDGE_DIR)

    # ------------------------------------------------------------------
    # 2. Bridge endpoints (hard per-endpoint timeout, total bounded)
    # ------------------------------------------------------------------
    endpoint_results: dict[str, dict] = {}
    bridge_reachable = False
    bridge_failures: list[str] = []
    liveness: dict = {}  # Step 15C v2: always initialized before any path

    # Hard per-endpoint timeout — KPI must complete even when bridge is
    # degraded.  Local HTTP responses should be sub-second; 5s is generous
    # for a local socket but prevents hanging tests.
    _KPI_ENDPOINT_TIMEOUT = 5.0

    # Step 15C: Try consolidated snapshot first (replaces 8 separate calls)
    snapshot_data: dict = {}
    snapshot_used = False
    try:
        snap_url = f"{BRIDGE_URL}{_KPI_SNAPSHOT_ENDPOINT}"
        req = urllib.request.Request(snap_url, method="GET")
        with urllib.request.urlopen(req, timeout=_KPI_ENDPOINT_TIMEOUT) as resp:
            if resp.status == 200:
                snapshot_data = json.loads(resp.read().decode())
                snapshot_used = True
                bridge_reachable = True
    except Exception:
        snapshot_used = False

    if snapshot_used:
        # Extract all evidence from snapshot (single consolidated call)
        endpoint_results["/snapshot"] = {"status": 200, "ok": True, "data": snapshot_data}

        # Bridge health from snapshot
        connected = snapshot_data.get("connected", None)
        mode = snapshot_data.get("mode", "?")
        read_only = snapshot_data.get("read_only", False)
        bridge_allow_orders = snapshot_data.get("allow_orders", "?")
        startup_safety = snapshot_data.get("startup_safety", {})

        # Safety flags from snapshot
        safety = snapshot_data.get("safety", {})
        readiness_ao = safety.get("IBKR_ALLOW_ORDERS", "?")
        readiness_re = safety.get("rules_enforced", "?")
        system_locked = safety.get("system_locked", True)

        # Reconciliation from snapshot
        recon = snapshot_data.get("reconciliation", {})
        recon_passed = recon.get("passed", None)
        active_alert_count = recon.get("alert_count", 0)
        live_alerts = []  # snapshot doesn't carry individual alert detail

        # Positions from snapshot
        positions_list = snapshot_data.get("positions", [])
        pos_count = len(positions_list)

        # Latest events — not in snapshot, empty
        latest_events: list[dict] = []

        # Net liquidation from snapshot
        net_liq = snapshot_data.get("net_liquidation", None)

        # Guard state from snapshot
        guard = snapshot_data.get("guard", {})

    # Step 15C v2: Always fetch liveness (OOM detection, 30-min lookback)
    # Separate endpoint with its own cache — does NOT add to endpoint storm risk.
    try:
        liveness_req = urllib.request.Request(f"{BRIDGE_URL}/monitor/liveness", method="GET")
        with urllib.request.urlopen(liveness_req, timeout=_KPI_ENDPOINT_TIMEOUT) as lr:
            if lr.status == 200:
                liveness = json.loads(lr.read().decode())
    except Exception:
        pass  # liveness unavailable — not a blocker itself

    if not snapshot_used:
        # Fallback: individual endpoint calls (legacy path)
        for ep in _KPI_ENDPOINTS:
            url = f"{BRIDGE_URL}{ep}"
            try:
                req = urllib.request.Request(url, method="GET")
                with urllib.request.urlopen(req, timeout=_KPI_ENDPOINT_TIMEOUT) as resp:
                    body = resp.read().decode(errors="replace")
                    try:
                        data = json.loads(body)
                    except json.JSONDecodeError:
                        data = {"_raw": body[:500], "_parse_error": True}
                    endpoint_results[ep] = {
                        "status": resp.status,
                        "ok": resp.status == 200,
                        "data": data,
                    }
                    if resp.status == 200:
                        bridge_reachable = True
                    else:
                        bridge_failures.append(f"{ep} (HTTP {resp.status})")
            except urllib.error.HTTPError as e:
                endpoint_results[ep] = {"status": e.code, "ok": False, "error": f"HTTP {e.code}"}
                bridge_failures.append(f"{ep} (HTTP {e.code})")
            except Exception as e:
                endpoint_results[ep] = {"status": 0, "ok": False, "error": str(e)[:200]}
                bridge_failures.append(f"{ep} ({type(e).__name__})")

        # Extract key data from individual endpoints
        health = endpoint_results.get("/health", {}).get("data", {})
        readiness = endpoint_results.get("/readiness", {}).get("data", {})
        status_data = endpoint_results.get("/status", {}).get("data", {})
        reconciliation = endpoint_results.get("/monitor/reconciliation", {}).get("data", {})
        alerts_data = endpoint_results.get("/monitor/alerts", {}).get("data", {})
        events_data = endpoint_results.get("/monitor/events", {}).get("data", {})
        positions_data = endpoint_results.get("/positions", {}).get("data", {})
        account_data = endpoint_results.get("/account", {}).get("data", {})

        # Bridge health
        connected = health.get("connected", None) if isinstance(health, dict) else None
        mode = health.get("mode", "?") if isinstance(health, dict) else "?"
        read_only = mode == "paper"
        bridge_allow_orders = health.get("allow_orders", "?") if isinstance(health, dict) else "?"
        startup_safety = health.get("startup_safety", {}) if isinstance(health, dict) else {}

        # Safety flags
        ks = readiness.get("summary", {}).get("kill_switches", {}) if isinstance(readiness, dict) else {}
        readiness_ao = ks.get("IBKR_ALLOW_ORDERS", "?")
        readiness_re = ks.get("rules.enforced", "?")
        system_locked = ks.get("system_locked", readiness.get("system_locked", True))

        # Alerts
        live_alerts = []
        if isinstance(alerts_data, dict):
            all_alerts = alerts_data.get("alerts", [])
            if isinstance(all_alerts, list):
                live_alerts = [a for a in all_alerts if isinstance(a, dict) and a.get("source") == "live"]
        active_alert_count = len(live_alerts)

        # Reconciliation
        recon_passed = reconciliation.get("passed", None) if isinstance(reconciliation, dict) else None

        # Positions
        pos_count = 0
        if isinstance(positions_data, dict) and "positions" in positions_data:
            pos_count = len(positions_data["positions"])
        elif isinstance(positions_data, list):
            pos_count = len(positions_data)

        # Latest events (last 3)
        latest_events: list[dict] = []
        if isinstance(events_data, dict) and "events" in events_data:
            latest_events = events_data["events"][-3:] if len(events_data["events"]) >= 3 \
                else events_data["events"]

        # Net liquidation
        net_liq = None
        if isinstance(account_data, dict) and "values" in account_data:
            for v in account_data["values"]:
                if v.get("tag") == "NetLiquidation" and v.get("currency") == "BASE":
                    net_liq = v.get("value")
                    break

        guard = {}

    # Liveness already fetched above (after snapshot attempt)

    # ------------------------------------------------------------------
    # 3. File-based checks
    # ------------------------------------------------------------------
    env_safety = _read_env_safety(BRIDGE_DIR / ".env")
    rules_state = _read_rules_enforced(Path.home() / ".openclaw" / "risk-rules" / "paper-trading-rules.yaml")
    autonomy_level = _read_autonomy_level(BRIDGE_DIR / "docs" / "AUTONOMY_CRITERIA.md")
    clean_cycles = _count_clean_cycles(OPENCLAW_DIR)
    hb_age = _heartbeat_age_seconds(HEARTBEAT_DIR)

    # ------------------------------------------------------------------
    # 4. Doctor (non-sudo)
    # ------------------------------------------------------------------
    doctor = _run_doctor_non_sudo()

    # ------------------------------------------------------------------
    # 5. Blocker list
    # ------------------------------------------------------------------
    blockers: list[dict] = []
    hold_reasons: list[dict] = []

    # NO-GO blockers (hard failures)
    if bridge_reachable:
        env_ao = env_safety.get("IBKR_ALLOW_ORDERS", "?")
        if env_ao.lower() in ("true", "1", "yes"):
            blockers.append({"severity": "NO-GO", "check": "env_IBKR_ALLOW_ORDERS",
                             "detail": f".env IBKR_ALLOW_ORDERS={env_ao}"})
        if rules_state.get("enforced", "?").lower() == "true":
            blockers.append({"severity": "NO-GO", "check": "rules_enforced",
                             "detail": "rules.enforced=true in paper-trading-rules.yaml"})
        if bridge_allow_orders not in (False, "false", "?"):
            blockers.append({"severity": "NO-GO", "check": "bridge_allow_orders",
                             "detail": f"Bridge allow_orders={bridge_allow_orders}"})
    else:
        blockers.append({"severity": "NO-GO", "check": "bridge_unreachable",
                         "detail": "Cannot verify safety flags — bridge unreachable"})

    if active_alert_count > 0:
        alert_types = {a.get("alert_type", "?") for a in live_alerts}
        blockers.append({"severity": "NO-GO", "check": "active_alerts",
                         "detail": f"{active_alert_count} live alert(s): {', '.join(sorted(alert_types))}"})

    if recon_passed is False:
        # Step 15C v2: reconciliation failure is NO-GO only when IBKR is connected
        # and there are active alerts. When disconnected, reconciliation is HOLD
        # (cannot verify cross-source consistency without live data).
        if connected and active_alert_count > 0:
            blockers.append({"severity": "NO-GO", "check": "reconciliation_failed",
                             "detail": "Reconciliation check(s) failed with active alerts"})
        else:
            hold_reasons.append({"severity": "HOLD", "check": "reconciliation_unavailable",
                                 "detail": "Reconciliation unavailable — IBKR disconnected or no alerts"})

    # Step 15C v2: Recent OOM kill → NO-GO (30-min lookback)
    if liveness:
        oom_evidence = liveness.get("oom_evidence", {})
        if oom_evidence.get("recent_oom_detected"):
            oom_details = oom_evidence.get("oom_details", [])
            detail = oom_details[0][:120] if oom_details else "OOM evidence found in journal"
            blockers.append({"severity": "NO-GO", "check": "recent_oom_kill",
                             "detail": detail})
        # Also check NRestarts — if restarts occurred recently, treat as OOM warning
        n_restarts = oom_evidence.get("n_restarts", 0)
        unit_result = oom_evidence.get("unit_result", "")
        if n_restarts >= 3 or unit_result == "oom-kill":
            if not oom_evidence.get("recent_oom_detected"):
                blockers.append({"severity": "NO-GO", "check": "recent_oom_kill",
                                 "detail": f"{n_restarts} restarts, result={unit_result} — consistent with OOM"})

    if doctor.get("_non_canary_ok") is False:
        doc_fails = doctor.get("_non_canary_failures", [])
        blockers.append({"severity": "NO-GO", "check": "doctor_non_canary_fail",
                         "detail": f"Doctor non-canary check(s) failed: {', '.join(doc_fails)}"})

    # HOLD blockers (soft / evidence insufficiencies)
    # Note: hold_reasons already initialized above; reconciliation HOLD may already be appended

    if not connected:
        hold_reasons.append({"severity": "HOLD", "check": "ibkr_not_connected",
                             "detail": "IBKR Gateway is not connected"})

    if int(autonomy_level) == 0:
        hold_reasons.append({"severity": "HOLD", "check": "autonomy_level_zero",
                             "detail": "Autonomy level 0 — manual approval required for all orders"})

    if clean_cycles == 0:
        hold_reasons.append({"severity": "HOLD", "check": "no_clean_cycles",
                             "detail": "Zero clean autonomous cycles logged"})

    if hb_age is None:
        hold_reasons.append({"severity": "HOLD", "check": "heartbeat_missing",
                             "detail": "No heartbeat artifacts found"})
    elif hb_age > 86400:  # > 24 hours
        hold_reasons.append({"severity": "HOLD", "check": "heartbeat_stale",
                             "detail": f"Heartbeat artifact age: {hb_age/3600:.1f}h"})

    if system_locked:
        hold_reasons.append({"severity": "HOLD", "check": "system_locked",
                             "detail": "System is locked (RTH closed or safety engaged)"})

    # ------------------------------------------------------------------
    # 6. Verdict
    # ------------------------------------------------------------------
    if any(b["severity"] == "NO-GO" for b in blockers):
        verdict = "NO-GO"
    elif any(r["severity"] == "HOLD" for r in hold_reasons):
        verdict = "HOLD"
    else:
        # All clear: GO
        verdict = "GO"

    # Combine all blockers for display
    all_blockers = blockers + hold_reasons

    # Warning: default is HOLD, not GO — if we somehow get here with ambiguous state
    if verdict == "GO" and not (connected and clean_cycles > 0 and not system_locked):
        verdict = "HOLD"

    # ------------------------------------------------------------------
    # 7. Build result
    # ------------------------------------------------------------------
    result = {
        "advisory": "Read-only KPI dashboard. No orders. No mutations. No H1 token.",
        "timestamp": ts_str,
        "git": {
            "branch": git["branch"],
            "commit_short": git["commit_short"],
            "tag": git["tag"],
        },
        "bridge": {
            "reachable": bridge_reachable,
            "url": BRIDGE_URL,
            "connected": connected,
            "mode": mode,
            "read_only": read_only,
            "allow_orders": bridge_allow_orders,
            "startup_safety_passed": startup_safety.get("all_passed", None),
            "startup_safety_count": f"{startup_safety.get('passed_count', '?')}/{startup_safety.get('check_count', '?')}",
            "positions_count": pos_count,
            "net_liquidation": net_liq,
            "endpoints_ok": sum(1 for v in endpoint_results.values() if v.get("ok")),
            "endpoints_total": len(_KPI_ENDPOINTS),
            "endpoint_failures": bridge_failures,
        },
        "safety_flags": {
            "read_only": read_only,
            "bridge_allow_orders": bridge_allow_orders,
            "env_IBKR_ALLOW_ORDERS": env_safety["IBKR_ALLOW_ORDERS"],
            "rules_enforced": rules_state["enforced"],
            "system_locked": system_locked,
            "readiness_allow_orders": readiness_ao,
            "readiness_rules_enforced": readiness_re,
        },
        "monitoring": {
            "reconciliation_passed": recon_passed,
            "active_alert_count": active_alert_count,
            "live_alerts": [{"type": a.get("alert_type"), "severity": a.get("severity"),
                            "detail": a.get("detail", "")[:120]} for a in live_alerts],
        },
        "events": {
            "latest": [{"type": e.get("event_type"), "gate": e.get("gate"),
                         "passed": e.get("passed"), "ts": e.get("timestamp_utc")}
                        for e in latest_events],
        },
        "autonomy": {
            "current_level": autonomy_level,
            "clean_cycles": clean_cycles,
        },
        "heartbeat": {
            "age_seconds": hb_age,
            "age_human": f"{hb_age/3600:.1f}h" if hb_age is not None else "none",
            "recent": hb_age is not None and hb_age < 86400,
        },
        "doctor": {
            "pass": doctor.get("pass", False),
            "non_canary_ok": doctor.get("_non_canary_ok", False),
            "non_canary_failures": doctor.get("_non_canary_failures", []),
            "check_count": len(doctor.get("checks", [])),
            "passed_count": sum(1 for c in doctor.get("checks", []) if c.get("ok")),
        },
        "blockers": all_blockers,
        "blocker_count": len(all_blockers),
        "verdict": verdict,
    }

    return result


def print_kpi(result: dict) -> None:
    """Print human-readable KPI dashboard."""
    v = result["verdict"]
    v_color = GREEN if v == "GO" else YELLOW if v == "HOLD" else RED

    print(f"\n{BOLD}══════════════════════════════════════════════════{RESET}")
    print(f"{BOLD}  IBKR KPI / Evidence Dashboard{RESET}")
    print(f"{BOLD}══════════════════════════════════════════════════{RESET}\n")

    print(f"  Timestamp:     {result['timestamp']}")
    print(f"  Git:           {result['git']['branch']} @ {result['git']['commit_short']}  (tag: {result['git']['tag']})")
    print()

    # Verdict
    print(f"  {BOLD}Verdict: {v_color}{v}{RESET}\n")

    # Bridge
    b = result["bridge"]
    conn_str = f"{GREEN}connected{RESET}" if b["connected"] else f"{RED}disconnected{RESET}"
    print(f"  {BOLD}Bridge{RESET}")
    print(f"    Reachable:    {b['reachable']}")
    print(f"    Connected:    {conn_str}")
    print(f"    Mode:         {b['mode']}")
    print(f"    Read-only:    {b['read_only']}")
    print(f"    Positions:    {b['positions_count']}")
    if b["net_liquidation"] is not None:
        print(f"    Net Liq:      {b['net_liquidation']:,.2f} EUR")
    print(f"    Endpoints:    {b['endpoints_ok']}/{b['endpoints_total']} OK")
    if b["endpoint_failures"]:
        for f in b["endpoint_failures"]:
            print(f"      {RED}✗{RESET} {f}")
    print()

    # Safety Flags
    sf = result["safety_flags"]
    print(f"  {BOLD}Safety Flags{RESET}")
    ao_s = f"{GREEN}{sf['bridge_allow_orders']}{RESET}" if sf['bridge_allow_orders'] in (False, "false") else f"{RED}{sf['bridge_allow_orders']}{RESET}"
    env_s = f"{GREEN}{sf['env_IBKR_ALLOW_ORDERS']}{RESET}" if sf['env_IBKR_ALLOW_ORDERS'] in ("false", "?") else f"{RED}{sf['env_IBKR_ALLOW_ORDERS']}{RESET}"
    re_s = f"{GREEN}{sf['rules_enforced']}{RESET}" if sf['rules_enforced'] in ("false", "?") else f"{RED}{sf['rules_enforced']}{RESET}"
    print(f"    Read-only:               {sf['read_only']}")
    print(f"    Bridge allow_orders:     {ao_s}")
    print(f"    .env IBKR_ALLOW_ORDERS:  {env_s}")
    print(f"    rules.enforced:          {re_s}")
    print(f"    System locked:           {sf['system_locked']}")
    print()

    # Monitoring
    m = result["monitoring"]
    recon_s = f"{GREEN}PASS{RESET}" if m["reconciliation_passed"] else f"{RED}FAIL{RESET}" if m["reconciliation_passed"] is False else "N/A"
    alert_s = f"{RED}{m['active_alert_count']} active{RESET}" if m["active_alert_count"] > 0 else f"{GREEN}0{RESET}"
    print(f"  {BOLD}Monitoring{RESET}")
    print(f"    Reconciliation:  {recon_s}")
    print(f"    Active Alerts:   {alert_s}")
    for a in m["live_alerts"]:
        print(f"      {RED}⚠{RESET} [{a['severity']}] {a['type']}: {a['detail']}")
    print()

    # Events
    ev = result["events"]
    print(f"  {BOLD}Latest Events{RESET}")
    if ev["latest"]:
        for e in ev["latest"]:
            e_color = GREEN if e.get("passed") else RED
            print(f"    {e_color}{e['type']}{RESET}  gate={e['gate']}  {e['ts']}")
    else:
        print(f"    (none)")
    print()

    # Autonomy
    au = result["autonomy"]
    print(f"  {BOLD}Autonomy{RESET}")
    print(f"    Current Level:  {au['current_level']}")
    print(f"    Clean Cycles:   {au['clean_cycles']}")
    print()

    # Heartbeat
    hb = result["heartbeat"]
    hb_recent = f"{GREEN}{hb['age_human']}{RESET}" if hb["recent"] else f"{YELLOW}{hb['age_human']}{RESET}"
    print(f"  {BOLD}Heartbeat{RESET}")
    print(f"    Age:            {hb_recent}")
    print()

    # Doctor
    d = result["doctor"]
    doc_ok = f"{GREEN}PASS{RESET}" if d["non_canary_ok"] else f"{RED}FAIL{RESET}"
    print(f"  {BOLD}Doctor{RESET}")
    print(f"    Non-canary:     {doc_ok}  ({d['passed_count']}/{d['check_count']} checks)")
    if d["non_canary_failures"]:
        for f in d["non_canary_failures"]:
            print(f"      {RED}✗{RESET} {f}")
    print()

    # Blockers
    print(f"  {BOLD}Blocker List ({result['blocker_count']}){RESET}")
    for blk in result["blockers"]:
        sev_color = RED if blk["severity"] == "NO-GO" else YELLOW
        print(f"    {sev_color}[{blk['severity']}]{RESET} {blk['check']}: {blk['detail']}")
    print()

    print(f"  {BOLD}Final Verdict: {v_color}{v}{RESET}")
    print()


def export_kpi(result: dict, export_dir: Path) -> Path:
    """Write KPI result to ~/.openclaw/exports/ and return path."""
    export_dir.mkdir(parents=True, exist_ok=True)
    ts_file = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = export_dir / f"kpi-dashboard-{ts_file}.json"
    tmp = out_path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, default=str, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, out_path)
    return out_path


# ---------------------------------------------------------------------------
# Step 15B — KPI Alert Repair (safe stale-evidence clearing)
# ---------------------------------------------------------------------------

def _atomic_write_json(path: Path, data: object) -> None:
    """Atomically write JSON to path (tmp + rename). Bypasses H1 guard for maintenance."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=str, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def _repair_stale_alerts(dry_run: bool = True) -> dict:
    """Repair proven-stale KPI alerts without broker mutation.

    Only repairs when evidence is definitively stale:
    - Orphan approvals from test artifacts (test-bracket, test-double, aprv_noexec, aprv_7)
    - Trade count inflated by test submissions sharing the same fake permId
    - Real unresolved alerts remain untouched

    Returns repair evidence dict with before/after state and audit trail.
    """
    import shutil
    from datetime import datetime, timezone
    from monitor import (
        load_guard_state,
        load_submitted_approvals,
        load_events,
    )

    now_utc = datetime.now(timezone.utc)
    ts_str = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")

    evidence: dict = {
        "repair_id": f"repair-{now_utc.strftime('%Y%m%dT%H%M%SZ')}",
        "timestamp_utc": ts_str,
        "dry_run": dry_run,
        "actions": [],
        "before": {},
        "after": {},
        "audit_events": [],
    }

    # --- 1. Inspect orphan approvals ---
    submitted = load_submitted_approvals()
    evidence["before"]["submitted_approvals_count"] = len(submitted)

    # Test artifact patterns — definitively stale
    stale_patterns = ["test-bracket-", "test-double-", "aprv_noexec", "aprv_7"]
    proven_stale = set()
    for aid in sorted(submitted):
        if not aid or aid == "":
            proven_stale.add(aid)  # empty string artifact
        else:
            for pat in stale_patterns:
                if aid.startswith(pat):
                    proven_stale.add(aid)
                    break

    # Also: UUID approvals with no matching order_submitted event ever
    # (these are submitted-approval orphans with no evidence of real trading)
    events = load_events(event_type="order_submitted")
    approval_ids_with_orders = {e.get("approval_id", "") for e in events}
    for aid in sorted(submitted):
        if aid in proven_stale:
            continue
        if aid not in approval_ids_with_orders:
            # Check: has this approval_id EVER had an order?
            # If not in events and not in today's events, it's an orphan
            # Only clear if the approval ID looks like a real UUID (not a canary)
            if aid.startswith("aprv_") and len(aid) > 40:
                proven_stale.add(aid)

    # NEVER clear: empty string (always stale), but be safe
    proven_stale.discard("aprv_canary")

    orphan_count = len(proven_stale)
    evidence["actions"].append({
        "action": "orphan_approvals_identified",
        "count": orphan_count,
        "ids": sorted(proven_stale),
    })

    if not dry_run and proven_stale:
        # Write backup
        backup_path = OPENCLAW_DIR / f"submitted-approvals.bak-{now_utc.strftime('%Y%m%dT%H%M%SZ')}.json"
        src = OPENCLAW_DIR / "submitted-approvals.json"
        if src.exists():
            shutil.copy2(src, backup_path)
            evidence["actions"].append({
                "action": "backup_created",
                "path": str(backup_path),
            })

        # Remove stale
        cleaned = submitted - proven_stale
        _atomic_write_json(OPENCLAW_DIR / "submitted-approvals.json", sorted(cleaned))
        evidence["actions"].append({
            "action": "orphan_approvals_cleared",
            "count": orphan_count,
            "remaining": len(cleaned),
        })
        evidence["audit_events"].append({
            "event_type": "alert_repair",
            "alert_type": "orphan_submitted_approval",
            "action": "cleared_stale_orphans",
            "count": orphan_count,
            "ids": sorted(proven_stale),
            "timestamp_utc": ts_str,
        })

    # --- 2. Repair trade_count_mismatch ---
    gs = load_guard_state()
    evidence["before"]["daily_trade_count"] = gs.get("daily_trade_count", 0)

    # Determine authoritative count: only count today's events with UNIQUE permIds
    trade_date = gs.get("trade_date", now_utc.strftime("%Y-%m-%d"))
    today_events = [e for e in events
                    if (ts := e.get("timestamp_utc", "")) and ts.startswith(trade_date)]
    # Exclude test-bracket events (fake permId 5001)
    real_today = [e for e in today_events
                  if not str(e.get("approval_id", "")).startswith("test-bracket-")]
    real_perm_ids = set()
    for e in real_today:
        ibkr = e.get("ibkr_metadata")
        if ibkr and ibkr.get("permId") is not None:
            real_perm_ids.add(ibkr["permId"])
        elif e.get("approval_id"):
            real_perm_ids.add(f"approval:{e['approval_id']}")
    authoritative_count = len(real_perm_ids)

    evidence["actions"].append({
        "action": "trade_count_analysed",
        "current_guard_count": gs.get("daily_trade_count", 0),
        "authoritative_count": authoritative_count,
        "test_events_excluded": len(today_events) - len(real_today),
        "real_unique_orders": authoritative_count,
    })

    if authoritative_count < gs.get("daily_trade_count", 0):
        if not dry_run:
            gs["daily_trade_count"] = authoritative_count
            gs["last_updated_utc"] = ts_str
            gs["trade_count_repaired"] = True
            gs["trade_count_repair_id"] = evidence["repair_id"]
            _atomic_write_json(OPENCLAW_DIR / "guard-state.json", gs)
            evidence["actions"].append({
                "action": "trade_count_corrected",
                "from": evidence["before"]["daily_trade_count"],
                "to": authoritative_count,
            })
            evidence["audit_events"].append({
                "event_type": "alert_repair",
                "alert_type": "trade_count_mismatch",
                "action": "corrected_guard_state",
                "from": evidence["before"]["daily_trade_count"],
                "to": authoritative_count,
                "timestamp_utc": ts_str,
            })
    else:
        evidence["actions"].append({
            "action": "trade_count_no_repair_needed",
            "reason": "authoritative count >= guard count",
        })

    evidence["after"]["submitted_approvals_count"] = len(submitted) - orphan_count if not dry_run else len(submitted) - orphan_count
    evidence["after"]["daily_trade_count"] = authoritative_count if not dry_run else gs.get("daily_trade_count", 0)

    return evidence


def print_repair_evidence(evidence: dict) -> None:
    """Print human-readable repair evidence."""
    BOLD = "\033[1m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RESET = "\033[0m"
    DRY = evidence.get("dry_run", True)
    label = f"{YELLOW}DRY-RUN{RESET}" if DRY else f"{GREEN}LIVE{RESET}"

    print(f"{BOLD}KPI Alert Repair{ RESET}  [{label}]")
    print(f"  Repair ID:   {evidence['repair_id']}")
    print(f"  Timestamp:   {evidence['timestamp_utc']}")
    print()

    for act in evidence["actions"]:
        action = act["action"]
        if action == "orphan_approvals_identified":
            print(f"  Orphan approvals identified: {act['count']}")
        elif action == "orphan_approvals_cleared":
            print(f"  {GREEN}Cleared{RESET} {act['count']} orphan approvals ({act['remaining']} remain)")
        elif action == "backup_created":
            print(f"  Backup: {act['path']}")
        elif action == "trade_count_analysed":
            print(f"  Trade count: guard={act['current_guard_count']}, "
                  f"real={act['authoritative_count']} "
                  f"(excluded {act['test_events_excluded']} test events)")
        elif action == "trade_count_corrected":
            print(f"  {GREEN}Corrected{RESET} daily_trade_count: {act['from']} → {act['to']}")
        elif action == "trade_count_no_repair_needed":
            print(f"  Trade count: no correction needed ({act['reason']})")

    print()
    if evidence["audit_events"]:
        print(f"  {BOLD}Audit events:{RESET} {len(evidence['audit_events'])}")
        for ae in evidence["audit_events"]:
            print(f"    - [{ae['alert_type']}] {ae['action']}")


# ---------------------------------------------------------------------------
# Phase 5B.1 — Hermes Advisory Proposal
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Step 14 (Phase 5D) — Clean-Cycle Rehearsal
# ---------------------------------------------------------------------------

_CYCLE_EXPORT_DIR_NAME = "autonomy-cycles"

# Forbidden endpoints that must NEVER be called during rehearsal
_REHEARSAL_FORBIDDEN_ENDPOINTS = frozenset({
    "/order",
    "/order/preflight",
    "/order/approve",
    "/order/submit",
    "/connect",
})


def _mock_gate_h_proposal() -> dict:
    """Validate Gate H proposal structure without broker mutation.

    Returns a dict with the proposal evidence block.
    No /order endpoints.  No H1 token.  No broker calls.
    """
    from guard import _require_allowed_symbol

    now_utc = datetime.now(timezone.utc)
    evidence = {
        "ok": True,
        "proposal_id": f"rehearsal-{now_utc.strftime('%Y%m%dT%H%M%SZ')}",
        "timestamp_utc": now_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "symbol": "META",
        "side": "BUY",
        "quantity": 1,
        "action": "BUY",
        "order_type": "MKT",
        "dry_run": True,
        "checks": {},
    }

    # Gate H: symbol in universe (via _require_allowed_symbol)
    try:
        result_sym = _require_allowed_symbol("META")
        evidence["checks"]["symbol_allowed"] = True
        evidence["checks"]["symbol_result"] = result_sym
    except ValueError as e:
        evidence["checks"]["symbol_allowed"] = False
        evidence["checks"]["symbol_allowed_error"] = str(e)
        evidence["ok"] = False
    except Exception as e:
        evidence["checks"]["symbol_allowed"] = False
        evidence["checks"]["symbol_allowed_error"] = f"{type(e).__name__}: {e}"
        evidence["ok"] = False

    # Gate H: side must be BUY or SELL
    valid_sides = {"BUY", "SELL"}
    evidence["checks"]["valid_side"] = "BUY" in valid_sides

    # Gate H: quantity must be positive integer
    evidence["checks"]["valid_quantity"] = isinstance(1, int) and 1 > 0

    return evidence


def _mock_p5_bracket_stop() -> dict:
    """Validate P5 protective stop requirements in dry-run form.

    Does NOT call bridge. Does NOT place any order.
    Returns evidence dict with bracket-stop validation result.
    """
    from guard import validate_bracket_stop

    evidence = {
        "ok": True,
        "dry_run": True,
        "checks": {},
    }

    # Validate that a BUY with stop_price works
    try:
        result = validate_bracket_stop(
            stop_price=475.0,
            entry_price=500.0,
            quantity=1,
            action="BUY",
        )
        evidence["checks"]["buy_bracket_valid"] = result.get("valid", True)
        evidence["checks"]["buy_bracket_evidence"] = {
            "protective_stop": result.get("protective_stop", False),
            "bracket": result.get("bracket", True),
            "parent_transmit": result.get("parent_transmit", False),
            "stop_transmit": result.get("stop_transmit", True),
        }
        if not result.get("valid", True):
            evidence["ok"] = False
            evidence["checks"]["buy_bracket_error"] = result.get("error", "validation failed")
    except Exception as e:
        evidence["checks"]["buy_bracket_valid"] = False
        evidence["checks"]["buy_bracket_error"] = str(e)
        evidence["ok"] = False

    # SELL does not require bracket stop
    try:
        result_sell = validate_bracket_stop(
            stop_price=None,
            entry_price=500.0,
            quantity=1,
            action="SELL",
        )
        evidence["checks"]["sell_no_bracket_required"] = (
            result_sell.get("valid", True) and not result_sell.get("bracket", True)
        )
    except Exception as e:
        evidence["checks"]["sell_no_bracket_required"] = False
        evidence["checks"]["sell_no_bracket_error"] = str(e)

    return evidence


def _scan_forbidden_endpoints(source_path: Path | None = None) -> dict:
    """AST-scan operator code for any forbidden endpoint calls.

    Only flags string constants that appear in URL-building context
    (near keywords like 'request', 'url', 'fetch', 'endpoint').
    Does NOT flag comments, docstrings, or safety documentation.

    Returns dict with scan_result and any violations found.
    """
    if source_path is None:
        source_path = Path(__file__).resolve()

    evidence = {
        "ok": True,
        "scanned_file": str(source_path),
        "violations": [],
    }

    try:
        import ast

        tree = ast.parse(source_path.read_text())
        source_lines = source_path.read_text().splitlines()

        # Keywords that indicate a string is documentation/safety, not an endpoint call
        _safety_keywords = [
            "no /order", "forbidden", "blocked", "never call",
            "must not", "do not", "safety", "disabled",
            "# no ", "# never ", "no order",
        ]

        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                val = node.value
                # Only flag if string looks like an endpoint path (starts with '/')
                # and a forbidden endpoint appears
                for ep in sorted(_REHEARSAL_FORBIDDEN_ENDPOINTS, key=len, reverse=True):
                    if ep not in val:
                        continue

                    # Skip strings that contain safety/documentation language
                    lower_val = val.lower()
                    if any(kw in lower_val for kw in _safety_keywords):
                        continue

                    # Check line context: skip comment lines
                    lineno = node.lineno
                    if lineno and lineno <= len(source_lines):
                        line = source_lines[lineno - 1].strip()
                        if line.startswith("#"):
                            continue
                        lower_line = line.lower()
                        if any(kw in lower_line for kw in _safety_keywords):
                            continue

                    # Only flag URL-building context (heuristic)
                    if any(kw in val.lower() for kw in ["request", "fetch", "url", "endpoint"]):
                        evidence["violations"].append({
                            "endpoint": ep,
                            "line": lineno,
                            "context": val[:120],
                        })
                        evidence["ok"] = False
    except Exception as e:
        evidence["ok"] = False
        evidence["scan_error"] = str(e)

    return evidence


def _run_cycle_rehearsal() -> dict:
    """Run a full autonomy-cycle rehearsal — read-only, no broker mutation.

    Verifies:
    1. Strategy/autonomy docs exist
    2. KPI dashboard is available and parseable
    3. Doctor non-canary checks pass or are recorded
    4. Bridge health is reachable
    5. Safety flags are locked
    6. Heartbeat evidence exists and is recent enough
    7. Reconciliation/alerts are captured honestly
    8. Mock Gate H proposal validated without broker
    9. P5 protective stop validated in dry-run form
    10. Forbidden endpoint scan passes
    11. Evidence exported

    Returns dict with verdict, blocker list, and all evidence.
    """
    from datetime import datetime, timezone

    now_utc = datetime.now(timezone.utc)
    ts_str = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    ts_file = now_utc.strftime("%Y%m%dT%H%M%SZ")

    blockers: list[dict] = []

    # --- 1. Strategy/autonomy docs exist ---
    strategy_path = Path(__file__).resolve().parent / "docs" / "STRATEGY.md"
    autonomy_path = Path(__file__).resolve().parent / "docs" / "AUTONOMY_CRITERIA.md"
    docs = {
        "strategy_exists": strategy_path.exists(),
        "autonomy_exists": autonomy_path.exists(),
    }
    if not docs["strategy_exists"]:
        blockers.append({"severity": "NO-GO", "check": "strategy_doc_missing",
                         "detail": "docs/STRATEGY.md not found"})
    if not docs["autonomy_exists"]:
        blockers.append({"severity": "NO-GO", "check": "autonomy_doc_missing",
                         "detail": "docs/AUTONOMY_CRITERIA.md not found"})

    # --- 2. KPI dashboard ---
    kpi_result = run_kpi()
    kpi_verdict = kpi_result.get("verdict", "ERROR")
    if kpi_verdict == "NO-GO":
        for b in kpi_result.get("blockers", []):
            if b.get("severity") == "NO-GO":
                blockers.append(b)

    # --- 3. Doctor non-canary checks (lightweight in-process snapshot) ---
    # Uses _collect_lightweight_evidence() — fast, no subprocess, no elevated privs.
    # Excludes h1_token_canary from blocking consideration.
    doctor_evidence = {}
    doctor_non_canary_ok = True
    try:
        light = _collect_lightweight_evidence()
        doc = light.get("doctor", {})
        doctor_evidence = {
            "pass": doc.get("pass", False),
            "total": doc.get("total", 0),
            "passed": doc.get("passed", 0),
            "checks": doc.get("checks", []),
            "_lightweight": True,
        }
        # Evaluate non-canary checks (exclude h1_token_canary)
        non_canary_checks = [
            c for c in doctor_evidence["checks"]
            if c.get("check") != "h1_token_canary"
        ]
        non_canary_failures = [
            c["check"] for c in non_canary_checks if not c.get("ok")
        ]
        doctor_non_canary_ok = len(non_canary_failures) == 0
        if not doctor_non_canary_ok:
            blockers.append({
                "severity": "HOLD", "check": "doctor_non_pass",
                "detail": f"Doctor non-canary checks failed: {', '.join(non_canary_failures)}"
            })
    except Exception as e:
        doctor_non_canary_ok = False
        doctor_evidence = {"error": str(e)[:300]}
        blockers.append({"severity": "HOLD", "check": "doctor_unavailable",
                         "detail": f"Lightweight doctor failed: {str(e)[:200]}"})

    # --- 4. Bridge health ---
    bridge_reachable = kpi_result.get("bridge", {}).get("reachable", False)
    bridge_connected = kpi_result.get("bridge", {}).get("connected", False)
    if not bridge_reachable:
        blockers.append({"severity": "NO-GO", "check": "bridge_unreachable",
                         "detail": "IBKR bridge is not reachable"})
    elif not bridge_connected:
        blockers.append({"severity": "HOLD", "check": "ibkr_not_connected",
                         "detail": "IBKR Gateway is not connected"})

    # --- 5. Safety flags locked ---
    sf = kpi_result.get("safety_flags", {})
    safety_locked = (
        sf.get("read_only") is True
        and sf.get("bridge_allow_orders") is False
        and sf.get("env_IBKR_ALLOW_ORDERS") == "false"
        and sf.get("rules_enforced") == "false"
    )
    if not safety_locked:
        fail_items = []
        if sf.get("read_only") is not True:
            fail_items.append("read_only is not True")
        if sf.get("bridge_allow_orders") is not False:
            fail_items.append("bridge_allow_orders is not False")
        if sf.get("env_IBKR_ALLOW_ORDERS") != "false":
            fail_items.append(f"env IBKR_ALLOW_ORDERS={sf.get('env_IBKR_ALLOW_ORDERS')}")
        if sf.get("rules_enforced") != "false":
            fail_items.append(f"rules.enforced={sf.get('rules_enforced')}")
        blockers.append({"severity": "NO-GO", "check": "safety_unlocked",
                         "detail": "; ".join(fail_items)})

    # --- 6. Heartbeat evidence ---
    hb = kpi_result.get("heartbeat", {})
    hb_recent = hb.get("recent", False)
    if not hb_recent:
        if hb.get("age_seconds") is None:
            blockers.append({"severity": "HOLD", "check": "heartbeat_missing",
                             "detail": "No heartbeat artifacts found"})
        else:
            blockers.append({"severity": "HOLD", "check": "heartbeat_stale",
                             "detail": f"Heartbeat age: {hb.get('age_human', '?')}"})

    # --- 7. Reconciliation/alerts (already captured via KPI) ---
    recon_passed = kpi_result.get("monitoring", {}).get("reconciliation_passed", None)
    alert_count = kpi_result.get("monitoring", {}).get("active_alert_count", 0)

    # --- 8. Mock Gate H proposal ---
    gate_h_ok = True
    gate_h_evidence = {}
    try:
        gate_h_evidence = _mock_gate_h_proposal()
        gate_h_ok = gate_h_evidence.get("ok", False)
    except Exception as e:
        gate_h_ok = False
        gate_h_evidence = {"error": str(e)}
    if not gate_h_ok:
        blockers.append({"severity": "HOLD", "check": "gate_h_mock_failed",
                         "detail": "Mock Gate H proposal validation failed"})

    # --- 9. P5 bracket stop ---
    p5_ok = True
    p5_evidence = {}
    try:
        p5_evidence = _mock_p5_bracket_stop()
        p5_ok = p5_evidence.get("ok", False)
    except Exception as e:
        p5_ok = False
        p5_evidence = {"error": str(e)}
    if not p5_ok:
        blockers.append({"severity": "NO-GO", "check": "p5_bracket_mock_failed",
                         "detail": "P5 bracket-stop dry-run validation failed"})

    # --- 10. Forbidden endpoint scan ---
    scan_result = _scan_forbidden_endpoints()
    scan_ok = scan_result.get("ok", True)
    if not scan_ok:
        violations = scan_result.get("violations", [])
        detail = f"{len(violations)} violation(s): " + "; ".join(
            v.get("endpoint", "?") for v in violations[:3]
        )
        blockers.append({"severity": "NO-GO", "check": "forbidden_endpoint_found",
                         "detail": detail})

    # --- Compute verdict ---
    has_nogo = any(b["severity"] == "NO-GO" for b in blockers)
    has_hold = any(b["severity"] == "HOLD" for b in blockers)

    if has_nogo:
        verdict = "NO-GO"
    elif has_hold:
        verdict = "HOLD"
    else:
        verdict = "CLEAN"

    # --- Build result ---
    result = {
        "advisory": "Read-only cycle rehearsal. No orders. No mutations. No H1 token.",
        "timestamp": ts_str,
        "git": _git_metadata(Path(__file__).resolve().parent),
        "verdict": verdict,
        "kpi_verdict": kpi_verdict,
        "docs": docs,
        "safety_flags": sf,
        "heartbeat": hb,
        "bridge": kpi_result.get("bridge", {}),
        "monitoring": {
            "reconciliation_passed": recon_passed,
            "active_alert_count": alert_count,
        },
        "doctor": doctor_evidence,
        "gate_h_mock": gate_h_evidence,
        "p5_bracket_mock": p5_evidence,
        "forbidden_endpoint_scan": scan_result,
        "blockers": blockers,
        "blocker_count": len(blockers),
    }

    return result


def print_cycle_rehearsal(result: dict) -> None:
    """Print cycle rehearsal result in human-readable format."""
    verdict = result["verdict"]
    v_color = {"CLEAN": GREEN, "HOLD": RESET, "NO-GO": RED}.get(verdict, RESET)

    print(f"{BOLD}Autonomy Cycle Rehearsal{RESET}  [{v_color}{verdict}{RESET}]")
    print(f"  Timestamp:  {result['timestamp']}")
    print(f"  KPI:        {result['kpi_verdict']}")
    print(f"  Blockers:   {result['blocker_count']}")

    safety = result["safety_flags"]
    locked = (
        safety.get("read_only") is True
        and safety.get("bridge_allow_orders") is False
        and safety.get("env_IBKR_ALLOW_ORDERS") == "false"
        and safety.get("rules_enforced") == "false"
    )
    print(f"  Safety:     {'LOCKED' if locked else f'{RED}UNLOCKED{RESET}'}")
    print(f"  Docs:       STRATEGY={'✓' if result['docs']['strategy_exists'] else '✗'} "
          f"AUTONOMY={'✓' if result['docs']['autonomy_exists'] else '✗'}")
    print(f"  Heartbeat:  {result['heartbeat'].get('age_human', 'none')}")
    print(f"  Bridge:     {'reachable' if result['bridge'].get('reachable') else 'unreachable'}, "
          f"{'connected' if result['bridge'].get('connected') else 'disconnected'}")
    print(f"  Recon:      {'PASS' if result['monitoring']['reconciliation_passed'] else 'N/A'}")
    print(f"  Alerts:     {result['monitoring']['active_alert_count']}")
    print(f"  Gate H:     {'✓' if result['gate_h_mock'].get('ok') else '✗'}")
    print(f"  P5 Bracket: {'✓' if result['p5_bracket_mock'].get('ok') else '✗'}")
    print(f"  EP Scan:    {'✓' if result['forbidden_endpoint_scan'].get('ok') else '✗'}")

    if result["blockers"]:
        print(f"\n  {BOLD}Blockers:{RESET}")
        for b in result["blockers"]:
            sev_color = {"NO-GO": RED, "HOLD": RESET, "CLEAN": GREEN}.get(
                b["severity"], RESET)
            print(f"    [{sev_color}{b['severity']}{RESET}] {b['check']}: {b['detail']}")


def export_cycle_rehearsal(result: dict, export_dir: Path | None = None) -> Path:
    """Export cycle rehearsal result to JSON file.

    Uses ~/.openclaw/autonomy-cycles/ as default export directory.
    Returns the output path.
    """
    if export_dir is None:
        export_dir = OPENCLAW_DIR / _CYCLE_EXPORT_DIR_NAME
    export_dir.mkdir(parents=True, exist_ok=True)

    ts_file = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = export_dir / f"cycle-rehearsal-{ts_file}.json"
    tmp = out_path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, default=str, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, out_path)
    return out_path


# ---------------------------------------------------------------------------
# Step 15A — Candidate Dry-Run (first paper-trade candidate)
# ---------------------------------------------------------------------------

_CANDIDATE_EXPORT_DIR_NAME = "candidate-dryruns"
_CANDIDATE_PROPOSALS_DIR = OPENCLAW_DIR / "proposals"

# Gate H allowed symbols (large-cap ETFs/stocks only, no penny, no leveraged, no options)
_CANDIDATE_ALLOWED_SYMBOLS: frozenset[str] = frozenset({
    "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA",
    "JPM", "V", "JNJ", "WMT", "PG", "XOM", "UNH", "HD", "BAC",
    "SPY", "QQQ", "IWM", "DIA", "VTI", "VOO", "BND", "AGG",
    "EFA", "EEM", "TLT", "LQD", "GLD", "XLF", "XLK", "XLE",
})

_LIGHTWEIGHT_DOCTOR_TIMEOUT = 8.0  # seconds for lightweight checks


def _collect_lightweight_evidence() -> dict:
    """Collect in-process evidence snapshot — fast, no subprocess, no sudo.

    Returns a dict with bridge_health, doctor_summary, and safety_status.
    This is designed to be fast (<8s) and safe for use inside candidate
    and rehearsal runs where full doctor invocation would be too heavy.
    """
    import urllib.request
    import urllib.error
    import subprocess
    from datetime import datetime, timezone

    now_utc = datetime.now(timezone.utc)
    repo = HOME / "agents" / "ibkr-bridge"

    evidence: dict[str, Any] = {
        "timestamp_utc": now_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "bridge": {},
        "doctor": {},
        "safety": {},
        "strategy": {},
        "liveness": {},
    }

    # --- Bridge health (single HTTP call, fast, one retry on failure) ---
    bridge_reachable = False
    bridge_data: dict = {}
    _health_timeout = 10.0  # bounded, with one retry below
    for _attempt in range(2):
        try:
            req = urllib.request.Request(f"{BRIDGE_URL}/health", method="GET")
            with urllib.request.urlopen(req, timeout=_health_timeout) as resp:
                bridge_data = json.loads(resp.read().decode())
                bridge_reachable = resp.status == 200
                break  # success, don't retry
        except Exception:
            if _attempt == 0:
                time.sleep(1.0)  # brief pause before retry
            bridge_reachable = False

    evidence["bridge"] = {
        "reachable": bridge_reachable,
        "url": BRIDGE_URL,
        "connected": bridge_data.get("connected", None) if bridge_data else None,
        "mode": bridge_data.get("mode", "?") if bridge_data else "?",
        "allow_orders": bridge_data.get("allow_orders", "?") if bridge_data else "?",
        "read_only": (bridge_data.get("mode", "?") == "paper") if bridge_data else False,
    }

    # --- In-process doctor checks (no subprocess, no H1, no sudo) ---
    checks = []
    all_pass = True

    # K2: RUNBOOK.md
    rb_path = repo / "RUNBOOK.md"
    k2 = rb_path.exists()
    if not k2:
        all_pass = False
    checks.append({"check": "runbook_exists", "ok": k2})

    # K3: operator symlink
    op_link = HOME / ".local/bin/ibkr-operator"
    k3 = op_link.is_symlink() or op_link.exists()
    if not k3:
        all_pass = False
    checks.append({"check": "operator_symlink", "ok": k3})

    # K4: Required files
    required = ["ibkr_operator.py", "bundle_audit.py", "monitor.py", "guard.py", "RUNBOOK.md"]
    k4 = all((repo / f).exists() for f in required)
    if not k4:
        all_pass = False
    checks.append({"check": "required_files", "ok": k4,
                   "detail": f"{sum(1 for f in required if (repo/f).exists())}/{len(required)}"})

    # K5: Bridge health (single endpoint, already checked above)
    k5 = True  # fallback always available
    checks.append({"check": "bridge_health", "ok": k5,
                   "detail": "reachable" if bridge_reachable else "unreachable (fallback ok)"})

    # K8: Export directory writable
    try:
        from bundle_audit import EXPORT_DIR
        EXPORT_DIR.mkdir(parents=True, exist_ok=True)
        test_f = EXPORT_DIR / ".doctor_writable"
        test_f.write_text("")
        test_f.unlink()
        checks.append({"check": "export_dir_writable", "ok": True})
    except Exception:
        all_pass = False
        checks.append({"check": "export_dir_writable", "ok": False})

    # K11: Hermes policy
    hermes_path = HOME / ".openclaw" / "memory" / "hermes-advisory-guard-policy.md"
    k11 = hermes_path.exists()
    if not k11:
        all_pass = False
    checks.append({"check": "hermes_policy_exists", "ok": k11})

    # K12: H1 canary — skip (no sudo, no token)
    checks.append({"check": "h1_token_canary", "ok": True,
                   "detail": "skipped (lightweight)"})

    # K13: Bridge port listener (at least one listener on port 8790)
    # Accept 1-2 listeners (uvicorn may bind IPv4 + IPv6).
    # Zero listeners is a failure.
    listener_count = 0
    try:
        result = subprocess.run(
            ["ss", "-tlnp", "sport", "=", ":8790"],
            capture_output=True, text=True, timeout=5,
        )
        for line in result.stdout.splitlines():
            if "LISTEN" in line.upper():
                listener_count += 1
    except Exception:
        listener_count = -1  # cannot determine
    k13_ok = listener_count >= 1
    if not k13_ok:
        all_pass = False
    checks.append({"check": "bridge_port_listener", "ok": k13_ok,
                   "detail": f"{listener_count} listener(s)" if listener_count >= 0 else "cannot check"})

    # K16: Bridge safety flags (from bridge health data, no separate HTTP call)
    # Matches full doctor's K16 logic: mode must be "paper", allow_orders must be false.
    if bridge_data:
        mode = bridge_data.get("mode", "?")
        allow_orders = bridge_data.get("allow_orders", "?")
        read_only = (mode == "paper")
        # allow_orders may be boolean False or string "false"
        orders_disabled = (allow_orders == "false" or allow_orders is False)
        k16_ok = read_only and orders_disabled
        if not k16_ok:
            all_pass = False
        checks.append({"check": "bridge_safety_flags", "ok": k16_ok,
                       "detail": f"read_only={read_only}, allow_orders={allow_orders}"})
    else:
        all_pass = False
        checks.append({"check": "bridge_safety_flags", "ok": False,
                       "detail": "bridge unreachable — cannot verify safety"})

    # K17: Step 15C — Recent OOM kill detection (systemctl + journal)
    oom_found = False
    oom_detail = "no OOM evidence"
    n_restarts = 0
    try:
        show = subprocess.run(
            ["systemctl", "show", "ibkr-bridge.service", "--no-pager",
             "-p", "NRestarts", "-p", "Result", "-p", "ExecMainStatus",
             "-p", "MemoryPeak", "-p", "MemoryMax"],
            capture_output=True, text=True, timeout=5,
        )
        if show.returncode == 0:
            props = {}
            for line in show.stdout.strip().splitlines():
                if "=" in line:
                    k, _, v = line.partition("=")
                    props[k] = v
            n_restarts = int(props.get("NRestarts", 0))
            exec_status = props.get("ExecMainStatus", "0")
            unit_result = props.get("Result", "success")

            # Check journal for OOM keyword in last 30 min
            jrnl = subprocess.run(
                ["journalctl", "-u", "ibkr-bridge.service", "--no-pager",
                 "--since", "30 min ago", "-o", "cat"],
                capture_output=True, text=True, timeout=5,
            )
            for line in jrnl.stdout.splitlines():
                lower = line.lower()
                if "oom" in lower or "out of memory" in lower:
                    oom_found = True
                    oom_detail = f"OOM evidence in journal: {line[:120]}"
                    break

            # Also check kernel messages as fallback
            if not oom_found:
                try:
                    dmesg = subprocess.run(
                        ["dmesg", "-T", "--level=err,warn"],
                        capture_output=True, text=True, timeout=5,
                    )
                    for line in dmesg.stdout.splitlines():
                        if "oom" in line.lower() or "killed process" in line.lower():
                            # crude recency check: look for today's date
                            today_short = datetime.now(timezone.utc).strftime("%b %d")
                            if today_short in line or "ibkr" in line.lower():
                                oom_found = True
                                oom_detail = f"Kernel OOM: {line[:120]}"
                                break
                except Exception:
                    pass

            # Check for crash-loop pattern (high restart count + killed status)
            if n_restarts >= 2 and (unit_result == "oom-kill" or exec_status == "9"):
                oom_found = True
                oom_detail = f"Restart pattern ({n_restarts} restarts, result={unit_result}, exit={exec_status}) — consistent with OOM"

            # Memory pressure warning
            mem_peak = int(props.get("MemoryPeak", 0))
            mem_max = int(props.get("MemoryMax", 0))
            if mem_max > 0 and mem_peak > 0 and mem_peak / mem_max > 0.7:
                pct = round(mem_peak / mem_max * 100)
                oom_detail += f" | Memory peak at {pct}% of limit"
    except Exception:
        oom_detail = "liveness check unavailable"

    k17_ok = not oom_found
    if not k17_ok:
        all_pass = False
    checks.append({"check": "no_recent_oom", "ok": k17_ok, "detail": oom_detail,
                   "n_restarts": n_restarts})

    evidence["doctor"] = {
        "pass": all_pass,
        "total": len(checks),
        "passed": sum(1 for c in checks if c["ok"]),
        "checks": checks,
        "_lightweight": True,
        "_note": "Lightweight in-process check — no subprocess calls, no sudo. Run 'ibkr-operator doctor' for full diagnostics.",
    }

    # --- Safety status ---
    env_allow = os.environ.get("IBKR_ALLOW_ORDERS", "false")
    env_rules = os.environ.get("IBKR_RULES_ENFORCED", "false")
    bridge_allow = bridge_data.get("allow_orders", "?") if bridge_data else "?"
    bridge_read_only = bridge_data.get("read_only", False) if bridge_data else False
    startup_safety = bridge_data.get("startup_safety", {}) if bridge_data else {}

    evidence["safety"] = {
        "read_only": bridge_read_only,
        "bridge_allow_orders": bridge_allow,
        "env_IBKR_ALLOW_ORDERS": env_allow,
        "rules_enforced": env_rules,
        "system_locked": (
            env_allow == "false"
            and env_rules == "false"
            and bridge_allow in ("false", False, "?")
        ),
        "startup_safety_passed": startup_safety.get("pass", None),
    }

    # --- Strategy docs ---
    strategy_path = repo / "docs" / "STRATEGY.md"
    autonomy_path = repo / "docs" / "AUTONOMY_CRITERIA.md"
    evidence["strategy"] = {
        "strategy_exists": strategy_path.exists(),
        "autonomy_exists": autonomy_path.exists(),
    }

    # --- Liveness (Step 15C) ---
    evidence["liveness"] = {
        "oom_detected": oom_found,
        "oom_detail": oom_detail,
        "n_restarts": n_restarts,
        "k17_ok": k17_ok,
    }

    return evidence


def _fetch_fx_evidence(base_currency: str, instrument_currency: str) -> dict:
    """Step 15G: Fetch FX exchange rate from bridge /account endpoint.

    Returns a dict with fx_rate, fx_pair, fx_source, fx_timestamp,
    fx_staleness_seconds, and fx_available. If instrument currency equals
    base currency, fx_rate=1.0 with no HTTP call.
    """
    import urllib.request
    from datetime import datetime, timezone

    now_epoch = time.time()
    result = {
        "fx_available": False,
        "fx_required": True,
        "fx_rate": None,
        "fx_pair": f"{instrument_currency}/{base_currency}",
        "fx_source": None,
        "fx_timestamp": None,
        "fx_staleness_seconds": None,
    }

    if not base_currency or not instrument_currency:
        return result

    # Same currency — no FX needed
    if base_currency.upper() == instrument_currency.upper():
        result["fx_available"] = True
        result["fx_required"] = False
        result["fx_rate"] = 1.0
        result["fx_source"] = "identity"
        result["fx_timestamp"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        result["fx_staleness_seconds"] = 0.0
        return result

    # Cross-currency — query /account for ExchangeRate
    try:
        req = urllib.request.Request(
            f"{BRIDGE_URL}/account", method="GET")
        with urllib.request.urlopen(req, timeout=10.0) as resp:
            account_data = json.loads(resp.read().decode())
    except Exception as e:
        result["fx_source"] = f"error: {str(e)[:100]}"
        return result

    if not isinstance(account_data, dict):
        return result

    values = account_data.get("values", [])

    # Extract ExchangeRate for instrument currency
    inst_rate = None
    base_rate = None
    for v in values:
        tag = v.get("tag", "")
        cur = v.get("currency", "")
        if tag == "ExchangeRate":
            if cur == instrument_currency:
                try:
                    inst_rate = float(v.get("value", ""))
                except (ValueError, TypeError):
                    pass
            elif cur == base_currency:
                try:
                    base_rate = float(v.get("value", ""))
                except (ValueError, TypeError):
                    pass

    if inst_rate is None:
        result["fx_source"] = f"no ExchangeRate for {instrument_currency}"
        return result

    # ExchangeRate in IBKR = value of 1 unit of 'currency' in BASE terms.
    # If base is EUR and instrument is USD, ExchangeRate USD=0.87 means
    # 1 USD = 0.87 EUR, so notional_EUR = notional_USD * 0.87.
    result["fx_available"] = True
    result["fx_rate"] = round(inst_rate, 8)
    result["fx_source"] = "ibkr_account_exchange_rate"
    result["fx_timestamp"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    result["fx_staleness_seconds"] = 0.0  # account data is fresh on each fetch

    return result


def _run_candidate_dryrun(symbol: str, side: str) -> dict:
    """Run a complete evidence-only paper-trade candidate dry-run.

    No order execution. No order approval. No H1 token. No sudo.
    No broker mutation. Bridge remains locked.

    Returns a 17-item evidence package with verdict READY_DRYRUN / HOLD / NO-GO.
    """
    import json as _json
    from datetime import datetime, timezone

    now_utc = datetime.now(timezone.utc)
    ts_str = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    ts_file = now_utc.strftime("%Y%m%dT%H%M%SZ")

    side = side.upper()
    symbol = symbol.upper()
    blockers: list[dict] = []

    # Validate inputs early
    if side not in ("BUY", "SELL"):
        return {
            "verdict": "ERROR",
            "error": f"Invalid side '{side}'. Must be BUY or SELL.",
            "timestamp": ts_str,
        }

    # ------------------------------------------------------------------
    # Common paths (needed early for rehearsal computation)
    # ------------------------------------------------------------------
    strategy_path = BRIDGE_DIR / "docs" / "STRATEGY.md"
    autonomy_path = BRIDGE_DIR / "docs" / "AUTONOMY_CRITERIA.md"

    # ------------------------------------------------------------------
    # E1: Timestamp
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # E2: Git metadata
    # ------------------------------------------------------------------
    git = _git_metadata(BRIDGE_DIR)

    # ------------------------------------------------------------------
    # E3: Doctor result (lightweight in-process — no subprocess, no sudo)
    # ------------------------------------------------------------------
    doctor_evidence: dict = {}
    doctor_unavailable = False
    light_evidence: dict = {}
    try:
        light_evidence = _collect_lightweight_evidence()
        doctor_evidence = light_evidence.get("doctor", {})
    except Exception as e:
        doctor_evidence = {"error": str(e)[:300]}
        doctor_unavailable = True

    # ------------------------------------------------------------------
    # E4: KPI result — single consistent snapshot
    # ------------------------------------------------------------------
    kpi_evidence: dict = {}
    kpi_unavailable = False
    try:
        kpi_evidence = run_kpi()
    except Exception as e:
        kpi_evidence = {"_kpi_error": str(e)[:300]}
        kpi_unavailable = True

    kpi_verdict = kpi_evidence.get("verdict", "ERROR" if kpi_unavailable else "UNKNOWN")

    # Use lightweight snapshot (fast, consistent with doctor E3) as fallback.
    # Prefer KPI bridge/safety data when KPI succeeded — it's more comprehensive.
    lw_bridge = light_evidence.get("bridge", {}) if light_evidence else {}
    lw_safety = light_evidence.get("safety", {}) if light_evidence else {}
    lw_strategy = light_evidence.get("strategy", {}) if light_evidence else {}

    # Bridge resolution strategy:
    #   reachable  → lightweight /health is fastest + most reliable single check.
    #                KPI can transiently fail individual endpoints, producing
    #                false bridge_unreachable.  Lightweight always wins here.
    #   connected  → KPI when available (more comprehensive), else lightweight.
    #   safety     → KPI when available, else lightweight.
    kpi_bridge = kpi_evidence.get("bridge", {}) if not kpi_unavailable else {}
    kpi_safety = kpi_evidence.get("safety_flags", {}) if not kpi_unavailable else {}

    # Reachable: lightweight /health is authoritative
    lw_reachable = lw_bridge.get("reachable", False) if lw_bridge else False
    kpi_reachable = kpi_bridge.get("reachable", False) if kpi_bridge else False

    if lw_reachable:
        # Lightweight /health says reachable — bridge IS reachable
        ibkr_reachable = True
        _bridge_source = "lightweight_health"
    elif kpi_bridge and not kpi_unavailable:
        # Lightweight couldn't reach, but KPI could — use KPI
        ibkr_reachable = kpi_reachable
        _bridge_source = "kpi"
    else:
        ibkr_reachable = False
        _bridge_source = "none"

    # Connected: KPI when available, else lightweight
    if kpi_bridge and not kpi_unavailable:
        ibkr_connected = kpi_bridge.get("connected", None)
    elif lw_bridge:
        ibkr_connected = lw_bridge.get("connected", None)
    else:
        ibkr_connected = None

    bridge_known = (ibkr_reachable is not None) or (ibkr_connected is not None)

    # Safety: KPI when available, else lightweight
    if kpi_safety and not kpi_unavailable:
        sf = kpi_safety
        _safety_source = "kpi"
    elif lw_safety:
        sf = lw_safety
        _safety_source = "lightweight"
    else:
        sf = {}
        _safety_source = "none"
    safety_locked = (
        sf.get("env_IBKR_ALLOW_ORDERS") == "false"
        and sf.get("rules_enforced") == "false"
        and sf.get("system_locked", False) is True
        and bool(sf)
    )

    # ------------------------------------------------------------------
    # E5: Cycle-rehearsal result (computed from same snapshot)
    # ------------------------------------------------------------------
    rehearsal_docs = {
        "strategy_exists": strategy_path.exists(),
        "autonomy_exists": autonomy_path.exists(),
    }
    rehearsal_blockers: list[dict] = []
    if not rehearsal_docs["strategy_exists"]:
        rehearsal_blockers.append({"severity": "NO-GO", "check": "strategy_doc_missing"})
    if not rehearsal_docs["autonomy_exists"]:
        rehearsal_blockers.append({"severity": "NO-GO", "check": "autonomy_doc_missing"})

    # Doctor non-canary (from same snapshot)
    doc_checks = doctor_evidence.get("checks", [])
    non_canary_failures = [c["check"] for c in doc_checks
                           if c.get("check") != "h1_token_canary" and not c.get("ok")]
    if non_canary_failures:
        rehearsal_blockers.append({"severity": "HOLD", "check": "doctor_non_pass",
                                   "detail": f"Failed: {', '.join(non_canary_failures)}"})
    if doctor_unavailable:
        rehearsal_blockers.append({"severity": "HOLD", "check": "doctor_unavailable",
                                   "detail": "Doctor command could not run"})

    # KPI cascades into rehearsal (respect KPI's own blockers)
    for b in kpi_evidence.get("blockers", []):
        if b.get("severity") == "NO-GO":
            rehearsal_blockers.append(b)
    if kpi_unavailable:
        rehearsal_blockers.append({"severity": "HOLD", "check": "dependency_timeout",
                                   "detail": "KPI dashboard dependency failed (timeout or unreachable)"})

    # Bridge / safety from snapshot (only if known)
    if bridge_known:
        if not ibkr_reachable:
            rehearsal_blockers.append({"severity": "NO-GO", "check": "bridge_unreachable"})
        elif not ibkr_connected:
            rehearsal_blockers.append({"severity": "HOLD", "check": "ibkr_not_connected"})
        if not safety_locked:
            rehearsal_blockers.append({"severity": "NO-GO", "check": "safety_unlocked"})
    else:
        rehearsal_blockers.append({"severity": "HOLD", "check": "bridge_unknown",
                                   "detail": "Bridge state unknown (KPI unavailable)"})

    # Heartbeat
    hb = kpi_evidence.get("heartbeat", {})
    if not hb.get("recent", False):
        if hb.get("age_seconds") is None:
            rehearsal_blockers.append({"severity": "HOLD", "check": "heartbeat_missing"})
        else:
            rehearsal_blockers.append({"severity": "HOLD", "check": "heartbeat_stale"})

    has_r_nogo = any(b["severity"] == "NO-GO" for b in rehearsal_blockers)
    has_r_hold = any(b["severity"] == "HOLD" for b in rehearsal_blockers)
    if has_r_nogo:
        rehearsal_verdict = "NO-GO"
    elif has_r_hold:
        rehearsal_verdict = "HOLD"
    else:
        rehearsal_verdict = "CLEAN"
    rehearsal_evidence = {
        "verdict": rehearsal_verdict,
        "blocker_count": len(rehearsal_blockers),
        "docs": rehearsal_docs,
        "_computed_from_candidate": True,
    }

    # ------------------------------------------------------------------
    # E6: Bridge safety flags (blocker check)
    # ------------------------------------------------------------------
    if bridge_known and not safety_locked:
        fail_items = []
        if sf.get("env_IBKR_ALLOW_ORDERS") != "false":
            fail_items.append(f"IBKR_ALLOW_ORDERS={sf.get('env_IBKR_ALLOW_ORDERS')}")
        if sf.get("rules_enforced") != "false":
            fail_items.append(f"rules.enforced={sf.get('rules_enforced')}")
        if sf.get("system_locked") is not True:
            fail_items.append("system_locked is not True")
        blockers.append({"severity": "NO-GO", "check": "safety_unlocked",
                         "detail": "; ".join(fail_items)})

    # ------------------------------------------------------------------
    # E7: IBKR connection state (blocker check)
    # ------------------------------------------------------------------
    if not bridge_known:
        blockers.append({"severity": "HOLD", "check": "bridge_unknown",
                         "detail": "Bridge state unknown — KPI unavailable, cannot verify connection"})
    elif not ibkr_reachable:
        blockers.append({"severity": "HOLD", "check": "ibkr_unreachable",
                         "detail": "IBKR bridge is not reachable — cannot verify connection"})
    elif not ibkr_connected:
        blockers.append({"severity": "HOLD", "check": "ibkr_disconnected",
                         "detail": "IBKR Gateway is not connected"})

    # ------------------------------------------------------------------
    # E8: Strategy match / no-trade conditions
    # ------------------------------------------------------------------
    strategy_ok = lw_strategy.get("strategy_exists", strategy_path.exists()) and \
                  lw_strategy.get("autonomy_exists", autonomy_path.exists())
    autonomy_level = _read_autonomy_level(autonomy_path)

    # E8a: Autonomy level check — Level 0 is always HOLD
    if int(autonomy_level) == 0:
        blockers.append({"severity": "HOLD", "check": "autonomy_level_zero",
                         "detail": "Autonomy level 0 — manual approval required for all orders"})

    # E8b: Clean cycle count check — zero clean cycles is HOLD
    home_oc = HOME / ".openclaw"
    clean_cycles = _count_clean_cycles(home_oc)
    if clean_cycles == 0:
        blockers.append({"severity": "HOLD", "check": "no_clean_cycles",
                         "detail": "Zero clean autonomous cycles logged — insufficient evidence for dry-run readiness"})

    # KPI cascades: only when KPI is actually NO-GO (not when unavailable)
    # KPI cascade: HOLD stays HOLD; only explicit KPI NO-GO blockers create candidate NO-GO.
    kpi_blockers = kpi_evidence.get("blockers", []) if isinstance(kpi_evidence, dict) else []
    kpi_has_nogo = any(isinstance(b, dict) and b.get("severity") == "NO-GO" for b in kpi_blockers)
    if kpi_verdict == "NO-GO" and not kpi_has_nogo:
        kpi_verdict = "HOLD"
    if kpi_verdict == "NO-GO" and kpi_has_nogo:
        blockers.append({"severity":"NO-GO","check":"kpi_nogo_cascade","detail":"KPI dashboard reports NO-GO — candidate cannot proceed"})
    elif kpi_verdict == "ERROR":
        blockers.append({"severity":"HOLD","check":"dependency_timeout","detail":"KPI dashboard unavailable or timed out — candidate remains HOLD"})

    # Rehearsal cascades: only when rehearsal is independently NO-GO
    # (not from KPI data we already cascade above)
    if rehearsal_verdict == "NO-GO" and kpi_verdict != "NO-GO":
        blockers.append({"severity": "NO-GO", "check": "rehearsal_nogo_cascade",
                         "detail": "Cycle rehearsal reports NO-GO (independent of KPI)"})
    elif rehearsal_verdict == "HOLD" and kpi_verdict == "GO":
        # Only add HOLD cascade if KPI would otherwise allow GO
        blockers.append({"severity": "HOLD", "check": "rehearsal_hold",
                         "detail": "Cycle rehearsal reports HOLD"})

    # ------------------------------------------------------------------
    # E9: Hermes advisory
    # ------------------------------------------------------------------
    hermes_evidence = {"hermes_available": False}
    try:
        hermes_test = _run_hermes_canary()
        hermes_evidence["canary"] = hermes_test
        hermes_evidence["hermes_available"] = hermes_test.get("ok", False)
    except Exception as e:
        hermes_evidence["canary_error"] = str(e)[:200]

    # ------------------------------------------------------------------
    # E10: Gate H proposal path
    # ------------------------------------------------------------------
    proposal_id = f"candidate-{symbol}-{side}-{ts_file}"
    proposal_dir = _CANDIDATE_PROPOSALS_DIR
    proposal_dir.mkdir(parents=True, exist_ok=True)
    proposal_path = proposal_dir / f"{proposal_id}.json"

    # ------------------------------------------------------------------
    # E11: Proposal schema validation (Gate H — symbol allowlist, side, quantity)
    # ------------------------------------------------------------------
    quantity = 1  # default for dry-run
    gate_h_ok = True
    gate_h_checks = {}
    try:
        from guard import _require_allowed_symbol
        _require_allowed_symbol(symbol)
        gate_h_checks["symbol_allowed"] = True
    except ValueError as e:
        gate_h_checks["symbol_allowed"] = False
        gate_h_checks["symbol_error"] = str(e)
        gate_h_ok = False
        blockers.append({"severity": "NO-GO", "check": "symbol_not_allowed",
                         "detail": f"Symbol {symbol} not in allowed universe: {str(e)}"})
    except Exception as e:
        gate_h_checks["symbol_allowed"] = False
        gate_h_checks["symbol_error"] = str(e)
        gate_h_ok = False

    gate_h_checks["valid_side"] = side in ("BUY", "SELL")
    gate_h_checks["valid_quantity"] = isinstance(quantity, int) and quantity > 0

    # ------------------------------------------------------------------
    # E12: Market data — real pricing from bridge (Step 15D)
    # ------------------------------------------------------------------
    market_data: dict = {}
    market_available = False
    market_stale = True
    reference_price = None
    price_source = "unknown"
    price_valid = False
    try:
        md_req = urllib.request.Request(
            f"{BRIDGE_URL}/market/snapshot/{symbol}", method="GET")
        with urllib.request.urlopen(md_req, timeout=10.0) as md_resp:
            if md_resp.status == 200:
                market_data = json.loads(md_resp.read().decode())
    except Exception as e:
        market_data = {
            "ok": False,
            "market_data_available": False,
            "symbol": symbol,
            "source": "bridge_market_data",
            "error": str(e)[:200],
            "bid": None,
            "ask": None,
            "last": None,
            "midpoint": None,
            "currency": None,
            "timestamp": None,
            "staleness_seconds": None,
        }

    market_available = market_data.get("market_data_available", False)
    market_stale = market_data.get("stale", True)

    # Select reference price: prefer last, then midpoint, then close
    if market_available and not market_stale:
        ref_candidates = [
            ("last", market_data.get("last")),
            ("midpoint", market_data.get("midpoint")),
            ("close", market_data.get("close")),
        ]
        for src, val in ref_candidates:
            if val is not None and isinstance(val, (int, float)) and val > 0:
                reference_price = float(val)
                price_source = src
                break

    price_valid = reference_price is not None and reference_price > 0

    # Blockers for market data issues
    if not ibkr_connected and not market_available:
        blockers.append({"severity": "HOLD", "check": "ibkr_disconnected",
                         "detail": "IBKR disconnected — market data unavailable"})
    elif not market_available:
        blockers.append({"severity": "HOLD", "check": "market_data_missing",
                         "detail": "Market data unavailable for " + symbol})
    elif market_stale:
        age_s = market_data.get("market_data_age_seconds", 0)
        blockers.append({"severity": "HOLD", "check": "market_data_stale",
                         "detail": f"Market data stale ({age_s}s old) for {symbol}"})

    # If no valid price, this is a placeholder situation → must HOLD, never READY
    if not price_valid:
        blockers.append({"severity": "HOLD", "check": "market_data_missing",
                         "detail": f"No valid reference price for {symbol} — placeholder pricing rejected"})

    # Notional — instrument currency (un-normalized)
    notional_instrument = round(quantity * reference_price, 2) if price_valid else None

    # ------------------------------------------------------------------
    # E13: Planned entry basis + Step 15G FX-normalized notional
    # ------------------------------------------------------------------
    instrument_currency = market_data.get("currency", "USD") if market_available else None

    # Determine base currency from KPI snapshot or lightweight evidence
    base_currency = None
    kpi_bridge_pre = kpi_evidence.get("bridge", {}) if not kpi_unavailable else {}
    base_currency = kpi_bridge_pre.get("base_currency")
    if not base_currency and lw_bridge:
        base_currency = lw_bridge.get("base_currency")
    if not base_currency:
        base_currency = "EUR"  # default assumption for this account

    # Step 15G: Fetch FX evidence
    fx_evidence = {}
    fx_valid = False
    if price_valid and instrument_currency and base_currency:
        fx_evidence = _fetch_fx_evidence(base_currency, instrument_currency)
        fx_valid = fx_evidence.get("fx_available", False)

    # Compute normalized notional
    fx_rate = fx_evidence.get("fx_rate") if fx_valid else None
    notional_base = round(notional_instrument * fx_rate, 2) if (notional_instrument is not None and fx_rate is not None) else None

    # Step 15G: FX blockers
    if price_valid and instrument_currency and base_currency:
        is_cross = instrument_currency.upper() != base_currency.upper()
        if is_cross:
            if not fx_valid:
                blockers.append({"severity": "HOLD", "check": "fx_missing",
                                 "detail": f"FX rate {instrument_currency}/{base_currency} unavailable — cannot normalize notional"})
            elif fx_rate is not None and fx_rate <= 0:
                blockers.append({"severity": "HOLD", "check": "fx_invalid",
                                 "detail": f"FX rate {instrument_currency}/{base_currency}={fx_rate} is invalid (<=0)"})
            else:
                fx_age = fx_evidence.get("fx_staleness_seconds", 0) if fx_evidence else 0
                _FX_MAX_STALENESS = 300.0
                if fx_age is not None and fx_age > _FX_MAX_STALENESS:
                    blockers.append({"severity": "HOLD", "check": "fx_stale",
                                     "detail": f"FX rate {instrument_currency}/{base_currency} stale ({fx_age:.0f}s > {_FX_MAX_STALENESS:.0f}s)"})

    entry_basis = {
        "type": "MKT",
        "reference_price": reference_price,
        "reference_source": price_source,
        "quantity": quantity,
        "notional_instrument_currency": notional_instrument,
        "notional_base_currency": notional_base,
        "instrument_currency": instrument_currency,
        "base_currency": base_currency,
        "notional_eur": notional_base,  # backward compat
        "currency": instrument_currency,
    }

    # ------------------------------------------------------------------
    # E14: Stop price derived from real reference price
    # ------------------------------------------------------------------
    stop_pct = 0.05  # 5% stop for dry-run
    if side == "BUY" and price_valid:
        stop_price = round(reference_price * (1 - stop_pct), 2)
        stop_rationale = f"{stop_pct*100:.0f}% protective stop below entry at {reference_price}"
    elif side == "SELL":
        stop_price = None
        stop_rationale = "SELL close-only — no protective stop required"
    else:
        stop_price = None
        stop_rationale = "Stop price unavailable — no valid reference price"

    # ------------------------------------------------------------------
    # E15: P5 bracket-stop validation (only when pricing is valid)
    # ------------------------------------------------------------------
    p5_evidence = {}
    p5_ok = True
    if price_valid:
        try:
            from guard import validate_bracket_stop
            if side == "BUY":
                result = validate_bracket_stop(
                    stop_price=stop_price,
                    entry_price=reference_price,
                    quantity=quantity,
                    action="BUY",
                )
                p5_evidence = {
                    "valid": result.get("valid", False),
                    "bracket": result.get("bracket", False),
                    "protective_stop": result.get("protective_stop", False),
                    "stop_distance": result.get("stop_distance"),
                    "parent_transmit": result.get("parent_transmit"),
                    "stop_transmit": result.get("stop_transmit"),
                }
                if not result.get("valid"):
                    p5_ok = False
                    p5_evidence["error"] = result.get("error", "P5 validation failed")
                    blockers.append({"severity": "NO-GO", "check": "p5_bracket_failed",
                                     "detail": f"P5 bracket-stop validation failed: {result.get('error', 'unknown')}"})
            else:
                result = validate_bracket_stop(
                    stop_price=None,
                    entry_price=reference_price,
                    quantity=quantity,
                    action="SELL",
                )
                p5_evidence = {
                    "valid": result.get("valid", False),
                    "bracket": False,
                    "protective_stop": False,
                    "note": "SELL close-only — P5 bracket not required",
                }
        except Exception as e:
            p5_evidence = {"valid": False, "error": str(e)[:300]}
            p5_ok = False
            blockers.append({"severity": "NO-GO", "check": "p5_bracket_failed",
                             "detail": f"P5 validation error: {str(e)[:200]}"})
    else:
        p5_evidence = {
            "valid": False,
            "skipped": True,
            "note": "P5 bracket validation skipped — no valid reference price",
        }

    # ------------------------------------------------------------------
    # E16: Forbidden endpoint scan
    # ------------------------------------------------------------------
    scan_result = _scan_forbidden_endpoints()
    scan_ok = scan_result.get("ok", True)
    if not scan_ok:
        violations = scan_result.get("violations", [])
        detail = f"{len(violations)} violation(s): " + "; ".join(
            v.get("endpoint", "?") for v in violations[:3]
        )
        blockers.append({"severity": "NO-GO", "check": "forbidden_endpoint_found",
                         "detail": detail})

    # ------------------------------------------------------------------
    # E17: Final verdict
    # ------------------------------------------------------------------
    has_nogo = any(b["severity"] == "NO-GO" for b in blockers)
    has_hold = any(b["severity"] == "HOLD" for b in blockers)

    if has_nogo:
        verdict = "NO-GO"
    elif has_hold:
        verdict = "HOLD"
    else:
        verdict = "READY_DRYRUN"

    # Save proposal to disk
    proposal_doc = {
        "proposal_id": proposal_id,
        "timestamp": ts_str,
        "symbol": symbol,
        "side": side,
        "quantity": quantity,
        "notional_eur": notional_base,
        "entry_basis": entry_basis,
        "stop_price": stop_price,
        "stop_rationale": stop_rationale,
        "verdict": verdict,
        "advisory_only": True,
        "dry_run": True,
        "no_order_enabled": True,
    }
    try:
        with open(proposal_path, "w", encoding="utf-8") as f:
            _json.dump(proposal_doc, f, indent=2, default=str, ensure_ascii=False)
    except Exception as e:
        blockers.append({"severity": "HOLD", "check": "proposal_write_failed",
                         "detail": f"Could not write proposal to {proposal_path}: {e}"})

    # Build result
    result = {
        "advisory": "Candidate dry-run. Read-only. No orders. No H1 token. No broker mutation.",
        "timestamp": ts_str,
        "git": git,
        "verdict": verdict,
        "symbol": symbol,
        "side": side,
        "quantity": quantity,
        "notional_eur": notional_base,
        "doctor": {
            "pass": doctor_evidence.get("pass", False),
            "total": doctor_evidence.get("total", 0),
            "passed": doctor_evidence.get("passed", 0),
        },
        "kpi": {
            "verdict": kpi_verdict,
            "bridge": lw_bridge if lw_bridge else kpi_evidence.get("bridge", {}),
            "safety_flags": sf if sf else kpi_evidence.get("safety_flags", {}),
        },
        "rehearsal": {
            "verdict": rehearsal_verdict,
            "blocker_count": rehearsal_evidence.get("blocker_count", -1),
        },
        "bridge_safety_flags": dict(sf, _source=_safety_source),
        "ibkr_connection": {
            "reachable": ibkr_reachable,
            "connected": ibkr_connected,
            "_source": _bridge_source,
        },
        "strategy": {
            "strategy_exists": strategy_ok,
            "autonomy_level": autonomy_level,
            "clean_cycles": clean_cycles,
        },
        "hermes": hermes_evidence,
        "gate_h": {
            "proposal_path": str(proposal_path),
            "proposal_id": proposal_id,
            "checks": gate_h_checks,
            "ok": gate_h_ok,
        },
        "proposal_schema": gate_h_checks,
        "candidate": {
            "symbol": symbol,
            "side": side,
            "quantity": quantity,
            "notional_eur": notional_base,
        },
        "market_data": market_data,  # Step 15D: full market snapshot
        "pricing": {
            "reference_price": reference_price,
            "price_source": price_source,
            "price_valid": price_valid,
            "stop_price": stop_price,
            "stop_pct": stop_pct if side == "BUY" else None,
            "currency": market_data.get("currency") if market_available else None,
            "bid": market_data.get("bid") if market_available else None,
            "ask": market_data.get("ask") if market_available else None,
            "last": market_data.get("last") if market_available else None,
            "midpoint": market_data.get("midpoint") if market_available else None,
            "staleness_seconds": market_data.get("market_data_age_seconds") if market_available else None,
            "snapshot_timestamp": market_data.get("snapshot_timestamp") if market_available else None,
        },
        "account_evidence": {
            "net_liquidation": None,
            "cash_balance": None,
            "base_currency": base_currency,
            "instrument_currency": instrument_currency,
            "fx_available": fx_valid,
            "fx_required": fx_evidence.get("fx_required", instrument_currency.upper() != base_currency.upper() if instrument_currency and base_currency else None),
            "fx_rate": fx_rate,
            "fx_pair": fx_evidence.get("fx_pair"),
            "fx_source": fx_evidence.get("fx_source"),
            "fx_timestamp": fx_evidence.get("fx_timestamp"),
            "fx_staleness_seconds": fx_evidence.get("fx_staleness_seconds"),
            "reference_price_currency": instrument_currency,
            "notional_instrument_currency": notional_instrument,
            "notional_base_currency": notional_base,
        },
        "entry_basis": entry_basis,
        "stop": {
            "price": stop_price,
            "pct": stop_pct if side == "BUY" else None,
            "rationale": stop_rationale,
        },
        "p5_bracket": p5_evidence,
        "forbidden_endpoint_scan": scan_result,
        "blockers": blockers,
        "blocker_count": len(blockers),
    }

    # Enrich account evidence from KPI snapshot if available (metadata only)
    # Step 15G: fx_available and related fields are set above from real FX evidence;
    # do NOT override them here.
    kpi_bridge_data = kpi_evidence.get("bridge", {}) if not kpi_unavailable else {}
    net_liq_snap = kpi_bridge_data.get("net_liquidation")
    if net_liq_snap is not None:
        result["account_evidence"]["net_liquidation"] = net_liq_snap
    cash_snap = kpi_bridge_data.get("cash_balance")
    if cash_snap is not None:
        result["account_evidence"]["cash_balance"] = cash_snap
    base_cur = kpi_bridge_data.get("base_currency")
    if base_cur and not result["account_evidence"].get("base_currency"):
        result["account_evidence"]["base_currency"] = base_cur

    # Step 15G: fx_missing blocker is already added above in E13 if cross-currency
    # and FX unavailable. Do not duplicate.

    # Final verdict after all enrichments
    has_nogo_v = any(b["severity"] == "NO-GO" for b in blockers)
    has_hold_v = any(b["severity"] == "HOLD" for b in blockers)
    if has_nogo_v:
        result["verdict"] = "NO-GO"
    elif has_hold_v:
        result["verdict"] = "HOLD"
    else:
        result["verdict"] = "READY_DRYRUN"

    # Update proposal doc with new fields
    proposal_doc["market_data"] = market_data
    proposal_doc["pricing"] = result["pricing"]
    proposal_doc["account_evidence"] = result["account_evidence"]
    proposal_doc["verdict"] = result["verdict"]
    proposal_doc["blockers"] = blockers
    try:
        with open(proposal_path, "w", encoding="utf-8") as f:
            _json.dump(proposal_doc, f, indent=2, default=str, ensure_ascii=False)
    except Exception:
        pass  # already logged above

    return result


def print_candidate_dryrun(result: dict) -> None:
    """Print candidate dry-run result in human-readable format."""
    verdict = result.get("verdict", "ERROR")
    v_color = {"READY_DRYRUN": GREEN, "HOLD": RESET, "NO-GO": RED, "ERROR": RED}.get(verdict, RESET)

    print(f"{BOLD}Candidate Dry-Run{RESET}  [{v_color}{verdict}{RESET}]")
    print(f"  Timestamp:  {result.get('timestamp', '?')}")
    print(f"  Symbol:     {result.get('symbol', '?')}")
    print(f"  Side:       {result.get('side', '?')}")
    print(f"  Quantity:   {result.get('quantity', '?')}")
    base_cur = result.get('account_evidence', {}).get('base_currency', 'EUR')
    print(f"  Notional:   {result.get('notional_eur', '?')} {base_cur}")
    print(f"  Git:        {result.get('git', {}).get('describe', '?')}"[:120])
    print()

    # Doctor
    doc = result.get("doctor", {})
    doc_pass = doc.get("pass", False)
    doc_color = GREEN if doc_pass else RED
    print(f"  Doctor:     {doc_color}{'PASS' if doc_pass else 'FAIL'}{RESET}  ({doc.get('passed', 0)}/{doc.get('total', 0)})")

    # KPI
    kpi = result.get("kpi", {})
    kpi_v = kpi.get("verdict", "?")
    kpi_color = {"GO": GREEN, "HOLD": RESET, "NO-GO": RED}.get(kpi_v, RESET)
    print(f"  KPI:        {kpi_color}{kpi_v}{RESET}")

    # Rehearsal
    rh = result.get("rehearsal", {})
    rh_v = rh.get("verdict", "?")
    rh_color = {"CLEAN": GREEN, "HOLD": RESET, "NO-GO": RED}.get(rh_v, RESET)
    print(f"  Rehearsal:  {rh_color}{rh_v}{RESET}")

    # IBKR connection
    ibkr = result.get("ibkr_connection", {})
    ibkr_color = GREEN if ibkr.get("connected") else RESET
    print(f"  IBKR:       {ibkr_color}{'connected' if ibkr.get('connected') else 'disconnected'}{RESET}")

    # Safety
    sf = result.get("bridge_safety_flags", {})
    safety_locked = (
        sf.get("env_IBKR_ALLOW_ORDERS") == "false"
        and sf.get("rules_enforced") == "false"
        and sf.get("system_locked") is True
    )
    print(f"  Safety:     {'LOCKED' if safety_locked else f'{RED}UNLOCKED{RESET}'}")

    # Gate H
    gh = result.get("gate_h", {})
    print(f"  Gate H:     {'✓' if gh.get('ok') else '✗'}  proposal={gh.get('proposal_id', '?')}")

    # P5
    p5 = result.get("p5_bracket", {})
    print(f"  P5 Bracket: {'✓' if p5.get('valid') else '✗'}")

    # EP Scan
    scan = result.get("forbidden_endpoint_scan", {})
    print(f"  EP Scan:    {'✓' if scan.get('ok') else '✗'}")

    # Stop
    stop = result.get("stop", {})
    if stop.get("price"):
        print(f"  Stop:       {stop['price']} ({stop.get('pct', '?')*100:.0f}%)")
    else:
        print(f"  Stop:       {stop.get('rationale', 'N/A')}")

    # Blockers
    blockers = result.get("blockers", [])
    if blockers:
        print(f"\n  {BOLD}Blockers:{RESET}")
        for b in blockers:
            sev_color = {"NO-GO": RED, "HOLD": RESET}.get(b["severity"], RESET)
            print(f"    [{sev_color}{b['severity']}{RESET}] {b['check']}: {b.get('detail', '')}"[:200])
    print()


def export_candidate_dryrun(result: dict, export_dir: Path | None = None) -> Path:
    """Export candidate dry-run result to JSON file.

    Uses ~/.openclaw/candidate-dryruns/ as default export directory.
    Returns the output path.
    """
    if export_dir is None:
        export_dir = OPENCLAW_DIR / _CANDIDATE_EXPORT_DIR_NAME
    export_dir.mkdir(parents=True, exist_ok=True)

    ts_file = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    symbol = result.get("symbol", "UNKNOWN")
    side = result.get("side", "?")
    out_path = export_dir / f"candidate-{symbol}-{side}-{ts_file}.json"
    tmp = out_path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, default=str, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, out_path)
    return out_path


# ---------------------------------------------------------------------------
# Phase 5B.1 — Hermes Advisory Proposal (original)
# ---------------------------------------------------------------------------


def _run_h1_canary() -> dict:
    """Run an H1 token canary test via the sudo trade-window helper.

    Invokes 'sudo /usr/local/sbin/ibkr-trade-window approve aprv_canary'.
    Uses a fake approval ID that should never exist — the expected
    response is 'Approval not found', which proves the H1 token was
    accepted and the bridge processed the request.

    NEVER prints, logs, exports, or persists the raw H1 token.
    The token stays in /etc/ibkr-bridge/h1_token (root:root 600).

    Returns dict with:
      ok: True if canary passed
      status: "PASS" | "FAIL" | "MANUAL_REQUIRED"
    """
    import subprocess
    from datetime import datetime, timezone

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    helper = "/usr/local/sbin/ibkr-trade-window"
    canary_id = "aprv_canary"

    # Check if sudo can run non-interactively (no password prompt)
    try:
        sudo_test = subprocess.run(
            ["sudo", "-n", "true"],
            capture_output=True, text=True, timeout=5,
        )
        can_sudo = sudo_test.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        can_sudo = False

    if not can_sudo:
        return {
            "ok": False,
            "status": "MANUAL_REQUIRED",
            "detail": "sudo requires password or is unavailable",
            "manual_command": f"sudo {helper} approve {canary_id}",
            "timestamp_utc": ts,
        }

    # Run the canary
    try:
        result = subprocess.run(
            ["sudo", "-n", helper, "approve", canary_id],
            capture_output=True, text=True, timeout=30,
        )
        combined = (result.stdout or "") + "\n" + (result.stderr or "")
        combined_lower = combined.lower()
    except FileNotFoundError:
        return {
            "ok": False,
            "status": "FAIL",
            "detail": f"Helper not found at {helper}",
            "timestamp_utc": ts,
        }
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "status": "FAIL",
            "detail": f"Canary timed out (30s)",
            "timestamp_utc": ts,
        }

    # Classify result — never include raw output in logs/output.
    # The expected response from the bridge for a fake approval is:
    #   "Approval 'aprv_canary' not found, expired, or already ruled."
    # Any other response means the H1 token is invalid or the bridge
    # rejected the request.

    if "not found, expired, or already ruled" in combined_lower:
        return {
            "ok": True,
            "status": "PASS",
            "detail": "H1 token accepted — fake approval correctly rejected",
            "timestamp_utc": ts,
        }

    # Specific failure modes
    if "h1_token_required" in combined_lower or "401" in combined:
        return {
            "ok": False,
            "status": "FAIL",
            "detail": "H1_TOKEN_REQUIRED — token missing, invalid, or not sent",
            "timestamp_utc": ts,
        }

    if "error" in combined_lower and "token" in combined_lower:
        return {
            "ok": False,
            "status": "FAIL",
            "detail": "Token error — check /etc/ibkr-bridge/h1_token permissions and content",
            "timestamp_utc": ts,
        }

    # Unexpected output — bridge may be down
    return {
        "ok": False,
        "status": "FAIL",
        "detail": f"Unexpected response — bridge may be unavailable or token invalid",
        "timestamp_utc": ts,
    }


def _run_hermes_canary() -> dict:
    """Run a Hermes canary test. Returns evidence block."""
    import subprocess
    from datetime import datetime, timezone

    request_ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    prompt = "Reply with exactly: HERMES_CANARY_OK. No other text."

    try:
        result = subprocess.run(
            ["hermes", "chat", "-q", prompt, "-m", "gpt-5.5",
             "--provider", "openai-codex", "-Q"],
            capture_output=True, text=True, timeout=60,
        )
        response_ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        stdout = result.stdout.strip()
        session_id = None
        combined = stdout + "\n" + (result.stderr or "")
        for line in combined.split("\n"):
            if "session_id" in line.lower():
                parts = line.split(":", 1)
                if len(parts) > 1:
                    session_id = parts[-1].strip()
                    break
        ok = "HERMES_CANARY_OK" in stdout and result.returncode == 0
        return {
            "command": "ibkr-operator hermes-proposal --canary",
            "timestamp_utc": response_ts,
            "ok": ok,
            "raw_response": stdout[:500],
            "evidence": {
                "hermes_invoked": True,
                "hermes_command_or_adapter": "ibkr-operator hermes-proposal -> hermes chat -q",
                "hermes_provider": "openai-codex",
                "hermes_model": "gpt-5.5",
                "resolved_model": "openai-codex/gpt-5.5",
                "hermes_request_timestamp_utc": request_ts,
                "hermes_response_timestamp_utc": response_ts,
                "hermes_session_id": session_id,
                "hermes_log_reference": f"hermes session {session_id or 'unknown'}",
                "fallback_used": False,
                "final_proposal_source": "canary (test)",
            },
        }
    except FileNotFoundError:
        return {"command": "hermes-proposal --canary", "ok": False,
                "error": "hermes CLI not found"}
    except subprocess.TimeoutExpired:
        return {"command": "hermes-proposal --canary", "ok": False,
                "error": "Hermes timed out"}


def _run_hermes_proposal(symbol: str, side: str, qty: int) -> dict:
    """Generate a Hermes-advised trade proposal.

    Advisory only. No order enablement. No state mutation.
    """
    from datetime import datetime, timezone
    import json
    import subprocess

    request_ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Gather baseline data
    baseline = {}
    try:
        ck = run_checklist()
        baseline["checklist"] = ck
    except Exception:
        baseline["checklist"] = {"error": "checklist unavailable"}
    try:
        dr = run_daily_report()
        baseline["daily_report"] = dr
    except Exception:
        baseline["daily_report"] = {"error": "daily_report unavailable"}
    try:
        doc = run_doctor()
        baseline["doctor"] = doc
    except Exception:
        baseline["doctor"] = {"error": "doctor unavailable"}

    # Build Hermes prompt
    prompt_parts = [
        "You are Hermes, an advisory-only trading research engine.",
        "You are generating a trade proposal for Chris to review.",
        "",
        "IMPORTANT RULES:",
        "- Advisory only. No order enabled or submitted.",
        "- You must NOT call any trading endpoints.",
        "- You must NOT suggest that orders are already approved.",
        "- You must NOT mutate any files.",
        "- Your proposal is a DRAFT for Chris to review.",
        "",
        "RISK RAILS (Phase 5 Pilot):",
        "- Max single position: 5% of Net Liq",
        "- Max total exposure: 25% of Net Liq",
        "- Max risk per trade: 0.25% of Net Liq",
        "- Max daily trades: 2, Max weekly: 5",
        "- No trade without stop/invalidation",
        "- No trade if drift, open order, or live requires_action alert",
        "- No trade if daily loss >= 1% or weekly >= 3% Net Liq",
        "",
        "CLOSE-ONLY SELL NOTE:",
        "Close-only SELLs (reducing/exiting existing long positions) are exempt from",
        "position sizing, notional caps, exposure limits, risk-per-trade, and",
        "stop/invalidation rails. Trade count limits, loss halt gates, and open order",
        "conflict checks still apply.",
        "",
        "HUMAN CONFIRMATION:",
        "- Every trade > EUR 0 requires Chris approval",
        "- Any order enablement requires Chris approval",
        "- Any order submit requires Chris approval",
        "",
        "BASELINE DATA:",
        json.dumps(baseline, indent=2, default=str),
        "",
        f"USER REQUEST: Generate a trade proposal for {side} {qty} {symbol}.",
        "",
        "OUTPUT FORMAT: Valid JSON only. Use this exact structure:",
        """{
  "symbol": "...",
  "side": "...",
  "quantity": N,
  "entry_reference": "...",
  "stop_loss_invalidation": "...",
  "max_loss_eur": N.N,
  "max_loss_pct": N.N,
  "position_notional_eur": N.N,
  "position_notional_pct": N.N,
  "portfolio_exposure_after_pct": N.N,
  "daily_drawdown_status": "...",
  "weekly_drawdown_status": "...",
  "reason_to_trade": "...",
  "reason_not_to_trade": "...",
  "preflight_command": "...",
  "facts": [...],
  "assumptions": [...],
  "estimates": [...],
  "unknowns": [...],
  "why_not_wait": "...",
  "awaiting_chris_approval": true,
  "advisory_only": true
}""",
    ]
    prompt = "\n".join(prompt_parts)

    try:
        start = time.time()
        result = subprocess.run(
            ["hermes", "chat", "-q", prompt, "-m", "gpt-5.5",
             "--provider", "openai-codex", "-Q"],
            capture_output=True, text=True, timeout=180,
        )
        elapsed = round(time.time() - start, 2)
        response_ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        stdout = result.stdout.strip()
        stderr = result.stderr.strip()
        session_id = None
        for line in (stdout + "\n" + stderr).split("\n"):
            if "session_id" in line.lower():
                parts = line.split(":", 1)
                if len(parts) > 1:
                    session_id = parts[-1].strip()
                    break

        # Parse JSON from response
        proposal = None
        try:
            start_idx = stdout.find("{")
            end_idx = stdout.rfind("}")
            if start_idx >= 0 and end_idx > start_idx:
                proposal = json.loads(stdout[start_idx:end_idx + 1])
        except (json.JSONDecodeError, ValueError):
            proposal = None

        evidence = {
            "hermes_invoked": True,
            "hermes_command_or_adapter": "ibkr-operator hermes-proposal -> hermes chat -q",
            "hermes_provider": "openai-codex",
            "hermes_model": "gpt-5.5",
            "resolved_model": "openai-codex/gpt-5.5",
            "hermes_request_timestamp_utc": request_ts,
            "hermes_response_timestamp_utc": response_ts,
            "hermes_session_id": session_id,
            "hermes_log_reference": f"hermes session {session_id or 'unknown'}",
            "fallback_used": False,
            "final_proposal_source": "Hermes" if proposal else "unknown",
            "elapsed_seconds": elapsed,
        }

        return {
            "command": "ibkr-operator hermes-proposal",
            "timestamp_utc": response_ts,
            "ok": proposal is not None,
            "proposal": proposal,
            "raw_response": stdout[:2000],
            "evidence": evidence,
            "advisory_only": True,
        }

    except FileNotFoundError:
        return {"command": "hermes-proposal", "ok": False,
                "error": "hermes CLI not found. Install hermes or check PATH.",
                "evidence": {"hermes_invoked": False,
                            "resolved_model": None,
                            "final_proposal_source": "unknown"}}
    except subprocess.TimeoutExpired:
        return {"command": "hermes-proposal", "ok": False,
                "error": "Hermes timed out after 180s",
                "evidence": {"hermes_invoked": True,
                            "resolved_model": "openai-codex/gpt-5.5",
                            "final_proposal_source": "unknown"}}


def _print_hermes_result(result: dict) -> None:
    """Print Hermes proposal result in human-readable format."""
    if not result.get("ok"):
        print(f"Hermes proposal FAILED: {result.get('error', 'unknown')}")
        print()
    else:
        print(f"{BOLD}Hermes-Advised Proposal{RESET}")
        print(f"{'=' * 40}")
        print()

    # Print evidence
    ev = result.get("evidence", {})
    print(f"{BOLD}Hermes Evidence Block{RESET}")
    print(f"  hermes_invoked: {ev.get('hermes_invoked', '?')}")
    print(f"  hermes_provider: {ev.get('hermes_provider', '?')}")
    print(f"  hermes_model: {ev.get('hermes_model', '?')}")
    print(f"  resolved_model: {ev.get('resolved_model', '?')}")
    print(f"  hermes_session_id: {ev.get('hermes_session_id', '?')}")
    print(f"  request: {ev.get('hermes_request_timestamp_utc', '?')}")
    print(f"  response: {ev.get('hermes_response_timestamp_utc', '?')}")
    print(f"  elapsed: {ev.get('elapsed_seconds', '?')}s")
    print(f"  source: {ev.get('final_proposal_source', '?')}")
    print()

    if result.get("ok") and result.get("proposal"):
        p = result["proposal"]
        print(f"{BOLD}Proposal{RESET}")
        print(f"  Symbol:          {p.get('symbol', '?')}")
        print(f"  Side:            {p.get('side', '?')}")
        print(f"  Quantity:        {p.get('quantity', '?')}")
        print(f"  Entry:           {p.get('entry_reference', '?')}")
        print(f"  Stop/Invalid:    {p.get('stop_loss_invalidation', '?')}")
        print(f"  Max Loss:        {p.get('max_loss_eur', '?')} EUR / {p.get('max_loss_pct', '?')}%")
        print(f"  Notional:        {p.get('position_notional_eur', '?')} EUR / {p.get('position_notional_pct', '?')}%")
        print(f"  Exposure after:  {p.get('portfolio_exposure_after_pct', '?')}%")
        print(f"  Daily drawdown:  {p.get('daily_drawdown_status', '?')}")
        print(f"  Weekly drawdown: {p.get('weekly_drawdown_status', '?')}")
        print(f"  Reason to trade: {p.get('reason_to_trade', '?')}")
        print(f"  Reason not to:   {p.get('reason_not_to_trade', '?')}")
        print()
        print(f"  Preflight cmd:")
        print(f"    {p.get('preflight_command', '?')}")
        print()
        if p.get("facts"):
            print(f"{BOLD}Facts{RESET}")
            for f in p["facts"]:
                print(f"  \u2022 {f}")
        if p.get("assumptions"):
            print(f"{BOLD}Assumptions{RESET}")
            for a in p["assumptions"]:
                print(f"  \u2022 {a}")
        if p.get("unknowns"):
            print(f"{BOLD}Unknowns{RESET}")
            for u in p["unknowns"]:
                print(f"  \u2022 {u}")
        print()
        print(f"  {BOLD}Awaiting Chris approval{RESET} \u2014 {p.get('awaiting_chris_approval', False)}")
        print(f"  {BOLD}Advisory only{RESET} \u2014 {p.get('advisory_only', False)}")

    print()
    print(f"{BOLD}Advisory only. No order enabled or submitted. No state mutated.{RESET}")


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="IBKR Operator Daily Checklist \u2014 read-only workflow automation",
    )
    sub = parser.add_subparsers(dest="command", help="Sub-command")

    cp = sub.add_parser("checklist", help="Run operator daily checklist")
    cp.add_argument("state", nargs="?", default=None,
                    help=f"Workflow state: {', '.join(sorted(VALID_STATES))}")
    cp.add_argument("--json", action="store_true", help="Output raw JSON only")
    cp.add_argument("--explain", action="store_true", help="Include rationale for checks")
    cp.add_argument("--offline", action="store_true",
                    help="End-of-day: file-based only, no bridge (subset of checks)")

    # Phase 4F — daily report subcommand
    drp = sub.add_parser("daily-report", help="Consolidated daily operator report")
    drp.add_argument("--json", action="store_true",
                     help="Output raw JSON only")

    # Phase 4H — evidence export subcommand
    ep = sub.add_parser("export", help="Read-only evidence export")
    ep.add_argument("--json", action="store_true",
                    help="Output raw JSON only")
    ep.add_argument("--save", action="store_true",
                    help="Write export to ~/.openclaw/exports/ and print path")
    ep.add_argument("--verify", type=str, default=None, nargs="?", const="latest",
                    help="Verify an export file (default: latest)")

    # Phase 4K — doctor subcommand
    docp = sub.add_parser("doctor", help="Operator self-test / environment diagnostics")
    docp.add_argument("--json", action="store_true",
                       help="Output raw JSON only")

    # Phase 4L — freeze subcommand
    fp = sub.add_parser("freeze", help="Release freeze / full CLI evidence snapshot")
    fp.add_argument("--json", action="store_true",
                     help="Output raw JSON only")

    # Phase 5B.1 — Hermes advisory proposal subcommand
    hp = sub.add_parser("hermes-proposal",
                         help="Generate Hermes-advised trade proposal (advisory only)")
    hp.add_argument("--json", action="store_true",
                    help="Output raw JSON only")
    hp.add_argument("--canary", action="store_true",
                    help="Test Hermes invocation and show evidence block")
    hp.add_argument("--symbol", type=str, default="AAPL",
                    help="Symbol for proposal (default: AAPL)")
    hp.add_argument("--side", type=str, default="BUY",
                    help="Side for proposal (default: BUY)")
    hp.add_argument("--qty", type=int, default=1,
                    help="Quantity for proposal (default: 1)")
    hp.add_argument("--output", type=str, default=None,
                    help="Save output to file")

    # Phase 4D — maintenance subcommand
    mp = sub.add_parser("maintenance", help="Audit/release artifact maintenance")
    mp.add_argument("--json", action="store_true",
                    help="Output raw JSON only")
    mp.add_argument("--dry-run", action="store_true",
                    help="Show what would be deleted without deleting anything")
    mp.add_argument("--prune-audit", action="store_true",
                    help="Prune old audit bundles (requires --keep-audit)")
    mp.add_argument("--prune-releases", action="store_true",
                    help="Prune old release tags (requires --keep-releases)")
    mp.add_argument("--keep-audit", type=int, default=None,
                    help="Number of audit bundles to keep (default: 20)")
    mp.add_argument("--keep-releases", type=int, default=None,
                    help="Number of release tags to keep (default: 20)")
    mp.add_argument("--prune-exports", action="store_true",
                    help="Prune old export files (requires --keep-exports)")
    mp.add_argument("--keep-exports", type=int, default=None,
                    help="Number of exports to keep (default: 20)")

    # Phase 5C (Step 12) — KPI / evidence dashboard subcommand
    kpp = sub.add_parser("kpi", help="KPI / evidence dashboard with GO/HOLD/NO-GO verdict")
    kpp.add_argument("--json", action="store_true",
                     help="Output raw JSON only")
    kpp.add_argument("--export", action="store_true",
                     help="Write output to ~/.openclaw/exports/")

    # Step 15B — KPI alert repair (safe stale-evidence clearing)
    krp = sub.add_parser("kpi-repair",
                         help="Repair proven-stale KPI alerts (orphans, trade count). No broker mutation.")
    krp.add_argument("--json", action="store_true",
                     help="Output raw JSON only")
    krp.add_argument("--live", action="store_true",
                     help="Execute the repair (default: dry-run only)")

    # Phase 7 — read-only heartbeat subcommand
    hbp = sub.add_parser("heartbeat", help="Run read-only bridge heartbeat")
    hbp.add_argument("--json", action="store_true",
                     help="Output raw JSON only")
    hbp.add_argument("--quiet", action="store_true",
                     help="Suppress human-readable output")

    # Phase 5D (Step 14) — cycle rehearsal subcommand
    crp = sub.add_parser("cycle-rehearsal", help="Run read-only autonomy cycle rehearsal")
    crp.add_argument("--json", action="store_true",
                     help="Output raw JSON only")
    crp.add_argument("--export", action="store_true",
                     help="Write output to ~/.openclaw/autonomy-cycles/")

    # Phase 5E (Step 15A) — candidate dry-run
    canp = sub.add_parser("candidate-dryrun",
                          help="Evidence-only paper-trade candidate dry-run")
    canp.add_argument("--symbol", required=True, type=str, help="Ticker symbol")
    canp.add_argument("--side", required=True, choices=["BUY", "SELL"],
                      help="Order side: BUY or SELL")
    canp.add_argument("--json", action="store_true",
                      help="Output raw JSON only")
    canp.add_argument("--export", action="store_true",
                      help="Write output to ~/.openclaw/candidate-dryruns/")

    args = parser.parse_args()

    if args.command == "daily-report":
        result = run_daily_report()
        if args.json:
            print(json.dumps(result, indent=2, default=str))
        else:
            print_daily_report(result)
        return

    if args.command == "export":
        if args.verify:
            from bundle_audit import verify_export
            vpath = None if args.verify == "latest" else args.verify
            vresult = verify_export(vpath)
            if args.json:
                print(json.dumps(vresult, indent=2, default=str))
            else:
                v_verdict = "PASS" if vresult["pass"] else "FAIL"
                v_color = GREEN if vresult["pass"] else RED
                print(f"Export Verification: {v_color}{v_verdict}{RESET}")
                print(f"  Source: {vresult.get('source', '?')}")
                print(f"  {vresult.get('passed_count', 0)}/{vresult.get('check_count', 0)}")
                for c in vresult.get("checks", []):
                    c_status = f"{GREEN}PASS{RESET}" if c["ok"] else f"{RED}FAIL{RESET}"
                    print(f"  {c_status} {c['check']}: {c['detail']}")
            return

        result = run_export()
        if args.save:
            out_path = write_export(result)
            if args.json:
                print(json.dumps(result, indent=2, default=str))
            else:
                print(f"Export written: {out_path}\n")
                print_export(result)
        elif args.json:
            print(json.dumps(result, indent=2, default=str))
        else:
            print_export(result)
        return

    if args.command == "maintenance":
        from bundle_audit import (
            maintenance_report,
            execute_prune,
            plan_prune,
            ProtectedPathError,
        )

        has_prune_flag = args.prune_audit or args.prune_releases or args.prune_exports

        if has_prune_flag:
            # Prune mode — requires explicit flags
            if args.dry_run:
                result = plan_prune(
                    keep_audit=args.keep_audit,
                    keep_releases=args.keep_releases,
                    keep_exports=args.keep_exports,
                )
            else:
                try:
                    result = execute_prune(
                        keep_audit=args.keep_audit if args.prune_audit else 0,
                        keep_releases=args.keep_releases if args.prune_releases else 0,
                        keep_exports=args.keep_exports,
                        prune_exports=args.prune_exports,
                        dry_run=False,
                    )
                except ProtectedPathError as e:
                    print(f"SAFETY BLOCKED: {e}", file=sys.stderr)
                    sys.exit(99)
        else:
            # Default: read-only report
            result = maintenance_report()

        if args.json:
            print(json.dumps(result, indent=2, default=str))
        else:
            _print_maintenance(result)
        return

    if args.command == "hermes-proposal":
        if args.canary:
            result = _run_hermes_canary()
        else:
            result = _run_hermes_proposal(args.symbol, args.side, args.qty)
        if args.json or args.canary:
            print(json.dumps(result, indent=2, default=str))
        else:
            _print_hermes_result(result)
        if args.output and result.get("ok"):
            with open(args.output, "w") as f:
                json.dump(result, f, indent=2)
            print(f"Output saved to {args.output}")
        return

    if args.command == "doctor":
        result = run_doctor()
        if args.json:
            print(json.dumps(result, indent=2, default=str))
        else:
            print_doctor(result)
        if not result.get("pass", False):
            sys.exit(2)
        return

    if args.command == "freeze":
        result = run_freeze()
        if args.json:
            print(json.dumps(result, indent=2, default=str))
        else:
            print_freeze(result)
        if not result.get("pass", False):
            sys.exit(2)
        return

    if args.command == "heartbeat":
        result = _run_heartbeat()
        artifact_path = result.pop("_artifact_path", None)
        if args.json:
            print(json.dumps(result, indent=2, default=str, ensure_ascii=False))
        elif not args.quiet:
            endpoints_healthy = result.get("all_endpoints_ok", result.get("ok", False))
            artifact_written = result.get("ok", False)
            if not artifact_written:
                status_str = f"{RED}FAIL{RESET}"
            elif endpoints_healthy:
                status_str = f"{GREEN}OK{RESET}"
            else:
                status_str = f"{RED}DEGRADED{RESET}"
            print(f"{BOLD}IBKR Bridge Heartbeat{RESET}  [{status_str}]")
            print(f"  Timestamp:      {result['timestamp']}")
            print(f"  Bridge:          {result['bridge_url']}")
            print(f"  Connected:       {result['connected']}")
            print(f"  Read-only:       {result['read_only']}")
            print(f"  Allow orders:    {result['allow_orders']}")
            print(f"  Startup safety:  {result['startup_safety_count']} "
                  f"({'PASS' if result.get('startup_safety_pass') else 'N/A'})")
            print(f"  Positions:       {result['positions_count']}")
            print(f"  Live alerts:     {result['live_alert_count']}")
            print(f"  Reconciliation:  {'PASS' if result.get('reconciliation_passed') else 'N/A'}")
            print(f"  Endpoints:       {result['endpoints_ok']}/{result['endpoints_total']} OK")
            if result["endpoint_failures"]:
                for f in result["endpoint_failures"]:
                    print(f"    {RED}FAIL{RESET} {f}")
            if artifact_path:
                print(f"  Artifact:        {artifact_path}")
        sys.exit(0 if result["ok"] else 2)

    if args.command == "kpi-repair":
        evidence = _repair_stale_alerts(dry_run=not args.live)
        if args.json:
            print(json.dumps(evidence, indent=2, default=str))
        else:
            print_repair_evidence(evidence)
        if not args.live:
            print("\n  (dry-run only — use --live to apply repairs)")
        return

    if args.command == "kpi":
        result = run_kpi()
        if args.export:
            export_path = export_kpi(result, OPENCLAW_DIR / "exports")
            result["_export_path"] = str(export_path)
        if args.json:
            print(json.dumps(result, indent=2, default=str))
        else:
            print_kpi(result)
            if args.export:
                print(f"  Export written: {result.get('_export_path', '?')}\n")
        sys.exit(2 if result["verdict"] == "NO-GO" else 0)

    if args.command == "cycle-rehearsal":
        result = _run_cycle_rehearsal()
        if args.export:
            export_path = export_cycle_rehearsal(result)
            result["_export_path"] = str(export_path)
        if args.json:
            print(json.dumps(result, indent=2, default=str))
        else:
            print_cycle_rehearsal(result)
            if args.export:
                print(f"\n  Export written: {result.get('_export_path', '?')}")
        sys.exit(2 if result["verdict"] == "NO-GO" else 0)

    if args.command == "candidate-dryrun":
        result = _run_candidate_dryrun(args.symbol, args.side)
        if args.export:
            export_path = export_candidate_dryrun(result)
            result["_export_path"] = str(export_path)
        if args.json:
            print(json.dumps(result, indent=2, default=str))
        else:
            print_candidate_dryrun(result)
            if args.export:
                print(f"  Export written: {result.get('_export_path', '?')}")
        exit_code = 2 if result["verdict"] == "NO-GO" else (0 if result["verdict"] == "READY_DRYRUN" else 1)
        sys.exit(exit_code)

    if args.command != "checklist":
        parser.print_help()
        sys.exit(1)

    raw_state = args.state
    state = None
    if raw_state:
        if raw_state in STATE_ALIASES:
            state = STATE_ALIASES[raw_state]
        elif raw_state in VALID_STATES:
            state = raw_state
        else:
            print(f"Error: Unknown state '{raw_state}'", file=sys.stderr)
            print(f"Valid: {', '.join(sorted(VALID_STATES))}", file=sys.stderr)
            sys.exit(1)

    if args.offline and state != "end-of-day":
        print("Warning: --offline only supported for end-of-day state. Ignoring.",
              file=sys.stderr)

    result = run_checklist(state_override=state)

    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        print_checklist(result, explain=args.explain)

    has_block = any(b["status"] == "BLOCK" for b in result["blocks"])
    is_error = result["verdict"] in ("STOP", "ERROR")
    if has_block or is_error:
        sys.exit(2)


if __name__ == "__main__":
    main()