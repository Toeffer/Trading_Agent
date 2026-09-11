"""IBKR adapter. All client access executes on BrokerLoop's owner thread."""

import asyncio
from collections.abc import Callable
from datetime import datetime
from decimal import Decimal
import time
from typing import Any

from trading_agent.broker_loop import BrokerLoop
from trading_agent.domain import (
    ApprovedOrderPlan,
    AccountFill,
    BrokerResult,
    ExecutionState,
    OpenOrder,
    PortfolioSnapshot,
    Position,
    money,
    timestamp,
    utcnow,
)
from trading_agent.settings import Settings


class IBKRBroker:
    def __init__(self, owner: BrokerLoop, settings: Settings, sectors: dict[str, str]):
        self.owner = owner
        self.settings = settings
        self.sectors = sectors
        self._inflight: set[str] = set()
        self.event_failure = False
        self.evidence_revision = 0
        self._snapshot_revision: int | None = None

    def observe(
        self,
        lookup: Callable[[str], ApprovedOrderPlan],
        sink: Callable[[str, BrokerResult], None],
    ) -> None:
        """Install callbacks on the client owner; only persisted intents match."""

        async def operation(ib: Any) -> None:
            def event(trade: Any, *_: Any) -> None:
                if trade.order.account == self.settings.account:
                    self.evidence_revision += 1
                reference = trade.order.orderRef.removesuffix(":stop")
                if not reference.startswith("exec_") or reference in self._inflight:
                    return
                try:
                    plan = lookup(reference)
                    trades = [t for t in ib.trades() if t.order.account == plan.account]
                    parents = [t for t in trades if t.order.orderRef == reference]
                    stops = [
                        t for t in trades if t.order.orderRef == reference + ":stop"
                    ]
                    if len(parents) != 1 or len(stops) > 1:
                        raise ValueError("AMBIGUOUS_BROKER_EVENT")
                    sink(
                        reference,
                        self._result(plan, parents[0], stops[0] if stops else None),
                    )
                except Exception:
                    # A failed durable callback blocks all subsequent intake;
                    # it is visible in readiness and cleared only on restart.
                    self.event_failure = True

            ib.orderStatusEvent += event
            ib.execDetailsEvent += event
            ib.positionEvent += lambda *args: setattr(
                self, "evidence_revision", self.evidence_revision + 1
            )
            ib.disconnectedEvent += lambda: setattr(self, "event_failure", True)

        self.owner.run(operation)

    def connect(self) -> dict[str, Any]:
        async def operation(ib: Any) -> dict[str, Any]:
            if not ib.isConnected():
                await ib.connectAsync(
                    self.settings.host,
                    self.settings.port,
                    clientId=self.settings.client_id,
                    readonly=False,
                    account=self.settings.account,
                    timeout=self.settings.read_timeout,
                )
            self._account(ib)
            return {"connected": True, "managed_accounts": ib.managedAccounts()}

        return self.owner.run(operation, timeout=self.settings.read_timeout + 1)

    def _account(self, ib: Any) -> None:
        if self.event_failure:
            raise ValueError("BROKER_EVENT_REVIEW_REQUIRED")
        if (
            not ib.isConnected()
            or self.settings.mode != "paper"
            or self.settings.account not in ib.managedAccounts()
        ):
            raise ValueError("PAPER_ACCOUNT_MISMATCH")

    def snapshot(self, symbol: str) -> PortfolioSnapshot:
        async def operation(ib: Any) -> PortfolioSnapshot:
            from ib_insync import Stock

            self._account(ib)
            contracts = await ib.qualifyContractsAsync(Stock(symbol, "SMART", "USD"))
            if len(contracts) != 1:
                raise ValueError("CONTRACT_UNAVAILABLE")
            contract = contracts[0]
            await ib.reqAccountUpdatesAsync(self.settings.account)
            inventory = await ib.reqPositionsAsync()
            await ib.reqAllOpenOrdersAsync()
            start_revision = self.evidence_revision
            values = {
                (v.tag, v.currency): v.value
                for v in ib.accountValues(self.settings.account)
                if v.account == self.settings.account
            }
            base = self.settings.base_currency
            net = money(values.get(("NetLiquidation", base)))
            rates = {
                currency: money(value)
                for (tag, currency), value in values.items()
                if tag == "ExchangeRate"
            }
            rates[base] = Decimal(
                1
            )  # Identity conversion, not a missing-rate fallback.
            quote_to_base = rates.get(contract.currency)
            if quote_to_base is None or quote_to_base <= 0:
                raise ValueError("FX_UNAVAILABLE")
            holdings = {
                p.contract.conId: money(p.position)
                for p in inventory
                if p.account == self.settings.account and p.position
            }
            portfolio = [
                p
                for p in ib.portfolio(self.settings.account)
                if p.account == self.settings.account and p.position
            ]
            valued = {p.contract.conId: money(p.position) for p in portfolio}
            if holdings != valued or len(valued) != len(portfolio):
                raise ValueError("POSITION_VALUATION_INCOMPLETE")
            positions = []
            for item in portfolio:
                rate = rates.get(item.contract.currency)
                if rate is None or rate <= 0:
                    raise ValueError("POSITION_FX_UNAVAILABLE")
                qty = money(item.position)
                if qty != int(qty):
                    raise ValueError("NON_INTEGER_HOLDINGS")
                positions.append(
                    Position(
                        item.contract.symbol,
                        int(qty),
                        money(item.marketValue) * rate,
                        self.sectors.get(item.contract.symbol, ""),
                    )
                )
            # Snapshot timestamps are quote observation times from IBKR's
            # tick-by-tick stream, not the time a stale quote was fetched.
            requested_at = utcnow()
            ib.reqMarketDataType(1)
            ticker = ib.reqTickByTickData(contract, "BidAsk", 0, False)
            try:
                while (
                    not ticker.tickByTicks
                    or timestamp(ticker.tickByTicks[-1].time) < requested_at
                ):
                    await asyncio.sleep(0.02)
                tick = ticker.tickByTicks[-1]
                bid, ask = money(tick.bidPrice), money(tick.askPrice)
                observed = timestamp(tick.time)
            finally:
                ib.cancelTickByTickData(contract, "BidAsk")
            orders = []
            for trade in ib.openTrades():
                if trade.order.account != self.settings.account:
                    continue
                reported = money(trade.orderStatus.remaining)
                remaining = money(trade.order.totalQuantity) - money(
                    trade.orderStatus.filled
                )
                if remaining != int(remaining) or remaining < 0 or reported < 0:
                    raise ValueError("NON_INTEGER_OPEN_ORDER")
                if reported != remaining and trade.orderStatus.status not in (
                    "PendingSubmit",
                    "ApiPending",
                    "PendingCancel",
                ):
                    raise ValueError("OPEN_ORDER_QUANTITY_UNCERTAIN")
                if not remaining:
                    continue
                rate = rates.get(trade.contract.currency)
                price = money(
                    trade.order.lmtPrice
                    if trade.order.orderType == "LMT"
                    else trade.order.auxPrice
                    if trade.order.orderType == "STP"
                    else (ask if trade.contract.conId == contract.conId else 0)
                )
                if rate is None or price <= 0:
                    raise ValueError("OPEN_ORDER_VALUATION_UNAVAILABLE")
                orders.append(
                    OpenOrder(
                        trade.contract.symbol,
                        trade.order.action,
                        int(remaining),
                        remaining * price * rate,
                        trade.order.orderRef or None,
                        not bool(trade.order.parentId)
                        and not bool(trade.orderStatus.filled),
                    )
                )
            executions = await ib.reqExecutionsAsync()
            trades = ib.trades()
            account_fills = []
            for fill in executions:
                execution = fill.execution
                if execution.acctNumber != self.settings.account:
                    continue
                matches = [
                    t
                    for t in trades
                    if t.order.account == self.settings.account
                    and t.order.orderId == execution.orderId
                    and t.order.clientId == execution.clientId
                ]
                if len(matches) != 1:
                    raise ValueError("ACCOUNTING_HISTORY_INCOMPLETE")
                trade = matches[0]
                if (
                    trade.contract.conId != fill.contract.conId
                    or (trade.order.permId and trade.order.permId != execution.permId)
                    or execution.side
                    != ("BOT" if trade.order.action == "BUY" else "SLD")
                ):
                    raise ValueError("ACCOUNT_FILL_IDENTITY_MISMATCH")
                identity = (
                    f"perm:{execution.permId}"
                    if execution.permId
                    else f"client:{execution.clientId}:order:{execution.orderId}"
                )
                if not execution.permId:
                    # Session-local IDs cannot establish external history across restarts.
                    if not trade.order.orderRef.startswith("exec_"):
                        raise ValueError("ACCOUNTING_HISTORY_INCOMPLETE")
                observed_fills = {
                    f.execution.execId: f
                    for f in executions
                    if f.execution.acctNumber == self.settings.account
                    and f.execution.clientId == execution.clientId
                    and f.execution.orderId == execution.orderId
                }
                complete = sum(
                    money(f.execution.shares) for f in observed_fills.values()
                ) == money(trade.orderStatus.filled)
                quantity = money(execution.shares)
                if quantity != int(quantity) or execution.side not in ("BOT", "SLD"):
                    raise ValueError("INVALID_ACCOUNT_FILL")
                account_fills.append(
                    AccountFill(
                        self.settings.account,
                        execution.execId,
                        identity,
                        fill.contract.symbol,
                        "BUY" if execution.side == "BOT" else "SELL",
                        int(quantity),
                        money(execution.price),
                        timestamp(fill.time),
                        trade.order.orderRef or None,
                        "stop"
                        if trade.order.parentId
                        and trade.order.orderRef.endswith(":stop")
                        else "parent",
                        complete,
                    )
                )
            if start_revision != self.evidence_revision:
                raise ValueError("ACCOUNT_EVIDENCE_CHANGED")
            self._snapshot_revision = self.evidence_revision
            return PortfolioSnapshot(
                self.settings.account,
                self.settings.mode,
                base,
                contract.currency,
                net,
                1 / quote_to_base,
                utcnow(),
                observed,
                "realtime" if ticker.marketDataType == 1 else "unavailable",
                bid,
                ask,
                tuple(positions),
                tuple(orders),
                0,
                False,
                False,
                contract.conId,
                verified_fills=tuple(account_fills),
                accounting_coverage=True,
            )

        return self.owner.run(operation, timeout=self.settings.read_timeout)

    def stop_price(self, symbol: str, entry: Decimal) -> Decimal:
        async def operation(ib: Any) -> Decimal:
            from ib_insync import Stock
            from trading_agent.legacy_guard import calc_stop

            contracts = await ib.qualifyContractsAsync(Stock(symbol, "SMART", "USD"))
            if len(contracts) != 1:
                raise ValueError("CONTRACT_UNAVAILABLE")
            bars = await ib.reqHistoricalDataAsync(
                contracts[0],
                endDateTime="",
                durationStr="30 D",
                barSizeSetting="1 day",
                whatToShow="TRADES",
                useRTH=True,
                formatDate=2,
                timeout=self.settings.read_timeout,
            )
            rows = [{"high": b.high, "low": b.low, "close": b.close} for b in bars]
            return money(calc_stop(float(entry), rows)["stop_price"])

        return self.owner.run(operation, timeout=self.settings.read_timeout)

    def submit(self, plan: ApprovedOrderPlan, reference: str) -> BrokerResult:
        async def operation(ib: Any) -> BrokerResult:
            from ib_insync import Contract, Order

            self._account(ib)
            if plan.account != self.settings.account or plan.expires_at <= utcnow():
                raise ValueError("ACCOUNT_MISMATCH_OR_EXPIRED")
            if plan.order_type != "MKT":
                raise ValueError("MKT_ONLY")
            contracts = await asyncio.wait_for(
                ib.qualifyContractsAsync(
                    Contract(conId=plan.contract_id, exchange="SMART")
                ),
                timeout=self.settings.read_timeout,
            )
            if (
                len(contracts) != 1
                or contracts[0].symbol != plan.symbol
                or contracts[0].currency != plan.currency
            ):
                raise ValueError("CONTRACT_CHANGED")
            contract = contracts[0]
            # Persisted reference correlates events even when the response is lost.
            if (
                self._snapshot_revision is not None
                and self._snapshot_revision != self.evidence_revision
            ):
                raise ValueError("ACCOUNT_EVIDENCE_CHANGED")
            parent_id = ib.client.getReqId()
            parent = Order(
                orderId=parent_id,
                action=plan.side,
                totalQuantity=plan.quantity,
                orderType="MKT",
                account=plan.account,
                orderRef=reference,
                transmit=plan.side == "SELL",
            )
            self._inflight.add(reference)
            parent_trade = ib.placeOrder(contract, parent)
            child_trade = None
            if plan.side == "BUY":
                if plan.stop_price is None:
                    raise ValueError("PROTECTIVE_STOP_REQUIRED")
                child = Order(
                    orderId=ib.client.getReqId(),
                    action="SELL",
                    totalQuantity=plan.quantity,
                    orderType="STP",
                    auxPrice=float(plan.stop_price),
                    account=plan.account,
                    parentId=parent_id,
                    orderRef=reference + ":stop",
                    transmit=True,
                )
                # No acknowledgement wait for the untransmitted parent.
                child_trade = ib.placeOrder(contract, child)
            deadline = time.monotonic() + self.settings.acknowledgement_timeout
            while True:
                result = self._result(plan, parent_trade, child_trade)
                if (
                    result.state != ExecutionState.UNKNOWN
                    or time.monotonic() >= deadline
                ):
                    self._inflight.discard(reference)
                    return result
                await asyncio.sleep(0.05)

        # A caller timeout never cancels a possibly transmitted order workflow.
        async def bounded(ib: Any) -> BrokerResult:
            try:
                return await asyncio.wait_for(
                    operation(ib),
                    self.settings.read_timeout + self.settings.acknowledgement_timeout,
                )
            finally:
                self._inflight.discard(reference)

        return self.owner.run(
            bounded,
            timeout=self.settings.read_timeout
            + self.settings.acknowledgement_timeout
            + 1,
            cancel_on_timeout=False,
        )

    @staticmethod
    def _result(plan: ApprovedOrderPlan, parent: Any, stop: Any) -> BrokerResult:
        if (
            parent.order.account != plan.account
            or parent.order.action != plan.side
            or parent.order.orderType != "MKT"
            or money(parent.order.totalQuantity) != plan.quantity
            or parent.contract.conId != plan.contract_id
            or parent.contract.symbol != plan.symbol
            or parent.contract.currency != plan.currency
        ):
            raise ValueError("BROKER_ORDER_IDENTITY_MISMATCH")
        status = parent.orderStatus.status
        states = {
            "Submitted": ExecutionState.ACKNOWLEDGED,
            "PreSubmitted": ExecutionState.ACKNOWLEDGED,
            "Filled": ExecutionState.FILLED,
            "Cancelled": ExecutionState.CANCELLED,
            "ApiCancelled": ExecutionState.CANCELLED,
        }
        state = states.get(status, ExecutionState.UNKNOWN)
        if status == "Inactive" and any(
            getattr(entry, "errorCode", 0) == 201
            for entry in getattr(parent, "log", ())
        ):
            state = ExecutionState.REJECTED
        filled = money(parent.orderStatus.filled)
        if filled != int(filled) or filled < 0:
            raise ValueError("INVALID_FILL_QUANTITY")

        def evidence(trade: Any) -> tuple[tuple[str, int, Decimal, datetime], ...]:
            events = []
            for fill in trade.fills if trade else ():
                execution = fill.execution
                if execution.acctNumber != plan.account:
                    continue
                if (
                    fill.contract.conId != plan.contract_id
                    or execution.orderId != trade.order.orderId
                    or execution.clientId != trade.order.clientId
                ):
                    raise ValueError("BROKER_FILL_IDENTITY_MISMATCH")
                quantity = money(execution.shares)
                if quantity != int(quantity) or quantity <= 0:
                    raise ValueError("INVALID_FILL_QUANTITY")
                events.append(
                    (
                        execution.execId,
                        int(quantity),
                        money(execution.price),
                        timestamp(fill.time),
                    )
                )
            return tuple(events)

        fills = evidence(parent)
        stop_fills = evidence(stop)
        if filled and not fills:
            state = ExecutionState.UNKNOWN
        elif 0 < filled < plan.quantity:
            state = ExecutionState.PARTIAL
        protection = "not_applicable"
        if plan.side == "BUY":
            protection = "unknown"
            if (
                stop is not None
                and stop.order.parentId == parent.order.orderId
                and stop.order.account == plan.account
                and stop.order.action == "SELL"
                and stop.order.orderType == "STP"
                and money(stop.order.totalQuantity) == plan.quantity
                and money(stop.order.auxPrice) == plan.stop_price
                and stop.order.orderRef == parent.order.orderRef + ":stop"
                and stop.contract.conId == plan.contract_id
            ):
                if stop.orderStatus.status in ("PreSubmitted", "Submitted") and money(
                    stop.orderStatus.remaining
                ) == plan.quantity - sum(f[1] for f in stop_fills):
                    protection = "confirmed"
                elif (
                    stop.orderStatus.status == "Filled"
                    and sum(f[1] for f in stop_fills) == plan.quantity
                ):
                    protection = "closed"
                elif (
                    stop.orderStatus.status in ("Cancelled", "ApiCancelled")
                    and filled == plan.quantity
                ):
                    protection = "cancelled"
            if protection == "unknown":
                state = ExecutionState.UNKNOWN
        return BrokerResult(
            state,
            parent.order.orderId,
            parent.order.permId or None,
            stop.order.orderId if stop else None,
            protection,
            int(filled),
            fills=fills,
            stop_fills=stop_fills,
            parent_status=status,
            stop_status=stop.orderStatus.status if stop else None,
        )

    def reconcile(self, plan: ApprovedOrderPlan, reference: str) -> BrokerResult:
        async def operation(ib: Any) -> BrokerResult:
            self._account(ib)
            await ib.reqAllOpenOrdersAsync()
            completed = await ib.reqCompletedOrdersAsync(apiOnly=False)
            fills = await ib.reqExecutionsAsync()
            trades = list(ib.trades()) + list(completed)
            parents = [
                t
                for t in trades
                if t.order.account == plan.account and t.order.orderRef == reference
            ]
            stops = [
                t
                for t in trades
                if t.order.account == plan.account
                and t.order.orderRef == reference + ":stop"
            ]
            parents = list(
                {
                    (t.order.clientId, t.order.orderId, t.order.permId): t
                    for t in parents
                }.values()
            )
            stops = list(
                {
                    (t.order.clientId, t.order.orderId, t.order.permId): t
                    for t in stops
                }.values()
            )
            if len(parents) != 1 or len(stops) > 1:
                return BrokerResult(
                    ExecutionState.UNKNOWN,
                    protection_state="unknown"
                    if plan.side == "BUY"
                    else "not_applicable",
                )
            for trade in parents + stops:
                matching = [
                    f
                    for f in fills
                    if f.execution.acctNumber == plan.account
                    and f.execution.permId == trade.order.permId
                    and trade.order.permId
                    and f.contract.conId == plan.contract_id
                ]
                trade.fills[:] = list(
                    {f.execution.execId: f for f in [*trade.fills, *matching]}.values()
                )
            return self._result(plan, parents[0], stops[0] if stops else None)

        return self.owner.run(operation, timeout=self.settings.read_timeout)

    def reconcile_legacy(self, expected: dict[str, Any]) -> dict[str, Any]:
        """Observe an imported identity; never accept fill assertions from HTTP."""

        async def operation(ib: Any) -> dict[str, Any]:
            self._account(ib)
            await ib.reqAllOpenOrdersAsync()
            completed = await ib.reqCompletedOrdersAsync(apiOnly=False)
            fills = await ib.reqExecutionsAsync()
            candidates = list(ib.trades()) + list(completed)
            matched = []
            for trade in candidates:
                order = trade.order
                if order.account != self.settings.account:
                    continue
                same = (
                    order.permId == expected["permanent_id"]
                    if expected.get("permanent_id")
                    else (
                        order.orderId == expected["order_id"]
                        and order.clientId == expected["client_id"]
                    )
                )
                if same:
                    matched.append(trade)
            unique = {
                (t.order.clientId, t.order.orderId, t.order.permId): t for t in matched
            }
            if len(unique) != 1:
                raise ValueError("LEGACY_BROKER_HISTORY_REQUIRED")
            trade = next(iter(unique.values()))
            order = trade.order
            if (
                trade.contract.symbol != expected["symbol"]
                or order.action != expected["side"]
                or money(order.totalQuantity) != expected["quantity"]
            ):
                raise ValueError("LEGACY_BROKER_IDENTITY_MISMATCH")
            actual = [
                f
                for f in fills
                if f.execution.acctNumber == self.settings.account
                and order.permId
                and f.execution.permId == order.permId
                and f.contract.conId == trade.contract.conId
            ]
            actual = list(
                {f.execution.execId: f for f in [*trade.fills, *actual]}.values()
            )
            quantity = sum((money(f.execution.shares) for f in actual), Decimal(0))
            status = trade.orderStatus.status
            if status not in (
                "Filled",
                "Cancelled",
                "ApiCancelled",
            ) or quantity != money(trade.orderStatus.filled):
                raise ValueError("LEGACY_EXECUTION_UNRESOLVED")
            if status == "Filled" and quantity != expected["quantity"]:
                raise ValueError("LEGACY_FILL_EVIDENCE_INCOMPLETE")
            # Historical BUY records do not reliably preserve their approved
            # protective stop. Require the position to be closed and all linked
            # orders terminal; never manufacture an approved stop retrospectively.
            await ib.reqPositionsAsync()
            if expected["side"] == "BUY" and (
                any(
                    p.account == self.settings.account
                    and p.contract.conId == trade.contract.conId
                    and p.position
                    for p in ib.positions()
                )
                or any(
                    t.order.account == self.settings.account
                    and t.contract.conId == trade.contract.conId
                    for t in ib.openTrades()
                )
            ):
                raise ValueError("LEGACY_PROTECTION_REVIEW_REQUIRED")
            return {
                "account": self.settings.account,
                "verified_at": utcnow().isoformat(),
                "order_id": order.orderId,
                "client_id": order.clientId,
                "permanent_id": order.permId,
                "contract_id": trade.contract.conId,
                "symbol": trade.contract.symbol,
                "side": order.action,
                "status": status,
                "filled_quantity": str(quantity),
                "fills": [
                    {
                        "broker_execution_id": f.execution.execId,
                        "quantity": str(money(f.execution.shares)),
                        "price": str(money(f.execution.price)),
                        "observed_at": timestamp(f.time).isoformat(),
                    }
                    for f in actual
                ],
            }

        return self.owner.run(operation, timeout=self.settings.read_timeout)
