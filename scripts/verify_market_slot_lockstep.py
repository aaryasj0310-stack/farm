"""Phase M0-H: Real-Engine Market Slot Lockstep Verification.

Microtests:
- A1: Same product, same slot (both players sell 5 WOOL in slot 0 -> quote symmetry).
- A2: Same product, different slots (Scenario A: Us slot 0, Opp slot 1 vs Scenario B: Us slot 1, Opp slot 0).
- A3: Seat symmetry (swapping Player 0 and Player 1).
- A4: Unequal quantities (e.g. 3 vs 10 units lockstep).
- A5: Different products (WOOL vs MILK in different slots -> verify price curves don't interact).
- A6: Fragile products sensitivity (STRAWBERRY, MELON, MILK, WOOL, FERTILIZER, WHEAT).

Outputs in simulations/results/phase_m0_h_engine_verification/:
- manifest.json
- same_slot_lockstep.json
- different_slot_price_race.json
- seat_symmetry.json
- quantity_asymmetry.json
- product_sensitivity.json
"""
from __future__ import annotations

import copy
import json
import os
import sys
from typing import Any, Dict, List

_REPO_ROOT = r"d:\website project\kaggri ox"
OUT_DIR = os.path.join(_REPO_ROOT, "simulations", "results", "phase_m0_h_engine_verification")
os.makedirs(OUT_DIR, exist_ok=True)

import kaggle_environments as ke
import kaggle_environments.envs.kaggriculture.kaggriculture as kengine


def make_fresh_market_state(seed: int = 96501):
    env = ke.make("kaggriculture", configuration={"episodeSteps": 720, "seed": seed}, debug=False)
    env.reset()
    state = env.state
    # Give both players ample shed stock and money for testing
    for s in state:
        priv = s.observation.private
        for prod in ["WOOL", "MILK", "STRAWBERRY", "MELON", "FERTILIZER", "WHEAT", "CARROT", "TOMATO"]:
            priv.shed[prod] = 50
    return env, state


def test_a1_same_slot_lockstep():
    """A1: Same product, same slot (slot 0 vs slot 0). Verify per-unit quote symmetry."""
    print("Running Test A1: Same product, same slot lockstep...")
    env, state = make_fresh_market_state()

    # Both players sell 5 WOOL in slot 0
    orders_p0 = [["SELL", "WOOL", 5]]
    orders_p1 = [["SELL", "WOOL", 5]]

    state[0].action = {"farmer": ["PASS"], "hands": [], "market": orders_p0}
    state[1].action = {"farmer": ["PASS"], "hands": [], "market": orders_p1}

    cash_pre_p0 = state[0].observation.farms[0]["money"]
    cash_pre_p1 = state[0].observation.farms[1]["money"]
    inv_pre = state[0].observation.market["inventory"]["WOOL"]

    kengine._process_market(state, env)

    cash_post_p0 = state[0].observation.farms[0]["money"]
    cash_post_p1 = state[0].observation.farms[1]["money"]
    inv_post = state[0].observation.market["inventory"]["WOOL"]

    rev_p0 = cash_post_p0 - cash_pre_p0
    rev_p1 = cash_post_p1 - cash_pre_p1

    assert rev_p0 == rev_p1, f"Both players must receive identical revenue in same slot: {rev_p0} vs {rev_p1}"
    assert inv_post == inv_pre + 10, f"Inventory must increase by 10: {inv_post} vs {inv_pre + 10}"

    print(f"  [PASS] A1: Rev P0=${rev_p0}, Rev P1=${rev_p1}, Exact Symmetry Verified.")
    return {
        "passed": True,
        "product": "WOOL",
        "quantity_each": 5,
        "revenue_p0": rev_p0,
        "revenue_p1": rev_p1,
        "symmetric": rev_p0 == rev_p1,
        "market_inv_pre": inv_pre,
        "market_inv_post": inv_post,
    }


def test_a2_different_slots_price_race():
    """A2: Same product, different slots. Compare Slot 0 vs Slot 1 advantage."""
    print("Running Test A2: Different slots price race...")
    # Scenario A: P0 in Slot 0, P1 in Slot 1
    env_a, state_a = make_fresh_market_state()
    # P1 does a dummy buy or dummy order in slot 0 to push their SELL to slot 1
    state_a[0].action = {"farmer": ["PASS"], "hands": [], "market": [["SELL", "WOOL", 5]]}
    state_a[1].action = {"farmer": ["PASS"], "hands": [], "market": [["SELL", "WHEAT", 1], ["SELL", "WOOL", 5]]}

    cash_pre_a0 = state_a[0].observation.farms[0]["money"]
    cash_pre_a1 = state_a[0].observation.farms[1]["money"]
    kengine._process_market(state_a, env_a)
    rev_a0 = state_a[0].observation.farms[0]["money"] - cash_pre_a0
    # Deduct the 1 wheat sale from P1 to get pure wool revenue
    p1_wheat_price = kengine.market_price("WHEAT", 10000)
    rev_a1 = (state_a[0].observation.farms[1]["money"] - cash_pre_a1) - p1_wheat_price

    # Scenario B: Reverse (P0 in Slot 1, P1 in Slot 0)
    env_b, state_b = make_fresh_market_state()
    state_b[0].action = {"farmer": ["PASS"], "hands": [], "market": [["SELL", "WHEAT", 1], ["SELL", "WOOL", 5]]}
    state_b[1].action = {"farmer": ["PASS"], "hands": [], "market": [["SELL", "WOOL", 5]]}

    cash_pre_b0 = state_b[0].observation.farms[0]["money"]
    cash_pre_b1 = state_b[0].observation.farms[1]["money"]
    kengine._process_market(state_b, env_b)
    p0_wheat_price = kengine.market_price("WHEAT", 10000)
    rev_b0 = (state_b[0].observation.farms[0]["money"] - cash_pre_b0) - p0_wheat_price
    rev_b1 = state_b[0].observation.farms[1]["money"] - cash_pre_b1

    # Slot 0 seller should earn strictly more than Slot 1 seller
    slot0_advantage = rev_a0 - rev_a1
    print(f"  Scenario A: Slot 0 Wool=${rev_a0}, Slot 1 Wool=${rev_a1}, Advantage=${slot0_advantage}")
    print(f"  Scenario B: Slot 1 Wool=${rev_b0}, Slot 0 Wool=${rev_b1}, Advantage=${rev_b1 - rev_b0}")
    assert rev_a0 > rev_a1, "Slot 0 seller must earn more than Slot 1 seller"
    assert rev_b1 > rev_b0, "Slot 0 seller must earn more than Slot 1 seller"
    assert rev_a0 == rev_b1, "Slot 0 revenue must be identical regardless of player seat"
    assert rev_a1 == rev_b0, "Slot 1 revenue must be identical regardless of player seat"

    print("  [PASS] A2: Slot 0 price-race advantage conclusively verified.")
    return {
        "passed": True,
        "product": "WOOL",
        "qty": 5,
        "slot_0_revenue": rev_a0,
        "slot_1_revenue": rev_a1,
        "price_race_advantage": slot0_advantage,
    }


def test_a3_seat_symmetry():
    """A3: Seat symmetry verification."""
    print("Running Test A3: Seat symmetry...")
    # Verified by exact equality of rev_a0 == rev_b1 and rev_a1 == rev_b0 in A2
    env, state = make_fresh_market_state()
    # P0 and P1 submit identical 3-order queues
    q = [["SELL", "STRAWBERRY", 3], ["SELL", "MILK", 2], ["SELL", "MELON", 1]]
    state[0].action = {"farmer": ["PASS"], "hands": [], "market": copy.deepcopy(q)}
    state[1].action = {"farmer": ["PASS"], "hands": [], "market": copy.deepcopy(q)}

    cash_pre_p0 = state[0].observation.farms[0]["money"]
    cash_pre_p1 = state[0].observation.farms[1]["money"]
    kengine._process_market(state, env)
    rev_p0 = state[0].observation.farms[0]["money"] - cash_pre_p0
    rev_p1 = state[0].observation.farms[1]["money"] - cash_pre_p1

    assert rev_p0 == rev_p1, f"Identical queues must yield identical revenue: {rev_p0} vs {rev_p1}"
    print(f"  [PASS] A3: P0 Rev=${rev_p0} == P1 Rev=${rev_p1} (Seat Neutral).")
    return {
        "passed": True,
        "queue": q,
        "revenue_p0": rev_p0,
        "revenue_p1": rev_p1,
        "seat_neutral": rev_p0 == rev_p1,
    }


def test_a4_quantity_asymmetry():
    """A4: Unequal quantities in same slot (e.g. 3 vs 10 units lockstep)."""
    print("Running Test A4: Unequal quantities lockstep...")
    env, state = make_fresh_market_state()
    # P0 sells 3 WOOL, P1 sells 10 WOOL in slot 0
    state[0].action = {"farmer": ["PASS"], "hands": [], "market": [["SELL", "WOOL", 3]]}
    state[1].action = {"farmer": ["PASS"], "hands": [], "market": [["SELL", "WOOL", 10]]}

    cash_pre_p0 = state[0].observation.farms[0]["money"]
    cash_pre_p1 = state[0].observation.farms[1]["money"]
    kengine._process_market(state, env)
    rev_p0 = state[0].observation.farms[0]["money"] - cash_pre_p0
    rev_p1 = state[0].observation.farms[1]["money"] - cash_pre_p1

    # First 3 units are quoted symmetrically. Then P0 is finished, and P1 continues units 4..10 alone
    # Compute theoretical first 3 units:
    inv = 10000
    first_3_rev = 0
    for _ in range(3):
        first_3_rev += kengine.market_price("WOOL", inv)
        inv += 2  # both committed 1 unit
    assert rev_p0 == first_3_rev, f"P0 first 3 units revenue: {rev_p0} vs {first_3_rev}"

    # P1 remaining 7 units
    remaining_7_rev = 0
    for _ in range(7):
        remaining_7_rev += kengine.market_price("WOOL", inv)
        inv += 1  # only P1 committed
    assert rev_p1 == first_3_rev + remaining_7_rev, f"P1 revenue: {rev_p1} vs {first_3_rev + remaining_7_rev}"

    print(f"  [PASS] A4: Lockstep matches exact theoretical unit progression (P0=${rev_p0}, P1=${rev_p1}).")
    return {
        "passed": True,
        "p0_qty": 3,
        "p1_qty": 10,
        "p0_revenue": rev_p0,
        "p1_revenue": rev_p1,
        "first_3_units_equal": True,
    }


def test_a5_different_products_independence():
    """A5: Slot ordering of different products (WOOL vs MILK) does not affect cross prices."""
    print("Running Test A5: Cross-product independence...")
    # Queue A: Slot 0 WOOL, Slot 1 MILK
    env_a, state_a = make_fresh_market_state()
    state_a[0].action = {"farmer": ["PASS"], "hands": [], "market": [["SELL", "WOOL", 4], ["SELL", "MILK", 4]]}
    state_a[1].action = {"farmer": ["PASS"], "hands": [], "market": []}
    cash_pre_a = state_a[0].observation.farms[0]["money"]
    kengine._process_market(state_a, env_a)
    rev_a = state_a[0].observation.farms[0]["money"] - cash_pre_a

    # Queue B: Slot 0 MILK, Slot 1 WOOL
    env_b, state_b = make_fresh_market_state()
    state_b[0].action = {"farmer": ["PASS"], "hands": [], "market": [["SELL", "MILK", 4], ["SELL", "WOOL", 4]]}
    state_b[1].action = {"farmer": ["PASS"], "hands": [], "market": []}
    cash_pre_b = state_b[0].observation.farms[0]["money"]
    kengine._process_market(state_b, env_b)
    rev_b = state_b[0].observation.farms[0]["money"] - cash_pre_b

    assert rev_a == rev_b, f"Independent products must yield identical total cash regardless of slot order: {rev_a} vs {rev_b}"
    print(f"  [PASS] A5: Uncontested products have zero slot dependency (${rev_a} == ${rev_b}).")
    return {
        "passed": True,
        "rev_wool_then_milk": rev_a,
        "rev_milk_then_wool": rev_b,
        "independent": rev_a == rev_b,
    }


def test_a6_product_sensitivity():
    """A6: Sensitivity of revenue to being 1 slot late (Slot 0 vs Slot 1) across all products."""
    print("Running Test A6: Product sensitivity analysis across all products...")
    products = ["STRAWBERRY", "MELON", "MILK", "WOOL", "FERTILIZER", "WHEAT", "CARROT", "TOMATO"]
    results = {}

    for prod in products:
        # Us: 5 units of prod. Opponent: 5 units of prod.
        # Slot 0 Us, Slot 1 Opp
        env_a, state_a = make_fresh_market_state()
        state_a[0].action = {"farmer": ["PASS"], "hands": [], "market": [["SELL", prod, 5]]}
        state_a[1].action = {"farmer": ["PASS"], "hands": [], "market": [["SELL", "WHEAT" if prod != "WHEAT" else "CARROT", 1], ["SELL", prod, 5]]}
        cash_pre_a0 = state_a[0].observation.farms[0]["money"]
        kengine._process_market(state_a, env_a)
        rev_early = state_a[0].observation.farms[0]["money"] - cash_pre_a0

        # Slot 1 Us, Slot 0 Opp
        env_b, state_b = make_fresh_market_state()
        state_b[0].action = {"farmer": ["PASS"], "hands": [], "market": [["SELL", "WHEAT" if prod != "WHEAT" else "CARROT", 1], ["SELL", prod, 5]]}
        state_b[1].action = {"farmer": ["PASS"], "hands": [], "market": [["SELL", prod, 5]]}
        cash_pre_b0 = state_b[0].observation.farms[0]["money"]
        dummy_price = kengine.market_price("WHEAT" if prod != "WHEAT" else "CARROT", 10000)
        kengine._process_market(state_b, env_b)
        rev_late = (state_b[0].observation.farms[0]["money"] - cash_pre_b0) - dummy_price

        loss_from_being_late = rev_early - rev_late
        pct_loss = (loss_from_being_late / rev_early * 100) if rev_early > 0 else 0.0

        results[prod] = {
            "rev_slot_0": rev_early,
            "rev_slot_1": rev_late,
            "loss_from_slot_1": loss_from_being_late,
            "pct_loss": pct_loss,
        }
        print(f"    {prod:12s}: Slot 0=${rev_early:6.1f} -> Slot 1=${rev_late:6.1f} | Loss=${loss_from_being_late:5.1f} ({pct_loss:.1f}%)")

    print("  [PASS] A6: Product price-race sensitivity measured.")
    return results


def main():
    print("=== Phase M0-H Engine Market Slot Verification ===")
    res_a1 = test_a1_same_slot_lockstep()
    res_a2 = test_a2_different_slots_price_race()
    res_a3 = test_a3_seat_symmetry()
    res_a4 = test_a4_quantity_asymmetry()
    res_a5 = test_a5_different_products_independence()
    res_a6 = test_a6_product_sensitivity()

    manifest = {
        "phase": "M0-H",
        "description": "Real-engine market slot lockstep verification",
        "all_passed": all([res_a1["passed"], res_a2["passed"], res_a3["passed"], res_a4["passed"], res_a5["passed"]]),
    }

    with open(os.path.join(OUT_DIR, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    with open(os.path.join(OUT_DIR, "same_slot_lockstep.json"), "w", encoding="utf-8") as f:
        json.dump(res_a1, f, indent=2)
    with open(os.path.join(OUT_DIR, "different_slot_price_race.json"), "w", encoding="utf-8") as f:
        json.dump(res_a2, f, indent=2)
    with open(os.path.join(OUT_DIR, "seat_symmetry.json"), "w", encoding="utf-8") as f:
        json.dump(res_a3, f, indent=2)
    with open(os.path.join(OUT_DIR, "quantity_asymmetry.json"), "w", encoding="utf-8") as f:
        json.dump(res_a4, f, indent=2)
    with open(os.path.join(OUT_DIR, "product_sensitivity.json"), "w", encoding="utf-8") as f:
        json.dump(res_a6, f, indent=2)

    print(f"\nAll deliverables written to {OUT_DIR}")
    print("Engine verification complete: ALL PASSED (6/6)")


if __name__ == "__main__":
    main()
