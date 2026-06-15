#!/usr/bin/env python3
"""
Phase 2B (P2b) — Gate E Loss-Halt Close-Only SELL Exemption Tests

Validates:
1. BUY blocked during active daily loss halt
2. BUY blocked during active weekly loss halt
3. BUY blocked during threshold-triggered halt
4. Close-only SELL allowed during active daily loss halt (position confirmed)
5. Close-only SELL allowed during active weekly loss halt (position confirmed)
6. Close-only SELL allowed during threshold-triggered halt (position confirmed)
7. Oversize SELL blocked (proposed > existing position)
8. SELL with unconfirmed position fail-closed
9. SELL with zero existing position fail-closed
10. SELL with no symbol fail-closed
11. SELL with zero/negative quantity fail-closed
12. Existing test compatibility (default args = BUY behavior)
13. gate_loss_halts defined exactly once
14. P2b details auditable in result
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from guard import gate_loss_halts, _get_existing_position

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


# ── Shared test fixtures ──────────────────────────────────────────────────

MOCK_RULES = {
    "loss_halts": {
        "daily": {"value": 1},   # 1% daily halt
        "weekly": {"value": 3},  # 3% weekly halt
    },
}

NL = 1_000_000.0  # €1M Net Liq

STATE_OK = {
    "daily_halt_active": False,
    "weekly_halt_active": False,
    "day_start_nl_eur": NL,
    "week_start_nl_eur": NL,
}                                          # no halts
STATE_DAILY_ACTIVE = {"daily_halt_active": True, "day_start_nl_eur": NL}
STATE_WEEKLY_ACTIVE = {"weekly_halt_active": True, "week_start_nl_eur": NL}

# Position provider that returns a confirmed long position
def _pos_provider_100_mock():
    return [{"symbol": "META", "position": 100, "marketValue": 50000}]


def _pos_provider_50_mock():
    return [{"symbol": "META", "position": 50, "marketValue": 25000}]


def _pos_provider_empty():
    return []


# ── 1. BUY blocked during active daily loss halt ──────────────────────────

def main() -> int:
    global PASS, FAIL
    PASS = 0
    FAIL = 0

    print("\n── 1. BUY blocked during active daily loss halt ──")
    ok, reason, details = gate_loss_halts(STATE_DAILY_ACTIVE, NL, MOCK_RULES)
    check("BUY blocked (daily_halt_active)", not ok)
    check("Reason mentions daily halt", "daily" in reason.lower())
    check("halt_type is daily", details.get("halt_type") == "daily")

    # ── 2. BUY blocked during active weekly loss halt ─────────────────────────
    print("\n── 2. BUY blocked during active weekly loss halt ──")
    ok, reason, details = gate_loss_halts(STATE_WEEKLY_ACTIVE, NL, MOCK_RULES)
    check("BUY blocked (weekly_halt_active)", not ok)
    check("Reason mentions weekly halt", "weekly" in reason.lower())
    check("halt_type is weekly", details.get("halt_type") == "weekly")

    # ── 3. BUY blocked during threshold-triggered halt ────────────────────────
    print("\n── 3. BUY blocked during threshold-triggered halt ──")
    # 1.5% daily loss triggers the 1% daily threshold
    ok, reason, details = gate_loss_halts(
        {"day_start_nl_eur": NL}, 985000, MOCK_RULES,
    )  # default: BUY
    check("BUY blocked (threshold daily)", not ok)
    check("Reason mentions pct drop", "%" in reason)
    check("Daily halt triggered in details", details.get("daily_halt_triggered") is True)

    # ── 4. Close-only SELL allowed during active daily loss halt ──────────────
    print("\n── 4. Close-only SELL allowed during active daily loss halt ──")
    ok, reason, details = gate_loss_halts(
        STATE_DAILY_ACTIVE, NL, MOCK_RULES,
        action="SELL", symbol="META", proposed_shares=72,
        position_provider=_pos_provider_100_mock,
    )
    check("SELL 72/100 passes active daily halt", ok)
    check("Reason mentions override/close-only",
          ("close-only" in reason.lower() or "override" in reason.lower()))
    check("p2b_exempt flag is True", details.get("p2b_exempt") is True)
    check("existing_position is 100", details.get("existing_position") == 100)
    check("position_source is ibkr_live", details.get("position_source") == "ibkr_live")

    # ── 5. Close-only SELL allowed during active weekly loss halt ─────────────
    print("\n── 5. Close-only SELL allowed during active weekly loss halt ──")
    ok, reason, details = gate_loss_halts(
        STATE_WEEKLY_ACTIVE, NL, MOCK_RULES,
        action="SELL", symbol="META", proposed_shares=72,
        position_provider=_pos_provider_100_mock,
    )
    check("SELL 72/100 passes active weekly halt", ok)
    check("p2b_exempt flag is True", details.get("p2b_exempt") is True)

    # ── 6. Close-only SELL allowed during threshold-triggered halt ────────────
    print("\n── 6. Close-only SELL allowed during threshold-triggered halt ──")
    ok, reason, details = gate_loss_halts(
        {"day_start_nl_eur": NL}, 985000, MOCK_RULES,
        action="SELL", symbol="META", proposed_shares=72,
        position_provider=_pos_provider_100_mock,
    )
    check("SELL 72/100 passes threshold-triggered halt", ok)
    check("p2b_exempt flag is True", details.get("p2b_exempt") is True)
    check("Daily halt triggered in details", details.get("daily_halt_triggered") is True)
    check("Reason includes pct info", "%" in reason)

    # ── 7. Oversize SELL blocked (proposed > existing) ────────────────────────
    print("\n── 7. Oversize SELL blocked ──")
    ok, reason, details = gate_loss_halts(
        STATE_DAILY_ACTIVE, NL, MOCK_RULES,
        action="SELL", symbol="META", proposed_shares=120,
        position_provider=_pos_provider_100_mock,
    )
    check("SELL 120 > 100 blocked during halt", not ok)
    check("p2b_note is oversize_sell_blocked",
          details.get("p2b_note") == "oversize_sell_blocked")
    check("Reason mentions quantity mismatch", "120" in reason and "100" in reason)
    check("existing_position is 100", details.get("existing_position") == 100)

    # ── 8. Oversize SELL with smaller existing position ───────────────────────
    print("\n── 8. Oversize SELL vs smaller position ──")
    ok, reason, details = gate_loss_halts(
        STATE_DAILY_ACTIVE, NL, MOCK_RULES,
        action="SELL", symbol="META", proposed_shares=72,
        position_provider=_pos_provider_50_mock,
    )
    check("SELL 72 > 50 blocked", not ok)
    check("p2b_note is oversize_sell_blocked",
          details.get("p2b_note") == "oversize_sell_blocked")
    check("existing_position is 50", details.get("existing_position") == 50)

    # ── 9. Full flatten (sell all) allowed ────────────────────────────────────
    print("\n── 9. Full flatten allowed ──")
    ok, reason, details = gate_loss_halts(
        STATE_DAILY_ACTIVE, NL, MOCK_RULES,
        action="SELL", symbol="META", proposed_shares=100,
        position_provider=_pos_provider_100_mock,
    )
    check("SELL 100/100 (full flatten) passes", ok)
    check("p2b_exempt flag is True", details.get("p2b_exempt") is True)

    # ── 10. Position unconfirmed (no position provider) ───────────────────────
    print("\n── 10. Position unconfirmed — fail closed ──")
    ok, reason, details = gate_loss_halts(
        STATE_DAILY_ACTIVE, NL, MOCK_RULES,
        action="SELL", symbol="META", proposed_shares=72,
        position_provider=None,
    )
    check("SELL without position provider fails closed", not ok)
    check("p2b_note is position_unconfirmed",
          details.get("p2b_note") == "position_unconfirmed")

    # ── 11. Position unconfirmed (empty position list) ────────────────────────
    print("\n── 11. Empty position list — fail closed ──")
    ok, reason, details = gate_loss_halts(
        STATE_DAILY_ACTIVE, NL, MOCK_RULES,
        action="SELL", symbol="META", proposed_shares=72,
        position_provider=_pos_provider_empty,
    )
    check("SELL with empty positions fails closed", not ok)
    check("p2b_note is position_unconfirmed",
          details.get("p2b_note") == "position_unconfirmed")

    # ── 12. Zero existing position — fail closed ─────────────────────────────
    print("\n── 12. Zero existing position — fail closed ──")
    ok, reason, details = gate_loss_halts(
        STATE_DAILY_ACTIVE, NL, MOCK_RULES,
        action="SELL", symbol="META", proposed_shares=72,
        position_provider=lambda: [{"symbol": "META", "position": 0}],
    )
    check("SELL with zero existing position fails closed", not ok)

    # ── 13. SELL with no symbol — fail closed ─────────────────────────────────
    print("\n── 13. SELL with no symbol ──")
    ok, reason, details = gate_loss_halts(
        STATE_DAILY_ACTIVE, NL, MOCK_RULES,
        action="SELL", symbol=None, proposed_shares=72,
        position_provider=_pos_provider_100_mock,
    )
    check("SELL with symbol=None fails closed", not ok)
    check("p2b_note is sell_no_symbol_or_qty",
          details.get("p2b_note") == "sell_no_symbol_or_qty")

    # ── 14. SELL with zero quantity — fail closed ────────────────────────────
    print("\n── 14. SELL with zero quantity ──")
    ok, reason, details = gate_loss_halts(
        STATE_DAILY_ACTIVE, NL, MOCK_RULES,
        action="SELL", symbol="META", proposed_shares=0,
        position_provider=_pos_provider_100_mock,
    )
    check("SELL with zero qty fails closed", not ok)
    check("p2b_note is sell_no_symbol_or_qty",
          details.get("p2b_note") == "sell_no_symbol_or_qty")

    # ── 15. Existing test backward compatibility ──────────────────────────────
    print("\n── 15. Backward compatibility (default args = BUY behavior) ──")
    # Original gate_loss_halts test from guard.py --test
    ok, reason, d = gate_loss_halts(STATE_OK, 995_000.0, MOCK_RULES)
    check("No halt, 0.5% daily loss: passes", ok)

    ok, reason, d = gate_loss_halts(STATE_OK, 989_000.0, MOCK_RULES)
    check("1.1% daily loss triggers halt: blocked (BUY)", not ok)
    check("Daily halt triggered", d.get("daily_halt_triggered") is True)

    # 3.5% weekly loss triggers weekly threshold
    ok, reason, d = gate_loss_halts(
        {"day_start_nl_eur": NL, "week_start_nl_eur": NL, "daily_halt_active": True},
        NL, MOCK_RULES,
    )
    check("Active daily halt + no weekly trigger: blocked", not ok)
    check("halt_type is daily", d.get("halt_type") == "daily")

    # ── 16. NO halt — SELL passes normally (no exemption needed) ──────────────
    print("\n── 16. No halt — SELL passes normally ──")
    ok, reason, details = gate_loss_halts(
        STATE_OK, NL, MOCK_RULES,
        action="SELL", symbol="META", proposed_shares=72,
        position_provider=_pos_provider_100_mock,
    )
    check("No halt + SELL: passes", ok)
    check("p2b_exempt flag absent (no halt)", "p2b_exempt" not in details)

    # ── 17. gate_loss_halts is defined exactly once ───────────────────────────
    print("\n── 17. Gate E definition count ──")
    import inspect
    src = inspect.getsource(sys.modules["guard"])
    count = src.count("def gate_loss_halts")
    check("gate_loss_halts defined exactly once", count == 1,
          f"found {count} definition(s)")

    # ── 18. P2b details in SELL exempt result ─────────────────────────────────
    print("\n── 18. P2b details auditable ──")
    ok, reason, details = gate_loss_halts(
        STATE_DAILY_ACTIVE, NL, MOCK_RULES,
        action="SELL", symbol="META", proposed_shares=72,
        position_provider=_pos_provider_100_mock,
    )
    check("p2b_exempt present", "p2b_exempt" in details)
    check("p2b_note present", "p2b_note" in details)
    check("existing_position in details", "existing_position" in details)
    check("position_source in details", "position_source" in details)
    check("halt_active in details", "halt_active" in details)

    # ── Summary ───────────────────────────────────────────────────────────────
    print(f"\n{'=' * 60}")
    print(f"Results:  ✅ {PASS} passed  ❌ {FAIL} failed")
    print(f"{'=' * 60}")

    if FAIL == 0:
        print("✅ ALL P2b CHECKS PASSED")
        return 0
    else:
        print("❌ P2b VALIDATION FAILED")
        return 1

    return 0 if FAIL == 0 else 1


def test_acceptance_suite_passes():
    assert main() == 0


if __name__ == "__main__":
    raise SystemExit(main())
