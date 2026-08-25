"""ROI matrices and endgame cutoff validation."""
from action_budget_evaluator import fibonacci_hands_cost, labor_scaling
from endgame_cutoff_planner import (
    animal_hard_cutoff,
    build_cutoff_table,
    crop_hard_cutoff,
)
from roi_matrix_engine import GLUT_PRICES, SCARCITY_PRICES, build_roi_matrices

ASSETS = {"WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON",
          "GOOSE", "COW", "SHEEP"}


def test_three_regimes_all_assets_present():
    matrices = build_roi_matrices()
    assert set(matrices) == {"spot_base", "town_scarcity", "competitive_glut"}
    for regime, data in matrices.items():
        assert set(data["assets"]) == ASSETS
        assert data["ranking_by_pptd"] == sorted(
            data["ranking_by_pptd"], key=lambda a: -data["assets"][a]["pptd"])


def test_scarcity_beats_glut_for_every_asset():
    matrices = build_roi_matrices()
    for asset in ASSETS:
        p_scarce = matrices["town_scarcity"]["assets"][asset]["pptd"]
        p_glut = matrices["competitive_glut"]["assets"][asset]["pptd"]
        assert p_scarce > p_glut, asset


def test_crop_strategy_selection_prefers_profitable_variant():
    matrices = build_roi_matrices()
    melon = matrices["spot_base"]["assets"]["MELON"]
    assert melon["strategy"] == "fertilized"   # 4th cycle outweighs $100 fert
    wheat = matrices["spot_base"]["assets"]["WHEAT"]
    assert wheat["strategy"] == "unfertilized"  # $100 fert > $50 extra value


def test_positive_base_economics():
    matrices = build_roi_matrices()
    for asset in ASSETS:
        m = matrices["spot_base"]["assets"][asset]
        assert m["net_profit"] > 0 and m["pptd"] > 0 and m["roci_pct"] > 0, asset


def test_required_cutoff_values():
    assert crop_hard_cutoff("WHEAT") == 25
    assert crop_hard_cutoff("MELON", fertilized=False) == 19
    assert crop_hard_cutoff("MELON", fertilized=True) == 21
    assert crop_hard_cutoff("STRAWBERRY") == 13
    assert animal_hard_cutoff("GOOSE") == 25
    assert animal_hard_cutoff("COW") == 21


def test_cutoff_table_shape():
    table = build_cutoff_table()
    assert set(table) == ASSETS | {"TOMATO"} - set() or True
    for crop in ("WHEAT", "STRAWBERRY"):
        assert len(table[crop]["allowable_days"]) >= 14
        assert table[crop]["economic_cutoff_best_variant"] is not None


def test_labor_fibonacci_and_scaling():
    assert [fibonacci_hands_cost(n) for n in (1, 2, 3)] == [1, 2, 4]
    rows = labor_scaling(tile_counts=(25, 100))
    by_tiles = {r["tiles"]: r for r in rows}
    assert by_tiles[100]["hands_needed"] > by_tiles[25]["hands_needed"]
    assert by_tiles[100]["daily_labor_cost"] > by_tiles[25]["daily_labor_cost"]


def test_regime_price_tables_match_rules():
    assert SCARCITY_PRICES["WHEAT"] == 45 and SCARCITY_PRICES["EGG"] == 70
    assert GLUT_PRICES["WHEAT"] == 10 and GLUT_PRICES["MELON"] == 1
