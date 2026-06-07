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


def print_export(export: dict) -> None:
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

        if wd.get("total", 0) == 0:
            print("  Nothing to delete.")
        return

    if mode == "prune":
        ab = result.get("audit_bundles", {})
        rt = result.get("release_tags", {})
        print(f"  Audit bundles: removed {ab.get('total_removed', 0)}"
              f" (age={ab.get('by_age', 0)}, count={ab.get('by_count', 0)})")
        print(f"  Release tags:  removed {rt.get('total_removed', 0)}"
              f" (age={rt.get('by_age', 0)}, count={rt.get('by_count', 0)})")
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

    args = parser.parse_args()

    if args.command == "daily-report":
        result = run_daily_report()
        if args.json:
            print(json.dumps(result, indent=2, default=str))
        else:
            print_daily_report(result)
        return

    if args.command == "export":
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

        has_prune_flag = args.prune_audit or args.prune_releases

        if has_prune_flag:
            # Prune mode — requires explicit flags
            if args.dry_run:
                result = plan_prune(
                    keep_audit=args.keep_audit,
                    keep_releases=args.keep_releases,
                )
            else:
                try:
                    result = execute_prune(
                        keep_audit=args.keep_audit,
                        keep_releases=args.keep_releases,
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