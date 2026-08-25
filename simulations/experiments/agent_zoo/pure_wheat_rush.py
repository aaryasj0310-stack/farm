"""Archetype 1: Pure Wheat Rush Agent.

Tests maximum early cashflow velocity:
- Spends initial capital on Wheat seeds (arriving turn 1).
- Hires 2 hands daily at turn 0 to manage 24 tiles in the NW quadrant.
- Waters daily during bonus window (days 2-4) to hit max yield (4).
- Harvests and sells immediately, buying seeds to replant continuously.
"""


def _get_direction(fx, fy, tx, ty):
    if tx > fx: return "EAST"
    if tx < fx: return "WEST"
    if ty > fy: return "SOUTH"
    if ty < fy: return "NORTH"
    return "PASS"


def pure_wheat_rush_agent(obs):
    player = obs["player"]
    me = obs["farms"][player]
    private = obs.get("private", {})
    day = obs.get("day", 0)
    hour = obs.get("hour", 0)
    money = me["money"]
    seeds = private.get("seeds", {})
    shed = private.get("shed", {})
    wheat_seeds = seeds.get("WHEAT", 0)
    
    market = []
    
    # 1. Market Orders: Sell harvested wheat immediately from shed
    wheat_in_shed = shed.get("WHEAT", 0)
    if wheat_in_shed > 0:
        market.append(["SELL", "WHEAT", wheat_in_shed])
        
    # Hire 2 hands on turn 0 of every day (costs 1 + 1 = $2)
    if hour == 0:
        if money >= 2 and day < 28:
            market.append(["HIRE"])
            market.append(["HIRE"])
            
    # Buy wheat seeds if low on seeds and before endgame
    if day < 26:
        # Check how many empty unlocked tiles we have
        empty_tiles = 0
        for y in range(5):
            for x in range(5):
                if me["tiles"][y][x] is None:
                    empty_tiles += 1
        needed = max(0, empty_tiles - wheat_seeds)
        if needed > 0 and money >= 10:
            buy_count = min(needed, int(money // 10), 10)
            if buy_count > 0:
                market.append(["BUY_SEED", "WHEAT", buy_count])

    # 2. Assign Unit Actions (Farmer + Hands)
    units = [me["farmer"]] + me.get("hands", [])
    unit_actions = []
    
    # Target grid in NW quadrant: (0..4, 0..4) excluding shed center tile (4,4)
    nw_tiles = [(x, y) for y in range(5) for x in range(5)]
    
    # Track reserved tiles this turn to prevent duplicate work
    targeted_tiles = set()
    seeds_left = wheat_seeds
    
    for u_idx, (ux, uy) in enumerate(units):
        action = ["PASS"]
        current_tile = me["tiles"][uy][ux]
        
        # Priority 1: Action on current standing tile
        if isinstance(current_tile, dict) and current_tile.get("kind") == "PLANT":
            crop_age = day - current_tile["planted_day"]
            # Harvest if mature (day 4+) or decaying
            if crop_age >= 4 or (day < 30 and day >= 28 and crop_age >= 2):
                action = ["HARVEST"]
            elif not current_tile.get("watered_today", False):
                action = ["WATER"]
        elif current_tile is None and seeds_left > 0 and day < 27:
            action = ["PLANT", "WHEAT"]
            seeds_left -= 1
        elif isinstance(current_tile, dict) and current_tile.get("kind") == "WEED":
            action = ["DIG"]
            
        # Priority 2: If standing tile needed no action, find closest work tile
        if action == ["PASS"]:
            best_dist = 999
            best_target = None
            
            for tx, ty in nw_tiles:
                if (tx, ty) in targeted_tiles:
                    continue
                t = me["tiles"][ty][tx]
                needs_work = False
                
                if isinstance(t, dict) and t.get("kind") == "PLANT":
                    crop_age = day - t["planted_day"]
                    if (crop_age >= 4 and t.get("yield_units", 0) > 0) or not t.get("watered_today", False):
                        needs_work = True
                elif t is None and seeds_left > 0 and day < 27:
                    needs_work = True
                elif isinstance(t, dict) and t.get("kind") == "WEED":
                    needs_work = True
                    
                if needs_work:
                    dist = abs(tx - ux) + abs(ty - uy)
                    if dist < best_dist:
                        best_dist = dist
                        best_target = (tx, ty)
                        
            if best_target is not None:
                targeted_tiles.add(best_target)
                tx, ty = best_target
                move_dir = _get_direction(ux, uy, tx, ty)
                action = [move_dir]
                
        unit_actions.append(action)
        
    farmer_action = unit_actions[0] if unit_actions else ["PASS"]
    hands_actions = unit_actions[1:] if len(unit_actions) > 1 else []
    
    return {
        "farmer": farmer_action,
        "hands": hands_actions,
        "market": market[:10]
    }
