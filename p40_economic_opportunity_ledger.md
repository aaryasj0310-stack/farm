# Kaggriculture P4.0 — Economic Opportunity Ledger

## 1. Ledger Structure & Methodological Rules

This ledger synthesizes the complete economic findings of the P4.0 audit into a rigorous, non-overlapping opportunity matrix.

### Strictly Enforced Constraints:
1. **Non-Overlapping Accounting**: Mutually exclusive opportunities are evaluated independently. No double-counting of the same worker turns, physical tiles, or investment dollars.
2. **Three-Tier Opportunity Separation**:
   - **Gross Theoretical Opportunity**: Unconstrained ceiling assuming zero friction or displacement.
   - **Feasible Incremental Opportunity**: Modeled net gain after subtracting land, seed, labor transit, and displaced core farm value.
   - **Experimentally Validated Score Improvement**: Ground truth from completed A/B evaluations (0 until tested).
3. **The Target Reality**: The remaining ~$28.2k gap between the baseline ($101.8k) and the $130k goal is a project objective, NOT guaranteed recoverable money.

---

## 2. Structured Opportunity Ledger

| Opportunity Name | Baseline Behavior | Economic Mechanism | Activation Conditions & Frequency | Gross Theoretical Revenue | Incremental Costs & Displaced Value | Feasible Net Final-Score Delta | Principal Risk & Failure Mode | Prior Evidence & Level | Isolation Feasibility |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **1. Late-Season SW Zonal Crop Expansion** | `QUADRANT_HARD_BLOCK = {4}`. Land strictly locked to NW+NE (46 usable tiles). | Unlocks SW for $2,000 on Day 14 when cash > $15k. Cultivates 8 shed-adjacent tiles with strawberries/wheat. Dedicated 2-worker cohort. | Day 14 Hour 0; Cash >= $15,000; 2Q core >= 90% full. Frequency: **100% of games**. | +$18,000 to +$22,000 | -$2,000 Land<br/>-$800 Seeds<br/>-$1,500 Transit/Labor Drag | **+$8,000 to +$14,000** | **Spatial Contagion**: If core workers get sucked into SW, core watering drops, losing -$5k to -$13k (P1.3 / P3.2 risk). | P1 / P1.3-C failed (-$13k) due to early timing & whole-quadrant sprawl. *Level: Modeled*. | High (Can be gated by single feature flag, strict day/cash check, and dedicated worker IDs). |
| **2. Terminal Carrot Replanting (Days 26–27)** | Vacated tiles after Day 25 are left fallow. Only wheat replanted up to Day 25. | Replants 4–8 vacant tiles with 2-day carrots on Days 26–27 to harvest on Days 28–29 before final liquidation. | Days 26–27; Empty tiles >= 4; Cash >= $200. Frequency: **100% of games**. | +$800 to +$1,400 | -$150 Seeds<br/>-$300 Displaced liquidation/care labor | **+$350 to +$650** | **Liquidation Congestion**: Workers tilling/watering carrots on Days 28–29 displace shed deliveries, leaving unsold goods. | Direct analogue of P2.3 Marginal Wheat (+$445 promoted). *Level: Modeled*. | Very High (Trivial policy tweak in terminal replanting module). |
| **3. Core 2Q Crop Re-weighting (More Strawberries)** | Maintains ~15 strawberries, ~17 wheat, 11 animals in NW+NE. | Converts 5 wheat tiles to strawberries to capture higher gross return per tile-day ($122 vs $55). | Days 10–12 during NE planting. Frequency: **100% of games**. | +$4,000 | -$300 Seeds<br/>-$3,200 Extra wheat feed purchases<br/>-$1,000 Extra watering burden | **-$500 to +$500** (Net Zero) | **Feed Inflation**: Reduced farm wheat forces buying expensive market wheat. Daily watering exceeds labor limit. | P2.1 Dynamic Strawberry Cap failed (+$110, CI crossed zero). *Level: Modeled / Semi-Validated*. | High. |
| **4. Early-Game Capital Reallocation (Days 0–5)** | Commits $2,788 on Day 0 (16 melons, 4 hands), holds $314–$506 reserve for Day 5 NE unlock. | Diverts melon capital to quick-turnover carrots/wheat or earlier NE unlock. | Day 0 Hour 0. | +$1,500 | -$4,500 Displaced melon profits on Day 9/11 | **-$3,000** (Net Loss) | **Capital Asphyxiation**: Sacrificing Day 0 melons destroys the $14k cash wave that funds the herd and hands 5–12. | P4.0 Early Capital Audit proved zero uncommitted cash. *Level: Direct Audit*. | High. |
| **5. Market Price Timing / Inventory Hoarding** | Sells harvested products immediately upon shed deposit (dwell time ~0 turns). | Holds strawberries and milk in shed to sell during Days 25–29 peak prices. | Days 10–24. | +$1,200 | -$8,000 Delayed livestock capital on Days 10–13 | **-$6,800** (Net Loss) | **Liquidity Starvation**: Delayed cash delays buying cows/sheep, losing $240/day in animal yield. | P4.0 Market Realization Audit proved market is supply-deficit. *Level: Direct Audit*. | High. |

---

## 3. Comparative Evaluation & Macro Opportunity Summary

```
Opportunity Space Decomposition:
┌────────────────────────────────────────────────────────────────────────────────────────┐
│ TOTAL PROJECT GAP TO $130,000 TARGET: -$28,163.64 / game                              │
├────────────────────────────────────────────────────────────────────────────────────────┤
│ 1. Early Bootstrapping (Days 0-5)     : $0.00 recoverable (Capital 100% optimized)     │
│ 2. Core Crop Substitution (Days 6-25) : $0.00 recoverable (Portfolio at equilibrium)   │
│ 3. Market Selling Timing              : $0.00 recoverable (Liquid capital dominates)   │
│ 4. Terminal Carrot Squeeze (Days 26-27): +$350 to +$650 / game (Low risk, tiny upside) │
│ 5. Late SW Zonal Acreage Expansion    : +$8,000 to +$14,000 / game (HIGH upside, risky)│
├────────────────────────────────────────────────────────────────────────────────────────┤
│ MAX FEASIBLE PROGRESS TOWARD GAP: +$8,500 to +$14,500 / game                           │
│ REMAINING STRUCTURAL GAP: ~$14,000 to ~$20,000 / game                                  │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

> [!IMPORTANT]
> **Definitive Economic Conclusion**:
> 1. There are only **TWO** non-overlapping opportunities in the entire game that possess positive expected value:
>    - **Opportunity 1 (Late SW Zonal Expansion)**: +$8,000 to +$14,000 net.
>    - **Opportunity 2 (Terminal Carrot Replanting)**: +$350 to +$650 net.
> 2. All other candidate avenues (early cash, core crop reshuffling, market holding) are economically net-negative.
> 3. Between the two viable opportunities, **Opportunity 2 (Terminal Carrots)** is an incremental micro-gain (~+$500), whereas **Opportunity 1 (Late SW Expansion)** is the **sole physical intervention capable of materially bridging the score gap** toward $130k.
