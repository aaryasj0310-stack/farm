"""Phase M0-D: Smoke Test Storage Rescue.

Runs 2 seeds x 2 opponents x 2 seats x 2 arms (OFF vs RESCUE) = 16 matches
Verifies:
- Execution without crash
- Discard reduction
- Conservation check: carried == deposited + discarded
"""

import sys, os
_REPO_ROOT = r"d:\website project\kaggri ox"
_AGENT_DIR = os.path.join(_REPO_ROOT, "agent")
sys.path = [_REPO_ROOT, _AGENT_DIR] + [os.path.join(_AGENT_DIR, s) for s in ("state", "strategy", "execution", "market")] + sys.path

import kaggle_environments as ke
import kaggle_environments.envs.kaggriculture.kaggriculture as kengine
from agent.main import agent, reset_agent_state
import config
from strategy.sw_tranche_controller import reset_sw_tranche_controller
from simulations.experiments.agent_zoo import get_agent
from execution.midnight_storage_controller import get_midnight_storage_telemetry

def run_match(seed: int, opp_name: str, seat: int, mode: str):
    config.set_same_turn_crop_pipeline_mode("OFF")
    config.set_midnight_storage_dump_mode(mode)
    config.SW_FORWARD_ARCHITECTURE_MODE = "OFF"
    config.SOFT_WORKER_LOCALITY_MODE = "OFF"
    reset_agent_state()
    reset_sw_tranche_controller()

    daily_events = []
    call_count = [0]
    orig_drop = kengine._drop_inventories_to_shed

    def inst_drop(private, capacity):
        p_id = call_count[0] % 2
        day = call_count[0] // 2
        call_count[0] += 1
        if p_id == seat:
            carried = {}
            for inv in private["inventories"]:
                for k, v in inv.items():
                    if v > 0:
                        carried[k] = carried.get(k, 0) + v
            shed_pre = dict(private["shed"])
            orig_drop(private, capacity)
            shed_post = dict(private["shed"])
            dep = {}
            for k in set(shed_pre.keys()).union(shed_post.keys()):
                d = shed_post.get(k, 0) - shed_pre.get(k, 0)
                if d > 0: dep[k] = d
            disc = {}
            for k, v in carried.items():
                diff = v - dep.get(k, 0)
                if diff > 0: disc[k] = diff
            c_tot = sum(carried.values())
            d_tot = sum(dep.values())
            x_tot = sum(disc.values())
            assert c_tot == d_tot + x_tot
            daily_events.append({"day": day, "carried": c_tot, "deposited": d_tot, "discarded": x_tot})
        else:
            orig_drop(private, capacity)

    kengine._drop_inventories_to_shed = inst_drop
    opp = get_agent(opp_name)
    env = ke.make("kaggriculture", configuration={"episodeSteps": 720, "seed": seed}, debug=False)
    env.reset()

    try:
        while not env.done:
            a0 = agent(env.state[seat].observation, env.configuration)
            try:
                a1 = opp(env.state[1 - seat].observation, env.configuration)
            except TypeError:
                a1 = opp(env.state[1 - seat].observation)
            actions = [a0, a1] if seat == 0 else [a1, a0]
            env.step(actions)
    finally:
        kengine._drop_inventories_to_shed = orig_drop

    final_cash = float(env.steps[-1][seat].reward or 0.0)
    tot_carried = sum(e["carried"] for e in daily_events)
    tot_dep = sum(e["deposited"] for e in daily_events)
    tot_disc = sum(e["discarded"] for e in daily_events)
    telem = get_midnight_storage_telemetry()

    return {
        "seed": seed, "opp": opp_name, "seat": seat, "mode": mode,
        "cash": final_cash, "carried": tot_carried, "deposited": tot_dep, "discarded": tot_disc,
        "rescue_events": telem.get("rescue_events", 0),
        "rescue_units_sold": telem.get("rescue_units_sold", 0),
    }

if __name__ == "__main__":
    for s in (96501, 96502):
        for o in ("pass", "full_production_agent"):
            for seat in (0,):
                r_off = run_match(s, o, seat, "OFF")
                r_res = run_match(s, o, seat, "RESCUE")
                d_cash = r_res["cash"] - r_off["cash"]
                d_disc = r_res["discarded"] - r_off["discarded"]
                print(f"Seed {s} vs {o:22s}: OFF cash=${r_off['cash']:,.2f} disc={r_off['discarded']} | RESCUE cash=${r_res['cash']:,.2f} disc={r_res['discarded']} (sold {r_res['rescue_units_sold']}) | delta cash=+${d_cash:,.2f} delta disc={d_disc}")
