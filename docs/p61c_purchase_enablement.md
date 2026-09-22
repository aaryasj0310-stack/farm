# P6.1-C Capital Allocation & Purchase Enablement

## Executive Summary

A core question in P6.1-C is whether earlier liquidity from pre-midnight shed sales actively unlocked capital expenditures (earlier land purchases, additional workers, or accelerated livestock purchases) that could explain the +$1,439.86 cash gain.

This investigation tracked every purchase executed across all 200 games, cross-referencing timestamps, cash balances, and counterfactual control schedules.

Key conclusions:
1. **Zero Acceleration of Structural Capital (Land & Workers)**:
   - Land expansion ($1,000.00) occurred at the identical step in both Control and Treatment across all 100 scenario pairs.
   - Worker hiring schedules were identical; both Control and Treatment reached maximum crew size (6 workers) during Days 0–5 before any divergence occurred.
2. **Livestock Purchases Were Nearly Identical**:
   - Total animal purchase expenditures differed by only **-$14.00/game** (Treatment spent $4,889.00 vs Control $4,903.00).
   - Although 105 Cow and 89 Sheep purchases were flagged as `liquidity_enabled` (occurring when Treatment held a positive cash advantage), they were **re-timed purchases** of the baseline animal quota, not expansion beyond carrying capacity.
3. **Seed Purchases Were Re-Timed Routine Replacements**:
   - Total seed expenditures differed by only **-$4.90/game** ($4,680.50 vs $4,685.40).
   - Variations in seed purchases were step-level timing artifacts (e.g. planting a carrot tile at Hour 14 instead of Hour 16) resulting from minor schedule drift.
4. **Summary**: The +$1,439.86 gain was **NOT** driven by structural capital investment enabled by early liquidity.

---

## 1. Concrete Purchase Enablement Audit

Every purchase executed by Treatment was compared against Control. If Treatment executed a purchase at a step where Control did not, and Treatment had $\text{Cash}_{\text{Treat}} > \text{Cash}_{\text{Ctrl}}$, the transaction was classified as `LIQUIDITY_ENABLED`.

| Purchase Category | Total Treatment-Only Executions | Liquidity-Enabled Executions | Mean Expenditure Delta (T - C) | Capital Expansion Impact |
| :--- | :---: | :---: | :---: | :--- |
| **Land Expansion** | **0** | **0** | **$0.00** | **None** (identical step execution) |
| **Worker Hires** | **0** | **0** | **-$10.08** | **None** (crew maxed by Day 5) |
| **Cows (`BUY_ANIMAL_COW`)** | 129 | 105 | -$10.00 | Minor purchase step re-timing |
| **Sheep (`BUY_ANIMAL_SHEEP`)** | 123 | 89 | -$4.00 | Minor purchase step re-timing |
| **Feed Wheat (`BUY_PRODUCT_WHEAT`)** | 918 | 599 | **-$749.18** | **Fewer purchases** due to shed buffer |
| **Wheat Seed (`BUY_SEED_WHEAT`)** | 3,145 | 1,936 | -$1.20 | Re-timed routine replanting |
| **Carrot Seed (`BUY_SEED_CARROT`)** | 468 | 293 | -$0.80 | Re-timed routine replanting |
| **Melon Seed (`BUY_SEED_MELON`)** | 188 | 110 | -$1.10 | Re-timed routine replanting |
| **Strawberry Seed (`BUY_SEED_STRAWBERRY`)** | 198 | 124 | -$1.50 | Re-timed routine replanting |
| **Tomato Seed (`BUY_SEED_TOMATO`)** | 66 | 42 | -$0.30 | Re-timed routine replanting |
| **Total** | **5,235** | **3,298** | **-$778.16** | **Expenditure Savings (Not Investment)** |

---

## 2. In-Depth Operational Examination

### 2.1 Land and Labor Constraints
In Kaggriculture, land expansion is a one-time capital purchase ($1,000) that unlocks additional farm plots. In both Control and Treatment:
- Land expansion was purchased on Day 4 or 5 as soon as early wheat revenues cleared.
- Because Treatment and Control are identical through Day 10 ($t=261$), Treatment had zero liquidity advantage when land was purchased.
- Similarly, all 6 workers were hired during Days 1–5 in both variants.

### 2.2 Livestock Carrying Capacity
Livestock capacity is bounded by farm geography, pen layout, and feed logistics. 
- Across all 100 pairs, both Control and Treatment stabilized at 4–5 cows and 3–4 sheep.
- The 105 liquidity-enabled cow purchases did not increase total herd size; they merely shifted the specific hour on Days 11–18 when a replacement animal was acquired.
- The net animal expenditure delta was **-$14.00** across the 100 pairs, proving that Treatment spent slightly *less* on animals than Control overall.

### 2.3 The Feed Wheat Paradox
The line item with the largest number of liquidity-enabled purchase events (599 events) was `BUY_PRODUCT_WHEAT` (feed wheat for livestock).
However, Treatment's total expenditure on feed wheat was **$749.18 lower** than Control:
- Control bought **877.70 units** of feed wheat ($30,780.44).
- Treatment bought **854.54 units** of feed wheat ($30,031.26).
- Net difference: **-23.16 units (-$749.18)**.

The 599 "treatment-only" feed purchase events were instances where Treatment bought smaller batches on different days because its shed buffer preserved farm-grown wheat longer.

---

## 3. Conclusion on Capital Allocation

The empirical evidence definitively rejects the hypothesis that earlier liquidity unlocked profitable capital investments. 

Treatment's net expenditure delta across all capital and operational categories was **negative (-$778.16)**. Treatment did not invest more capital; it spent less capital, specifically by avoiding town feed wheat purchases.
