#!/usr/bin/env python3
"""
Phase H2.1 — YAML Allowlist Live Mutation Test

Proves that paper-trading-rules.yaml is the single source of truth
for the symbol allowlist — no hardcoded duplicates, no stale symbols.

Test flow:
  1. Read current YAML allowlist.
  2. Save original YAML content.
  3. Confirm guard.py _get_allowed_symbols() returns the YAML list.
  4. Add a temporary test symbol "H2TEST" to the YAML allowlist.
  5. Confirm guard.py now includes "H2TEST".
  6. Remove "H2TEST" from YAML, restore original.
  7. Confirm guard.py no longer includes "H2TEST".
  8. Confirm SPY/QQQ are NOT in the allowlist (stale symbols rejected).
  9. Confirm no hardcoded ALLOWED_SYMBOLS remains in guard.py source.
"""

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

PASS = 0
FAIL = 0
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


def main():
    global PASS, FAIL, ERRORS

    print("=" * 60)
    print("Phase H2.1 — YAML Allowlist Live Mutation Test")
    print("=" * 60)

    home = Path.home()
    yaml_path = home / ".openclaw" / "risk-rules" / "paper-trading-rules.yaml"
    guard_path = home / "agents" / "ibkr-bridge" / "guard.py"

    # ── Step 0: Verify preconditions ──────────────────────────────────
    print("\n── Step 0: Preconditions ──")
    check(yaml_path.exists(), f"YAML rules file exists: {yaml_path}")
    check(guard_path.exists(), f"guard.py exists: {guard_path}")

    # Save original YAML
    original_yaml = yaml_path.read_text()
    original_backup = yaml_path.read_text()  # double-safe

    # ── Step 1: Read current allowlist from YAML ───────────────────────
    print("\n── Step 1: Current YAML Allowlist ──")
    import yaml
    rules = yaml.safe_load(original_yaml)
    current_allowlist = rules.get("symbol_allowlist", {}).get("allow", [])
    check(isinstance(current_allowlist, list) and len(current_allowlist) > 0,
          f"YAML allowlist is non-empty: {current_allowlist}")
    for sym in current_allowlist:
        check(isinstance(sym, str) and sym == sym.strip().upper(),
              f"YAML symbol '{sym}' is clean uppercase")

    # ── Step 2: guard.py uses YAML-derived list ────────────────────────
    print("\n── Step 2: guard.py Uses YAML-Derived List ──")
    sys.path.insert(0, str(home / "agents" / "ibkr-bridge"))
    from guard import _get_allowed_symbols

    guard_symbols = _get_allowed_symbols()
    check(set(guard_symbols) == set(current_allowlist),
          f"guard.py allowlist matches YAML: {sorted(guard_symbols)} == {sorted(current_allowlist)}")

    # ── Step 3: No hardcoded ALLOWED_SYMBOLS ───────────────────────────
    print("\n── Step 3: No Hardcoded ALLOWED_SYMBOLS ──")
    guard_content = guard_path.read_text()
    check("ALLOWED_SYMBOLS" not in guard_content,
          "ALLOWED_SYMBOLS not present in guard.py source")

    # ── Step 4: SPY/QQQ rejected (stale symbols) ───────────────────────
    print("\n── Step 4: Stale Symbols Rejected ──")
    from guard import _require_allowed_symbol
    stale_symbols = ["SPY", "QQQ"]
    for stale in stale_symbols:
        try:
            _require_allowed_symbol(stale)
            check(False, f"Stale symbol '{stale}' should be REJECTED but was accepted")
        except ValueError as e:
            check(stale not in guard_symbols,
                  f"Stale symbol '{stale}' correctly rejected: {str(e)[:80]}")

    # ── Step 5: Live YAML mutation — add H2TEST ────────────────────────
    print("\n── Step 5: Live YAML Mutation — Add H2TEST ──")
    test_symbol = "H2TEST"
    try:
        # Modify YAML in place to add test symbol
        import yaml as yaml_lib
        modified_rules = yaml_lib.safe_load(original_yaml)
        modified_rules["symbol_allowlist"]["allow"].append(test_symbol)

        # Write modified YAML
        with open(yaml_path, "w") as f:
            yaml_lib.dump(modified_rules, f, default_flow_style=False, sort_keys=False)

        # Re-verify contents were written
        written_rules = yaml_lib.safe_load(yaml_path.read_text())
        written_allowlist = written_rules.get("symbol_allowlist", {}).get("allow", [])
        check(test_symbol in written_allowlist,
              f"H2TEST successfully added to YAML: {written_allowlist}")

        # Now verify guard.py picks it up (must re-import or re-read)
        # _get_allowed_symbols reads fresh from disk via load_rules()
        fresh_symbols = _get_allowed_symbols()
        check(test_symbol in fresh_symbols,
              f"guard.py now includes H2TEST: {sorted(fresh_symbols)}")

        # _require_allowed_symbol should accept H2TEST
        try:
            result = _require_allowed_symbol(test_symbol)
            check(result == test_symbol,
                  f"_require_allowed_symbol('H2TEST') returned '{result}'")
        except ValueError as e:
            check(False, f"_require_allowed_symbol should accept H2TEST but rejected: {e}")

    finally:
        # ── Step 6: Restore original YAML ─────────────────────────────
        print("\n── Step 6: Restore Original YAML ──")
        yaml_path.write_text(original_yaml)
        restored_rules = yaml_lib.safe_load(yaml_path.read_text())
        restored_allowlist = restored_rules.get("symbol_allowlist", {}).get("allow", [])
        check(test_symbol not in restored_allowlist,
              f"H2TEST removed from YAML: {restored_allowlist}")
        check(restored_allowlist == current_allowlist,
              f"YAML restored to original: {restored_allowlist} == {current_allowlist}")

    # ── Step 7: guard.py reflects restoration ──────────────────────────
    print("\n── Step 7: guard.py Reflects Restoration ──")
    final_symbols = _get_allowed_symbols()
    check(test_symbol not in final_symbols,
          f"guard.py no longer includes H2TEST: {sorted(final_symbols)}")
    check(set(final_symbols) == set(current_allowlist),
          f"guard.py fully restored: {sorted(final_symbols)} == {sorted(current_allowlist)}")

    # ── Step 8: H2TEST now rejected again ──────────────────────────────
    print("\n── Step 8: H2TEST Rejected After Restoration ──")
    try:
        _require_allowed_symbol(test_symbol)
        check(False, "H2TEST should be rejected after YAML restoration")
    except ValueError:
        check(True, "H2TEST correctly rejected after YAML restoration")

    # ── Step 9: Follow-up note ─────────────────────────────────────────
    print("\n── Step 9: Follow-Up Note ──")
    print("  📝 TODO (H3+): Move Hermes advisory risk target 0.25% into YAML")
    print("     as an advisory parameter so the two-tier risk model has")
    print("     one source file (paper-trading-rules.yaml) for all risk params.")

    # ── SUMMARY ────────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    total = PASS + FAIL
    print(f"Results: {PASS} passed, {FAIL} failed (of {total} checks)")
    print("=" * 60)

    if ERRORS:
        print("\nFailed checks:")
        for e in ERRORS:
            print(f"  - {e}")

    return FAIL == 0


if __name__ == "__main__":
    ok = main()
    sys.exit(0 if ok else 1)
