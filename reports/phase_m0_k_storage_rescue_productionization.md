# Phase M0-K: Storage Rescue Productionization & Independent Confirmation

## 1. Executive Summary & Production Decision

Phase M0-K successfully productionized and independently confirmed **M0-D Storage Rescue** (`MIDNIGHT_STORAGE_DUMP_MODE = "RESCUE"`), promoting it as a permanent production default in the Kaggriculture agent architecture.

### Key Milestones & Outcomes
1. **Authoritative Reproduction on Current HEAD**:
   - Re-evaluated the historical M0-D matrix across consumed discovery seeds `97013–97022` $\times$ 5 benchmark opponents $\times$ 2 seats (100 scenario cells / 200 real-engine matches).
   - Achieved a **100% bit-for-bit exact match** to historical M0-D results:
     - Baseline C0 Mean: **$104,009.28**
     - Rescue C2 Mean: **$109,066.17**
     - Paired Mean Gain: **+$5,056.89** (Target: +$5,056.89)
     - Win/Tie/Loss: **84W / 0T / 16L** (84.0% win rate)
     - Discard Reduction: **3,682 $\to$ 279 units (-92.42%)**
     - Feed Violations: **0**, Animal Escapes: **0**
   - **Decision Gate G Passed Unconditionally**.

2. **Independent Confirmation on Fresh Protected Seeds**:
   - Evaluated the frozen candidate across 20 previously untouched seeds `96521–96540` $\times$ 5 opponents $\times$ 2 seats (200 scenario cells / 400 real-engine matches).
   - Final Results:
     - Baseline C0 Mean: **$101,979.75** ($\sigma = 8,958.89$, median = **$102,212.00**)
     - Candidate C2 Mean: **$106,984.40** ($\sigma = 8,668.26$, median = **$107,423.50**)
     - Paired Mean Gain: **+$5,004.65** ($\sigma = 4,782.72$)
     - Paired Median Gain: **+$5,361.00**
     - 95% Clustered CI: **[+$4,374.52, +$5,634.77]** (df=19, SE=$301.06)
     - Positive Seed Clusters: **20 / 20 (100.0%)**
     - Overall Win Rate: **171W / 0T / 29L (85.5% win rate)**
     - Discard Reduction: **7,536 $\to$ 538 units (-92.86%)**
     - Net Inventory Spot Value Preserved: **+$1,398,785.00** ($1,480,845.00 lost under C0 vs $82,060.00 lost under C2)
     - Animal Escapes / Starvations: **0**, Feed Floor Violations: **0**, Order Cap Breaches: **0**.
     - *Telemetry Note (R1)*: Avoided inventory destruction valued at spot prices ($1,398,785.00) represents physical crop asset value saved, distinct from realized paired terminal cash gain (+$5,004.65). Historical whole-step transaction revenue and net unit deltas are documented and labeled as unverified in the R1 Addendum.

3. **Production Promotion**:
   - All 8 explicit release acceptance gates passed.
   - `MIDNIGHT_STORAGE_DUMP_MODE = "RESCUE"` promoted to default in `agent/config.py` and `submission/config.py`.
   - Official multi-file submission package `dist/submission.zip` rebuilt and verified in isolated runtime ($115,554 match cash).
   - Full test suite verified: **1,335 / 1,335 tests passed (100%)**.

---

## 2. Repository Provenance & Environment

- **Repository**: `https://github.com/aaryasj0310-stack/farm`
- **Branch**: `experiment/sw-forward-architecture-phase-a`
- **Starting HEAD**: `451513efe88ede55717cea5ba2eb36decede4210`
- **Frozen Candidate Commit**: `0a23f93eaad59dad71723ff989d44fb9e132ca76`
- **Python Runtime**: Python 3.12.10 (Windows)
- **Engine Source**: `kaggle_environments/envs/kaggriculture/kaggriculture.py` (SHA256: `bc8a54879ef02c7ea64b8b333d6a976f0ea65c4949149d01f463f23bccee653e`)
- **Working Tree**: Clean throughout all audit stages.

---

## 3. Historical M0-D Reproduction Audit

### Methodology
To ensure current-HEAD has suffered zero code rot, broken dependencies, or silent semantic shifts since Phase M0-D, we executed an exact reproduction run across the original 100 scenario cells (seeds `97013–97022` $\times$ 5 benchmark opponents $\times$ 2 seats).

Matches were instrumented directly around the authoritative engine function `_drop_inventories_to_shed` in `kaggriculture.py`.

### Reproduction Matrix Results
| Metric | Historical Target (M0-D) | Current-HEAD Reproduction | Status |
| :--- | :--- | :--- | :--- |
| **C0 Mean Cash** | $104,009.28 | $104,009.28 | **Exact Match** |
| **C2 (Rescue) Mean Cash** | $109,066.17 | $109,066.17 | **Exact Match** |
| **Mean Paired Gain** | +$5,056.89 | +$5,056.89 | **Exact Match** |
| **Median Paired Gain** | +$5,012.00 | +$5,012.00 | **Exact Match** |
| **Win / Tie / Loss Record** | 84W / 0T / 16L | 84W / 0T / 16L | **Exact Match** |
| **95% Clustered CI** | [+$2,504.60, +$7,609.18] | [+$2,504.60, +$7,609.18] | **Exact Match** |
| **Clustered SE (df=9)** | $1,128.33 | $1,128.33 | **Exact Match** |
| **Positive Seed Clusters** | 10 / 10 (100%) | 10 / 10 (100%) | **Exact Match** |
| **Total Units Discarded** | 3,682 $\to$ 279 | 3,682 $\to$ 279 | **-92.42%** |
| **Feed Floor Violations** | 0 | 0 | **0 Violations** |
| **Animal Escapes (C0 / C2)**| 0 / 0 | 0 / 0 | **0 Escapes** |

---

## 4. Reproduction Evaluation & Decision Gate G

Decision Gate G criteria:
1. Current-HEAD reproduces M0-D paired mean gain $\ge$ +$4,000.00: **PASS (+ $5,056.89)**
2. Clustered positive seed clusters $\ge$ 8 / 10: **PASS (10 / 10)**
3. Feed floor violations == 0: **PASS (0 violations)**
4. Animal escapes C2 $\le$ C0: **PASS (C0=0, C2=0)**

**Decision Gate G: UNCONDITIONALLY PASSED.**

---

## 5. Release Candidate Architecture & Configuration Diff

Storage Rescue operates cleanly within the existing modular pipeline:
- **Location**: `agent/execution/midnight_storage_controller.py` (`apply_midnight_storage_rescue`).
- **Timing**: Hour 23, Day < 29.
- **Trigger**: Projected midnight load (`shed_load + carried_inventory > 98`).
- **Relief**: Appends `["SELL", "WHEAT", sell_qty]` to market orders, where:
  $$\text{needed} = \text{projected} - 98$$
  $$\text{safe\_wheat} = \max(10, \text{animal\_count} \times 2)$$
  $$\text{sell\_qty} = \min(\text{shed\_wheat} - \text{safe\_wheat}, \text{needed})$$
- **Arbitration Safety**: Only appended if `len(market) < 10`. Never displaces existing planned sell or buy orders.

### Configuration Diff
```diff
--- a/agent/config.py
+++ b/agent/config.py
@@ -292,7 +292,7 @@ def set_same_turn_crop_pipeline_mode(mode: str) -> None:
 
 # Kaggriculture Phase M0-D: Engine Mechanics Exploitation — Midnight Storage Dump & Rescue
 # Supported modes: "OFF" (production baseline), "BUFFER" / "ON" (M0-B buffered riding), "RESCUE" (M0-D end-of-day storage rescue)
-MIDNIGHT_STORAGE_DUMP_MODE: str = "OFF"
+MIDNIGHT_STORAGE_DUMP_MODE: str = "RESCUE"
```

---

## 6. Independent Confirmation Experiment Design

- **Panel**: 20 fresh protected seeds (`96521–96540`). Verified completely untouched by prior research or discovery scans.
- **Opponent Zoo**: 5 canonical benchmarks (`pass`, `pure_wheat_rush`, `cow_milk_engine`, `melon_sniper`, `full_production_agent`).
- **Seats**: Both Seat 0 and Seat 1.
- **Scale**: $20 \text{ seeds} \times 5 \text{ opponents} \times 2 \text{ seats} = 200 \text{ scenario cells} = 400 \text{ real-engine matches}$.
- **Arms**:
  - Arm C0: Production Baseline (`MIDNIGHT_STORAGE_DUMP_MODE = "OFF"`)
  - Arm C2: Frozen Candidate (`MIDNIGHT_STORAGE_DUMP_MODE = "RESCUE"`)

---

## 7. Confirmation Economic Results

### Aggregate Statistics
- **C0 Baseline Mean Cash**: $101,979.75 ($\sigma = 8,958.89$, median = $102,212.00)
- **C2 Rescue Mean Cash**: $106,984.40 ($\sigma = 8,668.26$, median = $107,423.50)
- **Paired Mean Gain**: **+$5,004.65** ($\sigma = 4,782.72$)
- **Paired Median Gain**: **+$5,361.00**
- **Win / Tie / Loss Record**: **171W / 0T / 29L (85.5% Win Rate)**
- **Seed-Clustered Standard Error**: **$301.06** (df=19)
- **95% Clustered Confidence Interval**: **[+$4,374.52, +$5,634.77]** ($p < 10^{-12}$)
- **Positive Seed Clusters**: **20 / 20 (100.0%)**
- *Statistical Property Note*: On skewed paired distributions, the median of paired differences ($\text{median}(\Delta) = +\$5,361.00$) does not equal the difference of individual medians ($\text{median}(C2) - \text{median}(C0) = \$107,423.50 - \$102,212.00 = +\$5,211.50$). The paired median represents the 50th percentile of match-by-match advantage.

### Clustered Performance by Seed (20 / 20 Positive)
| Seed | Mean Gain | Seed | Mean Gain | Seed | Mean Gain | Seed | Mean Gain |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **96521** | +$5,917.10 | **96526** | +$3,838.80 | **96531** | +$7,272.90 | **96536** | +$3,934.40 |
| **96522** | +$5,408.00 | **96527** | +$4,123.30 | **96532** | +$5,622.40 | **96537** | +$4,612.80 |
| **96523** | +$1,470.60 | **96528** | +$5,559.60 | **96533** | +$4,155.00 | **96538** | +$6,289.00 |
| **96524** | +$5,079.80 | **96529** | +$5,723.80 | **96534** | +$6,956.70 | **96539** | +$6,270.00 |
| **96525** | +$4,702.20 | **96530** | +$5,459.70 | **96535** | +$4,301.00 | **96540** | +$3,395.80 |

### Breakdown by Benchmark Opponent
| Opponent | Pairs | C0 Mean | C2 Mean | Paired Mean Gain | Median Gain | Win / Loss | Discards (C0 $\to$ C2) |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| `pass` | 40 | $100,565.95 | $105,911.68 | **+$5,345.72** | +$5,614.00 | 36W / 4L | 1,352 $\to$ 55 |
| `pure_wheat_rush` | 40 | $98,760.22 | $104,242.00 | **+$5,481.78** | +$5,757.00 | 30W / 10L | 2,042 $\to$ 182 |
| `cow_milk_engine` | 40 | $105,290.32 | $108,740.60 | **+$3,450.28** | +$3,210.50 | 33W / 7L | 978 $\to$ 29 |
| `melon_sniper` | 40 | $103,607.78 | $108,054.18 | **+$4,446.40** | +$4,652.00 | 34W / 6L | 1,657 $\to$ 187 |
| `full_production_agent` | 40 | $101,674.48 | $107,973.52 | **+$6,299.05** | +$6,497.00 | 38W / 2L | 1,507 $\to$ 85 |

### Breakdown by Seat
| Seat | Pairs | C0 Mean | C2 Mean | Paired Mean Gain | Median Gain | Win / Loss | Discards (C0 $\to$ C2) |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Seat 0** | 100 | $102,209.34 | $106,803.73 | **+$4,594.39** | +$5,073.00 | 83W / 17L | 3,694 $\to$ 307 |
| **Seat 1** | 100 | $101,750.16 | $107,165.06 | **+$5,414.90** | +$5,486.50 | 88W / 12L | 3,842 $\to$ 231 |

---

## 8. Storage & Overflow Accounting

- **C0 Total Units Destroyed**: 7,536 units (mean 37.68 units/match)
- **C2 Total Units Destroyed**: 538 units (mean 2.69 units/match)
- **Units Preserved from Destruction**: **6,998 units**
- **Destruction Elimination Rate**: **92.86%**
- **C0 Actual Spot Value Lost**: **$1,480,845.00**
- **C2 Actual Spot Value Lost**: **$82,060.00**
- **Net Inventory Spot Value Preserved**: **+$1,398,785.00**
- **Telemetry Reconciliation (R1)**:
  - The historical confirmation archive recorded `rescue_units_sold = -13024` and `rescue_revenue = 941919.0`.
  - *Root Cause Analysis*: As diagnosed in R1-02 and R1-03, `rescue_units_sold` was computed using `shed_wheat_pre - shed_wheat_post` over the midnight step (Hour 23 $\to$ Hour 0). At midnight rollover, the game engine executes `_drop_inventories_to_shed`, dumping workers' carried wheat into the shed. When worker deposits exceed wheat sold, `shed_wheat_post` exceeds `shed_wheat_pre`, creating negative step deltas (-13,024). Inverting this sign to claim "13,024 units sold" was an invalid post-hoc heuristic.
  - *Revenue Attribution*: The $941,919.00 figure measured total whole-step money deltas (`money_post - money_pre`) across all sales and purchases occurring on Hour 23 steps, rather than isolated rescue wheat order revenue.
  - *Status*: Avoided physical inventory destruction (6,998 units; $1,398,785.00 spot value preserved) and terminal paired cash gain (+$5,004.65) are authoritative and verified. Direct historical rescue transaction counts and revenues are formally labeled **unverified** in the archived telemetry.

---

## 9. Feed & Animal Safety Verification

A critical safety risk of dumping wheat is starving animals or provoking escapes.
- **Feed Reserve Floor**: Preserved strictly at $\max(10, \text{animals} \times 2)$.
- **Feed Reserve Floor Violations**: **0 / 400 matches (0.0%)**.
- **Animal Escapes under C0**: 0
- **Animal Escapes under C2**: 0
- **Animal Starvation Events**: 0
- **Livestock Safety Conclusion**: Perfect safety parity with baseline.

---

## 10. Market Cap & Order Arbitration Audit

- **Engine Market Order Cap**: $\le 10$ orders per turn.
- **Displaced Critical Orders**: **0**.
- **Order Cap Breaches**: **0** (verified across all turns of all matches).
- **Arbitration Mechanism**: Storage rescue checks `len(market) < 10` before appending. If 10 market orders are already planned by the economic brain, rescue yields unconditionally.
- **Telemetry Reconciliation (R1)**: The archived `market_safety.json` reported `orders_blocked_by_10_cap = 1067` because the script naively subtracted `executed` from `emitted`. In reality, orders unexecuted in the engine were due to inventory exhaustion (or net shed increase), not cap blocking. Gate 8 validation was confirmed across 100% of turns.

---

## 11. Downside Forensics

Across 200 paired scenario cells on fresh seeds:
- **Wins**: 171 (85.5%)
- **Losses**: 29 (14.5%)
- **Zero-loss Opponents**: None, but `full_production_agent` had only 2 losses out of 40 (95.0% win rate).
- **Observed Forensic Facts**:
  1. In all 29 loss cells, animal escapes were 0 and feed reserve floor violations were 0.
  2. In 26 of 29 losses, physical inventory discard was still reduced or equal under C2.
  3. The median loss drawdown was modest (-$2,014.00), vastly outweighed by the typical win (+ $5,361.00 median paired gain).
  4. The maximum loss occurred on Seed 96530 vs `pure_wheat_rush` Seat 0 (-$11,884.00), where C0 achieved $117,621.00 vs C2's $105,737.00.
- **Forensic Hypotheses (Non-Definitive)**:
  - *Hypothesis A (Market Equilibrium Shift)*: Proactively selling wheat at Hour 23 increases town market inventory by next morning, altering price elasticity curves for crops and slightly suppressing high-value melon or strawberry liquidation prices on volatile seeds.
  - *Hypothesis B (Task Schedule Divergence)*: Earlier cash realization can trigger capital purchases (e.g. land, animals) a turn earlier, slightly altering worker dispatch locations and harvest delivery timing.
  - These hypotheses explain observed variance without implying strategy invalidity, as C2 remains overwhelmingly superior across 85.5% of matches.

---

## 12. Final Release Decision & Gate Verification

| Release Gate | Requirement | Measured Value | Gate Status |
| :--- | :--- | :--- | :--- |
| **Gate 1: Paired Mean Gain** | $> 0$ | **+$5,004.65** | **PASSED** |
| **Gate 2: Clustered 95% CI Lower Bound** | $> 0$ | **+$4,374.52** | **PASSED** |
| **Gate 3: Positive Seed Clusters** | $\ge 14 / 20$ (70%) | **20 / 20 (100.0%)** | **PASSED** |
| **Gate 4: Overall Win Rate** | $\ge 70.0\%$ | **85.5% (171W / 29L)**| **PASSED** |
| **Gate 5: Discard Reduction** | $\ge 40.0\%$ | **92.86%** | **PASSED** |
| **Gate 6: Animal Escape Parity** | $C2 \le C0$ | **C0=0, C2=0** | **PASSED** |
| **Gate 7: Feed Floor Violations** | $== 0$ | **0 violations** | **PASSED** |
| **Gate 8: Market Order Cap** | $\le 10$ orders | **0 breaches (verified)** | **PASSED** |

**FINAL DISPOSITION: ALL 8 RELEASE GATES PASSED. PROMOTED TO PRODUCTION.**

---

## 13. Updated Production Configuration

```python
# agent/config.py & submission/config.py
MIDNIGHT_STORAGE_DUMP_MODE: str = "RESCUE"
SAME_TURN_DEPOSIT_SELL_MODE: str = "BASELINE"
SAME_TURN_CROP_PIPELINE_MODE: str = "OFF"
SW_FORWARD_ARCHITECTURE_MODE: str = "OFF"
SOFT_WORKER_LOCALITY_MODE: str = "OFF"
ANIMAL_SERVICE_ECONOMICS_MODE: str = "OFF"
```

---

## 14. Answers to the 21 Explicit Phase M0-K Questions

### Q1: Did current-HEAD reproduce M0-D (+ $5,056.89 paired mean gain, 84W/16L, 10/10 positive clusters)?
**Yes, 100% bit-for-bit exact match.** Baseline C0 cash was $104,009.28, Rescue C2 was $109,066.17, paired mean gain was +$5,056.89, median gain was +$5,012.00, win/tie/loss record was 84W / 0T / 16L, and all 10 seed clusters were positive.

### Q2: How much shed discard occurred under C0 vs C2 in the reproduction panel?
Under baseline C0, **3,682 units** of inventory were discarded by the engine. Under C2, this dropped to **279 units**, eliminating **92.42%** of all inventory discard.

### Q3: Were there any feed floor violations or animal escapes in the reproduction panel?
**Zero.** Feed floor violations were 0, and animal escapes were 0 for both C0 and C2.

### Q4: Did any rescue order displace a critical market order?
**No.** Rescue sell orders are only appended if `len(market) < 10`. Displaced critical orders was exactly 0.

### Q5: What was the exact git commit where the candidate was frozen before fresh-seed testing?
Commit **`0a23f93eaad59dad71723ff989d44fb9e132ca76`** (`release(kaggriculture): freeze M0-D storage rescue candidate`).

### Q6: What were the paired mean, median, standard error, and 95% CI on fresh confirmation seeds?
- Paired Mean Gain: **+$5,004.65** ($\sigma = 4,782.72$)
- Paired Median Gain: **+$5,361.00** (C0 Median = $102,212.00, C2 Median = $107,423.50)
- Clustered Standard Error: **$301.06** (df=19)
- 95% Clustered CI: **[+$4,374.52, +$5,634.77]**

### Q7: How many seed clusters were positive out of 20?
**20 out of 20 (100.0%)** seed clusters were positive, ranging from +$1,470.60 to +$7,272.90.

### Q8: What was the overall win rate on fresh confirmation seeds?
**85.5%** (171 Wins, 0 Ties, 29 Losses across 200 pairs).

### Q9: What was the performance breakdown by benchmark opponent?
- `pass`: +$5,345.72 mean gain (36W / 4L)
- `pure_wheat_rush`: +$5,481.78 mean gain (30W / 10L)
- `cow_milk_engine`: +$3,450.28 mean gain (33W / 7L)
- `melon_sniper`: +$4,446.40 mean gain (34W / 6L)
- `full_production_agent`: +$6,299.05 mean gain (38W / 2L)

### Q10: What was the performance breakdown by seat (0 vs 1)?
- **Seat 0**: +$4,594.39 mean gain (83W / 17L)
- **Seat 1**: +$5,414.90 mean gain (88W / 12L)

### Q11: How many units were discarded under baseline C0 vs candidate C2 on fresh seeds?
- Baseline C0: **7,536 units** discarded.
- Candidate C2: **538 units** discarded.
- Reduction: **6,998 units preserved**.

### Q12: What percentage of discards was eliminated by storage rescue on fresh seeds?
**92.86%** of all discards were eliminated.

### Q13: What was the total dollar value of inventory saved from destruction on fresh seeds?
**+$1,398,785.00** of inventory spot value was preserved ($1,480,845.00 lost under C0 vs $82,060.00 under C2). *(Note: Earlier draft narrative quoted $832,052 from preliminary partial calculations; the authoritative 200-pair archive records $1,398,785.00 preserved)*.

### Q14: How many rescue sell orders were emitted vs executed on fresh seeds?
1,232 candidate rescue orders were recorded by the controller. Exact executed orders at the market boundary were not isolated in historical telemetry and are labeled unverified; see R1 Addendum for methodology reconciliation.

### Q15: How many units of wheat were sold through rescue orders and what revenue was realized?
Historical archive recorded -13,024 units due to whole-step worker deposits, and $941,919.00 whole-step cash changes. Both metrics are formally labeled unverified. Authoritative avoided physical destruction was 6,998 units ($1,398,785.00 spot value).

### Q16: Were there any feed reserve floor violations on fresh seeds?
**Zero (0) violations.** The reserve floor of $\max(10, \text{animals} \times 2)$ was preserved on every step.

### Q17: Were there any animal escapes or starvation events under candidate C2 on fresh seeds?
**Zero (0) escapes and zero (0) starvation events** (C0 escapes = 0, C2 escapes = 0).

### Q18: Were there any market-order cap violations (orders > 10)?
**Zero (0) violations.** The 10-order cap was respected on 100% of turns. (The historical metric of 1,067 cap-blocked orders was a calculation artifact from subtracting unexecuted from emitted orders).

### Q19: What do downside forensics show for the losses on fresh seeds?
Observed facts: 0 animal escapes, 0 feed violations, discard reduced or equal in 26/29 losses. Hypothesized causes: secondary market price shifts and dispatch timing variance under earlier cash realization.

### Q20: Did the candidate pass all 8 release acceptance criteria?
**Yes, all 8 criteria passed unconditionally.**

### Q21: What is the final production disposition of Storage Rescue?
**PROMOTED TO PRODUCTION.** `MIDNIGHT_STORAGE_DUMP_MODE = "RESCUE"` is now the permanent production default in `agent/config.py`, mirrored in `submission/config.py`, verified in `dist/submission.zip`, and validated with a 100% passing test suite (1,335 tests).
