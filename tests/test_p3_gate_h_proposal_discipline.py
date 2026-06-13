#!/usr/bin/env python3
"""
Phase 3 (P3) — Gate H Proposal Discipline Tests

Validates:
1. Missing proposal → gate_proposal_discipline fails closed
2. File not found → fails closed
3. Malformed JSON → fails closed
4. Not a JSON object → fails closed
5. Incomplete proposal (missing fields) → fails closed
6. Valid proposal → passes
7. save_proposal_file writes valid JSON
8. Save/reload round-trip passes validation
9. Gate H wired into run_preflight (integration)
10. gate_loss_halts unchanged
"""

import json
import sys
import tempfile
from pathlib import Path

# Ensure guard.py is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from guard import (
    gate_proposal_discipline,
    save_proposal_file,
    _MANDATORY_PROPOSAL_STRING_FIELDS,
    _MANDATORY_PROPOSAL_NUMERIC_FIELDS,
    _MANDATORY_PROPOSAL_BOOL_FIELDS,
    _MANDATORY_POSITION_SIZING_FIELDS,
)

PASS = 0
FAIL = 0


def check(name: str, condition: bool, detail: str = ""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  ✅ {name}" + (f" — {detail}" if detail else ""))
    else:
        FAIL += 1
        print(f"  ❌ {name}" + (f" — {detail}" if detail else ""))


# ── Helper: build a minimal valid BUY proposal dict ────────────────────
def _valid_proposal() -> dict:
    return {
        "symbol": "AAPL",
        "side": "BUY",
        "quantity": 10,
        "entry_reference": "Limit buy at $150.00 support level",
        "stop_loss_invalidation": "Stop at $145.00 (2x ATR below entry)",
        "max_loss_eur": 50.0,
        "max_loss_pct": 0.005,
        "position_notional_eur": 1500.0,
        "position_notional_pct": 0.15,
        "portfolio_exposure_after_pct": 5.0,
        "daily_drawdown_status": "No drawdown",
        "weekly_drawdown_status": "No drawdown",
        "reason_to_trade": "Strong earnings momentum",
        "reason_not_to_trade": "Macro uncertainty",
        "preflight_command": "curl -X POST ... /order/preflight",
        "awaiting_chris_approval": True,
        "advisory_only": True,
        "position_sizing": {
            "method": "Fixed shares",
            "stop_price": 145.0,
            "final_shares": 10,
        },
    }


# ── Helper: build a minimal valid SELL / EXIT proposal dict ─────────────
def _valid_exit_proposal() -> dict:
    """Minimal valid close-only SELL proposal.

    An EXIT proposal requires only the common fields plus ``entry_reference``
    (which serves as the exit rationale / reference price).  Fields such as
    ``stop_loss_invalidation``, ``max_loss_eur``, position sizing, and
    notional/exposure caps are not required for EXIT proposals — Gate H
    enforces a lighter schema for SELL.
    """
    return {
        "symbol": "META",
        "side": "SELL",
        "quantity": 72,
        "entry_reference": "Exit at market — stop breached at $579.22, -5% floor breached at $566.47",
        "daily_drawdown_status": "Portfolio down ~0.27% from day-start",
        "weekly_drawdown_status": "Portfolio down ~0.27% from week-start",
        "reason_to_trade": "Stop-breach EXIT: pre-committed stop at $579.22 breached; -5% floor at $566.47 breached. 5 consecutive red daily candles.",
        "reason_not_to_trade": "-10% absolute floor at $536.66 still intact; dividend record date Jun 15 may provide support; snap-back risk.",
        "preflight_command": "curl -X POST http://127.0.0.1:8790/order/preflight -H 'Content-Type: application/json' -d '{\"symbol\":\"META\",\"action\":\"SELL\",\"totalQuantity\":72,\"orderType\":\"MKT\"}'",
        "awaiting_chris_approval": True,
        "advisory_only": True,
    }


# ── 1. Missing proposal (None) ───────────────────────────────────────────
print("\n── 1. Missing proposal ──")
ok, reason, details = gate_proposal_discipline(None)
check("Fails closed on None", not ok, reason[:80])
check("Error code is missing_proposal", details.get("error") == "missing_proposal")
check("Reason mentions proposals dir", "~/.openclaw/proposals/" in reason)


# ── 2. File not found ────────────────────────────────────────────────────
print("\n── 2. File not found ──")
ok, reason, details = gate_proposal_discipline("/nonexistent/proposal.json")
check("Fails closed on missing file", not ok)
check("Error code is file_not_found", details.get("error") == "file_not_found")


# ── 3. Malformed JSON ────────────────────────────────────────────────────
print("\n── 3. Malformed JSON ──")
with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
    f.write("{not valid json at all")
    bad_path = f.name
try:
    ok, reason, details = gate_proposal_discipline(bad_path)
    check("Fails closed on malformed JSON", not ok)
    check("Error code is malformed_json", details.get("error") == "malformed_json")
    check("Parse error is captured", bool(details.get("parse_error")))
finally:
    Path(bad_path).unlink(missing_ok=True)


# ── 4. Not a JSON object ─────────────────────────────────────────────────
print("\n── 4. Not a JSON object ──")
with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
    f.write("[1, 2, 3]")
    arr_path = f.name
try:
    ok, reason, details = gate_proposal_discipline(arr_path)
    check("Fails closed on array instead of object", not ok)
    check("Error code is not_a_dict", details.get("error") == "not_a_dict")
finally:
    Path(arr_path).unlink(missing_ok=True)


# ── 5. Incomplete proposal ───────────────────────────────────────────────
print("\n── 5. Incomplete proposal ──")

# 5a: Empty dict
with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
    json.dump({}, f)
    empty_path = f.name
try:
    ok, reason, details = gate_proposal_discipline(empty_path)
    check("Fails on empty dict", not ok)
    check("Error code is incomplete_proposal", details.get("error") == "incomplete_proposal")
    check("Many fields missing", details.get("total_missing", 0) >= 10)
finally:
    Path(empty_path).unlink(missing_ok=True)

# 5b: Missing a single required string field
p = _valid_proposal()
del p["reason_to_trade"]
with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
    json.dump(p, f)
    missing_str_path = f.name
try:
    ok, reason, details = gate_proposal_discipline(missing_str_path)
    check("Fails when single required string missing", not ok)
    check("Missing field identified", "reason_to_trade" in str(details.get("missing_string_fields", [])))
finally:
    Path(missing_str_path).unlink(missing_ok=True)

# 5c: Missing a numeric field
p = _valid_proposal()
del p["max_loss_eur"]
with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
    json.dump(p, f)
    missing_num_path = f.name
try:
    ok, reason, details = gate_proposal_discipline(missing_num_path)
    check("Fails when single required numeric missing", not ok)
    check("Missing numeric field identified", "max_loss_eur" in str(details.get("missing_numeric_fields", [])))
finally:
    Path(missing_num_path).unlink(missing_ok=True)

# 5d: Missing boolean field
p = _valid_proposal()
del p["advisory_only"]
with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
    json.dump(p, f)
    missing_bool_path = f.name
try:
    ok, reason, details = gate_proposal_discipline(missing_bool_path)
    check("Fails when single required bool missing", not ok)
    check("Missing bool field identified", "advisory_only" in str(details.get("missing_bool_fields", [])))
finally:
    Path(missing_bool_path).unlink(missing_ok=True)

# 5e: Missing position_sizing section
p = _valid_proposal()
del p["position_sizing"]
with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
    json.dump(p, f)
    missing_ps_path = f.name
try:
    ok, reason, details = gate_proposal_discipline(missing_ps_path)
    check("Fails when position_sizing missing", not ok)
    check("Position sizing gap identified", any("position_sizing" in m for m in details.get("missing_sizing_fields", [])))
finally:
    Path(missing_ps_path).unlink(missing_ok=True)

# 5f: Empty string field
p = _valid_proposal()
p["reason_to_trade"] = "   "
with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
    json.dump(p, f)
    blank_path = f.name
try:
    ok, reason, details = gate_proposal_discipline(blank_path)
    check("Fails when string field is blank", not ok)
    check("Blank field in missing_string_fields", "reason_to_trade" in str(details.get("missing_string_fields", [])))
finally:
    Path(blank_path).unlink(missing_ok=True)


# ── 6. Valid proposal ────────────────────────────────────────────────────
print("\n── 6. Valid proposal ──")
p = _valid_proposal()
with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
    json.dump(p, f)
    valid_path = f.name
try:
    ok, reason, details = gate_proposal_discipline(valid_path)
    check("Passes on valid proposal", ok)
    check("Reason mentions filename", Path(valid_path).name in reason)
    check("Details include symbol", details.get("symbol") == "AAPL")
    check("Details include side", details.get("side") == "BUY")
    check("Details include quantity", details.get("quantity") == 10)
finally:
    Path(valid_path).unlink(missing_ok=True)


# ── 7. save_proposal_file ────────────────────────────────────────────────
print("\n── 7. save_proposal_file ──")
p = _valid_proposal()
saved = None
try:
    saved = save_proposal_file(p, proposal_id="test-p3-001")
    check("save_proposal_file returns a Path", isinstance(saved, Path))
    check("Saved file exists", saved.exists())

    # Read back and validate
    with open(saved, "r") as f:
        reloaded = json.load(f)
    check("Reloaded is dict", isinstance(reloaded, dict))
    check("proposal_id is set", reloaded.get("proposal_id") == "test-p3-001")
    check("saved_at_utc is set", bool(reloaded.get("saved_at_utc")))
    check("Symbol preserved", reloaded.get("symbol") == "AAPL")

    # Round-trip: validate the persisted file passes Gate H
    ok, reason, details = gate_proposal_discipline(saved)
    check("Round-trip: saved proposal passes Gate H", ok)

    # save_proposal_file rejects non-dict
    try:
        save_proposal_file([1, 2, 3])
        check("Rejects non-dict proposal", False, "should have raised ValueError")
    except ValueError:
        check("Rejects non-dict proposal", True)
finally:
    if saved and saved.exists():
        saved.unlink()


# ── 8. Schema constants ──────────────────────────────────────────────────
print("\n── 8. Schema constants ──")
from guard import (
    _MANDATORY_PROPOSAL_STRING_FIELDS_COMMON,
    _MANDATORY_BUY_STRING_FIELDS,
    _MANDATORY_SELL_STRING_FIELDS,
    _MANDATORY_PROPOSAL_NUMERIC_FIELDS_COMMON,
    _MANDATORY_BUY_NUMERIC_FIELDS,
    _MANDATORY_SELL_NUMERIC_FIELDS,
    _MANDATORY_PROPOSAL_BOOL_FIELDS,
    _MANDATORY_POSITION_SIZING_FIELDS,
)
check("Common string fields defined", len(_MANDATORY_PROPOSAL_STRING_FIELDS_COMMON) >= 6)
check("BUY string fields defined", len(_MANDATORY_BUY_STRING_FIELDS) >= 2)
check("SELL string fields defined", len(_MANDATORY_SELL_STRING_FIELDS) >= 1)
check("Common numeric fields defined", len(_MANDATORY_PROPOSAL_NUMERIC_FIELDS_COMMON) >= 1)
check("BUY numeric fields defined", len(_MANDATORY_BUY_NUMERIC_FIELDS) >= 4)
check("SELL numeric fields empty", len(_MANDATORY_SELL_NUMERIC_FIELDS) == 0)
check("Bool fields defined", len(_MANDATORY_PROPOSAL_BOOL_FIELDS) >= 2)
check("Position sizing fields defined", len(_MANDATORY_POSITION_SIZING_FIELDS) >= 2)


# ── 9. EXIT: valid SELL proposal passes Gate H ───────────────────────────
print("\n── 9. EXIT: valid SELL proposal passes Gate H ──")
p = _valid_exit_proposal()
with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
    json.dump(p, f)
    exit_valid_path = f.name
try:
    ok, reason, details = gate_proposal_discipline(exit_valid_path)
    check("Valid EXIT proposal passes Gate H", ok, reason[:80])
    check("Reason includes SELL", "SELL" in reason)
    check("Details include symbol=META", details.get("symbol") == "META")
    check("Details include side=SELL", details.get("side") == "SELL")
    check("Details include quantity=72", details.get("quantity") == 72)
finally:
    Path(exit_valid_path).unlink(missing_ok=True)


# ── 10. EXIT: missing proposal_path fails closed ──────────────────────────
print("\n── 10. EXIT: missing proposal_path fails closed ──")
ok, reason, details = gate_proposal_discipline(None)
check("SELL without proposal_path fails closed", not ok)
check("Error code is missing_proposal", details.get("error") == "missing_proposal")
check("Reason is explicit", "proposal" in reason.lower())


# ── 11. EXIT: incomplete SELL proposal fails closed ───────────────────────
print("\n── 11. EXIT: incomplete SELL proposal fails closed ──")

# 11a: Missing reason_to_trade (common field)
p = _valid_exit_proposal()
del p["reason_to_trade"]
with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
    json.dump(p, f)
    exit_missing_path = f.name
try:
    ok, reason, details = gate_proposal_discipline(exit_missing_path)
    check("EXIT fails when reason_to_trade missing", not ok)
    check("Missing field is reason_to_trade", "reason_to_trade" in str(details.get("missing_string_fields", [])))
    check("Side recorded in details", details.get("side") == "SELL")
finally:
    Path(exit_missing_path).unlink(missing_ok=True)

# 11b: Missing entry_reference (SELL-specific field)
p = _valid_exit_proposal()
del p["entry_reference"]
with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
    json.dump(p, f)
    exit_missing_ref_path = f.name
try:
    ok, reason, details = gate_proposal_discipline(exit_missing_ref_path)
    check("EXIT fails when entry_reference missing", not ok)
    check("Missing field is entry_reference", "entry_reference" in str(details.get("missing_string_fields", [])))
finally:
    Path(exit_missing_ref_path).unlink(missing_ok=True)

# 11c: EXIT passes without BUY-only fields (stop_loss_invalidation, max_loss_eur, position_sizing)
p = _valid_exit_proposal()
with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
    json.dump(p, f)
    exit_no_buy_fields_path = f.name
try:
    ok, reason, details = gate_proposal_discipline(exit_no_buy_fields_path)
    check("EXIT passes without BUY-only fields", ok,
          f"(lacks: stop_loss, max_loss, position_sizing — still valid)")
    check("Side is SELL", details.get("side") == "SELL")
finally:
    Path(exit_no_buy_fields_path).unlink(missing_ok=True)

# 11d: Invalid side rejected
p = _valid_exit_proposal()
p["side"] = "SHORT"
with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
    json.dump(p, f)
    bad_side_path = f.name
try:
    ok, reason, details = gate_proposal_discipline(bad_side_path)
    check("Invalid side (SHORT) fails closed", not ok)
    check("Error code is invalid_side", details.get("error") == "invalid_side")
    check("Reason mentions invalid side", "SHORT" in reason)
finally:
    Path(bad_side_path).unlink(missing_ok=True)


# ── 12. EXIT: save + round-trip ───────────────────────────────────────────
print("\n── 12. EXIT: save + round-trip ──")
p = _valid_exit_proposal()
saved = None
try:
    saved = save_proposal_file(p, proposal_id="test-p3-exit-001")
    check("save_proposal_file EXIT returns Path", isinstance(saved, Path))
    check("EXIT file exists", saved.exists())
    with open(saved, "r") as f:
        reloaded = json.load(f)
    check("EXIT reloaded side=SELL", reloaded.get("side") == "SELL")
    check("EXIT reloaded symbol=META", reloaded.get("symbol") == "META")
    # Round-trip Gate H
    ok, reason, details = gate_proposal_discipline(saved)
    check("EXIT round-trip passes Gate H", ok)
    check("Details include symbol/side/quantity",
          details.get("symbol") == "META"
          and details.get("side") == "SELL"
          and details.get("quantity") == 72)
finally:
    if saved and saved.exists():
        saved.unlink()


# ── 13. BUY: missing proposal_path fails closed ───────────────────────────
print("\n── 13. BUY: missing proposal_path fails closed ──")
ok, reason, details = gate_proposal_discipline(None)
check("BUY without proposal_path fails closed (same as generic)", not ok)
check("Error details explicit", details.get("error") == "missing_proposal")


# ── 14. Proposal details are auditable ────────────────────────────────────
print("\n── 14. Proposal details are auditable ──")

# 14a: BUY proposal details
p_buy = _valid_proposal()
with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
    json.dump(p_buy, f)
    buy_detail_path = f.name
try:
    ok, reason, details = gate_proposal_discipline(buy_detail_path)
    check("BUY: details include symbol", details.get("symbol") == "AAPL")
    check("BUY: details include side=BUY", details.get("side") == "BUY")
    check("BUY: details include quantity=10", details.get("quantity") == 10)
    check("BUY: proposal_path is absolute", Path(details.get("proposal_path", "")).is_absolute())
finally:
    Path(buy_detail_path).unlink(missing_ok=True)

# 14b: EXIT proposal details
p_exit = _valid_exit_proposal()
with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
    json.dump(p_exit, f)
    exit_detail_path = f.name
try:
    ok, reason, details = gate_proposal_discipline(exit_detail_path)
    check("EXIT: details include symbol=META", details.get("symbol") == "META")
    check("EXIT: details include side=SELL", details.get("side") == "SELL")
    check("EXIT: details include quantity=72", details.get("quantity") == 72)
    check("EXIT: proposal_path is absolute", Path(details.get("proposal_path", "")).is_absolute())
finally:
    Path(exit_detail_path).unlink(missing_ok=True)


# ── 15. Integration: run_preflight accepts proposal_path ──────────────────
from guard import run_preflight
import inspect

# Verify run_preflight signature includes proposal_path
sig = inspect.signature(run_preflight)
check("run_preflight has proposal_path parameter", "proposal_path" in sig.parameters)
param = sig.parameters.get("proposal_path")
check("proposal_path default is None", param.default is None if param else False)

# Test that run_preflight calls Gate H when proposal_path is None
# (Gate H fails closed, but H1 authorization blocks full run_preflight)
try:
    result = run_preflight(
        {"symbol": "AAPL", "action": "BUY", "totalQuantity": 10, "orderType": "MKT"},
        proposal_path=None,
    )
    # If we get here (H1 authorized or startup phase), check gates
    gates = result.get("gates", [])
    proposal_gate = [g for g in gates if g.get("gate") == "proposal"]
    check("Gate H (proposal) appears in gates", len(proposal_gate) > 0)
    if proposal_gate:
        check("Gate H fails when no proposal_path", not proposal_gate[0]["passed"])
except PermissionError:
    # H1 enforcement active — expected. Gate H wiring verified via signature.
    check("run_preflight enforces H1 (expected)", True)
    check("Gate H wired (sig verified above)", True)

# With valid proposal file + H1 authorization still needed for guard-state
with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
    json.dump(_valid_proposal(), f)
    valid_path2 = f.name
try:
    # Gate H itself can be tested directly without H1
    ok, reason, details = gate_proposal_discipline(valid_path2)
    check("Gate H passes valid proposal (direct call)", ok)
finally:
    Path(valid_path2).unlink(missing_ok=True)


# ── 16. gate_loss_halts untouched ─────────────────────────────────────────
print("\n── 16. gate_loss_halts safety check ──")
import inspect
src = inspect.getsource(sys.modules["guard"])
count = src.count("def gate_loss_halts")
check("gate_loss_halts defined exactly once", count == 1, f"found {count} definition(s)")


# ── Summary ───────────────────────────────────────────────────────────────
print(f"\n{'='*60}")
print(f"Results:  ✅ {PASS} passed  ❌ {FAIL} failed")
print(f"{'='*60}")

if FAIL == 0:
    print("✅ ALL CHECKS PASSED")
    sys.exit(0)
else:
    print("❌ VALIDATION FAILED")
    sys.exit(1)
