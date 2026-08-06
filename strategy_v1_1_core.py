"""
strategy_v1_1_core.py — Phase 19B B1 deterministic pure evaluation library.

All functions are pure: they take explicit input snapshots, produce deterministic
structured outputs, and have zero side effects. No network, no broker, no filesystem,
no current-time reads, no model invocation, no strategy activation.

Phase 19B Gate 0.1 — HUMAN DECISIONS INCORPORATED (2026-08-01)
HIQ-001 through HIQ-012 resolved per Chris approval.

Governance:  Level 1 advisory-only
Execution:   NONE — no caller wires this module into guard.py or bridge.py
Authorized:  APPROVAL_GATE_PHASE19B_B1_CORE_IMPLEMENTATION
Tests:       B2 unit + golden-vector suite committed alongside B1 in the same
             commit (257/257 passing) — the "NOT AUTHORIZED (B2 separately
             gated)" line above was stale boilerplate carried over from an
             earlier template and contradicted the tests already present in
             this commit; corrected 2026-08-06. Registered in
             scripts/run-ci-portable so the curated CI gate actually runs them.
Activation:  NOT AUTHORIZED (B4 out of scope)
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

# ═══════════════════════════════════════════════════════════════════════════════
# Immutable constants — spec-advisory defaults (HIQ-008)
# ═══════════════════════════════════════════════════════════════════════════════

# §4.6 — Inverse-volatility scalar
# NOTE (2026-08-06): this module constant is the original HIQ-008
# spec-frozen value, pinned exactly by TestComputeGrossScalar /
# TestGrossScalarExtended's hardcoded 0.16-based assertions in B2 — do not
# change it here, it would break those frozen tests. It is only a
# fallback for callers that omit vol_reference_pct; HIQ-008 already states
# "vol_reference_pct and floor come from advisory config" at runtime. The
# proposal's own recalibration (16 -> 13, from real SPY history — see
# docs/strategy-proposals/PHASE19B_PROPOSED_YAML_CHANGES_v0_1.md) lives in
# the proposed advisory.vol_reference_pct YAML value, which is what would
# actually be supplied once this module is wired in (deferred to B4).
DEFAULT_VOL_REFERENCE_PCT: float = 16.0
DEFAULT_VOL_LOOKBACK_DAYS: int = 20
DEFAULT_GROSS_SCALAR_FLOOR: float = 0.25

# §4.5 — Regime gate
DEFAULT_REGIME_SMA_DAYS: int = 200
DEFAULT_REGIME_MOMENTUM_MONTHS: int = 12
DEFAULT_REGIME_CAUTION_MULTIPLIER: float = 0.5

# §4.3 — Cross-sectional RS
DEFAULT_RS_LOOKBACK_DAYS: int = 60
DEFAULT_RS_MIN_BARS: int = 60
DEFAULT_RS_TOP_FRACTION: float = 0.5

# §4.10 — Data-quality thresholds
DEFAULT_MIN_REFERENCE_BARS: int = 252
DEFAULT_MIN_VALID_SYMBOL_FRACTION: float = 0.5

# §6 — Hard YAML ceilings (unchanged from v1.0.0)
YAML_MAX_TOTAL_EXPOSURE_PCT: float = 30.0

# Trading days per year for annualization
TRADING_DAYS_PER_YEAR: float = 252.0


# ═══════════════════════════════════════════════════════════════════════════════
# HIQ-009 — Spec-frozen v1.1 universe (22 names, 11 sector groups)
# ═══════════════════════════════════════════════════════════════════════════════

FROZEN_UNIVERSE: Dict[str, str] = {
    # Information Technology
    "AAPL": "INFORMATION_TECHNOLOGY",
    "MSFT": "INFORMATION_TECHNOLOGY",
    "AVGO": "INFORMATION_TECHNOLOGY",
    # Semiconductors (distinct from IT per §4.7)
    "NVDA": "SEMICONDUCTORS",
    "AMD": "SEMICONDUCTORS",
    # Communication Services
    "META": "COMMUNICATION_SERVICES",
    "GOOGL": "COMMUNICATION_SERVICES",
    # Health Care
    "LLY": "HEALTH_CARE",
    "UNH": "HEALTH_CARE",
    "JNJ": "HEALTH_CARE",
    # Consumer Staples
    "PG": "CONSUMER_STAPLES",
    "KO": "CONSUMER_STAPLES",
    # Consumer Discretionary
    "AMZN": "CONSUMER_DISCRETIONARY",
    "HD": "CONSUMER_DISCRETIONARY",
    # Financials
    "JPM": "FINANCIALS",
    "BAC": "FINANCIALS",
    # Energy
    "XOM": "ENERGY",
    "CVX": "ENERGY",
    # Industrials
    "CAT": "INDUSTRIALS",
    "UNP": "INDUSTRIALS",
    # Utilities
    "NEE": "UTILITIES",
    "DUK": "UTILITIES",
}

# ═══════════════════════════════════════════════════════════════════════════════
# Stable reason-code inventory
# ═══════════════════════════════════════════════════════════════════════════════


class ReasonCode:
    """Stable reason-code constants for all B1 functions."""

    # Regime (R004)
    REGIME_RISK_ON = "REGIME_RISK_ON"
    REGIME_CAUTION = "REGIME_CAUTION"
    REGIME_RISK_OFF = "REGIME_RISK_OFF"
    REGIME_INSUFFICIENT_DATA = "REGIME_INSUFFICIENT_DATA"

    # Volatility scalar (R005, R011)
    VOL_SCALAR_NOMINAL = "VOL_SCALAR_NOMINAL"
    VOL_SCALAR_CLAMPED = "VOL_SCALAR_CLAMPED"
    VOL_SCALAR_INSUFFICIENT_DATA = "VOL_SCALAR_INSUFFICIENT_DATA"
    VOL_DEGENERATE_SERIES = "VOL_DEGENERATE_SERIES"
    VOL_COMPUTED = "VOL_COMPUTED"

    # Reference data quality (R010)
    SPY_DATA_VALID = "SPY_DATA_VALID"
    SPY_DATA_INSUFFICIENT = "SPY_DATA_INSUFFICIENT"
    SPY_DATA_STALE = "SPY_DATA_STALE"

    # Cross-sectional RS (R003, R012, R028)
    RS_RANK_TOP_HALF = "RS_RANK_TOP_HALF"
    RS_RANK_NOT_TOP_HALF = "RS_RANK_NOT_TOP_HALF"
    RS_RANK_INSUFFICIENT_DATA = "RS_RANK_INSUFFICIENT_DATA"
    RS_UNIVERSE_NO_TRADE = "RS_UNIVERSE_NO_TRADE"
    RS_UNIVERSE_VALID = "RS_UNIVERSE_VALID"

    # Gate I — sector concentration (R007)
    GATE_I_PASS = "GATE_I_PASS"
    GATE_I_SECTOR_FULL = "GATE_I_SECTOR_FULL"
    GATE_I_SYMBOL_UNMAPPED = "GATE_I_SYMBOL_UNMAPPED"

    # Budget (R006, R029)
    BUDGET_COMPUTED = "BUDGET_COMPUTED"
    BUDGET_RISK_OFF = "BUDGET_RISK_OFF"
    BUDGET_CEILING_VIOLATED = "BUDGET_CEILING_VIOLATED"
    BUDGET_AVAILABLE = "BUDGET_AVAILABLE"
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"

    # Hermes output validation (R019)
    HERMES_OUTPUT_VALID = "HERMES_OUTPUT_VALID"
    HERMES_FORBIDDEN_PATTERN = "HERMES_FORBIDDEN_PATTERN"

    # Hermes signal alignment (HIQ-010)
    SIGNAL_ALIGNMENT_VALID = "SIGNAL_ALIGNMENT_VALID"
    SIGNAL_ALIGNMENT_MISSING_FIELD = "SIGNAL_ALIGNMENT_MISSING_FIELD"
    SIGNAL_ALIGNMENT_EXTRA_FIELD = "SIGNAL_ALIGNMENT_EXTRA_FIELD"
    SIGNAL_ALIGNMENT_NON_BOOLEAN = "SIGNAL_ALIGNMENT_NON_BOOLEAN"
    SIGNAL_ALIGNMENT_NON_INTEGER_COUNT = "SIGNAL_ALIGNMENT_NON_INTEGER_COUNT"
    SIGNAL_ALIGNMENT_COUNT_OUT_OF_RANGE = "SIGNAL_ALIGNMENT_COUNT_OUT_OF_RANGE"
    SIGNAL_ALIGNMENT_COUNT_MISMATCH = "SIGNAL_ALIGNMENT_COUNT_MISMATCH"
    SIGNAL_ALIGNMENT_PASSED_MISMATCH = "SIGNAL_ALIGNMENT_PASSED_MISMATCH"

    # Advisory config validation (HIQ-008)
    ADVISORY_CONFIG_VALID = "ADVISORY_CONFIG_VALID"
    ADVISORY_CONFIG_MISSING_KEY = "ADVISORY_CONFIG_MISSING_KEY"
    ADVISORY_CONFIG_WRONG_TYPE = "ADVISORY_CONFIG_WRONG_TYPE"
    ADVISORY_CONFIG_NON_FINITE = "ADVISORY_CONFIG_NON_FINITE"
    ADVISORY_CONFIG_OUT_OF_RANGE = "ADVISORY_CONFIG_OUT_OF_RANGE"
    ADVISORY_CONFIG_MALFORMED = "ADVISORY_CONFIG_MALFORMED"

    # Generic data-quality
    INVALID_BAR = "INVALID_BAR"
    VALID_BAR = "VALID_BAR"
    INPUT_MISSING = "INPUT_MISSING"
    INPUT_NON_FINITE = "INPUT_NON_FINITE"
    INPUT_NON_NUMERIC = "INPUT_NON_NUMERIC"
    INPUT_OUT_OF_RANGE = "INPUT_OUT_OF_RANGE"
    INPUT_STALE = "INPUT_STALE"


# ═══════════════════════════════════════════════════════════════════════════════
# HIQ-002 — Bar validation
# ═══════════════════════════════════════════════════════════════════════════════

BAR_REQUIRED_FIELDS = frozenset({"open", "high", "low", "close", "volume"})


def _is_finite_numeric(x: Any) -> bool:
    """True when x is an int or float, and is finite (not NaN, not Inf)."""
    if isinstance(x, bool):
        return False  # HIQ: reject booleans where numeric values are expected
    if isinstance(x, (int, float)):
        return math.isfinite(x)
    return False


def is_valid_daily_bar(bar: Any) -> Tuple[bool, str]:
    """
    HIQ-002 — Validate a single daily bar.

    A bar is valid only when:
      - open, high, low, close, volume are all present
      - open, high, low, close are numeric, finite, and > 0
      - volume is numeric, finite, and >= 0
      - high >= max(open, close)
      - low <= min(open, close)
      - high >= low

    Returns:
        (True, "VALID_BAR") or (False, reason_code)
    """
    if not isinstance(bar, dict):
        return False, ReasonCode.INVALID_BAR

    for field in BAR_REQUIRED_FIELDS:
        if field not in bar:
            return False, ReasonCode.INVALID_BAR

    o, h, l, c, v = bar["open"], bar["high"], bar["low"], bar["close"], bar["volume"]

    # All OHLC must be numeric, finite, > 0
    for name, val in [("open", o), ("high", h), ("low", l), ("close", c)]:
        if not _is_finite_numeric(val):
            return False, ReasonCode.INPUT_NON_FINITE
        if val <= 0:
            return False, ReasonCode.INPUT_OUT_OF_RANGE

    # Volume must be numeric, finite, >= 0
    if not _is_finite_numeric(v):
        return False, ReasonCode.INPUT_NON_FINITE
    if v < 0:
        return False, ReasonCode.INPUT_OUT_OF_RANGE

    # High/low consistency
    if h < max(o, c):
        return False, ReasonCode.INVALID_BAR
    if l > min(o, c):
        return False, ReasonCode.INVALID_BAR
    if h < l:
        return False, ReasonCode.INVALID_BAR

    return True, ReasonCode.VALID_BAR


# ═══════════════════════════════════════════════════════════════════════════════
# R002 — resolve_sector
# ═══════════════════════════════════════════════════════════════════════════════


def resolve_sector(
    symbol: str,
    sector_map: Optional[Dict[str, str]] = None,
) -> Optional[str]:
    """
    R002 — Look up a symbol's GICS sector group.

    Args:
        symbol: Ticker (normalised to uppercase internally).
        sector_map: Optional explicit mapping. If None, FROZEN_UNIVERSE is used.

    Returns:
        Sector name string, or None for unmapped symbols.
    """
    if not isinstance(symbol, str) or not symbol.strip():
        return None
    if sector_map is None:
        sector_map = FROZEN_UNIVERSE
    return sector_map.get(symbol.upper().strip())


# ═══════════════════════════════════════════════════════════════════════════════
# R010 — validate_spy_reference_data  (HIQ-004: explicit cutoff)
# ═══════════════════════════════════════════════════════════════════════════════


def validate_spy_reference_data(
    bars: Optional[List[Dict[str, Any]]],
    min_bars: int = DEFAULT_MIN_REFERENCE_BARS,
    max_staleness_cutoff: Optional[str] = None,
    newest_bar_date_key: str = "date",
) -> Dict[str, Any]:
    """
    R010 — Validate SPY bar sufficiency and staleness.

    HIQ-004: B1 receives explicit cutoff; does not read current time or calendar.

    Args:
        bars: List of daily bar dicts for SPY.
        min_bars: Minimum valid bar count (default 252).
        max_staleness_cutoff: ISO-8601 date string. If provided and the newest
            bar's date is older than this cutoff, data is stale.
        newest_bar_date_key: Key used for the bar date in each dict.

    Returns:
        {valid, bar_count, stale, newest_bar_date, reason}
    """
    if bars is None:
        return {
            "valid": False, "bar_count": 0, "stale": False,
            "newest_bar_date": None, "reason": ReasonCode.SPY_DATA_INSUFFICIENT,
        }

    valid_bars = []
    newest_date = None
    for bar in bars:
        ok, _ = is_valid_daily_bar(bar)
        if ok:
            valid_bars.append(bar)
            d = bar.get(newest_bar_date_key)
            if isinstance(d, str) and (newest_date is None or d > newest_date):
                newest_date = d

    bar_count = len(valid_bars)

    if bar_count < min_bars:
        return {
            "valid": False, "bar_count": bar_count, "stale": False,
            "newest_bar_date": newest_date, "reason": ReasonCode.SPY_DATA_INSUFFICIENT,
        }

    stale = False
    if max_staleness_cutoff is not None and newest_date is not None:
        if newest_date < max_staleness_cutoff:
            stale = True

    if stale:
        return {
            "valid": False, "bar_count": bar_count, "stale": True,
            "newest_bar_date": newest_date, "reason": ReasonCode.SPY_DATA_STALE,
        }

    return {
        "valid": True, "bar_count": bar_count, "stale": False,
        "newest_bar_date": newest_date, "reason": ReasonCode.SPY_DATA_VALID,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# R005 helper — compute_daily_log_returns
# ═══════════════════════════════════════════════════════════════════════════════


def compute_daily_log_returns(
    bars: Optional[List[Dict[str, Any]]],
    price_key: str = "close",
) -> List[float]:
    """
    Compute ln(close[t] / close[t-1]) series from validated bar list.

    Bars that fail is_valid_daily_bar are skipped, producing a gap in the
    return series (caller must handle shorter-than-expected output).

    Args:
        bars: List of daily bar dicts (pre-validated or not).
        price_key: Key for close price in each bar dict.

    Returns:
        List of log returns. Empty list if any bar fails validation.
    """
    if bars is None:
        return []

    closes: List[float] = []
    for bar in bars:
        ok, _ = is_valid_daily_bar(bar)
        if not ok:
            return []  # fail closed: reject entire series on any invalid bar
        closes.append(float(bar[price_key]))

    if len(closes) < 2:
        return []

    returns: List[float] = []
    for i in range(1, len(closes)):
        if closes[i - 1] <= 0 or closes[i] <= 0:
            continue
        r = math.log(closes[i] / closes[i - 1])
        if math.isfinite(r):
            returns.append(r)

    return returns


# ═══════════════════════════════════════════════════════════════════════════════
# R005 — compute_realized_vol
# ═══════════════════════════════════════════════════════════════════════════════


def compute_realized_vol(
    bars: Optional[List[Dict[str, Any]]],
    lookback_days: int = DEFAULT_VOL_LOOKBACK_DAYS,
) -> Dict[str, Any]:
    """
    R005 — Annualized stdev of daily log returns over a lookback window.

    Args:
        bars: List of daily bar dicts.
        lookback_days: Number of most recent bars to use (default 20).

    Returns:
        {sigma_ref, bar_count, valid, reason}
        sigma_ref is annualized (decimal, e.g. 0.16 = 16%).
    """
    if lookback_days < 2:
        return {"sigma_ref": None, "bar_count": 0, "valid": False,
                "reason": ReasonCode.VOL_SCALAR_INSUFFICIENT_DATA}

    returns = compute_daily_log_returns(bars)
    if len(returns) < lookback_days:
        return {"sigma_ref": None, "bar_count": len(returns), "valid": False,
                "reason": ReasonCode.VOL_SCALAR_INSUFFICIENT_DATA}

    window = returns[-lookback_days:]
    n = len(window)

    mean_r = sum(window) / n
    variance = sum((r - mean_r) ** 2 for r in window) / (n - 1)

    scale = max(1.0, max(abs(value) for value in window))
    variance_floor = (math.ulp(scale) ** 2) * n
    if variance <= variance_floor or not math.isfinite(variance):
        return {"sigma_ref": None, "bar_count": n, "valid": False,
                "reason": ReasonCode.VOL_DEGENERATE_SERIES}

    sigma_ref = math.sqrt(variance) * math.sqrt(TRADING_DAYS_PER_YEAR)

    if not math.isfinite(sigma_ref):
        return {"sigma_ref": None, "bar_count": n, "valid": False,
                "reason": ReasonCode.VOL_DEGENERATE_SERIES}

    return {"sigma_ref": sigma_ref, "bar_count": n, "valid": True,
            "reason": ReasonCode.VOL_COMPUTED}


# ═══════════════════════════════════════════════════════════════════════════════
# R005 / R011 — compute_gross_scalar
# ═══════════════════════════════════════════════════════════════════════════════


def compute_gross_scalar(
    sigma_ref: Optional[float],
    vol_reference_pct: float = DEFAULT_VOL_REFERENCE_PCT,
    floor: float = DEFAULT_GROSS_SCALAR_FLOOR,
) -> Dict[str, Any]:
    """
    R005 / R011 — Inverse-volatility gross exposure scalar.

    gross_scalar = clamp(vol_reference / sigma_ref, floor, 1.0)

    HIQ-008: vol_reference_pct and floor come from advisory config.
    Fail-closed: if sigma_ref is None, NaN, Inf, or non-positive → return floor.

    Args:
        sigma_ref: Annualized realized vol (decimal, e.g. 0.16).
        vol_reference_pct: Reference vol percentage (e.g. 16.0 → 16%).
        floor: Minimum scalar value (0.25).

    Returns:
        {gross_scalar, sigma_ref, clamped, reason}
    """
    vol_ref_decimal = vol_reference_pct / 100.0
    floor_clamped = max(0.0, min(floor, 1.0))

    # Fail-closed on missing/non-finite/invalid sigma_ref
    if sigma_ref is None:
        return {"gross_scalar": floor_clamped, "sigma_ref": None, "clamped": True,
                "reason": ReasonCode.VOL_SCALAR_INSUFFICIENT_DATA}
    if not _is_finite_numeric(sigma_ref):
        return {"gross_scalar": floor_clamped, "sigma_ref": sigma_ref, "clamped": True,
                "reason": ReasonCode.VOL_SCALAR_INSUFFICIENT_DATA}
    if sigma_ref <= 0:
        return {"gross_scalar": 1.0, "sigma_ref": sigma_ref, "clamped": True,
                "reason": ReasonCode.VOL_DEGENERATE_SERIES}

    raw_scalar = vol_ref_decimal / sigma_ref
    clamped = raw_scalar < floor_clamped or raw_scalar > 1.0
    gross_scalar = max(floor_clamped, min(raw_scalar, 1.0))

    reason = ReasonCode.VOL_SCALAR_CLAMPED if clamped else ReasonCode.VOL_SCALAR_NOMINAL

    return {"gross_scalar": gross_scalar, "sigma_ref": sigma_ref,
            "clamped": clamped, "reason": reason}


# ═══════════════════════════════════════════════════════════════════════════════
# R004 — compute_sma
# ═══════════════════════════════════════════════════════════════════════════════


def compute_sma(
    bars: Optional[List[Dict[str, Any]]],
    lookback: int = DEFAULT_REGIME_SMA_DAYS,
    price_key: str = "close",
) -> Optional[float]:
    """
    R004 — Simple moving average of close prices.

    Args:
        bars: List of daily bar dicts.
        lookback: Number of bars for the SMA window (default 200).
        price_key: Key for close price.

    Returns:
        SMA value, or None if insufficient valid bars.
    """
    if bars is None or lookback < 1:
        return None

    closes: List[float] = []
    for bar in bars:
        ok, _ = is_valid_daily_bar(bar)
        if ok:
            closes.append(float(bar[price_key]))

    if len(closes) < lookback:
        return None

    window = closes[-lookback:]
    if not all(_is_finite_numeric(c) and c > 0 for c in window):
        return None

    return sum(window) / len(window)


# ═══════════════════════════════════════════════════════════════════════════════
# R004 — compute_trailing_return  (HIQ-003: price return, no dividends)
# ═══════════════════════════════════════════════════════════════════════════════


def compute_trailing_return(
    bars: Optional[List[Dict[str, Any]]],
    months: int = DEFAULT_REGIME_MOMENTUM_MONTHS,
    price_key: str = "close",
) -> Optional[float]:
    """
    R004 — Trailing N-month price return.

    HIQ-003: Uses price return only (close[-1] / close[-lookback] - 1).
    Does not model dividends or distributions.
    Internally described as "price return", not "total return".

    Args:
        bars: List of daily bar dicts.
        months: Lookback in months (12 → ~252 trading days).
        price_key: Key for close price.

    Returns:
        Decimal return (e.g. 0.10 = +10%), or None if insufficient data.
    """
    if bars is None or months < 1:
        return None

    approx_bars = months * 21  # ~21 trading days per month
    closes: List[float] = []
    for bar in bars:
        ok, _ = is_valid_daily_bar(bar)
        if ok:
            closes.append(float(bar[price_key]))

    if len(closes) < max(approx_bars, 2):
        return None

    # Use the bar at index -approx_bars from the end
    idx = max(0, len(closes) - approx_bars)
    if idx >= len(closes) - 1:
        return None

    old_close = closes[idx]
    new_close = closes[-1]

    if old_close <= 0 or new_close <= 0:
        return None
    if not _is_finite_numeric(old_close) or not _is_finite_numeric(new_close):
        return None

    return (new_close / old_close) - 1.0


# ═══════════════════════════════════════════════════════════════════════════════
# R004 — compute_regime_state
# ═══════════════════════════════════════════════════════════════════════════════


def compute_regime_state(
    bars: Optional[List[Dict[str, Any]]],
    sma_days: int = DEFAULT_REGIME_SMA_DAYS,
    momentum_months: int = DEFAULT_REGIME_MOMENTUM_MONTHS,
) -> Dict[str, Any]:
    """
    R004 — Portfolio regime state from SPY reference data.

    Conditions:
      A: SPY close > 200-day SMA
      B: SPY 12-month price return > 0

    Truth table:
      A ∧ B  → RISK_ON
      A ⊕ B  → CAUTION
      ¬A ∧ ¬B → RISK_OFF
      Either condition uncomputable → RISK_OFF (fail safe)

    Args:
        bars: SPY daily bars.
        sma_days: SMA lookback (200).
        momentum_months: Momentum lookback in months (12).

    Returns:
        {regime, sma_value, momentum_return, sma_above, momentum_positive, valid, reason}
    """
    sma = compute_sma(bars, sma_days)
    mom = compute_trailing_return(bars, momentum_months)

    if sma is None or mom is None:
        last_close = None
        if bars:
            for bar in reversed(bars):
                ok, _ = is_valid_daily_bar(bar)
                if ok:
                    last_close = float(bar["close"])
                    break
        return {
            "regime": "RISK_OFF", "sma_value": sma, "momentum_return": mom,
            "sma_above": False, "momentum_positive": False,
            "valid": False, "reason": ReasonCode.REGIME_INSUFFICIENT_DATA,
            "last_close": last_close,
        }

    # Get latest close for SMA comparison
    last_close: Optional[float] = None
    for bar in reversed(bars):
        ok, _ = is_valid_daily_bar(bar)
        if ok:
            last_close = float(bar["close"])
            break

    if last_close is None or not _is_finite_numeric(last_close):
        return {
            "regime": "RISK_OFF", "sma_value": sma, "momentum_return": mom,
            "sma_above": False, "momentum_positive": False,
            "valid": False, "reason": ReasonCode.REGIME_INSUFFICIENT_DATA,
            "last_close": None,
        }

    sma_above = last_close > sma
    momentum_positive = mom > 0

    if sma_above and momentum_positive:
        regime = "RISK_ON"
    elif sma_above or momentum_positive:
        regime = "CAUTION"
    else:
        regime = "RISK_OFF"

    reason = {
        "RISK_ON": ReasonCode.REGIME_RISK_ON,
        "CAUTION": ReasonCode.REGIME_CAUTION,
        "RISK_OFF": ReasonCode.REGIME_RISK_OFF,
    }[regime]

    return {
        "regime": regime, "sma_value": sma, "momentum_return": mom,
        "sma_above": sma_above, "momentum_positive": momentum_positive,
        "valid": True, "reason": reason, "last_close": last_close,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# R012 — validate_rs_universe
# ═══════════════════════════════════════════════════════════════════════════════


def validate_rs_universe(
    eligible_count: int,
    total_allowlist: int = 22,
    min_fraction: float = DEFAULT_MIN_VALID_SYMBOL_FRACTION,
) -> Dict[str, Any]:
    """
    R012 — Check whether enough symbols have valid data for a meaningful RS rank.

    If eligible_count / total_allowlist < min_fraction → NO_TRADE.

    Args:
        eligible_count: Number of symbols with ≥min_bars valid data.
        total_allowlist: Total symbols in the allowlist (default 22).
        min_fraction: Minimum fraction required (default 0.5).

    Returns:
        {no_trade, subset_ratio, total, eligible, reason}
    """
    if total_allowlist <= 0:
        return {"no_trade": True, "subset_ratio": 0.0, "total": total_allowlist,
                "eligible": eligible_count, "reason": ReasonCode.RS_UNIVERSE_NO_TRADE}

    ratio = eligible_count / total_allowlist if total_allowlist > 0 else 0.0

    if ratio < min_fraction:
        return {"no_trade": True, "subset_ratio": ratio, "total": total_allowlist,
                "eligible": eligible_count, "reason": ReasonCode.RS_UNIVERSE_NO_TRADE}

    return {"no_trade": False, "subset_ratio": ratio, "total": total_allowlist,
            "eligible": eligible_count, "reason": ReasonCode.RS_UNIVERSE_VALID}


# ═══════════════════════════════════════════════════════════════════════════════
# R003 / R028 — compute_cross_sectional_rs
# ═══════════════════════════════════════════════════════════════════════════════


def compute_cross_sectional_rs(
    bars_by_symbol: Optional[Dict[str, List[Dict[str, Any]]]],
    lookback_days: int = DEFAULT_RS_LOOKBACK_DAYS,
    min_bars: int = DEFAULT_RS_MIN_BARS,
    top_fraction: float = DEFAULT_RS_TOP_FRACTION,
    total_allowlist: int = 22,
) -> Dict[str, Any]:
    """
    R003 / R028 — Cross-sectional relative-strength ranking.

    For each symbol with ≥min_bars valid daily closes, compute
    60-day price return. Sort descending. Top floor(n_eligible × top_fraction)
    are "top half".

    HIQ-002: Valid bar is determined by is_valid_daily_bar.
    HIQ-009: Ties broken by symbol uppercase lexicographic ascending.

    Args:
        bars_by_symbol: {symbol: [bar_dicts]}.
        lookback_days: Return lookback (60).
        min_bars: Minimum valid bars required for eligibility (60).
        top_fraction: Fraction in top half (0.5).
        total_allowlist: Total symbols in allowlist for universe ratio.

    Returns:
        {ranks, subset_size, top_half_symbols, top_half_count, no_trade, no_trade_reason}
    """
    if bars_by_symbol is None or not isinstance(bars_by_symbol, dict):
        return {
            "ranks": [], "subset_size": 0, "top_half_symbols": [],
            "top_half_count": 0, "no_trade": True,
            "no_trade_reason": ReasonCode.RS_RANK_INSUFFICIENT_DATA,
        }

    # Build eligible symbol → return
    symbol_returns: Dict[str, float] = {}
    for sym, bars in bars_by_symbol.items():
        if not isinstance(bars, list):
            continue
        valid_closes: List[float] = []
        for bar in bars:
            ok, _ = is_valid_daily_bar(bar)
            if ok:
                valid_closes.append(float(bar["close"]))
        if len(valid_closes) < min_bars:
            continue
        # Compute return: close[-1] / close[-lookback] - 1
        idx = max(0, len(valid_closes) - lookback_days)
        if idx >= len(valid_closes) - 1:
            continue
        old = valid_closes[idx]
        new = valid_closes[-1]
        if old <= 0 or new <= 0:
            continue
        ret = (new / old) - 1.0
        if not math.isfinite(ret):
            continue
        symbol_returns[sym.upper().strip()] = ret

    subset_size = len(symbol_returns)

    # Universe validation
    universe = validate_rs_universe(subset_size, total_allowlist,
                                    DEFAULT_MIN_VALID_SYMBOL_FRACTION)
    if universe["no_trade"]:
        return {
            "ranks": [], "subset_size": subset_size,
            "top_half_symbols": [], "top_half_count": 0,
            "no_trade": True, "no_trade_reason": ReasonCode.RS_UNIVERSE_NO_TRADE,
        }

    # Sort by return descending, then symbol ascending (HIQ-009 tie-breaker)
    sorted_symbols = sorted(symbol_returns.items(),
                            key=lambda x: (-x[1], x[0]))

    top_n = max(1, int(math.floor(subset_size * top_fraction)))

    ranks = []
    top_half = []
    for rank_i, (sym, ret) in enumerate(sorted_symbols, start=1):
        in_top = rank_i <= top_n
        ranks.append({
            "symbol": sym, "rs_return": round(ret, 6),
            "rank": rank_i, "percentile": round((rank_i - 1) / subset_size, 4) if subset_size > 1 else 0.0,
            "eligible": True, "top_half": in_top,
            "reason": ReasonCode.RS_RANK_TOP_HALF if in_top else ReasonCode.RS_RANK_NOT_TOP_HALF,
        })
        if in_top:
            top_half.append(sym)

    return {
        "ranks": ranks, "subset_size": subset_size,
        "top_half_symbols": top_half, "top_half_count": len(top_half),
        "no_trade": False, "no_trade_reason": None,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# R006 — compute_effective_budget
# ═══════════════════════════════════════════════════════════════════════════════


def compute_effective_budget(
    max_total_exposure_pct: float = YAML_MAX_TOTAL_EXPOSURE_PCT,
    gross_scalar: float = 1.0,
    regime: str = "RISK_ON",
    caution_multiplier: float = DEFAULT_REGIME_CAUTION_MULTIPLIER,
) -> Dict[str, Any]:
    """
    R006 — Advisory effective exposure budget.

    effective = max_total_exposure × gross_scalar × regime_multiplier

    RISK_ON  → multiplier = 1.0
    CAUTION  → multiplier = caution_multiplier (0.5)
    RISK_OFF → effective = 0 (no new BUY)

    MUST assert effective ≤ max_total_exposure. RAISE on violation.

    Args:
        max_total_exposure_pct: YAML ceiling (30.0).
        gross_scalar: From compute_gross_scalar [0.25, 1.0].
        regime: "RISK_ON" | "CAUTION" | "RISK_OFF".
        caution_multiplier: Multiplier for CAUTION state (0.5).

    Returns:
        {effective_budget_pct, regime_multiplier, gross_scalar, assertion_passed, reason}
    """
    REGIME_MULTIPLIERS = {"RISK_ON": 1.0, "CAUTION": caution_multiplier, "RISK_OFF": 0.0}

    if regime not in REGIME_MULTIPLIERS:
        return {
            "effective_budget_pct": 0.0, "regime_multiplier": 0.0,
            "gross_scalar": gross_scalar, "assertion_passed": False,
            "reason": ReasonCode.BUDGET_RISK_OFF,
        }

    regime_mult = REGIME_MULTIPLIERS[regime]

    if regime == "RISK_OFF":
        return {
            "effective_budget_pct": 0.0, "regime_multiplier": 0.0,
            "gross_scalar": gross_scalar, "assertion_passed": True,
            "reason": ReasonCode.BUDGET_RISK_OFF,
        }

    effective = max_total_exposure_pct * gross_scalar * regime_mult

    assertion_passed = effective <= max_total_exposure_pct

    if not assertion_passed:
        # HIQ: structurally impossible by construction but must assert
        return {
            "effective_budget_pct": 0.0, "regime_multiplier": regime_mult,
            "gross_scalar": gross_scalar, "assertion_passed": False,
            "reason": ReasonCode.BUDGET_CEILING_VIOLATED,
        }

    return {
        "effective_budget_pct": round(effective, 6),
        "regime_multiplier": regime_mult,
        "gross_scalar": gross_scalar,
        "assertion_passed": True,
        "reason": ReasonCode.BUDGET_COMPUTED,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# R029 — compute_remaining_budget  (HIQ-011: explicit NetLiquidation)
# ═══════════════════════════════════════════════════════════════════════════════


def compute_remaining_budget(
    effective_budget_pct: float,
    net_liquidation_eur: float,
    exchange_rate: float,
    existing_exposure_usd: float = 0.0,
) -> Dict[str, Any]:
    """
    R029 — Remaining budget after accounting for existing positions.

    HIQ-011: net_liquidation_eur is explicit input. Fail closed on missing,
    non-numeric, non-finite, zero, or negative.

    Args:
        effective_budget_pct: From compute_effective_budget.
        net_liquidation_eur: Account NetLiquidation in EUR.
        exchange_rate: EUR/USD conversion rate.
        existing_exposure_usd: Current portfolio USD exposure.

    Returns:
        {effective_budget_usd, remaining_budget_usd, existing_exposure_pct,
         budget_exhausted, reason}
    """
    # HIQ-011: fail closed on invalid NetLiquidation
    if not _is_finite_numeric(net_liquidation_eur) or net_liquidation_eur <= 0:
        return {
            "effective_budget_usd": 0.0, "remaining_budget_usd": 0.0,
            "existing_exposure_pct": 0.0, "budget_exhausted": True,
            "reason": ReasonCode.INPUT_NON_FINITE,
        }
    if not _is_finite_numeric(exchange_rate) or exchange_rate <= 0:
        return {
            "effective_budget_usd": 0.0, "remaining_budget_usd": 0.0,
            "existing_exposure_pct": 0.0, "budget_exhausted": True,
            "reason": ReasonCode.INPUT_NON_FINITE,
        }

    net_liq_usd = net_liquidation_eur * exchange_rate
    effective_budget_usd = (effective_budget_pct / 100.0) * net_liq_usd
    existing_exposure = max(0.0, existing_exposure_usd)
    existing_exposure_pct = (existing_exposure / net_liq_usd * 100.0) if net_liq_usd > 0 else 0.0

    remaining = effective_budget_usd - existing_exposure
    budget_exhausted = remaining <= 0

    reason = ReasonCode.BUDGET_EXHAUSTED if budget_exhausted else ReasonCode.BUDGET_AVAILABLE

    return {
        "effective_budget_usd": round(effective_budget_usd, 2),
        "remaining_budget_usd": round(max(0.0, remaining), 2),
        "existing_exposure_pct": round(existing_exposure_pct, 4),
        "budget_exhausted": budget_exhausted,
        "reason": reason,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# R003 / R017 — is_candidate_rs_eligible
# ═══════════════════════════════════════════════════════════════════════════════


def is_candidate_rs_eligible(
    symbol: str,
    rs_result: Optional[Dict[str, Any]],
) -> bool:
    """
    R003 / R017 — Check if candidate symbol is in the RS top half.

    Args:
        symbol: Ticker symbol.
        rs_result: Output of compute_cross_sectional_rs.

    Returns:
        True if symbol is in top_half_symbols and no_trade is False.
    """
    if rs_result is None:
        return False
    if rs_result.get("no_trade", True):
        return False
    sym = symbol.upper().strip()
    return sym in rs_result.get("top_half_symbols", [])


# ═══════════════════════════════════════════════════════════════════════════════
# R007 — gate_sector_concentration (HIQ-006: runs first; HIQ-007: pending=occupied)
# ═══════════════════════════════════════════════════════════════════════════════


def gate_sector_concentration(
    symbol: str,
    positions: Optional[List[Dict[str, Any]]],
    sector_map: Optional[Dict[str, str]] = None,
    max_per_sector: int = 1,
    side: str = "BUY",
) -> Tuple[bool, str, Dict[str, Any]]:
    """
    R007 — Gate I: reject BUY if candidate's sector is already at capacity.

    HIQ-006: Evaluated first in the failure-precedence order.
    HIQ-007: Position occupies its sector slot until confirmed fully filled.
             Pending/staged/submitted/acknowledged/partially-filled positions
             still occupy the slot. B1 consumes explicit position snapshots.
    HIQ-008: max_per_sector from advisory config or spec (1).

    Args:
        symbol: Candidate ticker.
        positions: List of open position dicts, each with at least 'symbol'.
                   Only filled/held positions should be in this list.
                   Pending-SELL positions still count (HIQ-007).
        sector_map: Symbol → sector mapping. None uses FROZEN_UNIVERSE.
        max_per_sector: Maximum positions per sector group (1).
        side: "BUY" (gate applies) or "SELL" (exempt).

    Returns:
        (passed, reason, details)
    """
    if side.upper() == "SELL":
        return True, ReasonCode.GATE_I_PASS, {
            "symbol": symbol.upper().strip(), "sector": None,
            "positions_in_sector": 0, "cap": max_per_sector,
            "side": "SELL", "exempt": True,
        }

    sym = symbol.upper().strip()
    smap = sector_map if sector_map is not None else FROZEN_UNIVERSE
    sector = smap.get(sym)

    if sector is None:
        return False, ReasonCode.GATE_I_SYMBOL_UNMAPPED, {
            "symbol": sym, "sector": None, "positions_in_sector": 0,
            "cap": max_per_sector, "exempt": False,
        }

    if max_per_sector < 1:
        return False, ReasonCode.GATE_I_SECTOR_FULL, {
            "symbol": sym, "sector": sector, "positions_in_sector": 0,
            "cap": max_per_sector, "exempt": False,
        }

    # Count open positions in this sector (HIQ-007: pending counts as occupied)
    count = 0
    if positions:
        for pos in positions:
            if not isinstance(pos, dict):
                continue
            pos_sym = pos.get("symbol", "")
            pos_sector = smap.get(pos_sym.upper().strip())
            if pos_sector == sector:
                count += 1

    if count >= max_per_sector:
        return False, ReasonCode.GATE_I_SECTOR_FULL, {
            "symbol": sym, "sector": sector, "positions_in_sector": count,
            "cap": max_per_sector, "exempt": False,
        }

    return True, ReasonCode.GATE_I_PASS, {
        "symbol": sym, "sector": sector, "positions_in_sector": count,
        "cap": max_per_sector, "exempt": False,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# R019 — validate_hermes_output  (HIQ-010: strict signal_alignment)
# ═══════════════════════════════════════════════════════════════════════════════

# Forbidden patterns in Hermes output (size, leverage, confidence)
_DEFAULT_FORBIDDEN_PATTERNS: Tuple[str, ...] = (
    r"buy \d+ shares",
    r"sell \d+ shares",
    r"\d+ shares",
    r"position size",
    r"leverage",
    r"leveraged",
    r"margin",
    r"confidence multiplier",
    r"confidence score",
    r"\d+% of portfolio",
    r"\d+ percent of portfolio",
    r"weight:",
    r"allocation:",
)

# HIQ-010 — Canonical signal field names
_CANONICAL_SIGNAL_FIELDS = frozenset({"trend", "volume", "structure", "relative_strength"})


def validate_signal_alignment(
    signal_alignment: Any,
) -> Tuple[bool, str, Dict[str, Any]]:
    """
    HIQ-010 — Strict Hermes signal_alignment validation.

    Requires:
      {passed: bool, signals: {trend, volume, structure, relative_strength: bool},
       aligned_count: int}

    Validates:
      - All fields present, no extra signal fields
      - All signal values are strict booleans
      - aligned_count is an integer in 0..4
      - aligned_count == count of true signal fields
      - passed == (aligned_count >= 2)

    Does not invoke Hermes. Pure validation of already-obtained output.

    Returns:
        (valid, reason, details)
    """
    if not isinstance(signal_alignment, dict):
        return False, ReasonCode.SIGNAL_ALIGNMENT_MISSING_FIELD, {}

    # Check top-level fields
    if "passed" not in signal_alignment:
        return False, ReasonCode.SIGNAL_ALIGNMENT_MISSING_FIELD, {"missing": "passed"}
    if "signals" not in signal_alignment:
        return False, ReasonCode.SIGNAL_ALIGNMENT_MISSING_FIELD, {"missing": "signals"}
    if "aligned_count" not in signal_alignment:
        return False, ReasonCode.SIGNAL_ALIGNMENT_MISSING_FIELD, {"missing": "aligned_count"}

    passed = signal_alignment["passed"]
    signals = signal_alignment["signals"]
    aligned_count = signal_alignment["aligned_count"]

    # passed must be strict bool
    if not isinstance(passed, bool):
        return False, ReasonCode.SIGNAL_ALIGNMENT_NON_BOOLEAN, {"field": "passed", "value": passed}

    # signals must be a dict
    if not isinstance(signals, dict):
        return False, ReasonCode.SIGNAL_ALIGNMENT_MISSING_FIELD, {"missing": "signals (not a dict)"}

    # Exactly canonical fields, no extra
    actual_fields = set(signals.keys())
    if actual_fields != _CANONICAL_SIGNAL_FIELDS:
        missing = _CANONICAL_SIGNAL_FIELDS - actual_fields
        extra = actual_fields - _CANONICAL_SIGNAL_FIELDS
        details: Dict[str, Any] = {}
        if missing:
            details["missing_fields"] = sorted(missing)
        if extra:
            details["extra_fields"] = sorted(extra)
            return False, ReasonCode.SIGNAL_ALIGNMENT_EXTRA_FIELD, details
        if missing:
            return False, ReasonCode.SIGNAL_ALIGNMENT_MISSING_FIELD, details

    # Each signal value must be strict bool
    non_bools = []
    for fname in sorted(_CANONICAL_SIGNAL_FIELDS):
        if not isinstance(signals[fname], bool):
            non_bools.append(fname)
    if non_bools:
        return False, ReasonCode.SIGNAL_ALIGNMENT_NON_BOOLEAN, {"non_boolean_fields": non_bools}

    # aligned_count must be a strict int in 0..4
    if isinstance(aligned_count, bool):
        return False, ReasonCode.SIGNAL_ALIGNMENT_NON_INTEGER_COUNT, {"aligned_count": aligned_count}
    if not isinstance(aligned_count, int):
        return False, ReasonCode.SIGNAL_ALIGNMENT_NON_INTEGER_COUNT, {"aligned_count": aligned_count}
    if aligned_count < 0 or aligned_count > 4:
        return False, ReasonCode.SIGNAL_ALIGNMENT_COUNT_OUT_OF_RANGE, {"aligned_count": aligned_count}

    # aligned_count must equal number of true signal fields
    true_count = sum(1 for f in _CANONICAL_SIGNAL_FIELDS if signals[f] is True)
    if aligned_count != true_count:
        return False, ReasonCode.SIGNAL_ALIGNMENT_COUNT_MISMATCH, {
            "aligned_count": aligned_count, "true_count": true_count,
        }

    # passed must equal (aligned_count >= 2)
    expected_passed = aligned_count >= 2
    if passed is not expected_passed:
        return False, ReasonCode.SIGNAL_ALIGNMENT_PASSED_MISMATCH, {
            "passed": passed, "aligned_count": aligned_count, "expected": expected_passed,
        }

    return True, ReasonCode.SIGNAL_ALIGNMENT_VALID, {
        "passed": passed, "aligned_count": aligned_count,
    }


def validate_hermes_output(
    response_text: Optional[str],
    forbidden_patterns: Optional[Tuple[str, ...]] = None,
) -> Dict[str, Any]:
    """
    R019 — Validate Hermes output for forbidden size/leverage/confidence language.

    HIQ-010: This function does NOT invoke Hermes. It validates already-obtained
    output text for forbidden patterns. signal_alignment validation is separate
    (see validate_signal_alignment).

    Args:
        response_text: The Hermes response text to validate.
        forbidden_patterns: Patterns to search for. None uses defaults.

    Returns:
        {valid, violations, reason}
    """
    if response_text is None:
        return {"valid": False, "violations": [], "reason": ReasonCode.INPUT_MISSING}

    if forbidden_patterns is None:
        forbidden_patterns = _DEFAULT_FORBIDDEN_PATTERNS

    import re
    violations = []
    text_lower = response_text.lower()
    for pattern in forbidden_patterns:
        if re.search(pattern, text_lower):
            violations.append(pattern)

    if violations:
        return {"valid": False, "violations": violations,
                "reason": ReasonCode.HERMES_FORBIDDEN_PATTERN}

    return {"valid": True, "violations": [],
            "reason": ReasonCode.HERMES_OUTPUT_VALID}


# ═══════════════════════════════════════════════════════════════════════════════
# R016 — classify_position  (HIQ-005: explicit activation marker only)
# ═══════════════════════════════════════════════════════════════════════════════


def classify_position(
    symbol: str,
    sector_map: Optional[Dict[str, str]] = None,
    allowlist: Optional[List[str]] = None,
    is_pre_activation: bool = True,
) -> Dict[str, Any]:
    """
    R016 — Classify a position for grandfathering purposes.

    HIQ-005: Grandfathering depends only on explicit is_pre_activation marker.
    B1 does not implement activation commands, persistence, or environment checks.

    Args:
        symbol: Ticker.
        sector_map: Symbol → sector mapping.
        allowlist: Current allowlist of allowed symbols.
        is_pre_activation: True if v1.1 has NOT been activated yet.

    Returns:
        {grandfathered, sector, closeable, in_allowlist,
         counts_toward_exposure, counts_toward_sector_cap}
    """
    sym = symbol.upper().strip() if isinstance(symbol, str) else ""
    smap = sector_map if sector_map is not None else FROZEN_UNIVERSE
    alist = allowlist if allowlist is not None else list(FROZEN_UNIVERSE.keys())

    sector = smap.get(sym)
    in_allowlist = sym in alist

    # Grandfathered: existed before activation, regardless of allowlist membership
    grandfathered = is_pre_activation

    # Always closeable (SELL is close-only; Gate A applies to entries only)
    closeable = True

    return {
        "symbol": sym,
        "grandfathered": grandfathered,
        "sector": sector,
        "closeable": closeable,
        "in_allowlist": in_allowlist,
        "counts_toward_exposure": True,
        "counts_toward_sector_cap": True,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# HIQ-008 — Advisory config validation
# ═══════════════════════════════════════════════════════════════════════════════

ADVISORY_CONFIG_SCHEMA: Dict[str, Dict[str, Any]] = {
    "vol_reference_pct":        {"type": (int, float), "min": 1.0,  "max": 100.0, "default": DEFAULT_VOL_REFERENCE_PCT},
    "vol_lookback_days":         {"type": int,          "min": 2,    "max": 252,   "default": DEFAULT_VOL_LOOKBACK_DAYS},
    "gross_scalar_floor":        {"type": (int, float), "min": 0.0,  "max": 1.0,   "default": DEFAULT_GROSS_SCALAR_FLOOR},
    "regime_sma_days":           {"type": int,          "min": 10,   "max": 500,   "default": DEFAULT_REGIME_SMA_DAYS},
    "regime_momentum_months":    {"type": int,          "min": 1,    "max": 60,    "default": DEFAULT_REGIME_MOMENTUM_MONTHS},
    "regime_caution_multiplier": {"type": (int, float), "min": 0.0,  "max": 1.0,   "default": DEFAULT_REGIME_CAUTION_MULTIPLIER},
    "cross_sectional_rs_lookback_days": {"type": int,   "min": 10,   "max": 504,   "default": DEFAULT_RS_LOOKBACK_DAYS},
    "cross_sectional_rs_top_fraction":  {"type": (int, float), "min": 0.1, "max": 1.0, "default": DEFAULT_RS_TOP_FRACTION},
    "min_reference_bars":        {"type": int,          "min": 20,   "max": 5040,  "default": DEFAULT_MIN_REFERENCE_BARS},
    "min_symbol_bars_for_rs":    {"type": int,          "min": 10,   "max": 504,   "default": DEFAULT_RS_MIN_BARS},
    "min_valid_symbol_fraction": {"type": (int, float), "min": 0.1,  "max": 1.0,   "default": DEFAULT_MIN_VALID_SYMBOL_FRACTION},
    # reference_symbol and reference_bar_duration are string fields — validated separately
}


def validate_advisory_config(
    advisory_config: Optional[Dict[str, Any]],
) -> Tuple[bool, str, Dict[str, Any]]:
    """
    HIQ-008 — Validate the advisory configuration block.

    Rules:
      - If advisory_config is None or empty → VALID; defaults used at call sites.
      - If present, every key in ADVISORY_CONFIG_SCHEMA must be present and valid.
      - Fail closed on partial, malformed, contradictory, non-finite, or
        out-of-range values. Do not silently repair individual keys.

    Args:
        advisory_config: The 'advisory' dict from paper-trading-rules.yaml.

    Returns:
        (valid, reason, {validated_values, errors})
    """
    if advisory_config is None or (isinstance(advisory_config, dict) and len(advisory_config) == 0):
        return True, ReasonCode.ADVISORY_CONFIG_VALID, {"validated_values": {}, "used_defaults": True}

    if not isinstance(advisory_config, dict):
        return False, ReasonCode.ADVISORY_CONFIG_MALFORMED, {"errors": ["advisory block is not a dict"]}

    validated: Dict[str, Any] = {}
    errors: List[Dict[str, Any]] = []

    for key, schema in ADVISORY_CONFIG_SCHEMA.items():
        if key not in advisory_config:
            errors.append({"key": key, "error": ReasonCode.ADVISORY_CONFIG_MISSING_KEY})
            continue

        val = advisory_config[key]
        expected_type = schema["type"]

        # HIQ: reject booleans where numeric values are expected
        if isinstance(val, bool) and expected_type in ((int, float), int):
            errors.append({"key": key, "value": val,
                           "error": ReasonCode.ADVISORY_CONFIG_WRONG_TYPE,
                           "detail": "boolean where numeric expected"})
            continue

        if not isinstance(val, expected_type):
            errors.append({"key": key, "value": val,
                           "error": ReasonCode.ADVISORY_CONFIG_WRONG_TYPE,
                           "expected": str(expected_type), "got": type(val).__name__})
            continue

        if isinstance(val, float) and not math.isfinite(val):
            errors.append({"key": key, "value": val,
                           "error": ReasonCode.ADVISORY_CONFIG_NON_FINITE})
            continue

        lo, hi = schema["min"], schema["max"]
        if val < lo or val > hi:
            errors.append({"key": key, "value": val,
                           "error": ReasonCode.ADVISORY_CONFIG_OUT_OF_RANGE,
                           "range": [lo, hi]})
            continue

        validated[key] = val

    if errors:
        return False, ReasonCode.ADVISORY_CONFIG_MALFORMED, {"errors": errors}

    return True, ReasonCode.ADVISORY_CONFIG_VALID, {"validated_values": validated, "used_defaults": False}


# ═══════════════════════════════════════════════════════════════════════════════
# Module metadata — import-safe, no work at import time beyond constants
# ═══════════════════════════════════════════════════════════════════════════════

__all__ = [
    # Constants
    "FROZEN_UNIVERSE",
    "ReasonCode",
    "TRADING_DAYS_PER_YEAR",
    # Bar validation
    "is_valid_daily_bar",
    # Core functions
    "resolve_sector",
    "validate_spy_reference_data",
    "compute_daily_log_returns",
    "compute_realized_vol",
    "compute_gross_scalar",
    "compute_sma",
    "compute_trailing_return",
    "compute_regime_state",
    "validate_rs_universe",
    "compute_cross_sectional_rs",
    "compute_effective_budget",
    "compute_remaining_budget",
    "is_candidate_rs_eligible",
    "gate_sector_concentration",
    "validate_hermes_output",
    "validate_signal_alignment",
    "classify_position",
    "validate_advisory_config",
]

# No main routine. No work at import time beyond immutable constant definitions.
