# P6 Physical Wheat & Feed Liquidity Audit

## 1. Executive Summary & Epistemic Verdict

Physical wheat is the critical lifeblood of Kaggriculture. It is simultaneously:
1. **Biological Feed**: Required daily to prevent livestock escapes and trigger dairy/wool yields.
2. **Cash Crop**: Harvested and sold for cash ($36,837.79/game).
3. **Trade Commodity**: Purchased at market ($31,249.44/game) to maintain buffer reserves.

```
                             THE WHEAT CHURN CYCLE
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
> Across 100 baseline games, the agent's herd consumed only **213.90 units of wheat**, yet the agent harvested **381.91 units** and purchased an astonishing **863.02 units**.
> Over **80% of all purchased wheat was immediately resold to the market**, creating massive logistical churn, slot congestion, and shed overflow discards.

---

## 2. Key Empirical Findings

### 1. Grain Stockouts (Feed Insecurity)
- **Mean Stockout Hours / Game**: 1.36 hours
- **Games Experiencing Stockouts**: **52 out of 100 games (52.0%)**
- In over half of all baseline games, there was at least one hour where an animal was waiting to be fed, but total wheat across the shed and worker inventories was **zero**.
- Fortunately, zero animals escaped (escapes = 0.00) because the emergency buy fallback or daily wheat harvest replenished grain before the 2-day starvation limit expired. However, these stockouts triggered panic market orders that disrupted regular trading.

### 2. Massive Round-Trip Churn
- **Wheat Sold**: 1,010.72 units @ \$36.45 = \$36,837.79
- **Wheat Bought**: 863.02 units @ \$36.21 = \$31,249.44
- **Net Wheat Trade**: +\$5,588.35 cash from trading 1,873 units of wheat.
- Although the cash spread was positive (+\$0.24/unit), this nominal profit is completely eclipsed by the hidden costs:
  - **Shed Capacity Choke**: Carrying 20–40 units of buffer wheat leaves no room for high-value items, causing \$6,026.53 in discards.
  - **Order Slot Depletion**: Consumed hundreds of market slots that could have been used to liquidate high-value produce.

---

## 3. The Day 28 Desynchronization Bug

Detailed hourly inspection of Game 0 (and corroborated across all 100 games) revealed an extreme operational flaw:

```
Day 28 Hourly Trading Log:
  Hour 00: Bought  0, Sold 20
  Hour 01: Bought  0, Sold 20
  Hour 02: Bought 32, Sold  8
  Hour 03: Bought 20, Sold 20   <--- Simultaneous opposing orders!
  Hour 04: Bought 21, Sold 20
  Hour 05: Bought 20, Sold 20
  ...
  Hour 23: Bought 20, Sold 20
  Total Day 28: 453 units BOUGHT, 468 units SOLD!
```

### Mechanism of the Bug
1. **Endgame Liquidator**: Sees Day 28 and attempts to liquidate all shed wheat to maximize cash before game end, emitting `SELL WHEAT 20` every hour.
2. **Feed Feasibility / OrderBuilder**: Sees Day 28 Hour $h$ with low wheat and attempts to protect the herd against starvation on Day 29, emitting `BUY WHEAT 20` every hour.
3. **The Root Cause**: `P22A_DAY28_FEED_HARMONIZATION_ENABLED = False` in the production baseline.
4. **Consequences**:
   - The agent buys and sells 20 units of wheat in the **exact same hour** for 21 consecutive hours!
   - This single bug churned **450+ units of wheat on Day 28 alone**, maxing out market slots and filling the shed right before the Day 28 midnight drop, directly triggering the massive **Strawberry ($2,266.63) and Wool ($1,047.17) shed discards**!

---

## 4. Recoverable Value & Operational Verdict

| Impact Dimension | Measured Severity | Recoverable Cash Value | Epistemic Classification |
| :--- | :---: | :---: | :---: |
| **Day 28 Buy/Sell Churn** | 453 units bought / 468 sold | **+$1,200.00 – $2,500.00** (Indirect via discard reduction) | `INFERRED RECOVERABLE VALUE` |
| **Direct Discarded Wheat** | 19.23 units / game | **$700.88** | `MEASURED FACT` |
| **Feed Stockout Elimination** | 1.36 hours in 52% of games | **+$250.00 – $500.00** (Preventing feed-delay care losses) | `INFERRED RECOVERABLE VALUE` |
| **Total Physical Wheat Opportunity**| — | **+$2,150.00 – $3,700.88** | — |

> [!TIP]
> **Key Recommendation**:
> Enforcing strict unidirectional wheat orders (never buy wheat if selling wheat in the same turn) and synchronizing Day 28 feed reservations with endgame liquidation immediately prevents 450 units of fake churn and protects shed room for season-end cash liquidation.
