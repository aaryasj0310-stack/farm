"""Archetype 4: Cow Milk Engine Agent.

Strategy:
- Builds 2 pastures, places 2 Cows ($400 each).
- Plants 4 Wheat tiles for feed.
- Feeds cows daily, Cares on off-days (+1 care bonus -> 2 milk every 2 days).
- Collects 2 free fertilizer/day ($100 each).
- Sells milk and fertilizer steadily.
"""


def _get_direction(fx, fy, tx, ty):
    if tx > fx: return "EAST"
    if tx < fx: return "WEST"
    if ty > fy: return "SOUTH"
    if ty < fy: return "NORTH"
    return "PASS"


def cow_milk_agent(obs):
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
    
    # 1. Market Orders
    for item in ["MILK", "FERTILIZER"]:
        count = shed.get(item, 0)
        if count > 0:
            market.append(["SELL", item, count])
            
    # Sell excess wheat
    wheat_in_shed = shed.get("WHEAT", 0)
    if wheat_in_shed > 10:
        market.append(["SELL", "WHEAT", wheat_in_shed - 6])
        
    # Hire 2 hands daily at turn 0
    if hour == 0 and money >= 2 and day < 29:
        market.append(["HIRE"])
        market.append(["HIRE"])
        
    # Buy 2 Cows early
    cow_count = shed.get("COW", 0)
    placed_cows = 0
    for y in range(5):
        for x in range(5):
            t = me["tiles"][y][x]
            if isinstance(t, dict) and t.get("animal") == "COW":
                placed_cows += 1
                
    if cow_count + placed_cows < 2 and money >= 400 and day < 5:
        market.append(["BUY_ANIMAL", "COW", 1])
        
    # Maintain ~4 wheat tiles
    if wheat_seeds < 4 and money >= 10 and day < 26:
        market.append(["BUY_SEED", "WHEAT", 2])
        
    # 2. Plan Pastures & Actions
    pasture_positions = [(1, 1), (1, 2)]
    wheat_positions = [(2, 1), (2, 2), (3, 1), (3, 2)]
    
    units = [me["farmer"]] + me.get("hands", [])
    unit_actions = []
    targeted = set()
    
    for u_idx, (ux, uy) in enumerate(units):
        action = ["PASS"]
        tile = me["tiles"][uy][ux]
        inv = private.get("inventories", [{}])[u_idx] if u_idx < len(private.get("inventories", [])) else {}
        has_cow = inv.get("COW", 0) > 0
        
        # Action on standing tile
        if (ux, uy) in pasture_positions:
            if tile is None:
                action = ["BUILD_PASTURE"]
            elif isinstance(tile, dict) and tile.get("kind") == "PASTURE" and "animal" not in tile:
                if has_cow:
                    action = ["PLACE", "COW"]
            elif isinstance(tile, dict) and tile.get("animal") == "COW":
                if not tile.get("fed_today", False):
                    action = ["FEED"]
                elif not tile.get("cared_today", False):
                    action = ["CARE"]
                elif tile.get("fertilizer_available", False):
                    action = ["COLLECT_FERTILIZER"]
                elif tile.get("yield_units", 0) > 0:
                    action = ["HARVEST"]
        elif (ux, uy) in [(4, 4), (5, 4), (4, 5), (5, 5)] and shed.get("COW", 0) > 0 and not has_cow:
            action = ["PICKUP", "COW", 1]
        elif (ux, uy) in wheat_positions:
            if tile is None and wheat_seeds > 0 and day < 27:
                action = ["PLANT", "WHEAT"]
            elif isinstance(tile, dict) and tile.get("kind") == "PLANT":
                crop_age = day - tile["planted_day"]
                if crop_age >= 4 or (day >= 28 and crop_age >= 2):
                    action = ["HARVEST"]
                elif not tile.get("watered_today", False):
                    action = ["WATER"]
        elif isinstance(tile, dict) and tile.get("kind") == "WEED":
            action = ["DIG"]
            
        # Pathfinding
        if action == ["PASS"]:
            best_target = None
            best_dist = 999
            
            if shed.get("COW", 0) > 0 and not has_cow:
                best_target = (4, 4)
            else:
                for px, py in pasture_positions:
                    if (px, py) in targeted: continue
                    t = me["tiles"][py][px]
                    needs_pasture = False
                    if t is None:
                        needs_pasture = True
                    elif isinstance(t, dict) and t.get("kind") == "PASTURE" and "animal" not in t and has_cow:
                        needs_pasture = True
                    elif isinstance(t, dict) and t.get("animal") == "COW":
                        if not t.get("fed_today", False) or not t.get("cared_today", False) or t.get("fertilizer_available", False) or t.get("yield_units", 0) > 0:
                            needs_pasture = True
                    if needs_pasture:
                        dist = abs(px - ux) + abs(py - uy)
                        if dist < best_dist:
                            best_dist = dist
                            best_target = (px, py)
                            
                if best_target is None:
                    for wx, wy in wheat_positions:
                        if (wx, wy) in targeted: continue
                        t = me["tiles"][wy][wx]
                        needs_wheat = False
                        if t is None and wheat_seeds > 0 and day < 27:
                            needs_wheat = True
                        elif isinstance(t, dict) and t.get("kind") == "PLANT":
                            if not t.get("watered_today", False) or t.get("yield_units", 0) > 0:
                                needs_wheat = True
                        if needs_wheat:
                            dist = abs(wx - ux) + abs(wy - uy)
                            if dist < best_dist:
                                best_dist = dist
                                best_target = (wx, wy)
                                
            if best_target is not None:
                targeted.add(best_target)
                tx, ty = best_target
                action = [_get_direction(ux, uy, tx, ty)]
                
        unit_actions.append(action)
        
    farmer_action = unit_actions[0] if unit_actions else ["PASS"]
    hands_actions = unit_actions[1:] if len(unit_actions) > 1 else []
    
    return {
        "farmer": farmer_action,
        "hands": hands_actions,
        "market": market[:10]
    }
