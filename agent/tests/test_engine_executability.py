"""Direct-engine executability proofs for scheduler-emitted operations.

Every operation the decision layer can emit is executed against the REAL
installed kaggriculture engine functions and its state transition asserted.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from engine_bridge import get_engine

eng = get_engine()


class Harness:
    """Teleporting unit harness around engine._apply_unit_action."""

    def __init__(self):
        self.farm = eng._new_farm(10, 3000)
        self.private = eng._new_private()
        self.market = eng._new_market()

    def unit(self, pos, action, idx=0, day=0):
        if idx == 0:
            self.farm["farmer"] = list(pos)
        else:
            while len(self.farm["hands"]) < idx:
                self.farm["hands"].append([4, 4])
            self.farm["hands"][idx - 1] = list(pos)
        eng._apply_unit_action(self.farm, self.private, idx, action,
                               10, day, 24)

    def tile(self, x, y):
        return self.farm["tiles"][y][x]


def test_plant_executes_with_seeds_and_consumes_one():
    h = Harness()
    assert eng._commit_unit("BUY_SEED", "WHEAT", 10, h.farm, h.private,
                            h.market) is True
    assert h.private["seeds"]["WHEAT"] == 1
    h.unit((2, 2), ["PLANT", "WHEAT"], day=0)
    t = h.tile(2, 2)
    assert isinstance(t, dict) and t["kind"] == "PLANT" and t["crop"] == "WHEAT"
    assert h.private["seeds"]["WHEAT"] == 0
    # second PLANT without seeds must NOT create a second plant elsewhere
    h.unit((3, 3), ["PLANT", "WHEAT"], day=0)
    assert h.tile(3, 3) is None


def test_water_sets_flag_and_skipday_kills():
    h = Harness()
    h.private["seeds"]["WHEAT"] = 1
    h.unit((2, 2), ["PLANT", "WHEAT"], day=0)
    h.unit((2, 2), ["WATER"], day=0)
    assert h.tile(2, 2)["watered_today"] is True
    eng._daily_refresh_plants(h.farm, 0, 24)
    assert h.tile(2, 2)["consecutive_unwatered"] == 0
    # unwatered fresh seed dies same night (cu starts at 1 -> 2 at EOD)
    h2 = Harness()
    h2.private["seeds"]["WHEAT"] = 1
    h2.unit((2, 3), ["PLANT", "WHEAT"], day=0)      # NW quadrant: owned
    assert h2.tile(2, 3)["kind"] == "PLANT"
    eng._daily_refresh_plants(h2.farm, 0, 24)   # cu: 1 -> 2 -> weed
    assert h2.tile(2, 3) == {"kind": "WEED"}


def test_build_place_pickup_feed_care_chain():
    h = Harness()
    # build coop on an owned empty tile
    h.unit((2, 2), ["BUILD_COOP"], day=0)
    assert h.tile(2, 2)["kind"] == "COOP"
    # buy goose -> lands in SHED; pickup at shed-access tile; place on coop
    assert eng._commit_unit("BUY_ANIMAL", "GOOSE", 300, h.farm, h.private,
                            h.market) is True
    assert h.private["shed"]["GOOSE"] == 1
    h.unit((4, 4), ["PICKUP", "GOOSE", 1], day=0)          # shed-adjacent
    assert h.private["inventories"][0].get("GOOSE") == 1
    h.unit((2, 2), ["PLACE", "GOOSE"], day=0)
    t = h.tile(2, 2)
    assert t.get("animal") == "GOOSE" and t["placed_day"] == 0
    # FEED consumes UNIT wheat (engine line 510) — stage via PICKUP first
    h.private["shed"]["WHEAT"] = 5
    h.unit((4, 4), ["PICKUP", "WHEAT", 2], day=0)
    assert h.private["inventories"][0]["WHEAT"] == 2
    h.unit((2, 2), ["FEED"], day=0)
    assert h.tile(2, 2)["fed_today"] is True
    assert h.private["inventories"][0]["WHEAT"] == 1
    h.unit((2, 2), ["CARE"], day=0)
    assert h.tile(2, 2)["cared_today"] is True
    # end-of-day refresh banks the care bonus (fed + cared, no production yet)
    eng._daily_refresh_animals(h.farm, 0)
    assert h.tile(2, 2)["pending_care_bonus"] == 1


def test_harvest_moves_yield_to_inventory():
    h = Harness()
    h.private["seeds"]["WHEAT"] = 1
    h.unit((2, 2), ["PLANT", "WHEAT"], day=0)
    for day in range(0, 5):
        h.unit((2, 2), ["WATER"], day=day)       # window = ages 2..4
        if day < 4:
            eng._daily_refresh_plants(h.farm, day, 24)
    assert h.tile(2, 2)["yield_units"] == 4      # unfertilized cap
    h.unit((2, 2), ["HARVEST"], day=4)
    assert h.private["inventories"][0]["WHEAT"] == 4
    assert h.tile(2, 2) is None                  # one-time crop cleared


def test_collect_fertilizer_requires_placed_animal():
    h = Harness()
    h.unit((2, 2), ["BUILD_COOP"], day=0)
    # bare coop: no fertilizer (comes from ANIMALS, not structures)
    h.unit((2, 2), ["COLLECT_FERTILIZER"], day=0)
    assert "FERTILIZER" not in h.private["inventories"][0]
    # place a goose, then collection works
    eng._commit_unit("BUY_ANIMAL", "GOOSE", 300, h.farm, h.private, h.market)
    h.unit((4, 4), ["PICKUP", "GOOSE", 1], day=0)
    h.unit((2, 2), ["PLACE", "GOOSE"], day=0)
    h.tile(2, 2)["fertilizer_available"] = True
    h.unit((2, 2), ["COLLECT_FERTILIZER"], day=0)
    assert h.private["inventories"][0].get("FERTILIZER") == 1
    assert h.tile(2, 2)["fertilizer_available"] is False


def test_sell_pulls_from_shed_and_floor_freezes_inventory():
    h = Harness()
    h.private["shed"]["CARROT"] = 3
    price = eng.market_price("CARROT", eng.MARKET_I0)
    for _ in range(3):
        assert eng._commit_unit("SELL", "CARROT", price, h.farm, h.private,
                                h.market) is True
    assert h.farm["money"] == 3000 + 3 * price
    assert h.private["shed"].get("CARROT", 0) == 0
    assert h.market["inventory"]["CARROT"] == eng.MARKET_I0 + 3

    # $1 floor freeze: units sold at $1 do NOT enter market inventory
    h.market["inventory"]["MELON"] = eng.MARKET_I0 + 20000   # quote = $1
    h.private["shed"]["MELON"] = 5
    before = h.market["inventory"]["MELON"]
    for _ in range(5):
        assert eng._commit_unit("SELL", "MELON", 1, h.farm, h.private,
                                h.market) is True
    assert h.farm["money"] == 3000 + 3 * price + 5
    assert h.market["inventory"]["MELON"] == before           # frozen


def test_buy_seed_product_animal_commit_paths():
    h = Harness()
    inv = h.market["inventory"]
    assert eng._commit_unit("BUY_SEED", "CARROT", 20, h.farm, h.private,
                            h.market) is True
    assert h.private["seeds"]["CARROT"] == 1 and h.farm["money"] == 2980
    px = eng.market_price("WHEAT", inv["WHEAT"] - 1)   # post-buy quote rule
    assert eng._commit_unit("BUY_PRODUCT", "WHEAT", px, h.farm, h.private,
                            h.market) is True
    assert h.private["shed"]["WHEAT"] == 1 and inv["WHEAT"] == eng.MARKET_I0 - 1
    assert eng._commit_unit("BUY_ANIMAL", "SHEEP", 500, h.farm, h.private,
                            h.market) is True
    assert h.private["shed"]["SHEEP"] == 1


def test_hire_spawn_geometry_nwse_least_occupied():
    h = Harness()                                    # farmer at (4,4)
    eng._do_hire(h.farm, h.private, 10)
    eng._do_hire(h.farm, h.private, 10)
    eng._do_hire(h.farm, h.private, 10)
    assert [tuple(p) for p in h.farm["hands"]] == \
        [(5, 4), (4, 5), (5, 5)]
    assert len(h.private["inventories"]) == 4        # main + 3 hands
    assert h.farm["money"] == 3000 - (1 + 1 + 2)     # fib(0..2)


def test_buy_land_unlocks_ne_quadrant_tiles():
    h = Harness()
    assert h.tile(9, 0) == "LOCKED"
    eng._do_buy_land(h.farm, 10)
    assert "NE" in h.farm["unlocked_quadrants"]
    assert h.tile(9, 0) is None                      # LOCKED flipped to empty
    assert h.farm["money"] == 2000                   # $1000 NE price
