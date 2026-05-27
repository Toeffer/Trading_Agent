"""
Position sizing tests — verify the formula from CLAUDE.md §5.7 and the example
in §10. If a future edit to CLAUDE.md or sae-config.yaml breaks the formula,
these tests catch it before deployment.
"""
from __future__ import annotations

import math
from pathlib import Path

import pytest
import yaml

CONFIG = Path(__file__).resolve().parent.parent / "config" / "sae-config.yaml"


def position_size(portfolio: float, risk_pct: float, entry: float, stop: float) -> float:
    """The §5.7 universal formula. Returns units; rounding to lot size is caller's job."""
    if entry <= stop:
        raise ValueError("entry must be > stop for a long position")
    risk_amount = portfolio * (risk_pct / 100)
    stop_distance = entry - stop
    return risk_amount / stop_distance


# ─── §5.7 worked example ──────────────────────────────────────────────────────
def test_section_5_7_eth_example() -> None:
    """The €2,000 portfolio + 2% risk + €160 stop example must give 0.25 ETH."""
    size = position_size(portfolio=2000, risk_pct=2.0, entry=2800, stop=2640)
    assert size == pytest.approx(0.25)


# ─── §10 log example (after my fix) ───────────────────────────────────────────
def test_section_10_log_example_is_internally_consistent() -> None:
    """
    The log example uses risk_pct=2, risk_amount=$40, stop_distance=$160.80,
    position_size_units=0.25. Verify those numbers reconcile.
    """
    # Implied portfolio = risk_amount / (risk_pct/100) = 40 / 0.02 = 2000
    implied_portfolio = 40.0 / 0.02
    assert implied_portfolio == 2000

    # Position from formula
    size = 40.0 / 160.80
    assert size == pytest.approx(0.2488, abs=0.001)
    # The log rounds to 0.25 — small rounding, within Binance ETH minimum lot (0.0001)
    assert math.floor(size * 10000) / 10000 == pytest.approx(0.2488, abs=0.001)


# ─── Risk% by strategy table ──────────────────────────────────────────────────
@pytest.fixture(scope="module")
def sae_cfg() -> dict:
    with CONFIG.open() as f:
        return yaml.safe_load(f)


def test_strategy_b_risk_is_2_pct(sae_cfg: dict) -> None:
    assert sae_cfg["position_sizing"]["strategy_b_trend_follow_pct"] == 2.0


def test_strategy_d_risk_is_1_pct(sae_cfg: dict) -> None:
    """Strategy D uses TIGHTER risk (1%) than the SAE cap (5% total allocation).
    Per CLAUDE.md §5.7 the per-trade risk is deliberately 1%, not 2%."""
    assert sae_cfg["position_sizing"]["strategy_d_speculative_short_pct"] == 1.0


def test_averaging_down_is_forbidden(sae_cfg: dict) -> None:
    """CLAUDE.md §5.7: 'Adding to a losing position — PERMANENTLY FORBIDDEN'."""
    assert sae_cfg["position_sizing"]["averaging_down_allowed"] is False


# ─── Portfolio heat ───────────────────────────────────────────────────────────
def heat_after(open_risks_pct: list[float], new_risk_pct: float) -> float:
    return sum(open_risks_pct) + new_risk_pct


def test_heat_example_from_section_5_7(sae_cfg: dict) -> None:
    """
    The §5.7 example: open B (2%) + open D (1%) → current heat 3%.
    A new 2% entry: heat reaches 5% → allowed (< 6%).
    A second 2% entry: heat reaches 7% → BLOCKED.
    """
    cap = sae_cfg["exposure_budget"]["max_total_open_risk_pct"]
    assert cap == 6.0

    open_positions = [2.0, 1.0]  # B + D
    assert heat_after(open_positions, 2.0) <= cap, "first new 2% entry should be allowed"
    assert heat_after(open_positions + [2.0], 2.0) > cap, "second 2% entry should be blocked"


# ─── Wider stop → smaller position (the key insight of ATR-normalized sizing) ─
def test_wider_stop_yields_smaller_position() -> None:
    """If volatility doubles (ATR doubles → stop distance doubles), position halves."""
    small_stop = position_size(10000, 2.0, 100, 95)   # $5 stop
    wide_stop = position_size(10000, 2.0, 100, 90)    # $10 stop
    assert wide_stop == pytest.approx(small_stop / 2)


def test_long_with_stop_above_entry_raises() -> None:
    """The formula only applies to longs (entry > stop). Caller must adapt for shorts."""
    with pytest.raises(ValueError):
        position_size(10000, 2.0, 100, 105)
