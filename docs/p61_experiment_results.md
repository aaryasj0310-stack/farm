# Kaggriculture P6.1 — Pre-Midnight Storage Hygiene Experiment Results

- **Experiment Name**: P6.1 Pre-Midnight Storage Hygiene
- **Baseline Commit**: `536f1e7071eaa9cdb0f1f3bdb733dce7f75ee77e` (Production Baseline)
- **Active Branch**: `experiment/sw-p13-planting-gate`
- **Evaluation Panel**: 10 fresh untouched evaluation seeds (`96,411`–`96,420`) $\times$ 5 benchmark opponents $\times$ 2 seats = **100 matched pairs (200 live games)**
- **Protected Seeds Status**: Seeds `98,001`–`98,050` remain 100% untouched.
- **P5.1 Policy Confirmation**: `P51_T1_TWO_CYCLE_CARROT_ENABLED = False` permanently locked.
- **Official Verdict**: **NO-GO**

---

## 1. Executive Summary & Core Verdict

The P6.1 experiment tested whether pre-midnight storage hygiene (Hours 20, 21, 22) targeting $\ge 25$ units of shed headroom through prioritized liquidation of inventory *already in the shed* (Tier 1 safe fertilizer, Tier 2 high-value goods, Tier 3 surplus wheat above feed floor) could reduce midnight shed discards by $\ge 70\%$ and unlock $\ge +\$2,000$ in cash.

The formal tournament yielded a **statistically significant but economically insufficient** outcome:

| Metric | Control (Baseline) | Treatment (P6.1) | Delta / Change | 95% Confidence Interval |
| :--- | :---: | :---: | :---: | :---: |
| **Mean Final Cash** | \$99,890.78 | \$101,330.64 | **+\$1,439.86** | [+\$297.91, +\$2,581.81] |
| **Median Final Cash** | \$99,659.00 | \$100,564.00 | **+\$642.50** | — |
| **Win Rate** | 100.0% | 100.0% | 0.0% | [100%, 100%] |
| **Total Discard Units** | 42.08 u/game | 40.90 u/game | **-1.18 u/game (-2.8%)** | [-2.91, +0.55] |
| **Discard Realized Value** | \$5,900.91 | \$5,488.48 | **-\$412.43** | — |
| **Feed Starvations / Escapes**| 0 / 0 | 0 / 0 | **0 / 0 (Zero)** | Clean |
| **P0 Emergency Rejections** | 0 | 0 | **0 (Zero)** | Clean |
| **Slot Cap Rejections** | 100.61 / game | 101.67 / game | +1.06 / game | — |

### Decision Rule Evaluation
- **GO Threshold**: Mean cash delta $\ge +\$2,000$, discard reduction $\ge 70\%$, 0 feed failures, CI strictly positive. -> **FAILED** (Cash delta +$1,439.86 < +$2,000; Discard reduction 2.8% $\ll$ 70%).
- **ITERATE Threshold**: Mean cash delta $> 0$, discard reduction $\ge 50\%$, 0 feed failures. -> **FAILED** (Discard reduction 2.8% $\ll$ 50%).
- **Official Verdict**: **NO-GO**.

---

## 2. Tournament Performance Breakdown by Opponent

The matched tournament ran across all 5 benchmark archetypes:

| Opponent Archetype | Control Cash | Treatment Cash | Cash Delta | Control Discards | Treatment Discards | Discard Delta |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| `pass` (20 games) | \$108,542.45 | \$110,676.10 | **+\$2,133.65** | 37.10 u | 33.20 u | -3.90 u (-10.5%) |
| `pure_wheat_rush` (20 games) | \$96,380.15 | \$99,235.65 | **+\$2,855.50** | 47.95 u | 42.60 u | -5.35 u (-11.2%) |
| `cow_milk_engine` (20 games) | \$102,410.85 | \$103,428.75 | **+\$1,017.90** | 42.80 u | 44.80 u | +2.00 u (+4.7%) |
| `melon_sniper` (20 games) | \$100,684.30 | \$102,689.70 | **+\$2,005.40** | 35.85 u | 37.30 u | +1.45 u (+4.0%) |
| `full_production_agent` (20 games) | \$91,436.15 | \$90,623.00 | **-\$813.15** | 46.70 u | 46.60 u | -0.10 u (-0.2%) |
| **All Scenarios (100 matched pairs)** | **\$99,890.78** | **\$101,330.64** | **+\$1,439.86** | **42.08 u** | **40.90 u** | **-1.18 u (-2.8%)** |

---

## 3. Discard Volume & Product Decomposition

Physical discards decreased marginally from 42.08 to 40.90 units per game:

| Product | Control Discards (u/game) | Treatment Discards (u/game) | Unit Delta | % Change |
| :--- | :---: | :---: | :---: | :---: |
| **WHEAT** | 16.28 | 17.10 | +0.82 | +5.0% |
| **STRAWBERRY** | 8.71 | 9.05 | +0.34 | +3.9% |
| **MILK** | 4.34 | 3.63 | -0.71 | -16.4% |
| **WOOL** | 4.02 | 3.89 | -0.13 | -3.2% |
| **FERTILIZER** | 3.86 | 3.65 | -0.21 | -5.4% |
| **MELON** | 3.10 | 2.05 | -1.05 | -33.9% |
| **CARROT** | 1.20 | 1.01 | -0.19 | -15.8% |
| **TOMATO** | 0.57 | 0.52 | -0.05 | -8.8% |
| **EGG** | 0.00 | 0.00 | 0.00 | 0.0% |
| **TOTAL** | **42.08** | **40.90** | **-1.18** | **-2.8%** |

---

## 4. Key Takeaways

1. **Hypothesis Refuted**: Proactive late-evening shed selling does NOT solve shed overflow discards. It achieved only a 2.8% discard reduction instead of the projected $\ge 70\%$.
2. **Root Cause Discovered**: At Hours 20–22, high-value produce is held in **worker personal inventories** (backpacks), not the shed. The shed itself is largely occupied by protected herd feed wheat (40–48 units). Because workers only deposit inventory at the engine's midnight transition, the shed cannot liquidate goods it does not hold.
3. **Strict Invariant Maintained**: The intervention remained 100% feed safe (0 starvations, 0 escapes) and strictly preserved priority arbitration (0 P0 rejections).
4. **Strategic Direction**: Discards are a worker logistics / mid-day drop-off problem, not a late-night shed liquidation problem.
