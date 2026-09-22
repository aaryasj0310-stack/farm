# Kaggriculture P4.0 — Crop Transition Economics Report

## 1. Executive Summary & Marginal Crop Frontier

This report analyzes the realized marginal economics of every crop in the Kaggriculture environment, grounded in 100 fully instrumented games of the Promoted P2.3 Production Baseline.

We evaluate:
1. Realized yields, seed costs, gross revenues, and net margins by crop species.
2. Return per tile-day and labor intensity per dollar earned.
3. Why previous crop-portfolio treatments failed (P2.0 Second Melon, P2.1 Dynamic Strawberry Cap).
4. Why P2.3 Marginal Wheat succeeded and whether further crop transitions can generate additional score.

---

## 2. Realized Crop Economics Summary Table

The table below reports the empirical results across the 100 audited baseline games:

| Crop Species | Mean Plantings | Mean Harvest (Units) | Mean Seed Cost ($) | Mean Gross Revenue ($) | Mean Net Margin ($) | Gross Margin (%) | Realized Price ($/unit) | Cycle Days | Net Return per Tile-Day |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **WHEAT** | 101.7 | 1,003.0 | $1,032.40 | $36,708.63 | **+$35,676.23** | **97.19%** | $36.60 | 4 | **$54.90 / day** |
| **MELON** | 15.3 | 89.9 | $1,278.40 | $21,469.81 | **+$20,191.41** | **94.05%** | $238.71 | 8 | **$119.36 / day** |
| **STRAWBERRY** | 14.3 | 79.6 | $1,502.00 | $19,538.28 | **+$18,036.28** | **92.31%** | $245.58 | Ongoing (2d) | **$122.79 / day** |
| **CARROT** | 26.0 | 67.2 | $605.60 | $2,599.76 | **+$1,994.16** | **76.71%** | $38.67 | 2 | **$38.35 / day** |
| **TOMATO** | 4.6 | 24.2 | $264.50 | $1,673.97 | **+$1,409.47** | **84.20%** | $69.17 | 3 | **$46.11 / day** |
| **Total Crops** | **161.9** | **1,263.9** | **$4,682.90** | **$81,990.45** | **+$77,307.55** | **94.29%** | — | — | — |

---

## 3. Deep-Dive by Crop Archetype

### 1. Strawberry: The Ultimate Ongoing Capital Engine
- **Mechanics**: Seed cost $100. First harvest on Day 4 after planting; subsequently yields 2 units every 2 days indefinitely if watered.
- **Economics**: Across Days 11–28 (17 days active), a single strawberry tile produces ~16 units of strawberries.
  - At realized market prices of **$245.58 / unit**, a single strawberry tile yields **$3,929.28 in gross revenue** for a $100 seed investment!
  - Return per tile-day: **$122.79 / day** (highest of any crop in the game).
  - Labor efficiency: Requires only 1 water turn per day and 1 harvest turn every 2 days. No re-tilling, no re-planting.
- **Role in Baseline**: The backbone of mid-to-late season cash generation. 14–15 strawberry tiles generate $19.5k in revenue.

### 2. Melon: The Early-Game Capital Catalyst
- **Mechanics**: Seed cost $80. Takes 8 full days of daily watering to mature; yields 4 units on harvest (one-shot).
- **Economics**: 4 units $\times$ $238.71 = $954.84 revenue per tile. Less $80 seed cost = **+$874.84 net profit per tile**.
  - Return per tile-day: **$119.36 / day**.
  - Crucial role: Planted on Day 0, harvested on Day 8/9. Generates the massive **+$13,979 lump sum** that funds the entire herd acquisition and max-workforce hiring on Days 9–11.
- **Limitation**: Tying up a tile for 8 days without any cash flow is only tolerable in Days 0–8 when workforce is small and capital is bootstrapping.

### 3. Wheat: The Multi-Functional Workhorse
- **Mechanics**: Seed cost $10. Takes 4 days to mature; yields 6 units on harvest.
- **Economics**: 6 units $\times$ $36.60 = $219.60 revenue per tile. Less $10 seed cost = **+$209.60 net profit per tile** (97.2% margin!).
  - Return per tile-day: **$54.90 / day**.
  - Strategic role: Dual utility. Generates $36.7k in direct sales while serving as the vital animal feed supply for the cow/sheep herd.
  - P2.3 Marginal Replanting: Replanting wheat on vacated tiles up to Day 25 captures +$445/game in pure profit without interfering with terminal liquidation.

### 4. Carrot & Tomato: The Bootstrapping Stopgaps
- **Carrots**: 2-day cycle, yield 4 units. Return: $38.35/day. Used exclusively on Days 0–4 to provide fast liquidity before melons mature.
- **Tomatoes**: 3-day cycle, yield 4 units. Return: $46.11/day. Strictly inferior to strawberries ($122.79/day) and melons ($119.36/day) on mature land.

---

## 4. Why Past Crop Experiments Failed & Lessons Preserved

```
+-------------------------------------------------------------------------------+
|                       HISTORICAL EXPERIMENT EVIDENCE                          |
+------------------------------------+------------------------------------------+
| P2.0 Second Melon Tranche          | REJECTED (-$42/game, p=0.91)             |
| Mechanism: Planting 2nd wave of    | Causal Root: Tied up 8-12 tiles for 8    |
| melons on Days 9-10.               | days during Days 9-17, displacing ongoing|
|                                    | strawberries ($122/day) and herd pastures|
+------------------------------------+------------------------------------------+
| P2.1 Dynamic Strawberry Cap        | REJECTED (+$110/game, CI crossed zero)   |
| Mechanism: Capping strawberries    | Causal Root: Strawberry market price was |
| based on town shop unlocks.        | highly resilient ($245 avg); town demand |
|                                    | consumed 438 units. Artificial cap hurt. |
+------------------------------------+------------------------------------------+
| P2.3 Marginal Wheat Allocation     | PROMOTED (+$445 to +$452/game, p<0.05)   |
| Mechanism: Replanting vacant tiles | Causal Root: Replaced idle empty tiles   |
| with 4-day wheat on Days 20-25.    | with profitable $55/day crops that mature|
|                                    | cleanly before Day 29 cutoff.            |
+------------------------------------+------------------------------------------+
```

---

## 5. Potential Crop Opportunities Evaluated

### Opportunity 1: Expanding Strawberry Acreage in NW+NE Core
- **Hypothesis**: Could we convert wheat tiles to more strawberries?
- **Analysis**:
  - The 2Q core currently maintains ~14–15 strawberry tiles, ~10 animal tiles (pastures/coops), and ~15–18 wheat tiles.
  - Converting wheat tiles to strawberries would reduce homegrown wheat production.
  - As demonstrated in Report 1, the herd already requires 850 units of wheat feed. If wheat acreage is reduced, feed purchases must increase dollar-for-dollar from the market, driving up market wheat prices and creating shed congestion.
  - Furthermore, labor simulation in P3 showed that strawberries require daily watering and alternate-day harvesting, consuming ~22 worker-turns/day. Adding 10 more strawberry tiles would push daily crop labor above available turns, risking unwatered penalty streaks.
- **Verdict**: **Feasibility Low / Economically Neutral to Negative**.

### Opportunity 2: Terminal Carrot Squeeze (Days 26–27)
- **Hypothesis**: Replanting vacant tiles with 2-day carrots on Days 26–27 to harvest on Day 28/29.
- **Analysis**:
  - A carrot planted on Day 26 matures on Day 28 (yield 4 units @ $38.67 = $154.68 revenue - $15 seed = +$139.68 net profit).
  - Vacant tiles on Day 26 average 4.6 tiles; on Day 27 average 13.2 tiles.
  - If 5–8 carrot tiles are planted on Day 26, gross theoretical gain is +$700–$1,100.
  - **Risk**: Days 28 and 29 are peak liquidation and harvest days (293 shed deliveries). Workers must spend turns tilling, planting, and watering carrots during the exact hours when herd liquidation and shed dumping are required.
- **Verdict**: **Plausible narrow candidate (~+$300–$600 net)**, but limited upside. Cannot bridge the $28k gap alone.
