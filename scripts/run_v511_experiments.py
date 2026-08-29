"""v5.11 Experiment Runner — A/B testing for expansion planner variants.

Usage:
    python scripts/run_v511_experiments.py --experiment sw_seed_mix --episodes 100
    python scripts/run_v511_experiments.py --experiment day0_sw_interaction --episodes 100

Requires: kaggle_environments installed and configured.
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path
from dataclasses import dataclass, field
from typing import Dict, List, Any

# Add agent to path
sys.path.insert(0, str(Path(__file__).parent.parent / "agent"))
sys.path.insert(0, str(Path(__file__).parent.parent / "submission"))
for sub in ["state", "strategy", "execution", "market"]:
    sys.path.insert(0, str(Path(__file__).parent.parent / "submission", sub))

from kaggle_environments import make
from config import (
    get_sw_seed_targets,
    get_strawberry_cap,
    DAY_TO_HANDS,
    get_target_hands,
)


@dataclass
class VariantResult:
    name: str
    description: str
    terminal_wealths: List[float] = field(default_factory=list)
    metrics: Dict[str, List[float]] = field(default_factory=dict)
    
    @property
    def mean_wealth(self) -> float:
        return sum(self.terminal_wealths) / len(self.terminal_wealths) if self.terminal_wealths else 0
    
    @property
    def median_wealth(self) -> float:
        if not self.terminal_wealths:
            return 0
        sorted_wealths = sorted(self.terminal_wealths)
        n = len(sorted_wealths)
        if n % 2 == 0:
            return (sorted_wealths[n//2 - 1] + sorted_wealths[n//2]) / 2
        return sorted_wealths[n//2]
    
    @property
    def p10(self) -> float:
        if not self.terminal_wealths:
            return 0
        idx = len(self.terminal_wealths) // 10
        return sorted(self.terminal_wealths)[idx]
    
    @property
    def p90(self) -> float:
        if not self.terminal_wealths:
            return 0
        idx = 9 * len(self.terminal_wealths) // 10
        return sorted(self.terminal_wealths)[idx]


def load_experiment_config(name: str) -> Dict:
    """Load experiment config from JSON."""
    config_path = Path(__file__).parent.parent / "simulations" / "experiments" / "configs" / "v511_experiments.json"
    with open(config_path) as f:
        configs = json.load(f)
    for exp in configs["experiments"]:
        if exp["name"] == name:
            return exp
    raise ValueError(f"Experiment '{name}' not found")


def apply_variant_config(variant_config: Dict):
    """Apply variant config by temporarily overriding global config values.
    
    Returns dict of original values for restoration.
    """
    import config
    
    originals = {}
    
    if "sw_seed_strategy" in variant_config:
        originals["get_sw_seed_targets"] = getattr(config, "get_sw_seed_targets", None)
        strategy = variant_config["sw_seed_strategy"]
        
        if strategy == "static":
            strawberry = variant_config.get("strawberry", 8)
            tomato = variant_config.get("tomato", 4)
            config.get_sw_seed_targets = lambda day, money, land_cost=2000: {
                "STRAWBERRY": strawberry,
                "TOMATO": tomato,
            }
        elif strategy == "aggressive":
            config.get_sw_seed_targets = lambda day, money, land_cost=2000: {
                "STRAWBERRY": 12,
                "TOMATO": 0,
            }
        # "dynamic" uses the original function — no override needed
    
    if "day0_melon" in variant_config:
        originals["DAY0_MELON_TILES"] = getattr(config, "DAY0_MELON_TILES", None)
        config.DAY0_MELON_TILES = variant_config["day0_melon"]
    
    if "sw_purchase" in variant_config:
        originals["SW_PURCHASE_STRATEGY"] = getattr(config, "SW_PURCHASE_STRATEGY", None)
        config.SW_PURCHASE_STRATEGY = variant_config["sw_purchase"]
    
    return originals


def restore_config(originals: Dict):
    """Restore original config values after experiment."""
    import config
    for key, value in originals.items():
        if value is not None:
            setattr(config, key, value)


def extract_diagnostics_from_steps(env_steps) -> List[Dict]:
    """Extract diagnostics from environment steps.
    
    The agent stores diagnostics in the observation after each step.
    We parse the raw observation to extract diagnostic data.
    """
    diagnostics_log = []
    
    for step in env_steps:
        obs = step[0].observation
        day = obs.get("day", 0)
        hour = obs.get("hour", 0)
        
        # Extract basic metrics from observation
        farm = obs.get("farms", [{}])[0] if obs.get("farms") else {}
        
        diag = {
            "day": day,
            "hour": hour,
            "money": farm.get("money", 0),
            "hands": len(farm.get("hands", [])),
            "tiles_planted": sum(1 for t in farm.get("tiles", []) if t.get("is_plant", False)),
            "unlocked": farm.get("unlocked_quadrants", []),
        }
        
        # Count tiles by type
        tiles = farm.get("tiles", [])
        diag["tile_counts"] = {}
        for t in tiles:
            crop = t.get("crop", "EMPTY")
            diag["tile_counts"][crop] = diag["tile_counts"].get(crop, 0) + 1
        
        diagnostics_log.append(diag)
    
    return diagnostics_log


def run_episode(variant_config: Dict, seed: int) -> Dict[str, Any]:
    """Run a single episode and collect metrics."""
    env = make("kaggriculture", configuration={"seed": seed, "loglevel": "ERROR"})
    
    # Apply variant config
    originals = apply_variant_config(variant_config)
    
    try:
        # Import agent
        from main import agent
        
        # Run episode
        env.run([agent, "random"])
        
        # Extract metrics from final state
        final_obs = env.steps[-1][0].observation
        final_farm = final_obs.get("farms", [{}])[0] if final_obs.get("farms") else {}
        terminal_wealth = final_farm.get("money", 0)
        
        # Extract diagnostics from all steps
        diagnostics_log = extract_diagnostics_from_steps(env.steps)
        
        # Compute metrics
        metrics = {
            "terminal_wealth": terminal_wealth,
            "sw_occupancy": 0,
            "strawberry_tiles": 0,
            "land_roi": 0,
            "adjusted_roi": 0,
            "day10_cash": 0,
            "day20_cash": 0,
        }
        
        # Parse diagnostics log
        for diag in diagnostics_log:
            day = diag.get("day", 0)
            if day == 10:
                metrics["day10_cash"] = diag.get("money", 0)
            if day == 20:
                metrics["day20_cash"] = diag.get("money", 0)
            
            # Count strawberry tiles
            tile_counts = diag.get("tile_counts", {})
            strawberry = tile_counts.get("STRAWBERRY", 0)
            if strawberry > 0:
                metrics["strawberry_tiles"] = strawberry
                metrics["sw_occupancy"] = sum(1 for k, v in tile_counts.items() 
                                              if k in ["STRAWBERRY", "TOMATO", "MELON", "CARROT"] and v > 0)
        
        return metrics
    
    finally:
        # Restore original config
        restore_config(originals)


def run_experiment(experiment_name: str, episodes_per_variant: int):
    """Run full experiment with all variants."""
    config = load_experiment_config(experiment_name)
    print(f"\n{'='*60}")
    print(f"Experiment: {config['name']}")
    print(f"Description: {config['description']}")
    print(f"Episodes per variant: {episodes_per_variant}")
    print(f"{'='*60}\n")
    
    results = []
    for variant in config["variants"]:
        print(f"\nRunning variant: {variant['name']}...")
        result = VariantResult(
            name=variant["name"],
            description=variant["description"]
        )
        
        for i, seed in enumerate(config["seeds"]):
            for ep in range(episodes_per_variant):
                episode_result = run_episode(variant["config"], seed)
                result.terminal_wealths.append(episode_result["terminal_wealth"])
                
                # Collect other metrics
                for metric_name in ["sw_occupancy", "strawberry_tiles", "land_roi", 
                                   "adjusted_roi", "day10_cash", "day20_cash"]:
                    if metric_name not in result.metrics:
                        result.metrics[metric_name] = []
                    result.metrics[metric_name].append(episode_result[metric_name])
                
                # Progress indicator
                if (ep + 1) % 10 == 0:
                    print(f"  Seed {seed}: {ep + 1}/{episodes_per_variant} episodes")
        
        results.append(result)
    
    # Print results table
    print(f"\n{'='*60}")
    print("RESULTS")
    print(f"{'='*60}")
    print(f"{'Variant':<30} {'Mean':>10} {'Median':>10} {'P10':>10} {'P90':>10}")
    print("-" * 70)
    for r in results:
        print(f"{r.name:<30} {r.mean_wealth:>10.0f} {r.median_wealth:>10.0f} {r.p10:>10.0f} {r.p90:>10.0f}")
    
    # Print additional metrics
    print(f"\n{'='*60}")
    print("ADDITIONAL METRICS (Mean)")
    print(f"{'='*60}")
    metric_names = ["sw_occupancy", "strawberry_tiles", "land_roi", "adjusted_roi", 
                   "day10_cash", "day20_cash"]
    print(f"{'Variant':<30}", end="")
    for m in metric_names:
        print(f" {m[:12]:>12}", end="")
    print()
    print("-" * 120)
    for r in results:
        print(f"{r.name:<30}", end="")
        for m in metric_names:
            values = r.metrics.get(m, [0])
            mean_val = sum(values) / len(values) if values else 0
            print(f" {mean_val:>12.0f}", end="")
        print()
    
    # Save results
    output_path = Path(__file__).parent.parent / "simulations" / "experiments" / "results" / f"{experiment_name}_results.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump({
            "experiment": config["name"],
            "variants": [
                {
                    "name": r.name,
                    "description": r.description,
                    "mean_wealth": r.mean_wealth,
                    "median_wealth": r.median_wealth,
                    "p10": r.p10,
                    "p90": r.p90,
                    "terminal_wealths": r.terminal_wealths,
                    "metrics": {k: v for k, v in r.metrics.items()},
                }
                for r in results
            ]
        }, f, indent=2)
    print(f"\nResults saved to: {output_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run v5.11 A/B experiments")
    parser.add_argument("--experiment", required=True, help="Experiment name")
    parser.add_argument("--episodes", type=int, default=100, help="Episodes per variant")
    args = parser.parse_args()
    run_experiment(args.experiment, args.episodes)
