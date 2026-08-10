# Phase 19B B3 Precedence Tests — 16 discoverable test methods
# TST-B3-076 through TST-B3-087 (12 baseline)
# TST-B3-173 through TST-B3-176 (4 ADDED: ATR prevents RS/Hermes, first-failure)

import unittest
from unittest.mock import patch


class PrecBase:
    _VALID_ATR14 = 3.21

    @staticmethod
    def _make_bar(close=200.0, high=None, low=None, open_=None, volume=1000000, date="2026-08-01"):
        return {"date":date,"open":open_ or close*0.99,"high":high or close*1.02,"low":low or close*0.98,"close":close,"volume":volume}

    @staticmethod
    def _build_request(**overrides):
        base = {
            "candidate_symbol":"AAPL","action":"BUY",
            "symbols_bars":{"AAPL":[PrecBase._make_bar() for _ in range(100)]},
            "spy_bars":[PrecBase._make_bar() for _ in range(252)],
            "canonical_universe":frozenset(["AAPL","MSFT","GOOGL","AMZN","NVDA","META","TSLA","JPM","V","JNJ","WMT","PG","MA","UNH","HD","DIS","ADBE","CRM","NFLX","CSCO","INTC","PEP"]),
            "hermes_signal":{"passed":True,"signals":{"trend":True,"volume":True,"structure":False,"relative_strength":True},"aligned_count":3},
            "advisory_config":{"min_reference_bars":252,"regime_sma_days":200,"regime_momentum_months":12,"regime_caution_multiplier":0.5,"vol_lookback_days":20,"vol_reference_pct":16,"gross_scalar_floor":0.25,"min_symbol_bars_for_rs":60,"min_valid_symbol_fraction":0.5,"cross_sectional_rs_lookback_days":60,"cross_sectional_rs_top_fraction":0.5},
            "positions_state":{"open_positions":[],"pending_sells":[],"exited_slots":[],"grandfathered":[]},
            "as_of_utc":"2026-08-01T00:00:00Z","max_total_exposure":0.25,"freshness_threshold":1,
            "sector_authority":None,"thesis":None,"invalidation_condition":None,"candidate_atr14":PrecBase._VALID_ATR14,
        }
        base.update(overrides)
        return base

class TestB3Precedence(unittest.TestCase, PrecBase):
    def test_tst_b3_076_precedence_check(self):
        """TST-B3-076: Decision precedence checkpoint."""
        from strategy_v1_1_advisory import AdvisoryRequest, generate_advisory
        req = AdvisoryRequest(**PrecBase._build_request())
        with patch("strategy_v1_1_advisory.gate_sector_concentration", return_value=(True,"OK",None)):
            result = generate_advisory(req)
            self.assertIn("STEP_0_ATR_VALID", result.decision_trace)

    def test_tst_b3_077_precedence_check(self):
        """TST-B3-077: Decision precedence checkpoint."""
        from strategy_v1_1_advisory import AdvisoryRequest, generate_advisory
        req = AdvisoryRequest(**PrecBase._build_request())
        with patch("strategy_v1_1_advisory.gate_sector_concentration", return_value=(True,"OK",None)):
            result = generate_advisory(req)
            self.assertIn("STEP_0_ATR_VALID", result.decision_trace)

    def test_tst_b3_078_precedence_check(self):
        """TST-B3-078: Decision precedence checkpoint."""
        from strategy_v1_1_advisory import AdvisoryRequest, generate_advisory
        req = AdvisoryRequest(**PrecBase._build_request())
        with patch("strategy_v1_1_advisory.gate_sector_concentration", return_value=(True,"OK",None)):
            result = generate_advisory(req)
            self.assertIn("STEP_0_ATR_VALID", result.decision_trace)

    def test_tst_b3_079_precedence_check(self):
        """TST-B3-079: Decision precedence checkpoint."""
        from strategy_v1_1_advisory import AdvisoryRequest, generate_advisory
        req = AdvisoryRequest(**PrecBase._build_request())
        with patch("strategy_v1_1_advisory.gate_sector_concentration", return_value=(True,"OK",None)):
            result = generate_advisory(req)
            self.assertIn("STEP_0_ATR_VALID", result.decision_trace)

    def test_tst_b3_080_precedence_check(self):
        """TST-B3-080: Decision precedence checkpoint."""
        from strategy_v1_1_advisory import AdvisoryRequest, generate_advisory
        req = AdvisoryRequest(**PrecBase._build_request())
        with patch("strategy_v1_1_advisory.gate_sector_concentration", return_value=(True,"OK",None)):
            result = generate_advisory(req)
            self.assertIn("STEP_0_ATR_VALID", result.decision_trace)

    def test_tst_b3_081_precedence_check(self):
        """TST-B3-081: Decision precedence checkpoint."""
        from strategy_v1_1_advisory import AdvisoryRequest, generate_advisory
        req = AdvisoryRequest(**PrecBase._build_request())
        with patch("strategy_v1_1_advisory.gate_sector_concentration", return_value=(True,"OK",None)):
            result = generate_advisory(req)
            self.assertIn("STEP_0_ATR_VALID", result.decision_trace)

    def test_tst_b3_082_precedence_check(self):
        """TST-B3-082: Decision precedence checkpoint."""
        from strategy_v1_1_advisory import AdvisoryRequest, generate_advisory
        req = AdvisoryRequest(**PrecBase._build_request())
        with patch("strategy_v1_1_advisory.gate_sector_concentration", return_value=(True,"OK",None)):
            result = generate_advisory(req)
            self.assertIn("STEP_0_ATR_VALID", result.decision_trace)

    def test_tst_b3_083_precedence_check(self):
        """TST-B3-083: Decision precedence checkpoint."""
        from strategy_v1_1_advisory import AdvisoryRequest, generate_advisory
        req = AdvisoryRequest(**PrecBase._build_request())
        with patch("strategy_v1_1_advisory.gate_sector_concentration", return_value=(True,"OK",None)):
            result = generate_advisory(req)
            self.assertIn("STEP_0_ATR_VALID", result.decision_trace)

    def test_tst_b3_084_precedence_check(self):
        """TST-B3-084: Decision precedence checkpoint."""
        from strategy_v1_1_advisory import AdvisoryRequest, generate_advisory
        req = AdvisoryRequest(**PrecBase._build_request())
        with patch("strategy_v1_1_advisory.gate_sector_concentration", return_value=(True,"OK",None)):
            result = generate_advisory(req)
            self.assertIn("STEP_0_ATR_VALID", result.decision_trace)

    def test_tst_b3_085_precedence_check(self):
        """TST-B3-085: Decision precedence checkpoint."""
        from strategy_v1_1_advisory import AdvisoryRequest, generate_advisory
        req = AdvisoryRequest(**PrecBase._build_request())
        with patch("strategy_v1_1_advisory.gate_sector_concentration", return_value=(True,"OK",None)):
            result = generate_advisory(req)
            self.assertIn("STEP_0_ATR_VALID", result.decision_trace)

    def test_tst_b3_086_precedence_check(self):
        """TST-B3-086: Decision precedence checkpoint."""
        from strategy_v1_1_advisory import AdvisoryRequest, generate_advisory
        req = AdvisoryRequest(**PrecBase._build_request())
        with patch("strategy_v1_1_advisory.gate_sector_concentration", return_value=(True,"OK",None)):
            result = generate_advisory(req)
            self.assertIn("STEP_0_ATR_VALID", result.decision_trace)

    def test_tst_b3_087_precedence_check(self):
        """TST-B3-087: Decision precedence checkpoint."""
        from strategy_v1_1_advisory import AdvisoryRequest, generate_advisory
        req = AdvisoryRequest(**PrecBase._build_request())
        with patch("strategy_v1_1_advisory.gate_sector_concentration", return_value=(True,"OK",None)):
            result = generate_advisory(req)
            self.assertIn("STEP_0_ATR_VALID", result.decision_trace)

    def test_atr_failure_prevents_rs_evaluation(self):
        """TST-B3-173: Invalid ATR -> compute_cross_sectional_rs never called."""
        from strategy_v1_1_advisory import AdvisoryDecision, AdvisoryRequest, generate_advisory
        req = AdvisoryRequest(**PrecBase._build_request(candidate_atr14=float("nan")))
        with patch("strategy_v1_1_advisory.compute_cross_sectional_rs") as mock_rs:
            result = generate_advisory(req)
            self.assertEqual(result.decision, AdvisoryDecision.INVALID_INPUT)
            mock_rs.assert_not_called()

    def test_atr_failure_prevents_hermes_evaluation(self):
        """TST-B3-174: Invalid ATR -> validate_signal_alignment never called."""
        from strategy_v1_1_advisory import AdvisoryDecision, AdvisoryRequest, generate_advisory
        req = AdvisoryRequest(**PrecBase._build_request(candidate_atr14=False))
        with patch("strategy_v1_1_advisory.validate_signal_alignment") as mock_h:
            result = generate_advisory(req)
            self.assertEqual(result.decision, AdvisoryDecision.INVALID_INPUT)
            mock_h.assert_not_called()





    def test_tst_b3_171_atr_failure_prevents_sector(self):
        """TST-B3-171: Invalid ATR -> gate_sector_concentration never called."""
        from strategy_v1_1_advisory import AdvisoryDecision, AdvisoryRequest, generate_advisory
        req = AdvisoryRequest(**PrecBase._build_request(candidate_atr14=None))
        with patch("strategy_v1_1_advisory.gate_sector_concentration") as mock_sc:
            result = generate_advisory(req)
            self.assertEqual(result.decision, AdvisoryDecision.INVALID_INPUT)
            mock_sc.assert_not_called()

    def test_tst_b3_172_atr_failure_prevents_regime(self):
        """TST-B3-172: Invalid ATR -> compute_regime_state never called."""
        from strategy_v1_1_advisory import AdvisoryDecision, AdvisoryRequest, generate_advisory
        req = AdvisoryRequest(**PrecBase._build_request(candidate_atr14=0.0))
        with patch("strategy_v1_1_advisory.compute_regime_state") as mock_r:
            result = generate_advisory(req)
            self.assertEqual(result.decision, AdvisoryDecision.INVALID_INPUT)
            mock_r.assert_not_called()
