"""Per-turn prioritized task construction and greedy unit assignment."""
from config import (
    ANIMALS,
    CARE_GEESE,
    CROPS,
    PRIORITY_BONUS_WATER,
    PRIORITY_BUILD_STRUCTURE,
    PRIORITY_CARE_ANIMAL,
    PRIORITY_DECAY_HARVEST,
    PRIORITY_FERT_COLLECT,
    PRIORITY_PLANT_AND_WATER,
    PRIORITY_PROD_DAY_FEED,
    PRIORITY_STANDARD_HARVEST,
    PRIORITY_URGENT_SURVIVAL,
    PRIORITY_WEED_DIG,
)
from state.observation_parser import crop_age, in_bonus_window


def produces_today(tile, day):
    info = ANIMALS.get(tile.animal)
    if info is None:
        return False
    since_first = day + 1 - tile.placed_day - info["first_yield_day"]
    return since_first >= 0 and since_first % info["interval"] == 0


def build_tasks(ctx, macro):
    day, hour = ctx["day"], ctx["hour"]
    tasks = []

    def add(priority, op, target=None, args=None, kind="", meta=None):
        tasks.append({"priority": priority, "op": op, "target": target,
                      "args": args or [], "kind": kind, "meta": meta or {}})

    # 1. Crops
    plants = [t for t in ctx["farm"].iter_tiles() if t.is_plant]
    for t in plants:
        cd = CROPS.get(t.crop)
        if cd is None:
            continue
        age = crop_age(t, day)
        mature_one_time = (not cd["ongoing"]) and age >= cd["max_yield_day"]
        if t.yield_units > 0 and mature_one_time:
            add(PRIORITY_DECAY_HARVEST, "HARVEST", t.pos, kind="harvest_decay")
        elif t.yield_units > 0 and cd["ongoing"]:
            add(PRIORITY_STANDARD_HARVEST, "HARVEST", t.pos, kind="harvest_ongoing")
        elif t.yield_units >= cd["max_yield"] and not cd["ongoing"]:
            add(PRIORITY_STANDARD_HARVEST, "HARVEST", t.pos, kind="harvest_full")

        if not t.watered_today and hour < 23:
            dying_tomorrow = t.consecutive_unwatered >= 1
            prio = PRIORITY_URGENT_SURVIVAL if dying_tomorrow else (
                PRIORITY_BONUS_WATER if in_bonus_window(t, day) else 30)
            add(prio, "WATER", t.pos, kind="water")

    # 2. Animals
    for t in ctx["farm"].iter_tiles():
        if not t.is_animal:
            continue
        if t.consecutive_unfed >= 1 and not t.fed_today and hour < 23:
            add(PRIORITY_URGENT_SURVIVAL - 1, "FEED", t.pos, kind="feed_rescue")
        elif produces_today(t, day) and not t.fed_today:
            add(PRIORITY_PROD_DAY_FEED, "FEED", t.pos, kind="feed_prod")
        elif not t.fed_today and hour < 20:
            add(PRIORITY_CARE_ANIMAL - 5, "FEED", t.pos, kind="feed_off")
            
        if t.fertilizer_available:
            add(PRIORITY_FERT_COLLECT, "COLLECT_FERTILIZER", t.pos, kind="fert")
        if not t.cared_today and hour < 21:
            add(PRIORITY_CARE_ANIMAL, "CARE", t.pos, kind="care")

    # 3. Planting
    seeds = ctx["private"].seeds
    if hour <= 18 and day < 27:
        empty_tiles = [t for t in ctx["farm"].iter_tiles() if t.kind == "EMPTY"]
        for t in empty_tiles:
            if seeds.get("WHEAT", 0) > 0:
                add(PRIORITY_PLANT_AND_WATER, "PLANT", t.pos, args=["WHEAT"], kind="plant")
            elif seeds.get("CARROT", 0) > 0:
                add(PRIORITY_PLANT_AND_WATER, "PLANT", t.pos, args=["CARROT"], kind="plant")

    # 4. Weeds
    for t in ctx["farm"].iter_tiles():
        if t.kind == "WEED" and hour < 22:
            add(PRIORITY_WEED_DIG, "DIG", t.pos, kind="dig")

    return tasks


def assign_tasks(tasks, ctx):
    farm = ctx["farm"]
    units = [(0, tuple(farm.farmer))]
    for i, h in enumerate(farm.hands):
        units.append((i + 1, tuple(h)))

    busy = set()
    assignment = {}
    for task in sorted(tasks, key=lambda t: -t["priority"]):
        target = task.get("target") or tuple(farm.farmer)
        best, best_d = None, 10 ** 9
        for idx, pos in units:
            if idx in busy:
                continue
            d = abs(pos[0] - target[0]) + abs(pos[1] - target[1])
            if d < best_d:
                best, best_d = idx, d
        if best is not None:
            busy.add(best)
            task_copy = dict(task)
            task_copy["unit_idx"] = best
            task_copy["unit_pos"] = dict(units)[best]
            assignment[best] = task_copy

    # Unassigned units PASS
    for idx, pos in units:
        if idx not in assignment:
            assignment[idx] = {"op": "PASS", "target": pos, "args": [], "unit_idx": idx, "unit_pos": pos}

    return assignment
