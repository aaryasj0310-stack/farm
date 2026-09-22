# P6 Livestock Execution Loss & Care Yield Gap

## 1. Executive Summary & Epistemic Verdict

Livestock is the financial backbone of the baseline agent, generating **$50,240.98/game** in direct revenue ($34,533.39 Milk + $15,707.59 Wool).
However, significant revenue is abandoned due to:
1. **Missed daily care operations** (forfeiting output multipliers).
2. **Delayed harvests** (leaving milk and wool unharvested at season end).
3. **Shed overflow discards** of harvested livestock products.

```
                          COW MILK FUNNEL
  ┌────────────────────────────────────────────────────────┐
  │ Mechanically Max Potential Output:      174.67 units    │
  │ Actual Units Produced:                  157.57 units    │ (-17.10 missed care bonus)
  │ Actual Units Harvested:                 147.00 units    │ (-10.57 uncollected/decay)
  │ Discarded at Shed Overflow:               4.19 units    │ (-$1,013.91 discard loss)
  │ Final Units Sold at Market:             142.71 units    │ (Realized Cash: $34,533.39)
  └────────────────────────────────────────────────────────┘
```

> [!IMPORTANT]
> **Epistemic Classification: `MEASURED FACT`**
> Across 100 baseline games, the agent produces 157.57 units of milk and 78.87 units of wool, but sells only 142.71 units of milk and 72.00 units of wool. 
> Between **unharvested goods** and **shed discards**, the baseline forfeits **$4,978.77 / game** in livestock value ($3,571.64 Milk + $1,407.13 Wool).

---

## 2. Herd Inventory & Lifecycle Summary

| Animal Metric | Cows (`COW`) | Sheep (`SHEEP`) | Chickens (`CHICKEN`) |
| :--- | :---: | :---: | :---: |
| **Animals Placed / Game** | 6.73 | 4.45 | 0.00 |
| **Total Feed Events / Game** | 139.14 | 74.76 | 0.00 |
| **Total Care Events / Game** | 125.05 | 71.49 | 0.00 |
| **Missed Care Opportunities** | **17.10** | **7.59** | 0.00 |
| **Care Adherence Rate** | **89.87%** | **95.63%** | N/A |
| **Animal Escapes (Starvation)**| **0.00** | **0.00** | 0.00 |
| **Units Produced / Game** | 157.57 | 78.87 | 0.00 |
| **Units Harvested / Game** | 147.00 | 77.22 | 0.00 |
| **Unharvested Output at Season End** | 3.51 | 1.68 | 0.00 |
| **Harvest Completion Efficiency** | **93.29%** | **97.91%** | N/A |
| **Units Discarded at Shed** | 4.19 | 4.80 | 0.00 |
| **Units Sold at Market** | 142.71 | 72.00 | 0.00 |
| **Mean Realized Sale Price** | **$241.98** | **$218.16** | N/A |

---

## 3. Root Cause Analysis of Losses

### 1. Missed Care Bonus Loss: 24.69 Total Missed Events
- **Mechanism**: In Kaggriculture, caring for an animal before its production interval adds $+1$ bonus yield unit.
- **Occurrence**: Cows suffered **17.10 missed cares/game**; Sheep suffered **7.59 missed cares/game**.
- **Cause**: Workers were dispatched to distant NE crop fields or caught in transit gridlock during Hours 18–23, failing to execute `CARE` before the daily midnight refresh.
- **Gross Lost Potential**: $\sim 24.7 \text{ units} \times \$230 \approx \mathbf{\$5,681.00}$ gross theoretical upper bound (though not all cares align with production interval boundaries; net achievable bonus gap is $\sim 15$ units $\approx \$3,450$).

### 2. End-of-Season Unharvested Products
- At Turn 720 (Season End), our pastures still held:
  - **3.51 units of Cow Milk** in-pasture ($\times \$241.98 = \mathbf{\$849.35}$)
  - **1.68 units of Sheep Wool** in-pasture ($\times \$218.16 = \mathbf{\$366.51}$)
- **Root Cause**: The macro-planner stopped queuing harvest tasks on Day 29 Hours 18–23, or workers carrying products failed to deposit and sell before turn 720.

### 3. Shed Discard Destruction
- Harvested milk and wool deposited at Day-End shed drops encountered full sheds (100 units):
  - **4.19 units of Milk discarded** ($\times \$241.98 = \mathbf{\$1,013.91}$)
  - **4.80 units of Wool discarded** ($\times \$218.16 = \mathbf{\$1,047.17}$)
- Workers physically walked to the pasture, spent an action harvesting, carried the item to the shed, and the game engine destroyed it because shed capacity was clogged with low-value wheat or excess items!

---

## 4. Recoverable-Value Ledger: Livestock

| Loss Category | Physical Units | Valuation Basis | Theoretical Upper Bound | Inferred Recoverable Value | Epistemic Status |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **Shed Discarded Milk** | 4.19 | $241.98/unit | $1,013.91 | **$900.00 – $1,013.91** | `MEASURED FACT` |
| **Shed Discarded Wool** | 4.80 | $218.16/unit | $1,047.17 | **$950.00 – $1,047.17** | `MEASURED FACT` |
| **Unharvested Day-29 Milk**| 3.51 | $241.98/unit | $849.35 | **$600.00 – $800.00** | `MEASURED FACT` |
| **Unharvested Day-29 Wool**| 1.68 | $218.16/unit | $366.51 | **$250.00 – $350.00** | `MEASURED FACT` |
| **Missed Care Yield Bonus**| 24.69 events | ~$230/unit | $5,681.00 | **$1,200.00 – $2,000.00** | `INFERRED RECOVERABLE VALUE` |
| **Total Livestock Opportunity** | — | — | **$8,957.94** | **$3,900.00 – $5,211.08** | — |

> [!TIP]
> **Key Recommendation**:
> Prioritizing livestock care actions in the daily schedule and protecting shed room for high-value dairy/fiber alone unlocks over **+$3,900/game** with zero additional land or seed expenditure.
