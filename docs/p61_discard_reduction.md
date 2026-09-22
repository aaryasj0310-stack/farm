# Kaggriculture P6.1 — Shed Overflow Discard Reduction Analysis

- **Target Metric**: Physical shed overflow discard reduction (Hypothesis: $\ge 70\%$)
- **Measured Result**: **-1.18 units/game (-2.8% reduction)**
- **Baseline Discards**: 42.08 units/game (\$5,900.91 realized value)
- **Treatment Discards**: 40.90 units/game (\$5,488.48 realized value)
- **Hypothesis Status**: **FALSIFIED (2.8% $\ll$ 70%)**

---

## 1. Physical Discard Decomposition by Good

| Good | Baseline Control Discards (u/game) | Treatment Discards (u/game) | Unit Change | % Change | Control Realized Loss | Treatment Realized Loss | Dollar Savings |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **WHEAT** | 16.28 | 17.10 | +0.82 | +5.0% | \$573.71 | \$604.66 | -\$30.95 |
| **STRAWBERRY**| 8.71 | 9.05 | +0.34 | +3.9% | \$2,180.46 | \$2,259.15 | -\$78.69 |
| **MILK** | 4.34 | 3.63 | -0.71 | -16.4% | \$1,036.87 | \$875.66 | +\$161.21 |
| **WOOL** | 4.02 | 3.89 | -0.13 | -3.2% | \$893.77 | \$858.25 | +\$35.52 |
| **FERTILIZER** | 3.86 | 3.65 | -0.21 | -5.4% | \$314.01 | \$297.11 | +\$16.90 |
| **MELON** | 3.10 | 2.05 | -1.05 | -33.9% | \$740.40 | \$488.52 | +\$251.88 |
| **CARROT** | 1.20 | 1.01 | -0.19 | -15.8% | \$47.47 | \$40.36 | +\$7.11 |
| **TOMATO** | 0.57 | 0.52 | -0.05 | -8.8% | \$37.95 | \$34.82 | +\$3.13 |
| **EGG** | 0.00 | 0.00 | 0.00 | 0.0% | \$0.00 | \$0.00 | \$0.00 |
| **TOTAL** | **42.08** | **40.90** | **-1.18** | **-2.8%** | **\$5,824.64** | **\$5,458.53** | **+\$366.11** |

*(Note: Total realized discard values reflect contemporaneous average product selling prices).*

---

## 2. Where the Intervention Succeeded vs Where It Failed

### Success Modalities (Days 8–14)
On Days 8 through 14, crops like Melons and Milk first mature in small batches. When these products were harvested and deposited into the shed during earlier daytime windows (e.g. Hour 17 or 21), P6.1 detected `projected_load > 75` and successfully emitted late-evening sell orders:
- **Melon discards reduced by 33.9%** (3.10 u -> 2.05 u, saving \$251.88).
- **Milk discards reduced by 16.4%** (4.34 u -> 3.63 u, saving \$161.21).
- In specific scenarios (e.g. Seed 96411 `pass` Seat 0), Day 10 discards dropped from 44 units to 0 units, unlocking a single-game cash lift of **+$10,129.00**.

### Failure Modalities (Days 16–28)
In the second half of the season (Days 16–28), the farm expands to 6–8 workers and 10–12 animals:
1. **The Backpack Glut**:
   - Workers harvest massive quantities of Strawberry, Wool, and Milk throughout the day.
   - At Hours 20–22, workers are carrying **60 to 85 units** across their backpacks.
2. **The Shed Wheat Impasse**:
   - At Hours 20–22, the shed contains **40 to 48 units of Wheat** (the required 4-day feed reserve for 10–12 animals) and **0 units of Strawberry, Wool, or Milk**.
   - Storage hygiene calculates `projected_load = shed (48) + worker (82) = 130 > 75`.
   - Relief needed is $130 - 75 = 55$ units.
   - But what can be liquidated from the shed?
     - Tier 1 (Fertilizer): 0 in shed.
     - Tier 2 (Strawberries, Wool, Milk, Melon): 0 in shed (all in worker backpacks!).
     - Tier 3 (Surplus Wheat): 48 in shed, but the safe wheat floor is $12 \times 4 = 48$ units! Surplus wheat is 0!
   - Result: **0 sellable units available in the shed**. Storage hygiene cannot emit a single order.
3. **The Midnight Collision**:
   - At Turn 23 -> Turn 0, the engine executes `_drop_inventories_to_shed`.
   - 82 units from worker backpacks attempt to enter a shed with 48 units of wheat.
   - The shed accepts $100 - 48 = 52$ units.
   - The remaining **30 units of Strawberry, Milk, and Wool are permanently destroyed**.

---

## 3. Structural Conclusion

A storage hygiene mechanism operating strictly on *inventory already in the shed* cannot solve late-game overflow discards because **the overflow volume does not enter the shed until the midnight drop occurs**. 

To eliminate the remaining 40.90 units of discards, future interventions must address **mid-day worker inventory drop-off** or **feed wheat structural storage decoupling**, rather than late-evening market sales.
