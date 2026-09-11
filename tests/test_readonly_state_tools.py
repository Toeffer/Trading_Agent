import sqlite3
from types import SimpleNamespace

import pytest

from trading_agent.persistence import ExecutionStore, StateConflict
from trading_agent.cli.state import export_snapshots, upgrade_database


def test_snapshot_export_does_not_upgrade_an_old_database(tmp_path):
    path = tmp_path / "old.sqlite3"
    ExecutionStore(path)
    with sqlite3.connect(path) as db:
        db.execute("PRAGMA user_version=2")
    with pytest.raises(StateConflict, match="MIGRATION_REQUIRED"):
        export_snapshots(SimpleNamespace(database=path, output=tmp_path / "snapshots.jsonl"))
    with sqlite3.connect(path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 2


def test_upgrade_backup_preserves_preupgrade_schema(tmp_path):
    path, backup = tmp_path / "old.sqlite3", tmp_path / "backup.sqlite3"
    ExecutionStore(path)
    with sqlite3.connect(path) as db:
        db.execute("PRAGMA user_version=2")
    assert upgrade_database(SimpleNamespace(database=path, backup=backup))["reconciliation_required"]
    with sqlite3.connect(backup) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 2
    with sqlite3.connect(path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 3


def test_readonly_handle_cannot_mutate_execution_state(tmp_path):
    path = tmp_path / "state.sqlite3"
    ExecutionStore(path)
    store = ExecutionStore.open_readonly(path)
    with pytest.raises(StateConflict, match="READ_ONLY_STORE"):
        store.startup()
