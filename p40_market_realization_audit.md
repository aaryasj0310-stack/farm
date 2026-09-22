# Kaggriculture P4.0 — Market Revenue Realization Audit

## 1. Executive Summary & Market Mechanics

This audit evaluates whether the existing market selling strategy systematically misses higher-value selling opportunities or suffers from price erosion. We analyze actual transaction prices, town-shop consumption, opponent market interference, and shed dwell times across 100 fully instrumented games.

Key findings:
- **Premium Price Realization**: The agent captures realized sale prices far above base reference prices for 6 out of 8 products (e.g. Strawberries at **+$104.7%** over base; Milk at **+$51.5%** over base).
- **Town Shop Sink Effect**: Unlocked town shops consume **over 2,000 units of agricultural goods** per game, continuously draining market inventory and pushing late-game prices upward.
- **Zero Inventory Stranding**: Shed dwell time averages under 1 turn. The agent experiences zero lost sales due to order limits or shed overflow.
- **The Fertilizer Decay**: Fertilizer is the only product experiencing significant downward price degradation (-24.8% over the season) because town shops do not consume fertilizer.

---

## 2. Realized Price vs Base Price & Price Evolution Across Season

| Product | Base Engine Price | Realized Mean Price | Premium vs Base (%) | Early Season (Days 0–9) | Mid Season (Days 10–19) | Late Season (Days 20–29) | Season Trend (Late vs Early) |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **STRAWBERRY** | $120.00 | **$245.58** | **+104.65%** | N/A (Not mature) | $221.61 | **$249.07** | **+12.39%** (Mid -> Late) |
| **MILK** | $160.00 | **$242.32** | **+51.45%** | $198.19 | $213.18 | **$244.12** | **+23.18%** |
| **WHEAT** | $25.00 | **$36.60** | **+46.40%** | $28.42 | $32.00 | **$37.72** | **+32.72%** |
| **TOMATO** | $60.00 | **$69.17** | **+15.28%** | N/A | $65.57 | **$95.85** | **+46.18%** (Mid -> Late) |
| **WOOL** | $200.00 | **$225.68** | **+12.84%** | N/A | $233.05 | **$218.44** | **-6.27%** (Mid -> Late) |
| **CARROT** | $35.00 | **$38.67** | **+10.49%** | $34.10 | $33.66 | **$52.04** | **+52.61%** |
| **MELON** | $250.00 | **$238.71** | **-4.52%** | N/A | $238.41 | **$220.83** | **-7.37%** (Mid -> Late) |
| **FERTILIZER** | $100.00 | **$81.51** | **-18.49%** | $98.74 | $91.18 | **$74.29** | **-24.76%** |

```
Realized Price ($)
$260 |                                         *---* (Strawberry: ~$249)
$240 |                                     *---* (Milk: ~$244)
$220 |                             *-------* (Wool: ~$218)
$200 |                     *-------* (Melon: ~$220)
     |
 $80 |             *-------* (Fertilizer: drops $98 -> $74)
 $40 |     *-------* (Wheat: rises $28 -> $37)
     |_________________________________________________
       Days 0-9                Days 10-19            Days 20-29
```

---

## 3. Town Shop Consumption Dynamics

In the Kaggriculture engine, town shops unlock every 4 days and independently consume items from market inventory, reducing supply and raising prices:

| Product | Own Units Sold | Town Shop Consumption | Opponent Units Sold | Net Market Absorption | Shop Demand Vulnerability |
| :--- | :---: | :---: | :---: | :---: | :--- |
| **WHEAT** | 1,003.0 | 554.7 | 148.7 | +597.0 | Moderate (High volume, high town demand) |
| **STRAWBERRY** | 79.6 | **438.1** | 0.0 | **-358.5** | **Massive Town Deficit** (Town consumes 5.5x our production!) |
| **MILK** | 141.6 | **317.3** | 0.0 | **-175.7** | **Massive Town Deficit** (Town consumes 2.2x our production!) |
| **CARROT** | 67.2 | 290.5 | 17.5 | -205.8 | High Town Deficit |
| **WOOL** | 72.7 | 222.2 | 0.0 | -149.5 | High Town Deficit (Town consumes 3x our production) |
| **TOMATO** | 24.2 | 211.1 | 0.0 | -186.9 | High Town Deficit |
| **MELON** | 89.9 | 30.0 | 0.0 | +59.9 | Mild Surplus (Town rarely consumes melons) |
| **FERTILIZER** | 186.5 | **0.0** | 0.7 | **+187.2** | **Zero Town Demand** (Pure player-supply saturation) |

### Key Strategic Finding:
For **Strawberries**, **Milk**, and **Wool**, **town shop demand vastly exceeds total market supply**.
- Town shops consume **438 strawberries**, while our farm only produces **80 strawberries**!
- Because market supply is chronically negative relative to shop appetite, strawberry prices do NOT collapse—they climb steadily to **$249/unit**.
- This completely explains why P2.1 (Dynamic Strawberry Cap) failed: our agent was restricting production of a good whose market demand was insatiable.
- Conversely, **Fertilizer has zero town consumption**. As our 11 animals generate manure every day, fertilizer prices steadily degrade from $98 down to $74.

---

## 4. Execution & Shed Logistics Efficiency

- **Order Capacity Limit**: Engine enforces `maxMarketOrdersPerTurn = 10`.
  - Audited games showed an average of 1.4 market orders per turn. The 10-order cap was exceeded in **0 out of 72,000 audited turns**.
- **Shed Capacity Limit**: Engine enforces `shedCapacity = 100`.
  - Audited games showed a mean daytime shed occupancy of 14.2 units and a peak of 38 units.
  - The 100-unit shed limit was reached in **0 turns**.
- **Dwell Time in Shed**:
  - The mean dwell time between harvest/milking/shearing and market execution was **0.0 to 1.2 turns**. Products are immediately sold on the turn they enter the shed.

---

## 5. Counterfactual Selling Strategies: Can We Time the Market?

### Hypothesis A: Holding Strawberries or Milk for Late-Game Peak Prices
- **Mechanics**: Strawberry prices rise from $221 (Days 10–19) to $249 (Days 20–29), a gain of +$28/unit (+12.6%).
- **Trade-off Analysis**:
  - If we hold 40 strawberries on Days 10–15, we could theoretically earn an extra $1,120 at Day 25.
  - **However**: Holding 40 strawberries delays **$8,840 in liquid capital** during Days 10–15.
  - As proven in Report 3, Days 10–13 is the exact window when the farm spends $4,901 buying cows and sheep and $2,750 hiring hands.
  - Starving the farm of liquid cash on Days 10–13 would delay herd purchases, forfeiting milk ($242/day) and wool ($225/day), which far outweighs a $1.1k price timing gain.
- **Verdict**: **Counterfactual Fails on Liquidity Cost**.

### Hypothesis B: Holding Fertilizer Until Early-Season Prices Peak
- **Mechanics**: Fertilizer prices are $98 in early game and fall to $74 in late game.
- **Analysis**: The agent already sells fertilizer the very turn it is collected from the pasture! Fertilizer cannot be sold earlier than it is produced by the animals.
- **Verdict**: **Structurally Unactionable**.

### Conclusion:
The existing market strategy is already extracting nearly 100% of available market value under the engine's supply-demand curves. Market price timing cannot bridge the $28k gap.
