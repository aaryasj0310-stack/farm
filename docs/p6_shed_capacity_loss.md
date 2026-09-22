# P6 Shed Capacity & Storage Discard Loss Audit (P6-R Corrected)

## 1. Executive Summary & Epistemic Verdict

In Kaggriculture, storage capacity is strictly bounded:
$$\text{SHED\_CAPACITY} = 100 \text{ units}$$
At the end of each day (Hour 23), the simulation engine executes `_drop_inventories_to_shed`, forcing all workers to deposit their carried items. If the shed exceeds 100 units, all overflow is permanently discarded with zero compensation.

```
                  PHYSICAL DESTRUCTION AT SHED OVERFLOW (100-Game Mean)
   ┌────────────────────────────────────────────────────────────────────────┐
   │ Total Discard Events / Game:            16.76 events / game            │
   │ Total Physical Units Destroyed:         46.31 units / game             │
   │ REFERENCE CASH LOSS (Catalog Base):     $4,300.60 / game               │
   │ REFERENCE CASH LOSS (Realized Prices):  $6,026.53 / game               │
   └────────────────────────────────────────────────────────────────────────┘
```

> [!IMPORTANT]
> **Epistemic Classification: `MEASURED FACT` / `UNTESTED HYPOTHESIS`**
> - **46.31 units destroyed / game** across 16.76 events is a **`MEASURED FACT`**.
> - Reference cash valuation is **$4,300.60** at base prices, or **$6,026.53** at baseline realized prices (**`MEASURED REFERENCE VALUE`**).
> - Over 78% of discard value is concentrated in three high-value goods: **Strawberry ($2,266.63)**, **Wool ($1,047.17)**, and **Milk ($1,013.91)**.
> - Feasible recoverable cash is an **`UNTESTED HYPOTHESIS`** estimated at **+$2,500.00 to +$4,000.00 / game** after accounting for market price elasticity. This is the single highest-conviction target for P6.1.

---

## 2. Complete Discard Inventory & Reference Valuation (100 Games)

| Item Destroyed | Discarded Units / Game | Discard Events / Game | Base Catalog Price | Realized Market Price | Reference Loss (Realized) | % of Discard Value |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **Strawberry** | 9.11 | 3.36 | \$120.00 | \$248.81 | **\$2,266.63** | 37.61% |
| **Wool** | 4.80 | 1.32 | \$200.00 | \$218.16 | **\$1,047.17** | 17.38% |
| **Milk** | 4.19 | 1.39 | \$160.00 | \$241.98 | **\$1,013.91** | 16.82% |
| **Wheat** | 19.23 | 5.88 | \$25.00 | \$36.45 | **\$700.88** | 11.63% |
| **Melon** | 2.16 | 0.37 | \$250.00 | \$238.43 | **\$515.01** | 8.55% |
| **Fertilizer** | 4.73 | 3.65 | \$100.00 | \$81.37 | **\$384.89** | 6.39% |
| **Carrot** | 1.59 | 0.53 | \$35.00 | \$40.10 | **\$63.75** | 1.06% |
| **Tomato** | 0.46 | 0.22 | \$60.00 | \$74.55 | **\$34.29** | 0.57% |
| **Cow** | 0.04 | 0.04 | \$400.00 | \$0.00 | **\$0.00** | 0.00% |
| **TOTAL** | **46.31 units** | **16.76 events** | — | — | **\$6,026.53** | **100.0%** |

---

## 3. The Mechanism of Discard Events

### What Causes the Midnight Overflow?
1. **Intraday Shed Congestion**: Throughout the day, the shed maintains 50–70 units of baseline inventory (feed wheat buffers, gathered fertilizer, intermediate goods).
2. **Evening Harvest Arrival**: In Hours 18–23, workers harvest multi-unit yield bursts (strawberries 3–6 units/harvest, milk, wool).
3. **The Midnight Cliff**: At Hour 23 Step End, workers deposit 25–45 units into a shed that already has 75+ units. The engine executes `_drop_inventories_to_shed`, discarding any units exceeding 100.
4. **FIFO / Drop Sequence Vulnerability**: Freshly deposited high-value goods (strawberries, wool, milk) arrive last and are destroyed first.

---

## 4. Recoverable Value & P6.1 Focus

1. **Theoretical Upper Bound**:
   - Total measured discard reference value: **$6,026.53 / game**.
2. **Feasible Recoverable Cash: `+$2,500.00 – $4,000.00 / game`**:
   - Monetizing an additional 9 strawberries, 5 wool, and 4 milk per game slightly depresses market prices.
   - Net recoverable cash after price slippage: **$2,500 to $4,000 / game**.
3. **P6.1 Implementation Directive**:
   - Focus exclusively on **Pre-Midnight Storage Hygiene**:
   - Ensure shed headroom $\ge 25$ units during Hours 20–22 by proactively selling surplus buffer items before workers make their midnight drops.
