# ═══════════════════════════════════════════════════════════════════════════════
# strategy_v1_1_advisory.py — Phase 19B B3 Advisory Orchestration Layer
# ═══════════════════════════════════════════════════════════════════════════════
#
# Pure advisory orchestration around strategy_v1_1_core.py.
# Stateless, explicit-input, deterministic composition of B1 pure functions.
#
# DESIGN PRINCIPLE:
#   Takes all data as explicit inputs. Returns structured advisory results.
#   Never reads from IBKR, bridge runtime, .env, risk-rules YAML, guard state,
#   OpenClaw, system services, system time, live positions, or model providers.
#
# DECISION PRECEDENCE:
#   sector eligibility → regime → relative strength → Hermes signal alignment
#   First failing condition determines the primary ReasonCode.
#
# SCOPE:
#   BUY-only advisory. SELL/close-only is external guard.py behavior.
#   'advisory_only': True and 'execution_authorized': False in every result.
#
# HERMES BEHAVIOR:
#   Validation-only. B3 never invokes Hermes, OpenClaw, OpenRouter, or any model.
#   The caller supplies a pre-computed Hermes signal dict; B3 validates it.
#
# PHASE 19B B3 IMPLEMENTATION REMEDIATION — ATR amendment applied.
#   ATR amendment V2:
#     /tmp/phase19b-strategy-v1-1/phase19b-b3-design-and-test-plan-atr-amendment-v2.json
#     SHA-256: ce33e2a02df39af5fa7bf42de270609fa114549b02a2133be14e30cbadea2d06
#   Design-and-test-plan remediation (original):
#     /tmp/phase19b-strategy-v1-1/phase19b-b3-design-and-test-plan-remediation.json
#     SHA-256: 5c935cba0eb86a8d021571b0ec97fa4d1ef02b7e57ffd555854f37627eec6a04
# ═══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import copy
import json
import math
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

# ═══════════════════════════════════════════════════════════════════════════════
# Accepted B1 imports — ONLY from strategy_v1_1_core
# ═══════════════════════════════════════════════════════════════════════════════

from strategy_v1_1_core import (  # type: ignore[import-untyped]
    # ReasonCode enum
    ReasonCode,
    # Bar validation (HIQ-002)
    is_valid_daily_bar,
    # Sector (R002)
    resolve_sector,
    # Reference data (R010, HIQ-004)
    validate_spy_reference_data,
    # Volatility (R005)
    compute_daily_log_returns,
    compute_realized_vol,
    compute_gross_scalar,
    # Trend / momentum (R004)
    compute_sma,
    compute_trailing_return,
    compute_regime_state,
    # Cross-sectional RS (R003, R012, R028)
    validate_rs_universe,
    compute_cross_sectional_rs,
    # Budget (R006, R029)
    compute_effective_budget,
    # Sector gate (R007)
    gate_sector_concentration,
    # Hermes signal validation (HIQ-010)
    validate_signal_alignment,
    # Advisory config validation (HIQ-008)
    validate_advisory_config,
    # Immutable constants
    FROZEN_UNIVERSE,
    BAR_REQUIRED_FIELDS,
)

# ═══════════════════════════════════════════════════════════════════════════════
# AdvisoryDecision — permitted outcomes
# ═══════════════════════════════════════════════════════════════════════════════


class AdvisoryDecision(Enum):
    """Stable advisory decision enum.  Exactly three outcomes."""
    ADVISORY_CANDIDATE = "ADVISORY_CANDIDATE"
    NO_TRADE = "NO_TRADE"
    INVALID_INPUT = "INVALID_INPUT"


# ═══════════════════════════════════════════════════════════════════════════════
# AdvisoryRequest — 14-field frozen input contract
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class AdvisoryRequest:
    """
    Explicit input contract for generate_advisory().

    All 15 fields are caller-supplied.  No hidden reads from system time,
    globals, environment, live configuration, runtime state, IBKR, or
    OpenClaw.  For required/optional status, defaults, and validation
    see the remediation artifact (§remediation_1_public_input_contract).

    Field 15 (candidate_atr14) is an ATR(14) eligibility prerequisite
    supplied by the caller.  B3 validates it but does not compute it.
    It is not used for sizing, stop, budget, or RS calculations.
    """

    candidate_symbol: str
    action: str
    symbols_bars: Dict[str, List[Dict[str, Any]]]
    spy_bars: List[Dict[str, Any]]
    canonical_universe: frozenset
    hermes_signal: Dict[str, Any]
    advisory_config: Dict[str, Any]
    positions_state: Dict[str, Any]
    as_of_utc: str
    max_total_exposure: float
    freshness_threshold: int = 1
    sector_authority: Optional[Dict[str, str]] = None
    thesis: Optional[str] = None
    invalidation_condition: Optional[str] = None
    candidate_atr14: Optional[float] = None


# ═══════════════════════════════════════════════════════════════════════════════
# AdvisoryResult — 12-field frozen output contract
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class AdvisoryResult:
    """
    Structured advisory output.

    Every result carries advisory_only=True and execution_authorized=False.
    Prohibited fields (shares, quantity, weight, notional, leverage,
    confidence_multiplier, order_type, limit_price, stop_price,
    executable_order_payload, approval_token, h1_token) are absent.
    Failure results never contain a successful proposal.
    """

    decision: AdvisoryDecision
    reason_code: str
    advisory_only: bool = True
    execution_authorized: bool = False
    candidate_symbol: Optional[str] = None
    regime_state: Optional[str] = None
    gross_scalar: Optional[float] = None
    effective_budget: Optional[float] = None
    rs_rank_detail: Optional[Dict[str, Any]] = None
    decision_trace: List[str] = field(default_factory=list)
    thesis: Optional[str] = None
    invalidation_condition: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Deterministic, stable JSON-serializable dict representation."""
        return {
            "decision": self.decision.value,
            "reason_code": self.reason_code,
            "advisory_only": True,       # literal — always true
            "execution_authorized": False,  # literal — always false
            "candidate_symbol": self.candidate_symbol,
            "regime_state": self.regime_state,
            "gross_scalar": self.gross_scalar,
            "effective_budget": self.effective_budget,
            "rs_rank_detail": self.rs_rank_detail,
            "decision_trace": list(self.decision_trace),
            "thesis": self.thesis,
            "invalidation_condition": self.invalidation_condition,
        }


# ═══════════════════════════════════════════════════════════════════════════════
# Private helpers — normalization, copying, serialization
# ═══════════════════════════════════════════════════════════════════════════════


def _is_finite_float(x: Any) -> bool:
    """True when x is a float (not int, not bool) and is finite."""
    if not isinstance(x, float):
        return False
    if isinstance(x, bool):
        return False
    import math
    return math.isfinite(x)


def _deepcopy_bars(bars: Any) -> Any:
    """Immutable-safe deep copy of bar data for defensive isolation."""
    return copy.deepcopy(bars)


def _normalize_positions_state(raw: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalize positions_state to guaranteed structure.

    Returns dict with keys open_positions, pending_sells, exited_slots,
    grandfathered — each defaulting to empty list if missing.
    """
    return {
        "open_positions": list(raw.get("open_positions", [])),
        "pending_sells": list(raw.get("pending_sells", [])),
        "exited_slots": list(raw.get("exited_slots", [])),
        "grandfathered": list(raw.get("grandfathered", [])),
    }


def _build_invalid_input(
    reason_code: str,
    trace: Optional[List[str]] = None,
) -> AdvisoryResult:
    """Construct a standard INVALID_INPUT result."""
    return AdvisoryResult(
        decision=AdvisoryDecision.INVALID_INPUT,
        reason_code=reason_code,
        decision_trace=trace or [],
    )


def _build_no_trade(
    reason_code: str,
    trace: Optional[List[str]] = None,
    regime_state: Optional[str] = None,
    gross_scalar: Optional[float] = None,
    effective_budget: Optional[float] = None,
    rs_rank_detail: Optional[Dict[str, Any]] = None,
    thesis: Optional[str] = None,
    invalidation_condition: Optional[str] = None,
) -> AdvisoryResult:
    """Construct a standard NO_TRADE result with optional evidence."""
    return AdvisoryResult(
        decision=AdvisoryDecision.NO_TRADE,
        reason_code=reason_code,
        regime_state=regime_state,
        gross_scalar=gross_scalar,
        effective_budget=effective_budget,
        rs_rank_detail=rs_rank_detail,
        decision_trace=trace or [],
        thesis=thesis,
        invalidation_condition=invalidation_condition,
    )


def _build_candidate(
    candidate_symbol: str,
    reason_code: str,
    trace: List[str],
    regime_state: str,
    gross_scalar: float,
    effective_budget: float,
    rs_rank_detail: Dict[str, Any],
    thesis: Optional[str] = None,
    invalidation_condition: Optional[str] = None,
) -> AdvisoryResult:
    """Construct a standard ADVISORY_CANDIDATE result."""
    return AdvisoryResult(
        decision=AdvisoryDecision.ADVISORY_CANDIDATE,
        reason_code=reason_code,
        candidate_symbol=candidate_symbol,
        regime_state=regime_state,
        gross_scalar=gross_scalar,
        effective_budget=effective_budget,
        rs_rank_detail=rs_rank_detail,
        decision_trace=trace,
        thesis=thesis,
        invalidation_condition=invalidation_condition,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# validate_advisory_input — input validation gate
# ═══════════════════════════════════════════════════════════════════════════════


def validate_advisory_input(request: AdvisoryRequest) -> Optional[str]:
    """
    Validate all explicit inputs before strategy evaluation.

    Returns None if all inputs are valid, or a ReasonCode string
    describing the first validation failure.

    Checks performed:
      1. candidate_symbol: str, uppercase, in canonical_universe
      2. action: 'BUY' only
      3. symbols_bars: dict, all bars valid
      4. spy_bars: list of valid bars
      5. canonical_universe: frozenset, exactly 22 symbols
      6. hermes_signal: dict
      7. advisory_config: dict, passes validate_advisory_config
      8. positions_state: dict with valid structure
      9. as_of_utc: non-empty str
      10. max_total_exposure: finite float > 0 <= 1.0
      11. freshness_threshold: int >= 1
    """
    # (1) candidate_symbol
    if not isinstance(request.candidate_symbol, str):
        return ReasonCode.INPUT_MISSING
    symbol = request.candidate_symbol.strip()
    if not symbol or symbol != symbol.upper():
        return ReasonCode.INPUT_MISSING
    if symbol not in request.canonical_universe:
        return ReasonCode.INPUT_OUT_OF_RANGE

    # (2) action — BUY only
    if not isinstance(request.action, str):
        return ReasonCode.INPUT_MISSING
    if request.action != "BUY":
        return ReasonCode.INPUT_OUT_OF_RANGE

    # (3) symbols_bars
    if not isinstance(request.symbols_bars, dict):
        return ReasonCode.INPUT_MISSING
    if not request.symbols_bars:
        return ReasonCode.INPUT_MISSING
    # Validate every bar in every symbol's series
    for sym, bars in request.symbols_bars.items():
        if not isinstance(bars, list):
            return ReasonCode.INVALID_BAR
        for bar in bars:
            valid, reason = is_valid_daily_bar(bar)
            if not valid:
                return reason

    # (4) spy_bars
    if not isinstance(request.spy_bars, list):
        return ReasonCode.INPUT_MISSING
    if not request.spy_bars:
        return ReasonCode.INPUT_MISSING
    for bar in request.spy_bars:
        valid, reason = is_valid_daily_bar(bar)
        if not valid:
            return reason

    # (5) canonical_universe
    if not isinstance(request.canonical_universe, frozenset):
        return ReasonCode.INPUT_MISSING
    if len(request.canonical_universe) != 22:
        return ReasonCode.INPUT_OUT_OF_RANGE

    # (6) hermes_signal
    if not isinstance(request.hermes_signal, dict):
        return ReasonCode.INPUT_MISSING

    # (7) advisory_config
    if not isinstance(request.advisory_config, dict):
        return ReasonCode.ADVISORY_CONFIG_MISSING_KEY
    cfg_valid, cfg_reason, _ = validate_advisory_config(request.advisory_config)
    if not cfg_valid:
        return cfg_reason

    # (8) positions_state
    if not isinstance(request.positions_state, dict):
        return ReasonCode.INPUT_MISSING

    # (9) as_of_utc
    if not isinstance(request.as_of_utc, str) or not request.as_of_utc.strip():
        return ReasonCode.INPUT_MISSING

    # (10) max_total_exposure
    if not _is_finite_float(request.max_total_exposure):
        if isinstance(request.max_total_exposure, bool):
            return ReasonCode.INPUT_NON_NUMERIC
        return ReasonCode.INPUT_NON_FINITE
    if not (0.0 < request.max_total_exposure <= 1.0):
        return ReasonCode.INPUT_OUT_OF_RANGE

    # (11) freshness_threshold
    if not isinstance(request.freshness_threshold, int) or isinstance(request.freshness_threshold, bool):
        return ReasonCode.INPUT_NON_NUMERIC
    if request.freshness_threshold < 1:
        return ReasonCode.INPUT_OUT_OF_RANGE

    return None  # All inputs valid


# ═══════════════════════════════════════════════════════════════════════════════
# generate_advisory — primary entry point
# ═══════════════════════════════════════════════════════════════════════════════


def generate_advisory(request: AdvisoryRequest) -> AdvisoryResult:
    """
    Determine whether the supplied candidate qualifies as an advisory BUY.

    Decision precedence (first failing condition → primary ReasonCode):

      1.  Input validation            → INVALID_INPUT
      2.  Sector eligibility          → NO_TRADE (GATE_I_*)
      3.  Regime                      → NO_TRADE (REGIME_RISK_OFF) / CAUTION
      4.  Relative strength           → NO_TRADE (RS_RANK_* / RS_UNIVERSE_*)
      5.  Hermes signal alignment     → NO_TRADE (SIGNAL_ALIGNMENT_*)

    Returns AdvisoryResult with advisory_only=True and
    execution_authorized=False in every outcome.

    Args:
        request: AdvisoryRequest with all 14 fields explicitly supplied.

    Returns:
        AdvisoryResult — never None, never raises.
    """
    trace: List[str] = []

    # ── Step 0: Input validation ──────────────────────────────────────────
    trace.append("STEP_0: validate_advisory_input")
    validation_error = validate_advisory_input(request)
    if validation_error is not None:
        return _build_invalid_input(
            reason_code=validation_error,
            trace=trace,
        )
    trace.append("STEP_0: PASS")

    # ── Step 0a: ATR prerequisite validation ────────────────────────────
    # Every BUY candidate must have a valid ATR(14) supplied by the caller.
    # B3 does NOT calculate ATR, import guard.py, or verify Wilder arithmetic.
    # candidate_atr14 is eligibility evidence only — not used for sizing,
    # stop, budget, or RS calculations.
    atr = request.candidate_atr14

    # ATR-1: MISSING — None or omitted
    if atr is None:
        trace.append("STEP_0_ATR_MISSING")
        return _build_invalid_input(
            reason_code=ReasonCode.INPUT_MISSING,
            trace=trace,
        )

    # ATR-2: TYPE INVALID — bool rejected before int/float (bool is int subtype)
    if isinstance(atr, bool):
        trace.append("STEP_0_ATR_TYPE_INVALID")
        return _build_invalid_input(
            reason_code=ReasonCode.INPUT_NON_NUMERIC,
            trace=trace,
        )
    if not isinstance(atr, (int, float)):
        trace.append("STEP_0_ATR_TYPE_INVALID")
        return _build_invalid_input(
            reason_code=ReasonCode.INPUT_NON_NUMERIC,
            trace=trace,
        )

    # ATR-3: NON-FINITE — NaN, +inf, -inf
    if not math.isfinite(atr):
        trace.append("STEP_0_ATR_NON_FINITE")
        return _build_invalid_input(
            reason_code=ReasonCode.INPUT_NON_FINITE,
            trace=trace,
        )

    # ATR-4: NON-POSITIVE — finite zero or negative
    if atr <= 0:
        trace.append("STEP_0_ATR_NON_POSITIVE")
        return _build_invalid_input(
            reason_code=ReasonCode.INPUT_OUT_OF_RANGE,
            trace=trace,
        )

    # ATR-5: VALID — finite positive, continue to sector
    trace.append("STEP_0_ATR_VALID")

    # Extract frequently-used values
    symbol = request.candidate_symbol
    spy_bars = _deepcopy_bars(request.spy_bars)
    symbols_bars = _deepcopy_bars(request.symbols_bars)
    positions = _normalize_positions_state(request.positions_state)
    config = dict(request.advisory_config)  # shallow copy for safety
    sector_map = (
        dict(request.sector_authority)
        if request.sector_authority is not None
        else dict(FROZEN_UNIVERSE)
    )

    # ── Step 1: Sector eligibility ────────────────────────────────────────
    trace.append("STEP_1: gate_sector_concentration")
    sector = resolve_sector(symbol, sector_map)
    if sector is None:
        return _build_no_trade(
            reason_code=ReasonCode.GATE_I_SYMBOL_UNMAPPED,
            trace=trace,
            thesis=request.thesis,
            invalidation_condition=request.invalidation_condition,
        )
    trace.append(f"STEP_1: sector={sector}")

    sector_ok, sector_reason, _ = gate_sector_concentration(
        symbol=symbol,
        positions=positions["open_positions"] + positions["pending_sells"],
        sector_map=sector_map,
    )
    if not sector_ok:
        return _build_no_trade(
            reason_code=sector_reason,
            trace=trace,
            thesis=request.thesis,
            invalidation_condition=request.invalidation_condition,
        )
    trace.append("STEP_1: PASS")

    # ── Step 2: Regime ────────────────────────────────────────────────────
    trace.append("STEP_2: compute_regime_state")

    # Validate SPY reference data
    _as_of_dt = datetime.fromisoformat(request.as_of_utc.replace("Z", "+00:00"))
    _cutoff_date = (_as_of_dt - timedelta(days=request.freshness_threshold)).date()
    spy_validation = validate_spy_reference_data(
        bars=spy_bars,
        min_bars=config.get("min_reference_bars", 252),
        max_staleness_cutoff=_cutoff_date.isoformat(),
    )

    # If SPY data insufficient or stale → RISK_OFF → NO_TRADE
    regime_result = compute_regime_state(
        bars=spy_bars,
        sma_days=config.get("regime_sma_days", 200),
        momentum_months=config.get("regime_momentum_months", 12),
    )

    regime_state: Optional[str] = None
    if not regime_result.get("valid", False):
        regime_state = "RISK_OFF"
    else:
        regime_state = regime_result.get("regime", "RISK_OFF")

    trace.append(f"STEP_2: regime={regime_state}")

    # RISK_OFF → NO_TRADE for BUY
    if regime_state == "RISK_OFF":
        return _build_no_trade(
            reason_code=regime_result.get("reason", ReasonCode.REGIME_RISK_OFF),
            trace=trace,
            regime_state=regime_state,
            thesis=request.thesis,
            invalidation_condition=request.invalidation_condition,
        )
    trace.append("STEP_2: PASS (not RISK_OFF)")

    # ── Step 2a: Volatility scalar (within regime step) ────────────────────
    trace.append("STEP_2a: compute_gross_scalar")
    vol_result = compute_realized_vol(
        bars=spy_bars,
        lookback_days=config.get("vol_lookback_days", 20),
    )
    gross_scalar_result = compute_gross_scalar(
        sigma_ref=vol_result.get("sigma_ref"),
        vol_reference_pct=config.get("vol_reference_pct", 16),
        floor=config.get("gross_scalar_floor", 0.25),
    )
    gross_scalar: float = gross_scalar_result.get("gross_scalar", 1.0)
    vol_reason: str = gross_scalar_result.get("reason", ReasonCode.VOL_SCALAR_NOMINAL)
    trace.append(f"STEP_2a: gross_scalar={gross_scalar:.4f}, reason={vol_reason}")

    # ── Step 3: Relative strength ─────────────────────────────────────────
    trace.append("STEP_3: compute_cross_sectional_rs")

    # Validate RS universe
    min_bars = config.get("min_symbol_bars_for_rs", 60)
    eligible = sum(
        1 for sym_bars in symbols_bars.values()
        if isinstance(sym_bars, list)
        and sum(1 for b in sym_bars if isinstance(b, dict) and is_valid_daily_bar(b)[0]) >= min_bars
    )
    rs_universe = validate_rs_universe(
        eligible,
        len(request.canonical_universe),
        min_fraction=config.get("min_valid_symbol_fraction", 0.5),
    )

    if rs_universe.get("no_trade", False):
        return _build_no_trade(
            reason_code=rs_universe.get("reason", ReasonCode.RS_UNIVERSE_NO_TRADE),
            trace=trace,
            regime_state=regime_state,
            gross_scalar=gross_scalar,
            thesis=request.thesis,
            invalidation_condition=request.invalidation_condition,
        )
    trace.append(f"STEP_3: rs_universe_valid, eligible={rs_universe.get('eligible_count')}")

    # Compute RS rank for the candidate
    rs_result = compute_cross_sectional_rs(
        bars_by_symbol=symbols_bars,
        lookback_days=config.get("cross_sectional_rs_lookback_days", 60),
        min_bars=config.get("min_symbol_bars_for_rs", 60),
        top_fraction=config.get("cross_sectional_rs_top_fraction", 0.5),
        total_allowlist=len(request.canonical_universe),
    )

    if rs_result.get("no_trade", False):
        return _build_no_trade(
            reason_code=rs_result.get("no_trade_reason", ReasonCode.RS_RANK_INSUFFICIENT_DATA),
            trace=trace,
            regime_state=regime_state,
            gross_scalar=gross_scalar,
            thesis=request.thesis,
            invalidation_condition=request.invalidation_condition,
        )

    # Extract candidate from ranks list
    candidate_rank = next(
        (r for r in rs_result.get("ranks", []) if r.get("symbol") == symbol),
        None,
    )
    in_top_half = candidate_rank is not None and candidate_rank.get("top_half", False)
    rs_rank_detail: Dict[str, Any] = {
        "rank": candidate_rank["rank"] if candidate_rank else None,
        "total_eligible": rs_result.get("subset_size"),
        "in_top_half": in_top_half,
        "eligible_count": rs_result.get("subset_size"),
    }
    trace.append(f"STEP_3: rank={rs_rank_detail['rank']}/{rs_rank_detail['total_eligible']}, top_half={in_top_half}")

    if not in_top_half:
        return _build_no_trade(
            reason_code=rs_result.get("reason", ReasonCode.RS_RANK_NOT_TOP_HALF),
            trace=trace,
            regime_state=regime_state,
            gross_scalar=gross_scalar,
            rs_rank_detail=rs_rank_detail,
            thesis=request.thesis,
            invalidation_condition=request.invalidation_condition,
        )
    trace.append("STEP_3: PASS (top half)")

    # ── Step 4: Hermes signal alignment ───────────────────────────────────
    trace.append("STEP_4: validate_signal_alignment")

    signal_ok, signal_reason, _ = validate_signal_alignment(request.hermes_signal)
    if not signal_ok:
        return _build_no_trade(
            reason_code=signal_reason,
            trace=trace,
            regime_state=regime_state,
            gross_scalar=gross_scalar,
            rs_rank_detail=rs_rank_detail,
            thesis=request.thesis,
            invalidation_condition=request.invalidation_condition,
        )
    trace.append("STEP_4: PASS (hermes signal valid)")

    # ── Compute effective budget ──────────────────────────────────────────
    trace.append("STEP_5: compute_effective_budget")
    budget_result = compute_effective_budget(
        max_total_exposure_pct=request.max_total_exposure * 100.0,
        gross_scalar=gross_scalar,
        regime=regime_state,
        caution_multiplier=config.get("regime_caution_multiplier", 0.5),
    )
    effective_budget: float = budget_result.get("effective_budget_pct", 0.0) / 100.0
    budget_reason: str = budget_result.get("reason", ReasonCode.BUDGET_COMPUTED)
    trace.append(f"STEP_5: effective_budget={effective_budget:.6f}, reason={budget_reason}")

    # ── All gates passed → ADVISORY_CANDIDATE ─────────────────────────────
    trace.append("RESULT: ADVISORY_CANDIDATE")
    return _build_candidate(
        candidate_symbol=symbol,
        reason_code=ReasonCode.RS_RANK_TOP_HALF,  # primary ReasonCode
        trace=trace,
        regime_state=regime_state,
        gross_scalar=gross_scalar,
        effective_budget=effective_budget,
        rs_rank_detail=rs_rank_detail,
        thesis=request.thesis,
        invalidation_condition=request.invalidation_condition,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Deterministic serialization helper
# ═══════════════════════════════════════════════════════════════════════════════


def _result_to_json(result: AdvisoryResult) -> str:
    """Serialize AdvisoryResult to stable deterministic JSON string."""
    return json.dumps(
        result.to_dict(),
        sort_keys=True,
        indent=None,
        separators=(",", ":"),
        ensure_ascii=False,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Explicit public API
# ═══════════════════════════════════════════════════════════════════════════════

__all__ = [
    "AdvisoryDecision",
    "AdvisoryRequest",
    "AdvisoryResult",
    "generate_advisory",
    "validate_advisory_input",
]
