# Kaggriculture P4.0 — Southwest (SW) Expansion Feasibility Reassessment

## 1. Executive Summary & Context

Southwest (SW) quadrant expansion has historically been the most tempting yet disastrous intervention in the project's history. In Phase P1, unconstrained and conditionally gated SW expansion (including P1.3-C) produced massive score collapses of **-$13,000 to -$28,000 per game** relative to the 2-quadrant (NW+NE) control, prompting the institution of `QUADRANT_HARD_BLOCK = {4}`.

This report re-examines SW expansion against the empirical baseline reality established in P4.0:
- The 2Q core is **90–96% saturated** from Day 14 to Day 26 (only 1.8 to 4.7 empty tiles).
- The farm amasses **$17,721 in cash by Day 13** and over **$50,000 by Day 22**.
- The engine land cost for SW (the 2nd extra quadrant) is **$2,000**, easily affordable on Day 14.

We systematically decompose why past SW experiments failed and whether a tightly constrained mid-season mechanism could be economically viable.

---

## 2. Anatomy of Previous SW Failures (P1 & P1.3-C)

Archived post-mortems from Phase P1 and P1.3-C reveal three distinct failure mechanisms:

```
[PAST SW FAILURE CAUSAL TREE]
1. Early Capital Cannibalization (Days 6–10)
   ├── Bought SW ($2,000) when cash was in the $300-$500 trough
   ├── Delayed hiring Hands 5–12 ($5,500 total cost)
   └── Delayed buying Cows/Sheep ($4,900 total cost) -> Forfeited $30k in Milk/Wool

2. Cross-Quadrant Spatial Transit Drag
   ├── Workers assigned to SW pastures walked across the entire board (NE -> SW)
   ├── 10-turn transit per worker journey -> 400+ worker turns wasted walking
   └── Disrupted daily watering sweeps in NW/NE -> Crop decay and lost yields

3. Land Over-Commitment & Labor Exhaustion
   ├── Unlocked 25 SW tiles simultaneously
   ├── Spent 75 turns tilling and planting empty dirt
   └── Daily watering burden surged beyond worker capacity -> Unwatered penalties
```

### Quantitative Reality of P1.3-C Failure:
- **Net Delta**: -$13,420/game vs 2Q Control
- **Negative Cash Events**: 14.2% of games
- **NW+NE Crop Watering Failures**: Increased by +340%
- **Worker Transit Turns**: Rose from 857 to 1,420 turns/game

---

## 3. The Physical & Economic Reality of the Engine

### Land & Tile Architecture:
- Total board: 10 $\times$ 10 = 100 tiles.
- 4 quadrants of 25 tiles each: NW, NE, SW, SE.
- Shed occupies the 4 center tiles: `(4,4), (4,5)` in NW, and `(5,4), (5,5)` in NE.
- Usable tiles in NW: 23 tiles.
- Usable tiles in NE: 23 tiles.
- **Total usable tiles in 2Q Core**: **46 tiles**.
- Usable tiles in SW: **25 tiles** (all tiles usable; none occupied by shed, but tiles `(4,3), (4,2)...` border the shed).

### Engine Land Pricing Schedule (`LAND_PRICES`):
- 1st Quadrant (Northeast / NE): **$1,000** (Unlocked Day 5 in baseline)
- 2nd Quadrant (Southwest / SW): **$2,000**
- 3rd Quadrant (Southeast / SE): **$4,000**

---

## 4. SW Feasibility Audit: Mature Farm (Days 13–26)

| Parameter | Early Game (Days 0–10, P1 Era) | Mature Farm (Days 13–26, P4 Era) | Feasibility Verdict |
| :--- | :---: | :---: | :--- |
| **Farm Cash Balance** | $314 – $1,800 | **$17,721 – $69,609** | **Fully Solved**: $2k cost is only 11% of Day 13 cash. |
| **Livestock Herd Status** | Unpurchased / Incomplete | **Fully Populated** (11.1 cows/sheep) | **Fully Solved**: Herd already generating $6k/day. |
| **Workforce Available** | 4 – 8 hands (partial) | **Full 13 Units** (Farmer + 12 hands) | **Fully Solved**: 312 worker-turns/day active. |
| **2Q Core Tile Utilization** | 50% – 70% | **94% Saturated** (42/46 tiles full) | **Binding**: Land is the sole physical constraint. |
| **Worker Turn Surplus** | 0 turns (strained) | **~50–80 idle/low-value turns/day** | **Available**: Enough turns to till/water 10–12 tiles. |

---

## 5. Counterfactual SW Production Models

If SW is unlocked on **Day 13 Hour 0** for $2,000:

### Model A: Pure Marginal Wheat Farm (12 Tiles in SW)
- **Acreage**: Cultivate only the 12 northernmost tiles of SW immediately adjacent to the center shed (minimizing transit).
- **Timeline**: 16 days remaining (Days 13–29). Allows **3 full 4-day wheat cycles** (Days 14–18, Days 18–22, Days 22–26).
- **Production**:
  - 12 tiles $\times$ 3 cycles = 36 plantings.
  - Yield: 36 $\times$ 6 units = 216 units of wheat.
  - Gross Revenue: 216 $\times$ $36.60 = **+$7,905.60**.
- **Costs**:
  - Land Cost: -$2,000.00
  - Seed Cost: 36 $\times$ $10 = -$360.00
  - Labor Required: 36 tilling + 36 planting + (12 $\times$ 12 watering) + 36 harvesting = 252 turns over 16 days (15.75 turns/day).
- **Net Modeled Gain**: **+$5,545.60**.

### Model B: Dedicated Strawberry Cluster (8 Tiles in SW)
- **Acreage**: 8 tiles planted on Day 14. First harvest Day 18; yields 2 units every 2 days through Day 28 (6 harvests $\times$ 2 units = 12 units/tile).
- **Production**: 8 tiles $\times$ 12 units = 96 strawberries $\times$ $245.58 = **+$23,575.68 gross revenue**!
- **Costs**:
  - Land Cost: -$2,000.00
  - Seed Cost: 8 $\times$ $100 = -$800.00
  - Labor: 8 till + 8 plant + (8 $\times$ 14 watering) + (8 $\times$ 6 harvesting) = 176 turns (11 turns/day).
- **Gross Theoretical Margin**: **+$20,775.68**!

---

## 6. The Critical Risk: Why SW Can Still Destroy Score

Even with mature capital and labor, SW expansion carries lethal systemic risks:

1. **Spatial Contagion (The P3.2 Lesson)**:
   In P3.2, moving workers across quadrants to care for animals destroyed **-$3,455/game** because it broke worker spatial locality and caused watering drops in the core.
   - If workers from the core are dispatched into SW to water crops, they spend transit turns traversing the quadrant boundary.
   - If a single watering sweep is delayed, 15 strawberry tiles in the core lose their watering bonus (-$1,800) or die.
2. **Weed Proliferation**:
   Unlocking SW spawns weeds across all 25 tiles of SW. If weeds are ignored, do they spread to adjacent tiles?
   - Engine check: Weeds spawn randomly on empty unlocked tiles. An unweeded SW quadrant creates pathing obstacles for workers.
3. **Over-Cultivation Trap**:
   If the planner tries to cultivate all 25 tiles of SW, labor demand surges by 50 turns/day, exhausting the workforce and triggering core farm starvation.

---

## 7. The Only Viable Architecture for SW Expansion

To test SW without repeating the P1 catastrophe, an experiment must enforce **five strict structural constraints**:

1. **Day 13+ Hard Gate**: SW purchase is strictly prohibited before Day 13 Hour 0 and requires `cash >= $15,000`. Zero impact on early bootstrapping.
2. **Zonal Acreage Cap (Maximum 8–10 tiles)**: Never cultivate all 25 tiles. Hard-cap SW cultivation to the 8 tiles immediately adjacent to the shed `(x: 3-4, y: 5-8)`.
3. **Dedicated SW Worker Cohort**: Exactly 2 specific workers (e.g. Hands 11 & 12) are permanently zoned to SW. Core workers (Farmer + Hands 1–10) are strictly forbidden from entering SW.
4. **Zero Livestock in SW**: SW is used exclusively for crops. All cows, sheep, and coops remain strictly in the 2Q core to prevent feed logistics disruption.
5. **Fail-Safe Abort**: If core farm cash or watering reliability drops, SW operations instantly halt.

> [!CAUTION]
> SW expansion is the **only physical mechanism capable of generating the +$20k+ needed to reach the $130,000 target**, because the 2Q core is physically saturated. However, it is also the highest-risk intervention in the project. It must only be attempted under bulletproof zonal isolation.
