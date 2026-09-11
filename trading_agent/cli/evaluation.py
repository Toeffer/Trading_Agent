from __future__ import annotations
import argparse
from pathlib import Path
from typing import Any

from trading_agent.cli import register
from trading_agent.replay import preregistration, replay_file
from trading_agent.acceptance import evidence_report
from trading_agent.persistence import ExecutionStore


@register("evaluation")
def configure(sub: argparse._SubParsersAction[Any]) -> None:
    group = sub.add_parser("evaluation").add_subparsers(required=True)
    replay = group.add_parser("replay")
    replay.add_argument("source", type=Path)
    replay.set_defaults(handler=lambda a: {"results": replay_file(a.source)})
    prereg = group.add_parser("preregister")
    prereg.add_argument("--release", required=True)
    prereg.add_argument("--configuration-hash", required=True)
    prereg.set_defaults(
        handler=lambda a: preregistration(a.release, a.configuration_hash)
    )
    acceptance = group.add_parser(
        "acceptance-evidence",
        help="Check broker event sequence; does not verify host or relocking",
    )
    acceptance.add_argument("--database", type=Path, required=True)
    acceptance.add_argument("--buy-execution", required=True)
    acceptance.add_argument("--sell-execution", required=True)
    acceptance.set_defaults(handler=acceptance_report)


def acceptance_report(args: argparse.Namespace) -> dict[str, Any]:
    if not args.database.is_file():
        raise ValueError("Existing execution database required")
    return evidence_report(
        ExecutionStore(args.database), args.buy_execution, args.sell_execution
    )
