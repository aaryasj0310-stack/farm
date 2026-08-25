"""Animal lifecycle validation: care banking, feed, fertilizer, max_held."""
from animal_model import (
    ANIMALS,
    evaluate_fertilizer_use,
    production_days,
    simulate_animal_lifecycle,
)


def test_required_care_banking_bonuses():
    """REQUIRED: goose +0, cow +1, sheep +2 per cycle under 'always' care."""
    goose = simulate_animal_lifecycle("GOOSE", end_day=30, care_policy="always")
    cow = simulate_animal_lifecycle("COW", end_day=30, care_policy="always")
    sheep = simulate_animal_lifecycle("SHEEP", end_day=30, care_policy="always")
    assert goose["product_harvested"] == 26          # 1/day days 4..29, no bonus
    assert cow["product_harvested"] == 11 + 10       # base 11 + banked off-days
    assert sheep["product_harvested"] == 8 + 14      # base 8 + 2 per gap (7 gaps)


def test_production_schedule_delays():
    assert min(production_days(0, 30, 1, 4)) == 4     # goose first egg day 4
    assert min(production_days(0, 30, 2, 8)) == 8     # cow
    assert min(production_days(0, 30, 3, 6)) == 6     # sheep


def test_feed_accounting():
    res = simulate_animal_lifecycle("GOOSE", end_day=30)
    assert res["feed_wheat_units"] == 30
    assert res["feed_cost"] == 30 * 25


def test_max_held_cap_without_harvesting():
    res = simulate_animal_lifecycle("GOOSE", end_day=30, harvest_daily=False)
    assert res["pending_unharvested"] == 4            # capped, never higher
    assert res["product_harvested"] == 0


def test_unfed_animal_still_makes_base_product_but_no_bonus():
    res = simulate_animal_lifecycle("COW", end_day=30, care_policy="always",
                                    feed_daily=False)
    assert res["product_harvested"] == 11             # base only, no banking


def test_fertilizer_independent_of_care_and_feed():
    fed = simulate_animal_lifecycle("GOOSE", end_day=10)
    unfed = simulate_animal_lifecycle("GOOSE", end_day=10, feed_daily=False,
                                      product_price=0)
    assert fed["fertilizer_collected"] == 10
    assert unfed["fertilizer_collected"] == 10        # survives? rules: escapes
    # note: escape rule is out of scope here; spec says fert is unconditional


def test_net_profit_math_goose_never_care():
    res = simulate_animal_lifecycle("GOOSE", end_day=30, care_policy="never",
                                    wheat_price=25)
    expected = 26 * 50 - 30 * 25 - 300                # eggs - feed - purchase
    assert res["net_profit"] == expected


def test_fertilizer_use_evaluation():
    wheat = evaluate_fertilizer_use("WHEAT", applications=5)
    assert wheat["extra_units_per_application"] == 2   # 4 -> 6
    melon = evaluate_fertilizer_use("MELON")
    assert melon["tile_days_saved"] == 2               # 10 -> 8
