"""Agent Zoo: Strategic Archetypes and Benchmark Baselines for Kaggriculture."""

from .baselines import random_agent, starter_agent, pass_agent
from .pure_wheat_rush import pure_wheat_rush_agent
from .goose_wheat_engine import goose_wheat_agent, goose_no_care_agent
from .melon_sniper import melon_sniper_agent, melon_unfertilized_agent
from .cow_milk_engine import cow_milk_agent
from .full_production_agent import full_production_agent

AGENT_REGISTRY = {
    "random": random_agent,
    "starter": starter_agent,
    "pass": pass_agent,
    "pure_wheat_rush": pure_wheat_rush_agent,
    "goose_wheat_engine": goose_wheat_agent,
    "goose_no_care": goose_no_care_agent,
    "melon_sniper": melon_sniper_agent,
    "melon_unfertilized": melon_unfertilized_agent,
    "cow_milk_engine": cow_milk_agent,
    "full_production_agent": full_production_agent,
}


def get_agent(name):
    if name not in AGENT_REGISTRY:
        raise ValueError(f"Unknown agent: {name}. Available: {list(AGENT_REGISTRY.keys())}")
    return AGENT_REGISTRY[name]
