import os
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_PKG = os.path.dirname(_HERE)
sys.path.insert(0, _PKG)
for _sub in ("state", "strategy", "execution", "market"):
    sys.path.insert(0, os.path.join(_PKG, _sub))


# These assertions remain unchanged and run by default and at production release.
PRODUCTION_SYNC_TESTS = {
    ("test_animal_service_economics.py", "test_19_agent_and_submission_sync"),
    ("test_market_slot_sequencing.py", "test_19_agent_and_submission_remain_synchronized"),
    ("test_same_turn_deposit_sell.py", "test_17_agent_and_submission_synchronized"),
    ("test_same_turn_sale_financing.py", "test_21_agent_and_submission_synchronized"),
    ("test_same_turn_shed_relay.py", "test_22_agent_and_submission_synchronized"),
}


def pytest_addoption(parser):
    parser.addoption("--verification-gate", choices=("all", "experimental", "production"), default="all")


def pytest_configure(config):
    config.addinivalue_line("markers", "production_release: canonical source/submission release requirements")
    config.addinivalue_line("markers", "protected_artifact: protected production integrity, required in both gates")


def pytest_collection_modifyitems(config, items):
    selected, deselected = [], []
    gate = config.getoption("--verification-gate")
    for item in items:
        if ((item.path.name, item.name) in PRODUCTION_SYNC_TESTS
                or item.path.name == "test_submission_package.py"):
            item.add_marker(pytest.mark.production_release)
        production = item.get_closest_marker("production_release") is not None
        protected = item.get_closest_marker("protected_artifact") is not None
        keep = (gate == "all" or (gate == "experimental" and not production)
                or (gate == "production" and (production or protected)))
        (selected if keep else deselected).append(item)
    items[:] = selected
    if deselected:
        config.hook.pytest_deselected(items=deselected)
