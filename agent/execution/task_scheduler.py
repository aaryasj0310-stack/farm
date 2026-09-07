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
    PORT_SW,
    SHED_ACCESS_TILES,
    TURNS_PER_DAY,
    C2_MAX_SPILLOVER_DIST,
    C2_SPILLOVER_PRIORITY_FLOOR,
    C6_CLUSTER_RADIUS,
    C6_CLUSTER_BONUS,
    log,
)
try:
    from state.observation_parser import crop_age, in_bonus_window, needs_water_today, turns_until_decay
except ImportError:
    from observation_parser import crop_age, in_bonus_window, needs_water_today, turns_until_decay
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
        try:
            from market.order_builder import hire_total_cost
            h_cost = hire_total_cost(n_hands)
        except (ImportError, NameError):
            def _f(n):
                a, b = 1, 1
                for _ in range(n):
                    a, b = b, a + b
                return a
            h_cost = sum(_f(i) for i in range(n_hands))
        
        _daily_log[day] = {
            "actions_available": tot_avail,
            "actions_used": tot_used,
            "idle_actions": tot_idle,
            "utilization_pct": round(100.0 * tot_used / max(1, tot_avail), 1),
            "shed_occupancy": shed_cnt,
            "quadrant_ownership": unlocked_cnt,
            "daily_hires": n_hands,
            "hire_cost": h_cost,
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
        # C5: Harvest Decision Logic
        if not cd["ongoing"]:
            # One-time crops (Wheat, Carrot, Melon)
            is_max_day = (age >= cd["max_yield_day"])
            is_max_yield = (t.yield_units >= cd["max_yield"])
            tud = turns_until_decay(t, ctx["step"])
            decay_imminent = (tud is not None and tud <= 4) or (age > cd["max_yield_day"]) or (hour >= 20 and is_max_day)
            is_endgame = (day == 29 and age >= cd["first_yield_day"])
            
            if t.yield_units > 0:
                if is_endgame:
                    # Day 29 endgame liquidation: realize all available yield before season end
                    add(PRIORITY_DECAY_HARVEST, "HARVEST", t.pos, kind="harvest_endgame")
                elif decay_imminent:
                    # Decay imminent: harvest to prevent crop decay
                    add(PRIORITY_DECAY_HARVEST, "HARVEST", t.pos, kind="harvest_decay")
                elif is_max_yield:
                    # Already at absolute max yield cap: harvest immediately frees tile for replanting
                    prio = PRIORITY_DECAY_HARVEST if is_max_day else PRIORITY_STANDARD_HARVEST
                    add(prio, "HARVEST", t.pos, kind="harvest_full")
                elif is_max_day and t.watered_today:
                    # Watered today on max day: collected final bonus yield, harvest before tomorrow's decay
                    add(PRIORITY_DECAY_HARVEST, "HARVEST", t.pos, kind="harvest_mature_watered")
                # When is_max_day and not t.watered_today and hour < 20:
                # Intentionally defer HARVEST so WATER executes first and collects +1 (+2) bonus!
        else:
            # Ongoing crops (Tomato, Strawberry)
            tud = turns_until_decay(t, ctx["step"])
            decay_imminent = (tud is not None and tud <= 24)
            is_endgame = (day >= 28)
            
            if t.yield_units > 0:
                if is_endgame or decay_imminent:
                    add(PRIORITY_DECAY_HARVEST, "HARVEST", t.pos, kind="harvest_ongoing_decay")
                elif t.yield_units >= 2:
                    # Efficient harvest of accumulated produce (2+ units per action)
                    add(PRIORITY_STANDARD_HARVEST, "HARVEST", t.pos, kind="harvest_ongoing_accum")
                elif t.yield_units >= cd["max_yield"]:
                    add(PRIORITY_STANDARD_HARVEST, "HARVEST", t.pos, kind="harvest_ongoing_cap")

        if not t.watered_today and hour < 23:
            dying_tomorrow = t.consecutive_unwatered >= 1
            if dying_tomorrow:
                # Guardrail 2: mandatory survival watering
                need_water.append((PRIORITY_URGENT_SURVIVAL, t))
            elif needs_water_today(t, day):
                is_newly_planted = (t.planted_day == day)
                if is_newly_planted:
                    prio = PRIORITY_BONUS_WATER + 5  # Urgent paired water for new plants
                elif in_bonus_window(t, day) or cd.get("ongoing"):
                    # Elevate bonus water on max_yield_day so it waters promptly before harvest
                    if not cd.get("ongoing") and age == cd["max_yield_day"]:
                        prio = PRIORITY_BONUS_WATER + 6
                    else:
                        prio = PRIORITY_BONUS_WATER
                else:
                    prio = 30
                if not macro.watering_enabled and day == 28 and in_bonus_window(t, day):
                    harvestable_by_29 = (t.planted_day is not None
                                         and t.planted_day + cd.get("max_yield_day", 99) <= 29)
                    if not harvestable_by_29:
                        continue
                need_water.append((prio, t))

    for prio, t in need_water:
        add(prio, "WATER", t.pos, kind="water")

    # ---------------- fertilizer application (Strawberries, Tomatoes, & Surplus Arbitrage) ----
    fert_in_shed = int(ctx["private"].shed.get("FERTILIZER", 0)) if ctx.get("private") else 0
    fert_held = sum(int(inv.get("FERTILIZER", 0)) for inv in (ctx["private"].inventories if ctx.get("private") else []))
    total_fert = fert_in_shed + fert_held
    
    if total_fert > 0 and hour < 20:
        # Live fertilizer spot price from market
        fert_spot_price = ctx["market"].prices.get("FERTILIZER", 100) if ctx.get("market") else 100
        
        tier1_strawberry = []
        tier2_tomato = []
        tier3_wheat = []
        tier4_carrot = []
        
        for t in plants:
            if t.fertilized_until_day < day:
                age = crop_age(t, day)
                # Tier 1: Strawberry 2-application precision (Ages 9-10 covers 10 & 12; Ages 13-14 covers 14 & 16)
                if t.crop == "STRAWBERRY" and (9 <= age <= 10 or 13 <= age <= 14):
                    tier1_strawberry.append(t.pos)
                # Tier 2: Tomato 2-application precision (Ages 7-8 covers 8, 9, 10; Ages 10-11 covers 11)
                elif t.crop == "TOMATO" and (7 <= age <= 8 or 10 <= age <= 11):
                    tier2_tomato.append(t.pos)
                # Tier 3: Surplus Wheat Arbitrage (applies when market price < $50, window ages 1-2)
                elif fert_spot_price < 50 and t.crop == "WHEAT" and (1 <= age <= 2):
                    tier3_wheat.append(t.pos)
                # Tier 4: Surplus Carrot Arbitrage (applies when market price < $35, window ages 1-2)
                elif fert_spot_price < 35 and t.crop == "CARROT" and (1 <= age <= 2):
                    tier4_carrot.append(t.pos)
                    
        # Prioritize Tier 1 -> Tier 2 -> Tier 3 -> Tier 4
        all_fert_targets = tier1_strawberry + tier2_tomato + tier3_wheat + tier4_carrot
        
        for pos in all_fert_targets[:total_fert]:
            add(PRIORITY_FERTILIZE_CROP, "FERTILIZE", pos, kind="fertilize_crop")
            
        # Stage fertilizer pickup from shed if needed
        needed_pickup = len(all_fert_targets[:total_fert]) - fert_held
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
        if t.yield_units > 0:
            add(PRIORITY_STANDARD_HARVEST + 5, "HARVEST", t.pos, kind="harvest_animal")
        if t.fertilizer_available:
            add(PRIORITY_FERT_COLLECT, "COLLECT_FERTILIZER", t.pos, kind="fert")
        want_care = macro.feeding_enabled and (CARE_GEESE or t.animal != "GOOSE")
        if want_care and not t.cared_today and hour < 21:
            add(PRIORITY_CARE_ANIMAL, "CARE", t.pos, kind="care")

    # WHEAT STAGING: engine FEED consumes the UNIT's inventory (never the
    # shed), so staged PICKUP tasks must run before any FEED can succeed.
    # Distribute wheat across multiple workers in small chunks (2-3 wheat)
    # so multiple workers can feed animals simultaneously!
    if feeds_due > 0:
        held = sum(int(inv.get("WHEAT", 0)) for inv in ctx["private"].inventories)
        shed_wheat = int(ctx["private"].shed.get("WHEAT", 0))
        needed = min(shed_wheat, max(feeds_due - held, 0))
        if needed > 0:
            chunk_size = 3
            n_chunks = (needed + chunk_size - 1) // chunk_size
            for c_idx in range(n_chunks):
                take = min(chunk_size, needed - c_idx * chunk_size)
                target = SHED_ACCESS_TILES[c_idx % len(SHED_ACCESS_TILES)]
                add(PRIORITY_FEED_STAGING, "PICKUP", tuple(target),
                    args=["WHEAT", int(take)], kind="pickup_wheat")

    # ---------------- planting queue (seed-conflict-safe) ----------------
    seeds = ctx["private"].seeds
    wanted_plants = list(macro.plant_queue)  # [(pos, crop)]
    # Planting cutoff at hour 17 ensures every newly planted seed can be watered before midnight
    if hour <= 17 and macro.watering_enabled:
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
    for task in macro.place_queue[:4]:
        add(PRIORITY_PLACE_ANIMAL, task["op"], task.get("target"),
            args=task.get("args", []),
            kind=task.get("kind", "place_animal"))

    # ---------------- weeds ----------------
    blocked = {tuple(p) for p, _ in macro.plant_queue}
    for t in ctx["farm"].iter_tiles():
        if t.kind == "WEED" and ctx["farm"].quadrant_of(t.pos) in ctx["farm"].unlocked and hour < 23:
            prio = PRIORITY_WEED_DIG + 15 if t.pos in blocked else PRIORITY_WEED_DIG
            add(prio, "DIG", t.pos, kind="dig")

    return tasks


def get_home_quadrant(u_idx, n_units, unlocked):
    """Stage 8B Phase 1E: C2 Adaptive Zonal Dispatch.
    
    Deterministic home quadrant mapping:
    - If SW unlocked and n_units >= 5:
      Rule W1 partitions the last 4 or 5 hands into SW squad.
      Remaining non-SW hands are split evenly between NW and NE squads.
    - If NE unlocked:
      Units are split evenly between NW and NE squads.
    - If only NW unlocked:
      All units belong to NW squad.
    """
    if "SW" in unlocked and n_units >= 5:
        sw_squad_size = 5 if n_units >= 13 else 4
        sw_start = n_units - sw_squad_size
        if u_idx >= sw_start:
            return "SW"
        non_sw = sw_start
        half = max(1, non_sw // 2)
        return "NW" if u_idx < half else "NE"
    elif "NE" in unlocked:
        half = max(1, n_units // 2)
        return "NW" if u_idx < half else "NE"
    else:
        return "NW"


def assign_tasks(tasks, ctx, extra_units=()):
    """C2 Adaptive Zonal Dispatch + Greedy closest-unit assignment.
    
    Stage 8B Phase 1E:
    - Prioritizes home-zone workers for tasks in their preferred quadrant.
    - Permits controlled cross-zone spillover only when the home zone is underutilized.
    - Enforces travel distance threshold and prohibits diagonal jumps (SW <-> NE).
    - Preserves Rule W1/W2 SW squad partitioning, PORT_SW anchors, and shortest path routing.
    - Tracks daily utilization and logs idle actions.
    """
    farm = ctx["farm"]
    units = [(0, tuple(farm.farmer))]
    for i, h in enumerate(farm.hands):
        units.append((i + 1, tuple(h)))
    for idx, pos in extra_units:
        units.append((idx, tuple(pos)))
    pos_by_idx = dict(units)
    n_units = len(units)

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

    # Stage 8B Phase 1E (C2): Deterministic home quadrants + Rule W1 SW squad preservation
    home_quads = {u_idx: get_home_quadrant(u_idx, n_units, farm.unlocked) for u_idx in range(n_units)}
    sw_units = {u_idx for u_idx, q in home_quads.items() if q == "SW"}

    # Stage 8B Phase 1F: Separate urgent tasks from regular tasks
    urgent_tasks = []
    regular_tasks = []

    for t in tasks:
        tgt = t.get("target") or tuple(farm.farmer)
        t_quad = farm.quadrant_of(tgt)
        if t["op"] not in ("PICKUP", "PASS") and t_quad not in farm.unlocked:
            continue
        prio = t.get("priority", 0)
        is_urgent = (prio >= PRIORITY_URGENT_SURVIVAL or t.get("kind") in ("feed_rescue", "harvest_decay"))
        if is_urgent:
            urgent_tasks.append(t)
        else:
            regular_tasks.append(t)

    busy = set()
    assignment = {}          # unit_idx -> task
    deferred_place = []

    # 1. Tier 1: Urgent survival tasks dispatched immediately to closest capable worker
    for task in sorted(urgent_tasks, key=lambda t: -t.get("priority", 0)):
        eligible = _eligible(task)
        free_units = [u[0] for u in units if u[0] not in busy]
        if eligible is not None:
            free_units = [u for u in free_units if u in eligible]
        if not free_units:
            continue
        target = task.get("target") or tuple(farm.farmer)
        best = min(free_units, key=lambda u: abs(pos_by_idx[u][0] - target[0]) + abs(pos_by_idx[u][1] - target[1]))
        busy.add(best)
        task["unit_pos"] = pos_by_idx[best]
        assignment[best] = task

    # 2. Tier 2: Regular tasks with C2 Zonal Hierarchy + C6 Clustered Dispatch
    tasks_by_quad = {"NW": 0, "NE": 0, "SW": 0, "SE": 0}
    for t in regular_tasks:
        tgt = t.get("target") or tuple(farm.farmer)
        q = farm.quadrant_of(tgt)
        tasks_by_quad[q] = tasks_by_quad.get(q, 0) + 1
    unassigned_home_tasks = dict(tasks_by_quad)

    remaining_tasks = list(regular_tasks)

    while remaining_tasks and len(busy) < len(units):
        free_units = [u[0] for u in units if u[0] not in busy]
        if not free_units:
            break

        max_prio = max(t.get("priority", 0) for t in remaining_tasks)
        band_tasks = [t for t in remaining_tasks if t.get("priority", 0) >= max_prio - 2]

        best_match = None  # (score, d, target, u, task, target_quad)

        for task in band_tasks:
            eligible = _eligible(task)
            if eligible is not None and not eligible:
                deferred_place.append(task)
                continue
            cands = [u for u in free_units if eligible is None or u in eligible]
            if not cands:
                continue
            target = task.get("target") or tuple(farm.farmer)
            target_quad = farm.quadrant_of(target)
            prio = task.get("priority", 0)

            # C2 Zonal Eligibility
            home_cands = [u for u in cands if home_quads[u] == target_quad]
            if home_cands:
                eval_cands = [(u, False) for u in home_cands]
            else:
                eval_cands = []
                for u in cands:
                    u_home = home_quads[u]
                    free_in_home = sum(1 for fu in free_units if home_quads[fu] == u_home)
                    rem_tasks_home = unassigned_home_tasks.get(u_home, 0)
                    if rem_tasks_home < free_in_home:
                        if not ((u_home == "SW" and target_quad == "NE") or (u_home == "NE" and target_quad == "SW")):
                            d = abs(pos_by_idx[u][0] - target[0]) + abs(pos_by_idx[u][1] - target[1])
                            if d <= C2_MAX_SPILLOVER_DIST and prio >= C2_SPILLOVER_PRIORITY_FLOOR:
                                eval_cands.append((u, True))

            for u, is_spillover in eval_cands:
                d = abs(pos_by_idx[u][0] - target[0]) + abs(pos_by_idx[u][1] - target[1])
                cluster_bonus = 0
                if d <= C6_CLUSTER_RADIUS:
                    cluster_bonus += C6_CLUSTER_BONUS
                if d == 0:
                    cluster_bonus += C6_CLUSTER_BONUS
                spill_penalty = 10 if is_spillover else 0
                effective_score = (-prio * 10) + spill_penalty + (d - cluster_bonus)

                match_key = (effective_score, d, target, u)
                if best_match is None or match_key < best_match[0]:
                    best_match = (match_key, u, task, target_quad)

        if best_match is None:
            for t in band_tasks:
                remaining_tasks.remove(t)
            continue

        _, chosen_u, chosen_task, t_quad = best_match
        busy.add(chosen_u)
        remaining_tasks.remove(chosen_task)
        if t_quad in unassigned_home_tasks:
            unassigned_home_tasks[t_quad] = max(0, unassigned_home_tasks[t_quad] - 1)

        # Rule W2: SW squad hands anchor shed PICKUP at PORT_SW
        if chosen_u in sw_units and chosen_task.get("op") == "PICKUP" and chosen_task.get("target") in SHED_ACCESS_TILES:
            chosen_task["target"] = PORT_SW

        chosen_task["unit_pos"] = pos_by_idx[chosen_u]
        assignment[chosen_u] = chosen_task

    # v5.9: Fallback assignment for idle units to guarantee zero wasted actions
    # Default fallback priority: COLLECT_FERTILIZER -> WATER_MATURE/UNWATERED -> DIG_WEED
    unassigned_units = [idx for idx, _ in units if idx not in busy]
    if unassigned_units:
        targeted_positions = {tuple(t["target"]) for t in assignment.values() if t.get("target")}

        def _pick_best_unit(cands, target_pos):
            return min(cands, key=lambda u: abs(pos_by_idx[u][0] - target_pos[0]) + abs(pos_by_idx[u][1] - target_pos[1]))

        # 1. Fallback: collect any available fertilizer (prefer local home zone)
        for t in farm.iter_tiles():
            if not unassigned_units:
                break
            if t.is_animal and t.fertilizer_available and tuple(t.pos) not in targeted_positions:
                t_quad = farm.quadrant_of(t.pos)
                pref = [u for u in unassigned_units if home_quads[u] == t_quad]
                cands = pref if pref else [u for u in unassigned_units if not ((home_quads[u] == "SW" and t_quad == "NE") or (home_quads[u] == "NE" and t_quad == "SW"))]
                if not cands: cands = unassigned_units
                best_u = _pick_best_unit(cands, t.pos)
                unassigned_units.remove(best_u)
                busy.add(best_u)
                assignment[best_u] = {"priority": 10, "op": "COLLECT_FERTILIZER", "target": tuple(t.pos),
                                      "args": [], "kind": "fallback_fert", "meta": {}, "unit_pos": pos_by_idx[best_u]}
                targeted_positions.add(tuple(t.pos))

        # 2. Fallback: water any mature or unwatered crop (prefer local home zone)
        for t in farm.iter_tiles():
            if not unassigned_units:
                break
            if t.is_plant and not t.watered_today and tuple(t.pos) not in targeted_positions:
                t_quad = farm.quadrant_of(t.pos)
                pref = [u for u in unassigned_units if home_quads[u] == t_quad]
                cands = pref if pref else [u for u in unassigned_units if not ((home_quads[u] == "SW" and t_quad == "NE") or (home_quads[u] == "NE" and t_quad == "SW"))]
                if not cands: cands = unassigned_units
                best_u = _pick_best_unit(cands, t.pos)
                unassigned_units.remove(best_u)
                busy.add(best_u)
                assignment[best_u] = {"priority": 10, "op": "WATER", "target": tuple(t.pos),
                                      "args": [], "kind": "fallback_water", "meta": {}, "unit_pos": pos_by_idx[best_u]}
                targeted_positions.add(tuple(t.pos))

        # 3. Fallback: dig any weed on unlocked land (prefer local home zone)
        for t in farm.iter_tiles():
            if not unassigned_units:
                break
            if t.kind == "WEED" and farm.quadrant_of(t.pos) in farm.unlocked and tuple(t.pos) not in targeted_positions:
                t_quad = farm.quadrant_of(t.pos)
                pref = [u for u in unassigned_units if home_quads[u] == t_quad]
                cands = pref if pref else [u for u in unassigned_units if not ((home_quads[u] == "SW" and t_quad == "NE") or (home_quads[u] == "NE" and t_quad == "SW"))]
                if not cands: cands = unassigned_units
                best_u = _pick_best_unit(cands, t.pos)
                unassigned_units.remove(best_u)
                busy.add(best_u)
                assignment[best_u] = {"priority": 5, "op": "DIG", "target": tuple(t.pos),
                                      "args": [], "kind": "fallback_dig", "meta": {}, "unit_pos": pos_by_idx[best_u]}
                targeted_positions.add(tuple(t.pos))

        # Rule W2 anchor: Send remaining idle SW squad hands to PORT_SW
        if sw_units:
            for u in list(unassigned_units):
                if u in sw_units:
                    pos = pos_by_idx[u]
                    if pos != PORT_SW:
                        task = {"priority": 1, "op": "PASS", "target": PORT_SW,
                                "args": [], "kind": "sw_anchor", "meta": {}, "unit_pos": pos}
                        assignment[u] = task
                        busy.add(u)
                        unassigned_units.remove(u)

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
        "deferred_place": [(t.get("args") or [None])[0] for t in deferred_place],
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
