"""Gate G (close-only SELL, safety invariant #9) — wiring regression tests.

Bug (found 2026-09-07, fixed the same day): gate_close_only() was defined in
63052ed but never called. run_preflight()'s SELL branch appended a
"close_only" gate entry that silently reused Gate E's (ok, reason, details).
Gate E only inspects the position while a loss halt is active, so with no
halt active a SELL for a symbol with no position, or larger than the
position, passed preflight — the short-creation path invariant #9 exists to
block. Submit-time revalidation skips SELL checks and the broker path places
a plain SELL, so preflight was the only place this could be caught.

Level 1 / portable: guard.py only, providers injected, no IBKR, no ~/.openclaw.
"""

from historical.preflight import run_preflight as historical_preflight
from source_helpers import implementation_source

import re
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import guard  # noqa: E402

GUARD_SOURCE = implementation_source('guard.py', historical=True)


def _full_rules():
    return {
        "rules_version": "1.3-draft",
        "max_position_notional": {"value": 5},
        "max_risk_per_trade": {"value": 2},
        "max_total_exposure": {"value": 30},
        "max_trades_per_day": {"value": 2},
        "loss_halts": {"daily_pct": 1, "weekly_pct": 3},
        "initial_stop_loss": {"atr_multiplier": 2, "atr_period": 14, "absolute_floor_percent": 5},
        "symbol_allowlist": {"mode": "explicit_list", "allow": ["AAPL", "MSFT"]},
        "symbol_sectors": {"AAPL": "INFORMATION_TECHNOLOGY", "MSFT": "INFORMATION_TECHNOLOGY"},
        "max_positions_per_sector": {"value": 1},
        "manual_approval": {"enabled": True, "timeout_seconds": 300},
        "order_endpoint_gate": {},
        "guard_state": {"file": "guard-state.json"},
        "preflight": {"strict_mode": True, "response_type": "validation_results_only"},
        "logging": {"file": "guard-events.jsonl"},
    }


def _account():
    return {"net_liquidation_eur": 1_000_000.0, "exchange_rate": 1.08}


def _quote(symbol):
    return {"ask": 100.0, "bid": 99.5, "close": 99.8}


def _bars(symbol):
    return [{"open": 99.0, "high": 101.0, "low": 98.0, "close": 100.0, "volume": 1000} for _ in range(30)]


def _sell(qty, positions, tmp_path):
    """Run a SELL preflight with injected providers; return (result, close_only gate)."""
    with patch("guard.load_rules", return_value=_full_rules()), \
         patch("guard.load_guard_state", return_value=guard.default_guard_state()), \
         patch("guard.GUARD_STATE_PATH", tmp_path / "guard-state.json"), \
         patch("guard.GUARD_EVENTS_PATH", tmp_path / "guard-events.jsonl"), \
         patch("guard.APPROVAL_RECORDS_PATH", tmp_path / "approval-records.jsonl"), \
         patch("guard.ACTIVE_APPROVALS_PATH", tmp_path / "active-approvals.json"):
        result = historical_preflight(
            {"symbol": "AAPL", "action": "SELL", "totalQuantity": qty, "orderType": "MKT"},
            account_provider=_account,
            quote_provider=_quote,
            bars_provider=_bars,
            position_provider=lambda: positions,
            open_order_provider=lambda symbol: {"open": False},
        )
    gate = next((g for g in result.get("gates", []) if g["gate"] == "close_only"), None)
    assert gate is not None, f"no close_only gate entry in {result}"
    return result, gate


def _pos(symbol, qty):
    return {"symbol": symbol, "position": qty, "marketPrice": 100.0}


class TestGateGBlocksShorts:
    def test_sell_with_no_position_fails_close_only(self, tmp_path):
        result, gate = _sell(10, [], tmp_path)
        assert gate["passed"] is False
        assert "No existing long position" in gate["reason"]
        assert result["passed"] is False

    def test_sell_with_position_in_other_symbol_only_fails(self, tmp_path):
        result, gate = _sell(10, [_pos("MSFT", 50)], tmp_path)
        assert gate["passed"] is False
        assert result["passed"] is False

    def test_sell_larger_than_position_fails_and_flags_short(self, tmp_path):
        result, gate = _sell(72, [_pos("AAPL", 50)], tmp_path)
        assert gate["passed"] is False
        assert gate["details"]["would_open_short"] is True
        assert gate["details"]["existing_qty"] == 50
        assert gate["details"]["proposed_qty"] == 72
        assert result["passed"] is False

    def test_sell_within_position_passes_gate_g(self, tmp_path):
        # Overall preflight may still fail on Gate H (no proposal file); the
        # claim under test is Gate G's own verdict.
        _, gate = _sell(30, [_pos("AAPL", 50)], tmp_path)
        assert gate["passed"] is True
        assert gate["details"]["net_after"] == 20
        assert gate["details"]["would_open_short"] is False

    def test_close_only_entry_is_not_a_copy_of_loss_halts(self, tmp_path):
        # Before the fix the close_only entry was byte-identical to Gate E's.
        result, gate = _sell(10, [], tmp_path)
        loss = next(g for g in result["gates"] if g["gate"] == "loss_halts")
        assert loss["passed"] is True          # no halt active
        assert gate["passed"] is False         # but no position to close
        assert gate["details"] != loss["details"]
        assert "existing_qty" in gate["details"]


class TestHistoricalGateGIsWiredInSource:
    def test_run_preflight_calls_gate_close_only(self):
        start = GUARD_SOURCE.index("\ndef run_preflight(")
        end = GUARD_SOURCE.index("\ndef ", start + 1)
        body = GUARD_SOURCE[start:end]
        assert re.search(r"gate_close_only\(\s*symbol,\s*proposed_shares,\s*position_provider\s*\)", body)

    def test_close_only_entry_follows_its_own_call(self):
        start = GUARD_SOURCE.index("\ndef run_preflight(")
        end = GUARD_SOURCE.index("\ndef ", start + 1)
        body = GUARD_SOURCE[start:end]
        assert body.index("gate_close_only(") < body.index('"gate": "close_only"')
