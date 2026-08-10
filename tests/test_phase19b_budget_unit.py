"""
Phase 19B B2 — Budget unit tests.

R006/R029 — compute_effective_budget, compute_remaining_budget.
HIQ-011 — NetLiquidation fail-closed.
"""

import unittest
import strategy_v1_1_core as mod


class TestEffectiveBudget(unittest.TestCase):
    def test_risk_on_full(self):
        r = mod.compute_effective_budget(max_total_exposure_pct=30.0, gross_scalar=1.0,
                                          regime="RISK_ON")
        self.assertAlmostEqual(r["effective_budget_pct"], 30.0)
        self.assertEqual(r["reason"], mod.ReasonCode.BUDGET_COMPUTED)
        self.assertTrue(r["assertion_passed"])

    def test_caution_half(self):
        r = mod.compute_effective_budget(max_total_exposure_pct=30.0, gross_scalar=1.0,
                                          regime="CAUTION", caution_multiplier=0.5)
        self.assertAlmostEqual(r["effective_budget_pct"], 15.0)
        self.assertEqual(r["reason"], mod.ReasonCode.BUDGET_COMPUTED)

    def test_risk_off_zero(self):
        r = mod.compute_effective_budget(max_total_exposure_pct=30.0, regime="RISK_OFF")
        self.assertAlmostEqual(r["effective_budget_pct"], 0.0)
        self.assertEqual(r["reason"], mod.ReasonCode.BUDGET_RISK_OFF)
        self.assertAlmostEqual(r["regime_multiplier"], 0.0)

    def test_unknown_regime(self):
        r = mod.compute_effective_budget(regime="UNKNOWN")
        self.assertAlmostEqual(r["effective_budget_pct"], 0.0)
        self.assertEqual(r["reason"], mod.ReasonCode.BUDGET_RISK_OFF)
        self.assertFalse(r["assertion_passed"])

    def test_scalar_floor(self):
        """gross_scalar=0.25, RISK_ON → 30 * 0.25 = 7.5."""
        r = mod.compute_effective_budget(max_total_exposure_pct=30.0, gross_scalar=0.25)
        self.assertAlmostEqual(r["effective_budget_pct"], 7.5)

    def test_caution_with_scalar(self):
        """gross_scalar=0.5, CAUTION → 30 * 0.5 * 0.5 = 7.5."""
        r = mod.compute_effective_budget(max_total_exposure_pct=30.0, gross_scalar=0.5,
                                          regime="CAUTION")
        self.assertAlmostEqual(r["effective_budget_pct"], 7.5)

    def test_custom_caution_multiplier(self):
        r = mod.compute_effective_budget(max_total_exposure_pct=30.0, gross_scalar=1.0,
                                          regime="CAUTION", caution_multiplier=0.75)
        self.assertAlmostEqual(r["effective_budget_pct"], 22.5)

    def test_assertion_invariant(self):
        """effective should never exceed max_total_exposure_pct."""
        r = mod.compute_effective_budget(max_total_exposure_pct=30.0, gross_scalar=1.0)
        self.assertTrue(r["assertion_passed"])
        self.assertLessEqual(r["effective_budget_pct"], 30.0)

    def test_non_default_max(self):
        r = mod.compute_effective_budget(max_total_exposure_pct=20.0, gross_scalar=1.0)
        self.assertAlmostEqual(r["effective_budget_pct"], 20.0)


class TestRemainingBudget(unittest.TestCase):
    def test_available(self):
        r = mod.compute_remaining_budget(effective_budget_pct=30.0,
                                          net_liquidation_eur=10000.0,
                                          exchange_rate=1.10)
        self.assertGreater(r["remaining_budget_usd"], 0)
        self.assertEqual(r["reason"], mod.ReasonCode.BUDGET_AVAILABLE)
        self.assertFalse(r["budget_exhausted"])

    def test_available_values(self):
        r = mod.compute_remaining_budget(30.0, 10000.0, 1.10)
        expected_usd = (30.0 / 100.0) * 10000.0 * 1.10  # 3300
        self.assertAlmostEqual(r["effective_budget_usd"], expected_usd)
        self.assertAlmostEqual(r["remaining_budget_usd"], expected_usd)

    def test_exhausted(self):
        r = mod.compute_remaining_budget(effective_budget_pct=30.0,
                                          net_liquidation_eur=10000.0,
                                          exchange_rate=1.10,
                                          existing_exposure_usd=5000.0)
        self.assertTrue(r["budget_exhausted"])
        self.assertEqual(r["reason"], mod.ReasonCode.BUDGET_EXHAUSTED)
        self.assertAlmostEqual(r["remaining_budget_usd"], 0.0)

    def test_partial_remaining(self):
        r = mod.compute_remaining_budget(effective_budget_pct=30.0,
                                          net_liquidation_eur=10000.0,
                                          exchange_rate=1.10,
                                          existing_exposure_usd=1000.0)
        self.assertAlmostEqual(r["remaining_budget_usd"], 2300.0)
        self.assertFalse(r["budget_exhausted"])


class TestRemainingBudgetFailClosed(unittest.TestCase):
    """HIQ-011: fail closed on invalid NetLiquidation."""

    def test_zero_netliq(self):
        r = mod.compute_remaining_budget(30.0, 0.0, 1.10)
        self.assertEqual(r["reason"], mod.ReasonCode.INPUT_NON_FINITE)
        self.assertTrue(r["budget_exhausted"])

    def test_negative_netliq(self):
        r = mod.compute_remaining_budget(30.0, -1000, 1.10)
        self.assertEqual(r["reason"], mod.ReasonCode.INPUT_NON_FINITE)

    def test_nan_netliq(self):
        r = mod.compute_remaining_budget(30.0, float("nan"), 1.10)
        self.assertEqual(r["reason"], mod.ReasonCode.INPUT_NON_FINITE)

    def test_inf_netliq(self):
        r = mod.compute_remaining_budget(30.0, float("inf"), 1.10)
        self.assertEqual(r["reason"], mod.ReasonCode.INPUT_NON_FINITE)

    def test_bool_netliq(self):
        r = mod.compute_remaining_budget(30.0, True, 1.10)
        self.assertEqual(r["reason"], mod.ReasonCode.INPUT_NON_FINITE)

    def test_string_netliq(self):
        r = mod.compute_remaining_budget(30.0, "1000", 1.10)
        self.assertEqual(r["reason"], mod.ReasonCode.INPUT_NON_FINITE)

    def test_zero_exchange_rate(self):
        r = mod.compute_remaining_budget(30.0, 10000, 0.0)
        self.assertEqual(r["reason"], mod.ReasonCode.INPUT_NON_FINITE)

    def test_negative_exchange_rate(self):
        r = mod.compute_remaining_budget(30.0, 10000, -1.1)
        self.assertEqual(r["reason"], mod.ReasonCode.INPUT_NON_FINITE)

    def test_nan_exchange_rate(self):
        r = mod.compute_remaining_budget(30.0, 10000, float("nan"))
        self.assertEqual(r["reason"], mod.ReasonCode.INPUT_NON_FINITE)

    def test_existing_exposure_pct(self):
        r = mod.compute_remaining_budget(30.0, 10000, 1.10, existing_exposure_usd=1500)
        self.assertAlmostEqual(r["existing_exposure_pct"], 1500 / 11000 * 100, places=2)


class TestBudgetChain(unittest.TestCase):
    """End-to-end budget chain: regime → effective → remaining."""

    def test_risk_on_chain(self):
        eff = mod.compute_effective_budget(max_total_exposure_pct=30.0, gross_scalar=1.0,
                                            regime="RISK_ON")
        rem = mod.compute_remaining_budget(eff["effective_budget_pct"],
                                            net_liquidation_eur=50000.0,
                                            exchange_rate=1.05)
        self.assertGreater(rem["remaining_budget_usd"], 0)
        self.assertEqual(rem["reason"], mod.ReasonCode.BUDGET_AVAILABLE)

    def test_risk_off_chain(self):
        eff = mod.compute_effective_budget(regime="RISK_OFF")
        rem = mod.compute_remaining_budget(eff["effective_budget_pct"],
                                            net_liquidation_eur=50000.0,
                                            exchange_rate=1.05)
        self.assertAlmostEqual(rem["remaining_budget_usd"], 0.0)
        self.assertTrue(rem["budget_exhausted"])


class TestBudgetDeterminism(unittest.TestCase):
    def test_deterministic(self):
        import json
        r1 = mod.compute_effective_budget(max_total_exposure_pct=30.0, gross_scalar=0.7,
                                           regime="CAUTION", caution_multiplier=0.5)
        r2 = mod.compute_effective_budget(max_total_exposure_pct=30.0, gross_scalar=0.7,
                                           regime="CAUTION", caution_multiplier=0.5)
        self.assertEqual(json.dumps(r1), json.dumps(r2))


if __name__ == "__main__":
    unittest.main()
