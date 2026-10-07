"""Operational tests require explicit opt-in, regardless of host layout."""

import pytest

def pytest_addoption(parser):
    for marker in ("integration", "live", "host", "acceptance"):
        parser.addoption("--run-" + marker, action="store_true", default=False,
                         help="Explicitly enable " + marker + " checks")


def pytest_configure(config):
    for marker in ("portable", "unit", "integration", "live", "host", "acceptance", "slow"):
        config.addinivalue_line("markers", marker + ": explicit test classification")


def pytest_collection_modifyitems(config, items):
    operational = {"integration", "live", "host", "acceptance"}
    for item in items:
        marked = {m.name for m in item.iter_markers()}
        if not marked.intersection(operational):
            item.add_marker(pytest.mark.portable)
        for marker in operational.intersection(marked):
            if not config.getoption("--run-" + marker):
                item.add_marker(pytest.mark.skip(reason="Use --run-" + marker + " to explicitly opt in"))
