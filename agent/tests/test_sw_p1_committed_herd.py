"""Isolated SW-P1 purchase workload regression tests.

Only the purchase gate may ignore hypothetical future sheep. Current animal
and built-housing commitments, cash, ROI, worker partition, and activation
remain subject to their existing conservative protections.
"""
from types import SimpleNamespace

import config
from strategy.expansion_planner import should_buy_land
from strategy.land_serviceability_model import evaluate_sw_serviceability


def _tile(pos, *, kind, animal=None, crop=None):
    return SimpleNamespace(
        pos=pos, kind=kind, animal=animal, crop=crop,
        is_animal=animal is not None, is_plant=kind == "PLANT",
        fed_today=True, watered_today=True, cared_today=True,
        yield_units=0, planted_day=9, consecutive_unwatered=0,
    )


class _Farm:
    def __init__(self, ne_animals=0, ne_housing=0):
        self.unlocked = ["NW", "NE"]
        self.farmer = (4, 4)
        self.hands = [(4, 4)] * 12
        self.hires_today = 12
        self.money = 10000
        self._tiles = [
            _tile((1, 1), kind="PASTURE", animal="COW"),
            _tile((6, 1), kind="PLANT", crop="CARROT"),
        ]
        positions = [(x, y) for y in range(2, 5) for x in range(5, 10)]
        for pos in positions[:ne_animals]:
            self._tiles.append(_tile(pos, kind="PASTURE", animal="SHEEP"))
        for pos in positions[ne_animals:ne_animals + ne_housing]:
            self._tiles.append(_tile(pos, kind="PASTURE"))

    def iter_tiles(self):
        return iter(self._tiles)

    @staticmethod
    def quadrant_of(pos):
        x, y = pos
        return ("N" if y < 5 else "S") + ("W" if x < 5 else "E")


def _evaluate(farm, reserve_desired_herd=True):
    return evaluate_sw_serviceability(
        current_day=12, farm=farm, money=10000, forecast=None,
        target_quadrant=3, hour=10, allow_hypothetical=True,
        reserve_desired_herd=reserve_desired_herd,
    )


def test_default_evaluator_remains_legacy_and_p1_removes_only_aspirational_sheep():
    farm = _Farm()
    legacy = _evaluate(farm)
    default = evaluate_sw_serviceability(
        current_day=12, farm=farm, money=10000, forecast=None,
        target_quadrant=3, hour=10, allow_hypothetical=True,
    )
    p1 = _evaluate(farm, reserve_desired_herd=False)

    assert default == legacy
    assert legacy[2]["ne_desired_sheep_target"] == 12
    assert legacy[2]["ne_reserved_sheep_workload_count"] == 12
    assert legacy[2]["ne_deficit"] > 0
    assert legacy[0] is False
    assert p1[2]["ne_observed_animals_and_housing"] == 0
    assert p1[2]["ne_reserved_sheep_workload_count"] == 0
    assert p1[2]["ne_deficit"] == 0
    assert p1[0] is True
    # No change to workforce partition, safety margin, timing, or revenue model.
    assert p1[2]["worker_count"] == legacy[2]["worker_count"] == 13
    assert p1[2]["sw_cap"] == legacy[2]["sw_cap"]


def test_actual_ne_sheep_still_reserve_workload_in_p1():
    farm = _Farm(ne_animals=12)
    is_serviceable, _, diag = _evaluate(farm, reserve_desired_herd=False)
    assert diag["ne_observed_animals_and_housing"] == 12
    assert diag["ne_reserved_sheep_workload_count"] == 12
    assert diag["ne_deficit"] > 0
    assert is_serviceable is False


def test_unoccupied_ne_housing_remains_reserved_in_p1():
    farm = _Farm(ne_housing=5)
    _, _, diag = _evaluate(farm, reserve_desired_herd=False)
    assert diag["ne_observed_animals_and_housing"] == 5
    assert diag["ne_reserved_sheep_workload_count"] == 5
    assert diag["ne_workload"] >= 25.0


def test_purchase_switch_defaults_off_and_applies_only_to_sw_purchase(monkeypatch):
    farm = _Farm()
    kwargs = dict(
        next_quadrant=3, current_day=12, money=10000,
        farm=farm, hire_cost=0, feed_cost=0, animal_cost=0,
        reserve=300, roi=2.0, ow_factor=1.0,
        seeds_owned={"WHEAT": 100, "CARROT": 100},
        hour=10,
    )
    assert config.SW_P1_PURCHASE_COMMITTED_HERD_ONLY is False
    base = should_buy_land(**kwargs)
    assert base[0] is False
    assert base[1] == "insufficient_labor_capacity"
    assert base[2]["ne_reserved_sheep_workload_count"] == 12

    # Enabling P1 changes the purchase caller only; direct/default evaluator,
    # including MacroPlanner's activation call, remains legacy.
    monkeypatch.setattr(config, "SW_P1_PURCHASE_COMMITTED_HERD_ONLY", True)
    treatment = should_buy_land(**kwargs)
    assert treatment[0] is True
    assert treatment[2]["sw_p1_purchase_committed_herd_only"] is True
    assert treatment[2]["ne_reserved_sheep_workload_count"] == 0
    assert _evaluate(farm)[2]["ne_reserved_sheep_workload_count"] == 12

    # Existing housing/animals still prohibit unsafe purchase.
    blocked = should_buy_land(**{**kwargs, "farm": _Farm(ne_animals=12)})
    assert blocked[0] is False
    assert blocked[1] == "insufficient_labor_capacity"


def test_desired_target_changes_do_not_alter_p1_committed_workload(monkeypatch):
    farm = _Farm()
    monkeypatch.setattr(config, "get_active_livestock_targets", lambda: (0, 6, 12))
    first = _evaluate(farm, reserve_desired_herd=False)
    monkeypatch.setattr(config, "get_active_livestock_targets", lambda: (0, 6, 20))
    second = _evaluate(farm, reserve_desired_herd=False)
    assert first[2]["ne_reserved_sheep_workload_count"] == second[2]["ne_reserved_sheep_workload_count"] == 0
    assert first[0] == second[0]
    assert first[1] == second[1]


def test_p1_does_not_override_treasury_roi_or_purchase_timing(monkeypatch):
    monkeypatch.setattr(config, "SW_P1_PURCHASE_COMMITTED_HERD_ONLY", True)
    common = dict(
        next_quadrant=3, farm=_Farm(), hire_cost=0, feed_cost=0,
        animal_cost=0, reserve=300, roi=2.0,
        seeds_owned={"WHEAT": 100, "CARROT": 100}, hour=10,
    )
    early = should_buy_land(**common, current_day=8, money=10000)
    assert early[0] is False and early[1] == "before_day_9"
    poor = should_buy_land(**common, current_day=12, money=10000, roi=-0.1)
    assert poor[0] is False and poor[1].startswith("adjusted_roi_")
    cash = should_buy_land(**common, current_day=12, money=2200)
    assert cash[0] is False and cash[1].startswith("short_")
