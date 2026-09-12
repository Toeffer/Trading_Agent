"""Rehearse migrations on a new disposable copy, without broker imports."""

from contextlib import closing
from pathlib import Path
import sqlite3
from typing import Any

from trading_agent.persistence import ExecutionStore


def rehearse(source: Path, workspace: Path) -> dict[str, Any]:
    if not source.is_file() or workspace.exists():
        raise ValueError(
            "Existing source database and new rehearsal directory required"
        )
    workspace.mkdir(mode=0o700, parents=True, exist_ok=False)
    backup = workspace / "source-backup.sqlite3"
    candidate = workspace / "candidate.sqlite3"
    ExecutionStore.backup_existing(source, backup)
    ExecutionStore.backup_existing(backup, candidate)
    with closing(
        sqlite3.connect(backup.resolve().as_uri() + "?mode=ro", uri=True)
    ) as db:
        source_version = db.execute("PRAGMA user_version").fetchone()[0]
        original_executions = dict(
            db.execute("SELECT execution_id,approval_id FROM executions")
        )
        original_fills = sorted(db.execute("SELECT * FROM fills"))
    migrated = ExecutionStore(candidate)
    migrated.startup()
    with migrated.connection() as db:
        integrity = db.execute("PRAGMA integrity_check").fetchone()[0]
        foreign_keys = list(db.execute("PRAGMA foreign_key_check"))
        identities_preserved = (
            dict(db.execute("SELECT execution_id,approval_id FROM executions"))
            == original_executions
        )
        fills_preserved = (
            sorted(tuple(row) for row in db.execute("SELECT * FROM fills"))
            == original_fills
        )
        unused = db.execute(
            "SELECT COUNT(*) FROM approvals WHERE status IN ('pending','approved')"
        ).fetchone()[0]
    migrated.export(workspace / "exports")
    passed = (
        integrity == "ok"
        and not foreign_keys
        and identities_preserved
        and fills_preserved
        and unused == 0
    )
    return {
        "schema_version": 1,
        "rehearsal_passed": passed,
        "source_schema": source_version,
        "candidate_schema": 3,
        "integrity": integrity,
        "foreign_key_errors": len(foreign_keys),
        "execution_identities_preserved": identities_preserved,
        "fills_preserved": fills_preserved,
        "unused_approvals": unused,
        "workspace": str(workspace),
        "source_opened_readonly": True,
        "broker_contacted": False,
        "deployment_accepted": False,
        "recovery_policy": "Never restore this copy over authoritative state after transmission.",
    }
