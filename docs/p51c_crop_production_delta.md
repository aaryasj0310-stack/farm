# Kaggriculture P5.1-C — Crop Production Lifecycle Delta

## 1. Executive Summary

This report provides the full empirical accounting of crop production lifecycle metrics between the baseline Control (`536f1e7`) and the P5.1 Two-Cycle Carrot Treatment across all 100 matched pairs (200 live games).

### Key Empirical Findings:
1. **Direct Substitution Accounting**:
   - Treatment reduced wheat plantings by **−11.26 plantings / game** (99.66 $\rightarrow$ 88.40) and increased carrot plantings by **+13.29 plantings / game** (26.32 $\rightarrow$ 39.61).
   - This yielded **+37.61 additional harvested carrots** (70.15 $\rightarrow$ 107.76) at the direct cost of **−41.84 fewer harvested wheat units** (380.20 $\rightarrow$ 338.36).
2. **Crop Waterings Balanced**:
   - Wheat waterings dropped by **−49.58 waterings / game** (455.23 $\rightarrow$ 405.65).
   - Carrot waterings increased by **+46.06 waterings / game** (93.25 $\rightarrow$ 139.31).
   - Total crop waterings panel-wide slightly decreased by **−4.69 waterings / game**.
3. **Zero Weed Casualties**:
   - Weed deaths were exactly **0.00** across all crops in both Control and Treatment across all 200 games. The scheduler never let crops die to weeds.
4. **Decay and Unharvested End Losses**:
   - Unharvested carrots at Day 30 increased marginally from 1.58 to 2.01 (+0.43 units).
   - Carrot decay losses increased from 1.24 to 1.53 (+0.29 units).
   - These small losses reflect tight late-season deadlines but represent less than $30 in total value.

---

## 2. Complete Crop Lifecycle Accounting Table

The table below compiles panel-wide mean values per game across all 100 matched pairs:

| Crop | Metric | Control Mean | Treatment Mean | Delta ($\Delta$) | Unit Economic Impact |
| :--- | :--- | :---: | :---: | :---: | :---: |
| **WHEAT** | Planted Tiles | 99.66 | 88.40 | **−11.26** | Seed savings: +$108.80 |
| | Waterings | 455.23 | 405.65 | **−49.58** | Labor freed |
| | Harvest Events | 98.15 | 87.14 | **−11.01** | Less harvest actions |
| | **Harvested Units** | **380.20** | **338.36** | **−41.84** | **Grain deficit** |
| | Weed Deaths | 0.00 | 0.00 | **0.00** | No weed deaths |
| | Decay Lost Units | 1.87 | 1.61 | **−0.26** | Minor decay |
| | Unharvested at Day 30 | 3.26 | 2.63 | **−0.63** | Fewer late unharvested |
| :--- | :--- | :---: | :---: | :---: | :---: |
| **CARROT** | Planted Tiles | 26.32 | 39.61 | **+13.29** | Seed cost: −$246.40 |
| | Waterings | 93.25 | 139.31 | **+46.06** | Additional watering |
| | Harvest Events | 25.12 | 38.19 | **+13.07** | Harvest trips |
| | **Harvested Units** | **70.15** | **107.76** | **+37.61** | **Gross Rev: +$1,516.36** |
| | Weed Deaths | 0.00 | 0.00 | **0.00** | No weed deaths |
| | Decay Lost Units | 1.24 | 1.53 | **+0.29** | ~$12 lost |
| | Unharvested at Day 30 | 1.58 | 2.01 | **+0.43** | ~$18 lost |
| :--- | :--- | :---: | :---: | :---: | :---: |
| **TOMATO** | Planted Tiles | 4.47 | 4.47 | **0.00** | Invariant |
| | Waterings | 42.02 | 41.87 | **−0.15** | Negligible |
| | Fertilized Events | 4.64 | 4.67 | **+0.03** | Negligible |
| | Harvest Events | 10.99 | 11.05 | **+0.06** | Negligible |
| | Harvested Units | 23.62 | 23.83 | **+0.21** | Negligible |
| | Weed Deaths | 0.00 | 0.00 | **0.00** | No weed deaths |
| | Decay Lost Units | 1.83 | 1.83 | **0.00** | Invariant |
| | Unharvested at Day 30 | 0.01 | 0.00 | **−0.01** | Invariant |
| :--- | :--- | :---: | :---: | :---: | :---: |
| **STRAWBERRY**| Planted Tiles | 13.48 | 13.48 | **0.00** | Invariant |
| | Waterings | 179.90 | 178.97 | **−0.93** | Negligible |
| | Fertilized Events | 19.64 | 19.74 | **+0.10** | Negligible |
| | Harvest Events | 40.01 | 40.00 | **−0.01** | Invariant |
| | Harvested Units | 85.26 | 85.29 | **+0.03** | Invariant |
| | Weed Deaths | 0.00 | 0.00 | **0.00** | No weed deaths |
| | Decay Lost Units | 0.83 | 1.19 | **+0.36** | ~$90 lost |
| | Unharvested at Day 30 | 0.02 | 0.04 | **+0.02** | Invariant |
| :--- | :--- | :---: | :---: | :---: | :---: |
| **MELON** | Planted Tiles | 15.57 | 15.57 | **0.00** | Invariant |
| | Waterings | 162.60 | 162.61 | **+0.01** | Invariant |
| | Harvest Events | 15.57 | 15.57 | **0.00** | Invariant |
| | Harvested Units | 92.97 | 92.97 | **0.00** | Invariant |
| | Weed Deaths | 0.00 | 0.00 | **0.00** | No weed deaths |
| | Decay Lost Units | 0.20 | 0.20 | **0.00** | Invariant |
| | Unharvested at Day 30 | 0.00 | 0.00 | **0.00** | Invariant |

---

## 3. The Yield and Substitution Ratio

In the baseline strategy:
- Wheat planted on Days 21–23 is watered repeatedly through Day 27. It yields **4 to 6 units per tile** upon harvest.
- Specifically, the 11.26 wheat plantings that were replaced produced an average of:
  $$\frac{41.84 \text{ harvested wheat}}{11.26 \text{ replaced plantings}} = \mathbf{3.72 \text{ wheat units per tile}}$$
- In contrast, the replacement carrot cycles produced:
  $$\frac{37.61 \text{ harvested carrots}}{13.29 \text{ extra carrot plantings}} = \mathbf{2.83 \text{ carrot units per planting}}$$

Because wheat yield per planting (3.72 units) exceeded carrot yield per planting (2.83 units), and because wheat was replaced across multiple failed or single-cycle carrot attempts, the farm produced **41.84 fewer grain units** in exchange for only **37.61 carrot units**.

This unfavorable physical substitution directly starved the livestock feed pipeline.
