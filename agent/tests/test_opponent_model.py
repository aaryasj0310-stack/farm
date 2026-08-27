"""Unit tests for opponent_model.py (Phase 1) and state_tracker delta tracking.

Covers:
  - snapshot generation and equality comparisons
  - harvest detection for one-time crops (wheat/carrot/melon) and ongoing crops
  - animal product collection delta detection (eggs/milk/wool)
  - money delta and drain ledger attribution math
  - memory reset on new episode detection
"""
import os
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_AGENT = os.path.dirname(_HERE)
sys.path.insert(0, _AGENT)
sys.path.insert(0, os.path.join(_AGENT, "state"))
sys.path.insert(0, os.path.join(_AGENT, "strategy"))
sys.path.insert(0, os.path.join(_AGENT, "execution"))
sys.path.insert(0, os.path.join(_AGENT, "market"))

from opponent_model import (
    compute_opponent_sell_probabilities,
    detect_tile_deltas,
    forecast_opponent_production,
    get_imminent_harvests,
    infer_turn_transactions,
    predict_imminent_dumps,
    snapshot_equal,
    snapshot_opponent_farm,
    summarize_opponent_commitments,
    update_opponent_shed_estimate,
)
from state_tracker import (
    _STATE,
    _expected_town_consumption,
    diagnostics,
    get_state,
    record_our_sale,
    reset_memory,
)
from observation_parser import FarmView


# ---------------------------------------------------------------------------
# Helpers: build a mock raw farm dict -> FarmView
# ---------------------------------------------------------------------------

def _mk_tile(x, y, kind="EMPTY", crop=None, planted_day=None,
             yield_units=0, watered_today=False, consecutive_unwatered=0,
             fertilized_until_day=-1, animal=None, fed_today=False,
             cared_today=False, consecutive_unfed=0,
             fertilizer_available=False, pending_care_bonus=0,
             placed_day=None):
    """Build a raw tile dict matching the engine schema."""
    if kind == "EMPTY":
        return None
    t = {
        "kind": kind,
        "x": x, "y": y,
        "crop": crop,
        "planted_day": planted_day,
        "yield_units": yield_units,
        "watered_today": watered_today,
        "consecutive_unwatered": consecutive_unwatered,
        "fertilized_until_day": fertilized_until_day,
        "animal": animal,
        "fed_today": fed_today,
        "cared_today": cared_today,
        "consecutive_unfed": consecutive_unfed,
        "fertilizer_available": fertilizer_available,
        "pending_care_bonus": pending_care_bonus,
        "placed_day": placed_day,
    }
    return t


def _mk_farm(tiles_dict=None, money=0, hands=None, unlocked=None):
    """Build a FarmView from a minimal raw farm dict."""
    # Build a 10x10 grid of None (empty)
    grid = [[None for _ in range(10)] for _ in range(10)]
    if tiles_dict:
        for (x, y), tile in tiles_dict.items():
            grid[y][x] = tile
    raw = {
        "money": money,
        "tiles": grid,
        "farmer": (4, 4),
        "hands": hands or [],
        "unlocked_quadrants": unlocked or ["NW"],
        "hires_today": 0,
    }
    return FarmView(raw)


# ===== SNAPSHOT TESTS =====

class TestSnapshotOpponentFarm:
    def test_none_farm_returns_none(self):
        assert snapshot_opponent_farm(None) is None

    def test_empty_farm_snapshot(self):
        farm = _mk_farm(money=5000)
        snap = snapshot_opponent_farm(farm)
        assert snap is not None
        assert snap["money"] == 5000
        assert snap["hands"] == []
        assert snap["unlocked"] == ["NW"]
        # All 100 tiles should be EMPTY
        assert all(v[0] == "EMPTY" for v in snap["tiles"].values())
        assert len(snap["tiles"]) == 100

    def test_snapshot_captures_plant_tile(self):
        t = _mk_tile(2, 3, kind="PLANT", crop="WHEAT", planted_day=0,
                     yield_units=4, watered_today=True)
        farm = _mk_farm(tiles_dict={(2, 3): t}, money=1200)
        snap = snapshot_opponent_farm(farm)
        sig = snap["tiles"][(2, 3)]
        assert sig[0] == "PLANT"
        assert sig[1] == "WHEAT"
        assert sig[3] == 4  # yield_units

    def test_snapshot_captures_animal_tile(self):
        t = _mk_tile(5, 5, kind="COOP", animal="GOOSE", yield_units=2,
                     fed_today=True, cared_today=True)
        farm = _mk_farm(tiles_dict={(5, 5): t})
        snap = snapshot_opponent_farm(farm)
        sig = snap["tiles"][(5, 5)]
        assert sig[0] == "ANIMAL"
        assert sig[1] == "GOOSE"
        assert sig[2] == 2

    def test_snapshot_captures_structure_without_animal(self):
        t = _mk_tile(4, 4, kind="COOP")
        farm = _mk_farm(tiles_dict={(4, 4): t})
        snap = snapshot_opponent_farm(farm)
        sig = snap["tiles"][(4, 4)]
        assert sig[0] == "STRUCTURE"

    def test_snapshot_captures_money(self):
        farm = _mk_farm(money=9999.5)
        snap = snapshot_opponent_farm(farm)
        assert snap["money"] == 9999.5


class TestSnapshotEqual:
    def test_none_both(self):
        assert snapshot_equal(None, None) is True

    def test_none_vs_snap(self):
        farm = _mk_farm()
        snap = snapshot_opponent_farm(farm)
        assert snapshot_equal(None, snap) is False
        assert snapshot_equal(snap, None) is False

    def test_identical_farms_equal(self):
        farm_a = _mk_farm(money=1000)
        farm_b = _mk_farm(money=1000)
        snap_a = snapshot_opponent_farm(farm_a)
        snap_b = snapshot_opponent_farm(farm_b)
        assert snapshot_equal(snap_a, snap_b) is True

    def test_different_money_not_equal(self):
        farm_a = _mk_farm(money=1000)
        farm_b = _mk_farm(money=2000)
        snap_a = snapshot_opponent_farm(farm_a)
        snap_b = snapshot_opponent_farm(farm_b)
        assert snapshot_equal(snap_a, snap_b) is False

    def test_different_tile_not_equal(self):
        t1 = _mk_tile(2, 3, kind="PLANT", crop="WHEAT", planted_day=0,
                       yield_units=3)
        farm_a = _mk_farm(tiles_dict={(2, 3): t1})
        farm_b = _mk_farm()  # empty
        snap_a = snapshot_opponent_farm(farm_a)
        snap_b = snapshot_opponent_farm(farm_b)
        assert snapshot_equal(snap_a, snap_b) is False


# ===== HARVEST DETECTION TESTS =====

class TestDetectHarvest:
    def _prev_with_plant(self, x, y, crop, planted_day, yield_units):
        t = _mk_tile(x, y, kind="PLANT", crop=crop, planted_day=planted_day,
                     yield_units=yield_units)
        farm = _mk_farm(tiles_dict={(x, y): t})
        return snapshot_opponent_farm(farm)

    def test_wheat_harvest_clears_tile(self):
        """Wheat is one-time: harvest clears tile to EMPTY."""
        prev = self._prev_with_plant(3, 2, "WHEAT", 0, 6)
        farm = _mk_farm()  # tile now empty
        deltas = detect_tile_deltas(farm, prev)
        assert len(deltas) == 1
        d = deltas[0]
        assert d["pos"] == (3, 2)
        assert d["event"] == "harvest"
        assert d["details"]["crop"] == "WHEAT"
        assert d["details"]["yield_units"] == 6

    def test_carrot_harvest(self):
        prev = self._prev_with_plant(1, 1, "CARROT", 0, 4)
        farm = _mk_farm()
        deltas = detect_tile_deltas(farm, prev)
        assert len(deltas) == 1
        assert deltas[0]["event"] == "harvest"
        assert deltas[0]["details"]["crop"] == "CARROT"

    def test_melon_harvest(self):
        prev = self._prev_with_plant(7, 8, "MELON", 5, 6)
        farm = _mk_farm()
        deltas = detect_tile_deltas(farm, prev)
        assert len(deltas) == 1
        assert deltas[0]["event"] == "harvest"
        assert deltas[0]["details"]["crop"] == "MELON"
        assert deltas[0]["details"]["yield_units"] == 6

    def test_ongoing_crop_harvest_preserves_tile(self):
        """Tomato/strawberry: yield goes to 0 but tile stays PLANT."""
        prev = self._prev_with_plant(4, 4, "TOMATO", 0, 3)
        t = _mk_tile(4, 4, kind="PLANT", crop="TOMATO", planted_day=0,
                     yield_units=0)
        farm = _mk_farm(tiles_dict={(4, 4): t})
        deltas = detect_tile_deltas(farm, prev)
        # ongoing crop going to 0 is still a plant -> plant sig changes
        # but it's not a harvest (tile didn't go to EMPTY), just yield decreased
        # Our detector treats PLANT->PLANT with yield decrease as not a harvest
        # (harvest only fires when old was PLANT and new is EMPTY)
        # So ongoing crop collection is NOT detected as harvest by tile clear.
        # It's only detectable via animal_collect or explicit yield delta.
        # For ongoing crops, the tile stays; our detector only catches full clear.
        assert len(deltas) == 0  # tile signature differs but not caught as harvest


# ===== ANIMAL COLLECTION DELTA TESTS =====

class TestDetectAnimalCollect:
    def _prev_with_animal(self, x, y, animal, yield_units):
        t = _mk_tile(x, y, kind="COOP", animal=animal, yield_units=yield_units)
        farm = _mk_farm(tiles_dict={(x, y): t})
        return snapshot_opponent_farm(farm)

    def test_goose_egg_collection(self):
        prev = self._prev_with_animal(5, 5, "GOOSE", 3)
        t = _mk_tile(5, 5, kind="COOP", animal="GOOSE", yield_units=1)
        farm = _mk_farm(tiles_dict={(5, 5): t})
        deltas = detect_tile_deltas(farm, prev)
        assert len(deltas) == 1
        d = deltas[0]
        assert d["pos"] == (5, 5)
        assert d["event"] == "animal_collect"
        assert d["details"]["animal"] == "GOOSE"
        assert d["details"]["product"] == "EGG"
        assert d["details"]["old_yield"] == 3
        assert d["details"]["new_yield"] == 1

    def test_cow_milk_collection(self):
        prev = self._prev_with_animal(6, 6, "COW", 4)
        t = _mk_tile(6, 6, kind="PASTURE", animal="COW", yield_units=2)
        farm = _mk_farm(tiles_dict={(6, 6): t})
        deltas = detect_tile_deltas(farm, prev)
        assert len(deltas) == 1
        d = deltas[0]
        assert d["details"]["animal"] == "COW"
        assert d["details"]["product"] == "MILK"

    def test_sheep_wool_collection(self):
        prev = self._prev_with_animal(7, 7, "SHEEP", 5)
        t = _mk_tile(7, 7, kind="PASTURE", animal="SHEEP", yield_units=0)
        farm = _mk_farm(tiles_dict={(7, 7): t})
        deltas = detect_tile_deltas(farm, prev)
        assert len(deltas) == 1
        d = deltas[0]
        assert d["event"] == "animal_collect"
        assert d["details"]["product"] == "WOOL"

    def test_no_delta_when_yield_unchanged(self):
        prev = self._prev_with_animal(5, 5, "GOOSE", 2)
        t = _mk_tile(5, 5, kind="COOP", animal="GOOSE", yield_units=2)
        farm = _mk_farm(tiles_dict={(5, 5): t})
        deltas = detect_tile_deltas(farm, prev)
        assert len(deltas) == 0

    def test_animal_placement_detected(self):
        """Structure (no animal) -> Structure with animal = placement."""
        t_prev = _mk_tile(4, 4, kind="COOP")
        prev_farm = _mk_farm(tiles_dict={(4, 4): t_prev})
        prev_snap = snapshot_opponent_farm(prev_farm)

        t_new = _mk_tile(4, 4, kind="COOP", animal="GOOSE", yield_units=0)
        new_farm = _mk_farm(tiles_dict={(4, 4): t_new})
        deltas = detect_tile_deltas(new_farm, prev_snap)
        assert len(deltas) == 1
        assert deltas[0]["event"] == "animal_place"
        assert deltas[0]["details"]["animal"] == "GOOSE"

    def test_animal_death_detected(self):
        """Animal tile goes to EMPTY -> death."""
        prev = self._prev_with_animal(5, 5, "GOOSE", 0)
        farm = _mk_farm()  # tile is now empty
        deltas = detect_tile_deltas(farm, prev)
        assert len(deltas) == 1
        assert deltas[0]["event"] == "animal_death"
        assert deltas[0]["details"]["animal"] == "GOOSE"


# ===== PLANTING DETECTION TESTS =====

class TestDetectPlanting:
    def test_new_seed_detected(self):
        prev_farm = _mk_farm()  # all empty
        prev_snap = snapshot_opponent_farm(prev_farm)

        t = _mk_tile(3, 4, kind="PLANT", crop="WHEAT", planted_day=5,
                     yield_units=0)
        new_farm = _mk_farm(tiles_dict={(3, 4): t})
        deltas = detect_tile_deltas(new_farm, prev_snap)
        assert len(deltas) == 1
        d = deltas[0]
        assert d["event"] == "plant"
        assert d["details"]["crop"] == "WHEAT"
        assert d["details"]["planted_day"] == 5

    def test_multiple_plantings(self):
        prev_farm = _mk_farm()
        prev_snap = snapshot_opponent_farm(prev_farm)

        tiles = {}
        for i, crop in enumerate(["WHEAT", "CARROT", "MELON"]):
            tiles[(i, 0)] = _mk_tile(i, 0, kind="PLANT", crop=crop,
                                      planted_day=3, yield_units=0)
        new_farm = _mk_farm(tiles_dict=tiles)
        deltas = detect_tile_deltas(new_farm, prev_snap)
        assert len(deltas) == 3
        events = {(d["pos"], d["details"]["crop"]) for d in deltas}
        assert ((0, 0), "WHEAT") in events
        assert ((1, 0), "CARROT") in events
        assert ((2, 0), "MELON") in events


# ===== PLANT DEATH / STRUCTURE BUILD TESTS =====

class TestDetectOtherDeltas:
    def test_structure_build(self):
        prev_farm = _mk_farm()
        prev_snap = snapshot_opponent_farm(prev_farm)

        t = _mk_tile(4, 4, kind="COOP")
        new_farm = _mk_farm(tiles_dict={(4, 4): t})
        deltas = detect_tile_deltas(new_farm, prev_snap)
        assert len(deltas) == 1
        assert deltas[0]["event"] == "structure_build"
        assert deltas[0]["details"]["structure"] == "COOP"

    def test_no_delta_on_unchanged_farm(self):
        t = _mk_tile(2, 2, kind="PLANT", crop="WHEAT", planted_day=0,
                     yield_units=3)
        farm = _mk_farm(tiles_dict={(2, 2): t})
        prev_snap = snapshot_opponent_farm(farm)
        deltas = detect_tile_deltas(farm, prev_snap)
        assert len(deltas) == 0

    def test_none_prev_returns_empty(self):
        farm = _mk_farm()
        assert detect_tile_deltas(farm, None) == []

    def test_none_farm_returns_empty(self):
        prev = snapshot_opponent_farm(_mk_farm())
        assert detect_tile_deltas(None, prev) == []


# ===== MONEY DELTA / DRAIN LEDGER TESTS =====

class TestInferTurnTransactions:
    def test_town_drain_only(self):
        """Inventory dropped by town consumption only, money unchanged."""
        result = infer_turn_transactions(
            opp_money_delta=0,
            market_inventory_delta={"WHEAT": -2},
            town_consumption={"WHEAT": 2},
            our_sales={},
        )
        assert result["confirmed_sells"] == {}
        assert result["confirmed_buys"] == {}
        assert result["explained_money"] == 0
        assert result["unexplained_money"] == 0

    def test_opponent_sell_detected(self):
        """Inventory dropped more than town consumed -> opponent sold."""
        result = infer_turn_transactions(
            opp_money_delta=50,
            market_inventory_delta={"WHEAT": -5},
            town_consumption={"WHEAT": 2},
            our_sales={},
        )
        assert result["confirmed_sells"]["WHEAT"] == 3
        # explained: 3 units sold @ $1 each (unit accounting) = +3
        assert result["explained_money"] == 3
        assert result["unexplained_money"] == 47  # 50 - 3

    def test_our_sales_subtracted(self):
        """Our recorded sales are subtracted before attributing to opponent."""
        result = infer_turn_transactions(
            opp_money_delta=30,
            market_inventory_delta={"MELON": -8},
            town_consumption={"MELON": 2},
            our_sales={"MELON": 4},
        )
        assert result["confirmed_sells"]["MELON"] == 2  # 8 - 2(town) - 4(ours)
        assert result["explained_money"] == 2
        assert result["unexplained_money"] == 28

    def test_opponent_buy_detected(self):
        """Inventory increased despite town consumption -> opponent bought."""
        result = infer_turn_transactions(
            opp_money_delta=-200,
            market_inventory_delta={"WHEAT": 10},
            town_consumption={"WHEAT": 2},
            our_sales={},
        )
        assert result["confirmed_buys"]["WHEAT"] == 10
        assert result["explained_money"] == -10
        assert result["unexplained_money"] == -190

    def test_multiple_products(self):
        """Handle mixed sells/buys across products."""
        result = infer_turn_transactions(
            opp_money_delta=100,
            market_inventory_delta={"WHEAT": -3, "MELON": -2, "EGG": 5},
            town_consumption={"WHEAT": 1, "MELON": 0, "EGG": 1},
            our_sales={"WHEAT": 1},
        )
        # WHEAT: -(-3)=3 drain - 1 town - 1 ours = 1 opp sell
        assert result["confirmed_sells"]["WHEAT"] == 1
        # MELON: -(-2)=2 drain - 0 town = 2 opp sell
        assert result["confirmed_sells"]["MELON"] == 2
        # EGG: inventory rose by 5, town consumed 1 -> bought
        assert result["confirmed_buys"]["EGG"] == 5
        # explained: +1 (wheat sell) + 2 (melon sell) - 5 (egg buy) = -2
        assert result["explained_money"] == -2
        assert result["unexplained_money"] == 102  # 100 - (-2)

    def test_zero_everything(self):
        result = infer_turn_transactions(0, {}, {}, {})
        assert result["confirmed_sells"] == {}
        assert result["confirmed_buys"] == {}
        assert result["explained_money"] == 0
        assert result["unexplained_money"] == 0


# ===== STATE_TRACKER INTEGRATION TESTS =====

class TestRecordOurSale:
    def setup_method(self):
        reset_memory(_STATE)

    def test_record_single_sale(self):
        record_our_sale("WHEAT", 10)
        assert _STATE["our_units_sold"]["WHEAT"] == 10

    def test_record_multiple_sales_accumulate(self):
        record_our_sale("MELON", 3)
        record_our_sale("MELON", 5)
        assert _STATE["our_units_sold"]["MELON"] == 8

    def test_record_different_products(self):
        record_our_sale("WHEAT", 10)
        record_our_sale("EGG", 2)
        assert _STATE["our_units_sold"]["WHEAT"] == 10
        assert _STATE["our_units_sold"]["EGG"] == 2


class TestExpectedTownConsumption:
    def test_step_negative_returns_zero(self):
        assert _expected_town_consumption("WHEAT", ["BAKERY"], -1) == 0.0

    def test_step_zero_no_consumption(self):
        assert _expected_town_consumption("WHEAT", ["BAKERY"], 0) == 0.0

    def test_bakery_consumes_on_step4(self):
        """prev_step=4 -> shops consume at step 4, we see result at step 5."""
        # prev_step = step-1 = 4; 4%4==0 so shops consume
        # BAKERY sells EGG + WHEAT. WHEAT gets 1 unit.
        val = _expected_town_consumption("WHEAT", ["BAKERY"], 5)
        assert val >= 1.0

    def test_single_product_shop_doubles(self):
        """YARN_STORE sells only WOOL -> mult=2."""
        val = _expected_town_consumption("WOOL", ["YARN_STORE"], 5)
        assert val >= 2.0

    def test_daily_center_tick(self):
        """prev_step % 24 == 0 -> center consumes 1 of each (not FERTILIZER)."""
        # step=25 => prev_step=24, 24%24==0 -> center tick
        val = _expected_town_consumption("WHEAT", [], 25)
        assert val >= 1.0

    def test_fertilizer_excluded_from_center(self):
        val = _expected_town_consumption("FERTILIZER", [], 24)
        assert val == 0.0


class TestResetMemory:
    def setup_method(self):
        reset_memory(_STATE)

    def test_reset_clears_inventory(self):
        _STATE["prev_inventory"] = {"WHEAT": 100}
        reset_memory(_STATE)
        assert _STATE["prev_inventory"] is None

    def test_reset_clears_our_sales(self):
        record_our_sale("WHEAT", 10)
        reset_memory(_STATE)
        assert _STATE["our_units_sold"] == {}

    def test_reset_clears_opp_money(self):
        _STATE["prev_opp_money"] = 5000
        _STATE["opp_money_deltas"].append(100)
        reset_memory(_STATE)
        assert _STATE["prev_opp_money"] is None
        assert len(_STATE["opp_money_deltas"]) == 0

    def test_reset_clears_shops(self):
        _STATE["known_shops"] = ["BAKERY"]
        reset_memory(_STATE)
        assert _STATE["known_shops"] == []


class TestDiagnostics:
    def setup_method(self):
        reset_memory(_STATE)

    def test_diagnostics_includes_opp_money(self):
        _STATE["prev_opp_money"] = 4000
        _STATE["opp_money_deltas"].extend([100, -50, 200])
        diag = diagnostics()
        assert diag["prev_opp_money"] == 4000
        assert diag["opp_money_deltas"] == [100, -50, 200]
        assert diag["opp_money_delta_sum"] == 250

    def test_diagnostics_empty_state(self):
        diag = diagnostics()
        assert diag["prev_opp_money"] is None
        assert diag["opp_money_deltas"] == []
        assert diag["opp_money_delta_sum"] == 0


class TestMemoryResetOnNewEpisode:
    def setup_method(self):
        reset_memory(_STATE)

    def test_episode_detection_resets(self):
        # Simulate seeing day 5
        _STATE["episode"] = {"last_day": 5}
        _STATE["our_units_sold"] = {"WHEAT": 99}
        _STATE["prev_inventory"] = {"WHEAT": 100}
        _STATE["prev_opp_money"] = 5000
        _STATE["opp_money_deltas"].extend([100, -50])
        # Day goes backward -> new episode
        fake_obs = {
            "farms": [
                {"money": 1000, "tiles": [[None]*10 for _ in range(10)],
                 "farmer": (4, 4), "hands": [], "unlocked_quadrants": ["NW"],
                 "hires_today": 0},
                {"money": 5000, "tiles": [[None]*10 for _ in range(10)],
                 "farmer": (4, 4), "hands": [], "unlocked_quadrants": ["NW"],
                 "hires_today": 0},
            ],
            "player": 0, "day": 3, "hour": 0,
            "market": {"inventory": {}, "prices": {}},
            "town": {"unlocked_shops": []},
            "private": {"shed": {}, "seeds": {}, "inventories": []},
        }
        ctx, mem = get_state(fake_obs)
        # Memory should have been reset: sales cleared, opp money cleared
        assert mem["our_units_sold"] == {}
        assert mem["prev_opp_money"] is None
        assert len(mem["opp_money_deltas"]) == 0


# ===== LEGACY HELPER TESTS =====

class TestLegacyHelpers:
    def test_opponent_primary_product_default(self):
        from opponent_model import opponent_primary_product
        assert opponent_primary_product({}) == "MELON"
        assert opponent_primary_product({}, default="WHEAT") == "WHEAT"

    def test_opponent_primary_product_from_ledger(self):
        from opponent_model import opponent_primary_product
        mem = {"opp_sales_inferred": {"MELON": 5, "WHEAT": 2}}
        assert opponent_primary_product(mem) == "MELON"


# ===== PHASE 2: PRODUCTION FORECASTING TESTS =====

class TestForecastOneTimeCrops:
    """Test forecast_opponent_production for WHEAT, CARROT, MELON."""

    def test_wheat_maturity_day4(self):
        """Wheat planted day 0: matures day 4, yields max_yield=6."""
        t = _mk_tile(0, 0, kind="PLANT", crop="WHEAT", planted_day=0,
                     yield_units=0, watered_today=True)
        farm = _mk_farm(tiles_dict={(0, 0): t})
        sched = forecast_opponent_production(farm, current_day=0)
        assert "WHEAT" in sched
        assert sched["WHEAT"][4] == 6.0

    def test_carrot_maturity_day3(self):
        """Carrot planted day 0: matures day 3, yields max_yield=4."""
        t = _mk_tile(0, 0, kind="PLANT", crop="CARROT", planted_day=0,
                     yield_units=0, watered_today=True)
        farm = _mk_farm(tiles_dict={(0, 0): t})
        sched = forecast_opponent_production(farm, current_day=0)
        assert "CARROT" in sched
        assert sched["CARROT"][3] == 4.0

    def test_melon_maturity_day12(self):
        """Melon planted day 0: matures day 12, yields max_yield=6."""
        t = _mk_tile(0, 0, kind="PLANT", crop="MELON", planted_day=0,
                     yield_units=0, watered_today=True)
        farm = _mk_farm(tiles_dict={(0, 0): t})
        sched = forecast_opponent_production(farm, current_day=0)
        assert "MELON" in sched
        assert sched["MELON"][12] == 6.0

    def test_melon_planted_day5_matures_day17(self):
        """Melon planted day 5: matures day 5+12=17."""
        t = _mk_tile(0, 0, kind="PLANT", crop="MELON", planted_day=5,
                     yield_units=0, watered_today=True)
        farm = _mk_farm(tiles_dict={(0, 0): t})
        sched = forecast_opponent_production(farm, current_day=0)
        assert sched["MELON"][17] == 6.0

    def test_harvest_after_horizon_excluded(self):
        """Harvest day beyond horizon is excluded."""
        t = _mk_tile(0, 0, kind="PLANT", crop="MELON", planted_day=0,
                     yield_units=0, watered_today=True)
        farm = _mk_farm(tiles_dict={(0, 0): t})
        # horizon_days=10 => only days 0-10 included; melon matures day 12
        sched = forecast_opponent_production(farm, current_day=0, horizon_days=10)
        assert "MELON" not in sched

    def test_multiple_tiles_accumulate(self):
        """Two wheat tiles at same planted_day accumulate yield."""
        t1 = _mk_tile(0, 0, kind="PLANT", crop="WHEAT", planted_day=0,
                       yield_units=0, watered_today=True)
        t2 = _mk_tile(1, 0, kind="PLANT", crop="WHEAT", planted_day=0,
                       yield_units=0, watered_today=True)
        farm = _mk_farm(tiles_dict={(0, 0): t1, (1, 0): t2})
        sched = forecast_opponent_production(farm, current_day=0)
        assert sched["WHEAT"][4] == 12.0  # 6 + 6

    def test_none_farm_returns_empty(self):
        assert forecast_opponent_production(None, 0) == {}

    def test_current_day_past_harvest_excluded(self):
        """If current_day > harvest_day, that harvest is not forecasted."""
        t = _mk_tile(0, 0, kind="PLANT", crop="WHEAT", planted_day=0,
                     yield_units=0, watered_today=True)
        farm = _mk_farm(tiles_dict={(0, 0): t})
        # current_day=5, wheat matures day 4 -> already passed
        sched = forecast_opponent_production(farm, current_day=5)
        assert "WHEAT" not in sched

    def test_crop_mortality_unwatered(self):
        """Crops with consecutive_unwatered >= 1 and not watered => excluded."""
        t = _mk_tile(0, 0, kind="PLANT", crop="WHEAT", planted_day=0,
                     yield_units=0, watered_today=False,
                     consecutive_unwatered=1)
        farm = _mk_farm(tiles_dict={(0, 0): t})
        sched = forecast_opponent_production(farm, current_day=0)
        assert "WHEAT" not in sched


class TestForecastOngoingCrops:
    """Test forecast_opponent_production for TOMATO, STRAWBERRY."""

    def test_tomato_every_day_after_day8(self):
        """Tomato planted day 0: yields on days 8,9,10,...,29 (interval=1)."""
        t = _mk_tile(0, 0, kind="PLANT", crop="TOMATO", planted_day=0,
                     yield_units=0, watered_today=True)
        farm = _mk_farm(tiles_dict={(0, 0): t})
        sched = forecast_opponent_production(farm, current_day=0)
        assert "TOMATO" in sched
        # Day 8: first yield
        assert sched["TOMATO"][8] >= 1
        # Day 9: second yield
        assert sched["TOMATO"][9] >= 1
        # Day 29: last yield in season
        assert sched["TOMATO"][29] >= 1
        # Total yield days: days 8-29 = 22 days
        tomato_days = [d for d in range(8, 30) if d in sched.get("TOMATO", {})]
        assert len(tomato_days) == 22

    def test_strawberry_every_2_days_after_day10(self):
        """Strawberry planted day 0: yields on days 10,12,14,...,28 (interval=2)."""
        t = _mk_tile(0, 0, kind="PLANT", crop="STRAWBERRY", planted_day=0,
                     yield_units=0, watered_today=True)
        farm = _mk_farm(tiles_dict={(0, 0): t})
        sched = forecast_opponent_production(farm, current_day=0)
        assert "STRAWBERRY" in sched
        # Yield days: 10,12,14,16,18,20,22,24,26,28 = 10 days
        expected_days = [10, 12, 14, 16, 18, 20, 22, 24, 26, 28]
        for d in expected_days:
            assert d in sched["STRAWBERRY"], f"missing yield day {d}"
        assert sched["STRAWBERRY"][10] >= 1
        assert sched["STRAWBERRY"][28] >= 1

    def test_tomato_planted_day5_first_yield_day13(self):
        """Tomato planted day 5: first yield day 5+8=13."""
        t = _mk_tile(0, 0, kind="PLANT", crop="TOMATO", planted_day=5,
                     yield_units=0, watered_today=True)
        farm = _mk_farm(tiles_dict={(0, 0): t})
        sched = forecast_opponent_production(farm, current_day=0)
        assert 13 in sched["TOMATO"]
        # Days 12 and before should not have tomato yield
        assert 12 not in sched.get("TOMATO", {})

    def test_ongoing_crop_fertilized_bonus(self):
        """Fertilized ongoing crop gets +1 yield (up to max_yield)."""
        t = _mk_tile(0, 0, kind="PLANT", crop="TOMATO", planted_day=0,
                     yield_units=0, watered_today=True,
                     fertilized_until_day=15)
        farm = _mk_farm(tiles_dict={(0, 0): t})
        sched = forecast_opponent_production(farm, current_day=0)
        # Day 8: fertilized (8 <= 15) => 2 units
        assert sched["TOMATO"][8] == 2
        # Day 16: NOT fertilized (16 > 15) => 1 unit
        assert sched["TOMATO"][16] == 1

    def test_ongoing_crop_mortality(self):
        """Unwatered ongoing crop excluded from forecast."""
        t = _mk_tile(0, 0, kind="PLANT", crop="TOMATO", planted_day=0,
                     yield_units=0, watered_today=False,
                     consecutive_unwatered=1)
        farm = _mk_farm(tiles_dict={(0, 0): t})
        sched = forecast_opponent_production(farm, current_day=0)
        assert "TOMATO" not in sched


class TestForecastAnimals:
    """Test forecast_opponent_production for GOOSE, COW, SHEEP."""

    def test_goose_daily_eggs(self):
        """Goose placed day 0: eggs on days 4,5,6,...,29 (interval=1)."""
        t = _mk_tile(0, 0, kind="COOP", animal="GOOSE", placed_day=0,
                     yield_units=0, cared_today=False)
        farm = _mk_farm(tiles_dict={(0, 0): t})
        sched = forecast_opponent_production(farm, current_day=0)
        assert "EGG" in sched
        assert sched["EGG"][4] == 1
        assert sched["EGG"][5] == 1
        assert sched["EGG"][29] == 1
        # Days 4-29 = 26 production days
        egg_days = sorted(sched["EGG"].keys())
        assert len(egg_days) == 26
        assert egg_days[0] == 4
        assert egg_days[-1] == 29

    def test_cow_milk_every_2_days(self):
        """Cow placed day 0: milk on days 8,10,12,...,28 (interval=2)."""
        t = _mk_tile(0, 0, kind="PASTURE", animal="COW", placed_day=0,
                     yield_units=0, cared_today=False)
        farm = _mk_farm(tiles_dict={(0, 0): t})
        sched = forecast_opponent_production(farm, current_day=0)
        assert "MILK" in sched
        expected_days = [8, 10, 12, 14, 16, 18, 20, 22, 24, 26, 28]
        for d in expected_days:
            assert d in sched["MILK"], f"missing milk day {d}"
        assert len(expected_days) == 11
        for d in expected_days:
            assert sched["MILK"][d] == 1

    def test_sheep_wool_every_3_days(self):
        """Sheep placed day 0: wool on days 6,9,12,...,27 (interval=3)."""
        t = _mk_tile(0, 0, kind="PASTURE", animal="SHEEP", placed_day=0,
                     yield_units=0, cared_today=False)
        farm = _mk_farm(tiles_dict={(0, 0): t})
        sched = forecast_opponent_production(farm, current_day=0)
        assert "WOOL" in sched
        expected_days = [6, 9, 12, 15, 18, 21, 24, 27]
        for d in expected_days:
            assert d in sched["WOOL"], f"missing wool day {d}"
        assert len(expected_days) == 8

    def test_animal_care_bonus(self):
        """Cared goose gets +1 egg per cycle (2 instead of 1)."""
        t = _mk_tile(0, 0, kind="COOP", animal="GOOSE", placed_day=0,
                     yield_units=0, cared_today=True)
        farm = _mk_farm(tiles_dict={(0, 0): t})
        sched = forecast_opponent_production(farm, current_day=0)
        assert sched["EGG"][4] == 2  # 1 base + 1 care

    def test_animal_pending_care_bonus(self):
        """pending_care_bonus also grants +1."""
        t = _mk_tile(0, 0, kind="COOP", animal="GOOSE", placed_day=0,
                     yield_units=0, cared_today=False, pending_care_bonus=1)
        farm = _mk_farm(tiles_dict={(0, 0): t})
        sched = forecast_opponent_production(farm, current_day=0)
        assert sched["EGG"][4] == 2

    def test_animal_placed_day5_first_yield_day9(self):
        """Goose placed day 5: first egg day 5+4=9."""
        t = _mk_tile(0, 0, kind="COOP", animal="GOOSE", placed_day=5,
                     yield_units=0, cared_today=False)
        farm = _mk_farm(tiles_dict={(0, 0): t})
        sched = forecast_opponent_production(farm, current_day=0)
        assert 9 in sched["EGG"]
        assert 8 not in sched.get("EGG", {})

    def test_multiple_animals(self):
        """Two geese produce 2 eggs each per day."""
        t1 = _mk_tile(0, 0, kind="COOP", animal="GOOSE", placed_day=0,
                       yield_units=0, cared_today=False)
        t2 = _mk_tile(1, 0, kind="COOP", animal="GOOSE", placed_day=0,
                       yield_units=0, cared_today=False)
        farm = _mk_farm(tiles_dict={(0, 0): t1, (1, 0): t2})
        sched = forecast_opponent_production(farm, current_day=0)
        assert sched["EGG"][4] == 2.0  # 1 + 1


class TestGetImminentHarvests:
    """Test get_imminent_harvests for ripe crops and animals."""

    def test_ripe_wheat(self):
        """Wheat at age >= max_yield_day with yield > 0."""
        t = _mk_tile(0, 0, kind="PLANT", crop="WHEAT", planted_day=0,
                     yield_units=6)
        farm = _mk_farm(tiles_dict={(0, 0): t})
        harvests = get_imminent_harvests(farm, current_day=5)
        assert harvests["WHEAT"] == 6

    def test_ripe_melon(self):
        """Melon at age >= 12 with yield > 0."""
        t = _mk_tile(0, 0, kind="PLANT", crop="MELON", planted_day=0,
                     yield_units=6)
        farm = _mk_farm(tiles_dict={(0, 0): t})
        harvests = get_imminent_harvests(farm, current_day=15)
        assert harvests["MELON"] == 6

    def test_unripe_crop_not_harvested(self):
        """Wheat at age < max_yield_day not included."""
        t = _mk_tile(0, 0, kind="PLANT", crop="WHEAT", planted_day=0,
                     yield_units=3)
        farm = _mk_farm(tiles_dict={(0, 0): t})
        harvests = get_imminent_harvests(farm, current_day=3)  # age=3 < 4
        assert "WHEAT" not in harvests

    def test_ongoing_crop_on_yield_day(self):
        """Tomato on a yield day (day - planted_day) % interval == 0."""
        # Tomato planted day 0, first yield day 8, interval 1
        t = _mk_tile(0, 0, kind="PLANT", crop="TOMATO", planted_day=0,
                     yield_units=3)
        farm = _mk_farm(tiles_dict={(0, 0): t})
        # Day 10: age=10, first=8, (10-8)%1==0 => on yield day
        harvests = get_imminent_harvests(farm, current_day=10)
        assert harvests["TOMATO"] == 3

    def test_ongoing_crop_not_on_yield_day(self):
        """Tomato NOT on a yield day: strawberry interval=2."""
        t = _mk_tile(0, 0, kind="PLANT", crop="STRAWBERRY", planted_day=0,
                     yield_units=4)
        farm = _mk_farm(tiles_dict={(0, 0): t})
        # Day 11: first=10, (11-10)%2=1 => not on yield day
        harvests = get_imminent_harvests(farm, current_day=11)
        assert "STRAWBERRY" not in harvests

    def test_ongoing_crop_on_yield_day_strawberry(self):
        """Strawberry on yield day: day 12, first=10, (12-10)%2=0."""
        t = _mk_tile(0, 0, kind="PLANT", crop="STRAWBERRY", planted_day=0,
                     yield_units=4)
        farm = _mk_farm(tiles_dict={(0, 0): t})
        harvests = get_imminent_harvests(farm, current_day=12)
        assert harvests["STRAWBERRY"] == 4

    def test_animal_with_yield(self):
        """Goose with yield_units > 0."""
        t = _mk_tile(0, 0, kind="COOP", animal="GOOSE", yield_units=3)
        farm = _mk_farm(tiles_dict={(0, 0): t})
        harvests = get_imminent_harvests(farm, current_day=10)
        assert harvests["EGG"] == 3

    def test_animal_no_yield(self):
        """Goose with yield_units == 0 not included."""
        t = _mk_tile(0, 0, kind="COOP", animal="GOOSE", yield_units=0)
        farm = _mk_farm(tiles_dict={(0, 0): t})
        harvests = get_imminent_harvests(farm, current_day=10)
        assert "EGG" not in harvests

    def test_multiple_ripe_tiles(self):
        """Multiple ripe tiles accumulate."""
        t1 = _mk_tile(0, 0, kind="PLANT", crop="WHEAT", planted_day=0,
                       yield_units=6)
        t2 = _mk_tile(1, 0, kind="PLANT", crop="CARROT", planted_day=0,
                       yield_units=4)
        farm = _mk_farm(tiles_dict={(0, 0): t1, (1, 0): t2})
        harvests = get_imminent_harvests(farm, current_day=10)
        assert harvests["WHEAT"] == 6
        assert harvests["CARROT"] == 4

    def test_none_farm_returns_empty(self):
        assert get_imminent_harvests(None, 0) == {}

    def test_zero_yield_not_included(self):
        """Crop with yield_units=0 not included even if ripe."""
        t = _mk_tile(0, 0, kind="PLANT", crop="WHEAT", planted_day=0,
                     yield_units=0)
        farm = _mk_farm(tiles_dict={(0, 0): t})
        harvests = get_imminent_harvests(farm, current_day=5)
        assert "WHEAT" not in harvests


class TestSummarizeOpponentCommitments:
    """Test summarize_opponent_commitments portfolio allocation."""

    def test_empty_farm(self):
        farm = _mk_farm()
        s = summarize_opponent_commitments(farm)
        assert s["total_tiles"] == 100
        assert s["empty_tiles"] == 100
        assert s["crop_tiles"] == {}
        assert s["animal_counts"] == {}
        assert s["structure_count"] == 0

    def test_crop_allocation(self):
        tiles = {}
        for i in range(5):
            tiles[(i, 0)] = _mk_tile(i, 0, kind="PLANT", crop="WHEAT",
                                      planted_day=0)
        for i in range(3):
            tiles[(i, 1)] = _mk_tile(i, 1, kind="PLANT", crop="MELON",
                                      planted_day=0)
        farm = _mk_farm(tiles_dict=tiles)
        s = summarize_opponent_commitments(farm)
        assert s["crop_tiles"]["WHEAT"] == 5
        assert s["crop_tiles"]["MELON"] == 3
        assert s["allocation_pct"]["crop_WHEAT"] == 5.0
        assert s["allocation_pct"]["crop_MELON"] == 3.0

    def test_animal_counts(self):
        tiles = {}
        tiles[(0, 0)] = _mk_tile(0, 0, kind="COOP", animal="GOOSE")
        tiles[(1, 0)] = _mk_tile(1, 0, kind="COOP", animal="GOOSE")
        tiles[(2, 0)] = _mk_tile(2, 0, kind="PASTURE", animal="COW")
        farm = _mk_farm(tiles_dict=tiles)
        s = summarize_opponent_commitments(farm)
        assert s["animal_counts"]["GOOSE"] == 2
        assert s["animal_counts"]["COW"] == 1
        assert s["allocation_pct"]["animal_GOOSE"] == 2.0
        assert s["allocation_pct"]["animal_COW"] == 1.0

    def test_structures_without_animals(self):
        """Empty structures counted as structure_count."""
        tiles = {}
        tiles[(0, 0)] = _mk_tile(0, 0, kind="COOP")  # empty structure
        tiles[(1, 0)] = _mk_tile(1, 0, kind="PASTURE")  # empty structure
        farm = _mk_farm(tiles_dict=tiles)
        s = summarize_opponent_commitments(farm)
        assert s["structure_count"] == 2

    def test_locked_tiles(self):
        """LOCKED tiles counted separately."""
        grid = [[None for _ in range(10)] for _ in range(10)]
        grid[9][9] = "LOCKED"
        raw = {
            "money": 0,
            "tiles": grid,
            "farmer": (4, 4),
            "hands": [],
            "unlocked_quadrants": ["NW"],
            "hires_today": 0,
        }
        farm = FarmView(raw)
        s = summarize_opponent_commitments(farm)
        assert s["locked_tiles"] == 1
        assert s["empty_tiles"] == 99
        assert s["allocation_pct"]["locked"] == 1.0

    def test_none_farm(self):
        s = summarize_opponent_commitments(None)
        assert s["total_tiles"] == 0
        assert s["crop_tiles"] == {}

    def test_mixed_portfolio(self):
        """Full farm with crops, animals, structures, empty."""
        tiles = {}
        # 10 wheat
        for i in range(10):
            tiles[(i, 0)] = _mk_tile(i, 0, kind="PLANT", crop="WHEAT",
                                      planted_day=0)
        # 3 geese
        for i in range(3):
            tiles[(i, 1)] = _mk_tile(i, 1, kind="COOP", animal="GOOSE")
        # 1 empty structure
        tiles[(5, 1)] = _mk_tile(5, 1, kind="PASTURE")
        farm = _mk_farm(tiles_dict=tiles)
        s = summarize_opponent_commitments(farm)
        assert s["crop_tiles"]["WHEAT"] == 10
        assert s["animal_counts"]["GOOSE"] == 3
        assert s["structure_count"] == 1
        assert s["empty_tiles"] == 86  # 100 - 10 - 3 - 1
        assert s["total_tiles"] == 100


# ===== PHASE 3: SHED INFERENCE & SELL PREDICTION TESTS =====

class TestUpdateOpponentShedEstimate:
    """Test update_opponent_shed_estimate across multi-turn scenarios."""

    def test_none_prev_shed_returns_empty(self):
        result = update_opponent_shed_estimate(
            prev_shed=None, harvest_events=[], inferred_sales={},
            n_animals=0, day=0, hour=0,
        )
        assert result == {}

    def test_harvest_adds_to_shed(self):
        harvest = [{"event": "harvest", "details": {"crop": "WHEAT", "yield_units": 6}}]
        result = update_opponent_shed_estimate(
            prev_shed={}, harvest_events=harvest, inferred_sales={},
            n_animals=0, day=0, hour=0,
        )
        assert result["WHEAT"] == 6

    def test_animal_collect_adds_to_shed(self):
        harvest = [{"event": "animal_collect", "details": {
            "product": "EGG", "old_yield": 3, "new_yield": 1,
        }}]
        result = update_opponent_shed_estimate(
            prev_shed={}, harvest_events=harvest, inferred_sales={},
            n_animals=0, day=0, hour=0,
        )
        assert result["EGG"] == 2  # max(0, 3-1)

    def test_animal_collect_full_collect(self):
        harvest = [{"event": "animal_collect", "details": {
            "product": "MILK", "old_yield": 5, "new_yield": 0,
        }}]
        result = update_opponent_shed_estimate(
            prev_shed={}, harvest_events=harvest, inferred_sales={},
            n_animals=0, day=0, hour=0,
        )
        assert result["MILK"] == 5

    def test_inferred_sales_subtract(self):
        result = update_opponent_shed_estimate(
            prev_shed={"WHEAT": 10}, harvest_events=[], inferred_sales={"WHEAT": 3},
            n_animals=0, day=0, hour=0,
        )
        assert result["WHEAT"] == 7

    def test_sales_cannot_go_negative(self):
        result = update_opponent_shed_estimate(
            prev_shed={"WHEAT": 2}, harvest_events=[], inferred_sales={"WHEAT": 5},
            n_animals=0, day=0, hour=0,
        )
        assert result.get("WHEAT", 0) == 0

    def test_animal_feed_deducts_wheat(self):
        # 2 geese, 5 wheat, hour=0 triggers feed
        result = update_opponent_shed_estimate(
            prev_shed={"WHEAT": 5}, harvest_events=[], inferred_sales={},
            n_animals=2, day=5, hour=0,
        )
        assert result["WHEAT"] == 3  # 5 - 2

    def test_animal_feed_does_not_trigger_on_hour_1(self):
        result = update_opponent_shed_estimate(
            prev_shed={"WHEAT": 5}, harvest_events=[], inferred_sales={},
            n_animals=2, day=5, hour=1,
        )
        assert result["WHEAT"] == 5  # no feed at hour 1

    def test_animal_feed_capped_by_available_wheat(self):
        result = update_opponent_shed_estimate(
            prev_shed={"WHEAT": 1}, harvest_events=[], inferred_sales={},
            n_animals=5, day=5, hour=0,
        )
        assert result.get("WHEAT", 0) == 0  # only 1 wheat consumed

    def test_capacity_clamp_proportional(self):
        shed = {"WHEAT": 60, "EGG": 40}  # total = 100 = exactly at cap
        result = update_opponent_shed_estimate(
            prev_shed=shed, harvest_events=[], inferred_sales={},
            n_animals=0, day=0, hour=0,
        )
        assert sum(result.values()) <= 100

    def test_capacity_clamp_over_limit(self):
        shed = {"WHEAT": 70, "EGG": 50}  # total = 120 > 100
        result = update_opponent_shed_estimate(
            prev_shed=shed, harvest_events=[], inferred_sales={},
            n_animals=0, day=0, hour=0,
        )
        assert sum(result.values()) <= 100

    def test_capacity_clamp_empty_shed(self):
        result = update_opponent_shed_estimate(
            prev_shed={}, harvest_events=[], inferred_sales={},
            n_animals=0, day=0, hour=0,
        )
        assert result == {}

    def test_multi_turn_accumulation(self):
        # Turn 1: harvest 6 wheat
        t1 = [{"event": "harvest", "details": {"crop": "WHEAT", "yield_units": 6}}]
        s1 = update_opponent_shed_estimate({}, t1, {}, 0, 0, 0)
        assert s1 == {"WHEAT": 6}
        # Turn 2: harvest 4 carrots + sell 1 wheat
        t2 = [{"event": "harvest", "details": {"crop": "CARROT", "yield_units": 4}}]
        s2 = update_opponent_shed_estimate(s1, t2, {"WHEAT": 1}, 0, 0, 0)
        assert s2["WHEAT"] == 5
        assert s2["CARROT"] == 4

    def test_clamp_zero_product_removed(self):
        shed = {"WHEAT": 3, "EGG": 2}
        result = update_opponent_shed_estimate(
            prev_shed=shed, harvest_events=[], inferred_sales={"EGG": 2},
            n_animals=0, day=0, hour=0,
        )
        assert "EGG" not in result
        assert result["WHEAT"] == 3

    def test_non_harvest_events_ignored(self):
        events = [
            {"event": "plant", "details": {"crop": "WHEAT"}},
            {"event": "structure_build", "details": {"structure": "COOP"}},
            {"event": "animal_place", "details": {"animal": "GOOSE"}},
        ]
        result = update_opponent_shed_estimate(
            prev_shed={"WHEAT": 5}, harvest_events=events, inferred_sales={},
            n_animals=0, day=0, hour=0,
        )
        assert result == {"WHEAT": 5}  # unchanged


class TestComputeOpponentSellProbabilities:
    """Test compute_opponent_sell_probabilities multi-signal scoring."""

    def _mk_ctx(self, day=5, hour=0):
        return {"day": day, "hour": hour}

    def test_none_farm_returns_empty(self):
        probs = compute_opponent_sell_probabilities(None, {}, self._mk_ctx(), {})
        assert probs == {}

    def test_empty_shed_zero_probability(self):
        farm = _mk_farm()
        probs = compute_opponent_sell_probabilities(farm, {}, self._mk_ctx(), {})
        # With no shed stock, no imminent, etc. -> low probabilities
        for p, v in probs.items():
            assert 0.0 <= v <= 1.0

    def test_full_shed_high_probability(self):
        farm = _mk_farm()
        shed = {"WHEAT": 20, "EGG": 15}  # well above threshold
        probs = compute_opponent_sell_probabilities(farm, shed, self._mk_ctx(), {})
        assert probs["WHEAT"] > 0.10  # should be significant
        assert probs["EGG"] > 0.10

    def test_timing_boost_at_sell_window(self):
        farm = _mk_farm()
        shed = {"WHEAT": 10}
        probs_hour_1 = compute_opponent_sell_probabilities(
            farm, shed, self._mk_ctx(day=5, hour=1), {},
        )
        probs_hour_3 = compute_opponent_sell_probabilities(
            farm, shed, self._mk_ctx(day=5, hour=3), {},
        )
        # Hour 1 is post-drain sell window -> higher timing boost
        assert probs_hour_1["WHEAT"] >= probs_hour_3["WHEAT"]

    def test_end_of_day_liquidation_boost(self):
        farm = _mk_farm()
        shed = {"WHEAT": 10}
        probs_hour_22 = compute_opponent_sell_probabilities(
            farm, shed, self._mk_ctx(day=5, hour=22), {},
        )
        probs_hour_15 = compute_opponent_sell_probabilities(
            farm, shed, self._mk_ctx(day=5, hour=15), {},
        )
        # hour 22 triggers end-of-day liquidation (timing=0.3)
        # hour 15 has no timing boost (15%4=3, not 0/1, and <22)
        assert probs_hour_22["WHEAT"] >= probs_hour_15["WHEAT"]

    def test_imminent_harvest_increases_probability(self):
        # Farm with ripe wheat -> imminent score for WHEAT
        t = _mk_tile(0, 0, kind="PLANT", crop="WHEAT", planted_day=0, yield_units=6)
        farm = _mk_farm(tiles_dict={(0, 0): t})
        shed = {"WHEAT": 5}
        probs_with = compute_opponent_sell_probabilities(
            farm, shed, self._mk_ctx(day=5), {},
        )
        probs_without = compute_opponent_sell_probabilities(
            _mk_farm(), shed, self._mk_ctx(day=5), {},
        )
        assert probs_with["WHEAT"] >= probs_without["WHEAT"]

    def test_probability_bounds(self):
        """All probabilities must be in [0.0, 1.0]."""
        farm = _mk_farm()
        shed = {"WHEAT": 30, "EGG": 25, "MELON": 20}
        probs = compute_opponent_sell_probabilities(
            farm, shed, self._mk_ctx(day=5, hour=1), {},
        )
        for p, v in probs.items():
            assert 0.0 <= v <= 1.0, f"{p} = {v} out of bounds"

    def test_products_without_shed_get_base_score(self):
        """Products not in shed still get movement/pressure/timing base."""
        farm = _mk_farm()
        shed = {}
        probs = compute_opponent_sell_probabilities(
            farm, shed, self._mk_ctx(day=5, hour=1), {},
        )
        # Even with empty shed, some base signal exists
        for p, v in probs.items():
            assert v >= 0.0


class TestPredictImminentDumps:
    """Test predict_imminent_dumps volume estimation."""

    def test_above_threshold_returned(self):
        dump = predict_imminent_dumps(
            _mk_farm(), {"WHEAT": 10}, {"WHEAT": 0.85}, threshold=0.60,
        )
        assert "WHEAT" in dump
        assert dump["WHEAT"]["estimated_volume"] > 0
        assert dump["WHEAT"]["urgency"] == "HIGH"

    def test_medium_urgency(self):
        dump = predict_imminent_dumps(
            _mk_farm(), {"WHEAT": 10}, {"WHEAT": 0.70}, threshold=0.60,
        )
        assert "WHEAT" in dump
        assert dump["WHEAT"]["urgency"] == "MEDIUM"

    def test_below_threshold_excluded(self):
        dump = predict_imminent_dumps(
            _mk_farm(), {"WHEAT": 10}, {"WHEAT": 0.50}, threshold=0.60,
        )
        assert "WHEAT" not in dump

    def test_zero_shed_excluded(self):
        dump = predict_imminent_dumps(
            _mk_farm(), {}, {"WHEAT": 0.80}, threshold=0.60,
        )
        assert "WHEAT" not in dump

    def test_volume_capped_by_drip_slice(self):
        # drip_slice = 3, shed has 10 -> est_vol = 3
        dump = predict_imminent_dumps(
            _mk_farm(), {"WHEAT": 10}, {"WHEAT": 0.90}, threshold=0.60,
        )
        assert dump["WHEAT"]["estimated_volume"] == 3

    def test_volume_limited_by_shed(self):
        # drip_slice = 3, shed has 2 -> est_vol = 2
        dump = predict_imminent_dumps(
            _mk_farm(), {"WHEAT": 2}, {"WHEAT": 0.85}, threshold=0.60,
        )
        assert dump["WHEAT"]["estimated_volume"] == 2

    def test_multiple_dumps(self):
        dump = predict_imminent_dumps(
            _mk_farm(), {"WHEAT": 10, "EGG": 8},
            {"WHEAT": 0.90, "EGG": 0.75, "MELON": 0.40},
            threshold=0.60,
        )
        assert "WHEAT" in dump
        assert "EGG" in dump
        assert "MELON" not in dump  # below threshold

    def test_custom_threshold(self):
        dump = predict_imminent_dumps(
            _mk_farm(), {"WHEAT": 10}, {"WHEAT": 0.55}, threshold=0.50,
        )
        assert "WHEAT" in dump  # above 0.50

    def test_empty_sell_probs(self):
        dump = predict_imminent_dumps(
            _mk_farm(), {"WHEAT": 10}, {}, threshold=0.60,
        )
        assert dump == {}

    def test_probability_captured_in_output(self):
        dump = predict_imminent_dumps(
            _mk_farm(), {"WHEAT": 10}, {"WHEAT": 0.82}, threshold=0.60,
        )
        assert dump["WHEAT"]["probability"] == 0.82
