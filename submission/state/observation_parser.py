"""Robust parsing of the Kaggle observation into typed structures.

Handles both plain dicts and kaggle Struct objects via the `g()` accessor.
"""
from config import ANIMAL_LIST, ANIMALS, CROPS, PRODUCTS, SHED_ACCESS_TILES, TURNS_PER_DAY


def g(obj, key, default=None):
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


class TileView:
    __slots__ = ("x", "y", "raw", "kind", "crop", "planted_day", "watered_today",
                 "consecutive_unwatered", "yield_units", "fertilized_until_day",
                 "animal", "fed_today", "cared_today", "consecutive_unfed",
                 "fertilizer_available", "pending_care_bonus", "placed_day")

    def __init__(self, x, y, raw):
        self.x = x
        self.y = y
        self.raw = raw
        if raw is None:
            self.kind = "EMPTY"
        elif raw == "LOCKED":
            self.kind = "LOCKED"
        else:
            self.kind = g(raw, "kind", "?")
        self.crop = g(raw, "crop")
        self.planted_day = g(raw, "planted_day")
        self.watered_today = bool(g(raw, "watered_today", False))
        self.consecutive_unwatered = int(g(raw, "consecutive_unwatered", 0))
        self.yield_units = int(g(raw, "yield_units", 0) or 0)
        self.fertilized_until_day = int(g(raw, "fertilized_until_day", -1) or -1)
        self.animal = g(raw, "animal")
        self.fed_today = bool(g(raw, "fed_today", False))
        self.cared_today = bool(g(raw, "cared_today", False))
        self.consecutive_unfed = int(g(raw, "consecutive_unfed", 0))
        self.fertilizer_available = bool(g(raw, "fertilizer_available", False))
        self.pending_care_bonus = int(g(raw, "pending_care_bonus", 0) or 0)
        self.placed_day = g(raw, "placed_day")

    @property
    def is_plant(self):
        return self.kind == "PLANT"

    @property
    def is_animal(self):
        return self.animal is not None

    @property
    def pos(self):
        return (self.x, self.y)


class FarmView:
    """Public farm state for any player."""

    def __init__(self, raw):
        self.money = float(g(raw, "money", 0))
        self.tiles_raw = g(raw, "tiles", []) or []
        self.farmer = tuple(g(raw, "farmer", (4, 4)))
        self.hands = [tuple(h) for h in (g(raw, "hands", []) or [])]
        self.unlocked = set(g(raw, "unlocked_quadrants", ["NW"]) or ["NW"])
        self.hires_today = int(g(raw, "hires_today", 0))
        self.tiles = []
        for y, row in enumerate(self.tiles_raw):
            trow = []
            for x, t in enumerate(row):
                trow.append(TileView(x, y, t))
            self.tiles.append(trow)

    def tile_at(self, pos):
        x, y = pos
        if 0 <= y < len(self.tiles) and 0 <= x < len(self.tiles[0]):
            return self.tiles[y][x]
        return None

    def iter_tiles(self):
        for row in self.tiles:
            for t in row:
                yield t

    def quadrant_of(self, pos):
        x, y = pos
        half = len(self.tiles_raw[0]) // 2 if self.tiles_raw and self.tiles_raw[0] else 5
        return ("N" if y < half else "S") + ("W" if x < half else "E")

    def count_kind(self, kind):
        return sum(1 for t in self.iter_tiles() if t.kind == kind)


class MarketView:
    def __init__(self, raw):
        self.inventory = {k: float(v) for k, v in
                          (g(raw, "inventory", {}) or {}).items()}
        self.prices = {k: int(v) for k, v in
                       (g(raw, "prices", {}) or {}).items()}


class TownView:
    def __init__(self, raw):
        self.unlocked_shops = list(g(raw, "unlocked_shops", []) or [])


class PrivateView:
    def __init__(self, raw):
        self.shed = {k: int(v) for k, v in (g(raw, "shed", {}) or {}).items()
                     if int(v) > 0}
        self.seeds = {k: int(v) for k, v in (g(raw, "seeds", {}) or {}).items()
                      if int(v) > 0}
        invs = g(raw, "inventories", []) or []
        self.inventories = [{k: int(v) for k, v in (inv or {}).items() if int(v) > 0}
                            for inv in invs]

    def shed_count(self):
        return sum(self.shed.values())

    def unit_holding(self, idx):
        if idx < len(self.inventories):
            return self.inventories[idx]
        return {}


def parse_observation(obs):
    """Full observation parse into a light context object."""
    farms = g(obs, "farms", None)
    if not farms:
        return None
    player = int(g(obs, "player", 0))
    ctx = {
        "player": player,
        "day": int(g(obs, "day", 0)),
        "hour": int(g(obs, "hour", 0)),
        "step": int(g(obs, "day", 0)) * TURNS_PER_DAY + int(g(obs, "hour", 0)),
        "farm": FarmView(farms[player]),
        "market": MarketView(g(obs, "market")),
        "town": TownView(g(obs, "town")),
        "private": PrivateView(g(obs, "private")),
        "opponent_farm": FarmView(farms[1 - player]) if len(farms) > 1 else None,
        "n_units": 1 + len(FarmView(farms[player]).hands),
    }
    ctx["is_shed_adjacent"] = lambda pos: pos in SHED_ACCESS_TILES
    return ctx


# ---- derived per-tile attributes -------------------------------------------

def crop_age(tile, day):
    return day - tile.planted_day if tile.planted_day is not None else 0


def in_bonus_window(tile, day):
    cd = CROPS.get(tile.crop)
    if cd is None:
        return False
    age = crop_age(tile, day)
    start = cd.get("window_start", (cd["max_yield_day"] + 1) // 2)
    return start <= age <= cd["max_yield_day"]


def crop_produces_today(tile, day):
    """True if this ongoing crop produces today or at the end-of-day refresh today.

    Based on:
      * planted_day
      * first_yield_day
      * interval
      * max_yield
    """
    is_plant = getattr(tile, "is_plant", False) or g(tile, "kind") == "PLANT"
    if not is_plant:
        return False
    crop_name = getattr(tile, "crop", g(tile, "crop"))
    cd = CROPS.get(crop_name)
    if cd is None or not cd.get("ongoing"):
        return False
    planted = getattr(tile, "planted_day", g(tile, "planted_day"))
    if planted is None:
        return False

    first = cd["first_yield_day"]
    interval = cd["interval"]
    max_yield = cd["max_yield"]
    if interval <= 0:
        return False

    # 1. Engine end-of-day refresh timing:
    # In engine _daily_refresh_plants(), next_day = current_day + 1.
    # Production fires at end of `day` when:
    # days_since_first = (day + 1) - planted - first >= 0
    # and days_since_first % interval == 0
    # and (days_since_first // interval + 1) <= max_yield.
    since_first_eod = (day + 1) - planted - first
    if since_first_eod >= 0 and since_first_eod % interval == 0:
        if (since_first_eod // interval + 1) <= max_yield:
            return True

    # 2. Calendar age on `day`: age = day - planted
    # age >= first and (age - first) % interval == 0
    # and ((age - first) // interval + 1) <= max_yield.
    age = day - planted
    if age >= first and (age - first) % interval == 0:
        if ((age - first) // interval + 1) <= max_yield:
            return True

    return False


ongoing_crop_produces_today = crop_produces_today


def needs_water_today(tile, day):
    """Determine if a plant tile must/should be watered today under Points 1.2 & 1.5.

    1. Always water on planting day.
    2. If missed yesterday (counter >= 1), MUST water today (prevent weed).
    3. If ongoing crop produces today AND fertilizer is active today, water so fertilized production doubles.
    4. Otherwise for ongoing crops, alternate days by spatial checkerboard ((x + y + day) % 2 == 0).
    5. One-time crops: in bonus window -> ALWAYS water; otherwise alternate days.
    """
    is_plant = getattr(tile, "is_plant", False) or g(tile, "kind") == "PLANT"
    if not is_plant:
        return False
    watered_today = bool(getattr(tile, "watered_today", g(tile, "watered_today", False)))
    if watered_today:
        return False

    planted_day = getattr(tile, "planted_day", g(tile, "planted_day"))

    # Guardrail 1: Planting day ALWAYS requires same-day water (starts with counter=1)
    if planted_day is not None and planted_day == day:
        return True

    # Guardrail 2: Missed yesterday -> mandatory survival watering
    consecutive_unwatered = int(getattr(tile, "consecutive_unwatered", g(tile, "consecutive_unwatered", 0)) or 0)
    if consecutive_unwatered >= 1:
        return True

    crop_name = getattr(tile, "crop", g(tile, "crop"))
    cd = CROPS.get(crop_name)
    if cd is None:
        return True

    x = int(getattr(tile, "x", g(tile, "x", 0)) or 0)
    y = int(getattr(tile, "y", g(tile, "y", 0)) or 0)

    # Ongoing crops (Tomato, Strawberry): do NOT force daily watering
    if cd.get("ongoing"):
        fert_day = getattr(tile, "fertilized_until_day", g(tile, "fertilized_until_day", -1))
        fertilized_active = fert_day is not None and fert_day >= day
        # Scheduled production day AND fertilizer active today -> force water to double output
        if crop_produces_today(tile, day) and fertilized_active:
            return True
        # Otherwise alternate days by spatial checkerboard
        return (x + y + day) % 2 == 0

    # One-time crops (Wheat, Carrot, Melon)
    if in_bonus_window(tile, day):
        return True

    # Outside bonus window and watered yesterday -> alternate days
    return (x + y + day) % 2 == 0


def decay_step_for(tile):
    """First global step at which this one-time plant starts losing units."""
    cd = CROPS[tile.crop]
    if cd["ongoing"]:
        return None
    return (tile.planted_day + cd["max_yield_day"] + 1) * TURNS_PER_DAY


def turns_until_decay(tile, step):
    ds = decay_step_for(tile)
    return None if ds is None else max(0, ds - step)


def animal_production_days(tile):
    a = ANIMAL_LIST and None  # placeholder to keep lints quiet
    info = ANIMALS.get(tile.animal)
    if info is None:
        return set()
    first = tile.placed_day + info["first_yield_day"]
    return set(range(first, 31, info["interval"]))
