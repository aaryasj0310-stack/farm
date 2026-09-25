"""Phase M0-I: Real-Engine Same-Turn Sale-Funded Purchase Financing Verification.

Executes microtests against kaggle_environments.envs.kaggriculture.kaggriculture:
- A1: SELL -> BUY_SEED (forward succeeds using new cash; reverse fails when cash insufficient)
- A2: SELL -> BUY_LAND (forward succeeds using new cash; reverse fails)
- A3: SELL -> BUY_ANIMAL (forward succeeds and frees shed space; reverse fails)
- A4: SELL -> BUY_PRODUCT WHEAT (forward succeeds using live post-sale cash; reverse fails)
- A5: SELL -> HIRE (forward succeeds in slot 1 with slot 0 proceeds; reverse fails)
- A6: Multiple sale orders funding one purchase (cumulative revenue financing)
- A7: Partial sale execution (unsupported sale quantities fail and do not overfund purchases)

Outputs under simulations/results/phase_m0_i_engine_verification/:
- manifest.json
- sell_buy_seed.json
- sell_buy_land.json
- sell_buy_animal.json
- sell_buy_product.json
- sell_hire.json
- partial_execution.json
- multi_sale_financing.json
"""
from __future__ import annotations

import copy
import json
import os
import sys
from typing import Any, Dict

_REPO_ROOT = r"d:\website project\kaggri ox"
OUT_DIR = os.path.join(_REPO_ROOT, "simulations", "results", "phase_m0_i_engine_verification")
os.makedirs(OUT_DIR, exist_ok=True)

import kaggle_environments as ke
import kaggle_environments.envs.kaggriculture.kaggriculture as kengine


def make_fresh_state(seed: int = 96501):
    env = ke.make("kaggriculture", configuration={"episodeSteps": 720, "seed": seed}, debug=False)
    env.reset()
    state = env.state
    return env, state


def test_a1_sell_buy_seed() -> Dict[str, Any]:
    print("Running Test A1: SELL -> BUY_SEED...")
    # Strawberry seed costs 50
    # Forward: cash = $10, 1 FERTILIZER in shed. Slot 0 SELL FERTILIZER, Slot 1 BUY_SEED STRAWBERRY
    env_f, state_f = make_fresh_state()
    state_f[0].observation.farms[0]["money"] = 10.0
    state_f[0].observation.private.shed["FERTILIZER"] = 1
    state_f[0].action = {"market": [["SELL", "FERTILIZER", 1], ["BUY_SEED", "STRAWBERRY", 1]]}
    state_f[1].action = {"market": []}
    kengine._process_market(state_f, env_f)
    f_money = state_f[0].observation.farms[0]["money"]
    f_seeds = state_f[0].observation.private.seeds.get("STRAWBERRY", 0)

    # Reverse: Slot 0 BUY_SEED STRAWBERRY, Slot 1 SELL FERTILIZER
    env_r, state_r = make_fresh_state()
    state_r[0].observation.farms[0]["money"] = 10.0
    state_r[0].observation.private.shed["FERTILIZER"] = 1
    state_r[0].action = {"market": [["BUY_SEED", "STRAWBERRY", 1], ["SELL", "FERTILIZER", 1]]}
    state_r[1].action = {"market": []}
    kengine._process_market(state_r, env_r)
    r_money = state_r[0].observation.farms[0]["money"]
    r_seeds = state_r[0].observation.private.seeds.get("STRAWBERRY", 0)

    assert f_seeds == 1, "Forward BUY_SEED must succeed using sale proceeds"
    assert r_seeds == 0, "Reverse BUY_SEED must fail due to insufficient pre-sale cash"
    assert f_money == 10.0, f"Expected final money 10 (10 + 100 - 100), got {f_money}"
    assert r_money == 110.0, f"Expected final money 110 (10 + 100, seed not bought), got {r_money}"

    print(f"  [PASS] A1: Forward seeds={f_seeds}, Reverse seeds={r_seeds}")
    res = {
        "passed": True,
        "seed_product": "STRAWBERRY",
        "seed_cost": 50,
        "initial_cash": 10.0,
        "forward_seed_bought": f_seeds == 1,
        "forward_final_cash": f_money,
        "reverse_seed_bought": r_seeds == 1,
        "reverse_final_cash": r_money,
    }
    with open(os.path.join(OUT_DIR, "sell_buy_seed.json"), "w", encoding="utf-8") as f:
        json.dump(res, f, indent=2)
    return res


def test_a2_sell_buy_land() -> Dict[str, Any]:
    print("Running Test A2: SELL -> BUY_LAND...")
    # First extra quadrant (SE) costs 500
    # Forward: cash = $100, 10 FERTILIZER in shed (sale yields ~500). Slot 0 SELL FERTILIZER 10, Slot 1 BUY_LAND
    env_f, state_f = make_fresh_state()
    state_f[0].observation.farms[0]["money"] = 100.0
    state_f[0].observation.private.shed["FERTILIZER"] = 10
    state_f[0].action = {"market": [["SELL", "FERTILIZER", 10], ["BUY_LAND"]]}
    state_f[1].action = {"market": []}
    kengine._process_market(state_f, env_f)
    f_money = state_f[0].observation.farms[0]["money"]
    f_unlocked = len(state_f[0].observation.farms[0]["unlocked_quadrants"])

    # Reverse: Slot 0 BUY_LAND, Slot 1 SELL FERTILIZER 10
    env_r, state_r = make_fresh_state()
    state_r[0].observation.farms[0]["money"] = 100.0
    state_r[0].observation.private.shed["FERTILIZER"] = 10
    state_r[0].action = {"market": [["BUY_LAND"], ["SELL", "FERTILIZER", 10]]}
    state_r[1].action = {"market": []}
    kengine._process_market(state_r, env_r)
    r_money = state_r[0].observation.farms[0]["money"]
    r_unlocked = len(state_r[0].observation.farms[0]["unlocked_quadrants"])

    assert f_unlocked == 2, "Forward BUY_LAND must succeed with post-sale cash"
    assert r_unlocked == 1, "Reverse BUY_LAND must fail because pre-sale cash < 500"
    print(f"  [PASS] A2: Forward unlocked={f_unlocked}, Reverse unlocked={r_unlocked}")
    res = {
        "passed": True,
        "land_cost": 500,
        "initial_cash": 100.0,
        "forward_land_unlocked": f_unlocked == 2,
        "forward_final_cash": f_money,
        "reverse_land_unlocked": r_unlocked == 2,
        "reverse_final_cash": r_money,
    }
    with open(os.path.join(OUT_DIR, "sell_buy_land.json"), "w", encoding="utf-8") as f:
        json.dump(res, f, indent=2)
    return res


def test_a3_sell_buy_animal() -> Dict[str, Any]:
    print("Running Test A3: SELL -> BUY_ANIMAL...")
    # COW costs 400. Shed capacity is 100.
    # Case 1: Cash insufficient, sale funds cow
    env_f, state_f = make_fresh_state()
    state_f[0].observation.farms[0]["money"] = 50.0
    state_f[0].observation.private.shed["FERTILIZER"] = 8  # 8 * 50 = 400 -> cash = 450
    state_f[0].action = {"market": [["SELL", "FERTILIZER", 8], ["BUY_ANIMAL", "COW", 1]]}
    state_f[1].action = {"market": []}
    kengine._process_market(state_f, env_f)
    f_money = state_f[0].observation.farms[0]["money"]
    f_cow = state_f[0].observation.private.shed.get("COW", 0)

    # Reverse: BUY_ANIMAL first
    env_r, state_r = make_fresh_state()
    state_r[0].observation.farms[0]["money"] = 50.0
    state_r[0].observation.private.shed["FERTILIZER"] = 8
    state_r[0].action = {"market": [["BUY_ANIMAL", "COW", 1], ["SELL", "FERTILIZER", 8]]}
    state_r[1].action = {"market": []}
    kengine._process_market(state_r, env_r)
    r_money = state_r[0].observation.farms[0]["money"]
    r_cow = state_r[0].observation.private.shed.get("COW", 0)

    # Case 2: Shed capacity interaction: shed completely full (100 units).
    # SELL 1 unit frees 1 capacity, enabling BUY_ANIMAL 1 unit!
    env_cap, state_cap = make_fresh_state()
    state_cap[0].observation.farms[0]["money"] = 500.0  # plenty of money
    state_cap[0].observation.private.shed["WHEAT"] = 100  # 100/100 full
    state_cap[0].action = {"market": [["SELL", "WHEAT", 1], ["BUY_ANIMAL", "COW", 1]]}
    state_cap[1].action = {"market": []}
    kengine._process_market(state_cap, env_cap)
    cap_cow = state_cap[0].observation.private.shed.get("COW", 0)

    assert f_cow == 1, "Forward BUY_ANIMAL must succeed using sale proceeds"
    assert r_cow == 0, "Reverse BUY_ANIMAL must fail due to insufficient cash"
    assert cap_cow == 1, "SELL in slot 0 must free shed capacity to allow BUY_ANIMAL in slot 1"
    print(f"  [PASS] A3: Forward cow={f_cow}, Reverse cow={r_cow}, Full-shed cow={cap_cow}")
    res = {
        "passed": True,
        "animal": "COW",
        "animal_cost": 400,
        "initial_cash": 50.0,
        "forward_animal_bought": f_cow == 1,
        "reverse_animal_bought": r_cow == 1,
        "shed_capacity_freed_and_used": cap_cow == 1,
    }
    with open(os.path.join(OUT_DIR, "sell_buy_animal.json"), "w", encoding="utf-8") as f:
        json.dump(res, f, indent=2)
    return res


def test_a4_sell_buy_product() -> Dict[str, Any]:
    print("Running Test A4: SELL -> BUY_PRODUCT WHEAT...")
    # BUY_PRODUCT WHEAT costs post-buy inventory price (~25 at inv 10,000)
    # Forward: cash = $5, 1 FERTILIZER in shed. Slot 0 SELL FERTILIZER 1, Slot 1 BUY_PRODUCT WHEAT 1
    env_f, state_f = make_fresh_state()
    state_f[0].observation.farms[0]["money"] = 5.0
    state_f[0].observation.private.shed["FERTILIZER"] = 1
    state_f[0].action = {"market": [["SELL", "FERTILIZER", 1], ["BUY_PRODUCT", "WHEAT", 1]]}
    state_f[1].action = {"market": []}
    kengine._process_market(state_f, env_f)
    f_wheat = state_f[0].observation.private.shed.get("WHEAT", 0)

    # Reverse: Slot 0 BUY_PRODUCT WHEAT 1, Slot 1 SELL FERTILIZER 1
    env_r, state_r = make_fresh_state()
    state_r[0].observation.farms[0]["money"] = 5.0
    state_r[0].observation.private.shed["FERTILIZER"] = 1
    state_r[0].action = {"market": [["BUY_PRODUCT", "WHEAT", 1], ["SELL", "FERTILIZER", 1]]}
    state_r[1].action = {"market": []}
    kengine._process_market(state_r, env_r)
    r_wheat = state_r[0].observation.private.shed.get("WHEAT", 0)

    assert f_wheat == 1, "Forward BUY_PRODUCT must succeed using sale cash"
    assert r_wheat == 0, "Reverse BUY_PRODUCT must fail due to cash shortfall"
    print(f"  [PASS] A4: Forward wheat={f_wheat}, Reverse wheat={r_wheat}")
    res = {
        "passed": True,
        "product": "WHEAT",
        "initial_cash": 5.0,
        "forward_product_bought": f_wheat == 1,
        "reverse_product_bought": r_wheat == 1,
    }
    with open(os.path.join(OUT_DIR, "sell_buy_product.json"), "w", encoding="utf-8") as f:
        json.dump(res, f, indent=2)
    return res


def test_a5_sell_hire() -> Dict[str, Any]:
    print("Running Test A5: SELL -> HIRE...")
    # First hire of the day costs _fib(0) * mult = 1 * 1 = $1.00
    # Forward: cash = $0, 1 FERTILIZER in shed. Slot 0 SELL FERTILIZER 1, Slot 1 HIRE
    env_f, state_f = make_fresh_state()
    state_f[0].observation.farms[0]["money"] = 0.0
    state_f[0].observation.private.shed["FERTILIZER"] = 1
    state_f[0].action = {"market": [["SELL", "FERTILIZER", 1], ["HIRE"]]}
    state_f[1].action = {"market": []}
    kengine._process_market(state_f, env_f)
    f_hands = len(state_f[0].observation.farms[0]["hands"])
    f_money = state_f[0].observation.farms[0]["money"]

    # Reverse: Slot 0 HIRE, Slot 1 SELL FERTILIZER 1
    env_r, state_r = make_fresh_state()
    state_r[0].observation.farms[0]["money"] = 0.0
    state_r[0].observation.private.shed["FERTILIZER"] = 1
    state_r[0].action = {"market": [["HIRE"], ["SELL", "FERTILIZER", 1]]}
    state_r[1].action = {"market": []}
    kengine._process_market(state_r, env_r)
    r_hands = len(state_r[0].observation.farms[0]["hands"])
    r_money = state_r[0].observation.farms[0]["money"]

    assert f_hands == 1, "Forward HIRE in slot 1 must succeed using slot 0 sale cash"
    assert r_hands == 0, "Reverse HIRE in slot 0 must fail due to zero pre-sale cash"
    assert f_money == 99.0, f"Expected final money 99 (0 + 100 - 1), got {f_money}"
    assert r_money == 100.0, f"Expected final money 100 (0 + 100, hire failed), got {r_money}"
    print(f"  [PASS] A5: Forward hands={f_hands}, Reverse hands={r_hands}")
    res = {
        "passed": True,
        "initial_cash": 0.0,
        "hire_cost": 1,
        "forward_hire_succeeded": f_hands == 1,
        "forward_final_cash": f_money,
        "reverse_hire_succeeded": r_hands == 1,
        "reverse_final_cash": r_money,
    }
    with open(os.path.join(OUT_DIR, "sell_hire.json"), "w", encoding="utf-8") as f:
        json.dump(res, f, indent=2)
    return res


def test_a6_multi_sale_financing() -> Dict[str, Any]:
    print("Running Test A6: Multiple sale orders funding one purchase...")
    # Land costs 1000. Cash = $10.
    # Slot 0 SELL FERTILIZER 8 (yields ~800), Slot 1 SELL MILK 3 (yields ~469), Slot 2 BUY_LAND
    env, state = make_fresh_state()
    state[0].observation.farms[0]["money"] = 10.0
    state[0].observation.private.shed["FERTILIZER"] = 8
    state[0].observation.private.shed["MILK"] = 3
    state[0].action = {"market": [["SELL", "FERTILIZER", 8], ["SELL", "MILK", 3], ["BUY_LAND"]]}
    state[1].action = {"market": []}
    kengine._process_market(state, env)
    unlocked = len(state[0].observation.farms[0]["unlocked_quadrants"])
    final_cash = state[0].observation.farms[0]["money"]

    assert unlocked == 2, "Cumulative proceeds from multiple sales must fund BUY_LAND"
    print(f"  [PASS] A6: Cumulative sales funded BUY_LAND. Final cash=${final_cash:.2f}")
    res = {
        "passed": True,
        "sales_count": 2,
        "target_purchase": "BUY_LAND",
        "purchase_succeeded": unlocked == 2,
        "final_cash": final_cash,
    }
    with open(os.path.join(OUT_DIR, "multi_sale_financing.json"), "w", encoding="utf-8") as f:
        json.dump(res, f, indent=2)
    return res


def test_a7_partial_sale_execution() -> Dict[str, Any]:
    print("Running Test A7: Partial sale execution...")
    # Agent requests SELL 10 FERTILIZER, but shed has only 2!
    # Proceeds from 2 FERTILIZER = $100.
    # Target purchase in slot 1 is COW ($400).
    # Since only 2 units sold, cash is only $100 (< 400), so COW purchase must FAIL!
    env, state = make_fresh_state()
    state[0].observation.farms[0]["money"] = 0.0
    state[0].observation.private.shed["FERTILIZER"] = 2  # Only 2 available!
    state[0].action = {"market": [["SELL", "FERTILIZER", 10], ["BUY_ANIMAL", "COW", 1]]}
    state[1].action = {"market": []}
    kengine._process_market(state, env)
    cow = state[0].observation.private.shed.get("COW", 0)
    final_cash = state[0].observation.farms[0]["money"]

    assert cow == 0, "BUY_ANIMAL must fail because partial sale revenue was insufficient"
    assert final_cash == 200.0, f"Expected exactly 2 units sold ($200), got {final_cash}"
    print(f"  [PASS] A7: Partial sale correctly blocked overfunded purchase. Cash=${final_cash}")
    res = {
        "passed": True,
        "requested_sell_qty": 10,
        "actual_shed_qty": 2,
        "partial_revenue": final_cash,
        "overfunded_purchase_prevented": cow == 0,
    }
    with open(os.path.join(OUT_DIR, "partial_execution.json"), "w", encoding="utf-8") as f:
        json.dump(res, f, indent=2)
    return res


def main():
    print("=== Phase M0-I Real-Engine Same-Turn Sale Financing Verification ===")
    r1 = test_a1_sell_buy_seed()
    r2 = test_a2_sell_buy_land()
    r3 = test_a3_sell_buy_animal()
    r4 = test_a4_sell_buy_product()
    r5 = test_a5_sell_hire()
    r6 = test_a6_multi_sale_financing()
    r7 = test_a7_partial_sale_execution()

    all_passed = all([
        r1["passed"], r2["passed"], r3["passed"], r4["passed"],
        r5["passed"], r6["passed"], r7["passed"]
    ])
    manifest = {
        "phase": "M0-I",
        "description": "Real-engine same-turn sale-funded purchase financing verification",
        "all_passed": all_passed,
        "tests": {
            "A1_SELL_BUY_SEED": r1["passed"],
            "A2_SELL_BUY_LAND": r2["passed"],
            "A3_SELL_BUY_ANIMAL": r3["passed"],
            "A4_SELL_BUY_PRODUCT": r4["passed"],
            "A5_SELL_HIRE": r5["passed"],
            "A6_MULTI_SALE_FINANCING": r6["passed"],
            "A7_PARTIAL_SALE_EXECUTION": r7["passed"],
        }
    }
    with open(os.path.join(OUT_DIR, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    print(f"\nAll 7 microtests passed: {all_passed}")


if __name__ == "__main__":
    main()
