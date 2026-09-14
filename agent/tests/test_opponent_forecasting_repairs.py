"""Unit tests for Repaired Opponent Model and Shadow Forecasting System."""

import pytest
from observation_parser import FarmView
from config import CROPS, ANIMALS, PRODUCTS
from state.repaired_opponent_model import (
    snapshot_farm,
    detect_tile_deltas_repaired,
    forecast_opponent_production_repaired,
    RepairedOpponentInventoryTracker,
)
from strategy.repaired_opponent_advisor import (
    compute_delay_sell_repaired,
    compute_sell_probabilities_repaired,
    build_repaired_opponent_advice,
)
from strategy.shadow_forecast import ShadowOpponentForecaster


def _mk_tile(x, y, kind="EMPTY", crop=None, planted_day=None,
             yield_units=0, watered_today=False, consecutive_unwatered=0,
             fertilized_until_day=-1, animal=None, fed_today=False,
             cared_today=False, consecutive_unfed=0,
             fertilizer_available=False, pending_care_bonus=0,
             placed_day=None):
    if kind == "EMPTY":
        return None
    return {
        "kind": kind, "x": x, "y": y,
        "crop": crop, "planted_day": planted_day,
        "yield_units": yield_units, "watered_today": watered_today,
        "consecutive_unwatered": consecutive_unwatered,
        "fertilized_until_day": fertilized_until_day,
        "animal": animal, "fed_today": fed_today,
        "cared_today": cared_today, "consecutive_unfed": consecutive_unfed,
        "fertilizer_available": fertilizer_available,
        "pending_care_bonus": pending_care_bonus,
        "placed_day": placed_day,
    }


def _mk_farm(tiles_dict=None, money=1000):
    grid = [[None for _ in range(10)] for _ in range(10)]
    if tiles_dict:
        for (x, y), t in tiles_dict.items():
            grid[y][x] = t
    raw = {
        "money": money,
        "tiles": grid,
        "farmer": (4, 4),
        "hands": [],
        "unlocked_quadrants": ["NW"],
        "hires_today": 0,
    }
    return FarmView(raw)


class TestRepairedForecasting:
    def test_finite_tomato_schedules(self):
        """Tomato planted Day 0 must produce EXACTLY 4 cycles (days 8, 9, 10, 11), not through Day 29."""
        t = _mk_tile(0, 0, kind="PLANT", crop="TOMATO", planted_day=0, yield_units=0, watered_today=True)
        farm = _mk_farm({(0, 0): t})
        res = forecast_opponent_production_repaired(farm, current_day=0)
        sched = res["base_schedule"]["TOMATO"]

        # Exactly 4 harvest days
        assert set(sched.keys()) == {8, 9, 10, 11}
        assert 12 not in sched
        assert 29 not in sched

    def test_finite_strawberry_schedules(self):
        """Strawberry planted Day 0 must produce EXACTLY 4 cycles (days 10, 12, 14, 16)."""
        t = _mk_tile(0, 0, kind="PLANT", crop="STRAWBERRY", planted_day=0, yield_units=0, watered_today=True)
        farm = _mk_farm({(0, 0): t})
        res = forecast_opponent_production_repaired(farm, current_day=0)
        sched = res["base_schedule"]["STRAWBERRY"]

        assert set(sched.keys()) == {10, 12, 14, 16}
        assert 18 not in sched
        assert 28 not in sched

    def test_realistic_wheat_yields(self):
        """Unfertilized wheat yields 4 units base, fertilized yields 6."""
        t_unfert = _mk_tile(0, 0, kind="PLANT", crop="WHEAT", planted_day=0, yield_units=0, watered_today=True)
        farm1 = _mk_farm({(0, 0): t_unfert})
        res1 = forecast_opponent_production_repaired(farm1, current_day=0)
        assert res1["base_schedule"]["WHEAT"][4] == 4.0

        t_fert = _mk_tile(0, 0, kind="PLANT", crop="WHEAT", planted_day=0, yield_units=0, watered_today=True, fertilized_until_day=10)
        farm2 = _mk_farm({(0, 0): t_fert})
        res2 = forecast_opponent_production_repaired(farm2, current_day=0)
        assert res2["base_schedule"]["WHEAT"][4] == 6.0

    def test_realistic_carrot_yields(self):
        """Unfertilized carrot yields 3 units base, fertilized yields 4."""
        t_unfert = _mk_tile(0, 0, kind="PLANT", crop="CARROT", planted_day=0, yield_units=0, watered_today=True)
        farm1 = _mk_farm({(0, 0): t_unfert})
        res1 = forecast_opponent_production_repaired(farm1, current_day=0)
        assert res1["base_schedule"]["CARROT"][3] == 3.0

        t_fert = _mk_tile(0, 0, kind="PLANT", crop="CARROT", planted_day=0, yield_units=0, watered_today=True, fertilized_until_day=10)
        farm2 = _mk_farm({(0, 0): t_fert})
        res2 = forecast_opponent_production_repaired(farm2, current_day=0)
        assert res2["base_schedule"]["CARROT"][3] == 4.0

    def test_recoverable_crop_logic(self):
        """Crop with consecutive_unwatered == 1 is kept during morning hours (hour 8) but excluded at late night (hour 22)."""
        t = _mk_tile(0, 0, kind="PLANT", crop="MELON", planted_day=0, yield_units=0, watered_today=False, consecutive_unwatered=1)
        farm = _mk_farm({(0, 0): t})

        res_morning = forecast_opponent_production_repaired(farm, current_day=1, current_hour=8)
        assert "MELON" in res_morning["base_schedule"]

        res_night = forecast_opponent_production_repaired(farm, current_day=1, current_hour=22)
        assert "MELON" not in res_night["base_schedule"]


class TestRepairedDeltaDetection:
    def test_ongoing_crop_harvest_detected(self):
        """Ongoing crop yields dropping from 3 to 0 while remaining PLANT must trigger a harvest delta."""
        t_old = _mk_tile(0, 0, kind="PLANT", crop="TOMATO", planted_day=0, yield_units=3)
        snap_old = snapshot_farm(_mk_farm({(0, 0): t_old}))

        t_new = _mk_tile(0, 0, kind="PLANT", crop="TOMATO", planted_day=0, yield_units=0)
        farm_new = _mk_farm({(0, 0): t_new})

        deltas = detect_tile_deltas_repaired(farm_new, snap_old)
        assert len(deltas) == 1
        assert deltas[0]["event"] == "harvest"
        assert deltas[0]["details"]["crop"] == "TOMATO"
        assert deltas[0]["details"]["yield_units"] == 3
        assert deltas[0]["details"]["ongoing"] is True

    def test_plant_cleared_not_harvest(self):
        """Plant disappearing with 0 yield must be plant_cleared, NOT harvest."""
        t_old = _mk_tile(0, 0, kind="PLANT", crop="WHEAT", planted_day=0, yield_units=0)
        snap_old = snapshot_farm(_mk_farm({(0, 0): t_old}))

        farm_new = _mk_farm({})  # tile now empty
        deltas = detect_tile_deltas_repaired(farm_new, snap_old)
        assert len(deltas) == 1
        assert deltas[0]["event"] == "plant_cleared"


class TestRepairedInventoryTracker:
    def test_carried_and_shed_bounds_and_rollover(self):
        tracker = RepairedOpponentInventoryTracker()

        # Harvest 10 Melons on Day 2 Hour 10
        harvest_delta = [{"event": "harvest", "details": {"crop": "MELON", "yield_units": 10.0}}]
        tracking = tracker.update(deltas=harvest_delta, confirmed_sells={}, confirmed_buys={}, n_animals=0, day=2, hour=10)

        # Melons are carried, NOT yet confirmed in shed
        assert tracking["carried_bounds"]["MELON"][1] == 10.0
        assert tracking["shed_bounds"].get("MELON", [0, 0])[0] == 0.0

        # At Day rollover (Day 3 Hour 0), engine drops all carried stock into shed
        rollover_tracking = tracker.update(deltas=[], confirmed_sells={}, confirmed_buys={}, n_animals=0, day=3, hour=0)
        assert rollover_tracking["shed_bounds"]["MELON"][1] == 10.0
        assert rollover_tracking["carried_bounds"].get("MELON", [0, 0])[1] == 0.0


class TestRepairedAdvisor:
    def test_delay_sell_dimensionally_valid(self):
        """Delay sell checks recent dump vs reference price, ignoring ancient cumulative sales."""
        our_shed = {"MELON": 5}
        # Recent sales history: 70 Melons dumped 1 step ago at step 100 (depresses price from 250 to 201)
        mem = {
            "opp_sales_history": [(100, "MELON", 70.0)],
        }
        ctx = {
            "step": 101,
            "market": {"inventory": {"MELON": 10070}},  # inventory surged to 10070
        }
        delay = compute_delay_sell_repaired(mem, our_shed, ctx, max_steps=4)
        assert "MELON" in delay

        # If 10 steps elapsed, recent dump has aged out of the 4-step window
        ctx_late = {
            "step": 115,
            "market": {"inventory": {"MELON": 10070}},
        }
        delay_late = compute_delay_sell_repaired(mem, our_shed, ctx_late, max_steps=4)
        assert "MELON" not in delay_late


class TestShadowForecaster:
    def test_shadow_forecast_telemetry_generation(self):
        forecaster = ShadowOpponentForecaster()
        t = _mk_tile(0, 0, kind="PLANT", crop="MELON", planted_day=0, yield_units=0, watered_today=True)
        farm = _mk_farm({(0, 0): t})
        ctx = {"step": 24, "day": 1, "hour": 0, "opponent_farm": farm}
        mem = {}

        telemetry = forecaster.update(farm, ctx, mem)
        assert telemetry["step"] == 24
        assert "MELON" in telemetry["production_forecast"]
        assert telemetry["production_forecast"]["MELON"][12] == 6.0
        assert "production_scenarios" in telemetry
        assert "shed_bounds" in telemetry
        assert "p_sale_next_4_turns" in telemetry
        assert telemetry["next_sell_step"] == 25  # 24 + 1
        assert "confidence_metadata" in telemetry
        assert "WHEAT" in telemetry["confidence_metadata"]
        assert "production" in telemetry["confidence_metadata"]["WHEAT"]
        assert "promotion_gate_status" in telemetry["confidence_metadata"]["WHEAT"]


class TestStructuralBlindSpotRepairs:
    """Tests for animal fertilizer collection, feeding, and market purchase inference."""

    def test_fertilizer_collection_and_feeding_deltas(self):
        # Step 0: animal placed with fertilizer available
        grid0 = [[None for _ in range(10)] for _ in range(10)]
        grid0[0][0] = {
            "kind": "PASTURE", "x": 0, "y": 0, "animal": "COW", "yield_units": 0,
            "fed_today": False, "cared_today": False, "consecutive_unfed": 0,
            "fertilizer_available": True, "placed_day": 0, "pending_care_bonus": 0,
        }
        farm0 = FarmView({"money": 1000, "tiles": grid0})
        snap0 = snapshot_farm(farm0)

        # Step 1: worker feeds cow and collects fertilizer
        grid1 = [[None for _ in range(10)] for _ in range(10)]
        grid1[0][0] = {
            "kind": "PASTURE", "x": 0, "y": 0, "animal": "COW", "yield_units": 0,
            "fed_today": True, "cared_today": False, "consecutive_unfed": 0,
            "fertilizer_available": False, "placed_day": 0, "pending_care_bonus": 0,
        }
        farm1 = FarmView({"money": 1000, "tiles": grid1})

        deltas = detect_tile_deltas_repaired(farm1, snap0)
        events = {d["event"]: d for d in deltas}

        assert "collect_fertilizer" in events
        assert events["collect_fertilizer"]["details"]["units"] == 1
        assert "animal_fed" in events
        assert events["animal_fed"]["details"]["product"] == "WHEAT"

    def test_inferred_market_buys_and_consumption(self):
        tracker = RepairedOpponentInventoryTracker()

        # Step 1: Opponent buys 20 Wheat from market
        inferred_buys = {"WHEAT": {"lower": 20.0, "upper": 21.0, "confidence": "high"}}
        inv1 = tracker.update(
            deltas=[],
            confirmed_sells={},
            confirmed_buys=None,
            n_animals=2,
            day=1,
            hour=5,
            inferred_buys=inferred_buys,
        )
        assert inv1["shed_bounds"]["WHEAT"][0] >= 20.0

        # Step 2: 2 animals fed -> 2 Wheat consumed
        feed_deltas = [
            {"event": "animal_fed", "details": {"product": "WHEAT", "units": 1}},
            {"event": "animal_fed", "details": {"product": "WHEAT", "units": 1}},
        ]
        inv2 = tracker.update(
            deltas=feed_deltas,
            confirmed_sells={},
            confirmed_buys=None,
            n_animals=2,
            day=1,
            hour=6,
        )
        assert inv2["shed_bounds"]["WHEAT"][0] == 18.0
        assert inv2["cum_consumed"]["WHEAT"] == 2.0

