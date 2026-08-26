---
name: experiment-runner
description: "Run Kaggressive simulations, CLI tools and validation games with exact commands: Monte Carlo shop sims, price/liquidation CLI, profitability reports, agent vs random/starter via kaggle_environments. Triggers on: run the simulation, run experiments, benchmark the agent, play games against, generate report, parameter sweep."
---

# Experiment Runner — Exact Commands

Run from each package dir. Artifacts -> that package's `results/`.
Pass/fail judgment -> `regression-checker`.

## Durations & Operational Notes

- monte_carlo 10k sims ~8s; all CLIs <10s; 20 validation games = minutes.
- Long runs: batch per opponent and set generous shell timeout (>=300000 ms).
- `actTimeout = 1s`/turn: agent losses with "timeout" status are harness
  failures, not strategy failures — check before blaming logic.
- Seed everything (env configuration={"seed": s}); one variable per sweep.

## Monte Carlo Shop Simulation

```
cd simulations/monte_carlo_shops
python run_simulation.py --simulations 10000 --scenarios all --seed 42 --output results/
python run_simulation.py --simulations 1000 --scenarios town_only --output results/quick_test/
```

## Price / Liquidation Engine

```
cd simulations/price_simulator
python cli.py --marginal-revenue --product MELON --quantity 50
python cli.py --recovery-time --product STRAWBERRY --dump-size 40 --shops 2
python cli.py --simulate-pvp --p0-order "SELL MELON 50" --p1-order "SELL MELON 10"
python cli.py --generate-all-plots --output results/plots/
python cli.py --liquidation-guide results/liquidation_guide.md
```

## Profitability Calculator

```
cd simulations/profitability_calculator
python cli.py --crop-roi --all-crops
python cli.py --animal-roi --include-fertilizer-sale
python cli.py --endgame-cutoffs
python cli.py --generate-report --output results/profitability_report.md
python cli.py --generate-all-plots results/plots
```

## Agent Validation Games

```python
from kaggle_environments import make
env = make("kaggriculture", configuration={"seed": <s>})
env.run([our_agent_callable_or_path, "random"])   # also "starter", "pass"
print(env.steps[-1][0].reward)                     # final money
```
Standard: 20 games (10 vs "random", 10 vs "starter"), fixed seeds.
Bundle first: `python build_submission.py --output dist/main.py` from `agent/`.
New sweep scripts go to `simulations/experiments/`; never modify engine or
agent code from this skill. Query big result JSONs via python one-liners,
not full reads.
