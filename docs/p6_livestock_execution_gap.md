# P6 Livestock Execution Loss & Care Yield Gap (P6-R Corrected)

## 1. Executive Summary & Epistemic Verdict

Livestock is the financial backbone of the baseline agent, generating **$50,240.98/game** in direct revenue ($34,533.39 Milk + $15,707.59 Wool).
However, revenue is lost due to:
1. **Missed daily care operations** (forfeiting output multipliers).
2. **Shed overflow discards** of harvested livestock products ($2,061.08/game destroyed).

```
                          COW MILK FUNNEL (100-Game Mean)
  ┌────────────────────────────────────────────────────────┐
  │ Mechanically Max Potential Output:      166.14 units    │
  │ Actual Units Produced:                  150.33 units    │ (-15.81 missed care gap)
  │ Actual Units Harvested:                 147.00 units    │ (-3.33 unharvested)
  │ Discarded at Shed Overflow:               4.19 units    │ (-$1,013.91 discard loss)
  │ Final Units Sold at Market:             142.71 units    │ (Realized Cash: $34,533.39)
  └────────────────────────────────────────────────────────┘
```

> [!IMPORTANT]
> **Epistemic Classification: `MEASURED FACT`**
> - Under engine ground truth rules, Cow mechanical maximum is **166.14 units/game** (production efficiency 90.48%) and Sheep mechanical maximum is **90.26 units/game** (production efficiency 87.38%).
> - Actual production **never** exceeds mechanical maximum.
> - Harvest completion efficiency is exceptionally high: **97.78% for milk** and **97.91% for wool**.
> - The 3.51 milk and 1.68 wool unharvested at Turn 720 spawned at the Step 719 EOD refresh after the episode completed; they were physically unharvestable under engine rules.

---

## 2. Herd Inventory & Lifecycle Summary (100 Games)

| Animal Metric | Cows (`COW`) | Sheep (`SHEEP`) |
| :--- | :---: | :---: |
| **Animals Placed / Game** | 6.73 | 4.45 |
| **Total Feed Events / Game** | 139.14 | 74.76 |
| **Total Care Events / Game** | 125.05 | 71.49 |
| **Missed Care Opportunities** | **17.10** | **7.59** |
| **Missed Production-Relevant Cares** | **15.81** | **11.39** |
| **Mechanically Max Yield / Game** | **166.14** | **90.26** |
| **Units Produced / Game** | **150.33** | **78.87** |
| **Production Yield Efficiency** | **90.48%** | **87.38%** |
| **Units Harvested / Game** | **147.00** | **77.22** |
| **Harvest Completion Efficiency** | **97.78%** | **97.91%** |
| **Unharvested Output at Season End** | 3.51 | 1.68 |
| **Units Discarded at Shed Overflow** | 4.19 | 4.80 |
| **Units Sold at Market** | 142.71 | 72.00 |
| **Mean Realized Sale Price** | **$241.98** | **$218.16** |
| **Animal Escapes (Starvation)**| **0.00** | **0.00** |

---

## 3. Root Cause Analysis & Corrections

### 1. Missed Care Bonus Gap (15.81 Cow, 11.39 Sheep)
- **Mechanism**: In Kaggriculture, caring for an animal before its production interval adds $+1$ bonus yield unit.
- **Occurrence**: Cows missed 15.81 production-relevant cares/game; Sheep missed 11.39 production-relevant cares/game.
- **Cause**: Workers were dispatched to distant NE crop fields or caught in transit gridlock during Hours 18–23, failing to execute `CARE` before the daily midnight refresh.
- **Gross Reference Value**: $\sim 27.20 \text{ units} \approx \mathbf{\$4,809.52}$ gross theoretical value. Feasible recoverable value is **+$800.00 to +$1,500.00 / game** with dedicated care route prioritization.

### 2. End-of-Season Unharvested Products: Refutation of Harvest Opportunity
- At Turn 720 (Season End), our pastures showed:
  - **3.51 units of Cow Milk**
  - **1.68 units of Sheep Wool**
- **Correction**: P6-R diagnostic hooks proved that before the Step 719 EOD refresh, pastures contained **0.00 mature units**. These units spawned after the game ended and were physically impossible to harvest. Recoverable value is **$0.00** (`NOT A REAL OPPORTUNITY`).

### 3. Shed Discard Destruction: The Real Loss
- Harvested milk and wool deposited at Day-End shed drops encountered full sheds (100 units):
  - **4.19 units of Milk discarded** ($\times \$241.98 = \mathbf{\$1,013.91}$)
  - **4.80 units of Wool discarded** ($\times \$218.16 = \mathbf{\$1,047.17}$)
- This is physical destruction of goods that were already fed, cared for, and harvested. Preventing shed discards recovers **+$1,800 to +$2,060 / game** in livestock value alone.

---

## 4. Recoverable-Value Ledger: Livestock

| Loss Category | Physical Units | Reference Valuation | Feasible Recoverable Cash | Epistemic Status |
| :--- | :---: | :---: | :---: | :---: |
| **Shed Discarded Milk** | 4.19 u | $1,013.91 | **$900.00 – $1,013.91** | `MEASURED FACT` (Addressed in P6.1) |
| **Shed Discarded Wool** | 4.80 u | $1,047.17 | **$950.00 – $1,047.17** | `MEASURED FACT` (Addressed in P6.1) |
| **Missed Care Yield Bonus**| 27.20 u | $4,809.52 | **$800.00 – $1,500.00** | `UNTESTED HYPOTHESIS` |
| **Unharvested Day-29 Assets**| 5.19 u | $1,215.86 | **$0.00 (Refuted)** | `NOT A REAL OPPORTUNITY` |
| **Total Livestock Opportunity** | — | — | **$2,650.00 – $3,561.08** | — |
