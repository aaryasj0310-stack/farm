"""Authoritative, non-invasive engine transaction & operational instrumentation.

Captures ground-truth execution events at the engine boundary without modifying
game state, RNG, agent decisions, or order execution.
"""
from __future__ import annotations

import copy
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

import kaggle_environments.envs.kaggriculture.kaggriculture as kengine


PRODUCT_BASE_PRICES = {
    "WHEAT": 25.0,
    "CARROT": 35.0,
    "TOMATO": 60.0,
    "STRAWBERRY": 120.0,
    "MELON": 250.0,
    "EGG": 50.0,
    "MILK": 160.0,
    "WOOL": 200.0,
    "FERTILIZER": 100.0,
}

SEED_PRICES = {
    "WHEAT": 10,
    "CARROT": 20,
    "TOMATO": 50,
    "STRAWBERRY": 100,
    "MELON": 80,
}

ANIMAL_PRICES = {
    "GOOSE": 300,
    "COW": 400,
    "SHEEP": 500,
}


def get_quadrant(x: int, y: int, board_size: int = 10) -> str:
    half = board_size // 2
    return ("N" if y < half else "S") + ("W" if x < half else "E")


class CensusSession:
    """Non-invasive observational session wrapping kaggriculture engine functions."""

    def __init__(self, seat: int):
        self.seat = seat
        self.our_farm: Optional[Dict[str, Any]] = None
        self.our_private: Optional[Dict[str, Any]] = None

        self.current_step = 0
        self.current_day = 0
        self.current_hour = 0
        self.current_market_prices: Dict[str, float] = dict(PRODUCT_BASE_PRICES)

        # Domain A: Capital Allocation
        self.hourly_cash: List[Dict[str, Any]] = []
        self.executed_transactions: List[Dict[str, Any]] = []
        self.rejected_transactions: List[Dict[str, Any]] = []
        self.hires: List[Dict[str, Any]] = []
        self.land_purchases: List[Dict[str, Any]] = []
        self.emitted_market_orders: List[Dict[str, Any]] = []

        # Domain B: Productive Land Utilization
        self.quadrant_unlock_step: Dict[str, Optional[int]] = {
            "NW": 0, "NE": None, "SW": None, "SE": None
        }
        self.daily_quadrant_census: Dict[int, Dict[str, Dict[str, int]]] = {}

        # Domain C: Crop Portfolio Economics
        self.crop_plantings: List[Dict[str, Any]] = []
        self.crop_waterings: List[Dict[str, Any]] = []
        self.crop_fertilizations: List[Dict[str, Any]] = []
        self.crop_harvests: List[Dict[str, Any]] = []

        # Domain D: Worker Throughput
        self.worker_actions: List[Dict[str, Any]] = []

        # Domain E: Livestock Economics
        self.animal_placements: List[Dict[str, Any]] = []
        self.animal_feeds: List[Dict[str, Any]] = []
        self.animal_cares: List[Dict[str, Any]] = []
        self.fertilizer_collections: List[Dict[str, Any]] = []
        self.animal_harvests: List[Dict[str, Any]] = []
        self.animal_daily_snapshots: List[Dict[str, Any]] = []

        # Storage & Discards
        self.midnight_discards: List[Dict[str, Any]] = []

        # Environment & interpreter tracking
        self.env: Optional[Any] = None
        self._orig_interpreter = kengine.interpreter
        self._orig_env_interpreter: Optional[Any] = None

        # Original function pointers
        self._orig_commit_unit = kengine._commit_unit
        self._orig_do_hire = kengine._do_hire
        self._orig_do_buy_land = kengine._do_buy_land
        self._orig_apply_unit_action = kengine._apply_unit_action
        self._orig_drop_inventories_to_shed = kengine._drop_inventories_to_shed

    def attach_env_state(self, env_state: Any):
        """Update our active farm & private references for the current turn."""
        if hasattr(env_state[self.seat], "observation"):
            obs = env_state[self.seat].observation
            if hasattr(obs, "farms") and len(obs.farms) > self.seat:
                self.our_farm = obs.farms[self.seat]
            if hasattr(obs, "private"):
                self.our_private = obs.private
            if hasattr(obs, "day"):
                self.current_day = obs.day
            if hasattr(obs, "hour"):
                self.current_hour = obs.hour
            self.current_step = getattr(obs, "step", self.current_day * 24 + self.current_hour)
            if hasattr(obs, "market") and "prices" in obs.market:
                self.current_market_prices = dict(obs.market["prices"])

    def record_commit(self, op: str, item: str, price: float, success: bool):
        rec = {
            "step": self.current_step,
            "day": self.current_day,
            "hour": self.current_hour,
            "op": op,
            "item": item,
            "price": price,
            "success": success,
        }
        if success:
            self.executed_transactions.append(rec)
        else:
            self.rejected_transactions.append(rec)

    def record_hire(self, cost: float, total_hands: int):
        self.hires.append({
            "step": self.current_step,
            "day": self.current_day,
            "hour": self.current_hour,
            "cost": cost,
            "total_hands": total_hands,
        })

    def record_land_buy(self, cost: float, quadrant: str):
        self.land_purchases.append({
            "step": self.current_step,
            "day": self.current_day,
            "hour": self.current_hour,
            "cost": cost,
            "quadrant": quadrant,
        })
        if self.quadrant_unlock_step[quadrant] is None:
            self.quadrant_unlock_step[quadrant] = self.current_step

    def record_worker_action(
        self,
        unit_idx: int,
        action: List[Any],
        pos: Tuple[int, int],
        quadrant: str,
        success: bool,
        detail: Dict[str, Any],
    ):
        op = action[0] if action else "PASS"
        self.worker_actions.append({
            "step": self.current_step,
            "day": self.current_day,
            "hour": self.current_hour,
            "unit_idx": unit_idx,
            "op": op,
            "pos": list(pos) if pos else None,
            "quadrant": quadrant,
            "success": success,
            "detail": detail,
        })

    def record_midnight_drop(
        self,
        carried: Dict[str, int],
        shed_pre: Dict[str, int],
        shed_post: Dict[str, int],
        deposited: Dict[str, int],
        discarded: Dict[str, int],
    ):
        base_val_lost = sum(
            cnt * PRODUCT_BASE_PRICES.get(prod, 25.0) for prod, cnt in discarded.items()
        )
        spot_val_lost = sum(
            cnt * float(self.current_market_prices.get(prod, PRODUCT_BASE_PRICES.get(prod, 25.0)))
            for prod, cnt in discarded.items()
        )
        self.midnight_discards.append({
            "step": self.current_step,
            "day": self.current_day,
            "hour": self.current_hour,
            "carried": carried,
            "shed_pre": shed_pre,
            "shed_post": shed_post,
            "deposited": deposited,
            "discarded": discarded,
            "carried_total": sum(carried.values()),
            "deposited_total": sum(deposited.values()),
            "discarded_total": sum(discarded.values()),
            "base_value_lost": base_val_lost,
            "spot_value_lost": spot_val_lost,
        })

    def capture_tile_census(self, farm: Dict[str, Any]):
        """Capture authoritative classification of all 100 tiles by quadrant."""
        if farm is None or "tiles" not in farm:
            return

        census = {
            "NW": {"LOCKED": 0, "EMPTY": 0, "PLANT": 0, "STRUCTURE": 0, "ANIMAL": 0, "WEED": 0},
            "NE": {"LOCKED": 0, "EMPTY": 0, "PLANT": 0, "STRUCTURE": 0, "ANIMAL": 0, "WEED": 0},
            "SW": {"LOCKED": 0, "EMPTY": 0, "PLANT": 0, "STRUCTURE": 0, "ANIMAL": 0, "WEED": 0},
            "SE": {"LOCKED": 0, "EMPTY": 0, "PLANT": 0, "STRUCTURE": 0, "ANIMAL": 0, "WEED": 0},
        }

        tiles = farm["tiles"]
        board_size = len(tiles)
        for y in range(board_size):
            for x in range(board_size):
                q = get_quadrant(x, y, board_size)
                t = tiles[y][x]
                if t == "LOCKED":
                    census[q]["LOCKED"] += 1
                elif t is None:
                    census[q]["EMPTY"] += 1
                elif isinstance(t, dict):
                    kind = t.get("kind")
                    if kind == "PLANT":
                        census[q]["PLANT"] += 1
                    elif "animal" in t:
                        census[q]["ANIMAL"] += 1
                    elif kind in ("COOP", "PASTURE"):
                        census[q]["STRUCTURE"] += 1
                    elif kind == "WEED":
                        census[q]["WEED"] += 1
                    else:
                        census[q]["EMPTY"] += 1

        self.daily_quadrant_census[self.current_day] = census

    def install_hooks(self, env: Optional[Any] = None):
        """Install non-invasive observation hooks onto kaggriculture engine."""
        self.env = env
        session = self

        self._orig_interpreter = kengine.interpreter

        def hooked_interpreter(state, env_arg):
            if hasattr(state[0].observation, "farms") and len(state[0].observation.farms) > session.seat:
                session.our_farm = state[0].observation.farms[session.seat]
                session.our_private = state[session.seat].observation.private
                session.current_day = getattr(state[0].observation, "day", 0)
                session.current_hour = getattr(state[0].observation, "hour", 0)
                session.current_step = getattr(state[0].observation, "step", session.current_day * 24 + session.current_hour)
                if hasattr(state[0].observation, "market") and hasattr(state[0].observation.market, "get"):
                    prices = state[0].observation.market.get("prices", {})
                    if prices:
                        session.current_market_prices = dict(prices)
            return session._orig_interpreter(state, env_arg)

        kengine.interpreter = hooked_interpreter
        if env is not None and hasattr(env, "interpreter"):
            self._orig_env_interpreter = env.interpreter
            env.interpreter = hooked_interpreter

        def hooked_commit(op, item, price, farm, private, market, shed_capacity=100):
            is_ours = (farm is session.our_farm) or (private is session.our_private)
            ok = session._orig_commit_unit(op, item, price, farm, private, market, shed_capacity)
            if is_ours:
                session.record_commit(op, item, price, ok)
            return ok

        def hooked_hire(farm, private, board_size, mult=kengine.FARM_HAND_COST_MULT):
            is_ours = (farm is session.our_farm)
            pre_money = farm.get("money", 0.0) if is_ours else 0.0
            pre_hands = len(farm.get("hands", [])) if is_ours else 0
            session._orig_do_hire(farm, private, board_size, mult)
            if is_ours:
                post_money = farm.get("money", 0.0)
                cost = pre_money - post_money
                if cost > 0:
                    session.record_hire(cost, pre_hands + 1)

        def hooked_buy_land(farm, board_size):
            is_ours = (farm is session.our_farm)
            pre_money = farm.get("money", 0.0) if is_ours else 0.0
            
            # Determine which quadrant is next to unlock
            quad_to_unlock = None
            if is_ours and "tiles" in farm:
                half = board_size // 2
                # Check candidate tiles for NE, SW, SE
                if farm["tiles"][0][half] == "LOCKED":
                    quad_to_unlock = "NE"
                elif farm["tiles"][half][0] == "LOCKED":
                    quad_to_unlock = "SW"
                elif farm["tiles"][half][half] == "LOCKED":
                    quad_to_unlock = "SE"

            session._orig_do_buy_land(farm, board_size)
            if is_ours:
                post_money = farm.get("money", 0.0)
                cost = pre_money - post_money
                if cost > 0 and quad_to_unlock:
                    session.record_land_buy(cost, quad_to_unlock)

        def hooked_apply_unit_action(farm, private, idx, action, board_size, day, turns_per_day, shed_capacity=100):
            is_ours = (farm is session.our_farm)
            if not is_ours:
                return session._orig_apply_unit_action(farm, private, idx, action, board_size, day, turns_per_day, shed_capacity)

            pos = kengine._farmer_position(farm, idx)
            fx, fy = pos[0], pos[1] if pos else (-1, -1)
            quadrant = get_quadrant(fx, fy, board_size) if pos else "UNKNOWN"
            inv_pre = copy.deepcopy(kengine._farmer_inventory(private, idx)) if pos else {}
            tile_pre = copy.deepcopy(farm["tiles"][fy][fx]) if pos else None
            seeds_pre = copy.deepcopy(private.get("seeds", {}))
            shed_pre = copy.deepcopy(private.get("shed", {}))

            session._orig_apply_unit_action(farm, private, idx, action, board_size, day, turns_per_day, shed_capacity)

            pos_post = kengine._farmer_position(farm, idx)
            inv_post = kengine._farmer_inventory(private, idx) if pos else {}
            tile_post = farm["tiles"][fy][fx] if pos else None
            seeds_post = private.get("seeds", {})
            shed_post = private.get("shed", {})

            op = action[0] if (isinstance(action, list) and action) else "PASS"
            success = False
            detail = {}

            if op in kengine.FARMER_MOVES:
                success = (pos_post != pos)
            elif op == "PASS":
                success = True
            elif op == "DROP":
                shed_inc = sum(shed_post.values()) - sum(shed_pre.values())
                success = (shed_inc > 0) or (len(inv_pre) == 0 and len(inv_post) == 0)
                detail["deposited_units"] = shed_inc
            elif op == "PICKUP":
                inv_inc = sum(inv_post.values()) - sum(inv_pre.values())
                success = (inv_inc > 0)
                detail["picked_units"] = inv_inc
            elif op == "PLACE":
                item = action[1] if len(action) >= 2 else None
                if item in kengine.ANIMALS:
                    success = isinstance(tile_post, dict) and tile_post.get("animal") == item
                    if success:
                        session.animal_placements.append({
                            "step": session.current_step,
                            "day": session.current_day,
                            "hour": session.current_hour,
                            "animal": item,
                            "pos": [fx, fy],
                            "quadrant": quadrant,
                        })
                else:
                    shed_inc = sum(shed_post.values()) - sum(shed_pre.values())
                    success = (shed_inc > 0)
            elif op == "PLANT":
                crop = action[1] if len(action) >= 2 else None
                success = isinstance(tile_post, dict) and tile_post.get("kind") == "PLANT" and (tile_pre is None)
                if success:
                    session.crop_plantings.append({
                        "step": session.current_step,
                        "day": session.current_day,
                        "hour": session.current_hour,
                        "crop": crop,
                        "pos": [fx, fy],
                        "quadrant": quadrant,
                    })
            elif op == "WATER":
                success = isinstance(tile_post, dict) and tile_post.get("watered_today", False) and (not isinstance(tile_pre, dict) or not tile_pre.get("watered_today", False))
                if success and isinstance(tile_post, dict):
                    session.crop_waterings.append({
                        "step": session.current_step,
                        "day": session.current_day,
                        "hour": session.current_hour,
                        "crop": tile_post.get("crop"),
                        "pos": [fx, fy],
                        "quadrant": quadrant,
                    })
            elif op == "FERTILIZE":
                success = isinstance(tile_post, dict) and tile_post.get("fertilized_until_day", -1) >= day
                if success and isinstance(tile_post, dict):
                    session.crop_fertilizations.append({
                        "step": session.current_step,
                        "day": session.current_day,
                        "hour": session.current_hour,
                        "crop": tile_post.get("crop"),
                        "pos": [fx, fy],
                        "quadrant": quadrant,
                    })
            elif op == "HARVEST":
                inv_diff = {item: inv_post.get(item, 0) - inv_pre.get(item, 0) for item in set(inv_post) | set(inv_pre)}
                gained = sum(max(0, v) for v in inv_diff.values())
                success = (gained > 0)
                if success:
                    detail["harvested_units"] = gained
                    crop_name = None
                    if isinstance(tile_pre, dict):
                        crop_name = tile_pre.get("crop") or tile_pre.get("animal")
                    for itm, cnt in inv_diff.items():
                        if cnt > 0:
                            if itm in kengine.CROPS:
                                session.crop_harvests.append({
                                    "step": session.current_step,
                                    "day": session.current_day,
                                    "hour": session.current_hour,
                                    "crop": itm,
                                    "pos": [fx, fy],
                                    "quadrant": quadrant,
                                    "units": cnt,
                                })
                            elif itm in ("EGG", "MILK", "WOOL"):
                                session.animal_harvests.append({
                                    "step": session.current_step,
                                    "day": session.current_day,
                                    "hour": session.current_hour,
                                    "product": itm,
                                    "pos": [fx, fy],
                                    "quadrant": quadrant,
                                    "units": cnt,
                                })
            elif op == "FEED":
                success = isinstance(tile_post, dict) and tile_post.get("fed_today", False) and (not isinstance(tile_pre, dict) or not tile_pre.get("fed_today", False))
                if success and isinstance(tile_post, dict):
                    session.animal_feeds.append({
                        "step": session.current_step,
                        "day": session.current_day,
                        "hour": session.current_hour,
                        "animal": tile_post.get("animal"),
                        "pos": [fx, fy],
                        "quadrant": quadrant,
                    })
            elif op == "CARE":
                success = isinstance(tile_post, dict) and tile_post.get("cared_today", False) and (not isinstance(tile_pre, dict) or not tile_pre.get("cared_today", False))
                if success and isinstance(tile_post, dict):
                    session.animal_cares.append({
                        "step": session.current_step,
                        "day": session.current_day,
                        "hour": session.current_hour,
                        "animal": tile_post.get("animal"),
                        "pos": [fx, fy],
                        "quadrant": quadrant,
                    })
            elif op == "COLLECT_FERTILIZER":
                fert_gained = inv_post.get("FERTILIZER", 0) - inv_pre.get("FERTILIZER", 0)
                success = (fert_gained > 0)
                if success:
                    animal_type = tile_pre.get("animal") if isinstance(tile_pre, dict) else "UNKNOWN"
                    session.fertilizer_collections.append({
                        "step": session.current_step,
                        "day": session.current_day,
                        "hour": session.current_hour,
                        "animal": animal_type,
                        "pos": [fx, fy],
                        "quadrant": quadrant,
                    })
            elif op in ("BUILD_COOP", "BUILD_PASTURE"):
                kind = "COOP" if op == "BUILD_COOP" else "PASTURE"
                success = isinstance(tile_post, dict) and tile_post.get("kind") == kind and (tile_pre is None)
            elif op == "DIG":
                success = (tile_post is None) and (tile_pre is not None)
                if success and isinstance(tile_pre, dict):
                    detail["cleared_kind"] = tile_pre.get("kind", "UNKNOWN")

            session.record_worker_action(idx, action, (fx, fy), quadrant, success, detail)

        def hooked_drop(private, capacity):
            is_ours = (private is session.our_private)
            if not is_ours:
                return session._orig_drop_inventories_to_shed(private, capacity)

            shed_pre = dict(private.get("shed", {}))
            carried = defaultdict(int)
            for inv in private.get("inventories", []):
                if isinstance(inv, dict):
                    for item, n in inv.items():
                        carried[item] += max(0, int(n))
            carried = dict(carried)

            session._orig_drop_inventories_to_shed(private, capacity)

            shed_post = dict(private.get("shed", {}))
            dep = defaultdict(int)
            disc = defaultdict(int)
            cur = sum(shed_pre.values())
            for item, n in carried.items():
                if n <= 0:
                    continue
                room = max(0, capacity - cur)
                t = min(n, room)
                if t > 0:
                    dep[item] += t
                    cur += t
                l = n - t
                if l > 0:
                    disc[item] += l

            session.record_midnight_drop(carried, shed_pre, shed_post, dict(dep), dict(disc))

        kengine._commit_unit = hooked_commit
        kengine._do_hire = hooked_hire
        kengine._do_buy_land = hooked_buy_land
        kengine._apply_unit_action = hooked_apply_unit_action
        kengine._drop_inventories_to_shed = hooked_drop

    def remove_hooks(self):
        """Restore original engine functions."""
        kengine.interpreter = self._orig_interpreter
        if self._orig_env_interpreter is not None and self.env is not None and hasattr(self.env, "interpreter"):
            self.env.interpreter = self._orig_env_interpreter
        kengine._commit_unit = self._orig_commit_unit
        kengine._do_hire = self._orig_do_hire
        kengine._do_buy_land = self._orig_do_buy_land
        kengine._apply_unit_action = self._orig_apply_unit_action
        kengine._drop_inventories_to_shed = self._orig_drop_inventories_to_shed

    def __enter__(self):
        self.install_hooks()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.remove_hooks()
