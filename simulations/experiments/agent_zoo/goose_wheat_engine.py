"""Archetype 2: Goose-Wheat Engine Agent (with Care & No-Care variants).

Strategy:
- Builds 3 coops, places 3 Geese.
- Plants 6 Wheat tiles for sustainable feed.
- Feeds daily, Cares daily (yielding 2 eggs/day under v1.32.7).
- Collects daily free fertilizer ($100 base) from every goose.
- Sells eggs and fertilizer steadily.
"""


def _get_direction(fx, fy, tx, ty):
    if tx > fx: return "EAST"
    if tx < fx: return "WEST"
    if ty > fy: return "SOUTH"
    if ty < fy: return "NORTH"
    return "PASS"


def _make_goose_agent(use_care=True):
    def agent(obs):
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
        # Sell eggs and fertilizer from shed
        for item in ["EGG", "FERTILIZER"]:
            count = shed.get(item, 0)
            if count > 0:
                market.append(["SELL", item, count])
                
        # Sell excess wheat if we have > 10 stored
        wheat_in_shed = shed.get("WHEAT", 0)
        if wheat_in_shed > 10:
            market.append(["SELL", "WHEAT", wheat_in_shed - 6])
            
        # Hire 2 hands daily at turn 0
        if hour == 0 and money >= 2 and day < 29:
            market.append(["HIRE"])
            market.append(["HIRE"])
            
        # Buy Geese early (target 3 geese)
        goose_count = shed.get("GOOSE", 0)
        placed_geese = 0
        for y in range(5):
            for x in range(5):
                t = me["tiles"][y][x]
                if isinstance(t, dict) and t.get("animal") == "GOOSE":
                    placed_geese += 1
                    
        total_geese = goose_count + placed_geese
        if total_geese < 3 and money >= 300 and day < 5:
            market.append(["BUY_ANIMAL", "GOOSE", 1])
            
        # Maintain ~6 wheat seeds/plants
        wheat_tiles = 0
        for y in range(5):
            for x in range(5):
                t = me["tiles"][y][x]
                if isinstance(t, dict) and t.get("crop") == "WHEAT":
                    wheat_tiles += 1
        if wheat_tiles + wheat_seeds < 6 and money >= 10 and day < 26:
            market.append(["BUY_SEED", "WHEAT", 3])
            
        # 2. Plan Coops & Actions
        coop_positions = [(1, 1), (1, 2), (1, 3)]
        wheat_positions = [(2, 1), (2, 2), (2, 3), (3, 1), (3, 2), (3, 3)]
        
        units = [me["farmer"]] + me.get("hands", [])
        unit_actions = []
        targeted = set()
        
        for u_idx, (ux, uy) in enumerate(units):
            action = ["PASS"]
            tile = me["tiles"][uy][ux]
            inv = private.get("inventories", [{}])[u_idx] if u_idx < len(private.get("inventories", [])) else {}
            has_goose = inv.get("GOOSE", 0) > 0
            
            # Action on standing tile
            if (ux, uy) in coop_positions:
                if tile is None:
                    action = ["BUILD_COOP"]
                elif isinstance(tile, dict) and tile.get("kind") == "COOP" and "animal" not in tile:
                    if has_goose:
                        action = ["PLACE", "GOOSE"]
                elif isinstance(tile, dict) and tile.get("animal") == "GOOSE":
                    if not tile.get("fed_today", False):
                        action = ["FEED"]
                    elif use_care and not tile.get("cared_today", False):
                        action = ["CARE"]
                    elif tile.get("fertilizer_available", False):
                        action = ["COLLECT_FERTILIZER"]
                    elif tile.get("yield_units", 0) > 0:
                        action = ["HARVEST"]
            elif (ux, uy) in [(4, 4), (5, 4), (4, 5), (5, 5)] and shed.get("GOOSE", 0) > 0 and not has_goose:
                # Pickup goose from shed
                action = ["PICKUP", "GOOSE", 1]
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
                
                # Check if we need to pick up a goose from shed first
                if shed.get("GOOSE", 0) > 0 and not has_goose:
                    best_target = (4, 4)
                else:
                    # Check coop work
                    for cx, cy in coop_positions:
                        if (cx, cy) in targeted: continue
                        t = me["tiles"][cy][cx]
                        needs_coop = False
                        if t is None:
                            needs_coop = True
                        elif isinstance(t, dict) and t.get("kind") == "COOP" and "animal" not in t and has_goose:
                            needs_coop = True
                        elif isinstance(t, dict) and t.get("animal") == "GOOSE":
                            if not t.get("fed_today", False) or (use_care and not t.get("cared_today", False)) or t.get("fertilizer_available", False) or t.get("yield_units", 0) > 0:
                                needs_coop = True
                        if needs_coop:
                            dist = abs(cx - ux) + abs(cy - uy)
                            if dist < best_dist:
                                best_dist = dist
                                best_target = (cx, cy)
                                
                    # Check wheat work
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
    return agent


goose_wheat_agent = _make_goose_agent(use_care=True)
goose_no_care_agent = _make_goose_agent(use_care=False)
