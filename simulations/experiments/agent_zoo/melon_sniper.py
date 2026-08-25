"""Archetype 3: Melon Sniper Agent (Fertilized & Unfertilized variants).

Strategy:
- Plants 8 Melons in NW quadrant on Day 0.
- Fertilized variant: Buys & applies Fertilizer on Day 5 (active Days 6-8).
- Waters in window 6-12 to hit max yield (6) on Day 8.
- Obeys hard harvest gate at Day 10 (first_yield_day).
- Drip-sells 2 melons per turn on turns t % 4 == 1 to maximize price retention.
"""


def _get_direction(fx, fy, tx, ty):
    if tx > fx: return "EAST"
    if tx < fx: return "WEST"
    if ty > fy: return "SOUTH"
    if ty < fy: return "NORTH"
    return "PASS"


def _make_melon_agent(use_fertilizer=True):
    def agent(obs):
        player = obs["player"]
        me = obs["farms"][player]
        private = obs.get("private", {})
        day = obs.get("day", 0)
        hour = obs.get("hour", 0)
        money = me["money"]
        seeds = private.get("seeds", {})
        shed = private.get("shed", {})
        melon_seeds = seeds.get("MELON", 0)
        
        market = []
        
        # 1. Market Orders
        # Drip-sell Melons: 2 per turn on post-shop tick (hour % 4 == 1) or dump on Day 30
        melons_in_shed = shed.get("MELON", 0)
        if melons_in_shed > 0:
            if day >= 29:
                # Endgame dump
                market.append(["SELL", "MELON", min(melons_in_shed, 10)])
            elif hour % 4 == 1:
                # Drip sell 2 units
                market.append(["SELL", "MELON", min(melons_in_shed, 2)])
                
        # Buy Melon seeds on Day 0
        if day == 0 and hour == 0 and money >= 80 * 8:
            market.append(["BUY_SEED", "MELON", 8])
            
        # Buy Fertilizer on Day 4 (to apply on Day 5)
        if use_fertilizer and day == 4 and hour == 0 and money >= 100 * 8:
            market.append(["BUY_PRODUCT", "FERTILIZER", 8])
            
        # Hire 1 hand on watering days
        if hour == 0 and day >= 6 and money >= 1:
            market.append(["HIRE"])
            
        # 2. Assign Unit Actions
        melon_positions = [(x, y) for y in range(1, 4) for x in range(1, 4) if not (x == 2 and y == 2)]  # 8 tiles
        units = [me["farmer"]] + me.get("hands", [])
        unit_actions = []
        targeted = set()
        
        for u_idx, (ux, uy) in enumerate(units):
            action = ["PASS"]
            tile = me["tiles"][uy][ux]
            inv = private.get("inventories", [{}])[u_idx] if u_idx < len(private.get("inventories", [])) else {}
            
            # Action on standing tile
            if (ux, uy) in melon_positions:
                if tile is None and melon_seeds > 0 and day < 20:
                    action = ["PLANT", "MELON"]
                elif isinstance(tile, dict) and tile.get("kind") == "PLANT":
                    crop_age = day - tile["planted_day"]
                    # Apply fertilizer on Day 5 (age 5)
                    if use_fertilizer and crop_age == 5 and tile.get("fertilized_until_day", -1) < day:
                        if inv.get("FERTILIZER", 0) > 0:
                            action = ["FERTILIZE"]
                        elif shed.get("FERTILIZER", 0) > 0 and (ux, uy) in [(4, 4), (1, 1)]:
                            action = ["PICKUP", "FERTILIZER", 1]
                    # Harvest only once day >= 10 (hard gate)
                    elif crop_age >= 10 and tile.get("yield_units", 0) > 0:
                        action = ["HARVEST"]
                    # Water during window 6-12 (or day 0)
                    elif (crop_age >= 6 or crop_age == 0) and not tile.get("watered_today", False):
                        action = ["WATER"]
            elif isinstance(tile, dict) and tile.get("kind") == "WEED":
                action = ["DIG"]
                
            # If standing tile needed nothing, path to target
            if action == ["PASS"]:
                best_target = None
                best_dist = 999
                for tx, ty in melon_positions:
                    if (tx, ty) in targeted: continue
                    t = me["tiles"][ty][tx]
                    needs_work = False
                    if t is None and melon_seeds > 0 and day < 20:
                        needs_work = True
                    elif isinstance(t, dict) and t.get("kind") == "PLANT":
                        age = day - t["planted_day"]
                        if age >= 10 and t.get("yield_units", 0) > 0:
                            needs_work = True
                        elif (age >= 6 or age == 0) and not t.get("watered_today", False):
                            needs_work = True
                        elif use_fertilizer and age == 5 and t.get("fertilized_until_day", -1) < day:
                            needs_work = True
                    if needs_work:
                        dist = abs(tx - ux) + abs(ty - uy)
                        if dist < best_dist:
                            best_dist = dist
                            best_target = (tx, ty)
                            
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


melon_sniper_agent = _make_melon_agent(use_fertilizer=True)
melon_unfertilized_agent = _make_melon_agent(use_fertilizer=False)
