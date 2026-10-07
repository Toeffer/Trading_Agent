"""Synthetic, reproducible agent demonstration; these are not market observations."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from trading_agent.agent.controller import AgentController
from trading_agent.agent.store import AgentStore
from trading_agent.domain import canonical


def demo_inputs() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    config: dict[str, Any] = {
        "schema_version": 1,
        "mode": "simulation",
        "account": "SIM_DEMO",
        "base_currency": "EUR",
        "quote_currency": "USD",
        "initial_cash": "10000",
        "starts_at": "2026-09-01T00:00:00Z",
        "expires_at": "2026-10-01T00:00:00Z",
        "instruments": {
            "AAPL": {"contract_id": 1, "sector": "TECH"},
            "JPM": {"contract_id": 2, "sector": "FINANCE"},
        },
        "risk": {
            "position_fraction": "0.05",
            "trade_risk_fraction": "0.0025",
            "exposure_fraction": "0.30",
            "max_trades_per_day": 2,
            "max_positions_per_sector": 1,
            "daily_loss_fraction": "0.01",
            "weekly_loss_fraction": "0.03",
        },
        "strategy": {
            "version": "agent-trend-v1",
            "stop_fraction": "0.05",
            "max_holding_days": 20,
            "max_bar_age_hours": 96,
        },
        "costs": {"slippage_bps": "5", "commission_per_order_quote": "1"},
    }
    days: list[datetime] = []
    cursor = datetime(2026, 9, 10, 20, tzinfo=timezone.utc)
    while len(days) < 270:
        if cursor.weekday() < 5:
            days.append(cursor)
        cursor -= timedelta(days=1)
    days.reverse()

    def bars(start: float, slope: float) -> list[dict[str, Any]]:
        series = []
        for i, day in enumerate(days):
            close = round(start + slope * i + (i % 5) * 0.02, 4)
            series.append(
                {
                    "ended_at": day.isoformat(),
                    "available_at": (day + timedelta(minutes=5)).isoformat(),
                    "open": close,
                    "high": close + 1,
                    "low": close - 1,
                    "close": close,
                    "volume": 1000000,
                }
            )
        return series

    def opinion(action: str, at: str) -> dict[str, Any]:
        return {
            "action": action,
            "thesis": "Synthetic fixture demonstrating recorded reasoning.",
            "invalidation": "Synthetic exit event closes the demonstration position.",
            "sources": ["fixture://agent-demo"],
            "model": "synthetic-fixture",
            "observed_at": at,
        }

    event: dict[str, Any] = {
        "schema_version": 1,
        "account": "SIM_DEMO",
        "base_to_quote": "1.1",
        "reference_bars": bars(350, 0.30),
        "quotes": {
            "AAPL": {"bid": "99.90", "ask": "100", "bars": bars(65, 0.13)},
            "JPM": {"bid": "99.90", "ask": "100", "bars": bars(85, 0.04)},
        },
    }
    events: list[dict[str, Any]] = []
    for i in range(4):
        item = deepcopy(event)
        item["event_id"] = f"demo-{i + 1}"
        item["at"] = datetime(2026, 9, 11, 14, i, tzinfo=timezone.utc).isoformat()
        for quote in item["quotes"].values():
            quote["observed_at"] = item["at"]
        if i == 0:
            item["opinions"] = {"AAPL": opinion("HOLD", item["at"])}
        if i == 3:
            item["opinions"] = {"AAPL": opinion("EXIT", item["at"])}
            item["quotes"]["AAPL"].update(bid="103", ask="103.10")
        events.append(item)
    return config, events


def run_demo(workspace: Path) -> dict[str, Any]:
    workspace.mkdir()  # Refuse an existing directory, preserving previous evidence.
    config, events = demo_inputs()
    (workspace / "mandate.json").write_text(canonical(config) + "\n", encoding="utf-8")
    (workspace / "observations.jsonl").write_text(
        "\n".join(canonical(e) for e in events) + "\n", encoding="utf-8"
    )
    database = workspace / "agent.sqlite3"
    controller = AgentController(AgentStore.create(database, config))
    controller.process(events[0])
    controller.prepare(events[1])
    # Reconstruct all objects after the decision is durable and before execution.
    restarted = AgentController(AgentStore(database))
    restarted.recover()
    restarted.process(events[2])
    restarted.process(events[3])
    restarted.process(events[1])  # Exact replay must not create another fill.
    report = restarted.store.report()
    report["synthetic_data"] = True
    report["restart_exercised"] = True
    (workspace / "report.json").write_text(canonical(report) + "\n", encoding="utf-8")
    return {
        "mode": "simulation",
        "synthetic_data": True,
        "restart_exercised": True,
        "cycles": len(report["cycles"]),
        "fills": len(report["fills"]),
        "portfolio": report["portfolio"],
        "report": str((workspace / "report.json").resolve()),
    }
