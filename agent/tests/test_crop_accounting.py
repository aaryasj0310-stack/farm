"""Unit tests for farm-wide crop self-glut accounting and unified crop planning architecture."""
import pytest
from config import CROPS, CROP_TILE_CAPS
from strategy.macro_planner import get_committed_crop_counts, MacroPlanner, _crop_score
from price_forecast import PriceForecast


class DummyTile:
    def __init__(self, x, y, kind="EMPTY", crop=None, is_plant=False, consecutive_unwatered=0):
        self.x = x
        self.y = y
        self.pos = (x, y)
        self.kind = kind
        self.crop = crop
        self.is_plant = is_plant
        self.consecutive_unwatered = consecutive_unwatered


class DummyFarm:
    def __init__(self, tiles, unlocked=("NW", "NE")):
        self.tiles = tiles
        self.unlocked = set(unlocked)
        self.money = 100000
        self.farmer = (4, 4)
        self.hands = []
        self.hires_today = 0

    def iter_tiles(self):
        return iter(self.tiles)

    def quadrant_of(self, pos):
        r, c = pos
        if r < 8 and c < 8:
            return "NW"
        elif r < 8 and c >= 8:
            return "NE"
        elif r >= 8 and c < 8:
            return "SW"
        else:
            return "SE"


def test_get_committed_crop_counts_basic():
    """Verify live plants are counted, while dead or non-plant tiles are excluded."""
    tiles = [
        DummyTile(0, 0, kind="PLANT", crop="MELON", is_plant=True, consecutive_unwatered=0),
        DummyTile(0, 1, kind="PLANT", crop="MELON", is_plant=True, consecutive_unwatered=1),
        DummyTile(0, 2, kind="PLANT", crop="MELON", is_plant=True, consecutive_unwatered=2),  # dead!
        DummyTile(0, 3, kind="EMPTY"),  # harvested / empty
        DummyTile(1, 0, kind="PLANT", crop="WHEAT", is_plant=True, consecutive_unwatered=0),
    ]
    farm = DummyFarm(tiles)
    counts = get_committed_crop_counts(farm)
    assert counts["MELON"] == 2  # 2 live melons, 1 dead excluded
    assert counts["WHEAT"] == 1
    assert counts["CARROT"] == 0

    # With planned additions
    planned = {"MELON": 3, "WHEAT": 2}
    counts_with_planned = get_committed_crop_counts(farm, planned=planned)
    assert counts_with_planned["MELON"] == 5
    assert counts_with_planned["WHEAT"] == 3


def test_melon_cap_enforced_against_live_farm_tiles():
    """If farm already has 12 melons, Phase 2b should not plant any more melons."""
    tiles = []
    # 12 live melons in NW
    for i in range(12):
        tiles.append(DummyTile(i // 4, i % 4, kind="PLANT", crop="MELON", is_plant=True))
    # remaining tiles empty in NE
    for r in range(4):
        for c in range(8, 12):
            tiles.append(DummyTile(r, c, kind="EMPTY"))

    farm = DummyFarm(tiles, unlocked=("NW", "NE"))
    counts = get_committed_crop_counts(farm)
    assert counts["MELON"] == 12
    assert counts["MELON"] >= CROP_TILE_CAPS["MELON"]


def test_marginal_score_drops_with_committed_tiles():
    """Evaluating a candidate tile against an existing committed pool should produce lower ROI due to self-glut."""
    fc = PriceForecast.load()
    score_first, _ = _crop_score("MELON", day=4, forecast=fc, boosts={}, own_tiles=1)
    score_later, _ = _crop_score("MELON", day=4, forecast=fc, boosts={}, own_tiles=12)
    assert score_first > score_later, f"Marginal score should decrease with own-glut: {score_first} vs {score_later}"


def test_tomato_cap_strictly_honored():
    """15 existing tomatoes + 1 planned = 16 (cap 16). 17th tomato must be blocked."""
    tiles = []
    for i in range(15):
        tiles.append(DummyTile(i // 4, i % 4, kind="PLANT", crop="TOMATO", is_plant=True))
    farm = DummyFarm(tiles)
    planned = {"TOMATO": 1}
    counts = get_committed_crop_counts(farm, planned=planned)
    assert counts["TOMATO"] == 16
    assert counts["TOMATO"] >= CROP_TILE_CAPS["TOMATO"]
