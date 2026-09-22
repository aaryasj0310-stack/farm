# Kaggriculture P5.1 — Economic Reconciliation Report

## 1. Context & The Model vs Live Gap

In P5.0-R, offline counterfactual modeling identified an estimated **shadow opportunity of +$655.25 / game** by substituting surplus late-season wheat plantings (Days 21–23) on core NW+NE tiles with two consecutive 3-day carrot cycles.

However, when tested in the full, unconstrained 100-pair (200-game) live discovery replay against all 5 benchmark opponents:
- **Modeled Shadow Opportunity**: **+$655.25 / game**
- **Empirical Live Discovery Delta**: **−$1,020.68 / game**
- **Net Divergence (Delta Gap)**: **−$1,675.93 / game**

This document provides the economic and mechanical forensic reconciliation explaining why the modeled shadow gain failed to materialize in live play, despite achieving near-perfect physical execution (**626 completed rotations**, **96.6% C2 completion**, and **0 animal starvations**).

---

## 2. Quantitative Decomposition of the Gap

| Potential Cost Mechanism | Estimated Per-Game Impact | Primary Evidence |
| :--- | :---: | :--- |
| **1. Severe Late-Season Labor Displacement** | **−$950 to −$1,200** | Extra 43.8 worker actions displacing milking & high-value crop harvesting |
| **2. Town Shop Demand Saturation & Price Depletion** | **−$300 to −$450** | Flooding ~38 extra carrots/game into finite daily town demand |
| **3. Market Order Slot Competition** | **−$150 to −$250** | Urgent carrot seed buys crowding out high-value milk/wool sales |
| **4. Unsold Inventory / Endgame Liquidation Haircut** | **−$100 to −$200** | Intraday Day 28–29 carrot harvest remaining in inventory unsold |
| **Total Reconciled Drag** | **−$1,500 to −$2,100** | Matches the empirical gap of **−$1,675.93** |

---

## 3. Detailed Forensic Mechanisms

### 3.1 Mechanism 1: Late-Season Worker Action Saturation (Labor Displacement)

The fundamental difference between late-season wheat and a two-cycle carrot rotation is **action intensity**:

| Crop Schedule | Planting | Daily Waterings | Harvest | Total Worker Actions |
| :--- | :---: | :---: | :---: | :---: |
| **Late Wheat (Days 21–23)** | 1 action | 1 action (Day 0 only) | 1 action (Days 27–29) | **3 actions** |
| **Carrot Cycle 1** | 1 action | 3 actions (Days 21, 22, 23) | 1 action (Day 24) | **5 actions** |
| **Carrot Cycle 2** | 1 action | 3 actions (Days 24, 25, 26) | 1 action (Day 27) | **5 actions** |
| **Two-Cycle Total** | **2 actions** | **6 actions** | **2 actions** | **10 actions** |

Across an average of **6.26 completed rotations per game**, the treatment demands:
$$6.26 \times (10 - 3) = \mathbf{43.82 \text{ additional worker actions}}$$
all concentrated in the critical late-season window (Days 21 through 28).

#### The Opportunity Cost of Worker Time on Days 21–28:
In the baseline production agent:
1. **Cow Milking**: A mature dairy cow produces milk daily. Missing a single milking action forfeits **$200–$400** of pure profit.
2. **Sheep Shearing**: Shearing ready sheep yields wool worth **$150–$300**.
3. **High-Value Harvests**: Melons and cauliflowers planted earlier in the season reach maturity on Days 22–27. If workers are routed to water carrot tiles across the core farm, high-value crops risk spoilage or missed daily shop delivery windows.

In offline static models, tile actions are evaluated in isolation assuming zero marginal labor cost. In live simulation, the worker pool is fixed (maximum 4–6 workers), making labor a strictly finite, highly congested resource.

---

### 3.2 Mechanism 2: Town Shop Demand Saturation & Price Collapse

In offline models, carrots are assumed to sell at or near the nominal shop price (~$45–$50 per carrot).
However, the engine models local town shop economies:
- Each carrot harvest yields **3 carrots per tile**.
- Two cycles across 6.26 tiles yield:
  $$6.26 \times 3 \times 2 = \mathbf{37.56 \text{ additional carrots}}$$
- Town shops have modest daily demand capacities (typically 5–15 carrots total per day across all reachable shops).
- When the agent attempts to dump ~38 extra carrots over Days 24–29, town shop demand is exhausted. Subsequent carrots either:
  1. Sell at depressed prices near the salvage floor (~$15–$20/carrot).
  2. Remain stored in inventory at Day 30, receiving only the endgame liquidation valuation (or zero cash credit).

In contrast, **wheat is an internal productive input**:
- 6.26 wheat tiles produce ~30–38 wheat units.
- Wheat is consumed directly by livestock on the farm, converting 1:1 into milk and wool without paying market transaction costs or suffering town shop demand depreciation.

---

### 3.3 Mechanism 3: Market Order Slot Congestion

The game engine imposes an absolute ceiling of `MAX_MARKET_ORDERS = 10` per day.
To guarantee Cycle 2 execution, P5.1 elevated `BUY_SEED CARROT` to `P1_URGENT` priority (urgency 1.0) at Hour 0.
Additionally, selling 38 extra carrots required 2–4 sell orders across Days 24–29.

Under this regime:
- The 10 available order slots were frequently saturated by carrot buys and sells.
- Lower-priority but much higher-value orders (such as spot milk sells at distant town shops offering premium prices) were pushed past the 10th slot and dropped.
- Dropping a single milk sell order costs $300–$600 on that day.

---

### 3.4 Mechanism 4: Opponent Interaction Dynamics

The opponent breakdown in the 100-pair replay highlights how competition amplifies these bottlenecks:

- **Against Passive Opponents (`pass`, `pure_wheat_rush`)**:
  - Opponents do not compete for town shop carrot demand or milk prices.
  - Median deltas are slightly positive (**+$338.00** and **+$776.00**), confirming that when shop demand and worker capacity are unpressured, two-cycle carrots can technically break even.
- **Against Competitive Opponents (`cow_milk_engine`, `full_production_agent`)**:
  - `full_production_agent` competes aggressively for town shop demand and optimizes worker pathing.
  - Against `full_production_agent`, the mean delta plummeted to **−$2,171.45 / game** (17 negative out of 20 pairs).
  - The extra labor spent on carrots severely weakened the agent's competitive posture.

---

## 4. Synthesis: Why Offline Counterfactuals Misled

The P5.0-R offline counterfactual assumed:
1. Infinite worker availability (0 shadow wage for watering actions).
2. Infinite town shop absorption capacity at static base prices.
3. Zero market order slot competition.
4. Complete fungibility between cash and livestock feed.

The live engine proved that **none of these assumptions hold in end-game play**. Late wheat is not merely "lazy" farming; it is an exquisitely labor-efficient, market-independent strategy that frees up critical worker hours for the compounding dairy and livestock operations that win tournaments.
