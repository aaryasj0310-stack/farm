"""Tests for P2.0 Dynamic Second Melon Tranche isolation and admission logic."""
import pytest
import sys
import os

# Ensure agent paths are present
AGENT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
for p in [AGENT_DIR] + [os.path.join(AGENT_DIR, s) for s in ("state", "strategy", "execution", "market")]:
    if p not in sys.path:
        sys.path.insert(0, p)

import config
from strategy.second_melon_evaluator import (
    evaluate_second_melon_tranche,
    _melon_market_price,
    _project_melon_batch_revenue,
)


def test_default_flag_is_false():
    """Verify P20_SECOND_MELON_TRANCHE_ENABLED defaults to False."""
    assert config.P20_SECOND_MELON_TRANCHE_ENABLED is False
    assert config.get_p20_second_melon_tranche_enabled() is False


def test_flag_toggle():
    """Verify setter toggles flag cleanly."""
    try:
        config.set_p20_second_melon_tranche_enabled(True)
        assert config.P20_SECOND_MELON_TRANCHE_ENABLED is True
        assert config.get_p20_second_melon_tranche_enabled() is True

        config.set_p20_second_melon_tranche_enabled(False)
        assert config.P20_SECOND_MELON_TRANCHE_ENABLED is False
        assert config.get_p20_second_melon_tranche_enabled() is False
    finally:
        config.set_p20_second_melon_tranche_enabled(False)


def test_melon_pricing_math():
    """Verify exact engine quadratic pricing for Melon."""
    # At I0 (10,000): price = 250
    assert _melon_market_price(10000) == 250.0

    # At I0 + 72: diff = 72. amp = 3.60 * 250 / 90000 = 0.01. diff^2 = 5184. amp * 5184 = 51.84.
    # Price = 250 - 51.84 = 198.16 -> rounded = 198.
    assert _melon_market_price(10072) == 198.0

    # Batch revenue for 72 units sold starting at I0
    rev, avg_p = _project_melon_batch_revenue(10000, 72)
    assert 198.0 <= avg_p <= 250.0
    assert rev > 72 * 198.0


def test_evaluator_outside_window():
    """Verify evaluator rejects days outside Days 10-12."""
    config.set_p20_second_melon_tranche_enabled(True)
    try:
        for d in (0, 3, 9, 13, 15, 20):
            k, diag = evaluate_second_melon_tranche(
                day=d, hour=0, farm=None, private=None, market=None, forecast=None,
                committed_counts={}, empty_tiles=[(0, 0)], available_money=10000.0,
            )
            assert k == 0
            assert "outside_window" in diag["decision_reason"]
    finally:
        config.set_p20_second_melon_tranche_enabled(False)


def test_evaluator_disabled_returns_zero():
    """Verify evaluator returns 0 immediately when flag is False."""
    config.set_p20_second_melon_tranche_enabled(False)
    k, diag = evaluate_second_melon_tranche(
        day=10, hour=0, farm=None, private=None, market=None, forecast=None,
        committed_counts={}, empty_tiles=[(0, 0)], available_money=10000.0,
    )
    assert k == 0
    assert diag["decision_reason"] == "p20_disabled"
