"""Local agent simulation commands; broker modes are not exposed."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from trading_agent.agent.controller import AgentController
from trading_agent.agent.demo import run_demo
from trading_agent.agent.store import AgentStore
from trading_agent.cli import register


@register("agent")
def configure(sub: argparse._SubParsersAction[Any]) -> None:
    commands = sub.add_parser(
        "agent", help="Persistent autonomous simulation"
    ).add_subparsers(required=True)
    init = commands.add_parser("init")
    init.add_argument("--database", type=Path, required=True)
    init.add_argument("--mandate", type=Path, required=True)
    init.set_defaults(handler=initialize)
    run = commands.add_parser(
        "run",
        help="Consume a bounded JSONL observation stream; exact replay is idempotent",
    )
    run.add_argument("--database", type=Path, required=True)
    run.add_argument("--events", type=Path, required=True)
    run.add_argument("--max-events", type=int, default=1000)
    run.set_defaults(handler=consume)
    status = commands.add_parser("status")
    status.add_argument("--database", type=Path, required=True)
    status.set_defaults(handler=lambda a: AgentStore(a.database).report())
    recover = commands.add_parser("recover")
    recover.add_argument("--database", type=Path, required=True)
    recover.set_defaults(
        handler=lambda a: {
            "recovered": AgentController(AgentStore(a.database)).recover()
        }
    )
    pause = commands.add_parser("pause")
    pause.add_argument("--database", type=Path, required=True)
    pause.add_argument("--reason", required=True)
    pause.set_defaults(handler=change_pause)
    resume = commands.add_parser(
        "resume", help="Clear the local simulation pause; does not enable broker orders"
    )
    resume.add_argument("--database", type=Path, required=True)
    resume.set_defaults(handler=change_pause, reason=None)
    demo = commands.add_parser(
        "demo", help="Synthetic no-trade, entry, restart, hold and exit demonstration"
    )
    demo.add_argument("--workspace", type=Path, required=True)
    demo.set_defaults(handler=lambda a: run_demo(a.workspace))


def initialize(args: argparse.Namespace) -> dict[str, Any]:
    config = json.loads(args.mandate.read_text(encoding="utf-8"))
    return AgentStore.create(args.database, config).report()


def change_pause(args: argparse.Namespace) -> dict[str, Any]:
    store = AgentStore(args.database)
    store.pause(args.reason)
    return {"mode": "simulation", "pause_reason": args.reason}


def consume(args: argparse.Namespace) -> dict[str, Any]:
    if not 1 <= args.max_events <= 100000:
        raise ValueError("MAX_EVENTS_OUT_OF_RANGE")
    controller = AgentController(AgentStore(args.database))
    processed = 0
    replayed = 0
    last: str | None = None
    # Opening the source first avoids recovering pending work when the requested
    # input path itself is invalid. Earlier completed lines survive a later error.
    with args.events.open(encoding="utf-8") as source:
        recovered = controller.recover()
        while processed < args.max_events:
            line = source.readline(5 * 1024 * 1024 + 1)
            if not line:
                break
            if len(line) > 5 * 1024 * 1024:
                raise ValueError("OBSERVATION_LINE_TOO_LARGE")
            if not line.strip():
                continue
            event_id = controller.prepare(json.loads(line))
            with controller.store.connection() as db:
                completed = (
                    db.execute(
                        "SELECT status FROM cycles WHERE event_id=?", (event_id,)
                    ).fetchone()[0]
                    == "completed"
                )
            result = controller.complete(event_id)
            if completed:
                replayed += 1
            else:
                processed += 1
            last = result["event_id"]
    return {
        "mode": "simulation",
        "processed": processed,
        "replayed": replayed,
        "recovered": len(recovered),
        "last_event_id": last,
    }
