"""Trace actual engine farm state across all 30 days using parsed observation."""

import os
import sys

_REPO_ROOT = r"d:\website project\kaggri ox"
_AGENT_DIR = os.path.join(_REPO_ROOT, "agent")
sys.path = [_REPO_ROOT, _AGENT_DIR] + [os.path.join(_AGENT_DIR, s) for s in ('state', 'strategy', 'execution', 'market')] + [p for p in sys.path if 'agent' not in p]

from kaggle_environments import make
import config
from main import agent, reset_agent_state
from state.observation_parser import parse_observation
from simulations.experiments.agent_zoo import get_agent

config.set_sw_forward_architecture_mode("OFF")
reset_agent_state()

daily_stats = []

def tracking_agent(obs, conf=None):
    act = agent(obs, conf)
    if obs.get("hour") == 23:
        ctx = parse_observation(obs)
        if ctx:
            day = ctx["day"]
            shed = ctx["private"].shed
            total_shed = sum(shed.values())
            workers = ctx["n_units"]
            money = ctx["farm"].money
            daily_stats.append({
                "day": day,
                "workers": workers,
                "shed_total": total_shed,
                "shed_items": dict(shed),
                "money": money,
            })
    return act

env = make("kaggriculture", configuration={"episodeSteps": 720, "seed": 96511}, debug=False)
env.run([tracking_agent, get_agent("pass")])

print(f"{'Day':<5} | {'Workers':<8} | {'Money':<10} | {'Shed Total':<10} | {'Shed Items'}")
print("-" * 85)
for s in daily_stats:
    print(f"{s['day']:<5} | {s['workers']:<8} | ${s['money']:<9.1f} | {s['shed_total']:<10} | {s['shed_items']}")
