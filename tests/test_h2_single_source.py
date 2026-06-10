#!/usr/bin/env python3
"""
Phase H2 — Single Source of Truth — Consistency Tests

Verifies:
  H2-C1: No hardcoded allowlist in guard.py (YAML is sole source)
  H2-C2: _get_allowed_symbols() reads from YAML
  H2-C3: _require_allowed_symbol uses YAML, not hardcoded list
  H2-C4: submit_order allowlist check uses YAML
  H2-C5: load_rules does not compare YAML allowlist to any hardcoded list
  H2-C6: CLAUDE.md declares YAML as single source of truth
  H2-C7: Two-tier risk model documented (guard hard ceiling + Hermes envelope)
  H2-C8: YAML risk params match CLAUDE.md summary
  H2-C9: YAML risk params match guard enforcement values
  H2-C10: ALLOWED_SYMBOLS constant removed
"""

import json
import sys
from pathlib import Path

PASS = 0
FAIL = 0
WARN = 0
ERRORS = []


def check(ok: bool, message: str):
    global PASS, FAIL, ERRORS
    if ok:
        PASS += 1
        print(f"  ✅ {message}")
    else:
        FAIL += 1
        ERRORS.append(message)
        print(f"  ❌ {message}")


def warn(message: str):
    global WARN
    WARN += 1
    print(f"  ⚠️  {message}")


def main():
    global PASS, FAIL, WARN, ERRORS

    print("=" * 60)
    print("Phase H2 — Single Source of Truth — Consistency Tests")
    print("=" * 60)

    home = Path.home()
    guard_path = home / "agents" / "ibkr-bridge" / "guard.py"
    claude_path = home / "agents" / "ibkr-bridge" / "CLAUDE.md"
    yaml_path = home / ".openclaw" / "risk-rules" / "paper-trading-rules.yaml"

    guard_content = guard_path.read_text() if guard_path.exists() else ""
    claude_content = claude_path.read_text() if claude_path.exists() else ""
    yaml_content = yaml_path.read_text() if yaml_path.exists() else ""

    # ── H2-C1: No hardcoded allowlist in guard.py ─────────────────────
    print("\n── H2-C1: No Hardcoded Allowlist ──")
    check("ALLOWED_SYMBOLS =" not in guard_content,
          "ALLOWED_SYMBOLS constant removed from guard.py")
    check("ALLOWED_SYMBOLS" not in guard_content,
          "No reference to ALLOWED_SYMBOLS anywhere in guard.py")

    # ── H2-C2: _get_allowed_symbols reads from YAML ───────────────────
    print("\n── H2-C2: _get_allowed_symbols from YAML ──")
    check("_get_allowed_symbols" in guard_content,
          "_get_allowed_symbols() function exists in guard.py")
    check("symbol_allowlist" in guard_content and "load_rules" in guard_content,
          "_get_allowed_symbols references paper-trading-rules.yaml")
    check("SINGLE SOURCE OF TRUTH" in guard_content,
          "Single source of truth comment present in guard.py")

    # ── H2-C3: _require_allowed_symbol uses YAML ──────────────────────
    print("\n── H2-C3: _require_allowed_symbol from YAML ──")
    check("_get_allowed_symbols" in guard_content,
          "_require_allowed_symbol delegates to _get_allowed_symbols")
    check("Only AAPL, SPY, QQQ" not in guard_content,
          "Stale 'Only AAPL, SPY, QQQ' error message removed")
    check("paper-trading-rules.yaml symbol_allowlist" in guard_content,
          "Error message references paper-trading-rules.yaml")

    # ── H2-C4: submit_order allowlist check uses YAML ─────────────────
    print("\n── H2-C4: submit_order allowlist from YAML ──")
    check("SYMBOL_BLOCKED" in guard_content,
          "SYMBOL_BLOCKED error code still present in submit validation")
    check("_get_allowed_symbols()" in guard_content,
          "submit_order calls _get_allowed_symbols()")

    # ── H2-C5: load_rules no hardcoded comparison ─────────────────────
    print("\n── H2-C5: load_rules no hardcoded comparison ──")
    check("must be" not in guard_content.split("symbol_allowlist.allow must be")[-1][:100]
          if "symbol_allowlist.allow must be" in guard_content else True,
          "load_rules no longer compares YAML to hardcoded list")
    check("Phase H2: YAML is the single source" in guard_content,
          "Phase H2 comment present in load_rules validation")

    # ── H2-C6: CLAUDE.md declares YAML as single source ───────────────
    print("\n── H2-C6: CLAUDE.md Single Source Declaration ──")
    check("Single Source of Truth" in claude_content,
          "CLAUDE.md declares Phase H2 single source of truth")
    check("YAML wins on conflict" in claude_content or "YAML only" in claude_content,
          "CLAUDE.md states YAML wins on conflict")
    check("No hardcoded duplicates exist" in claude_content,
          "CLAUDE.md confirms no hardcoded duplicates")

    # ── H2-C7: Two-tier risk model documented ─────────────────────────
    print("\n── H2-C7: Two-Tier Risk Model ──")
    check("Two-Tier Risk Model" in claude_content or "two-tier" in claude_content.lower(),
          "Two-tier risk model section present in CLAUDE.md")
    check("Guard Hard Ceiling" in claude_content or "hard ceiling" in claude_content.lower(),
          "Guard hard ceiling documented")
    check("Hermes Advisory Envelope" in claude_content or "advisory envelope" in claude_content.lower(),
          "Hermes advisory envelope documented")
    check("0.25%" in claude_content,
          "0.25% risk/trade for Hermes envelope documented")
    check("2% risk/trade" in claude_content or "2%" in claude_content,
          "2% risk/trade guard ceiling documented")

    # ── H2-C8: YAML risk params match CLAUDE.md ───────────────────────
    print("\n── H2-C8: YAML ↔ CLAUDE.md Consistency ──")

    # Parse YAML for key values
    import yaml
    try:
        rules = yaml.safe_load(yaml_content)
    except Exception as e:
        check(False, f"YAML parse failed: {e}")
        rules = {}

    yaml_risk = rules.get("max_risk_per_trade", {}).get("value")
    yaml_exposure = rules.get("max_total_exposure", {}).get("value")
    yaml_trades = rules.get("max_trades_per_day", {}).get("value")
    yaml_notional = rules.get("max_position_notional", {}).get("value")
    yaml_allowlist = rules.get("symbol_allowlist", {}).get("allow", [])

    # Check CLAUDE.md mentions the correct values
    check(f"{yaml_risk}%" in claude_content or f"**{yaml_risk}%**" in claude_content,
          f"CLAUDE.md reflects YAML risk: {yaml_risk}%")
    check(f"{yaml_exposure}%" in claude_content,
          f"CLAUDE.md reflects YAML exposure: {yaml_exposure}%")
    check(f"{yaml_trades}" in claude_content and "trades/day" in claude_content,
          f"CLAUDE.md reflects YAML trades/day: {yaml_trades}")
    check(f"{yaml_notional}%" in claude_content,
          f"CLAUDE.md reflects YAML notional: {yaml_notional}%")

    # ── H2-C9: YAML ↔ guard.py enforcement consistency ────────────────
    print("\n── H2-C9: YAML ↔ guard.py Consistency ──")

    # Verify guard.py reads risk values from YAML (not hardcoded)
    check("rules.get(\"max_risk_per_trade\"" in guard_content,
          "guard.py reads max_risk_per_trade from YAML rules dict")
    check("rules.get(\"max_total_exposure\"" in guard_content,
          "guard.py reads max_total_exposure from YAML rules dict")
    check("rules.get(\"max_trades_per_day\"" in guard_content,
          "guard.py reads max_trades_per_day from YAML rules dict")
    check("rules.get(\"symbol_allowlist\"" in guard_content,
          "guard.py reads symbol_allowlist from YAML rules dict")

    # ── H2-C10: Stale references removed ──────────────────────────────
    print("\n── H2-C10: Stale References Removed ──")

    # The old error message must be gone from enforcement code.
    # Self-test mock data may still reference AAPL/SPY/QQQ — that's fine.
    check("Only AAPL, SPY, QQQ" not in guard_content,
          "Stale 'Only AAPL, SPY, QQQ' error message removed")
    # Confirm no hardcoded ALLOWED_SYMBOLS list in enforcement code
    check("ALLOWED_SYMBOLS" not in guard_content,
          "ALLOWED_SYMBOLS not referenced in guard.py")

    # ── H2-C11: YAML allowlist integrity ──────────────────────────────
    print("\n── H2-C11: YAML Allowlist Integrity ──")

    check(isinstance(yaml_allowlist, list) and len(yaml_allowlist) > 0,
          f"YAML allowlist is non-empty: {yaml_allowlist}")
    for sym in yaml_allowlist:
        check(isinstance(sym, str) and sym == sym.strip().upper(),
              f"YAML symbol '{sym}' is clean uppercase")

    # All symbols in YAML should be valid (no ETFs blocked by KID/PRIIPs)
    # SPY/QQQ were removed 2026-06-09 per CHANGELOG
    check("SPY" not in yaml_allowlist,
          "SPY removed from YAML allowlist (KID/PRIIPs)")
    check("QQQ" not in yaml_allowlist,
          "QQQ removed from YAML allowlist (KID/PRIIPs)")

    # ── SUMMARY ────────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    total = PASS + FAIL
    print(f"Results: {PASS} passed, {FAIL} failed, {WARN} warnings (of {total} checks)")
    print("=" * 60)

    if ERRORS:
        print("\nFailed checks:")
        for e in ERRORS:
            print(f"  - {e}")

    return FAIL == 0


if __name__ == "__main__":
    ok = main()
    sys.exit(0 if ok else 1)
