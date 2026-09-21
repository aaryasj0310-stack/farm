# Kaggriculture P2.3 — Wheat Lifecycle Comprehensive Telemetry Audit

## Executive Summary

Across 20 full-season matches of True Production Control (`237cf5ee54498ed1ad2fa04d00ad9a0ebd27352e`, `QUADRANT_HARD_BLOCK={4}`) on fresh seeds (88,001–88,020) against all 5 opponent archetypes, we recorded the exact day-by-day and turn-by-turn physical and economic flow of every wheat unit.

### Core Season Aggregates (Per Game Average)

| Metric | Measured Baseline Value | Economic Impact |
| :--- | :--- | :--- |
| **Final Score** | **$101,615.20** | Reference Production Benchmark |
| **Wheat Tiles Planted** | **108.7 tiles** | $1,087 seed capital + 760 labor actions |
| **Wheat Units Harvested** | **369.3 units** | ~3.40 units/tile average realized yield |
| **Wheat Units Fed to Livestock** | **211.7 units** | Consumed by ~10–11 animal herd |
| **Wheat Bought from Market** | **841.5 units** | **$21,038.75 gross cash spent** |
| **Wheat Sold to Market** | **999.1 units** | **$24,978.75 gross revenue realized** |
| **Net Wheat Cash Flow** | **+$3,940.00** | Net receipts ($24,978.75 - $21,038.75) |
| **Endgame Unsold Wheat** | **0.0 units** | 100% liquidated by Day 29 |

---

## Complete Physical Balance Reconciliation

$$\text{Starting Inventory (0)} + \text{Harvested (369.3)} + \text{Bought (841.5)} - \text{Fed (211.7)} - \text{Sold (999.1)} = \text{Ending Inventory (0)}$$

$$\Delta = 369.3 + 841.5 - 211.7 - 999.1 = 0.0$$

The physical ledger reconciles with 100% mathematical precision.

---

## Planting Cohorts by Strategic Season Phase

| Season Phase | Days | Wheat Tiles Planted | Maturation Window | Primary Strategic Purpose |
| :--- | :---: | :---: | :---: | :--- |
| **Phase 1: Cash / Early Survival** | 0–4 | 15.0 tiles | Days 4–8 | Bootstrap cash for NE unlock ($1,000) & early 2 cows |
| **Phase 2a: NE Unlock & Herd Ramp** | 5–8 | 7.45 tiles | Days 9–12 | Scaling wheat alongside NE expansion |
| **Phase 2b: Strawberry Priority** | 9–13 | 23.25 tiles | Days 13–17 | Replanting harvested wheat up to 20-tile target |
| **Phase 3: Mid-Season Plateau** | 14–19 | 27.55 tiles | Days 18–23 | Continuous 20-tile maintenance replanting |
| **Phase 4: Late Replants** | 20–24 | 23.00 tiles | Days 24–28 | Matures during endgame; yields 2x remaining feed need |
| **Phase 5: Terminal Window** | 25+ | 12.45 tiles | Days 29–31+ | Days 26–27 plantings cannot mature before Day 30 |

### Critical Findings from Cohort Breakdown:
1. **Terminal Replants (Days 26–27)**:
   - Exactly **6.10 wheat tiles** are planted on Days 26–27.
   - Because wheat requires 4 full growth days to mature (`planted_day + 4`), wheat planted on Day 26 matures on Day 30, and Day 27 matures on Day 31.
   - The season ends at Day 30 Hour 0. These crops produce zero harvestable yield or revenue, directly wasting seed money and worker planting labor.
2. **Late-Season Oversupply (Days 20–25)**:
   - 29.35 wheat tiles are planted from Day 20 to Day 25.
   - These tiles yield ~100–120 wheat units between Day 24 and Day 29.
   - The entire herd of 11 animals only requires 11 units/day $\times$ 5 days = **55 units** to reach the Day 28 feed cutoff.
   - Over 50% of this late wheat is purely commercial surplus sold at $25/unit.

---

## Day-by-Day Wheat Transaction Dynamics

```
Day  Planted   Fed    Bought   Bought$   Sold    Sold$    ShedEOD  Animals
 0     7.0     2.0     33.0    $825.0    21.0    $525.0     0.0      2.0
 1     1.0     2.0     12.0    $300.0    10.0    $250.0     0.0      2.0
 4     7.0     2.0     12.0    $300.0    10.0    $250.0     0.0      2.0
 5     0.0     2.0      3.5     $87.5    29.8    $745.0     0.0      2.0
10     5.0     3.7     26.1    $651.2    11.2    $280.0     0.0      4.5
11     6.3     4.8     26.4    $658.8    23.8    $595.0     0.0      7.1
12     3.7     7.2     27.6    $691.2    16.6    $415.0     0.0      9.8
13     4.0     9.8     36.1    $903.8    34.8    $868.8     0.0     10.4
14     4.2     9.2     34.5    $862.5    36.5    $911.2     0.0     10.8
15     5.2    10.4     25.9    $647.5    31.3    $782.5     0.0     11.1
16     4.4    10.5     23.9    $598.8    34.5    $863.8     0.0     11.1
17     3.8    10.9     14.1    $351.2    17.6    $440.0     0.0     11.1
18     5.0    10.7     11.4    $286.2    16.9    $422.5     0.0     11.1
19     5.0    10.8     10.4    $261.2    15.8    $396.2     0.0     11.1
20     4.5    10.5     10.8    $268.8    19.1    $478.8     0.0     11.1
21     3.8    10.3     10.7    $266.2    15.3    $383.8     0.0     11.1
22     4.5    10.8     10.7    $267.5    15.9    $398.8     0.0     11.1
23     4.8    11.0     10.6    $265.0    16.4    $410.0     0.0     11.1
24     5.3    10.4     10.6    $265.0    18.9    $472.5     0.0     11.1
25     6.3    11.0     10.8    $271.2    14.2    $355.0     0.0     11.1
26     2.2    10.8     10.9    $272.5    14.4    $361.2     0.0     11.1
27     3.9    11.1     10.9    $272.5    14.2    $356.2     0.0     11.1
28     0.0    10.9    439.8  $10993.8   467.8  $11695.0     0.0     11.1
29     0.0     6.3      0.0      $0.0    58.7   $1467.5     0.0      0.0
```

### Key Lifecycle Takeaways:
1. **The Mid-Season Feed Churn**:
   - On Days 10–27, the agent continuously buys ~11–35 wheat units every day while simultaneously selling ~14–36 wheat units every day.
   - Because `MacroPlanner` at Hour 0 enforces `wheat_needed = animals * 4`, any depletion of shed wheat (from feeding or selling) triggers an immediate market buy order at $25.
   - Later in the day, field harvests replenish the shed, which `MarketBrain` then sells during scheduled sell windows.
2. **Gross Spend vs Net Leak**:
   - The agent spends $21,038.75 on wheat purchases and earns $24,978.75 from wheat sales.
   - Across the entire season, the agent is a net seller of wheat (+$3,940 net cash flow).
   - Therefore, the $21k wheat spend is NOT a $21k score leak. It is a cash-flow buffer churn.
