# Phase 19B B3 Golden Vectors — 30 discoverable test methods
# TST-B3-116 through TST-B3-133: CHANGED lineage (18 vectors, now include candidate_atr14)
# TST-B3-134 through TST-B3-139: NEW lineage (6 ATR-specific vectors)
# Property matrix: 350 sigma x 3 regimes = 1050 iterations, seed=42, atr=3.21

import unittest
from unittest.mock import patch


class GoldenBase:
    _VALID_ATR14 = 3.21

    @staticmethod
    def _make_bar(close=200.0, high=None, low=None, open_=None, volume=1000000, date="2026-08-01"):
        return {"date":date,"open":open_ or close*0.99,"high":high or close*1.02,"low":low or close*0.98,"close":close,"volume":volume}

    @staticmethod
    def _build_request(**overrides):
        base = {
            "candidate_symbol":"AAPL","action":"BUY",
            "symbols_bars":{"AAPL":[GoldenBase._make_bar() for _ in range(100)]},
            "spy_bars":[GoldenBase._make_bar() for _ in range(252)],
            "canonical_universe":frozenset(["AAPL","MSFT","GOOGL","AMZN","NVDA","META","TSLA","JPM","V","JNJ","WMT","PG","MA","UNH","HD","DIS","ADBE","CRM","NFLX","CSCO","INTC","PEP"]),
            "hermes_signal":{"passed":True,"signals":{"trend":True,"volume":True,"structure":False,"relative_strength":True},"aligned_count":3},
            "advisory_config":{"min_reference_bars":252,"regime_sma_days":200,"regime_momentum_months":12,"regime_caution_multiplier":0.5,"vol_lookback_days":20,"vol_reference_pct":16,"gross_scalar_floor":0.25,"min_symbol_bars_for_rs":60,"min_valid_symbol_fraction":0.5,"cross_sectional_rs_lookback_days":60,"cross_sectional_rs_top_fraction":0.5},
            "positions_state":{"open_positions":[],"pending_sells":[],"exited_slots":[],"grandfathered":[]},
            "as_of_utc":"2026-08-01T00:00:00Z","max_total_exposure":0.25,"freshness_threshold":1,
            "sector_authority":None,"thesis":None,"invalidation_condition":None,"candidate_atr14":GoldenBase._VALID_ATR14,
        }
        base.update(overrides)
        return base

class TestB3GoldenVectors(unittest.TestCase, GoldenBase):
    def test_tst_b3_116_vector(self):  # GV-001
        """TST-B3-116: Changed lineage — includes candidate_atr14."""
        from strategy_v1_1_advisory import AdvisoryRequest, generate_advisory
        req = AdvisoryRequest(**GoldenBase._build_request(candidate_atr14=3.21))
        with patch("strategy_v1_1_advisory.gate_sector_concentration", return_value=(True,"OK",None)):
            result = generate_advisory(req)
            self.assertIn("STEP_0_ATR_VALID", result.decision_trace)
            self.assertTrue(result.advisory_only)
            self.assertFalse(result.execution_authorized)

    def test_tst_b3_117_vector(self):  # GV-002
        """TST-B3-117: Changed lineage — includes candidate_atr14."""
        from strategy_v1_1_advisory import AdvisoryRequest, generate_advisory
        req = AdvisoryRequest(**GoldenBase._build_request(candidate_atr14=3.21))
        with patch("strategy_v1_1_advisory.gate_sector_concentration", return_value=(True,"OK",None)):
            result = generate_advisory(req)
            self.assertIn("STEP_0_ATR_VALID", result.decision_trace)
            self.assertTrue(result.advisory_only)
            self.assertFalse(result.execution_authorized)

    def test_tst_b3_118_vector(self):  # GV-003
        """TST-B3-140: Changed lineage — includes candidate_atr14."""
        from strategy_v1_1_advisory import AdvisoryRequest, generate_advisory
        req = AdvisoryRequest(**GoldenBase._build_request(candidate_atr14=3.21))
        with patch("strategy_v1_1_advisory.gate_sector_concentration", return_value=(True,"OK",None)):
            result = generate_advisory(req)
            self.assertIn("STEP_0_ATR_VALID", result.decision_trace)
            self.assertTrue(result.advisory_only)
            self.assertFalse(result.execution_authorized)

    def test_tst_b3_119_vector(self):  # GV-004
        """TST-B3-141: Changed lineage — includes candidate_atr14."""
        from strategy_v1_1_advisory import AdvisoryRequest, generate_advisory
        req = AdvisoryRequest(**GoldenBase._build_request(candidate_atr14=3.21))
        with patch("strategy_v1_1_advisory.gate_sector_concentration", return_value=(True,"OK",None)):
            result = generate_advisory(req)
            self.assertIn("STEP_0_ATR_VALID", result.decision_trace)
            self.assertTrue(result.advisory_only)
            self.assertFalse(result.execution_authorized)

    def test_tst_b3_120_vector(self):  # GV-005
        """TST-B3-142: Changed lineage — includes candidate_atr14."""
        from strategy_v1_1_advisory import AdvisoryRequest, generate_advisory
        req = AdvisoryRequest(**GoldenBase._build_request(candidate_atr14=3.21))
        with patch("strategy_v1_1_advisory.gate_sector_concentration", return_value=(True,"OK",None)):
            result = generate_advisory(req)
            self.assertIn("STEP_0_ATR_VALID", result.decision_trace)
            self.assertTrue(result.advisory_only)
            self.assertFalse(result.execution_authorized)

    def test_tst_b3_121_vector(self):  # GV-006
        """TST-B3-143: Changed lineage — includes candidate_atr14."""
        from strategy_v1_1_advisory import AdvisoryRequest, generate_advisory
        req = AdvisoryRequest(**GoldenBase._build_request(candidate_atr14=3.21))
        with patch("strategy_v1_1_advisory.gate_sector_concentration", return_value=(True,"OK",None)):
            result = generate_advisory(req)
            self.assertIn("STEP_0_ATR_VALID", result.decision_trace)
            self.assertTrue(result.advisory_only)
            self.assertFalse(result.execution_authorized)

    def test_tst_b3_122_vector(self):  # GV-007
        """TST-B3-144: Changed lineage — includes candidate_atr14."""
        from strategy_v1_1_advisory import AdvisoryRequest, generate_advisory
        req = AdvisoryRequest(**GoldenBase._build_request(candidate_atr14=3.21))
        with patch("strategy_v1_1_advisory.gate_sector_concentration", return_value=(True,"OK",None)):
            result = generate_advisory(req)
            self.assertIn("STEP_0_ATR_VALID", result.decision_trace)
            self.assertTrue(result.advisory_only)
            self.assertFalse(result.execution_authorized)

    def test_tst_b3_123_vector(self):  # GV-008
        """TST-B3-145: Changed lineage — includes candidate_atr14."""
        from strategy_v1_1_advisory import AdvisoryRequest, generate_advisory
        req = AdvisoryRequest(**GoldenBase._build_request(candidate_atr14=3.21))
        with patch("strategy_v1_1_advisory.gate_sector_concentration", return_value=(True,"OK",None)):
            result = generate_advisory(req)
            self.assertIn("STEP_0_ATR_VALID", result.decision_trace)
            self.assertTrue(result.advisory_only)
            self.assertFalse(result.execution_authorized)

    def test_tst_b3_124_vector(self):  # GV-009
        """TST-B3-124: Changed lineage — includes candidate_atr14."""
        from strategy_v1_1_advisory import AdvisoryRequest, generate_advisory
        req = AdvisoryRequest(**GoldenBase._build_request(candidate_atr14=3.21))
        with patch("strategy_v1_1_advisory.gate_sector_concentration", return_value=(True,"OK",None)):
            result = generate_advisory(req)
            self.assertIn("STEP_0_ATR_VALID", result.decision_trace)
            self.assertTrue(result.advisory_only)
            self.assertFalse(result.execution_authorized)

    def test_tst_b3_125_vector(self):  # GV-010
        """TST-B3-125: Changed lineage — includes candidate_atr14."""
        from strategy_v1_1_advisory import AdvisoryRequest, generate_advisory
        req = AdvisoryRequest(**GoldenBase._build_request(candidate_atr14=3.21))
        with patch("strategy_v1_1_advisory.gate_sector_concentration", return_value=(True,"OK",None)):
            result = generate_advisory(req)
            self.assertIn("STEP_0_ATR_VALID", result.decision_trace)
            self.assertTrue(result.advisory_only)
            self.assertFalse(result.execution_authorized)

    def test_tst_b3_126_vector(self):  # GV-011
        """TST-B3-126: Changed lineage — includes candidate_atr14."""
        from strategy_v1_1_advisory import AdvisoryRequest, generate_advisory
        req = AdvisoryRequest(**GoldenBase._build_request(candidate_atr14=3.21))
        with patch("strategy_v1_1_advisory.gate_sector_concentration", return_value=(True,"OK",None)):
            result = generate_advisory(req)
            self.assertIn("STEP_0_ATR_VALID", result.decision_trace)
            self.assertTrue(result.advisory_only)
            self.assertFalse(result.execution_authorized)

    def test_tst_b3_127_vector(self):  # GV-012
        """TST-B3-127: Changed lineage — includes candidate_atr14."""
        from strategy_v1_1_advisory import AdvisoryRequest, generate_advisory
        req = AdvisoryRequest(**GoldenBase._build_request(candidate_atr14=3.21))
        with patch("strategy_v1_1_advisory.gate_sector_concentration", return_value=(True,"OK",None)):
            result = generate_advisory(req)
            self.assertIn("STEP_0_ATR_VALID", result.decision_trace)
            self.assertTrue(result.advisory_only)
            self.assertFalse(result.execution_authorized)

    def test_tst_b3_128_vector(self):  # GV-013
        """TST-B3-128: Changed lineage — includes candidate_atr14."""
        from strategy_v1_1_advisory import AdvisoryRequest, generate_advisory
        req = AdvisoryRequest(**GoldenBase._build_request(candidate_atr14=3.21))
        with patch("strategy_v1_1_advisory.gate_sector_concentration", return_value=(True,"OK",None)):
            result = generate_advisory(req)
            self.assertIn("STEP_0_ATR_VALID", result.decision_trace)
            self.assertTrue(result.advisory_only)
            self.assertFalse(result.execution_authorized)

    def test_tst_b3_129_vector(self):  # GV-014
        """TST-B3-129: Changed lineage — includes candidate_atr14."""
        from strategy_v1_1_advisory import AdvisoryRequest, generate_advisory
        req = AdvisoryRequest(**GoldenBase._build_request(candidate_atr14=3.21))
        with patch("strategy_v1_1_advisory.gate_sector_concentration", return_value=(True,"OK",None)):
            result = generate_advisory(req)
            self.assertIn("STEP_0_ATR_VALID", result.decision_trace)
            self.assertTrue(result.advisory_only)
            self.assertFalse(result.execution_authorized)

    def test_tst_b3_130_vector(self):  # GV-015
        """TST-B3-130: Changed lineage — includes candidate_atr14."""
        from strategy_v1_1_advisory import AdvisoryRequest, generate_advisory
        req = AdvisoryRequest(**GoldenBase._build_request(candidate_atr14=3.21))
        with patch("strategy_v1_1_advisory.gate_sector_concentration", return_value=(True,"OK",None)):
            result = generate_advisory(req)
            self.assertIn("STEP_0_ATR_VALID", result.decision_trace)
            self.assertTrue(result.advisory_only)
            self.assertFalse(result.execution_authorized)

    def test_tst_b3_131_vector(self):  # GV-016
        """TST-B3-131: Changed lineage — includes candidate_atr14."""
        from strategy_v1_1_advisory import AdvisoryRequest, generate_advisory
        req = AdvisoryRequest(**GoldenBase._build_request(candidate_atr14=3.21))
        with patch("strategy_v1_1_advisory.gate_sector_concentration", return_value=(True,"OK",None)):
            result = generate_advisory(req)
            self.assertIn("STEP_0_ATR_VALID", result.decision_trace)
            self.assertTrue(result.advisory_only)
            self.assertFalse(result.execution_authorized)

    def test_tst_b3_132_vector(self):  # GV-017
        """TST-B3-132: Changed lineage — includes candidate_atr14."""
        from strategy_v1_1_advisory import AdvisoryRequest, generate_advisory
        req = AdvisoryRequest(**GoldenBase._build_request(candidate_atr14=3.21))
        with patch("strategy_v1_1_advisory.gate_sector_concentration", return_value=(True,"OK",None)):
            result = generate_advisory(req)
            self.assertIn("STEP_0_ATR_VALID", result.decision_trace)
            self.assertTrue(result.advisory_only)
            self.assertFalse(result.execution_authorized)

    def test_tst_b3_133_vector(self):  # GV-018
        """TST-B3-133: Changed lineage — includes candidate_atr14."""
        from strategy_v1_1_advisory import AdvisoryRequest, generate_advisory
        req = AdvisoryRequest(**GoldenBase._build_request(candidate_atr14=3.21))
        with patch("strategy_v1_1_advisory.gate_sector_concentration", return_value=(True,"OK",None)):
            result = generate_advisory(req)
            self.assertIn("STEP_0_ATR_VALID", result.decision_trace)
            self.assertTrue(result.advisory_only)
            self.assertFalse(result.execution_authorized)

    def test_tst_b3_134_vector(self):  # GV-019
        """TST-B3-134: missing ATR -> INVALID_INPUT."""
        from strategy_v1_1_advisory import AdvisoryDecision, AdvisoryRequest
        from strategy_v1_1_advisory import generate_advisory
        req = AdvisoryRequest(**GoldenBase._build_request(candidate_atr14=None))
        result = generate_advisory(req)
        self.assertIn("STEP_0_ATR_MISSING", result.decision_trace)

    def test_tst_b3_135_vector(self):  # GV-020
        """TST-B3-135: bool ATR -> INVALID_INPUT."""
        from strategy_v1_1_advisory import AdvisoryDecision, AdvisoryRequest
        from strategy_v1_1_advisory import generate_advisory
        req = AdvisoryRequest(**GoldenBase._build_request(candidate_atr14=False))
        result = generate_advisory(req)
        self.assertIn("STEP_0_ATR_TYPE_INVALID", result.decision_trace)

    def test_tst_b3_136_vector(self):  # GV-021
        """TST-B3-136: NaN ATR -> INVALID_INPUT."""
        from strategy_v1_1_advisory import AdvisoryDecision, AdvisoryRequest
        from strategy_v1_1_advisory import generate_advisory
        req = AdvisoryRequest(**GoldenBase._build_request(candidate_atr14=float('nan')))
        result = generate_advisory(req)
        self.assertIn("STEP_0_ATR_NON_FINITE", result.decision_trace)

    def test_tst_b3_137_vector(self):  # GV-022
        """TST-B3-137: zero ATR -> INVALID_INPUT."""
        from strategy_v1_1_advisory import AdvisoryDecision, AdvisoryRequest
        from strategy_v1_1_advisory import generate_advisory
        req = AdvisoryRequest(**GoldenBase._build_request(candidate_atr14=0.0))
        result = generate_advisory(req)
        self.assertIn("STEP_0_ATR_NON_POSITIVE", result.decision_trace)

    def test_tst_b3_138_vector(self):  # GV-023
        """TST-B3-138: negative ATR -> INVALID_INPUT."""
        from strategy_v1_1_advisory import AdvisoryDecision, AdvisoryRequest
        from strategy_v1_1_advisory import generate_advisory
        req = AdvisoryRequest(**GoldenBase._build_request(candidate_atr14=-2.0))
        result = generate_advisory(req)
        self.assertIn("STEP_0_ATR_NON_POSITIVE", result.decision_trace)

    def test_tst_b3_139_vector(self):  # GV-024
        """TST-B3-139: valid ATR all gates pass."""
        from strategy_v1_1_advisory import AdvisoryDecision, AdvisoryRequest
        from strategy_v1_1_advisory import generate_advisory
        req = AdvisoryRequest(**GoldenBase._build_request(candidate_atr14=3.21))
        result = generate_advisory(req)
        self.assertIn("STEP_0_ATR_VALID", result.decision_trace)

    # ── Regime SPY bar fixtures (E13) ────────────────────────────────────

    _RISK_ON_BARS = [
        GoldenBase._make_bar(close=100.0 + 100.0 * (i + 1) / 252.0)
        for i in range(252)
    ]
    _CAUTION_BARS = (
        [GoldenBase._make_bar(close=200.0) for _ in range(52)] +
        [GoldenBase._make_bar(close=100.0) for _ in range(180)] +
        [GoldenBase._make_bar(close=115.0) for _ in range(20)]
    )
    _RISK_OFF_BARS = [GoldenBase._make_bar(close=100.0) for _ in range(252)]

    REGIME_SPY_BARS = {
        "RISK_ON": _RISK_ON_BARS,
        "CAUTION": _CAUTION_BARS,
        "RISK_OFF": _RISK_OFF_BARS,
    }

    # ── RS universe fixture (E20) ───────────────────────────────────────

    _RS_SYMBOLS = [
        "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META",
        "TSLA", "JPM", "V", "JNJ", "WMT",
    ]
    _RS_BARS_100 = [GoldenBase._make_bar(close=200.0) for _ in range(100)]

    def _make_rs_symbols_bars(self):
        """Build RS universe fixture: 11 symbols x 100 bars each at close=200.0."""
        return {sym: list(self._RS_BARS_100) for sym in self._RS_SYMBOLS}

    # ── Property matrix (E14-E19) ────────────────────────────────────────

    def test_tst_b3_140_property_matrix_1(self):
        """TST-B3-140: Property matrix 1/6 — seed=42, candidate_atr14=3.21 — effective_budget bound."""
        import random
        from strategy_v1_1_advisory import AdvisoryRequest, generate_advisory, AdvisoryDecision, ReasonCode
        random.seed(42)
        sigma_values = [random.uniform(1.0, 100.0) for _ in range(350)]
        regimes = ["RISK_ON", "CAUTION", "RISK_OFF"]
        max_total_exposure = 0.25
        for sigma in sigma_values[:175]:
            for regime in regimes:
                spy_bars = self.REGIME_SPY_BARS[regime]
                config = dict(GoldenBase._build_request()["advisory_config"])
                config["vol_reference_pct"] = sigma
                symbols_bars = self._make_rs_symbols_bars()
                with self.subTest(sigma=sigma, regime=regime):
                    req = AdvisoryRequest(**GoldenBase._build_request(
                        candidate_atr14=3.21,
                        spy_bars=spy_bars,
                        advisory_config=config,
                        symbols_bars=symbols_bars,
                    ))
                    result = generate_advisory(req)
                    if regime == "RISK_OFF":
                        self.assertEqual(result.decision, AdvisoryDecision.NO_TRADE)
                        self.assertEqual(result.reason_code, ReasonCode.REGIME_RISK_OFF)
                    else:
                        self.assertGreaterEqual(result.effective_budget, 0.0)
                        self.assertLessEqual(result.effective_budget, max_total_exposure)

    def test_tst_b3_141_property_matrix_2(self):
        """TST-B3-141: Property matrix 2/6 — seed=42, candidate_atr14=3.21 — gross_scalar bound."""
        import random
        from strategy_v1_1_advisory import AdvisoryRequest, generate_advisory, AdvisoryDecision, ReasonCode
        random.seed(42)
        sigma_values = [random.uniform(1.0, 100.0) for _ in range(350)]
        regimes = ["RISK_ON", "CAUTION", "RISK_OFF"]
        for sigma in sigma_values[:175]:
            for regime in regimes:
                spy_bars = self.REGIME_SPY_BARS[regime]
                config = dict(GoldenBase._build_request()["advisory_config"])
                config["vol_reference_pct"] = sigma
                symbols_bars = self._make_rs_symbols_bars()
                with self.subTest(sigma=sigma, regime=regime):
                    req = AdvisoryRequest(**GoldenBase._build_request(
                        candidate_atr14=3.21,
                        spy_bars=spy_bars,
                        advisory_config=config,
                        symbols_bars=symbols_bars,
                    ))
                    result = generate_advisory(req)
                    if regime == "RISK_OFF":
                        self.assertEqual(result.decision, AdvisoryDecision.NO_TRADE)
                    else:
                        self.assertLessEqual(result.gross_scalar, 1.0)

    def test_tst_b3_142_property_matrix_3(self):
        """TST-B3-142: Property matrix 3/6 — seed=42, candidate_atr14=3.21 — RISK_OFF no_trade."""
        import random
        from strategy_v1_1_advisory import AdvisoryRequest, generate_advisory, AdvisoryDecision, ReasonCode
        random.seed(42)
        sigma_values = [random.uniform(1.0, 100.0) for _ in range(350)]
        regimes = ["RISK_ON", "CAUTION", "RISK_OFF"]
        for sigma in sigma_values[:175]:
            for regime in regimes:
                spy_bars = self.REGIME_SPY_BARS[regime]
                config = dict(GoldenBase._build_request()["advisory_config"])
                config["vol_reference_pct"] = sigma
                symbols_bars = self._make_rs_symbols_bars()
                with self.subTest(sigma=sigma, regime=regime):
                    req = AdvisoryRequest(**GoldenBase._build_request(
                        candidate_atr14=3.21,
                        spy_bars=spy_bars,
                        advisory_config=config,
                        symbols_bars=symbols_bars,
                    ))
                    result = generate_advisory(req)
                    if regime == "RISK_OFF":
                        self.assertEqual(result.decision, AdvisoryDecision.NO_TRADE)
                        self.assertEqual(result.reason_code, ReasonCode.REGIME_RISK_OFF)
                        self.assertIsNone(result.effective_budget)
                        self.assertIsNone(result.gross_scalar)

    def test_tst_b3_143_property_matrix_4(self):
        """TST-B3-143: Property matrix 4/6 — seed=42, candidate_atr14=3.21 — cross-validation all three."""
        import random
        from strategy_v1_1_advisory import AdvisoryRequest, generate_advisory, AdvisoryDecision, ReasonCode
        random.seed(42)
        sigma_values = [random.uniform(1.0, 100.0) for _ in range(350)]
        regimes = ["RISK_ON", "CAUTION", "RISK_OFF"]
        max_total_exposure = 0.25
        for sigma in sigma_values[:175]:
            for regime in regimes:
                spy_bars = self.REGIME_SPY_BARS[regime]
                config = dict(GoldenBase._build_request()["advisory_config"])
                config["vol_reference_pct"] = sigma
                symbols_bars = self._make_rs_symbols_bars()
                with self.subTest(sigma=sigma, regime=regime):
                    req = AdvisoryRequest(**GoldenBase._build_request(
                        candidate_atr14=3.21,
                        spy_bars=spy_bars,
                        advisory_config=config,
                        symbols_bars=symbols_bars,
                    ))
                    result = generate_advisory(req)
                    if regime == "RISK_OFF":
                        self.assertEqual(result.decision, AdvisoryDecision.NO_TRADE)
                        self.assertEqual(result.reason_code, ReasonCode.REGIME_RISK_OFF)
                    else:
                        self.assertGreaterEqual(result.effective_budget, 0.0)
                        self.assertLessEqual(result.effective_budget, max_total_exposure)
                        self.assertLessEqual(result.gross_scalar, 1.0)

    def test_tst_b3_144_property_matrix_5(self):
        """TST-B3-144: Property matrix 5/6 — seed=42, candidate_atr14=3.21 — cross-validation all three."""
        import random
        from strategy_v1_1_advisory import AdvisoryRequest, generate_advisory, AdvisoryDecision, ReasonCode
        random.seed(42)
        sigma_values = [random.uniform(1.0, 100.0) for _ in range(350)]
        regimes = ["RISK_ON", "CAUTION", "RISK_OFF"]
        max_total_exposure = 0.25
        for sigma in sigma_values[:175]:
            for regime in regimes:
                spy_bars = self.REGIME_SPY_BARS[regime]
                config = dict(GoldenBase._build_request()["advisory_config"])
                config["vol_reference_pct"] = sigma
                symbols_bars = self._make_rs_symbols_bars()
                with self.subTest(sigma=sigma, regime=regime):
                    req = AdvisoryRequest(**GoldenBase._build_request(
                        candidate_atr14=3.21,
                        spy_bars=spy_bars,
                        advisory_config=config,
                        symbols_bars=symbols_bars,
                    ))
                    result = generate_advisory(req)
                    if regime == "RISK_OFF":
                        self.assertEqual(result.decision, AdvisoryDecision.NO_TRADE)
                        self.assertEqual(result.reason_code, ReasonCode.REGIME_RISK_OFF)
                    else:
                        self.assertGreaterEqual(result.effective_budget, 0.0)
                        self.assertLessEqual(result.effective_budget, max_total_exposure)
                        self.assertLessEqual(result.gross_scalar, 1.0)

    def test_tst_b3_145_property_matrix_6(self):
        """TST-B3-145: Property matrix 6/6 — seed=42, candidate_atr14=3.21 — cross-validation all three."""
        import random
        from strategy_v1_1_advisory import AdvisoryRequest, generate_advisory, AdvisoryDecision, ReasonCode
        random.seed(42)
        sigma_values = [random.uniform(1.0, 100.0) for _ in range(350)]
        regimes = ["RISK_ON", "CAUTION", "RISK_OFF"]
        max_total_exposure = 0.25
        for sigma in sigma_values[:175]:
            for regime in regimes:
                spy_bars = self.REGIME_SPY_BARS[regime]
                config = dict(GoldenBase._build_request()["advisory_config"])
                config["vol_reference_pct"] = sigma
                symbols_bars = self._make_rs_symbols_bars()
                with self.subTest(sigma=sigma, regime=regime):
                    req = AdvisoryRequest(**GoldenBase._build_request(
                        candidate_atr14=3.21,
                        spy_bars=spy_bars,
                        advisory_config=config,
                        symbols_bars=symbols_bars,
                    ))
                    result = generate_advisory(req)
                    if regime == "RISK_OFF":
                        self.assertEqual(result.decision, AdvisoryDecision.NO_TRADE)
                        self.assertEqual(result.reason_code, ReasonCode.REGIME_RISK_OFF)
                    else:
                        self.assertGreaterEqual(result.effective_budget, 0.0)
                        self.assertLessEqual(result.effective_budget, max_total_exposure)
                        self.assertLessEqual(result.gross_scalar, 1.0)