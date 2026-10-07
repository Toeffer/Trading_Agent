from __future__ import annotations
import argparse
from pathlib import Path
from typing import Any

from trading_agent.cli import register
from trading_agent.host_verification import verify


@register("host")
def configure(sub: argparse._SubParsersAction[Any]) -> None:
    command = sub.add_parser(
        "host", help="Read-only checks on the actual Linux deployment"
    )
    command.add_argument("--release", type=Path, required=True)
    command.add_argument("--state", type=Path, default=Path("/var/lib/ibkr-bridge"))
    command.add_argument("--config", type=Path, default=Path("/etc/ibkr-bridge"))
    command.add_argument("--gateway-port", type=int, default=4002)
    command.add_argument("--advisory-user", required=True)
    command.set_defaults(
        handler=lambda a: verify(
            a.release, a.state, a.config, a.gateway_port, a.advisory_user
        )
    )
