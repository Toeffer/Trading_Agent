from dataclasses import replace

import pytest

from trading_agent.runtime import Runtime
from trading_agent.settings import Settings
from trading_agent import legacy_guard
from test_execution_application import RULES


def test_explicit_startup_owns_loop_and_clears_compatibility_binding(tmp_path, monkeypatch):
    monkeypatch.setattr(Runtime, "load_rules", lambda self: RULES)
    settings = Settings(account="PAPER_TEST", state_dir=tmp_path / "state")
    runtime = Runtime(settings)
    runtime.start()
    try:
        assert legacy_guard._execution_service is runtime.service
        assert runtime.owner.run(lambda ib: connected(ib)) is False
        competing = Runtime(settings)
        with pytest.raises(RuntimeError, match="ALREADY_RUNNING"):
            competing.start()
    finally:
        runtime.close()
    assert legacy_guard._execution_service is None
    assert legacy_guard._proposal_loader is None


async def connected(ib):
    return ib.isConnected()


def test_configuration_identity_changes_with_account_and_never_exposes_token():
    settings = Settings(account="PAPER_TEST", token_hash="a" * 64)
    assert "token_hash" not in settings.public_identity()
    assert settings.public_identity()["configuration_hash"] != replace(settings, account="OTHER").public_identity()["configuration_hash"]
