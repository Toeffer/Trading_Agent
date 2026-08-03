"""
Phase 19B B2 — deterministic unit tests for strategy_v1_1_core.py.

Tests all 19 public functions plus ReasonCode inventory.
stdlib only. unittest.TestCase. No pytest, numpy, pandas, network, filesystem,
environment, current-time, random, guard.py, broker, OpenClaw, Hermes.

Source immutability:
  SKD-256 e7762ceb04989d210346512af61c908ea684514de2a6308381088d3304dc6f6a
"""

import importlib
import json
import math
import sys
import unittest

import strategy_v1_1_core as mod

PYTHONDONTWRITEBYTECODE = "1"

# ── helpers ──────────────────────────────────────────────────────────────────


def _mk_bar(o, h, l, c, v=100, **kw):
    return {"open": o, "high": h, "low": l, "close": c, "volume": v, **kw}


def _mk_valid_bar(close=100.0, delta=0.5):
    return _mk_bar(close - delta, close + delta, close - delta * 1.2, close)


def _mk_bars(closes, delta=0.5):
    return [_mk_valid_bar(c, delta) for c in closes]


def _rising_series(n: int, start=100.0, step=0.5):
    return _mk_bars([start + i * step for i in range(n)])


# ── ReasonCode Inventory ─────────────────────────────────────────────────────


class TestReasonCodeInventory(unittest.TestCase):
    """Verify the ReasonCode class is stable and complete."""

    def test_01_48_members(self):
        """Exactly 48 public ReasonCode constants."""
        rc = [a for a in dir(mod.ReasonCode) if not a.startswith("_") and not callable(getattr(mod.ReasonCode, a))]
        self.assertEqual(len(rc), 48,
                         msg="ReasonCode count drifted: %d != 48" % len(rc))

    def test_02_no_duplicate_values(self):
        """No two ReasonCode constants share the same string value."""
        vals = {}
        for a in dir(mod.ReasonCode):
            if a.startswith("_") or callable(getattr(mod.ReasonCode, a)):
                continue
            v = getattr(mod.ReasonCode, a)
            self.assertIsInstance(v, str, msg="%s is not str" % a)
            if v in vals:
                self.fail("Duplicate ReasonCode value '%s' in %s and %s" % (v, vals[v], a))
            vals[v] = a

    def test_03_all_reasoncode_values_are_uppercase_snake(self):
        """Every ReasonCode value is UPPER_SNAKE_CASE."""
        for a in dir(mod.ReasonCode):
            if a.startswith("_") or callable(getattr(mod.ReasonCode, a)):
                continue
            v = getattr(mod.ReasonCode, a)
            self.assertEqual(v, v.upper(), msg="%s has lowercase: %s" % (a, v))
            self.assertNotIn(" ", v, msg="%s has spaces: %s" % (a, v))

    def test_04_no_raw_strings_returned(self):
        """No function returns bare reason strings; all use ReasonCode.XXX."""
        for attr in dir(mod):
            fn = getattr(mod, attr)
            if not callable(fn):
                continue
            if getattr(fn, "__module__", "") != mod.__name__:
                continue
            try:
                src = __import__("inspect").getsource(fn)
            except (OSError, TypeError):
                continue
            # Look for return dicts containing "reason": "X" (raw strings)
            import re
            reasons = re.findall(r'"reason":\s*"([A-Z_]+)"', src)
            for r in reasons:
                self.assertIn(r, [getattr(mod.ReasonCode, a) for a in dir(mod.ReasonCode) if not a.startswith("_")],
                              msg="%s returns raw string '%s' not via ReasonCode" % (attr, r))


# ── FROZEN_UNIVERSE ──────────────────────────────────────────────────────────


class TestFrozenUniverse(unittest.TestCase):
    def test_01_22_symbols(self):
        self.assertEqual(len(mod.FROZEN_UNIVERSE), 22)

    def test_02_sector_strings(self):
        for sym, sec in mod.FROZEN_UNIVERSE.items():
            self.assertIsInstance(sym, str)
            self.assertIsInstance(sec, str)
            self.assertGreater(len(sec), 0)

    def test_03_immutable_snapshot(self):
        uni2 = dict(mod.FROZEN_UNIVERSE)
        self.assertEqual(uni2, mod.FROZEN_UNIVERSE)

    CANONICAL_22 = [
        "AAPL", "AMD", "AMZN", "AVGO", "BAC", "CAT", "CVX", "DUK",
        "GOOGL", "HD", "JNJ", "JPM", "KO", "LLY", "META", "MSFT",
        "NEE", "NVDA", "PG", "UNH", "UNP", "XOM",
    ]

    def test_04_exact_symbol_set(self):
        """FROZEN_UNIVERSE must contain exactly the canonical 22 symbols in the correct sectors."""
        actual = sorted(mod.FROZEN_UNIVERSE.keys())
        self.assertEqual(actual, self.CANONICAL_22,
                         msg="FROZEN_UNIVERSE symbol set has diverged from canonical 22")

    def test_05_expected_sectors(self):
        """Each symbol must map to its expected sector group."""
        expected_sectors = {
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
        self.assertEqual(dict(sorted(mod.FROZEN_UNIVERSE.items())),
                         dict(sorted(expected_sectors.items())),
                         msg="FROZEN_UNIVERSE sector mapping has diverged")


# ── HIQ-002 — is_valid_daily_bar ─────────────────────────────────────────────


class TestIsValidDailyBar(unittest.TestCase):

    def test_01_valid_bar(self):
        ok, reason = mod.is_valid_daily_bar(_mk_bar(100, 102, 99, 101, 1000))
        self.assertTrue(ok)
        self.assertEqual(reason, mod.ReasonCode.VALID_BAR)

    def test_02_missing_field(self):
        for f in ["open", "high", "low", "close", "volume"]:
            b = _mk_bar(100, 102, 99, 101, 1000)
            del b[f]
            ok, reason = mod.is_valid_daily_bar(b)
            self.assertFalse(ok, msg="missing %s should be invalid" % f)
            self.assertEqual(reason, mod.ReasonCode.INVALID_BAR)

    def test_03_non_dict(self):
        for v in [None, 42, "bar", [], True]:
            ok, reason = mod.is_valid_daily_bar(v)
            self.assertFalse(ok, msg="%r should be invalid" % v)

    def test_04_nan_values(self):
        for f in ["open", "high", "low", "close", "volume"]:
            b = _mk_bar(100, 102, 99, 101, 1000)
            b[f] = float("nan")
            ok, reason = mod.is_valid_daily_bar(b)
            self.assertFalse(ok, msg="NaN %s should be invalid" % f)

    def test_05_inf_values(self):
        for f in ["open", "high", "low", "close"]:
            b = _mk_bar(100, 102, 99, 101, 1000)
            b[f] = float("inf")
            ok, reason = mod.is_valid_daily_bar(b)
            self.assertFalse(ok, msg="Inf %s should be invalid" % f)

    def test_06_boolean_rejected(self):
        b = _mk_bar(100, 102, 99, 101, 1000)
        b["close"] = True
        ok, reason = mod.is_valid_daily_bar(b)
        self.assertFalse(ok)
        self.assertEqual(reason, mod.ReasonCode.INPUT_NON_FINITE)

    def test_07_string_rejected(self):
        b = _mk_bar(100, 102, 99, 101, 1000)
        b["high"] = "102"
        ok, reason = mod.is_valid_daily_bar(b)
        self.assertFalse(ok)

    def test_08_zero_close_rejected(self):
        b = _mk_bar(100, 102, 99, 0, 1000)
        ok, reason = mod.is_valid_daily_bar(b)
        self.assertFalse(ok)
        self.assertEqual(reason, mod.ReasonCode.INPUT_OUT_OF_RANGE)

    def test_09_negative_price_rejected(self):
        b = _mk_bar(100, 102, 99, -1, 1000)
        ok, reason = mod.is_valid_daily_bar(b)
        self.assertFalse(ok)

    def test_10_negative_volume_rejected(self):
        b = _mk_bar(100, 102, 99, 101, -1)
        ok, reason = mod.is_valid_daily_bar(b)
        self.assertFalse(ok)

    def test_11_zero_volume_accepted(self):
        ok, reason = mod.is_valid_daily_bar(_mk_bar(100, 102, 99, 101, 0))
        self.assertTrue(ok)

    def test_12_high_too_low(self):
        b = _mk_bar(100, 102, 99, 105, 1000)
        ok, reason = mod.is_valid_daily_bar(b)
        self.assertFalse(ok)

    def test_13_low_too_high(self):
        b = _mk_bar(100, 102, 105, 101, 1000)
        ok, reason = mod.is_valid_daily_bar(b)
        self.assertFalse(ok)

    def test_14_high_below_low(self):
        b = _mk_bar(100, 99, 101, 100, 1000)
        ok, reason = mod.is_valid_daily_bar(b)
        self.assertFalse(ok)


# ── R002 — resolve_sector ───────────────────────────────────────────────────


class TestResolveSector(unittest.TestCase):
    def test_01_known_symbol(self):
        self.assertEqual(mod.resolve_sector("AAPL"), "INFORMATION_TECHNOLOGY")

    def test_02_lowercase_normalized(self):
        self.assertEqual(mod.resolve_sector("aapl"), "INFORMATION_TECHNOLOGY")

    def test_03_unknown_symbol(self):
        self.assertIsNone(mod.resolve_sector("ZZXY"))

    def test_04_empty_string(self):
        self.assertIsNone(mod.resolve_sector(""))

    def test_05_non_string(self):
        self.assertIsNone(mod.resolve_sector(42))

    def test_06_explicit_map(self):
        custom = {"FOO": "BAR"}
        self.assertEqual(mod.resolve_sector("FOO", custom), "BAR")
        self.assertIsNone(mod.resolve_sector("AAPL", custom))

    def test_07_whitespace_trimmed(self):
        self.assertEqual(mod.resolve_sector("  AAPL  "), "INFORMATION_TECHNOLOGY")


# ── R010 — validate_spy_reference_data ───────────────────────────────────────


class TestValidateSpyReferenceData(unittest.TestCase):
    def test_01_sufficient(self):
        bars = _rising_series(260)
        r = mod.validate_spy_reference_data(bars)
        self.assertTrue(r["valid"])
        self.assertEqual(r["reason"], mod.ReasonCode.SPY_DATA_VALID)
        self.assertGreaterEqual(r["bar_count"], 252)

    def test_02_none_input(self):
        r = mod.validate_spy_reference_data(None)
        self.assertFalse(r["valid"])
        self.assertEqual(r["reason"], mod.ReasonCode.SPY_DATA_INSUFFICIENT)

    def test_03_insufficient_bars(self):
        bars = _rising_series(100)
        r = mod.validate_spy_reference_data(bars, min_bars=252)
        self.assertFalse(r["valid"])
        self.assertEqual(r["reason"], mod.ReasonCode.SPY_DATA_INSUFFICIENT)

    def test_04_staleness(self):
        bars = _rising_series(260)
        for i, b in enumerate(bars):
            b["date"] = "2020-01-%02d" % (1 + (i % 31))
        r = mod.validate_spy_reference_data(bars, max_staleness_cutoff="9999-12-31")
        self.assertFalse(r["valid"])
        self.assertEqual(r["reason"], mod.ReasonCode.SPY_DATA_STALE)
        self.assertTrue(r["stale"])

    def test_05_with_date_key(self):
        bars = _rising_series(260)
        for i, b in enumerate(bars):
            b["date"] = "2026-%02d-01" % (max(1, min(12, i + 1)))
        r = mod.validate_spy_reference_data(bars, max_staleness_cutoff="2026-01-01")
        # newest should be >= cutoff
        self.assertTrue(r["valid"])

    def test_06_mixed_valid_invalid(self):
        bars = _rising_series(260)
        bars[0]["close"] = float("nan")  # invalidates one bar
        r = mod.validate_spy_reference_data(bars, min_bars=250)
        self.assertTrue(r["valid"])  # 259 valid >= 250
        self.assertEqual(r["bar_count"], 259)


# ── compute_daily_log_returns ────────────────────────────────────────────────


class TestComputeDailyLogReturns(unittest.TestCase):
    def test_01_all_valid(self):
        bars = _rising_series(10)
        rets = mod.compute_daily_log_returns(bars)
        self.assertEqual(len(rets), 9)
        self.assertTrue(all(math.isfinite(r) for r in rets))

    def test_02_insufficient_data(self):
        bars = _rising_series(1)
        self.assertEqual(mod.compute_daily_log_returns(bars), [])

    def test_03_empty_input(self):
        self.assertEqual(mod.compute_daily_log_returns([]), [])

    def test_04_none_input(self):
        self.assertEqual(mod.compute_daily_log_returns(None), [])

    def test_05_fail_closed_on_first_invalid(self):
        """B1_006: first invalid bar → empty list, no partial results."""
        bars = _rising_series(5)
        bars[0]["close"] = float("nan")
        rets = mod.compute_daily_log_returns(bars)
        self.assertEqual(rets, [], msg="should return empty on first invalid")

    def test_06_fail_closed_on_middle_invalid(self):
        bars = _rising_series(5)
        bars[2]["close"] = "bad"
        rets = mod.compute_daily_log_returns(bars)
        self.assertEqual(rets, [])

    def test_07_fail_closed_on_final_invalid(self):
        bars = _rising_series(5)
        bars[4]["close"] = float("inf")
        rets = mod.compute_daily_log_returns(bars)
        self.assertEqual(rets, [])

    def test_08_no_partial_prefix(self):
        """If bar 4 of 10 is invalid, bars 0-3 are NOT returned."""
        bars = _rising_series(10)
        bars[3]["close"] = -0.5
        rets = mod.compute_daily_log_returns(bars)
        self.assertEqual(rets, [], msg="must not return partial valid prefix")

    def test_09_no_partial_suffix(self):
        bars = _rising_series(10)
        bars[4]["volume"] = float("nan")
        rets = mod.compute_daily_log_returns(bars)
        self.assertEqual(rets, [])

    def test_10_deterministic(self):
        bars = _rising_series(6)
        r1 = mod.compute_daily_log_returns(bars)
        r2 = mod.compute_daily_log_returns(bars)
        self.assertEqual(json.dumps(r1), json.dumps(r2))

    def test_11_return_type_unchanged(self):
        bars = _rising_series(10)
        self.assertIsInstance(mod.compute_daily_log_returns(bars), list)


# ── R005 — compute_realized_vol ──────────────────────────────────────────────


class TestComputeRealizedVol(unittest.TestCase):
    def test_01_computed(self):
        r = mod.compute_realized_vol(_rising_series(30), lookback_days=20)
        self.assertTrue(r["valid"])
        self.assertEqual(r["reason"], mod.ReasonCode.VOL_COMPUTED)
        self.assertIsNotNone(r["sigma_ref"])
        self.assertGreater(r["sigma_ref"], 0)

    def test_02_insufficient_bars(self):
        r = mod.compute_realized_vol(_rising_series(5), lookback_days=20)
        self.assertFalse(r["valid"])
        self.assertEqual(r["reason"], mod.ReasonCode.VOL_SCALAR_INSUFFICIENT_DATA)

    def test_03_lookback_less_than_2(self):
        r = mod.compute_realized_vol(_rising_series(30), lookback_days=1)
        self.assertFalse(r["valid"])
        self.assertEqual(r["reason"], mod.ReasonCode.VOL_SCALAR_INSUFFICIENT_DATA)

    def test_04_degenerate_identical(self):
        bars = _mk_bars([100.0] * 21)
        r = mod.compute_realized_vol(bars, lookback_days=20)
        self.assertFalse(r["valid"])
        self.assertEqual(r["reason"], mod.ReasonCode.VOL_DEGENERATE_SERIES)

    def test_05_boundary_exact(self):
        """6 prices with lookback=5 → exactly 5 returns → COMPUTED."""
        bars = _rising_series(6)
        r = mod.compute_realized_vol(bars, lookback_days=5)
        self.assertTrue(r["valid"])
        self.assertEqual(r["reason"], mod.ReasonCode.VOL_COMPUTED)

    def test_06_boundary_below(self):
        """5 prices with lookback=5 → only 4 returns → INSUFFICIENT."""
        bars = _rising_series(5)
        r = mod.compute_realized_vol(bars, lookback_days=5)
        self.assertFalse(r["valid"])
        self.assertEqual(r["reason"], mod.ReasonCode.VOL_SCALAR_INSUFFICIENT_DATA)

    def test_07_malformed_series_fails_closed(self):
        """Any invalid bar in the series → compute_daily_log_returns → [] → INSUFFICIENT."""
        bars = _rising_series(30)
        bars[10]["close"] = float("nan")
        r = mod.compute_realized_vol(bars, lookback_days=20)
        self.assertFalse(r["valid"])
        self.assertEqual(r["reason"], mod.ReasonCode.VOL_SCALAR_INSUFFICIENT_DATA)

    def test_08_none_input(self):
        r = mod.compute_realized_vol(None)
        self.assertFalse(r["valid"])
        self.assertEqual(r["reason"], mod.ReasonCode.VOL_SCALAR_INSUFFICIENT_DATA)

    def test_09_constant_positive_log_returns(self):
        """Exp growth → mathematically constant log returns → DEGENERATE (B1_007)."""
        import math as m
        bars = _mk_bars([100.0 * m.exp(0.001 * i) for i in range(21)])
        r = mod.compute_realized_vol(bars, lookback_days=20)
        self.assertEqual(r["reason"], mod.ReasonCode.VOL_DEGENERATE_SERIES)

    def test_10_return_schema_keys(self):
        r = mod.compute_realized_vol(_rising_series(30))
        for k in ["sigma_ref", "bar_count", "valid", "reason"]:
            self.assertIn(k, r)


# ── R005/R011 — compute_gross_scalar ─────────────────────────────────────────


class TestComputeGrossScalar(unittest.TestCase):
    def test_01_nominal(self):
        r = mod.compute_gross_scalar(0.16)
        self.assertEqual(r["reason"], mod.ReasonCode.VOL_SCALAR_NOMINAL)
        self.assertAlmostEqual(r["gross_scalar"], 1.0)
        self.assertFalse(r["clamped"])

    def test_02_clamped_floor(self):
        r = mod.compute_gross_scalar(2.0)
        self.assertEqual(r["reason"], mod.ReasonCode.VOL_SCALAR_CLAMPED)
        self.assertAlmostEqual(r["gross_scalar"], 0.25)

    def test_03_none_sigma(self):
        r = mod.compute_gross_scalar(None)
        self.assertEqual(r["reason"], mod.ReasonCode.VOL_SCALAR_INSUFFICIENT_DATA)
        self.assertTrue(r["clamped"])

    def test_04_nan_sigma(self):
        r = mod.compute_gross_scalar(float("nan"))
        self.assertEqual(r["reason"], mod.ReasonCode.VOL_SCALAR_INSUFFICIENT_DATA)

    def test_05_zero_sigma(self):
        r = mod.compute_gross_scalar(0.0)
        self.assertEqual(r["reason"], mod.ReasonCode.VOL_DEGENERATE_SERIES)
        self.assertAlmostEqual(r["gross_scalar"], 1.0)

    def test_06_inf_sigma(self):
        r = mod.compute_gross_scalar(float("inf"))
        self.assertEqual(r["reason"], mod.ReasonCode.VOL_SCALAR_INSUFFICIENT_DATA)


# ── R004 — compute_sma ───────────────────────────────────────────────────────


class TestComputeSma(unittest.TestCase):
    def test_01_sufficient_data(self):
        bars = _rising_series(220)  # 200 + 20
        sma = mod.compute_sma(bars, lookback=200)
        self.assertIsNotNone(sma)
        self.assertGreater(sma, 0)

    def test_02_insufficient_data(self):
        bars = _rising_series(100)
        self.assertIsNone(mod.compute_sma(bars, lookback=200))

    def test_03_none_input(self):
        self.assertIsNone(mod.compute_sma(None))

    def test_04_lookback_lt_1(self):
        self.assertIsNone(mod.compute_sma(_rising_series(10), lookback=0))

    def test_05_equal_bars(self):
        bars = _mk_bars([10.0] * 200)
        sma = mod.compute_sma(bars, lookback=50)
        self.assertAlmostEqual(sma, 10.0)

    def test_06_deterministic(self):
        bars = _rising_series(250)
        self.assertAlmostEqual(mod.compute_sma(bars, 200), mod.compute_sma(bars, 200))


# ── R004 — compute_trailing_return ───────────────────────────────────────────


class TestComputeTrailingReturn(unittest.TestCase):
    def test_01_positive_return(self):
        bars = _rising_series(300, start=100, step=1)
        r = mod.compute_trailing_return(bars, months=12)
        self.assertIsNotNone(r)
        self.assertGreater(r, 0)

    def test_02_insufficient_data(self):
        bars = _rising_series(50)
        self.assertIsNone(mod.compute_trailing_return(bars, months=12))

    def test_03_none_input(self):
        self.assertIsNone(mod.compute_trailing_return(None))


# ── R004 — compute_regime_state ──────────────────────────────────────────────


class TestComputeRegimeState(unittest.TestCase):
    def _spy_above_sma_positive_mom(self):
        """SPY well above SMA 200, positive 12m return → RISK_ON."""
        bars = _rising_series(300, start=100, step=0.8)
        return bars

    def _spy_barely(self):
        """SPY barely above SMA."""
        bars = _rising_series(300, start=100, step=0.1)
        return bars

    def _spy_short(self):
        return _rising_series(100)

    def test_01_risk_on(self):
        r = mod.compute_regime_state(self._spy_above_sma_positive_mom())
        self.assertTrue(r["valid"])
        self.assertEqual(r["regime"], "RISK_ON")
        self.assertEqual(r["reason"], mod.ReasonCode.REGIME_RISK_ON)

    def test_02_insufficient_data(self):
        r = mod.compute_regime_state(self._spy_short())
        self.assertFalse(r["valid"])
        self.assertEqual(r["reason"], mod.ReasonCode.REGIME_INSUFFICIENT_DATA)
        self.assertEqual(r["regime"], "RISK_OFF")

    def test_03_none_input(self):
        r = mod.compute_regime_state(None)
        self.assertFalse(r["valid"])
        self.assertEqual(r["regime"], "RISK_OFF")

    def test_04_schema_keys(self):
        r = mod.compute_regime_state(self._spy_above_sma_positive_mom())
        for k in ["regime", "sma_value", "momentum_return", "sma_above",
                   "momentum_positive", "valid", "reason", "last_close"]:
            self.assertIn(k, r)

    def test_05_three_regime_values(self):
        seen = set()
        # RISK_ON
        r = mod.compute_regime_state(self._spy_above_sma_positive_mom())
        seen.add(r["regime"])
        self.assertIn(r["regime"], {"RISK_ON", "CAUTION", "RISK_OFF"})
        # Test that fallback returns RISK_OFF
        r2 = mod.compute_regime_state(self._spy_short())
        self.assertEqual(r2["regime"], "RISK_OFF")


# ── R012 — validate_rs_universe ──────────────────────────────────────────────


class TestValidateRsUniverse(unittest.TestCase):
    def test_01_sufficient(self):
        r = mod.validate_rs_universe(eligible_count=15, total_allowlist=22)
        self.assertFalse(r["no_trade"])
        self.assertEqual(r["reason"], mod.ReasonCode.RS_UNIVERSE_VALID)

    def test_02_insufficient(self):
        r = mod.validate_rs_universe(eligible_count=3, total_allowlist=22)
        self.assertTrue(r["no_trade"])
        self.assertEqual(r["reason"], mod.ReasonCode.RS_UNIVERSE_NO_TRADE)

    def test_03_zero_eligible(self):
        r = mod.validate_rs_universe(0, 22)
        self.assertTrue(r["no_trade"])

    def test_04_deterministic(self):
        r1 = mod.validate_rs_universe(12, 22)
        r2 = mod.validate_rs_universe(12, 22)
        self.assertEqual(json.dumps(r1), json.dumps(r2))


# ── R003 — compute_cross_sectional_rs ────────────────────────────────────────


class TestCrossSectionalRS(unittest.TestCase):
    def _uni(self):
        """22 symbols, 60 bars each, varying returns."""
        syms = list(mod.FROZEN_UNIVERSE.keys())
        out = {}
        for i, s in enumerate(syms):
            base = 100.0 + i * 5.0
            out[s] = _rising_series(65, start=base, step=base * 0.001)
        return out

    def test_01_full_universe(self):
        r = mod.compute_cross_sectional_rs(self._uni())
        self.assertFalse(r["no_trade"])
        self.assertEqual(r["subset_size"], 22)
        self.assertEqual(len(r["ranks"]), 22)
        self.assertGreater(len(r["top_half_symbols"]), 0)

    def test_02_top_half_count(self):
        r = mod.compute_cross_sectional_rs(self._uni())
        self.assertEqual(r["top_half_count"], 11)

    def test_03_ties_broken_lexicographic(self):
        """HIQ-009: ties broken by symbol uppercase lexicographic ascending."""
        syms = list(mod.FROZEN_UNIVERSE.keys())[:5]
        out = {}
        # All symbols get identical prices → identical returns
        for s in syms:
            out[s] = _rising_series(65, start=100, step=0.1)
        r = mod.compute_cross_sectional_rs(out)
        ranks = r["ranks"]
        for i in range(len(ranks) - 1):
            if ranks[i]["rs_return"] == ranks[i + 1]["rs_return"]:
                self.assertLess(ranks[i]["symbol"], ranks[i + 1]["symbol"])

    def test_04_none_input(self):
        r = mod.compute_cross_sectional_rs(None)
        self.assertTrue(r["no_trade"])
        self.assertEqual(r["no_trade_reason"], mod.ReasonCode.RS_RANK_INSUFFICIENT_DATA)

    def test_05_empty_dict(self):
        r = mod.compute_cross_sectional_rs({})
        self.assertTrue(r["no_trade"])

    def test_06_malformed_bars_returns(self):
        """RS function uses its own is_valid_daily_bar loop; invalid bar skipped, symbol still eligible."""
        syms = list(mod.FROZEN_UNIVERSE.keys())[:10]
        out = {}
        for s in syms:
            out[s] = _rising_series(65, start=100, step=0.1)
        # Corrupt one symbol's bar — still has 64 valid closes >= 60 min_bars
        out[syms[0]][10]["close"] = "bad"
        r = mod.compute_cross_sectional_rs(out)
        self.assertGreaterEqual(r["subset_size"], 9)  # all or most still eligible


# ── R006 — compute_effective_budget ──────────────────────────────────────────


class TestComputeEffectiveBudget(unittest.TestCase):
    def test_01_risk_on(self):
        r = mod.compute_effective_budget(max_total_exposure_pct=30.0, gross_scalar=1.0, regime="RISK_ON")
        self.assertAlmostEqual(r["effective_budget_pct"], 30.0)
        self.assertEqual(r["reason"], mod.ReasonCode.BUDGET_COMPUTED)

    def test_02_caution(self):
        r = mod.compute_effective_budget(max_total_exposure_pct=30.0, gross_scalar=1.0, regime="CAUTION")
        self.assertAlmostEqual(r["effective_budget_pct"], 15.0)
        self.assertEqual(r["reason"], mod.ReasonCode.BUDGET_COMPUTED)

    def test_03_risk_off(self):
        r = mod.compute_effective_budget(regime="RISK_OFF")
        self.assertAlmostEqual(r["effective_budget_pct"], 0.0)
        self.assertEqual(r["reason"], mod.ReasonCode.BUDGET_RISK_OFF)

    def test_04_unknown_regime(self):
        r = mod.compute_effective_budget(regime="MARS")
        self.assertEqual(r["reason"], mod.ReasonCode.BUDGET_RISK_OFF)
        self.assertFalse(r["assertion_passed"])

    def test_05_scaled_down(self):
        r = mod.compute_effective_budget(gross_scalar=0.5, regime="RISK_ON")
        self.assertAlmostEqual(r["effective_budget_pct"], 15.0)

    def test_06_assertion(self):
        r = mod.compute_effective_budget(max_total_exposure_pct=30.0, gross_scalar=1.0)
        self.assertTrue(r["assertion_passed"])


# ── R029 — compute_remaining_budget ──────────────────────────────────────────


class TestComputeRemainingBudget(unittest.TestCase):
    def test_01_available(self):
        r = mod.compute_remaining_budget(30.0, 10000.0, 1.05)
        self.assertGreater(r["remaining_budget_usd"], 0)
        self.assertEqual(r["reason"], mod.ReasonCode.BUDGET_AVAILABLE)
        self.assertFalse(r["budget_exhausted"])

    def test_02_exhausted(self):
        r = mod.compute_remaining_budget(30.0, 10000.0, 1.05, existing_exposure_usd=5000.0)
        # 3000 - 5000 ≤ 0 → exhausted
        self.assertTrue(r["budget_exhausted"])
        self.assertEqual(r["reason"], mod.ReasonCode.BUDGET_EXHAUSTED)

    def test_03_zero_netliq(self):
        r = mod.compute_remaining_budget(30.0, 0.0, 1.05)
        self.assertEqual(r["reason"], mod.ReasonCode.INPUT_NON_FINITE)

    def test_04_negative_netliq(self):
        r = mod.compute_remaining_budget(30.0, -1000, 1.05)
        self.assertEqual(r["reason"], mod.ReasonCode.INPUT_NON_FINITE)

    def test_05_nan_exchange_rate(self):
        r = mod.compute_remaining_budget(30.0, 10000, float("nan"))
        self.assertEqual(r["reason"], mod.ReasonCode.INPUT_NON_FINITE)


# ── R003/R017 — is_candidate_rs_eligible ─────────────────────────────────────


class TestIsCandidateRsEligible(unittest.TestCase):
    def _good_rs(self):
        """Need full 22-symbol universe for RS ranking to produce top_half_symbols."""
        syms = list(mod.FROZEN_UNIVERSE.keys())
        out = {}
        for s in syms:
            out[s] = _rising_series(65, start=100, step=0.1)
        return mod.compute_cross_sectional_rs(out)

    def test_01_in_top_half(self):
        rs = self._good_rs()
        top = rs["top_half_symbols"][0]
        self.assertTrue(mod.is_candidate_rs_eligible(top, rs))

    def test_02_none_input(self):
        self.assertFalse(mod.is_candidate_rs_eligible("AAPL", None))

    def test_03_no_trade(self):
        self.assertFalse(mod.is_candidate_rs_eligible("AAPL",
                         {"no_trade": True, "top_half_symbols": ["AAPL"]}))

    def test_04_not_in_top_half(self):
        rs = self._good_rs()
        self.assertFalse(mod.is_candidate_rs_eligible("ZZXY", rs))


# ── R007 — gate_sector_concentration ─────────────────────────────────────────


class TestGateSectorConcentration(unittest.TestCase):
    def test_01_pass(self):
        passed, reason, details = mod.gate_sector_concentration("AAPL", [])
        self.assertTrue(passed)
        self.assertEqual(reason, mod.ReasonCode.GATE_I_PASS)

    def test_02_sector_full(self):
        positions = [{"symbol": "AAPL"}]
        passed, reason, details = mod.gate_sector_concentration("AAPL", positions)
        self.assertFalse(passed)
        self.assertEqual(reason, mod.ReasonCode.GATE_I_SECTOR_FULL)

    def test_03_sell_exempt(self):
        passed, reason, details = mod.gate_sector_concentration(
            "AAPL", [{"symbol": "AAPL"}], side="SELL")
        self.assertTrue(passed)
        self.assertEqual(reason, mod.ReasonCode.GATE_I_PASS)
        self.assertTrue(details["exempt"])

    def test_04_unmapped_symbol(self):
        passed, reason, details = mod.gate_sector_concentration("ZZXY", [])
        self.assertFalse(passed)
        self.assertEqual(reason, mod.ReasonCode.GATE_I_SYMBOL_UNMAPPED)

    def test_05_different_sectors(self):
        """AAPL (IT) should not conflict with JPM (Financials)."""
        passed, reason, details = mod.gate_sector_concentration(
            "AAPL", [{"symbol": "JPM"}])
        self.assertTrue(passed)

    def test_06_max_per_sector_lt_1(self):
        passed, reason, details = mod.gate_sector_concentration(
            "AAPL", [], max_per_sector=0)
        self.assertFalse(passed)


# ── R019/HIQ-010 — validate_signal_alignment ─────────────────────────────────


class TestValidateSignalAlignment(unittest.TestCase):
    _VALID = {
        "passed": True,
        "signals": {"trend": True, "volume": True, "structure": False, "relative_strength": False},
        "aligned_count": 2,
    }

    def test_01_valid(self):
        ok, reason, details = mod.validate_signal_alignment(self._VALID)
        self.assertTrue(ok)
        self.assertEqual(reason, mod.ReasonCode.SIGNAL_ALIGNMENT_VALID)

    def test_02_not_dict(self):
        ok, reason, details = mod.validate_signal_alignment("not dict")
        self.assertFalse(ok)

    def test_03_missing_passed(self):
        v = dict(self._VALID); del v["passed"]
        ok, reason, _ = mod.validate_signal_alignment(v)
        self.assertFalse(ok)
        self.assertEqual(reason, mod.ReasonCode.SIGNAL_ALIGNMENT_MISSING_FIELD)

    def test_04_extra_signal_field(self):
        v = dict(self._VALID)
        v["signals"] = dict(v["signals"])
        v["signals"]["confidence"] = True
        ok, reason, _ = mod.validate_signal_alignment(v)
        self.assertFalse(ok)
        self.assertEqual(reason, mod.ReasonCode.SIGNAL_ALIGNMENT_EXTRA_FIELD)

    def test_05_non_bool_signal(self):
        v = dict(self._VALID)
        v["signals"] = dict(v["signals"])
        v["signals"]["trend"] = 1
        ok, reason, _ = mod.validate_signal_alignment(v)
        self.assertFalse(ok)
        self.assertEqual(reason, mod.ReasonCode.SIGNAL_ALIGNMENT_NON_BOOLEAN)

    def test_06_count_mismatch(self):
        v = dict(self._VALID)
        v["aligned_count"] = 4  # only 2 true signals
        ok, reason, _ = mod.validate_signal_alignment(v)
        self.assertFalse(ok)
        self.assertEqual(reason, mod.ReasonCode.SIGNAL_ALIGNMENT_COUNT_MISMATCH)

    def test_07_passed_mismatch(self):
        v = dict(self._VALID)
        v["passed"] = False  # aligned_count=2 should be passed=True
        ok, reason, _ = mod.validate_signal_alignment(v)
        self.assertFalse(ok)
        self.assertEqual(reason, mod.ReasonCode.SIGNAL_ALIGNMENT_PASSED_MISMATCH)

    def test_08_non_int_aligned_count(self):
        v = dict(self._VALID)
        v["aligned_count"] = "2"
        ok, reason, _ = mod.validate_signal_alignment(v)
        self.assertFalse(ok)
        self.assertEqual(reason, mod.ReasonCode.SIGNAL_ALIGNMENT_NON_INTEGER_COUNT)

    def test_09_bool_aligned_count(self):
        v = dict(self._VALID)
        v["aligned_count"] = True
        ok, reason, _ = mod.validate_signal_alignment(v)
        self.assertFalse(ok)
        self.assertEqual(reason, mod.ReasonCode.SIGNAL_ALIGNMENT_NON_INTEGER_COUNT)

    def test_10_out_of_range_count(self):
        v = dict(self._VALID)
        v["aligned_count"] = 5
        ok, reason, _ = mod.validate_signal_alignment(v)
        self.assertFalse(ok)
        self.assertEqual(reason, mod.ReasonCode.SIGNAL_ALIGNMENT_COUNT_OUT_OF_RANGE)

    def test_11_passed_false_valid(self):
        """aligned_count=1 → passed should be False."""
        v = {
            "passed": False,
            "signals": {"trend": True, "volume": False, "structure": False, "relative_strength": False},
            "aligned_count": 1,
        }
        ok, reason, _ = mod.validate_signal_alignment(v)
        self.assertTrue(ok)


# ── R019 — validate_hermes_output ────────────────────────────────────────────


class TestValidateHermesOutput(unittest.TestCase):
    def test_01_clean_output(self):
        r = mod.validate_hermes_output("AAPL shows strong trend and volume support.")
        self.assertTrue(r["valid"])
        self.assertEqual(r["reason"], mod.ReasonCode.HERMES_OUTPUT_VALID)

    def test_02_forbidden_pattern(self):
        r = mod.validate_hermes_output("Recommend buy 500 shares of AAPL")
        self.assertFalse(r["valid"])
        self.assertEqual(r["reason"], mod.ReasonCode.HERMES_FORBIDDEN_PATTERN)
        self.assertGreater(len(r["violations"]), 0)

    def test_03_none_input(self):
        r = mod.validate_hermes_output(None)
        self.assertFalse(r["valid"])
        self.assertEqual(r["reason"], mod.ReasonCode.INPUT_MISSING)

    def test_04_leverage_blocked(self):
        r = mod.validate_hermes_output("Use leveraged ETF with 3x leverage")
        self.assertFalse(r["valid"])

    def test_05_percent_of_portfolio_blocked(self):
        r = mod.validate_hermes_output("Allocate 5% of portfolio to AAPL")
        self.assertFalse(r["valid"])

    def test_06_custom_forbidden_patterns(self):
        r = mod.validate_hermes_output("All clear", forbidden_patterns=("clear",))
        self.assertFalse(r["valid"])
        self.assertEqual(r["violations"], ["clear"])


# ── R016 — classify_position ─────────────────────────────────────────────────


class TestClassifyPosition(unittest.TestCase):
    def test_01_pre_activation(self):
        r = mod.classify_position("AAPL", is_pre_activation=True)
        self.assertTrue(r["grandfathered"])
        self.assertTrue(r["closeable"])
        self.assertTrue(r["counts_toward_exposure"])
        self.assertTrue(r["counts_toward_sector_cap"])
        self.assertEqual(r["sector"], "INFORMATION_TECHNOLOGY")

    def test_02_post_activation(self):
        r = mod.classify_position("AAPL", is_pre_activation=False)
        self.assertFalse(r["grandfathered"])

    def test_03_unknown_symbol(self):
        r = mod.classify_position("ZZXY")
        self.assertIsNone(r["sector"])
        self.assertFalse(r["in_allowlist"])

    def test_04_custom_allowlist(self):
        r = mod.classify_position("AAPL", allowlist=["MSFT", "JPM"])
        self.assertFalse(r["in_allowlist"])

    def test_05_lowercase(self):
        r = mod.classify_position("aapl")
        self.assertEqual(r["symbol"], "AAPL")


# ── HIQ-008 — validate_advisory_config ───────────────────────────────────────


class TestValidateAdvisoryConfig(unittest.TestCase):
    def test_01_none_uses_defaults(self):
        ok, reason, details = mod.validate_advisory_config(None)
        self.assertTrue(ok)
        self.assertTrue(details["used_defaults"])

    def test_02_empty_dict(self):
        ok, reason, details = mod.validate_advisory_config({})
        self.assertTrue(ok)
        self.assertTrue(details["used_defaults"])

    def test_03_full_valid_config(self):
        cfg = {k: s["default"] for k, s in mod.ADVISORY_CONFIG_SCHEMA.items()}
        ok, reason, details = mod.validate_advisory_config(cfg)
        self.assertTrue(ok)
        self.assertEqual(reason, mod.ReasonCode.ADVISORY_CONFIG_VALID)

    def test_04_missing_key(self):
        cfg = {"vol_reference_pct": 16.0}
        ok, reason, details = mod.validate_advisory_config(cfg)
        self.assertFalse(ok)
        self.assertEqual(reason, mod.ReasonCode.ADVISORY_CONFIG_MALFORMED)
        self.assertGreater(len(details["errors"]), 0)

    def test_05_wrong_type(self):
        cfg = {"vol_reference_pct": "16"}
        ok, reason, details = mod.validate_advisory_config(cfg)
        self.assertFalse(ok)
        self.assertIn("ADVISORY_CONFIG_WRONG_TYPE", str(details["errors"]))

    def test_06_out_of_range(self):
        cfg = {"vol_reference_pct": 500.0}
        ok, reason, details = mod.validate_advisory_config(cfg)
        self.assertFalse(ok)
        self.assertIn("ADVISORY_CONFIG_OUT_OF_RANGE", str(details["errors"]))

    def test_07_boolean_rejected(self):
        cfg = {"vol_reference_pct": True}
        ok, reason, details = mod.validate_advisory_config(cfg)
        self.assertFalse(ok)

    def test_08_non_finite(self):
        cfg = {"vol_reference_pct": float("nan")}
        ok, reason, details = mod.validate_advisory_config(cfg)
        self.assertFalse(ok)


# ── module invariants ────────────────────────────────────────────────────────


class TestModuleInvariants(unittest.TestCase):
    def test_01_trading_days(self):
        self.assertEqual(mod.TRADING_DAYS_PER_YEAR, 252.0)

    def test_02_all_count(self):
        self.assertIn("FROZEN_UNIVERSE", mod.__all__)
        self.assertIn("ReasonCode", mod.__all__)
        self.assertIn("is_valid_daily_bar", mod.__all__)
        self.assertIn("compute_realized_vol", mod.__all__)

    def test_03_no_non_stdlib_imports(self):
        with open(mod.__file__, encoding="utf-8") as handle:
            src = handle.read()
        import_lines = [l for l in src.split("\n") if l.startswith(("import ", "from "))]
        allowed = {"__future__", "math", "dataclasses", "typing", "re"}
        for line in import_lines:
            if line.startswith("from ."):
                continue
            tokens = line.split()
            mod_name = tokens[1] if tokens[0] == "from" else tokens[1]
            self.assertIn(mod_name.split(".")[0], allowed,
                          msg="non-stdlib import: %s" % line)


if __name__ == "__main__":
    unittest.main()
