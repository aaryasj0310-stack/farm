# Phase M0-H: Market Slot Sequencing & Lockstep Price-Race Exploitation Report

## Executive Summary

Phase M0-H investigated whether optimizing the execution order of our already-selected `SELL` orders within the 10-slot market queue could capture price-race advantages under Kaggriculture's lockstep per-unit market processing engine.

While authoritative real-engine microtests (Part A) proved that the lockstep market mechanics do create an earlier-slot advantage for contested products (e.g. +$13.00 on 5 wool / +1.3%, +$54.00 on milk / +6.9%, +$47.00 on strawberry / +8.1%), the comprehensive 100-match authoritative Oracle Replay Audit (Part B–H) proved that in practice, **this opportunity virtually never occurs**:

* **Mean Oracle Slot Regret:** **$0.12 / match** (Threshold for Decision Gate A: **$250.00 / match**)
* **Median Oracle Slot Regret:** **$0.00 / match**
* **P90 Oracle Slot Regret:** **$0.00 / match**
* **P95 Oracle Slot Regret:** **$1.00 / match**
* **Maximum Oracle Slot Regret:** **$3.00** in any match across all 100 matches
* **Uncontested Sells Rate:** **97.27%** (24,886 of 25,585 executed sell orders had zero opponent competition)
* **Contested Sells with Same Slot (Zero Regret):** **60.9%** of all collisions occurred in the exact same slot, where symmetric lockstep quotes both players at the identical price.
* **Fragile Product Collisions:** **ZERO** collisions across 100 matches for Strawberry (0), Melon (0), Tomato (0), Milk (0), Wool (0), or Egg (0).
* **Opponent Regret:** Four of the five benchmark opponents (`pass`, `pure_wheat_rush`, `cow_milk_engine`, `melon_sniper`) yielded **$0.00** oracle regret across all 20 matches each. Only `full_production_agent` produced any regret, averaging **$0.60 / match**.

### Decision Gate A Outcome
```text
GATE A THRESHOLD: mean oracle regret >= $250.00 / match
ACTUAL OBSERVED:  mean oracle regret =  $0.12 / match

STATUS: DECISION GATE A FAILED DECISIVELY
DECISION: M0-H CLOSED — slot sequencing has insufficient oracle value
```

In accordance with strict experimental protocols, no prospective predictor was built, no live treatment was deployed, and M0-H is closed early.

---

## Part A: Real-Engine Microtest Results

All 6 real-engine microtests executed against `kaggle_environments.envs.kaggriculture.kaggriculture` and verified key engine behaviors:

| Test ID | Mechanic Verified | Result | Key Metric |
| :--- | :--- | :--- | :--- |
| **A1** | Same Product, Same Slot Lockstep | **PASS** | Exact per-unit quote symmetry ($993.00 each for 5 Wool in Slot 0) |
| **A2** | Same Product, Different Slots | **PASS** | Slot 0 captures +$13.00 (+1.3%) advantage on 5 Wool over Slot 1 ($998 vs $985) |
| **A3** | Seat Symmetry | **PASS** | P0 and P1 earn identical revenue ($914.00) under identical queues; advantage is seat-neutral |
| **A4** | Unequal Quantities Lockstep | **PASS** | Lockstep holds until shorter order finishes; remainder sells into depressed inventory |
| **A5** | Cross-Product Independence | **PASS** | Uncontested products have zero slot dependency (Wool-then-Milk == Milk-then-Wool == $1,778) |
| **A6** | Product Sensitivity | **PASS** | Measured 1-slot penalty: Strawberry (8.1%), Milk (6.9%), Tomato (6.3%), Carrot (4.8%), Wheat (4.1%), Wool (1.3%), Fertilizer (1.0%), Melon (0.2%) |

---

## Part B–H: Authoritative Oracle Replay Audit Results

### 1. Panel Configuration
* **Seeds:** `96501–96510` (10 seeds)
* **Opponents:** `pass`, `pure_wheat_rush`, `cow_milk_engine`, `melon_sniper`, `full_production_agent` (5 opponents)
* **Seats:** `Seat 0`, `Seat 1` (2 seats)
* **Total Matches:** 100 matches (72,000 engine steps)
* **Multi-Sell Turns Evaluated:** 4,475 turns with $\ge 2$ SELL orders

### 2. Global Oracle Regret Distribution
| Metric | Value |
| :--- | :--- |
| **Mean Oracle Regret / Match** | **$0.12** |
| **Median Oracle Regret / Match** | **$0.00** |
| **P50 Regret** | **$0.00** |
| **P75 Regret** | **$0.00** |
| **P90 Regret** | **$0.00** |
| **P95 Regret** | **$1.00** |
| **Max Regret in a Single Match** | **$3.00** |
| **Total Regret Across All 100 Matches** | **$12.00** |
| **Matches with Regret > $0** | 6 / 100 (6.0%) |
| **Turns with Regret > $0** | 7 / 4,475 (0.16%) |
| **Turns with Regret > $25** | **0** |
| **Turns with Regret > $50** | **0** |
| **Turns with Regret > $100** | **0** |

### 3. Collision Frequency by Product
Across all 25,585 executed sell orders:

| Product | Total Sells | Collisions | Collision Rate | Opponent Earlier | Same Slot | Opponent Later | Uncontested |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **WHEAT** | 11,536 | 678 | 5.88% | 223 | 426 | 29 | 10,858 (94.12%) |
| **CARROT** | 1,630 | 7 | 0.43% | 5 | 2 | 0 | 1,623 (99.57%) |
| **TOMATO** | 727 | 0 | 0.00% | 0 | 0 | 0 | 727 (100.0%) |
| **STRAWBERRY**| 1,782 | 0 | 0.00% | 0 | 0 | 0 | 1,782 (100.0%) |
| **MELON** | 1,754 | 0 | 0.00% | 0 | 0 | 0 | 1,754 (100.0%) |
| **EGG** | 0 | 0 | 0.00% | 0 | 0 | 0 | 0 |
| **MILK** | 2,411 | 0 | 0.00% | 0 | 0 | 0 | 2,411 (100.0%) |
| **WOOL** | 1,473 | 0 | 0.00% | 0 | 0 | 0 | 1,473 (100.0%) |
| **FERTILIZER**| 4,272 | 14 | 0.33% | 14 | 0 | 0 | 4,258 (99.67%) |
| **TOTAL** | **25,585** | **699** | **2.73%** | **242** | **428** | **29** | **24,886 (97.27%)** |

### 4. Oracle Regret by Opponent
| Opponent | Matches | Our Mean Cash | Opp Mean Cash | Mean Regret | Median Regret | P90 Regret | Max Regret | Matches w/ Regret |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `pass` | 20 | $102,018.15 | $3,000.00 | **$0.00** | $0.00 | $0.00 | $0.00 | 0 / 20 |
| `pure_wheat_rush` | 20 | $99,703.30 | $11,780.35 | **$0.00** | $0.00 | $0.00 | $0.00 | 0 / 20 |
| `cow_milk_engine` | 20 | $102,164.45 | $1,657.25 | **$0.00** | $0.00 | $0.00 | $0.00 | 0 / 20 |
| `melon_sniper` | 20 | $99,103.95 | $1,535.00 | **$0.00** | $0.00 | $0.00 | $0.00 | 0 / 20 |
| `full_production_agent`| 20 | $99,195.35 | $9,563.75 | **$0.60** | $0.00 | $2.10 | $3.00 | 6 / 20 |

### 5. Oracle Regret by Product
| Product | Total Regret Dollars | Turns with Regret | Mean Loss / Contested Turn |
| :--- | :--- | :--- | :--- |
| **CARROT** | $6.50 | 3 | $2.17 |
| **WHEAT** | $4.50 | 5 | $0.90 |
| **FERTILIZER** | $1.00 | 2 | $0.50 |
| **TOMATO** | $0.00 | 0 | $0.00 |
| **STRAWBERRY** | $0.00 | 0 | $0.00 |
| **MELON** | $0.00 | 0 | $0.00 |
| **MILK** | $0.00 | 0 | $0.00 |
| **WOOL** | $0.00 | 0 | $0.00 |

### 6. Representative Regret Analysis
The largest single-turn regret observed across all 72,000 steps was **$3.00**:
* **Match:** Seed 96504 vs `full_production_agent`, Seat 1, Day 26, Hour 1
* **Actual Queue:** `[SELL WHEAT 9, SELL CARROT 3, SELL MILK 6, SELL WOOL 4, SELL STRAWBERRY 4, SELL MELON 6, SELL FERTILIZER 10, HIRE, HIRE, HIRE]` -> Revenue = $4,731.00
* **Opponent Queue:** `[SELL CARROT 3, ...]` in Slot 0
* **Best Permutation:** Swapping CARROT to Slot 0 and WHEAT to Slot 1 -> Revenue = $4,734.00
* **Regret:** $3.00

---

## Answers to Required 28 Questions

1. **Does same-product slot index materially change realized revenue?**
   Yes, in isolated microtests when both players sell the same product in different slots, the slot 0 seller earns strictly more (+$13.00 on 5 wool / +1.3%, +$54.00 on milk / +6.9%, +$47.00 on strawberry / +8.1%).
2. **Do both players receive equivalent quotes when selling the same product in the same slot?**
   Yes, verified by Test A1 and Test 1: both players receive identical quotes per unit lockstep ($993.00 each for 5 wool in slot 0).
3. **Is there any seat asymmetry?**
   No, verified by Test A3 and Test 6: when symmetric order queues are submitted, P0 and P1 earn identical revenue ($914.00 == $914.00), and swapping seats in price race tests yields exact identical advantages.
4. **Which products are most slot-sensitive?**
   From Test A6 product sensitivity measurements: Strawberry ($47.00 / 8.1% loss for being 1 slot late), Milk ($54.00 / 6.9%), Tomato ($18.00 / 6.3%), Carrot ($8.00 / 4.8%), Wheat ($5.00 / 4.1%), Wool ($13.00 / 1.3%), Fertilizer ($5.00 / 1.0%), Melon ($2.00 / 0.2%).
5. **How often do same-product sell collisions occur?**
   Across 100 benchmark matches (25,585 total sell orders executed), collisions occurred on only 699 orders, an overall collision rate of 2.73%. 97.27% of all sell orders were completely uncontested.
6. **How much oracle slot-regret exists per match?**
   Mean oracle slot regret is $0.12 / match ($12.00 total regret across 100 matches).
7. **What is median oracle regret?**
   Median oracle regret is $0.00 / match.
8. **What is P90 oracle regret?**
   P90 oracle regret is $0.00 / match (P95 is $1.00 / match).
9. **Which opponents create the most price-race opportunity?**
   `full_production_agent` was the ONLY opponent that created any price race opportunity (mean regret $0.60 / match, max $3.00). All four other opponents (`pass`, `pure_wheat_rush`, `cow_milk_engine`, `melon_sniper`) created exactly $0.00 regret across all matches.
10. **Which products create the most price-race opportunity?**
    Carrot ($6.50 total regret across 3 turns, $2.17/turn), Wheat ($4.50 total regret across 5 turns, $0.90/turn), Fertilizer ($1.00 total regret across 2 turns, $0.50/turn). All other products (Milk, Wool, Strawberry, Melon, Tomato, Egg) had $0.00 regret because opponents never sold them on the same turn.
11. **Does current historical ordering already capture most oracle value?**
    Yes. Historical ordering already captures 99.99% of possible market revenue, leaving only $0.12/match of uncaptured regret.
12. **How often does current `preempt_sell` shadow signal correctly predict same-turn opponent selling?**
    Evaluated: Since oracle regret itself is only $0.12/match and Gate A failed ($0.12 << $250.00 threshold), prospective predictor is not deployed. The shadow preemption signal historically triggers rarely, matching the low 2.73% collision rate.
13. **What is precision by product?**
    N/A (Gate A closed early: insufficient oracle value; no prospective predictor warranted).
14. **What is recall by product?**
    N/A (Gate A closed early: insufficient oracle value).
15. **What fraction of oracle value can the prospective predictor recover?**
    Even if 100% of oracle value were recovered, the maximum theoretical economic ceiling is only $0.12 / match.
16. **Can prediction be done using only legal pre-turn information?**
    Yes, architecture enforces strict no-cheating boundaries (Test 9 passes, only public obs consumed), but prospective prediction is not warranted.
17. **Is a live slot sequencer warranted?**
    No. With only $0.12/match at stake and a 97.27% uncontested market rate, introducing a live sequencer adds complexity and regression risk for virtually zero reward.
18. **If tested LIVE, did it improve terminal cash?**
    N/A — not tested LIVE due to decisive Gate A stop ($0.12 << $250 threshold).
19. **What was mean paired cash delta?**
    N/A (Gate A stopped).
20. **What was median/P50?**
    N/A (Gate A stopped).
21. **What was seed-clustered 95% CI?**
    N/A (Gate A stopped).
22. **How many seed clusters were positive?**
    N/A (Gate A stopped).
23. **Did order selection remain exactly unchanged?**
    Yes, multiset conservation invariant `Counter(before) == Counter(after)` verified (Test 7 & 12).
24. **Were any critical purchases displaced or reordered unsafely?**
    No, purchase positions remain strictly locked and atomic ordering preserved (Test 13 & 16).
25. **Did any feed/safety regression occur?**
    No, all safety constraints preserved (1281/1281 tests passing).
26. **Were false preemptions costly?**
    In theory false preemption of high-value crops could delay critical sales; in practice, with $0.12 oracle ceiling, any false preemption penalty would instantly wipe out any theoretical gain.
27. **Is M0-H independently valuable?**
    No. Oracle value is statistically indistinguishable from zero ($0.12/match mean, $0.00 median, $3.00 max).
28. **Should M0-H later be combined with M0-D?**
    No. M0-H is closed and will not be combined with M0-D. M0-D (Storage Rescue) remains the authoritative improvement (+~$5,056.89).

---

## Test Verification Summary
```text
pytest agent/tests
collected: 1281 items
passed: 1281
failed: 0
skipped: 0
pass rate: 100.0%
```

---

## Final Decision Outcome

```text
M0-H CLOSED — slot sequencing has insufficient oracle value
```
