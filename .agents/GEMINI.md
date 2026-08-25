# Kaggriculture Competition Project

This workspace contains a Kaggle competition project for **Kaggriculture** — a two-player farming simulation where agents compete to earn the most coins over a 30-day season.

## Project Structure

- `docs/` — Competition rules, analysis, implicit mechanics catalog, strategies
- `docs/knowledge/` — Persistent knowledge base (facts, hypotheses, experiments, lessons)
- `simulations/monte_carlo_shops/` — Monte Carlo town shop demand simulation (10k runs)
- `simulations/experiments/` — Strategy testing experiment scripts
- `app/` — Existing application code (unrelated to agent)

## Key Files

- `docs/new rules.md` — Official competition rules
- `docs/AGENTS (1).md` — Agent API, observation format, action format
- `docs/implicit_mechanics_catalog.md` — 40+ non-obvious mechanics and edge cases
- `docs/analysis_results.md` — Crop/animal economics, market dynamics analysis
- Game engine source (ground truth): `C:\Users\rohit\AppData\Local\Programs\Python\Python312\Lib\site-packages\kaggle_environments\envs\kaggriculture\kaggriculture.py`

## Subagents

This project uses 7 specialized subagents for development. When working on Kaggriculture tasks, activate the `kaggriculture-subagents` skill to define them for the current conversation.
