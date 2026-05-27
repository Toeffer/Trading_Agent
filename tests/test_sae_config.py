"""
SAE config invariants — these MUST match CLAUDE.md §6. If anyone edits one
without the other, this fails.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

CONFIG = Path(__file__).resolve().parent.parent / "config" / "sae-config.yaml"


@pytest.fixture(scope="module")
def cfg() -> dict:
    with CONFIG.open() as f:
        return yaml.safe_load(f)


# ─── Exposure budget (§6 hard invariants) ─────────────────────────────────────
def test_max_total_open_risk_is_6pct(cfg: dict) -> None:
    assert cfg["exposure_budget"]["max_total_open_risk_pct"] == 6.0


def test_max_single_position_is_2pct(cfg: dict) -> None:
    assert cfg["exposure_budget"]["max_single_position_pct"] == 2.0


def test_max_daily_loss_is_4pct(cfg: dict) -> None:
    """Kill switch — halt trading if hit."""
    assert cfg["exposure_budget"]["max_daily_loss_pct"] == 4.0


def test_max_weekly_loss_is_8pct(cfg: dict) -> None:
    assert cfg["exposure_budget"]["max_weekly_loss_pct"] == 8.0


def test_max_speculative_short_is_5pct(cfg: dict) -> None:
    """Per §5.4 + §15: Strategy D capped at 5% total portfolio. Non-negotiable."""
    assert cfg["exposure_budget"]["max_speculative_short_pct"] == 5.0


def test_max_funding_harvest_is_20pct(cfg: dict) -> None:
    assert cfg["exposure_budget"]["max_funding_harvest_pct"] == 20.0


# ─── Order controls ───────────────────────────────────────────────────────────
def test_max_leverage_is_2x(cfg: dict) -> None:
    """Per §15: 'Use leverage above 2x under any circumstance' is forbidden."""
    assert cfg["order_controls"]["max_leverage"] == 2


def test_short_max_hold_is_48h(cfg: dict) -> None:
    """Per §15: 'Hold a speculative short position longer than 48 hours' is forbidden."""
    assert cfg["order_controls"]["max_short_hold_hours"] == 48


def test_min_cooldown_15min(cfg: dict) -> None:
    assert cfg["order_controls"]["min_cooldown_between_same_asset_s"] == 900


def test_slippage_max_half_pct(cfg: dict) -> None:
    assert cfg["order_controls"]["slippage_max_pct"] == 0.5


# ─── Short safety ─────────────────────────────────────────────────────────────
def test_short_requires_operator_confirm(cfg: dict) -> None:
    """Per §5.4: 'every short requires operator confirmation' permanently."""
    assert cfg["short_safety"]["require_operator_confirm"] is True


def test_short_blocked_if_funding_positive(cfg: dict) -> None:
    assert cfg["short_safety"]["block_short_if_funding_positive"] is True


def test_squeeze_oi_threshold_is_3pct(cfg: dict) -> None:
    assert cfg["short_safety"]["squeeze_oi_threshold_pct"] == 3.0


# ─── Venues & withdraw block ──────────────────────────────────────────────────
def test_venue_allowlist_is_exhaustive(cfg: dict) -> None:
    """Per §4: only binance + kucoin (+ testnet) allowed. Per §15: no other exchanges."""
    assert set(cfg["venue_allowlist"]) == {"binance", "kucoin", "binance_testnet"}


def test_withdraw_block_is_true(cfg: dict) -> None:
    """The single most important rule. Per §11 rule 2: PERMANENTLY DISABLED."""
    assert cfg["withdraw_block"] is True


# ─── Asset filters (§15) ──────────────────────────────────────────────────────
def test_min_token_age_90_days(cfg: dict) -> None:
    assert cfg["asset_filters"]["min_age_days"] >= 90


def test_min_volume_1M_usd(cfg: dict) -> None:
    assert cfg["asset_filters"]["min_24h_volume_usd"] >= 1_000_000


def test_meme_coins_blocked(cfg: dict) -> None:
    assert cfg["asset_filters"]["block_meme_coins"] is True


# ─── Consistency cross-checks ─────────────────────────────────────────────────
def test_single_position_does_not_exceed_total(cfg: dict) -> None:
    """A single position can't be allowed to exceed total open risk."""
    assert (
        cfg["exposure_budget"]["max_single_position_pct"]
        <= cfg["exposure_budget"]["max_total_open_risk_pct"]
    )


def test_weekly_loss_at_least_double_daily(cfg: dict) -> None:
    """A weekly cap tighter than 2x the daily cap is nonsense — you'd hit it in 2 bad days."""
    assert (
        cfg["exposure_budget"]["max_weekly_loss_pct"]
        >= 2 * cfg["exposure_budget"]["max_daily_loss_pct"]
    )
