"""Behavioral contracts for autonomous local decisions and durable simulation."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from decimal import Decimal
import json
import sqlite3

import pytest

from trading_agent.agent.contracts import Mandate, Observation
from trading_agent.agent.controller import AgentController
from trading_agent.agent.demo import demo_inputs, run_demo
from trading_agent.agent.reasoning import StrategyReasoner
from trading_agent.agent.store import AgentStore
from trading_agent.cli import main
from trading_agent.domain import canonical


@pytest.fixture
def inputs():
    return demo_inputs()


def agent(tmp_path, config, reasoner=None):
    return AgentController(AgentStore.create(tmp_path / "agent.db", config), reasoner)


def test_full_lifecycle_reconciles_costs_fx_and_memory(tmp_path, inputs):
    config, events = inputs
    controller = agent(tmp_path, config)
    results = [controller.process(event) for event in events]
    assert results[0]["fills"] == []
    assert results[2]["fills"] == []
    entry, exit_fill = results[1]["fills"][0], results[3]["fills"][0]
    assert entry["side"] == "BUY" and exit_fill["side"] == "SELL"
    assert entry["quantity"] == exit_fill["quantity"] == 5
    assert entry["price"] == "100.0500"
    assert exit_fill["price"] == "102.9485"
    expected = (Decimal("102.9485") - Decimal("100.0500")) * 5 / Decimal(
        "1.1"
    ) - Decimal(2) / Decimal("1.1")
    assert abs(Decimal(exit_fill["realized_pnl_base"]) - expected) < Decimal("1e-20")
    report = controller.store.report()
    assert abs(
        Decimal(report["portfolio"]["cash"]) - Decimal(10000) - expected
    ) < Decimal("1e-20")
    assert report["portfolio"]["positions"] == {}
    assert len(report["cycles"]) == 4 and len(report["fills"]) == 2
    assert report["pending"] == []
    assert report["reconciliation"]["ok"]
    assert results[1]["after"]["positions"]["AAPL"]["thesis"]
    assert results[1]["reasoning"]["tools"]["regime"]["regime"] == "RISK_ON"


def test_restart_reuses_recorded_decision_without_reasoning_again(tmp_path, inputs):
    config, events = inputs
    controller = agent(tmp_path, config)
    controller.prepare(events[1])

    class MustNotReason(StrategyReasoner):
        def decide(self, *args):
            pytest.fail("Recovery must use the durable decision")

    restarted = AgentController(AgentStore(tmp_path / "agent.db"), MustNotReason())
    recovered = restarted.recover()
    assert len(recovered) == 1 and len(recovered[0]["fills"]) == 1
    assert restarted.recover() == []
    assert restarted.process(events[1]) == recovered[0]
    assert len(restarted.store.report()["fills"]) == 1


def test_duplicate_delivery_and_concurrent_controllers_have_one_fill(tmp_path, inputs):
    config, events = inputs
    first = agent(tmp_path, config)
    second = AgentController(AgentStore(tmp_path / "agent.db"))
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(c.process, events[1]) for c in (first, second)]
        results = [f.result(timeout=15) for f in futures]
    assert results[0] == results[1]
    assert len(first.store.report()["fills"]) == 1


def test_conflicting_id_and_old_time_do_not_change_portfolio(tmp_path, inputs):
    config, events = inputs
    controller = agent(tmp_path, config)
    controller.process(events[1])
    before = controller.store.report()
    conflict = deepcopy(events[1])
    conflict["quotes"]["AAPL"]["bid"] = "99.80"
    with pytest.raises(ValueError, match="EVENT_ID_CONTENT_CONFLICT"):
        controller.process(conflict)
    with pytest.raises(ValueError, match="OUT_OF_ORDER_OBSERVATION"):
        controller.process(events[0])
    assert controller.store.report() == before


def test_pending_cycle_blocks_new_observations(tmp_path, inputs):
    config, events = inputs
    controller = agent(tmp_path, config)
    controller.prepare(events[1])
    with pytest.raises(RuntimeError, match="RECOVERY"):
        controller.prepare(events[2])
    assert controller.store.report()["fills"] == []


def test_fill_storage_failure_rolls_back_cash_holdings_and_cycle(tmp_path, inputs):
    config, events = inputs
    controller = agent(tmp_path, config)
    controller.prepare(events[1])
    with controller.store.connection(write=True) as db:
        db.execute(
            "CREATE TRIGGER fail_fill BEFORE INSERT ON fills BEGIN SELECT RAISE(ABORT,'disk fixture'); END"
        )
    before = controller.store.report()
    with pytest.raises(sqlite3.IntegrityError, match="disk fixture"):
        controller.complete(events[1]["event_id"])
    assert controller.store.report() == before
    with controller.store.connection(write=True) as db:
        db.execute("DROP TRIGGER fail_fill")
    assert len(controller.recover()[0]["fills"]) == 1


def test_pause_survives_restart_and_prevents_pending_execution(tmp_path, inputs):
    config, events = inputs
    controller = agent(tmp_path, config)
    controller.prepare(events[1])
    controller.store.pause("operator pause")
    restarted = AgentController(AgentStore(tmp_path / "agent.db"))
    with pytest.raises(RuntimeError, match="AGENT_PAUSED"):
        restarted.recover()
    assert restarted.store.report()["fills"] == []
    restarted.store.pause(None)
    assert len(restarted.recover()[0]["fills"]) == 1


def test_shared_risk_daily_limit_rejects_discretionary_exit(tmp_path, inputs):
    config, events = inputs
    config["risk"]["max_trades_per_day"] = 1
    controller = agent(tmp_path, config)
    controller.process(events[1])
    result = controller.process(events[3])
    assert result["fills"] == []
    exit_outcome = next(o for o in result["outcomes"] if o["symbol"] == "AAPL")
    assert exit_outcome["rejection"] == "DAILY_CAPACITY_EXCEEDED"
    assert result["after"]["positions"]["AAPL"]["protection"] == "simulated_stop"


def test_stop_executes_at_gap_price_despite_daily_cap_and_reasoner_hold(
    tmp_path, inputs
):
    config, events = inputs
    config["risk"]["max_trades_per_day"] = 1
    controller = agent(tmp_path, config)
    controller.process(events[1])
    event = deepcopy(events[2])
    event["quotes"]["AAPL"].update(bid="90", ask="90.10")

    class HoldReasoner(StrategyReasoner):
        def decide(self, *args):
            result = super().decide(*args)
            for d in result["decisions"]:
                d.update(action="HOLD", protective=False)
            return result

    controller.reasoner = HoldReasoner()
    result = controller.process(event)
    fill = result["fills"][0]
    assert fill["role"] == "stop" and fill["price"] == "89.9550"
    assert result["after"]["positions"] == {}
    assert result["after"]["daily_count"] == 1


def test_same_sector_and_portfolio_budgets_use_sequential_holdings(tmp_path, inputs):
    config, events = inputs
    config["instruments"]["JPM"]["sector"] = "TECH"

    class BothEnter(StrategyReasoner):
        def decide(self, *args):
            result = super().decide(*args)
            for d in result["decisions"]:
                d.update(action="ENTER", protective=False)
            return result

    controller = agent(tmp_path, config, BothEnter())
    result = controller.process(events[1])
    assert len(result["fills"]) == 1
    assert any(
        o.get("rejection") == "SECTOR_CAPACITY_EXCEEDED" for o in result["outcomes"]
    )


def test_small_account_cannot_create_fractional_or_unfunded_position(tmp_path, inputs):
    config, events = inputs
    config["initial_cash"] = "10"
    result = agent(tmp_path, config).process(events[1])
    assert result["fills"] == []
    assert any(
        o.get("rejection") == "NO_AFFORDABLE_QUANTITY" for o in result["outcomes"]
    )
    assert result["after"]["cash"] == "10"


def test_expired_mandate_does_not_start_cycle(tmp_path, inputs):
    config, events = inputs
    config["expires_at"] = events[1]["at"]
    controller = agent(tmp_path, config)
    with pytest.raises(ValueError, match="OUTSIDE_MANDATE_WINDOW"):
        controller.process(events[1])
    assert controller.store.report()["cycles"] == []


@pytest.mark.parametrize(
    "fault",
    [
        "quote_future",
        "quote_stale",
        "crossed",
        "future_bar",
        "availability",
        "unordered",
        "duplicate_day",
        "nan",
        "missing_symbol",
        "account",
        "timestamp_type",
        "misaligned",
        "opinion_future",
        "opinion_quantity",
    ],
)
def test_bad_observations_fail_before_durable_decisions(tmp_path, inputs, fault):
    config, events = inputs
    event = deepcopy(events[0])
    quote = event["quotes"]["AAPL"]
    bar = quote["bars"][-1]
    if fault == "quote_future":
        quote["observed_at"] = "2026-09-11T15:00:00Z"
    elif fault == "quote_stale":
        quote["observed_at"] = "2026-09-11T13:00:00Z"
    elif fault == "crossed":
        quote["bid"] = "101"
    elif fault == "future_bar":
        bar.update(ended_at="2026-09-12T20:00:00Z", available_at="2026-09-12T20:05:00Z")
    elif fault == "availability":
        bar["available_at"] = "2026-09-11T15:00:00Z"
    elif fault == "unordered":
        quote["bars"].reverse()
    elif fault == "duplicate_day":
        bar.update(
            ended_at=quote["bars"][-2]["ended_at"],
            available_at=quote["bars"][-2]["available_at"],
        )
    elif fault == "nan":
        quote["ask"] = "NaN"
    elif fault == "missing_symbol":
        del event["quotes"]["JPM"]
    elif fault == "account":
        event["account"] = "another-account"
    elif fault == "timestamp_type":
        event["at"] = 123
    elif fault == "misaligned":
        quote["bars"].pop()
    elif fault == "opinion_future":
        event["opinions"]["AAPL"]["observed_at"] = "2026-09-11T15:00:00Z"
    elif fault == "opinion_quantity":
        event["opinions"]["AAPL"]["quantity"] = 1000000
    controller = agent(tmp_path, config)
    with pytest.raises(ValueError):
        controller.process(event)
    assert controller.store.report()["cycles"] == []


@pytest.mark.parametrize("mode", ["live", "paper", "shadow", True])
def test_only_local_simulation_can_be_initialized(tmp_path, inputs, mode):
    config, _ = inputs
    config["mode"] = mode
    with pytest.raises(ValueError, match="ONLY_SIMULATION"):
        AgentStore.create(tmp_path / "agent.db", config)
    assert not (tmp_path / "agent.db").exists()


def test_wrong_database_is_never_migrated_or_overwritten(tmp_path, inputs):
    config, _ = inputs
    path = tmp_path / "execution.db"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE existing(value TEXT)")
    before = path.read_bytes()
    with pytest.raises(ValueError, match="NOT_AN_AGENT_DATABASE"):
        AgentStore(path)
    with pytest.raises(FileExistsError):
        AgentStore.create(path, config)
    assert path.read_bytes() == before


@pytest.mark.parametrize("column", ["state", "decision", "observation"])
def test_recovery_detects_inconsistent_saved_evidence(tmp_path, inputs, column):
    config, events = inputs
    controller = agent(tmp_path, config)
    controller.prepare(events[1])
    with controller.store.connection(write=True) as db:
        if column == "state":
            state = json.loads(db.execute("SELECT state FROM agent").fetchone()[0])
            state["cash"] = "9000"
            db.execute("UPDATE agent SET state=?", (canonical(state),))
        else:
            # Column comes only from the fixed test parameter list above.
            raw = json.loads(db.execute(f"SELECT {column} FROM cycles").fetchone()[0])
            raw["unexpected"] = True
            db.execute(f"UPDATE cycles SET {column}=?", (canonical(raw),))
    with pytest.raises(RuntimeError, match="CHANGED|HASH_MISMATCH"):
        controller.recover()
    assert controller.store.report()["fills"] == []


def test_insufficient_history_records_no_trade(tmp_path, inputs):
    config, events = inputs
    event = events[1]
    event["reference_bars"] = event["reference_bars"][-10:]
    for quote in event["quotes"].values():
        quote["bars"] = quote["bars"][-10:]
    result = agent(tmp_path, config).process(event)
    assert result["fills"] == []
    assert all(o["reason"] == "INSUFFICIENT_STRATEGY_DATA" for o in result["outcomes"])


def test_input_and_portfolio_are_not_mutated_by_reasoner(inputs):
    config, events = inputs
    original = deepcopy(events[1])
    mandate = Mandate.parse(config)
    StrategyReasoner().decide(
        Observation.parse(events[1], mandate), mandate, {"positions": {}}
    )
    assert events[1] == original


def test_cli_can_resume_bounded_file_without_replaying_prefix_forever(
    tmp_path, inputs, capsys
):
    config, events = inputs
    mandate, source, database = (
        tmp_path / "mandate.json",
        tmp_path / "events.jsonl",
        tmp_path / "agent.db",
    )
    mandate.write_text(canonical(config), encoding="utf-8")
    source.write_text("\n".join(canonical(e) for e in events), encoding="utf-8")
    assert (
        main(["agent", "init", "--database", str(database), "--mandate", str(mandate)])
        == 0
    )
    capsys.readouterr()
    command = [
        "agent",
        "run",
        "--database",
        str(database),
        "--events",
        str(source),
        "--max-events",
        "2",
    ]
    assert main(command) == 0
    assert json.loads(capsys.readouterr().out)["processed"] == 2
    assert main(command) == 0
    second = json.loads(capsys.readouterr().out)
    assert second["processed"] == 2 and second["replayed"] == 2
    assert main(command) == 0
    third = json.loads(capsys.readouterr().out)
    assert third["processed"] == 0 and third["replayed"] == 4
    assert len(AgentStore(database).report()["fills"]) == 2


def test_demo_is_repeatable_and_refuses_existing_output(tmp_path):
    result = run_demo(tmp_path / "demo")
    assert result["cycles"] == 4 and result["fills"] == 2
    assert result["restart_exercised"] and result["synthetic_data"]
    with pytest.raises(FileExistsError):
        run_demo(tmp_path / "demo")


@pytest.mark.parametrize("damage", ["cash", "position", "missing_fill"])
def test_ledger_drift_blocks_new_decisions_and_is_visible_in_status(
    tmp_path, inputs, damage
):
    config, events = inputs
    controller = agent(tmp_path, config)
    controller.process(events[1])
    with controller.store.connection(write=True) as db:
        if damage == "missing_fill":
            db.execute("DELETE FROM fills")
        else:
            state = json.loads(db.execute("SELECT state FROM agent").fetchone()[0])
            if damage == "cash":
                state["cash"] = "10000"
            else:
                state["positions"]["AAPL"]["quantity"] = 6
            db.execute("UPDATE agent SET state=?", (canonical(state),))
    assert not controller.store.report()["reconciliation"]["ok"]
    with pytest.raises(RuntimeError, match="PORTFOLIO_LEDGER_MISMATCH"):
        controller.process(events[2])
    assert len(controller.store.report()["cycles"]) == 1


def test_missing_database_cli_returns_structured_failure_without_creating_it(
    tmp_path, capsys
):
    path = tmp_path / "absent.db"
    assert main(["agent", "status", "--database", str(path)]) == 1
    assert json.loads(capsys.readouterr().out)["ok"] is False
    assert not path.exists()
