---
name: impact-analysis
description: "Map blast radius before editing Kaggriculture code: engine-mirror sync risks, duplicated price math and constants across packages, which tests/sims/docs a change touches. Triggers on: impact of changing, what breaks if, blast radius, safe to change, mirror sync, engine was updated."
---

# Impact Analysis — Pre-Edit Blast Radius

Run BEFORE touching shared/duplicated logic. Produces a checklist only;
edits happen after, gates via `regression-checker`.

## Duplication Map (the known hazards)

Price curve + game constants are mirrored in 4 places + the installed engine.
Any constant change means checking every row:

| Logic | Copies |
|---|---|
| CROPS / ANIMALS tables | `agent/config.py`, engine `kaggriculture.py` |
| MARKET_PARAMS + price curve | `agent/market/price_math.py`, `simulations/monte_carlo_shops/price_function.py`, `simulations/price_simulator/price_curve_engine.py`, engine |
| SHOP demand table | `agent/config.py` (SHOPS), `monte_carlo_shops/town_demand_engine.py`, `price_simulator/recovery_simulator.py` |
| Growth/yield economics | `agent/config.py`, `profitability_calculator/crop_model.py` (own CROPS dict) |

Engine updated? Diff engine constants against ALL mirrors first. Past deltas
to watch: farm-before-market ordering (no same-turn BUY_SEED+PLANT; hired
hands act T+1), goose CARE profitable, melon harvest gated by
first_yield_day=10, decay every 2nd global step from (planted+max_day+1)*24.

## Procedure (4 steps)

1. Grep the symbol across `agent/ simulations/` -> candidate files (skip
   `app/ frontend replays results docs`).
2. Callers: graph `trace_path(inbound)` / `detect_changes` when indexed,
   else Grep.
3. Classify each hit: must-update / verify-only / unaffected. Tests encoding
   expected numbers are guards — they SHOULD break on real changes.
4. Output checklist rows: file -> change -> verified-by (which pytest suite /
   gate). For behavior changes add: diff pre/post validation distributions
   from `replays/`.
