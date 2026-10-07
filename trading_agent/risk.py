"""One deterministic risk evaluator for preflight and submission."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from trading_agent.domain import (
    ApprovedOrderPlan,
    PortfolioSnapshot,
    content_hash,
    money,
    timestamp,
    utcnow,
)


class RiskRejected(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class RiskPolicy:
    allowed_symbols: frozenset[str]
    blocked_buys: frozenset[str]
    sectors: tuple[tuple[str, str], ...]
    max_position_pct: Decimal
    max_risk_pct: Decimal
    max_exposure_pct: Decimal
    max_trades_per_day: int
    max_positions_per_sector: int
    daily_loss_pct: Decimal
    weekly_loss_pct: Decimal
    policy_hash: str
    snapshot_max_age_seconds: int = 30
    quote_max_age_seconds: int = 30

    @classmethod
    def from_rules(cls, rules: dict[str, Any]) -> "RiskPolicy":
        def percentage(key: str) -> Decimal:
            result = money(rules[key]["value"]) / 100
            if not 0 < result <= 1:
                raise ValueError(f"Invalid {key}")
            return result

        def loss_percentage(period: str) -> Decimal:
            loss = rules["loss_halts"]
            value = money(
                loss[period]["value"] if period in loss else loss[period + "_pct"]
            )
            if (
                period in loss
                and period + "_pct" in loss
                and value != money(loss[period + "_pct"])
            ):
                raise ValueError("Conflicting loss halt thresholds")
            if not 0 < value <= 100:
                raise ValueError("Invalid loss halt threshold")
            return value / 100

        allow = rules["symbol_allowlist"]
        if allow["mode"] != "explicit_list" or not allow["allow"]:
            raise ValueError("An explicit symbol allowlist is required")
        sectors = rules["symbol_sectors"]
        if not isinstance(sectors, dict):
            raise ValueError("Explicit sector mappings required")
        max_trades = rules["max_trades_per_day"]["value"]
        max_sector = rules["max_positions_per_sector"]["value"]
        if (
            type(max_trades) is not int
            or max_trades <= 0
            or type(max_sector) is not int
            or max_sector <= 0
        ):
            raise ValueError("Capacity limits must be positive integers")
        # Hash the whole normalized rule document, including enablement. A
        # changed rule document requires a fresh preflight and human approval.
        from trading_agent.legacy_guard import _load_us_etf_blocklist

        return cls(
            frozenset(allow["allow"]),
            _load_us_etf_blocklist(rules),
            tuple(sorted(sectors.items())),
            percentage("max_position_notional"),
            percentage("max_risk_per_trade"),
            percentage("max_total_exposure"),
            max_trades,
            max_sector,
            loss_percentage("daily"),
            loss_percentage("weekly"),
            content_hash(rules),
        )


def validate_snapshot(
    snapshot: PortfolioSnapshot,
    expected_account: str,
    *,
    now: datetime | None = None,
    max_snapshot_age: int = 30,
    max_quote_age: int = 30,
) -> None:
    now = now or utcnow()
    if (
        not expected_account
        or snapshot.account != expected_account
        or snapshot.mode != "paper"
    ):
        raise RiskRejected("PAPER_ACCOUNT_MISMATCH")
    if (
        not snapshot.base_currency
        or not snapshot.quote_currency
        or snapshot.contract_id <= 0
    ):
        raise RiskRejected("INCOMPLETE_ACCOUNT_OR_CONTRACT")
    for observed, maximum in (
        (snapshot.observed_at, max_snapshot_age),
        (snapshot.market_observed_at, max_quote_age),
    ):
        age = (now - timestamp(observed)).total_seconds()
        if age < -2 or age > maximum:
            raise RiskRejected("STALE_OR_FUTURE_DATA")
    if snapshot.market_data_type != "realtime":
        raise RiskRejected("EXECUTION_REQUIRES_REALTIME_DATA")
    if any(
        money(v) <= 0
        for v in (
            snapshot.net_liquidation,
            snapshot.base_to_quote,
            snapshot.bid,
            snapshot.ask,
        )
    ):
        raise RiskRejected("INVALID_ACCOUNT_FX_OR_PRICE")
    if snapshot.ask < snapshot.bid:
        raise RiskRejected("CROSSED_QUOTE")
    if type(snapshot.daily_trade_count) is not int or snapshot.daily_trade_count < 0:
        raise RiskRejected("INVALID_DAILY_COUNT")
    for position in snapshot.positions:
        if (
            type(position.quantity) is not int
            or position.quantity < 0
            or money(position.market_value_base) < 0
        ):
            raise RiskRejected("INVALID_OR_SHORT_POSITION")
        if position.quantity and position.market_value_base <= 0:
            raise RiskRejected("POSITION_VALUATION_UNAVAILABLE")
    for order in snapshot.open_orders:
        if (
            order.side not in ("BUY", "SELL")
            or type(order.remaining) is not int
            or order.remaining < 0
        ):
            raise RiskRejected("INVALID_OPEN_ORDER")
        if order.remaining and money(order.value_base) <= 0:
            raise RiskRejected("OPEN_ORDER_VALUATION_UNAVAILABLE")


def evaluate(
    plan: ApprovedOrderPlan,
    snapshot: PortfolioSnapshot,
    policy: RiskPolicy,
    reservations: list[dict[str, Any]],
    *,
    now: datetime | None = None,
) -> None:
    now = now or utcnow()
    validate_snapshot(
        snapshot,
        plan.account,
        now=now,
        max_snapshot_age=policy.snapshot_max_age_seconds,
        max_quote_age=policy.quote_max_age_seconds,
    )
    if plan.expires_at <= now:
        raise RiskRejected("EXPIRED")
    if plan.policy_hash != policy.policy_hash:
        raise RiskRejected("POLICY_CHANGED")
    if (
        plan.contract_id != snapshot.contract_id
        or plan.currency != snapshot.quote_currency
    ):
        raise RiskRejected("CONTRACT_CHANGED")
    if plan.symbol not in policy.allowed_symbols or (
        plan.side == "BUY" and plan.symbol in policy.blocked_buys
    ):
        raise RiskRejected("SYMBOL_NOT_ALLOWED")
    current_price = snapshot.ask if plan.side == "BUY" else snapshot.bid
    if (
        plan.side == "BUY"
        and plan.max_entry_price is not None
        and current_price > plan.max_entry_price
    ):
        raise RiskRejected("APPROVED_ENTRY_PRICE_EXCEEDED")
    if (
        plan.side == "SELL"
        and plan.min_exit_price is not None
        and current_price < plan.min_exit_price
    ):
        raise RiskRejected("APPROVED_EXIT_PRICE_NOT_MET")
    if abs(current_price / plan.entry_price - 1) > Decimal("0.01"):
        raise RiskRejected("PRICE_DRIFT")
    # A reservation represented by a broker open order is counted once.
    refs = {
        order.execution_ref for order in snapshot.open_orders if order.execution_ref
    }
    pending = [r for r in reservations if r["execution_id"] not in refs]

    def unfilled(reservation: dict[str, Any]) -> int:
        quantity = int(reservation["quantity"])
        filled = int(reservation.get("filled_quantity", 0))
        if not 0 <= filled <= quantity:
            raise RiskRejected("RESERVATION_QUANTITY_CONFLICT")
        if filled and snapshot.evidence_revision is None:
            raise RiskRejected("ACCOUNTING_HISTORY_INCOMPLETE")
        return quantity - filled

    pending_trades = sum(not r.get("filled_quantity", 0) for r in pending) + len(
        {
            o.execution_ref or (o.symbol, o.side)
            for o in snapshot.open_orders
            if o.remaining and o.counts_as_pending_trade
        }
    )
    if snapshot.daily_trade_count + pending_trades >= policy.max_trades_per_day:
        raise RiskRejected("DAILY_CAPACITY_EXCEEDED")
    position_qty = sum(
        p.quantity for p in snapshot.positions if p.symbol == plan.symbol
    )
    if plan.side == "SELL":
        reserved_sell = sum(
            unfilled(r)
            for r in pending
            if r["symbol"] == plan.symbol and r["side"] == "SELL"
        )
        open_sell = sum(
            o.remaining
            for o in snapshot.open_orders
            if o.symbol == plan.symbol and o.side == "SELL"
        )
        if plan.quantity > position_qty - reserved_sell - open_sell:
            raise RiskRejected("CLOSE_ONLY_EXCEEDED")
        # Confirmed risk-reducing exits retain the documented loss-halt exemption.
        return
    if snapshot.daily_loss_halt or snapshot.weekly_loss_halt:
        raise RiskRejected("LOSS_HALT")
    if plan.stop_price is None or plan.stop_price >= snapshot.ask:
        raise RiskRejected("INVALID_PROTECTIVE_STOP")
    fx = snapshot.base_to_quote
    proposed_base = plan.quantity * snapshot.ask / fx
    existing = sum((p.market_value_base for p in snapshot.positions), Decimal(0))
    symbol_existing = sum(
        (p.market_value_base for p in snapshot.positions if p.symbol == plan.symbol),
        Decimal(0),
    )
    reserved = sum(
        (unfilled(r) * money(r["price"]) / fx for r in pending if r["side"] == "BUY"),
        Decimal(0),
    )
    symbol_reserved = sum(
        (
            unfilled(r) * money(r["price"]) / fx
            for r in pending
            if r["side"] == "BUY" and r["symbol"] == plan.symbol
        ),
        Decimal(0),
    )
    open_buy = sum(
        (o.value_base for o in snapshot.open_orders if o.side == "BUY"), Decimal(0)
    )
    symbol_open_buy = sum(
        (
            o.value_base
            for o in snapshot.open_orders
            if o.side == "BUY" and o.symbol == plan.symbol
        ),
        Decimal(0),
    )
    if (
        proposed_base + symbol_existing + symbol_reserved + symbol_open_buy
        > snapshot.net_liquidation * policy.max_position_pct
    ):
        raise RiskRejected("SYMBOL_EXPOSURE_EXCEEDED")
    if (
        proposed_base + existing + reserved + open_buy
        > snapshot.net_liquidation * policy.max_exposure_pct
    ):
        raise RiskRejected("PORTFOLIO_EXPOSURE_EXCEEDED")
    if (
        plan.quantity * (snapshot.ask - plan.stop_price) / fx
        > snapshot.net_liquidation * policy.max_risk_pct
    ):
        raise RiskRejected("TRADE_RISK_EXCEEDED")
    sectors = dict(policy.sectors)
    sector = sectors.get(plan.symbol)
    if not sector:
        raise RiskRejected("SECTOR_UNAVAILABLE")
    symbols = {p.symbol for p in snapshot.positions if p.quantity}
    symbols.update(r["symbol"] for r in pending if r["side"] == "BUY")
    symbols.update(
        o.symbol for o in snapshot.open_orders if o.side == "BUY" and o.remaining
    )
    symbols.add(plan.symbol)
    if any(symbol not in sectors for symbol in symbols):
        raise RiskRejected("SECTOR_UNAVAILABLE")
    if sum(sectors[s] == sector for s in symbols) > policy.max_positions_per_sector:
        raise RiskRejected("SECTOR_CAPACITY_EXCEEDED")
