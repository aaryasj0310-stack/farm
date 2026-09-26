# Phase M0-L-B-R — Evidence Reconciliation Addendum

**Date:** September 2026  
**Reference Report:** `reports/phase_m0_l_b_r_reconciliation.md`  
**Branch:** `experiment/m0-l-b-r-oracle-integrity` / `release/phase-m0-l-c-soft-locality`  
**Purpose:** Preflight evidence corrections and methodological clarifications prior to Phase M0-L-C candidate freeze.

---

## 1. Summary of Corrections

This addendum records specific preflight corrections identified during audit review of the Phase M0-L-B-R report and reconciliation artifacts:

### 1.1 Treatment Final Cash Median Correction
- **Reported in preliminary draft:** \$113,462.00
- **Authoritative Verified Value from 100 Raw Records:** **\$112,797.00**
- **Control Final Cash Median:** \$108,802.00
- **Paired Delta Median:** **+\$4,660.00** (unchanged and preserved)
- **Mean Paired Lift:** **+\$4,883.33** (unchanged and preserved)

### 1.2 Baseline Parity Formal Assertion
Baseline parity between M0-L-B-R Control and the Phase M0-L-A census was re-verified with strict exact equality (`actual == expected`):
- All 100 expected scenario keys `(seed, opponent, seat)` across Seeds 97013–97022, 5 benchmark opponents, and 2 seats are present in both datasets.
- **Exact value equality:** **100 / 100 (100.0%)** exact float equality matches.
- Discrepancy count: **0**.

### 1.3 Animal Escape Instrumentation Distinction
- In previous test scripts, potential animal escapes were estimated pre-action at Hour 23 by checking `consecutive_unfed >= 1 and not fed_today`.
- For authoritative confirmation in Phase M0-L-C, animal escapes are measured strictly as **engine-confirmed post-transition state changes**: verifying at Day rollover (Hour 0) whether any tile with a previously active animal transitioned to a structure-only tile (`{"kind": "PASTURE"}` or `{"kind": "COOP"}`).
- Under this verified post-transition measurement, Treatment had **0 confirmed animal escapes** across all 100 matches in M0-L-B-R.

### 1.4 Emitted Actions vs Executed Operations Clarification
- In M0-L-B-R, unit commands were classified by emitted action type:
  - Directional commands (`NORTH`, `SOUTH`, `EAST`, `WEST`) $\to$ Emitted Moves (4,561.7 vs 4,763.1)
  - `PASS` commands $\to$ Emitted Idle
  - Non-movement commands (`WATER`, `HARVEST`, `PLANT`, `FEED`, `CARE`, etc.) $\to$ Emitted Productive Actions (2,303.3 vs 2,187.4)
- **Clarification:** The reported +\$42.13 per additional action (\$4,883.33 paired gain / +115.90 emitted non-movement actions) is a **descriptive accounting ratio**, not an established marginal causal value. Total terminal cash lift arises from the combined non-linear benefits of improved chore timeliness, avoided animal starvation, reduced harvest decay, and optimized drip selling.

---

## 2. Updated Authoritative M0-L-B-R Reference Table

| Metric | Baseline Control | Treatment (Soft Locality) | Paired Difference |
| :--- | :---: | :---: | :---: |
| **Panel Size** | 100 matched matches | 100 matched matches | **100 matched pairs** |
| **Mean Final Cash** | \$109,066.17 | \$113,949.50 | **+\$4,883.33** |
| **Median Final Cash** | \$108,802.00 | **\$112,797.00** | **+\$4,660.00** |
| **Standard Deviation** | \$9,346.07 | \$9,655.42 | \$7,879.89 |
| **Win / Loss / Tie Record** | — | — | **74W / 26L / 0T (74.0%)** |
| **95% Seed-Clustered CI** | — | — | **[+\$1,436.75, +\$8,329.91]** |
| **Confirmed Animal Escapes** | 2 | **0** | -2 escapes |
| **Max Market Orders / Turn** | 10 | 10 | 0 breaches |
| **Emitted Movement Overhead** | 64.47% (4,763.1 moves) | 61.79% (4,561.7 moves) | -2.68 pp (-201.3 moves) |
| **Emitted Productive Actions** | 29.61% (2,187.4 ops) | 31.20% (2,303.3 ops) | +1.59 pp (+115.9 ops) |
| **Descriptive Cash Ratio** | — | — | **\$42.13 / emitted op** |

All historical raw M0-L-B-R artifacts in `simulations/results/phase_m0_l_b_r_reconciliation/` remain preserved.
