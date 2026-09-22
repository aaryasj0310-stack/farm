# Kaggriculture P4.0 — Next Experiment Selection & Decision Document

## 1. Context & Decision Framework

The P4.0 economic audit evaluated the entire macroeconomic landscape of the Promoted P2.3 Production Baseline across 100 representative games. It proved:
1. **The 2Q Core Farm is Physically Saturated**: From Day 14 to Day 26, the 46 usable tiles in NW+NE are 90–96% occupied (only 1.8 to 4.7 empty tiles).
2. **The Farm is Highly Capital-Rich in Mid-Game**: Cash reaches **$17,721 on Day 13** and **$50,849 on Day 22**. The $2,000 engine land cost for SW is less than 11% of available cash on Day 14.
3. **The Micro-Execution Frontier is Exhausted**: P3.1, P3.2, P3.3-A, P3.3-B, and P3.4 proved that priority reordering, task dispatch locality, care escalation, and feed batching cannot extract additional score within the fixed 46 tiles.
4. **The Score Gap Reality**: Current baseline mean is **$101,836.36**. The distance to the $130,000 target is **-$28,163.64**.

---

## 2. Evaluation of Competing Candidates

| Candidate Opportunity | Plausible Score Impact | Capital & Labor Feasibility | Difference from Prior Failures | Downside Risk | Decision |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **Candidate A: Late-Season SW Zonal Acreage Expansion (Day 14+ Gated)** | **+$8,000 to +$14,000** | High ($17k cash, 13 workers available) | **Fundamentally Different**: Day 14+ gate vs Day 6; 8 shed tiles vs 25 tiles; dedicated 2-worker cohort vs farm-wide wandering. | High (Spatial contagion if workers cross boundaries) | **SELECTED (CONDITIONAL GO)** |
| **Candidate B: Terminal Carrot Replanting (Days 26–27)** | +$350 to +$650 | High (Uses fallow tiles) | Incremental extension of P2.3 marginal wheat. | Low (Minor risk of liquidation congestion) | **DEFERRED** (Positive EV, but cannot bridge the $28k gap; can be stacked later) |
| **Candidate C: Core Crop Re-weighting (More Strawberries)** | -$500 to +$500 | Low (Exhausts watering capacity; spikes feed buy) | Similar to P2.1 Dynamic Strawberry Cap (Rejected). | Moderate (Crop starvation) | **REJECTED** |
| **Candidate D: Early Capital Reallocation (Days 0–5)** | -$3,000 (Net Loss) | Zero (Cash trough $314) | Violates proved solvency corridor. | Catastrophic (Bankruptcy / NE delay) | **REJECTED** |
| **Candidate E: Market Price Timing / Inventory Holding** | -$6,800 (Net Loss) | Zero (Delays livestock capital) | Violates cash velocity requirement. | Severe (Delayed herd cash flows) | **REJECTED** |

---

## 3. The Selection: P4.1 Late-Season Isolated SW Zonal Acreage Expansion

We select **Candidate A: Late-Season Isolated SW Zonal Acreage Expansion** as the subject of the P4.1 investigation and implementation plan.

### Why Candidate A is the Sole Justified Strategic Frontier:
1. **The Acreage Bottleneck**: In the 2-quadrant core, maximum achievable score is structurally capped at ~$105k because 46 tiles cannot generate more than ~$82k in crops and ~$30k in net livestock value. Reaching $130,000 **physically requires more cultivating tiles**.
2. **Why P4.1 is Materially Different from the Failed P1 / P1.3-C Treatments**:
   - **Timing**: P1 unlocked SW on Days 6–9 when cash was $300–$500, starving the farm of working capital and delaying herd acquisition. P4.1 unlocks SW on **Day 14 Hour 0** when the herd is 100% bought and cash exceeds **$15,000**.
   - **Bounded Scale**: P1 attempted to cultivate all 25 tiles of SW, exhausting worker stamina. P4.1 enforces a strict **8-tile ceiling** directly adjacent to the center shed `(x: 3-4, y: 5-8)`.
   - **Workforce Isolation**: P1 allowed all workers to path between NE and SW, wasting hundreds of turns in transit. P4.1 establishes a **dedicated 2-worker cohort (Hands 11 & 12)** permanently zoned to SW. Core workers (Farmer + Hands 1–10) are hard-blocked from ever entering SW.
3. **Causal Pathway**:
   $$\text{Day 14 ($17k Cash)} \xrightarrow{\text{Buy SW ($2k)}} \text{8 Shed Tiles Tilled} \xrightarrow{\text{Dedicated Hands 11-12}} \text{+96 Strawberries} \xrightarrow{\text{Sold @ \$245}} \mathbf{+\$10k\text{ to }+\$14k Net Score}$$

---

## 4. Formal Decision

We issue a **CONDITIONAL GO** for **P4.1 Late-Season Isolated SW Zonal Acreage Expansion**:
- We proceed to Phase 10: Drafting the comprehensive, rigorous **`p41_implementation_plan.md`**.
- Per instructions: **STOP after producing the P4.0 findings and proposed P4.1 plan. Do NOT implement P4.1 until the plan is reviewed and approved.**
