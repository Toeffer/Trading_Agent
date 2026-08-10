"""
Phase 19B/B4 — Gate I wired into guard.py.

Resolves the question left open after Phase 19B (YAML confirmed live) and B3
(strategy_v1_1_advisory.py, advisory-only, never blocks anything): the
proposal's own §10.1 check #2 — "Gate I rejects 3rd same-sector position,
100% rejection" — is a paper-run pass/fail criterion that can only be
satisfied if guard.py itself, not an advisory layer, actually rejects the
order at preflight. This module verifies that guard.py does that, using
strategy_v1_1_core.py's pure gate_sector_concentration (B1) as the single
source of truth — guard.py contains no duplicate counting logic (H2).

Covers:
  - guard.gate_sector_concentration() is a thin rules-dict adapter, not a
    reimplementation.
  - load_rules() requires symbol_sectors/max_positions_per_sector and
    validates every allowlisted symbol has a sector.
  - run_preflight() actually rejects a 2nd same-sector BUY, allows the 1st
    and a different-sector BUY.
  - SELL never reaches Gate I (close-only reduces concentration, per §9.4).
  - Position-fetch failure (or no position_provider) fails Gate I CLOSED,
    not open — an empty-positions default would make the cap unenforceable.
  - A flat (qty=0) position reported by IBKR doesn't occupy a sector slot.
"""

import inspect
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import guard  # noqa: E402
import strategy_v1_1_core as core  # noqa: E402

GUARD_SOURCE = (REPO / "guard.py").read_text()

SECTOR_MAP = {
    "AAPL": "INFORMATION_TECHNOLOGY",
    "MSFT": "INFORMATION_TECHNOLOGY",
    "NVDA": "SEMICONDUCTORS",
    "AMD": "SEMICONDUCTORS",
}


def _position(symbol, qty=100):
    return {"symbol": symbol, "position": qty}


def _full_rules(**overrides):
    rules = {
        "rules_version": "1.3-draft",
        "max_position_notional": {"value": 5},
        "max_risk_per_trade": {"value": 2},
        "max_total_exposure": {"value": 30},
        "max_trades_per_day": {"value": 2},
        "loss_halts": {"daily_pct": 1, "weekly_pct": 3},
        "initial_stop_loss": {
            "atr_multiplier": 2, "atr_period": 14, "absolute_floor_percent": 5,
        },
        "symbol_allowlist": {
            "mode": "explicit_list", "allow": ["AAPL", "MSFT", "NVDA", "AMD"],
        },
        "symbol_sectors": dict(SECTOR_MAP),
        "max_positions_per_sector": {"value": 1},
        "manual_approval": {"enabled": True, "timeout_seconds": 300},
        "order_endpoint_gate": {},
        "guard_state": {"file": "guard-state.json"},
        "preflight": {
            "strict_mode": True, "response_type": "validation_results_only",
        },
        "logging": {"file": "guard-events.jsonl"},
    }
    rules.update(overrides)
    return rules


def _account():
    return {"net_liquidation_eur": 1_000_000.0, "exchange_rate": 1.08}


def _quote(symbol):
    return {"ask": 100.0, "bid": 99.5, "close": 99.8}


def _bars(symbol):
    return [
        {"open": 99.0 + i * 0.01, "high": 101.0 + i * 0.01, "low": 98.0 + i * 0.01,
         "close": 100.0 + i * 0.01, "volume": 1000}
        for i in range(30)
    ]


# ── guard.gate_sector_concentration() — thin adapter, not a duplicate ──────


class TestGateWrapperDelegatesToB1:
    def test_pass_empty_positions(self):
        rules = _full_rules()
        ok, reason, details = guard.gate_sector_concentration("AAPL", [], rules)
        assert ok is True
        assert reason == core.ReasonCode.GATE_I_PASS
        assert details["sector"] == "INFORMATION_TECHNOLOGY"

    def test_blocks_second_same_sector(self):
        rules = _full_rules()
        ok, reason, details = guard.gate_sector_concentration(
            "MSFT", [_position("AAPL")], rules,
        )
        assert ok is False
        assert reason == core.ReasonCode.GATE_I_SECTOR_FULL

    def test_allows_different_sector(self):
        rules = _full_rules()
        ok, reason, details = guard.gate_sector_concentration(
            "NVDA", [_position("AAPL")], rules,
        )
        assert ok is True

    def test_unmapped_symbol_fails_closed(self):
        rules = _full_rules(symbol_sectors={})
        ok, reason, details = guard.gate_sector_concentration("ZZZZ", [], rules)
        assert ok is False
        assert reason == core.ReasonCode.GATE_I_SYMBOL_UNMAPPED

    def test_flat_position_does_not_occupy_slot(self):
        """A position with qty=0 (flat, still reported by IBKR) must not
        count as occupying the sector — matches _get_existing_position's
        own qty > 0 convention."""
        rules = _full_rules()
        ok, reason, details = guard.gate_sector_concentration(
            "MSFT", [_position("AAPL", qty=0)], rules,
        )
        assert ok is True, "A flat (qty=0) position must not occupy a sector slot"

    def test_no_hardcoded_duplicate(self):
        """guard.py's wrapper must delegate, not reimplement the counting
        loop (H2: no hardcoded duplicates)."""
        src = inspect.getsource(guard.gate_sector_concentration)
        assert "for pos in" not in src or "held = [" in src, (
            "the only loop in this function should be the qty-filter "
            "comprehension, not a sector-counting loop"
        )
        assert "_core_gate_sector_concentration(" in src

    def test_reason_codes_come_from_core_module(self):
        """Guard against a future edit inventing new guard.py-local reason
        strings instead of using B1's ReasonCode constants."""
        src = inspect.getsource(guard.gate_sector_concentration)
        assert "ReasonCode" not in src, (
            "guard.py's wrapper should never construct ReasonCode itself — "
            "those come back through the (ok, reason, details) tuple from "
            "strategy_v1_1_core"
        )


# ── SELL exemption ───────────────────────────────────────────────────────


class TestSellExemption:
    def test_sell_never_reaches_gate_i(self):
        start = GUARD_SOURCE.index("if is_close:\n        # SELL")
        end = GUARD_SOURCE.index("# Build result", start)
        block = GUARD_SOURCE[start:end]
        buy_start = block.index("else:\n        # BUY")
        sell_only = block[:buy_start]
        assert "gate_sector_concentration" not in sell_only


# ── load_rules() validation ──────────────────────────────────────────────


class TestLoadRulesSectorValidation:
    def _write(self, tmp_path, rules):
        p = tmp_path / "rules.yaml"
        p.write_text(yaml.dump(rules))
        return p

    def test_missing_symbol_sectors_raises(self, tmp_path):
        rules = _full_rules()
        del rules["symbol_sectors"]
        p = self._write(tmp_path, rules)
        with pytest.raises(ValueError, match="Missing required rule sections"):
            guard.load_rules(path=p)

    def test_missing_max_positions_per_sector_raises(self, tmp_path):
        rules = _full_rules()
        del rules["max_positions_per_sector"]
        p = self._write(tmp_path, rules)
        with pytest.raises(ValueError, match="Missing required rule sections"):
            guard.load_rules(path=p)

    def test_unmapped_allowlist_symbol_raises(self, tmp_path):
        rules = _full_rules()
        rules["symbol_allowlist"]["allow"] = ["AAPL", "TSLA"]  # TSLA unmapped
        p = self._write(tmp_path, rules)
        with pytest.raises(ValueError, match="missing a mapping"):
            guard.load_rules(path=p)

    def test_zero_max_per_sector_raises(self, tmp_path):
        rules = _full_rules(max_positions_per_sector={"value": 0})
        p = self._write(tmp_path, rules)
        with pytest.raises(ValueError, match="max_positions_per_sector"):
            guard.load_rules(path=p)

    def test_non_int_max_per_sector_raises(self, tmp_path):
        rules = _full_rules(max_positions_per_sector={"value": "one"})
        p = self._write(tmp_path, rules)
        with pytest.raises(ValueError, match="max_positions_per_sector"):
            guard.load_rules(path=p)

    def test_valid_full_document_loads(self, tmp_path):
        rules = _full_rules()
        p = self._write(tmp_path, rules)
        loaded = guard.load_rules(path=p)
        assert loaded["symbol_sectors"] == SECTOR_MAP
        assert loaded["max_positions_per_sector"]["value"] == 1

    def test_extra_symbol_beyond_allowlist_is_fine(self, tmp_path):
        """symbol_sectors may contain more entries than the current
        allowlist (e.g. staged for a future expansion) — only the reverse
        (an allowlisted symbol missing a sector) is an error."""
        rules = _full_rules()
        rules["symbol_sectors"]["GOOGL"] = "COMMUNICATION_SERVICES"
        p = self._write(tmp_path, rules)
        loaded = guard.load_rules(path=p)  # must not raise
        assert "GOOGL" in loaded["symbol_sectors"]


# ── run_preflight() integration — the actual §10.1 check #2 claim ─────────


class TestRunPreflightIntegration:
    @patch("guard.load_guard_state")
    @patch("guard.load_rules")
    def test_second_same_sector_position_rejected(self, mock_load_rules, mock_state):
        mock_load_rules.return_value = _full_rules()
        mock_state.return_value = guard.default_guard_state()
        result = guard.run_preflight(
            {"symbol": "MSFT", "action": "BUY", "totalQuantity": 1, "orderType": "MKT"},
            account_provider=_account,
            quote_provider=_quote,
            bars_provider=_bars,
            position_provider=lambda: [_position("AAPL")],
            open_order_provider=lambda symbol: {"open": False},
        )
        gate = next(g for g in result["gates"] if g["gate"] == "sector_concentration")
        assert gate["passed"] is False
        assert result["passed"] is False

    @patch("guard.load_guard_state")
    @patch("guard.load_rules")
    def test_first_position_in_sector_allowed(self, mock_load_rules, mock_state):
        mock_load_rules.return_value = _full_rules()
        mock_state.return_value = guard.default_guard_state()
        result = guard.run_preflight(
            {"symbol": "AAPL", "action": "BUY", "totalQuantity": 1, "orderType": "MKT"},
            account_provider=_account,
            quote_provider=_quote,
            bars_provider=_bars,
            position_provider=lambda: [],
            open_order_provider=lambda symbol: {"open": False},
        )
        gate = next(g for g in result["gates"] if g["gate"] == "sector_concentration")
        assert gate["passed"] is True

    @patch("guard.load_guard_state")
    @patch("guard.load_rules")
    def test_different_sector_allowed_despite_existing_position(self, mock_load_rules, mock_state):
        mock_load_rules.return_value = _full_rules()
        mock_state.return_value = guard.default_guard_state()
        result = guard.run_preflight(
            {"symbol": "NVDA", "action": "BUY", "totalQuantity": 1, "orderType": "MKT"},
            account_provider=_account,
            quote_provider=_quote,
            bars_provider=_bars,
            position_provider=lambda: [_position("AAPL")],
            open_order_provider=lambda symbol: {"open": False},
        )
        gate = next(g for g in result["gates"] if g["gate"] == "sector_concentration")
        assert gate["passed"] is True

    @patch("guard.load_guard_state")
    @patch("guard.load_rules")
    def test_positions_unavailable_fails_closed(self, mock_load_rules, mock_state):
        """A provider that raises must reject, not silently pass with an
        empty-positions assumption — that would make the cap unenforceable
        exactly when position data is least trustworthy."""
        mock_load_rules.return_value = _full_rules()
        mock_state.return_value = guard.default_guard_state()

        def _raising_position_provider():
            raise RuntimeError("IBKR disconnected")

        result = guard.run_preflight(
            {"symbol": "AAPL", "action": "BUY", "totalQuantity": 1, "orderType": "MKT"},
            account_provider=_account,
            quote_provider=_quote,
            bars_provider=_bars,
            position_provider=_raising_position_provider,
            open_order_provider=lambda symbol: {"open": False},
        )
        gate = next(g for g in result["gates"] if g["gate"] == "sector_concentration")
        assert gate["passed"] is False
        assert result["passed"] is False

    @patch("guard.load_guard_state")
    @patch("guard.load_rules")
    def test_no_position_provider_fails_closed(self, mock_load_rules, mock_state):
        mock_load_rules.return_value = _full_rules()
        mock_state.return_value = guard.default_guard_state()
        result = guard.run_preflight(
            {"symbol": "AAPL", "action": "BUY", "totalQuantity": 1, "orderType": "MKT"},
            account_provider=_account,
            quote_provider=_quote,
            bars_provider=_bars,
            position_provider=None,
            open_order_provider=lambda symbol: {"open": False},
        )
        gate = next(g for g in result["gates"] if g["gate"] == "sector_concentration")
        assert gate["passed"] is False

    @patch("guard.load_guard_state")
    @patch("guard.load_rules")
    def test_non_list_position_provider_return_fails_closed(self, mock_load_rules, mock_state):
        mock_load_rules.return_value = _full_rules()
        mock_state.return_value = guard.default_guard_state()
        result = guard.run_preflight(
            {"symbol": "AAPL", "action": "BUY", "totalQuantity": 1, "orderType": "MKT"},
            account_provider=_account,
            quote_provider=_quote,
            bars_provider=_bars,
            position_provider=lambda: None,
            open_order_provider=lambda symbol: {"open": False},
        )
        gate = next(g for g in result["gates"] if g["gate"] == "sector_concentration")
        assert gate["passed"] is False


# ── Gate registry consistency ────────────────────────────────────────────


class TestGateRegistryConsistency:
    """Regex is scoped to the official '\"\"\"Gate X — ...' docstring claim
    format only — run_preflight's inline '# Gate X — ...' comments echo the
    same letter and would double-count otherwise."""

    def test_gate_i_letter_claimed_exactly_once(self):
        import re
        claims = re.findall(r'"""Gate ([A-Z]) —', GUARD_SOURCE)
        assert claims.count("I") == 1

    def test_all_letters_a_through_i_present_exactly_once(self):
        import re
        claims = re.findall(r'"""Gate ([A-Z]) —', GUARD_SOURCE)
        for letter in "ABCDEFGHI":
            assert claims.count(letter) == 1, f"Gate {letter} count: {claims.count(letter)}"

    def test_sector_concentration_gate_registered_in_buy_branch(self):
        assert '"gate": "sector_concentration"' in GUARD_SOURCE
