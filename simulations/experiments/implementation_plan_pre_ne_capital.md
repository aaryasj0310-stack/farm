# Implementation Plan: Point-2 Pre-NE Capital Admission Policy

## Objective
Implement and empirically validate the Pre-NE Capital Admission Policy (`POINT2_PRE_NE_CAPITAL_MODE`) across 200 held-out seed/opponent conditions (800 matches total) comparing:
- **Arm A (Shadow Control)**: `shadow / none / Late1 OFF / pre-NE off`
- **Arm B (Current Rejected Live Baseline)**: `live / ArmE / Late1 ON / pre-NE off`
- **Arm C (NE-first Live)**: `live / ArmE / Late1 ON / pre-NE ne_first`
- **Arm D (NE-escrow Live)**: `live / ArmE / Late1 ON / pre-NE ne_escrow`

## 1. Config Specification
In `agent/config.py` (and mirrored in `submission/config.py`):
```python
POINT2_PRE_NE_CAPITAL_MODE = "off"  # Supported: "off", "ne_first", "ne_escrow"

def get_point2_pre_ne_capital_mode() -> str:
    global POINT2_PRE_NE_CAPITAL_MODE
    return POINT2_PRE_NE_CAPITAL_MODE
```
Production defaults remain strictly:
`POINT2_PRE_NE_CAPITAL_MODE = "off"`
`POINT2_FEED_MODE = "shadow"`
`BOOTSTRAP_LIVESTOCK_ARM = "none"`
`ONE_AT_A_TIME_LATE_HOUSING_ENABLED = False`

## 2. Policy Mechanics
- **`ne_first`**:
  - While `"NE" not in farm.unlocked`: livestock candidate admission = 0.
  - Zero preparatory structure demand (no extra pastures/coops, no BUILD intent for deferred candidates).
  - Existing-herd feeding/survival is completely unaffected.
  - As soon as `"NE" in farm.unlocked`, normal Live candidate evaluation resumes from the current observation (no automatic replay of missed Day 0 sequence).
- **`ne_escrow`**:
  - While `"NE" not in farm.unlocked`: livestock may only use genuine surplus above protected NE capital.
  - NE land hold = `$1,000` (counted ONCE, never double-counted with other land reserves).
  - Sequential candidate envelope:
    `candidate_package_cost = purchase_cost + candidate_incremental_feed_cash_hold` (from `cand_res.candidate_feed_cash_hold`).
    If `candidate_package_cost <= remaining_envelope`: candidate accepted, envelope decremented.
    If `candidate_package_cost > remaining_envelope`: candidate deferred for NE (`reason = "ne_capital_deferred"`), zero feed committed, zero housing consumed.
  - Deferred candidates do NOT inflate target herd or structure queue.
  - As soon as `"NE" in farm.unlocked`, envelope restriction ends.

## 3. Component Updates
1. `agent/config.py` & `submission/config.py`: Add `POINT2_PRE_NE_CAPITAL_MODE` and getter.
2. `agent/strategy/herd_planner.py` & `submission/strategy/herd_planner.py`:
   - In `generate_dynamic_herd_plan`, accept `pre_ne_capital_mode`, `ne_locked`, `pre_ne_livestock_envelope`.
   - In Day 0 bootstrap loop: apply pre-NE capital check before admitting each candidate.
   - In Day > 0 dynamic loop: apply pre-NE capital check before admitting each candidate.
   - Expose diagnostics: `pre_ne_capital_mode`, `ne_locked`, `ne_land_hold`, `nonlivestock_holds`, `livestock_envelope_before`, `livestock_envelope_after`, `candidate_package_cost`, `candidate_deferred_for_ne`.
3. `agent/strategy/macro_planner.py` & `submission/strategy/macro_planner.py`:
   - Compute `ne_locked = bool("NE" not in farm.unlocked)`.
   - If `pre_ne_mode in ("ne_first", "ne_escrow")` and `ne_locked`:
     Calculate `pre_ne_nonlivestock_holds`, `ne_land_hold = 1000.0`, `pre_ne_livestock_envelope`.
     Pass into `generate_dynamic_herd_plan`.
     Ensure `target_pastures` and `reserved_structure_tiles` do not queue structures for deferred candidates.
     Expose diagnostics in `plan.diagnostics["pre_ne_capital"]`.
4. `agent/market/order_builder.py` & `submission/market/order_builder.py`:
   - During C2B sequential replay: independently enforce pre-NE capital gate.
   - For each candidate: calculate `candidate_package_cost = purchase_cost + float(cand_res.candidate_feed_cash_hold)`.
   - If exceeds remaining envelope: reject with `reason = "ne_capital_deferred"`, do not commit feed, do not consume housing.
5. Unit Tests:
   - `agent/tests/test_pre_ne_capital_policy.py`:
     - Test `mode == "off"` changes nothing.
     - Test `mode == "ne_first"` suppresses Day 0 livestock and preparatory structures; resumes after NE.
     - Test `mode == "ne_escrow"` counts $1,000 hold once, evaluates sequential package, rejects when envelope exhausted, leaves feed/housing uncommitted.
     - Test deferred candidates are not automatically replayed after NE.
     - Test OrderBuilder final enforcement matches Macro intent.
   - Run full regression suite (`pytest agent/tests/ -q -m "not slow"`, C2C tests, Late1 tests, submission tests).

## 4. Experiment Runner & Analyzer
- `simulations/experiments/run_pre_ne_capital_experiment.py`:
  - Runs all 4 arms (A, B, C, D) across the 200 held-out seeds (800 matches total).
  - Telemetry captures:
    - Score, NE purchase (day, hour), first NE planting (day, hour), first NE harvest (day, hour).
    - Herd: Day 0, at NE purchase, Day 10, Day 12, final.
    - Crop revenue through Day 10, full crop revenue.
    - Milk, wool, fertilizer revenue.
    - Cash: Day 1, 3, 5, immediately before NE, immediately after NE, Day 10, Day 12.
    - Livestock candidates requested, admitted, deferred_for_ne, admitted post-NE, rejected post-NE.
    - Candidate package cost, NE envelope before/after.
    - Wheat bought, wheat spend, feed actions.
    - Pastures built, unused pastures.
    - All 11 hard safety invariants.
- `simulations/experiments/analyze_pre_ne_capital_experiment.py`:
  - Computes all required aggregate tables, paired statistics (C vs B, D vs B, D vs C, C vs A, D vs A), Q1-Q7 answers, escrow admission distributions, recovery fractions, and concludes with the required terminal phrase.
