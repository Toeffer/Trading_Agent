"""Read-only compatibility for historical broker diagnostic endpoints."""

import asyncio
import inspect
from typing import Any

from trading_agent.broker_loop import BrokerLoop


class ReadOnlyBrokerProxy:
    """Legacy diagnostics use the owner's loop; order mutation is unavailable."""

    _allowed = frozenset(
        {
            "isConnected",
            "managedAccounts",
            "positions",
            "portfolio",
            "accountValues",
            "accountSummary",
            "trades",
            "openTrades",
            "fills",
            "reqContractDetails",
            "qualifyContracts",
            "reqHistoricalData",
            "reqTickers",
            "reqMarketDataType",
            "reqMktData",
            "cancelMktData",
            "reqPositions",
            "reqAllOpenOrders",
            "sleep",
            "connect",
            "disconnect",
        }
    )
    _async = {
        "connect",
        "accountSummary",
        "reqContractDetails",
        "qualifyContracts",
        "reqHistoricalData",
        "reqTickers",
        "reqPositions",
        "reqAllOpenOrders",
    }

    def __init__(self, owner: BrokerLoop):
        self.owner = owner

    def __getattr__(self, name: str) -> Any:
        if name not in self._allowed:
            raise AttributeError(f"Legacy broker access prohibited: {name}")

        def invoke(*args: Any, **kwargs: Any) -> Any:
            async def operation(ib: Any) -> Any:
                if name == "sleep":
                    return await asyncio.sleep(*args)
                target = getattr(ib, name + "Async" if name in self._async else name)
                value = target(*args, **kwargs)
                return await value if inspect.isawaitable(value) else value

            try:
                return self.owner.run(operation, timeout=8)
            except RuntimeError:
                if name == "isConnected":
                    return False
                raise

        return invoke
