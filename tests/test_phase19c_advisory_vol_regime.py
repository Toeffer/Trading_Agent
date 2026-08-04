"""Phase 19C — advisory layer: volatility, regime, cross-sectional RS.

strategy_v1_1 proposal §9.3. Advisory only — these functions never gate,
size, or touch the order path. The single most important test in this
module is `TestEffectiveBudgetNeverExceedsCeiling` (§9.5): it proves the
advisory layer is structurally incapable of loosening guard.py's
gate_exposure ceiling, across randomized volatility and all three regime
states.
"""

import math
import random
import statistics
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from hermes_advisory import (  # noqa: E402
    REFERENCE_SYMBOL,
    REGIME_MULTIPLIERS,
    REGIME_STATES,
    build_proposal,
    compute_effective_budget,
    compute_gross_scalar,
    compute_realized_vol,
    compute_regime_state,
    rank_cross_sectional_rs,
)


def _bars(closes):
    return [{"close": c} for c in closes]


# ── Reference symbol stays off any order path ───────────────────────────────


class TestReferenceSymbolIsNeverOrderEligible:
    def test_reference_symbol_is_spy(self):
        assert REFERENCE_SYMBOL == "SPY"

    def test_advisory_module_has_no_order_paths(self):
        source = (REPO / "hermes_advisory.py").read_text()
        for forbidden in ["order_path", "preflight_path", "approval_path",
                           "submission_path", "H1_access"]:
            assert forbidden not in source, forbidden

    def test_no_sizing_import(self):
        """The advisory layer must not import guard's sizing/stop functions —
        it must be structurally incapable of proposing a size. Checks actual
        import statements only, so a docstring/comment mentioning these
        names (to say they're absent) is not itself a false positive."""
        import ast
        tree = ast.parse((REPO / "hermes_advisory.py").read_text())
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                imported.update(a.name for a in node.names)
        forbidden = {"compute_final_max_shares", "calc_stop", "calc_true_range"}
        assert forbidden.isdisjoint(imported), forbidden & imported


# ── Realized volatility ─────────────────────────────────────────────────────


class TestRealizedVol:
    def test_known_series_exact(self):
        """closes = [100, 100e, 100]: log returns [+1, -1], sample stdev
        sqrt(2), annualized sqrt(2 * 252) -- hand-computable, no randomness."""
        bars = _bars([100.0, 100.0 * math.e, 100.0])
        vol = compute_realized_vol(bars, lookback=2)
        expected = math.sqrt(2) * math.sqrt(252)
        assert abs(vol - expected) < 1e-9

    def test_matches_independent_recomputation(self):
        """Independently rebuilds the log-return window/annualization
        outside compute_realized_vol and checks they agree — catches an
        off-by-one in the lookback window or a wrong annualization factor."""
        rng = random.Random(7)
        closes = [100.0]
        for _ in range(40):
            closes.append(closes[-1] * math.exp(rng.gauss(0, 0.01)))
        vol = compute_realized_vol(_bars(closes), lookback=20)

        recent = closes[-21:]
        rets = [math.log(recent[i] / recent[i - 1]) for i in range(1, len(recent))]
        expected = statistics.stdev(rets) * math.sqrt(252)
        assert abs(vol - expected) < 1e-9

    def test_zero_vol_flat_series(self):
        bars = _bars([100.0] * 25)
        assert compute_realized_vol(bars, lookback=20) == 0.0

    def test_ignores_none_closes(self):
        closes = [100.0 + i for i in range(25)]
        bars = _bars(closes)
        bars.insert(3, {"close": None})
        vol = compute_realized_vol(bars, lookback=20)
        assert vol >= 0.0

    def test_insufficient_bars_raises(self):
        with pytest.raises(ValueError):
            compute_realized_vol(_bars([100.0, 101.0]), lookback=20)

    def test_lookback_must_be_positive(self):
        with pytest.raises(ValueError):
            compute_realized_vol(_bars([100.0, 101.0, 102.0]), lookback=0)


# ── Regime state truth table (strategy_v1_1 §4.5) ───────────────────────────


class TestRegimeStateTruthTable:
    """A: last close > sma_days SMA.  B: trailing momentum_days return > 0."""

    def test_risk_on_both_true(self):
        closes = list(range(1, 12))  # 1..11, strictly rising
        state = compute_regime_state(_bars(closes), sma_days=5, momentum_days=10)
        assert state == "RISK_ON"

    def test_risk_off_both_false(self):
        closes = list(range(11, 0, -1))  # 11..1, strictly falling
        state = compute_regime_state(_bars(closes), sma_days=5, momentum_days=10)
        assert state == "RISK_OFF"

    def test_caution_a_true_b_false(self):
        """Long decline (momentum negative) with a small recent uptick
        (last close above its own trailing 5-day average)."""
        closes = [30, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14]
        state = compute_regime_state(_bars(closes), sma_days=5, momentum_days=10)
        assert state == "CAUTION"

    def test_caution_a_false_b_true(self):
        """Long uptrend overall (momentum positive) with a sharp recent dip
        (last close below its own trailing 5-day average)."""
        closes = [1, 2, 3, 4, 5, 6, 7, 8, 50, 10, 9]
        state = compute_regime_state(_bars(closes), sma_days=5, momentum_days=10)
        assert state == "CAUTION"

    def test_returns_only_known_states(self):
        for closes in (list(range(1, 12)), list(range(11, 0, -1)),
                       [30, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14]):
            assert compute_regime_state(
                _bars(closes), sma_days=5, momentum_days=10
            ) in REGIME_STATES

    def test_insufficient_bars_raises(self):
        with pytest.raises(ValueError):
            compute_regime_state(_bars([100.0] * 3), sma_days=5, momentum_days=10)

    def test_never_evaluates_sell(self):
        """This function takes no action/side argument at all — it cannot
        distinguish or block a SELL, by construction."""
        import inspect
        params = inspect.signature(compute_regime_state).parameters
        assert "action" not in params and "side" not in params


# ── Inverse-volatility gross scalar (strategy_v1_1 §4.6) ────────────────────


class TestGrossScalarClamping:
    CFG = {"vol_reference_pct": 16, "gross_scalar_floor": 0.25}

    def test_typical_vol_scalar_near_one(self):
        assert compute_gross_scalar(0.16, self.CFG) == pytest.approx(1.0)

    def test_calm_vol_clamped_to_one(self):
        """Doc table: sigma_ref=10% or 12%, RISK_ON -> gross_scalar clamped to 1.00."""
        assert compute_gross_scalar(0.10, self.CFG) == pytest.approx(1.0)
        assert compute_gross_scalar(0.12, self.CFG) == pytest.approx(1.0)

    def test_elevated_vol_scales_down(self):
        # Doc table: sigma_ref=24% -> gross_scalar ~= 0.67
        assert compute_gross_scalar(0.24, self.CFG) == pytest.approx(0.667, abs=0.01)

    def test_crisis_vol_clamped_to_floor(self):
        # Doc table: sigma_ref=64% -> gross_scalar = 0.25 (floor)
        assert compute_gross_scalar(0.64, self.CFG) == pytest.approx(0.25)

    def test_extreme_vol_never_below_floor(self):
        assert compute_gross_scalar(2.00, self.CFG) == pytest.approx(0.25)

    @pytest.mark.parametrize("sigma", [0.001, 0.05, 0.16, 0.30, 0.64, 1.0, 2.0])
    def test_always_within_floor_and_one(self, sigma):
        scalar = compute_gross_scalar(sigma, self.CFG)
        assert 0.25 <= scalar <= 1.0

    def test_nonpositive_sigma_raises(self):
        with pytest.raises(ValueError):
            compute_gross_scalar(0.0, self.CFG)
        with pytest.raises(ValueError):
            compute_gross_scalar(-0.1, self.CFG)

    def test_bad_floor_raises(self):
        with pytest.raises(ValueError):
            compute_gross_scalar(0.16, {"vol_reference_pct": 16, "gross_scalar_floor": 0.0})
        with pytest.raises(ValueError):
            compute_gross_scalar(0.16, {"vol_reference_pct": 16, "gross_scalar_floor": 1.5})


# ── Effective budget — the mandatory ceiling property (§9.3, §9.5) ─────────


class TestEffectiveBudgetNeverExceedsCeiling:
    """The single most important test in the 19E set: the advisory layer
    must be structurally incapable of loosening the guard."""

    CFG = {"vol_reference_pct": 16, "gross_scalar_floor": 0.25}
    RULES = {"max_total_exposure": {"value": 30}}

    def test_worked_illustration_table(self):
        """Spot-check every row of the doc's own worked-illustration table
        (§4.6), not just the property in the abstract."""
        cases = [
            (0.10, "RISK_ON", 30.0),
            (0.12, "RISK_ON", 30.0),
            (0.16, "RISK_ON", 30.0),
            (0.18, "RISK_ON", 26.7),
            (0.24, "RISK_ON", 20.0),
            (0.24, "CAUTION", 10.0),
            (0.40, "RISK_ON", 12.0),
            (0.64, "RISK_ON", 7.5),
        ]
        for sigma, regime, expected in cases:
            got = compute_effective_budget(sigma, regime, self.RULES, self.CFG)
            assert got == pytest.approx(expected, abs=0.1), (sigma, regime, got, expected)

    def test_risk_off_is_always_zero(self):
        for sigma in (0.05, 0.16, 0.5, 2.0):
            assert compute_effective_budget(sigma, "RISK_OFF", self.RULES, self.CFG) == 0.0

    def test_unknown_regime_raises(self):
        with pytest.raises(ValueError):
            compute_effective_budget(0.16, "SOMETHING_ELSE", self.RULES, self.CFG)

    @pytest.mark.parametrize("max_exposure_pct", [5, 10, 25, 30, 50, 100])
    @pytest.mark.parametrize("regime", REGIME_STATES)
    def test_property_never_exceeds_ceiling(self, max_exposure_pct, regime):
        """Required property test (§9.5): for randomized sigma_ref in
        (0, 200%] and all three regime states, effective_budget must never
        exceed max_total_exposure — across a range of ceilings and floors
        too, not just the 30%/0.25 defaults."""
        rng = random.Random(1234 + max_exposure_pct)
        rules = {"max_total_exposure": {"value": max_exposure_pct}}
        for _ in range(300):
            sigma_ref = rng.uniform(1e-4, 2.0)
            vol_reference_pct = rng.uniform(1.0, 40.0)
            floor = rng.uniform(0.05, 0.9)
            cfg = {"vol_reference_pct": vol_reference_pct, "gross_scalar_floor": floor}
            budget = compute_effective_budget(sigma_ref, regime, rules, cfg)
            assert budget <= max_exposure_pct + 1e-9, (
                f"effective_budget {budget} exceeded ceiling {max_exposure_pct} "
                f"(sigma_ref={sigma_ref}, regime={regime}, cfg={cfg})"
            )
            assert budget >= 0.0

    def test_gross_scalar_le_one_is_the_mechanism(self):
        """Directly confirms the mechanism the property test relies on:
        gross_scalar <= 1.0 and regime_multiplier <= 1.0 always."""
        rng = random.Random(99)
        for _ in range(200):
            sigma_ref = rng.uniform(1e-4, 3.0)
            cfg = {"vol_reference_pct": rng.uniform(1.0, 40.0),
                   "gross_scalar_floor": rng.uniform(0.05, 0.9)}
            assert compute_gross_scalar(sigma_ref, cfg) <= 1.0
        assert all(m <= 1.0 for m in REGIME_MULTIPLIERS.values())


# ── Cross-sectional relative strength (strategy_v1_1 §4.3 reference) ───────


class TestCrossSectionalRS:
    def test_top_half_by_trailing_return(self):
        symbol_bars = {
            "UP": _bars(list(range(100, 161))),      # +60%
            "FLAT": _bars([100.0] * 61),               # 0%
            "DOWN": _bars(list(range(100, 39, -1))),  # -61%
        }
        top = rank_cross_sectional_rs(symbol_bars, lookback=60, top_fraction=0.5)
        assert "UP" in top
        assert "DOWN" not in top

    def test_excludes_symbols_with_too_few_bars(self):
        symbol_bars = {
            "OK": _bars([100.0] * 61),
            "TOO_SHORT": _bars([100.0] * 10),
        }
        top = rank_cross_sectional_rs(symbol_bars, lookback=60)
        assert "TOO_SHORT" not in top

    def test_all_symbols_excluded_returns_empty_set(self):
        symbol_bars = {"A": _bars([100.0] * 5)}
        assert rank_cross_sectional_rs(symbol_bars, lookback=60) == set()

    def test_bad_top_fraction_raises(self):
        with pytest.raises(ValueError):
            rank_cross_sectional_rs({}, top_fraction=0.0)
        with pytest.raises(ValueError):
            rank_cross_sectional_rs({}, top_fraction=1.5)

    def test_never_gates_or_sizes(self):
        """Return type is a set of symbols only — no gate/order-relevant
        fields can leak through this function's output."""
        symbol_bars = {"A": _bars([100.0] * 61), "B": _bars(list(range(100, 161)))}
        top = rank_cross_sectional_rs(symbol_bars, lookback=60)
        assert isinstance(top, set)
        assert all(isinstance(s, str) for s in top)


# ── Advisory proposal shape (never a size or leverage) ─────────────────────


class TestBuildProposal:
    def test_returns_no_size_or_leverage_field(self):
        p = build_proposal(
            "NVDA", rank=1, thesis="momentum", invalidation_condition="close<sma50",
            regime_state="RISK_ON", in_top_half_rs=True,
        )
        forbidden_keys = {"shares", "quantity", "notional", "leverage", "size",
                           "totalQuantity", "position_notional_eur", "position_notional_usd"}
        assert forbidden_keys.isdisjoint(p.keys())

    def test_marked_advisory_only(self):
        p = build_proposal(
            "AAPL", rank=2, thesis="t", invalidation_condition="i",
            regime_state="CAUTION", in_top_half_rs=False,
        )
        assert p["advisory_only"] is True
        assert p["size_or_leverage_included"] is False

    def test_rank_and_thesis_roundtrip(self):
        p = build_proposal(
            "MSFT", rank=5, thesis="quality compounder",
            invalidation_condition="close<200sma",
            regime_state="RISK_ON", in_top_half_rs=True,
        )
        assert p["symbol"] == "MSFT"
        assert p["rank"] == 5
        assert p["thesis"] == "quality compounder"
        assert p["invalidation_condition"] == "close<200sma"
        assert p["regime_state"] == "RISK_ON"
        assert p["in_top_half_rs"] is True
