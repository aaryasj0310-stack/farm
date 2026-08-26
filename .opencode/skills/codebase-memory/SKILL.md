---
name: codebase-memory
description: "Repo-specific knowledge-graph state for Kaggriculture: what is indexed, index freshness after changes, flat-import caveats, coverage checks before structural claims. Requires the MCP graph tools. Triggers on: index the repo, is it indexed, stale index, graph coverage, check_index_coverage, list_projects for this project."
---

# Codebase Memory — Repo Index State Only

Generic MCP tool syntax and evidence tiers are ALWAYS injected via AGENTS.md —
do not restate them here or in answers. File discovery -> `codebase-explorer`.

## Session Start (30 seconds)

1. `list_projects` -> is a kaggri-ox project indexed?
2. `index_status` -> note parse_partial/skipped files.
3. Missing/stale after significant edits? `index_repository` (fast mode
   suffices for structural work), then re-check status.

## Known Index Facts (re-verify each session)

- `simulations/monte_carlo_shops` was indexed historically.
- `agent/`, `price_simulator/`, `profitability_calculator/` likely NOT indexed
  yet — index before trusting graph results there.
- Flat-module layout (`from config import ...` sibling imports) => IMPORTS
  edges may be sparse; LSP-based CALLS edges still resolve.

## Coverage Discipline

After candidate paths exist: one `check_index_coverage` call with ALL cited
paths (+ scopes behind any negative/exhaustive claim). Clean result = no
RECORDED gap, never proof of completeness — read/grep reported missed ranges
before relying on the answer. State Scout/Verify/Auditor tier used.
