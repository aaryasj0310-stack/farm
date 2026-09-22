# P6 Physical Wheat & Feed Liquidity Audit (P6-R Corrected)

## 1. Executive Summary & Epistemic Verdict

Physical wheat is the critical operational commodity in Kaggriculture:
1. **Biological Feed**: Required daily to prevent livestock escapes and trigger dairy/wool yields.
2. **Cash Crop**: Harvested and sold for cash ($36,837.79/game).
3. **Trade Commodity**: Purchased at market ($31,249.44/game) to maintain buffer reserves.

```
                             THE WHEAT CHURN CYCLE (100-Game Mean)
   ┌────────────────────────────────────────────────────────────────────────┐
   │ Farm Harvested Wheat:                     381.91 units                 │
   │ Purchased from Market:                    863.02 units  ($31,249.44)   │
   │ TOTAL ACQUIRED WHEAT:                   1,244.93 units                 │
   ├────────────────────────────────────────────────────────────────────────┤
   │ Consumed by Livestock (213.90 feeds):     213.90 units                 │
   │ Discarded at Shed Overflow:                19.23 units  (-$700.88)     │
   │ Sold back to Market:                    1,010.72 units  (+$36,837.79)  │
   │ Ending Inventory (Workers + Field):         1.08 units                 │
   └────────────────────────────────────────────────────────────────────────┘
```

> [!IMPORTANT]
> **Epistemic Classification: `MEASURED FACT`**
> - The herd consumes only **213.90 units of wheat/game**, yet the baseline buys 863.02 units and sells 1,010.72 units.
> - On Day 28, desynchronized buy/sell orders churned **440.39 units bought vs 465.98 units sold per game** (panel total: 44,039 bought / 46,598 sold).
> - However, the net financial delta on Day 28 was positive (**+$1,040.97 / game**), zero animals escaped or starved, and market slots were NOT saturated (8 free slots/hour).

---

## 2. Key Empirical Findings (100-Game Panel)

### 1. Grain Stockouts (Intraday Feed Insecurity)
- **Mean Stockout Hours / Game**: 1.36 hours
- **Games Experiencing Stockouts**: **52 out of 100 games (52.0%)**
- In 52 games, there was at least one hour where an unfed animal existed while total wheat across the shed and worker inventories was zero.
- However, zero animals starved or escaped (escapes = 0.00). Morning harvests or subsequent intraday market purchases arrived before midnight.

### 2. Panel-Wide Wheat Trading
- **Wheat Sold**: 1,010.72 units @ \$36.45 = \$36,837.79
- **Wheat Bought**: 863.02 units @ \$36.21 = \$31,249.44
- **Net Wheat Trade**: +\$5,588.35 cash spread across 1,873.74 traded units.

---

## 3. The Day 28 Desynchronization Analysis: Fact vs Hypothesis

### The Mechanism
1. **Endgame Liquidator**: Emits `SELL WHEAT 20` every hour starting on Day 28 (`reserved_wheat = 0`).
2. **OrderBuilder Intraday Feed Protection**: Seeing low wheat in the shed, requests 240 units of buffer wheat (`BUY_PRODUCT WHEAT 20` every hour).
3. **Engine Execution**: The engine executes `SELL` then `BUY` in lockstep.

### Panel Reconciliation: 100 Games
- **Scope Clarification**: The previously cited figure of "453 bought / 468 sold" was from **Game 0 only**.
- **Panel Average**:
  * **Units Bought**: 440.39 units/game ($17,521.17 cost)
  * **Units Sold**: 465.98 units/game ($18,562.14 revenue)
  * **Net Cash Lift**: **+$1,040.97 / game** (Total: +$104,097.00 across the panel).
- **Slot Capacity Audit**:
  * Churn consumed exactly 2 orders per turn (1 SELL, 1 BUY).
  * 8 out of 10 slots remained available in every churn hour.
  * CentralPlanner rejections during Day 28: only 5.49 across the entire day.
- **Shed State Audit**:
  * Shed wheat at Day 28 Hour 23 was **0.00 units**.
  * Churn did not cause midnight shed overflow discards.

---

## 4. Recoverable Value & Operational Verdict

| Impact Dimension | Measured Reality | Financial Impact | Epistemic Classification |
| :--- | :---: | :---: | :---: |
| **Day 28 Buy/Sell Churn** | 440.4 b / 466.0 s / game | **Net +$1,040.97 / game** (Profitable net sale) | `MEASURED FACT` |
| **Direct Discarded Wheat** | 19.23 units / game | **$700.88 loss** (Captured in shed discards) | `MEASURED FACT` |
| **Feed Stockout Elimination** | 1.36 hours in 52% of games | **$0.00 direct cash** (Zero escapes occurred) | `MEASURED FACT` |
| **Fertilizer Backlog Claim** | Refuted | **$0.00** (Conservation closed) | `NOT A REAL OPPORTUNITY` |

> [!TIP]
> **Operational Verdict**:
> The Day 28 churn is sloppy and wasteful of order slots, but it is financially net-positive and did not cause feed failures or slot saturation. 
> Fixing it will not produce direct cash lift; it is a code-cleanliness and risk-reduction improvement that should NOT be bundled into P6.1.
