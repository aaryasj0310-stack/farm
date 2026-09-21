# Authoritative Production Baseline After P2.3 Promotion

## 1. Executive Summary
- **Promoted Treatment**: Point 2.3 Marginal Wheat Replanting / Terminal Wheat Guard
- **Status**: **PROMOTED TO PRODUCTION BASELINE**
- **Authoritative Commit**: Promoted on branch `experiment/sw-p13-planting-gate`
- **Predecessor Baseline**: `237cf5ee54498ed1ad2fa04d00ad9a0ebd27352e` (~$103,160/game)
- **New Validated Performance**: **~$103,605/game** (+$445.48 to +$451.50 mean paired delta over Pre-P2.3 Control)
- **Production Flag**: `P23_MARGINAL_WHEAT_ALLOCATION_ENABLED = True` (default in `agent/config.py`)
- **Canonical Artifact**: `dist/submission.zip` (synced, isolated 720-step verification passed)

---

## 2. Experimental Lineage & Dual Validation Record

The P2.3 treatment was subjected to dual matched-pair evaluations against the True Pre-P2.3 Production Control (`237cf5ee54498ed1ad2fa04d00ad9a0ebd27352e`, `QUADRANT_HARD_BLOCK={4}`).

### A. Discovery Validation (Seeds 88,001–88,050)
- **Sample**: 100 matched pairs (200 live games), 8 workers, 5 opponents (`pass`, `pure_wheat_rush`, `cow_milk_engine`, `melon_sniper`, `full_production_agent`)
- **Control Mean**: $103,159.65
- **P2.3 Mean**: $103,605.13
- **Paired Mean Delta**: **+$445.48/game**
- **Median Delta**: **+$435.50/game**
- **95% Confidence Interval**: [+$291.56, +$599.40]
- **Statistical Significance**: $t = 5.6728$, $p = 1.4051 \times 10^{-8}$
- **Record**: 70W / 27L / 3T (70.0% win rate)

### B. Independent Held-Out Promotion Validation (Seeds 89,001–89,050)
- **Sample**: 100 matched pairs (200 live games), fresh unseen seeds
- **Old Control Mean**: $101,467.43
- **Promoted Baseline Mean**: $101,918.93
- **Paired Mean Delta**: **+$451.50/game**
- **Median Delta**: **+$106.50/game**
- **95% Confidence Interval**: [+$213.63, +$689.37]
- **Statistical Significance**: $t = 3.7659$, $p = 2.8179 \times 10^{-4}$
- **Record**: 60W / 38L / 2T (60.0% win rate)

Both independent suites independently confirmed a statistically significant ~+$450/game improvement with 95% confidence intervals strictly positive and bounded away from zero.

---

## 3. Validated Causal Mechanism & Telemetry Breakdown

### Telemetry Comparison Across 200 Held-Out Games
| Metric | Pre-P2.3 Control | Promoted Production | Delta / Impact |
| :--- | :--- | :--- | :--- |
| **Wheat Tiles Planted** | 108.1 tiles | 102.2 tiles | **-5.9 tiles** |
| **Carrot Tiles Planted** | 25.5 tiles | 27.4 tiles | **+1.9 tiles** |
| **Wheat Fed to Herd** | 211.8 units | 211.8 units | **+0.0 units (Exact 0 Impact)** |
| **Wheat Buy Spend** | $0.00 | $0.00 | $0.00 |
| **Solvency Regressions** | 0 | 0 | None (0 negative cash steps) |
| **Animal Starvation Days (EOD)** | 1,556 | 1,555 | -1 (Strictly 0 animal escapes) |

### The Causal Mechanism
1. **The Terminal Maturation Boundary**: Wheat requires 4 full days to mature (`plant_day + 4`). Wheat planted on Day 26 or later matures on Day 30+, after the 720-step season ends, resulting in complete write-off of seed cost ($10/tile) and opportunity cost of land.
2. **Endgame Crop Substitution**: By setting `wheat_to_plant = 0` on Day 26+ (`if day > 25`), empty tiles in the NW+NE quadrants are immediately yielded to the downstream general crop planner. The planner plants fast-maturing crops (primarily Carrots, 2-day maturation), allowing them to mature and be harvested on Days 28–29 before final liquidation.
3. **Strict Feed Security Preservation**: On Days 0–25, continuous wheat replanting is maintained without interference. As proven by telemetry, the herd consumed exactly 211.8 units of wheat in both Control and Treatment, maintaining 100% feed self-sufficiency without requiring market purchases.

---

## 4. Authoritative Configuration State

All production configuration invariants remain strictly enforced in `agent/config.py`:

```python
# Core 2-Quadrant Policy
QUADRANT_HARD_BLOCK = {4}  # NW + NE active, SE blocked, SW strictly blocked

# P2.3 Marginal Wheat Replanting (PROMOTED)
P23_MARGINAL_WHEAT_ALLOCATION_ENABLED = True

# Prior Rejected Experiments (Frozen to False)
P20_SECOND_MELON_TRANCHE_ENABLED = False
P21_DYNAMIC_STRAWBERRY_ALLOCATION_ENABLED = False
P22A_DAY28_FEED_HARMONIZATION_ENABLED = False

# All SW Expansion Flags (Frozen to False / Production Mode)
SW_OWNERSHIP_MODE = "production"
SW_TIMING_PRIOR_ENABLED = False
SW_ACTIVATION_MODE = "production"
STRATEGIC_SW_OWNERSHIP_ENABLED = False
DYNAMIC_ZONAL_ALLOCATION = False
DYNAMIC_SW_CROPS_ENABLED = False
PERSISTENT_WORKER_LOCALITY_ENABLED = False
SW_CELL_HOUSING_ENABLED = False
SW_P1_PURCHASE_COMMITTED_HERD_ONLY = False
SW_WORKLOAD_RESPONSIVE_SCHEDULER_ENABLED = False
SW_SERVICEABILITY_AWARE_ACTIVATION_ENABLED = False
SW_GENERIC_PLANTING_GATE_ENABLED = False
P13_TIGHT_SOIL_ENABLED = False
P13_LIVESTOCK_CAP_ENABLED = False
```

---

## 5. Verification Checklist
- [x] Pre-P2.3 control commit confirmed (`237cf5ee54498ed1ad2fa04d00ad9a0ebd27352e`).
- [x] Production switch defaulted to `True` in `agent/config.py`.
- [x] All 7 P2.3 unit tests passing in `agent/tests/test_p23_marginal_wheat_isolation.py`.
- [x] 1,021 tests passing across full agent test suite.
- [x] Package build script (`scripts/build_submission.py`) generated valid `dist/submission.zip`.
- [x] `test_submission_package.py` verified 720-step isolated match execution ($109,749.00 score).
- [x] 100-pair held-out validation completed on fresh seeds 89,001–89,050 with positive paired delta (+451.50/game, $p < 0.0003$).
