"""Dynamic market pricing, priority sorting, and terminal liquidation controller."""

from typing import Any, Dict, List, Optional, Tuple
from config import PRODUCTS, SELL_TIE_PRIORITY, NON_SELL_PRIORITY

_PRICE_HISTORY: List[float] = []


def reset_price_history():
    global _PRICE_HISTORY
    _PRICE_HISTORY = []


def update_turn_price_history(obs: Dict[str, Any]) -> None:
    global _PRICE_HISTORY
    prices = ((obs.get("market", {}) or {}).get("prices", {}) or {})
    wheat_p = float(prices.get("WHEAT", 24.0) or 24.0)
    _PRICE_HISTORY.append(wheat_p)
    if len(_PRICE_HISTORY) > 20:
        _PRICE_HISTORY.pop(0)


def sort_market_orders(action: Dict[str, Any], obs: Dict[str, Any]) -> Dict[str, Any]:
    step = int(obs.get("step", 0) or 0)
    if not (300 <= step < 716):
        return action
    orders = list(action.get("market", []) or [])[:10]
    prices = ((obs.get("market", {}) or {}).get("prices", {}) or {})
    private = obs.get("private", {}) or {}
    shed = private.get("shed", {}) or {}

    total_shed = sum(int(v or 0) for v in shed.values())
    fill_ratio = min(total_shed / 500.0, 1.0)

    sma = sum(_PRICE_HISTORY) / len(_PRICE_HISTORY) if _PRICE_HISTORY else 24.0
    res_floor = max(22.0, sma * 1.05) * max(0.60, 1.0 - (0.10 * fill_ratio))

    sells = []
    others = []
    for index, order in enumerate(orders):
        if order and order[0] == "SELL" and len(order) >= 3:
            item = str(order[1])
            quantity = max(0, int(order[2] or 0))
            price = max(0, int(prices.get(item, 0) or 0))

            bonus_weight = 1.30 if price >= res_floor else 1.0
            score = -(price * quantity * bonus_weight)
            sells.append((score, -price, -quantity, -SELL_TIE_PRIORITY.get(item, 0), index, order))
        else:
            op = str(order[0]) if order else ""
            others.append((NON_SELL_PRIORITY.get(op, 99), index, order))

    sells.sort()
    others.sort()
    action["market"] = [x[-1] for x in sells] + [x[-1] for x in others]
    return action


def best_terminal_item(inventory: Dict[str, Any], prices: Dict[str, Any]) -> Optional[Tuple[int, int, int, int, str]]:
    choices = []
    for item, quantity in (inventory or {}).items():
        quantity = int(quantity or 0)
        if item not in PRODUCTS or quantity <= 0:
            continue
        price = int(prices.get(item, 0) or 0)
        choices.append((price * quantity, price, quantity, SELL_TIE_PRIORITY.get(item, 0), item))
    return max(choices, default=None)


def terminal_action(obs: Dict[str, Any]) -> Dict[str, Any]:
    private = obs.get("private", {}) or {}
    inventories = private.get("inventories", []) or []
    shed = private.get("shed", {}) or {}
    prices = ((obs.get("market", {}) or {}).get("prices", {}) or {})
    player = int(obs.get("player", 0) or 0)
    farms = obs.get("farms", []) or []
    farm = farms[player] if 0 <= player < len(farms) else {}
    hand_count = len(farm.get("hands", []) or [])

    placed: Dict[str, int] = {}
    farmer = ["PASS"]
    if inventories:
        choice = best_terminal_item(inventories[0], prices)
        if choice is not None:
            _, _, quantity, _, item = choice
            farmer = ["PLACE", item, quantity]
            placed[item] = placed.get(item, 0) + quantity

    hands = []
    for index in range(hand_count):
        inv = inventories[index + 1] if index + 1 < len(inventories) else {}
        choice = best_terminal_item(inv, prices)
        if choice is None:
            hands.append(["PASS"])
        else:
            _, _, quantity, _, item = choice
            hands.append(["PLACE", item, quantity])
            placed[item] = placed.get(item, 0) + quantity

    totals: Dict[str, int] = {}
    for item in PRODUCTS:
        quantity = int(shed.get(item, 0) or 0) + int(placed.get(item, 0) or 0)
        if quantity > 0:
            totals[item] = quantity

    ordered = sorted(
        totals,
        key=lambda item: (
            int(prices.get(item, 0) or 0) * totals[item],
            int(prices.get(item, 0) or 0),
            totals[item],
            SELL_TIE_PRIORITY.get(item, 0),
        ),
        reverse=True,
    )
    return {
        "farmer": farmer,
        "hands": hands,
        "market": [["SELL", item, totals[item]] for item in ordered[:10]],
    }
