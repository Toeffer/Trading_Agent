"""Integration contracts for research commands and isolated simulator transport."""

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


@pytest.mark.parametrize("command,options,handler,status", [
    ("hermes-research", ["--data", "fixture-bars"], "_run_hermes_research", "DRAFT_READY"),
    ("hermes-review", ["--run-id", "fixture-run"], "_run_hermes_review", "REVIEW_READY"),
])
def test_registered_cli_dispatches_advisory_commands(monkeypatch, capsys, command, options, handler, status):
    from trading_agent.cli import operator_registry, operator_workflow_helpers
    calls = []

    def run(args):
        calls.append(args)
        return {"status": status, "advisory_only": True}

    monkeypatch.setattr(operator_workflow_helpers, handler, run)
    monkeypatch.setattr(sys, "argv", ["ibkr-operator", command, *options, "--json"])
    with pytest.raises(SystemExit) as result:
        operator_registry.main()
    assert result.value.code == 0
    assert len(calls) == 1 and calls[0].command == command
    assert json.loads(capsys.readouterr().out)["status"] == status


def test_test_transport_allows_its_ephemeral_listener_and_blocks_other_destinations(tmp_path):
    root = Path(__file__).resolve().parents[1]
    env = {**os.environ, "IBKR_TEST_ISOLATION": "1", "IBKR_TEST_ROOT": str(tmp_path),
           "IBKR_TEST_LOOPBACK_PORTS": "", "PYTHONPATH": str(root / "tests/isolation")}
    script = '''
import socket
with socket.socket() as listener:
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    with socket.create_connection(listener.getsockname(), timeout=1):
        connection, _ = listener.accept()
        connection.close()
for address in [("127.0.0.1", 8790), ("192.0.2.1", 4002)]:
    with socket.socket() as client:
        client.settimeout(0.1)
        for method in (client.connect, client.connect_ex):
            try:
                method(address)
            except OSError as exc:
                assert str(exc) == "Network disabled in portable tests", repr(exc)
            else:
                raise AssertionError("Unregistered destination was allowed")
'''
    result = subprocess.run([sys.executable, "-c", script], env=env, capture_output=True,
                            text=True, timeout=10)
    assert result.returncode == 0, result.stderr
