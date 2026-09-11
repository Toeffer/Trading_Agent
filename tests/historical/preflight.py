from __future__ import annotations
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from pathlib import Path
from trading_agent.legacy_guard import _get_existing_position, _reject_us_domiciled_etf, _require_allowed_symbol, _rollover_guard_state, _validate_preflight_request, append_guard_event, calc_stop, compute_final_max_shares, create_approval_record, expire_all_pending, fetch_account, fetch_bars, fetch_quote, gate_allowlist, gate_close_only, gate_exposure, gate_loss_halts, gate_notional, gate_open_orders, gate_proposal_discipline, gate_risk, gate_sector_concentration, gate_trades_per_day, h1_authorized_scope, load_guard_state, load_rules

"""Historical validation harness; never used by production entry points."""

def run_preflight(
    request: dict,
    account_provider=None,
    quote_provider=None,
    bars_provider=None,
    position_provider=None,
    open_order_provider=None,
    proposal_path: str | Path | None = None,
) -> dict:
    """Run full preflight validation for a proposed order.

    Orchestrates: request validation, rules load, state load,
    account fetch, quote fetch, bars fetch, stop calc,
    gates A-H, share sizing, event logging.

    For SELL (close-only): gates A, D, E, G, H run. Gates B, C, F skipped
    (notional/risk/exposure not applicable to closing positions).

    Args:
        request: Dict with allowed fields only.
        account_provider: Optional callable() -> dict for account data.
        quote_provider: Optional callable(symbol) -> dict for quote data.
        bars_provider: Optional callable(symbol) -> list for bar data.
        position_provider: Optional callable() -> list of position dicts.
            Required for SELL preflight to verify existing position.
        proposal_path: Optional path to a persisted proposal JSON file.
            Gate H validates this file exists and is well-formed.
            When None, Gate H fails closed (proposal required).

    Returns:
        Validation result dict. Never returns executable order payloads.
    """
    try:
        norm = _validate_preflight_request(request)
    except ValueError as e:
        return {"passed": False, "error": str(e)}

    symbol = norm["symbol"]
    proposed_shares = norm["totalQuantity"]
    action = norm["action"]
    is_close = (action == "SELL")

    # Clean up expired pending approvals before processing
    expire_all_pending()

    # Early-reject unknown symbols before any data retrieval
    try:
        _require_allowed_symbol(symbol)
    except ValueError as e:
        append_guard_event("preflight_fail", {
            "symbol": symbol, "passed": False,
            "reason": str(e), "gate": "allowlist",
        })
        return {"passed": False, "error": str(e), "gate": "allowlist"}

    # H4.1: Structural US-domiciled ETF rejection (BUY only — SELL closes are fine)
    if not is_close:
        try:
            _reject_us_domiciled_etf(symbol)
        except ValueError as e:
            append_guard_event("preflight_fail", {
                "symbol": symbol, "passed": False,
                "reason": str(e), "gate": "us_etf_block",
            })
            return {"passed": False, "error": str(e), "gate": "us_etf_block"}

    # Load data — use injected providers if given, else default (HTTP self-call)
    try:
        rules = load_rules()
        state = load_guard_state()

        # Calendar day/week rollover: if trade_date or week_start_date is
        # stale, reset counters before running any gates.
        #
        # Bug fix (2026-08-17): this call writes to guard-state.json (a
        # Phase H1.2 protected path) via save_guard_state_atomic() whenever
        # either rollover actually fires. Preflight itself never carries H1
        # authorization -- H1 is scoped to /order/approve and /order/submit
        # only (invariant #17) -- so an unguarded call here raised
        # PermissionError, uncaught by the except clause below, producing an
        # unhandled 500 instead of the validation-only response preflight is
        # documented to always return. Confirmed live: this hard-blocked
        # preflight entirely once trade_date and week_start_date were both
        # stale (both trigger the same write path). The rollover itself is
        # deterministic, wall-clock-driven housekeeping with no adversarial
        # degrees of freedom -- not an order mutation -- so it gets its own
        # narrow h1_authorized_scope(), exactly the pattern that context
        # manager exists for. This does not widen H1 authorization for
        # anything else in this request; the scope ends immediately after.
        with h1_authorized_scope():
            _rollover_guard_state(state)

        account = account_provider() if account_provider else fetch_account()
        quote = quote_provider(symbol) if quote_provider else fetch_quote(symbol)
        bars = bars_provider(symbol) if bars_provider else fetch_bars(symbol)
    except (RuntimeError, ValueError, FileNotFoundError) as e:
        append_guard_event("preflight_fail", {
            "symbol": symbol, "passed": False,
            "reason": f"Data retrieval failed: {e}",
        })
        return {"passed": False, "error": f"Data retrieval failed: {e}"}

    net_liquidation_eur = account["net_liquidation_eur"]
    exchange_rate = account["exchange_rate"]

    # H4.2: FX plausibility guard — reject if EUR/USD outside [0.8, 1.4]
    if exchange_rate is None or not isinstance(exchange_rate, (int, float)):
        append_guard_event("preflight_fail", {
            "symbol": symbol, "passed": False,
            "reason": "EUR/USD rate unavailable from IBKR account",
            "gate": "fx_plausibility",
        })
        return {
            "passed": False,
            "error": "EUR/USD rate unavailable: cannot compute USD sizing.",
            "gate": "fx_plausibility",
        }
    if exchange_rate < 0.8 or exchange_rate > 1.4:
        append_guard_event("preflight_fail", {
            "symbol": symbol, "passed": False,
            "reason": f"EUR/USD rate {exchange_rate:.4f} outside [0.80, 1.40]",
            "gate": "fx_plausibility",
        })
        return {
            "passed": False,
            "error": f"EUR/USD rate {exchange_rate:.4f} outside plausibility range [0.80, 1.40].",
            "gate": "fx_plausibility",
        }

    if is_close:
        # SELL: use bid price for exit reference; skip stop calc
        entry_price = quote.get("bid") or quote.get("close") or 0.0
        if entry_price is None or entry_price <= 0:
            entry_price = quote.get("close", 0.0)
        # No stop needed for closing a position
        stop_price = None
        stop_distance = 0.0
        atr14 = None
    else:
        entry_price = quote["ask"]

    # Compute or validate stop (BUY only)
    if not is_close:
        user_stop = norm.get("stopPrice")
        user_stop_pct = norm.get("stopPercent")

        # P5: stopPercent takes precedence if both are provided
        if user_stop_pct is not None:
            # stopPercent is a negative number, e.g. -5.0 = 5% below entry
            derived_stop = entry_price * (1.0 + user_stop_pct / 100.0)
            if derived_stop <= 0 or derived_stop >= entry_price:
                return {
                    "passed": False,
                    "error": (
                        f"Derived stop from stopPercent={user_stop_pct}% "
                        f"({derived_stop:.2f}) must be below entry price ({entry_price:.2f})"
                    ),
                }
            stop_price = derived_stop
            stop_distance = entry_price - stop_price
            atr14 = None
        elif user_stop is not None:
            try:
                user_stop = float(user_stop)
            except (TypeError, ValueError):
                return {"passed": False, "error": "stopPrice must be numeric"}
            if user_stop >= entry_price:
                return {
                    "passed": False,
                    "error": f"stopPrice ({user_stop}) must be below entry price ({entry_price:.2f})",
                }
            stop_price = user_stop
            stop_distance = entry_price - stop_price
            atr14 = None
        else:
            try:
                stop_result = calc_stop(entry_price, bars)
                stop_price = stop_result["stop_price"]
                stop_distance = stop_result["stop_distance"]
                atr14 = stop_result["atr14"]
            except ValueError as e:
                append_guard_event("preflight_fail", {
                    "symbol": symbol, "passed": False,
                    "reason": f"Stop calculation failed: {e}",
                })
                return {"passed": False, "error": f"Stop calculation failed: {e}"}

    # Compute share sizing (BUY only; SELL uses existing position size)
    if is_close:
        sizing = None
        final_max_shares = 0
    else:
        sizing = compute_final_max_shares(
            rules, net_liquidation_eur, exchange_rate,
            entry_price, stop_distance,
        )
        final_max_shares = sizing["final_max_shares"]

    # Run gates (SELL path skips B, C, F)
    gates = []
    all_pass = True

    # Gate A \u2014 allowlist (both BUY and SELL)
    ok, reason, details = gate_allowlist(symbol, rules)
    gates.append({"gate": "allowlist", "passed": ok, "reason": reason, "details": details})
    if not ok:
        all_pass = False

    # Gate H \u2014 proposal discipline (both BUY and SELL)
    ok, reason, details = gate_proposal_discipline(proposal_path)
    gates.append({"gate": "proposal", "passed": ok, "reason": reason, "details": details})
    if not ok:
        all_pass = False

    if is_close:
        # SELL (close-only): skip B (notional), C (risk), F (exposure)
        # Run D (trades/day), E (loss halts), G (close-only position gate)

        # Gate D \u2014 trades per day
        ok, reason, details = gate_trades_per_day(state, rules)
        gates.append({"gate": "trades_per_day", "passed": ok, "reason": reason, "details": details})
        if not ok:
            all_pass = False

        # Gate E — loss halts (P2b: close-only SELL exempt)
        ok, reason, details = gate_loss_halts(
            state, net_liquidation_eur, rules,
            action=action, symbol=symbol,
            proposed_shares=proposed_shares,
            position_provider=position_provider,
        )
        gates.append({"gate": "loss_halts", "passed": ok, "reason": reason, "details": details})
        if not ok:
            all_pass = False
        # Gate G — close-only position gate (invariant #9).
        # Bug fix (2026-09-07): this gate was never wired. Since 63052ed
        # (which added gate_close_only()) the branch appended a "close_only"
        # entry that silently reused Gate E's (ok, reason, details), so
        # gate_close_only() never ran. Gate E only checks the position while
        # a loss halt is active, so with no halt a SELL for a symbol with no
        # position, or larger than the position, passed preflight — the
        # exact short-creation path invariant #9 exists to block. Found by
        # tests/test_claude_md_consistency.py's "every gate function is
        # wired into run_preflight()" assertion.
        ok, reason, details = gate_close_only(symbol, proposed_shares, position_provider)
        gates.append({"gate": "close_only", "passed": ok, "reason": reason, "details": details})
        if not ok:
            all_pass = False

        # Open order conflict check (close-only)
        ok, reason, details = gate_open_orders(symbol, open_order_provider)
        gates.append({"gate": "open_orders", "passed": ok, "reason": reason, "details": details})
        if not ok:
            all_pass = False

    else:
        # BUY: run gates B, C, D, E, F

        # Gate B \u2014 notional (no existing exposure in this call)
        ok, reason, details = gate_notional(
            symbol, proposed_shares, entry_price,
            rules, net_liquidation_eur, exchange_rate,
        )
        gates.append({"gate": "notional", "passed": ok, "reason": reason, "details": details})
        if not ok:
            all_pass = False

        # Gate C \u2014 risk
        ok, reason, details = gate_risk(
            proposed_shares, stop_distance,
            rules, net_liquidation_eur, exchange_rate,
        )
        gates.append({"gate": "risk", "passed": ok, "reason": reason, "details": details})
        if not ok:
            all_pass = False

        # Gate D \u2014 trades per day
        ok, reason, details = gate_trades_per_day(state, rules)
        gates.append({"gate": "trades_per_day", "passed": ok, "reason": reason, "details": details})
        if not ok:
            all_pass = False

        # Gate E \u2014 loss halts
        ok, reason, details = gate_loss_halts(state, net_liquidation_eur, rules)
        gates.append({"gate": "loss_halts", "passed": ok, "reason": reason, "details": details})
        if not ok:
            all_pass = False

        # Gate F \u2014 exposure (no positions in this call)
        ok, reason, details = gate_exposure(
            proposed_shares, entry_price,
            rules, net_liquidation_eur, exchange_rate,
            [],
        )
        gates.append({"gate": "exposure", "passed": ok, "reason": reason, "details": details})
        if not ok:
            all_pass = False

        # Gate I — sector concentration. Requires live position data to be
        # meaningful (an empty-positions default would make the cap
        # unenforceable); fails closed if positions can't be fetched, the
        # same way a failed account/quote/bars fetch aborts preflight above.
        try:
            gate_i_positions = position_provider() if position_provider else None
            if not isinstance(gate_i_positions, list):
                gate_i_positions = None
        except Exception:
            gate_i_positions = None

        if gate_i_positions is None:
            ok, reason, details = (
                False,
                "GATE_I_POSITIONS_UNAVAILABLE",
                {"symbol": symbol, "sector": None, "exempt": False},
            )
        else:
            ok, reason, details = gate_sector_concentration(symbol, gate_i_positions, rules)
        gates.append({"gate": "sector_concentration", "passed": ok, "reason": reason, "details": details})
        if not ok:
            all_pass = False

    # Build result
    result = {
        "passed": all_pass,
        "symbol": symbol,
        "action": norm["action"],
        "orderType": norm["orderType"],
        "totalQuantity": proposed_shares,
        "entry_price": round(entry_price, 2) if not is_close else None,
        "stop_price": round(stop_price, 2) if not is_close else None,
        "stop_distance": round(stop_distance, 2) if not is_close else None,
        "atr14": round(atr14, 2) if not is_close and atr14 is not None else None,
        "gates": gates,
    }

    # Add close-specific fields for SELL
    if is_close:
        pos_info = _get_existing_position(symbol, position_provider)
        result["close_only"] = True
        result["position_source"] = pos_info["source"]
        result["existing_position_qty"] = pos_info["qty"]
        result["position_note"] = pos_info["note"]
    else:
        result["binding_cap"] = sizing["binding_cap"] if sizing else None
        result["final_max_shares"] = final_max_shares
        result["shares_requested"] = proposed_shares
        result["shares_exceeds_max"] = proposed_shares > final_max_shares
        result["close_only"] = False
        result["position_source"] = None

    # Log event and create approval record
    if all_pass:
        try:
            approval = create_approval_record(result)
            result["approval_id"] = approval["approval_id"]
            result["approval_expires_at_utc"] = approval["expires_at_utc"]
        except ValueError as e:
            result["passed"] = False
            result["error"] = f"Approval creation failed: {e}"
            return result

        append_guard_event("preflight_pass", {
            "symbol": symbol, "passed": True,
            "reason": "All gates green",
            "approval_id": approval["approval_id"],
            "final_max_shares": final_max_shares,
            "binding_cap": sizing["binding_cap"] if sizing else None,
        })
    else:
        failed_gates = [g["gate"] for g in gates if not g["passed"]]
        append_guard_event("preflight_fail", {
            "symbol": symbol, "passed": False,
            "reason": f"Gates blocked: {failed_gates}",
            "failed_gates": failed_gates,
        })

    return result


_historical = run_preflight

def run_preflight(*args, **kwargs):
    import types
    from trading_agent import legacy_guard
    function = types.FunctionType(_historical.__code__, vars(legacy_guard), argdefs=_historical.__defaults__)
    return function(*args, **kwargs)
