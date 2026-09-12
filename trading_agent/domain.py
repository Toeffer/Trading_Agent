"""Immutable contracts shared by policy, storage, HTTP and broker adapters."""

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from enum import StrEnum
import hashlib
import json
from typing import Any, cast


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def timestamp(value: str | datetime) -> datetime:
    result = (
        datetime.fromisoformat(value.replace("Z", "+00:00"))
        if isinstance(value, str)
        else value
    )
    if result.tzinfo is None:
        raise ValueError("Timestamp must include timezone")
    return result.astimezone(timezone.utc)


def money(value: Any) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise ValueError("Missing or invalid monetary value")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("Invalid monetary value") from exc
    if not result.is_finite():
        raise ValueError("Monetary values must be finite")
    return result


def canonical(value: Any) -> str:
    def encode(item: Any) -> str:
        if isinstance(item, Decimal):
            return str(item)
        if isinstance(item, datetime):
            return timestamp(item).isoformat()
        raise TypeError(type(item).__name__)

    return json.dumps(
        value, default=encode, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def content_hash(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


class ExecutionState(StrEnum):
    SUBMITTING = "submitting"
    ACKNOWLEDGED = "acknowledged"
    PARTIAL = "partially_filled"
    FILLED = "filled"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class ApprovedOrderPlan:
    account: str
    symbol: str
    contract_id: int
    currency: str
    side: str
    quantity: int
    order_type: str
    entry_price: Decimal
    stop_price: Decimal | None
    proposal_hash: str
    policy_hash: str
    created_at: datetime
    expires_at: datetime
    market_observed_at: datetime
    proposal_id: str | None = None
    schema_version: int = 1
    stop_basis: str = "explicit"
    max_entry_price: Decimal | None = None
    min_exit_price: Decimal | None = None

    def __post_init__(self) -> None:
        if self.schema_version != 1 or self.order_type != "MKT":
            raise ValueError("Only version 1 MKT plans are executable")
        if not self.account or not self.symbol or not self.currency:
            raise ValueError("Account, symbol and currency are required")
        if type(self.quantity) is not int or self.quantity <= 0:
            raise ValueError("Quantity must be a positive integer")
        if type(self.contract_id) is not int or self.contract_id <= 0:
            raise ValueError("Qualified contract identity is required")
        if self.side not in ("BUY", "SELL"):
            raise ValueError("Invalid side")
        if self.stop_basis not in ("explicit", "atr"):
            raise ValueError("Invalid stop basis")
        object.__setattr__(self, "entry_price", money(self.entry_price))
        if self.entry_price <= 0:
            raise ValueError("Entry reference must be positive")
        if self.stop_price is not None:
            object.__setattr__(self, "stop_price", money(self.stop_price))
        if self.side == "BUY" and (
            self.stop_price is None or not 0 < self.stop_price < self.entry_price
        ):
            raise ValueError("BUY requires a protective stop below entry")
        for field in ("max_entry_price", "min_exit_price"):
            value = getattr(self, field)
            if value is not None:
                value = money(value)
                if value <= 0:
                    raise ValueError("Price constraints must be positive")
                object.__setattr__(self, field, value)
        for field in ("created_at", "expires_at", "market_observed_at"):
            object.__setattr__(self, field, timestamp(getattr(self, field)))
        if (self.expires_at - self.created_at).total_seconds() != 300:
            raise ValueError(
                "Approval expiry must be exactly 300 seconds, without extension"
            )
        for digest in (self.proposal_hash, self.policy_hash):
            if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
                raise ValueError("A SHA-256 proposal/policy identity is required")

    def to_dict(self) -> dict[str, Any]:
        return cast(dict[str, Any], json.loads(canonical(asdict(self))))

    def to_json(self) -> str:
        return canonical(self.to_dict())

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ApprovedOrderPlan":
        return cls(**value)

    @classmethod
    def from_json(cls, value: str) -> "ApprovedOrderPlan":
        return cls.from_dict(json.loads(value))


@dataclass(frozen=True, slots=True)
class BrokerResult:
    state: ExecutionState
    order_id: int | None = None
    permanent_id: int | None = None
    stop_order_id: int | None = None
    protection_state: str = "not_applicable"
    filled_quantity: int = 0
    error_code: str | None = None
    # These are actual broker execution events, never inferred from status totals.
    fills: tuple[tuple[str, int, Decimal, datetime], ...] = ()
    stop_fills: tuple[tuple[str, int, Decimal, datetime], ...] = ()
    parent_status: str | None = None
    stop_status: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.state, ExecutionState):
            raise ValueError("Invalid broker state")
        if self.protection_state not in (
            "not_applicable",
            "unknown",
            "confirmed",
            "closed",
            "cancelled",
        ):
            raise ValueError("Invalid protection state")
        if type(self.filled_quantity) is not int or self.filled_quantity < 0:
            raise ValueError("Invalid fill total")
        for events in (self.fills, self.stop_fills):
            for identity, quantity, price, observed in events:
                if (
                    not identity
                    or type(quantity) is not int
                    or quantity <= 0
                    or money(price) <= 0
                ):
                    raise ValueError("Invalid fill evidence")
                timestamp(observed)

    def to_dict(self) -> dict[str, Any]:
        return cast(dict[str, Any], json.loads(canonical(asdict(self))))


@dataclass(frozen=True, slots=True)
class Position:
    symbol: str
    quantity: int
    market_value_base: Decimal
    sector: str


@dataclass(frozen=True, slots=True)
class OpenOrder:
    symbol: str
    side: str
    remaining: int
    value_base: Decimal
    execution_ref: str | None = None
    counts_as_pending_trade: bool = True
    contract_id: int | None = None


@dataclass(frozen=True, slots=True)
class AccountFill:
    account: str
    broker_execution_id: str
    order_key: str
    symbol: str
    side: str
    quantity: int
    price: Decimal
    executed_at: datetime
    execution_ref: str | None = None
    role: str = "parent"
    history_complete: bool = False

    def __post_init__(self) -> None:
        if (
            not all(
                (self.account, self.broker_execution_id, self.order_key, self.symbol)
            )
            or self.side not in ("BUY", "SELL")
            or self.role not in ("parent", "stop")
            or type(self.quantity) is not int
            or self.quantity <= 0
            or money(self.price) <= 0
        ):
            raise ValueError("INVALID_ACCOUNT_FILL")
        timestamp(self.executed_at)


@dataclass(frozen=True, slots=True)
class PortfolioSnapshot:
    account: str
    mode: str
    base_currency: str
    quote_currency: str
    net_liquidation: Decimal
    base_to_quote: Decimal
    observed_at: datetime
    market_observed_at: datetime
    market_data_type: str
    bid: Decimal
    ask: Decimal
    positions: tuple[Position, ...]
    open_orders: tuple[OpenOrder, ...]
    daily_trade_count: int
    daily_loss_halt: bool
    weekly_loss_halt: bool
    contract_id: int
    evidence_revision: int | None = None
    verified_fills: tuple[AccountFill, ...] = ()
    accounting_coverage: bool = True
