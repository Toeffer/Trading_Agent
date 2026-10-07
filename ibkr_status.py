#!/usr/bin/env python3
"""
ibkr_status.py — Phase 3Q Status CLI Wrapper

Read-only. No trading. No automation.

Prints a summary of system state: phase/tag, commit, locked baseline,
readiness, startup safety, drift, open orders, regression count.

Calls the bridge /status endpoint when available (port 8790).
Falls back to reading local files when bridge is down.
"""

import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HOME = Path.home()
OPENCLAW_DIR = HOME / ".openclaw"
BRIDGE_DIR = HOME / "agents" / "ibkr-bridge"
BRIDGE_URL = os.environ.get("IBKR_BRIDGE_URL", "http://127.0.0.1:8790")

AUDIT_DIR = OPENCLAW_DIR / "audit-bundles"
RELEASE_DIR = OPENCLAW_DIR / "releases"


# ---------------------------------------------------------------------------
# Bridge fetcher
# ---------------------------------------------------------------------------

def _fetch(endpoint: str) -> tuple[int, Any]:
    """Fetch a bridge endpoint. Returns (status_code, data)."""
    url = f"{BRIDGE_URL}{endpoint}"
    try:
        r = urllib.request.urlopen(url, timeout=5)
        return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, {}
    except Exception as e:
        return 0, {"_error": str(e)}


# ---------------------------------------------------------------------------
# Fallback: local file readers
# ---------------------------------------------------------------------------

def _latest_bundle() -> dict | None:
    """Read the latest audit bundle from disk."""
    if not AUDIT_DIR.exists():
        return None
    bundles = sorted(AUDIT_DIR.glob("bundle_*.json"), reverse=True)
    if not bundles:
        return None
    try:
        return json.loads(bundles[0].read_text())
    except (json.JSONDecodeError, OSError):
        return None


def _latest_release() -> dict | None:
    """Read the latest release tag from disk."""
    if not RELEASE_DIR.exists():
        return None
    tags = sorted(RELEASE_DIR.glob("release_*.json"), reverse=True)
    if not tags:
        return None
    try:
        return json.loads(tags[0].read_text())
    except (json.JSONDecodeError, OSError):
        return None


def _git_info() -> tuple[str | None, str | None]:
    """Get git commit and tag. Returns (commit, tag)."""
    if not (BRIDGE_DIR / ".git").exists():
        return None, None
    try:
        gc = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True, cwd=BRIDGE_DIR, timeout=5,
        )
        commit = gc.stdout.strip() if gc.returncode == 0 else None
        gt = subprocess.run(
            ["git", "describe", "--tags", "--abbrev=0"],
            capture_output=True, text=True, cwd=BRIDGE_DIR, timeout=5,
        )
        tag = gt.stdout.strip() if gt.returncode == 0 else None
        return commit, tag
    except Exception:
        return None, None


def _guard_state() -> dict:
    """Read guard-state.json (safe default on error)."""
    p = OPENCLAW_DIR / "guard-state.json"
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def _counter_from_events() -> int:
    """Count submitted orders from guard-events.jsonl (rough trade count)."""
    p = OPENCLAW_DIR / "guard-events.jsonl"
    if not p.exists():
        return 0
    count = 0
    try:
        for line in p.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
                if ev.get("event_type") == "order_submitted":
                    count += 1
            except json.JSONDecodeError:
                pass
        return count
    except OSError:
        return 0


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------

GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
CYAN = "\033[96m"
BOLD = "\033[1m"
RESET = "\033[0m"


def _color(val: Any, ok_vals=(True, "ok", "GO", "PASS", "clean", False),
           warn_vals=("warn", "ok_with_warnings", "NO-GO (scheduling)")) -> str:
    """Return color-wrapped string: green for ok_vals, yellow for warn, red otherwise."""
    s = str(val) if val is not None else "—"
    if val in ok_vals:
        return f"{GREEN}{s}{RESET}"
    if val in warn_vals:
        return f"{YELLOW}{s}{RESET}"
    if val is False or val == "error" or val is None or s == "—":
        return f"{RED}{s}{RESET}"
    return f"{CYAN}{s}{RESET}"


def _bool_color(val: bool | None) -> str:
    if val is True:
        return f"{GREEN}✓{RESET}"
    if val is False:
        return f"{RED}✗{RESET}"
    return f"{YELLOW}?{RESET}"


# ---------------------------------------------------------------------------
# Main: print status
# ---------------------------------------------------------------------------

def print_status() -> None:
    # Try bridge first
    code, data = _fetch("/status")

    if code == 200 and isinstance(data, dict):
        # Bridge mode
        d = data
        overall = data.get("status", "?")
        h = d.get("health", {})
        rdy = d.get("readiness", {})
        git = d.get("git", {})
        ab = d.get("audit_bundle", {})
        rt = d.get("release_tag", {})
        mon = d.get("monitoring", {})

        commit = git.get("commit", "")
        commit_short = commit[:16] if commit else "—"
        tag = git.get("tag", "—")

        ss = h.get("startup_safety", {})
        ss_str = f"{ss.get('passed_count', '?')}/{ss.get('check_count', '?')}" if ss else "—"

        drift = mon.get("drift", {})
        oo = mon.get("open_orders", {})
        pos = mon.get("positions", {})

        reg_str = ab.get("regression", "—") if ab else "—"
        rt_str = rt.get("tag_id", "—") if rt else "—"
        rt_phase = rt.get("phase_label", "") if rt else ""

        regimen = rt_phase.replace("_", " ").title() if rt_phase else ""
        if not regimen and tag and tag != "—":
            regimen = tag.replace("_", " ").title()

    else:
        # Fallback: local files (bridge down)
        overall = "fallback"
        commit, tag = _git_info()
        commit_short = commit[:16] if commit else "—"
        tag = tag or "—"

        ss_str = "—"

        # Readiness from guard-state
        gs = _guard_state()
        halt_active = gs.get("daily_halt_active", False) or gs.get("weekly_halt_active", False)
        verdict = "NO-GO" if halt_active else "UNKNOWN (bridge down)"
        locked = not halt_active if gs else None

        # Regression from latest bundle
        bundle = _latest_bundle()
        reg = bundle.get("regression", {}) if bundle else {}
        reg_str = f"{reg.get('passed', '?')}/{reg.get('total', '?')}" if reg else "—"

        # Release tag
        release = _latest_release()
        rt_str = release.get("tag_id", "—") if release else "—"
        rt_phase = release.get("phase_label", "") if release else ""

        regimen = rt_phase.replace("_", " ").title() if rt_phase else ""
        if not regimen and tag and tag != "—":
            regimen = tag.replace("_", " ").title()

        # Drift, open orders from file monitors
        try:
            sys.path.insert(0, str(BRIDGE_DIR))
            from monitor import position_drift_check, open_orders_check
            drift_data = position_drift_check()
            drift = {"status": "ok", "expected_positions": len(drift_data.get("expected_positions", {})),
                     "symbols": drift_data.get("symbols", [])}
        except Exception:
            drift = {"status": "error"}
        try:
            from monitor import open_orders_check
            oo_data = open_orders_check()
            oo = {"status": "ok", "open_count": oo_data.get("open_count", 0)}
        except Exception:
            oo = {"status": "error"}

        # Trade count from events
        trade_count = _counter_from_events()

        # Build fallback readiness section
        rdy = {"verdict": verdict, "system_locked": locked,
               "allow_orders": None, "ibkr_connected": False,
               "block_count": 0, "warn_count": 0}

        mon = {"drift": drift, "open_orders": oo, "positions": {"status": "warn", "detail": "bridge down"}}

        ab = {"bundle_id": bundle.get("bundle_id") if bundle else None, "regression": reg_str}
        rt = {"tag_id": rt_str, "phase_label": rt_phase}

    # Build the display
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    mode_str = "FALLBACK (bridge down)" if overall == "fallback" else h.get("mode", "?").upper()
    verdict_str = rdy.get("verdict", "?") or "?"
    system_locked = rdy.get("system_locked")

    print(f"{BOLD}╔══════════════════════════════════════════╗{RESET}")
    print(f"{BOLD}║      IBKR Bridge Status Dashboard       ║{RESET}")
    print(f"{BOLD}╚══════════════════════════════════════════╝{RESET}")
    print(f"  Time:       {now}")
    print(f"  Mode:       {_color(mode_str, ok_vals=('PAPER',), warn_vals=('FALLBACK (bridge down)',))}")
    print(f"  Status:     {_color(overall)}")
    print()
    print(f"{BOLD}Provenance{RESET}")
    print(f"  Tag:        {tag}")
    print(f"  Commit:     {commit_short}")
    print(f"  Regimen:    {regimen or '—'}")
    print()
    print(f"{BOLD}Safety{RESET}")
    print(f"  Verdict:    {_color(verdict_str)}")
    print(f"  Locked:     {_bool_color(system_locked)}  {f'system_locked={system_locked}' if system_locked is not None else ''}")
    print(f"  Allow Ord:  {_bool_color(rdy.get('allow_orders'))}")
    print(f"  Startup:    {_color(ss_str, ok_vals=('10/10',))}")
    print(f"  IBKR:       {_bool_color(rdy.get('ibkr_connected'))}")
    print()
    print(f"{BOLD}Monitoring{RESET}")
    print(f"  Drift:      {_color(drift.get('status', '?'))}  {drift.get('expected_positions', '?')} positions expected")
    print(f"  Open Ord:   {_color(oo.get('status', '?'))}  {oo.get('open_count', '?')} open")
    print(f"  Positions:  {_color(mon.get('positions', {}).get('status', '?'))}  {mon.get('positions', {}).get('detail', '')}")
    print()
    print(f"{BOLD}Audit{RESET}")
    print(f"  Regression: {reg_str}")
    print(f"  Bundle:     {_color(ab.get('bundle_id', '—') if ab else '—')}")
    print(f"  Release:    {rt_str}")
    print()
    print(f"{BOLD}Advisory{RESET}")
    print(f"  No trading. No order automation.")

    # Source indicator
    if overall == "fallback":
        print(f"  {YELLOW}[fallback mode — bridge unreachable at {BRIDGE_URL}]{RESET}")
    else:
        print(f"  [bridge at {BRIDGE_URL}]")

    print()
    print(f"{BOLD}Model Policy{RESET}")
    print(f"  Model:      openrouter/deepseek/deepseek-v4-flash")
    print(f"  Tier:       1 (Strong)")
    print(f"  Policy:     ~/.openclaw/memory/model-routing-safety-policy.md")
    print(f"  Rules:      Tier 1 req for bridge/guard/monitor safety edits",
          f"\n              Tier 2 ok for docs/formatting/read-only")


def main() -> None:
    try:
        print_status()
    except KeyboardInterrupt:
        sys.exit(0)
    except Exception as e:
        print(f"Error: {type(e).__name__}: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()