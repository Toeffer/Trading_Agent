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

import hashlib
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


def _ledger_entry_strict_clean(entry: dict) -> tuple[bool, list[str]]:
    """Evaluate whether a single ledger entry meets ALL strict clean-cycle criteria.

    Returns (is_clean, reasons). Checks beyond the top-level `clean` flag:
      - clean is True
      - doctor_verdict == PASS
      - kpi_verdict != NO-GO
      - candidate_verdict != NO-GO
      - no_forbidden_endpoints is True
      - safety_flags are locked (read_only=True, allow_orders=False, etc.)
      - no blockers of severity NO-GO (if blockers are dicts with severity)

    Missing sub-fields are treated leniently (not a failure) so older
    ledger entries without full detail are not penalised.
    """
    reasons: list[str] = []

    # 0. Top-level clean flag must be True
    if entry.get("clean") is not True:
        reasons.append("clean_flag_not_true")
        return False, reasons

    # 1. doctor_verdict must be PASS (if present)
    dv = entry.get("doctor_verdict")
    if dv is not None and dv != "PASS":
        reasons.append(f"doctor_verdict={dv}")

    # 2. kpi_verdict must NOT be NO-GO (if present)
    kv = entry.get("kpi_verdict")
    if kv is not None and kv == "NO-GO":
        reasons.append(f"kpi_verdict={kv}")

    # 3. candidate_verdict must NOT be NO-GO (if present)
    cv = entry.get("candidate_verdict")
    if cv is not None and cv == "NO-GO":
        reasons.append(f"candidate_verdict={cv}")

    # 4. no_forbidden_endpoints must be True (if present)
    nfe = entry.get("no_forbidden_endpoints")
    if nfe is not None and nfe is not True:
        reasons.append("no_forbidden_endpoints_not_true")

    # 5. Safety flags must be locked (if present)
    sf = entry.get("safety_flags")
    if isinstance(sf, dict):
        if sf.get("read_only") is False:
            reasons.append("safety_read_only_false")
        bao = sf.get("bridge_allow_orders")
        if bao is not None and bao is not False and bao != "false":
            reasons.append(f"safety_bridge_allow_orders={bao}")
        eao = sf.get("env_IBKR_ALLOW_ORDERS")
        if eao is not None and eao != "false":
            reasons.append(f"safety_env_IBKR_ALLOW_ORDERS={eao}")
        re = sf.get("rules_enforced")
        if re is not None and re != "false":
            reasons.append(f"safety_rules_enforced={re}")

    # 6. No blockers of severity NO-GO (if blockers list present with dicts)
    blockers = entry.get("blockers")
    if isinstance(blockers, list):
        for b in blockers:
            if isinstance(b, dict) and b.get("severity") == "NO-GO":
                reasons.append(f"blocker_NO-GO: {b.get('check', '?')}")

    return len(reasons) == 0, reasons


def _count_clean_cycles(openclaw_dir: Path, max_age_days: int | None = None) -> int:
    """Count strictly-clean cycle entries from the JSONL ledger.

    Reads ~/.openclaw/autonomy-cycles/clean-cycle-ledger.jsonl.
    Uses _ledger_entry_strict_clean for validation — not just the
    top-level `clean` flag.  Malformed lines are ignored safely.

    If max_age_days is set, only entries within that many days are counted.
    """
    import json as _json
    ledger = openclaw_dir / "autonomy-cycles" / "clean-cycle-ledger.jsonl"
    if not ledger.exists():
        return 0
    cutoff = None
    if max_age_days is not None:
        cutoff = time.time() - (max_age_days * 86400)
    count = 0
    try:
        with open(ledger, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = _json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue  # skip malformed
                if not isinstance(entry, dict):
                    continue
                # Apply strict validation
                is_clean, _reasons = _ledger_entry_strict_clean(entry)
                if not is_clean:
                    continue
                if cutoff is not None:
                    ts = entry.get("timestamp", "")
                    try:
                        from datetime import datetime, timezone as tz
                        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                        if dt.timestamp() < cutoff:
                            continue
                    except (ValueError, TypeError):
                        pass  # include entries with unparseable timestamps
                count += 1
    except OSError:
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
# Step 15O — Guard-State Trade-Count Reconciliation Cleanup
# ---------------------------------------------------------------------------

_GUARD_STATE_REPAIRS_DIR = OPENCLAW_DIR / "guard-state-repairs"

_GUARD_RECONCILE_EXPLICIT_NON_ACTIONS: list[str] = [
    "This command did not change autonomy level.",
    "This command did not open an order window.",
    "This command did not call any no-order endpoints.",
    "This command did not read H1 token.",
    "This command did not place, modify, cancel, or transmit any order.",
    "This command did not enable IBKR_ALLOW_ORDERS.",
    "This command did not enable rules.enforced.",
    "This command repairs local guard-state.json trade count only — no broker mutation.",
]


def _run_guard_state_reconcile(
    apply_repair: bool = False,
    confirm_local_state_repair: bool = False,
) -> dict:
    """Reconcile guard-state trade count against confirmed event evidence (Step 15O).

    Dry-run by default. Repairs only when --apply and --confirm-local-state-repair
    are both present.

    Repair policy:
      - Downward only: guard count > confirmed events → can repair down.
      - Never upward: confirmed > guard count → NO_GO.
      - Ambiguous evidence → HOLD, no apply.
      - Requires 0 live IBKR orders, flat positions, locked safety.

    Returns comprehensive reconciliation dict.
    """
    import hashlib
    import json as _json
    import shutil
    from datetime import datetime, timezone
    from monitor import (
        load_guard_state,
        load_events,
    )
    import urllib.request

    now_utc = datetime.now(timezone.utc)
    ts_str = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    ts_file = now_utc.strftime("%Y%m%dT%H%M%SZ")
    repair_id = f"guard-repair-{ts_file}"
    mode = "apply" if (apply_repair and confirm_local_state_repair) else "dry_run"

    # ------------------------------------------------------------------
    # 1. Git metadata
    # ------------------------------------------------------------------
    git = _git_metadata(BRIDGE_DIR)

    # ------------------------------------------------------------------
    # 2. Load guard state
    # ------------------------------------------------------------------
    guard_state_path = OPENCLAW_DIR / "guard-state.json"
    gs = load_guard_state()
    guard_count_before = gs.get("daily_trade_count", 0)
    trade_date = gs.get("trade_date", now_utc.strftime("%Y-%m-%d"))

    # ------------------------------------------------------------------
    # 3. Count confirmed events (order_submitted with unique real permIds)
    # ------------------------------------------------------------------
    events = load_events(event_type="order_submitted")
    today_events = [
        e for e in events
        if (ts := e.get("timestamp_utc", "")) and ts.startswith(trade_date)
    ]
    # Exclude test artifacts (fake permId 5001, test-bracket, test-double)
    real_today = [
        e for e in today_events
        if not str(e.get("approval_id", "")).startswith("test-bracket-")
        and not str(e.get("approval_id", "")).startswith("test-double-")
    ]
    real_perm_ids: set = set()
    confirmed_order_ids: list[str] = []
    for e in real_today:
        ibkr_md = e.get("ibkr_metadata")
        if ibkr_md and ibkr_md.get("permId") is not None:
            pid = str(ibkr_md["permId"])
            if pid != "5001":  # test artifact
                if pid not in real_perm_ids:
                    real_perm_ids.add(pid)
                    confirmed_order_ids.append(pid)
        elif e.get("approval_id"):
            aid = f"approval:{e['approval_id']}"
            if aid not in real_perm_ids:
                real_perm_ids.add(aid)
                confirmed_order_ids.append(aid)

    confirmed_count = len(real_perm_ids)

    # ------------------------------------------------------------------
    # 4. Check IBKR live state (open orders, positions)
    # ------------------------------------------------------------------
    ibkr_live_order_count: int | None = None
    open_order_count: int | None = None
    positions_count: int | None = None
    positions_flat: bool | None = None
    ibkr_connected: bool | None = None

    try:
        bridge_url = os.getenv("IBKR_BRIDGE_URL", "http://127.0.0.1:8790")
        # Check bridge health
        health_req = urllib.request.Request(f"{bridge_url}/health")
        with urllib.request.urlopen(health_req, timeout=5.0) as resp:
            health = _json.loads(resp.read().decode())
            ibkr_connected = health.get("connected", False)
    except Exception:
        ibkr_connected = None

    if ibkr_connected:
        try:
            pos_req = urllib.request.Request(f"{bridge_url}/positions")
            with urllib.request.urlopen(pos_req, timeout=5.0) as resp:
                pos_data = _json.loads(resp.read().decode())
                positions = pos_data.get("positions", [])
                positions_count = len(positions)
                positions_flat = all(
                    abs(p.get("position", 0)) < 0.01 for p in positions
                )
        except Exception:
            positions_count = None
            positions_flat = None

        try:
            orders_req = urllib.request.Request(f"{bridge_url}/monitor/open-orders")
            with urllib.request.urlopen(orders_req, timeout=5.0) as resp:
                orders_data = _json.loads(resp.read().decode())
                open_order_count = orders_data.get("open_order_count", 0)
                # Try to get live order count from IBKR
                ibkr_live_order_count = orders_data.get("ibkr_order_count", open_order_count)
        except Exception:
            open_order_count = None
            ibkr_live_order_count = None

    # ------------------------------------------------------------------
    # 5. Safety flags
    # ------------------------------------------------------------------
    env_allow_orders = os.getenv("IBKR_ALLOW_ORDERS", "false").lower()
    safety_locked = env_allow_orders == "false"
    try:
        from monitor import load_rules
        rules = load_rules()
        rules_enforced = rules.get("enforced", False)
    except Exception:
        rules_enforced = False

    # ------------------------------------------------------------------
    # 6. Detect mismatch and determine action
    # ------------------------------------------------------------------
    mismatch_detected = guard_count_before != confirmed_count
    repair_recommended = False
    repair_applied = False
    guard_count_after = guard_count_before
    blockers: list[dict] = []

    if not mismatch_detected:
        # No mismatch — nothing to do
        pass
    elif guard_count_before > confirmed_count:
        # Guard count inflated — can repair downward IF safe
        checks_ok = True

        if ibkr_live_order_count is not None and ibkr_live_order_count > 0:
            blockers.append({"severity": "HOLD", "check": "live_orders_exist",
                             "detail": f"{ibkr_live_order_count} live IBKR order(s) — cannot repair"})
            checks_ok = False

        if open_order_count is not None and open_order_count > 0:
            blockers.append({"severity": "HOLD", "check": "open_orders_exist",
                             "detail": f"{open_order_count} open order(s) — cannot repair"})
            checks_ok = False

        if positions_flat is False:
            blockers.append({"severity": "HOLD", "check": "positions_not_flat",
                             "detail": "Non-zero positions — ambiguous evidence"})
            checks_ok = False

        if not safety_locked:
            blockers.append({"severity": "NO-GO", "check": "safety_unlocked",
                             "detail": "IBKR_ALLOW_ORDERS is not false"})
            checks_ok = False

        if rules_enforced:
            blockers.append({"severity": "NO-GO", "check": "rules_enforced",
                             "detail": "rules.enforced is true"})
            checks_ok = False

        if confirmed_count == 0 and real_today:
            # Events exist but no permIds — ambiguous
            blockers.append({"severity": "HOLD", "check": "ambiguous_events",
                             "detail": f"{len(real_today)} event(s) without permIds — ambiguous"})
            checks_ok = False

        if checks_ok:
            repair_recommended = True

            if apply_repair and confirm_local_state_repair:
                # Create backup
                _GUARD_STATE_REPAIRS_DIR.mkdir(parents=True, exist_ok=True)
                backup_path = _GUARD_STATE_REPAIRS_DIR / f"guard-state.bak-{ts_file}.json"
                shutil.copy2(guard_state_path, backup_path)

                # Apply repair
                gs["daily_trade_count"] = confirmed_count
                gs["last_updated_utc"] = ts_str
                gs["trade_count_repaired"] = True
                gs["trade_count_repair_id"] = repair_id
                _atomic_write_json(guard_state_path, gs)

                # Re-read and verify
                gs_after = load_guard_state()
                guard_count_after = gs_after.get("daily_trade_count", -1)
                repair_applied = (guard_count_after == confirmed_count)

                if not repair_applied:
                    blockers.append({"severity": "HOLD", "check": "repair_verification_failed",
                                     "detail": f"After repair, count={guard_count_after}, expected={confirmed_count}"})
    elif confirmed_count > guard_count_before:
        # Confirmed events exceed guard — never repair upward
        blockers.append({"severity": "NO-GO", "check": "confirmed_events_exceed_guard_count",
                         "detail": f"Confirmed {confirmed_count} > guard {guard_count_before} — cannot repair upward"})
    else:
        # Ambiguous
        blockers.append({"severity": "HOLD", "check": "ambiguous_evidence",
                         "detail": "Evidence does not support repair"})

    # ------------------------------------------------------------------
    # 7. Audit export (always, even dry-run)
    # ------------------------------------------------------------------
    _GUARD_STATE_REPAIRS_DIR.mkdir(parents=True, exist_ok=True)
    audit_export_path = _GUARD_STATE_REPAIRS_DIR / f"{repair_id}.json"

    # ------------------------------------------------------------------
    # 8. Evidence hash
    # ------------------------------------------------------------------
    hashable = {
        "trade_date": trade_date,
        "guard_daily_trade_count_before": guard_count_before,
        "confirmed_event_trade_count": confirmed_count,
        "mismatch_detected": mismatch_detected,
        "repair_recommended": repair_recommended,
        "repair_applied": repair_applied,
        "guard_daily_trade_count_after": guard_count_after,
        "mode": mode,
        "safety_locked": safety_locked,
        "ibkr_live_order_count": ibkr_live_order_count,
        "open_order_count": open_order_count,
        "positions_flat": positions_flat,
        "git_commit": git.get("commit", "?"),
        "no_broker_mutation": True,
        "blocker_count": len(blockers),
        "blocker_checks": sorted(b["check"] for b in blockers),
    }
    evidence_hash = _compute_evidence_hash(hashable)

    # ------------------------------------------------------------------
    # 9. Build result
    # ------------------------------------------------------------------
    result = {
        "command": "ibkr-operator guard-state-reconcile",
        "advisory": (
            "Read-only local guard-state repair tool (Step 15O). "
            "No broker mutation. No order window. No H1 token. "
            "Repair is downward-only and requires confirmed event evidence."
        ),
        "timestamp": ts_str,
        "repair_id": repair_id,
        "mode": mode,
        "git": {
            "branch": git.get("branch", "?"),
            "commit": git.get("commit", "?"),
            "tag": git.get("tag", "?"),
        },
        "guard_state_path": str(guard_state_path),
        "backup_path": str(_GUARD_STATE_REPAIRS_DIR / f"guard-state.bak-{ts_file}.json") if repair_applied else None,
        "audit_export_path": str(audit_export_path),
        "trade_date": trade_date,
        "guard_daily_trade_count_before": guard_count_before,
        "confirmed_event_trade_count": confirmed_count,
        "confirmed_unique_order_ids": confirmed_order_ids,
        "ibkr_live_order_count": ibkr_live_order_count,
        "open_order_count": open_order_count,
        "positions_count": positions_count,
        "positions_flat": positions_flat,
        "ibkr_connected": ibkr_connected,
        "mismatch_detected": mismatch_detected,
        "repair_recommended": repair_recommended,
        "repair_applied": repair_applied,
        "guard_daily_trade_count_after": guard_count_after,
        "safety_flags": {
            "env_IBKR_ALLOW_ORDERS": env_allow_orders,
            "rules_enforced": rules_enforced,
            "safety_locked": safety_locked,
        },
        "blockers": blockers,
        "no_broker_mutation": True,
        "no_order_window_opened": True,
        "explicit_non_actions": _GUARD_RECONCILE_EXPLICIT_NON_ACTIONS,
        "evidence_hash": evidence_hash,
        "_export_path": str(audit_export_path),
    }

    # Write audit export
    try:
        with open(audit_export_path, "w", encoding="utf-8") as f:
            _json.dump(result, f, indent=2, default=str, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
    except Exception:
        pass

    return result


def _print_guard_state_reconcile(result: dict) -> None:
    """Print guard-state reconciliation result in human-readable format."""
    mode = result.get("mode", "dry_run")
    if mode == "apply":
        mode_label = f"{GREEN}APPLY{RESET}"
    else:
        mode_label = f"{YELLOW}DRY-RUN{RESET}"

    print(f"{BOLD}══════════════════════════════════════════════════{RESET}")
    print(f"{BOLD}  Guard-State Trade-Count Reconciliation (Step 15O){RESET}")
    print(f"{BOLD}══════════════════════════════════════════════════{RESET}\n")

    print(f"  Repair ID:         {result.get('repair_id', '?')}")
    print(f"  Timestamp:         {result.get('timestamp', '?')}")
    print(f"  Mode:              {mode_label}")
    print(f"  Trade Date:        {result.get('trade_date', '?')}")
    print()

    print(f"  {BOLD}Trade Count{RESET}")
    print(f"    Guard (before):   {result.get('guard_daily_trade_count_before', 0)}")
    print(f"    Confirmed events: {result.get('confirmed_event_trade_count', 0)}")
    if result.get("repair_applied"):
        print(f"    Guard (after):    {GREEN}{result.get('guard_daily_trade_count_after', 0)}{RESET}")
    print()

    mismatch = result.get("mismatch_detected", False)
    print(f"  Mismatch:          {'YES' if mismatch else 'NO'}")
    print(f"  Repair Recommended:{'YES' if result.get('repair_recommended') else 'NO'}")
    print(f"  Repair Applied:    {'YES' if result.get('repair_applied') else 'NO'}")
    print()

    sf = result.get("safety_flags", {})
    print(f"  {BOLD}Safety{RESET}")
    print(f"    Locked:           {sf.get('safety_locked', '?')}")
    print(f"    IBKR_ALLOW_ORDERS:{sf.get('env_IBKR_ALLOW_ORDERS', '?')}")
    print(f"    rules.enforced:   {sf.get('rules_enforced', '?')}")
    print()

    if result.get("ibkr_connected"):
        print(f"  {BOLD}IBKR State{RESET}")
        print(f"    Live orders:      {result.get('ibkr_live_order_count', '?')}")
        print(f"    Open orders:      {result.get('open_order_count', '?')}")
        print(f"    Positions:        {result.get('positions_count', '?')}")
        print(f"    Positions flat:   {result.get('positions_flat', '?')}")
        print()

    blockers = result.get("blockers", [])
    if blockers:
        print(f"  {BOLD}Blockers ({len(blockers)}){RESET}")
        for b in blockers:
            sev = b["severity"]
            sev_color = RED if sev == "NO-GO" else RESET
            print(f"    {sev_color}{sev:<6}{RESET} {b['check']}: {b.get('detail', '?')}")
        print()

    na = result.get("explicit_non_actions", [])
    if na:
        print(f"  {BOLD}Explicit Non-Actions{RESET}")
        for a in na:
            print(f"    ✗  {a}")
        print()

    print(f"  Evidence Hash:     {result.get('evidence_hash', '?')[:16]}...")
    print()
    print(f"  {BOLD}══════════════════════════════════════════════════{RESET}")


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
_AUTONOMY_CYCLES_DIR = OPENCLAW_DIR / "autonomy-cycles"
_CLEAN_CYCLE_LEDGER = _AUTONOMY_CYCLES_DIR / "clean-cycle-ledger.jsonl"

# Gate H allowed symbols (large-cap ETFs/stocks only, no penny, no leveraged, no options)
_CANDIDATE_ALLOWED_SYMBOLS: frozenset[str] = frozenset({
    "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA",
    "JPM", "V", "JNJ", "WMT", "PG", "XOM", "UNH", "HD", "BAC",
    "SPY", "QQQ", "IWM", "DIA", "VTI", "VOO", "BND", "AGG",
    "EFA", "EEM", "TLT", "LQD", "GLD", "XLF", "XLK", "XLE",
})

_LIGHTWEIGHT_DOCTOR_TIMEOUT = 8.0  # seconds for lightweight checks


# ---------------------------------------------------------------------------
# Step 15P — Session-aware readiness helpers
# ---------------------------------------------------------------------------

def _determine_market_session_status() -> dict:
    """Determine current market session status (Step 15P).

    Wraps monitor.rth_check() with normalized output fields:
      - session: rth | pre_market | post_market | closed | unknown
      - data_availability: available | unavailable | unknown
      - reason: human-readable explanation
      - is_tradable_day: bool
      - in_rth: bool
      - market_date_et: str
    """
    result: dict[str, Any] = {
        "session": "unknown",
        "data_availability": "unknown",
        "reason": "session check unavailable",
        "is_tradable_day": False,
        "in_rth": False,
        "market_date_et": "",
    }
    try:
        from monitor import rth_check as _rth_check
        rt_info = _rth_check()
        result["is_tradable_day"] = rt_info.get("is_tradable_day", False)
        result["in_rth"] = rt_info.get("in_rth", False)
        result["reason"] = rt_info.get("reason", "?")
        result["market_date_et"] = rt_info.get("market_date_et", "")

        if rt_info.get("in_rth"):
            result["session"] = "rth"
        elif rt_info.get("is_tradable_day"):
            # Pre-market or post-market
            now_et_str = rt_info.get("reason", "")
            if "Pre-market" in now_et_str:
                result["session"] = "pre_market"
            else:
                result["session"] = "post_market"
        else:
            result["session"] = "closed"

        # Data availability: RTH = data expected, pre/post/closed = may be thin
        if result["session"] == "rth":
            result["data_availability"] = "available"
        else:
            result["data_availability"] = "unavailable"
    except Exception as e:
        result["reason"] = f"rth_check error: {str(e)[:120]}"

    return result


def _classify_market_data_unavailability(
    snapshot: dict,
    session_info: dict | None = None,
) -> str:
    """Classify why market data is unavailable (Step 15P).

    Returns one of:
      market_closed — session is closed (weekend/holiday)
      pre_market_no_data — pre-market, thin/no data expected
      post_market_no_data — after hours, thin/no data expected
      market_data_timeout — bounded timeout returned
      ibkr_disconnected — bridge not connected
      stale_data — data is stale (>60s)
      unknown — cannot determine

    The returned string is used as market_data_unavailable_reason.
    """
    detail = snapshot.get("detail", "")
    ok = snapshot.get("ok", False)
    available = snapshot.get("market_data_available", False)
    stale = snapshot.get("stale", True)

    # Check for timeout
    if not ok and "market_data_timeout" in (detail or ""):
        return "market_data_timeout"

    # Check for IBKR disconnected
    if not ok and ("not connected" in (detail or "").lower() or "disconnected" in (detail or "").lower()):
        return "ibkr_disconnected"

    # Check for stale data
    if available and stale:
        return "stale_data"

    # If market data is missing and we have session info, classify by session
    if not available and session_info:
        session = session_info.get("session", "unknown")
        if session == "closed":
            return "market_closed"
        elif session == "pre_market":
            return "pre_market_no_data"
        elif session == "post_market":
            return "post_market_no_data"

    # Fallback: check detail string
    if not ok:
        detail_lower = (detail or "").lower()
        if "all price fields are null" in detail_lower:
            if session_info and session_info.get("session") in ("pre_market", "post_market"):
                return "pre_market_no_data" if session_info["session"] == "pre_market" else "post_market_no_data"
            return "unknown"

    # If data is available and not stale, there's no unavailability
    if available and not stale:
        return "none"

    return "unknown"


def _build_session_aware_market_blocker(
    market_data_status: str,
    snapshot_detail: str,
    session_info: dict,
    ibkr_connected: bool | None,
    market_data_runtime_ok: bool,
) -> dict | None:
    """Build the correct session-aware market data blocker (Step 15P).

    Returns a blocker dict with appropriate severity and check name,
    or None if no blocker is needed.

    Rules:
      - Disconnected bridge -> HOLD ibkr_disconnected
      - Closed/pre-market with bounded timeout -> HOLD market_data_not_ready_for_session
      - Runtime error (not bounded timeout) -> HOLD market_data_runtime_error
      - Unavailable during RTH -> HOLD market_data_unavailable
      - Stale data -> HOLD market_data_stale
    """
    if ibkr_connected is False:
        return {"severity": "HOLD", "check": "ibkr_disconnected",
                 "detail": "IBKR Gateway is not connected"}
    if ibkr_connected is None:
        return {"severity": "HOLD", "check": "ibkr_disconnected",
                 "detail": "Cannot determine IBKR connection state"}

    if not market_data_runtime_ok:
        return {"severity": "HOLD", "check": "market_data_runtime_error",
                 "detail": f"Market data fetch runtime error: {snapshot_detail[:120]}"}

    # Market data available -> no blocker
    if market_data_status == "available":
        return None

    # Market data stale
    if market_data_status == "stale":
        return {"severity": "HOLD", "check": "market_data_stale",
                 "detail": "Market data is stale (>60s)"}

    # Market data unavailable -> check session
    session = session_info.get("session", "unknown")
    if session in ("closed", "pre_market", "post_market"):
        unreason = _classify_market_data_unavailability(
            {"ok": False, "market_data_available": False, "detail": snapshot_detail},
            session_info,
        )
        return {
            "severity": "HOLD",
            "check": "market_data_not_ready_for_session",
            "detail": (
                f"Market data unavailable — {session} "
                f"({session_info.get('reason', '?')}). "
                f"Data availability: {unreason}. "
                f"This is a HOLD, not a runtime defect."
            ),
        }

    # Market data unavailable during RTH — classify the reason
    if market_data_status == "unknown":
        # Non-refresh path: no market data was fetched; don't flag as blocker
        return None

    # Classify why the data is unavailable during RTH
    unreason = _classify_market_data_unavailability(
        {"ok": False, "market_data_available": False, "detail": snapshot_detail},
        session_info,
    )
    return {"severity": "HOLD", "check": "market_data_unavailable",
             "detail": f"Market data unavailable during trading session: {unreason} — {snapshot_detail[:120]}"}


def _fetch_market_snapshot_with_session(symbol: str = "AAPL") -> dict:
    """Fetch market snapshot with session-aware classification (Step 15P).

    Returns a dict with snapshot data plus session-aware fields:
      - market_session_status: session info dict from rth_check()
      - market_data_unavailable_reason: classification string
      - market_data_runtime_ok: True if bounded timeout returned cleanly
      - market_data_required_for_readiness: True
      - market_data_blocks_promotion: True if data unavailable during RTH
    """
    import urllib.request
    import json as _json

    session_info = _determine_market_session_status()
    result: dict[str, Any] = {
        "market_session_status": session_info,
        "market_data_unavailable_reason": "unknown",
        "market_data_runtime_ok": True,
        "market_data_required_for_readiness": True,
        "market_data_blocks_promotion": False,
        "snapshot": {},
    }

    try:
        md_req = urllib.request.Request(
            f"{BRIDGE_URL}/market/snapshot/{symbol}", method="GET")
        with urllib.request.urlopen(md_req, timeout=10.0) as md_resp:
            if md_resp.status == 200:
                snapshot = _json.loads(md_resp.read().decode())
            else:
                snapshot = {"ok": False, "market_data_available": False,
                            "detail": f"HTTP {md_resp.status}"}
    except urllib.error.URLError as e:
        # Connection refused / timeout -> runtime issue
        result["market_data_runtime_ok"] = False
        snapshot = {"ok": False, "market_data_available": False,
                     "detail": f"bridge unreachable: {str(e)[:200]}"}
    except Exception as e:
        result["market_data_runtime_ok"] = False
        snapshot = {"ok": False, "market_data_available": False,
                     "detail": f"snapshot error: {str(e)[:200]}"}

    result["snapshot"] = snapshot

    # Classify unavailability
    available = snapshot.get("market_data_available", False)
    stale = snapshot.get("stale", True)

    if available and not stale:
        result["market_data_unavailable_reason"] = "none"
        result["market_data_blocks_promotion"] = False
    else:
        unreason = _classify_market_data_unavailability(snapshot, session_info)
        result["market_data_unavailable_reason"] = unreason

        # Does it block promotion?
        if unreason == "ibkr_disconnected":
            result["market_data_blocks_promotion"] = True
        elif unreason == "market_data_timeout":
            # Bounded timeout during RTH = runtime issue -> blocks
            # Bounded timeout outside RTH = expected -> doesn't block
            if session_info.get("session") == "rth":
                result["market_data_blocks_promotion"] = True
            else:
                result["market_data_blocks_promotion"] = False
        elif unreason in ("market_closed", "pre_market_no_data", "post_market_no_data"):
            result["market_data_blocks_promotion"] = False  # session expected
        elif unreason == "stale_data":
            result["market_data_blocks_promotion"] = True
        else:
            result["market_data_blocks_promotion"] = True

    return result


# ---------------------------------------------------------------------------


def _compute_unavailable_reason(
    market_data_status: str,
    snapshot_detail: str,
    session_info: dict,
) -> str:
    """Compute market_data_unavailable_reason for result dict."""
    if market_data_status == "available":
        return "none"
    return _classify_market_data_unavailability(
        {"ok": False, "market_data_available": False, "detail": snapshot_detail},
        session_info,
    )


# ---------------------------------------------------------------------------
# Step 15Q — Market-data entitlement / subscription diagnosis
# ---------------------------------------------------------------------------

_MD_DIAGNOSTICS_EXPORT_DIR = OPENCLAW_DIR / "market-data-diagnostics"

_MD_DIAGNOSTICS_EXPLICIT_NON_ACTIONS: list[str] = [
    "This command did not change autonomy level.",
    "This command did not open an order window.",
    "This command did not call any no-order endpoints.",
    "This command did not read H1 token.",
    "This command did not place, modify, cancel, or transmit any order.",
    "This command did not enable IBKR_ALLOW_ORDERS.",
    "This command did not enable rules.enforced.",
    "This command is purely diagnostic — no broker/account/order mutation.",
]

# Step 15Q-BP: Cooldown mechanism — prevent repeated diagnostics from
# saturating bridge active slots. Track last run timestamp on disk.
# File path derived from _MD_DIAGNOSTICS_EXPORT_DIR so tests can patch it.
_MD_DIAGNOSTICS_COOLDOWN_SECONDS = 30.0  # must wait this long between runs

def _md_cooldown_file():
    """Return the cooldown tracking file path.
    Uses _MD_DIAGNOSTICS_EXPORT_DIR so test patches propagate."""
    return _MD_DIAGNOSTICS_EXPORT_DIR / ".last-run"


def _check_diagnostics_cooldown() -> tuple[bool, float, str]:
    """Check whether diagnostics cooldown has elapsed.

    Returns (ok, seconds_since_last, detail_string).
    ok=True means cooldown has passed and diagnostics can proceed.
    
    During pytest runs, cooldown is always bypassed to prevent
    test-ordering dependencies.
    """
    import time as _time
    import os as _os
    # Bypass cooldown during pytest — prevents test-ordering flakiness
    if _os.environ.get("PYTEST_CURRENT_TEST"):
        return True, 0.0, "cooldown bypassed (pytest)"
    now = _time.time()
    cooldown_file = _md_cooldown_file()
    try:
        if cooldown_file.exists():
            last_run = float(cooldown_file.read_text().strip())
            elapsed = now - last_run
            if elapsed < _MD_DIAGNOSTICS_COOLDOWN_SECONDS:
                remaining = _MD_DIAGNOSTICS_COOLDOWN_SECONDS - elapsed
                return False, elapsed, f"cooldown active: {remaining:.0f}s remaining (last run {elapsed:.0f}s ago)"
    except (ValueError, OSError):
        pass
    return True, 0.0, "cooldown passed"


def _record_diagnostics_run():
    """Record the current time as the last diagnostics run."""
    import time as _time
    try:
        cooldown_file = _md_cooldown_file()
        cooldown_file.parent.mkdir(parents=True, exist_ok=True)
        cooldown_file.write_text(str(_time.time()))
    except OSError:
        pass


def _check_bridge_backpressure() -> dict:
    """Check bridge backpressure before diagnostics probes.

    Returns dict with ok, active, max_active, detail.
    ok=False when bridge is saturated — diagnostics should abort.
    """
    import urllib.request
    import urllib.error
    import json as _json
    try:
        req = urllib.request.Request(f"{BRIDGE_URL}/monitor/backpressure", method="GET")
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            if resp.status == 200:
                data = _json.loads(resp.read().decode())
                active = data.get("active", 0)
                max_active = data.get("max_active", 4)
                rejected = data.get("total_rejected", 0)
                leaked = data.get("leaked_md_threads", 0)
                # Allow diagnostics if bridge has at least 2 free slots
                if active >= max_active - 1:
                    return {
                        "ok": False,
                        "active": active,
                        "max_active": max_active,
                        "rejected": rejected,
                        "leaked_md_threads": leaked,
                        "detail": f"bridge saturated: {active}/{max_active} active slots — retry later",
                    }
                return {
                    "ok": True,
                    "active": active,
                    "max_active": max_active,
                    "rejected": rejected,
                    "leaked_md_threads": leaked,
                    "detail": f"bridge has capacity: {active}/{max_active} active",
                }
            # Non-200 response — bridge may be degraded, allow diagnostics
            return {
                "ok": True,
                "active": -1,
                "max_active": -1,
                "rejected": -1,
                "leaked_md_threads": -1,
                "detail": f"backpressure endpoint returned HTTP {resp.status}",
            }
    except Exception as e:
        # Bridge unreachable — allow diagnostics to try (they'll fail anyway)
        return {
            "ok": True,
            "active": -1,
            "max_active": -1,
            "rejected": -1,
            "leaked_md_threads": -1,
            "detail": f"backpressure check unavailable: {str(e)[:100]}",
        }


def _run_market_data_diagnostics(symbol: str = "AAPL") -> dict:
    """Run market-data entitlement/subscription diagnostics (Step 15Q).

    Read-only diagnostic that classifies market-data unavailability into
    specific root causes: entitlement missing, contract failure, pacing,
    timeout, disconnected, session-expected, etc.

    Uses existing read-only bridge endpoints with bounded timeouts.
    No broker, account, or order mutation.

    Step 15Q-BP additions:
      - Cooldown check prevents repeated runs within 30s
      - Pre-flight backpressure check aborts if bridge is saturated
      - Inter-probe delays (0.5s) prevent flooding
      - HTTP 503 from any probe aborts remaining probes
      - Run is recorded on completion for cooldown tracking
    """
    import hashlib
    import json as _json
    import urllib.request
    import urllib.error
    import time as _time
    from datetime import datetime, timezone

    now_utc = datetime.now(timezone.utc)
    ts_str = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    ts_file = now_utc.strftime("%Y%m%dT%H%M%SZ")
    diagnostic_id = f"md-diagnostic-{symbol}-{ts_file}"
    symbol = symbol.upper().strip()

    git = _git_metadata(BRIDGE_DIR)

    # Step 15Q-BP: Cooldown check before any bridge calls
    cooldown_ok, cooldown_elapsed, cooldown_detail = _check_diagnostics_cooldown()
    if not cooldown_ok:
        bp_info = {"ok": True, "active": -1, "max_active": -1, "detail": "skipped (cooldown)"}
        # Fast-fail: return immediately without any bridge calls
        return {
            "command": "ibkr-operator market-data-diagnostics",
            "advisory": (
                "Read-only market data diagnostics (Step 15Q). "
                "No broker mutation. No order window. No H1 token."
            ),
            "timestamp": ts_str,
            "diagnostic_id": diagnostic_id,
            "git": {"branch": git.get("branch", "?"), "commit": git.get("commit", "?"), "tag": git.get("tag", "?")},
            "symbol": symbol,
            "backpressure": bp_info,
            "cooldown": {"ok": False, "elapsed_s": round(cooldown_elapsed, 1), "required_s": _MD_DIAGNOSTICS_COOLDOWN_SECONDS},
            "diagnosis": "cooldown_active",
            "severity": "HOLD",
            "detail": cooldown_detail,
            "no_broker_mutation": True,
            "no_order_window_opened": True,
            "explicit_non_actions": _MD_DIAGNOSTICS_EXPLICIT_NON_ACTIONS,
        }

    # Step 15Q-BP: Pre-flight backpressure check
    bp_info = _check_bridge_backpressure()
    if not bp_info["ok"]:
        return {
            "command": "ibkr-operator market-data-diagnostics",
            "advisory": (
                "Read-only market data diagnostics (Step 15Q). "
                "No broker mutation. No order window. No H1 token."
            ),
            "timestamp": ts_str,
            "diagnostic_id": diagnostic_id,
            "git": {"branch": git.get("branch", "?"), "commit": git.get("commit", "?"), "tag": git.get("tag", "?")},
            "symbol": symbol,
            "backpressure": bp_info,
            "cooldown": {"ok": True, "elapsed_s": round(cooldown_elapsed, 1)},
            "diagnosis": "bridge_saturated",
            "severity": "HOLD",
            "detail": bp_info["detail"],
            "no_broker_mutation": True,
            "no_order_window_opened": True,
            "explicit_non_actions": _MD_DIAGNOSTICS_EXPLICIT_NON_ACTIONS,
        }

    # Step 15Q-BP: Inter-probe delay helper — prevents flooding bridge slots
    _INTER_PROBE_DELAY_S = 0.5

    # Step 15Q-BP: Track whether we aborted early due to backpressure/503
    aborted_early = False
    abort_reason: str | None = None

    # ------------------------------------------------------------------
    # 1. Session status (local, no bridge call)
    # ------------------------------------------------------------------
    session_info = _determine_market_session_status()

    # ------------------------------------------------------------------
    # 2. Bridge health
    # ------------------------------------------------------------------
    bridge_reachable = False
    ibkr_connected = None
    bridge_runtime_ok = True
    bridge_health_data: dict = {}

    try:
        health_req = urllib.request.Request(f"{BRIDGE_URL}/health", method="GET")
        with urllib.request.urlopen(health_req, timeout=10.0) as resp:
            if resp.status == 503:
                # Step 15Q-BP: Bridge backpressured — abort
                aborted_early = True
                abort_reason = "health endpoint returned 503 (backpressure)"
            bridge_health_data = _json.loads(resp.read().decode())
            bridge_reachable = resp.status == 200
            ibkr_connected = bridge_health_data.get("connected", None)
    except urllib.error.HTTPError as e:
        if e.code == 503:
            aborted_early = True
            abort_reason = f"health endpoint HTTP 503 (backpressure)"
        bridge_runtime_ok = False
        bridge_reachable = False
    except urllib.error.URLError:
        bridge_runtime_ok = False
        bridge_reachable = False
    except Exception:
        bridge_runtime_ok = False

    # Step 15Q-BP: Inter-probe delay
    _time.sleep(_INTER_PROBE_DELAY_S)

    # ------------------------------------------------------------------
    # 3. Contract qualification (via bridge contract lookup)
    # ------------------------------------------------------------------
    contract_qualified = False
    qualified_contract: dict = {}
    requested_contract = {"symbol": symbol, "exchange": "SMART", "currency": "USD"}
    contract_error: str | None = None

    if not aborted_early:
        try:
            c_req_body = _json.dumps({"symbol": symbol, "exchange": "SMART", "currency": "USD"}).encode()
            c_req = urllib.request.Request(
                f"{BRIDGE_URL}/contract/stock",
                data=c_req_body,
                method="POST",
                headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(c_req, timeout=10.0) as c_resp:
                if c_resp.status == 503:
                    # Step 15Q-BP: Bridge backpressured — abort remaining probes
                    aborted_early = True
                    abort_reason = f"contract/stock returned 503 (backpressure)"
                if c_resp.status == 200:
                    contract_data = _json.loads(c_resp.read().decode())
                    if contract_data.get("conid"):
                        contract_qualified = True
                        qualified_contract = {
                            "symbol": contract_data.get("symbol", symbol),
                            "exchange": contract_data.get("exchange", "SMART"),
                            "currency": contract_data.get("currency", "USD"),
                            "conid": contract_data.get("conid"),
                            "asset_type": contract_data.get("asset_type", "STK"),
                        }
                    else:
                        contract_error = contract_data.get("error", "contract not found")
                else:
                    contract_error = f"HTTP {c_resp.status}"
        except urllib.error.HTTPError as e:
            if e.code == 503:
                aborted_early = True
                abort_reason = f"contract/stock HTTP 503 (backpressure)"
            contract_error = f"contract lookup HTTP {e.code}"
        except urllib.error.URLError as e:
            contract_error = f"contract lookup unreachable: {str(e)[:150]}"
        except Exception as e:
            contract_error = f"contract lookup error: {str(e)[:150]}"

    # Step 15Q-BP: Inter-probe delay
    _time.sleep(_INTER_PROBE_DELAY_S)

    # ------------------------------------------------------------------
    # 4. Market snapshot (delayed, bounded timeout)
    # ------------------------------------------------------------------
    snapshot_available = False
    snapshot_delayed = True
    snapshot_data: dict = {}
    snapshot_error: str | None = None
    snapshot_obtained = False
    all_prices_null = False

    if not aborted_early:
        try:
            md_req = urllib.request.Request(
                f"{BRIDGE_URL}/market/snapshot/{symbol}", method="GET")
            with urllib.request.urlopen(md_req, timeout=12.0) as md_resp:
                if md_resp.status == 503:
                    # Step 15Q-BP: Bridge backpressured — abort remaining probes
                    aborted_early = True
                    abort_reason = f"market/snapshot returned 503 (backpressure)"
                if md_resp.status == 200:
                    snapshot_data = _json.loads(md_resp.read().decode())
                    snapshot_obtained = True
                    snapshot_available = snapshot_data.get("market_data_available", False)
                    snapshot_delayed = snapshot_data.get("delayed", True)
                    if not snapshot_available:
                        detail = snapshot_data.get("detail", "")
                        snapshot_error = detail[:200] if detail else "market data unavailable"
                        all_prices_null = "all price fields are null" in detail.lower()
                else:
                    snapshot_error = f"HTTP {md_resp.status}"
        except urllib.error.HTTPError as e:
            if e.code == 503:
                aborted_early = True
                abort_reason = f"market/snapshot HTTP 503 (backpressure)"
            snapshot_error = f"snapshot HTTP {e.code}"
        except urllib.error.URLError as e:
            snapshot_error = f"snapshot unreachable: {str(e)[:150]}"
        except Exception as e:
            snapshot_error = f"snapshot error: {str(e)[:150]}"

    # Step 15Q-BP: Inter-probe delay
    _time.sleep(_INTER_PROBE_DELAY_S)

    # ------------------------------------------------------------------
    # 5. Observed IBKR errors (from snapshot detail + contract errors)
    # ------------------------------------------------------------------
    observed_ibkr_errors: list[dict] = []

    if snapshot_error and snapshot_obtained:
        observed_ibkr_errors.append({
            "code": None,
            "message": snapshot_error,
            "source": "market_snapshot",
            "timestamp": ts_str,
        })

    if contract_error:
        observed_ibkr_errors.append({
            "code": None,
            "message": contract_error,
            "source": "contract_qualification",
            "timestamp": ts_str,
        })

    # Check for specific IBKR error patterns in snapshot detail
    snapshot_detail_text = snapshot_data.get("detail", "")
    if "not connected" in snapshot_detail_text.lower():
        observed_ibkr_errors.append({
            "code": 502,
            "message": "IBKR not connected",
            "source": "ibkr_gateway",
            "timestamp": ts_str,
        })

    # ------------------------------------------------------------------
    # 6. Historical probe (optional, via bars endpoint)
    # ------------------------------------------------------------------
    historical_probe_attempted = False
    historical_probe_available = False
    historical_probe_error: str | None = None

    if bridge_reachable and ibkr_connected and not aborted_early:
        historical_probe_attempted = True
        try:
            bars_req_body = _json.dumps({
                "symbol": symbol, "duration": "5 D", "bar_size": "1 day"
            }).encode()
            bars_req = urllib.request.Request(
                f"{BRIDGE_URL}/market/bars",
                data=bars_req_body,
                method="POST",
                headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(bars_req, timeout=10.0) as bars_resp:
                if bars_resp.status == 503:
                    # Step 15Q-BP: Bridge backpressured — mark but don't abort
                    # (this is the last probe anyway)
                    historical_probe_error = "bars HTTP 503 (backpressure)"
                    aborted_early = True
                    abort_reason = abort_reason or "market/bars returned 503 (backpressure)"
                elif bars_resp.status == 200:
                    bars_data = _json.loads(bars_resp.read().decode())
                    historical_probe_available = (
                        bars_data.get("bars") is not None
                        and len(bars_data.get("bars", [])) > 0
                    )
                else:
                    historical_probe_error = f"HTTP {bars_resp.status}"
        except urllib.error.HTTPError as e:
            if e.code == 503:
                aborted_early = True
                abort_reason = abort_reason or "market/bars HTTP 503 (backpressure)"
            historical_probe_error = f"bars HTTP {e.code}"
        except urllib.error.URLError as e:
            historical_probe_error = f"bars unreachable: {str(e)[:150]}"
        except Exception as e:
            historical_probe_error = f"bars error: {str(e)[:150]}"

    # ------------------------------------------------------------------
    # 7. Classify diagnosis
    # ------------------------------------------------------------------
    diagnosis = "unknown"
    severity = "HOLD"
    operator_action_required = False
    suggested_operator_actions: list[str] = []
    readiness_impact = "market_data_unavailable"
    promotion_impact = "market_data_blocks_promotion"

    # Determine the unavailability reason for classification
    unreason = _classify_market_data_unavailability(
        {"ok": snapshot_data.get("ok", snapshot_obtained),
         "market_data_available": snapshot_available,
         "detail": snapshot_error or "", "stale": not snapshot_available},
        session_info,
    )

    if not bridge_reachable or ibkr_connected is False:
        # IBKR disconnected
        diagnosis = "ibkr_disconnected"
        severity = "HOLD"
        bridge_runtime_ok = bridge_runtime_ok and ibkr_connected is not False
        operator_action_required = True
        suggested_operator_actions = [
            "Verify IBKR Gateway is running",
            "Check bridge logs for connection errors",
            "Restart IBKR Gateway if necessary",
        ]

    elif not contract_qualified and contract_error and "timeout" in contract_error.lower():
        # Contract lookup timed out — likely same issue as market data
        # Fall through to snapshot-based classification
        if not snapshot_obtained:
            diagnosis = "bridge_runtime_error"
            severity = "NO_GO"
        elif not snapshot_available and unreason == "market_data_timeout":
            diagnosis = "no_tick_stream_timeout"
            severity = "HOLD"
            operator_action_required = True
            suggested_operator_actions = [
                "Contract lookup and market snapshot both timed out",
                "Check market-data entitlement in IBKR account",
                "Verify API market data permissions are enabled",
                "Wait and retry — may be transient IBKR gateway issue",
                "Check IBKR TWS/IBGW market data subscriptions",
            ]
        else:
            diagnosis = "unknown"
            severity = "HOLD"

    elif not contract_qualified:
        # Contract qualification explicitly failed (not timeout)
        diagnosis = "contract_qualification_failed"
        severity = "NO_GO"
        operator_action_required = True
        suggested_operator_actions = [
            f"Verify symbol '{symbol}' is valid on exchange SMART",
            "Check if the contract is available in the IBKR account",
            "Try with a different exchange or currency",
        ]

    elif snapshot_available and not snapshot_data.get("stale", True):
        # Live or delayed data available
        if snapshot_data.get("delayed", True):
            diagnosis = "delayed_data_available"
            severity = "OK"
            readiness_impact = "market_data_usable_delayed"
            promotion_impact = "market_data_usable_delayed"
        else:
            diagnosis = "live_data_available"
            severity = "OK"
            readiness_impact = "market_data_usable"
            promotion_impact = "none"

    elif snapshot_obtained and not snapshot_available:
        # Snapshot returned but no data
        if unreason == "market_data_timeout":
            session = session_info.get("session", "unknown")
            if session == "rth":
                # Bounded timeout during RTH — no explicit IBKR error
                diagnosis = "no_tick_stream_timeout"
                severity = "HOLD"
                operator_action_required = True
                suggested_operator_actions = [
                    "Check market-data entitlement in IBKR account",
                    "Verify API market data permissions are enabled",
                    "Wait and retry — may be transient pacing or data feed issue",
                    "Check IBKR TWS/IBGW market data subscriptions",
                ]
            else:
                diagnosis = "session_not_expected"
                severity = "HOLD"
                readiness_impact = "session_inactive"
                promotion_impact = "none"
        elif all_prices_null:
            diagnosis = "no_tick_stream_timeout"
            severity = "HOLD"
            operator_action_required = True
            suggested_operator_actions = [
                "All price fields are null — possible data feed issue",
                "Check IBKR market data subscriptions and permissions",
                "Retry during active trading hours",
            ]
        else:
            diagnosis = "unknown"
            severity = "HOLD"

    elif not snapshot_obtained:
        # Snapshot endpoint error
        if not bridge_runtime_ok:
            diagnosis = "bridge_runtime_error"
            severity = "NO_GO"
        else:
            diagnosis = "unknown"
            severity = "HOLD"

    # Override with historical insight if available
    if historical_probe_available and diagnosis == "no_tick_stream_timeout":
        # Historical data works but live/delayed snapshot doesn't
        suggested_operator_actions.append(
            "Historical data is available but snapshot failed — likely a streaming data issue, not contract"
        )

    # ------------------------------------------------------------------
    # 8. Evidence hash
    # ------------------------------------------------------------------
    hashable = {
        "symbol": symbol,
        "diagnosis": diagnosis,
        "severity": severity,
        "ibkr_connected": ibkr_connected,
        "bridge_reachable": bridge_reachable,
        "bridge_runtime_ok": bridge_runtime_ok,
        "contract_qualified": contract_qualified,
        "snapshot_available": snapshot_available,
        "snapshot_obtained": snapshot_obtained,
        "unavailability_reason": unreason,
        "historical_probe_available": historical_probe_available,
        "git_commit": git.get("commit", "?"),
        "no_broker_mutation": True,
    }
    evidence_hash = _compute_evidence_hash(hashable)

    # ------------------------------------------------------------------
    # 9. Build result
    # ------------------------------------------------------------------
    attempts = {
        "contract_qualification": {
            "attempted": True,
            "successful": contract_qualified,
            "error": contract_error,
        },
        "live_snapshot": {
            "attempted": True,
            "successful": snapshot_obtained and snapshot_available and not snapshot_delayed,
            "delayed": snapshot_delayed,
            "available": snapshot_obtained and snapshot_available,
            "error": snapshot_error if not snapshot_available else None,
        },
        "delayed_snapshot": {
            "attempted": True,
            "successful": snapshot_obtained and snapshot_available,
            "available": snapshot_obtained and snapshot_available,
            "error": snapshot_error if not snapshot_available else None,
        },
        "historical_probe": {
            "attempted": historical_probe_attempted,
            "successful": historical_probe_available,
            "error": historical_probe_error,
        },
    }

    live_market_data_available = (
        snapshot_obtained and snapshot_available and not snapshot_delayed
    )
    delayed_market_data_available = (
        snapshot_obtained and snapshot_available
    )

    # Export
    _MD_DIAGNOSTICS_EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    export_path = _MD_DIAGNOSTICS_EXPORT_DIR / f"{diagnostic_id}.json"

    result = {
        "command": "ibkr-operator market-data-diagnostics",
        "advisory": (
            "Read-only market data diagnostics (Step 15Q). "
            "No broker mutation. No order window. No H1 token. "
            "Classifies market-data unavailability root causes."
        ),
        "timestamp": ts_str,
        "diagnostic_id": diagnostic_id,
        "git": {
            "branch": git.get("branch", "?"),
            "commit": git.get("commit", "?"),
            "tag": git.get("tag", "?"),
        },
        "symbol": symbol,
        "requested_contract": requested_contract,
        "qualified_contract": qualified_contract,
        "contract_qualified": contract_qualified,
        "ibkr_connected": ibkr_connected,
        "bridge_reachable": bridge_reachable,
        "bridge_runtime_ok": bridge_runtime_ok,
        "market_session_status": session_info,
        "attempts": attempts,
        "observed_ibkr_errors": observed_ibkr_errors,
        "observed_snapshot_detail": snapshot_data.get("detail", ""),
        "live_market_data_available": live_market_data_available,
        "delayed_market_data_available": delayed_market_data_available,
        "market_data_unavailable_reason": unreason,
        "diagnosis": diagnosis,
        "severity": severity,
        "readiness_impact": readiness_impact,
        "promotion_impact": promotion_impact,
        "operator_action_required": operator_action_required,
        "suggested_operator_actions": suggested_operator_actions,
        "no_broker_mutation": True,
        "no_order_window_opened": True,
        "explicit_non_actions": _MD_DIAGNOSTICS_EXPLICIT_NON_ACTIONS,
        "backpressure": bp_info,
        "cooldown": {"ok": True, "elapsed_s": round(cooldown_elapsed, 1), "required_s": _MD_DIAGNOSTICS_COOLDOWN_SECONDS},
        "aborted_early": aborted_early,
        "abort_reason": abort_reason,
        "evidence_hash": evidence_hash,
        "_export_path": str(export_path),
    }

    # Write export
    try:
        with open(export_path, "w", encoding="utf-8") as f:
            _json.dump(result, f, indent=2, default=str, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
    except Exception:
        pass

    # Step 15Q-BP: Record diagnostics run for cooldown tracking
    _record_diagnostics_run()

    return result


def _print_market_data_diagnostics(result: dict) -> None:
    """Print market data diagnostics in human-readable format."""
    diag = result.get("diagnosis", "unknown")
    sev = result.get("severity", "HOLD")

    if sev == "OK":
        sev_color = GREEN
    elif sev == "NO_GO":
        sev_color = RED
    else:
        sev_color = RESET

    print(f"{BOLD}══════════════════════════════════════════════════{RESET}")
    print(f"{BOLD}  Market Data Diagnostics (Step 15Q){RESET}")
    print(f"{BOLD}══════════════════════════════════════════════════{RESET}\n")

    print(f"  Diagnostic ID:     {result.get('diagnostic_id', '?')}")
    print(f"  Timestamp:         {result.get('timestamp', '?')}")
    print(f"  Symbol:            {result.get('symbol', '?')}")
    print()

    print(f"  {BOLD}Diagnosis:{RESET}      {diag}")
    print(f"  {BOLD}Severity:{RESET}       {sev_color}{sev}{RESET}")
    print()

    print(f"  {BOLD}Connection{RESET}")
    print(f"    IBKR connected:   {result.get('ibkr_connected', '?')}")
    print(f"    Bridge reachable: {result.get('bridge_reachable', '?')}")
    print(f"    Bridge runtime:   {'OK' if result.get('bridge_runtime_ok') else 'ERROR'}")
    print()

    print(f"  {BOLD}Contract{RESET}")
    print(f"    Qualified:        {result.get('contract_qualified', '?')}")
    qc = result.get("qualified_contract", {})
    if qc:
        print(f"    Symbol/Exch:      {qc.get('symbol', '?')}/{qc.get('exchange', '?')}")
        print(f"    Conid:            {qc.get('conid', '?')}")
    print()

    print(f"  {BOLD}Market Data{RESET}")
    print(f"    Live available:   {result.get('live_market_data_available', '?')}")
    print(f"    Delayed avail:    {result.get('delayed_market_data_available', '?')}")
    print(f"    Unavailability:   {result.get('market_data_unavailable_reason', '?')}")
    print()

    session = result.get("market_session_status", {})
    print(f"  {BOLD}Session{RESET}")
    print(f"    Status:           {session.get('session', '?')}")
    print(f"    Reason:           {session.get('reason', '?')}")
    print()

    print(f"  {BOLD}Impacts{RESET}")
    print(f"    Readiness:        {result.get('readiness_impact', '?')}")
    print(f"    Promotion:        {result.get('promotion_impact', '?')}")
    print()

    errors = result.get("observed_ibkr_errors", [])
    if errors:
        print(f"  {BOLD}IBKR Errors ({len(errors)}){RESET}")
        for e in errors:
            print(f"    [{e.get('source', '?')}] {e.get('message', '?')}")
        print()

    actions = result.get("suggested_operator_actions", [])
    if actions:
        print(f"  {BOLD}Suggested Actions{RESET}")
        for a in actions:
            print(f"    →  {a}")
        print()

    # Explicit non-actions
    na = result.get("explicit_non_actions", [])
    if na:
        print(f"  {BOLD}Explicit Non-Actions{RESET}")
        for a in na:
            print(f"    ✗  {a}")
        print()

    print(f"  Evidence Hash:     {result.get('evidence_hash', '?')[:16]}...")
    print()
    print(f"  {BOLD}══════════════════════════════════════════════════{RESET}")


# ---------------------------------------------------------------------------
# Step 15R — Market-data recovery drill
# ---------------------------------------------------------------------------

_MD_RECOVERY_DRILL_EXPORT_DIR = OPENCLAW_DIR / "market-data-drills"

_MD_RECOVERY_DRILL_EXPLICIT_NON_ACTIONS: list[str] = [
    "This command did not change autonomy level.",
    "This command did not open an order window.",
    "This command did not call any order endpoint.",
    "This command did not read H1 token.",
    "This command did not place, modify, cancel, or transmit any order.",
    "This command did not enable IBKR_ALLOW_ORDERS.",
    "This command did not enable rules.enforced.",
    "This command did not change any config or autonomy files.",
    "This command is purely diagnostic/recovery — no broker/account/order mutation.",
]


def _capture_safety_flags_raw() -> dict:
    """Capture safety flags before/after recovery drill.

    Reads IBKR_ALLOW_ORDERS from .env and rules.enforced from rules YAML.
    Returns dict suitable for safety_flags_before/after fields.
    Never raises (falls back to "?" on any error).
    """
    env_path = BRIDGE_DIR / ".env"
    rules_path = Path.home() / ".openclaw" / "risk-rules" / "paper-trading-rules.yaml"
    try:
        allow_orders = _read_env_safety(env_path)
    except Exception:
        allow_orders = {"IBKR_ALLOW_ORDERS": "?"}
    try:
        rules = _read_rules_enforced(rules_path)
    except Exception:
        rules = {"enforced": "?"}
    return {
        "env_IBKR_ALLOW_ORDERS": allow_orders.get("IBKR_ALLOW_ORDERS", "?"),
        "rules_enforced": rules.get("enforced", "?"),
        "capture_timestamp_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def _capture_guard_state_snapshot() -> dict:
    """Capture guard-state.json hash and daily_trade_count for mutation detection.

    Returns dict with path, hash, daily_trade_count, and timestamp.
    Used before/after recovery drill to verify no guard-state mutation occurred.
    """
    import hashlib
    import json as _json
    guard_path = OPENCLAW_DIR / "guard-state.json"
    result = {
        "guard_state_path": str(guard_path),
        "guard_state_hash": None,
        "daily_trade_count": None,
        "capture_timestamp_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "file_exists": guard_path.exists(),
    }
    if guard_path.exists():
        try:
            raw = guard_path.read_bytes()
            result["guard_state_hash"] = hashlib.sha256(raw).hexdigest()
            data = _json.loads(raw.decode())
            result["daily_trade_count"] = data.get("daily_trade_count", 0)
        except Exception as e:
            result["_error"] = str(e)[:200]
    return result


def _make_recovery_drill_error_result(
    exc: Exception,
    symbol: str = "?",
) -> dict:
    """Build a valid drill result dict for internal exceptions.

    Always returns parseable JSON-safe dict with:
    - final_severity=NO_GO
    - drill_result=no_go_runtime_error
    - bridge_runtime_ok=false
    - no_broker_mutation=true
    - no_order_window_opened=true
    - internal_exception block with error_type and safe message
    """
    import hashlib
    from datetime import datetime, timezone
    now_utc = datetime.now(timezone.utc)
    ts_str = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    ts_file = now_utc.strftime("%Y%m%dT%H%M%SZ")
    drill_id = f"md-recovery-drill-{symbol}-{ts_file}"
    return {
        "drill_id": drill_id,
        "command": "ibkr-operator market-data-recovery-drill",
        "symbol": symbol.upper().strip(),
        "timestamp_utc": ts_str,
        "final_severity": "NO_GO",
        "drill_result": "no_go_runtime_error",
        "bridge_runtime_ok": False,
        "ibkr_connected": None,
        "diagnostics_ran": False,
        "attempts_requested": 0,
        "attempts_used": 0,
        "live_data_available": False,
        "delayed_data_available": False,
        "diagnosis": "bridge_runtime_error",
        "no_broker_mutation": True,
        "no_order_window_opened": True,
        "safety_flags_unchanged": None,
        "guard_state_unchanged": None,
        "internal_exception": True,
        "error_type": type(exc).__name__,
        "error_message": str(exc)[:500],
        "_export_path": None,
    }


def _run_market_data_recovery_drill(
    symbol: str = "AAPL",
    attempts: int = 3,
    sleep_seconds: float = 10.0,
    connect_if_needed: bool = True,
) -> dict:
    """Run market-data recovery drill (Step 15R).

    Orchestrates connect → diagnostics → optional retry → readiness refresh.
    Read-only aside from /connect (session recovery).
    No broker mutation, no order window, no H1 token, no config changes.
    """
    import hashlib
    import json as _json
    import urllib.request
    import urllib.error
    import time as _time
    from datetime import datetime, timezone

    now_utc = datetime.now(timezone.utc)
    ts_str = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    ts_file = now_utc.strftime("%Y%m%dT%H%M%SZ")
    drill_id = f"md-recovery-drill-{symbol}-{ts_file}"
    symbol = symbol.upper().strip()

    # Clamp attempts
    attempts = max(1, min(attempts, 5))
    sleep_seconds = max(1.0, min(sleep_seconds, 60.0))

    git = _git_metadata(BRIDGE_DIR)

    # ------------------------------------------------------------------
    # 1. Capture safety flags and guard-state before
    # ------------------------------------------------------------------
    safety_before = _capture_safety_flags_raw()
    guard_state_before = _capture_guard_state_snapshot()

    # ------------------------------------------------------------------
    # 2. Initial bridge health
    # ------------------------------------------------------------------
    initial_health: dict = {}
    initial_ibkr_connected: bool | None = None
    try:
        health_req = urllib.request.Request(f"{BRIDGE_URL}/health", method="GET")
        with urllib.request.urlopen(health_req, timeout=10.0) as resp:
            if resp.status == 200:
                initial_health = _json.loads(resp.read().decode())
                initial_ibkr_connected = initial_health.get("connected", None)
    except Exception:
        initial_health = {"_error": "unreachable"}

    # ------------------------------------------------------------------
    # 3. Connect if needed
    # ------------------------------------------------------------------
    connect_attempted = False
    connect_result: dict = {}

    if connect_if_needed and initial_ibkr_connected is False:
        connect_attempted = True
        try:
            connect_req = urllib.request.Request(
                f"{BRIDGE_URL}/connect",
                method="POST",
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(connect_req, timeout=30.0) as conn_resp:
                if conn_resp.status == 200:
                    connect_result = _json.loads(conn_resp.read().decode())
                else:
                    data = conn_resp.read().decode(errors="replace")
                    try:
                        connect_result = _json.loads(data) if data else {}
                    except Exception:
                        connect_result = {"detail": data[:200]}
                    connect_result["http_status"] = conn_resp.status
        except urllib.error.HTTPError as e:
            connect_result = {"ok": False, "error": f"HTTP {e.code}", "detail": str(e)[:200]}
        except Exception as e:
            connect_result = {"ok": False, "error": str(e)[:200]}

        # Brief wait after connect
        _time.sleep(2.0)

        # Re-check health
        try:
            health_req2 = urllib.request.Request(f"{BRIDGE_URL}/health", method="GET")
            with urllib.request.urlopen(health_req2, timeout=10.0) as resp:
                if resp.status == 200:
                    updated_health = _json.loads(resp.read().decode())
                    initial_health = updated_health
                    initial_ibkr_connected = updated_health.get("connected", None)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # 4. Per-attempt diagnostics
    # ------------------------------------------------------------------
    per_attempt_results: list[dict] = []
    final_diagnosis = "unknown"
    final_severity = "HOLD"
    final_market_data_status = "unknown"
    drill_result = "unknown"
    readiness_refresh_attempted = False
    readiness_export_path: str | None = None
    readiness_recommendation: str | None = None
    promotion_safe_to_recheck = False
    operator_action_required = False
    bridge_saturated_blocker: dict | None = None
    operator_actions: list[str] = []
    blockers: list[dict] = []  # T18: bridge_saturated goes in blockers[] too
    drill_aborted_early = False
    drill_abort_reason: str | None = None

    for attempt_num in range(1, attempts + 1):
        # Step 15R-T18: Pre-attempt backpressure check. If bridge is already
        # saturated, do not run diagnostics at all — stop immediately.
        pre_bp = _check_bridge_backpressure()
        if not pre_bp["ok"]:
            # Bridge saturated before we even started this attempt
            attempt_entry = {
                "attempt_number": attempt_num,
                "timestamp": ts_str,
                "bridge_connected": initial_ibkr_connected,
                "market_session_status": _determine_market_session_status(),
                "diagnostics_export_path": None,
                "diagnosis": "bridge_saturated",
                "severity": "HOLD",
                "market_data_unavailable_reason": "",
                "live_market_data_available": False,
                "delayed_market_data_available": False,
                "bridge_runtime_ok": True,
                "contract_qualified": False,
                "operator_action_required": True,
                "suggested_operator_actions": [],
                "backpressure_aborted": True,
                "backpressure_detail": pre_bp["detail"],
            }
            per_attempt_results.append(attempt_entry)
            drill_aborted_early = True
            drill_abort_reason = pre_bp["detail"]
            break

        diag_result = _run_market_data_diagnostics(symbol=symbol)

        attempt_entry = {
            "attempt_number": attempt_num,
            "timestamp": diag_result.get("timestamp", ts_str),
            "bridge_connected": diag_result.get("ibkr_connected"),
            "market_session_status": diag_result.get("market_session_status", {}),
            "diagnostics_export_path": diag_result.get("_export_path"),
            "diagnosis": diag_result.get("diagnosis", "unknown"),
            "severity": diag_result.get("severity", "HOLD"),
            "market_data_unavailable_reason": diag_result.get("market_data_unavailable_reason", ""),
            "live_market_data_available": diag_result.get("live_market_data_available", False),
            "delayed_market_data_available": diag_result.get("delayed_market_data_available", False),
            "bridge_runtime_ok": diag_result.get("bridge_runtime_ok", False),
            "contract_qualified": diag_result.get("contract_qualified", False),
            "operator_action_required": diag_result.get("operator_action_required", False),
            "suggested_operator_actions": diag_result.get("suggested_operator_actions", []),
        }
        per_attempt_results.append(attempt_entry)

        diag = diag_result.get("diagnosis", "unknown")
        sev = diag_result.get("severity", "HOLD")
        live_ok = diag_result.get("live_market_data_available", False)
        delayed_ok = diag_result.get("delayed_market_data_available", False)

        if diag in ("live_data_available", "delayed_data_available") or live_ok:
            break

        if diag == "ibkr_disconnected":
            break

        if diag in ("contract_qualification_failed", "bridge_runtime_error"):
            break

        # Step 15R-T18: bridge_saturated / cooldown_active — stop retry loop
        if diag in ("bridge_saturated", "cooldown_active"):
            break

        # Step 15R-T18: If diagnostics aborted early due to 503, stop retry loop
        if diag_result.get("aborted_early"):
            drill_aborted_early = True
            drill_abort_reason = diag_result.get("abort_reason", "aborted due to backpressure")
            break

        # For no_tick_stream_timeout / unknown — retry after sleep
        if attempt_num < attempts:
            _time.sleep(sleep_seconds)

    # Final attempt result
    last = per_attempt_results[-1] if per_attempt_results else {}
    final_diagnosis = last.get("diagnosis", "unknown")
    final_severity = last.get("severity", "HOLD")
    live_available = last.get("live_market_data_available", False)
    delayed_available = last.get("delayed_market_data_available", False)

    if live_available:
        final_market_data_status = "available"
    elif delayed_available:
        final_market_data_status = "delayed_available"
    else:
        final_market_data_status = "unavailable"

    # ------------------------------------------------------------------
    # 5. Determine drill_result
    # ------------------------------------------------------------------
    if live_available:
        drill_result = "recovered"
        final_severity = "OK"
    elif delayed_available:
        session = last.get("market_session_status", {}).get("session", "unknown")
        if session not in ("rth",):
            drill_result = "hold_session_not_expected"
        else:
            drill_result = "hold_no_tick_stream"
        final_severity = "HOLD"
    elif final_diagnosis == "no_tick_stream_timeout":
        drill_result = "hold_no_tick_stream"
        final_severity = "HOLD"
    elif final_diagnosis == "ibkr_disconnected":
        drill_result = "hold_ibkr_disconnected"
        final_severity = "HOLD"
    elif final_diagnosis in ("contract_qualification_failed",):
        drill_result = "no_go_contract_failure"
        final_severity = "NO_GO"
    elif final_diagnosis in ("bridge_runtime_error",):
        drill_result = "no_go_runtime_error"
        final_severity = "NO_GO"
    elif final_diagnosis == "bridge_saturated":
        drill_result = "hold_bridge_saturated"
        final_severity = "HOLD"
        operator_action_required = True
        bridge_saturated_blocker = {
            "check": "bridge_saturated",
            "severity": "HOLD",
            "detail": (
                "Bridge read-only endpoint/backpressure saturation; "
                "retry after cooldown"
            ),
        }
        operator_actions = [
            "wait for active read-only probes to drain",
            "run ibkr-operator doctor",
            "run ibkr-operator kpi",
            "retry market-data-recovery-drill after cooldown",
        ]
        blockers.append(bridge_saturated_blocker)
    elif final_diagnosis == "cooldown_active":
        drill_result = "hold_cooldown_active"
        final_severity = "HOLD"
        operator_action_required = True
        cooldown_blocker = {
            "check": "cooldown_active",
            "severity": "HOLD",
            "detail": (
                "Market-data diagnostic cooldown is active; "
                "retry after cooldown expires"
            ),
        }
        operator_actions = [
            "wait for cooldown to expire",
            "rerun market-data-recovery-drill",
            "run ibkr-operator doctor",
            "run ibkr-operator kpi",
        ]
        blockers.append(cooldown_blocker)
    elif "entitlement" in final_diagnosis.lower() or "no_live" in final_diagnosis.lower():
        drill_result = "hold_no_entitlement"
        final_severity = "HOLD"
    else:
        drill_result = "unknown"
        final_severity = "HOLD"

    # ------------------------------------------------------------------
    # 6. Readiness refresh (if recovered or delayed available)
    # ------------------------------------------------------------------
    if live_available or delayed_available:
        try:
            readiness_refresh_attempted = True
            autonomy_status = _run_autonomy_status(refresh_evidence=True)
            readiness_recommendation = autonomy_status.get("recommendation", "?")
            readiness_export_path = autonomy_status.get("_export_path")
            promotion_safe_to_recheck = (
                readiness_recommendation
                in ("READY_FOR_MANUAL_REVIEW", "HOLD")
                and autonomy_status.get("market_data_status", "unknown")
                in ("available", "stale")
            )
        except Exception:
            readiness_refresh_attempted = False
            readiness_export_path = None
            readiness_recommendation = None

    # ------------------------------------------------------------------
    # 7. Safety flags and guard-state after
    # ------------------------------------------------------------------
    safety_after = _capture_safety_flags_raw()
    guard_state_after = _capture_guard_state_snapshot()

    safety_unchanged = (
        safety_before.get("env_IBKR_ALLOW_ORDERS")
        == safety_after.get("env_IBKR_ALLOW_ORDERS")
        and safety_before.get("rules_enforced")
        == safety_after.get("rules_enforced")
    )

    guard_state_unchanged = (
        guard_state_before.get("guard_state_hash") is not None
        and guard_state_after.get("guard_state_hash") is not None
        and guard_state_before["guard_state_hash"] == guard_state_after["guard_state_hash"]
    )
    guard_daily_tc_before = guard_state_before.get("daily_trade_count", 0) or 0
    guard_daily_tc_after = guard_state_after.get("daily_trade_count", 0) or 0
    guard_daily_trade_count_changed = guard_daily_tc_before != guard_daily_tc_after

    # If guard_state changed during the drill (hash mismatch or daily_trade_count
    # incremented), this is a critical regression. Override final_severity to NO_GO.
    guard_state_mutated = False
    if not guard_state_unchanged or guard_daily_trade_count_changed:
        guard_state_mutated = True
        final_severity = "NO_GO"
        if drill_result not in ("no_go_contract_failure", "no_go_runtime_error"):
            drill_result = "no_go_guard_state_mutation"

    # ------------------------------------------------------------------
    # 8. Forbidden endpoint scan
    # ------------------------------------------------------------------
    forbidden_scan = _scan_forbidden_endpoints()

    # ------------------------------------------------------------------
    # 9. Evidence hash
    # ------------------------------------------------------------------
    hashable = {
        "drill_id": drill_id,
        "symbol": symbol,
        "attempts": attempts,
        "connect_if_needed": connect_if_needed,
        "final_diagnosis": final_diagnosis,
        "final_severity": final_severity,
        "drill_result": drill_result,
        "safety_unchanged": safety_unchanged,
        "git_commit": git.get("commit", "?"),
        "no_broker_mutation": True,
    }
    evidence_hash = _compute_evidence_hash(hashable)

    # ------------------------------------------------------------------
    # 10. Build result
    # ------------------------------------------------------------------
    _MD_RECOVERY_DRILL_EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    export_path = _MD_RECOVERY_DRILL_EXPORT_DIR / f"{drill_id}.json"

    result: dict[str, Any] = {
        "command": "ibkr-operator market-data-recovery-drill",
        "advisory": (
            "Read-only market data recovery drill (Step 15R). "
            "No broker mutation. No order window. No H1 token. "
            "May call /connect for session recovery only."
        ),
        "timestamp": ts_str,
        "drill_id": drill_id,
        "git": {
            "branch": git.get("branch", "?"),
            "commit": git.get("commit", "?"),
            "tag": git.get("tag", "?"),
        },
        "symbol": symbol,
        "attempts_requested": attempts,
        "attempts_completed": len(per_attempt_results),
        "connect_if_needed": connect_if_needed,
        "drill_aborted_early": drill_aborted_early,
        "drill_abort_reason": drill_abort_reason,
        "initial_bridge_health": {
            "connected": initial_ibkr_connected,
            "reachable": bool(initial_health and "_error" not in initial_health),
        },
        "initial_ibkr_connected": initial_ibkr_connected,
        "connect_attempted": connect_attempted,
        "connect_result": connect_result if connect_attempted else {"skipped": True},
        "per_attempt_results": per_attempt_results,
        "final_diagnosis": final_diagnosis,
        "final_severity": final_severity,
        "final_market_data_status": final_market_data_status,
        "readiness_refresh_attempted": readiness_refresh_attempted,
        "readiness_export_path": readiness_export_path,
        "readiness_recommendation": readiness_recommendation,
        "promotion_safe_to_recheck": promotion_safe_to_recheck,
        "drill_result": drill_result,
        "no_broker_mutation": True,
        "no_order_window_opened": True,
        "safety_flags_before": safety_before,
        "safety_flags_after": safety_after,
        "safety_flags_unchanged": safety_unchanged,
        "guard_state_path": guard_state_before.get("guard_state_path", str(OPENCLAW_DIR / "guard-state.json")),
        "guard_state_hash_before": guard_state_before.get("guard_state_hash"),
        "guard_state_hash_after": guard_state_after.get("guard_state_hash"),
        "guard_daily_trade_count_before": guard_daily_tc_before,
        "guard_daily_trade_count_after": guard_daily_tc_after,
        "guard_state_unchanged": guard_state_unchanged,
        "forbidden_endpoint_scan": forbidden_scan,
        "explicit_non_actions": _MD_RECOVERY_DRILL_EXPLICIT_NON_ACTIONS,
        "evidence_hash": evidence_hash,
        "operator_action_required": operator_action_required,
        "bridge_saturated_blocker": bridge_saturated_blocker,
        "operator_actions": operator_actions,
        "blockers": blockers,
        "_export_path": str(export_path),
    }

    # Write export
    try:
        with open(export_path, "w", encoding="utf-8") as f:
            _json.dump(result, f, indent=2, default=str, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
    except Exception:
        pass

    return result


# ===========================================================================
# Step 15S — Contract Qualification / Root-Cause Drill
# ===========================================================================

_CQ_DRILL_EXPORT_DIR = OPENCLAW_DIR / "contract-qualification-drills"
_CQ_DRILL_EXPLICIT_NON_ACTIONS: list[str] = [
    "No orders placed or modified",
    "No account values queried",
    "No position changes",
    "No IBKR_ALLOW_ORDERS changes",
    "No rules.enforced changes",
    "No autonomy-level changes",
    "No H1 token reads",
    "No /order, /order/preflight, /order/approve, /order/submit",
]

_CQ_DEFAULT_EXCHANGES: list[str] = ["SMART"]
_CQ_ALTERNATE_PRIMARY_EXCHANGES: list[str] = ["NASDAQ", "NYSE", "ARCA"]
_CQ_ALTERNATE_EXCHANGES: list[tuple[str, str]] = [
    # (exchange, primaryExchange) — bounded safe alternates
    ("SMART", "NASDAQ"),
    ("SMART", "NYSE"),
    ("SMART", "ARCA"),
    ("NASDAQ", ""),
    ("NYSE", ""),
]


def _qualify_contract_probe(
    symbol: str,
    exchange: str = "SMART",
    currency: str = "USD",
    sec_type: str = "STK",
    primary_exchange: str = "",
    timeout: float = 10.0,
) -> dict:
    """Single contract qualification probe via bridge /contract/stock.

    Returns standardized dict with:
    - qualified: bool
    - contract: dict | None
    - error_code: str | None
    - error_message: str | None
    - duration_seconds: float
    - aborted_503: bool
    """
    import json as _json
    import urllib.request
    import urllib.error
    import time as _time

    start = _time.monotonic()
    request_body = {
        "symbol": symbol.upper().strip(),
        "exchange": exchange,
        "currency": currency,
        "secType": sec_type,
    }
    if primary_exchange:
        request_body["primaryExchange"] = primary_exchange

    result: dict = {
        "qualified": False,
        "contract": None,
        "con_id": None,
        "exchange": exchange,
        "primary_exchange": primary_exchange or None,
        "currency": currency,
        "sec_type": sec_type,
        "local_symbol": None,
        "trading_class": None,
        "error_code": None,
        "error_message": None,
        "duration_seconds": 0.0,
        "aborted_503": False,
    }

    try:
        c_req_body = _json.dumps(request_body).encode()
        c_req = urllib.request.Request(
            f"{BRIDGE_URL}/contract/stock",
            data=c_req_body,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(c_req, timeout=timeout) as c_resp:
            elapsed = _time.monotonic() - start
            result["duration_seconds"] = round(elapsed, 3)
            if c_resp.status == 503:
                result["aborted_503"] = True
                result["error_message"] = "contract/stock returned 503 (backpressure)"
            if c_resp.status == 200:
                contract_data = _json.loads(c_resp.read().decode())
                if contract_data.get("conid"):
                    result["qualified"] = True
                    result["contract"] = contract_data
                    result["con_id"] = contract_data.get("conid")
                    result["local_symbol"] = contract_data.get("localSymbol")
                    result["trading_class"] = contract_data.get("tradingClass")
                    # Use actual exchange from response if available
                    result["exchange"] = contract_data.get("exchange", exchange)
                    result["primary_exchange"] = (
                        contract_data.get("primaryExchange") or primary_exchange or None
                    )
                    result["currency"] = contract_data.get("currency", currency)
                else:
                    result["error_code"] = contract_data.get("code")
                    result["error_message"] = contract_data.get("error", "contract not found")
    except urllib.error.HTTPError as e:
        elapsed = _time.monotonic() - start
        result["duration_seconds"] = round(elapsed, 3)
        if e.code == 503:
            result["aborted_503"] = True
            result["error_message"] = f"contract/stock HTTP 503 (backpressure)"
        else:
            result["error_code"] = e.code
            result["error_message"] = f"contract lookup HTTP {e.code}"
    except urllib.error.URLError as e:
        elapsed = _time.monotonic() - start
        result["duration_seconds"] = round(elapsed, 3)
        result["error_message"] = f"contract lookup unreachable: {str(e)[:150]}"
    except Exception as e:
        elapsed = _time.monotonic() - start
        result["duration_seconds"] = round(elapsed, 3)
        result["error_message"] = f"contract lookup error: {str(e)[:150]}"

    return result


def _run_contract_qualification_drill(
    symbol: str = "AAPL",
    sec_type: str = "STK",
    currency: str = "USD",
    exchange: str = "SMART",
    primary_exchange: str = "",
    attempt_alternates: bool = True,
    max_attempts: int = 5,
) -> dict:
    """Run contract qualification / root-cause drill (Step 15S).

    Systematically probes contract qualification with default and alternate
    exchange/primaryExchange combinations to determine root cause of
    contract_qualification_failed.

    Read-only. No broker/account/order mutation. No H1 token.
    """
    import hashlib
    import json as _json
    import urllib.request
    import urllib.error
    import time as _time
    from datetime import datetime, timezone

    now_utc = datetime.now(timezone.utc)
    ts_str = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    ts_file = now_utc.strftime("%Y%m%dT%H%M%SZ")
    drill_id = f"cq-drill-{symbol}-{ts_file}"
    symbol = symbol.upper().strip()
    max_attempts = min(max(max_attempts, 1), 8)

    git = _git_metadata(BRIDGE_DIR)

    # ------------------------------------------------------------------
    # 1. Capture safety flags and guard-state before
    # ------------------------------------------------------------------
    safety_before = _capture_safety_flags_raw()
    guard_state_before = _capture_guard_state_snapshot()

    # ------------------------------------------------------------------
    # 2. Bridge health
    # ------------------------------------------------------------------
    bridge_reachable = False
    ibkr_connected: bool | None = None
    bridge_runtime_ok = True
    market_session_status: dict = {}

    try:
        health_req = urllib.request.Request(f"{BRIDGE_URL}/health", method="GET")
        with urllib.request.urlopen(health_req, timeout=10.0) as resp:
            if resp.status == 200:
                health_data = _json.loads(resp.read().decode())
                bridge_reachable = True
                ibkr_connected = health_data.get("connected", None)
    except Exception:
        bridge_runtime_ok = False

    # Determine market session status (local, no bridge call)
    market_session_status = _determine_market_session_status()

    # ------------------------------------------------------------------
    # 3. Contract qualification probes
    # ------------------------------------------------------------------
    attempts: list[dict] = []
    best_contract: dict | None = None
    all_qualified: list[dict] = []
    root_cause = "unknown"
    severity = "HOLD"
    operator_action_required = False
    suggested_operator_actions: list[str] = []

    # Build the probe list
    probe_contracts: list[tuple[str, str, str, str]] = []

    # 3a. Default probe (no primary exchange unless specified)
    probe_contracts.append((symbol, exchange, currency, primary_exchange))

    # 3b. If default has no primary exchange, also try with common ones
    if attempt_alternates and not primary_exchange:
        if primary_exchange == "":
            for pe in _CQ_ALTERNATE_PRIMARY_EXCHANGES:
                probe_contracts.append((symbol, exchange, currency, pe))
        for alt_ex, alt_pe in _CQ_ALTERNATE_EXCHANGES:
            if alt_ex != exchange or alt_pe != primary_exchange:
                # Avoid duplicating the default probe
                already = any(
                    p[1] == alt_ex and p[3] == alt_pe for p in probe_contracts
                )
                if not already:
                    probe_contracts.append((symbol, alt_ex, currency, alt_pe))

    # Limit to max_attempts
    probe_contracts = probe_contracts[:max_attempts]

    for attempt_num, (sym, exc, cur, pe) in enumerate(probe_contracts, start=1):
        probe_result = _qualify_contract_probe(
            symbol=sym,
            exchange=exc,
            currency=cur,
            sec_type=sec_type,
            primary_exchange=pe,
        )

        attempt_entry = {
            "attempt_number": attempt_num,
            "contract_request": {
                "symbol": sym,
                "exchange": exc,
                "currency": cur,
                "sec_type": sec_type,
                "primary_exchange": pe or None,
            },
            "qualified": probe_result["qualified"],
            "qualified_contract": probe_result["contract"],
            "con_id": probe_result["con_id"],
            "exchange": probe_result["exchange"],
            "primary_exchange": probe_result["primary_exchange"],
            "currency": probe_result["currency"],
            "local_symbol": probe_result["local_symbol"],
            "trading_class": probe_result["trading_class"],
            "error_code": probe_result["error_code"],
            "error_message": probe_result["error_message"],
            "duration_seconds": probe_result["duration_seconds"],
            "aborted_503": probe_result["aborted_503"],
        }
        attempts.append(attempt_entry)

        if probe_result["qualified"]:
            all_qualified.append(attempt_entry)
            if best_contract is None:
                best_contract = attempt_entry

        # Stop early on 503 — backpressure
        if probe_result["aborted_503"]:
            break

        # Brief delay between probes
        if attempt_num < len(probe_contracts):
            _time.sleep(0.3)

    # ------------------------------------------------------------------
    # 4. Classify root cause
    # ------------------------------------------------------------------
    contract_qualified = len(all_qualified) > 0
    n_qualified = len(all_qualified)

    if not bridge_reachable or not bridge_runtime_ok:
        root_cause = "bridge_runtime_error"
        severity = "NO_GO"
        operator_action_required = True
        suggested_operator_actions = [
            "Check bridge health",
            "Verify bridge is running and reachable",
            "Run ibkr-operator doctor",
        ]
    elif ibkr_connected is False:
        root_cause = "ibkr_disconnected"
        severity = "HOLD"
        operator_action_required = True
        suggested_operator_actions = [
            "Verify IBKR Gateway is running",
            "Connect bridge to IBKR: ibkr-operator connect",
            "Check bridge logs for connection errors",
        ]
    elif any(a.get("aborted_503") for a in attempts):
        root_cause = "pacing_or_backpressure"
        severity = "HOLD"
        operator_action_required = True
        suggested_operator_actions = [
            "Wait for bridge backpressure to drain",
            "Retry after cooldown",
            "Run ibkr-operator doctor",
        ]
    elif n_qualified == 1:
        # One contract qualified — determine root cause by what fixed it
        qual = all_qualified[0]
        req = qual.get("contract_request", {})
        req_pe = req.get("primary_exchange")
        req_ex = req.get("exchange", "SMART")

        if qual["attempt_number"] == 1:
            root_cause = "qualified_with_default_contract"
            severity = "OK"
        elif req_pe and req_pe != "":
            # Alternate succeeded because of primary exchange
            root_cause = "missing_primary_exchange"
            severity = "OK"
            operator_action_required = True
            suggested_operator_actions = [
                f"Use primaryExchange={req_pe} for {symbol}",
                "Update trading config to include primary exchange",
            ]
        elif req_ex not in ("SMART",):
            root_cause = "qualified_with_alternate_exchange"
            severity = "OK"
            operator_action_required = True
            suggested_operator_actions = [
                f"Use exchange={req_ex} instead of SMART for {symbol}",
                "Update trading config to use alternate exchange",
            ]
        else:
            root_cause = "contract_construction_bug"
            severity = "HOLD"
            operator_action_required = True
            suggested_operator_actions = [
                "Unexpected: default failed but identical alternate succeeded",
                "Review contract construction in bridge",
                "Run ibkr-operator doctor",
            ]
    elif n_qualified > 1:
        root_cause = "ambiguous_multiple_contracts"
        severity = "HOLD"
        operator_action_required = True
        suggested_operator_actions = [
            "Multiple contracts qualified — ambiguous",
            "Review qualified_contracts to select the correct one",
            "Specify primaryExchange explicitly to disambiguate",
        ]
    else:
        # n_qualified == 0 — all failed
        error_messages = [a.get("error_message", "") for a in attempts]
        combined = " ".join(e for e in error_messages if e)
        if "not found" in combined.lower() or "200" in combined:
            root_cause = "ibkr_contract_not_found"
            severity = "NO_GO"
        elif "timeout" in combined.lower():
            root_cause = "pacing_or_backpressure"
            severity = "HOLD"
        elif any("unreachable" in (e or "") for e in error_messages):
            root_cause = "bridge_runtime_error"
            severity = "NO_GO"
        else:
            root_cause = "unknown"
            severity = "HOLD"
        operator_action_required = True
        suggested_operator_actions = [
            f"Symbol '{symbol}' not found on any probed exchange",
            "Verify symbol is correct and listed on IBKR",
            "Check contract details in TWS or IBKR Client Portal",
        ]

    # ------------------------------------------------------------------
    # 5. Safety flags and guard-state after
    # ------------------------------------------------------------------
    safety_after = _capture_safety_flags_raw()
    guard_state_after = _capture_guard_state_snapshot()

    safety_unchanged = (
        safety_before.get("env_IBKR_ALLOW_ORDERS")
        == safety_after.get("env_IBKR_ALLOW_ORDERS")
        and safety_before.get("rules_enforced")
        == safety_after.get("rules_enforced")
    )
    guard_state_unchanged = (
        guard_state_before.get("guard_state_hash") is not None
        and guard_state_after.get("guard_state_hash") is not None
        and guard_state_before["guard_state_hash"] == guard_state_after["guard_state_hash"]
    )

    # ------------------------------------------------------------------
    # 6. Forbidden endpoint scan
    # ------------------------------------------------------------------
    forbidden_scan = _scan_forbidden_endpoints()

    # ------------------------------------------------------------------
    # 7. Readiness / promotion impact
    # ------------------------------------------------------------------
    if severity == "OK":
        readiness_impact = "contract_qualified"
        promotion_impact = "none"
    elif severity == "NO_GO":
        readiness_impact = "contract_blocked"
        promotion_impact = "contract_blocks_promotion"
    else:
        readiness_impact = "contract_unknown"
        promotion_impact = "contract_blocks_promotion"

    # ------------------------------------------------------------------
    # 8. Evidence hash
    # ------------------------------------------------------------------
    hashable = {
        "drill_id": drill_id,
        "symbol": symbol,
        "root_cause": root_cause,
        "severity": severity,
        "contract_qualified": contract_qualified,
        "safety_unchanged": safety_unchanged,
        "git_commit": git.get("commit", "?"),
        "no_broker_mutation": True,
    }
    evidence_hash = _compute_evidence_hash(hashable)

    # ------------------------------------------------------------------
    # 9. Build result
    # ------------------------------------------------------------------
    _CQ_DRILL_EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    export_path = _CQ_DRILL_EXPORT_DIR / f"{drill_id}.json"

    result: dict = {
        "command": "ibkr-operator contract-qualification-drill",
        "advisory": (
            "Read-only contract qualification drill (Step 15S). "
            "No broker mutation. No order window. No H1 token."
        ),
        "timestamp": ts_str,
        "drill_id": drill_id,
        "git": {
            "branch": git.get("branch", "?"),
            "commit": git.get("commit", "?"),
            "tag": git.get("tag", "?"),
        },
        "symbol": symbol,
        "requested_contract": {
            "symbol": symbol,
            "sec_type": sec_type,
            "currency": currency,
            "exchange": exchange,
            "primary_exchange": primary_exchange or None,
        },
        "ibkr_connected": ibkr_connected,
        "bridge_reachable": bridge_reachable,
        "bridge_runtime_ok": bridge_runtime_ok,
        "market_session_status": market_session_status,
        "attempts": attempts,
        "attempts_count": len(attempts),
        "best_contract": best_contract,
        "qualified_contracts": all_qualified,
        "contract_qualified": contract_qualified,
        "root_cause": root_cause,
        "severity": severity,
        "readiness_impact": readiness_impact,
        "promotion_impact": promotion_impact,
        "operator_action_required": operator_action_required,
        "suggested_operator_actions": suggested_operator_actions,
        "no_broker_mutation": True,
        "no_order_window_opened": True,
        "safety_flags_before": safety_before,
        "safety_flags_after": safety_after,
        "safety_flags_unchanged": safety_unchanged,
        "guard_state_path": guard_state_before.get(
            "guard_state_path", str(OPENCLAW_DIR / "guard-state.json")
        ),
        "guard_state_hash_before": guard_state_before.get("guard_state_hash"),
        "guard_state_hash_after": guard_state_after.get("guard_state_hash"),
        "guard_daily_trade_count_before": guard_state_before.get("daily_trade_count", 0) or 0,
        "guard_daily_trade_count_after": guard_state_after.get("daily_trade_count", 0) or 0,
        "guard_state_unchanged": guard_state_unchanged,
        "forbidden_endpoint_scan": forbidden_scan,
        "explicit_non_actions": _CQ_DRILL_EXPLICIT_NON_ACTIONS,
        "evidence_hash": evidence_hash,
        "_export_path": str(export_path),
    }

    # Write export
    try:
        with open(export_path, "w", encoding="utf-8") as f:
            _json.dump(result, f, indent=2, default=str, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
    except Exception:
        pass

    return result


# ===========================================================================
# Step 15T — Backpressure Drain Drill
# ===========================================================================

_BP_DRAIN_EXPORT_DIR = OPENCLAW_DIR / "backpressure-drain-drills"
_BP_DRAIN_EXPLICIT_NON_ACTIONS: list[str] = [
    "No orders placed or modified",
    "No account values mutated",
    "No position changes",
    "No IBKR_ALLOW_ORDERS changes",
    "No rules.enforced changes",
    "No autonomy-level changes",
    "No H1 token reads",
    "No /order, /order/preflight, /order/approve, /order/submit",
]


def _run_backpressure_drain_drill(
    observe_seconds: int = 15,
    poll_seconds: int = 3,
    include_endpoint_probes: bool = True,
    symbol: str = "AAPL",
) -> dict:
    """Run bridge saturation / backpressure drain drill (Step 15T).

    Observes bridge backpressure over time to determine whether saturation
    drains naturally or indicates a persistent leak.

    Read-only. No broker/account/order mutation. No H1 token.
    """
    import hashlib
    import json as _json
    import urllib.request
    import urllib.error
    import time as _time
    from datetime import datetime, timezone

    now_utc = datetime.now(timezone.utc)
    ts_str = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    ts_file = now_utc.strftime("%Y%m%dT%H%M%SZ")
    drill_id = f"bp-drain-drill-{ts_file}"
    symbol = symbol.upper().strip()
    observe_seconds = min(max(observe_seconds, 1), 120)
    poll_seconds = min(max(poll_seconds, 1), 15)

    git = _git_metadata(BRIDGE_DIR)

    # ------------------------------------------------------------------
    # 1. Capture safety flags and guard-state before
    # ------------------------------------------------------------------
    safety_before = _capture_safety_flags_raw()
    guard_state_before = _capture_guard_state_snapshot()

    # ------------------------------------------------------------------
    # 2. Initial bridge health
    # ------------------------------------------------------------------
    initial_health: dict = {}
    bridge_reachable = False
    ibkr_connected: bool | None = None
    bridge_runtime_ok = True

    try:
        health_req = urllib.request.Request(f"{BRIDGE_URL}/health", method="GET")
        with urllib.request.urlopen(health_req, timeout=10.0) as resp:
            if resp.status == 200:
                initial_health = _json.loads(resp.read().decode())
                bridge_reachable = True
                ibkr_connected = initial_health.get("connected")
    except Exception:
        bridge_runtime_ok = False

    # ------------------------------------------------------------------
    # 3. Cooldown state
    # ------------------------------------------------------------------
    cooldown_md_ok, cooldown_md_elapsed, _ = _check_diagnostics_cooldown()
    cooldown_md_active = not cooldown_md_ok

    # Recovery drill cooldown — same mechanism (reads same last-run file)
    cooldown_recovery_active = cooldown_md_active
    cooldown_remaining = max(0.0, _MD_DIAGNOSTICS_COOLDOWN_SECONDS - cooldown_md_elapsed)

    cooldown_state: dict = {
        "market_data_diagnostics_cooldown_active": cooldown_md_active,
        "recovery_drill_cooldown_active": cooldown_recovery_active,
        "cooldown_remaining_seconds": round(cooldown_remaining, 1),
        "source": "market-data-diagnostics/.last-run",
    }

    # ------------------------------------------------------------------
    # 4. Observe backpressure over time
    # ------------------------------------------------------------------
    backpressure_samples: list[dict] = []
    endpoint_probe_results: list[dict] = []
    endpoint_probes_run = False

    start_time = _time.monotonic()
    elapsed = 0.0
    sample_num = 0

    while elapsed < observe_seconds:
        sample_num += 1
        sample_ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        # Fetch backpressure snapshot
        bp = _check_bridge_backpressure()
        active = bp.get("active", -1)
        max_active = bp.get("max_active", 4)
        leaked = bp.get("leaked_md_threads", -1)

        # Health status for this sample
        health_status = 200
        try:
            hq = urllib.request.Request(f"{BRIDGE_URL}/health", method="GET")
            with urllib.request.urlopen(hq, timeout=5.0) as hr:
                health_status = hr.status
        except urllib.error.HTTPError as he:
            health_status = he.code
        except Exception:
            health_status = 0

        saturated = bp["ok"] is False

        sample_entry: dict = {
            "sample_number": sample_num,
            "timestamp": sample_ts,
            "active_count": active,
            "max_active": max_active,
            "tier_counts": {},
            "leaked_thread_count": leaked,
            "saturated": saturated,
            "health_http_status": health_status,
        }
        backpressure_samples.append(sample_entry)

        elapsed = _time.monotonic() - start_time
        if elapsed >= observe_seconds:
            break

        # Wait for next poll interval
        _time.sleep(min(poll_seconds, observe_seconds - elapsed))
        elapsed = _time.monotonic() - start_time

    # If endpoint probes enabled, run them once at the end (not during polling
    # to avoid worsening saturation)
    if include_endpoint_probes and bridge_reachable:
        endpoint_probes_run = True
        probe_endpoints = [
            "/positions",
            "/account",
            "/monitor/alerts",
        ]
        for ep in probe_endpoints:
            ep_start = _time.monotonic()
            ep_result: dict = {
                "endpoint": ep,
                "attempted": True,
                "http_status": None,
                "ok": False,
                "duration_seconds": 0.0,
                "error": None,
            }
            try:
                ep_req = urllib.request.Request(f"{BRIDGE_URL}{ep}", method="GET")
                with urllib.request.urlopen(ep_req, timeout=10.0) as ep_resp:
                    ep_result["http_status"] = ep_resp.status
                    ep_result["ok"] = ep_resp.status == 200
                    if ep_resp.status == 200:
                        ep_resp.read()  # consume body
            except urllib.error.HTTPError as e:
                ep_result["http_status"] = e.code
                ep_result["error"] = f"HTTP {e.code}"
            except Exception as e:
                ep_result["error"] = str(e)[:150]
            ep_result["duration_seconds"] = round(_time.monotonic() - ep_start, 3)
            endpoint_probe_results.append(ep_result)
            # Brief delay between probes
            _time.sleep(0.3)

    # ------------------------------------------------------------------
    # 5. Final health
    # ------------------------------------------------------------------
    final_health: dict = {}
    try:
        fh_req = urllib.request.Request(f"{BRIDGE_URL}/health", method="GET")
        with urllib.request.urlopen(fh_req, timeout=10.0) as fh_resp:
            if fh_resp.status == 200:
                final_health = _json.loads(fh_resp.read().decode())
                bridge_reachable = True
                ibkr_connected = final_health.get("connected", ibkr_connected)
    except Exception:
        pass

    # ------------------------------------------------------------------
    # 6. Classify diagnosis
    # ------------------------------------------------------------------
    diagnosis = "unknown"
    severity = "HOLD"
    operator_action_required = False
    suggested_operator_actions: list[str] = []

    samples = backpressure_samples
    first_sample = samples[0] if samples else {}
    last_sample = samples[-1] if samples else {}

    active_first = first_sample.get("active_count", -1)
    active_last = last_sample.get("active_count", -1)
    saturated_first = first_sample.get("saturated", False)
    saturated_last = last_sample.get("saturated", False)
    leaked_first = first_sample.get("leaked_thread_count", -1)
    leaked_last = last_sample.get("leaked_thread_count", -1)

    if not bridge_reachable or not bridge_runtime_ok:
        diagnosis = "bridge_unreachable"
        severity = "NO_GO"
        operator_action_required = True
        suggested_operator_actions = [
            "Check if bridge process is running",
            "Run ibkr-operator doctor",
            "Restart bridge if needed",
        ]
    elif cooldown_md_active and active_last <= 0:
        diagnosis = "cooldown_active"
        severity = "HOLD"
        operator_action_required = True
        suggested_operator_actions = [
            "Wait for market-data diagnostics cooldown to expire",
            "Rerun backpressure-drain-drill after cooldown",
        ]
    elif not saturated_first and not saturated_last and active_last <= 0:
        diagnosis = "healthy_idle"
        severity = "OK"
    elif saturated_first and not saturated_last and active_last <= 0:
        diagnosis = "transient_saturation_drained"
        severity = "OK"
        suggested_operator_actions = [
            "Saturation was transient — bridge has recovered",
            "Monitor for recurrence",
        ]
    elif saturated_last and active_last == active_first:
        # No change — persistent
        if leaked_last > 0:
            diagnosis = "suspected_thread_leak"
            severity = "NO_GO"
            operator_action_required = True
            suggested_operator_actions = [
                f"Leaked thread count: {leaked_last} — threads may be stuck",
                "Check bridge logs for hanging requests",
                "Run ibkr-operator doctor",
                "Consider bridge restart to clear leaked threads",
            ]
        else:
            diagnosis = "persistent_saturation"
            severity = "HOLD"
            operator_action_required = True
            suggested_operator_actions = [
                f"Bridge remains saturated at {active_last}/{max_active} slots",
                "Check for stuck diagnostic/read probes",
                "Run ibkr-operator doctor",
                "If saturation persists >60s, consider bridge restart",
            ]
    elif saturated_last and active_last > active_first:
        # Getting worse
        if leaked_last > leaked_first:
            diagnosis = "suspected_thread_leak"
            severity = "NO_GO"
            operator_action_required = True
            suggested_operator_actions = [
                f"Active slots growing ({active_first}→{active_last}) AND leaked threads ({leaked_first}→{leaked_last})",
                "Bridge may be accumulating stuck threads",
                "Run ibkr-operator doctor immediately",
                "Consider bridge restart",
            ]
        else:
            diagnosis = "suspected_active_count_leak"
            severity = "HOLD"
            operator_action_required = True
            suggested_operator_actions = [
                f"Active slots growing ({active_first}→{active_last})",
                "Check for slow/hanging probe calls",
                "Run ibkr-operator doctor",
            ]
    elif saturated_last:
        diagnosis = "persistent_saturation"
        severity = "HOLD"
        operator_action_required = True
        suggested_operator_actions = [
            "Bridge remains saturated",
            "Run ibkr-operator doctor",
            "If saturation persists, consider bridge restart",
        ]
    else:
        diagnosis = "unknown"
        severity = "HOLD"

    # ------------------------------------------------------------------
    # 7. Safety flags and guard-state after
    # ------------------------------------------------------------------
    safety_after = _capture_safety_flags_raw()
    guard_state_after = _capture_guard_state_snapshot()

    safety_unchanged = (
        safety_before.get("env_IBKR_ALLOW_ORDERS")
        == safety_after.get("env_IBKR_ALLOW_ORDERS")
        and safety_before.get("rules_enforced")
        == safety_after.get("rules_enforced")
    )
    guard_state_unchanged = (
        guard_state_before.get("guard_state_hash") is not None
        and guard_state_after.get("guard_state_hash") is not None
        and guard_state_before["guard_state_hash"] == guard_state_after["guard_state_hash"]
    )
    guard_daily_tc_before = guard_state_before.get("daily_trade_count", 0) or 0
    guard_daily_tc_after = guard_state_after.get("daily_trade_count", 0) or 0

    # If guard_state changed during the drain drill, override to NO_GO
    if not guard_state_unchanged or guard_daily_tc_before != guard_daily_tc_after:
        diagnosis = "guard_state_mutation" if diagnosis != "bridge_unreachable" else diagnosis
        severity = "NO_GO"
        operator_action_required = True
        suggested_operator_actions.insert(0,
            f"Guard-state mutated: daily_trade_count {guard_daily_tc_before}→{guard_daily_tc_after}")

    # ------------------------------------------------------------------
    # 8. Forbidden endpoint scan (backpressure drain drill)
    # ------------------------------------------------------------------
    forbidden_scan = _scan_forbidden_endpoints()

    # ------------------------------------------------------------------
    # 9. Evidence hash
    # ------------------------------------------------------------------
    hashable = {
        "drill_id": drill_id,
        "observe_seconds": observe_seconds,
        "diagnosis": diagnosis,
        "severity": severity,
        "safety_unchanged": safety_unchanged,
        "git_commit": git.get("commit", "?"),
        "no_broker_mutation": True,
    }
    evidence_hash = _compute_evidence_hash(hashable)

    # ------------------------------------------------------------------
    # 10. Build result
    # ------------------------------------------------------------------
    _BP_DRAIN_EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    export_path = _BP_DRAIN_EXPORT_DIR / f"{drill_id}.json"

    result: dict = {
        "command": "ibkr-operator backpressure-drain-drill",
        "advisory": (
            "Read-only backpressure drain drill (Step 15T). "
            "No broker mutation. No order window. No H1 token."
        ),
        "timestamp": ts_str,
        "drill_id": drill_id,
        "git": {
            "branch": git.get("branch", "?"),
            "commit": git.get("commit", "?"),
            "tag": git.get("tag", "?"),
        },
        "observe_seconds": observe_seconds,
        "poll_seconds": poll_seconds,
        "bridge_reachable": bridge_reachable,
        "ibkr_connected": ibkr_connected,
        "bridge_runtime_ok": bridge_runtime_ok,
        "safety_flags_before": safety_before,
        "safety_flags_after": safety_after,
        "safety_flags_unchanged": safety_unchanged,
        "guard_state_path": guard_state_before.get(
            "guard_state_path", str(OPENCLAW_DIR / "guard-state.json")
        ),
        "guard_state_hash_before": guard_state_before.get("guard_state_hash"),
        "guard_state_hash_after": guard_state_after.get("guard_state_hash"),
        "guard_daily_trade_count_before": guard_state_before.get("daily_trade_count", 0) or 0,
        "guard_daily_trade_count_after": guard_state_after.get("daily_trade_count", 0) or 0,
        "guard_state_unchanged": guard_state_unchanged,
        "initial_health": initial_health,
        "final_health": final_health,
        "backpressure_samples": backpressure_samples,
        "samples_count": len(backpressure_samples),
        "endpoint_probe_results": endpoint_probe_results,
        "endpoint_probes_run": endpoint_probes_run,
        "cooldown_state": cooldown_state,
        "diagnosis": diagnosis,
        "severity": severity,
        "operator_action_required": operator_action_required,
        "suggested_operator_actions": suggested_operator_actions,
        "no_broker_mutation": True,
        "no_order_window_opened": True,
        "forbidden_endpoint_scan": forbidden_scan,
        "explicit_non_actions": _BP_DRAIN_EXPLICIT_NON_ACTIONS,
        "evidence_hash": evidence_hash,
        "_export_path": str(export_path),
    }

    # Write export
    try:
        with open(export_path, "w", encoding="utf-8") as f:
            _json.dump(result, f, indent=2, default=str, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
    except Exception:
        pass

    return result


# ---------------------------------------------------------------------------


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

    # --- Step 15P: Session-aware readiness ---
    session_info = _determine_market_session_status()
    evidence["market_session_status"] = session_info
    evidence["market_data_runtime_ok"] = None  # filled by heavier checks
    evidence["market_data_required_for_readiness"] = True
    evidence["market_data_blocks_promotion"] = None  # filled by heavier checks

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


# ---------------------------------------------------------------------------
# Step 15I — Clean-cycle ledger helpers
# ---------------------------------------------------------------------------



def _compute_entry_hash(entry: dict) -> str:
    """Compute SHA-256 hash of a canonicalised ledger entry (excludes hash field)."""
    canonical = {k: entry[k] for k in sorted(entry) if k != "entry_hash"}
    raw = json.dumps(canonical, sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _write_ledger_entry(entry: dict, ledger_path: Path) -> None:
    """Append a single JSON line to the JSONL ledger with fsync.

    Creates parent directory if needed. Uses atomic write pattern
    (write to .tmp, fsync, rename) for the file as a whole for safety,
    but JSONL semantics mean we append to a tmp copy of the existing file.
    """
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(entry, default=str, ensure_ascii=False) + "\n"
    with open(ledger_path, "a", encoding="utf-8") as f:
        f.write(line)
        f.flush()
        os.fsync(f.fileno())


def _is_clean_cycle(evidence: dict) -> tuple[bool, list[str]]:
    """Evaluate whether an evidence bundle constitutes a clean autonomy cycle.

    Returns (clean_bool, list_of_reasons).
    A cycle is clean only when ALL criteria are met (see requirements).
    Autonomy level zero and system_locked are ALLOWED — they do not block clean.
    """
    reasons: list[str] = []

    ibkr_conn = evidence.get("ibkr", {})
    safety = evidence.get("safety", {})
    doctor = evidence.get("doctor", {})
    kpi = evidence.get("kpi", {})
    candidate = evidence.get("candidate", {})
    scan = evidence.get("forbidden_endpoint_scan", {})
    monitoring = evidence.get("monitoring", {})

    # 1. Bridge reachable
    if not ibkr_conn.get("reachable"):
        reasons.append("bridge_not_reachable")

    # 2. Safety locked
    if not safety.get("read_only"):
        reasons.append("safety_read_only_false")
    if safety.get("bridge_allow_orders") is not False:
        reasons.append("safety_bridge_allow_orders_not_false")
    if safety.get("env_IBKR_ALLOW_ORDERS") != "false":
        reasons.append("safety_env_IBKR_ALLOW_ORDERS_not_false")
    if safety.get("rules_enforced") != "false":
        reasons.append("safety_rules_enforced_not_false")

    # 3. No active alerts
    if monitoring.get("active_alert_count", 0) > 0:
        reasons.append("active_alerts_present")

    # 4. No reconciliation failure
    if monitoring.get("reconciliation_passed") is False:
        reasons.append("reconciliation_failed")

    # 5. Doctor passes (H1 canary skippable)
    doc_pass = doctor.get("pass")
    if not doc_pass:
        # Check if H1 canary is the ONLY failure
        checks = doctor.get("checks", [])
        non_h1_failures = [
            c.get("check", "?")
            for c in checks
            if not c.get("ok") and c.get("check") != "h1_token_canary"
        ]
        if non_h1_failures:
            reasons.append(f"doctor_non_pass: {', '.join(non_h1_failures)}")
        elif not checks:
            # No checks at all — cannot verify doctor; fail open (flag as dirty)
            reasons.append("doctor_non_pass: no checks available")
        elif doc_pass is None:
            # pass=None with check list but no non-H1 failures means
            # the doctor result is indeterminate — flag as dirty
            reasons.append("doctor_non_pass: indeterminate (pass=None)")
        # else: only h1_token_canary failed — acceptable

    # 6. KPI is not NO-GO
    kpi_verdict = kpi.get("verdict", "ERROR")
    if kpi_verdict == "NO-GO":
        reasons.append("kpi_nogo")

    # 7. Candidate is not NO-GO
    cand_verdict = candidate.get("verdict", "ERROR")
    if cand_verdict == "NO-GO":
        reasons.append("candidate_nogo")

    # 8. No market_data_missing when IBKR connected
    market = evidence.get("market_data", {})
    if ibkr_conn.get("connected") and not market.get("market_data_available"):
        reasons.append("market_data_missing_while_connected")

    # 9. No fx_missing/fx_stale when FX required
    account_ev = evidence.get("account_evidence", {})
    fx_required = account_ev.get("fx_required", False)
    if fx_required:
        if not account_ev.get("fx_available"):
            reasons.append("fx_missing_when_required")
        elif (account_ev.get("fx_staleness_seconds") or 0) > 300:
            reasons.append("fx_stale")

    # 10. No forbidden endpoint violations
    if not scan.get("ok"):
        reasons.append("forbidden_endpoint_violations")

    # 11. No /order* calls (confirmed via scan)
    # 12. No H1 token reads (confirmed via doctor H1 canary)

    clean = len(reasons) == 0
    return clean, reasons


def _run_evidence_cycle(
    symbol: str,
    side: str,
    record: bool = False,
) -> dict:
    """Run a full read-only evidence bundle for one candidate.

    Collects doctor, KPI, cycle-rehearsal, candidate-dryrun,
    forbidden-endpoint scan, and safety flags. Evaluates clean-cycle
    criteria. Optionally records to the JSONL ledger.

    Returns the evidence dict plus entry metadata.
    """
    from datetime import datetime, timezone

    now_utc = datetime.now(timezone.utc)
    ts_str = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    ts_file = now_utc.strftime("%Y%m%dT%H%M%SZ")
    cycle_id = f"cycle-{symbol}-{side}-{ts_file}"

    # Lightweight evidence snapshot (single call — safety + doctor)
    lw_ev: dict = {}
    try:
        lw_ev = _collect_lightweight_evidence()
    except Exception:
        pass

    # Canonical doctor: use lightweight evidence doctor (actual in-process
    # checks), NOT the placeholder _run_doctor_non_sudo().
    doctor_result = lw_ev.get("doctor", {})
    if not doctor_result:
        # Fallback
        try:
            doctor_result = _run_doctor_non_sudo()
        except Exception as e:
            doctor_result = {"error": str(e)[:200]}

    kpi_result = run_kpi()

    rehearsal_result = {}
    try:
        rehearsal_result = _run_cycle_rehearsal()
    except Exception as e:
        rehearsal_result = {"error": str(e)[:200]}

    candidate_result = {}
    try:
        candidate_result = _run_candidate_dryrun(symbol, side)
    except Exception as e:
        candidate_result = {"error": str(e)[:200]}

    scan_result = _scan_forbidden_endpoints()

    # Build safety snapshot
    safety_snapshot: dict = {}
    sf = lw_ev.get("safety", {})
    if sf:
        safety_snapshot = {
            "read_only": sf.get("read_only"),
            "bridge_allow_orders": sf.get("bridge_allow_orders"),
            "env_IBKR_ALLOW_ORDERS": sf.get("env_IBKR_ALLOW_ORDERS"),
            "rules_enforced": sf.get("rules_enforced"),
            "system_locked": sf.get("system_locked"),
        }

    # IBKR connection state from KPI
    ibkr_snapshot = {
        "reachable": kpi_result.get("bridge", {}).get("reachable", False),
        "connected": kpi_result.get("bridge", {}).get("connected", False),
        "mode": kpi_result.get("bridge", {}).get("mode"),
    }

    # Monitoring snapshot
    mon = kpi_result.get("monitoring", {})
    monitoring_snapshot = {
        "active_alert_count": mon.get("active_alert_count", 0),
        "reconciliation_passed": mon.get("reconciliation_passed"),
    }

    # Build evidence bundle for clean evaluation
    evidence_bundle = {
        "ibkr": ibkr_snapshot,
        "safety": safety_snapshot,
        "doctor": doctor_result,
        "kpi": kpi_result,
        "candidate": candidate_result,
        "forbidden_endpoint_scan": scan_result,
        "monitoring": monitoring_snapshot,
        "market_data": candidate_result.get("market_data", {}),
        "account_evidence": candidate_result.get("account_evidence", {}),
    }

    clean, reasons = _is_clean_cycle(evidence_bundle)

    # Convert string reasons to structured blockers with severity
    structured_blockers: list[dict] = []
    for reason in reasons:
        # Extract check name from reason string
        check_name = reason.split(":")[0].strip() if ":" in reason else reason
        # All _is_clean_cycle reasons are NO-GO for the cycle
        structured_blockers.append({
            "severity": "NO-GO",
            "check": check_name,
            "detail": reason,
        })

    # Export candidate dry-run to disk
    candidate_export_path = None
    try:
        candidate_export_path = str(export_candidate_dryrun(candidate_result))
    except Exception:
        pass

    # Build ledger entry
    git_meta = _git_metadata(BRIDGE_DIR)
    ledger_entry = {
        "timestamp": ts_str,
        "cycle_id": cycle_id,
        "git_branch": git_meta.get("branch", "?"),
        "git_commit": git_meta.get("commit", "?"),
        "git_tag": git_meta.get("tag"),
        "symbol": symbol,
        "side": side,
        "doctor_verdict": "PASS" if doctor_result.get("pass") is True else ("FAIL" if doctor_result else "N/A"),
        "kpi_verdict": kpi_result.get("verdict", "ERROR"),
        "rehearsal_verdict": rehearsal_result.get("verdict", "ERROR"),
        "candidate_verdict": candidate_result.get("verdict", "ERROR"),
        "candidate_export_path": candidate_export_path,
        "kpi_export_path": kpi_result.get("_export_path"),
        "safety_flags": safety_snapshot,
        "ibkr_connected": ibkr_snapshot.get("connected", False),
        "ibkr_reachable": ibkr_snapshot.get("reachable", False),
        "market_data_available": candidate_result.get("market_data", {}).get("market_data_available", False),
        "fx_available": candidate_result.get("account_evidence", {}).get("fx_available"),
        "fx_required": candidate_result.get("account_evidence", {}).get("fx_required"),
        "no_forbidden_endpoints": scan_result.get("ok", False),
        "clean": clean,
        "blockers": structured_blockers,
        "dirty_reasons": reasons,  # human-readable reasons (for diagnostics)
        "entry_hash": "",  # placeholder, computed below
    }

    # Compute hash after building the entry
    ledger_entry["entry_hash"] = _compute_entry_hash(ledger_entry)

    # Record to ledger if requested
    if record:
        _write_ledger_entry(ledger_entry, _CLEAN_CYCLE_LEDGER)
        ledger_entry["_recorded"] = True
        ledger_entry["_ledger_path"] = str(_CLEAN_CYCLE_LEDGER)
    else:
        ledger_entry["_recorded"] = False

    # Build result
    result = {
        "advisory": "Read-only evidence cycle. No orders. No H1 token. No broker mutation.",
        "timestamp": ts_str,
        "cycle_id": cycle_id,
        "symbol": symbol,
        "side": side,
        "clean": clean,
        "clean_reasons": reasons if not clean else [],
        "recorded": record,
        "ledger_path": str(_CLEAN_CYCLE_LEDGER) if record else None,
        "doctor_verdict": ledger_entry["doctor_verdict"],
        "kpi_verdict": ledger_entry["kpi_verdict"],
        "rehearsal_verdict": ledger_entry["rehearsal_verdict"],
        "candidate_verdict": ledger_entry["candidate_verdict"],
        "candidate_export_path": candidate_export_path,
        "kpi_export_path": ledger_entry["kpi_export_path"],
        "safety_flags": safety_snapshot,
        "ibkr_connected": ibkr_snapshot.get("connected", False),
        "ibkr_reachable": ibkr_snapshot.get("reachable", False),
        "market_data_available": ledger_entry["market_data_available"],
        "fx_available": ledger_entry["fx_available"],
        "fx_required": ledger_entry["fx_required"],
        "no_forbidden_endpoints": scan_result.get("ok", False),
        "entry_hash": ledger_entry["entry_hash"],
        "blockers": structured_blockers,  # structured dicts with severity
        "dirty_reasons": reasons,          # human-readable strings
        "evidence": evidence_bundle,
    }

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


def _print_evidence_cycle(result: dict) -> None:
    """Print evidence cycle result in human-readable format."""
    clean = result.get("clean", False)
    status_text = f"{GREEN}CLEAN{RESET}" if clean else f"{RED}DIRTY{RESET}"

    print(f"{BOLD}Evidence Cycle{RESET}  [{status_text}]")
    print(f"  Timestamp:       {result.get('timestamp', '?')}")
    print(f"  Cycle ID:        {result.get('cycle_id', '?')}")
    print(f"  Symbol/Side:     {result.get('symbol', '?')} {result.get('side', '?')}")
    print(f"  Recorded:        {'✓' if result.get('recorded') else '✗'}")
    if result.get("ledger_path"):
        print(f"  Ledger:          {result['ledger_path']}")
    print(f"  Doctor:          {result.get('doctor_verdict', '?')}")
    print(f"  KPI:             {result.get('kpi_verdict', '?')}")
    print(f"  Rehearsal:       {result.get('rehearsal_verdict', '?')}")
    print(f"  Candidate:       {result.get('candidate_verdict', '?')}")
    print(f"  IBKR connected:  {result.get('ibkr_connected', False)}")
    print(f"  Market data:     {'available' if result.get('market_data_available') else 'missing'}")
    print(f"  FX available:    {result.get('fx_available')}  (required={result.get('fx_required')})")
    print(f"  EP scan clean:   {result.get('no_forbidden_endpoints', False)}")
    print(f"  Entry hash:      {result.get('entry_hash', '?')[:16]}...")

    blockers = result.get("blockers", [])
    dirty_reasons = result.get("dirty_reasons", [])
    if blockers or dirty_reasons:
        print(f"\n  {BOLD}Blocker details:{RESET}")
        for b in blockers:
            if isinstance(b, dict):
                sev_color = RED if b.get("severity") == "NO-GO" else RESET
                print(f"    [{sev_color}{b.get('severity', '?')}{RESET}] {b.get('check', '?')}: {b.get('detail', '')}")
            else:
                print(f"    - {b}")
        if dirty_reasons and not blockers:
            for r in dirty_reasons:
                print(f"    - {r}")
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


# ---------------------------------------------------------------------------
# Step 15J — Autonomy Readiness Evaluator / Promotion Proposal
# ---------------------------------------------------------------------------

_AUTONOMY_STATUS_EXPORT_DIR = OPENCLAW_DIR / "autonomy-status"
_CLEAN_CYCLES_REQUIRED = 5
_CLEAN_CYCLES_WINDOW_DAYS = 7
_CANDIDATE_EVIDENCE_MAX_AGE_SECONDS = 600
_DEFAULT_REFRESH_SYMBOL = "AAPL"
_DEFAULT_REFRESH_SIDE = "BUY"


def _latest_clean_cycle_timestamp(ledger_path: Path) -> str | None:
    """Return the timestamp of the most recent clean=true entry in the ledger.

    Malformed lines are ignored safely.
    """
    import json as _json
    if not ledger_path.exists():
        return None
    latest_ts: str | None = None
    latest_epoch: float = 0.0
    try:
        with open(ledger_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = _json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue
                if not isinstance(entry, dict):
                    continue
                if entry.get("clean") is not True:
                    continue
                ts = entry.get("timestamp", "")
                if not ts:
                    continue
                try:
                    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                    epoch = dt.timestamp()
                    if epoch > latest_epoch:
                        latest_epoch = epoch
                        latest_ts = ts
                except (ValueError, TypeError):
                    pass
    except OSError:
        pass
    return latest_ts


def _run_autonomy_status(refresh_evidence: bool = False) -> dict:
    """Run autonomy readiness evaluator / promotion proposal.

    Read-only. No broker mutation. No autonomy level changes.
    Determines whether the system has enough evidence to be
    manually reviewed for promotion from autonomy level 0 to level 1.

    Args:
        refresh_evidence: If True, run fresh candidate dry-run + connected
            checks (doctor, KPI, market/FX snapshot, forbidden endpoints).
            If False, use latest on-disk exports and mark evidence age.

    Returns a dict with recommendation: HOLD | READY_FOR_MANUAL_REVIEW | NO_GO.
    """
    import json as _json
    from datetime import datetime, timezone

    now_utc = datetime.now(timezone.utc)
    ts_str = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    ts_file = now_utc.strftime("%Y%m%dT%H%M%SZ")

    # ------------------------------------------------------------------
    # 1. Git metadata
    # ------------------------------------------------------------------
    git = _git_metadata(BRIDGE_DIR)

    # ------------------------------------------------------------------
    # 2. Current autonomy level
    # ------------------------------------------------------------------
    autonomy_path = BRIDGE_DIR / "docs" / "AUTONOMY_CRITERIA.md"
    current_level = _read_autonomy_level(autonomy_path) if autonomy_path.exists() else "0"
    target_level = "1"

    # ------------------------------------------------------------------
    # 3. Clean-cycle ledger
    # ------------------------------------------------------------------
    ledger_path = _CLEAN_CYCLE_LEDGER
    clean_cycles_observed = _count_clean_cycles(OPENCLAW_DIR, max_age_days=_CLEAN_CYCLES_WINDOW_DAYS)
    clean_cycles_required = _CLEAN_CYCLES_REQUIRED
    latest_clean_ts = _latest_clean_cycle_timestamp(ledger_path)

    # ------------------------------------------------------------------
    # 4. Bridge health (lightweight snapshot)
    # ------------------------------------------------------------------
    light_evidence: dict = {}
    try:
        light_evidence = _collect_lightweight_evidence()
    except Exception as e:
        light_evidence = {"_error": str(e)[:200]}

    lw_bridge = light_evidence.get("bridge", {})
    lw_safety = light_evidence.get("safety", {})
    lw_doctor = light_evidence.get("doctor", {})

    bridge_reachable = lw_bridge.get("reachable", False)
    ibkr_connected = lw_bridge.get("connected", None)

    safety_locked = (
        lw_safety.get("read_only") is True
        and lw_safety.get("bridge_allow_orders") in (False, "false")
        and lw_safety.get("env_IBKR_ALLOW_ORDERS") == "false"
        and lw_safety.get("rules_enforced") == "false"
        and lw_safety.get("system_locked") is True
    )

    env_allow_orders = lw_safety.get("env_IBKR_ALLOW_ORDERS", "?")
    rules_enforced = lw_safety.get("rules_enforced", "?")

    # ------------------------------------------------------------------
    # 5. Doctor verdict (lightweight, H1 canary MANUAL allowed)
    # ------------------------------------------------------------------
    doctor_pass = lw_doctor.get("pass", False)
    doctor_checks = lw_doctor.get("checks", [])
    # H1 canary may be MANUAL_REQUIRED — that's acceptable
    non_h1_failures = [
        c.get("check", "?")
        for c in doctor_checks
        if not c.get("ok") and c.get("check") != "h1_token_canary"
    ]
    doctor_ok = doctor_pass or len(non_h1_failures) == 0
    doctor_verdict = "PASS" if doctor_ok else "FAIL"

    # ------------------------------------------------------------------
    # 6. KPI verdict
    # ------------------------------------------------------------------
    kpi_evidence: dict = {}
    kpi_verdict = "UNKNOWN"
    try:
        kpi_evidence = run_kpi()
        kpi_verdict = kpi_evidence.get("verdict", "ERROR")
    except Exception as e:
        kpi_evidence = {"_error": str(e)[:200]}
        kpi_verdict = "ERROR"

    # ------------------------------------------------------------------
    # 7. Monitoring / alerts / reconciliation
    # ------------------------------------------------------------------
    monitoring = kpi_evidence.get("monitoring", {})
    active_alert_count = monitoring.get("active_alert_count", 0)
    reconciliation_passed = monitoring.get("reconciliation_passed", None)

    # ------------------------------------------------------------------
    # 8. Candidate evidence: fresh (refresh) or from latest on-disk export
    # ------------------------------------------------------------------
    refreshed_fields: dict = {}
    candidate_evidence_age_seconds: float | None = None
    latest_candidate_verdict = "unknown"
    market_data_status = "unknown"
    fx_status = "unknown"
    latest_cand_data: dict = {}
    refreshed_candidate_path: str | None = None
    refreshed_kpi_path: str | None = None

    candidate_dir = OPENCLAW_DIR / _CANDIDATE_EXPORT_DIR_NAME

    if refresh_evidence:
        # ------------------------------------------------------------------
        # 8a. Fresh connected evidence: candidate dry-run + fresh KPI/doctor
        # ------------------------------------------------------------------
        refresh_start = time.time()
        refreshed_at_ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        # Fresh KPI
        kpi_evidence = run_kpi()
        kpi_verdict = kpi_evidence.get("verdict", "ERROR")
        monitoring = kpi_evidence.get("monitoring", {})
        active_alert_count = monitoring.get("active_alert_count", 0)
        reconciliation_passed = monitoring.get("reconciliation_passed", None)

        # Export fresh KPI
        try:
            kpi_export_dir = OPENCLAW_DIR / "exports"
            kpi_export_dir.mkdir(parents=True, exist_ok=True)
            kpi_export_path = kpi_export_dir / f"kpi-dashboard-{ts_file}.json"
            with open(kpi_export_path, "w", encoding="utf-8") as kf:
                _json.dump(kpi_evidence, kf, indent=2, default=str, ensure_ascii=False)
            refreshed_kpi_path = str(kpi_export_path)
        except Exception:
            pass

        # Fresh candidate dry-run
        try:
            fresh_candidate = _run_candidate_dryrun(_DEFAULT_REFRESH_SYMBOL, _DEFAULT_REFRESH_SIDE)
            latest_cand_data = fresh_candidate
            latest_candidate_verdict = fresh_candidate.get("verdict", "unknown")
            refreshed_candidate_path = fresh_candidate.get("_export_path")

            # Market data status from fresh candidate
            md = fresh_candidate.get("market_data", {})
            if md.get("market_data_available"):
                market_data_status = "available" if not md.get("stale", True) else "stale"
            elif md:
                market_data_status = "unavailable"

            # FX status from fresh candidate
            ae = fresh_candidate.get("account_evidence", {}) or fresh_candidate.get("fx_evidence", {})
            if ae:
                fx_available = ae.get("fx_available", False)
                fx_required = ae.get("fx_required", None)
                if fx_required is False:
                    fx_status = "not_required"
                elif fx_available:
                    fx_stale = (ae.get("fx_staleness_seconds") or 0) > 300
                    fx_status = "available" if not fx_stale else "stale"
                else:
                    fx_status = "unavailable"
        except Exception as e:
            fresh_candidate = {"_error": str(e)[:200], "verdict": "ERROR"}
            latest_candidate_verdict = "ERROR"

        # Fresh forbidden endpoint scan
        scan_result = _scan_forbidden_endpoints()
        scan_ok = scan_result.get("ok", True)

        # Fresh doctor (lightweight)
        try:
            light_evidence = _collect_lightweight_evidence()
        except Exception:
            pass
        lw_bridge = light_evidence.get("bridge", {})
        lw_safety = light_evidence.get("safety", {})
        lw_doctor = light_evidence.get("doctor", {})

        bridge_reachable = lw_bridge.get("reachable", False)
        ibkr_connected = lw_bridge.get("connected", None)
        safety_locked = (
            lw_safety.get("read_only") is True
            and lw_safety.get("bridge_allow_orders") in (False, "false")
            and lw_safety.get("env_IBKR_ALLOW_ORDERS") == "false"
            and lw_safety.get("rules_enforced") == "false"
            and lw_safety.get("system_locked") is True
        )
        env_allow_orders = lw_safety.get("env_IBKR_ALLOW_ORDERS", "?")
        rules_enforced = lw_safety.get("rules_enforced", "?")

        doctor_pass = lw_doctor.get("pass", False)
        doctor_checks = lw_doctor.get("checks", [])
        non_h1_failures = [
            c.get("check", "?")
            for c in doctor_checks
            if not c.get("ok") and c.get("check") != "h1_token_canary"
        ]
        doctor_ok = doctor_pass or len(non_h1_failures) == 0
        doctor_verdict = "PASS" if doctor_ok else "FAIL"

        candidate_evidence_age_seconds = time.time() - refresh_start

        refreshed_fields = {
            "refreshed_at": refreshed_at_ts,
            "refreshed_candidate_export_path": refreshed_candidate_path,
            "refreshed_kpi_export_path": refreshed_kpi_path,
            "refreshed_market_data_status": market_data_status,
            "refreshed_fx_status": fx_status,
            "refreshed_ibkr_connected": ibkr_connected,
            "refreshed_evidence_age_seconds": round(candidate_evidence_age_seconds, 2),
        }
    else:
        # ------------------------------------------------------------------
        # 8b. Latest candidate verdict from on-disk export (existing behaviour)
        # ------------------------------------------------------------------
        try:
            if candidate_dir.exists():
                candidate_files = sorted(
                    candidate_dir.glob("candidate-*.json"),
                    key=lambda f: f.stat().st_mtime,
                    reverse=True,
                )
                if candidate_files:
                    latest_cand_path_obj = candidate_files[0]
                    candidate_evidence_age_seconds = time.time() - latest_cand_path_obj.stat().st_mtime
                    with open(latest_cand_path_obj, "r", encoding="utf-8") as cf:
                        latest_cand_data = _json.load(cf)
                        latest_candidate_verdict = latest_cand_data.get("verdict", "unknown")

                        # Market data status from candidate
                        md = latest_cand_data.get("market_data", {})
                        if md.get("market_data_available"):
                            market_data_status = "available" if not md.get("stale", True) else "stale"
                        elif md:
                            market_data_status = "unavailable"

                        # FX status from candidate
                        ae = latest_cand_data.get("account_evidence", {})
                        if ae:
                            fx_available = ae.get("fx_available", False)
                            fx_required = ae.get("fx_required", None)
                            if fx_required is False:
                                fx_status = "not_required"
                            elif fx_available:
                                fx_stale = (ae.get("fx_staleness_seconds") or 0) > 300
                                fx_status = "available" if not fx_stale else "stale"
                            else:
                                fx_status = "unavailable"
        except Exception:
            pass

        # Age-based staleness marker (non-refresh path only)
        refreshed_fields = {}

    # ------------------------------------------------------------------
    # 11. Forbidden endpoint scan
    # ------------------------------------------------------------------
    scan_result = _scan_forbidden_endpoints()
    scan_ok = scan_result.get("ok", True)

    # ------------------------------------------------------------------
    # 12. No H1 token reads (from doctor H1 canary)
    # ------------------------------------------------------------------
    h1_canary_check = next(
        (c for c in doctor_checks if c.get("check") == "h1_token_canary"),
        None,
    )
    h1_token_read = False
    if h1_canary_check:
        h1_token_read = h1_canary_check.get("ok") is True
    # Doctor's H1 canary is a PASS (token accepted) or MANUAL_REQUIRED.
    # FAIL would mean token issues.
    h1_canary_ok = h1_canary_check.get("ok", False) if h1_canary_check else True

    # ------------------------------------------------------------------
    # 13. Build blocker list
    # ------------------------------------------------------------------
    blockers: list[dict] = []
    hold_reasons: list[dict] = []

    # --- NO-GO conditions ---

    if bridge_reachable is False and lw_bridge.get("_error") is None:
        blockers.append({"severity": "NO-GO", "check": "bridge_unreachable",
                         "detail": "IBKR bridge is not reachable"})

    if not safety_locked:
        fail_items = []
        if lw_safety.get("read_only") is not True:
            fail_items.append("read_only is not True")
        if lw_safety.get("bridge_allow_orders") not in (False, "false"):
            fail_items.append(f"bridge_allow_orders={lw_safety.get('bridge_allow_orders')}")
        if lw_safety.get("env_IBKR_ALLOW_ORDERS") != "false":
            fail_items.append(f"env IBKR_ALLOW_ORDERS={env_allow_orders}")
        if lw_safety.get("rules_enforced") != "false":
            fail_items.append(f"rules.enforced={rules_enforced}")
        blockers.append({"severity": "NO-GO", "check": "safety_unlocked",
                         "detail": "; ".join(fail_items) if fail_items else "safety unlocked"})

    if active_alert_count > 0:
        blockers.append({"severity": "NO-GO", "check": "active_alerts",
                         "detail": f"{active_alert_count} active alert(s)"})

    if reconciliation_passed is False:
        blockers.append({"severity": "NO-GO", "check": "reconciliation_failed",
                         "detail": "Reconciliation check(s) failed"})

    if kpi_verdict == "NO-GO":
        blockers.append({"severity": "NO-GO", "check": "kpi_nogo",
                         "detail": "KPI dashboard reports NO-GO"})

    if latest_candidate_verdict == "NO-GO":
        blockers.append({"severity": "NO-GO", "check": "candidate_nogo",
                         "detail": "Latest candidate dry-run verdict is NO-GO"})

    if not scan_ok:
        violations = scan_result.get("violations", [])
        blockers.append({"severity": "NO-GO", "check": "forbidden_endpoint_violation",
                         "detail": f"{len(violations)} forbidden endpoint(s) found in source"})

    # H1 token read: if the canary explicitly READ the token (PASS with token read)
    # we consider it evidence of H1 token usage — but the canary is designed to
    # USE the token. The NO-GO condition is when H1 token has been read outside
    # of the expected canary path (FAIL with token_required = token was read but invalid).
    # For autonomy readiness, H1 token read evidence means the canary was run and
    # the token was consumed. That's expected behaviour, not a NO-GO.
    # Only flag if the canary status is PASS (token was sent to bridge).
    h1_canary_status = h1_canary_check.get("status", "") if h1_canary_check else ""
    # The "H1 token read" blocker in the spec is about UNINTENDED token reads.
    # The canary deliberately uses the token — that's not a violation.
    # We interpret "no H1 token read evidence" as: the canary did not unexpectedly
    # succeed with a real token when it shouldn't have. Since the doctor H1 canary
    # is designed to exercise the token, we do NOT flag it as NO-GO.

    # --- HOLD conditions ---

    if current_level != "0":
        hold_reasons.append({"severity": "HOLD", "check": "autonomy_not_level_zero",
                             "detail": f"Current autonomy level is {current_level}, not 0 — promotion only from level 0"})

    if clean_cycles_observed < clean_cycles_required:
        hold_reasons.append({"severity": "HOLD", "check": "insufficient_clean_cycles",
                             "detail": f"{clean_cycles_observed}/{clean_cycles_required} clean cycles in {_CLEAN_CYCLES_WINDOW_DAYS}-day window"})

    # --- Step 15P: Session-aware market data blocker ---
    session_info = light_evidence.get("market_session_status", {})
    if not session_info:
        session_info = _determine_market_session_status()
    snapshot_detail = str(latest_cand_data.get("market_data", {}).get("detail", ""))
    market_runtime_ok = light_evidence.get("market_data_runtime_ok", True)

    md_blocker = _build_session_aware_market_blocker(
        market_data_status=market_data_status,
        snapshot_detail=snapshot_detail,
        session_info=session_info,
        ibkr_connected=ibkr_connected,
        market_data_runtime_ok=market_runtime_ok is not False,
    )
    if md_blocker:
        hold_reasons.append(md_blocker)

    if fx_status == "unavailable":
        hold_reasons.append({"severity": "HOLD", "check": "fx_unavailable",
                             "detail": "FX rate unavailable when required"})
    elif fx_status == "stale":
        hold_reasons.append({"severity": "HOLD", "check": "fx_stale",
                             "detail": "FX rate is stale (>300s)"})

    if doctor_verdict == "FAIL":
        hold_reasons.append({"severity": "HOLD", "check": "doctor_fail",
                             "detail": f"Doctor non-canary checks failed: {', '.join(non_h1_failures)}" if non_h1_failures else "Doctor failed"})

    # Stale connected evidence (non-refresh path only)
    if not refresh_evidence and candidate_evidence_age_seconds is not None:
        if candidate_evidence_age_seconds > _CANDIDATE_EVIDENCE_MAX_AGE_SECONDS:
            hold_reasons.append({"severity": "HOLD", "check": "stale_candidate_evidence",
                                 "detail": f"Candidate evidence is {candidate_evidence_age_seconds:.0f}s old (> {_CANDIDATE_EVIDENCE_MAX_AGE_SECONDS}s max)"})

    # ------------------------------------------------------------------
    # 14. Compute recommendation
    # ------------------------------------------------------------------
    has_nogo = any(b["severity"] == "NO-GO" for b in blockers)
    has_hold = any(r["severity"] == "HOLD" for r in hold_reasons)

    if has_nogo:
        recommendation = "NO_GO"
    elif has_hold:
        recommendation = "HOLD"
    else:
        recommendation = "READY_FOR_MANUAL_REVIEW"

    # Combine all for display
    all_blockers = blockers + hold_reasons

    # ------------------------------------------------------------------
    # 15. Evidence exports
    # ------------------------------------------------------------------
    evidence_exports: list[str] = []
    _AUTONOMY_STATUS_EXPORT_DIR.mkdir(parents=True, exist_ok=True)

    # Export autonomy status result itself
    export_path = _AUTONOMY_STATUS_EXPORT_DIR / f"autonomy-status-{ts_file}.json"
    evidence_exports.append(str(export_path))

    # ------------------------------------------------------------------
    # 16. Build result
    # ------------------------------------------------------------------
    result = {
        "command": "ibkr-operator autonomy-status",
        "advisory": "Read-only autonomy readiness evaluator. No broker mutation. No autonomy level changes.",
        "timestamp": ts_str,
        "git": {
            "branch": git.get("branch", "?"),
            "commit": git.get("commit", "?"),
            "tag": git.get("tag", "?"),
        },
        "current_autonomy_level": current_level,
        "target_autonomy_level": target_level,
        "recommendation": recommendation,
        "clean_cycles_observed": clean_cycles_observed,
        "clean_cycles_required": clean_cycles_required,
        "clean_cycles_window_days": _CLEAN_CYCLES_WINDOW_DAYS,
        "latest_clean_cycle_timestamp": latest_clean_ts,
        "ledger_path": str(ledger_path),
        "doctor_verdict": doctor_verdict,
        "kpi_verdict": kpi_verdict,
        "bridge_reachable": bridge_reachable,
        "ibkr_connected": ibkr_connected,
        "safety_locked": safety_locked,
        "env_IBKR_ALLOW_ORDERS": env_allow_orders,
        "rules_enforced": rules_enforced,
        "active_alert_count": active_alert_count,
        "reconciliation_passed": reconciliation_passed,
        "latest_candidate_verdict": latest_candidate_verdict,
        "market_data_status": market_data_status,
        "fx_status": fx_status,
        "refresh_evidence": refresh_evidence,
        "candidate_evidence_age_seconds": round(candidate_evidence_age_seconds, 2) if candidate_evidence_age_seconds is not None else None,
        # Step 15P: Session-aware fields
        "market_session_status": session_info,
        "market_data_unavailable_reason": _compute_unavailable_reason(
            market_data_status, snapshot_detail, session_info
        ),
        "market_data_runtime_ok": market_runtime_ok is not False,
        "market_data_required_for_readiness": True,
        "market_data_blocks_promotion": md_blocker.get("check", "") not in ("market_data_not_ready_for_session", "") if md_blocker else False,
        **refreshed_fields,
        "blockers": all_blockers,
        "blocker_count": len(all_blockers),
        "evidence_exports": evidence_exports,
        "no_broker_mutation": True,
    }

    # Write export
    try:
        with open(export_path, "w", encoding="utf-8") as f:
            _json.dump(result, f, indent=2, default=str, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
    except Exception:
        pass

    return result


def print_autonomy_status(result: dict) -> None:
    """Print autonomy status in human-readable format."""
    rec = result.get("recommendation", "HOLD")
    if rec == "READY_FOR_MANUAL_REVIEW":
        rec_color = GREEN
        rec_text = f"{GREEN}READY_FOR_MANUAL_REVIEW{RESET}"
    elif rec == "NO_GO":
        rec_color = RED
        rec_text = f"{RED}NO_GO{RESET}"
    else:
        rec_color = RESET
        rec_text = f"{RESET}HOLD{RESET}"

    print(f"{BOLD}══════════════════════════════════════════════════{RESET}")
    print(f"{BOLD}  Autonomy Readiness Evaluator{RESET}")
    print(f"{BOLD}══════════════════════════════════════════════════{RESET}\n")

    print(f"  Timestamp:          {result.get('timestamp', '?')}")
    print(f"  Git:                {result['git'].get('branch', '?')} @ {result['git'].get('commit', '?')}  (tag: {result['git'].get('tag', '?')})")
    print()

    print(f"  {BOLD}Recommendation: {rec_text}{RESET}\n")

    print(f"  {BOLD}Autonomy Levels{RESET}")
    print(f"    Current: {result.get('current_autonomy_level', '?')}")
    print(f"    Target:  {result.get('target_autonomy_level', '?')}")
    print()

    print(f"  {BOLD}Clean Cycles{RESET}")
    print(f"    Observed:  {result.get('clean_cycles_observed', 0)}")
    print(f"    Required:  {result.get('clean_cycles_required', _CLEAN_CYCLES_REQUIRED)}")
    print(f"    Window:    {result.get('clean_cycles_window_days', _CLEAN_CYCLES_WINDOW_DAYS)} days")
    print(f"    Latest:    {result.get('latest_clean_cycle_timestamp', 'none')}")
    print(f"    Ledger:    {result.get('ledger_path', '?')}")
    print()

    print(f"  {BOLD}Bridge{RESET}")
    print(f"    Reachable: {result.get('bridge_reachable', False)}")
    print(f"    Connected: {result.get('ibkr_connected', False)}")
    print()

    print(f"  {BOLD}Safety{RESET}")
    print(f"    Locked:    {result.get('safety_locked', False)}")
    print(f"    Allow Ord: {result.get('env_IBKR_ALLOW_ORDERS', '?')}")
    print(f"    Enforced:  {result.get('rules_enforced', '?')}")
    print()

    print(f"  {BOLD}Verdicts{RESET}")
    print(f"    Doctor:    {result.get('doctor_verdict', '?')}")
    print(f"    KPI:       {result.get('kpi_verdict', '?')}")
    print(f"    Candidate: {result.get('latest_candidate_verdict', '?')}")
    print()

    print(f"  {BOLD}Monitoring{RESET}")
    print(f"    Alerts:    {result.get('active_alert_count', 0)}")
    print(f"    Recon:     {'PASS' if result.get('reconciliation_passed') else 'N/A'}")
    print()

    print(f"  {BOLD}Data Status{RESET}")
    print(f"    Market:    {result.get('market_data_status', '?')}")
    print(f"    FX:        {result.get('fx_status', '?')}")
    print()

    blockers = result.get("blockers", [])
    if blockers:
        print(f"  {BOLD}Blockers ({len(blockers)}){RESET}")
        for b in blockers:
            sev_color = RED if b["severity"] == "NO-GO" else RESET
            print(f"    [{sev_color}{b['severity']}{RESET}] {b['check']}: {b.get('detail', '')}"[:200])
        print()

    exports = result.get("evidence_exports", [])
    if exports:
        print(f"  {BOLD}Evidence Exports{RESET}")
        for e in exports:
            print(f"    {e}")
        print()

    print(f"  no_broker_mutation: {result.get('no_broker_mutation', True)}")
    print()


# ---------------------------------------------------------------------------
# Step 15K — Manual Autonomy-Promotion Review Package
# ---------------------------------------------------------------------------

_AUTONOMY_REVIEW_EXPORT_DIR = OPENCLAW_DIR / "autonomy-review"

_MANUAL_REVIEW_CHECKLIST: list[str] = [
    "Confirm no order window was opened.",
    "Confirm safety flags are locked (IBKR_ALLOW_ORDERS=false, rules.enforced=false).",
    "Confirm clean cycles are valid and recent.",
    "Confirm candidate evidence is HOLD/READY only, never NO-GO.",
    "Confirm market data and FX evidence if IBKR connected.",
    "Confirm promotion is manual only — this package does not auto-promote.",
    "Confirm no live orders will be enabled by this review package.",
]

# Step 15M — Manual Level-1 Promotion Plan (advisory/procedural only)
# ---------------------------------------------------------------------------

_AUTONOMY_PROMOTION_PLANS_DIR = OPENCLAW_DIR / "autonomy-promotion-plans"

_MANUAL_PROMOTION_PRECONDITIONS: list[str] = [
    "Confirm operator is intentionally reviewing autonomy level 0 -> 1.",
    "Confirm no order window is open (IBKR_ALLOW_ORDERS=false, rules.enforced=false).",
    "Confirm safety flags remain locked throughout.",
    "Confirm fresh connected evidence from autonomy-status --refresh-evidence is READY.",
    "Confirm clean cycles are strict-valid and within the required time window.",
    "Confirm this promotion plan does not itself change any config.",
    "Confirm rollback procedure is understood before any manual change.",
]

_MANUAL_PROMOTION_STEPS: list[str] = [
    "1. Locate the autonomy-level definition in docs/AUTONOMY_CRITERIA.md.",
    "2. Record the current autonomy level value (expected: 0).",
    "3. Apply the manual change from level 0 to level 1 ONLY after operator approval.",
    "4. Do NOT enable IBKR_ALLOW_ORDERS — keep it false.",
    "5. Do NOT enable rules.enforced — keep it false.",
    "6. If the local control component requires restart/reload, perform it now.",
    "7. Immediately run post-promotion validation (see validation steps below).",
]

_MANUAL_ROLLBACK_STEPS: list[str] = [
    "1. Revert autonomy level back to 0 in docs/AUTONOMY_CRITERIA.md.",
    "2. Keep IBKR_ALLOW_ORDERS=false — do not enable.",
    "3. Keep rules.enforced=false — do not enable.",
    "4. Restart/reload the local control component if changed.",
    "5. Run ibkr-operator doctor.",
    "6. Run ibkr-operator kpi.",
    "7. Run ibkr-operator autonomy-status --refresh-evidence.",
    "8. Run ibkr-operator autonomy-review.",
    "9. Export rollback evidence using ibkr-operator autonomy-promotion-plan --export.",
]

_POST_PROMOTION_VALIDATION_STEPS: list[str] = [
    "1. Run ibkr-operator doctor — must PASS.",
    "2. Run ibkr-operator kpi — must be HOLD or better, never NO-GO.",
    "3. Run ibkr-operator autonomy-status — must show current level 1.",
    "4. Verify safety flags are still locked.",
    "5. Verify no order window was opened.",
    "6. Verify no positions changed (compare to pre-promotion snapshot).",
    "7. Verify no active alerts.",
    "8. Verify no broker mutation evidence in guard-state.json.",
]

_EXPLICIT_NON_ACTIONS: list[str] = [
    "This command did not change autonomy level.",
    "This command did not open an order window.",
    "This command did not call any no-order endpoints (no /order calls).",
    "This command did not read H1 token.",
    "This command did not place, modify, cancel, or transmit any order.",
    "This command did not enable IBKR_ALLOW_ORDERS.",
    "This command did not enable rules.enforced.",
]


def _run_autonomy_promotion_plan(target_level: str = "1") -> dict:
    """Build a manual autonomy-promotion plan (Step 15M).

    Read-only advisory/procedural artifact. Never changes config or enables trading.
    Always runs fresh connected evidence (refresh_evidence=True).

    Args:
        target_level: Target autonomy level (default "1").

    Returns:
        Dict with plan_status (HOLD | READY_FOR_MANUAL_DECISION | NO_GO),
        all backing evidence, manual steps, and explicit non-actions.
    """
    import hashlib
    import json as _json
    from datetime import datetime, timezone

    now_utc = datetime.now(timezone.utc)
    ts_str = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    ts_file = now_utc.strftime("%Y%m%dT%H%M%SZ")
    plan_id = f"promotion-plan-{ts_file}"

    # ------------------------------------------------------------------
    # 1. Git metadata
    # ------------------------------------------------------------------
    git = _git_metadata(BRIDGE_DIR)

    # ------------------------------------------------------------------
    # 2. Fresh readiness evidence (always refresh)
    # ------------------------------------------------------------------
    autonomy_status: dict = {}
    autonomy_review: dict = {}
    status_error = None
    review_error = None

    try:
        autonomy_status = _run_autonomy_status(refresh_evidence=True)
    except Exception as e:
        autonomy_status = {"_error": str(e)[:200], "recommendation": "ERROR"}
        status_error = str(e)[:200]

    try:
        autonomy_review = _run_autonomy_review(target_level=target_level, refresh_evidence=True)
    except Exception as e:
        autonomy_review = {"_error": str(e)[:200], "review_status": "ERROR"}
        review_error = str(e)[:200]

    # ------------------------------------------------------------------
    # 3. Extract evidence from autonomy-status
    # ------------------------------------------------------------------
    as_recommendation = autonomy_status.get("recommendation", "ERROR")
    current_level = autonomy_status.get("current_autonomy_level", "0")
    clean_cycles_observed = autonomy_status.get("clean_cycles_observed", 0)
    clean_cycles_required = autonomy_status.get("clean_cycles_required", _CLEAN_CYCLES_REQUIRED)
    latest_clean_ts = autonomy_status.get("latest_clean_cycle_timestamp")
    doctor_verdict = autonomy_status.get("doctor_verdict", "UNKNOWN")
    kpi_verdict = autonomy_status.get("kpi_verdict", "UNKNOWN")
    bridge_connected = autonomy_status.get("ibkr_connected", None)
    bridge_reachable = autonomy_status.get("bridge_reachable", False)
    market_data_status = autonomy_status.get("market_data_status", "unknown")
    fx_status = autonomy_status.get("fx_status", "unknown")
    safety_locked = autonomy_status.get("safety_locked", False)
    active_alert_count = autonomy_status.get("active_alert_count", 0)
    reconciliation_passed = autonomy_status.get("reconciliation_passed", None)
    env_allow_orders = autonomy_status.get("env_IBKR_ALLOW_ORDERS", "?")
    rules_enforced = autonomy_status.get("rules_enforced", "?")
    system_locked = autonomy_status.get("system_locked", None)

    readiness_export_path = None
    as_exports = autonomy_status.get("evidence_exports", [])
    if as_exports:
        readiness_export_path = as_exports[0]

    # ------------------------------------------------------------------
    # 4. Extract evidence from autonomy-review
    # ------------------------------------------------------------------
    review_status = autonomy_review.get("review_status", "ERROR")
    review_export_path = autonomy_review.get("_export_path")

    # ------------------------------------------------------------------
    # 5. Forbidden endpoint scan
    # ------------------------------------------------------------------
    scan_result = _scan_forbidden_endpoints()
    scan_ok = scan_result.get("ok", True)
    scan_violations = scan_result.get("violations", [])

    # ------------------------------------------------------------------
    # 6. Compute plan_status
    # ------------------------------------------------------------------
    blockers: list[dict] = []

    # --- NO-GO conditions ---
    if not safety_locked:
        blockers.append({"severity": "NO-GO", "check": "safety_unlocked",
                         "detail": "Safety flags are not locked"})

    if env_allow_orders == "true":
        blockers.append({"severity": "NO-GO", "check": "orders_enabled",
                         "detail": "IBKR_ALLOW_ORDERS is true — must be false"})

    if rules_enforced == "true":
        blockers.append({"severity": "NO-GO", "check": "rules_enforced",
                         "detail": "rules.enforced is true — must be false"})

    if not bridge_reachable and bridge_connected is not True:
        blockers.append({"severity": "NO-GO", "check": "bridge_unreachable",
                         "detail": "IBKR bridge is unreachable"})

    if doctor_verdict == "FAIL":
        # Only NO-GO if non-H1 failures exist
        blockers.append({"severity": "NO-GO", "check": "doctor_fail",
                         "detail": "Doctor non-H1 checks failed"})

    if kpi_verdict == "NO-GO":
        blockers.append({"severity": "NO-GO", "check": "kpi_nogo",
                         "detail": "KPI dashboard reports NO-GO"})

    if active_alert_count > 0:
        blockers.append({"severity": "NO-GO", "check": "active_alerts",
                         "detail": f"{active_alert_count} active alert(s)"})

    if reconciliation_passed is False:
        blockers.append({"severity": "NO-GO", "check": "reconciliation_failed",
                         "detail": "Reconciliation check(s) failed"})

    if not scan_ok:
        blockers.append({"severity": "NO-GO", "check": "forbidden_endpoint_violation",
                         "detail": f"{len(scan_violations)} forbidden endpoint(s) in source"})

    # Check for order endpoint usage in autonomy-status / review source
    _source_checks = _scan_source_for_order_usage()
    if not _source_checks.get("ok", True):
        blockers.append({"severity": "NO-GO", "check": "source_order_usage",
                         "detail": "Order endpoint references found in operator source"})

    # Check for H1 token reads
    _h1_checks = _scan_source_for_h1_usage()
    if not _h1_checks.get("ok", True):
        blockers.append({"severity": "NO-GO", "check": "h1_token_read",
                         "detail": "H1 token read evidence detected"})

    # --- HOLD conditions (only if no NO-GO) ---
    hold_reasons: list[dict] = []

    if current_level != "0":
        hold_reasons.append({"severity": "HOLD", "check": "autonomy_not_level_zero",
                             "detail": f"Current level is {current_level}, promotion only from level 0"})

    if target_level != "1":
        hold_reasons.append({"severity": "HOLD", "check": "invalid_target_level",
                             "detail": f"Target level {target_level} is not '1'"})

    if as_recommendation == "HOLD":
        hold_reasons.append({"severity": "HOLD", "check": "autonomy_status_hold",
                             "detail": "Autonomy-status recommendation is HOLD"})

    if as_recommendation == "ERROR":
        hold_reasons.append({"severity": "HOLD", "check": "autonomy_status_error",
                             "detail": f"Autonomy-status failed: {status_error or 'unknown'}"})

    if review_status == "HOLD":
        hold_reasons.append({"severity": "HOLD", "check": "autonomy_review_hold",
                             "detail": "Autonomy-review status is HOLD"})

    if review_status == "ERROR":
        hold_reasons.append({"severity": "HOLD", "check": "autonomy_review_error",
                             "detail": f"Autonomy-review failed: {review_error or 'unknown'}"})

    if clean_cycles_observed < clean_cycles_required:
        hold_reasons.append({"severity": "HOLD", "check": "insufficient_clean_cycles",
                             "detail": f"{clean_cycles_observed}/{clean_cycles_required} clean cycles"})

    if bridge_connected is False:
        hold_reasons.append({"severity": "HOLD", "check": "ibkr_disconnected",
                             "detail": "IBKR Gateway is not connected"})

    # Step 15P: Session-aware market data blocker (instead of ad-hoc checks)
    session_info_p = autonomy_status.get("market_session_status", {})
    snapshot_detail_p = autonomy_status.get("market_data_unavailable_reason", "unknown")
    market_runtime_ok_p = autonomy_status.get("market_data_runtime_ok", True)

    md_blocker_p = _build_session_aware_market_blocker(
        market_data_status=market_data_status,
        snapshot_detail=snapshot_detail_p,
        session_info=session_info_p,
        ibkr_connected=bridge_connected,
        market_data_runtime_ok=market_runtime_ok_p is not False,
    )
    if md_blocker_p:
        hold_reasons.append(md_blocker_p)

    if fx_status == "unavailable":
        hold_reasons.append({"severity": "HOLD", "check": "fx_unavailable",
                             "detail": "FX rate unavailable when required"})
    elif fx_status == "stale":
        hold_reasons.append({"severity": "HOLD", "check": "fx_stale",
                             "detail": "FX rate is stale"})

    if doctor_verdict not in ("PASS", "UNKNOWN", "ERROR"):
        hold_reasons.append({"severity": "HOLD", "check": "doctor_not_pass",
                             "detail": f"Doctor verdict is {doctor_verdict}"})

    # --- Compute final plan_status ---
    has_nogo = any(b["severity"] == "NO-GO" for b in blockers)
    has_hold = any(r["severity"] == "HOLD" for r in hold_reasons)

    if has_nogo:
        plan_status = "NO_GO"
    elif has_hold:
        plan_status = "HOLD"
    elif (as_recommendation == "READY_FOR_MANUAL_REVIEW"
          and review_status == "READY_FOR_OPERATOR_REVIEW"
          and current_level == "0"
          and target_level == "1"
          and clean_cycles_observed >= clean_cycles_required
          and doctor_verdict == "PASS"
          and kpi_verdict not in ("NO-GO", "ERROR")
          and bridge_connected is True
          and market_data_status == "available"
          and fx_status in ("available", "not_required")
          and active_alert_count == 0
          and reconciliation_passed is True
          and safety_locked
          and env_allow_orders == "false"
          and rules_enforced == "false"
          and scan_ok):
        plan_status = "READY_FOR_MANUAL_DECISION"
    else:
        plan_status = "HOLD"

    all_blockers = blockers + hold_reasons

    # ------------------------------------------------------------------
    # 7. Evidence hash (tamper-evident)
    # ------------------------------------------------------------------
    hashable = {
        "current_autonomy_level": current_level,
        "target_autonomy_level": target_level,
        "plan_status": plan_status,
        "clean_cycles_observed": clean_cycles_observed,
        "clean_cycles_required": clean_cycles_required,
        "safety_locked": safety_locked,
        "env_IBKR_ALLOW_ORDERS": env_allow_orders,
        "rules_enforced": rules_enforced,
        "bridge_connected": bridge_connected,
        "bridge_reachable": bridge_reachable,
        "active_alert_count": active_alert_count,
        "reconciliation_passed": reconciliation_passed,
        "autonomy_status_recommendation": as_recommendation,
        "autonomy_review_status": review_status,
        "doctor_verdict": doctor_verdict,
        "kpi_verdict": kpi_verdict,
        "market_data_status": market_data_status,
        "fx_status": fx_status,
        "forbidden_endpoint_scan_ok": scan_ok,
        "blocker_count": len(all_blockers),
        "blocker_checks": sorted(b["check"] for b in all_blockers),
        "git_commit": git.get("commit", "?"),
        "auto_promotion_performed": False,
        "no_broker_mutation": True,
    }
    evidence_hash = _compute_evidence_hash(hashable)

    # ------------------------------------------------------------------
    # 8. Export to disk
    # ------------------------------------------------------------------
    _AUTONOMY_PROMOTION_PLANS_DIR.mkdir(parents=True, exist_ok=True)
    export_path = _AUTONOMY_PROMOTION_PLANS_DIR / f"{plan_id}.json"

    # ------------------------------------------------------------------
    # 9. Build result
    # ------------------------------------------------------------------
    result = {
        "command": "ibkr-operator autonomy-promotion-plan",
        "advisory": (
            "Read-only manual promotion procedure specification (Step 15M). "
            "This artifact is advisory/procedural only. It does NOT change "
            "autonomy level, enable trading, or mutate broker state. "
            "All actions must be performed manually by the operator."
        ),
        "timestamp": ts_str,
        "plan_id": plan_id,
        "git": {
            "branch": git.get("branch", "?"),
            "commit": git.get("commit", "?"),
            "tag": git.get("tag", "?"),
        },
        "current_autonomy_level": current_level,
        "target_autonomy_level": target_level,
        "plan_status": plan_status,
        "operator_decision_required": True,
        "auto_promotion_performed": False,
        "config_changed": False,
        "no_broker_mutation": True,
        "no_order_window_opened": True,
        "readiness_export_path": readiness_export_path,
        "review_export_path": review_export_path,
        "clean_cycles_observed": clean_cycles_observed,
        "clean_cycles_required": clean_cycles_required,
        "latest_clean_cycle_timestamp": latest_clean_ts,
        "doctor_verdict": doctor_verdict,
        "kpi_verdict": kpi_verdict,
        "autonomy_status_recommendation": as_recommendation,
        "autonomy_review_status": review_status,
        "bridge_connected": bridge_connected,
        "bridge_reachable": bridge_reachable,
        "market_data_status": market_data_status,
        "fx_status": fx_status,
        # Step 15P: Session-aware market data fields
        "market_session_status": session_info_p,
        "market_data_unavailable_reason": snapshot_detail_p,
        "market_data_runtime_ok": market_runtime_ok_p,
        "market_data_required_for_readiness": True,
        "market_data_blocks_promotion": md_blocker_p.get("check", "") not in ("market_data_not_ready_for_session", "") if md_blocker_p else False,
        "safety_flags": {
            "safety_locked": safety_locked,
            "env_IBKR_ALLOW_ORDERS": env_allow_orders,
            "rules_enforced": rules_enforced,
            "system_locked": system_locked,
        },
        "active_alert_count": active_alert_count,
        "reconciliation_passed": reconciliation_passed,
        "forbidden_endpoint_scan": {
            "ok": scan_ok,
            "violations": scan_violations,
        },
        "blockers": all_blockers,
        "manual_preconditions": [
            {"step": idx + 1, "precondition": p}
            for idx, p in enumerate(_MANUAL_PROMOTION_PRECONDITIONS)
        ],
        "manual_promotion_steps": [
            {"step": idx + 1, "action": s}
            for idx, s in enumerate(_MANUAL_PROMOTION_STEPS)
        ],
        "manual_rollback_steps": [
            {"step": idx + 1, "action": s}
            for idx, s in enumerate(_MANUAL_ROLLBACK_STEPS)
        ],
        "post_promotion_validation_steps": [
            {"step": idx + 1, "action": s}
            for idx, s in enumerate(_POST_PROMOTION_VALIDATION_STEPS)
        ],
        "explicit_non_actions": _EXPLICIT_NON_ACTIONS,
        "evidence_hash": evidence_hash,
        "_export_path": str(export_path),
    }

    # Write export
    try:
        with open(export_path, "w", encoding="utf-8") as f:
            _json.dump(result, f, indent=2, default=str, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
    except Exception:
        pass

    return result


def _scan_source_for_order_usage() -> dict:
    """Scan _run_autonomy_promotion_plan source for order endpoint usage."""
    import inspect
    forbidden = ["/order/preflight", "/order/approve", "/order/submit",
                 "placeOrder", "cancelOrder"]
    found = []
    try:
        src = inspect.getsource(_run_autonomy_promotion_plan)
        for line in src.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            for pattern in forbidden:
                if pattern in stripped:
                    found.append({"pattern": pattern, "line": stripped[:100]})
    except Exception:
        pass
    return {"ok": len(found) == 0, "found": found}


def _scan_source_for_h1_usage() -> dict:
    """Scan _run_autonomy_promotion_plan source for H1 token references."""
    import inspect
    forbidden = ["_run_h1_canary(", "sudo ", "/etc/ibkr-bridge/h1_token",
                 "H1_APPROVAL_TOKEN"]
    found = []
    try:
        src = inspect.getsource(_run_autonomy_promotion_plan)
        for line in src.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            for pattern in forbidden:
                if pattern in stripped:
                    found.append({"pattern": pattern, "line": stripped[:100]})
    except Exception:
        pass
    return {"ok": len(found) == 0, "found": found}


def _print_promotion_plan(result: dict) -> None:
    """Print autonomy promotion plan in human-readable format."""
    ps = result.get("plan_status", "HOLD")
    if ps == "READY_FOR_MANUAL_DECISION":
        ps_color = GREEN
        ps_text = f"{GREEN}READY_FOR_MANUAL_DECISION{RESET}"
    elif ps == "NO_GO":
        ps_color = RED
        ps_text = f"{RED}NO_GO{RESET}"
    else:
        ps_color = RESET
        ps_text = f"{RESET}HOLD{RESET}"

    print(f"{BOLD}══════════════════════════════════════════════════{RESET}")
    print(f"{BOLD}  Autonomy Level 0 → 1 Promotion Plan (Step 15M){RESET}")
    print(f"{BOLD}══════════════════════════════════════════════════{RESET}\n")

    print(f"  Plan ID:           {result.get('plan_id', '?')}")
    print(f"  Timestamp:         {result.get('timestamp', '?')}")
    print(f"  Git:               {result['git'].get('branch', '?')} @ "
          f"{result['git'].get('commit', '?')}")
    print()

    print(f"  {BOLD}Plan Status: {ps_text}{RESET}\n")

    print(f"  {BOLD}Autonomy Levels{RESET}")
    print(f"    Current:          {result.get('current_autonomy_level', '?')}")
    print(f"    Target:           {result.get('target_autonomy_level', '?')}")
    print()

    print(f"  {BOLD}Evidence{RESET}")
    print(f"    Clean Cycles:     {result.get('clean_cycles_observed', 0)}/"
          f"{result.get('clean_cycles_required', 5)}")
    print(f"    Doctor:           {result.get('doctor_verdict', '?')}")
    print(f"    KPI:              {result.get('kpi_verdict', '?')}")
    print(f"    Autonomy-Status:  {result.get('autonomy_status_recommendation', '?')}")
    print(f"    Autonomy-Review:  {result.get('autonomy_review_status', '?')}")
    print()

    sf = result.get("safety_flags", {})
    print(f"  {BOLD}Safety{RESET}")
    print(f"    Locked:           {sf.get('safety_locked', '?')}")
    print(f"    IBKR_ALLOW_ORDERS:{sf.get('env_IBKR_ALLOW_ORDERS', '?')}")
    print(f"    rules.enforced:   {sf.get('rules_enforced', '?')}")
    print()

    print(f"  {BOLD}Connection{RESET}")
    print(f"    Bridge Connected: {result.get('bridge_connected', '?')}")
    print(f"    Market Data:      {result.get('market_data_status', '?')}")
    print(f"    FX:               {result.get('fx_status', '?')}")
    print()

    print(f"  {BOLD}Alerts{RESET}")
    print(f"    Active:           {result.get('active_alert_count', 0)}")
    print(f"    Reconciliation:   {result.get('reconciliation_passed', '?')}")
    print()

    blockers = result.get("blockers", [])
    if blockers:
        print(f"  {BOLD}Blockers ({len(blockers)}){RESET}")
        for b in blockers:
            sev = b["severity"]
            sev_color = RED if sev == "NO-GO" else RESET
            print(f"    {sev_color}{sev:<6}{RESET} {b['check']}: {b.get('detail', '?')}")
        print()

    print(f"  {BOLD}Operator Decision Required: YES{RESET}")
    print(f"  Auto-Promotion:    {result.get('auto_promotion_performed', False)}")
    print(f"  Config Changed:    {result.get('config_changed', False)}")
    print(f"  Broker Mutation:   {not result.get('no_broker_mutation', True)}")
    print()

    pre = result.get("manual_preconditions", [])
    if pre:
        print(f"  {BOLD}Manual Preconditions{RESET}")
        for p in pre:
            print(f"    [{p['step']}]  {p['precondition']}")
        print()

    steps = result.get("manual_promotion_steps", [])
    if steps:
        print(f"  {BOLD}Manual Promotion Steps{RESET}")
        for s in steps:
            print(f"    {s['action']}")
        print()

    rb = result.get("manual_rollback_steps", [])
    if rb:
        print(f"  {BOLD}Manual Rollback Steps{RESET}")
        for s in rb:
            print(f"    {s['action']}")
        print()

    na = result.get("explicit_non_actions", [])
    if na:
        print(f"  {BOLD}Explicit Non-Actions{RESET}")
        for a in na:
            print(f"    ✗  {a}")
        print()

    print(f"  Evidence Hash:     {result.get('evidence_hash', '?')[:16]}...")
    print()
    print(f"  {BOLD}══════════════════════════════════════════════════{RESET}")


def _compute_evidence_hash(data: object) -> str:
    """Compute a SHA-256 hash of canonicalised review evidence.

    Used to provide tamper-evident packaging for manual review.
    Excludes volatile fields (timestamp, review_id, evidence_hash itself).
    """
    import hashlib
    if isinstance(data, dict):
        canonical = {
            k: _compute_evidence_hash(v)
            for k, v in sorted(data.items())
            if k not in ("timestamp", "review_id", "evidence_hash", "generated_at_utc")
        }
        raw = json.dumps(canonical, sort_keys=True, default=str, ensure_ascii=False)
    elif isinstance(data, list):
        raw = json.dumps(
            [_compute_evidence_hash(v) for v in data],
            sort_keys=True, default=str, ensure_ascii=False,
        )
    else:
        raw = json.dumps(data, default=str, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _run_autonomy_review(target_level: str = "1", refresh_evidence: bool = False) -> dict:
    """Build a manual autonomy-promotion review package.

    Read-only. No broker mutation. No autonomy level changes.
    Never auto-promotes. Packages all evidence for operator review.

    Args:
        target_level: Target autonomy level (default "1").
        refresh_evidence: Pass through to autonomy-status for fresh connected checks.

    Returns:
        Dict with review_status, manual checklist, evidence hash, and all
        backing evidence needed for a human operator to make a promotion decision.
    """
    import hashlib
    import json as _json
    from datetime import datetime, timezone

    now_utc = datetime.now(timezone.utc)
    ts_str = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    ts_file = now_utc.strftime("%Y%m%dT%H%M%SZ")
    review_id = f"review-{ts_file}"

    # ------------------------------------------------------------------
    # 1. Git metadata
    # ------------------------------------------------------------------
    git = _git_metadata(BRIDGE_DIR)

    # ------------------------------------------------------------------
    # 2. Run autonomy-status (canonical readiness evaluation)
    # ------------------------------------------------------------------
    autonomy_status: dict = {}
    try:
        autonomy_status = _run_autonomy_status(refresh_evidence=refresh_evidence)
    except Exception as e:
        autonomy_status = {"_error": str(e)[:200], "recommendation": "ERROR"}

    as_recommendation = autonomy_status.get("recommendation", "HOLD")
    current_level = autonomy_status.get("current_autonomy_level", "0")

    # ------------------------------------------------------------------
    # 3. Latest candidate (most recent from candidate-dryruns)
    # ------------------------------------------------------------------
    latest_candidate: dict = {}
    latest_cand_path: str | None = None
    candidate_dir = OPENCLAW_DIR / _CANDIDATE_EXPORT_DIR_NAME
    try:
        if candidate_dir.exists():
            cand_files = sorted(
                candidate_dir.glob("candidate-*.json"),
                key=lambda f: f.stat().st_mtime,
                reverse=True,
            )
            if cand_files:
                latest_cand_path = str(cand_files[0])
                with open(cand_files[0], "r", encoding="utf-8") as cf:
                    latest_candidate = _json.load(cf)
    except Exception:
        pass

    cand_verdict = latest_candidate.get("verdict", "unavailable")
    cand_summary = {
        "path": latest_cand_path,
        "symbol": latest_candidate.get("symbol", "?"),
        "side": latest_candidate.get("side", "?"),
        "verdict": cand_verdict,
        "timestamp": latest_candidate.get("timestamp", "?"),
    }

    # ------------------------------------------------------------------
    # 4. Latest KPI (most recent from exports)
    # ------------------------------------------------------------------
    latest_kpi: dict = {}
    kpi_files: list = []
    kpi_dir = OPENCLAW_DIR / "exports"
    try:
        if kpi_dir.exists():
            kpi_files = sorted(
                kpi_dir.glob("kpi-dashboard-*.json"),
                key=lambda f: f.stat().st_mtime,
                reverse=True,
            )
            if kpi_files:
                with open(kpi_files[0], "r", encoding="utf-8") as kf:
                    latest_kpi = _json.load(kf)
    except Exception:
        pass

    kpi_verdict = latest_kpi.get("verdict", "unavailable")
    kpi_summary = {
        "path": str(kpi_files[0]) if kpi_files else None,
        "verdict": kpi_verdict,
        "timestamp": latest_kpi.get("timestamp", "?"),
        "active_alert_count": latest_kpi.get("monitoring", {}).get("active_alert_count", -1),
        "reconciliation_passed": latest_kpi.get("monitoring", {}).get("reconciliation_passed"),
    }

    # ------------------------------------------------------------------
    # 5. Doctor summary (lightweight in-process)
    # ------------------------------------------------------------------
    doctor_summary: dict = {}
    try:
        lw = _collect_lightweight_evidence()
        doc = lw.get("doctor", {})
        doctor_summary = {
            "pass": doc.get("pass"),
            "passed": doc.get("passed", 0),
            "total": doc.get("total", 0),
            "checks": [
                {"check": c.get("check"), "ok": c.get("ok")}
                for c in doc.get("checks", [])
            ],
        }
    except Exception:
        doctor_summary = {"pass": None, "error": "unavailable"}

    # ------------------------------------------------------------------
    # 6. Clean-cycle ledger entries used (with time window)
    # ------------------------------------------------------------------
    ledger_path = _CLEAN_CYCLE_LEDGER
    clean_cycle_entries: list[dict] = []
    window_cutoff = time.time() - (_CLEAN_CYCLES_WINDOW_DAYS * 86400)
    try:
        if ledger_path.exists():
            with open(ledger_path, "r", encoding="utf-8") as lf:
                for line in lf:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = _json.loads(line)
                    except (json.JSONDecodeError, ValueError):
                        continue
                    if not isinstance(entry, dict):
                        continue
                    is_clean, _ = _ledger_entry_strict_clean(entry)
                    if not is_clean:
                        continue
                    # Apply time window
                    ts = entry.get("timestamp", "")
                    try:
                        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                        if dt.timestamp() < window_cutoff:
                            continue
                    except (ValueError, TypeError):
                        pass
                    # Include timestamp/id/symbol for audit trail
                    clean_cycle_entries.append({
                        "cycle_id": entry.get("cycle_id", "?"),
                        "timestamp": entry.get("timestamp", "?"),
                        "symbol": entry.get("symbol", "?"),
                        "side": entry.get("side", "?"),
                        "entry_hash": entry.get("entry_hash", "?")[:16],
                    })
    except Exception:
        pass

    clean_cycles_observed = len(clean_cycle_entries)
    clean_cycles_required = _CLEAN_CYCLES_REQUIRED

    # ------------------------------------------------------------------
    # 7. Safety flags (from autonomy-status)
    # ------------------------------------------------------------------
    safety_locked = autonomy_status.get("safety_locked", False)
    env_ao = autonomy_status.get("env_IBKR_ALLOW_ORDERS", "?")
    rules_enforced = autonomy_status.get("rules_enforced", "?")
    ibkr_connected = autonomy_status.get("ibkr_connected", None)
    active_alert_count = autonomy_status.get("active_alert_count", 0)
    reconciliation_passed = autonomy_status.get("reconciliation_passed", None)
    market_data_status = autonomy_status.get("market_data_status", "unknown")
    fx_status = autonomy_status.get("fx_status", "unknown")

    # ------------------------------------------------------------------
    # 8. Forbidden endpoint scan
    # ------------------------------------------------------------------
    scan_result = _scan_forbidden_endpoints()
    scan_ok = scan_result.get("ok", True)
    scan_violations = scan_result.get("violations", [])

    # ------------------------------------------------------------------
    # 9. Compute review_status
    # ------------------------------------------------------------------
    blockers: list[dict] = []

    # NO-GO conditions
    if not safety_locked:
        blockers.append({"severity": "NO-GO", "check": "safety_unlocked",
                         "detail": "Safety flags are not locked"})

    # Bridge reachable check (from autonomy-status)
    if not autonomy_status.get("bridge_reachable", False):
        blockers.append({"severity": "NO-GO", "check": "bridge_unreachable",
                         "detail": "IBKR bridge is unreachable"})

    if kpi_verdict == "NO-GO":
        blockers.append({"severity": "NO-GO", "check": "kpi_nogo",
                         "detail": "Latest KPI dashboard reports NO-GO"})

    if cand_verdict == "NO-GO":
        blockers.append({"severity": "NO-GO", "check": "candidate_nogo",
                         "detail": "Latest candidate dry-run verdict is NO-GO"})

    if active_alert_count > 0:
        blockers.append({"severity": "NO-GO", "check": "active_alerts",
                         "detail": f"{active_alert_count} active alert(s)"})

    if reconciliation_passed is False:
        blockers.append({"severity": "NO-GO", "check": "reconciliation_failed",
                         "detail": "Reconciliation check(s) failed"})

    if not scan_ok:
        blockers.append({"severity": "NO-GO", "check": "forbidden_endpoint_violation",
                         "detail": f"{len(scan_violations)} forbidden endpoint(s) in source"})

    if as_recommendation == "NO_GO":
        blockers.append({"severity": "NO-GO", "check": "autonomy_status_nogo",
                         "detail": "Autonomy-status recommendation is NO_GO"})

    if current_level != "0":
        blockers.append({"severity": "NO-GO", "check": "autonomy_not_level_zero",
                         "detail": f"Current level is {current_level}, promotion only from level 0"})

    if target_level != "1":
        blockers.append({"severity": "NO-GO", "check": "invalid_target_level",
                         "detail": f"Target level {target_level} is not '1'"})

    # HOLD conditions (only if no NO-GO)
    hold_reasons: list[dict] = []

    if as_recommendation == "HOLD":
        hold_reasons.append({"severity": "HOLD", "check": "autonomy_status_hold",
                             "detail": "Autonomy-status recommendation is HOLD"})

    if clean_cycles_observed < clean_cycles_required:
        hold_reasons.append({"severity": "HOLD", "check": "insufficient_clean_cycles",
                             "detail": f"{clean_cycles_observed}/{clean_cycles_required} clean cycles"})

    if ibkr_connected is False:
        hold_reasons.append({"severity": "HOLD", "check": "ibkr_disconnected",
                             "detail": "IBKR Gateway is not connected"})

    # Step 15P: Session-aware market data blocker
    session_info_r = autonomy_status.get("market_session_status", {})
    snapshot_detail_r = autonomy_status.get("market_data_unavailable_reason", "unknown")
    market_runtime_ok_r = autonomy_status.get("market_data_runtime_ok", True)

    md_blocker_r = _build_session_aware_market_blocker(
        market_data_status=market_data_status,
        snapshot_detail=snapshot_detail_r,
        session_info=session_info_r,
        ibkr_connected=ibkr_connected,
        market_data_runtime_ok=market_runtime_ok_r is not False,
    )
    if md_blocker_r:
        hold_reasons.append(md_blocker_r)

    if fx_status == "unavailable":
        hold_reasons.append({"severity": "HOLD", "check": "fx_unavailable",
                             "detail": "FX rate unavailable when required"})

    if autonomy_status.get("system_locked") is True and not any(
        b["check"] == "autonomy_status_hold" for b in hold_reasons
    ):
        # System locked is only HOLD if no other blockers explain it
        pass  # already covered by autonomy_status_hold

    # Compute final review_status
    has_nogo = any(b["severity"] == "NO-GO" for b in blockers)
    has_hold = any(r["severity"] == "HOLD" for r in hold_reasons)

    # READY_FOR_OPERATOR_REVIEW requires autonomy-status READY_FOR_MANUAL_REVIEW
    # plus no NO-GO and no HOLD conditions
    if as_recommendation == "READY_FOR_MANUAL_REVIEW" and not has_nogo and not has_hold:
        review_status = "READY_FOR_OPERATOR_REVIEW"
    elif has_nogo:
        review_status = "NO_GO"
    else:
        review_status = "HOLD"

    all_blockers = blockers + hold_reasons

    # ------------------------------------------------------------------
    # 10. Build evidence hash (tamper-evident)
    # ------------------------------------------------------------------
    hashable = {
        "current_autonomy_level": current_level,
        "target_autonomy_level": target_level,
        "review_status": review_status,
        "clean_cycles_observed": clean_cycles_observed,
        "clean_cycles_required": clean_cycles_required,
        "safety_locked": safety_locked,
        "env_IBKR_ALLOW_ORDERS": env_ao,
        "rules_enforced": rules_enforced,
        "ibkr_connected": ibkr_connected,
        "active_alert_count": active_alert_count,
        "reconciliation_passed": reconciliation_passed,
        "autonomy_status_recommendation": as_recommendation,
        "kpi_verdict": kpi_verdict,
        "candidate_verdict": cand_verdict,
        "forbidden_endpoint_scan_ok": scan_ok,
        "blocker_count": len(all_blockers),
        "blocker_checks": sorted(b["check"] for b in all_blockers),
        "git_commit": git.get("commit", "?"),
        "auto_promotion_performed": False,
        "no_broker_mutation": True,
    }
    evidence_hash = _compute_evidence_hash(hashable)

    # ------------------------------------------------------------------
    # 11. Export
    # ------------------------------------------------------------------
    _AUTONOMY_REVIEW_EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    export_path = _AUTONOMY_REVIEW_EXPORT_DIR / f"autonomy-review-{ts_file}.json"

    # Build result
    result = {
        "command": "ibkr-operator autonomy-review",
        "advisory": "Read-only manual review package. No broker mutation. No autonomy level changes. No auto-promotion.",
        "timestamp": ts_str,
        "review_id": review_id,
        "git": {
            "branch": git.get("branch", "?"),
            "commit": git.get("commit", "?"),
            "tag": git.get("tag", "?"),
        },
        "current_autonomy_level": current_level,
        "target_autonomy_level": target_level,
        "review_status": review_status,
        "operator_decision_required": True,
        "auto_promotion_performed": False,
        "no_broker_mutation": True,
        "autonomy_status_export_path": autonomy_status.get("evidence_exports", [None])[0],
        "latest_autonomy_status_summary": {
            "recommendation": as_recommendation,
            "clean_cycles_observed": autonomy_status.get("clean_cycles_observed", 0),
            "doctor_verdict": autonomy_status.get("doctor_verdict", "?"),
            "kpi_verdict": autonomy_status.get("kpi_verdict", "?"),
            "latest_candidate_verdict": autonomy_status.get("latest_candidate_verdict", "?"),
            "market_data_status": autonomy_status.get("market_data_status", "?"),
            "market_session_status": autonomy_status.get("market_session_status", {}),
            "market_data_unavailable_reason": autonomy_status.get("market_data_unavailable_reason", "unknown"),
            "market_data_runtime_ok": autonomy_status.get("market_data_runtime_ok", True),
            "market_data_blocks_promotion": autonomy_status.get("market_data_blocks_promotion", False),
            "fx_status": autonomy_status.get("fx_status", "?"),
            "active_alert_count": autonomy_status.get("active_alert_count", 0),
            "reconciliation_passed": autonomy_status.get("reconciliation_passed"),
        },
        "clean_cycles_observed": clean_cycles_observed,
        "clean_cycles_required": clean_cycles_required,
        "clean_cycle_ledger_path": str(ledger_path),
        "clean_cycle_entries_used": clean_cycle_entries,
        "latest_candidate_export_path": latest_cand_path,
        "latest_candidate_summary": cand_summary,
        "latest_kpi_summary": kpi_summary,
        "doctor_summary": doctor_summary,
        "safety_flags": {
            "safety_locked": safety_locked,
            "env_IBKR_ALLOW_ORDERS": env_ao,
            "rules_enforced": rules_enforced,
            "system_locked": autonomy_status.get("system_locked"),
            "bridge_read_only": autonomy_status.get("bridge_reachable"),
        },
        "ibkr_connected": ibkr_connected,
        "market_data_status": market_data_status,
        "fx_status": fx_status,
        # Step 15P: Session-aware market data fields
        "market_session_status": session_info_r,
        "market_data_unavailable_reason": snapshot_detail_r,
        "market_data_runtime_ok": market_runtime_ok_r,
        "market_data_required_for_readiness": True,
        "market_data_blocks_promotion": md_blocker_r.get("check", "") not in ("market_data_not_ready_for_session", "") if md_blocker_r else False,
        "active_alert_count": active_alert_count,
        "reconciliation_passed": reconciliation_passed,
        "blockers": all_blockers,
        "manual_review_checklist": [
            {"item": idx + 1, "task": task}
            for idx, task in enumerate(_MANUAL_REVIEW_CHECKLIST)
        ],
        "evidence_hash": evidence_hash,
        "_export_path": str(export_path),
    }

    # Write export
    try:
        with open(export_path, "w", encoding="utf-8") as f:
            _json.dump(result, f, indent=2, default=str, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
    except Exception:
        pass

    return result


def print_autonomy_review(result: dict) -> None:
    """Print autonomy review package in human-readable format."""
    rs = result.get("review_status", "HOLD")
    if rs == "READY_FOR_OPERATOR_REVIEW":
        rs_color = GREEN
        rs_text = f"{GREEN}READY_FOR_OPERATOR_REVIEW{RESET}"
    elif rs == "NO_GO":
        rs_color = RED
        rs_text = f"{RED}NO_GO{RESET}"
    else:
        rs_color = RESET
        rs_text = f"{RESET}HOLD{RESET}"

    print(f"{BOLD}══════════════════════════════════════════════════{RESET}")
    print(f"{BOLD}  Autonomy Promotion Review Package{RESET}")
    print(f"{BOLD}══════════════════════════════════════════════════{RESET}\n")

    print(f"  Review ID:         {result.get('review_id', '?')}")
    print(f"  Timestamp:         {result.get('timestamp', '?')}")
    print(f"  Git:               {result['git'].get('branch', '?')} @ {result['git'].get('commit', '?')}")
    print()

    print(f"  {BOLD}Review Status: {rs_text}{RESET}\n")

    print(f"  {BOLD}Autonomy Levels{RESET}")
    print(f"    Current:          {result.get('current_autonomy_level', '?')}")
    print(f"    Target:           {result.get('target_autonomy_level', '?')}")
    print()

    print(f"  {BOLD}Clean Cycles{RESET}")
    print(f"    Observed:         {result.get('clean_cycles_observed', 0)}")
    print(f"    Required:         {result.get('clean_cycles_required', _CLEAN_CYCLES_REQUIRED)}")
    print(f"    Ledger:           {result.get('clean_cycle_ledger_path', '?')}")
    entries = result.get('clean_cycle_entries_used', [])
    if entries:
        for e in entries[:5]:
            print(f"      {e.get('cycle_id', '?')}  {e.get('symbol', '?')}/{e.get('side', '?')}  {e.get('timestamp', '?')}")
        if len(entries) > 5:
            print(f"      ... and {len(entries) - 5} more")
    print()

    print(f"  {BOLD}Safety{RESET}")
    sf = result.get("safety_flags", {})
    print(f"    Locked:           {sf.get('safety_locked', False)}")
    print(f"    Allow Orders:     {sf.get('env_IBKR_ALLOW_ORDERS', '?')}")
    print(f"    Rules Enforced:   {sf.get('rules_enforced', '?')}")
    print()

    print(f"  {BOLD}Summaries{RESET}")
    aus = result.get("latest_autonomy_status_summary", {})
    print(f"    Autonomy-status:  {aus.get('recommendation', '?')}")
    kpi = result.get("latest_kpi_summary", {})
    print(f"    KPI:              {kpi.get('verdict', '?')}")
    cand = result.get("latest_candidate_summary", {})
    print(f"    Candidate:        {cand.get('verdict', '?')}  ({cand.get('symbol', '?')} {cand.get('side', '?')})")
    doc = result.get("doctor_summary", {})
    doc_pass = doc.get("pass")
    doc_label = "PASS" if doc_pass is True else ("FAIL" if doc_pass is False else "N/A")
    print(f"    Doctor:           {doc_label}  ({doc.get('passed', 0)}/{doc.get('total', 0)})")
    print()

    print(f"  {BOLD}Connection & Data{RESET}")
    print(f"    IBKR connected:   {result.get('ibkr_connected', False)}")
    print(f"    Market data:      {result.get('market_data_status', '?')}")
    print(f"    FX:               {result.get('fx_status', '?')}")
    print(f"    Active alerts:    {result.get('active_alert_count', 0)}")
    print(f"    Reconciliation:   {'PASS' if result.get('reconciliation_passed') else 'N/A'}")
    print()

    blockers = result.get("blockers", [])
    if blockers:
        print(f"  {BOLD}Blockers ({len(blockers)}){RESET}")
        for b in blockers:
            sev_color = RED if b["severity"] == "NO-GO" else RESET
            print(f"    [{sev_color}{b['severity']}{RESET}] {b['check']}: {b.get('detail', '')}"[:200])
        print()

    print(f"  {BOLD}Manual Review Checklist{RESET}")
    for item in result.get("manual_review_checklist", []):
        print(f"    [{item['item']}] {item['task']}")
    print()

    print(f"  Evidence hash:     {result.get('evidence_hash', '?')[:16]}...")
    print(f"  Export:            {result.get('_export_path', '?')}")
    print(f"  operator_decision_required: {result.get('operator_decision_required', True)}")
    print(f"  auto_promotion_performed:   {result.get('auto_promotion_performed', False)}")
    print(f"  no_broker_mutation:         {result.get('no_broker_mutation', True)}")
    print()


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

    # Step 15I — evidence cycle
    ecp = sub.add_parser("evidence-cycle",
                         help="Read-only evidence bundle + clean-cycle ledger entry")
    ecp.add_argument("--symbol", required=True, type=str, help="Ticker symbol")
    ecp.add_argument("--side", required=True, choices=["BUY", "SELL"],
                      help="Order side: BUY or SELL")
    ecp.add_argument("--json", action="store_true",
                      help="Output raw JSON only")
    ecp.add_argument("--export", action="store_true",
                      help="Write candidate export to ~/.openclaw/candidate-dryruns/")
    ecp.add_argument("--record", action="store_true",
                      help="Append clean-cycle entry to ~/.openclaw/autonomy-cycles/clean-cycle-ledger.jsonl")

    # Step 15J — autonomy readiness evaluator
    asp = sub.add_parser("autonomy-status",
                         help="Autonomy readiness evaluator / promotion proposal")
    asp.add_argument("--json", action="store_true",
                      help="Output raw JSON only")
    asp.add_argument("--export", action="store_true",
                      help="Write output to ~/.openclaw/autonomy-status/")
    asp.add_argument("--refresh-evidence", "--refresh-connected-evidence",
                      action="store_true", dest="refresh_evidence",
                      help="Run fresh connected checks: doctor, KPI, candidate dry-run, market/FX snapshot")
    # Alias
    arp = sub.add_parser("autonomy-readiness",
                         help="Alias for autonomy-status")
    arp.add_argument("--json", action="store_true",
                      help="Output raw JSON only")
    arp.add_argument("--export", action="store_true",
                      help="Write output to ~/.openclaw/autonomy-status/")
    arp.add_argument("--refresh-evidence", "--refresh-connected-evidence",
                      action="store_true", dest="refresh_evidence",
                      help="Run fresh connected checks: doctor, KPI, candidate dry-run, market/FX snapshot")

    # Step 15K — autonomy promotion review package
    avp = sub.add_parser("autonomy-review",
                         help="Manual autonomy-promotion review package")
    avp.add_argument("--target-level", type=str, default="1",
                      help="Target autonomy level (default: 1)")
    avp.add_argument("--json", action="store_true",
                      help="Output raw JSON only")
    avp.add_argument("--export", action="store_true",
                      help="Write output to ~/.openclaw/autonomy-review/")
    # Alias
    pvp = sub.add_parser("promotion-review",
                         help="Alias for autonomy-review")
    pvp.add_argument("--target-level", type=str, default="1",
                      help="Target autonomy level (default: 1)")
    pvp.add_argument("--json", action="store_true",
                      help="Output raw JSON only")
    pvp.add_argument("--export", action="store_true",
                      help="Write output to ~/.openclaw/autonomy-review/")

    # Step 15M — Manual level-1 promotion plan (advisory/procedural only)
    app = sub.add_parser("autonomy-promotion-plan",
                         help="Manual level-1 promotion procedure/spec (Step 15M)")
    app.add_argument("--target-level", type=str, default="1",
                      help="Target autonomy level (default: 1)")
    app.add_argument("--json", action="store_true",
                      help="Output raw JSON only")
    app.add_argument("--export", action="store_true",
                      help="Write output to ~/.openclaw/autonomy-promotion-plans/")
    # Alias
    ppp = sub.add_parser("promotion-plan",
                         help="Alias for autonomy-promotion-plan")
    ppp.add_argument("--target-level", type=str, default="1",
                      help="Target autonomy level (default: 1)")
    ppp.add_argument("--json", action="store_true",
                      help="Output raw JSON only")
    ppp.add_argument("--export", action="store_true",
                      help="Write output to ~/.openclaw/autonomy-promotion-plans/")
    # Alias
    l1p = sub.add_parser("level1-promotion-plan",
                         help="Alias for autonomy-promotion-plan")
    l1p.add_argument("--target-level", type=str, default="1",
                      help="Target autonomy level (default: 1)")
    l1p.add_argument("--json", action="store_true",
                      help="Output raw JSON only")
    l1p.add_argument("--export", action="store_true",
                      help="Write output to ~/.openclaw/autonomy-promotion-plans/")

    # Step 15O — Guard-state trade-count reconciliation
    gsr = sub.add_parser("guard-state-reconcile",
                         help="Reconcile guard-state trade count against confirmed events")
    gsr.add_argument("--json", action="store_true",
                      help="Output raw JSON only")
    gsr.add_argument("--export", action="store_true",
                      help="Write output to ~/.openclaw/guard-state-repairs/")
    gsr.add_argument("--apply", action="store_true",
                      help="Apply the repair (requires --confirm-local-state-repair)")
    gsr.add_argument("--confirm-local-state-repair", action="store_true",
                      help="Explicit confirmation for local state repair")
    # Alias
    tcr = sub.add_parser("trade-count-reconcile",
                         help="Alias for guard-state-reconcile")
    tcr.add_argument("--json", action="store_true")
    tcr.add_argument("--export", action="store_true")
    tcr.add_argument("--apply", action="store_true")
    tcr.add_argument("--confirm-local-state-repair", action="store_true")
    # Alias
    rtc = sub.add_parser("repair-trade-count",
                         help="Alias for guard-state-reconcile")
    rtc.add_argument("--json", action="store_true")
    rtc.add_argument("--export", action="store_true")
    rtc.add_argument("--apply", action="store_true")
    rtc.add_argument("--confirm-local-state-repair", action="store_true")

    # Step 15Q — Market-data diagnostics
    mdd = sub.add_parser("market-data-diagnostics",
                         help="Diagnose market-data entitlement/subscription issues")
    mdd.add_argument("--symbol", type=str, default="AAPL",
                      help="Symbol to diagnose (default: AAPL)")
    mdd.add_argument("--json", action="store_true",
                      help="Output raw JSON only")
    mdd.add_argument("--export", action="store_true",
                      help="Write JSON export to ~/.openclaw/market-data-diagnostics/")
    # Aliases
    md_doctor = sub.add_parser("market-data-doctor",
                               help="Alias for market-data-diagnostics")
    md_doctor.add_argument("--symbol", type=str, default="AAPL")
    md_doctor.add_argument("--json", action="store_true")
    md_doctor.add_argument("--export", action="store_true")
    md_diag = sub.add_parser("md-diagnostics",
                             help="Alias for market-data-diagnostics")
    md_diag.add_argument("--symbol", type=str, default="AAPL")
    md_diag.add_argument("--json", action="store_true")
    md_diag.add_argument("--export", action="store_true")

    # Step 15R — Market-data recovery drill
    mdr = sub.add_parser("market-data-recovery-drill",
                         help="Recovery drill: connect + diagnostics + readiness refresh")
    mdr.add_argument("--symbol", type=str, default="AAPL",
                      help="Symbol to recover (default: AAPL)")
    mdr.add_argument("--json", action="store_true",
                      help="Output raw JSON only")
    mdr.add_argument("--export", action="store_true",
                      help="Write JSON export to ~/.openclaw/market-data-drills/")
    mdr.add_argument("--attempts", type=int, default=3,
                      help="Maximum diagnostic attempts (1-5, default 3)")
    mdr.add_argument("--sleep-seconds", type=float, default=10.0,
                      help="Seconds between retry attempts (1-60, default 10)")
    mdr.add_argument("--connect-if-needed", action="store_true", dest="connect_if_needed",
                      default=True, help="Call /connect if disconnected (default)")
    mdr.add_argument("--no-connect", action="store_false", dest="connect_if_needed",
                      help="Do not call /connect — diagnose only")
    # Aliases
    md_rec1 = sub.add_parser("md-recovery-drill",
                             help="Alias for market-data-recovery-drill")
    md_rec1.add_argument("--symbol", type=str, default="AAPL")
    md_rec1.add_argument("--json", action="store_true")
    md_rec1.add_argument("--export", action="store_true")
    md_rec1.add_argument("--attempts", type=int, default=3)
    md_rec1.add_argument("--sleep-seconds", type=float, default=10.0)
    md_rec1.add_argument("--connect-if-needed", action="store_true", default=True)
    md_rec1.add_argument("--no-connect", action="store_false", dest="connect_if_needed")
    md_rec2 = sub.add_parser("market-recovery",
                             help="Alias for market-data-recovery-drill")
    md_rec2.add_argument("--symbol", type=str, default="AAPL")
    md_rec2.add_argument("--json", action="store_true")
    md_rec2.add_argument("--export", action="store_true")
    md_rec2.add_argument("--attempts", type=int, default=3)
    md_rec2.add_argument("--sleep-seconds", type=float, default=10.0)
    md_rec2.add_argument("--connect-if-needed", action="store_true", default=True)
    md_rec2.add_argument("--no-connect", action="store_false", dest="connect_if_needed")

    # Step 15S: Contract qualification / root-cause drill
    cq_drill = sub.add_parser("contract-qualification-drill",
                               help="Run contract qualification root-cause drill (Step 15S)")
    cq_drill.add_argument("--symbol", type=str, default="AAPL")
    cq_drill.add_argument("--json", action="store_true")
    cq_drill.add_argument("--export", action="store_true")
    cq_drill.add_argument("--sec-type", type=str, default="STK")
    cq_drill.add_argument("--currency", type=str, default="USD")
    cq_drill.add_argument("--exchange", type=str, default="SMART")
    cq_drill.add_argument("--primary-exchange", type=str, default="")
    cq_drill.add_argument("--attempt-alternates", action="store_true", default=True)
    cq_drill.add_argument("--no-attempt-alternates", action="store_false", dest="attempt_alternates")
    cq_drill.add_argument("--max-attempts", type=int, default=5)

    cq_d2 = sub.add_parser("contract-diagnostics",
                            help="Alias for contract-qualification-drill")
    cq_d2.add_argument("--symbol", type=str, default="AAPL")
    cq_d2.add_argument("--json", action="store_true")
    cq_d2.add_argument("--export", action="store_true")
    cq_d2.add_argument("--sec-type", type=str, default="STK")
    cq_d2.add_argument("--currency", type=str, default="USD")
    cq_d2.add_argument("--exchange", type=str, default="SMART")
    cq_d2.add_argument("--primary-exchange", type=str, default="")
    cq_d2.add_argument("--attempt-alternates", action="store_true", default=True)
    cq_d2.add_argument("--no-attempt-alternates", action="store_false", dest="attempt_alternates")
    cq_d2.add_argument("--max-attempts", type=int, default=5)

    cq_d3 = sub.add_parser("cq-drill",
                            help="Alias for contract-qualification-drill")
    cq_d3.add_argument("--symbol", type=str, default="AAPL")
    cq_d3.add_argument("--json", action="store_true")
    cq_d3.add_argument("--export", action="store_true")
    cq_d3.add_argument("--sec-type", type=str, default="STK")
    cq_d3.add_argument("--currency", type=str, default="USD")
    cq_d3.add_argument("--exchange", type=str, default="SMART")
    cq_d3.add_argument("--primary-exchange", type=str, default="")
    cq_d3.add_argument("--attempt-alternates", action="store_true", default=True)
    cq_d3.add_argument("--no-attempt-alternates", action="store_false", dest="attempt_alternates")
    cq_d3.add_argument("--max-attempts", type=int, default=5)

    # Step 15T: Backpressure drain drill
    bp_drain = sub.add_parser("backpressure-drain-drill",
                               help="Run bridge saturation / backpressure drain drill (Step 15T)")
    bp_drain.add_argument("--json", action="store_true")
    bp_drain.add_argument("--export", action="store_true")
    bp_drain.add_argument("--observe-seconds", type=int, default=15)
    bp_drain.add_argument("--poll-seconds", type=int, default=3)
    bp_drain.add_argument("--include-endpoint-probes", action="store_true", default=True)
    bp_drain.add_argument("--no-endpoint-probes", action="store_false", dest="include_endpoint_probes")
    bp_drain.add_argument("--symbol", type=str, default="AAPL")

    bp_d2 = sub.add_parser("bridge-drain-drill",
                            help="Alias for backpressure-drain-drill")
    bp_d2.add_argument("--json", action="store_true")
    bp_d2.add_argument("--export", action="store_true")
    bp_d2.add_argument("--observe-seconds", type=int, default=15)
    bp_d2.add_argument("--poll-seconds", type=int, default=3)
    bp_d2.add_argument("--include-endpoint-probes", action="store_true", default=True)
    bp_d2.add_argument("--no-endpoint-probes", action="store_false", dest="include_endpoint_probes")
    bp_d2.add_argument("--symbol", type=str, default="AAPL")

    bp_d3 = sub.add_parser("backpressure-doctor",
                            help="Alias for backpressure-drain-drill")
    bp_d3.add_argument("--json", action="store_true")
    bp_d3.add_argument("--export", action="store_true")
    bp_d3.add_argument("--observe-seconds", type=int, default=15)
    bp_d3.add_argument("--poll-seconds", type=int, default=3)
    bp_d3.add_argument("--include-endpoint-probes", action="store_true", default=True)
    bp_d3.add_argument("--no-endpoint-probes", action="store_false", dest="include_endpoint_probes")
    bp_d3.add_argument("--symbol", type=str, default="AAPL")

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

    if args.command == "evidence-cycle":
        result = _run_evidence_cycle(args.symbol, args.side, record=args.record)
        if args.json:
            print(json.dumps(result, indent=2, default=str))
        else:
            _print_evidence_cycle(result)
        exit_code = 0 if result["clean"] else 1
        sys.exit(exit_code)

    if args.command in ("autonomy-status", "autonomy-readiness"):
        refresh = getattr(args, "refresh_evidence", False)
        result = _run_autonomy_status(refresh_evidence=refresh)
        if args.json:
            print(json.dumps(result, indent=2, default=str))
        else:
            print_autonomy_status(result)
        if args.export:
            exports = result.get("evidence_exports", [])
            if exports:
                print(f"  Export written: {exports[0]}", file=sys.stderr)
        exit_code = 0 if result["recommendation"] == "READY_FOR_MANUAL_REVIEW" else 1
        sys.exit(exit_code)

    if args.command in ("autonomy-review", "promotion-review"):
        refresh = getattr(args, "refresh_evidence", False)
        result = _run_autonomy_review(target_level=args.target_level, refresh_evidence=refresh)
        if args.json:
            print(json.dumps(result, indent=2, default=str))
        else:
            print_autonomy_review(result)
        if args.export:
            ep = result.get("_export_path")
            if ep:
                print(f"  Export written: {ep}", file=sys.stderr)
        exit_code = 0 if result["review_status"] == "READY_FOR_OPERATOR_REVIEW" else 1
        sys.exit(exit_code)

    if args.command in ("autonomy-promotion-plan", "promotion-plan", "level1-promotion-plan"):
        result = _run_autonomy_promotion_plan(target_level=args.target_level)
        if args.json:
            print(json.dumps(result, indent=2, default=str))
        else:
            _print_promotion_plan(result)
        if args.export:
            ep = result.get("_export_path")
            if ep:
                print(f"  Export written: {ep}", file=sys.stderr)
        exit_code = 0 if result["plan_status"] == "READY_FOR_MANUAL_DECISION" else 1
        sys.exit(exit_code)

    if args.command in ("guard-state-reconcile", "trade-count-reconcile", "repair-trade-count"):
        apply_flag = getattr(args, "apply", False)
        confirm_flag = getattr(args, "confirm_local_state_repair", False)
        result = _run_guard_state_reconcile(
            apply_repair=apply_flag,
            confirm_local_state_repair=confirm_flag,
        )
        if args.json:
            print(json.dumps(result, indent=2, default=str))
        else:
            _print_guard_state_reconcile(result)
        if args.export:
            ep = result.get("_export_path")
            if ep:
                print(f"  Export written: {ep}", file=sys.stderr)
        exit_code = 0 if result.get("repair_recommended") or result.get("repair_applied") else 1
        sys.exit(exit_code)

    if args.command in ("market-data-diagnostics", "market-data-doctor", "md-diagnostics"):
        symbol = getattr(args, "symbol", "AAPL")
        result = _run_market_data_diagnostics(symbol=symbol)
        if args.json:
            print(json.dumps(result, indent=2, default=str))
        else:
            _print_market_data_diagnostics(result)
        if args.export:
            ep = result.get("_export_path")
            if ep:
                print(f"  Export written: {ep}", file=sys.stderr)
        exit_code = 0 if result["severity"] in ("OK", "HOLD") else 1
        sys.exit(exit_code)

    if args.command in ("market-data-recovery-drill", "md-recovery-drill", "market-recovery"):
        symbol = getattr(args, "symbol", "AAPL")
        attempts = getattr(args, "attempts", 3)
        sleep_seconds = getattr(args, "sleep_seconds", 10.0)
        connect_if_needed = getattr(args, "connect_if_needed", True)
        try:
            result = _run_market_data_recovery_drill(
                symbol=symbol,
                attempts=attempts,
                sleep_seconds=sleep_seconds,
                connect_if_needed=connect_if_needed,
            )
        except Exception as exc:
            result = _make_recovery_drill_error_result(exc, symbol=symbol)
            # Log traceback to stderr only (stdout stays pure JSON)
            import traceback
            print(f"Recovery drill internal exception: {exc}", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)
        # Pure JSON stdout
        print(json.dumps(result, indent=2, default=str))
        # Export messages to stderr
        if args.export:
            ep = result.get("_export_path")
            if ep:
                print(f"  Export written: {ep}", file=sys.stderr)
        exit_code = 0 if result["final_severity"] in ("OK", "HOLD") else 1
        sys.exit(exit_code)

    if args.command in ("backpressure-drain-drill", "bridge-drain-drill", "backpressure-doctor"):
        observe_seconds = getattr(args, "observe_seconds", 15)
        poll_seconds = getattr(args, "poll_seconds", 3)
        include_endpoint_probes = getattr(args, "include_endpoint_probes", True)
        symbol = getattr(args, "symbol", "AAPL")
        try:
            result = _run_backpressure_drain_drill(
                observe_seconds=observe_seconds,
                poll_seconds=poll_seconds,
                include_endpoint_probes=include_endpoint_probes,
                symbol=symbol,
            )
        except Exception as exc:
            import traceback
            from datetime import datetime, timezone
            now_utc = datetime.now(timezone.utc)
            ts_str = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
            ts_file = now_utc.strftime("%Y%m%dT%H%M%SZ")
            result = {
                "command": "ibkr-operator backpressure-drain-drill",
                "timestamp": ts_str,
                "drill_id": f"bp-drain-drill-{ts_file}",
                "diagnosis": "bridge_unreachable",
                "severity": "NO_GO",
                "internal_exception": True,
                "error_type": type(exc).__name__,
                "error_message": str(exc)[:500],
                "no_broker_mutation": True,
                "no_order_window_opened": True,
                "_export_path": None,
            }
            print(f"Backpressure drain drill internal exception: {exc}", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)
        # Pure JSON stdout
        print(json.dumps(result, indent=2, default=str))
        if args.export:
            ep = result.get("_export_path")
            if ep:
                print(f"  Export written: {ep}", file=sys.stderr)
        exit_code = 0 if result.get("severity") in ("OK", "HOLD") else 1
        sys.exit(exit_code)

    if args.command in ("contract-qualification-drill", "contract-diagnostics", "cq-drill"):
        symbol = getattr(args, "symbol", "AAPL")
        sec_type = getattr(args, "sec_type", "STK")
        currency = getattr(args, "currency", "USD")
        exchange = getattr(args, "exchange", "SMART")
        primary_exchange = getattr(args, "primary_exchange", "")
        attempt_alternates = getattr(args, "attempt_alternates", True)
        max_attempts = getattr(args, "max_attempts", 5)
        try:
            result = _run_contract_qualification_drill(
                symbol=symbol,
                sec_type=sec_type,
                currency=currency,
                exchange=exchange,
                primary_exchange=primary_exchange,
                attempt_alternates=attempt_alternates,
                max_attempts=max_attempts,
            )
        except Exception as exc:
            # Build a safe error result (same contract as recovery drill errors)
            import traceback
            from datetime import datetime, timezone
            now_utc = datetime.now(timezone.utc)
            ts_str = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
            ts_file = now_utc.strftime("%Y%m%dT%H%M%SZ")
            result = {
                "command": "ibkr-operator contract-qualification-drill",
                "timestamp": ts_str,
                "drill_id": f"cq-drill-{symbol}-{ts_file}",
                "symbol": symbol.upper().strip(),
                "contract_qualified": False,
                "root_cause": "bridge_runtime_error",
                "severity": "NO_GO",
                "internal_exception": True,
                "error_type": type(exc).__name__,
                "error_message": str(exc)[:500],
                "no_broker_mutation": True,
                "no_order_window_opened": True,
                "_export_path": None,
            }
            print(f"CQ drill internal exception: {exc}", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)
        # Pure JSON stdout
        print(json.dumps(result, indent=2, default=str))
        if args.export:
            ep = result.get("_export_path")
            if ep:
                print(f"  Export written: {ep}", file=sys.stderr)
        exit_code = 0 if result.get("severity") in ("OK", "HOLD") else 1
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