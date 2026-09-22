# Kaggriculture P5.1 — Formal STOP/GO Gate Decision

## 1. Formal Recommendation

### **RECOMMENDATION: STOP**

The P5.1 treatment (Two-Cycle Carrot Rotation on Days 21–23) **MUST NOT** be enabled in production and **MUST NOT** proceed to live deployment.

The default configuration in [`agent/config.py`](file:///d:/website%20project/kaggri%20ox/agent/config.py) remains:
```python
P51_T1_TWO_CYCLE_CARROT_ENABLED: bool = False
```
preserving 100% bit-for-bit behavioral equivalence with authoritative baseline `536f1e7071eaa9cdb0f1f3bdb733dce7f75ee77e`.

Furthermore, because the STOP gate has been triggered, the formal held-out tournament on seeds `98,001–98,050` **will not be executed**, strictly conserving the unexposed evaluation panel for future genuine improvements.

---

## 2. Gate Evaluation Matrix

| Decision Criteria | Standard Required | Empirical Live Result (100 Pairs) | Verdict |
| :--- | :---: | :---: | :---: |
| **1. Net Paired Money Delta** | $\overline{\Delta \text{Money}} > \$0.00$ | **−$1,020.68 / game** | **FAIL** |
| **2. Statistical Significance** | 95% CI Lower Bound > \$0 | **95% CI: [−$1,578.80, −$462.56]** ($p < 0.001$) | **FAIL** |
| **3. Herd Feed Safety** | 0.0% animal starvations | **0 starved animals across 100 games** | **PASS** |
| **4. Mechanical Feasibility** | Two-cycle execution $\ge 80\%$ | **626 completed rotations (96.6% of C2 planted)** | **PASS** |
| **5. Day 23 Viability** | $\ge 1$ Day 23 completion | **211 Day 23 rotations completed (2.11 / game)** | **PASS** |
| **6. Market / Labor Side Effects** | Neutral / manageable | **−$1,675.93 labor & market congestion drag** | **FAIL** |
| **OVERALL GATE VERDICT** | **All criteria PASS** | **3 PASS / 3 FAIL** | **STOP** |

---

## 3. Why the Implementation Stopped Despite Architectural Success

From an engineering and algorithmic perspective, P5.1 was an unqualified technical success:
- The **two-cycle rotation manager** accurately tracked all 1,659 tile opportunities across 100 games without a single unhandled exception or crash.
- The **sequential day-by-day feed ledger** correctly guaranteed animal feed security, producing **0 starved animals** across 200 simulation games.
- The **Hour 0 priority pre-ordering** and **MacroPlan coordinate reservation** completely eliminated tile hijacking and market-order drops, resulting in **626 fully executed rotations** and **96.60%** completion of planted Cycle 2 crops.
- The smoke test proved Day 23 plantings can reach maturity by Day 29.

However, the game's holistic equilibrium demonstrated that **the offline economic hypothesis was invalid**:
1. **Labor is the Binding Constraint**:
   - A single wheat tile requires 3 total actions. Two carrot cycles require 10 actions.
   - The extra ~44 worker actions required on Days 21–28 severely starved the agent's high-margin dairy and livestock operations, causing unmilked cows, unsheared sheep, and delayed harvests of valuable melons and cauliflowers.
2. **Town Shop Demand is Inelastic**:
   - Draining ~38 extra carrots into local town markets depressed sales prices and created inventory bottlenecks.
   - In contrast, wheat is converted on-farm into milk and wool with zero market transaction friction.
3. **Competitive Degradation**:
   - Against top benchmark `full_production_agent`, the delta dropped to **−$2,171.45 / game** (underperforming in 17 out of 20 matches).

---

## 4. Conditions Required to Revisit

Two-cycle fast crop rotations should only be reconsidered under the following architectural conditions:

1. **Explicit Labor-Budgeting in CentralPlanner**:
   - Rather than treating tile substitutions as free labor, CentralPlanner must explicitly calculate worker utilization on Days 21–28. Rotations should only trigger if worker slack exists after all livestock milking/shearing and high-value crop harvesting are 100% scheduled.
2. **Dynamic Town Shop Demand Forecasting**:
   - Rotations must check that reachable town shops will have open carrot demand at un-depreciated prices on Day 24 and Day 27 before committing seeds.
3. **Dedicated Low-Labor Alternates**:
   - If wheat truly is surplus, explore zero-watering or 1-watering alternatives that do not consume 10 worker actions per tile.

---

## 5. Summary & Archival

- All P5.1 state machine, priority injection, and feed ledger modules are cleanly encapsulated and protected behind `P51_T1_TWO_CYCLE_CARROT_ENABLED: bool = False`.
- Production baseline remains pristine and fully functional.
- The experiment concludes with rigorous empirical evidence, saving development time and avoiding tournament degradation.
