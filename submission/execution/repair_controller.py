"""Pasture weed repair, crop replanting, and weather hedging controller."""

import copy
from typing import Any, Dict
from config import UNIT_TRACE
from state.observation_parser import tile_at

_PENDING_PASTURE = None
_FARMER_SHIFT_END = None
_PENDING_PLANT = None
_PENDING_WATER = None
_WATER_SHIFT = None
_REPAIR_ACTIVATED = False


def reset_repair_state():
    global _PENDING_PASTURE, _FARMER_SHIFT_END
    global _PENDING_PLANT, _PENDING_WATER, _WATER_SHIFT, _REPAIR_ACTIVATED
    _PENDING_PASTURE = None
    _FARMER_SHIFT_END = None
    _PENDING_PLANT = None
    _PENDING_WATER = None
    _WATER_SHIFT = None
    _REPAIR_ACTIVATED = False


def repair_pasture(obs: Dict[str, Any], action: Dict[str, Any]) -> Dict[str, Any]:
    global _PENDING_PASTURE, _FARMER_SHIFT_END
    step = int(obs.get("step", 0) or 0)
    player = int(obs.get("player", 0) or 0)
    farms = obs.get("farms", []) or []
    if not (0 <= player < len(farms)):
        return action
    farm = farms[player] or {}
    hands = farm.get("hands", []) or []
    hand_actions = list(action.get("hands", []) or [])

    if _FARMER_SHIFT_END is not None:
        if step <= _FARMER_SHIFT_END:
            previous = max(0, step - 1)
            action["farmer"] = copy.deepcopy(UNIT_TRACE[previous]["farmer"])
        else:
            _FARMER_SHIFT_END = None

    if _PENDING_PASTURE is not None:
        channel, actor, position, expected_step = _PENDING_PASTURE
        if step == expected_step:
            if channel == "farmer":
                current = farm.get("farmer")
                if list(current or []) == position and tile_at(farm, current) is None:
                    action["farmer"] = ["BUILD_PASTURE"]
            elif 0 <= actor < len(hands) and actor < len(hand_actions):
                if list(hands[actor]) == position and tile_at(farm, hands[actor]) is None:
                    hand_actions[actor] = ["BUILD_PASTURE"]
        _PENDING_PASTURE = None

    farmer_position = farm.get("farmer")
    farmer_tile = tile_at(farm, farmer_position)
    if action.get("farmer") == ["BUILD_PASTURE"] and isinstance(farmer_tile, dict) and farmer_tile.get("kind") == "WEED":
        action["farmer"] = ["DIG"]
        if step % 24 >= 20:
            _FARMER_SHIFT_END = (step // 24 + 1) * 24 - 1
        _PENDING_PASTURE = ("farmer", None, list(farmer_position), step + 1)

    for actor, requested in enumerate(hand_actions[:len(hands)]):
        if _PENDING_PASTURE is not None:
            break
        if requested != ["BUILD_PASTURE"]:
            continue
        if isinstance(tile_at(farm, hands[actor]), dict) and tile_at(farm, hands[actor]).get("kind") == "WEED":
            hand_actions[actor] = ["DIG"]
            _PENDING_PASTURE = ("hands", actor, list(hands[actor]), step + 1)
            break
    action["hands"] = hand_actions
    return action


def repair_crop_and_weather(obs: Dict[str, Any], action: Dict[str, Any]) -> Dict[str, Any]:
    global _PENDING_PLANT, _PENDING_WATER, _WATER_SHIFT, _REPAIR_ACTIVATED
    step = int(obs.get("step", 0) or 0)
    player = int(obs.get("player", 0) or 0)
    farms = obs.get("farms", []) or []
    if not (0 <= player < len(farms)):
        return action
    farm = farms[player] or {}
    positions = farm.get("hands", []) or []
    hand_actions = list(action.get("hands", []) or [])
    seeds = ((obs.get("private", {}) or {}).get("seeds", {}) or {})

    if _WATER_SHIFT is not None:
        actor, end_step = _WATER_SHIFT
        if step <= end_step and actor < len(hand_actions):
            previous = max(0, step - 1)
            prev_hands = UNIT_TRACE[previous]["hands"]
            if actor < len(prev_hands):
                hand_actions[actor] = copy.deepcopy(prev_hands[actor])
        else:
            _WATER_SHIFT = None

    if _PENDING_WATER is not None:
        position, planter, expected_step = _PENDING_WATER
        if step == expected_step and isinstance(tile_at(farm, position), dict):
            actor = next((i for i, p in enumerate(positions) if i != planter and i < len(hand_actions) and list(p) == position), planter if planter < len(hand_actions) else None)
            if actor is not None:
                hand_actions[actor] = ["WATER"]
                _WATER_SHIFT = (actor, (step // 24 + 1) * 24 - 1)
        _PENDING_WATER = None

    if _PENDING_PLANT is not None:
        actor, crop, position, expected_step = _PENDING_PLANT
        if step == expected_step and actor < len(positions) and actor < len(hand_actions) and list(positions[actor]) == position and tile_at(farm, positions[actor]) is None:
            if int(seeds.get(crop, 0) or 0) > 0:
                hand_actions[actor] = ["PLANT", crop]
                _PENDING_WATER = (list(position), actor, step + 1)
        _PENDING_PLANT = None

    if step >= 636:
        for actor, requested in enumerate(hand_actions[:len(positions)]):
            if requested and requested[0] == "PLANT":
                tile = tile_at(farm, positions[actor])
                if isinstance(tile, dict) and tile.get("kind") == "WEED":
                    hand_actions[actor] = ["DIG"]
                    _PENDING_PLANT = (actor, "WHEAT", list(positions[actor]), step + 1)
                    _REPAIR_ACTIVATED = True
                    break
    action["hands"] = hand_actions
    return action
