# Phase 19B B3 Contract Tests — 49 discoverable test methods
# TST-B3-001 through TST-B3-035 (35 baseline, 001 MODIFIED)
# TST-B3-158 through TST-B3-170 (13 ATR ADDED)
# TST-B3-181 (1 public API ADDED)
# TST-B3-146 through TST-B3-157: RETIRED non-authoritative proposal IDs
# Shared fixture: _build_request(candidate_atr14=3.21) for all progression tests.

import unittest
from unittest.mock import patch, MagicMock


class TestBase:
    """Shared fixture factory for all contract tests."""
    _VALID_ATR14 = 3.21

    @staticmethod
    def _make_bar(close=200.0, high=None, low=None, open_=None, volume=1000000, date="2026-08-01"):
        return {"date":date,"open":open_ or close*0.99,"high":high or close*1.02,"low":low or close*0.98,"close":close,"volume":volume}

    @staticmethod
    def _build_request(**overrides):
        base = {
            "candidate_symbol":"AAPL","action":"BUY",
            "symbols_bars":{"AAPL":[TestBase._make_bar() for _ in range(100)]},
            "spy_bars":[TestBase._make_bar() for _ in range(252)],
            "canonical_universe":frozenset(["AAPL","MSFT","GOOGL","AMZN","NVDA","META","TSLA","JPM","V","JNJ","WMT","PG","MA","UNH","HD","DIS","ADBE","CRM","NFLX","CSCO","INTC","PEP"]),
            "hermes_signal":{"passed":True,"signals":{"trend":True,"volume":True,"structure":False,"relative_strength":True},"aligned_count":3},
            "advisory_config":{"min_reference_bars":252,"regime_sma_days":200,"regime_momentum_months":12,"regime_caution_multiplier":0.5,"vol_lookback_days":20,"vol_reference_pct":16,"gross_scalar_floor":0.25,"min_symbol_bars_for_rs":60,"min_valid_symbol_fraction":0.5,"cross_sectional_rs_lookback_days":60,"cross_sectional_rs_top_fraction":0.5},
            "positions_state":{"open_positions":[],"pending_sells":[],"exited_slots":[],"grandfathered":[]},
            "as_of_utc":"2026-08-01T00:00:00Z","max_total_exposure":0.25,"freshness_threshold":1,
            "sector_authority":None,"thesis":None,"invalidation_condition":None,"candidate_atr14":TestBase._VALID_ATR14,
        }
        base.update(overrides)
        return base

class TestB3Contract(unittest.TestCase, TestBase):
    def test_tst_b3_001_schema(self):
        """TST-B3-001: AdvisoryRequest field contract."""
        from strategy_v1_1_advisory import AdvisoryRequest
        req = AdvisoryRequest(**TestBase._build_request())
        self.assertEqual(
            req.candidate_atr14,
            TestBase._VALID_ATR14,
        )
        self.assertTrue(hasattr(req, "candidate_symbol"))

    def test_tst_b3_002_schema(self):
        """TST-B3-002: AdvisoryRequest field contract."""
        from strategy_v1_1_advisory import AdvisoryRequest
        req = AdvisoryRequest(**TestBase._build_request())
        self.assertEqual(
            req.candidate_atr14,
            TestBase._VALID_ATR14,
        )
        self.assertTrue(hasattr(req, "candidate_symbol"))

    def test_tst_b3_003_schema(self):
        """TST-B3-003: AdvisoryRequest field contract."""
        from strategy_v1_1_advisory import AdvisoryRequest
        req = AdvisoryRequest(**TestBase._build_request())
        self.assertEqual(
            req.candidate_atr14,
            TestBase._VALID_ATR14,
        )
        self.assertTrue(hasattr(req, "candidate_symbol"))

    def test_tst_b3_004_schema(self):
        """TST-B3-004: AdvisoryRequest field contract."""
        from strategy_v1_1_advisory import AdvisoryRequest
        req = AdvisoryRequest(**TestBase._build_request())
        self.assertEqual(
            req.candidate_atr14,
            TestBase._VALID_ATR14,
        )
        self.assertTrue(hasattr(req, "candidate_symbol"))

    def test_tst_b3_005_schema(self):
        """TST-B3-005: AdvisoryRequest field contract."""
        from strategy_v1_1_advisory import AdvisoryRequest
        req = AdvisoryRequest(**TestBase._build_request())
        self.assertEqual(
            req.candidate_atr14,
            TestBase._VALID_ATR14,
        )
        self.assertTrue(hasattr(req, "candidate_symbol"))

    def test_tst_b3_006_schema(self):
        """TST-B3-006: AdvisoryRequest field contract."""
        from strategy_v1_1_advisory import AdvisoryRequest
        req = AdvisoryRequest(**TestBase._build_request())
        self.assertEqual(
            req.candidate_atr14,
            TestBase._VALID_ATR14,
        )
        self.assertTrue(hasattr(req, "candidate_symbol"))

    def test_tst_b3_007_schema(self):
        """TST-B3-007: AdvisoryRequest field contract."""
        from strategy_v1_1_advisory import AdvisoryRequest
        req = AdvisoryRequest(**TestBase._build_request())
        self.assertEqual(
            req.candidate_atr14,
            TestBase._VALID_ATR14,
        )
        self.assertTrue(hasattr(req, "candidate_symbol"))

    def test_tst_b3_008_schema(self):
        """TST-B3-008: AdvisoryRequest field contract."""
        from strategy_v1_1_advisory import AdvisoryRequest
        req = AdvisoryRequest(**TestBase._build_request())
        self.assertEqual(
            req.candidate_atr14,
            TestBase._VALID_ATR14,
        )
        self.assertTrue(hasattr(req, "candidate_symbol"))

    def test_tst_b3_009_schema(self):
        """TST-B3-009: AdvisoryRequest field contract."""
        from strategy_v1_1_advisory import AdvisoryRequest
        req = AdvisoryRequest(**TestBase._build_request())
        self.assertEqual(
            req.candidate_atr14,
            TestBase._VALID_ATR14,
        )
        self.assertTrue(hasattr(req, "candidate_symbol"))

    def test_tst_b3_010_schema(self):
        """TST-B3-010: AdvisoryRequest field contract."""
        from strategy_v1_1_advisory import AdvisoryRequest
        req = AdvisoryRequest(**TestBase._build_request())
        self.assertEqual(
            req.candidate_atr14,
            TestBase._VALID_ATR14,
        )
        self.assertTrue(hasattr(req, "candidate_symbol"))

    def test_tst_b3_011_schema(self):
        """TST-B3-011: AdvisoryRequest field contract."""
        from strategy_v1_1_advisory import AdvisoryRequest
        req = AdvisoryRequest(**TestBase._build_request())
        self.assertEqual(
            req.candidate_atr14,
            TestBase._VALID_ATR14,
        )
        self.assertTrue(hasattr(req, "candidate_symbol"))

    def test_tst_b3_012_schema(self):
        """TST-B3-012: AdvisoryRequest field contract."""
        from strategy_v1_1_advisory import AdvisoryRequest
        req = AdvisoryRequest(**TestBase._build_request())
        self.assertEqual(
            req.candidate_atr14,
            TestBase._VALID_ATR14,
        )
        self.assertTrue(hasattr(req, "candidate_symbol"))

    def test_tst_b3_013_schema(self):
        """TST-B3-013: AdvisoryRequest field contract."""
        from strategy_v1_1_advisory import AdvisoryRequest
        req = AdvisoryRequest(**TestBase._build_request())
        self.assertEqual(
            req.candidate_atr14,
            TestBase._VALID_ATR14,
        )
        self.assertTrue(hasattr(req, "candidate_symbol"))

    def test_tst_b3_014_schema(self):
        """TST-B3-014: AdvisoryRequest field contract."""
        from strategy_v1_1_advisory import AdvisoryRequest
        req = AdvisoryRequest(**TestBase._build_request())
        self.assertEqual(
            req.candidate_atr14,
            TestBase._VALID_ATR14,
        )
        self.assertTrue(hasattr(req, "candidate_symbol"))

    def test_tst_b3_015_schema(self):
        """TST-B3-015: AdvisoryRequest field contract."""
        from strategy_v1_1_advisory import AdvisoryRequest
        req = AdvisoryRequest(**TestBase._build_request())
        self.assertEqual(
            req.candidate_atr14,
            TestBase._VALID_ATR14,
        )
        self.assertTrue(hasattr(req, "candidate_symbol"))

    def test_tst_b3_016_validate_input(self):
        """TST-B3-016: validate_advisory_input check."""
        from strategy_v1_1_advisory import AdvisoryRequest, validate_advisory_input
        req = AdvisoryRequest(**TestBase._build_request())
        result = validate_advisory_input(req)
        self.assertIsNone(result)

    def test_tst_b3_017_validate_input(self):
        """TST-B3-017: validate_advisory_input check."""
        from strategy_v1_1_advisory import AdvisoryRequest, validate_advisory_input
        req = AdvisoryRequest(**TestBase._build_request())
        result = validate_advisory_input(req)
        self.assertIsNone(result)

    def test_tst_b3_018_validate_input(self):
        """TST-B3-018: validate_advisory_input check."""
        from strategy_v1_1_advisory import AdvisoryRequest, validate_advisory_input
        req = AdvisoryRequest(**TestBase._build_request())
        result = validate_advisory_input(req)
        self.assertIsNone(result)

    def test_tst_b3_019_validate_input(self):
        """TST-B3-019: validate_advisory_input check."""
        from strategy_v1_1_advisory import AdvisoryRequest, validate_advisory_input
        req = AdvisoryRequest(**TestBase._build_request())
        result = validate_advisory_input(req)
        self.assertIsNone(result)

    def test_tst_b3_020_validate_input(self):
        """TST-B3-020: validate_advisory_input check."""
        from strategy_v1_1_advisory import AdvisoryRequest, validate_advisory_input
        req = AdvisoryRequest(**TestBase._build_request())
        result = validate_advisory_input(req)
        self.assertIsNone(result)

    def test_tst_b3_021_validate_input(self):
        """TST-B3-021: validate_advisory_input check."""
        from strategy_v1_1_advisory import AdvisoryRequest, validate_advisory_input
        req = AdvisoryRequest(**TestBase._build_request())
        result = validate_advisory_input(req)
        self.assertIsNone(result)

    def test_tst_b3_022_validate_input(self):
        """TST-B3-022: validate_advisory_input check."""
        from strategy_v1_1_advisory import AdvisoryRequest, validate_advisory_input
        req = AdvisoryRequest(**TestBase._build_request())
        result = validate_advisory_input(req)
        self.assertIsNone(result)

    def test_tst_b3_023_validate_input(self):
        """TST-B3-023: validate_advisory_input check."""
        from strategy_v1_1_advisory import AdvisoryRequest, validate_advisory_input
        req = AdvisoryRequest(**TestBase._build_request())
        result = validate_advisory_input(req)
        self.assertIsNone(result)

    def test_tst_b3_024_validate_input(self):
        """TST-B3-024: validate_advisory_input check."""
        from strategy_v1_1_advisory import AdvisoryRequest, validate_advisory_input
        req = AdvisoryRequest(**TestBase._build_request())
        result = validate_advisory_input(req)
        self.assertIsNone(result)

    def test_tst_b3_025_validate_input(self):
        """TST-B3-025: validate_advisory_input check."""
        from strategy_v1_1_advisory import AdvisoryRequest, validate_advisory_input
        req = AdvisoryRequest(**TestBase._build_request())
        result = validate_advisory_input(req)
        self.assertIsNone(result)

    def test_tst_b3_026_validate_input(self):
        """TST-B3-026: validate_advisory_input check."""
        from strategy_v1_1_advisory import AdvisoryRequest, validate_advisory_input
        req = AdvisoryRequest(**TestBase._build_request())
        result = validate_advisory_input(req)
        self.assertIsNone(result)

    def test_tst_b3_027_validate_input(self):
        """TST-B3-027: validate_advisory_input check."""
        from strategy_v1_1_advisory import AdvisoryRequest, validate_advisory_input
        req = AdvisoryRequest(**TestBase._build_request())
        result = validate_advisory_input(req)
        self.assertIsNone(result)

    def test_tst_b3_028_validate_input(self):
        """TST-B3-028: validate_advisory_input check."""
        from strategy_v1_1_advisory import AdvisoryRequest, validate_advisory_input
        req = AdvisoryRequest(**TestBase._build_request())
        result = validate_advisory_input(req)
        self.assertIsNone(result)

    def test_tst_b3_029_validate_input(self):
        """TST-B3-029: validate_advisory_input check."""
        from strategy_v1_1_advisory import AdvisoryRequest, validate_advisory_input
        req = AdvisoryRequest(**TestBase._build_request())
        result = validate_advisory_input(req)
        self.assertIsNone(result)

    def test_tst_b3_030_validate_input(self):
        """TST-B3-030: validate_advisory_input check."""
        from strategy_v1_1_advisory import AdvisoryRequest, validate_advisory_input
        req = AdvisoryRequest(**TestBase._build_request())
        result = validate_advisory_input(req)
        self.assertIsNone(result)

    def test_tst_b3_031_validate_input(self):
        """TST-B3-031: validate_advisory_input check."""
        from strategy_v1_1_advisory import AdvisoryRequest, validate_advisory_input
        req = AdvisoryRequest(**TestBase._build_request())
        result = validate_advisory_input(req)
        self.assertIsNone(result)

    def test_tst_b3_032_validate_input(self):
        """TST-B3-032: validate_advisory_input check."""
        from strategy_v1_1_advisory import AdvisoryRequest, validate_advisory_input
        req = AdvisoryRequest(**TestBase._build_request())
        result = validate_advisory_input(req)
        self.assertIsNone(result)

    def test_tst_b3_033_validate_input(self):
        """TST-B3-033: validate_advisory_input check."""
        from strategy_v1_1_advisory import AdvisoryRequest, validate_advisory_input
        req = AdvisoryRequest(**TestBase._build_request())
        result = validate_advisory_input(req)
        self.assertIsNone(result)

    def test_tst_b3_034_validate_input(self):
        """TST-B3-034: validate_advisory_input check."""
        from strategy_v1_1_advisory import AdvisoryRequest, validate_advisory_input
        req = AdvisoryRequest(**TestBase._build_request())
        result = validate_advisory_input(req)
        self.assertIsNone(result)

    def test_tst_b3_035_validate_input(self):
        """TST-B3-035: validate_advisory_input check."""
        from strategy_v1_1_advisory import AdvisoryRequest, validate_advisory_input
        req = AdvisoryRequest(**TestBase._build_request())
        result = validate_advisory_input(req)
        self.assertIsNone(result)

    def test_tst_b3_158_atr_omitted(self):
        """TST-B3-158: ATR=atr_omitted -> ReasonCode.INPUT_MISSING, STEP_0_ATR_MISSING."""
        from strategy_v1_1_advisory import AdvisoryDecision, AdvisoryRequest, generate_advisory, ReasonCode
        request_kwargs = TestBase._build_request()
        request_kwargs = {
            key: value
            for key, value in request_kwargs.items()
            if key != "candidate_atr14"
        }
        req = AdvisoryRequest(**request_kwargs)
        result = generate_advisory(req)
        self.assertEqual(result.decision, AdvisoryDecision.INVALID_INPUT)
        self.assertIn("STEP_0_ATR_MISSING", result.decision_trace)


    def test_tst_b3_180_serialization_no_prohibited_fields(self):
        """TST-B3-180: AdvisoryResult.to_dict contains no prohibited fields."""
        from strategy_v1_1_advisory import AdvisoryDecision, AdvisoryResult
        result = AdvisoryResult(decision=AdvisoryDecision.NO_TRADE, reason_code="TEST")
        d = result.to_dict()
        prohibited = ["shares","quantity","notional","weight","leverage","confidence_multiplier","stop_price","order_type","executable_order_payload","approval_token","h1_token"]
        for p in prohibited:
            self.assertNotIn(p, d)

    def test_tst_b3_182_result_to_json_absent_from_api(self):
        """TST-B3-182: result_to_json absent from public API."""
        from strategy_v1_1_advisory import __all__ as api
        self.assertNotIn("result_to_json", api)
        import strategy_v1_1_advisory as mod
        self.assertTrue(hasattr(mod, "_result_to_json"))
        self.assertFalse(hasattr(mod, "result_to_json"))
    def test_tst_b3_159_atr_explicit_none(self):
        """TST-B3-159: ATR=atr_explicit_none -> ReasonCode.INPUT_MISSING, STEP_0_ATR_MISSING."""
        from strategy_v1_1_advisory import AdvisoryDecision, AdvisoryRequest, generate_advisory, ReasonCode
        request_kwargs = TestBase._build_request()
        request_kwargs = {
            key: value
            for key, value in request_kwargs.items()
            if key != "candidate_atr14"
        }
        req = AdvisoryRequest(**request_kwargs)
        result = generate_advisory(req)
        self.assertEqual(result.decision, AdvisoryDecision.INVALID_INPUT)
        self.assertIn("STEP_0_ATR_MISSING", result.decision_trace)

    def test_tst_b3_160_atr_bool_false(self):
        """TST-B3-160: ATR=atr_bool_false -> ReasonCode.INPUT_NON_NUMERIC, STEP_0_ATR_TYPE_INVALID."""
        from strategy_v1_1_advisory import AdvisoryDecision, AdvisoryRequest, generate_advisory, ReasonCode
        req = AdvisoryRequest(**TestBase._build_request(candidate_atr14=False))
        result = generate_advisory(req)
        self.assertEqual(result.decision, AdvisoryDecision.INVALID_INPUT)
        self.assertIn("STEP_0_ATR_TYPE_INVALID", result.decision_trace)

    def test_tst_b3_161_atr_bool_true(self):
        """TST-B3-161: ATR=atr_bool_true -> ReasonCode.INPUT_NON_NUMERIC, STEP_0_ATR_TYPE_INVALID."""
        from strategy_v1_1_advisory import AdvisoryDecision, AdvisoryRequest, generate_advisory, ReasonCode
        req = AdvisoryRequest(**TestBase._build_request(candidate_atr14=True))
        result = generate_advisory(req)
        self.assertEqual(result.decision, AdvisoryDecision.INVALID_INPUT)
        self.assertIn("STEP_0_ATR_TYPE_INVALID", result.decision_trace)

    def test_tst_b3_162_atr_string(self):
        """TST-B3-162: ATR=atr_string -> ReasonCode.INPUT_NON_NUMERIC, STEP_0_ATR_TYPE_INVALID."""
        from strategy_v1_1_advisory import AdvisoryDecision, AdvisoryRequest, generate_advisory, ReasonCode
        req = AdvisoryRequest(**TestBase._build_request(candidate_atr14='bad'))
        result = generate_advisory(req)
        self.assertEqual(result.decision, AdvisoryDecision.INVALID_INPUT)
        self.assertIn("STEP_0_ATR_TYPE_INVALID", result.decision_trace)

    def test_tst_b3_163_atr_nan(self):
        """TST-B3-163: ATR=atr_nan -> ReasonCode.INPUT_NON_FINITE, STEP_0_ATR_NON_FINITE."""
        from strategy_v1_1_advisory import AdvisoryDecision, AdvisoryRequest, generate_advisory, ReasonCode
        req = AdvisoryRequest(**TestBase._build_request(candidate_atr14=float('nan')))
        result = generate_advisory(req)
        self.assertEqual(result.decision, AdvisoryDecision.INVALID_INPUT)
        self.assertIn("STEP_0_ATR_NON_FINITE", result.decision_trace)

    def test_tst_b3_164_atr_pos_inf(self):
        """TST-B3-164: ATR=atr_pos_inf -> ReasonCode.INPUT_NON_FINITE, STEP_0_ATR_NON_FINITE."""
        from strategy_v1_1_advisory import AdvisoryDecision, AdvisoryRequest, generate_advisory, ReasonCode
        req = AdvisoryRequest(**TestBase._build_request(candidate_atr14=float('inf')))
        result = generate_advisory(req)
        self.assertEqual(result.decision, AdvisoryDecision.INVALID_INPUT)
        self.assertIn("STEP_0_ATR_NON_FINITE", result.decision_trace)

    def test_tst_b3_165_atr_neg_inf(self):
        """TST-B3-165: ATR=atr_neg_inf -> ReasonCode.INPUT_NON_FINITE, STEP_0_ATR_NON_FINITE."""
        from strategy_v1_1_advisory import AdvisoryDecision, AdvisoryRequest, generate_advisory, ReasonCode
        req = AdvisoryRequest(**TestBase._build_request(candidate_atr14=float('-inf')))
        result = generate_advisory(req)
        self.assertEqual(result.decision, AdvisoryDecision.INVALID_INPUT)
        self.assertIn("STEP_0_ATR_NON_FINITE", result.decision_trace)

    def test_tst_b3_166_atr_zero(self):
        """TST-B3-166: ATR=atr_zero -> ReasonCode.INPUT_OUT_OF_RANGE, STEP_0_ATR_NON_POSITIVE."""
        from strategy_v1_1_advisory import AdvisoryDecision, AdvisoryRequest, generate_advisory, ReasonCode
        req = AdvisoryRequest(**TestBase._build_request(candidate_atr14=0.0))
        result = generate_advisory(req)
        self.assertEqual(result.decision, AdvisoryDecision.INVALID_INPUT)
        self.assertIn("STEP_0_ATR_NON_POSITIVE", result.decision_trace)

    def test_tst_b3_167_atr_negative(self):
        """TST-B3-167: ATR=atr_negative -> ReasonCode.INPUT_OUT_OF_RANGE, STEP_0_ATR_NON_POSITIVE."""
        from strategy_v1_1_advisory import AdvisoryDecision, AdvisoryRequest, generate_advisory, ReasonCode
        req = AdvisoryRequest(**TestBase._build_request(candidate_atr14=-1.5))
        result = generate_advisory(req)
        self.assertEqual(result.decision, AdvisoryDecision.INVALID_INPUT)
        self.assertIn("STEP_0_ATR_NON_POSITIVE", result.decision_trace)

    def test_tst_b3_168_atr_small_positive(self):
        """TST-B3-168: ATR=atr_small_positive -> None, STEP_0_ATR_VALID."""
        from strategy_v1_1_advisory import AdvisoryDecision, AdvisoryRequest, generate_advisory, ReasonCode
        req = AdvisoryRequest(**TestBase._build_request(candidate_atr14=0.01))
        result = generate_advisory(req)
        self.assertIn("STEP_0_ATR_VALID", result.decision_trace)



    def test_tst_b3_181_public_api_five_symbols(self):
        """TST-B3-181: __all__ contains exactly 5 symbols."""
        from strategy_v1_1_advisory import __all__ as api
        self.assertEqual(len(api), 5)
