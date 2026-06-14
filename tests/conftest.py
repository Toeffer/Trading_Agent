"""Pytest configuration for P7 heartbeat tests."""


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "integration: live heartbeat invocation (skipped by default)"
    )
