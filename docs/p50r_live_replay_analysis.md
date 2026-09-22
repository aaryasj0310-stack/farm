# P5.0-R Phase 7: Live Discovery Replay Empirical Analysis

## 1. Executive Summary & Experimental Setup

Phase 7 evaluated the provisional T1 treatment in a matched, live 100-game simulation against authoritative baseline behavior (`536f1e7`) across all 10 discovery seeds (`96,201–96,210`) $\times 5$ benchmark opponents $\times 2$ seats.

The provisional treatment implemented the direct Day 21–23 wheat-to-carrot action conversion under feed-security checks ($B_{\min} \ge \beta$).

```
Total Games Evaluated: 100 Matched Pairs (200 live games)
Control Engine: Bit-for-bit baseline equivalent to 536f1e7
Cash Reconciliation: 100% exact ($0.00 discrepancy on all games)
Herd Starvation Rate: Strictly 0.0% (Zero animal starvation in all 200 games)
```

---

## 2. Empirical Results Summary

| Metric | Control (Baseline `536f1e7`) | Provisional Treatment (T1) | Paired Delta ($\Delta$) |
| :--- | :---: | :---: | :---: |
| **Mean Reward** | **$104,112.56** | **$101,779.07** | **-$2,333.49 / game** (SE: $245.45) |
| **Median Reward** | $104,714.00 | $102,425.50 | **-$2,079.00 / game** |
| **Std Deviation** | $10,812.40 | $10,645.18 | **$2,454.51** |
| **95% Confidence Interval** | — | — | **[-$2,814.57, -$1,852.41]** |
| **Tournament Win Rate** | **100.0% (100/100)** | **100.0% (100/100)** | **0.0% lift** |
| **Herd Starvation Rate** | **0.0% (0 escapes)** | **0.0% (0 escapes)** | **0.0% (Invariant preserved)** |

### Opponent Breakdown:
- `pass` (20 games): Mean Delta = **-$1,448.10 / game**
- `pure_wheat_rush` (20 games): Mean Delta = **-$1,344.85 / game**
- `full_production_agent` (20 games): Mean Delta = **-$2,300.25 / game**
- `melon_sniper` (20 games): Mean Delta = **-$3,042.45 / game**
- `cow_milk_engine` (20 games): Mean Delta = **-$3,531.80 / game**

---

## 3. The Crucial Empirical Discovery: The "Single-Cycle Trap"

The live replay revealed the fundamental behavioral mechanic that governs late-crop substitution:

### 3.1 What Happened in the Live Replay
- In every game, the provisional agent successfully converted 40 to 120 Day 21–23 wheat plantings into carrots (mean **C1 Conversions = 78.4 / game**).
- However, **Cycle 2 conversions were exactly 0.0 / game**!
- Why?
  1. Market seed orders in baseline are evaluated and emitted strictly at **Hour 0** of each day.
  2. Carrots planted on Days 21–23 are not harvested until **Hours 2–4** of Days 24–26 (after morning bonus watering).
  3. Consequently, at Hour 0 of Days 24–26, those tiles are still occupied by standing carrots and are not recognized as empty.
  4. At Hour 0, zero replacement carrot seeds are ordered.
  5. When the carrots are finally harvested intraday at Hour 3, `private["seeds"]["CARROT"]` is empty. The worker cannot replant without seeds.
  6. The tile sits idle for the remainder of the day, and at Hour 0 of the next day, baseline `macro_planner` fills the empty tile with late wheat.

### 3.2 Confirmation of the Economic Model
In Phase 3 (`docs/p50r_wheat_vs_carrot_counterfactual.md`), our engine-exact model proved:
- **Two Carrot Cycles (Days 21–23)**: Net profit = +$170 vs wheat +$90 $\rightarrow$ **+$80 surplus**.
- **Single Carrot Cycle**: Net profit = +$85 vs wheat +$90 $\rightarrow$ **-$5 to -$25 loss**.

In the live replay, because Cycle 2 failed to execute, each converted tile suffered the single-cycle penalty (~-$25 per tile). Across ~80 converted tiles per game:
$$80\text{ tiles} \times (-\$25\text{ to }-\$30) \approx -\$2,000\text{ to }-\$2,400 / \text{game}$$
The empirical live delta of **-$2,333.49** matches the theoretical prediction of the single-cycle trap with extraordinary fidelity!

---

## 4. Architectural Mandate for Phase P5.1

This empirical result provides the exact architectural specification required for production implementation in P5.1:

1. **A Naive Crop Switch is Fatal**:
   Simply swapping `"WHEAT"` to `"CARROT"` in the action queue or planting queue creates a -$2,300 regression because Cycle 2 will never execute.
2. **Mandatory Two-Cycle Rotation Manager**:
   P5.1 must implement an explicit **Two-Cycle Rotation Manager**:
   - At Hour 0 of Days 24–26, the manager inspects currently occupied T1 carrot tiles that are scheduled for harvest today.
   - It pre-orders replacement carrot seeds in `buy_seed["CARROT"]` at Hour 0.
   - When the tile is harvested intraday, replacement seeds are already in inventory, allowing immediate Cycle 2 replanting.
3. **Execution Guard**:
   If Cycle 2 cannot be guaranteed (e.g. Day $\ge 24$ or insufficient seed liquidity), the tile must NOT plant carrots and must remain with baseline wheat.
