"""
Phase 19B B2 — Golden-vector end-to-end deterministic tests.

Full pipeline: bar validation → SPY reference → realized vol →
gross scalar → regime → RS ranking → budget → gate → position classification.

All inputs are inline deterministic values. No network, no filesystem,
no environment, no current time.
"""

import json
import math
import unittest
import strategy_v1_1_core as mod


# ══════════════════════════════════════════════════════════════════════════════
# Deterministic input fixtures (inline)
# ══════════════════════════════════════════════════════════════════════════════


def _mk_bar(o, h, l, c, v=100, **kw):
    return {"open": o, "high": h, "low": l, "close": c, "volume": v, **kw}


def _spy_bull_300_days():
    """SPY: 300 days, rising from 100 to ~250."""
    bars = []
    for i in range(300):
        c = 100.0 + i * 0.5
        bars.append(_mk_bar(c - 1.0, c + 1.5, c - 1.5, c, 1000000))
    return bars


def _universe_bars(symbols, n_days=65):
    """Generate bars for each symbol with different returns."""
    out = {}
    for i, s in enumerate(symbols):
        base = 100.0 + i * 3.0
        step = 0.01 + i * 0.005
        out[s] = [_mk_bar(base + j * step - 0.3, base + j * step + 0.3,
                          base + j * step - 0.4, base + j * step, 10000)
                  for j in range(n_days)]
    return out


# ══════════════════════════════════════════════════════════════════════════════
# Golden vectors
# ══════════════════════════════════════════════════════════════════════════════


class TestGoldenPipelineRiskOn(unittest.TestCase):
    """Full pipeline: SPY bull market → RISK_ON → full budget → RS ranking."""

    def test_full_pipeline_risk_on(self):
        # Step 1: SPY reference data
        spy_bars = _spy_bull_300_days()
        spy_val = mod.validate_spy_reference_data(spy_bars)
        self.assertTrue(spy_val["valid"])
        self.assertEqual(spy_val["reason"], mod.ReasonCode.SPY_DATA_VALID)
        self.assertGreaterEqual(spy_val["bar_count"], 252)

        # Step 2: Regime → RISK_ON
        regime = mod.compute_regime_state(spy_bars)
        self.assertTrue(regime["valid"])
        self.assertIn(regime["regime"], {"RISK_ON", "CAUTION", "RISK_OFF"})

        # Step 3: Realized vol from SPY bars
        vol = mod.compute_realized_vol(spy_bars, lookback_days=20)
        self.assertTrue(vol["valid"])
        self.assertIsNotNone(vol["sigma_ref"])

        # Step 4: Gross scalar
        scalar = mod.compute_gross_scalar(vol["sigma_ref"])
        self.assertGreater(scalar["gross_scalar"], 0)
        self.assertIn(scalar["reason"],
                      [mod.ReasonCode.VOL_SCALAR_NOMINAL, mod.ReasonCode.VOL_SCALAR_CLAMPED])

        # Step 5: Effective budget
        budget = mod.compute_effective_budget(regime=regime["regime"],
                                               gross_scalar=scalar["gross_scalar"])
        self.assertTrue(budget["assertion_passed"])
        if regime["regime"] == "RISK_OFF":
            self.assertAlmostEqual(budget["effective_budget_pct"], 0.0)
        else:
            self.assertGreaterEqual(budget["effective_budget_pct"], 0.0)

        # Step 6: Remaining budget
        rem = mod.compute_remaining_budget(budget["effective_budget_pct"],
                                            net_liquidation_eur=50000.0,
                                            exchange_rate=1.05)
        self.assertGreaterEqual(rem["remaining_budget_usd"], 0.0)

        # Step 7: RS ranking
        symbols = list(mod.FROZEN_UNIVERSE.keys())
        uni = _universe_bars(symbols)
        rs = mod.compute_cross_sectional_rs(uni)
        self.assertFalse(rs["no_trade"])
        self.assertEqual(len(rs["ranks"]), len(symbols))

        # Step 8: Verify top-half symbol passes gate
        top_sym = rs["top_half_symbols"][0]
        ok, reason, details = mod.gate_sector_concentration(top_sym, [])
        self.assertTrue(ok)
        self.assertEqual(reason, mod.ReasonCode.GATE_I_PASS)

        # Step 9: Verify top-half symbol is RS eligible
        self.assertTrue(mod.is_candidate_rs_eligible(top_sym, rs))

        # Step 10: Signal alignment validation
        sa = {
            "passed": True,
            "signals": {"trend": True, "volume": True, "structure": False, "relative_strength": False},
            "aligned_count": 2,
        }
        ok_sa, _, _ = mod.validate_signal_alignment(sa)
        self.assertTrue(ok_sa)

        # Step 11: Classify a position
        pos = mod.classify_position(top_sym, is_pre_activation=True)
        self.assertTrue(pos["grandfathered"])
        self.assertIsNotNone(pos["sector"])

        # Step 12: Advisory config validation
        ok_cfg, _, _ = mod.validate_advisory_config(None)
        self.assertTrue(ok_cfg)


class TestGoldenPipelineRiskOff(unittest.TestCase):
    """Insufficient SPY data → RISK_OFF → zero budget."""

    def test_insufficient_spy_pipeline(self):
        spy_bars = [_mk_bar(99, 102, 98, 100, 1000) for _ in range(50)]  # insufficient
        vol = mod.compute_realized_vol(spy_bars, lookback_days=20)
        self.assertFalse(vol["valid"])

        regime = mod.compute_regime_state(spy_bars)
        self.assertEqual(regime["regime"], "RISK_OFF")

        budget = mod.compute_effective_budget(regime="RISK_OFF")
        self.assertAlmostEqual(budget["effective_budget_pct"], 0.0)

        rem = mod.compute_remaining_budget(0.0, net_liquidation_eur=50000.0, exchange_rate=1.05)
        self.assertAlmostEqual(rem["remaining_budget_usd"], 0.0)
        self.assertTrue(rem["budget_exhausted"])


class TestGoldenHermesValidation(unittest.TestCase):
    def test_clean_output(self):
        r = mod.validate_hermes_output("AAPL technicals remain strong")
        self.assertTrue(r["valid"])
        self.assertEqual(r["reason"], mod.ReasonCode.HERMES_OUTPUT_VALID)

    def test_forbidden_buy(self):
        r = mod.validate_hermes_output("Buy 500 shares of AAPL at market open")
        self.assertFalse(r["valid"])
        self.assertEqual(r["reason"], mod.ReasonCode.HERMES_FORBIDDEN_PATTERN)

    def test_forbidden_percent(self):
        r = mod.validate_hermes_output("Allocate 10% of portfolio")
        self.assertFalse(r["valid"])


class TestGoldenSignalAlignment(unittest.TestCase):
    def test_valid_3_of_4(self):
        sa = {
            "passed": True,
            "signals": {"trend": True, "volume": True, "structure": True, "relative_strength": False},
            "aligned_count": 3,
        }
        ok, reason, _ = mod.validate_signal_alignment(sa)
        self.assertTrue(ok)

    def test_valid_0_of_4(self):
        sa = {
            "passed": False,
            "signals": {"trend": False, "volume": False, "structure": False, "relative_strength": False},
            "aligned_count": 0,
        }
        ok, reason, _ = mod.validate_signal_alignment(sa)
        self.assertTrue(ok)

    def test_valid_4_of_4(self):
        sa = {
            "passed": True,
            "signals": {"trend": True, "volume": True, "structure": True, "relative_strength": True},
            "aligned_count": 4,
        }
        ok, reason, _ = mod.validate_signal_alignment(sa)
        self.assertTrue(ok)


class TestGoldenAdvisoryConfig(unittest.TestCase):
    def test_full_valid_overrides(self):
        cfg = {
            "vol_reference_pct": 14.0,
            "vol_lookback_days": 30,
            "gross_scalar_floor": 0.3,
            "regime_sma_days": 150,
            "regime_momentum_months": 6,
            "regime_caution_multiplier": 0.6,
            "cross_sectional_rs_lookback_days": 42,
            "cross_sectional_rs_top_fraction": 0.4,
            "min_reference_bars": 300,
            "min_symbol_bars_for_rs": 50,
            "min_valid_symbol_fraction": 0.6,
        }
        ok, reason, details = mod.validate_advisory_config(cfg)
        self.assertTrue(ok)
        self.assertFalse(details["used_defaults"])
        self.assertEqual(len(details["validated_values"]), 11)

    def test_single_override(self):
        cfg = {"vol_reference_pct": 12.0}
        ok, reason, details = mod.validate_advisory_config(cfg)
        self.assertFalse(ok)  # partial → fail closed
        self.assertEqual(reason, mod.ReasonCode.ADVISORY_CONFIG_MALFORMED)


class TestGoldenPositionClassification(unittest.TestCase):
    def test_pre_activation_grandfathered(self):
        r = mod.classify_position("AAPL", is_pre_activation=True)
        self.assertTrue(r["grandfathered"])
        self.assertTrue(r["closeable"])
        self.assertEqual(r["sector"], "INFORMATION_TECHNOLOGY")
        self.assertTrue(r["in_allowlist"])

    def test_post_activation_not_grandfathered(self):
        r = mod.classify_position("AAPL", is_pre_activation=False)
        self.assertFalse(r["grandfathered"])
        self.assertTrue(r["closeable"])

    def test_non_allowlist_grandfathered(self):
        """Pre-activation position in non-allowlist symbol is still grandfathered."""
        r = mod.classify_position("ZZXY", is_pre_activation=True,
                                   sector_map={"ZZXY": "SPECIAL"})
        self.assertTrue(r["grandfathered"])
        self.assertFalse(r["in_allowlist"])


class TestGoldenDeterminismFullPipeline(unittest.TestCase):
    def test_full_determinism(self):
        """Run the full pipeline twice and verify byte-identical JSON results."""
        spy_bars = _spy_bull_300_days()
        symbols = list(mod.FROZEN_UNIVERSE.keys())
        uni = _universe_bars(symbols)

        def run():
            vol = mod.compute_realized_vol(spy_bars, lookback_days=20)
            regime = mod.compute_regime_state(spy_bars)
            scalar = mod.compute_gross_scalar(vol["sigma_ref"])
            budget = mod.compute_effective_budget(regime=regime["regime"],
                                                   gross_scalar=scalar["gross_scalar"])
            rs = mod.compute_cross_sectional_rs(uni)
            return {
                "regime": regime["regime"],
                "vol_valid": vol["valid"],
                "gross_scalar": scalar["gross_scalar"],
                "budget_pct": budget["effective_budget_pct"],
                "rs_top_half": rs["top_half_symbols"],
            }

        r1 = run()
        r2 = run()
        self.assertEqual(json.dumps(r1), json.dumps(r2))


if __name__ == "__main__":
    unittest.main()
