"""
Phase 19B B2 — Cross-sectional RS ranking unit tests.

R003/R028/R012 — compute_cross_sectional_rs, validate_rs_universe, is_candidate_rs_eligible.
HIQ-009 — tie-breaking.
"""

import json
import unittest
import strategy_v1_1_core as mod


def _mk_bar(o, h, l, c, v=100):
    return {"open": o, "high": h, "low": l, "close": c, "volume": v}


def _mk_bars(closes, delta=0.5):
    return [_mk_bar(c - delta, c + delta, c - delta * 1.2, c) for c in closes]


def _full_universe():
    """22 symbols, 65 bars each, varying returns."""
    syms = list(mod.FROZEN_UNIVERSE.keys())
    out = {}
    for i, s in enumerate(syms):
        base = 100.0 + i * 5.0
        out[s] = _mk_bars([base + j * 0.01 for j in range(65)])
    return out


class TestRSRanking(unittest.TestCase):
    def test_full_universe_ranks(self):
        r = mod.compute_cross_sectional_rs(_full_universe())
        self.assertFalse(r["no_trade"])
        self.assertEqual(r["subset_size"], 22)
        self.assertEqual(len(r["ranks"]), 22)
        self.assertEqual(r["top_half_count"], 11)

    def test_ranks_sorted_descending(self):
        r = mod.compute_cross_sectional_rs(_full_universe())
        for i in range(len(r["ranks"]) - 1):
            self.assertGreaterEqual(r["ranks"][i]["rs_return"],
                                     r["ranks"][i + 1]["rs_return"])

    def test_ties_broken_lexicographic(self):
        """HIQ-009: equal returns → sorted by symbol uppercase ascending."""
        syms = ["META", "GOOGL", "AMZN"]  # 3 symbols
        out = {}
        for s in syms:
            out[s] = _mk_bars([100.0 + j * 0.001 for j in range(65)])
        r = mod.compute_cross_sectional_rs(out)
        ranks = r["ranks"]
        for i in range(len(ranks) - 1):
            if abs(ranks[i]["rs_return"] - ranks[i + 1]["rs_return"]) < 1e-10:
                self.assertLess(ranks[i]["symbol"], ranks[i + 1]["symbol"],
                                msg="tie not broken by lexicographic: %s >= %s" %
                                    (ranks[i]["symbol"], ranks[i + 1]["symbol"]))

    def test_reason_codes_on_ranks(self):
        r = mod.compute_cross_sectional_rs(_full_universe())
        top = [x for x in r["ranks"] if x["top_half"]]
        bottom = [x for x in r["ranks"] if not x["top_half"]]
        self.assertGreater(len(top), 0)
        self.assertGreater(len(bottom), 0)
        for x in top:
            self.assertEqual(x["reason"], mod.ReasonCode.RS_RANK_TOP_HALF)
        for x in bottom:
            self.assertEqual(x["reason"], mod.ReasonCode.RS_RANK_NOT_TOP_HALF)

    def test_rs_universe_too_few(self):
        """Only 3 eligible out of 22 → RS_UNIVERSE_NO_TRADE."""
        syms = list(mod.FROZEN_UNIVERSE.keys())[:3]
        out = {}
        for s in syms:
            out[s] = _mk_bars([100 + j * 0.01 for j in range(65)])
        r = mod.compute_cross_sectional_rs(out)
        self.assertTrue(r["no_trade"])
        self.assertEqual(r["no_trade_reason"], mod.ReasonCode.RS_UNIVERSE_NO_TRADE)
        self.assertEqual(len(r["ranks"]), 0)


class TestRSInsufficient(unittest.TestCase):
    def test_none_input(self):
        r = mod.compute_cross_sectional_rs(None)
        self.assertTrue(r["no_trade"])
        self.assertEqual(r["no_trade_reason"], mod.ReasonCode.RS_RANK_INSUFFICIENT_DATA)

    def test_empty_dict(self):
        r = mod.compute_cross_sectional_rs({})
        self.assertTrue(r["no_trade"])

    def test_no_symbols_with_min_bars(self):
        syms = list(mod.FROZEN_UNIVERSE.keys())[:5]
        out = {}
        for s in syms:
            out[s] = _mk_bars([100])  # only 1 bar
        r = mod.compute_cross_sectional_rs(out)
        self.assertTrue(r["no_trade"])

    def test_malformed_bars_exclude_symbol(self):
        """RS function uses its own is_valid_daily_bar loop; invalid bars skipped.
        Symbol with 1 malformed bar (64 valid >= 60 min_bars) still eligible."""
        syms = ["AAPL", "MSFT", "NVDA", "META", "GOOGL"]
        out = {}
        for s in syms:
            out[s] = _mk_bars([100 + j * 0.1 for j in range(65)])
        out["AAPL"][10]["close"] = "broken"
        r = mod.compute_cross_sectional_rs(out)
        # All 5 symbols have >= 60 valid bars; subset_size is 5
        self.assertEqual(r["subset_size"], 5)
        # But 5/22 < 50% → no_trade=True
        self.assertTrue(r["no_trade"])


class TestRSValidateUniverse(unittest.TestCase):
    def test_at_threshold(self):
        """Exactly 50% of 22 = 11 → valid (no_trade=False)."""
        r = mod.validate_rs_universe(11, 22, min_fraction=0.5)
        self.assertFalse(r["no_trade"])

    def test_below_threshold(self):
        r = mod.validate_rs_universe(10, 22, min_fraction=0.5)
        self.assertTrue(r["no_trade"])

    def test_zero_allowlist(self):
        r = mod.validate_rs_universe(5, 0, min_fraction=0.5)
        # 0 total allowlist → no trade possible
        self.assertTrue(r["no_trade"])


class TestRSEligibility(unittest.TestCase):
    def test_in_top_half(self):
        r = mod.compute_cross_sectional_rs(_full_universe())
        top = r["top_half_symbols"][0]
        self.assertTrue(mod.is_candidate_rs_eligible(top, r))

    def test_not_in_top_half(self):
        r = mod.compute_cross_sectional_rs(_full_universe())
        self.assertFalse(mod.is_candidate_rs_eligible("ZZXY", r))

    def test_none_result(self):
        self.assertFalse(mod.is_candidate_rs_eligible("AAPL", None))

    def test_no_trade_true(self):
        self.assertFalse(mod.is_candidate_rs_eligible("AAPL",
                         {"no_trade": True, "top_half_symbols": ["AAPL"]}))


class TestRSDeterminism(unittest.TestCase):
    def test_deterministic(self):
        r1 = mod.compute_cross_sectional_rs(_full_universe())
        r2 = mod.compute_cross_sectional_rs(_full_universe())
        self.assertEqual(json.dumps(r1), json.dumps(r2))


if __name__ == "__main__":
    unittest.main()
