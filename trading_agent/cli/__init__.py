"""Command groups and shared JSON output for the modular application."""

from __future__ import annotations
import argparse
from collections.abc import Callable
from typing import Any

from trading_agent.domain import canonical

REGISTRY: dict[str, Callable[[argparse._SubParsersAction[Any]], None]] = {}


def register(
    name: str,
) -> Callable[
    [Callable[[argparse._SubParsersAction[Any]], None]],
    Callable[[argparse._SubParsersAction[Any]], None],
]:
    def decorator(
        function: Callable[[argparse._SubParsersAction[Any]], None],
    ) -> Callable[[argparse._SubParsersAction[Any]], None]:
        if name in REGISTRY:
            raise ValueError("Duplicate command group")
        REGISTRY[name] = function
        return function

    return decorator


def main(argv: list[str] | None = None) -> int:
    from trading_agent.cli import evaluation, state, host  # noqa: F401

    parser = argparse.ArgumentParser(
        description="Durable paper execution operator tools"
    )
    sub = parser.add_subparsers(dest="group", required=True)
    for configure in REGISTRY.values():
        configure(sub)
    args = parser.parse_args(argv)
    try:
        result = args.handler(args)
    except (ValueError, OSError, RuntimeError) as exc:
        print(
            canonical({"ok": False, "error": type(exc).__name__, "message": str(exc)})
        )
        return 1
    print(canonical(result))
    return 0
