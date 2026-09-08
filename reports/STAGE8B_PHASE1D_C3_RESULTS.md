# STAGE 8B PHASE 1D — C3 PHASED MELON STRATEGY RESULTS

**Authoritative Baseline**: `B2-C5 = commit 79fad9e` (B1 + C5 Optimal Maturity & Bonus-Window Harvesting)  
**Experiment**: Isolated Counter-Policy C3 — Phased Melon Strategy  
**Comparison**: `B2-C5 → B2-C5 + C3`  
**Evaluation Date**: September 8, 2026  
**Result**: **REJECT (B2-C5 Remains Authoritative Baseline)**

---

## 1. Executive Summary

In Stage 8B Phase 1D, counter-policy **C3 (Phased Melon Strategy)** was implemented and rigorously evaluated as an isolated policy modification on top of the established **B2-C5** production baseline (`commit 79fad9e`).

The core hypothesis from prior Dusta research was that controlled, phased melon planting across Phase 2 (Days 3–9) and Phase 3 (Days 10–17) would capture high melon margins and improve terminal wealth (+$1,192.50 in Dusta Stage 8A).

However, rigorous empirical benchmarking on the production architecture demonstrates that **C3 causes substantial economic degradation across both canonical isolated benchmarks and bilateral head-to-head matches**:

1. **Canonical 5-Seed Paired Benchmark**:
   - Baseline Wealth (B2-C5): **$36,946.20**
   - Candidate Wealth (B2-C5 + C3): **$33,543.20**
   - Mean Delta: **-$3,403.00 (-9.21%)**
   - Improved Seeds: **1 / 5 (20.0%)** (Seed 202: +$744.00)
   - Worsened Seeds: **4 / 5 (80.0%)** (Seed 101: -$8,118.00; Seed 303: -$4,340.00; Seed 404: -$4,522.00; Seed 505: -$779.00)
2. **Head-to-Head Tournament (6 Matches vs B1 `submission.py`)**:
   - Our Agent (C3): **0 wins / 6 matches (0.0% win rate)**, Avg Score **$21,975.50**
   - Opponent Agent: **6 wins / 6 matches (100.0% win rate)**, Avg Score **$24,963.00**
   - Net Margin: **-$2,987.50/match**
   - *Context*: Without C3, baseline B2-C5 achieved an **83.3% win rate (5/6 wins)** against this identical opponent!
3. **Forensic Root Cause Discovered**:
   - **Baseline Monoculture vs Production Reality**: Dusta's Stage 8A synthetic baseline suffered from a low-melon monoculture (only 6.83% melon allocation). In stark contrast, our production agent *already* possessed the Leader-Calibrated Day-0 NW Melon Springboard (12 melons on Day 0) and opportunistic Phase 2b fill planting, which *already* produced 83 to 102 units of Melon per match (generating $18,000 to $24,000 in melon revenue) and operated near the physical town market ceiling (`MELON_SEASON_SALE_CAP = 150`).
   - **Severe Strawberry Crowding**: Forcing phased melon targets on Days 12–15 occupied prime NE soil tiles for 10 continuous days, crowding out high-yielding Strawberry waves. On Seed 101, Strawberry plantings dropped from 18 to 11 tiles, and realized strawberry produce sales collapsed by **-72.2% (54 units -> 15 units)**.
   - **Early Working Capital Starvation**: Purchasing extra melon seeds ($80 each) during Days 3–9 drained liquid treasury during the critical capital-formation window required for NE expansion, livestock acquisitions (Cows $400, Sheep $500), and SW land accumulation.

Per the experimental guidelines: *"A mixed result must be reported honestly. If C3 is negative: REJECT C3. Do not attempt to rescue it by simultaneously changing C2 or C6. B2-C5 remains authoritative."*

**DECISION: REJECT C3.** The production baseline remains **B2-C5**.

---

## 2. Baseline Definition

The authoritative baseline for this experiment is:
- **Identifier**: `B2-C5`
- **Git Commit**: `79fad9ecc2b73eecce2a34a38277fb0eae327d79`
- **Branch**: `v5.12-sw-utilization`
- **Composition**:
  - `B0`: Preflight baseline with SW utilization and Leader-calibrated Day-0 springboard.
  - `C4`: Late-Game Livestock Investment Cap (cutoff at Day 12/14, pasture caps, animal ROI feasibility guards).
  - `C5`: Optimal Maturity / Bonus-Window Harvesting (deferred harvest until bonus watering on max day, decay safety, endgame liquidation).
- **Strict Exclusions**:
  - `C1` (Dynamic Capacity Hiring): Evaluated in Phase 1B, failed (-$1,528.60), and strictly excluded.
  - `C2` (Zonal Dispatch) and `C6` (Dynamic Selling): Unimplemented and inactive.

---

## 3. Baseline Integrity Check

Prior to benchmarking C3, repository integrity was strictly verified:
1. `git log -1 --oneline` confirmed HEAD at `79fad9e` (`checkpoint: B2-C5 baseline`).
2. The entire existing unit test suite (373 tests) passed cleanly in 28.26s (`pytest agent/tests/`).
3. Baseline canonical 5-seed validation via `scripts/run_v511_validation.py` achieved $36,946.20 average wealth with 0 engine violations and Day 12 SW unlock across all 5 seeds.
4. C4 livestock guards and C5 maturity-window logic were verified 100% active and functional.

---

## 4. Exact C3 Implementation

Counter-policy C3 was implemented as a structured, phased melon planning engine within `agent/strategy/macro_planner.py` and `agent/config.py`:

### Config Parameters (`agent/config.py`)
```python
C3_PHASE2_MELON_TARGET = 4          # Active melon plots targeted in Phase 2 (Days 3-9)
C3_PHASE3_MELON_TARGET = 6          # Active melon plots targeted in Phase 3 (Days 10-17)
C3_MELON_PRICE_FLOOR = 60.0         # Minimum expected price at harvest to warrant Melon vs staples

def get_melon_cap(day):
    if day == 0:
        return PHASE1_MELON_TILES_NW # 12
    elif day <= 2:
        return 0
    elif day <= 9:
        return C3_PHASE2_MELON_TARGET # 4
    elif day <= MELON_PLANT_DEADLINE:
        return C3_PHASE3_MELON_TARGET # 6
    else:
        return 0
```

### Phased Planning Function (`agent/strategy/macro_planner.py`)
`compute_phased_melon_plan(...)` enforces 6 strict economic and physical gates:
1. **Seasonal Window Gate**: Active only from `day >= 3` to `MELON_PLANT_DEADLINE` (Day 17). Melons planted after Day 17 cannot reach max yield before Day 29.
2. **Economic EV Comparative Gate**: Expected daily profit per tile for Melon must exceed both Wheat and Carrot alternatives:
   $$\text{EV}_{\text{melon}} = \frac{6.0 \cdot P_{\text{melon}} - 80}{10} > \max\left(\frac{6.0 \cdot P_{\text{wheat}} - 10}{4}, \frac{4.0 \cdot P_{\text{carrot}} - 15}{3}\right)$$
3. **Spot Price Floor Gate**: Expected harvest price must satisfy $P_{\text{melon}} \ge 60.0$.
4. **Market Absorption Ceiling Guard**: Projected cumulative season sales plus shed stock plus growing crops must not exceed `MELON_SEASON_SALE_CAP = 150` units.
5. **Liquidity Escrow Protection**: Cash available for melon seeds strictly excludes mandatory land escrows (NE $1,000 on Days 3–4, SW $2,000 on Days 8–11) and SW seed reserve ($150).
6. **Tile Reservation & Queue Ordering**: Selected tiles (in NE/NW) are temporarily reserved before continuous wheat planting, and appended to `plant_queue` immediately after wheat so that Wheat remains at index 0 for immediate morning worker dispatch.

---

## 5. Files and Functions Changed

1. `agent/config.py`:
   - Added `C3_PHASE2_MELON_TARGET`, `C3_PHASE3_MELON_TARGET`, `C3_MELON_PRICE_FLOOR`.
   - Implemented `get_melon_cap(day)`.
2. `agent/strategy/macro_planner.py`:
   - Implemented `compute_phased_melon_plan(...)`.
   - Integrated call site in `MacroPlanner.build()` between Carrot Blitz and Continuous Wheat.
   - Enforced `get_melon_cap(day)` and liquidity escrow checks in Phase 2b general fill loop.
3. `agent/main.py`:
   - Passed `our_units_sold` into planner context from `_STATE`.
4. `submission/config.py`, `submission/strategy/macro_planner.py`, `submission/main.py`:
   - Mirrored changes for bundle generation.
5. `agent/tests/test_phased_melon.py` (NEW):
   - Created comprehensive unit test suite covering Tests A through L (12 tests).

---

## 6. Current Crop Allocation Before C3

Before C3 was introduced, baseline B2-C5 already had a highly optimized crop portfolio:
- **Day 0**: 12 Melons ($960), 8 Wheat ($80), 4 fallow tiles in NW. Sells 72 melons on Day 10 for a massive $15,000–$18,000 cash surge.
- **Days 3–13**: Dedicated Strawberry Wave in NE quadrant (caps 16 -> 18 -> 20) providing recurring harvests every 2 days.
- **Days 9–27**: SW Quadrant dedicated soil planting strictly allocated to continuous Wheat (feed buffer) and late-game Carrot Blitz (Days 25–27).
- **Phase 2b Opportunistic Filling**: Any residual empty tiles were dynamically filled based on marginal revenue scores. Across full matches, B2-C5 naturally planted 16–21 melons per match and sold 83–102 units.

---

## 7. C3 Economic Model

The theoretical model for Melon compared to alternative crops:

| Crop | Seed Cost | Maturation Days | Yield at Harvest | Revenue/Cycle | Net Profit/Cycle | Daily Profit/Tile |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **Melon** | $80.00 | 10 days | 6.0 units | 6 × $220 = $1,320 | $1,240.00 | **$124.00/day** |
| **Wheat** | $10.00 | 4 days | 6.0 units | 6 × $25 = $150 | $140.00 | **$35.00/day** |
| **Carrot** | $15.00 | 3 days | 4.0 units | 4 × $35 = $140 | $125.00 | **$41.67/day** |
| **Strawberry** | $40.00 | 4 days (first) + 2d ongoing | 2.0 units/cycle | 2 × $120 = $240 | $240.00/cycle | **$120.00/day** (recurring) |

While Melon exhibits high apparent profit per tile-day under initial market prices ($220/unit), this advantage rapidly collapses when:
1. Town demand cannot absorb more than 150 units per season without catastrophic price decay.
2. The 10-day tile lockup prevents nimble adaptation to livestock feed deficits.
3. High seed cost ($80) consumes capital during critical expansion days.

---

## 8. Phased Entry Logic

C3 phased entry divides the season into four distinct phases:
- **Phase 1 (Days 0–2)**: Handled exclusively by the Day-0 12-Melon Springboard. Zero new seed buys on Days 1–2 to conserve cash for Day 3 NE expansion ($1,000).
- **Phase 2 (Days 3–9)**: Phased target of up to 4 active melon plots in NE/NW.
- **Phase 3 (Days 10–17)**: Following the harvest and sale of the Day-0 springboard, target up to 6 active melon plots.
- **Phase 4 (Days 18–29)**: Zero new melon plantings (`MELON_PLANT_DEADLINE = 17`). Endgame realization only.

---

## 9. Melon Allocation Cap

To protect the town market from price collapse, C3 enforces:
- **Active Plot Cap**: Maximum 4 plots in Phase 2, 6 plots in Phase 3.
- **Season Volume Cap**: Hard ceiling at `MELON_SEASON_SALE_CAP = 150` units. Any planned planting where `committed + 6 > 150` is instantly rejected.

---

## 10. Cash/Liquidity Controls

To prevent C3 from bankrupting the agent:
- **NE Land Escrow**: $1,000 reserved on Days 3–4 if NE is locked.
- **SW Land Escrow**: $2,000 reserved on Days 8–11 if SW is locked and treasury >= $2,000.
- **SW Seed Escrow**: $150 reserved on Days 8–9 for immediate SW wheat planting.
- **Future Wage Protection**: 3-day projected payroll subtracted before seed budget calculation.

---

## 11. C5 Interaction

Under C5 (Optimal Maturity / Bonus-Window Harvesting), Melon harvest behavior operates as follows:
- On Day 10 (when melon reaches `max_yield_day`), morning bonus watering executes at priority 76, increasing yield from 5 to 6 units (+20% yield).
- Once watered, harvest executes at priority 90 before Step 24 decay.
- **Interaction Finding**: C5 correctly and reliably harvests every mature melon at max yield (6.0 units). Zero melon decays occurred. However, because C5 maximizes the yield of *all* crops, the relative yield boost to rapid-turnover crops (Wheat +25%, Carrot +50%, Strawberries batched at 2+ units) significantly favored Strawberry and Wheat over 10-day Melon monoculture.

---

## 12. Unit-Test Results

All 12 focused unit tests in `agent/tests/test_phased_melon.py` passed cleanly:
- **Test A (Melon economic eligibility)**: PASS — melon rejected when alternative crops have higher EV.
- **Test B (Cash reserve protection)**: PASS — melon seed buys respect land/seed escrows.
- **Test C (Displacement logic)**: PASS — empty NW/NE tiles allocated to melon displace low-priority fill.
- **Test D (Phased entry)**: PASS — zero melon plantings on Days 1–2.
- **Test E (Allocation cap)**: PASS — melon plots strictly capped by `get_melon_cap(day)`.
- **Test F (Poor Melon economics)**: PASS — price below $60 floor suppresses melon purchases.
- **Test G (C5 integration)**: PASS — melon harvested at max yield after bonus watering.
- **Test H (Endgame realization)**: PASS — plantings after Day 17 rejected.
- **Test I (C4 integration)**: PASS — livestock cutoff at Day 12/14 completely unaffected.
- **Test J (Determinism)**: PASS — identical states produce identical melon allocations.
- **Test K (Existing crop policies)**: PASS — wheat replanting priority preserved.
- **Test L (No C1 activation)**: PASS — hiring schedule unchanged.

**Complete Test Suite**: **385 passed in 18.91s** (0 failures).

---

## 13. Canonical 5-Seed Results

Evaluated via side-by-side execution against identical random seeds:

| Seed | B2-C5 Wealth | B2-C5 + C3 Wealth | Delta ($) | Delta (%) | Improved? | SW Unlock |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **101** | $37,783.00 | $29,665.00 | -$8,118.00 | -21.49% | NO | Day 12 |
| **202** | $37,257.00 | $38,001.00 | +$744.00 | +2.00% | **YES** | Day 12 |
| **303** | $37,208.00 | $32,868.00 | -$4,340.00 | -11.66% | NO | Day 12 |
| **404** | $34,375.00 | $29,853.00 | -$4,522.00 | -13.15% | NO | Day 12 |
| **505** | $38,108.00 | $37,329.00 | -$779.00 | -2.04% | NO | Day 12 |
| **MEAN**| **$36,946.20** | **$33,543.20** | **-$3,403.00** | **-9.21%** | **1 / 5 (20%)** | **12.0** |

### Statistical Summary
- **Mean Delta**: -$3,403.00 (-9.21%)
- **Median Delta**: -$4,340.00 (-11.66%)
- **Minimum Delta**: -$8,118.00 (-21.49%)
- **Maximum Delta**: +$744.00 (+2.00%)
- **Improved Matches**: 1 / 5 (20.0%)
- **Worsened Matches**: 4 / 5 (80.0%)
- **Unchanged Matches**: 0 / 5 (0.0%)

---

## 14. Head-to-Head (H2H) Results

Evaluated via `scripts/run_h2h.py` (6 bilateral matches against root submission `submission.py`):

| Match | Seed | Our Agent (C3) | Opponent (B1) | Winner | Margin ($) |
| :---: | :---: | :---: | :---: | :---: | :---: |
| **1** | 42 (P0 vs P1) | $21,679.00 | $25,679.00 | Opponent (P1) | -$4,000.00 |
| **2** | 42 (P1 vs P0) | $21,864.00 | $24,067.00 | Opponent (P0) | -$2,203.00 |
| **3** | 303 (P0 vs P1) | $26,385.00 | $28,338.00 | Opponent (P1) | -$1,953.00 |
| **4** | 303 (P1 vs P0) | $23,958.00 | $24,495.00 | Opponent (P0) | -$537.00 |
| **5** | 777 (P0 vs P1) | $19,375.00 | $23,174.00 | Opponent (P1) | -$3,799.00 |
| **6** | 777 (P1 vs P0) | $18,592.00 | $24,025.00 | Opponent (P0) | -$5,433.00 |

### H2H Summary
- **Our Agent (C3)**: Average Score = **$21,975.50** | Wins = **0/6 (0.0%)**
- **Opponent Agent**: Average Score = **$24,963.00** | Wins = **6/6 (100.0%)**
- **Net Margin**: **-$2,987.50/match**

---

## 15. 100-Match Results
An automated 100-match tournament harness is currently **not available** in the local environment without external cloud/cluster orchestration. Per experimental guidelines, no 100-match results are fabricated.

---

## 16. Crop Allocation Forensics

Detailed comparison of Seed 101 lifecycle demonstrates exactly why C3 lost $8,118.00:

| Metric | B2-C5 Baseline | B2-C5 + C3 | Delta |
| :--- | :---: | :---: | :---: |
| **Melon Plants** | 16 | 17 | +1 plant |
| **Melon Plant Days** | Days 0 (12), 3 (3), 12 (1) | Days 0 (12), 12 (1), 14 (2), 15 (2) | Shifted to mid-season |
| **Strawberry Plants** | 18 | 11 | **-7 plants (-38.9%)** |
| **Strawberry Sales** | 54 units | 15 units | **-39 units (-72.2%)** |
| **Wheat Plants** | 110 | 119 | +9 plants (+8.2%) |
| **Wheat Sales** | 277 units | 327 units | +50 units (+18.1%) |
| **Carrot Sales** | 136 units | 164 units | +28 units (+20.6%) |
| **Melon Sales** | 83 units | 102 units | +19 units (+22.9%) |

### The Strawberry Cannibalization Mechanism
In B2-C5, 18 Strawberry plants in NE produced recurring harvests throughout Days 7–29, yielding 54 units sold at $120/unit = **$6,480 in recurring strawberry revenue**.
Under C3, the planner forced melon plantings on Days 14 and 15. Because melons occupy soil tiles for 10 consecutive days, Strawberry plantings were reduced to 11 tiles, collapsing strawberry sales to 15 units ($1,800 revenue). The extra 19 melon units gained only $2,850 at depressed late-game prices, producing a massive net loss after subtracting $400 in seed costs and lost strawberry cycles.

---

## 17. Melon Economic Forensics

- **Total Melon Seeds Purchased**: 18 seeds across all seeds ($1,440.00 seed capital invested).
- **Unharvested Melons at Day 29**: **0 across all seeds** (100% realization thanks to C5).
- **Realized Yield**: Exactly 6.0 units per harvested melon plant.
- **Average Realized Price**:
  - Day 10 Springboard Melons (72 units): Realized $220–$240/unit.
  - Days 24–25 Mid-Season Melons (30 units): Realized $140–$165/unit (town inventory backlog depressed prices by >30%).
- **Capital Drag**: Locking $480 in seed capital on Day 14–15 reduced liquid cash reserves, preventing tactical livestock feed buffers.

---

## 18. Market/Price Analysis

The Kaggriculture town shop mechanics impose severe nonlinear price penalties when cumulative market deliveries exceed town consumption:
- Initial inventory: $I_0 = 100$. Town drain: approximately 3–4 units/day.
- By Day 24, town demand has consumed roughly 80 units.
- The Day 10 springboard dumps 72 units. Mid-season melons dump another 30 units.
- Cumulative melon sales reached 102 units, pushing market inventory above equilibrium and crashing price from $240 down to $140.
- Attempting to force additional melon volume beyond 80–90 units directly erodes the unit margin of the entire harvest.

---

## 19. Regression Audit

Verified across all benchmark matches:
- **Workforce & Hiring**: Preserved identically. Target hands reached 12 by Day 6. Zero wage violations.
- **Land Unlocks**: Preserved identically. NE unlocked Day 3, SW unlocked Day 12. SE hard block strictly respected.
- **Livestock Care**: Animals fed, cared for, and sheared/milked normally. C4 cutoff at Day 12/14 preserved.
- **Legality**: 0 engine violations across all runs.

---

## 20. C4 Integrity Check

- `C4_LIVESTOCK_CUTOFF_DAY = 14` present and active in `agent/strategy/animal_planner.py`.
- Dynamic animal target guards confirmed intact.
- Zero animal purchases occurred after Day 14.

---

## 21. C1 Exclusion Check

- Dynamic hiring logic remains completely excluded.
- Hand hiring follows the static baseline schedule.

---

## 22. Limitations & Dusta Discrepancy

Why did C3 succeed in Dusta Stage 8A (+$1,192.50) but fail severely in production (-$3,403.00)?
1. **Baseline Discrepancy**: Dusta's baseline had an impoverished melon allocation (6.83% of tiles), meaning Dusta's market was completely starved of melons. Introducing melons captured uncontested early market demand.
2. **Production Saturation**: Our production agent *already* possessed the 12-Melon NW Springboard, capturing all available high-price market capacity. Adding more melons over-saturated the market and crowded out higher-yielding recurring crops.

---

## 23. Decision Gate

| Criteria | Target | Measured | Result |
| :--- | :---: | :---: | :---: |
| 1. All unit tests pass | 100% | 385 / 385 passed | **PASS** |
| 2. Engine violations | 0 | 0 | **PASS** |
| 3. C4 integrity intact | Preserved | Verified | **PASS** |
| 4. C5 integrity intact | Preserved | Verified | **PASS** |
| 5. C1 excluded/inactive | Strictly excluded | Verified | **PASS** |
| 6. Positive economic delta | Delta > $0 | **-$3,403.00 (-9.21%)** | **FAIL** |
| 7. Causal attribution | Melon allocation | Confirmed (strawberry crowding) | **PASS** |
| 8. No major regression | H2H win rate >= 50% | **0/6 wins (0.0%)** | **FAIL** |
| 9. Economically explainable | Yes | Confirmed by forensics | **PASS** |
| 10. Policy isolation | Only C3 | Confirmed | **PASS** |

**DECISION: REJECT C3.**

---

## 24. Final Recommendation

1. **Reject C3**: Do NOT promote C3 to the production baseline.
2. **Restore Clean B2-C5**: Revert all experimental C3 modifications in `agent/` and `submission/`.
3. **Preserve Baseline**: `B2-C5` (`commit 79fad9e`) remains the sole authoritative production baseline.
4. **Halt Execution**: Enforce the Absolute Stop Condition. Await explicit user instructions before evaluating any further counter-policies.
