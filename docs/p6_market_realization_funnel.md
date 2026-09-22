# P6 Market Realization Funnel Audit (P6-R Corrected)

## 1. Executive Summary & Epistemic Verdict

The market realization funnel measures how efficiently physical goods progress from **Production $\rightarrow$ Harvesting $\rightarrow$ Shed Storage $\rightarrow$ Market Sale $\rightarrow$ Cash Realization**.

```
                        GROSS VALUE PRODUCTION FUNNEL (100-Game Mean)
    ┌────────────────────────────────────────────────────────────────────────┐
    │ Potential Output Produced:              ~$154,300 / game               │
    │ Harvested & Deposited:                  ~$151,100 / game               │
    │ Destroyed by Shed Overflow Discards:     -$6,026.53 / game             │
    │ Unharvested at Season End (Terminal):    -$1,456.30 / game             │
    │ TOTAL REALIZED CASH REVENUE:            $147,457.41 / game             │
    └────────────────────────────────────────────────────────────────────────┘
```

> [!IMPORTANT]
> **Epistemic Classification: `MEASURED FACT`**
> - The baseline's market pricing and drip-sell algorithm is highly effective, monetizing harvested goods with minimal price slippage.
> - Realized revenue leakage is overwhelmingly driven by **shed overflow discards ($6,026.53 reference value)**.
> - Final-day unharvested assets ($1,456.30) are terminal spawns that cannot be harvested under engine rules.
> - Fertilizer disposal backlog claims ($800–$1,400) are fully refuted: fertilizer inventory conservation closed with 0.00 error.

---

## 2. Comprehensive Product Funnels (100-Game Panel)

| Product | Produced Units | Harvested Units | Discarded Units | Sold Units | Realized Cash Revenue | Mean Realized Price | Realization % (Sold / Produced) |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Wheat** | 0.00* | 381.91 | 19.23 | 1,010.72 | \$36,837.79 | \$36.45 | N/A (Trading Hub) |
| **Milk** | 150.33 | 147.00 | 4.19 | 142.71 | \$34,533.39 | \$241.98 | **94.93%** |
| **Melon** | 93.43 | 93.43 | 2.16 | 91.27 | \$21,761.63 | \$238.43 | **97.69%** |
| **Strawberry**| 84.88 | 84.88 | **9.11** | 75.73 | \$18,842.10 | \$248.81 | **89.22%** |
| **Wool** | 78.87 | 77.22 | 4.80 | 72.00 | \$15,707.59 | \$218.16 | **91.29%** |
| **Fertilizer**| 221.23 | 218.13 | 4.73 | 187.76 | \$15,278.36 | \$81.37 | **84.87%** (23.7 used on crops) |
| **Carrot** | 71.08 | 71.08 | 1.59 | 69.10 | \$2,770.70 | \$40.10 | **97.21%** |
| **Tomato** | 23.61 | 23.61 | 0.46 | 23.15 | \$1,725.85 | \$74.55 | **98.05%** |
| **TOTAL** | — | — | **46.31** | — | **\$147,457.41** | — | — |

*\*Wheat produced on tiles is captured in harvested units (381.91 u).*

---

## 3. Detailed Leakage Analysis & Corrections

### 1. Strawberry Discard Chokepoint: Verified 10.7% Loss
- **Harvested**: 84.88 units
- **Discarded**: **9.11 units** (10.73% of entire crop harvest!)
- **Sold**: 75.73 units
- **Leakage Value**: **$2,266.63 lost per game**
- **Root Cause**: Batch harvesting of strawberries (3–6 units/harvest) into a full shed immediately triggers midnight discards. This is the primary single target for P6.1.

### 2. Fertilizer: Refutation of the "Disposal Deficit"
- **Produced**: 221.23 units | **Collected**: 218.13 units
- **Outflows**:
  * **Sold**: 187.76 units
  * **Used on Crops**: 23.67 units
  * **Discarded in Shed**: 4.73 units
  * **Ending in Worker Inventory**: 1.97 units
  * **Ending Shed Inventory**: **0.00 units**
  * **Conservation Error**: **0.000000** ($\text{Error} = 0$)
- **Verdict**: Zero fertilizer backlog exists. Previous claim of market slot exhaustion bumping fertilizer is refuted. Market rejections were $<0.006$/hour.

### 3. Season-End Unharvested Assets: Refutation of Harvest Gap
- At Step 720 (Season End), tiles showed 3.51 milk, 1.68 wool, 3.45 wheat, 2.86 carrot.
- **Correction**: Pre-EOD diagnostic at Step 719 showed **0.00 mature units**. All units spawned at Step 719 EOD refresh after the simulation terminated. Recoverable value is **$0.00** (`NOT A REAL OPPORTUNITY`).

---

## 4. Recoverable Value Ledger: Realization Funnel

| Leakage Category | Measured Physical Loss | Reference Valuation | Feasible Recoverable Cash | Epistemic Status |
| :--- | :---: | :---: | :---: | :---: |
| **Shed Discard Prevention (P6.1)** | 46.31 units | $6,026.53 | **$2,500.00 – $4,000.00** | `MEASURED FACT` / `UNTESTED HYPOTHESIS` |
| **Fertilizer Backlog** | 0.00 units | $0.00 | **$0.00 (Refuted)** | `NOT A REAL OPPORTUNITY` |
| **Unharvested Day-29 Assets** | 11.53 units | $1,456.30 | **$0.00 (Refuted)** | `NOT A REAL OPPORTUNITY` |
| **Total Realization Funnel Potential**| — | — | **$2,500.00 – $4,000.00** | — |
