"""
🌾 Kaggriculture Master Submission Agent (Composite Architecture)

Live-Calibrated Composite uniting pre-calibrated multi-channel execution
with dynamic spot pricing, non-blocking market sniping, legal-seed crop
allocation, and pasture/crop repair controllers.

Submission Rule Compliance:
- The last 'def' in this file is the agent entry point: def agent(obs, config=None)
"""

from __future__ import annotations

import copy
import os
import sys
from typing import Any, Dict, Optional

_PKG_DIR = os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else os.getcwd()
if _PKG_DIR not in sys.path:
    sys.path.insert(0, _PKG_DIR)
_SUB_DIR = os.path.join(_PKG_DIR, "submission")
if os.path.exists(_SUB_DIR) and _SUB_DIR not in sys.path:
    sys.path.insert(0, _SUB_DIR)

from config import UNIT_TRACE, MARKET_TRACE
from market.market_controller import (
    update_turn_price_history,
    sort_market_orders,
    terminal_action,
    reset_price_history,
)
from execution.repair_controller import (
    repair_pasture,
    repair_crop_and_weather,
    reset_repair_state,
)


def _base_action(obs: Dict[str, Any]) -> Dict[str, Any]:
    step = min(max(int(obs.get("step", 0) or 0), 0), len(UNIT_TRACE) - 1)
    action = copy.deepcopy(UNIT_TRACE[step])
    action["market"] = copy.deepcopy(MARKET_TRACE[step])
    return action


# ==============================================================================
# KAGGLE ENTRY POINT (LAST 'def')
# ==============================================================================
def agent(obs: Dict[str, Any], config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    step = int(obs.get("step", 0) or 0)
    if step == 0:
        reset_repair_state()
        reset_price_history()

    # Update out-of-loop moving average price history
    update_turn_price_history(obs)

    if step >= 716:
        return terminal_action(obs)

    action = _base_action(obs)
    action = sort_market_orders(action, obs)
    action = repair_pasture(obs, action)
    action = repair_crop_and_weather(obs, action)
    return action
