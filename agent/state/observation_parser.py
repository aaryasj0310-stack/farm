"""Robust parsing of the Kaggle observation into typed structures.

Handles both plain dicts and kaggle Struct objects via the `g()` accessor.
"""
from config import ANIMAL_LIST, CROPS, PRODUCTS, SHED_ACCESS_TILES, TURNS_PER_DAY


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
    from config import ANIMALS
    info = ANIMALS.get(tile.animal)
    if info is None:
        return set()
    first = tile.placed_day + info["first_yield_day"]
    return set(range(first, 31, info["interval"]))
