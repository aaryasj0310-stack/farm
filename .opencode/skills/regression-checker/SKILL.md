---
name: regression-checker
description: "Verify nothing broke after Kaggressive code changes: per-package pytest suites, submission bundler smoke test, 20-game agent validation gates (100% win, >$35k avg). Triggers on: check regressions, did anything break, run the tests, pre-submit checks, validate before submit, green build."
---

# Regression Checker — Post-Change Gates

Run after edits; complements `experiment-runner` (produces data) and
`task-planner` (DoD). Fix forward — never weaken tests to pass.
Gates marked "(when present)" apply once those files exist in `agent/`.

## Gate 1: Unit Suites (per touched package)

```
cd simulations\monte_carlo_shops        && python -m pytest tests -q
cd simulations\price_simulator          && python -m pytest tests -q
cd simulations\profitability_calculator && python -m pytest tests -q
cd agent                                && python -m pytest tests -q   (when present)
```
All green required. Baseline counts at creation: 23 / 34 / 30 — use as drift
signal only, not permanent truth.

## Gate 2: Bundler + Import Smoke (agent changes, when present)

```
cd agent && python build_submission.py --output dist/main.py
python -m py_compile dist\main.py
```
Then assert NO sibling-import lines survived bundling:
`Select-String -Path dist\main.py -Pattern '^\s*(from|import) (config|observation_parser|state_tracker|opponent_model|pathfinding|unit_controller|task_scheduler|hiring_manager|shop_adapter|macro_planner|endgame_liquidator|price_math|order_builder|market_brain)\b'`
-> must return nothing. Optional runtime check via runpy on a stub obs.

## Gate 3: Validation Games (agent behavior changes)

20 games via `experiment-runner`. PASS requires ALL:
- 100% win rate vs both "random" and "starter"
- average final money > $35,000
- zero agent exceptions; timeout-status games = harness failure, re-run

## Gate 4: Artifact Freshness

Constants or sim logic changed? Regenerate stale `results/` via
`experiment-runner` before trusting them; JSONs re-serialize without NaN;
plots exist under each `results/plots/`.

Report: gate -> PASS/FAIL -> evidence (counts, scores). Any red blocks submit.
