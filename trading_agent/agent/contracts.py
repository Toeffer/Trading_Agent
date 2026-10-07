"""Validated inputs for an offline agent; no ambient account or configuration reads."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
import math
from typing import Any

from trading_agent.domain import content_hash, money, timestamp
from trading_agent.risk import RiskPolicy


def fields(raw: Any, required: set[str], optional: set[str] | None = None) -> None:
    if not isinstance(raw, dict) or not required <= raw.keys():
        raise ValueError("MISSING_FIELDS: " + ",".join(sorted(required)))
    if raw.keys() - required - (optional or set()):
        raise ValueError("UNKNOWN_FIELDS")


def label(value: Any) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 500:
        raise ValueError("INVALID_LABEL")
    return value


def integer(value: Any, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError("INTEGER_OUT_OF_RANGE")
    return value


def fraction(value: Any) -> Decimal:
    result = money(value)
    if not 0 < result <= 1:
        raise ValueError("FRACTION_OUT_OF_RANGE")
    return result


def instant(value: Any) -> datetime:
    if not isinstance(value, (str, datetime)):
        raise ValueError("INVALID_TIMESTAMP")
    return timestamp(value)


@dataclass(frozen=True)
class Mandate:
    """Simulation mandate, pinned for the lifetime of one agent database."""

    raw: dict[str, Any]
    identity: str
    account: str
    instruments: dict[str, dict[str, Any]]
    starts_at: datetime
    expires_at: datetime
    policy: RiskPolicy

    @classmethod
    def parse(cls, raw: dict[str, Any]) -> "Mandate":
        fields(
            raw,
            {
                "schema_version",
                "mode",
                "account",
                "base_currency",
                "quote_currency",
                "initial_cash",
                "starts_at",
                "expires_at",
                "instruments",
                "risk",
                "strategy",
                "costs",
            },
        )
        if type(raw["schema_version"]) is not int or raw["schema_version"] != 1:
            raise ValueError("UNSUPPORTED_MANDATE_VERSION")
        if raw["mode"] != "simulation":
            raise ValueError("ONLY_SIMULATION_IS_IMPLEMENTED")
        account = label(raw["account"])
        for key in ("base_currency", "quote_currency"):
            value = label(raw[key])
            if (
                len(value) != 3
                or not value.isascii()
                or not value.isalpha()
                or value != value.upper()
            ):
                raise ValueError("INVALID_CURRENCY")
        if money(raw["initial_cash"]) <= 0:
            raise ValueError("INVALID_INITIAL_CASH")
        start, expiry = instant(raw["starts_at"]), instant(raw["expires_at"])
        if start >= expiry:
            raise ValueError("INVALID_MANDATE_WINDOW")
        instruments = raw["instruments"]
        if not isinstance(instruments, dict) or not 1 <= len(instruments) <= 32:
            raise ValueError("INVALID_UNIVERSE")
        contracts: set[int] = set()
        for symbol, instrument in instruments.items():
            if label(symbol) != symbol.upper() or not symbol.isascii():
                raise ValueError("INVALID_SYMBOL")
            fields(instrument, {"contract_id", "sector"})
            contract = integer(instrument["contract_id"], 1, 2**31 - 1)
            if contract in contracts:
                raise ValueError("DUPLICATE_CONTRACT")
            contracts.add(contract)
            label(instrument["sector"])
        risk = raw["risk"]
        fields(
            risk,
            {
                "position_fraction",
                "trade_risk_fraction",
                "exposure_fraction",
                "max_trades_per_day",
                "max_positions_per_sector",
                "daily_loss_fraction",
                "weekly_loss_fraction",
            },
        )
        strategy = raw["strategy"]
        fields(
            strategy,
            {"version", "stop_fraction", "max_holding_days", "max_bar_age_hours"},
        )
        if strategy["version"] != "agent-trend-v1":
            raise ValueError("UNSUPPORTED_STRATEGY")
        if fraction(strategy["stop_fraction"]) >= 1:
            raise ValueError("INVALID_STOP_FRACTION")
        integer(strategy["max_holding_days"], 1, 365)
        integer(strategy["max_bar_age_hours"], 1, 168)
        costs = raw["costs"]
        fields(costs, {"slippage_bps", "commission_per_order_quote"})
        if not 0 <= money(costs["slippage_bps"]) <= 100:
            raise ValueError("INVALID_SLIPPAGE")
        if money(costs["commission_per_order_quote"]) < 0:
            raise ValueError("INVALID_COMMISSION")
        identity = content_hash(raw)
        policy = RiskPolicy(
            allowed_symbols=frozenset(instruments),
            blocked_buys=frozenset(),
            sectors=tuple(sorted((s, i["sector"]) for s, i in instruments.items())),
            max_position_pct=fraction(risk["position_fraction"]),
            max_risk_pct=fraction(risk["trade_risk_fraction"]),
            max_exposure_pct=fraction(risk["exposure_fraction"]),
            max_trades_per_day=integer(risk["max_trades_per_day"], 1, 1000),
            max_positions_per_sector=integer(risk["max_positions_per_sector"], 1, 32),
            daily_loss_pct=fraction(risk["daily_loss_fraction"]),
            weekly_loss_pct=fraction(risk["weekly_loss_fraction"]),
            policy_hash=identity,
        )
        return cls(raw, identity, account, instruments, start, expiry, policy)


@dataclass(frozen=True)
class Observation:
    raw: dict[str, Any]
    identity: str
    at: datetime

    @classmethod
    def parse(cls, raw: dict[str, Any], mandate: Mandate) -> "Observation":
        fields(
            raw,
            {
                "schema_version",
                "event_id",
                "account",
                "at",
                "base_to_quote",
                "quotes",
                "reference_bars",
            },
            {"opinions"},
        )
        if type(raw["schema_version"]) is not int or raw["schema_version"] != 1:
            raise ValueError("UNSUPPORTED_OBSERVATION_VERSION")
        identity = label(raw["event_id"])
        if raw["account"] != mandate.account:
            raise ValueError("ACCOUNT_MISMATCH")
        at = instant(raw["at"])
        fx = money(raw["base_to_quote"])
        if fx <= 0 or (
            mandate.raw["base_currency"] == mandate.raw["quote_currency"] and fx != 1
        ):
            raise ValueError("INVALID_FX")
        quotes = raw["quotes"]
        if not isinstance(quotes, dict) or quotes.keys() != mandate.instruments.keys():
            raise ValueError("COMPLETE_UNIVERSE_QUOTES_REQUIRED")
        cutoff = cls._bars(raw["reference_bars"], at, mandate)
        for quote in quotes.values():
            fields(quote, {"bid", "ask", "observed_at", "bars"})
            bid, ask = money(quote["bid"]), money(quote["ask"])
            if not 0 < bid <= ask:
                raise ValueError("INVALID_QUOTE")
            age = (at - instant(quote["observed_at"])).total_seconds()
            if not 0 <= age <= mandate.policy.quote_max_age_seconds:
                raise ValueError("STALE_OR_FUTURE_QUOTE")
            if cls._bars(quote["bars"], at, mandate) != cutoff:
                raise ValueError("MISALIGNED_HISTORY")
        opinions = raw.get("opinions", {})
        if (
            not isinstance(opinions, dict)
            or opinions.keys() - mandate.instruments.keys()
        ):
            raise ValueError("INVALID_OPINION_SYMBOL")
        for opinion in opinions.values():
            fields(
                opinion,
                {"action", "thesis", "invalidation", "sources", "model", "observed_at"},
            )
            if opinion["action"] not in ("ENTER", "HOLD", "EXIT"):
                raise ValueError("INVALID_OPINION_ACTION")
            for key in ("thesis", "invalidation", "model"):
                label(opinion[key])
            if not 0 <= (at - instant(opinion["observed_at"])).total_seconds() <= 86400:
                raise ValueError("STALE_OR_FUTURE_OPINION")
            sources = opinion["sources"]
            if not isinstance(sources, list) or not 1 <= len(sources) <= 20:
                raise ValueError("OPINION_SOURCES_REQUIRED")
            for source in sources:
                label(source)
        return cls(raw, identity, at)

    @staticmethod
    def _bars(raw: Any, at: datetime, mandate: Mandate) -> datetime:
        from strategy_v1_1_core import is_valid_daily_bar

        if not isinstance(raw, list) or not 1 <= len(raw) <= 4096:
            raise ValueError("INVALID_BAR_HISTORY")
        previous: datetime | None = None
        for bar in raw:
            fields(
                bar,
                {"ended_at", "available_at", "open", "high", "low", "close", "volume"},
            )
            ended, available = instant(bar["ended_at"]), instant(bar["available_at"])
            if not ended <= available <= at or (
                previous is not None and ended.date() <= previous.date()
            ):
                raise ValueError("FUTURE_OR_UNORDERED_HISTORY")
            numbers = {
                key: float(money(bar[key]))
                for key in ("open", "high", "low", "close", "volume")
            }
            if (
                not all(math.isfinite(v) for v in numbers.values())
                or not is_valid_daily_bar(numbers)[0]
            ):
                raise ValueError("INVALID_BAR")
            previous = ended
        assert previous is not None
        if (at - previous).total_seconds() > mandate.raw["strategy"][
            "max_bar_age_hours"
        ] * 3600:
            raise ValueError("STALE_HISTORY")
        return previous


def numeric_bars(bars: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            key: float(money(bar[key]))
            for key in ("open", "high", "low", "close", "volume")
        }
        for bar in bars
    ]
