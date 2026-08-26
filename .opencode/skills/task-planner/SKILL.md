---
name: task-planner
description: "Plan and sequence multi-step Kaggriculture work before executing: decompose into ordered todos, pick the owning package (agent vs simulations), set definition-of-done. Triggers on: plan this, implement feature, multi-step task, what order, break down the work, phase C work."
---

# Task Planner — Sequencing Work

Produces ordered todos + DoD. Risk preview -> `impact-analysis`. Execution
commands -> `experiment-runner`. Gates -> `regression-checker`.

## Decomposition Template (todowrite, <=10 items)

1. **Verify engine behavior** — Grep + ranged-read the relevant
   `kaggriculture.py` functions; cite lines. Blocks everything else.
2. **Pick owning package** — gameplay/behavior -> `agent/`; market or
   economics analysis -> `simulations/*`. Docs/strategy notes -> `docs/`
   (knowledge store lives in `docs/knowledge/`).
3. **Implement** one layer at a time within `agent/`:
   config -> state -> strategy -> execution -> market.
4. **Unit tests** in that package's `tests/`, written with the code.
5. **Gates** — pytest suite (+ bundler smoke for `agent/`) via
   `regression-checker`.
6. **Tune last** — strategy parameters only after correctness gates pass;
   sweep via `experiment-runner` with seeds. Never edit tests to pass.

## Repo Constraints to Plan Around

- Engine mirrors: constant changes imply sync review (`impact-analysis`)
  across agent/config.py + 3 simulation packages.
- `actTimeout = 1s` per turn: keep per-turn agent computation cheap;
  heavy analysis belongs in offline sims, never in the agent loop.
- 720 steps/game: budget validation runs accordingly.

State which assumptions came from engine source vs docs vs inference.
