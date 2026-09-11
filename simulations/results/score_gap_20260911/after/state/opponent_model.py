"""Opponent model: public farm scan + market-ledger inference + delta detection.

Phase 1 of the opponent modelling system:
  - snapshot_opponent_farm: compact state representation of all opponent tiles
  - detect_tile_deltas: harvest, planting, animal purchase/collection events
  - infer_turn_transactions: reconcile money + market deltas to detect sales

Phase 2 — Production Forecasting (Pillar 1):
  - forecast_opponent_production: exact forward schedule of harvests/yields
  - get_imminent_harvests: currently ripe uncollected produce on field
  - summarize_opponent_commitments: portfolio allocation percentages

Phase 3 — Shed Inference & Sell Prediction (Pillars 2 & 3):
  - update_opponent_shed_estimate: probabilistic shed reconstruction
  - compute_opponent_sell_probabilities: multi-signal sell scoring
  - predict_imminent_dumps: dump volume estimation
"""
from collections import defaultdict
from config import ANIMALS, CROPS, PRODUCTS, SHED_CAPACITY, SHED_ACCESS_TILES
from observation_parser import crop_age


# ---------------------------------------------------------------------------
# Tile-level snapshot helpers
# ---------------------------------------------------------------------------

def _tile_signature(tile):
    """Compact hashable signature of a tile's observable state."""
    if tile.kind == "EMPTY" or tile.kind == "LOCKED":
        return ("EMPTY",) if tile.kind == "EMPTY" else ("LOCKED",)
    if tile.is_animal:
        return ("ANIMAL", tile.animal, tile.yield_units, tile.fed_today,
                tile.cared_today, tile.consecutive_unfed)
    if tile.is_plant:
        return ("PLANT", tile.crop, tile.planted_day, tile.yield_units,
                tile.watered_today, tile.consecutive_unwatered,
                tile.fertilized_until_day)
    # Structure (COOP / PASTURE) with no animal on it
    return ("STRUCTURE", tile.kind)


def snapshot_opponent_farm(opp_farm):
    """Capture a compact state representation of all opponent tiles.

    Returns a dict with:
      - tiles: dict mapping (x,y) -> tile signature tuple
      - money: float
      - hands: list of (x,y) hand positions
      - unlocked: sorted list of unlocked quadrants
      - shed: dict of product counts
    """
    if opp_farm is None:
        return None
    tiles = {}
    for t in opp_farm.iter_tiles():
        tiles[(t.x, t.y)] = _tile_signature(t)
    return {
        "tiles": tiles,
        "money": opp_farm.money,
        "hands": list(opp_farm.hands),
        "unlocked": sorted(opp_farm.unlocked),
        "shed": dict(getattr(opp_farm, "shed", {})),
    }


def snapshot_equal(snap_a, snap_b):
    """True if two snapshots are structurally identical."""
    if snap_a is None or snap_b is None:
        return snap_a is snap_b
    return (snap_a["tiles"] == snap_b["tiles"]
            and snap_a["money"] == snap_b["money"]
            and snap_a["hands"] == snap_b["hands"]
            and snap_a["unlocked"] == snap_b["unlocked"])


# ---------------------------------------------------------------------------
# Delta detection between consecutive snapshots
# ---------------------------------------------------------------------------

def detect_tile_deltas(current_farm, prev_snapshot):
    """Compare current farm tiles to previous snapshot.

    Returns a list of delta dicts, each with:
      - pos: (x,y) position
      - event: str - one of 'harvest', 'plant', 'animal_collect',
        'animal_place', 'animal_death', 'plant_death'
      - details: dict with crop/animal type, old/new yield, etc.
    """
    if prev_snapshot is None or current_farm is None:
        return []

    deltas = []
    prev_tiles = prev_snapshot["tiles"]

    for t in current_farm.iter_tiles():
        pos = (t.x, t.y)
        old_sig = prev_tiles.get(pos)
        new_sig = _tile_signature(t)

        if old_sig == new_sig:
            continue

        old_kind = old_sig[0] if old_sig else "EMPTY"
        new_kind = new_sig[0]

        # --- Harvest events ---
        if new_kind == "EMPTY" and old_kind == "PLANT":
            old_crop = old_sig[1]
            old_yield = old_sig[3] if len(old_sig) > 3 else 0
            deltas.append({
                "pos": pos, "event": "harvest",
                "details": {"crop": old_crop, "yield_units": old_yield},
            })
            continue

        # --- Planting events ---
        if new_kind == "PLANT" and old_kind == "EMPTY":
            deltas.append({
                "pos": pos, "event": "plant",
                "details": {"crop": t.crop, "planted_day": t.planted_day},
            })
            continue

        # --- Animal product collection (yield decreased) ---
        if new_kind == "ANIMAL" and old_kind == "ANIMAL":
            old_animal = old_sig[1]
            new_animal = new_sig[1]
            old_yield = old_sig[2] if len(old_sig) > 2 else 0
            new_yield = new_sig[2] if len(new_sig) > 2 else 0
            if new_yield < old_yield:
                product = ANIMALS.get(new_animal, {}).get("product", "?")
                deltas.append({
                    "pos": pos, "event": "animal_collect",
                    "details": {"animal": new_animal, "product": product,
                                "old_yield": old_yield, "new_yield": new_yield},
                })
            continue

        # --- Animal placement (structure -> animal) ---
        if new_kind == "ANIMAL" and old_kind == "STRUCTURE":
            deltas.append({
                "pos": pos, "event": "animal_place",
                "details": {"animal": t.animal},
            })
            continue

        # --- Animal death (animal -> empty or structure) ---
        if old_kind == "ANIMAL" and new_kind in ("EMPTY", "STRUCTURE"):
            deltas.append({
                "pos": pos, "event": "animal_death",
                "details": {"animal": old_sig[1]},
            })
            continue

        # --- Plant death / decay (plant cleared without harvest) ---
        if new_kind == "EMPTY" and old_kind == "PLANT":
            # Already handled above (harvest case), so this is death
            pass  # redundant guard; harvest covers plant->empty

        # --- Structure added (empty -> structure) ---
        if new_kind == "STRUCTURE" and old_kind == "EMPTY":
            deltas.append({
                "pos": pos, "event": "structure_build",
                "details": {"structure": t.kind},
            })

    return deltas


# ---------------------------------------------------------------------------
# Market + money delta inference
# ---------------------------------------------------------------------------

def infer_turn_transactions(opp_money_delta, market_inventory_delta,
                            town_consumption, our_sales):
    """Reconcile opponent money change with market inventory changes.

    Args:
      opp_money_delta: float, change in opponent money this turn.
      market_inventory_delta: dict {product: delta_inv} for this turn.
        Positive delta = inventory increased (bought). Negative = decreased (sold).
      town_consumption: dict {product: units} consumed by town this turn.
      our_sales: dict {product: units} we sold this turn.

    Returns a dict with:
      - confirmed_sells: dict {product: units} opponent definitely sold.
      - confirmed_buys: dict {product: units} opponent definitely bought.
      - explained_money: float, money change explained by confirmed sells/buys.
      - unexplained_money: float, money delta not explained by known transactions.
    """
    confirmed_sells = {}
    confirmed_buys = {}
    explained_money = 0.0

    for product in PRODUCTS:
        inv_delta = market_inventory_delta.get(product, 0)
        town = town_consumption.get(product, 0)
        ours = our_sales.get(product, 0)

        # Net drain on market = -inv_delta (positive => someone sold)
        net_market_drain = max(0, -inv_delta)
        # Subtract town consumption to isolate player sells
        player_sells = max(0, net_market_drain - town)
        # Subtract our recorded sales to isolate opponent sells
        opp_sells = max(0, player_sells - ours)
        if opp_sells > 0:
            confirmed_sells[product] = opp_sells
            explained_money += opp_sells  # selling adds money

        # Check for opponent buying: inventory increased despite town drain
        if inv_delta > 0 and town > 0:
            opp_bought = inv_delta
            confirmed_buys[product] = opp_bought
            explained_money -= opp_bought  # buying costs money

    return {
        "confirmed_sells": confirmed_sells,
        "confirmed_buys": confirmed_buys,
        "explained_money": explained_money,
        "unexplained_money": opp_money_delta - explained_money,
    }


# ---------------------------------------------------------------------------
# Phase 2 — Production Forecasting (Pillar 1)
# ---------------------------------------------------------------------------

def _ongoing_crop_yield(crop_name, day, fertilized_until_day):
    """Per-cycle yield for an ongoing crop on a given day.

    1 unit base, +1 bonus if fertilized_until_day covers this day.
    """
    base = 1
    if fertilized_until_day >= day:
        base += 1
    return min(base, CROPS[crop_name]["max_yield"])


def forecast_opponent_production(opp_farm, current_day, horizon_days=30):
    """Build an exact forward schedule of the opponent's crop harvests.

    Args:
      opp_farm: FarmView of the opponent's farm (or None).
      current_day: int, the current in-game day (0-indexed).
      horizon_days: int, how many days to project forward (default 30 = full season).

    Returns:
      Dict[str, Dict[int, float]] mapping product -> {day: projected_units}.
      Only includes days within the season (day <= 29).
    """
    if opp_farm is None:
        return {}

    schedule = defaultdict(lambda: defaultdict(float))
    last_day = min(current_day + horizon_days, 29)  # season ends at day 29

    for t in opp_farm.iter_tiles():
        # --- One-time crops ---
        if t.is_plant and not CROPS.get(t.crop, {}).get("ongoing", True):
            cd = CROPS[t.crop]
            harvest_day = t.planted_day + cd["max_yield_day"]

            # Crop mortality: unwatered >= 1 and not watered today => likely death
            if t.consecutive_unwatered >= 1 and not t.watered_today:
                continue  # skip — crop likely dies before maturity

            # Only forecast if harvest is within remaining season
            if current_day < harvest_day <= last_day:
                # Yield: use max_yield as projection (engine caps at max_yield_day)
                # Fertilizer effect: bonus window extends effective yield window
                yield_units = cd["max_yield"]
                # If fertilized, the crop has +1 effective yield per bonus day
                # remaining, but engine caps at max_yield — so just use max_yield
                # since fertilized crops hit max_yield at max_yield_day.
                schedule[t.crop][harvest_day] += yield_units

        # --- Ongoing crops (tomato, strawberry) ---
        if t.is_plant and CROPS.get(t.crop, {}).get("ongoing", False):
            cd = CROPS[t.crop]
            first = t.planted_day + cd["first_yield_day"]
            interval = cd["interval"]

            # Crop mortality check
            if t.consecutive_unwatered >= 1 and not t.watered_today:
                continue

            if interval <= 0:
                continue  # safety — ongoing should always have interval > 0

            # Generate all yield days from first through season end
            day = first
            while day <= last_day:
                if day >= current_day:
                    yld = _ongoing_crop_yield(t.crop, day,
                                              t.fertilized_until_day)
                    schedule[t.crop][day] += yld
                day += interval

        # --- Animals ---
        if t.is_animal and t.animal in ANIMALS:
            info = ANIMALS[t.animal]
            product = info["product"]
            first = t.placed_day + info["first_yield_day"]
            interval = info["interval"]

            # Produce on each interval day through season end.
            # We assume regular collection (opponent clears yield before
            # max_held fills), so each production day is independent.
            day = first
            while day <= last_day:
                if day >= current_day:
                    yld = 1
                    if t.cared_today or t.pending_care_bonus > 0:
                        yld += 1
                    schedule[product][day] += yld
                day += interval

    return {k: dict(v) for k, v in schedule.items()}


def get_imminent_harvests(opp_farm, current_day):
    """Identify crops/animals currently ripe with uncollected yield on field.

    Returns:
      Dict[str, int] mapping product -> ripe_units_on_field.
    """
    if opp_farm is None:
        return {}

    harvests = defaultdict(int)

    for t in opp_farm.iter_tiles():
        # --- One-time crops: ripe if age >= max_yield_day and yield > 0 ---
        if t.is_plant:
            cd = CROPS.get(t.crop)
            if cd is None:
                continue
            age = crop_age(t, current_day)
            if not cd["ongoing"] and age >= cd["max_yield_day"] and t.yield_units > 0:
                harvests[t.crop] += t.yield_units

            # --- Ongoing crops: ripe if on a yield day and yield > 0 ---
            if cd["ongoing"] and t.yield_units > 0:
                first = t.planted_day + cd["first_yield_day"]
                if current_day >= first and (current_day - first) % cd["interval"] == 0:
                    harvests[t.crop] += t.yield_units

        # --- Animals: product ready if yield_units > 0 ---
        if t.is_animal and t.animal in ANIMALS:
            if t.yield_units > 0:
                product = ANIMALS[t.animal]["product"]
                harvests[product] += t.yield_units

    return dict(harvests)


def summarize_opponent_commitments(opp_farm):
    """Summarize the opponent's tile allocation and portfolio percentages.

    Returns:
      Dict with keys:
        - crop_tiles: dict {crop: count}
        - animal_counts: dict {animal_type: count}
        - structure_count: int (COOP + PASTURE, including those with animals)
        - empty_tiles: int
        - locked_tiles: int
        - total_tiles: int
        - allocation_pct: dict {category: percentage_of_total}
    """
    if opp_farm is None:
        return {
            "crop_tiles": {}, "animal_counts": {}, "structure_count": 0,
            "empty_tiles": 0, "locked_tiles": 0, "total_tiles": 0,
            "allocation_pct": {},
        }

    crop_tiles = defaultdict(int)
    animal_counts = defaultdict(int)
    structure_count = 0
    empty_tiles = 0
    locked_tiles = 0
    total = 0

    for t in opp_farm.iter_tiles():
        total += 1
        if t.kind == "LOCKED":
            locked_tiles += 1
        elif t.kind == "EMPTY":
            empty_tiles += 1
        elif t.is_animal:
            animal_counts[t.animal] += 1
        elif t.is_plant:
            crop_tiles[t.crop] += 1
        elif t.kind in ("COOP", "PASTURE"):
            structure_count += 1

    # Allocation percentages
    alloc = {}
    if total > 0:
        for crop, cnt in crop_tiles.items():
            alloc[f"crop_{crop}"] = round(cnt / total * 100, 1)
        for animal, cnt in animal_counts.items():
            alloc[f"animal_{animal}"] = round(cnt / total * 100, 1)
        alloc["empty"] = round(empty_tiles / total * 100, 1)
        alloc["locked"] = round(locked_tiles / total * 100, 1)

    return {
        "crop_tiles": dict(crop_tiles),
        "animal_counts": dict(animal_counts),
        "structure_count": structure_count,
        "empty_tiles": empty_tiles,
        "locked_tiles": locked_tiles,
        "total_tiles": total,
        "allocation_pct": alloc,
    }


# ---------------------------------------------------------------------------
# Phase 3 — Shed Inference & Sell Prediction (Pillars 2 & 3)
# ---------------------------------------------------------------------------

def update_opponent_shed_estimate(prev_shed, harvest_events, inferred_sales,
                                  n_animals, day, hour):
    """Probabilistically reconstruct opponent's shed contents across turns.

    Args:
      prev_shed: dict {product: count} — previous estimated shed state (or None).
      harvest_events: list of delta dicts from detect_tile_deltas with
        event in ('harvest', 'animal_collect').
      inferred_sales: dict {product: units} — opponent sales inferred from
        the market drain ledger this turn.
      n_animals: int — number of opponent animals (for feed deduction).
      day: int — current game day.
      hour: int — current game hour (24h clock).

    Returns:
      dict {product: count} — updated estimated shed state.
    """
    shed = dict(prev_shed) if prev_shed else {}

    # --- Additions: harvest events ---
    for ev in harvest_events:
        if ev["event"] == "harvest":
            product = ev["details"].get("crop", "")
            units = ev["details"].get("yield_units", 0)
            if product and units > 0:
                shed[product] = shed.get(product, 0) + units
        elif ev["event"] == "animal_collect":
            product = ev["details"].get("product", "")
            old_y = ev["details"].get("old_yield", 0)
            new_y = ev["details"].get("new_yield", 0)
            collected = max(0, old_y - new_y)
            if product and collected > 0:
                shed[product] = shed.get(product, 0) + collected

    # --- Subtractions: inferred sales from market ledger ---
    for product, units in inferred_sales.items():
        if units > 0:
            shed[product] = max(0, shed.get(product, 0) - units)

    # --- Subtractions: animal feed at end-of-day rollover ---
    # Animals consume 1 WHEAT each at hour 23->0 boundary
    if hour == 0 and n_animals > 0:
        feed_cost = min(n_animals, shed.get("WHEAT", 0))
        if feed_cost > 0:
            shed["WHEAT"] = shed.get("WHEAT", 0) - feed_cost

    # --- Bounds: clamp non-negative ---
    for p in list(shed.keys()):
        shed[p] = max(0, shed[p])
        if shed[p] == 0:
            del shed[p]

    # --- Bounds: enforce total shed capacity ---
    total = sum(shed.values())
    if total > SHED_CAPACITY:
        # Proportionally shrink each product
        scale = SHED_CAPACITY / total if total > 0 else 0
        for p in shed:
            shed[p] = int(shed[p] * scale)
        # Fix rounding error: trim largest product
        new_total = sum(shed.values())
        if new_total > SHED_CAPACITY and shed:
            biggest = max(shed, key=shed.get)
            shed[biggest] -= (new_total - SHED_CAPACITY)

    return shed


def compute_opponent_sell_probabilities(opp_farm, estimated_shed, ctx, mem):
    """Score each product on [0.0, 1.0] for likelihood of opponent selling.

    Multi-signal heuristic weights:
      1. Shed stock (0.35)
      2. Imminent / unharvested units (0.25)
      3. Shed distance / movement signal (0.20)
      4. Global shed pressure (0.15)
      5. Timing window boost (0.05)

    Args:
      opp_farm: FarmView of opponent's farm (or None).
      estimated_shed: dict {product: count} from update_opponent_shed_estimate.
      ctx: parsed observation context dict.
      mem: persistent memory dict.

    Returns:
      dict {product: sell_probability} on [0.0, 1.0].
    """
    if opp_farm is None:
        return {}

    day = ctx.get("day", 0)
    hour = ctx.get("hour", 0)

    # Signal 1: Shed stock weight
    total_shed = sum(estimated_shed.values())
    shed_stock_scores = {}
    for p in PRODUCTS:
        units = estimated_shed.get(p, 0)
        shed_stock_scores[p] = min(1.0, units / 15.0)  # 15 units = full signal

    # Signal 2: Imminent / unharvested units
    imminent = get_imminent_harvests(opp_farm, day)
    imminent_scores = {}
    for p in PRODUCTS:
        units = imminent.get(p, 0)
        imminent_scores[p] = min(1.0, units / 6.0)  # 6 units = full signal

    # Signal 3: Shed distance / movement signal
    shed_tiles = set(SHED_ACCESS_TILES)
    all_positions = []
    for t in opp_farm.iter_tiles():
        if t.is_animal or t.is_plant:
            all_positions.append((t.x, t.y))
    # Check farmer and hands positions
    farmer_pos = getattr(opp_farm, "farmer", (4, 4))
    hand_positions = getattr(opp_farm, "hands", [])
    nearby_count = 0
    for pos in [farmer_pos] + list(hand_positions):
        if pos in shed_tiles:
            nearby_count += 2  # right at shed = very high signal
        else:
            # Manhattan distance to nearest shed tile
            min_dist = min(abs(pos[0] - sx) + abs(pos[1] - sy)
                           for sx, sy in shed_tiles)
            if min_dist <= 1:
                nearby_count += 1
    movement_score = min(1.0, nearby_count / 2.0)

    # Signal 4: Global shed pressure
    pressure = total_shed / SHED_CAPACITY if SHED_CAPACITY > 0 else 0
    pressure_score = min(1.0, max(0.0, (pressure - 0.6) / 0.4)) if pressure >= 0.6 else 0.0

    # Signal 5: Timing window boost
    timing_score = 0.0
    if hour % 4 == 1:  # post-drain sell window
        timing_score = 0.5
    elif hour >= 22:  # end-of-day liquidation push
        timing_score = 0.3
    elif hour % 4 == 0:  # drain just happened, selling imminent
        timing_score = 0.2

    # Combine weighted signals
    W_SHED = 0.35
    W_IMMINENT = 0.25
    W_MOVEMENT = 0.20
    W_PRESSURE = 0.15
    W_TIMING = 0.05

    probs = {}
    for p in PRODUCTS:
        score = (
            W_SHED * shed_stock_scores[p]
            + W_IMMINENT * imminent_scores[p]
            + W_MOVEMENT * movement_score
            + W_PRESSURE * pressure_score
            + W_TIMING * timing_score
        )
        probs[p] = round(min(1.0, max(0.0, score)), 4)

    return probs


def predict_imminent_dumps(opp_farm, estimated_shed, sell_probs, threshold=0.60):
    """Estimate dump volume for products with high sell probability.

    Args:
      opp_farm: FarmView (for drip-slice estimation).
      estimated_shed: dict {product: count}.
      sell_probs: dict {product: probability} from compute_opponent_sell_probabilities.
      threshold: float — minimum probability to flag as imminent dump.

    Returns:
      dict {product: {"probability": float, "estimated_volume": int,
                       "urgency": "HIGH" | "MEDIUM"}}.
    """
    dumps = {}
    drip_slice = 3  # conservative estimate of units per sell order

    for p, prob in sell_probs.items():
        if prob < threshold:
            continue
        shed_units = estimated_shed.get(p, 0)
        if shed_units <= 0:
            continue
        est_vol = min(shed_units, drip_slice)
        urgency = "HIGH" if prob >= 0.80 else "MEDIUM"
        dumps[p] = {
            "probability": prob,
            "estimated_volume": est_vol,
            "urgency": urgency,
        }

    return dumps


# ---------------------------------------------------------------------------
# Legacy helpers (kept for backward compat)
# ---------------------------------------------------------------------------

def opponent_snapshot(ctx, mem):
    """Summarize the opponent's public state each turn (legacy)."""
    opp = ctx["opponent_farm"]
    if opp is None:
        return {}
    ripe_melons = 0
    ripe_crops = {}
    for t in opp.iter_tiles():
        if t.is_plant:
            cd = CROPS.get(t.crop)
            if cd is None:
                continue
            age = crop_age(t, ctx["day"])
            if not cd["ongoing"] and age >= cd["max_yield_day"]:
                ripe_crops[t.crop] = ripe_crops.get(t.crop, 0) + t.yield_units
    animals = sum(1 for t in opp.iter_tiles() if t.is_animal)
    return {
        "money": opp.money,
        "ripe_units": ripe_crops,
        "animals": animals,
        "hands": len(opp.hands),
        "unlocked": sorted(opp.unlocked),
    }


def opponent_primary_product(mem, default="MELON"):
    """Product the opponent most likely holds for sale (from ledger inference)."""
    inferred = mem.get("opp_sales_inferred", {})
    if not inferred:
        return default
    return max(inferred, key=lambda k: inferred[k])
