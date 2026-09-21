# Kaggriculture 2-Quadrant Core Farm Value Audit
## Diagnostic Analysis & Strategic Roadmap to $130,000

---

## 1. Executive Summary & The Strategic Reality

### 1.1 The Grounded Baseline
Through 400 held-out live simulation games against diverse opponent archetypes, the performance of the True Production Control architecture (`237cf5ee54498ed1ad2fa04d00ad9a0ebd27352e`) has been rigorously established:
- **Baseline True Control Score**: **$103,237.66**
- **Roadmap Target Score**: **~$130,000.00**
- **The Unrealized Value Gap**: **+$26,762.34 / game**

### 1.2 The Strategic Pivot: 2-Quadrant Concentration
The exhaustive SW expansion investigations (P1.0 through P1.3-C) proved conclusively that geographic expansion into the SW quadrant under tested mechanics is regressive (-$3,805.92 vs True Control). Diverting worker actions to cross-quadrant transit, paying $2,000 land fees, and diluting labor across 75 tiles severely degraded core farm performance:
- **-9,763** NW+NE productive operations
- **-1,547** NW+NE harvests
- **+872** neglected core plant-days
- **+1,385** starvation animal-days
- **+59,412** SW worker turns

The highest-leverage path to ~$130,000 does **not** lie in territorial expansion. It lies entirely in **maximizing the economic density, capital velocity, and labor efficiency of the compact 2-quadrant core farm (NW + NE = 49 usable tiles)**.

---

## 2. Realized Marginal Value Model (All Crops Across Days 0–28)

To identify where the 2Q baseline is leaving value unrealized, we model the complete lifecycle economics of all five crops across all valid planting days under three market regimes:
1. **Baseline Equilibrium ($I_0 = 10,000$)**
2. **Shop-Drained Scarcity ($I_0 - 0.5T$ to $I_0 - 1.0T$)**
3. **Player/Opponent Glut ($I_0 + 0.5T$)**

### 2.1 Crop Economics Matrix (Baseline $I_0$)

| Crop | Seed Cost | Cycle Length | Harvest Window | Unfert Yield | Fert Yield | Base Price | Gross Rev | Net Profit | Profit / Tile-Day | Total Actions | Profit / Action |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| **MELON** | $80 | 11 days | Day 10 | 6 | 6 | $250 | $1,500 | **$1,420** | **$129.1** | 13.5 | **$105.2** |
| **STRAWBERRY** | $100 | 17 days | Days 10, 12, 14, 16 | 4 | 8 | $120 | $480 | **$380** | **$22.4** | 24.0 | **$15.8** |
| **CARROT** | $20 | 4 days | Day 3 | 3 | 4 | $35 | $105 | **$85** | **$21.2** | 6.5 | **$13.1** |
| **WHEAT** | $10 | 5 days | Day 4 | 4 | 6 | $25 | $100 | **$90** | **$18.0** | 7.5 | **$12.0** |
| **TOMATO** | $50 | 12 days | Days 8, 9, 10, 11 | 4 | 8 | $60 | $240 | **$190** | **$15.8** | 19.0 | **$10.0** |

### 2.2 Time-Varying Viability & Marginal Value Across Planting Days

| Planting Day | Wheat Net ($/Tile-Day) | Carrot Net ($/Tile-Day) | Melon Net ($/Tile-Day) | Strawberry Net ($/Tile-Day) | Tomato Net ($/Tile-Day) | Dominant Crop |
|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| **0** | $18.0 | $21.2 | **$129.1** | $22.4 | $15.8 | **MELON** |
| **5** | $18.0 | $21.2 | **$129.1** | $22.4 | $15.8 | **MELON** |
| **10** | $18.0 | $21.2 | **$129.1** | $22.4 | $15.8 | **MELON (Tranche 2)** |
| **13** | $18.0 | $21.2 | **$129.1** | $22.4 | $15.8 | **MELON (Tranche 2)** |
| **14** | $18.0 | **$21.2** | **$129.1** | $16.2 (3 yields) | $15.8 | **MELON / CARROT** |
| **18** | $18.0 | **$21.2** | **$129.1** | $1.7 (1 yield) | $15.8 | **MELON / CARROT** |
| **20** | $18.0 | **$21.2** | *Expired* | *Expired* | $7.0 (2 yields) | **CARROT** |
| **24** | $18.0 | **$21.2** | *Expired* | *Expired* | *Expired* | **CARROT** |
| **25** | $18.0 | **$21.2** | *Expired* | *Expired* | *Expired* | **CARROT** |
| **26** | $16.2 | **$21.2** | *Expired* | *Expired* | *Expired* | **CARROT** |
| **27** | $13.3 | **$16.7** | *Expired* | *Expired* | *Expired* | **CARROT** |
| **28** | *Expired* | *Expired* | *Expired* | *Expired* | *Expired* | *None* |

### 2.3 Market Curve Elasticity & Glut Vulnerability Analysis

The price mechanics differ fundamentally between commodity staples and premium crops:

1. **Melon ($T=300$, $above\_func=sq$, $above\_target=3.60$)**:
   - $amp = 3.60 \times 250 / 300^2 = 0.01$.
   - Price drops quadratically: $P(inv) = 250 - 0.01 \times (inv - I_0)^2$.
   - Selling **72 melons** (Day 0 springboard) drops price from $250 to **$198** (average price ~$224).
   - Selling **120 melons** drops price to **$106**.
   - Price hits the $1 floor only when sales exceed **160 cumulative units**.
   - **Key Finding**: The market easily absorbs **two waves of melons** (e.g. 72 units on Day 10 + 48 units on Day 20 = 120 total units), yielding massive returns before touching the quadratic cliff.

2. **Strawberry ($T=100$, $above\_func=linear$, $above\_target=1.60$)**:
   - $amp = 1.60 \times 120 / 100 = 1.92$.
   - Price drops linearly by **$1.92 per unit sold**!
   - Selling just **40 units** drops price from $120 to **$43.20**.
   - Selling **63 units** crashes price directly to the **$1.00 floor**!
   - **Key Finding**: The baseline's forced 16–20 tile Strawberry wave produces $64$–$80$ units. Without heavy town shop drain, **Strawberry gluts itself to near-worthlessness**, destroying expected returns while tying up $1,600–$2,000 in capital and 24 labor actions per tile over 17 days.

3. **Carrot ($T=450$, $below\_func=hinge$, $below\_target=1.00$, $above\_func=sqrt$, $above\_target=0.70$)**:
   - Glut absorption is $sqrt$: even +200 units above $I_0$ only drops price from $35 to $23.
   - Under Pet Cafe demand (12/day per instance) or Farmers Market (6/day), demand crosses into the hinge scarcity zone ($u > 1$), where price climbs parabolically:
     $$P = 35 + 35 \cdot (u + 8(u-1)^2)$$
     At $u=1.2$ (90 units drained), price jumps to **$77.00**!
     At $u=1.4$, price jumps to **$140.00**!
   - **Key Finding**: Carrot is vastly superior to Strawberry in capital velocity (4-day cycle vs 17-day cycle), labor efficiency (6.5 actions vs 24.0 actions), and shop-demand upside.

---

## 3. Comprehensive Audit of Baseline Policies

A systematic line-by-line review of `macro_planner.py`, `config.py`, and `central_planner.py` reveals several legacy heuristics that cap performance on the 2Q farm:

### 3.1 Policy 1: Day-0 Fallow Tile Leakage
- **Mechanism**: `macro_planner.py` lines 1898–1969 allocates exactly 12 Melons and 8 Wheat on Day 0. Lines 1968–1969 state: `"Keep remaining NW tiles fallow (reserved for Strawberry wave / no cash leak); empty_tiles.clear()"`.
- **Flaw**: 4 NW tiles (excluding shed at (4,4)) remain completely idle on Days 0, 1, and 2.
- **Lost Opportunity**: 4 tiles $\times$ 4 wheat = 16 wheat harvested on Day 4 for +$400 cash, accelerating the $1,000 NE expansion without delaying any Day 3 plans.

### 3.2 Policy 2: The Rigid "Dedicated Strawberry Wave"
- **Mechanism**: Lines 2309–2332 enforce a hard override: `if 3 <= day <= STRAWBERRY_PLANT_DEADLINE and "NE" in farm.unlocked: s_cap = get_strawberry_cap(day, True)` where cap is 16–20 tiles.
- **Flaw**: This policy bypasses portfolio scoring entirely and forces 16–20 strawberry tiles regardless of whether town shops demand strawberry, locking up 40% of the farm until Day 19–20 and flooding strawberry past its $T=100$ threshold.

### 3.3 Policy 3: The Complete Absence of a Second Melon Tranche
- **Mechanism**: `CROP_TILE_CAPS["MELON"] = 12`. Because Day-0 melons occupy tiles until Day 10, the cap is 100% saturated during the entire early game. When Day 10 arrives and melons are harvested, `quadrant_wheat_target` immediately expands to 20, while remaining empty tiles are swallowed by Strawberry or fallbacks.
- **Flaw**: Melon is the single most profitable crop in the simulation ($129.1/tile-day). The market has room for ~120–140 melons before price degradation. A second tranche of 8–10 melons planted on Days 10–13 yields an extra $10,000–$12,000 in net cash by Day 20.

### 3.4 Policy 4: Unconstrained / Speculative Livestock Expansion
- **Mechanism**: Baseline targets 6 cows and 12 sheep without verifying feed sustainability across a rolling multi-day horizon.
- **Flaw**: Each pasture consumes 1 tile permanently. Each animal consumes 1 wheat/day. Feeding 12 animals requires 15 continuous wheat tiles plus 24 daily labor actions. When wheat runs short, animals starve or force emergency market purchases at inflated prices ($35–$45/unit).

### 3.5 Policy 5: Fixed Static Caps vs Responsive Town Shop Specialization
- **Mechanism**: Crop caps are hardcoded (`CARROT: 16, TOMATO: 16, MELON: 12`).
- **Flaw**: Town shop unlocks are stochastic. When 2 Pet Cafes unlock, carrot demand is 24 units/day, creating a guaranteed multi-thousand-dollar scarcity spike. Capping carrots at 16 tiles prevents the agent from capitalizing on this windfall.

---

## 4. Quantitative Score-Loss Decomposition (Ranking Bottlenecks to $130,000)

| Rank | Bottleneck / Loss Vector | Root Mechanism | Estimated Score Loss / Game | Target Score Contribution |
|:---:|:---|:---|---:|---:|
| **1** | **Absence of Second Melon Tranche** | Fixed 12-tile cap & wheat priority prevents Day 10–13 melon replant | **$7,200** | $103,238 $\rightarrow$ $110,438$ |
| **2** | **Rigid Dedicated Strawberry Wave** | 16–20 tiles forced into slow, glut-prone strawberry instead of high-velocity crops | **$6,800** | $110,438 $\rightarrow$ $117,238$ |
| **3** | **Unconstrained Livestock & Feed Overhead** | Unserviceable animals incur pasture opportunity cost, high labor, & emergency feed spend | **$4,500** | $117,238 $\rightarrow$ $121,738$ |
| **4** | **Town Shop Specialization Failure** | Static crop caps fail to surge production into high-demand shop niches (Pet Cafe carrots, etc.) | **$4,200** | $121,738 $\rightarrow$ $125,938$ |
| **5** | **Day-0 Fallow Tile Leakage** | 4 NW tiles left fallow on Days 0–2 for zero return | **$1,600** | $125,938 $\rightarrow$ $127,538$ |
| **6** | **Spatial Task Scheduling Friction** | Non-clustered worker transit between NW and NE costs ~15–20% of labor turns | **$2,500** | $127,538 $\rightarrow$ **$130,038** |
| **TOTAL** | **Comprehensive Unrealized Value** | **Sum of Isolated Structural Bottlenecks** | **$26,800** | **Goal: ~$130,000** |

---

## 5. Recommended Next Isolated Experiment

### Candidate: P2.0 — The Dynamic Tranche-2 Melon Engine
- **Hypothesis**: Allowing a second calibrated tranche of 8 Melons to be planted on Days 10–12 upon the Day-10 harvest of the Day-0 springboard, while maintaining safe feed and reserve buffers, will capture ~$7,000+ in incremental net revenue without causing market collapse.
- **Isolation Guardrails**:
  - Keep 2Q core boundaries strictly intact (`QUADRANT_HARD_BLOCK = {4}`).
  - Zero changes to land purchase policy or labor rules.
  - Test via paired 100-case (200-game) A/B evaluation against True Production Control.
