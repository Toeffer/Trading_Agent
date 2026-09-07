"""Pytest configuration for IBKR bridge tests.

Marker policy:
  - unit (default): always collected and run in CI
  - integration: live heartbeat/network calls — opt-in, excluded by default
  - live: requires live IBKR connection — opt-in, excluded by default
  - host: needs the production host layout (~/.openclaw rules, ~/agents/
    ibkr-bridge, user systemd units) or host-speed timing. Auto-skipped on
    any machine without that layout so `pytest tests/` is green anywhere;
    runs unchanged on the host. Force with `-m host` or IBKR_HOST_TESTS=1.

Default CI invocation:
  pytest -m "not integration and not live" -q tests/
"""

import os
from pathlib import Path

import pytest


def _host_layout_present() -> bool:
    home = Path.home()
    return (
        (home / ".openclaw" / "risk-rules" / "paper-trading-rules.yaml").exists()
        and (home / "agents" / "ibkr-bridge").exists()
    )


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
    config.addinivalue_line(
        "markers",
        "slow: slow tests (doctor, full rehearsal — skipped in fast CI)"
    )
    config.addinivalue_line(
        "markers",
        "host: needs the production host layout or host timing "
        "(auto-skipped elsewhere; force with -m host or IBKR_HOST_TESTS=1)"
    )


def pytest_collection_modifyitems(config, items):
    """Default CI mode: skip integration and live markers.

    Tests marked @pytest.mark.integration or @pytest.mark.live are
    automatically skipped unless explicitly selected with -m.
    This ensures CI never accidentally hits live IBKR or network endpoints.

    Tests marked @pytest.mark.host are skipped when the production host
    layout is absent (unless selected with -m host or IBKR_HOST_TESTS=1).
    """
    markers_to_skip = {"integration", "live"}
    selected = set(config.getoption("-m", "").split())
    host_ok = (
        "host" in selected
        or bool(os.environ.get("IBKR_HOST_TESTS"))
        or _host_layout_present()
    )
    # If user explicitly selected a marker, don't auto-skip it
    for item in items:
        item_markers = {m.name for m in item.iter_markers()}
        for marker in markers_to_skip:
            if marker in item_markers and marker not in selected:
                item.add_marker(pytest.mark.skip(
                    reason=f"{marker} tests are excluded by default. Use -m {marker} to opt in."
                ))
        if "host" in item_markers and not host_ok:
            item.add_marker(pytest.mark.skip(
                reason="needs the production host layout (~/.openclaw, ~/agents/ibkr-bridge); "
                       "absent here. Force with -m host or IBKR_HOST_TESTS=1."
            ))
