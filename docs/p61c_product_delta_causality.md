# P6.1-C Product Delta Causality

## Executive Summary

In P6.1, net product sales revenue rose by **+$661.70**, composed of distinct gains in Milk (+1.97 u, +$799.35), Melon (+2.45 u, +$535.48), and Strawberry (+0.68 u, +$115.62), set against a sharp reduction in Wheat revenue (-24.24 u, -$731.49).

This report traces the causal pathways connecting the pre-midnight storage hygiene routine to these product-level shifts.

Key conclusions:
1. **Direct Discard Salvage (~$501 of value)**:
   - Hygiene directly saved **1.05 units of Melon** and **0.71 units of Milk** from midnight shed discards.
   - This direct salvage explains **42.9% of the Melon volume gain** (1.05 of 2.45 u) and **36.0% of the Milk volume gain** (0.71 of 1.97 u).
2. **Animal Care Continuity & Feed Reliability (+1.26 units Milk)**:
   - By enforcing a 48-unit shed feed wheat buffer, Treatment experienced **0.58 fewer missed animal feedings per game** (13.08 vs 13.66 missed feeds).
   - Sustained nutrition prevented lactation stalls, generating an additional **+1.26 units of Milk** across the season.
3. **The Wheat Tradeoff (-24.24 units Wheat Sold, -23.16 units Bought)**:
   - Treatment sold 24.24 fewer units of wheat because the hygiene routine refused to sell shed wheat below the safety floor.
   - That retained wheat was consumed on-farm by livestock, directly displacing 23.16 units of store-bought feed wheat.

---

## 1. Product Delta Decomposition

The table below decomposes each product's quantity and revenue delta into direct discard salvage vs. yield/planner drift.

| Product | Total Qty Delta (u) | Units Saved from Discards (u) | Residual Yield Delta (u) | Mean Realized Sell Price | Total Revenue Delta | Revenue from Discard Salvage | Revenue from Yield Shift |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Milk** | **+1.97** | **+0.71** | +1.26 | $405.76/u | **+$799.35** | +$288.09 | +$511.26 |
| **Melon** | **+2.45** | **+1.05** | +1.40 | $218.46/u | **+$535.48** | +$229.38 | +$306.10 |
| **Strawberry** | **+0.68** | -0.34 (worse) | +1.02 | $170.23/u | **+$115.62** | -$57.88 | +$173.50 |
| **Carrot** | **+0.54** | **+0.19** | +0.35 | $91.11/u | **+$49.40** | +$17.31 | +$32.09 |
| **Tomato** | **+0.45** | **+0.05** | +0.40 | $87.12/u | **+$39.15** | +$4.36 | +$34.79 |
| **Wool** | **-0.06** | **+0.13** | -0.19 | $220.63/u | **-$137.40** | +$28.68 | -$166.08 |
| **Fertilizer** | **-0.22** | **+0.21** | -0.43 | $81.40/u | **-$8.41** | +$17.09 | -$25.50 |
| **Wheat** | **-24.24** | -0.82 (worse) | -23.42 | $30.18/u | **-$731.49** | -$24.75 | -$706.74 |
| **Total** | — | **+1.18** | — | — | **+$661.70** | **+$502.28** | **+$159.42** |

---

## 2. Analysis of Primary Product Mechanisms

### 2.1 Dairy Production (Milk: +1.97 units, +$799.35)
Milk was the single largest revenue contributor to Treatment's outperformance. The causal pathway operates through two distinct mechanisms:
1. **Direct Discard Reduction (0.71 u = $288.09)**:
   - On days when cows produced milk in late afternoon, milk deposited into the shed at midnight was occasionally discarded in Control due to lack of space.
   - When Treatment managed to sell residual surplus wheat or fertilizer at H21, it occasionally opened 1–2 slots in the shed, allowing the milk to survive midnight.
2. **Nutritional Continuity (1.26 u = $511.26)**:
   - In Kaggriculture, cows require 1 unit of wheat daily. If unfed, lactation halts, and consecutive unfed days risk starvation or productivity penalties.
   - In Control, aggressive wheat dumping left the shed empty at morning feeding (Hour 0) on 13.66 animal-days per game.
   - Treatment's safety buffer reduced missed feedings to 13.08 animal-days.
   - The extra 0.58 uninterrupted feeding days enabled cows to produce 1.26 additional milk units over the 30-day season.

### 2.2 Melons (+2.45 units, +$535.48)
Melons have a high unit value (~$218/u) and mature on 14-day cycles.
- In Control, when a melon harvest coincides with a full shed at midnight, bulky melon units (volume 1) are discarded. Control lost 3.10 units of melon per game to discards.
- In Treatment, melon discards dropped to 2.05 units per game (a direct salvage of **1.05 melons = +$229.38**).
- The remaining +1.40 units of melon came from slight worker dispatch differences on late harvest days.

### 2.3 Wheat Retention and Transfer Pricing (-24.24 units Sold)
Wheat was the only major crop to experience a revenue decline (-$731.49):
- In Control, the agent periodically dumped all available wheat into the town market, receiving wholesale sell prices (~$30.18/u).
- In Treatment, the hygiene routine strictly forbade selling wheat if shed inventory was $\le 48$ units.
- Consequently, Treatment sold 24.24 fewer units of wheat into the town market.
- However, as proven in the cash reconciliation, this retained wheat was fed directly to livestock, avoiding the purchase of 23.16 units of feed wheat at town retail buy prices (~$32.35/u, saving $749.18).

---

## 3. Summary of Revenue Causality

The +$661.70 sales revenue gain was **not** caused by faster crop cycling or expanded planting area. It was produced by:
1. **Direct salvage of high-value units**: $502.28 (mostly 1.05 melons and 0.71 milk).
2. **Dairy health continuity**: $511.26 (improved feed stability generating +1.26 milk).
3. **Offset by wheat sales reduction**: -$731.49 (retaining wheat on-farm).
4. **Minor crop yield and price variances**: +$379.65.
