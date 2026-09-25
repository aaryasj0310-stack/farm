"""
Verify engine midnight overflow mechanics directly against the real kaggle_environments engine.
Covers Cases A, B, C, and D.
"""

import copy
import json
import os
import kaggle_environments as ke
import kaggle_environments.envs.kaggriculture.kaggriculture as kengine


def run_direct_mechanics_test():
    results = {}

    # Test Case A: Normal deposit below capacity
    shed_a = {"WHEAT": 40}
    invs_a = [{"CARROT": 10}, {"COW_MILK": 10}]
    priv_a = {"shed": copy.deepcopy(shed_a), "inventories": copy.deepcopy(invs_a)}
    kengine._drop_inventories_to_shed(priv_a, capacity=100)
    results["Case_A_Below_Capacity"] = {
        "description": "Total items (60) <= capacity (100). All items deposited.",
        "pre_shed": shed_a,
        "pre_inventories": invs_a,
        "post_shed": priv_a["shed"],
        "post_inventories": priv_a["inventories"],
        "total_shed_pre": sum(shed_a.values()),
        "total_carried_pre": sum(sum(inv.values()) for inv in invs_a),
        "total_shed_post": sum(priv_a["shed"].values()),
        "deposited": sum(priv_a["shed"].values()) - sum(shed_a.values()),
        "discarded": sum(sum(inv.values()) for inv in invs_a) - (sum(priv_a["shed"].values()) - sum(shed_a.values())),
        "all_inventories_cleared": all(len(inv) == 0 for inv in priv_a["inventories"]),
    }

    # Test Case B: Partial overflow
    shed_b = {"WHEAT": 90}
    invs_b = [{"CARROT": 15}]
    priv_b = {"shed": copy.deepcopy(shed_b), "inventories": copy.deepcopy(invs_b)}
    kengine._drop_inventories_to_shed(priv_b, capacity=100)
    results["Case_B_Partial_Overflow"] = {
        "description": "Shed at 90/100, farmer carries 15 carrots. 10 deposited, 5 discarded.",
        "pre_shed": shed_b,
        "pre_inventories": invs_b,
        "post_shed": priv_b["shed"],
        "post_inventories": priv_b["inventories"],
        "total_shed_pre": sum(shed_b.values()),
        "total_carried_pre": sum(sum(inv.values()) for inv in invs_b),
        "total_shed_post": sum(priv_b["shed"].values()),
        "deposited": sum(priv_b["shed"].values()) - sum(shed_b.values()),
        "discarded": sum(sum(inv.values()) for inv in invs_b) - (sum(priv_b["shed"].values()) - sum(shed_b.values())),
        "all_inventories_cleared": all(len(inv) == 0 for inv in priv_b["inventories"]),
    }

    # Test Case C: Full overflow
    shed_c = {"WHEAT": 100}
    invs_c = [{"MELON": 10}]
    priv_c = {"shed": copy.deepcopy(shed_c), "inventories": copy.deepcopy(invs_c)}
    kengine._drop_inventories_to_shed(priv_c, capacity=100)
    results["Case_C_Full_Overflow"] = {
        "description": "Shed at 100/100 (full), farmer carries 10 melons. 0 deposited, 10 discarded.",
        "pre_shed": shed_c,
        "pre_inventories": invs_c,
        "post_shed": priv_c["shed"],
        "post_inventories": priv_c["inventories"],
        "total_shed_pre": sum(shed_c.values()),
        "total_carried_pre": sum(sum(inv.values()) for inv in invs_c),
        "total_shed_post": sum(priv_c["shed"].values()),
        "deposited": sum(priv_c["shed"].values()) - sum(shed_c.values()),
        "discarded": sum(sum(inv.values()) for inv in invs_c) - (sum(priv_c["shed"].values()) - sum(shed_c.values())),
        "all_inventories_cleared": all(len(inv) == 0 for inv in priv_c["inventories"]),
    }

    # Test Case D: Multi-worker precedence
    shed_d = {"WHEAT": 95}
    invs_d = [{"EGG": 4}, {"SHEEP_WOOL": 4}]
    priv_d = {"shed": copy.deepcopy(shed_d), "inventories": copy.deepcopy(invs_d)}
    kengine._drop_inventories_to_shed(priv_d, capacity=100)
    results["Case_D_Multi_Worker_Precedence"] = {
        "description": "Shed at 95/100. Worker 0 carries 4 eggs, Worker 1 carries 4 wool. Room starts at 5. Worker 0 deposits 4, Worker 1 deposits 1, 3 wool discarded.",
        "pre_shed": shed_d,
        "pre_inventories": invs_d,
        "post_shed": priv_d["shed"],
        "post_inventories": priv_d["inventories"],
        "total_shed_pre": sum(shed_d.values()),
        "total_carried_pre": sum(sum(inv.values()) for inv in invs_d),
        "total_shed_post": sum(priv_d["shed"].values()),
        "deposited": sum(priv_d["shed"].values()) - sum(shed_d.values()),
        "discarded": sum(sum(inv.values()) for inv in invs_d) - (sum(priv_d["shed"].values()) - sum(shed_d.values())),
        "all_inventories_cleared": all(len(inv) == 0 for inv in priv_d["inventories"]),
    }

    # Verify real engine step 23 -> step 0 midnight transition
    env = ke.make("kaggriculture", configuration={"episodeSteps": 48})
    env.reset()
    # Fast-forward to step 23
    for _ in range(23):
        env.step([{}, {}])
    
    # At step 23, plant/give items to farmer and fill shed
    state = env.state
    state[0].observation.private["shed"] = {"WHEAT": 95}
    state[0].observation.private["inventories"] = [{"CARROT": 10}]
    
    # Step 23 action executes, triggers _end_of_day
    env.step([{}, {}])
    post_state = env.state
    post_shed = post_state[0].observation.private["shed"]
    post_invs = post_state[0].observation.private["inventories"]
    
    results["In_Engine_Step23_Transition"] = {
        "pre_step23_shed": {"WHEAT": 95},
        "pre_step23_inventory": [{"CARROT": 10}],
        "post_step24_shed": post_shed,
        "post_step24_inventory": post_invs,
        "deposited": sum(post_shed.values()) - 95,
        "discarded": 10 - (sum(post_shed.values()) - 95),
        "step_after_eod": env.steps[-1][0]["observation"]["step"],
        "day_after_eod": env.steps[-1][0]["observation"]["day"],
        "hour_after_eod": env.steps[-1][0]["observation"]["hour"],
    }

    return results


if __name__ == "__main__":
    res = run_direct_mechanics_test()
    out_dir = "simulations/results/phase_m0_d_engine_audit"
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "overflow_microtests.json")
    with open(out_path, "w") as fp:
        json.dump(res, fp, indent=2)
    print("Saved microtests to", out_path)
