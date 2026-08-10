"""
Phase 19B B2 — Gate I unit tests (sector concentration gate).

R007 / HIQ-006 / HIQ-007 — gate_sector_concentration.
"""

import unittest
import strategy_v1_1_core as mod


class TestGateIBasic(unittest.TestCase):
    def test_pass_empty_positions(self):
        ok, reason, details = mod.gate_sector_concentration("AAPL", [])
        self.assertTrue(ok)
        self.assertEqual(reason, mod.ReasonCode.GATE_I_PASS)
        self.assertEqual(details["sector"], "INFORMATION_TECHNOLOGY")

    def test_block_same_sector(self):
        ok, reason, details = mod.gate_sector_concentration(
            "AAPL", [{"symbol": "AAPL"}])
        self.assertFalse(ok)
        self.assertEqual(reason, mod.ReasonCode.GATE_I_SECTOR_FULL)

    def test_allow_different_sector(self):
        ok, reason, details = mod.gate_sector_concentration(
            "NVDA", [{"symbol": "AAPL"}])  # NVDA=SEMICONDUCTORS, AAPL=IT
        self.assertTrue(ok)

    def test_sell_always_passes(self):
        ok, reason, details = mod.gate_sector_concentration(
            "AAPL", [{"symbol": "AAPL"}], side="SELL")
        self.assertTrue(ok)
        self.assertTrue(details["exempt"])

    def test_sell_case_insensitive(self):
        ok, reason, details = mod.gate_sector_concentration(
            "AAPL", [{"symbol": "AAPL"}], side="sell")
        self.assertTrue(ok)

    def test_unmapped_symbol(self):
        ok, reason, details = mod.gate_sector_concentration("ZZXY", [])
        self.assertFalse(ok)
        self.assertEqual(reason, mod.ReasonCode.GATE_I_SYMBOL_UNMAPPED)

    def test_custom_sector_map(self):
        custom = {"FOO": "TECH", "BAR": "TECH"}
        ok, reason, details = mod.gate_sector_concentration(
            "FOO", [{"symbol": "BAR"}], sector_map=custom)
        self.assertFalse(ok)
        self.assertEqual(reason, mod.ReasonCode.GATE_I_SECTOR_FULL)

    def test_max_per_sector_lt_1(self):
        ok, reason, details = mod.gate_sector_concentration(
            "AAPL", [], max_per_sector=0)
        self.assertFalse(ok)
        self.assertEqual(reason, mod.ReasonCode.GATE_I_SECTOR_FULL)

    def test_none_positions(self):
        ok, reason, details = mod.gate_sector_concentration("AAPL", None)
        self.assertTrue(ok)

    def test_non_dict_positions_ignored(self):
        ok, reason, details = mod.gate_sector_concentration(
            "AAPL", ["not_a_dict"])
        self.assertTrue(ok)


class TestGateIHIQ007PendingOccupiesSlot(unittest.TestCase):
    """HIQ-007: pending/staged/submitted positions occupy sector slots."""

    def test_two_in_same_sector_blocked(self):
        positions = [{"symbol": "AAPL"}, {"symbol": "MSFT"}]  # both IT
        ok, reason, details = mod.gate_sector_concentration("AAPL", positions)
        self.assertFalse(ok)

    def test_same_symbol_twice_blocked(self):
        positions = [{"symbol": "AAPL"}, {"symbol": "AAPL"}]
        ok, reason, details = mod.gate_sector_concentration("MSFT", positions)
        self.assertFalse(ok)  # sector already at 2
        self.assertGreaterEqual(details["positions_in_sector"], 1)

    def test_max_per_sector_2(self):
        """With cap=2, one existing position should allow a second."""
        ok, reason, details = mod.gate_sector_concentration(
            "MSFT", [{"symbol": "AAPL"}], max_per_sector=2)
        self.assertTrue(ok)
        self.assertEqual(details["positions_in_sector"], 1)


class TestGateIDeterminism(unittest.TestCase):
    def test_deterministic(self):
        import json
        p1 = mod.gate_sector_concentration("AAPL",
            [{"symbol": "JPM"}, {"symbol": "XOM"}])
        p2 = mod.gate_sector_concentration("AAPL",
            [{"symbol": "JPM"}, {"symbol": "XOM"}])
        self.assertEqual((p1[0], p1[1], json.dumps(p1[2])),
                         (p2[0], p2[1], json.dumps(p2[2])))


if __name__ == "__main__":
    unittest.main()
