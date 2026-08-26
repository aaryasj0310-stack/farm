---
name: codebase-explorer
description: "Orient in this Kaggriculture repo: repo map, module inventory, where docs/simulations/agent/results/replays live, find files by purpose. Triggers on: explore the codebase, give me an overview, where is X, project layout, find the file that, which module handles."
---

# Codebase Explorer — Filesystem Orientation

Read-only discovery of WHAT lives WHERE. Structural/call-graph questions ->
`codebase-memory`. Running things -> `experiment-runner`.

## Repo Map

```
kaggri ox/
├── agent/                  # Phase C agent: config.py mirror, state|strategy|
│                           #   execution|market layers, build_submission.py, tests/
├── simulations/
│   ├── monte_carlo_shops/          # shop-unlock Monte Carlo (run_simulation.py)
│   ├── price_simulator/            # liquidation microstructure (cli.py)
│   └── profitability_calculator/   # crop/animal ROI (cli.py)
│       each: results/*.json|csv|plots/ + tests/
├── docs/                   # new rules.md, ARCHITECTURE.md, analysis_results.md,
│                           #   implicit_mechanics_catalog.md, knowledge/ store
├── replays/                # saved game outputs from validation runs
├── scripts/benchmark.py
├── AGENTS.md               # repo conventions
└── app/, frontend/         # UNRELATED ASR web app - exclude from competition work
```

## Ground Truth

- Engine source (authoritative, ~1.1k lines): `C:\Users\rohit\AppData\Local\
  \Programs\Python\Python312\Lib\site-packages\kaggle_environments\envs\
  kaggriculture\kaggriculture.py` (+ AGENTS.md, README.md, kaggriculture.json).
  Engine beats docs on any disagreement.
- Rules doc `docs/new rules.md` may LAG the installed engine — verify deltas.

## Anti-Token Rules

- NEVER full-read the engine: Grep `def _<name>` first, then ranged
  Read(offset, limit) around hits; cite line numbers.
- NEVER full-read `results/**/*.json` (up to ~150 KB). Query via
  `python -c "import json;d=json.load(open(r'<path>'));print(d['key'])"`.
- Scope searches to one package dir before repo-wide; skip `app/ frontend/ replays/`
  unless asked about them.

Output: paths + line refs + <=5-line summary. No edits.
