"""
Phase 19B B2 — Volatility scalar unit tests.

R005/R011 — compute_realized_vol, compute_gross_scalar.
Includes B1_006 (malformed fail-closed) and B1_007 (variance floor) matrices.
"""

import json
import math
import unittest
import strategy_v1_1_core as mod


def _mk_bar(o, h, l, c, v=100):
    return {"open": o, "high": h, "low": l, "close": c, "volume": v}


def _mk_bars(closes, delta=0.5):
    return [_mk_bar(c - delta, c + delta, c - delta * 1.2, c) for c in closes]


# ══════════════════════════════════════════════════════════════════════════════
# B1_006 — 108 malformed surplus-history probe matrix
# ══════════════════════════════════════════════════════════════════════════════


MALFORMED_TYPES = [
    ("True", True),
    ("False", False),
    ("NaN", float("nan")),
    ("+Inf", float("inf")),
    ("-Inf", float("-inf")),
    ("zero", 0.0),
    ("negative", -1.0),
    ("None", None),
    ("string", "bad"),
]


class TestMalformedSurplus108(unittest.TestCase):
    """108 probes: 3 lengths × 4 positions × 9 types."""

    def test_all_108_fail_closed(self):
        vol_computed = 0
        insufficient = 0
        other = 0
        exceptions = 0

        for n_prices in [7, 8, 10]:
            for pos_label, pos in [("first", 0), ("middle", n_prices // 2),
                                    ("penultimate", n_prices - 2), ("final", n_prices - 1)]:
                for type_label, mal_val in MALFORMED_TYPES:
                    closes = [100.0 + i * 0.5 for i in range(n_prices)]
                    bars = _mk_bars(closes)
                    bars[pos]["close"] = mal_val
                    try:
                        r = mod.compute_realized_vol(bars, lookback_days=5)
                        if r["reason"] == "VOL_COMPUTED" or r["reason"] == mod.ReasonCode.VOL_COMPUTED:
                            vol_computed += 1
                        elif r["reason"] in (mod.ReasonCode.VOL_SCALAR_INSUFFICIENT_DATA,):
                            insufficient += 1
                        else:
                            other += 1
                    except Exception:
                        exceptions += 1

        self.assertEqual(exceptions, 0, msg="%d exceptions in 108 probes" % exceptions)
        self.assertEqual(vol_computed, 0, msg="%d VOL_COMPUTED in 108 malformed probes" % vol_computed)
        self.assertEqual(insufficient, 108, msg="expected 108 insufficient, got %d (%d other)" % (insufficient, other))

    def test_continuity_gap(self):
        """Valid bars separated by invalid bar → entire series rejected."""
        bars = (_mk_bars([100, 101, 102]) +
                [_mk_bar(103, 105, 98, "bad", 100)] +
                _mk_bars([104, 105, 106, 107, 108, 109, 110]))
        rets = mod.compute_daily_log_returns(bars)
        self.assertEqual(len(rets), 0, msg="continuity gap should produce empty returns")
        r = mod.compute_realized_vol(bars, lookback_days=5)
        self.assertEqual(r["reason"], mod.ReasonCode.VOL_SCALAR_INSUFFICIENT_DATA)


# ══════════════════════════════════════════════════════════════════════════════
# B1_007 — Variance-floor matrix
# ══════════════════════════════════════════════════════════════════════════════


class TestVarianceFloor(unittest.TestCase):
    """B1_007: constant return series correctly classified as DEGENERATE."""

    def test_identical_prices(self):
        bars = _mk_bars([100.0] * 21)
        r = mod.compute_realized_vol(bars, lookback_days=20)
        self.assertFalse(r["valid"])
        self.assertEqual(r["reason"], mod.ReasonCode.VOL_DEGENERATE_SERIES)

    def test_constant_positive_log_returns(self):
        """Exp growth: mathematically identical log returns → DEGENERATE."""
        closes = [100.0 * math.exp(0.001 * i) for i in range(21)]
        bars = _mk_bars(closes)
        r = mod.compute_realized_vol(bars, lookback_days=20)
        self.assertEqual(r["reason"], mod.ReasonCode.VOL_DEGENERATE_SERIES,
                         msg="constant +log returns should be DEGENERATE, got %s" % r["reason"])

    def test_constant_negative_log_returns(self):
        """Exp decay: mathematically identical log returns → DEGENERATE."""
        closes = [100.0 * math.exp(-0.001 * i) for i in range(21)]
        bars = _mk_bars(closes)
        r = mod.compute_realized_vol(bars, lookback_days=20)
        self.assertEqual(r["reason"], mod.ReasonCode.VOL_DEGENERATE_SERIES,
                         msg="constant -log returns should be DEGENERATE, got %s" % r["reason"])

    def test_varying_returns_still_computable(self):
        """Genuine variance must remain computable."""
        bars = _mk_bars([100.0 + i * 0.5 for i in range(21)])
        r = mod.compute_realized_vol(bars, lookback_days=20)
        self.assertEqual(r["reason"], mod.ReasonCode.VOL_COMPUTED,
                         msg="varying returns should be COMPUTED, got %s" % r["reason"])
        self.assertTrue(r["valid"])

    def test_variance_floor_present(self):
        """Verify variance_floor computation exists in source."""
        import inspect
        src = inspect.getsource(mod.compute_realized_vol)
        self.assertIn("variance_floor", src)
        self.assertIn("math.ulp", src)

    def test_lookback5_identical(self):
        bars = _mk_bars([50.0] * 10)
        r = mod.compute_realized_vol(bars, lookback_days=5)
        self.assertEqual(r["reason"], mod.ReasonCode.VOL_DEGENERATE_SERIES)

    def test_lookback5_varying(self):
        bars = _mk_bars([50.0 + i * 0.5 for i in range(10)])
        r = mod.compute_realized_vol(bars, lookback_days=5)
        self.assertEqual(r["reason"], mod.ReasonCode.VOL_COMPUTED)

    def test_minimal_variance_but_varying(self):
        """Extremely tiny but genuine variance → might be DEGENERATE or COMPUTED depending on floor."""
        # Use a very small step
        closes = [100.0 + i * 1e-7 for i in range(21)]
        bars = _mk_bars(closes)
        r = mod.compute_realized_vol(bars, lookback_days=20)
        self.assertIn(r["reason"], [mod.ReasonCode.VOL_DEGENERATE_SERIES,
                                     mod.ReasonCode.VOL_COMPUTED])
        # Either is acceptable: tiny variance may or may not exceed ULP floor


# ══════════════════════════════════════════════════════════════════════════════
# History boundary matrix
# ══════════════════════════════════════════════════════════════════════════════


class TestHistoryBoundary(unittest.TestCase):
    """Boundary matrix: lookback=5, 0-8 valid varying prices."""

    LOOKBACK = 5

    def _probe(self, n):
        bars = _mk_bars([100.0 + i * 0.5 for i in range(n)]) if n > 0 else []
        return mod.compute_realized_vol(bars, self.LOOKBACK)

    def test_zero_prices(self):
        r = self._probe(0)
        self.assertFalse(r["valid"])
        self.assertEqual(r["reason"], mod.ReasonCode.VOL_SCALAR_INSUFFICIENT_DATA)

    def test_one_price(self):
        r = self._probe(1)
        self.assertFalse(r["valid"])
        self.assertEqual(r["reason"], mod.ReasonCode.VOL_SCALAR_INSUFFICIENT_DATA)

    def test_two_prices(self):
        r = self._probe(2)
        self.assertFalse(r["valid"])
        self.assertEqual(r["reason"], mod.ReasonCode.VOL_SCALAR_INSUFFICIENT_DATA)

    def test_three_prices(self):
        r = self._probe(3)
        self.assertFalse(r["valid"])
        self.assertEqual(r["reason"], mod.ReasonCode.VOL_SCALAR_INSUFFICIENT_DATA)

    def test_four_prices(self):
        r = self._probe(4)
        self.assertFalse(r["valid"])
        self.assertEqual(r["reason"], mod.ReasonCode.VOL_SCALAR_INSUFFICIENT_DATA)

    def test_five_prices(self):
        r = self._probe(5)
        self.assertFalse(r["valid"])
        self.assertEqual(r["reason"], mod.ReasonCode.VOL_SCALAR_INSUFFICIENT_DATA)

    def test_six_prices(self):
        r = self._probe(6)
        self.assertTrue(r["valid"])
        self.assertEqual(r["reason"], mod.ReasonCode.VOL_COMPUTED)
        self.assertIsNotNone(r["sigma_ref"])

    def test_seven_prices(self):
        r = self._probe(7)
        self.assertTrue(r["valid"])
        self.assertEqual(r["reason"], mod.ReasonCode.VOL_COMPUTED)

    def test_eight_prices(self):
        r = self._probe(8)
        self.assertTrue(r["valid"])
        self.assertEqual(r["reason"], mod.ReasonCode.VOL_COMPUTED)

    def test_no_partial_window(self):
        """5 prices = 4 returns. lookback=5. Must be INSUFFICIENT, not computed with 4."""
        bars = _mk_bars([10, 11, 12, 13, 14])
        r = mod.compute_realized_vol(bars, lookback_days=5)
        self.assertFalse(r["valid"])
        self.assertEqual(r["reason"], mod.ReasonCode.VOL_SCALAR_INSUFFICIENT_DATA)


# ══════════════════════════════════════════════════════════════════════════════
# gross_scalar
# ══════════════════════════════════════════════════════════════════════════════


class TestGrossScalarExtended(unittest.TestCase):
    def test_default_floor(self):
        r = mod.compute_gross_scalar(1.28)  # 0.16/1.28 = 0.125 < 0.25
        self.assertAlmostEqual(r["gross_scalar"], 0.25)
        self.assertTrue(r["clamped"])

    def test_ceiling(self):
        r = mod.compute_gross_scalar(0.10)  # 0.16/0.10 = 1.6 > 1.0
        self.assertAlmostEqual(r["gross_scalar"], 1.0)
        self.assertTrue(r["clamped"])

    def test_nominal_mid(self):
        r = mod.compute_gross_scalar(0.20)  # 0.16/0.20 = 0.8
        self.assertAlmostEqual(r["gross_scalar"], 0.8)
        self.assertFalse(r["clamped"])

    def test_custom_vol_reference(self):
        r = mod.compute_gross_scalar(0.20, vol_reference_pct=10.0)  # 0.10/0.20 = 0.5
        self.assertAlmostEqual(r["gross_scalar"], 0.5)

    def test_custom_floor(self):
        r = mod.compute_gross_scalar(2.0, floor=0.5)
        self.assertAlmostEqual(r["gross_scalar"], 0.5)

    def test_boolean_sigma_rejected(self):
        r = mod.compute_gross_scalar(True)
        self.assertEqual(r["reason"], mod.ReasonCode.VOL_SCALAR_INSUFFICIENT_DATA)


class TestVolDeterminism(unittest.TestCase):
    """compute_realized_vol must be deterministic: same input → same output."""

    def test_deterministic_repeat(self):
        bars = _mk_bars([100.0 + i * 0.5 for i in range(30)])
        r1 = mod.compute_realized_vol(bars, lookback_days=20)
        r2 = mod.compute_realized_vol(bars, lookback_days=20)
        self.assertEqual(json.dumps(r1), json.dumps(r2),
                         msg="compute_realized_vol must be deterministic")
        self.assertTrue(r1["valid"])
        self.assertIsNotNone(r1["sigma_ref"])

    def test_deterministic_insufficient(self):
        bars = _mk_bars([100.0 + i * 0.5 for i in range(4)])
        r1 = mod.compute_realized_vol(bars, lookback_days=5)
        r2 = mod.compute_realized_vol(bars, lookback_days=5)
        self.assertEqual(json.dumps(r1), json.dumps(r2))
        self.assertFalse(r1["valid"])
        self.assertEqual(r1["reason"], mod.ReasonCode.VOL_SCALAR_INSUFFICIENT_DATA)

    def test_deterministic_degenerate(self):
        bars = _mk_bars([100.0 * math.exp(0.001 * i) for i in range(21)])
        r1 = mod.compute_realized_vol(bars, lookback_days=20)
        r2 = mod.compute_realized_vol(bars, lookback_days=20)
        self.assertEqual(json.dumps(r1), json.dumps(r2))
        self.assertEqual(r1["reason"], mod.ReasonCode.VOL_DEGENERATE_SERIES)


if __name__ == "__main__":
    unittest.main()
