"""Per-turn prioritized task construction + greedy distance assignment.

Engine facts encoded here:
  - One action per unit per turn; moves and ops are mutually exclusive.
  - HANDS HIRED THIS TURN CANNOT ACT THIS TURN: interpreter applies unit
    actions BEFORE _process_market() (where HIRE appends to farm["hands"]),
    so a just-hired hand's position lookup returns None and its action is
    dropped. Hands first act on turn T+1. Scheduling therefore dispatches to
    currently-observed hands only; new hires join the roster next turn.
  - Seeds bought this turn are likewise only PLANTable next turn (same
    farm-before-market ordering).
  - A plant with consecutive_unwatered == 1 dies at end-of-day unless watered
    TODAY (urgent survival).
  - One-time crops start decaying the day after max_yield_day -> harvest on
    max_yield_day morning at the latest.
  - Animals produce during end-of-day refresh when (day+1 - placed -
    first_yield_day) % interval == 0; feeding must be done BEFORE that refresh,
    and an unfed production day wipes the banked care bonus.
  - fertilizer_available flips True at end-of-day; collect it any time next day.
"""
from config import (
    ANIMALS,
    CARE_GEESE,
    CROPS,
    PRIORITY_BONUS_WATER,
    PRIORITY_BUILD_STRUCTURE,
    PRIORITY_CARE_ANIMAL,
    PRIORITY_DECAY_HARVEST,
    PRIORITY_FEED_STAGING,
    PRIORITY_FERT_COLLECT,
    PRIORITY_PLACE_ANIMAL,
    PRIORITY_PLANT_AND_WATER,
    PRIORITY_PROD_DAY_FEED,
    PRIORITY_STANDARD_HARVEST,
    PRIORITY_URGENT_SURVIVAL,
    PRIORITY_WEED_DIG,
    SHED_ACCESS_TILES,
    log,
)
from observation_parser import crop_age, in_bonus_window


def farm_pos_of(ctx):
    return ctx["farm"].farmer


def produces_today(tile, day):
    """True if this animal's production fires at END-of-day refresh today."""
    info = ANIMALS.get(tile.animal)
    if info is None:
        return False
    since_first = day + 1 - tile.placed_day - info["first_yield_day"]
    return since_first >= 0 and since_first % info["interval"] == 0


def build_tasks(ctx, macro):
    """Construct the prioritized TaskList for this turn."""
    day, hour = ctx["day"], ctx["hour"]
    tasks = []

    def add(priority, op, target=None, args=None, kind="", meta=None):
        tasks.append({"priority": priority, "op": op, "target": target,
                      "args": args or [], "kind": kind, "meta": meta or {}})

    # ---------------- crops ----------------
    water_starved = False
    plants = [t for t in ctx["farm"].iter_tiles() if t.is_plant]
    need_water = []
    for t in plants:
        cd = CROPS.get(t.crop)
        if cd is None:
            continue
        age = crop_age(t, day)
        mature_one_time = (not cd["ongoing"]) and age >= cd["max_yield_day"]
        # decay-imminent harvest (one-time at/after max day, still alive)
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
            if not macro.watering_enabled:
                continue
            if not dying_tomorrow and macro.water_budget_exceeded:
                water_starved = True   # skip-day fallback: alternate batches
                if (t.x + t.y + day) % 2 != 0:
                    continue
            need_water.append((prio, t))
    for prio, t in need_water:
        add(prio, "WATER", t.pos, kind="water")

    # ---------------- animals ----------------
    feeds_due = 0
    for t in ctx["farm"].iter_tiles():
        if not t.is_animal:
            continue
        feed_now = False
        if t.consecutive_unfed >= 1 and not t.fed_today and hour < 23:
            add(PRIORITY_URGENT_SURVIVAL - 1, "FEED", t.pos,
                kind="feed_rescue", meta={"wheat": 1})
            feed_now = True
        elif produces_today(t, day) and not t.fed_today:
            add(PRIORITY_PROD_DAY_FEED, "FEED", t.pos,
                kind="feed_prod", meta={"wheat": 1})
            feed_now = True
        elif not t.fed_today and hour < 20 and macro.feeding_enabled:
            add(PRIORITY_CARE_ANIMAL - 5, "FEED", t.pos, kind="feed_off",
                meta={"wheat": 1})
            feed_now = True
        feeds_due += 1 if feed_now else 0
        if t.fertilizer_available:
            add(PRIORITY_FERT_COLLECT, "COLLECT_FERTILIZER", t.pos, kind="fert")
        want_care = macro.feeding_enabled and (CARE_GEESE or t.animal != "GOOSE")
        if want_care and not t.cared_today and hour < 21:
            add(PRIORITY_CARE_ANIMAL, "CARE", t.pos, kind="care")

    # WHEAT STAGING: engine FEED consumes the UNIT's inventory (never the
    # shed), so staged PICKUP tasks must run before any FEED can succeed.
    if feeds_due > 0:
        held = sum(int(inv.get("WHEAT", 0))
                   for inv in ctx["private"].inventories)
        shed_wheat = int(ctx["private"].shed.get("WHEAT", 0))
        grab = min(shed_wheat, max(feeds_due - held, 0))
        if grab > 0:
            farmer_pos = tuple(farm_pos_of(ctx))
            target = min(SHED_ACCESS_TILES,
                         key=lambda tp: abs(tp[0] - farmer_pos[0])
                         + abs(tp[1] - farmer_pos[1]))
            add(PRIORITY_FEED_STAGING, "PICKUP", tuple(target),
                args=["WHEAT", int(grab)], kind="pickup_wheat")

    # ---------------- planting queue (seed-conflict-safe) ----------------
    seeds = ctx["private"].seeds
    wanted_plants = list(macro.plant_queue)  # [(pos, crop)]
    if hour <= 18 and macro.watering_enabled:
        by_crop = {}
        for pos, crop in wanted_plants:
            if seeds.get(crop, 0) > by_crop.get(crop, 0):
                by_crop[crop] = by_crop.get(crop, 0) + 1
                add(PRIORITY_PLANT_AND_WATER, "PLANT", pos, args=[crop],
                    kind="plant", meta={"paired_water": True})
            else:
                break  # serialize strictly: never exceed seed stock

    # ---------------- structures & animals ----------------
    for pos in macro.build_queue[:2]:
        add(PRIORITY_BUILD_STRUCTURE, macro.build_op, pos, kind="build")
        for task in macro.place_queue[:2]:
            add(PRIORITY_PLACE_ANIMAL, task["op"], task.get("target"),
                args=task.get("args", []),
                kind=task.get("kind", "place_animal"))

    # ---------------- weeds ----------------
    blocked = {tuple(p) for p, _ in macro.plant_queue}
    for t in ctx["farm"].iter_tiles():
        if t.kind == "WEED" and t.pos in blocked and hour < 22:
            add(PRIORITY_WEED_DIG, "DIG", t.pos, kind="dig")

    return tasks


def assign_tasks(tasks, ctx, extra_units=()):
    """Greedy closest-unit dispatch. Returns per-unit actions + bookkeeping."""
    farm = ctx["farm"]
    units = [(0, tuple(farm.farmer))]
    for i, h in enumerate(farm.hands):
        units.append((i + 1, tuple(h)))
    for idx, pos in extra_units:
        units.append((idx, tuple(pos)))
    pos_by_idx = dict(units)

    # Holder map for PLACE tasks: engine PLACE requires the ACTING unit to
    # hold the animal, so dispatch must prefer/require holding units.
    holders = {}
    private = ctx.get("private")
    if private is not None:
        for u_idx, inv in enumerate(private.inventories):
            for item, cnt in (inv or {}).items():
                if cnt > 0:
                    holders.setdefault(item, []).append(u_idx)

    def _eligible(task):
        """Units that could execute this task this turn without a no-op."""
        if task["op"] == "PLACE" and task.get("args"):
            item = task["args"][0]
            if item in ANIMALS:
                return set(holders.get(item, []))   # empty => defer, don't no-op
        return None                                  # no restriction

    busy = set()
    assignment = {}          # unit_idx -> task
    deferred_place = []
    for task in sorted(tasks, key=lambda t: -t["priority"]):
        eligible = _eligible(task)
        if eligible is not None and not eligible:
            deferred_place.append(task)               # nobody holds it yet
            continue
        target = task.get("target") or tuple(farm.farmer)
        best, best_d = None, 10 ** 9
        for idx, pos in units:
            if idx in busy:
                continue
            if eligible is not None and idx not in eligible:
                continue
            d = abs(pos[0] - target[0]) + abs(pos[1] - target[1])
            if d < best_d:
                best, best_d = idx, d
        if best is None:
            continue
        busy.add(best)
        task["unit_pos"] = pos_by_idx[best]
        assignment[best] = task

    actions = {idx: ["PASS"] for idx in range(len(units))}
    for idx, task in assignment.items():
        actions[idx] = emit(task)

    # Bookkeeping: PLANT intents count as seed reservations whether or not the
    # unit is standing on the tile yet (seeds are consumed only on execution,
    # but the atomic all-or-nothing rule counts REQUESTS this turn).
    plant_intents = {}
    watered_now, harvested, fed_animals = [], [], []
    executed_plants = {}
    for task in assignment.values():
        if task["op"] == "PLANT":
            crop = task["args"][0] if task.get("args") else None
            if crop:
                plant_intents[crop] = plant_intents.get(crop, 0) + 1
                if task["unit_pos"] == tuple(task["target"]):
                    executed_plants[crop] = executed_plants.get(crop, 0) + 1
        elif task["op"] == "WATER":
            watered_now.append(task["target"])
        elif task["op"] == "HARVEST":
            harvested.append(task["target"])
        elif task["op"] == "FEED":
            fed_animals.append(task["target"])
    return {
        "actions": actions,
        "assignment": assignment,
        "plant_intents": plant_intents,
        "executed_plants": executed_plants,
        "watered_now": watered_now,
        "harvested": harvested,
        "fed": fed_animals,
        "deferred_place": [t.get("args", [None])[0] for t in deferred_place],
    }


def emit(task):
    """Move toward target or execute op when standing on it."""
    op = task["op"]
    target = task.get("target")
    pos = tuple(task.get("unit_pos", (4, 4)))

    if target is not None and pos != tuple(target):
        from pathfinding import bfs_first_step
        move = bfs_first_step(pos, tuple(target))
        if move is not None:
            return [move]
        # already adjacent-but-unreachable case shouldn't happen on open grid

    if op == "PICKUP":
        return ["PICKUP", *task.get("args", [])]
    if op == "PLACE":
        return ["PLACE", *task.get("args", [])]
    if task.get("args"):
        return [op, *task["args"]]
    return [op]


def estimate_daily_load(ctx):
    """Rough action-count needed today (used by hiring_manager)."""
    day = ctx["day"]
    load = 0
    for t in ctx["farm"].iter_tiles():
        if t.is_plant and not t.watered_today:
            load += 1
        if t.is_animal:
            load += 1 + (1 if t.fertilizer_available else 0)
            info = ANIMALS.get(t.animal)
            if info and (day + 1 - t.placed_day - info["first_yield_day"]) % info["interval"] == 0:
                load += 1  # production-day feed + harvest next morning
    load += len(ctx["private"].seeds) and sum(
        1 for t in ctx["farm"].iter_tiles() if t.kind == "EMPTY")
    return load
