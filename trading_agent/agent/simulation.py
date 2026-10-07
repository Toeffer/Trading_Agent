"""Atomic local fills and portfolio accounting, using the shared risk evaluator.

No broker adapter, approval token, socket or order endpoint is used here.
The legacy snapshot's 'paper'/'realtime' vocabulary is used only inside the
pure risk evaluator. External results and fill identities are simulation-only.
"""

from copy import deepcopy
from datetime import timedelta
from decimal import Decimal, ROUND_FLOOR
from typing import Any

from trading_agent.agent.contracts import Mandate, Observation, fields, label
from trading_agent.domain import (
    ApprovedOrderPlan,
    PortfolioSnapshot,
    Position,
    content_hash,
    money,
)
from trading_agent.risk import RiskRejected, evaluate


def equity(state: dict[str, Any], observation: Observation) -> Decimal:
    quotes = observation.raw["quotes"]
    fx = money(observation.raw["base_to_quote"])
    return money(state["cash"]) + sum(
        (
            p["quantity"] * money(quotes[s]["bid"]) / fx
            for s, p in state["positions"].items()
        ),
        Decimal(0),
    )


def validate_decision(
    decision: dict[str, Any], observation: Observation, mandate: Mandate
) -> None:
    fields(
        decision, {"version", "observed_at", "tools", "budget_fraction", "decisions"}
    )
    if decision["version"] != mandate.raw["strategy"]["version"]:
        raise ValueError("REASONER_VERSION_MISMATCH")
    if decision["observed_at"] != observation.at.isoformat():
        raise ValueError("DECISION_TIME_MISMATCH")
    if not 0 <= money(decision["budget_fraction"]) <= mandate.policy.max_exposure_pct:
        raise ValueError("INVALID_ADVISORY_BUDGET")
    items = decision["decisions"]
    if not isinstance(items, list) or len(items) != len(mandate.instruments):
        raise ValueError("ONE_DECISION_PER_SYMBOL_REQUIRED")
    seen: set[str] = set()
    for item in items:
        fields(
            item,
            {
                "symbol",
                "action",
                "reason",
                "protective",
                "thesis",
                "invalidation",
                "opinion",
                "sma20",
            },
        )
        symbol = item["symbol"]
        if symbol not in mandate.instruments or symbol in seen:
            raise ValueError("INVALID_DECISION_SYMBOL")
        seen.add(symbol)
        if (
            item["action"] not in ("ENTER", "HOLD", "EXIT")
            or type(item["protective"]) is not bool
        ):
            raise ValueError("INVALID_DECISION_ACTION")
        for key in ("reason", "thesis", "invalidation"):
            label(item[key])


def apply_cycle(
    state: dict[str, Any],
    observation: Observation,
    mandate: Mandate,
    decision: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    validate_decision(decision, observation, mandate)
    state = deepcopy(state)
    at = observation.at
    if not mandate.starts_at <= at < mandate.expires_at:
        raise ValueError("OUTSIDE_MANDATE_WINDOW")
    day = at.date().isoformat()
    iso = at.isocalendar()
    week = f"{iso.year}-{iso.week:02}"
    # Use the prior observation's equity as the new period baseline, so an
    # overnight gap is not erased by resetting to the first new-day quote.
    if state["day"] != day:
        state.update(day=day, daily_count=0, day_anchor=state["equity"])
    if state["week"] != week:
        state.update(week=week, week_anchor=state["equity"])
    before = {
        "cash": state["cash"],
        "equity": str(equity(state, observation)),
        "positions": deepcopy(state["positions"]),
    }
    fills: list[dict[str, Any]] = []
    outcomes: list[dict[str, Any]] = []
    for item in decision["decisions"]:
        item = deepcopy(item)
        position = state["positions"].get(item["symbol"])
        # Protection belongs to execution, independent of the reasoning provider.
        if position and money(
            observation.raw["quotes"][item["symbol"]]["bid"]
        ) <= money(position["stop_price"]):
            item.update(action="EXIT", protective=True, reason="PROTECTIVE_STOP")
        outcome = deepcopy(item)
        if item["action"] == "HOLD":
            outcome["status"] = "held"
        else:
            try:
                fill = execute_intent(state, observation, mandate, decision, item)
                fills.append(fill)
                outcome.update(
                    status="simulated_fill", execution_id=fill["execution_id"]
                )
            except RiskRejected as exc:
                outcome.update(status="rejected", rejection=str(exc))
        outcomes.append(outcome)
    state.update(equity=str(equity(state, observation)), last_at=at.isoformat())
    result = {
        "mode": "simulation",
        "event_id": observation.identity,
        "mandate_hash": mandate.identity,
        "reasoning": decision,
        "outcomes": outcomes,
        "fills": fills,
        "before": before,
        "after": deepcopy(state),
    }
    return state, result, fills


def execute_intent(
    state: dict[str, Any],
    observation: Observation,
    mandate: Mandate,
    decision: dict[str, Any],
    item: dict[str, Any],
) -> dict[str, Any]:
    symbol = item["symbol"]
    quote = observation.raw["quotes"][symbol]
    fx = money(observation.raw["base_to_quote"])
    bid, ask = money(quote["bid"]), money(quote["ask"])
    at = observation.at
    instrument = mandate.instruments[symbol]
    nl = equity(state, observation)
    position = state["positions"].get(symbol)
    buy = item["action"] == "ENTER"
    slip = money(mandate.raw["costs"]["slippage_bps"]) / 10000
    price = ask * (1 + slip) if buy else bid * (1 - slip)
    fee = money(mandate.raw["costs"]["commission_per_order_quote"]) / fx
    stop = (
        price * (1 - money(mandate.raw["strategy"]["stop_fraction"])) if buy else None
    )
    positions = tuple(
        Position(
            s,
            p["quantity"],
            p["quantity"] * money(observation.raw["quotes"][s]["bid"]) / fx,
            mandate.instruments[s]["sector"],
        )
        for s, p in state["positions"].items()
    )
    protective = item["protective"]
    if protective and (buy or not position or bid > money(position["stop_price"])):
        raise RiskRejected("INVALID_PROTECTIVE_EXIT")
    if buy:
        if position:
            raise RiskRejected("POSITION_ALREADY_OPEN")
        assert stop is not None
        # Size at adverse fill price and include fees in the cash bound.
        exposure = sum((p.market_value_base for p in positions), Decimal(0))
        budget = max(Decimal(0), nl * money(decision["budget_fraction"]) - exposure)
        quote_budget = (
            min(
                nl * mandate.policy.max_position_pct,
                budget,
                max(Decimal(0), money(state["cash"]) - fee),
            )
            * fx
        )
        quantity = int(
            min(
                quote_budget / price,
                nl * mandate.policy.max_risk_pct * fx / (price - stop),
            ).to_integral_value(rounding=ROUND_FLOOR)
        )
        if quantity <= 0:
            raise RiskRejected("NO_AFFORDABLE_QUANTITY")
    else:
        if not position:
            raise RiskRejected("NO_POSITION_TO_CLOSE")
        quantity = position["quantity"]
    if not protective:
        # Simulation supports atomic full close, including removal of its local
        # stop. A future broker adapter must reconcile cancellation separately.
        snapshot = PortfolioSnapshot(
            mandate.account,
            "paper",
            mandate.raw["base_currency"],
            mandate.raw["quote_currency"],
            nl,
            fx,
            at,
            at,
            "realtime",
            price if not buy else bid,
            price if buy else ask,
            positions,
            (),
            state["daily_count"],
            nl <= money(state["day_anchor"]) * (1 - mandate.policy.daily_loss_pct),
            nl <= money(state["week_anchor"]) * (1 - mandate.policy.weekly_loss_pct),
            instrument["contract_id"],
        )
        plan = ApprovedOrderPlan(
            mandate.account,
            symbol,
            instrument["contract_id"],
            mandate.raw["quote_currency"],
            "BUY" if buy else "SELL",
            quantity,
            "MKT",
            price,
            stop,
            content_hash(item),
            mandate.identity,
            at,
            at + timedelta(seconds=300),
            at,
        )
        evaluate(plan, snapshot, mandate.policy, [], now=at)
    value = quantity * price / fx
    realized: Decimal | None = None
    if buy:
        state["cash"] = str(money(state["cash"]) - value - fee)
        state["positions"][symbol] = {
            "quantity": quantity,
            "entry_price": str(price),
            "stop_price": str(stop),
            "entry_cost_base": str(value + fee),
            "opened_at": at.isoformat(),
            "entry_event_id": observation.identity,
            "thesis": item["thesis"],
            "invalidation": item["invalidation"],
            "protection": "simulated_stop",
        }
    else:
        assert position is not None
        realized = value - fee - money(position["entry_cost_base"])
        state["cash"] = str(money(state["cash"]) + value - fee)
        del state["positions"][symbol]
    if not protective:
        state["daily_count"] += 1
    return {
        "execution_id": "sim-"
        + content_hash(
            [mandate.identity, observation.identity, symbol, item["action"]]
        ),
        "event_id": observation.identity,
        "symbol": symbol,
        "side": "BUY" if buy else "SELL",
        "quantity": quantity,
        "price": str(price),
        "commission_base": str(fee),
        "base_to_quote": str(fx),
        "executed_at": at.isoformat(),
        "realized_pnl_base": str(realized) if realized is not None else None,
        "role": "stop" if protective else "parent",
        "mode": "simulation",
    }
