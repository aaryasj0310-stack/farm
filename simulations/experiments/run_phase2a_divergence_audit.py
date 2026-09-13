import sys
import os
import copy
import json
import time
from concurrent.futures import ProcessPoolExecutor
from kaggle_environments import make

_REPO_ROOT = r"d:\website project\kaggri ox"
_BASELINE_DIR = os.path.join(_REPO_ROOT, "simulations", "baselines", "baseline_59cf176", "agent")
_CANDIDATE_DIR = os.path.join(_REPO_ROOT, "agent")

def run_agent_game(agent_dir, seed, opp_name):
    # Setup isolated environment
    clean_sys_path = [p for p in sys.path if 'agent' not in p and '.worktrees' not in p]
    sys.path = [agent_dir] + [os.path.join(agent_dir, s) for s in ('state', 'strategy', 'execution', 'market')] + clean_sys_path

    to_delete = [k for k in sys.modules if any(k.startswith(p) for p in (
        'main', 'config', 'strategy', 'state', 'execution', 'market',
        'task_scheduler', 'macro_planner', 'order_builder', 'animal_planner', 'pasture_planner',
        'expansion_planner', 'observation_parser', 'state_tracker', 'land_serviceability_model'
    ))]
    for k in to_delete:
        del sys.modules[k]

    import main as agent_module
    import state_tracker
    from observation_parser import parse_observation

    state_tracker.reset_memory()
    agent_module.reset_agent_state()
    agent_module.set_arbitration_mode("historical_candidates_central")

    actions_history = []
    obs_history = []

    def tracking_agent(obs, config=None):
        day = obs.get("day", 0)
        hour = obs.get("hour", 0)
        step = obs.get("step", day * 24 + hour)
        farms = obs.get("farms", [{}])
        my_farm = farms[0] if farms else {}
        
        snap = {
            "step": step,
            "day": day,
            "hour": hour,
            "money": my_farm.get("money", 0),
            "unlocked": list(my_farm.get("unlocked_quadrants", ["NW"])),
            "seeds": dict(my_farm.get("seeds", {})),
            "hands": len(my_farm.get("hands", [])),
        }
        obs_history.append(snap)

        act = agent_module.agent(obs, config)
        actions_history.append(act)
        return act

    env = make("kaggriculture", configuration={"seed": seed, "episodeSteps": 720})
    runner = env.run([tracking_agent, opp_name])

    last_step = runner[-1]
    final_reward = float(last_step[0].get("reward", 0.0) or 0.0)

    # Check if SW was bought
    p0_farm = last_step[0].get("observation", {}).get("farms", [{}])[0]
    final_unlocked = p0_farm.get("unlocked_quadrants", [])
    sw_bought = "SW" in final_unlocked

    return {
        "reward": final_reward,
        "sw_bought": sw_bought,
        "actions": actions_history,
        "obs_snapshots": obs_history
    }

def audit_pair(payload):
    seed = payload["seed"]
    opp = payload["opponent"]

    base_res = run_agent_game(_BASELINE_DIR, seed, opp)
    cand_res = run_agent_game(_CANDIDATE_DIR, seed, opp)

    diverged = False
    div_step = None
    div_day = None
    div_hour = None
    base_act = None
    cand_act = None
    base_state_sum = None
    cand_state_sum = None

    min_len = min(len(base_res["actions"]), len(cand_res["actions"]))
    for i in range(min_len):
        b_act = base_res["actions"][i]
        c_act = cand_res["actions"][i]

        if b_act != c_act:
            diverged = True
            b_obs = base_res["obs_snapshots"][i]
            c_obs = cand_res["obs_snapshots"][i]
            div_step = b_obs["step"]
            div_day = b_obs["day"]
            div_hour = b_obs["hour"]
            base_act = b_act
            cand_act = c_act
            base_state_sum = b_obs
            cand_state_sum = c_obs
            break

    return {
        "seed": seed,
        "opponent": opp,
        "diverged": diverged,
        "div_step": div_step,
        "div_day": div_day,
        "div_hour": div_hour,
        "base_reward": base_res["reward"],
        "cand_reward": cand_res["reward"],
        "delta": cand_res["reward"] - base_res["reward"],
        "base_sw": base_res["sw_bought"],
        "cand_sw": cand_res["sw_bought"],
        "base_act": base_act,
        "cand_act": cand_act,
        "base_state": base_state_sum,
        "cand_state": cand_state_sum,
    }

def main():
    seeds = range(101, 126)
    opponents = ["starter", "random"]
    payloads = [{"seed": s, "opponent": o} for s in seeds for o in opponents]

    print(f"Starting paired divergence audit across {len(payloads)} games...", flush=True)
    start_t = time.time()
    results = []

    with ProcessPoolExecutor(max_workers=6) as executor:
        futures = [executor.submit(audit_pair, p) for p in payloads]
        for fut in futures:
            res = fut.result()
            results.append(res)
            div_str = f"Diverged at D{res['div_day']:2d} H{res['div_hour']:2d} (Step {res['div_step']})" if res['diverged'] else "IDENTICAL"
            print(f"Seed {res['seed']:3d} vs {res['opponent']:7s}: {div_str:30s} | Base: ${res['base_reward']:,.0f} | Cand: ${res['cand_reward']:,.0f} | Delta: ${res['delta']:+,.0f}", flush=True)

    elapsed = time.time() - start_t
    print(f"\nAudit complete in {elapsed:.1f}s.", flush=True)

    divergent_runs = [r for r in results if r["diverged"]]
    print(f"Total pairs: {len(results)}, Divergent: {len(divergent_runs)}, Identical: {len(results) - len(divergent_runs)}", flush=True)

    out_file = os.path.join(_REPO_ROOT, "simulations", "experiments", "phase2a_divergence_results.json")
    with open(out_file, "w") as f:
        json.dump(results, f, indent=2)
    print(f"Results written to {out_file}", flush=True)

if __name__ == "__main__":
    main()
