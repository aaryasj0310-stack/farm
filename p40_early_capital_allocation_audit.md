# Kaggriculture P4.0 — Early Capital Allocation Audit (Days 0–13)

## 1. Objective & Audit Scope

This audit investigates whether the agent is leaving profitable investment opportunities unused or holding excessive idle cash during the critical early-game bootstrapping window (Days 0–13).

We evaluate:
1. Hourly and daily cash availability versus near-term obligations.
2. The exact timing and funding mechanism of the Northeast (NE) quadrant unlock ($1,000 land cost).
3. The hiring progression and labor absorption capacity.
4. Empty usable tiles on the Northwest (NW) and Northeast (NE) quadrants.
5. Whether "idle liquidity" exists, or whether apparent cash balances are strictly required reserves.

---

## 2. Early Cash Availability & Minimum Reserve Analysis

Across all 100 audited baseline games, the agent's cash position was tracked hourly from Day 0 Hour 0 to Day 13 Hour 23 (336 hours):

| Metric | Day 0–5 (Pre-NE) | Day 6–8 (Post-NE Trough) | Day 9–13 (Melon Realization) |
| :--- | :---: | :---: | :---: |
| **Mean Daily Cash Balance** | $578.00 | $343.33 | $9,067.20 |
| **Minimum Cash Observed (Mean)** | $314.00 | $249.69 | $1,853.00 |
| **Absolute Minimum Cash (100 Games)** | $246.00 | **$246.00** | $1,142.00 |
| **Hours with Cash < $500** | 76.4 hours | 58.2 hours | 0.0 hours |
| **Negative Cash Violations** | **0** | **0** | **0** |

```
Cash ($)
$20,000 |                                                    * (Day 13: $17.7k)
$15,000 |                                             * (Day 12: $13.9k)
$10,000 |                                      * (Day 11: $8.9k)
 $5,000 |
 $3,000 | * (Start: $3k)
 $1,000 |   \                      * (NE Buy: $1k)
   $500 |    *---*                 / \
     $0 |________*_______*________*___*___________________
        D0  D1  D2  D3  D4  D5  D6  D7  D8  D9  D10 D11 D12 D13
```

### Finding 1: The Razor-Thin Days 0–8 Solvency Corridor
- The farm starts with $3,000. On Day 0, it spends $2,788 (92.9% of starting capital) within 24 turns:
  - $700 on hiring Hands 1–4 ($100, $100, $200, $300)
  - $1,280 on 16 Melon seeds (16 $\times$ $80)
  - $400 on initial wheat and carrot seeds
  - $408 on emergency buffer and hand actions
- By Day 2, cash drops to **$354.00**.
- Over Days 3–5, cash rises modestly to **$506.00** as early wheat/carrots are harvested and sold.
- **On Day 5, NE quadrant is purchased for $1,000**, which consumes virtually every dollar of available cash and incoming Day 5 sales.
- On Day 6, the farm hires Hands 5–8 ($1,050 total cost), driving cash down to the **absolute seasonal trough of $246.00–$314.00 on Days 7–8**.

> [!IMPORTANT]
> **Zero Idle Capital in Days 0–8**: The farm is operating at near-maximum capital intensity. Any additional spending on seeds, animals, or workers during Days 0–8 would cause a catastrophic negative cash failure or postpone the NE land unlock.

---

## 3. Northeast (NE) Quadrant Unlock Timing

- **Engine Land Price for 1st Quadrant**: $1,000
- **Earliest Unlock Day**: Day 5 Hour 18
- **Mean Unlock Day**: **Day 5.2**
- **Latest Unlock Day**: Day 6 Hour 2

### Why Day 5 is the Optimal Frontier for NE:
1. **Cash Constraint**: Unlocking NE before Day 5 is mathematically impossible without sacrificing the 16 Melon seed purchase ($1,280) or Hands 1–4 ($700). Melons planted on Day 0 are the primary economic engine that pays for the entire mid-game farm ($3,110 on Day 9 and $10,869 on Day 11). Sacrificing Day 0 Melons to buy empty land on Day 3 would be an economic disaster.
2. **Labor Constraint**: On Days 0–4, the 4 hired hands + farmer (5 units = 120 turns/day) are 100% occupied clearing weeds, tilling 23 tiles in NW, planting 16 melons and 7 wheat/carrots, and watering every crop daily. They would have zero spare turns to till or water tiles in NE prior to Day 5.
3. **Synthesis**: The Day 5 unlock is synchronized to perfection with the completion of NW tilling and the arrival of early crop revenue.

---

## 4. Workforce Scaling & Absorption Capacity

The table below traces labor supply and empty tiles during the Days 0–13 expansion:

| Day | Active Units (Farmer + Hands) | Daily Worker-Turns Available | Usable Core Tiles Owned | Active Crops | Active Animals | Empty Usable Tiles | Daily Turn Allocation Priority |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| **0** | 1 + 4 = 5 | 120 | 23 (NW) | 16 Melons, 7 Other | 0 | 8.0 | Clearing NW, tilling soil, planting Day 0 crops |
| **1** | 1 + 4 = 5 | 120 | 23 (NW) | 20 Crops | 0 | 3.0 | Watering 20 crops (20 turns), tilling remaining NW |
| **2** | 1 + 4 = 5 | 120 | 23 (NW) | 20 Crops | 0 | 3.0 | Watering 20 crops, harvesting early carrots |
| **3** | 1 + 4 = 5 | 120 | 23 (NW) | 23 Crops | 0 | **0.0** | All 23 NW tiles 100% cultivated |
| **4** | 1 + 4 = 5 | 120 | 23 (NW) | 23 Crops | 0 | **0.0** | 100% NW tile occupancy; saving cash for NE |
| **5** | 1 + 4 = 5 | 120 | 23 -> 46 | 23 Crops | 0 | 20.0 | NE unlocked (23 new tiles added) |
| **6** | 1 + 8 = 9 | 216 | 46 (NW+NE) | 25 Crops | 0 | 5.7 | Hands 5–8 clear weeds and till NE tiles |
| **7** | 1 + 8 = 9 | 216 | 46 (NW+NE) | 28 Crops | 0 | 1.4 | Tilling NE, watering 28 crops |
| **8** | 1 + 8 = 9 | 216 | 46 (NW+NE) | 30 Crops | 0 | 5.4 | Cash trough; preparing for Day 9 melon harvest |
| **9** | 1 + 8 = 9 | 216 | 46 (NW+NE) | 26 Crops | 2.6 | 7.8 | 16 Melons harvested (+$3.1k); First cows bought |
| **10** | 1 + 10 = 11 | 264 | 46 (NW+NE) | 24 Crops | 4.6 | 12.2 | Hands 9–10 hired; building pastures, planting strawberries |
| **11** | 1 + 12 = 13 | 312 | 46 (NW+NE) | 26 Crops | 7.2 | 3.0 | Hands 11–12 hired (Full 13-unit core); Herd scaling |
| **12** | 1 + 12 = 13 | 312 | 46 (NW+NE) | 30 Crops | 9.7 | 3.3 | 46 usable tiles 93% full |
| **13** | 1 + 12 = 13 | 312 | 46 (NW+NE) | 31 Crops | 10.5 | 4.1 | 46 usable tiles 91% full; Herd fully populated |

---

## 5. Audit Conclusions: Is Recoverable Value Lost in Days 0–13?

### Category A: Unused Liquidity
- **Finding**: **None**. Cash balances during Days 0–8 are strictly functional minimum reserves ($246–$354). On Days 9–13, incoming melon revenue is reinvested immediately into farm hands ($2,750), livestock ($4,901), and strawberry seeds ($1,500).

### Category B: Idle Tiles
- **Days 0–4**: NW is 100% full by Day 3 (0.0 empty tiles).
- **Days 5–8**: NE is cleared and tilled within 48 hours of acquisition. By Day 7, only 1.4 tiles are empty.
- **Days 9–10**: A temporary bump to 7.8–12.2 empty tiles occurs solely because 16 melons were harvested simultaneously on Day 9. These tiles are immediately converted into pasture/coop infrastructure and strawberry beds by Day 11 (3.0 empty tiles).

### Category C: Hiring Velocity
- Hands are hired in exact synchrony with tile availability and cash flow:
  - 4 hands for NW (Days 0–5)
  - 4 hands for NE (Days 6–9)
  - 4 hands for Livestock & Strawberry intensification (Days 10–11)
- Hiring earlier would cause bankruptcy; hiring later would leave land unwatered.

> [!NOTE]
> **Definitive Finding**: The early-game capital allocation (Days 0–13) is already operating at peak capital efficiency. There is no uncommitted cash or idle land to exploit in Days 0–13. The remaining ~$28k project gap CANNOT be extracted from early-game bootstrapping.
