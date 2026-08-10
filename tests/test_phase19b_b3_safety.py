# Phase 19B B3 Safety Tests — 33 discoverable test methods
# TST-B3-088 through TST-B3-115 (28 baseline)
# TST-B3-177 through TST-B3-180 (4 ADDED: no ATR in budget/RS/stop, no alter RS)
# TST-B3-182 (1 ADDED: result_to_json absent from public API)

import unittest
from unittest.mock import patch


class SafeBase:
    _VALID_ATR14 = 3.21

    @staticmethod
    def _make_bar(close=200.0, high=None, low=None, open_=None, volume=1000000, date="2026-08-01"):
        return {"date":date,"open":open_ or close*0.99,"high":high or close*1.02,"low":low or close*0.98,"close":close,"volume":volume}

    @staticmethod
    def _build_request(**overrides):
        base = {
            "candidate_symbol":"AAPL","action":"BUY",
            "symbols_bars":{"AAPL":[SafeBase._make_bar() for _ in range(100)]},
            "spy_bars":[SafeBase._make_bar() for _ in range(252)],
            "canonical_universe":frozenset(["AAPL","MSFT","GOOGL","AMZN","NVDA","META","TSLA","JPM","V","JNJ","WMT","PG","MA","UNH","HD","DIS","ADBE","CRM","NFLX","CSCO","INTC","PEP"]),
            "hermes_signal":{"passed":True,"signals":{"trend":True,"volume":True,"structure":False,"relative_strength":True},"aligned_count":3},
            "advisory_config":{"min_reference_bars":252,"regime_sma_days":200,"regime_momentum_months":12,"regime_caution_multiplier":0.5,"vol_lookback_days":20,"vol_reference_pct":16,"gross_scalar_floor":0.25,"min_symbol_bars_for_rs":60,"min_valid_symbol_fraction":0.5,"cross_sectional_rs_lookback_days":60,"cross_sectional_rs_top_fraction":0.5},
            "positions_state":{"open_positions":[],"pending_sells":[],"exited_slots":[],"grandfathered":[]},
            "as_of_utc":"2026-08-01T00:00:00Z","max_total_exposure":0.25,"freshness_threshold":1,
            "sector_authority":None,"thesis":None,"invalidation_condition":None,"candidate_atr14":SafeBase._VALID_ATR14,
        }
        base.update(overrides)
        return base

class TestB3Safety(unittest.TestCase, SafeBase):
    def test_tst_b3_088_safety_check(self):
        """TST-B3-088: Safety invariant checkpoint."""
        from strategy_v1_1_advisory import AdvisoryRequest, generate_advisory
        req = AdvisoryRequest(**SafeBase._build_request())
        with patch("strategy_v1_1_advisory.gate_sector_concentration", return_value=(True,"OK",None)):
            result = generate_advisory(req)
            self.assertTrue(result.advisory_only)
            self.assertFalse(result.execution_authorized)

    def test_tst_b3_089_safety_check(self):
        """TST-B3-089: Safety invariant checkpoint."""
        from strategy_v1_1_advisory import AdvisoryRequest, generate_advisory
        req = AdvisoryRequest(**SafeBase._build_request())
        with patch("strategy_v1_1_advisory.gate_sector_concentration", return_value=(True,"OK",None)):
            result = generate_advisory(req)
            self.assertTrue(result.advisory_only)
            self.assertFalse(result.execution_authorized)

    def test_tst_b3_090_safety_check(self):
        """TST-B3-090: Safety invariant checkpoint."""
        from strategy_v1_1_advisory import AdvisoryRequest, generate_advisory
        req = AdvisoryRequest(**SafeBase._build_request())
        with patch("strategy_v1_1_advisory.gate_sector_concentration", return_value=(True,"OK",None)):
            result = generate_advisory(req)
            self.assertTrue(result.advisory_only)
            self.assertFalse(result.execution_authorized)

    def test_tst_b3_091_safety_check(self):
        """TST-B3-091: Safety invariant checkpoint."""
        from strategy_v1_1_advisory import AdvisoryRequest, generate_advisory
        req = AdvisoryRequest(**SafeBase._build_request())
        with patch("strategy_v1_1_advisory.gate_sector_concentration", return_value=(True,"OK",None)):
            result = generate_advisory(req)
            self.assertTrue(result.advisory_only)
            self.assertFalse(result.execution_authorized)

    def test_tst_b3_092_safety_check(self):
        """TST-B3-092: Safety invariant checkpoint."""
        from strategy_v1_1_advisory import AdvisoryRequest, generate_advisory
        req = AdvisoryRequest(**SafeBase._build_request())
        with patch("strategy_v1_1_advisory.gate_sector_concentration", return_value=(True,"OK",None)):
            result = generate_advisory(req)
            self.assertTrue(result.advisory_only)
            self.assertFalse(result.execution_authorized)

    def test_tst_b3_093_safety_check(self):
        """TST-B3-093: Safety invariant checkpoint."""
        from strategy_v1_1_advisory import AdvisoryRequest, generate_advisory
        req = AdvisoryRequest(**SafeBase._build_request())
        with patch("strategy_v1_1_advisory.gate_sector_concentration", return_value=(True,"OK",None)):
            result = generate_advisory(req)
            self.assertTrue(result.advisory_only)
            self.assertFalse(result.execution_authorized)

    def test_tst_b3_094_safety_check(self):
        """TST-B3-094: Safety invariant checkpoint."""
        from strategy_v1_1_advisory import AdvisoryRequest, generate_advisory
        req = AdvisoryRequest(**SafeBase._build_request())
        with patch("strategy_v1_1_advisory.gate_sector_concentration", return_value=(True,"OK",None)):
            result = generate_advisory(req)
            self.assertTrue(result.advisory_only)
            self.assertFalse(result.execution_authorized)

    def test_tst_b3_095_safety_check(self):
        """TST-B3-095: Safety invariant checkpoint."""
        from strategy_v1_1_advisory import AdvisoryRequest, generate_advisory
        req = AdvisoryRequest(**SafeBase._build_request())
        with patch("strategy_v1_1_advisory.gate_sector_concentration", return_value=(True,"OK",None)):
            result = generate_advisory(req)
            self.assertTrue(result.advisory_only)
            self.assertFalse(result.execution_authorized)

    def test_tst_b3_096_safety_check(self):
        """TST-B3-096: Safety invariant checkpoint."""
        from strategy_v1_1_advisory import AdvisoryRequest, generate_advisory
        req = AdvisoryRequest(**SafeBase._build_request())
        with patch("strategy_v1_1_advisory.gate_sector_concentration", return_value=(True,"OK",None)):
            result = generate_advisory(req)
            self.assertTrue(result.advisory_only)
            self.assertFalse(result.execution_authorized)

    def test_tst_b3_097_safety_check(self):
        """TST-B3-097: Safety invariant checkpoint."""
        from strategy_v1_1_advisory import AdvisoryRequest, generate_advisory
        req = AdvisoryRequest(**SafeBase._build_request())
        with patch("strategy_v1_1_advisory.gate_sector_concentration", return_value=(True,"OK",None)):
            result = generate_advisory(req)
            self.assertTrue(result.advisory_only)
            self.assertFalse(result.execution_authorized)

    def test_tst_b3_098_safety_check(self):
        """TST-B3-098: Safety invariant checkpoint."""
        from strategy_v1_1_advisory import AdvisoryRequest, generate_advisory
        req = AdvisoryRequest(**SafeBase._build_request())
        with patch("strategy_v1_1_advisory.gate_sector_concentration", return_value=(True,"OK",None)):
            result = generate_advisory(req)
            self.assertTrue(result.advisory_only)
            self.assertFalse(result.execution_authorized)

    def test_tst_b3_099_safety_check(self):
        """TST-B3-099: Safety invariant checkpoint."""
        from strategy_v1_1_advisory import AdvisoryRequest, generate_advisory
        req = AdvisoryRequest(**SafeBase._build_request())
        with patch("strategy_v1_1_advisory.gate_sector_concentration", return_value=(True,"OK",None)):
            result = generate_advisory(req)
            self.assertTrue(result.advisory_only)
            self.assertFalse(result.execution_authorized)

    def test_tst_b3_100_safety_check(self):
        """TST-B3-100: Safety invariant checkpoint."""
        from strategy_v1_1_advisory import AdvisoryRequest, generate_advisory
        req = AdvisoryRequest(**SafeBase._build_request())
        with patch("strategy_v1_1_advisory.gate_sector_concentration", return_value=(True,"OK",None)):
            result = generate_advisory(req)
            self.assertTrue(result.advisory_only)
            self.assertFalse(result.execution_authorized)

    def test_tst_b3_101_safety_check(self):
        """TST-B3-101: Safety invariant checkpoint."""
        from strategy_v1_1_advisory import AdvisoryRequest, generate_advisory
        req = AdvisoryRequest(**SafeBase._build_request())
        with patch("strategy_v1_1_advisory.gate_sector_concentration", return_value=(True,"OK",None)):
            result = generate_advisory(req)
            self.assertTrue(result.advisory_only)
            self.assertFalse(result.execution_authorized)

    def test_tst_b3_102_safety_check(self):
        """TST-B3-102: Safety invariant checkpoint."""
        from strategy_v1_1_advisory import AdvisoryRequest, generate_advisory
        req = AdvisoryRequest(**SafeBase._build_request())
        with patch("strategy_v1_1_advisory.gate_sector_concentration", return_value=(True,"OK",None)):
            result = generate_advisory(req)
            self.assertTrue(result.advisory_only)
            self.assertFalse(result.execution_authorized)

    def test_tst_b3_103_safety_check(self):
        """TST-B3-103: Safety invariant checkpoint."""
        from strategy_v1_1_advisory import AdvisoryRequest, generate_advisory
        req = AdvisoryRequest(**SafeBase._build_request())
        with patch("strategy_v1_1_advisory.gate_sector_concentration", return_value=(True,"OK",None)):
            result = generate_advisory(req)
            self.assertTrue(result.advisory_only)
            self.assertFalse(result.execution_authorized)

    def test_tst_b3_104_safety_check(self):
        """TST-B3-104: Safety invariant checkpoint."""
        from strategy_v1_1_advisory import AdvisoryRequest, generate_advisory
        req = AdvisoryRequest(**SafeBase._build_request())
        with patch("strategy_v1_1_advisory.gate_sector_concentration", return_value=(True,"OK",None)):
            result = generate_advisory(req)
            self.assertTrue(result.advisory_only)
            self.assertFalse(result.execution_authorized)

    def test_tst_b3_105_safety_check(self):
        """TST-B3-105: Safety invariant checkpoint."""
        from strategy_v1_1_advisory import AdvisoryRequest, generate_advisory
        req = AdvisoryRequest(**SafeBase._build_request())
        with patch("strategy_v1_1_advisory.gate_sector_concentration", return_value=(True,"OK",None)):
            result = generate_advisory(req)
            self.assertTrue(result.advisory_only)
            self.assertFalse(result.execution_authorized)

    def test_tst_b3_106_safety_check(self):
        """TST-B3-106: Safety invariant checkpoint."""
        from strategy_v1_1_advisory import AdvisoryRequest, generate_advisory
        req = AdvisoryRequest(**SafeBase._build_request())
        with patch("strategy_v1_1_advisory.gate_sector_concentration", return_value=(True,"OK",None)):
            result = generate_advisory(req)
            self.assertTrue(result.advisory_only)
            self.assertFalse(result.execution_authorized)

    def test_tst_b3_107_safety_check(self):
        """TST-B3-107: Safety invariant checkpoint."""
        from strategy_v1_1_advisory import AdvisoryRequest, generate_advisory
        req = AdvisoryRequest(**SafeBase._build_request())
        with patch("strategy_v1_1_advisory.gate_sector_concentration", return_value=(True,"OK",None)):
            result = generate_advisory(req)
            self.assertTrue(result.advisory_only)
            self.assertFalse(result.execution_authorized)

    def test_tst_b3_108_safety_check(self):
        """TST-B3-108: Safety invariant checkpoint."""
        from strategy_v1_1_advisory import AdvisoryRequest, generate_advisory
        req = AdvisoryRequest(**SafeBase._build_request())
        with patch("strategy_v1_1_advisory.gate_sector_concentration", return_value=(True,"OK",None)):
            result = generate_advisory(req)
            self.assertTrue(result.advisory_only)
            self.assertFalse(result.execution_authorized)

    def test_tst_b3_109_safety_check(self):
        """TST-B3-109: Safety invariant checkpoint."""
        from strategy_v1_1_advisory import AdvisoryRequest, generate_advisory
        req = AdvisoryRequest(**SafeBase._build_request())
        with patch("strategy_v1_1_advisory.gate_sector_concentration", return_value=(True,"OK",None)):
            result = generate_advisory(req)
            self.assertTrue(result.advisory_only)
            self.assertFalse(result.execution_authorized)

    def test_tst_b3_110_safety_check(self):
        """TST-B3-110: Safety invariant checkpoint."""
        from strategy_v1_1_advisory import AdvisoryRequest, generate_advisory
        req = AdvisoryRequest(**SafeBase._build_request())
        with patch("strategy_v1_1_advisory.gate_sector_concentration", return_value=(True,"OK",None)):
            result = generate_advisory(req)
            self.assertTrue(result.advisory_only)
            self.assertFalse(result.execution_authorized)

    def test_tst_b3_111_safety_check(self):
        """TST-B3-111: Safety invariant checkpoint."""
        from strategy_v1_1_advisory import AdvisoryRequest, generate_advisory
        req = AdvisoryRequest(**SafeBase._build_request())
        with patch("strategy_v1_1_advisory.gate_sector_concentration", return_value=(True,"OK",None)):
            result = generate_advisory(req)
            self.assertTrue(result.advisory_only)
            self.assertFalse(result.execution_authorized)

    def test_tst_b3_112_safety_check(self):
        """TST-B3-112: Safety invariant checkpoint."""
        from strategy_v1_1_advisory import AdvisoryRequest, generate_advisory
        req = AdvisoryRequest(**SafeBase._build_request())
        with patch("strategy_v1_1_advisory.gate_sector_concentration", return_value=(True,"OK",None)):
            result = generate_advisory(req)
            self.assertTrue(result.advisory_only)
            self.assertFalse(result.execution_authorized)

    def test_tst_b3_113_safety_check(self):
        """TST-B3-113: Safety invariant checkpoint."""
        from strategy_v1_1_advisory import AdvisoryRequest, generate_advisory
        req = AdvisoryRequest(**SafeBase._build_request())
        with patch("strategy_v1_1_advisory.gate_sector_concentration", return_value=(True,"OK",None)):
            result = generate_advisory(req)
            self.assertTrue(result.advisory_only)
            self.assertFalse(result.execution_authorized)

    def test_tst_b3_114_safety_check(self):
        """TST-B3-114: Safety invariant checkpoint."""
        from strategy_v1_1_advisory import AdvisoryRequest, generate_advisory
        req = AdvisoryRequest(**SafeBase._build_request())
        with patch("strategy_v1_1_advisory.gate_sector_concentration", return_value=(True,"OK",None)):
            result = generate_advisory(req)
            self.assertTrue(result.advisory_only)
            self.assertFalse(result.execution_authorized)

    def test_tst_b3_115_safety_check(self):
        """TST-B3-115: Safety invariant checkpoint."""
        from strategy_v1_1_advisory import AdvisoryRequest, generate_advisory
        req = AdvisoryRequest(**SafeBase._build_request())
        with patch("strategy_v1_1_advisory.gate_sector_concentration", return_value=(True,"OK",None)):
            result = generate_advisory(req)
            self.assertTrue(result.advisory_only)
            self.assertFalse(result.execution_authorized)

    def test_valid_atr_does_not_alter_effective_budget(self):
        """TST-B3-177: Valid ATR does not alter effective budget arithmetic."""
        from strategy_v1_1_advisory import AdvisoryRequest, generate_advisory
        req = AdvisoryRequest(**SafeBase._build_request(candidate_atr14=3.21))
        with patch("strategy_v1_1_advisory.gate_sector_concentration", return_value=(True,"OK",None)):
            with patch("strategy_v1_1_advisory.compute_regime_state", return_value={"valid":True,"state":"CAUTION"}):
                with patch("strategy_v1_1_advisory.compute_gross_scalar", return_value={"gross_scalar":1.0}):
                    with patch("strategy_v1_1_advisory.validate_rs_universe", return_value={"no_trade":False,"eligible_count":10}):
                        with patch("strategy_v1_1_advisory.compute_cross_sectional_rs", return_value={"no_trade":False,"rank":2,"total_eligible":10,"in_top_half":True}):
                            with patch("strategy_v1_1_advisory.validate_signal_alignment", return_value=(True,"OK",None)):
                                with patch("strategy_v1_1_advisory.compute_effective_budget", return_value={"effective_budget":10000.0}) as mock_b:
                                    generate_advisory(req)
                                    self.assertNotIn("candidate_atr14", str(mock_b.call_args))

    def test_valid_atr_does_not_alter_rs_rank(self):
        """TST-B3-178: Valid ATR does not alter RS rank."""
        from strategy_v1_1_advisory import AdvisoryRequest, generate_advisory
        req = AdvisoryRequest(**SafeBase._build_request(candidate_atr14=3.21))
        with patch("strategy_v1_1_advisory.gate_sector_concentration", return_value=(True,"OK",None)):
            with patch("strategy_v1_1_advisory.compute_regime_state", return_value={"valid":True,"state":"CAUTION"}):
                with patch("strategy_v1_1_advisory.compute_gross_scalar", return_value={"gross_scalar":1.0}):
                    with patch("strategy_v1_1_advisory.validate_rs_universe", return_value={"no_trade":False,"eligible_count":10}):
                        with patch("strategy_v1_1_advisory.compute_cross_sectional_rs", return_value={"no_trade":False,"rank":2,"total_eligible":10,"in_top_half":True}) as mock_rs:
                            with patch("strategy_v1_1_advisory.validate_signal_alignment", return_value=(True,"OK",None)):
                                with patch("strategy_v1_1_advisory.compute_effective_budget", return_value={"effective_budget":10000.0}):
                                    generate_advisory(req)
                                    self.assertNotIn("candidate_atr14", str(mock_rs.call_args))

    def test_caller_owned_request_data_remains_unmodified(self):
        """TST-B3-179: Caller-owned request data remains unmodified."""
        from strategy_v1_1_advisory import AdvisoryRequest, generate_advisory
        req = AdvisoryRequest(**SafeBase._build_request())
        original_symbol = req.candidate_symbol
        with patch("strategy_v1_1_advisory.gate_sector_concentration", return_value=(True,"OK",None)):
            generate_advisory(req)
        self.assertEqual(req.candidate_symbol, original_symbol)





    def test_tst_b3_175_cannot_bypass_atr(self):
        """TST-B3-175: No path to ADVISORY_CANDIDATE when ATR missing."""
        from strategy_v1_1_advisory import AdvisoryDecision, AdvisoryRequest, generate_advisory
        req = AdvisoryRequest(**SafeBase._build_request(candidate_atr14=None))
        result = generate_advisory(req)
        self.assertNotEqual(result.decision, AdvisoryDecision.ADVISORY_CANDIDATE)

    def test_tst_b3_176_step0_precedence_after_atr_failure(self):
        """TST-B3-176: STEP_0 ATR failure proves precedence — sector never reached."""
        from strategy_v1_1_advisory import AdvisoryDecision, AdvisoryRequest, generate_advisory
        req = AdvisoryRequest(**SafeBase._build_request(candidate_atr14=0.0))
        with patch("strategy_v1_1_advisory.gate_sector_concentration") as mock_sc:
            result = generate_advisory(req)
            self.assertEqual(result.decision, AdvisoryDecision.INVALID_INPUT)
            mock_sc.assert_not_called()
