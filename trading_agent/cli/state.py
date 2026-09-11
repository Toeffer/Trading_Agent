from __future__ import annotations
import argparse
from pathlib import Path
import shutil
from typing import Any

from trading_agent.cli import register
from trading_agent.migration import migrate_legacy
from trading_agent.ownership import ServiceLock
from trading_agent.persistence import ExecutionStore
from trading_agent.domain import canonical


def migrate(args: argparse.Namespace) -> dict[str, Any]:
    # Taking the same OS lock proves this service instance is stopped.
    lock = ServiceLock(args.database.parent / "service.lock")
    lock.acquire()
    try:
        if args.backup.resolve().is_relative_to(args.source.resolve()):
            raise ValueError("Backup must be outside the legacy source directory")
        if args.backup.exists():
            raise ValueError("Backup must be a new directory")
        shutil.copytree(args.source, args.backup)
        args.backup.chmod(0o700)
        store = ExecutionStore(args.database)
        store.backup(args.backup / "pre-migration.sqlite3")
        return migrate_legacy(args.source, store, args.account)
    finally:
        lock.close()


@register("state")
def configure(sub: argparse._SubParsersAction[Any]) -> None:
    group = sub.add_parser("state").add_subparsers(required=True)
    command = group.add_parser(
        "migrate", help="Offline migration after stopping old and new services"
    )
    command.add_argument("--source", type=Path, required=True)
    command.add_argument("--backup", type=Path, required=True)
    command.add_argument("--database", type=Path, required=True)
    command.add_argument("--account", required=True)
    command.set_defaults(handler=migrate)
    snapshots = group.add_parser(
        "export-snapshots",
        help="Export timestamped risk inputs for deterministic replay",
    )
    snapshots.add_argument("--database", type=Path, required=True)
    snapshots.add_argument("--output", type=Path, required=True)
    snapshots.set_defaults(handler=export_snapshots)


def export_snapshots(args: argparse.Namespace) -> dict[str, Any]:
    if not args.database.is_file() or args.output.exists():
        raise ValueError("Existing database and new output path required")
    snapshots = ExecutionStore(args.database).decision_snapshots()
    with args.output.open("x", encoding="utf-8", newline="\n") as stream:
        for snapshot in snapshots:
            stream.write(canonical(snapshot) + "\n")
    return {"snapshots": len(snapshots), "output": str(args.output)}
