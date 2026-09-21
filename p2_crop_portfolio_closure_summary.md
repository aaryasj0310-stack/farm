# Phase P2: Core 2-Quadrant Crop Portfolio & Capital Allocation Closure Summary

## 1. Phase Overview & Objectives
Phase P2 focused on optimizing crop portfolio selection, capital deployment, and harvest economics within the validated 2-quadrant core (NW+NE, 50 tiles) without expanding into SW or adding land purchase overhead.

The objective was to determine whether land, water, capital, and feed resources in the NW+NE quadrants were being misallocated or underutilized under the baseline strategy (~$103.1k), and to bridge the performance gap toward the $130,000 target.

---

## 2. Experimental Ledger & Outcomes

| Investigation | Hypothesis / Intervention | Result | Outcome | Key Lesson Learned |
| :--- | :--- | :--- | :--- | :--- |
| **P2.0: Second Melon Tranche** | Plant an opportunistic second melon tranche on Days 6–10 if money and worker slack permit. | Mean delta: **-$42/game** (CI: [-$638, +$554]) | **REJECTED** | Melons consume massive water over an 8-day cycle; a second tranche starved mid-season strawberries and animals of water, creating large downside variance. |
| **P2.1: Dynamic Strawberry Allocation** | Adjust strawberry planting caps based on shed wheat reserves and real-time market inventory. | Mean delta: **+$110/game** (CI crossed zero; 95/100 cases identical) | **REJECTED** | Baseline strawberry cap schedule (16->18->20->0) is already near-optimal. Dynamic scaling rarely triggered without creating collateral risk. |
| **P2.2-A: Feed / Liquidation Harmonization** | Coordinate Day 28 livestock feeding with early liquidation of satiated animals to sell wheat early. | Mean delta: **-$62/game** (solvency neutral, lost yield) | **REJECTED** | Animals produce high-value milk/wool/eggs during late ticks. Early liquidation cost more product revenue than early wheat receipts gained. |
| **P2.3: Marginal Wheat Replanting** | Block economically terminal wheat replanting on Day 26+ (`day > 25`) and substitute fast endgame carrots. | Mean delta: **+$445.48** (Discovery) / **+$451.50** (Held-Out), $p < 0.0003$ | **PROMOTED** | Wheat planted on Day 26+ cannot mature before Day 30. Cutting terminal replanting frees 5.9 tiles for profitable carrot blitzes with 0 herd feed impact. |

---

## 3. Updated Project Scorecard & Roadmap to $130,000

### Progress So Far
- **Initial Baseline (Pre-P1)**: ~$98,000
- **Production Baseline (Post-P1 / 2Q Re-anchored)**: ~$103,160 (`237cf5ee54498ed1ad2fa04d00ad9a0ebd27352e`)
- **Production Baseline (Post-P2.3 Promoted)**: **~$103,610**
- **Remaining Target Gap**: **~$26,390** (to reach $130,000)

### Why 2-Quadrant Crop Yield Has Plateaued Near ~$104k
The P2 series demonstrated that within the fixed 50-tile NW+NE core, agronomic yields are close to the theoretical ceiling under the current workforce execution model:
- **Tiles Allocated**:
  - ~10 tiles dedicated to livestock housing & pasture (NW/NE boundary)
  - ~20 tiles dedicated to continuous feed wheat (mandatory ~212 units feed)
  - ~16–20 tiles dedicated to strawberry cash wave (Days 3–13)
  - Remaining ~5–10 tiles cycled through early carrots, initial melons, and endgame carrots.
- Further shifting of crop mix (more melons, fewer strawberries, less mid-season wheat) consistently caused either water contention, seed capital starvation, or herd risk.

---

## 4. Re-Profiling the Next Workstreams (Where the Next $26k Lives)

To achieve $130,000, future work must look beyond macro crop selection and tackle **workforce logistics, operational throughput, and micro-arbitration**:

### Workstream 3.1: Worker Pathfinding, Clustering & Latency Elimination
- **Current Observation**: In a 720-hour game with 8 workers (5,760 worker-hours), workers spend 25–35% of their time walking between distant tiles, wells, sheds, and markets.
- **Hypothesis**: Spatial task clustering and tool unbundling (e.g. specialized waterers, harvesters, and feed couriers) can reduce transit overhead by 15–20%, effectively generating 800+ additional productive worker-hours.

### Workstream 3.2: Livestock Care Velocity & Daily Feeding Scheduling
- **Current Observation**: Although EOD starvation is 0, animals spend many intraday hours unfed while workers prioritize crop watering. Unfed animals delay their product cycle (milk/wool generation).
- **Hypothesis**: Scheduling feed and care tasks at Hour 0–3 of each day accelerates product generation ticks, increasing total milk and wool revenue across the 30-day season by $5,000–$8,000.

### Workstream 3.3: High-Frequency Market Price Timing & Arbitrage
- **Current Observation**: `MarketBrain` drip-sells commodities in fixed tranches, frequently selling into low-price ticks or holding excess inventory into Day 30 that sells at fire-sale prices.
- **Hypothesis**: Aligning sell orders with opponent demand spikes and town shop replenishment cycles will capture an additional 10–15% margin on high-value animal products and crops.

### Workstream 3.4: Precision End-of-Season Capital Liquidation
- **Current Observation**: On Day 29, workers occasionally perform low-value maintenance (watering crops that cannot mature) instead of executing 100% synchronized inventory clearance and harvest collection.
- **Hypothesis**: A dedicated Day 29 harvest sweep and complete inventory liquidation protocol guarantees zero wasted residual inventory at the season buzzer.
