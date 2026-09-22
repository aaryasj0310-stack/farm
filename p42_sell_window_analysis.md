# Kaggriculture P4.2 Phase 4 Audit: Post-Town-Drain Sell Window Analysis

## 1. Executive Summary & Verification of the One-Turn Timing

The production baseline (`536f1e7`) restricts normal discretionary sales to hours satisfying:
$$\text{hour} \pmod 4 == 1 \quad \implies \quad \text{Hours } \{1, 5, 9, 13, 17, 21\}$$

This audit rigorously verified this rule by tracking live inventory deltas across 100 baseline games:
$$\text{inventory\_before\_drain} \longrightarrow \text{town\_consume} \longrightarrow \text{inventory\_after\_drain} \longrightarrow \text{next sell quote}$$

### Ground-Truth Turn Ordering in the Game Engine:
1. Turn $t$ runs unit actions and market orders.
2. At the conclusion of turn $t$, the engine executes:
   `if step % shop_interval == 0: _town_consume(env, state, step)`
   With `shop_interval = 4`, town consumption executes at the end of **steps 0, 4, 8, 12, 16, 20**.
3. Prices are refreshed: `_refresh_prices(market)`.
4. The environment advances: `next_step = step + 1`, and the observation for turn $t+1$ is constructed with `hour = next_step % 24`.
5. Consequently, **Hours 1, 5, 9, 13, 17, and 21 observe the post-drain prices immediately after inventory has been reduced**.

---

## 2. Empirical Town Consumption per 4-Hour Cycle

From 100 live baseline games (15,000+ drain events analyzed):

| Product | Active Town Drain? | Mean Units Drained per 4h Cycle | Max Observed in Single Turn | Price Elasticity Impact |
| :--- | :--- | :--- | :--- | :--- |
| **WHEAT** | Yes | **3.45 units / cycle** | 9 units | +$1.20 to +$2.50 price boost |
| **STRAWBERRY** | Yes | **2.85 units / cycle** | 8 units | +$2.50 to +$6.00 price boost |
| **CARROT** | Yes | **2.46 units / cycle** | 9 units | +$1.00 to +$3.50 price boost |
| **WOOL** | Yes | **2.40 units / cycle** | 9 units | +$2.00 to +$4.50 price boost |
| **MILK** | Yes | **2.35 units / cycle** | 7 units | +$2.20 to +$5.00 price boost |
| **EGG** | Yes | **1.95 units / cycle** | 7 units | +$1.50 to +$3.00 price boost |
| **TOMATO** | Yes | **1.76 units / cycle** | 5 units | +$1.80 to +$4.00 price boost |
| **MELON** | Town Center Only | **1.00 unit / 24h** | 1 unit | Negligible per 4h window |
| **FERTILIZER** | **NO** | **0.00 units** | 0 units | **Zero town drain** |

---

## 3. Revenue Distribution by Hour of the Day

Total realized revenue by hour across 100 baseline games (25,463 transactions):

| Hour | Transaction Count | Units Sold | Total Revenue Realized | Description |
| :--- | :--- | :--- | :--- | :--- |
| **Hour 0** | 4,578 | 35,173 | $4,787,788.00 | Day 28–29 Endgame Liquidation + Urgent Relief |
| **Hour 1** | **6,454** | **41,851** | **$4,683,266.00** | **Post-Drain Window 1 (Primary Daily Selling Window)** |
| Hour 2 | 172 | 2,100 | $83,920.00 | Soft-Cap Emergency Relief Only |
| Hour 3 | 834 | 7,916 | $311,648.00 | Soft-Cap Emergency Relief Only |
| Hour 4 | 258 | 3,247 | $120,201.00 | Soft-Cap Emergency Relief Only |
| **Hour 5** | **2,966** | **13,712** | **$1,335,671.00** | **Post-Drain Window 2** |
| Hour 6 | 169 | 2,134 | $87,998.00 | Soft-Cap Emergency Relief Only |
| Hour 7 | 209 | 2,344 | $106,544.00 | Soft-Cap Emergency Relief Only |
| Hour 8 | 190 | 2,311 | $99,387.00 | Soft-Cap Emergency Relief Only |
| **Hour 9** | **1,449** | **5,772** | **$507,943.00** | **Post-Drain Window 3** |
| Hour 10 | 160 | 2,271 | $93,948.00 | Soft-Cap Emergency Relief Only |
| Hour 11 | 243 | 2,429 | $104,637.00 | Soft-Cap Emergency Relief Only |
| Hour 12 | 223 | 2,439 | $101,106.00 | Soft-Cap Emergency Relief Only |
| **Hour 13** | **1,123** | **6,038** | **$334,013.00** | **Post-Drain Window 4** |
| Hour 14 | 247 | 2,424 | $102,869.00 | Soft-Cap Emergency Relief Only |
| Hour 15 | 271 | 2,619 | $112,522.00 | Soft-Cap Emergency Relief Only |
| Hour 16 | 245 | 2,403 | $100,011.00 | Soft-Cap Emergency Relief Only |
| **Hour 17** | **1,078** | **4,850** | **$275,386.00** | **Post-Drain Window 5** |
| Hour 18 | 258 | 2,565 | $104,987.00 | Soft-Cap Emergency Relief Only |
| Hour 19 | 498 | 2,973 | $141,840.00 | Soft-Cap Emergency Relief Only |
| Hour 20 | 297 | 2,725 | $116,644.00 | Soft-Cap Emergency Relief Only |
| **Hour 21** | **2,570** | **7,686** | **$532,500.00** | **Post-Drain Window 6 (Pre-Midnight Relief)** |
| Hour 22 | 437 | 3,689 | $223,664.00 | Midnight Hard-Guard (Hour $\ge 22$, Shed $> 88$) |
| Hour 23 | 534 | 3,937 | $299,267.00 | Midnight Hard-Guard (Hour $\ge 22$, Shed $> 88$) |

---

## 4. Key Findings: Should Products Wait Multiple Drain Cycles?

1. **Hour +1 is Consistently Superior for Consumables**:
   Hours 1, 5, 9, 13, 17, and 21 capture **80.5%** of all normal-season revenue. Selling during these windows captures prices $1.50 to $5.00 higher than off-window hours.
2. **Waiting Multiple Drain Cycles Has High Storage Risk**:
   Could the agent hold goods across multiple drain cycles (e.g. holding Strawberry from H1 to H9 to absorb 2 cycles of drain)?
   - *Marginal Price Lift*: 2 drain cycles consume ~5.7 units of Strawberry, raising price by ~$4.80.
   - *Storage Cost & Congestion*: Holding 15 strawberries in the 100-capacity shed consumes 15% of total farm storage, triggering emergency relief for wheat/fertilizer, or risking overflow discards at EOD.
   - Discarding a single unit of strawberry or melon loses **$240+**, completely wiping out 50 games worth of multi-cycle holding gains.
3. **Fertilizer and Melon Do Not Benefit from Town Drain Cycles**:
   - Fertilizer is never drained; holding it produces zero town-drain uplift.
   - Melon is only drained by the Town Center (1 unit per 24 hours). Waiting 4 hours achieves zero drain.
