"""Phase 19D — Gate I: sector concentration cap.

strategy_v1_1 proposal §4.7 / §9.4. Momentum clusters by sector, so without
this gate the ranker could fill two slots with one correlated bet (e.g.
NVDA + AMD) at effectively double the intended risk.

Per CLAUDE.md §6, guard.py edits require a Tier-1 model and a Chris-
approved, git-tagged change. Per the proposal's own dependency order
(§9.9), this code must not reach the live bridge before Chris's Phase 19B
YAML edit is actually applied there — landing it first would make
guard.load_rules() raise on the missing symbol_sectors /
max_positions_per_sector keys and the bridge would fail to start. These
tests exercise the gate and the required-keys validation purely with
synthetic rules dicts; they prove no live YAML.

Coverage (§9.5):
  - 2nd position in a sector rejected; 1st allowed
  - SELL exempt
  - unmapped symbol fails closed
  - semis treated as distinct from IT
  - grandfathered position occupies its sector slot
"""

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import guard  # noqa: E402


SECTOR_MAP = {
    "AAPL": "INFORMATION_TECHNOLOGY",
    "MSFT": "INFORMATION_TECHNOLOGY",
    "NVDA": "SEMICONDUCTORS",
    "AMD": "SEMICONDUCTORS",
    "META": "COMMUNICATION_SERVICES",
    "GOOGL": "COMMUNICATION_SERVICES",
}

RULES = {
    "symbol_sectors": SECTOR_MAP,
    "max_positions_per_sector": {"value": 1},
}


def _position(symbol, shares=10, price=100.0):
    return {"symbol": symbol, "position": shares, "marketPrice": price}


# ── Core gate behavior ───────────────────────────────────────────────────


class TestGateISectorCap:
    def test_first_position_in_sector_allowed(self):
        ok, reason, details = guard.gate_sector_concentration("NVDA", [], RULES)
        assert ok, reason
        assert details["occupants"] == []

    def test_second_position_in_same_sector_rejected(self):
        """NVDA already held; AMD (same sector) must be rejected — this is
        exactly the momentum-cluster failure mode §4.7.1 describes."""
        positions = [_position("NVDA")]
        ok, reason, details = guard.gate_sector_concentration("AMD", positions, RULES)
        assert not ok
        assert details["sector"] == "SEMICONDUCTORS"
        assert details["occupants"] == ["NVDA"]

    def test_second_position_in_different_sector_allowed(self):
        positions = [_position("NVDA")]  # SEMICONDUCTORS
        ok, reason, details = guard.gate_sector_concentration("AAPL", positions, RULES)  # IT
        assert ok, reason

    def test_symbol_can_backfill_after_flat_close(self):
        """A closed (qty<=0) position does not occupy its sector slot."""
        positions = [_position("NVDA", shares=0)]
        ok, reason, details = guard.gate_sector_concentration("AMD", positions, RULES)
        assert ok, reason
        assert details["occupants"] == []

    def test_cap_of_two_allows_two_in_sector(self):
        rules = {"symbol_sectors": SECTOR_MAP, "max_positions_per_sector": {"value": 2}}
        positions = [_position("NVDA")]
        ok, reason, details = guard.gate_sector_concentration("AMD", positions, rules)
        assert ok, reason

    def test_cap_of_two_rejects_third_in_sector(self):
        rules = {"symbol_sectors": SECTOR_MAP, "max_positions_per_sector": {"value": 2}}
        # Third semis name — reuse NVDA/AMD as the two occupants.
        positions = [_position("NVDA"), _position("AMD")]
        ok, reason, details = guard.gate_sector_concentration("AVGO_TEST", positions,
            {"symbol_sectors": {**SECTOR_MAP, "AVGO_TEST": "SEMICONDUCTORS"},
             "max_positions_per_sector": {"value": 2}})
        assert not ok
        assert len(details["occupants"]) == 2


# ── Fail-closed on unmapped symbols ──────────────────────────────────────


class TestFailClosedUnmapped:
    def test_unmapped_candidate_symbol_rejected(self):
        ok, reason, details = guard.gate_sector_concentration("ZZZZ", [], RULES)
        assert not ok
        assert "sector mapping" in reason
        assert details["sector"] is None

    def test_unmapped_occupant_symbol_does_not_crash(self):
        """A position in a symbol with no sector entry must not raise —
        it simply can't occupy any sector slot."""
        positions = [_position("UNMAPPED_LEGACY_SYMBOL")]
        ok, reason, details = guard.gate_sector_concentration("NVDA", positions, RULES)
        assert ok, reason

    def test_empty_sector_string_fails_closed(self):
        rules = {"symbol_sectors": {"WEIRD": ""}, "max_positions_per_sector": {"value": 1}}
        ok, reason, details = guard.gate_sector_concentration("WEIRD", [], rules)
        assert not ok

    def test_missing_symbol_sectors_key_fails_closed(self):
        rules = {"max_positions_per_sector": {"value": 1}}
        ok, reason, details = guard.gate_sector_concentration("NVDA", [], rules)
        assert not ok


# ── SELL exemption ────────────────────────────────────────────────────────


class TestSellExemption:
    def test_gate_is_never_invoked_for_sell_in_run_preflight(self):
        """run_preflight's SELL branch must not call gate_sector_concentration
        — closing a position can only reduce concentration, never increase
        it (consistent with Gate G close-only logic)."""
        source = (REPO / "guard.py").read_text()
        sell_start = source.index("if is_close:\n        # SELL (close-only)")
        sell_end = source.index("else:\n        # BUY: run gates")
        sell_body = source[sell_start:sell_end]
        assert "gate_sector_concentration" not in sell_body

    def test_gate_i_itself_takes_no_action_argument(self):
        """The gate function has no BUY/SELL branch at all — callers alone
        decide whether to invoke it, and only the BUY path does."""
        import inspect
        params = list(inspect.signature(guard.gate_sector_concentration).parameters)
        assert params == ["symbol", "positions", "rules"]


# ── Semiconductors distinct from Information Technology ─────────────────


class TestSemiconductorsDistinctFromIT:
    def test_nvda_and_aapl_are_different_sectors(self):
        ok, reason, details = guard.gate_sector_concentration(
            "AAPL", [_position("NVDA")], RULES,
        )
        assert ok, "NVDA (SEMICONDUCTORS) must not block AAPL (INFORMATION_TECHNOLOGY)"

    def test_two_it_names_still_capped(self):
        """MSFT occupies IT; AAPL (also IT) is capped — the cap is real
        for IT, it's just a separate bucket from SEMICONDUCTORS."""
        ok, reason, details = guard.gate_sector_concentration(
            "AAPL", [_position("MSFT")], RULES,
        )
        assert not ok


# ── Grandfathered position occupies its sector slot ──────────────────────


class TestGrandfatheredPosition:
    def test_pre_existing_position_counts_as_occupant(self):
        """A position opened before Gate I existed still occupies its
        sector slot going forward — no special-casing by open date."""
        grandfathered = [_position("NVDA", shares=72)]
        ok, reason, details = guard.gate_sector_concentration("AMD", grandfathered, RULES)
        assert not ok
        assert "NVDA" in details["occupants"]

    def test_grandfathered_position_itself_not_reblocked(self):
        """Gate I only evaluates a candidate BUY symbol; it says nothing
        about a symbol that is already held (that is not a new BUY)."""
        # Re-buying more of the already-held symbol in the same sector is
        # still blocked once the sector is at capacity — no self-exemption.
        ok, reason, details = guard.gate_sector_concentration(
            "NVDA", [_position("NVDA", shares=72)], RULES,
        )
        assert not ok


# ── load_rules() validation (Phase 19D adds these) ───────────────────────


class TestLoadRulesSectorValidation:
    def _full_rules(self, allow, sectors, cap=1):
        return {
            "rules_version": "1.3-draft",
            "max_position_notional": {"value": 5},
            "max_risk_per_trade": {"value": 2},
            "max_total_exposure": {"value": 30},
            "max_trades_per_day": {"value": 2},
            "loss_halts": {"daily": {"value": 1}, "weekly": {"value": 3}},
            "initial_stop_loss": {"atr_multiplier": 2, "atr_period": 14, "absolute_floor_percent": 5},
            "symbol_allowlist": {"mode": "explicit_list", "allow": allow},
            "manual_approval": {"enabled": True, "timeout_seconds": 300},
            "order_endpoint_gate": {},
            "guard_state": {"file": "guard-state.json"},
            "preflight": {"strict_mode": True, "response_type": "validation_results_only"},
            "logging": {"file": "guard-events.jsonl"},
            "symbol_sectors": sectors,
            "max_positions_per_sector": {"value": cap},
        }

    def _write(self, tmp_path, rules):
        import yaml
        p = tmp_path / "rules.yaml"
        p.write_text(yaml.dump(rules))
        return p

    def test_missing_symbol_sectors_key_raises_at_load(self, tmp_path):
        rules = self._full_rules(["AAPL"], {"AAPL": "INFORMATION_TECHNOLOGY"})
        del rules["symbol_sectors"]
        path = self._write(tmp_path, rules)
        with pytest.raises(ValueError, match="Missing required rule sections"):
            guard.load_rules(path)

    def test_missing_max_positions_per_sector_key_raises_at_load(self, tmp_path):
        rules = self._full_rules(["AAPL"], {"AAPL": "INFORMATION_TECHNOLOGY"})
        del rules["max_positions_per_sector"]
        path = self._write(tmp_path, rules)
        with pytest.raises(ValueError, match="Missing required rule sections"):
            guard.load_rules(path)

    def test_allowlisted_symbol_without_sector_raises_at_load(self):
        """Every allowlisted symbol must have a sector mapping, else raise
        at load (§9.4 requirement) — this is the exact hazard the proposal
        flags for 19D landing before 19B."""
        rules = self._full_rules(["AAPL", "TSLA"], {"AAPL": "INFORMATION_TECHNOLOGY"})
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            path = self._write(Path(d), rules)
            with pytest.raises(ValueError, match="TSLA"):
                guard.load_rules(path)

    def test_valid_sector_map_loads_cleanly(self, tmp_path):
        rules = self._full_rules(
            ["AAPL", "NVDA"],
            {"AAPL": "INFORMATION_TECHNOLOGY", "NVDA": "SEMICONDUCTORS"},
        )
        path = self._write(tmp_path, rules)
        loaded = guard.load_rules(path)
        assert loaded["symbol_sectors"]["NVDA"] == "SEMICONDUCTORS"

    def test_zero_cap_raises_at_load(self, tmp_path):
        rules = self._full_rules(
            ["AAPL"], {"AAPL": "INFORMATION_TECHNOLOGY"}, cap=0,
        )
        path = self._write(tmp_path, rules)
        with pytest.raises(ValueError, match="max_positions_per_sector"):
            guard.load_rules(path)

    def test_non_dict_symbol_sectors_raises_at_load(self, tmp_path):
        rules = self._full_rules(["AAPL"], {"AAPL": "INFORMATION_TECHNOLOGY"})
        rules["symbol_sectors"] = "not-a-dict"
        path = self._write(tmp_path, rules)
        with pytest.raises(ValueError, match="symbol_sectors"):
            guard.load_rules(path)


# ── No hardcoded duplicate (H2 invariant) ────────────────────────────────


class TestNoHardcodedDuplicate:
    def test_gate_reads_sector_map_from_rules_argument_only(self):
        source = (REPO / "guard.py").read_text()
        fn_start = source.index("def gate_sector_concentration")
        fn_end = source.index("\n\n\n", fn_start)
        fn_body = source[fn_start:fn_end]
        # No hardcoded sector name list — only reads via rules.get(...)
        assert "SEMICONDUCTORS" not in fn_body
        assert "INFORMATION_TECHNOLOGY" not in fn_body
        assert 'rules.get("symbol_sectors"' in fn_body
        assert 'rules["max_positions_per_sector"]' in fn_body
