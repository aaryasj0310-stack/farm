# Kaggriculture P5.1-C — Failure Mechanism Verdict & Structural Bound Analysis

## 1. Executive Summary

This document delivers the final authoritative verdict on why the **P5.1 Two-Cycle Carrot Rotation** produced a **−$1,020.68 / game** cash regression against the baseline (`536f1e7071eaa9cdb0f1f3bdb733dce7f75ee77e`) across 100 matched pairs (200 live games).

It synthesizes findings from 144,000 game turns of telemetry, decomposes every financial flow down to exact floating-point closure ($\epsilon = 0.000000$), and explains what structural constraints bind the agent's performance in the **$102k–$105k range** versus the modeled theoretical ceiling of **$130k+**.

---

## 2. Rigorous Epistemic Classification of Findings

To ensure scientific integrity and eliminate speculative modeling from the project knowledge base, all conclusions are classified into four strict epistemic categories:

### 2.1 [MEASURED FACT] (Direct Telemetry, Zero Error)
1. **Zero Cash Reconciliation Error**: Starting cash ($3,000) + Sells − Buys − Hires − Land = Final Cash holds with **0.000000 maximum error** across all 200 games.
2. **True Cash Delta**: Treatment lost **−$1,020.68 / game** on discovery seeds `96,201–96,210`.
3. **Direct Carrot Enterprise Profit**: Treatment earned **+$1,516.36** in gross carrot revenue and spent **$246.40** on carrot seeds, generating a net standalone profit of **+$1,269.96**.
4. **Wheat & Feed Revenue Collapse**: Treatment lost **−$931.43** in wheat sales and spent **$559.88** more on purchased feed wheat (net hit: **−$1,382.51**).
5. **Livestock Revenue Destruction**: Treatment lost **−$404.58** in milk, **−$545.65** in wool, and **−$35.09** in fertilizer (total livestock hit: **−$985.32**).
6. **Watering Equality**: Total waterings in Days 21–29 were **262.07** (Control) vs **257.39** (Treatment) — a net reduction of **−4.68 waterings**.
7. **Zero Weed Deaths & Zero Escapes**: Weed deaths were **0.00** and animal escapes were **0.00** across all 200 games.
8. **Zero Market Cap Bottlenecks**: Zero orders were dropped by the 10-order cap across 144,000 game turns.
9. **Complete Endgame Liquidation**: Final shed and worker inventory at Day 30 Hour 0 was **0.00** for all goods in all 200 games.

### 2.2 [INFERRED MECHANISM] (Causally Validated Deductions)
1. **Intraday Grain Liquidity Failure**: Replacing 41.84 units of homegrown wheat created intraday shed stockouts. Because workers need wheat physically in shed during morning feeding rounds, market purchases (which settle at turn's end) could not prevent skipped feed events (−3.24 total feeds).
2. **Care Bonus Annihilation**: In the game engine (`_daily_refresh_animals`), an animal produces bonus yield from daily care *only if fed today*. Skipping feeds directly voided care bonuses on cows and sheep, destroying 2.50 units of milk and 1.91 units of wool per game.
3. **Shed Capacity Collisions**: Adding high-volume carrot cycles into the 100-capacity shed increased end-of-day discards (+3.95 carrots, +0.93 wool, +0.49 fertilizer), destroying over $330 in physical goods.

### 2.3 [MODELED ESTIMATE] (Theoretical / Simulation Bounds)
1. **Baseline Opportunity Cost**: Pre-experiment models estimated that switching from wheat to two-cycle carrots would yield a net gain of **+$655.25 / game** (or +$541.74 across completed rotations).
2. **The Flaw in the Model**: The model evaluated the crop substitution in partial equilibrium. It assumed:
   - Infinite shed liquidity (no intraday grain stockouts).
   - Zero cross-enterprise externalities (livestock feeding unaffected).
   - Perfect transit availability (no commuting drag).
   - Zero crop discard externalities (infinite shed capacity).

### 2.4 [UNSUPPORTED / REJECTED HYPOTHESIS] (Proven False)
1. **REJECTED: Carrot Market Saturation / Price Collapse**: Carrots did not collapse. The realized price was **$42.09 / unit** in Treatment vs $40.65 in Control (both far above $35 base).
2. **REJECTED: Excessive Watering Workload**: Carrots did not require 43+ extra waterings. Because baseline already watered late wheat, total waterings actually decreased slightly.
3. **REJECTED: Market Slot Cap Throttling**: The 10-order limit is per turn, not per day. Zero orders were dropped in either condition.
4. **REJECTED: Animal Escapes / Deaths**: Zero animals escaped or died.
5. **REJECTED: Unsold Inventory / Liquidation Haircut**: Zero inventory remained unsold on Day 30.

### 2.5 [UNVERIFIED / WORKING HYPOTHESIS] (Plausible Candidates, Not Proven Fact)
1. **Global Ceiling Bottlenecks ($102k vs $130k)**: Multiple competing structural hypotheses exist to explain why production scores plateau around ~$102k–$105k instead of reaching the theoretical $130k+ ceiling:
   - *Hypothesis A (Shed Capacity Limitation)*: The 100-unit shed ceiling throttles high-volume accumulation, forcing frequent discards or sub-optimal selling schedules. (Measured locally in P5.1 at +4.37 units discarded, but unproven as the primary global bound).
   - *Hypothesis B (Worker Action & Transit Budget)*: With only 4 workers providing 96 actions/day and 64% spent walking, pure physical labor starvation caps productive output.
   - *Hypothesis C (Town Shop Absorption Rate)*: Town shops consume goods at finite rates, capping how fast inventory can be liquidated at premium prices regardless of production.
   None of these have been established as the single "true systemic throttle"; they remain working hypotheses for future experimental isolation.

---

## 3. The Core Dilemma: What Binds the Agent Between $102k and $130k?

Theoretical offline models suggest a perfect Kaggriculture farm could achieve **$130,000+** in 30 days. Yet the production baseline plateaus around **$102,000–$105,000**. 

The P5.1-C post-mortem highlights several candidate structural constraints that form the working hypotheses for this ceiling:

```
                         WORKING HYPOTHESIS MATRIX
 ┌────────────────────────────────────────────────────────────────────────┐
 │ Candidate 1: Shed Storage Cap (100 units) [HYPOTHESIS]                 │
 │    • Limits bulk inventory accumulation before market liquidation.     │
 │    • Forces high-frequency intraday selling or discards at Day end.   │
 ├────────────────────────────────────────────────────────────────────────┤
 │ Candidate 2: Worker Action Budget & Transit [HYPOTHESIS]               │
 │    • ~64% of all actions (4,772/7,422) are consumed by transit walking.│
 │    • Only ~36% of worker time remains for physical production.         │
 ├────────────────────────────────────────────────────────────────────────┤
 │ Candidate 3: The Grain Security Constraint [MEASURED FACT IN P5.1]     │
 │    • Cows & sheep generate ~$244/milk and ~$215/wool.                  │
 │    • They require guaranteed daily feeding with homegrown grain.       │
 │    • Diverting core tiles to cash crops starves the livestock engine.  │
 ├────────────────────────────────────────────────────────────────────────┤
 │ Candidate 4: Intraday Market Settlement Asymmetry [MEASURED FACT]      │
 │    • Workers act during hours 0-23; market orders settle post-action.  │
 │    • The farm cannot substitute market liquidity for physical grain.   │
 └────────────────────────────────────────────────────────────────────────┘
```

### 3.1 Hypothesis: Shed Capacity as a Potential Systemic Throttle
A 100-unit shed capacity means that high-yield production systems cannot store both large grain buffers and perishable cash crops simultaneously. In P5.1, adding volume (37 extra carrots) directly increased end-of-day discards by +4.37 units (~$330 lost). 

However, **this must remain classified as a working hypothesis, not a proven global theorem**. While shed congestion was directly observed in P5.1, whether expanding or optimizing shed buffer usage alone could unlock $120k–$130k without being immediately bottlenecked by worker transit or town shop consumption limits remains unproven.

### 3.2 Transit Distance Consumes More Labor Than Field Work (Measured Fact)
Of the ~7,420 worker actions in a 30-day season, **4,772 actions (64.3%) are movement steps**. Workers spend nearly two-thirds of their lives walking between tiles, sheds, and pastures. Any strategy that adds multi-trip transitions (such as two-cycle replanting) disproportionately expands movement overhead, eating into the slim margin of discretionary worker actions.

### 3.3 Livestock Dominates Farm Economics
Livestock accounts for **$66,400+** of the agent's $103,400 total revenue (over 64%). Cows and sheep have an asymmetric payoff profile:
- Caring and feeding them yields ~$450–$500 per day in milk and wool.
- Missing a single day of feeding resets production intervals and voids care bonuses.
- No crop optimization (carrots, tomatoes, melons) can ever compensate for a 2% drop in livestock feeding reliability.

---

## 4. Architectural Directives for Future Work

1. **Strictly Abandon Two-Cycle Carrot Rotations (P5.1)**:
   - `P51_T1_TWO_CYCLE_CARROT_ENABLED = False` must remain permanent.
   - Do not attempt "P5.2" or further tweaks to this concept.
2. **Grain Security Must Be Hard-Coded**:
   - The central planner must treat wheat on the core NW+NE farm not as a discretionary cash crop, but as **strategic infrastructure** supporting the dairy and wool engines.
   - Never replace core wheat plantings without guaranteed physical grain reserves in the shed.
3. **Optimize Worker Transit, Not Field Micro-Cycles**:
   - Real score improvements toward $110k–$120k will come from route optimization, clustered pastures, and minimizing empty transit trips, not from squeezing high-maintenance crop cycles into the late game.
