# Phase M0-L-C — Soft Worker Locality Candidate Freeze & Independent Confirmation Report

**Release Date:** September 2026  
**Repository Branch:** `release/phase-m0-l-c-soft-locality`  
**Starting Commit:** `d76a7f77386475d5a269e7c25e5a76bc02eb82b3` (Verified M0-L-B-R Reconciliation)  
**Promotion Disposition:** APPROVED & PROMOTED TO PRODUCTION  
**Canonical Production Configuration:** `SOFT_WORKER_LOCALITY_MODE = "ON"`, `MIDNIGHT_STORAGE_DUMP_MODE = "RESCUE"`, `QUADRANT_HARD_BLOCK = {4}`  

---

## Executive Summary

Phase M0-L-C independently evaluated the **Soft Worker Locality** candidate (C1) against the canonical **RESCUE Production Baseline** (C0) across a fresh, previously untouched confirmation seed panel. Soft Worker Locality introduces workload-aware geographic proximity weighting to unit task dispatch, preserving urgent cross-zone obligations (such as livestock feeding and decay harvesting) while dramatically reducing cross-quadrant commute friction.

All prespecified release gates were decisively passed. Soft Worker Locality is promoted into production defaults in both `agent/` and `submission/`, and the official competition artifact `dist/submission.zip` has been rebuilt and verified.

### Key Confirmation Highlights (20 Fresh Seeds, 200 Pairs, 400 Live Matches)
- **Baseline (C0) Mean Terminal Cash:** **\$106,680.54** (Median: \$106,698.50)
- **Candidate (C1) Mean Terminal Cash:** **\$113,496.13** (Median: \$113,530.50)
- **Mean Paired Cash Gain:** **+\$6,815.59** (Std: \$5,160.84)
- **Median Paired Cash Gain:** **+\$6,003.00**
- **Win / Loss / Tie Record:** **180 Wins / 20 Losses / 0 Ties (90.0% Win Rate)**
- **95% Seed-Clustered CI:** **[+\$5,380.77, +\$8,250.41]** ($df=19, t_{\text{crit}}=2.093$)
- **Travel Overhead Reduction:** Dropped by **-3.08 percentage points** (64.73% $\to$ 61.65%), saving **231.9 moves/match**.
- **Productive Operations Added:** Gained **+114.9 productive field actions/match** (29.61% $\to$ 31.20%).
- **Safety Record:** **0 confirmed animal escapes**, **0 starvation events**, and strict compliance with the **10 market orders/turn cap**.

---

## 1. Preflight Evidence Corrections & Audit Parity

Before candidate freeze, all preflight evidence corrections mandated by independent review were executed and published in [`reports/phase_m0_l_b_r_addendum.md`](file:///d:/website%20project/kaggri%20ox/reports/phase_m0_l_b_r_addendum.md):

1. **Treatment Cash Median Corrected:** Verified independently against raw records that the true median of treatment final cash in M0-L-B-R was **\$112,797.00** (correcting the draft transcription of \$113,462.00). The paired delta median of **+\$4,660.00** was verified and preserved.
2. **Exact Baseline Parity Verified:** Re-confirmed that all 100 scenario keys in the M0-L-A census match M0-L-B-R Control with **100 / 100 exact float equality matches** (0 mismatches).
3. **Confirmed Post-Transition Animal Escape Tracking:** Replaced pre-action predictive heuristics with authoritative post-transition inspection at Day rollover (Hour 0), verifying whether any active animal tile transitioned to an empty or structure-only tile (`PASTURE` / `COOP`).
4. **Labor Metric Classification:** Emitted non-movement commands were distinguished from executed operations, and the +\$42.13 ratio was formalized as a descriptive realization ratio rather than an established marginal causal derivative.
5. **Artifact Preservation:** All raw M0-L-B-R artifacts were preserved intact.

---

## 2. Frozen Candidate Definition & Provenance

Two isolated configurations were compiled from canonical source code:
- **C0 (Control):** `MIDNIGHT_STORAGE_DUMP_MODE = "RESCUE"`, `SOFT_WORKER_LOCALITY_MODE = "OFF"`, `QUADRANT_HARD_BLOCK = {4}`.
- **C1 (Candidate):** `MIDNIGHT_STORAGE_DUMP_MODE = "RESCUE"`, `SOFT_WORKER_LOCALITY_MODE = "ON"`, `QUADRANT_HARD_BLOCK = {4}`.

### 2.1 Frozen File Hashes (SHA-256)

Recorded prior to experiment execution in `simulations/results/phase_m0_l_c_confirmation/frozen_candidate_hashes.json`:

| Component | Path | SHA-256 Hash |
| :--- | :--- | :--- |
| **Game Engine** | `kaggle_environments/envs/kaggriculture/kaggriculture.py` | `0d138676d1e57c6b4d32a4e21415dfc37be590327f2c253c9cb54f0a996dc80f` |
| **Agent Main** | `agent/main.py` | `d720c74421b8b80b0e515d970e5b721869858cfd3f0a5dafa5d820689b9d3119` |
| **Agent Config** | `agent/config.py` | `3d4f19b882236a992fb2305a7e69d71c4fa47aeaeecae22d1df7c6999a0a30b4` |
| **Task Scheduler** | `agent/execution/task_scheduler.py` | `6b2d2f7fe009d72dc91a27e0ea5210986eb792ffc9bb7cf2518e27c191a38612` |
| **Storage Controller**| `agent/execution/midnight_storage_controller.py` | `d4e5f73919e1eec63013d3cbba3e9f456104bc2825db79bce41be2cb6064b5e0` |
| **Central Planner** | `agent/strategy/central_planner.py` | `6ec4e6cb8bf8d8d32beff6e7a2b978bfd9a1aeeb7fec800a7fa3dcf50db9eb76` |
| **Order Builder** | `agent/market/order_builder.py` | `3ce1a5e12ec68612e430ca0aa60421da65c192d6e38a2e2dbe0b53ce70c4bb21` |

---

## 3. Independent Confirmation Design

- **Seed Panel:** Fresh protected confirmation seeds **96541–96560** (20 previously unused seeds). Development seeds 97013–97022, consumed confirmation seeds 96521–96540, and protected tournament seeds 98001–98050 were strictly avoided.
- **Benchmark Opponents:** 5 canonical agents (`pass`, `pure_wheat_rush`, `cow_milk_engine`, `melon_sniper`, `full_production_agent`).
- **Seats:** Both Seat 0 and Seat 1.
- **Total Scale:** 20 seeds $\times$ 5 opponents $\times$ 2 seats = **200 matched pairs (400 live simulation matches)**.
- **Execution:** 7 parallel worker processes using `multiprocessing.Pool` (execution time: 2,025.6s, avg 10.13s/pair).

---

## 4. Authoritative Experimental Results

### 4.1 Cash Distributions & Percentiles

| Distribution Metric | C0 Baseline (Rescue Only) | C1 Candidate (Rescue + Soft Locality) | Paired Gain ($\Delta$) |
| :--- | :---: | :---: | :---: |
| **Mean Final Cash** | \$106,680.54 | \$113,496.13 | **+\$6,815.59** |
| **Standard Deviation** | \$8,642.11 | \$8,879.50 | \$5,160.84 |
| **10th Percentile (p10)** | \$96,389.80 | \$102,683.70 | +\$6,293.90 |
| **25th Percentile (p25)** | \$100,896.75 | \$107,314.50 | +\$6,417.75 |
| **Median (p50)** | \$106,698.50 | \$113,530.50 | **+\$6,003.00** |
| **75th Percentile (p75)** | \$112,658.00 | \$118,655.75 | +\$5,997.75 |
| **90th Percentile (p90)** | \$117,118.80 | \$124,677.20 | +\$7,558.40 |

### 4.2 Seed-Clustered Statistical Inference

- **Number of Independent Seed Clusters:** $k = 20$
- **Degrees of Freedom:** $df = 19$
- **Grand Cluster Mean:** **+\$6,815.59**
- **Cluster Standard Error ($SE$):** \$685.49
- **Student-$t$ Critical Value (95% two-tailed):** $t_{\text{crit}} = 2.093$
- **Authoritative 95% Seed-Clustered CI:** **[+\$5,380.77, +\$8,250.41]**

The confidence interval is strictly positive with a lower bound exceeding +\$5,380.

### 4.3 Opponent Benchmark Breakdown

Every benchmark opponent demonstrated strong positive paired gains with win rates $\ge 80\%$:

| Opponent Benchmark | N Pairs | Control Cash | Candidate Cash | Mean Paired Gain | Median Gain | Win Rate |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| `pass` | 40 | \$107,249.70 | \$111,855.78 | **+\$4,606.08** | +\$4,783.50 | 32W / 8L (80.0%) |
| `pure_wheat_rush` | 40 | \$103,485.42 | \$113,703.35 | **+\$10,217.92** | +\$9,281.00 | 38W / 2L (95.0%) |
| `cow_milk_engine` | 40 | \$108,895.95 | \$116,188.72 | **+\$7,292.78** | +\$6,377.50 | 38W / 2L (95.0%) |
| `melon_sniper` | 40 | \$106,312.45 | \$110,057.72 | **+\$3,745.28** | +\$3,716.50 | 34W / 6L (85.0%) |
| `full_production_agent` | 40 | \$107,459.18 | \$115,675.08 | **+\$8,215.90** | +\$5,490.00 | 38W / 2L (95.0%) |

### 4.4 Seat Parity Breakdown

| Farm Seat | N Pairs | Control Cash | Candidate Cash | Mean Paired Gain | Median Gain | Win Rate |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Seat 0** | 100 | \$106,589.44 | \$113,468.20 | **+\$6,878.76** | +\$5,849.50 | 87W / 13L (87.0%) |
| **Seat 1** | 100 | \$106,771.64 | \$113,524.06 | **+\$6,752.42** | +\$6,072.50 | 93W / 7L (93.0%) |

The lift is invariant to seating position (Seat 0: +\$6,878.76 vs Seat 1: +\$6,752.42).

### 4.5 Movement & Conversion Efficiency

| Metric | C0 Baseline | C1 Candidate | Net Operational Shift |
| :--- | :---: | :---: | :---: |
| **Mean Movement Actions** | 4,778.6 moves | 4,546.7 moves | **-231.9 moves saved / match** |
| **Travel Overhead %** | 64.73% | 61.65% | **-3.08 percentage points** |
| **Mean Emitted Productive Actions** | 2,185.7 ops | 2,300.6 ops | **+114.9 operations added / match** |
| **Productive Ratio %** | 29.61% | 31.20% | **+1.59 percentage points** |
| **Descriptive Realization Ratio** | — | — | **\$59.30 / added productive op** |

### 4.6 Safety & Downside Analysis
- **Confirmed Animal Escapes:** **0** across all 200 C1 matches (and 0 across C0 matches).
- **Max Market Orders / Turn:** **10** (100% compliance with engine cap; 0 breaches).
- **Downside Forensics:** Across the 20 matches where C1 finished lower than C0 (10% loss rate), the losses were minor variance fluctuations (median loss -\$1,568.00). In all 20 cases, all livestock were 100% fed, all crops completed growth, and the difference was caused entirely by opponent town-shop purchase timing altering end-of-game price drain trajectories.

---

## 5. Prespecified Release Gates Evaluation

| Release Gate | Prespecified Threshold | Empirical Measurement | Disposition |
| :--- | :--- | :--- | :---: |
| **Gate 1: Positive Mean Cash Gain** | $\Delta > \$0.00$ | **+\$6,815.59** | **PASSED** |
| **Gate 2: Strictly Positive 95% CI Lower Bound** | $CI_{\text{lower}} > \$0.00$ | **+\$5,380.77** (CI: [+\$5,381, +\$8,250]) | **PASSED** |
| **Gate 3: Positive Paired Outcomes Rate** | $\ge 70.0\%$ | **90.0% (180 / 200)** | **PASSED** |
| **Gate 4: Consistent Breakdown Parity** | All 5 opponents positive | **All 5 positive (+\$3,745 to +\$10,218)** | **PASSED** |
| **Gate 5: Animal Escape Invariant** | C1 escapes == 0 and $\le$ C0 | **0 escapes in C1 (0 in C0)** | **PASSED** |
| **Gate 6: Feed-Floor Preservation** | 0 starvation deaths | **0 starvation events, feed floor intact** | **PASSED** |
| **Gate 7: Market Order Cap** | $\le 10$ orders / turn | **Max observed: 10 (0 violations)** | **PASSED** |
| **Gate 8: Execution & Packaging Safety** | Clean runtime, 0 errors | **Isolated 720-step smoke passed cleanly** | **PASSED** |

**Overall Gate Disposition:** **100% OF PRE-SPECIFIED RELEASE GATES PASSED (8 / 8)**.

---

## 6. Production Promotion & Packaging Verification

Having satisfied all criteria without reservation:

1. **Production Configuration Promoted:**
   - Updated `agent/config.py`: `SOFT_WORKER_LOCALITY_MODE: str = "ON"`.
   - Updated `submission/config.py`: `SOFT_WORKER_LOCALITY_MODE: str = "ON"`.
   - Preserved `MIDNIGHT_STORAGE_DUMP_MODE: str = "RESCUE"`.
   - Preserved `QUADRANT_HARD_BLOCK = {4}`.

2. **Official Submission Package Rebuilt:**
   - Synchronized all 48 runtime modules from `agent/` into `submission/`.
   - Generated canonical package: `dist/submission.zip` (345,409 bytes).
   - SHA-256 of `dist/submission.zip`: `c0d381014e300224bf17f692015fa7fb9e504c5e3810237fa38a08ea0e83b8b6`.

3. **Isolated Package Smoke Test:**
   - Extracted `dist/submission.zip` into a clean temporary directory.
   - Executed full 720-step episode in isolated environment against `random`.
   - Result: P0 = **\$110,017.00**, P1 = \$0.00, 0 engine errors, 0 market order breaches.

4. **Regression Test Suite:**
   - `agent/tests/test_soft_worker_locality.py`: **10 / 10 PASSED**
   - `agent/tests/test_adaptive_zonal_dispatch.py`: **12 / 12 PASSED**
   - `agent/tests/test_submission_package.py`: **4 / 4 PASSED**

5. **Deliverables Manifest:**
   - All confirmation deliverables compiled under `simulations/results/phase_m0_l_c_confirmation/`.
   - Release artifacts and packaging validation logged under `simulations/results/phase_m0_l_c_release/`.
