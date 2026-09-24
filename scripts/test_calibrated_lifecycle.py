"""Prototype calibrated lifecycle storage flow on representative trace states."""

import os
import sys

_REPO_ROOT = r"d:\website project\kaggri ox"
_AGENT_DIR = os.path.join(_REPO_ROOT, "agent")
sys.path = [_REPO_ROOT, _AGENT_DIR] + [os.path.join(_AGENT_DIR, s) for s in ('state', 'strategy', 'execution', 'market')] + [p for p in sys.path if 'agent' not in p]

from config import CROPS, ANIMALS
from strategy.whole_farm_planner import WholeFarmPlanner, ShadowSnapshot

def evaluate_lifecycle_calibrated(
    portfolio,
    snapshot,
    raw_ctx=None,
    horizon_days=None,
):
    start_day = snapshot.day
    end_day = 30 if horizon_days is None else min(30, start_day + horizon_days)
    active_workers = max(1, snapshot.active_worker_count)
    daily_action_capacity = active_workers * 24
    daily_sale_limit = min(20, active_workers * 10)

    current_shed_count = sum(cnt for _, cnt in snapshot.shed_inventory)
    peak_shed = current_shed_count
    peak_daily_actions = 0

    daily_actions = {d: 0 for d in range(start_day, end_day)}
    daily_shed_additions = {d: 0 for d in range(start_day, end_day)}
    daily_commercial_additions = {d: 0 for d in range(start_day, end_day)}

    # 1. Livestock feeding
    num_animals = 0
    if raw_ctx and "farm" in raw_ctx:
        for t in raw_ctx["farm"].iter_tiles():
            if getattr(t, "is_animal", False) or (getattr(t, "animal", None) is not None) or getattr(t, "kind", None) in ANIMALS:
                num_animals += 1
    elif snapshot.animals_summary:
        num_animals = sum(cnt for _, cnt in snapshot.animals_summary)
    else:
        num_animals = sum(cnt for k, cnt in snapshot.tiles_summary if k in ANIMALS)

    for d in range(start_day, end_day):
        daily_actions[d] += (num_animals * 2)

    # 2. Core crop obligations
    if raw_ctx and "farm" in raw_ctx:
        farm_obj = raw_ctx["farm"]
        for t in farm_obj.iter_tiles():
            is_sw_tile = (t.x < 5 and t.y >= 5)
            if is_sw_tile or not getattr(t, "is_plant", False):
                continue
            crop_name = getattr(t, "crop", None)
            if not crop_name:
                continue
            cd = CROPS.get(crop_name, {})
            planted_day = getattr(t, "planted_day", snapshot.day)
            is_ongoing = cd.get("ongoing", False)
            first_yield = cd.get("first_yield_day", 2)
            interval = cd.get("interval", 2)
            max_yield_count = cd.get("max_yield", 6)
            max_yield_day = cd.get("max_yield_day", 4)

            yield_per_harvest = 1
            if crop_name == "WHEAT":
                yield_per_harvest = 6
            elif crop_name == "CARROT":
                yield_per_harvest = 4
            elif crop_name == "MELON":
                yield_per_harvest = 2

            if is_ongoing:
                for d in range(start_day, end_day):
                    age = d - planted_day
                    days_since_first = age - first_yield
                    if days_since_first >= 0 and (days_since_first % interval == 0) and ((days_since_first // interval) < max_yield_count):
                        daily_actions[d] += 2
                        daily_shed_additions[d] += yield_per_harvest
                        if crop_name != "WHEAT":
                            daily_commercial_additions[d] += yield_per_harvest
                    else:
                        if (t.x + t.y + d) % 2 == 0:
                            daily_actions[d] += 1
            else:
                harvest_day = planted_day + max_yield_day
                if start_day <= harvest_day < end_day:
                    daily_actions[harvest_day] += 2
                    daily_shed_additions[harvest_day] += yield_per_harvest
                    if crop_name != "WHEAT":
                        daily_commercial_additions[harvest_day] += yield_per_harvest
                w_start = (max_yield_day + 1) // 2
                for d in range(start_day, min(end_day, harvest_day)):
                    age = d - planted_day
                    if age >= w_start:
                        daily_actions[d] += 1
    else:
        planted_count = sum(cnt for k, cnt in snapshot.tiles_summary if k in ("CARROT", "MELON", "WHEAT", "STRAWBERRY", "TOMATO", "PLANT"))
        if planted_count > 0:
            base_core_actions = min(12, max(2, planted_count // 3))
            for d in range(start_day, end_day):
                daily_actions[d] += base_core_actions

    # 3. SW candidate obligations
    for crop_name, n_units, tiles in portfolio.get("allocations", []):
        cd = CROPS.get(crop_name, {})
        is_ongoing = cd.get("ongoing", False)
        first_yield = cd.get("first_yield_day", 2)
        interval = cd.get("interval", 2)
        max_yield_count = cd.get("max_yield", 6) if is_ongoing else 1
        max_yield_day = cd.get("max_yield_day", 4)
        n_tiles = len(tiles)

        yield_per_tile = 1
        if crop_name == "WHEAT":
            yield_per_tile = 6
        elif crop_name == "CARROT":
            yield_per_tile = 4
        elif crop_name == "MELON":
            yield_per_tile = 2

        daily_actions[start_day] += (n_tiles * 2)

        if is_ongoing:
            for d in range(start_day + 1, end_day):
                age = d - start_day
                days_since_first = age - first_yield
                if days_since_first >= 0 and (days_since_first % interval == 0) and ((days_since_first // interval) < max_yield_count):
                    daily_actions[d] += (n_tiles * 2)
                    daily_shed_additions[d] += (n_tiles * yield_per_tile)
                    if crop_name != "WHEAT":
                        daily_commercial_additions[d] += (n_tiles * yield_per_tile)
                else:
                    if age % 2 == 1:
                        daily_actions[d] += n_tiles
        else:
            harvest_day = start_day + max_yield_day
            for d in range(start_day + 1, end_day):
                age = d - start_day
                if d == harvest_day:
                    daily_actions[d] += (n_tiles * 2)
                    daily_shed_additions[d] += (n_tiles * yield_per_tile)
                    if crop_name != "WHEAT":
                        daily_commercial_additions[d] += (n_tiles * yield_per_tile)
                elif d < harvest_day:
                    w_start = (max_yield_day + 1) // 2
                    if age >= w_start:
                        daily_actions[d] += n_tiles

    # Flow simulation
    simulated_shed = current_shed_count
    # Current sellable inventory (non-wheat plus wheat above protected feed)
    days_left = max(0, 30 - start_day)
    protected_feed_total = num_animals * days_left
    
    current_wheat = dict(snapshot.shed_inventory).get("WHEAT", 0)
    current_non_wheat = sum(cnt for item, cnt in snapshot.shed_inventory if item != "WHEAT")
    
    sellable_stock = current_non_wheat + max(0, current_wheat - protected_feed_total)
    
    for d in range(start_day, end_day):
        acts = daily_actions.get(d, 0)
        if acts > peak_daily_actions:
            peak_daily_actions = acts
        if acts > daily_action_capacity:
            return False, peak_shed, peak_daily_actions, f"labor_exceeded_day_{d}_{acts}_gt_{daily_action_capacity}"

        # Animal feed consumption from shed
        simulated_shed = max(0, simulated_shed - num_animals)

        # Incoming harvests for today
        additions = daily_shed_additions.get(d, 0)
        comm_additions = daily_commercial_additions.get(d, 0)
        simulated_shed += additions
        sellable_stock += comm_additions

        # Sell commercial goods up to daily limit
        sales_today = min(sellable_stock, daily_sale_limit)
        sellable_stock -= sales_today
        simulated_shed = max(0, simulated_shed - sales_today)

        if simulated_shed > peak_shed:
            peak_shed = simulated_shed
        if simulated_shed > 100:
            return False, peak_shed, peak_daily_actions, f"storage_overflow_day_{d}_{simulated_shed}_gt_100"

    return True, peak_shed, peak_daily_actions, None

print("Prototype module loaded successfully.")
