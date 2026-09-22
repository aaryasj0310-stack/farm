# P6 Market Realization Funnel Audit

## 1. Executive Summary & Epistemic Verdict

The market realization funnel measures how efficiently physical goods progress from **Production $\rightarrow$ Harvesting $\rightarrow$ Shed Storage $\rightarrow$ Market Sale $\rightarrow$ Cash Realization**.

```
                           GROSS VALUE PRODUCTION FUNNEL
   ┌────────────────────────────────────────────────────────────────────────┐
   │ Potential Output Produced:              ~$158,500 / game               │
   │ Harvested & Deposited:                  ~$154,800 / game               │
   │ Destroyed by Shed Overflow Discards:     -$6,026.53 / game             │
   │ Unharvested at Season End:               -$1,385.00 / game             │
   │ TOTAL REALIZED CASH REVENUE:            $147,457.41 / game             │
   └────────────────────────────────────────────────────────────────────────┘
```

> [!IMPORTANT]
> **Epistemic Classification: `MEASURED FACT`**
> The baseline's market pricing and timing algorithm is highly effective, achieving **over 99% of theoretical base price** on realized sales (e.g. Strawberry at \$248.81 vs \$250 base, Milk at \$241.98 vs \$240 base).
> Market realization loss is almost entirely driven by **pre-sale physical destruction ($6.0k discards)** and **unharvested season-end leftovers ($1.4k)**, not market price degradation.

---

## 2. Comprehensive Product Funnels

| Product | Produced / Acquired | Harvested Units | Discarded Units | Sold Units | Realized Cash Revenue | Mean Realized Price | Conversion Efficiency (Sold / Harvested) |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Wheat** | 1,244.93 | 381.91 | 19.23 | 1,010.72 | \$36,837.79 | \$36.45 | N/A (Trading Hub) |
| **Milk** | 157.57 | 147.00 | 4.19 | 142.71 | \$34,533.39 | \$241.98 | **97.08%** |
| **Melon** | 93.43 | 93.43 | 2.16 | 91.27 | \$21,761.63 | \$238.43 | **97.69%** |
| **Strawberry**| 84.88 | 84.88 | **9.11** | 75.73 | \$18,842.10 | \$248.81 | **89.22%** |
| **Wool** | 78.87 | 77.22 | 4.80 | 72.00 | \$15,707.59 | \$218.16 | **93.24%** |
| **Fertilizer**| 221.23 | 218.13 | 4.73 | 187.76 | \$15,278.36 | \$81.37 | **86.08%** |
| **Carrot** | 71.08 | 71.08 | 1.59 | 69.10 | \$2,770.70 | \$40.10 | **97.21%** |
| **Tomato** | 23.61 | 23.61 | 0.46 | 23.15 | \$1,725.85 | \$74.55 | **98.05%** |
| **TOTAL** | — | — | **46.31** | — | **\$147,457.41** | — | — |

---

## 3. Detailed Leakage Analysis

### 1. Strawberry: The 10.8% Leakage Severe Chokepoint
- **Harvested**: 84.88 units
- **Discarded**: **9.11 units** (10.73% of entire crop harvest!)
- **Sold**: 75.73 units
- **Revenue**: \$18,842.10
- **Leakage Value**: **$2,266.63 lost per game**
- **Analysis**: Strawberries mature in large multi-unit clusters. Workers harvest 12–18 units in a single afternoon and dump them into a shed that already contains 85+ units of wheat and fertilizer. Over 1 out of every 10 harvested strawberries is discarded into the void!

### 2. Fertilizer: The 33.47 Unit Disposal Deficit
- **Produced**: 221.23 units
- **Harvested**: 218.13 units
- **Sold**: 187.76 units
- **Discarded**: 4.73 units
- **Retained in Worker Inventory**: 1.97 units
- **Unsold Output**: 33.47 units ($\sim \mathbf{\$2,723.00}$ unrealized value)
- **Analysis**: The market order builder limits sales to 10 slots per turn. Because animal and crop sales take priority, fertilizer orders are constantly bumped from the queue, leaving valuable fertilizer sitting in workers' pockets or the shed until discarded.

### 3. Season-End Unharvested Assets (Turn 720)
At the final buzzer (Hour 23, Day 29), the following mature assets remained in the field:
- **Milk**: 3.51 units ($\times \$241.98 = \mathbf{\$849.35}$)
- **Wool**: 1.68 units ($\times \$218.16 = \mathbf{\$366.51}$)
- **Wheat**: 3.45 units ($\times \$36.45 = \mathbf{\$125.75}$)
- **Carrot**: 2.86 units ($\times \$40.10 = \mathbf{\$114.69}$)
- **Total Unharvested Season-End Cash**: **$1,456.30 / game**

---

## 4. Recoverable Value & Operational Verdict

| Leakage Category | Measured Physical Loss | Valuation Basis | Theoretical Upper Bound | Inferred Recoverable Value |
| :--- | :---: | :---: | :---: | :---: |
| **High-Value Discards (Straw/Wool/Milk/Melon)** | 20.26 units | Realized Prices | $4,842.72 | **$3,200.00 – $4,200.00** |
| **Unharvested Day-29 Assets** | 11.50 units | Realized Prices | $1,456.30 | **$900.00 – $1,200.00** |
| **Fertilizer Backlog Realization** | 33.47 units | Realized Prices | $2,723.49 | **$800.00 – $1,500.00** |
| **Total Realization Funnel Opportunity** | — | — | **$9,022.51** | **$4,900.00 – $6,900.00** |

> [!TIP]
> **Key Recommendation**:
> The realization funnel is losing ~\$5,000/game not because of weak market demand, but because of **poor queue arbitration**: low-priority fertilizer clogs shed space, preventing strawberry drops, while endgame harvesting shuts down 6 hours too early.
