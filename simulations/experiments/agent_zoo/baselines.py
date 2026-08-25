"""Wrappers for baseline agents."""


def pass_agent(obs):
    return {"farmer": ["PASS"], "hands": [], "market": []}


# Kaggle environments recognizes string names "random", "starter", "pass" natively in env.run(),
# but for internal python callables we can wrap or delegate them.
def random_agent(obs):
    # Fallback callable for random if called directly
    return {"farmer": ["PASS"], "hands": [], "market": []}


def starter_agent(obs):
    # Simple deterministic baseline
    step = obs.get("step", 0)
    player = obs["player"]
    me = obs["farms"][player]
    private = obs.get("private", {})
    seeds = private.get("seeds", {})
    shed = private.get("shed", {})
    market = []
    
    # Sell anything in shed
    for item, count in shed.items():
        if count > 0:
            market.append(["SELL", item, count])
            
    if step == 0 and me["money"] >= 10:
        market.append(["BUY_SEED", "WHEAT", 1])
        
    fx, fy = me["farmer"]
    tile = me["tiles"][fy][fx]
    
    if tile is None and seeds.get("WHEAT", 0) > 0:
        return {"farmer": ["PLANT", "WHEAT"], "hands": [], "market": market}
    if isinstance(tile, dict) and tile.get("kind") == "PLANT":
        crop_age = obs["day"] - tile["planted_day"]
        if crop_age >= 2:
            return {"farmer": ["HARVEST"], "hands": [], "market": market}
        if not tile.get("watered_today", False):
            return {"farmer": ["WATER"], "hands": [], "market": market}
            
    return {"farmer": ["PASS"], "hands": [], "market": market}
