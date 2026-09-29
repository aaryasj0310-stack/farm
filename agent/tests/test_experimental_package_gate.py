"""Small gate regression: protected seeds and unsafe terminal outcomes fail closed."""
import importlib.util
from pathlib import Path

import pytest


def test_package_gate_rejects_unsafe_evidence():
    path = Path(__file__).parents[2] / "scripts/verify_experimental_package.py"
    spec = importlib.util.spec_from_file_location("experimental_package_gate", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    good = dict(statuses=["DONE", "DONE"], steps=720, errors=[],
                fallbacks=[], max_market_orders=10, escapes=[], unfed=[])
    assert module.engine_gate(good)
    for key, value in [("statuses", ["ERROR", "DONE"]), ("steps", 2),
                       ("fallbacks", [1]), ("escapes", [1]),
                       ("max_market_orders", 11)]:
        assert not module.engine_gate(dict(good, **{key: value}))
    with pytest.raises(ValueError):
        module.validate_seed(98001)
    module.validate_seed(11)
