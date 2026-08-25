"""Archetype 5: Full Production Agent (Phase C Candidate).

Implements the 5-layer decoupled architecture:
1. State Tracker & Clock (turn, day, shop unlocks, decay timers)
2. Macro Strategy Planner (Phase 1 Wheat Cash -> Phase 2 Animals & Fertilizer -> Phase 3 Shop Pivots -> Phase 4 Liquidation)
3. Priority-Queue Task Scheduler (Survival > Prod-Day Feed > Fertilizer > Bonus Water > Care > Harvest > Plant+Water > Dig)
4. Spatial Navigator with locked-tile shortcuts
5. Microstructure Market Brain (Post-shop tick selling on t % 4 == 1, batch limit Q*, same-turn buy-1-ahead)
"""


def _get_direction(fx, fy, tx, ty):
    if tx > fx: return "EAST"
    if tx < fx: return "WEST"
    if ty > fy: return "SOUTH"
    if ty < fy: return "NORTH"
    return "PASS"


def full_production_agent(obs):
    step = obs.get("step", 0)
    day = obs.get("day", 0)
    hour = obs.get("hour", 0)
    player = obs["player"]
    me = obs["farms"][player]
    private = obs.get("private", {})
    market_data = obs.get("market", {})
    town = obs.get("town", {})
    unlocked_shops = town.get("unlocked_shops", [])
    
    money = me["money"]
    seeds = private.get("seeds", {})
    shed = private.get("shed", {})
    farmer_pos = me["farmer"]
    hands_pos = me.get("hands", [])
    unlocked_quads = me.get("unlocked_quadrants", ["NW"])
    
    market = []
    
    # -------------------------------------------------------------
    # 1. MARKET BRAIN & LIQUIDATION ENGINE
    # -------------------------------------------------------------
    is_sell_turn = (hour % 4 == 1) or (day >= 29)
    
    if is_sell_turn:
        for product in ["MELON", "STRAWBERRY", "MILK", "WOOL", "FERTILIZER", "EGG", "TOMATO", "CARROT"]:
            count = shed.get(product, 0)
            if count > 0:
                batch_limit = 2 if product in ["MELON", "STRAWBERRY", "MILK", "WOOL"] and day < 29 else min(count, 10)
                market.append(["SELL", product, min(count, batch_limit)])
                
        wheat_in_shed = shed.get("WHEAT", 0)
        if wheat_in_shed > 12:
            market.append(["SELL", "WHEAT", min(wheat_in_shed - 8, 10)])
            
    if hour == 0 and day < 29:
        hands_to_hire = 3 if money >= 1500 and len(unlocked_quads) > 1 else (2 if money >= 100 else 1)
        for _ in range(hands_to_hire):
            market.append(["HIRE"])
            
    if len(unlocked_quads) == 1 and money >= 2200 and day < 20:
        market.append(["BUY_LAND"])
        
    if day == 0 and hour == 0 and money >= 200:
        market.append(["BUY_SEED", "WHEAT", 15])
        
    goose_in_shed = shed.get("GOOSE", 0)
    placed_geese = 0
    for y in range(10):
        for x in range(10):
            t = me["tiles"][y][x]
            if isinstance(t, dict) and t.get("animal") == "GOOSE":
                placed_geese += 1
    if goose_in_shed + placed_geese < 2 and money >= 350 and 2 <= day <= 15:
        market.append(["BUY_ANIMAL", "GOOSE", 1])
        
    if "PET_CAFE" in unlocked_shops and seeds.get("CARROT", 0) < 6 and money >= 100 and day < 24:
        market.append(["BUY_SEED", "CARROT", 4])
    elif seeds.get("WHEAT", 0) < 8 and money >= 80 and day < 26:
        market.append(["BUY_SEED", "WHEAT", 6])
        
    # -------------------------------------------------------------
    # 2. TASK SCHEDULER & SPATIAL EXECUTION
    # -------------------------------------------------------------
    units = [farmer_pos] + hands_pos
    unit_actions = []
    targeted_tiles = set()
    coop_spots = [(1, 1), (1, 2)]
    
    for u_idx, (ux, uy) in enumerate(units):
        action = ["PASS"]
        tile = me["tiles"][uy][ux]
        inv = private.get("inventories", [{}])[u_idx] if u_idx < len(private.get("inventories", [])) else {}
        has_goose = inv.get("GOOSE", 0) > 0
        
        # Immediate Tile Actions
        if (ux, uy) in coop_spots:
            if tile is None:
                action = ["BUILD_COOP"]
            elif isinstance(tile, dict) and tile.get("kind") == "COOP" and "animal" not in tile:
                if has_goose:
                    action = ["PLACE", "GOOSE"]
            elif isinstance(tile, dict) and tile.get("animal") == "GOOSE":
                if not tile.get("fed_today", False):
                    action = ["FEED"]
                elif not tile.get("cared_today", False):
                    action = ["CARE"]
                elif tile.get("fertilizer_available", False):
                    action = ["COLLECT_FERTILIZER"]
                elif tile.get("yield_units", 0) > 0:
                    action = ["HARVEST"]
        elif (ux, uy) in [(4, 4), (5, 4), (4, 5), (5, 5)] and shed.get("GOOSE", 0) > 0 and not has_goose:
            action = ["PICKUP", "GOOSE", 1]
        elif isinstance(tile, dict) and tile.get("kind") == "PLANT":
            crop_age = day - tile["planted_day"]
            crop_name = tile["crop"]
            if (crop_name == "WHEAT" and crop_age >= 4) or \
               (crop_name == "CARROT" and crop_age >= 3) or \
               (crop_name == "MELON" and crop_age >= 10 and tile.get("yield_units", 0) > 0) or \
               (day >= 28 and crop_age >= 2):
                action = ["HARVEST"]
            elif not tile.get("watered_today", False):
                action = ["WATER"]
        elif tile is None and day < 27:
            if seeds.get("CARROT", 0) > 0:
                action = ["PLANT", "CARROT"]
            elif seeds.get("WHEAT", 0) > 0:
                action = ["PLANT", "WHEAT"]
        elif isinstance(tile, dict) and tile.get("kind") == "WEED":
            action = ["DIG"]
            
        # Pathfinding
        if action == ["PASS"]:
            best_target = None
            best_dist = 999
            
            if shed.get("GOOSE", 0) > 0 and not has_goose:
                best_target = (4, 4)
            else:
                accessible_coords = [(x, y) for y in range(5) for x in range(5)]
                if "NE" in unlocked_quads:
                    accessible_coords += [(x, y) for y in range(5) for x in range(5, 10)]
                    
                for tx, ty in accessible_coords:
                    if (tx, ty) in targeted_tiles:
                        continue
                    t = me["tiles"][ty][tx]
                    needs_work = False
                    
                    if (tx, ty) in coop_spots:
                        if t is None:
                            needs_work = True
                        elif isinstance(t, dict) and t.get("kind") == "COOP" and "animal" not in t and has_goose:
                            needs_work = True
                        elif isinstance(t, dict) and t.get("animal") == "GOOSE":
                            if not t.get("fed_today", False) or not t.get("cared_today", False) or t.get("fertilizer_available", False) or t.get("yield_units", 0) > 0:
                                needs_work = True
                    elif isinstance(t, dict) and t.get("kind") == "PLANT":
                        crop_age = day - t["planted_day"]
                        if (crop_age >= 4 and t.get("yield_units", 0) > 0) or not t.get("watered_today", False):
                            needs_work = True
                    elif t is None and (seeds.get("WHEAT", 0) > 0 or seeds.get("CARROT", 0) > 0) and day < 27:
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
                action = [_get_direction(ux, uy, tx, ty)]
                
        unit_actions.append(action)
        
    farmer_action = unit_actions[0] if unit_actions else ["PASS"]
    hands_actions = unit_actions[1:] if len(unit_actions) > 1 else []
    
    return {
        "farmer": farmer_action,
        "hands": hands_actions,
        "market": market[:10]
    }
