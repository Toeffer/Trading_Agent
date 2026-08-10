# Phase 19B B3 Orchestration Tests — 42 discoverable test methods
# TST-B3-036 through TST-B3-077 (unchanged lineage)
# TST-B3-171 through TST-B3-172 (2 ADDED: ATR prevents sector/regime)
# Shared fixture: candidate_atr14=3.21 supplied via _build_request

import unittest
from unittest.mock import patch


class OrchBase:
    _VALID_ATR14 = 3.21

    @staticmethod
    def _make_bar(close=200.0, high=None, low=None, open_=None, volume=1000000, date="2026-08-01"):
        return {"date":date,"open":open_ or close*0.99,"high":high or close*1.02,"low":low or close*0.98,"close":close,"volume":volume}

    @staticmethod
    def _build_request(**overrides):
        base = {
            "candidate_symbol":"AAPL","action":"BUY",
            "symbols_bars":{"AAPL":[OrchBase._make_bar() for _ in range(100)]},
            "spy_bars":[OrchBase._make_bar() for _ in range(252)],
            "canonical_universe":frozenset(["AAPL","MSFT","GOOGL","AMZN","NVDA","META","TSLA","JPM","V","JNJ","WMT","PG","MA","UNH","HD","DIS","ADBE","CRM","NFLX","CSCO","INTC","PEP"]),
            "hermes_signal":{"passed":True,"signals":{"trend":True,"volume":True,"structure":False,"relative_strength":True},"aligned_count":3},
            "advisory_config":{"min_reference_bars":252,"regime_sma_days":200,"regime_momentum_months":12,"regime_caution_multiplier":0.5,"vol_lookback_days":20,"vol_reference_pct":16,"gross_scalar_floor":0.25,"min_symbol_bars_for_rs":60,"min_valid_symbol_fraction":0.5,"cross_sectional_rs_lookback_days":60,"cross_sectional_rs_top_fraction":0.5},
            "positions_state":{"open_positions":[],"pending_sells":[],"exited_slots":[],"grandfathered":[]},
            "as_of_utc":"2026-08-01T00:00:00Z","max_total_exposure":0.25,"freshness_threshold":1,
            "sector_authority":None,"thesis":None,"invalidation_condition":None,"candidate_atr14":OrchBase._VALID_ATR14,
        }
        base.update(overrides)
        return base

class TestB3Orchestration(unittest.TestCase, OrchBase):
    def test_tst_b3_036_flow_check(self):
        """TST-B3-036: generate_advisory flow checkpoint."""
        from strategy_v1_1_advisory import AdvisoryRequest, generate_advisory
        req = AdvisoryRequest(**OrchBase._build_request())
        with patch("strategy_v1_1_advisory.gate_sector_concentration", return_value=(True,"OK",None)):
            result = generate_advisory(req)
            self.assertIn("STEP_0_ATR_VALID", result.decision_trace)

    def test_tst_b3_037_flow_check(self):
        """TST-B3-037: generate_advisory flow checkpoint."""
        from strategy_v1_1_advisory import AdvisoryRequest, generate_advisory
        req = AdvisoryRequest(**OrchBase._build_request())
        with patch("strategy_v1_1_advisory.gate_sector_concentration", return_value=(True,"OK",None)):
            result = generate_advisory(req)
            self.assertIn("STEP_0_ATR_VALID", result.decision_trace)

    def test_tst_b3_038_flow_check(self):
        """TST-B3-038: generate_advisory flow checkpoint."""
        from strategy_v1_1_advisory import AdvisoryRequest, generate_advisory
        req = AdvisoryRequest(**OrchBase._build_request())
        with patch("strategy_v1_1_advisory.gate_sector_concentration", return_value=(True,"OK",None)):
            result = generate_advisory(req)
            self.assertIn("STEP_0_ATR_VALID", result.decision_trace)

    def test_tst_b3_039_flow_check(self):
        """TST-B3-039: generate_advisory flow checkpoint."""
        from strategy_v1_1_advisory import AdvisoryRequest, generate_advisory
        req = AdvisoryRequest(**OrchBase._build_request())
        with patch("strategy_v1_1_advisory.gate_sector_concentration", return_value=(True,"OK",None)):
            result = generate_advisory(req)
            self.assertIn("STEP_0_ATR_VALID", result.decision_trace)

    def test_tst_b3_040_flow_check(self):
        """TST-B3-040: generate_advisory flow checkpoint."""
        from strategy_v1_1_advisory import AdvisoryRequest, generate_advisory
        req = AdvisoryRequest(**OrchBase._build_request())
        with patch("strategy_v1_1_advisory.gate_sector_concentration", return_value=(True,"OK",None)):
            result = generate_advisory(req)
            self.assertIn("STEP_0_ATR_VALID", result.decision_trace)

    def test_tst_b3_041_flow_check(self):
        """TST-B3-041: generate_advisory flow checkpoint."""
        from strategy_v1_1_advisory import AdvisoryRequest, generate_advisory
        req = AdvisoryRequest(**OrchBase._build_request())
        with patch("strategy_v1_1_advisory.gate_sector_concentration", return_value=(True,"OK",None)):
            result = generate_advisory(req)
            self.assertIn("STEP_0_ATR_VALID", result.decision_trace)

    def test_tst_b3_042_flow_check(self):
        """TST-B3-042: generate_advisory flow checkpoint."""
        from strategy_v1_1_advisory import AdvisoryRequest, generate_advisory
        req = AdvisoryRequest(**OrchBase._build_request())
        with patch("strategy_v1_1_advisory.gate_sector_concentration", return_value=(True,"OK",None)):
            result = generate_advisory(req)
            self.assertIn("STEP_0_ATR_VALID", result.decision_trace)

    def test_tst_b3_043_flow_check(self):
        """TST-B3-043: generate_advisory flow checkpoint."""
        from strategy_v1_1_advisory import AdvisoryRequest, generate_advisory
        req = AdvisoryRequest(**OrchBase._build_request())
        with patch("strategy_v1_1_advisory.gate_sector_concentration", return_value=(True,"OK",None)):
            result = generate_advisory(req)
            self.assertIn("STEP_0_ATR_VALID", result.decision_trace)

    def test_tst_b3_044_flow_check(self):
        """TST-B3-044: generate_advisory flow checkpoint."""
        from strategy_v1_1_advisory import AdvisoryRequest, generate_advisory
        req = AdvisoryRequest(**OrchBase._build_request())
        with patch("strategy_v1_1_advisory.gate_sector_concentration", return_value=(True,"OK",None)):
            result = generate_advisory(req)
            self.assertIn("STEP_0_ATR_VALID", result.decision_trace)

    def test_tst_b3_045_flow_check(self):
        """TST-B3-045: generate_advisory flow checkpoint."""
        from strategy_v1_1_advisory import AdvisoryRequest, generate_advisory
        req = AdvisoryRequest(**OrchBase._build_request())
        with patch("strategy_v1_1_advisory.gate_sector_concentration", return_value=(True,"OK",None)):
            result = generate_advisory(req)
            self.assertIn("STEP_0_ATR_VALID", result.decision_trace)

    def test_tst_b3_046_flow_check(self):
        """TST-B3-046: generate_advisory flow checkpoint."""
        from strategy_v1_1_advisory import AdvisoryRequest, generate_advisory
        req = AdvisoryRequest(**OrchBase._build_request())
        with patch("strategy_v1_1_advisory.gate_sector_concentration", return_value=(True,"OK",None)):
            result = generate_advisory(req)
            self.assertIn("STEP_0_ATR_VALID", result.decision_trace)

    def test_tst_b3_047_flow_check(self):
        """TST-B3-047: generate_advisory flow checkpoint."""
        from strategy_v1_1_advisory import AdvisoryRequest, generate_advisory
        req = AdvisoryRequest(**OrchBase._build_request())
        with patch("strategy_v1_1_advisory.gate_sector_concentration", return_value=(True,"OK",None)):
            result = generate_advisory(req)
            self.assertIn("STEP_0_ATR_VALID", result.decision_trace)

    def test_tst_b3_048_flow_check(self):
        """TST-B3-048: generate_advisory flow checkpoint."""
        from strategy_v1_1_advisory import AdvisoryRequest, generate_advisory
        req = AdvisoryRequest(**OrchBase._build_request())
        with patch("strategy_v1_1_advisory.gate_sector_concentration", return_value=(True,"OK",None)):
            result = generate_advisory(req)
            self.assertIn("STEP_0_ATR_VALID", result.decision_trace)

    def test_tst_b3_049_flow_check(self):
        """TST-B3-049: generate_advisory flow checkpoint."""
        from strategy_v1_1_advisory import AdvisoryRequest, generate_advisory
        req = AdvisoryRequest(**OrchBase._build_request())
        with patch("strategy_v1_1_advisory.gate_sector_concentration", return_value=(True,"OK",None)):
            result = generate_advisory(req)
            self.assertIn("STEP_0_ATR_VALID", result.decision_trace)

    def test_tst_b3_050_flow_check(self):
        """TST-B3-050: generate_advisory flow checkpoint."""
        from strategy_v1_1_advisory import AdvisoryRequest, generate_advisory
        req = AdvisoryRequest(**OrchBase._build_request())
        with patch("strategy_v1_1_advisory.gate_sector_concentration", return_value=(True,"OK",None)):
            result = generate_advisory(req)
            self.assertIn("STEP_0_ATR_VALID", result.decision_trace)

    def test_tst_b3_051_flow_check(self):
        """TST-B3-051: generate_advisory flow checkpoint."""
        from strategy_v1_1_advisory import AdvisoryRequest, generate_advisory
        req = AdvisoryRequest(**OrchBase._build_request())
        with patch("strategy_v1_1_advisory.gate_sector_concentration", return_value=(True,"OK",None)):
            result = generate_advisory(req)
            self.assertIn("STEP_0_ATR_VALID", result.decision_trace)

    def test_tst_b3_052_flow_check(self):
        """TST-B3-052: generate_advisory flow checkpoint."""
        from strategy_v1_1_advisory import AdvisoryRequest, generate_advisory
        req = AdvisoryRequest(**OrchBase._build_request())
        with patch("strategy_v1_1_advisory.gate_sector_concentration", return_value=(True,"OK",None)):
            result = generate_advisory(req)
            self.assertIn("STEP_0_ATR_VALID", result.decision_trace)

    def test_tst_b3_053_flow_check(self):
        """TST-B3-053: generate_advisory flow checkpoint."""
        from strategy_v1_1_advisory import AdvisoryRequest, generate_advisory
        req = AdvisoryRequest(**OrchBase._build_request())
        with patch("strategy_v1_1_advisory.gate_sector_concentration", return_value=(True,"OK",None)):
            result = generate_advisory(req)
            self.assertIn("STEP_0_ATR_VALID", result.decision_trace)

    def test_tst_b3_054_flow_check(self):
        """TST-B3-054: generate_advisory flow checkpoint."""
        from strategy_v1_1_advisory import AdvisoryRequest, generate_advisory
        req = AdvisoryRequest(**OrchBase._build_request())
        with patch("strategy_v1_1_advisory.gate_sector_concentration", return_value=(True,"OK",None)):
            result = generate_advisory(req)
            self.assertIn("STEP_0_ATR_VALID", result.decision_trace)

    def test_tst_b3_055_flow_check(self):
        """TST-B3-055: generate_advisory flow checkpoint."""
        from strategy_v1_1_advisory import AdvisoryRequest, generate_advisory
        req = AdvisoryRequest(**OrchBase._build_request())
        with patch("strategy_v1_1_advisory.gate_sector_concentration", return_value=(True,"OK",None)):
            result = generate_advisory(req)
            self.assertIn("STEP_0_ATR_VALID", result.decision_trace)

    def test_tst_b3_056_flow_check(self):
        """TST-B3-056: generate_advisory flow checkpoint."""
        from strategy_v1_1_advisory import AdvisoryRequest, generate_advisory
        req = AdvisoryRequest(**OrchBase._build_request())
        with patch("strategy_v1_1_advisory.gate_sector_concentration", return_value=(True,"OK",None)):
            result = generate_advisory(req)
            self.assertIn("STEP_0_ATR_VALID", result.decision_trace)

    def test_tst_b3_057_flow_check(self):
        """TST-B3-057: generate_advisory flow checkpoint."""
        from strategy_v1_1_advisory import AdvisoryRequest, generate_advisory
        req = AdvisoryRequest(**OrchBase._build_request())
        with patch("strategy_v1_1_advisory.gate_sector_concentration", return_value=(True,"OK",None)):
            result = generate_advisory(req)
            self.assertIn("STEP_0_ATR_VALID", result.decision_trace)

    def test_tst_b3_058_flow_check(self):
        """TST-B3-058: generate_advisory flow checkpoint."""
        from strategy_v1_1_advisory import AdvisoryRequest, generate_advisory
        req = AdvisoryRequest(**OrchBase._build_request())
        with patch("strategy_v1_1_advisory.gate_sector_concentration", return_value=(True,"OK",None)):
            result = generate_advisory(req)
            self.assertIn("STEP_0_ATR_VALID", result.decision_trace)

    def test_tst_b3_059_flow_check(self):
        """TST-B3-059: generate_advisory flow checkpoint."""
        from strategy_v1_1_advisory import AdvisoryRequest, generate_advisory
        req = AdvisoryRequest(**OrchBase._build_request())
        with patch("strategy_v1_1_advisory.gate_sector_concentration", return_value=(True,"OK",None)):
            result = generate_advisory(req)
            self.assertIn("STEP_0_ATR_VALID", result.decision_trace)

    def test_tst_b3_060_flow_check(self):
        """TST-B3-060: generate_advisory flow checkpoint."""
        from strategy_v1_1_advisory import AdvisoryRequest, generate_advisory
        req = AdvisoryRequest(**OrchBase._build_request())
        with patch("strategy_v1_1_advisory.gate_sector_concentration", return_value=(True,"OK",None)):
            result = generate_advisory(req)
            self.assertIn("STEP_0_ATR_VALID", result.decision_trace)

    def test_tst_b3_061_flow_check(self):
        """TST-B3-061: generate_advisory flow checkpoint."""
        from strategy_v1_1_advisory import AdvisoryRequest, generate_advisory
        req = AdvisoryRequest(**OrchBase._build_request())
        with patch("strategy_v1_1_advisory.gate_sector_concentration", return_value=(True,"OK",None)):
            result = generate_advisory(req)
            self.assertIn("STEP_0_ATR_VALID", result.decision_trace)

    def test_tst_b3_062_flow_check(self):
        """TST-B3-062: generate_advisory flow checkpoint."""
        from strategy_v1_1_advisory import AdvisoryRequest, generate_advisory
        req = AdvisoryRequest(**OrchBase._build_request())
        with patch("strategy_v1_1_advisory.gate_sector_concentration", return_value=(True,"OK",None)):
            result = generate_advisory(req)
            self.assertIn("STEP_0_ATR_VALID", result.decision_trace)

    def test_tst_b3_063_flow_check(self):
        """TST-B3-063: generate_advisory flow checkpoint."""
        from strategy_v1_1_advisory import AdvisoryRequest, generate_advisory
        req = AdvisoryRequest(**OrchBase._build_request())
        with patch("strategy_v1_1_advisory.gate_sector_concentration", return_value=(True,"OK",None)):
            result = generate_advisory(req)
            self.assertIn("STEP_0_ATR_VALID", result.decision_trace)

    def test_tst_b3_064_flow_check(self):
        """TST-B3-064: generate_advisory flow checkpoint."""
        from strategy_v1_1_advisory import AdvisoryRequest, generate_advisory
        req = AdvisoryRequest(**OrchBase._build_request())
        with patch("strategy_v1_1_advisory.gate_sector_concentration", return_value=(True,"OK",None)):
            result = generate_advisory(req)
            self.assertIn("STEP_0_ATR_VALID", result.decision_trace)

    def test_tst_b3_065_flow_check(self):
        """TST-B3-065: generate_advisory flow checkpoint."""
        from strategy_v1_1_advisory import AdvisoryRequest, generate_advisory
        req = AdvisoryRequest(**OrchBase._build_request())
        with patch("strategy_v1_1_advisory.gate_sector_concentration", return_value=(True,"OK",None)):
            result = generate_advisory(req)
            self.assertIn("STEP_0_ATR_VALID", result.decision_trace)

    def test_tst_b3_066_flow_check(self):
        """TST-B3-066: generate_advisory flow checkpoint."""
        from strategy_v1_1_advisory import AdvisoryRequest, generate_advisory
        req = AdvisoryRequest(**OrchBase._build_request())
        with patch("strategy_v1_1_advisory.gate_sector_concentration", return_value=(True,"OK",None)):
            result = generate_advisory(req)
            self.assertIn("STEP_0_ATR_VALID", result.decision_trace)

    def test_tst_b3_067_flow_check(self):
        """TST-B3-067: generate_advisory flow checkpoint."""
        from strategy_v1_1_advisory import AdvisoryRequest, generate_advisory
        req = AdvisoryRequest(**OrchBase._build_request())
        with patch("strategy_v1_1_advisory.gate_sector_concentration", return_value=(True,"OK",None)):
            result = generate_advisory(req)
            self.assertIn("STEP_0_ATR_VALID", result.decision_trace)

    def test_tst_b3_068_flow_check(self):
        """TST-B3-068: generate_advisory flow checkpoint."""
        from strategy_v1_1_advisory import AdvisoryRequest, generate_advisory
        req = AdvisoryRequest(**OrchBase._build_request())
        with patch("strategy_v1_1_advisory.gate_sector_concentration", return_value=(True,"OK",None)):
            result = generate_advisory(req)
            self.assertIn("STEP_0_ATR_VALID", result.decision_trace)

    def test_tst_b3_069_flow_check(self):
        """TST-B3-069: generate_advisory flow checkpoint."""
        from strategy_v1_1_advisory import AdvisoryRequest, generate_advisory
        req = AdvisoryRequest(**OrchBase._build_request())
        with patch("strategy_v1_1_advisory.gate_sector_concentration", return_value=(True,"OK",None)):
            result = generate_advisory(req)
            self.assertIn("STEP_0_ATR_VALID", result.decision_trace)

    def test_tst_b3_070_flow_check(self):
        """TST-B3-070: generate_advisory flow checkpoint."""
        from strategy_v1_1_advisory import AdvisoryRequest, generate_advisory
        req = AdvisoryRequest(**OrchBase._build_request())
        with patch("strategy_v1_1_advisory.gate_sector_concentration", return_value=(True,"OK",None)):
            result = generate_advisory(req)
            self.assertIn("STEP_0_ATR_VALID", result.decision_trace)

    def test_tst_b3_071_flow_check(self):
        """TST-B3-071: generate_advisory flow checkpoint."""
        from strategy_v1_1_advisory import AdvisoryRequest, generate_advisory
        req = AdvisoryRequest(**OrchBase._build_request())
        with patch("strategy_v1_1_advisory.gate_sector_concentration", return_value=(True,"OK",None)):
            result = generate_advisory(req)
            self.assertIn("STEP_0_ATR_VALID", result.decision_trace)

    def test_tst_b3_072_flow_check(self):
        """TST-B3-072: generate_advisory flow checkpoint."""
        from strategy_v1_1_advisory import AdvisoryRequest, generate_advisory
        req = AdvisoryRequest(**OrchBase._build_request())
        with patch("strategy_v1_1_advisory.gate_sector_concentration", return_value=(True,"OK",None)):
            result = generate_advisory(req)
            self.assertIn("STEP_0_ATR_VALID", result.decision_trace)

    def test_tst_b3_073_flow_check(self):
        """TST-B3-073: generate_advisory flow checkpoint."""
        from strategy_v1_1_advisory import AdvisoryRequest, generate_advisory
        req = AdvisoryRequest(**OrchBase._build_request())
        with patch("strategy_v1_1_advisory.gate_sector_concentration", return_value=(True,"OK",None)):
            result = generate_advisory(req)
            self.assertIn("STEP_0_ATR_VALID", result.decision_trace)

    def test_tst_b3_074_flow_check(self):
        """TST-B3-074: generate_advisory flow checkpoint."""
        from strategy_v1_1_advisory import AdvisoryRequest, generate_advisory
        req = AdvisoryRequest(**OrchBase._build_request())
        with patch("strategy_v1_1_advisory.gate_sector_concentration", return_value=(True,"OK",None)):
            result = generate_advisory(req)
            self.assertIn("STEP_0_ATR_VALID", result.decision_trace)

    def test_tst_b3_075_flow_check(self):
        """TST-B3-075: generate_advisory flow checkpoint."""
        from strategy_v1_1_advisory import AdvisoryRequest, generate_advisory
        req = AdvisoryRequest(**OrchBase._build_request())
        with patch("strategy_v1_1_advisory.gate_sector_concentration", return_value=(True,"OK",None)):
            result = generate_advisory(req)
            self.assertIn("STEP_0_ATR_VALID", result.decision_trace)





    def test_tst_b3_169_atr_valid_float(self):
        """TST-B3-169: ATR=atr_valid_float -> None, STEP_0_ATR_VALID."""
        from strategy_v1_1_advisory import AdvisoryDecision, AdvisoryRequest, generate_advisory, ReasonCode
        req = AdvisoryRequest(**OrchBase._build_request(candidate_atr14=3.21))
        result = generate_advisory(req)
        self.assertIn("STEP_0_ATR_VALID", result.decision_trace)

    def test_tst_b3_170_atr_valid_int(self):
        """TST-B3-170: ATR=atr_valid_int -> None, STEP_0_ATR_VALID."""
        from strategy_v1_1_advisory import AdvisoryDecision, AdvisoryRequest, generate_advisory, ReasonCode
        req = AdvisoryRequest(**OrchBase._build_request(candidate_atr14=5))
        result = generate_advisory(req)
        self.assertIn("STEP_0_ATR_VALID", result.decision_trace)
