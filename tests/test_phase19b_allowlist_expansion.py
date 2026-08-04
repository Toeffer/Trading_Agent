"""Phase 19B — allowlist expansion (4 -> 22 symbols) + sector map.

Phase 19B itself is a YAML-only change Chris applies directly to
`~/.openclaw/risk-rules/paper-trading-rules.yaml` (CLAUDE.md invariant 6 —
Werner never modifies that file). That live file is outside this
repository, so these tests do not read it. Instead they pin that
`guard.load_rules()` correctly accepts and validates a rules document
shaped exactly like the strategy_v1_1 proposal §9.2 diff — the same
property whether Chris's live file or this synthetic fixture is loaded.

Coverage (strategy_v1_1 §9.5):
  - 22 symbols load
  - every symbol has a sector
  - symbol_allowlist.mode stays 'explicit_list'
  - a symbol outside the allowlist still fails Gate A
"""

import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import guard  # noqa: E402


# ── The proposed 19B content (strategy_v1_1 §9.2), verbatim ────────────────

PROPOSED_ALLOWLIST = [
    "AAPL", "MSFT", "AVGO", "NVDA", "AMD", "META", "GOOGL", "LLY", "UNH",
    "JNJ", "PG", "KO", "AMZN", "HD", "JPM", "BAC", "XOM", "CVX", "CAT",
    "UNP", "NEE", "DUK",
]

PROPOSED_SECTOR_MAP = {
    "AAPL": "INFORMATION_TECHNOLOGY",
    "MSFT": "INFORMATION_TECHNOLOGY",
    "AVGO": "INFORMATION_TECHNOLOGY",
    "NVDA": "SEMICONDUCTORS",
    "AMD": "SEMICONDUCTORS",
    "META": "COMMUNICATION_SERVICES",
    "GOOGL": "COMMUNICATION_SERVICES",
    "LLY": "HEALTH_CARE",
    "UNH": "HEALTH_CARE",
    "JNJ": "HEALTH_CARE",
    "PG": "CONSUMER_STAPLES",
    "KO": "CONSUMER_STAPLES",
    "AMZN": "CONSUMER_DISCRETIONARY",
    "HD": "CONSUMER_DISCRETIONARY",
    "JPM": "FINANCIALS",
    "BAC": "FINANCIALS",
    "XOM": "ENERGY",
    "CVX": "ENERGY",
    "CAT": "INDUSTRIALS",
    "UNP": "INDUSTRIALS",
    "NEE": "UTILITIES",
    "DUK": "UTILITIES",
}

PROPOSED_ADVISORY = {
    "vol_reference_pct": 16,
    "vol_lookback_days": 20,
    "gross_scalar_floor": 0.25,
    "regime_sma_days": 200,
    "regime_momentum_months": 12,
    "regime_caution_multiplier": 0.5,
    "cross_sectional_rs_lookback_days": 60,
    "cross_sectional_rs_top_fraction": 0.5,
    "reference_symbol": "SPY",
    "reference_bar_duration": "1 Y",
    "min_reference_bars": 252,
    "min_symbol_bars_for_rs": 60,
    "min_valid_symbol_fraction": 0.5,
    "hermes_risk_per_trade_pct": 0.25,
}


def _full_rules(allow=None, sectors=None, per_sector_cap=1):
    """A complete, load_rules()-valid document shaped like 19B's proposal.

    Sections load_rules() requires but that §9.2's diff doesn't show (they
    predate 19B and are unchanged by it) are filled with the values
    load_rules() itself asserts on, so this fixture exercises real
    validation rather than a shortcut around it.
    """
    return {
        "rules_version": "1.3-draft",
        "max_position_notional": {"value": 5},
        "max_risk_per_trade": {"value": 2},
        "max_total_exposure": {"value": 30},
        "max_trades_per_day": {"value": 2},
        "loss_halts": {"daily": {"value": 1}, "weekly": {"value": 3}},
        "initial_stop_loss": {"atr_multiplier": 2, "atr_period": 14, "absolute_floor_percent": 5},
        "symbol_allowlist": {
            "mode": "explicit_list",
            "allow": PROPOSED_ALLOWLIST if allow is None else allow,
        },
        "manual_approval": {"enabled": True, "timeout_seconds": 300},
        "order_endpoint_gate": {},
        "guard_state": {"file": "guard-state.json"},
        "preflight": {"strict_mode": True, "response_type": "validation_results_only"},
        "logging": {"file": "guard-events.jsonl"},
        "symbol_sectors": PROPOSED_SECTOR_MAP if sectors is None else sectors,
        "max_positions_per_sector": {"value": per_sector_cap},
        "advisory": dict(PROPOSED_ADVISORY),
    }


def _write_rules(tmp_path, rules) -> Path:
    p = tmp_path / "paper-trading-rules.yaml"
    p.write_text(yaml.dump(rules))
    return p


# ── Tests ────────────────────────────────────────────────────────────────


class TestAllowlistExpansion:
    def test_22_symbols_load(self, tmp_path):
        path = _write_rules(tmp_path, _full_rules())
        rules = guard.load_rules(path)
        allowed = guard._get_allowed_symbols(rules)
        assert len(allowed) == 22
        assert set(allowed) == set(PROPOSED_ALLOWLIST)

    def test_mode_stays_explicit_list(self, tmp_path):
        path = _write_rules(tmp_path, _full_rules())
        rules = guard.load_rules(path)
        assert rules["symbol_allowlist"]["mode"] == "explicit_list"

    @pytest.mark.parametrize("symbol", PROPOSED_ALLOWLIST)
    def test_every_allowlisted_symbol_passes_gate_a(self, tmp_path, symbol):
        path = _write_rules(tmp_path, _full_rules())
        rules = guard.load_rules(path)
        ok, reason, details = guard.gate_allowlist(symbol, rules)
        assert ok, reason

    def test_unknown_symbol_still_fails_gate_a(self, tmp_path):
        path = _write_rules(tmp_path, _full_rules())
        rules = guard.load_rules(path)
        ok, reason, details = guard.gate_allowlist("TSLA", rules)
        assert not ok
        assert "TSLA" in reason


class TestSectorMapCompleteness:
    @pytest.mark.parametrize("symbol", PROPOSED_ALLOWLIST)
    def test_every_symbol_has_a_sector(self, symbol):
        assert symbol in PROPOSED_SECTOR_MAP
        assert PROPOSED_SECTOR_MAP[symbol]

    def test_load_rules_accepts_the_full_map(self, tmp_path):
        path = _write_rules(tmp_path, _full_rules())
        rules = guard.load_rules(path)
        assert rules["symbol_sectors"] == PROPOSED_SECTOR_MAP

    def test_nvda_amd_are_one_sector_group(self):
        """strategy_v1_1 §4.7.1 — momentum clusters by sector; NVDA/AMD
        must be treated as one bet, not two, so Gate I can bind on them."""
        assert PROPOSED_SECTOR_MAP["NVDA"] == PROPOSED_SECTOR_MAP["AMD"]

    def test_semiconductors_distinct_from_information_technology(self):
        """§4.7 — semis are a distinct sector from IT for Gate I purposes."""
        assert PROPOSED_SECTOR_MAP["NVDA"] != PROPOSED_SECTOR_MAP["AAPL"]
        assert PROPOSED_SECTOR_MAP["NVDA"] == "SEMICONDUCTORS"
        assert PROPOSED_SECTOR_MAP["AAPL"] == "INFORMATION_TECHNOLOGY"

    @pytest.mark.parametrize("pair", [
        ("NVDA", "AMD"), ("META", "GOOGL"), ("JPM", "BAC"), ("XOM", "CVX"),
    ])
    def test_near_duplicate_pairs_share_a_sector(self, pair):
        """§4.7.1's four named near-duplicate pairs must share a sector."""
        a, b = pair
        assert PROPOSED_SECTOR_MAP[a] == PROPOSED_SECTOR_MAP[b]

    @pytest.mark.parametrize("pair", [("CAT", "UNP"), ("AMZN", "HD")])
    def test_genuinely_different_businesses_still_share_a_gics_sector(self, pair):
        """§4.7.1 — CAT/UNP (machinery vs rail) and AMZN/HD (e-commerce vs
        home improvement) are 'unaffected either way' by the cap's value:
        unlike the four near-duplicate pairs, the proposal doesn't rely on
        Gate I to prevent a correlated double-bet here. They do still share
        a GICS sector bucket in this map (Industrials, Consumer
        Discretionary) — Gate I applies to them mechanically the same as
        any other pair in a sector; the doc's point is about correlation
        risk, not about which sector bucket they land in."""
        a, b = pair
        assert PROPOSED_SECTOR_MAP[a] == PROPOSED_SECTOR_MAP[b]


class TestBackwardCompatibility:
    """§9.2 — adding symbol_sectors/max_positions_per_sector/advisory must
    not disturb any other section load_rules() already validated."""

    def test_unknown_top_level_key_does_not_break_load(self, tmp_path):
        rules = _full_rules()
        rules["some_future_section"] = {"anything": True}
        path = _write_rules(tmp_path, rules)
        loaded = guard.load_rules(path)
        assert loaded["some_future_section"] == {"anything": True}

    def test_advisory_section_is_optional_for_load_rules(self, tmp_path):
        """advisory is read by hermes_advisory.py, not enforced by guard.py
        (§9.2) — its absence must not stop guard.py from loading."""
        rules = _full_rules()
        del rules["advisory"]
        path = _write_rules(tmp_path, rules)
        loaded = guard.load_rules(path)
        assert "advisory" not in loaded

    def test_us_etf_blocklist_still_optional(self, tmp_path):
        rules = _full_rules()
        rules["us_etf_blocklist"] = {"mode": "extend_regulatory_baseline", "symbols": []}
        path = _write_rules(tmp_path, rules)
        loaded = guard.load_rules(path)
        assert loaded["us_etf_blocklist"]["symbols"] == []

    def test_numeric_caps_unchanged_by_expansion(self, tmp_path):
        path = _write_rules(tmp_path, _full_rules())
        rules = guard.load_rules(path)
        assert rules["max_position_notional"]["value"] == 5
        assert rules["max_risk_per_trade"]["value"] == 2
        assert rules["max_total_exposure"]["value"] == 30
        assert rules["max_trades_per_day"]["value"] == 2
