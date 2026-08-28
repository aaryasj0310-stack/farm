"""Per-turn prioritized task construction + greedy distance assignment.

v5.9: Action-budget allocator with utilization tracking.

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
    PRIORITY_FERTILIZE_CROP,
    PRIORITY_PLACE_ANIMAL,
    PRIORITY_PLANT_AND_WATER,
    PRIORITY_PROD_DAY_FEED,
    PRIORITY_STANDARD_HARVEST,
    PRIORITY_URGENT_SURVIVAL,
    PRIORITY_WEED_DIG,
    SHED_ACCESS_TILES,
    TURNS_PER_DAY,
    log,
)
from observation_parser import crop_age, in_bonus_window, needs_water_today
try:
    from execution.pathfinding import bfs_first_step
except ImportError:
    from pathfinding import bfs_first_step


# v5.9: Daily utilization tracking (accumulated across all 24 hours of each day)
_daily_log = {}
_daily_accum = {}

def get_daily_log():
    """Return the utilization log for the current episode."""
    return _daily_log

def reset_daily_log():
    """Reset utilization log at start of new episode."""
    global _daily_log, _daily_accum
    _daily_log = {}
    _daily_accum = {}

def _record_turn_utilization(ctx, n_units, actions_taken):
    """Accumulate hourly utilization and finalize daily log at hour 23."""
    day, hour = ctx["day"], ctx["hour"]
    if day not in _daily_accum:
        _daily_accum[day] = {"available": 0, "used": 0, "idle": 0, "idle_causes": []}
    
    used = sum(1 for a in actions_taken.values() if a != ["PASS"])
    avail = n_units
    idle = max(0, avail - used)
    
    _daily_accum[day]["available"] += avail
    _daily_accum[day]["used"] += used
    _daily_accum[day]["idle"] += idle
    if idle > 0:
        _daily_accum[day]["idle_causes"].append("no_tasks" if used == 0 else "partial_idle")
        
    if hour == 23 or ctx.get("step", 0) % TURNS_PER_DAY == 23:
        tot_avail = _daily_accum[day]["available"]
        tot_used = _daily_accum[day]["used"]
        tot_idle = _daily_accum[day]["idle"]
        shed_cnt = sum(ctx["private"].shed.values()) if ctx.get("private") else 0
        unlocked_cnt = len(ctx["farm"].unlocked) if ctx.get("farm") else 1
        n_hands = len(ctx["farm"].hands) if ctx.get("farm") else 0
        from market.order_builder import hire_total_cost
        
        _daily_log[day] = {
            "actions_available": tot_avail,
            "actions_used": tot_used,
            "idle_actions": tot_idle,
            "utilization_pct": round(100.0 * tot_used / max(1, tot_avail), 1),
            "shed_occupancy": shed_cnt,
            "quadrant_ownership": unlocked_cnt,
            "daily_hires": n_hands,
            "hire_cost": hire_total_cost(n_hands),
            "idle_cause": "queue_empty" if tot_idle > 0 else None,
        }


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
            if dying_tomorrow:
                # Guardrail 2: mandatory survival watering
                need_water.append((PRIORITY_URGENT_SURVIVAL, t))
            elif needs_water_today(t, day):
                prio = PRIORITY_BONUS_WATER if in_bonus_window(t, day) else 30
                if not macro.watering_enabled and day == 28 and in_bonus_window(t, day):
                    cd = CROPS.get(t.crop, {})
                    harvestable_by_29 = (t.planted_day is not None
                                         and t.planted_day + cd.get("max_yield_day", 99) <= 29)
                    if not harvestable_by_29:
                        continue
                need_water.append((prio, t))

    for prio, t in need_water:
        add(prio, "WATER", t.pos, kind="water")

    # ---------------- fertilizer application (Strawberries & Tomatoes) ----
    fert_in_shed = int(ctx["private"].shed.get("FERTILIZER", 0)) if ctx.get("private") else 0
    fert_held = sum(int(inv.get("FERTILIZER", 0)) for inv in (ctx["private"].inventories if ctx.get("private") else []))
    total_fert = fert_in_shed + fert_held
    
    if total_fert > 0 and hour < 20:
        fert_targets = []
        for t in plants:
            if t.crop in ("STRAWBERRY", "TOMATO") and t.fertilized_until_day < day:
                fert_targets.append(t.pos)
                
        for pos in fert_targets[:total_fert]:
            add(PRIORITY_FERTILIZE_CROP, "FERTILIZE", pos, kind="fertilize_crop")
            
        # Stage fertilizer pickup from shed if needed
        needed_pickup = len(fert_targets) - fert_held
        if needed_pickup > 0 and fert_in_shed > 0:
            grab_fert = min(fert_in_shed, needed_pickup)
            farmer_pos = tuple(farm_pos_of(ctx))
            target = min(SHED_ACCESS_TILES,
                         key=lambda tp: abs(tp[0] - farmer_pos[0]) + abs(tp[1] - farmer_pos[1]))
            add(PRIORITY_FEED_STAGING + 1, "PICKUP", tuple(target),
                args=["FERTILIZER", int(grab_fert)], kind="pickup_fertilizer")

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
                continue  # skip this crop's remaining instances, keep processing others

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
    """Greedy closest-unit dispatch. Returns per-unit actions + bookkeeping.
    
    v5.9: Tracks daily utilization and logs idle actions.
    """
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
        elif task["op"] == "FERTILIZE":
            return set(holders.get("FERTILIZER", []))
        elif task["op"] == "FEED":
            return set(holders.get("WHEAT", []))
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

    # v5.9: Fallback assignment for idle units to guarantee zero wasted actions
    # Default fallback priority: COLLECT_FERTILIZER -> WATER_MATURE/UNWATERED -> DIG_WEED
    unassigned_units = [idx for idx, _ in units if idx not in busy]
    if unassigned_units:
        targeted_positions = {tuple(t["target"]) for t in assignment.values() if t.get("target")}
        
        # 1. Fallback: collect any available fertilizer
        for t in farm.iter_tiles():
            if not unassigned_units:
                break
            if t.is_animal and t.fertilizer_available and tuple(t.pos) not in targeted_positions:
                best_u = min(unassigned_units, key=lambda u: abs(pos_by_idx[u][0] - t.x) + abs(pos_by_idx[u][1] - t.y))
                unassigned_units.remove(best_u)
                busy.add(best_u)
                task = {"priority": 10, "op": "COLLECT_FERTILIZER", "target": tuple(t.pos),
                        "args": [], "kind": "fallback_fert", "meta": {}, "unit_pos": pos_by_idx[best_u]}
                assignment[best_u] = task
                targeted_positions.add(tuple(t.pos))

        # 2. Fallback: water any mature or unwatered crop
        for t in farm.iter_tiles():
            if not unassigned_units:
                break
            if t.is_plant and not t.watered_today and tuple(t.pos) not in targeted_positions:
                best_u = min(unassigned_units, key=lambda u: abs(pos_by_idx[u][0] - t.x) + abs(pos_by_idx[u][1] - t.y))
                unassigned_units.remove(best_u)
                busy.add(best_u)
                task = {"priority": 10, "op": "WATER", "target": tuple(t.pos),
                        "args": [], "kind": "fallback_water", "meta": {}, "unit_pos": pos_by_idx[best_u]}
                assignment[best_u] = task
                targeted_positions.add(tuple(t.pos))

        # 3. Fallback: dig any weed on unlocked land
        for t in farm.iter_tiles():
            if not unassigned_units:
                break
            if t.kind == "WEED" and farm.quadrant_of(t.pos) in farm.unlocked and tuple(t.pos) not in targeted_positions:
                best_u = min(unassigned_units, key=lambda u: abs(pos_by_idx[u][0] - t.x) + abs(pos_by_idx[u][1] - t.y))
                unassigned_units.remove(best_u)
                busy.add(best_u)
                task = {"priority": 5, "op": "DIG", "target": tuple(t.pos),
                        "args": [], "kind": "fallback_dig", "meta": {}, "unit_pos": pos_by_idx[best_u]}
                assignment[best_u] = task
                targeted_positions.add(tuple(t.pos))

    actions = {idx: ["PASS"] for idx in range(len(units))}
    for idx, task in assignment.items():
        actions[idx] = emit(task)

    # v5.9: Track utilization across all 24 hours of the day
    _record_turn_utilization(ctx, len(units), actions)

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
    seed_units = sum(ctx["private"].seeds.values())
    empty_unlocked = sum(
        1 for t in ctx["farm"].iter_tiles()
        if t.kind == "EMPTY" and ctx["farm"].quadrant_of(t.pos) in ctx["farm"].unlocked
    )
    load += min(seed_units, empty_unlocked)
    return load
