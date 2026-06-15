"""Pytest configuration for IBKR bridge tests.

Marker policy:
  - unit (default): always collected and run in CI
  - integration: live heartbeat/network calls — opt-in, excluded by default
  - live: requires live IBKR connection — opt-in, excluded by default

Default CI invocation:
  pytest -m "not integration and not live" -q tests/
"""

import pytest


def pytest_configure(config):
    # Register custom markers
    config.addinivalue_line(
        "markers",
        "integration: live heartbeat invocation (skipped by default)"
    )
    config.addinivalue_line(
        "markers",
        "live: requires live IBKR connection (skipped by default)"
    )


def pytest_collection_modifyitems(config, items):
    """Default CI mode: skip integration and live markers.

    Tests marked @pytest.mark.integration or @pytest.mark.live are
    automatically skipped unless explicitly selected with -m.
    This ensures CI never accidentally hits live IBKR or network endpoints.
    """
    markers_to_skip = {"integration", "live"}
    selected = set(config.getoption("-m", "").split())
    # If user explicitly selected a marker, don't auto-skip it
    for item in items:
        item_markers = {m.name for m in item.iter_markers()}
        for marker in markers_to_skip:
            if marker in item_markers and marker not in selected:
                item.add_marker(pytest.mark.skip(
                    reason=f"{marker} tests are excluded by default. Use -m {marker} to opt in."
                ))
