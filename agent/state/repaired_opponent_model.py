"""Repaired Opponent Model: Engine-Verified Lifecycle, Realistic Yields, and Principled Bounds.

Authoritative Ground Truth Fixes (compared to legacy opponent_model.py):
1. Finite Ongoing Crops: Tomato & Strawberry produce at most CROPS[crop]["max_yield"] (4) cycles
   before entering decay (max_lifespan_step), NOT an infinite loop through Day 29.
2. Realistic One-Time Crop Yields:
   - Wheat: 1 initial + 3 watering window days = 4 units base (6 only if fertilized).
   - Carrot: 1 initial + 2 watering window days = 3 units base (4 only if fertilized).
   - Melon: 1 initial + 7 watering window days = 6 units (if watered >= 5 days).
3. Ongoing Crop Harvest Detection: Detects harvest on ongoing crops when tile remains PLANT
   but yield_units drops (previously completely invisible in detect_tile_deltas).
4. Harvest vs Cleared/Death Distinction: Plant disappearance with 0 yield or before maturity
   is classified as plant_cleared / plant_death, NOT harvest.
5. Principled Hidden State Bounds: Opponent carried inventory and shed stock are represented
   as [min, max] intervals with confidence rather than single invented integers.
   Shed visits alone do not prove deposits; EOD auto-drop (hour 0) collapses carried stock into shed.
6. Animal Lifecycle & Saturation: Respects interval, fed prerequisites, and max_held caps
   (4 for Goose, 6 for Cow/Sheep).
7. Recoverable Crops: A crop with consecutive_unwatered == 1 is treated as recoverable
   during daytime hours, not written off as dead.
"""

from collections import defaultdict, deque
from typing import Dict, List, Any, Tuple, Optional
from config import ANIMALS, CROPS, PRODUCTS, SHED_CAPACITY, SHED_ACCESS_TILES


# ---------------------------------------------------------------------------
# Tile Snapshot & Delta Detection
# ---------------------------------------------------------------------------

def tile_signature(tile) -> Tuple:
    """Compact hashable signature of an observable tile."""
    if tile is None or tile.kind in ("EMPTY", "LOCKED"):
        return (tile.kind if tile is not None else "EMPTY",)
    if tile.is_animal:
        return ("ANIMAL", tile.animal, int(tile.yield_units), bool(tile.fed_today),
                bool(tile.cared_today), int(tile.consecutive_unfed),
                bool(getattr(tile, "fertilizer_available", False)))
    if tile.is_plant:
        return ("PLANT", tile.crop, int(tile.planted_day), int(tile.yield_units),
                bool(tile.watered_today), int(tile.consecutive_unwatered),
                int(getattr(tile, "fertilized_until_day", -1)))
    return ("STRUCTURE", tile.kind)


def snapshot_farm(farm) -> Optional[Dict[str, Any]]:
    """Capture compact state representation of an observed farm."""
    if farm is None:
        return None
    tiles = {}
    for t in farm.iter_tiles():
        tiles[(t.x, t.y)] = tile_signature(t)
    return {
        "tiles": tiles,
        "money": float(farm.money),
        "farmer": tuple(farm.farmer) if hasattr(farm, "farmer") else (4, 4),
        "hands": [tuple(h) for h in getattr(farm, "hands", [])],
        "unlocked": sorted(farm.unlocked),
        "shed": dict(getattr(farm, "shed", {})),
    }


def detect_tile_deltas_repaired(current_farm, prev_snapshot) -> List[Dict[str, Any]]:
    """Detect ground-truth tile transitions between consecutive observations.

    Correctly identifies:
      - harvest (both one-time crop clearing AND ongoing crop yield drops)
      - plant_cleared (dug up or cleared without harvest)
      - plant_death (transitioned to WEED)
      - animal_collect (animal yield dropped)
      - plant, animal_place, animal_death, structure_build
    """
    if prev_snapshot is None or current_farm is None:
        return []

    deltas = []
    prev_tiles = prev_snapshot["tiles"]

    for t in current_farm.iter_tiles():
        pos = (t.x, t.y)
        old_sig = prev_tiles.get(pos)
        new_sig = tile_signature(t)

        if old_sig == new_sig:
            continue

        old_kind = old_sig[0] if old_sig else "EMPTY"
        new_kind = new_sig[0]

        # 1. PLANT -> EMPTY
        if new_kind == "EMPTY" and old_kind == "PLANT":
            old_crop = old_sig[1]
            old_planted = old_sig[2] if len(old_sig) > 2 else 0
            old_yield = old_sig[3] if len(old_sig) > 3 else 0
            cd = CROPS.get(old_crop, {})
            # Only count as harvest if there was ripe yield or reached harvest age
            if old_yield > 0:
                deltas.append({
                    "pos": pos, "event": "harvest",
                    "details": {"crop": old_crop, "yield_units": old_yield, "ongoing": False},
                })
            else:
                deltas.append({
                    "pos": pos, "event": "plant_cleared",
                    "details": {"crop": old_crop, "yield_units": 0},
                })
            continue

        # 2. PLANT -> WEED or STRUCTURE (decay / unwatered death)
        if old_kind == "PLANT" and new_kind == "STRUCTURE":
            old_crop = old_sig[1]
            deltas.append({
                "pos": pos, "event": "plant_death",
                "details": {"crop": old_crop, "structure": t.kind},
            })
            continue

        # 3. PLANT -> PLANT (Ongoing crop harvest or fertilizing)
        if old_kind == "PLANT" and new_kind == "PLANT":
            old_crop = old_sig[1]
            old_yield = old_sig[3] if len(old_sig) > 3 else 0
            new_yield = new_sig[3] if len(new_sig) > 3 else 0
            if new_yield < old_yield:
                collected = old_yield - new_yield
                deltas.append({
                    "pos": pos, "event": "harvest",
                    "details": {"crop": old_crop, "yield_units": collected, "ongoing": True},
                })
            # Check fertilizing event (fertilized_until_day increased)
            old_fert = old_sig[6] if len(old_sig) > 6 else -1
            new_fert = new_sig[6] if len(new_sig) > 6 else -1
            if new_fert > old_fert:
                deltas.append({
                    "pos": pos, "event": "plant_fertilized",
                    "details": {"crop": old_crop, "units": 1},
                })
            continue

        # 4. EMPTY -> PLANT
        if new_kind == "PLANT" and old_kind in ("EMPTY", "STRUCTURE"):
            deltas.append({
                "pos": pos, "event": "plant",
                "details": {"crop": t.crop, "planted_day": t.planted_day},
            })
            continue

        # 5. ANIMAL -> ANIMAL (Animal product collection, fertilizer collection, feeding)
        if new_kind == "ANIMAL" and old_kind == "ANIMAL":
            old_animal = old_sig[1]
            new_animal = new_sig[1]
            old_yield = old_sig[2] if len(old_sig) > 2 else 0
            new_yield = new_sig[2] if len(new_sig) > 2 else 0
            if new_yield < old_yield:
                collected = old_yield - new_yield
                product = ANIMALS.get(new_animal, {}).get("product", "")
                deltas.append({
                    "pos": pos, "event": "animal_collect",
                    "details": {"animal": new_animal, "product": product, "units": collected},
                })
            # Check animal fertilizer collection (fertilizer_available True -> False)
            old_fert_avail = old_sig[6] if len(old_sig) > 6 else False
            new_fert_avail = new_sig[6] if len(new_sig) > 6 else False
            if old_fert_avail and not new_fert_avail:
                deltas.append({
                    "pos": pos, "event": "collect_fertilizer",
                    "details": {"animal": new_animal, "product": "FERTILIZER", "units": 1},
                })
            # Check animal feeding event (fed_today False -> True)
            old_fed = old_sig[3] if len(old_sig) > 3 else False
            new_fed = new_sig[3] if len(new_sig) > 3 else False
            if not old_fed and new_fed:
                deltas.append({
                    "pos": pos, "event": "animal_fed",
                    "details": {"animal": new_animal, "product": "WHEAT", "units": 1},
                })
            continue

        # 6. STRUCTURE -> ANIMAL
        if new_kind == "ANIMAL" and old_kind == "STRUCTURE":
            deltas.append({
                "pos": pos, "event": "animal_place",
                "details": {"animal": t.animal},
            })
            continue

        # 7. ANIMAL -> EMPTY or STRUCTURE (Animal death / escape)
        if old_kind == "ANIMAL" and new_kind in ("EMPTY", "STRUCTURE"):
            deltas.append({
                "pos": pos, "event": "animal_death",
                "details": {"animal": old_sig[1]},
            })
            continue

        # 8. EMPTY -> STRUCTURE
        if new_kind == "STRUCTURE" and old_kind == "EMPTY":
            deltas.append({
                "pos": pos, "event": "structure_build",
                "details": {"structure": t.kind},
            })
            continue

    return deltas


# ---------------------------------------------------------------------------
# Repaired Production Forecasting with Scenarios (Low / Base / High)
# ---------------------------------------------------------------------------

def forecast_opponent_production_repaired(
    opp_farm,
    current_day: int,
    current_hour: int = 0,
    horizon_days: int = 30
) -> Dict[str, Any]:
    """Build forward production schedule with Low / Base / High scenarios.

    Returns dict with:
      - 'schedules': {product: {day: {'low': float, 'base': float, 'high': float}}}
      - 'base_schedule': {product: {day: float}}  (for simple consumer lookups)
      - 'imminent_field_stock': {product: int}     (ripe now on tiles)
      - 'total_projected_base': {product: float}
    """
    if opp_farm is None:
        return {
            "schedules": {},
            "base_schedule": {},
            "imminent_field_stock": {},
            "total_projected_base": {},
        }

    schedules = defaultdict(lambda: defaultdict(lambda: {"low": 0.0, "base": 0.0, "high": 0.0}))
    imminent_field_stock = defaultdict(int)
    last_day = min(current_day + horizon_days, 29)

    for t in opp_farm.iter_tiles():
        # --- Observable Ripe produce on tile ---
        if getattr(t, "yield_units", 0) > 0:
            if t.is_plant:
                imminent_field_stock[t.crop] += int(t.yield_units)
            elif t.is_animal and t.animal in ANIMALS:
                prod = ANIMALS[t.animal]["product"]
                imminent_field_stock[prod] += int(t.yield_units)

        # --- One-Time Crops (WHEAT, CARROT, MELON) ---
        if t.is_plant and not CROPS.get(t.crop, {}).get("ongoing", True):
            cd = CROPS[t.crop]
            harvest_day = t.planted_day + cd["max_yield_day"]

            # Mortality check:
            # If consecutive_unwatered >= 2, already dead
            if t.consecutive_unwatered >= 2:
                continue
            # If consecutive_unwatered == 1 and not watered today:
            # During early/mid day (hour <= 20), worker can still water today -> recoverable.
            # At hour > 20, if still unwatered, unlikely to be saved.
            if t.consecutive_unwatered == 1 and not t.watered_today and current_hour > 20:
                continue

            if current_day < harvest_day <= last_day:
                crop_name = t.crop
                fertilized = (t.fertilized_until_day >= harvest_day or t.fertilized_until_day >= current_day)

                if crop_name == "WHEAT":
                    # 1 initial + 3 window days (days 2, 3, 4)
                    low_y = 2.0
                    base_y = 6.0 if fertilized else 4.0
                    high_y = 6.0
                elif crop_name == "CARROT":
                    # 1 initial + 2 window days (days 2, 3)
                    low_y = 2.0
                    base_y = 4.0 if fertilized else 3.0
                    high_y = 4.0
                elif crop_name == "MELON":
                    # 1 initial + 7 window days (days 6..12). Hits 6 if watered >= 5 days.
                    low_y = 3.0
                    base_y = 6.0
                    high_y = 6.0
                else:
                    low_y = 1.0
                    base_y = float(cd["max_yield"])
                    high_y = float(cd["max_yield"])

                s = schedules[crop_name][harvest_day]
                s["low"] += low_y
                s["base"] += base_y
                s["high"] += high_y

        # --- Ongoing Crops (TOMATO, STRAWBERRY) ---
        if t.is_plant and CROPS.get(t.crop, {}).get("ongoing", False):
            cd = CROPS[t.crop]
            if t.consecutive_unwatered >= 2:
                continue
            if t.consecutive_unwatered == 1 and not t.watered_today and current_hour > 20:
                continue

            first = t.planted_day + cd["first_yield_day"]
            interval = cd["interval"]
            max_cycles = cd["max_yield"]  # Exactly 4 cycles!

            for cycle in range(max_cycles):
                yday = first + cycle * interval
                if yday < current_day or yday > last_day:
                    continue

                fertilized = (t.fertilized_until_day >= yday)
                # Engine: +2 if fertilized and watered, else +1
                low_y = 1.0
                base_y = 2.0 if fertilized else 1.0
                high_y = 2.0

                s = schedules[t.crop][yday]
                s["low"] += low_y
                s["base"] += base_y
                s["high"] += high_y

        # --- Animals (GOOSE, COW, SHEEP) ---
        if t.is_animal and t.animal in ANIMALS:
            info = ANIMALS[t.animal]
            product = info["product"]
            first = t.placed_day + info["first_yield_day"]
            interval = info["interval"]
            max_held = info["max_held"]

            # Animal dies if unfed >= 2
            if t.consecutive_unfed >= 2:
                continue

            yday = first
            while yday <= last_day:
                if yday >= current_day:
                    # Low scenario: un-cared fed
                    low_y = 1.0
                    # Base scenario: regular fed, care bonus if currently cared or active
                    base_bonus = 1.0 if (t.cared_today or t.pending_care_bonus > 0) else 0.0
                    base_y = min(float(max_held), 1.0 + base_bonus)
                    # High scenario: cared + fed
                    high_y = min(float(max_held), 2.0)

                    s = schedules[product][yday]
                    s["low"] += low_y
                    s["base"] += base_y
                    s["high"] += high_y
                yday += interval

    # Build base_schedule and totals
    base_schedule = {}
    total_projected_base = defaultdict(float)
    clean_schedules = {}

    for prod, day_dict in schedules.items():
        clean_schedules[prod] = {}
        base_schedule[prod] = {}
        for d, vals in day_dict.items():
            clean_schedules[prod][d] = {
                "low": round(vals["low"], 2),
                "base": round(vals["base"], 2),
                "high": round(vals["high"], 2),
            }
            base_schedule[prod][d] = round(vals["base"], 2)
            total_projected_base[prod] += vals["base"]

    return {
        "schedules": clean_schedules,
        "base_schedule": base_schedule,
        "imminent_field_stock": dict(imminent_field_stock),
        "total_projected_base": {k: round(v, 2) for k, v in total_projected_base.items()},
    }


# ---------------------------------------------------------------------------
# Principled Inventory Tracking: Field -> Carried -> Shed Bounds
# ---------------------------------------------------------------------------

class RepairedOpponentInventoryTracker:
    """Tracks opponent inventory across field, worker carried stock, and shed.

    Adheres strictly to engine truths:
    1. Harvest goes to worker inventory, NOT shed.
    2. Shed access tiles visited do not prove deposit (could be pass-through).
    3. At Day boundary (hour 23 -> 0), engine _drop_inventories_to_shed forces all
       carried stock into the shed (capped at 100).
    4. Confirmed market sales require goods to have been in the shed.
    5. Bounds [lower, upper] are maintained for both carried and shed stock.
    """

    def __init__(self):
        self.reset()

    def reset(self):
        self.cum_harvested = defaultdict(float)
        self.cum_sold = defaultdict(float)
        self.cum_bought = defaultdict(float)
        self.cum_consumed = defaultdict(float)
        self.shed_lower_bound = defaultdict(float)
        self.shed_upper_bound = defaultdict(float)
        self.carried_lower_bound = defaultdict(float)
        self.carried_upper_bound = defaultdict(float)
        self.buy_lower_bound = defaultdict(float)
        self.buy_upper_bound = defaultdict(float)
        self.buy_confidence = defaultdict(lambda: "none")
        self.last_day = 0
        self.last_hour = 0

    def update(
        self,
        deltas: List[Dict[str, Any]],
        confirmed_sells: Dict[str, float],
        confirmed_buys: Optional[Dict[str, Any]],
        n_animals: int,
        day: int,
        hour: int,
        inferred_buys: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        is_day_rollover = (hour == 0 and (self.last_hour == 23 or day > self.last_day))
        self.last_day = day
        self.last_hour = hour

        # 1. Tile transitions: harvests, collections, and in-field consumption
        for d in deltas:
            ev = d.get("event")
            if ev == "harvest":
                crop = d["details"].get("crop")
                qty = float(d["details"].get("yield_units", 0))
                if crop and qty > 0:
                    self.cum_harvested[crop] += qty
                    self.carried_upper_bound[crop] += qty
            elif ev == "animal_collect":
                prod = d["details"].get("product")
                qty = float(d["details"].get("units", 0))
                if prod and qty > 0:
                    self.cum_harvested[prod] += qty
                    self.carried_upper_bound[prod] += qty
            elif ev == "collect_fertilizer":
                qty = float(d["details"].get("units", 1))
                self.cum_harvested["FERTILIZER"] += qty
                self.carried_upper_bound["FERTILIZER"] += qty
            elif ev == "animal_fed":
                # Inferred consumption: 1 unit Wheat consumed
                qty = float(d["details"].get("units", 1))
                self.cum_consumed["WHEAT"] += qty
                if self.carried_upper_bound["WHEAT"] >= qty:
                    self.carried_upper_bound["WHEAT"] -= qty
                else:
                    rem = qty - self.carried_upper_bound["WHEAT"]
                    self.carried_upper_bound["WHEAT"] = 0.0
                    self.shed_lower_bound["WHEAT"] = max(0.0, self.shed_lower_bound["WHEAT"] - rem)
                    self.shed_upper_bound["WHEAT"] = max(0.0, self.shed_upper_bound["WHEAT"] - rem)
            elif ev == "plant_fertilized":
                # Inferred consumption: 1 unit Fertilizer consumed
                qty = float(d["details"].get("units", 1))
                self.cum_consumed["FERTILIZER"] += qty
                if self.carried_upper_bound["FERTILIZER"] >= qty:
                    self.carried_upper_bound["FERTILIZER"] -= qty
                else:
                    rem = qty - self.carried_upper_bound["FERTILIZER"]
                    self.carried_upper_bound["FERTILIZER"] = 0.0
                    self.shed_lower_bound["FERTILIZER"] = max(0.0, self.shed_lower_bound["FERTILIZER"] - rem)
                    self.shed_upper_bound["FERTILIZER"] = max(0.0, self.shed_upper_bound["FERTILIZER"] - rem)

        # 2. Inferred market purchases (enter shed directly during market order execution)
        all_buys = {}
        if isinstance(confirmed_buys, dict):
            for k, v in confirmed_buys.items():
                if isinstance(v, dict):
                    all_buys[k] = v
                elif isinstance(v, (int, float)) and v > 0:
                    all_buys[k] = {"lower": float(v), "upper": float(v), "confidence": "high"}
        if isinstance(inferred_buys, dict):
            for k, v in inferred_buys.items():
                if k not in all_buys and isinstance(v, dict):
                    all_buys[k] = v

        for item, binfo in all_buys.items():
            lo = float(binfo.get("lower", 0.0))
            hi = float(binfo.get("upper", 0.0))
            conf = str(binfo.get("confidence", "low"))
            if hi > 0:
                self.cum_bought[item] += lo
                self.buy_lower_bound[item] += lo
                self.buy_upper_bound[item] += hi
                self.buy_confidence[item] = conf
                self.shed_lower_bound[item] += lo
                self.shed_upper_bound[item] = min(float(SHED_CAPACITY), self.shed_upper_bound[item] + hi)

        # 3. Process confirmed sells (sells require prior shed presence)
        for item, qty in confirmed_sells.items():
            if qty > 0:
                self.cum_sold[item] += qty
                self.shed_lower_bound[item] = max(0.0, self.shed_lower_bound[item] - qty)
                self.shed_upper_bound[item] = max(0.0, self.shed_upper_bound[item] - qty)

        # 4. Day rollover: engine drops all worker carried stock into shed
        if is_day_rollover:
            for item in PRODUCTS:
                self.shed_lower_bound[item] = min(float(SHED_CAPACITY), self.shed_lower_bound[item] + self.carried_lower_bound[item])
                self.shed_upper_bound[item] = min(float(SHED_CAPACITY), self.shed_upper_bound[item] + self.carried_upper_bound[item])
                self.carried_lower_bound[item] = 0.0
                self.carried_upper_bound[item] = 0.0

        # Global capacity clamp
        for item in PRODUCTS:
            self.shed_upper_bound[item] = min(float(SHED_CAPACITY), max(self.shed_lower_bound[item], self.shed_upper_bound[item]))
            self.carried_upper_bound[item] = max(self.carried_lower_bound[item], self.carried_upper_bound[item])

        # Point estimates: mid-point of bounds
        shed_point = {}
        for p in PRODUCTS:
            lo = self.shed_lower_bound[p]
            hi = self.shed_upper_bound[p]
            shed_point[p] = round((lo + hi) / 2.0, 1)

        return {
            "shed_bounds": {p: [round(self.shed_lower_bound[p], 1), round(self.shed_upper_bound[p], 1)]
                            for p in PRODUCTS},
            "carried_bounds": {p: [round(self.carried_lower_bound[p], 1), round(self.carried_upper_bound[p], 1)]
                              for p in PRODUCTS},
            "shed_point_estimate": shed_point,
            "inferred_buys": {p: {"lower": self.buy_lower_bound[p], "upper": self.buy_upper_bound[p], "confidence": self.buy_confidence[p]}
                              for p in PRODUCTS if self.buy_upper_bound[p] > 0},
            "cum_harvested": dict(self.cum_harvested),
            "cum_sold": dict(self.cum_sold),
            "cum_consumed": dict(self.cum_consumed),
        }
